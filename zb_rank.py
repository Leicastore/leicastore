# -*- coding: utf-8 -*-
"""
销售排名表

把商场店的销售业绩排成一张表，按人、按店、按月。
数据实时从智邦国际 ERP 取。

用法：
    python zb_rank.py                          # 用 config.json 的日期范围
    python zb_rank.py --开始 2026-09-01 --结束 2026-09-30
    python zb_rank.py --时间 上月
    python zb_rank.py --出图片                  # 额外生成一张可发微信的图片
"""
from __future__ import annotations

import argparse
import datetime as _dt
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import zbom_core as core
from zb_erp import ErpError, ZbErp, clean_person
from zb_web import resolve_range

# ---------------------------------------------------------------- 取数

def fetch(cfg: dict, start: str, end: str) -> list[dict]:
    e = cfg.get("智邦ERP") or {}
    erp = ZbErp(e["地址"], e["账号"], e["密码"], e.get("串号") or "zb-scraper-01")
    erp.login(log=lambda *_: None)
    rows = erp.contracts(start, end, page_size=int(e.get("每页条数") or 300), log=None)

    stores_cfg = cfg.get("门店", {}) or {}
    mall = {n for n, s in stores_cfg.items()
            if isinstance(s, dict) and (s.get("类型") or "") == "商场店"}
    match = core.build_store_matcher(cfg)

    out = []
    for r in rows:
        store = core.cell_text(r.get("htfl"))
        if store not in stores_cfg:
            store = match(store) or store or "其他渠道"
        if mall and store not in mall:
            continue
        dt = core.to_date(r.get("dateQD"))
        out.append({
            "门店": store,
            "销售员": clean_person(r.get("xsry")) or "（未填）",
            "金额": core.to_money(r.get("moneyall")),
            "日期": dt,
            "月份": dt.strftime("%Y-%m") if dt else "",
            "合同号": core.cell_text(r.get("htid")),
            "客户": core.cell_text(r.get("khmc")),
            "已回款": core.to_money(r.get("hkmoney")),
        })
    return out


# ---------------------------------------------------------------- 汇总

def by_person(rows: list[dict]) -> list[dict]:
    g: dict[tuple, dict] = {}
    for r in rows:
        k = (r["门店"], r["销售员"])
        d = g.setdefault(k, {"门店": r["门店"], "销售员": r["销售员"], "合同数": 0,
                             "金额": 0.0, "最大单": 0.0, "首单": None, "末单": None})
        d["合同数"] += 1
        d["金额"] += r["金额"]
        d["最大单"] = max(d["最大单"], r["金额"])
        if r["日期"]:
            if d["首单"] is None or r["日期"] < d["首单"]:
                d["首单"] = r["日期"]
            if d["末单"] is None or r["日期"] > d["末单"]:
                d["末单"] = r["日期"]

    total = sum(d["金额"] for d in g.values()) or 1
    for d in g.values():
        d["平均单值"] = d["金额"] / d["合同数"] if d["合同数"] else 0
        d["占总额比"] = d["金额"] / total
        d["首单"] = d["首单"].isoformat() if d["首单"] else ""
        d["末单"] = d["末单"].isoformat() if d["末单"] else ""

    ranked = sorted(g.values(), key=lambda x: (-x["金额"], x["销售员"]))
    for i, d in enumerate(ranked, 1):
        d["总排名"] = i
    return ranked


def by_month(rows: list[dict]) -> tuple[list[str], dict]:
    """返回 (月份列表, {(门店,销售员): {月份: 金额}})"""
    months = set()
    per: dict[tuple, dict] = defaultdict(lambda: defaultdict(float))
    names: dict[tuple, dict] = {}
    for r in rows:
        m = r.get("月份")
        if not m:
            d = r.get("日期")
            if isinstance(d, str):
                d = core.to_date(d)
            m = d.strftime("%Y-%m") if d else ""
        if not m:
            continue
        k = (r["门店"], r["销售员"])
        per[k][m] += r["金额"]
        names[k] = {"门店": r["门店"], "销售员": r["销售员"]}
        months.add(m)
    return sorted(months), {k: {"info": names[k], "月": dict(v)} for k, v in per.items()}


# ---------------------------------------------------------------- 出表

def write_excel(cfg: dict, rows: list[dict], start: str, end: str,
                prev_rows: list[dict] | None = None, prev_label: str = "") -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    THIN = Side(style="thin", color="B7C2D0")
    BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
    HEAD = PatternFill("solid", fgColor="1F4E78")
    HEADF = Font(name="微软雅黑", size=10, bold=True, color="FFFFFF")
    TITLE = Font(name="微软雅黑", size=15, bold=True, color="1F4E78")
    SUB = Font(name="微软雅黑", size=9, color="808080")
    BODY = Font(name="微软雅黑", size=10)
    BOLD = Font(name="微软雅黑", size=10, bold=True)
    GOLD = PatternFill("solid", fgColor="FFE699")
    SILVER = PatternFill("solid", fgColor="E7E9EC")
    BRONZE = PatternFill("solid", fgColor="F8CBAD")
    STRIPE = PatternFill("solid", fgColor="F7F9FC")
    MONEY = '#,##0.00'
    INT = '#,##0'
    PCT = '0.0%'
    C = Alignment(horizontal="center", vertical="center")
    L = Alignment(horizontal="left", vertical="center")
    R = Alignment(horizontal="right", vertical="center")

    ranked = by_person(rows)
    months, monthly = by_month(rows)
    total = sum(d["金额"] for d in ranked)
    total_cnt = sum(d["合同数"] for d in ranked)
    period = f"{start or '不限'} ~ {end or '不限'}"
    now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    brand = cfg.get("报表标题") or "门店业绩"

    wb = Workbook()

    def title(ws, text, span):
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=span)
        ws.cell(row=1, column=1, value=text).font = TITLE
        ws.row_dimensions[1].height = 28
        ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=span)
        ws.cell(row=2, column=1,
                value=f"统计区间 {period}　|　商场店　|　口径：合同金额（优惠后）· 签订日期"
                      f"　|　共 {total_cnt} 份合同 / {len(ranked)} 人 / {total:,.2f} 元　|　生成 {now}").font = SUB

    def head(ws, row, headers, widths):
        for i, h in enumerate(headers, 1):
            c = ws.cell(row=row, column=i, value=h)
            c.fill, c.font, c.alignment, c.border = HEAD, HEADF, C, BORDER
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.row_dimensions[row].height = 22
        ws.freeze_panes = ws.cell(row=row + 1, column=1)

    def medal(ws, r, rank, ncol):
        f = {1: GOLD, 2: SILVER, 3: BRONZE}.get(rank)
        if f:
            for j in range(1, ncol + 1):
                ws.cell(row=r, column=j).fill = f

    # ---------------- 总排名 ----------------
    ws = wb.active
    ws.title = "总排名"
    title(ws, f"{brand} · 销售排名表", 8)
    head(ws, 4, ["排名", "销售员", "所属门店", "合同数", "业绩金额", "占总额比",
                 "平均单值", "最大单"], [7, 13, 14, 10, 16, 11, 14, 14])
    r = 5
    for d in ranked:
        vals = [d["总排名"], d["销售员"], d["门店"], d["合同数"], d["金额"],
                d["占总额比"], d["平均单值"], d["最大单"]]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=r, column=j, value=v)
            c.font, c.border = BODY, BORDER
            c.alignment = L if j == 2 else (R if j in (5, 7, 8) else C)
        for j in (5, 7, 8):
            ws.cell(row=r, column=j).number_format = MONEY
        ws.cell(row=r, column=4).number_format = INT
        ws.cell(row=r, column=6).number_format = PCT
        medal(ws, r, d["总排名"], 8)
        r += 1
    for j, v in enumerate(["", "合计", f"{len({d['门店'] for d in ranked})} 个门店",
                           total_cnt, total, 1 if total else 0,
                           total / total_cnt if total_cnt else 0, ""], 1):
        c = ws.cell(row=r, column=j, value=v)
        c.font, c.border = BOLD, BORDER
        c.fill = PatternFill("solid", fgColor="DDEBF7")
        c.alignment = L if j == 2 else (R if j in (5, 7, 8) else C)
    for j in (5, 7):
        ws.cell(row=r, column=j).number_format = MONEY
    ws.cell(row=r, column=6).number_format = PCT

    # ---------------- 分店排名 ----------------
    ws2 = wb.create_sheet("分店排名")
    title(ws2, f"{brand} · 各门店排名", 8)
    r = 4
    stores = [s for s in (cfg.get("门店") or {})]
    for store in stores:
        group = [d for d in ranked if d["门店"] == store]
        if not group:
            continue
        group.sort(key=lambda x: -x["金额"])
        sub = sum(d["金额"] for d in group)
        ws2.merge_cells(start_row=r, start_column=1, end_row=r, end_column=8)
        c = ws2.cell(row=r, column=1,
                     value=f"◆ {store}　{len(group)} 人 / {sum(d['合同数'] for d in group)} 份 / "
                           f"{sub:,.2f} 元")
        c.font = Font(name="微软雅黑", size=11, bold=True, color="1F4E78")
        c.alignment = L
        ws2.row_dimensions[r].height = 24
        r += 1
        head(ws2, r, ["店内排名", "销售员", "合同数", "业绩金额", "占门店比",
                      "平均单值", "最大单", "最近成交"], [9, 13, 10, 16, 11, 14, 14, 13])
        r += 1
        for i, d in enumerate(group, 1):
            vals = [i, d["销售员"], d["合同数"], d["金额"],
                    d["金额"] / sub if sub else 0, d["平均单值"], d["最大单"], d["末单"] or "—"]
            for j, v in enumerate(vals, 1):
                cc = ws2.cell(row=r, column=j, value=v)
                cc.font, cc.border = BODY, BORDER
                cc.alignment = L if j == 2 else (R if j in (4, 6, 7) else C)
            for j in (4, 6, 7):
                ws2.cell(row=r, column=j).number_format = MONEY
            ws2.cell(row=r, column=5).number_format = PCT
            medal(ws2, r, i, 8)
            r += 1
        r += 1

    # ---------------- 月度排名 ----------------
    ws3 = wb.create_sheet("月度排名")
    title(ws3, f"{brand} · 月度排名", max(3, len(months) + 3))
    head(ws3, 4, ["月份", "销售员", "门店", "业绩金额", "本月排名"],
         [10, 13, 14, 16, 10])
    r = 5
    for m in months:
        items = [{"门店": v["info"]["门店"], "销售员": v["info"]["销售员"],
                  "金额": v["月"].get(m, 0.0)} for v in monthly.values() if v["月"].get(m)]
        items.sort(key=lambda x: -x["金额"])
        if not items:
            continue
        for i, it in enumerate(items, 1):
            for j, val in enumerate([m, it["销售员"], it["门店"], it["金额"], i], 1):
                c = ws3.cell(row=r, column=j, value=val)
                c.font, c.border = BODY, BORDER
                c.alignment = L if j == 2 else (R if j == 4 else C)
            ws3.cell(row=r, column=4).number_format = MONEY
            if i == 1:
                ws3.cell(row=r, column=5).font = Font(name="微软雅黑", size=10, bold=True, color="BF8F00")
            r += 1
        r += 1

    # ---------------- 排名走势 ----------------
    ws4 = wb.create_sheet("排名走势")
    title(ws4, f"{brand} · 每人每月排名", max(3, len(months) + 2))
    head(ws4, 4, ["销售员", "门店"] + months + ["最好名次"],
         [13, 14] + [11] * len(months) + [11])
    # 先算每人每月的名次
    rank_by_month: dict[str, dict[str, int]] = defaultdict(dict)
    for m in months:
        items = [{"销售员": v["info"]["销售员"], "金额": v["月"].get(m, 0.0)}
                 for v in monthly.values()]
        items = [x for x in items if x["金额"] > 0]
        items.sort(key=lambda x: -x["金额"])
        for i, it in enumerate(items, 1):
            rank_by_month[it["销售员"]][m] = i

    r = 5
    for d in ranked:
        ranks = rank_by_month.get(d["销售员"], {})
        best = min(ranks.values()) if ranks else ""
        vals = [d["销售员"], d["门店"]] + [ranks.get(m, "") for m in months] + [best]
        for j, v in enumerate(vals, 1):
            c = ws4.cell(row=r, column=j, value=v)
            c.font, c.border = BODY, BORDER
            c.alignment = L if j <= 2 else C
            if isinstance(v, int) and v == 1:
                c.fill = GOLD
                c.font = BOLD
        r += 1

    # ---------------- 同比环比 ----------------
    if prev_rows is not None:
        wsc = wb.create_sheet("同比环比")
        title(wsc, f"{brand} · 逐月同比环比", 7)
        wsc.merge_cells(start_row=3, start_column=1, end_row=3, end_column=7)
        note = wsc.cell(row=3, column=1,
                        value=f"环比 = 与上一个月比　·　同比 = 与去年同月比　|　去年同期：{prev_label or '—'}")
        note.font = SUB
        r0row = 4
        head(wsc, r0row, ["月份", "本月业绩", "环比", "上月", "去年同期", "同比", "说明"],
             [10, 16, 10, 16, 16, 10, 20])
        prev_by_month: dict[str, float] = {}
        for r0 in prev_rows:
            d = r0.get("日期")
            if isinstance(d, str):
                d = core.to_date(d)
            if d:
                prev_by_month[d.strftime("%Y-%m")] = prev_by_month.get(d.strftime("%Y-%m"), 0.0) + r0["金额"]

        cur_by_month: dict[str, float] = {}
        for r0 in rows:
            d = r0.get("日期")
            if isinstance(d, str):
                d = core.to_date(d)
            if d:
                cur_by_month[d.strftime("%Y-%m")] = cur_by_month.get(d.strftime("%Y-%m"), 0.0) + r0["金额"]

        rr = 5
        prev_total = None
        cur_sum = prev_sum = 0.0
        for m in sorted(cur_by_month):
            cur = cur_by_month[m]
            lm = f"{int(m[:4]) - 1}-{m[5:]}"
            ly = prev_by_month.get(lm, 0.0)
            cur_sum += cur
            prev_sum += ly
            no_base = ly == 0 and cur > 0
            mom = ((cur - prev_total) / prev_total) if prev_total else None
            yoy = ((cur - ly) / ly) if ly else None
            vals = [m, cur,
                    ("—" if mom is None else f"{mom * 100:+.1f}%"),
                    (prev_total if prev_total is not None else "—"),
                    ("无经营" if no_base else ly),
                    ("新增" if no_base else ("—" if yoy is None else f"{yoy * 100:+.1f}%")),
                    ("去年同月无经营" if no_base else "")]
            for j, v in enumerate(vals, 1):
                c = wsc.cell(row=rr, column=j, value=v)
                c.font, c.border = BODY, BORDER
                c.alignment = C if j in (1, 3, 6) else (R if j in (2, 4, 5) else L)
                if j in (2, 4, 5) and isinstance(v, (int, float)):
                    c.number_format = MONEY
                if j == 6 and isinstance(v, str) and v != "—":
                    c.font = Font(name="微软雅黑", size=10, bold=True,
                                  color="C00000" if (v == "新增" or v.startswith("-")) else "1B7F4B")
                if j == 3 and isinstance(v, str) and v.startswith("-"):
                    c.font = Font(name="微软雅黑", size=10, color="C00000")
                elif j == 3 and isinstance(v, str) and v.startswith("+"):
                    c.font = Font(name="微软雅黑", size=10, color="1B7F4B")
            prev_total = cur
            rr += 1

        tot_mom = ((cur_sum - prev_total) / prev_total) if prev_total else None
        tot_yoy = ((cur_sum - prev_sum) / prev_sum) if prev_sum else None
        for j, v in enumerate(["合计", cur_sum,
                               ("—" if tot_mom is None else f"{tot_mom * 100:+.1f}%"),
                               "—", prev_sum,
                               ("—" if tot_yoy is None else f"{tot_yoy * 100:+.1f}%"), ""], 1):
            c = wsc.cell(row=rr, column=j, value=v)
            c.font, c.fill, c.border = BOLD, PatternFill("solid", fgColor="F2F2F2"), BORDER
            c.alignment = C if j in (1, 3, 6) else (R if j in (2, 4, 5) else L)
        for j in (2, 4, 5):
            wsc.cell(row=rr, column=j).number_format = MONEY

    out_dir = core.cfg_path(cfg, "目录")
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = f"{start}_{end}" if (start or end) else ""
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M")
    target = out_dir / f"销售排名表_{tag + '_' if tag else ''}{stamp}.xlsx"
    wb.save(target)
    return target


# ---------------------------------------------------------------- 图片（方便发微信）

RANK_HTML = """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:"Microsoft YaHei","PingFang SC",sans-serif;background:#f4f6fa;padding:28px;width:1080px}
.card{background:#fff;border-radius:14px;box-shadow:0 2px 14px rgba(20,35,70,.09);overflow:hidden}
.hd{background:linear-gradient(120deg,#1f4e78,#2e75b6);color:#fff;padding:20px 26px}
.hd h1{font-size:23px;font-weight:700}
.hd p{font-size:13px;opacity:.86;margin-top:6px}
.kpis{display:flex;border-bottom:1px solid #e4e8f0}
.kpi{flex:1;padding:15px 22px;border-right:1px solid #e4e8f0}
.kpi:last-child{border-right:none}
.kpi .l{font-size:12px;color:#7a869a}
.kpi .v{font-size:22px;font-weight:700;color:#1b2233;margin-top:3px}
table{width:100%;border-collapse:collapse}
th{background:#f7f9fc;color:#7a869a;font-size:12.5px;font-weight:600;padding:11px 14px;text-align:left;border-bottom:1px solid #e4e8f0}
td{padding:11px 14px;font-size:14px;border-bottom:1px solid #f0f3f8}
tr:last-child td{border-bottom:none}
.rk{display:inline-flex;align-items:center;justify-content:center;width:25px;height:25px;border-radius:50%;font-size:12.5px;font-weight:700;background:#eef2f8;color:#7a869a}
.rk.r1{background:#d4a017;color:#fff}.rk.r2{background:#9aa5b1;color:#fff}.rk.r3{background:#b87333;color:#fff}
tr.top1 td{background:#fffaf0}tr.top2 td{background:#fafbfc}tr.top3 td{background:#fff9f5}
.n{text-align:right;font-variant-numeric:tabular-nums}
.nm{font-weight:700}
.bar{height:7px;border-radius:4px;background:#eef2f8;overflow:hidden;min-width:80px}
.bar i{display:block;height:100%;background:linear-gradient(90deg,#2e75b6,#1f4e78);border-radius:4px}
.ft{padding:13px 26px;font-size:11.5px;color:#98a2b3;background:#fbfcfe}
</style></head><body><div class="card">
<div class="hd"><h1>__TITLE__</h1><p>统计区间 __PERIOD__　|　商场店　|　口径：合同金额（优惠后）· 签订日期</p></div>
<div class="kpis">
<div class="kpi"><div class="l">总业绩</div><div class="v">__TOTAL__ 元</div></div>
<div class="kpi"><div class="l">合同数</div><div class="v">__ORDERS__ 份</div></div>
<div class="kpi"><div class="l">销售人数</div><div class="v">__PEOPLE__ 人</div></div>
<div class="kpi"><div class="l">平均单值</div><div class="v">__AVG__ 元</div></div>
</div>
<table><thead><tr><th style="width:70px">排名</th><th>销售员</th><th>所属门店</th>
<th class="n">合同数</th><th class="n">业绩金额</th><th style="width:150px">占比</th><th class="n">占比</th></tr></thead>
<tbody>__ROWS__</tbody></table>
<div class="ft">__FOOT__</div></div></body></html>"""


def find_browser() -> str | None:
    """找可用的无头浏览器。Windows 用 Edge/Chrome，Linux 用 chromium/google-chrome。"""
    import os
    import shutil
    cands = [
        # Windows
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        # Linux / macOS
        "/usr/bin/chromium", "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome", "/usr/bin/google-chrome-stable",
        "/usr/bin/microsoft-edge", "/snap/bin/chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for c in cands:
        if os.path.exists(c):
            return c
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable",
                 "microsoft-edge", "msedge"):
        found = shutil.which(name)
        if found:
            return found
    return None


def write_image(cfg: dict, rows: list[dict], start: str, end: str, log=print) -> Path | None:
    """生成一张 PNG（先出 HTML，再用系统自带 Edge 无头截图）"""
    import html as _html

    ranked = by_person(rows)
    total = sum(d["金额"] for d in ranked)
    cnt = sum(d["合同数"] for d in ranked)
    brand = cfg.get("报表标题") or "门店业绩"

    rk = []
    for i, d in enumerate(ranked, 1):
        rk.append(
            f'<tr class="top{i if i <= 3 else 0}">'
            f'<td><span class="rk r{i if i <= 3 else 0}">{i}</span></td>'
            f'<td class="nm">{_html.escape(d["销售员"])}</td>'
            f'<td>{_html.escape(d["门店"])}</td>'
            f'<td class="n">{d["合同数"]}</td>'
            f'<td class="n nm">{d["金额"]:,.2f}</td>'
            f'<td><div class="bar"><i style="width:{d["占总额比"] * 100:.1f}%"></i></div></td>'
            f'<td class="n">{d["占总额比"] * 100:.1f}%</td></tr>')

    body = (RANK_HTML
            .replace("__TITLE__", _html.escape(f"{brand} · 销售排名表"))
            .replace("__PERIOD__", f"{start or '不限'} ~ {end or '不限'}")
            .replace("__TOTAL__", f"{total:,.2f}")
            .replace("__ORDERS__", str(cnt))
            .replace("__PEOPLE__", str(len(ranked)))
            .replace("__AVG__", f"{total / cnt:,.2f}" if cnt else "0.00")
            .replace("__ROWS__", "".join(rk))
            .replace("__FOOT__",
                     f"生成时间 {_dt.datetime.now():%Y-%m-%d %H:%M}　|　数据来自智邦国际 ERP"))

    out_dir = core.cfg_path(cfg, "目录")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M")
    html_path = out_dir / f"_排名表_{stamp}.html"
    html_path.write_text(body, encoding="utf-8")

    browser = find_browser()
    if not browser:
        log(f"  没找到 Edge/Chrome/Chromium，跳过图片。HTML 已生成：{html_path}")
        return None

    png = out_dir / f"销售排名表_{stamp}.png"
    height = 260 + 46 * len(ranked) + 60
    try:
        subprocess.run([browser, "--headless=new", "--disable-gpu", "--no-sandbox",
                        "--hide-scrollbars", f"--screenshot={png}",
                        f"--window-size=1080,{height}", "--virtual-time-budget=8000",
                        html_path.as_uri()],
                       capture_output=True, timeout=120)
    except Exception as exc:
        log(f"  图片生成失败：{exc}")
        return None
    finally:
        try:
            html_path.unlink()
        except OSError:
            pass
    if png.exists() and png.stat().st_size > 5000:
        return png
    if png.exists():
        png.unlink()
    return None


# ----------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="销售排名表")
    ap.add_argument("--开始")
    ap.add_argument("--结束")
    ap.add_argument("--时间", help="本月/上月/本季/今年/去年/全部")
    ap.add_argument("--出图片", action="store_true", help="额外生成一张可发微信的图片")
    args = ap.parse_args(argv)

    cfg = core.load_config()
    e = cfg.get("智邦ERP") or {}
    dr = e.get("日期范围") or {}

    if args.开始 or args.结束:
        start, end = args.开始 or "", args.结束 or ""
    elif args.时间:
        start, end = resolve_range(args.时间)
    else:
        start, end = dr.get("开始") or "", dr.get("结束") or ""

    print(f"取数：{start or '不限'} ~ {end or '不限'}（商场店）")
    rows = fetch(cfg, start, end)
    if not rows:
        raise SystemExit("没取到数据，检查日期范围或账号权限。")
    print(f"  {len(rows)} 份合同 / {sum(r['金额'] for r in rows):,.2f} 元\n")

    ranked = by_person(rows)
    total = sum(d["金额"] for d in ranked)
    print(f"{'排名':<4}{'销售员':<10}{'门店':<14}{'合同数':>7}{'业绩金额':>16}{'占比':>9}")
    print("-" * 62)
    for d in ranked:
        print(f"{d['总排名']:<6}{d['销售员']:<12}{d['门店']:<14}"
              f"{d['合同数']:>6}{d['金额']:>16,.2f}{d['占总额比'] * 100:>8.1f}%")
    print("-" * 62)
    print(f"{'合计':<6}{len(ranked)} 人{'':<6}{sum(d['合同数'] for d in ranked):>6}"
          f"{total:>16,.2f}{'':>9}")

    prev_rows = None
    prev_label = ""
    if start and end:
        from zb_web import shift_year
        ps, pe = shift_year(start, -1), shift_year(end, -1)
        try:
            print(f"\n取去年同期：{ps} ~ {pe}")
            prev_rows = fetch(cfg, ps, pe)
            prev_label = f"{ps} ~ {pe}"
            print(f"  {len(prev_rows)} 份合同")
        except Exception as exc:
            print(f"  去年同期取数失败，跳过同比：{exc}")
    target = write_excel(cfg, rows, start, end, prev_rows=prev_rows, prev_label=prev_label)
    print(f"\n排名表已生成：\n  {target}")
    if args.出图片:
        png = write_image(cfg, rows, start, end)
        if png:
            print(f"图片已生成（可直接发微信）：\n  {png}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ErpError as exc:
        print(f"\n[失败] {exc}", file=sys.stderr)
        sys.exit(1)
