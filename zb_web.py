# -*- coding: utf-8 -*-
"""
天诺影像 · 商场店销售看板（网页版）

本地起一个服务，浏览器打开就能看，数据实时从智邦国际 ERP 拉。

用法：
    python zb_web.py                 # 启动后打开 http://127.0.0.1:8848
    python zb_web.py --端口 9000
    python zb_web.py --打开           # 启动并自动打开浏览器

接口：
    GET  /                    看板页面
    GET  /api/data            聚合数据（start/end/范围）
    GET  /api/status          服务和缓存状态
    POST /api/refresh         清缓存并重新抓
    POST /api/report          导出 Excel 报表，返回文件名
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import hmac
import json
import socket
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import zbom_core as core
from zb_erp import ErpError, ZbErp, clean_person

WEB_DIR = Path(__file__).resolve().parent / "web"

# 这些静态文件不需要访问码：
# 它们只是样式和脚本，不含任何业绩数据。
# 如果也要求验证，未登录时请求 .css/.js 会被回一个 HTML 登录页，
# 浏览器解析不了，页面会闪一下没样式 —— 白白制造困惑。
PUBLIC_FILES = ("/style.css", "/app.js", "/favicon.ico")

# 别人（非本机）第一次打开时会看到这个页面，输入访问码才放行
LOGIN_PAGE = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>天诺影像 · 销售看板</title>
<style>
  *{box-sizing:border-box}
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       background:#F7F8FA;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
       "Hiragino Sans GB","Microsoft YaHei",sans-serif;color:#14161A}
  .box{background:#fff;border-radius:16px;padding:38px 40px;width:min(400px,92vw);
       box-shadow:0 1px 2px rgba(20,22,26,.04),0 8px 28px rgba(20,22,26,.08)}
  h1{margin:0;font-size:19px;font-weight:700;letter-spacing:-.01em}
  .sub{font-size:11px;color:#8C929B;letter-spacing:.1em;text-transform:uppercase;margin-top:4px}
  p{font-size:13px;color:#565C66;margin:22px 0 18px;line-height:1.6}
  label{display:block;font-size:11.5px;color:#8C929B;margin-bottom:7px}
  input{width:100%;padding:12px 14px;font-size:17px;letter-spacing:.22em;text-align:center;
        border:1px solid #ECEEF1;border-radius:10px;font-family:inherit;outline:none}
  input:focus{border-color:#14161A;box-shadow:0 0 0 3px rgba(20,22,26,.06)}
  button{width:100%;margin-top:14px;padding:12px;border:0;border-radius:10px;background:#E20613;
         color:#fff;font-size:14px;font-weight:700;font-family:inherit;cursor:pointer}
  button:hover{background:#C10511}
  .err{color:#E20613;font-size:12.5px;margin-top:12px;font-weight:600}
  .bar{height:3px;background:#E20613;border-radius:2px;width:34px;margin-bottom:20px}
</style></head><body>
<form class="box" method="POST" action="/api/login">
  <div class="bar"></div>
  <h1>天诺影像 · 销售看板</h1>
  <div class="sub">Tiannuo Imaging</div>
  <p>这是公司内部看板，请输入访问码。</p>
  <label>访问码</label>
  <input name="code" autocomplete="off" autofocus inputmode="latin">
  <button type="submit">进入看板</button>
  <div class="err">__ERR__</div>
</form></body></html>
"""


def lan_ips() -> list[str]:
    """本机所有可用于局域网访问的 IPv4"""
    out = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip.startswith("127.") or ip.startswith("169.254."):
                continue
            if ip not in out:
                out.append(ip)
    except OSError:
        pass
    if not out:                       # 兜底：探一下默认出口
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            out.append(s.getsockname()[0])
        except OSError:
            pass
        finally:
            s.close()
    return out


# --------------------------------------------------------------------------
# 时间范围预设
# --------------------------------------------------------------------------

def resolve_range(preset: str, start: str = "", end: str = "") -> tuple[str, str]:
    today = _dt.date.today()
    if start or end:
        return start, end
    p = (preset or "今年").strip()
    if p == "全部":
        return "", ""
    if p == "本月":
        return today.replace(day=1).isoformat(), today.isoformat()
    if p == "上月":
        first_this = today.replace(day=1)
        last_prev = first_this - _dt.timedelta(days=1)
        return last_prev.replace(day=1).isoformat(), last_prev.isoformat()
    if p == "本季":
        q = (today.month - 1) // 3
        first = today.replace(month=q * 3 + 1, day=1)
        return first.isoformat(), today.isoformat()
    if p == "今年":
        return today.replace(month=1, day=1).isoformat(), today.isoformat()
    if p == "去年":
        y = today.year - 1
        return f"{y}-01-01", f"{y}-12-31"
    return "", ""


def shift_year(d: str, delta: int) -> str:
    """把 2026-01-01 变成 2025-01-01（2/29 自动退到 2/28）"""
    try:
        dt = _dt.date.fromisoformat(d)
    except ValueError:
        return d
    try:
        return dt.replace(year=dt.year + delta).isoformat()
    except ValueError:                                  # 2月29日
        return dt.replace(year=dt.year + delta, day=28).isoformat()


def history_range(cfg: dict, start: str, end: str) -> tuple[str, str]:
    """按历史占比分目标时，用来取「历史」的区间。

    **必须排除查询区间本身**，否则目标按他已经卖了多少来定，
    每人的完成率会算成同一个数（门店业绩 ÷ 标准），指标就废了。

    config.json → 网页版 → 目标基准区间：
        前12个月（默认，查询开始日往前 12 个月，不含查询区间）
        去年同期（去年同一天到同一天）
        前3个月
    """
    mode = ((cfg.get("网页版", {}) or {}).get("目标基准区间") or "前12个月").strip()
    try:
        a = _dt.date.fromisoformat(start) if start else _dt.date.today()
        b = _dt.date.fromisoformat(end) if end else a
    except ValueError:
        return "", ""
    if mode == "去年同期":
        return shift_year(start, -1), shift_year(end, -1)
    if mode in ("前3个月", "近3个月"):
        return (a - _dt.timedelta(days=91)).isoformat(), (a - _dt.timedelta(days=1)).isoformat()
    if mode in ("前6个月", "近6个月"):
        return (a - _dt.timedelta(days=182)).isoformat(), (a - _dt.timedelta(days=1)).isoformat()
    # 默认：查询开始日往前 12 个月
    return (a - _dt.timedelta(days=365)).isoformat(), (a - _dt.timedelta(days=1)).isoformat()


def ref_range(cfg: dict, end: str) -> tuple[str, str]:
    """型号/系列结构用的基准区间 —— 不能用查询区间。

    为什么：看「本月」时查询区间只有 16 天，当月没卖的型号占比就是 0，
    目标会直接算成 0 台（实测看不到 M11-P / SL3 / M系列 / SL系列）。
    目标的结构基准必须是稳定的长周期。

    config.json → 网页版 → 型号结构区间：
        近12个月（默认）/ 今年 / 去年 / 全部
    """
    mode = ((cfg.get("网页版", {}) or {}).get("型号结构区间") or "近12个月").strip()
    try:
        e = _dt.date.fromisoformat(end) if end else _dt.date.today()
    except ValueError:
        e = _dt.date.today()

    if mode in ("近12个月", "近一年", "12个月"):
        return (e - _dt.timedelta(days=365)).isoformat(), e.isoformat()
    if mode == "今年":
        return _dt.date(e.year, 1, 1).isoformat(), e.isoformat()
    if mode == "去年":
        return _dt.date(e.year - 1, 1, 1).isoformat(), _dt.date(e.year - 1, 12, 31).isoformat()
    if mode in ("全部", "不限", ""):
        return "", ""
    return (e - _dt.timedelta(days=365)).isoformat(), e.isoformat()


def prev_period(start: str, end: str) -> tuple[str, str]:
    """紧邻当前区间之前、长度相同的一段（算环比用）

    整月区间（如 9/1~9/30）要对齐到上一个整月（8/1~8/31），
    否则会算成 8/2~8/31，白白漏掉 8 月 1 号一天。
    """
    try:
        a = _dt.date.fromisoformat(start)
        b = _dt.date.fromisoformat(end)
    except ValueError:
        return "", ""

    # 整月区间
    if a.day == 1 and (b + _dt.timedelta(days=1)).day == 1:
        months = (b.year - a.year) * 12 + (b.month - a.month) + 1
        prev_end = a - _dt.timedelta(days=1)
        y, m = prev_end.year, prev_end.month - months + 1
        while m <= 0:
            m += 12
            y -= 1
        return _dt.date(y, m, 1).isoformat(), prev_end.isoformat()

    span = (b - a).days + 1
    return (a - _dt.timedelta(days=span)).isoformat(), (a - _dt.timedelta(days=1)).isoformat()


def _snap(cfg: dict, rows: list[dict], keep_set: set | None) -> dict:
    """把一批 ERP 合同行压成可比对的快照：总额 / 按门店 / 按人 / 按月"""
    stores_cfg = cfg.get("门店", {}) or {}
    match = core.build_store_matcher(cfg)
    total = 0.0
    by_store: dict[str, float] = {}
    by_person: dict[tuple, float] = {}
    by_month: dict[str, float] = {}
    count = 0
    for r in rows:
        store = core.cell_text(r.get("htfl"))
        if store not in stores_cfg:
            store = match(store) or store or "其他渠道"
        if keep_set is not None and store not in keep_set:
            continue
        amt = core.to_money(r.get("moneyall"))
        person = clean_person(r.get("xsry")) or "（未填销售）"
        dt = core.to_date(r.get("dateQD"))
        total += amt
        count += 1
        by_store[store] = by_store.get(store, 0.0) + amt
        by_person[(store, person)] = by_person.get((store, person), 0.0) + amt
        if dt:
            m = dt.strftime("%Y-%m")
            by_month[m] = by_month.get(m, 0.0) + amt
    return {"total": total, "count": count, "store": by_store,
            "person": by_person, "month": by_month}


def _person_amounts(cfg: dict, rows: list[dict], scope: str) -> dict:
    """把一批 ERP 合同行按销售员汇总成 {姓名: 金额}（只统计本次范围里的门店）

    用来按历史占比分目标。**必须喂查询区间之外的数据**，
    否则目标按他已经卖了多少来定，每人的完成率会变成同一个数。
    """
    keep = _scope_stores(cfg, scope)
    stores_cfg = cfg.get("门店", {}) or {}
    match = core.build_store_matcher(cfg)
    out: dict[str, float] = {}
    for r in rows:
        store = core.cell_text(r.get("htfl"))
        if store not in stores_cfg:
            store = match(store) or store or "其他渠道"
        if keep is not None and store not in keep:
            continue
        person = clean_person(r.get("xsry")) or "（未填销售）"
        out[person] = out.get(person, 0.0) + core.to_money(r.get("moneyall"))
    return out


def _delta(cur: float, base: float) -> dict:
    """算增减：金额差 + 百分比（基期为 0 时 pct 为 None，别除零）"""
    diff = cur - base
    if base:
        pct = diff / base
    else:
        pct = None if cur else 0.0
    return {"本期": round(cur, 2), "基期": round(base, 2),
            "增减": round(diff, 2), "百分比": (round(pct, 4) if pct is not None else None),
            "可比": base > 0}



# --------------------------------------------------------------------------
# 聚合
# --------------------------------------------------------------------------

class StoreInfo:
    def __init__(self, name: str, spec: dict):
        self.name = name
        self.type = (spec or {}).get("类型") or "其他"
        self.fixed_staff = [core.cell_text(x) for x in ((spec or {}).get("人员") or [])]


def aggregate(cfg: dict, rows: list[dict], scope: str = "商场店",
              compares: dict | None = None, span_months: float = 0.0,
              hist: dict | None = None) -> dict:
    """把 ERP 合同行聚合成看板要的 JSON

    compares: {"同比": 快照, "环比": 快照, "同比标签": "...", "环比标签": "..."}
    hist: 各销售员的历史业绩 {姓名: 金额}，按历史占比分目标用（必须排除查询区间）
    """
    compares = compares or {}
    yoy = compares.get("同比") or {}
    mom = compares.get("环比") or {}
    stores_cfg = cfg.get("门店", {}) or {}
    infos = {name: StoreInfo(name, spec if isinstance(spec, dict) else {}) for name, spec in stores_cfg.items()}

    unmatched_name = "其他渠道"
    buckets: dict[str, dict] = {}
    monthly: dict[str, dict[str, float]] = {}
    monthly_person: dict[str, dict[str, float]] = {}
    records: list[dict] = []

    def bucket(store: str) -> dict:
        if store not in buckets:
            info = infos.get(store)
            buckets[store] = {
                "name": store,
                "type": info.type if info else "其他",
                "staff": {},
                "amount": 0.0,
                "count": 0,
            }
        return buckets[store]

    for r in rows:
        store = core.cell_text(r.get("htfl")) or unmatched_name
        if store not in infos:
            store = unmatched_name
        person = clean_person(r.get("xsry")) or "（未填销售）"
        amount = core.to_money(r.get("moneyall"))
        dt = core.to_date(r.get("dateQD"))

        b = bucket(store)
        s = b["staff"].setdefault(person, {"name": person, "amount": 0.0, "count": 0, "max": 0.0,
                                           "first": None, "last": None})
        s["amount"] += amount
        s["count"] += 1
        s["max"] = max(s["max"], amount)
        if dt:
            if s["first"] is None or dt < s["first"]:
                s["first"] = dt
            if s["last"] is None or dt > s["last"]:
                s["last"] = dt
        b["amount"] += amount
        b["count"] += 1

        if dt:
            monthly.setdefault(dt.strftime("%Y-%m"), {}).setdefault(store, 0.0)
            monthly[dt.strftime("%Y-%m")][store] += amount
            # 逐人逐月（月度走势按人拆解用）
            mp = monthly_person.setdefault(dt.strftime("%Y-%m"), {})
            mp[person] = mp.get(person, 0.0) + amount

        records.append({
            "store": store,
            "person": person,
            "amount": round(amount, 2),
            "date": dt.isoformat() if dt else "",
            "no": core.cell_text(r.get("htid")),
            "customer": core.cell_text(r.get("khmc")),
            "title": core.cell_text(r.get("title")),
            "paid": round(core.to_money(r.get("hkmoney")), 2),
        })

    # 补齐固定名单
    for name, info in infos.items():
        if info.fixed_staff:
            b = bucket(name)
            for person in info.fixed_staff:
                b["staff"].setdefault(person, {"name": person, "amount": 0.0, "count": 0, "max": 0.0,
                                               "first": None, "last": None})

    # 排名与占比
    for store, b in buckets.items():
        ranked = sorted(b["staff"].values(), key=lambda x: (-x["amount"], x["name"]))
        for i, s in enumerate(ranked, 1):
            s["rank"] = i
            s["share"] = (s["amount"] / b["amount"]) if b["amount"] else 0.0
            s["avg"] = (s["amount"] / s["count"]) if s["count"] else 0.0
            s["first"] = s["first"].isoformat() if s["first"] else ""
            s["last"] = s["last"].isoformat() if s["last"] else ""
            s["同比"] = _delta(s["amount"], (yoy.get("person") or {}).get((store, s["name"]), 0.0)) if yoy else None
            s["环比"] = _delta(s["amount"], (mom.get("person") or {}).get((store, s["name"]), 0.0)) if mom else None
        b["staff"] = ranked
        b["people"] = len([x for x in ranked if x["count"] > 0])
        b["avg"] = (b["amount"] / b["count"]) if b["count"] else 0.0
        b["同比"] = _delta(b["amount"], (yoy.get("store") or {}).get(store, 0.0)) if yoy else None
        b["环比"] = _delta(b["amount"], (mom.get("store") or {}).get(store, 0.0)) if mom else None

    # 范围过滤
    all_names = list(infos.keys()) + [unmatched_name]
    if scope == "商场店":
        keep = [n for n in all_names if n != unmatched_name and infos.get(n) and infos[n].type == "商场店"]
    elif scope == "全部":
        keep = all_names
    else:
        keep = [scope] if scope in buckets else all_names

    store_list = [buckets[n] for n in keep if n in buckets]
    keep_set = set(keep)

    # 全员排名（只在保留范围内）
    everyone: list[dict] = []
    for b in store_list:
        for s in b["staff"]:
            if s["count"] == 0 and scope != "全部":
                continue
            everyone.append({**s, "store": b["name"], "storeType": b["type"]})
    everyone.sort(key=lambda x: (-x["amount"], x["name"]))
    total_amount = sum(x["amount"] for x in everyone)
    for i, s in enumerate(everyone, 1):
        s["rank"] = i
        s["totalShare"] = (s["amount"] / total_amount) if total_amount else 0.0

    # 月度趋势：总额 + 按门店 + 按人（按人拆解给看板的堆叠图用）
    months = sorted(monthly.keys())
    yoy_month = yoy.get("month") or {}
    # 人的排序：按区间总业绩降序，保证每个人在每根柱子里的位置固定、颜色稳定
    person_totals: dict[str, float] = {}
    for mp in monthly_person.values():
        for p, v in mp.items():
            person_totals[p] = person_totals.get(p, 0.0) + v
    person_order = [p for p, _ in sorted(person_totals.items(), key=lambda kv: (-kv[1], kv[0]))]
    # 范围内门店的人（循环外算一次，别在循环里重复算）
    keep_people = {s["name"] for name in keep for s in buckets.get(name, {}).get("staff", [])}

    trend = []
    prev_total = None
    for m in months:
        item = {"month": m, "total": 0.0, "byStore": {}, "byPerson": {}}
        for name in keep:
            v = monthly[m].get(name, 0.0)
            if v:
                item["byStore"][name] = round(v, 2)
                item["total"] += v
        for p in person_order:
            v = monthly_person.get(m, {}).get(p, 0.0)
            if v and (not keep_people or p in keep_people):
                item["byPerson"][p] = round(v, 2)
        item["total"] = round(item["total"], 2)
        # 去年同期（同一个月，年份 -1）
        lm = shift_year(m + "-01", -1)[:7] if len(m) == 7 else ""
        ly = round(yoy_month.get(lm, 0.0), 2)
        item["lastYear"] = ly
        item["lastYearMonth"] = lm
        item["同比"] = _delta(item["total"], ly)
        # 环比（上一个月）
        item["环比"] = _delta(item["total"], prev_total) if prev_total is not None else None
        prev_total = item["total"]
        trend.append(item)

    filtered_records = [r for r in records if r["store"] in keep_set]

    total_count = sum(b["count"] for b in store_list)
    grand = round(sum(b["amount"] for b in store_list), 2)
    return {
        "scope": scope,
        "totals": {
            "amount": grand,
            "count": total_count,
            "people": len([x for x in everyone if x["count"] > 0]),
            "avg": round(grand / total_count, 2) if total_count else 0.0,
            "stores": len([b for b in store_list if b["count"] > 0]),
            "同比": _delta(grand, yoy.get("total", 0.0)) if yoy else None,
            "环比": _delta(grand, mom.get("total", 0.0)) if mom else None,
            "同比合同数": _delta(total_count, yoy.get("count", 0)) if yoy else None,
        },
        "compare": {
            "同比标签": compares.get("同比标签") or "",
            "环比标签": compares.get("环比标签") or "",
            "有同比": bool(yoy),
            "有环比": bool(mom),
        },
        "stores": store_list,
        "everyone": everyone,
        "trend": trend,
        "personOrder": [p for p in person_order if p in keep_people],
        "records": filtered_records,
        "storeTypes": {n: (infos[n].type if n in infos else "其他") for n in all_names},
        "任务": add_task(cfg, store_list, span_months, hist) if span_months else None,
    }


def build_compares(cfg: dict, start: str, end: str, scope: str, fetch) -> dict:
    """取去年同期 / 上一周期的数据做成可比快照。fetch(start, end) 由调用方提供。"""
    compares: dict = {}
    keep = _scope_stores(cfg, scope)
    if not (start and end):
        return compares
    try:
        ys, ye = shift_year(start, -1), shift_year(end, -1)
        yrows = fetch(ys, ye)
        if yrows:
            compares["同比"] = _snap(cfg, yrows, keep)
            compares["同比标签"] = f"去年同期 {ys} ~ {ye}"
    except Exception as exc:
        print(f"  [同比] 取数失败，跳过：{exc}")
    try:
        ms, me = prev_period(start, end)
        if ms and me:
            mrows = fetch(ms, me)
            if mrows:
                compares["环比"] = _snap(cfg, mrows, keep)
                compares["环比标签"] = f"上一周期 {ms} ~ {me}"
    except Exception as exc:
        print(f"  [环比] 取数失败，跳过：{exc}")
    return compares


# --------------------------------------------------------------------------
# 数据服务（带缓存）
# --------------------------------------------------------------------------

class DataService:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.lock = threading.Lock()
        self.cache: dict[tuple, tuple[float, list]] = {}
        self.pseries: dict[tuple, dict] = {}      # 产品统计缓存（分类要遍历上千行，别每请求都算）
        self.ref_cache: dict[tuple, tuple] = {}   # 型号结构基准数据（长 TTL）
        self.last_error: str | None = None
        self.last_fetch: float | None = None
        ttl_min = (cfg.get("网页版", {}) or {}).get("缓存分钟", 10)
        self.ttl = max(0, float(ttl_min or 10)) * 60

    def _erp(self) -> ZbErp:
        e = self.cfg.get("智邦ERP") or {}
        return ZbErp(e["地址"], e["账号"], e["密码"], e.get("串号") or "zb-scraper-01")

    def fetch(self, start: str, end: str, force: bool = False, log=print) -> list[dict]:
        key = (start, end)
        now = time.time()
        with self.lock:
            hit = self.cache.get(key)
            if hit and not force and (now - hit[0]) < self.ttl:
                log(f"  命中缓存（{int(now - hit[0])} 秒前抓的）")
                return hit[1]

        log(f"从 ERP 抓取 {start or '不限'} ~ {end or '不限'} ...")
        erp = self._erp()
        erp.login(log=lambda *_: None)
        rows = erp.contracts(start, end, page_size=int((self.cfg.get("智邦ERP") or {}).get("每页条数") or 300),
                             log=None)
        with self.lock:
            self.cache[key] = (time.time(), rows)
            self.last_fetch = time.time()
            self.last_error = None
        log(f"  抓到 {len(rows)} 条合同")
        return rows

    def fetch_ref(self, start: str, end: str, log=print) -> list[dict]:
        """型号结构的基准数据。

        不能跟查询区间走 —— 用户切到「本月」时，当月没卖的型号占比就是 0，
        目标会直接算成 0 台（实测：本月看不到 M11-P / SL3 / M系列 / SL系列）。
        所以基准区间单独抓、缓存久一点（默认 12 小时）。
        """
        key = ("ref", start, end)
        now = time.time()
        ttl = 12 * 3600
        with self.lock:
            hit = self.ref_cache.get(key)
            if hit and (now - hit[0]) < ttl:
                return hit[1]
        log(f"抓型号结构基准数据 {start} ~ {end}（首次较慢，之后缓存 12 小时）...")
        rows = self.fetch(start, end, force=True, log=log)
        with self.lock:
            self.ref_cache[key] = (time.time(), rows)
        return rows

    def product_stats(self, rows: list[dict], scope: str, start: str, end: str) -> dict | None:
        """一次分类，产出：
            系列均价  —— 把「目标金额」换算成「要卖多少台」
            人员型号  —— 每个人实际卖的型号构成（查询区间的实际值）
            相机型号  —— 相机型号的均价与结构占比（**基准区间**，保证稳定）
            人员相机占比 —— 每人相机占其业绩的比例（**基准区间**）
        """
        key = (start, end, scope)
        hit = self.pseries.get(key)
        if hit is not None:
            return hit or None
        cache_path = core.BASE / "数据/缓存/合同产品明细.json"
        if not cache_path.exists():
            self.pseries[key] = {}
            return None
        try:
            import zb_products as zp
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
            items = zp.classify_all(cache, rows, self.cfg)
            stores_cfg = self.cfg.get("门店", {}) or {}
            scope_stores = None
            if scope == "商场店":
                scope_stores = {n for n, s in stores_cfg.items()
                                if isinstance(s, dict) and (s.get("类型") or "") == "商场店"}
            ps = zp.summarize(items, scope_stores)

            # ---- 基准区间：型号结构（占相机）和每人的相机占比都从这里算 ----
            ref_start, ref_end = ref_range(self.cfg, end)
            ref_items = items
            if ref_start and ref_start != start:
                try:
                    ref_rows = self.fetch_ref(ref_start, ref_end)
                    ref_items = zp.classify_all(cache, ref_rows, self.cfg)
                    ref_ps = zp.summarize(ref_items, scope_stores)
                    ref_rel = list(ref_ps.get("明细", []))
                    if scope_stores is not None:
                        ref_rel = [it for it in ref_rel if it.get("门店") in scope_stores]
                except Exception as exc:
                    print(f"  [基准区间] 抓不到，退回用查询区间：{exc}")
                    ref_rel = None
            else:
                ref_rel = None
            if ref_rel is None:
                ref_rel = [it for it in ps.get("明细", [])
                           if scope_stores is None or it.get("门店") in scope_stores]
                ref_start = ref_end = ""

            # 型号拆解口径：相机按系列、镜头按卡口系列、其余按品类。
            # 规则在 config.json 的「产品分类 → 型号拆解分类」里，改口径不用改代码。
            # 口径必须统一，否则目标金额拆不满 100%（相机只占 66%）。
            def cat_of(it: dict) -> str:
                return zp.breakdown_cat(it, self.cfg)

            rel = list(ps.get("明细", []))
            if scope_stores is not None:
                rel = [it for it in rel if it.get("门店") in scope_stores]

            # ---- 系列结构也用基准区间（ref_rel）----
            # 跟型号结构一个道理：看「本月」时只有 16 天数据，
            # 当月没卖的系列占比就是 0，目标会算成 0 台。
            agg: dict[str, dict] = {}
            pm: dict[str, dict] = {}
            for it in ref_rel:
                cat = cat_of(it)
                qty = it.get("数量") or 0
                amt = it.get("金额") or 0
                a = agg.setdefault(cat, {"数量": 0.0, "金额": 0.0})
                a["数量"] += qty
                a["金额"] += amt

            # 人 × 系列（实际销售，用查询区间 rel，这是"卖了多少"的实际情况）
            for it in rel:
                cat = cat_of(it)
                qty = it.get("数量") or 0
                amt = it.get("金额") or 0
                per = it.get("销售员") or "（未填）"
                rec = pm.setdefault(per, {"销售员": per, "门店": it.get("门店") or "",
                                          "系列": {}, "合计台数": 0.0, "合计金额": 0.0})
                s = rec["系列"].setdefault(cat, {"数量": 0.0, "金额": 0.0})
                s["数量"] += qty
                s["金额"] += amt
                rec["合计台数"] += qty
                rec["合计金额"] += amt

            total_amt = sum(v["金额"] for v in agg.values()) or 1
            series = []
            for cat, v in sorted(agg.items(), key=lambda kv: -kv[1]["金额"]):
                series.append({
                    "系列": cat,
                    "数量": round(v["数量"], 2),
                    "金额": round(v["金额"], 2),
                    "占比": v["金额"] / total_amt,
                    "均价": round(v["金额"] / v["数量"], 2) if v["数量"] else 0,
                })

            order = {r["系列"]: i for i, r in enumerate(series)}
            people = sorted(pm.values(), key=lambda x: -x["合计金额"])
            for rec in people:
                rec["合计台数"] = round(rec["合计台数"], 2)
                rec["合计金额"] = round(rec["合计金额"], 2)
                for s in rec["系列"].values():
                    s["数量"] = round(s["数量"], 2)
                    s["金额"] = round(s["金额"], 2)
                rec["列"] = sorted(rec["系列"].keys(), key=lambda k: order.get(k, 999))

            # ---- 相机具体型号（相机系列均价掩盖了型号间的巨大价差：
            #      M系列 8 个型号从 6,958 到 69,318，差 10 倍。
            #      目标拆到「系列」会算出没有意义的台数，必须拆到型号。）
            #      用 ref_rel（基准区间）而不是 rel（查询区间），保证结构稳定。
            #      均价只用**全新**：二手价会把均价拉低（Q3 43 全新 5.5万，
            #      掺进二手就变成 5.0万），拿它算目标台数是错的。----
            mg: dict[str, dict] = {}
            cam_cats: list[str] = []
            for it in ref_rel:
                if (it.get("品类") or "") != "相机":
                    continue
                c = cat_of(it)
                if c not in cam_cats:
                    cam_cats.append(c)
                name = it.get("型号") or "未识别"
                rec = mg.setdefault(name, {"型号": name, "系列": it.get("系列") or "",
                                           "品牌": it.get("品牌") or "",
                                           "台数": 0.0, "金额": 0.0,
                                           "新台数": 0.0, "新金额": 0.0})
                q = it.get("数量") or 0
                amt = it.get("金额") or 0
                rec["台数"] += q
                rec["金额"] += amt
                if (it.get("新旧") or "全新") == "全新":
                    rec["新台数"] += q
                    rec["新金额"] += amt
            cam_total = sum(v["金额"] for v in mg.values()) or 1
            # 人工维护的价目表优先（config.json → 相机价目表）。
            # 成交均价受折扣、样机、二手影响，不能当"卖一台算多少钱"用。
            price_book = {k: v for k, v in ((self.cfg.get("相机价目表") or {}).items())
                          if not k.startswith("_") and v}
            active_book = {k: v for k, v in ((self.cfg.get("相机在产") or {}).items())
                           if not k.startswith("_")}
            # 同一个东西被识别成两个型号名时合并（实测：SOFORT 2 和「拍立得」同价重复两行）
            alias = {k: v for k, v in ((self.cfg.get("相机型号别名") or {}).items())
                     if not k.startswith("_")}
            merged: dict[str, dict] = {}
            for v in mg.values():
                name = alias.get(v["型号"], v["型号"])
                if name in merged:
                    m0 = merged[name]
                    m0["台数"] += v["台数"]
                    m0["金额"] += v["金额"]
                    m0["新台数"] += v["新台数"]
                    m0["新金额"] += v["新金额"]
                else:
                    merged[name] = dict(v, 型号=name)
            mg = merged
            cam_total = sum(v["金额"] for v in mg.values()) or 1

            models = []
            for v in sorted(mg.values(), key=lambda x: -x["金额"]):
                if v["台数"] <= 0:
                    continue
                manual = price_book.get(v["型号"])
                if manual:
                    price, src = float(manual), "价目表"
                elif v["新台数"] > 0:
                    price, src = v["新金额"] / v["新台数"], "全新成交均价"
                else:
                    price, src = v["金额"] / v["台数"], "只有二手"
                models.append({
                    "型号": v["型号"], "系列": v["系列"], "品牌": v["品牌"],
                    "台数": round(v["台数"], 2), "金额": round(v["金额"], 2),
                    "均价": round(price, 2), "价格来源": src,
                    "在产": bool(active_book.get(v["型号"], False)),
                    "占相机": v["金额"] / cam_total,
                })

            # 系列均价也改用「各型号单价 × 销量」加权，跟型号口径一致。
            # 直接用系列自己的成交均价会被二手拉低（跟型号层同一个毛病）。
            price_by_model = {m["型号"]: m["均价"] for m in models}
            qty_by_cat: dict[str, float] = {}
            amt_by_cat: dict[str, float] = {}
            for it in ref_rel:
                q = it.get("数量") or 0
                if not q:
                    continue
                cat = cat_of(it)
                p = price_by_model.get(it.get("型号") or "")
                if not p:
                    p = (it.get("金额") or 0) / q
                qty_by_cat[cat] = qty_by_cat.get(cat, 0.0) + q
                amt_by_cat[cat] = amt_by_cat.get(cat, 0.0) + q * p
            for r in series:
                q = qty_by_cat.get(r["系列"], 0.0)
                if q:
                    r["均价"] = round(amt_by_cat[r["系列"]] / q, 2)

            # ---- 每人的「相机占比」也要用基准区间 ----
            # 用查询区间的话，本月某人不巧没卖相机，占比就是 0，相机目标直接算成 0。
            cam_set = set(cam_cats)
            pshare: dict[str, dict] = {}
            agg_ref: dict[str, float] = {}
            for it in ref_rel:
                cat = cat_of(it)
                amt = it.get("金额") or 0
                agg_ref[cat] = agg_ref.get(cat, 0.0) + amt
                per = it.get("销售员") or "（未填）"
                r = pshare.setdefault(per, {"相机": 0.0, "合计": 0.0})
                r["合计"] += amt
                if cat in cam_set:
                    r["相机"] += amt
            people_cam = {k: round(v["相机"] / v["合计"], 4) for k, v in pshare.items() if v["合计"]}

            # 相机占业绩的比例，必须在**同一个基准区间内**算。
            # 不能拿「基准区间的相机金额 ÷ 查询区间的总业绩」—— 两个窗口混用会算出 >1 的比例。
            ref_total = sum(agg_ref.values()) or 1
            cam_share = cam_total / ref_total

            out = {"系列均价": series, "人员型号": people,
                   "相机型号": models, "相机合计": round(cam_total, 2),
                   "相机大类": cam_cats, "相机占比": round(cam_share, 4),
                   "人员相机占比": people_cam,
                   "基准区间": {"start": ref_start, "end": ref_end},
                   "缓存合同数": len(cache)}
            self.pseries[key] = out
            return out
        except Exception as exc:
            print(f"  [产品统计] 算不出来，跳过：{exc}")
            self.pseries[key] = {}
            return None

    def series_prices(self, rows: list[dict], scope: str, start: str, end: str) -> list[dict] | None:
        st = self.product_stats(rows, scope, start, end)
        return (st or {}).get("系列均价") or None

    def clear(self):
        with self.lock:
            self.cache.clear()
            self.pseries.clear()


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

def add_task(cfg: dict, store_list: list[dict], span: float,
             hist: dict | None = None) -> dict:
    """给每个门店挂上任务和完成率，并把门店目标拆解到人

    hist: 各销售员的**历史**业绩 {姓名: 金额}，用来按历史占比分目标。

    为什么必须传历史：如果用当前区间的业绩分目标，
        目标_i = 标准 × 业绩_i / 门店业绩
        完成率_i = 业绩_i / 目标_i = 门店业绩 / 标准
    每个人算出来完全一样 —— 这个指标就废了。
    """
    mode = ((cfg.get("网页版", {}) or {}).get("目标拆解方式") or "平均").strip()
    hist = hist or {}
    tot = {"月数": span, "最低": 0.0, "标准": 0.0, "有最低": False, "有标准": False,
           "拆解方式": mode, "历史依据": bool(hist)}
    for b in store_list:
        t = core.task_of(cfg, b["name"], span)
        if not t:
            b["任务"] = None
            continue
        b["任务"] = t
        b["完成率最低"] = (b["amount"] / t["最低"]) if t["最低"] else None
        b["完成率标准"] = (b["amount"] / t["标准"]) if t["标准"] else None
        if t["最低"]:
            tot["最低"] += t["最低"]
            tot["有最低"] = True
        if t["标准"]:
            tot["标准"] += t["标准"]
            tot["有标准"] = True

        # ---- 拆解到人 ----
        std = t["标准"]
        active = [x for x in (b.get("staff") or []) if x.get("count", 0) > 0]
        for x in (b.get("staff") or []):
            x["目标"] = None
            x["目标完成率"] = None
            x["目标差额"] = None
            x["历史业绩"] = round(hist.get(x.get("name") or "", 0), 2)
        if std and active:
            hsum = sum(hist.get(x.get("name") or "", 0) for x in active)
            if mode == "按历史占比" and hsum > 0:
                # 按各人历史业绩占比分 —— 卖得多的背得多
                for x in active:
                    x["目标"] = round(std * hist.get(x.get("name") or "", 0) / hsum, 2)
            else:
                if mode == "按历史占比":
                    tot["历史缺失"] = True
                each = round(std / len(active), 2)
                for x in active:
                    x["目标"] = each
            for x in active:
                x["目标完成率"] = (x["amount"] / x["目标"]) if x["目标"] else None
                x["目标差额"] = round(x["目标"] - x["amount"], 2)

    amount = sum(b["amount"] for b in store_list)
    tot["业绩"] = round(amount, 2)
    tot["完成率最低"] = (amount / tot["最低"]) if tot["最低"] else None
    tot["完成率标准"] = (amount / tot["标准"]) if tot["标准"] else None
    return tot


def _scope_stores(cfg: dict, scope: str):
    """这个范围要对哪些门店统计。None = 不限制"""
    infos = cfg.get("门店", {}) or {}
    if scope == "商场店":
        return {n for n, s in infos.items()
                if isinstance(s, dict) and (s.get("类型") or "") == "商场店"}
    if scope in infos:
        return {scope}
    return None


def build_payload(cfg: dict, rows: list[dict], scope: str, start: str, end: str,
                  compares: dict, service, hist: dict | None = None,
                  log=print) -> dict:
    """组装看板要的完整 payload。

    **api_data（在线看板）和 zb_static（GitHub Pages 静态版）必须共用这个函数。**
    之前两边各写一份，结果静态版一直停在旧逻辑 ——
    目标拆解、强制型号、官方价、整数台数全都没有，发布出去是个残缺版。

    service: DataService（要提供 fetch_ref / product_stats）
    """
    # 按历史占比分目标要用的历史业绩。必须排除查询区间，
    # 否则目标按他已经卖了多少来定，每人的完成率会变成同一个数。
    if hist is None:
        hist = {}
        hs, he = history_range(cfg, start, end)
        if hs and he:
            try:
                hist = _person_amounts(cfg, service.fetch_ref(hs, he), scope)
                log(f"  历史基准 {hs} ~ {he}：{len(hist)} 人")
            except Exception as exc:
                log(f"  [历史基准] 抓不到，目标只能平均分：{exc}")

    payload = aggregate(cfg, rows, scope=scope, compares=compares,
                        span_months=core.task_months(start, end), hist=hist)

    # 目标按整月算；另外给「实际过了几个月」显示时间进度。
    # 看 10-01~10-16 时，目标记 1 个月（10月），进度记 0.53 个月。
    elapsed = core.month_span(start, end)
    tgt_months = core.task_months(start, end)
    payload["时间进度"] = {
        "实际月数": elapsed,
        "目标月数": tgt_months,
        "百分比": round(elapsed / tgt_months, 4) if tgt_months else None,
    }
    payload["range"] = {"start": start, "end": end}
    hs2, he2 = history_range(cfg, start, end)
    payload["历史基准区间"] = {"start": hs2, "end": he2} if hs2 else None
    payload["fetchedAt"] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload["rawCount"] = len(rows)
    payload["title"] = cfg.get("报表标题") or "门店业绩看板"

    try:
        st = service.product_stats(rows, scope, start, end) or {}
    except Exception as exc:
        log(f"  （产品统计跳过：{exc}）")
        st = {}
    payload["系列均价"] = st.get("系列均价") or None
    payload["人员型号"] = st.get("人员型号") or None
    payload["相机型号"] = st.get("相机型号") or None
    payload["相机合计"] = st.get("相机合计") or 0
    payload["相机大类"] = st.get("相机大类") or None
    payload["人员相机占比"] = st.get("人员相机占比") or None
    payload["相机占比"] = st.get("相机占比") or 0
    payload["型号基准区间"] = st.get("基准区间") or None
    payload["产品缓存合同数"] = st.get("缓存合同数") or 0

    # 强制型号台数（每人至少卖几台）—— config.json 配置
    raw = {k: v for k, v in ((cfg.get("强制型号台数") or {}).items())
           if not k.startswith("_") and isinstance(v, dict) and v}
    payload["强制型号"] = ({"所有人": raw.pop("所有人", {}) or {}, "按人": raw}
                           if raw else None)
    return payload


class Handler(BaseHTTPRequestHandler):
    server_version = "TiannuoBoard/1.0"
    service: DataService = None          # 由 main 注入
    cfg: dict = None

    # ---- 工具
    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _redirect(self, to: str):
        self.send_response(302)
        self.send_header("Location", to)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    # ---- 访问控制
    # 本机(127.0.0.1)永远免验证，方便自己用；别的机器必须带访问码。
    def _access_code(self) -> str:
        return ((self.cfg or {}).get("网页版", {}) or {}).get("访问码") or ""

    def _real_ip(self) -> str:
        """访客的真实 IP。

        走隧道/反向代理时，直接连进来的永远是 127.0.0.1，
        真实访客在 CF-Connecting-IP / X-Forwarded-For 里。
        但这两个头谁都能伪造，所以**只在请求确实来自本机时才采信**：
        外面的人从局域网连进来，源地址是他的内网 IP，伪造的头会被忽略。
        """
        try:
            direct = self.client_address[0]
        except (IndexError, TypeError):
            return ""
        if direct in ("127.0.0.1", "::1"):
            for h in ("CF-Connecting-IP", "X-Forwarded-For", "X-Real-IP"):
                v = self.headers.get(h)
                if v:
                    ip = v.split(",")[0].strip()
                    if ip:
                        return ip
        return direct

    def _is_local(self) -> bool:
        return self._real_ip() in ("127.0.0.1", "::1", "localhost", "")

    def _token(self) -> str:
        return hashlib.sha256(("tnboard:" + self._access_code()).encode("utf-8")).hexdigest()[:24]

    def _authorized(self) -> bool:
        code = self._access_code()
        if not code:
            return True                      # 没设访问码 = 不拦
        if self._is_local():
            return True                      # 本机放行
        raw = self.headers.get("Cookie") or ""
        for part in raw.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "board_key" and hmac.compare_digest(v.strip(), self._token()):
                return True
        return False

    def _deny(self):
        """没通过验证：页面请求给登录页，接口请求给 401"""
        if (self.path or "").startswith("/api/"):
            return self._json({"error": "需要访问码", "needLogin": True}, 401)
        body = LOGIN_PAGE.replace("__ERR__", "").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _login(self):
        """校验访问码并下发 cookie"""
        try:
            n = int(self.headers.get("Content-Length") or 0)
            form = parse_qs(self.rfile.read(n).decode("utf-8", "replace"))
        except (ValueError, OSError):
            form = {}
        given = (form.get("code") or [""])[0].strip()
        if self._access_code() and hmac.compare_digest(given, self._access_code()):
            # 关键：登录成功后必须 302 跳回看板。
            # 如果直接返回文本 "ok"，浏览器会把它当成新页面显示 —— 用户看到一片空白，
            # 以为看板坏了。（接口测试看 HTTP 200 是正常的，只有真浏览器才暴露这个问题）
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie",
                             f"board_key={self._token()}; Path=/; Max-Age=2592000; SameSite=Lax")
            self.send_header("Content-Length", "0")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        body = LOGIN_PAGE.replace("__ERR__", "访问码不对，再试一次。").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionAbortedError):
            pass

    def _file(self, path: Path):
        # 目录包含校验：只允许读 web/ 里的文件，防止被 .replace("..","") 的漏洞绕过
        try:
            real = path.resolve()
            root = WEB_DIR.resolve()
            if real != root and root not in real.parents:
                self._send(403, "forbidden".encode(), "text/plain; charset=utf-8")
                return
        except (OSError, ValueError):
            self._send(400, b"bad path", "text/plain; charset=utf-8")
            return
        if not path.exists() or not path.is_file():
            self._send(404, b"not found", "text/plain; charset=utf-8")
            return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
        }.get(path.suffix.lower(), "application/octet-stream")
        self._send(200, path.read_bytes(), ctype)

    def log_message(self, fmt, *args):
        if "/api/" in (self.path or ""):
            sys.stderr.write(f"  {self.address_string()} {fmt % args}\n")

    # ---- 路由
    def do_GET(self):
        u = urlparse(self.path)
        # /api/login 是 POST 接口。有人在浏览器里直接粘这个地址时，
        # 会看到一串 JSON 以为坏了 —— 直接送回登录页。
        if u.path in ("/api/login", "/api/logout"):
            return self._redirect("/")
        if u.path not in PUBLIC_FILES and not self._authorized():
            return self._deny()
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path in ("/", "/index.html"):
                return self._file(WEB_DIR / "index.html")
            if u.path == "/api/status":
                return self._json({
                    "ok": True,
                    "cached": [{"start": k[0], "end": k[1], "ageSec": int(time.time() - v[0]),
                                "rows": len(v[1])} for k, v in self.service.cache.items()],
                    "lastFetch": self.service.last_fetch,
                    "lastError": self.service.last_error,
                })
            if u.path == "/api/data":
                return self.api_data(q)
            if u.path == "/api/products":
                return self.api_products(q)
            return self._file(WEB_DIR / u.path.lstrip("/").replace("..", ""))
        except ErpError as exc:
            self.service.last_error = str(exc)
            return self._json({"error": str(exc)}, 502)
        except Exception as exc:
            traceback.print_exc()
            self.service.last_error = str(exc)
            return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    def do_POST(self):
        u = urlparse(self.path)
        if u.path == "/api/login":          # 登录本身当然不能要求先登录
            return self._login()
        if not self._authorized():
            return self._deny()
        try:
            if u.path == "/api/refresh":
                self.service.clear()
                return self._json({"ok": True, "message": "缓存已清空，下次刷新会重新抓取"})
            if u.path == "/api/report":
                return self.api_report()
            return self._json({"error": "unknown endpoint"}, 404)
        except Exception as exc:
            traceback.print_exc()
            return self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)

    # ---- 业务
    def api_data(self, q: dict):
        start = q.get("start", "")
        end = q.get("end", "")
        if not start and not end:
            preset = q.get("时间") or (self.cfg.get("网页版", {}) or {}).get("默认时间") or "今年"
            start, end = resolve_range(preset)
        scope = q.get("范围") or (self.cfg.get("网页版", {}) or {}).get("默认看") or "商场店"
        force = q.get("force") in ("1", "true")

        print(f"[请求] {start or '不限'} ~ {end or '不限'}  范围={scope}{' (强制刷新)' if force else ''}")
        rows = self.service.fetch(start, end, force=force)

        # ---- 同比 / 环比 ----
        compares = build_compares(self.cfg, start, end, scope,
                                  lambda a, b: self.service.fetch(a, b))

        # 组装 payload —— 和静态版（zb_static.py）共用同一个函数，别各写一份
        payload = build_payload(self.cfg, rows, scope, start, end, compares,
                                self.service)
        return self._json(payload)

    def api_products(self, q: dict):
        """产品销售分类"""
        import zb_products as zp

        start = q.get("start", "")
        end = q.get("end", "")
        if not start and not end:
            preset = q.get("时间") or (self.cfg.get("网页版", {}) or {}).get("默认时间") or "今年"
            start, end = resolve_range(preset)
        scope = q.get("范围") or (self.cfg.get("网页版", {}) or {}).get("默认看") or "商场店"

        cache_path = core.BASE / "数据/缓存/合同产品明细.json"
        if not cache_path.exists():
            return self._json({
                "error": "还没有产品明细缓存。\n先跑一次： python zb_products.py --抓取\n"
                         "（单线程限速抓取，510 份合同约 8 分钟；不要并发猛拉，会把 ERP 的会话服务打挂）"
            }, 400)

        print(f"[请求] 产品分类  {start or '不限'} ~ {end or '不限'}  范围={scope}")
        rows = self.service.fetch(start, end)
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        items = zp.classify_all(cache, rows, self.cfg)

        stores_cfg = self.cfg.get("门店", {}) or {}
        scope_stores = None
        if scope == "商场店":
            scope_stores = {n for n, s in stores_cfg.items()
                            if isinstance(s, dict) and (s.get("类型") or "") == "商场店"}

        s = zp.summarize(items, scope_stores)
        # 明细压扁一点，网页够用就行
        s["明细"] = [{k: it[k] for k in ("日期", "门店", "销售员", "htid", "品类", "系列",
                                         "型号", "品牌", "新旧", "数量", "金额", "产品名")}
                     for it in s["明细"]]
        s["scope"] = scope
        s["range"] = {"start": start, "end": end}
        s["fetchedAt"] = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        s["缓存合同数"] = len(cache)
        return self._json(s)

    def api_report(self):
        import subprocess
        print("[请求] 生成 Excel 报表 ...")
        py = sys.executable
        r = subprocess.run([py, str(core.BASE / "zbom_report.py")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        if r.returncode != 0:
            return self._json({"error": (r.stderr or r.stdout or "生成失败")[-800:]}, 500)
        out_dir = core.cfg_path(self.cfg, "目录")
        files = sorted(out_dir.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
        return self._json({
            "ok": True,
            "file": files[0].name if files else "",
            "dir": str(out_dir),
            "log": (r.stdout or "")[-600:],
        })


class BoardServer(ThreadingHTTPServer):
    # Windows 上 SO_REUSEADDR 允许两个进程绑同一端口（和 Linux 行为不同），
    # 会导致重复双击 bat 时静默起两个服务。关掉它，并靠启动前的探测来判断。
    allow_reuse_address = False
    daemon_threads = True


def already_running(port: int, timeout: float = 3.0) -> bool:
    """探测这个端口上是不是已经跑着我们这个看板"""
    import urllib.request as _u
    try:
        with _u.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=timeout) as r:
            if r.status != 200:
                return False
            data = json.loads(r.read().decode("utf-8"))
        return bool(data.get("ok")) and "cached" in data
    except Exception:
        return False


def _browser_candidates(cfg: dict | None) -> list[str]:
    """优先用真正的浏览器打开，不依赖系统默认关联"""
    import os as _os
    want = ((cfg or {}).get("网页版", {}) or {}).get("浏览器")
    out = [want] if want else []
    out += [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        _os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files\Mozilla Firefox\firefox.exe",
        r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        # Linux
        "/usr/bin/chromium", "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/firefox",
        # macOS
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    return [p for p in out if p]


def open_browser(url: str, cfg: dict | None = None, log=print) -> str:
    """用真正的浏览器打开看板，返回用了哪个"""
    import os as _os
    import subprocess
    # 服务器上没有图形界面，别去拉浏览器（拉也拉不起来）
    if _os.name != "nt" and not _os.environ.get("DISPLAY") and not _os.environ.get("WAYLAND_DISPLAY"):
        return "（服务器无图形界面，跳过）"
    for p in _browser_candidates(cfg):
        if _os.path.exists(p):
            try:
                subprocess.Popen([p, url], close_fds=True)
                return _os.path.basename(p)
            except OSError as exc:
                log(f"  （{p} 起不来：{exc}，换下一个）")
    webbrowser.open(url)
    return "系统默认浏览器"


def self_check(cfg: dict) -> int:
    """环境自检：部署到服务器后先跑这个，看缺什么"""
    import os as _os
    import platform
    wc = cfg.get("网页版", {}) or {}
    port = int(wc.get("端口") or 8848)
    bind = wc.get("监听") or "127.0.0.1"
    code = (wc.get("访问码") or "").strip()
    bad = []

    def ok(label, passed, detail=""):
        if not passed:
            bad.append(label)
        print(f"  [{'OK' if passed else 'XX'}] {label}" + (f"  -- {detail}" if detail else ""))

    print("=" * 62)
    print("  天诺影像 · 看板环境自检")
    print("=" * 62)
    ok("Python >= 3.10", sys.version_info >= (3, 10),
       f"{platform.python_version()} / {platform.system()} {platform.machine()}")
    try:
        import openpyxl
        ok("openpyxl 可导入", True, f"v{openpyxl.__version__}")
    except ImportError as exc:
        ok("openpyxl 可导入", False, f"缺依赖 pip install openpyxl ({exc})")
    ok("标准输出编码", True,
       f"stdout={getattr(sys.stdout, 'encoding', '?')} LANG={_os.environ.get('LANG', '-')}")

    for label, path in (("原始数据目录", core.cfg_path(cfg, "原始数据目录")),
                        ("输出目录", core.cfg_path(cfg, "目录")),
                        ("缓存目录", core.BASE / "数据/缓存")):
        try:
            path.mkdir(parents=True, exist_ok=True)
            probe = path / ".write_probe"
            probe.write_text("x", encoding="utf-8")
            probe.unlink()
            ok(f"{label}可写", True, str(path))
        except Exception as exc:
            ok(f"{label}可写", False, str(exc))

    e = cfg.get("智邦ERP") or {}
    ok("ERP 地址已配置", bool(e.get("地址")), str(e.get("地址") or "config.json 里没填"))
    if e.get("地址"):
        try:
            erp = ZbErp(e["地址"], e.get("账号", ""), e.get("密码", ""),
                        e.get("串号") or "zb-scout")
            erp.login(log=lambda *_: None)
            ok("ERP 登录成功", True, f"账号 {e.get('账号')}")
        except Exception as exc:
            ok("ERP 登录成功", False, f"{type(exc).__name__}: {exc}")

    if already_running(port):
        ok(f"端口 {port}", True, "本看板已在运行")
    else:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((bind, port))
            ok(f"端口 {port} 可绑定 ({bind})", True)
        except OSError as exc:
            ok(f"端口 {port} 可绑定 ({bind})", False, str(exc))
        finally:
            s.close()

    try:
        import zb_rank
        b = zb_rank.find_browser()
        ok("无头浏览器", bool(b), str(b) if b else "没装 chromium，PNG 会跳过，不影响看板")
    except Exception as exc:
        ok("无头浏览器", False, str(exc))

    if _os.name != "nt":
        import subprocess as _sp
        try:
            r = _sp.run(["fc-list", ":lang=zh"], capture_output=True, timeout=15)
            has = bool(r.stdout.strip())
            ok("中文字体", has, "有" if has else "缺 apt install -y fonts-noto-cjk")
        except Exception:
            ok("中文字体", False, "装不上 fc-list，先 apt install -y fontconfig")

    print("-" * 62)
    print(f"  监听: {bind}:{port}")
    if bind in ("0.0.0.0", "::"):
        print(f"  对外: http://<服务器IP>:{port}/")
    else:
        print("  注意: 监听是 127.0.0.1，服务器上外部访问不了，改成 0.0.0.0")
    print("  访问码: " + ("已设置" if code else "未设置 —— 公网部署必须设置！"))
    print("=" * 62)
    print("  自检通过" if not bad else f"  有 {len(bad)} 项没通过: {', '.join(bad)}")
    return 0 if not bad else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="天诺影像 · 商场店销售看板")
    ap.add_argument("--端口", type=int, help="监听端口，默认取 config.json")
    ap.add_argument("--监听", help="绑定地址：127.0.0.1=只本机，0.0.0.0=局域网可访问")
    ap.add_argument("--打开", action="store_true", help="启动后自动打开浏览器")
    ap.add_argument("--自检", action="store_true",
                    help="检查运行环境（部署到服务器后先跑这个）")
    ap.add_argument("--只开浏览器", action="store_true",
                    help="不起服务，只把看板在浏览器里打开（服务已经在跑时用这个）")
    args = ap.parse_args(argv)

    cfg = core.load_config()
    wc = cfg.get("网页版", {}) or {}

    if args.自检:
        return self_check(cfg)

    port = args.端口 or int(wc.get("端口") or 8848)
    bind = args.监听 or wc.get("监听") or "127.0.0.1"
    code = (wc.get("访问码") or "").strip()
    url = f"http://127.0.0.1:{port}/"
    lan = [f"http://{ip}:{port}/" for ip in lan_ips()] if bind not in ("127.0.0.1", "localhost") else []

    # 只开浏览器：服务在不在都试一下，最省事的入口
    if args.只开浏览器:
        if not already_running(port):
            print(f"[提示] 看板服务没在运行，{url} 会打不开。")
            print("       先双击「打开看板.bat」把服务起来，再开这个。")
            return 1
        used = open_browser(url, cfg)
        print(f"已用 {used} 打开：{url}")
        return 0

    # 已经跑着就直接开浏览器，别起第二个
    if already_running(port):
        print(f"看板已经在运行了：{url}")
        if args.打开:
            used = open_browser(url, cfg)
            print(f"已用 {used} 打开（这个窗口可以直接关掉）")
        else:
            print("（不用再开一个，这个窗口可以直接关掉）")
        return 0

    Handler.cfg = cfg
    Handler.service = DataService(cfg)

    try:
        srv = BoardServer((bind, port), Handler)
    except OSError as exc:
        print(f"[错误] 端口 {port} 起不来：{exc}")
        print(f"可能是被别的程序占用了。换一个端口再试： python zb_web.py --端口 9000")
        return 1

    print("=" * 60)
    print("  天诺影像 · 商场店销售看板")
    print("=" * 60)
    print(f"  本机打开：{url}")
    if lan:
        print("  局域网访问（发给同事）：")
        for u in lan:
            print(f"      {u}")
        if code:
            print(f"      访问码： {code}")
        else:
            print("      ⚠ 没设访问码，同网段任何人都能看，建议在 config.json 里设「访问码」")
    else:
        print("  局域网访问：未开启（config.json 的「网页版 → 监听」改成 0.0.0.0 才开）")
    print(f"  默认：{(wc.get('默认看') or '商场店')} / {(wc.get('默认时间') or '今年')}")
    print(f"  缓存：{wc.get('缓存分钟', 10)} 分钟")
    print("  停止：按 Ctrl+C")
    print("=" * 60)

    if args.打开:
        def _open():
            used = open_browser(url, cfg)
            print(f"  已用 {used} 打开：{url}")
        threading.Timer(1.0, _open).start()

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
