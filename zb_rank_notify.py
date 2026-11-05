# -*- coding: utf-8 -*-
"""把「本月全员业绩排名」画成一张图，发到另一个企业微信群。

和 zb_notify.py（开单提醒）分开发，因为：
  · 开单提醒要实时（每 25 分钟检查一次）
  · 排名是日报性质，一天发一次就够，发太勤会刷屏

默认每天 20:00 之后第一次运行发一次（同一天只发一次）。
时间可以在 config.json 的「网页版 → 排名推送时间」里改（0~23）。

用法：
  set WECOM_WEBHOOK_RANK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
  python zb_rank_notify.py
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
SNAP = BASE / "数据/缓存/看板快照.json"
STATE = BASE / "数据/缓存/已发排名.json"
OUT_PNG = BASE / "数据/缓存/业绩排名.png"

C_INK = (20, 22, 26)
C_RED = (226, 6, 19)
C_GRAY = (110, 118, 128)
C_LINE = (232, 234, 238)
C_BG = (255, 255, 255)
C_SOFT = (247, 248, 250)
C_UP = (18, 145, 84)
C_DOWN = (200, 30, 45)

FONTS = [
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
]
BOLD = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
]


def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    for p in (BOLD if bold else []) + FONTS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return None


def _load(p: Path, default):
    """读 json —— 仓库里的是密文，用 zb_crypt 自动解开"""
    try:
        import zb_crypt as _zc
        got = _zc.load_json(p, default=None)
        return default if got is None else got
    except Exception:
        return default


def _money_s(v) -> str:
    try:
        v = float(v)
    except Exception:
        return "0"
    if abs(v) >= 1e8:
        return f"{v / 1e8:.2f}亿"
    if abs(v) >= 1e4:
        return f"{v / 1e4:.2f}万"
    return f"{v:,.0f}"


def _post(hook: str, payload: dict) -> bool:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        hook, data=data,
        headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8", "replace")
        ok = '"errcode":0' in body.replace(" ", "")
        if not ok:
            print("  企业微信返回：" + body[:200])
        return ok
    except Exception as exc:
        print(f"  发送失败：{exc}")
        return False


def build_rows(snap: dict) -> tuple[list[dict], dict]:
    """从快照里取出「全员排名」+ 姓名→门店"""
    store_of = {}
    for s in (snap.get("stores") or []):
        for p in (s.get("staff") or []):
            if p.get("name"):
                store_of[p["name"]] = s.get("name") or ""
    rows = []
    for p in (snap.get("everyone") or []):
        if not p.get("count"):
            continue
        rows.append({
            "name": p.get("name") or "",
            "store": store_of.get(p.get("name") or "", ""),
            "amount": float(p.get("amount") or 0),
            "count": int(p.get("count") or 0),
            "yoy": (p.get("同比") or {}).get("百分比"),
        })
    rows.sort(key=lambda x: -x["amount"])
    return rows, {"total": sum(r["amount"] for r in rows), "people": len(rows)}


def render(snap: dict, out: Path):
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:
        print(f"  没有 Pillow：{exc}")
        return None

    rows, tot = build_rows(snap)
    if not rows:
        print("  没有排名数据")
        return None

    f_title = _font(32, True)
    f_sub = _font(19)
    f_no = _font(26, True)
    f_name = _font(25, True)
    f_small = _font(16)
    f_amt = _font(26, True)
    f_total = _font(32, True)
    if not (f_title and f_name and f_amt):
        print("  找不到中文字体")
        return None

    W = 900
    pad = 34
    head_h = 122
    row_h = 82
    foot_h = 84
    rows = rows[:12]
    H = head_h + row_h * len(rows) + foot_h

    img = Image.new("RGB", (W, H), C_BG)
    d = ImageDraw.Draw(img)

    d.rectangle([0, 0, W, 5], fill=C_RED)
    d.text((pad, 28), "全员业绩排名", font=f_title, fill=C_INK)
    span = snap.get("range") or {}
    d.text((pad, 78), f"{span.get('start', '')} ~ {span.get('end', '')}"
                     f"　·　{tot['people']} 人", font=f_sub, fill=C_GRAY)
    right = _money_s(tot["total"]) + "元"
    d.text((W - pad - d.textlength(right, font=f_total), 34), right,
           font=f_total, fill=C_RED)
    d.line([pad, head_h - 12, W - pad, head_h - 12], fill=C_LINE, width=1)

    top = max(r["amount"] for r in rows) or 1
    bar_x0 = pad + 250
    bar_w = 300
    y = head_h
    for i, r in enumerate(rows, 1):
        d.text((pad, y + 12), str(i), font=f_no, fill=C_RED if i == 1 else C_INK)
        d.text((pad + 34, y + 2), r["name"], font=f_name, fill=C_INK)
        d.text((pad + 34, y + 36), r["store"], font=f_small, fill=C_GRAY)

        ratio = r["amount"] / top
        d.rectangle([bar_x0, y + 26, bar_x0 + bar_w, y + 46], fill=C_SOFT)
        d.rectangle([bar_x0, y + 26, bar_x0 + int(bar_w * ratio), y + 46],
                    fill=C_RED if i == 1 else (40, 44, 52))

        amt = f"{r['amount']:,.2f}"
        d.text((W - pad - d.textlength(amt, font=f_amt), y + 8), amt,
               font=f_amt, fill=C_INK)
        tail = f"{r['count']} 单"
        yoy = r["yoy"]
        if yoy is not None:
            tail += f"　{yoy * 100:+.1f}%"
        d.text((W - pad - d.textlength(tail, font=f_small), y + 42), tail,
               font=f_small, fill=(C_UP if (yoy or 0) >= 0 else C_DOWN))
        y += row_h
        d.line([pad, y - 12, W - pad, y - 12], fill=C_LINE, width=1)

    d.rectangle([0, H - foot_h, W, H], fill=C_SOFT)
    note = "本月累计　·　数据来源：智邦 ERP"
    d.text((pad, H - foot_h + 30), note, font=f_small, fill=C_GRAY)
    stamp = f"生成于 {snap.get('fetchedAt') or ''}"
    d.text((W - pad - d.textlength(stamp, font=f_small), H - foot_h + 30),
           stamp, font=f_small, fill=C_GRAY)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    return out


def main() -> int:
    hook = (os.environ.get("WECOM_WEBHOOK_RANK") or "").strip()
    if not hook:
        # 本地定时任务用：地址存在这个文件里，不提交到仓库（仓库是公开的）
        f = BASE / "数据/缓存/排名webhook.txt"
        try:
            hook = f.read_text(encoding="utf-8").strip()
            if hook:
                print("  从本地文件读取 webhook")
        except Exception:
            hook = ""
    if not hook:
        print("  没配 WECOM_WEBHOOK_RANK，跳过排名推送")
        return 0

    snap = _load(SNAP, None)
    if not snap:
        print(f"  没有快照（{SNAP}）")
        return 0

    now = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=8)
    today = now.strftime("%Y-%m-%d")

    # 和开单提醒同一时机：这一轮有新单才发排名。
    # 开单提醒发成功后会写 本次有新单.flag，这里检查它。
    flag = BASE / "数据/缓存/本次有新单.flag"
    if not flag.exists() and (os.environ.get("RANK_FORCE") or "") != "1":
        print("  这一轮没有新开单，排名不发（和开单提醒保持同步）")
        return 0

    print("  生成排名图 …")
    png = render(snap, OUT_PNG)
    if not png or not png.exists():
        # 没有图就发文字，别什么都不发
        rows, tot = build_rows(snap)
        lines = [f"**{i}. {r['name']}**（{r['store']}） {r['amount']:,.2f} 元 · {r['count']} 单"
                 for i, r in enumerate(rows, 1)]
        ok = _post(hook, {"msgtype": "markdown", "markdown": {
            "content": "## 本月全员业绩排名\n" + "\n".join(lines)
                       + f"\n\n合计 {tot['total']:,.2f} 元 / {tot['people']} 人"}})
    else:
        raw = png.read_bytes()
        print(f"  图片 {len(raw) / 1024:.0f} KB，发送中")
        ok = _post(hook, {"msgtype": "image", "image": {
            "base64": base64.b64encode(raw).decode("ascii"),
            "md5": hashlib.md5(raw).hexdigest()}})

    if not ok:
        print("  没发出去，不记状态，下次重试")
        return 1

    try:
        flag.unlink()
    except Exception:
        pass
    print(f"  已推送 {today} 的排名")
    return 0


if __name__ == "__main__":
    sys.exit(main())
