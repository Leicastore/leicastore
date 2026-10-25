# -*- coding: utf-8 -*-
"""
天诺影像 · 生成「单文件静态看板」

用途：把看板渲染成一个自包含的 HTML（CSS/JS/数据全部内联），
可以直接扔到任何静态托管上 —— 比如 GitHub Pages，不需要服务器。

用法：
    python zb_static.py                                  # 商场店 / 今年 -> public/index.html
    python zb_static.py --范围 全部 --时间 上月
    python zb_static.py --开始 2026-09-01 --结束 2026-09-30 --输出 public/index.html
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
from pathlib import Path

import zbom_core as core
import zb_web as W
from zb_erp import ErpError, ZbErp

WEB_DIR = Path(__file__).resolve().parent / "web"


def _product_payload(cfg: dict, rows: list[dict], scope: str, fetched: str) -> dict | None:
    """产品分类（用本地缓存，不额外打 ERP）"""
    cache_path = core.BASE / "数据/缓存/合同产品明细.json"
    if not cache_path.exists():
        return None
    try:
        import zb_products as zp
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
        items = zp.classify_all(cache, rows, cfg)
        stores_cfg = cfg.get("门店", {}) or {}
        scope_stores = None
        if scope == "商场店":
            scope_stores = {n for n, s in stores_cfg.items()
                            if isinstance(s, dict) and (s.get("类型") or "") == "商场店"}
        ps = zp.summarize(items, scope_stores)
        ps["明细"] = [{k: it[k] for k in ("日期", "门店", "销售员", "htid", "品类", "系列",
                                          "型号", "品牌", "新旧", "数量", "金额", "产品名")}
                      for it in ps["明细"]]
        ps["scope"] = scope
        ps["fetchedAt"] = fetched
        ps["缓存合同数"] = len(cache)
        return ps
    except Exception as exc:                     # 产品分类失败不该拖垮整个看板
        print(f"  （产品分类跳过：{exc}）")
        return None


SNAP = Path(__file__).resolve().parent / "数据/缓存/看板快照.json"
FETCH_CACHE = Path(__file__).resolve().parent / "数据/缓存/历史取数"


def _cached_fetch(erp, e: dict, start: str, end: str, ttl_days: int = 7):
    """给「历史区间」的取数加磁盘缓存。

    为什么：GitHub Actions 每次都是全新进程，内存缓存用不上。
    一次刷新要拉 5 段数据（当期 / 同比 / 环比 / 历史基准 / 型号基准）≈ 2900 条，
    每 10 分钟跑一次就是一天 41 万条 —— 对智邦的云端 ERP 是明显压力
    （之前并发猛拉把它的会话服务打挂过）。

    但同比、环比、两个基准**都是历史数据，已经定死了**，没必要每次重拉。
    所以只缓存「非当期」的区间，7 天失效一次。当期数据永远实时去拿。
    """
    def fetch(a, b):
        # 当期数据不缓存 —— 要的就是最新
        if (a, b) == (start, end):
            return erp.contracts(a, b, page_size=int(e.get("每页条数") or 300), log=None)

        FETCH_CACHE.mkdir(parents=True, exist_ok=True)
        key = f"{a or 'x'}_{b or 'x'}.json".replace(":", "")
        p = FETCH_CACHE / key
        if p.exists():
            age_days = (_dt.datetime.now().timestamp() - p.stat().st_mtime) / 86400
            if age_days < ttl_days:
                try:
                    return json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    pass
        rows = erp.contracts(a, b, page_size=int(e.get("每页条数") or 300), log=None)
        try:
            p.write_text(json.dumps(rows, ensure_ascii=False, default=str), encoding="utf-8")
        except Exception:
            pass
        return rows

    return fetch


def _render(payload: dict, out_file: Path, log=print, presets: dict | None = None) -> Path:
    """把 payload 渲染成自包含的单文件 HTML"""
    html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    css = (WEB_DIR / "style.css").read_text(encoding="utf-8")
    js = (WEB_DIR / "app.js").read_text(encoding="utf-8")

    # JSON 里的 "<" 必须转义，否则数据中出现 </script> 会提前闭合脚本标签
    def dump(o) -> str:
        return json.dumps(o, ensure_ascii=False, default=str).replace("<", "\\u003c")

    boot = "<script>window.__STATIC__=1;window.__DATA__=" + dump(payload) + ";"
    # 多区间：把每个预设的整份数据都嵌进来，前端切换时不用联网。
    # 只有当月那份要实时拉，其余（上月/去年…）都是历史数据，走 7 天缓存，几乎不增加 ERP 压力。
    presets = presets or {}
    if len(presets) > 1:
        boot += "window.__PRESETS__=" + dump(presets) + ";"
    boot += "</script>"

    html = html.replace('<link rel="stylesheet" href="style.css">',
                        "<style>\n" + css + "\n</style>")
    html = html.replace('<script src="app.js"></script>',
                        boot + "\n<script>\n" + js + "\n</script>")
    title = payload.get("title") or "门店业绩看板"
    html = html.replace("<title>商场店销售看板</title>", f"<title>{title}</title>")
    # 链接预览（微信/企业微信/飞书 抓的是 og:* 和 description）
    desc = ("商场店业绩看板 · " + (payload.get("range") or {}).get("start", "")
            + " ~ " + (payload.get("range") or {}).get("end", ""))
    og = (f'<meta name="description" content="{desc}">\n'
          f'<meta property="og:title" content="{title}">\n'
          f'<meta property="og:description" content="{desc}">\n'
          f'<meta property="og:type" content="website">')
    if "<meta name=\"description\"" not in html:
        html = html.replace("</title>", "</title>\n" + og, 1)

    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(html, encoding="utf-8")
    log(f"  已生成 {out_file}  ({out_file.stat().st_size / 1024:.0f} KB)")
    return out_file


def build_offline(out_file: Path, log=print) -> Path:
    """不打 ERP，用仓库里存的上次快照生成页面。

    兜底用：GitHub 的服务器在境外，未必连得上国内 ERP。
    连不上时至少还能发布上次的数据，而不是让整站挂掉。
    """
    if not SNAP.exists():
        raise SystemExit(f"没有快照文件 {SNAP}，离线模式用不了")
    payload = json.loads(SNAP.read_text(encoding="utf-8"))
    log(f"  离线模式：用快照（{payload.get('fetchedAt') or '未知时间'}）")
    return _render(payload, out_file, log=log)


def build(cfg: dict, scope: str, start: str, end: str, out_file: Path, log=print,
          preset: str = "", extra: list[str] | None = None) -> Path:
    e = cfg.get("智邦ERP") or {}
    if not e.get("地址"):
        raise SystemExit("config.json 里「智邦ERP」没配好。")

    log("  登录 ERP ...")
    erp = ZbErp(e["地址"], e["账号"], e["密码"], e.get("串号") or "zb-static")

    erp.login(log=lambda *_: None)
    log(f"  取数 {start or '不限'} ~ {end or '不限'} ...")
    # 历史区间走磁盘缓存，当期数据永远实时拉
    fetch = _cached_fetch(erp, e, start, end)
    rows = fetch(start, end)
    log(f"    拿到 {len(rows)} 条合同")

    log("  取去年同期 / 上一周期 ...")
    compares = W.build_compares(cfg, start, end, scope, fetch)
    if compares.get("同比"):
        log(f"    {compares['同比标签']}：{compares['同比']['total']:,.2f} 元")

    # 用和在线看板**完全相同**的组装逻辑（W.build_payload）。
    # 之前这里自己写了一份，结果静态版一直停在旧逻辑 ——
    # 目标拆解、强制型号、官方价、整数台数全都没有。
    # DataService 只是为了拿到它的缓存和 product_stats（会去取基准区间）。
    svc = W.DataService(cfg)
    svc.fetch = lambda a, b, force=False, log=print: fetch(a, b)   # 复用已经登录的会话
    payload = W.build_payload(cfg, rows, scope, start, end, compares, svc, log=log)
    # 把实际用的是哪个预设（本月/今年…）带进页面，
    # 否则静态页顶部那个按钮会高亮错 —— 数据是本月，却亮着「今年」。
    payload["preset"] = preset or ""

    # 存一份快照，供离线兜底用
    try:
        SNAP.parent.mkdir(parents=True, exist_ok=True)
        SNAP.write_text(json.dumps(payload, ensure_ascii=False, default=str),
                        encoding="utf-8")
        log(f"  快照已存（{SNAP.stat().st_size/1024:.0f} KB）")
    except Exception as exc:
        log(f"  （快照存不下：{exc}）")

    # ---- 其它区间也一起生成（上月/今年…），嵌进同一个页面 ----
    # 这些区间都是历史数据，_cached_fetch 会命中 7 天缓存，不会反复打 ERP。
    presets = {}
    if preset:
        presets[preset] = payload
    for name in (extra or []):
        if not name or name in presets:
            continue
        try:
            s2, e2 = W.resolve_range(name)
            log(f"  另取「{name}」（{s2} ~ {e2}）...")
            rows2 = fetch(s2, e2)
            cmp2 = W.build_compares(cfg, s2, e2, scope, fetch)
            p2 = W.build_payload(cfg, rows2, scope, s2, e2, cmp2, svc, log=log)
            p2["preset"] = name
            presets[name] = p2
            log(f"    「{name}」{len(rows2)} 条合同，已并入页面")
        except Exception as exc:
            log(f"    「{name}」取不到，跳过：{exc}")

    return _render(payload, out_file, log=log, presets=presets)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="生成单文件静态看板（给 GitHub Pages 等静态托管用）")
    ap.add_argument("--范围", default="", help="商场店 / 全部，默认取 config.json")
    ap.add_argument("--时间", default="", help="本月/上月/本季/今年/去年/全部")
    ap.add_argument("--开始", default="")
    ap.add_argument("--结束", default="")
    ap.add_argument("--输出", default="public/index.html", help="输出文件路径")
    ap.add_argument("--离线", action="store_true",
                    help="不打 ERP，用仓库里的快照生成（ERP 连不上时兜底）")
    args = ap.parse_args(argv)

    cfg = core.load_config()
    wc = cfg.get("网页版", {}) or {}

    scope = args.范围 or wc.get("默认看") or "商场店"
    # --时间 可以写「本月,上月」：第一个是打开时显示的，后面几个也一起生成
    wants = [x.strip() for x in (args.时间 or "").split(",") if x.strip()]
    if not wants:
        wants = [wc.get("默认时间") or "本月"]
    if args.开始 or args.结束:
        start, end = args.开始, args.结束
    else:
        start, end = W.resolve_range(wants[0])

    print("=" * 58)
    print("  生成静态看板" + ("（离线模式）" if args.离线 else ""))
    print("=" * 58)
    try:
        if args.离线:
            out = build_offline(Path(args.输出))
        else:
            out = build(cfg, scope, start, end, Path(args.输出),
                        preset=wants[0], extra=wants[1:])
    except ErpError as exc:
        print(f"\n  [X] ERP 出错：{exc}")
        return 2
    print("=" * 58)
    print(f"  完成：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
