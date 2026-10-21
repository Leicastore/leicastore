# -*- coding: utf-8 -*-
"""有新开单就画一张「今日开单」图片，发到企业微信群机器人。

为什么要画图
------------
群里一堆文字没人看。一张卡片图更直观：谁开的、哪个店、卖了多少、今天累计。

实现
----
用 Pillow 直接画（不依赖浏览器，GitHub 机器上也能跑）。
中文字体按顺序找：Linux 的文泉驿/思源 → Windows 的微软雅黑。
找不到中文字体就退回发文字消息，不会发不出去。

判断「新开单」靠 数据/缓存/已通知.json 记的合同号，不会重复提醒。
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
STATE = BASE / "数据/缓存/已通知.json"
OUT_PNG = BASE / "数据/缓存/今日开单.png"
MAX_KEEP = 800

C_INK = (20, 22, 26)
C_RED = (226, 6, 19)
C_GRAY = (110, 118, 128)
C_LINE = (232, 234, 238)
C_BG = (255, 255, 255)
C_SOFT = (247, 248, 250)
C_NEW = (255, 246, 247)

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
]
BOLD_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
]


def _money(v) -> str:
    try:
        return f"{float(v):,.2f}"
    except Exception:
        return str(v)


def _money_s(v) -> str:
    try:
        v = float(v)
    except Exception:
        return "0"
    if abs(v) >= 1e8:
        return f"{v / 1e8:.2f} 亿"
    if abs(v) >= 1e4:
        return f"{v / 1e4:.2f} 万"
    return f"{v:,.0f}"


def _load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _font(size: int, bold: bool = False):
    from PIL import ImageFont
    for p in (BOLD_CANDIDATES if bold else []) + FONT_CANDIDATES:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return None


def _wd(date_str: str) -> str:
    try:
        return "周" + "一二三四五六日"[_dt.date.fromisoformat(date_str).weekday()]
    except Exception:
        return ""


def _post(hook: str, payload: dict) -> bool:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        hook, data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read().decode("utf-8", "replace")
        ok = '"errcode":0' in body.replace(" ", "")
        if not ok:
            print(f"  企业微信返回：{body[:220]}")
        return ok
    except Exception as exc:
        print(f"  发送失败：{exc}")
        return False


def render_card(today: str, rows_all: list, rows_new: list, out: Path):
    """画「今日开单」卡片。字体不可用返回 None。"""
    try:
        from PIL import Image, ImageDraw
    except Exception as exc:
        print(f"  没有 Pillow，跳过画图：{exc}")
        return None

    f_title = _font(34, True)
    f_sub = _font(19)
    f_name = _font(23, True)
    f_small = _font(16)
    f_amt = _font(25, True)
    f_total = _font(34, True)
    if not (f_title and f_name and f_amt):
        print("  找不到中文字体，改发文字")
        return None

    rows = rows_all[:12]
    overflow = len(rows_all) - len(rows)
    newset = {str(r.get("no") or "") for r in rows_new}

    W = 880
    pad = 34
    head_h = 126
    row_h = 72
    foot_h = 92
    H = head_h + row_h * max(len(rows), 1) + (30 if overflow > 0 else 0) + foot_h

    img = Image.new("RGB", (W, H), C_BG)
    d = ImageDraw.Draw(img)
    total = sum(float(r.get("amount") or 0) for r in rows_all)

    d.rectangle([0, 0, W, 5], fill=C_RED)
    d.text((pad, 30), "今日开单", font=f_title, fill=C_INK)
    d.text((pad + 152, 40), _wd(today), font=f_sub, fill=C_GRAY)
    right = _money_s(total) + "元"
    d.text((W - pad - d.textlength(right, font=f_total), 26), right, font=f_total, fill=C_RED)

    d.text((pad, 82), f"{today}　·　{len(rows_all)} 单", font=f_small, fill=C_GRAY)
    if rows_new:
        tail = f"新开 {len(rows_new)} 单"
        d.text((W - pad - d.textlength(tail, font=f_small), 84), tail,
               font=f_small, fill=C_RED)

    d.line([pad, head_h - 12, W - pad, head_h - 12], fill=C_LINE, width=1)

    y = head_h
    if not rows:
        d.text((pad, y + 14), "今天还没有成交", font=f_sub, fill=C_GRAY)
    for r in rows:
        is_new = str(r.get("no") or "") in newset
        if is_new:
            d.rectangle([pad - 12, y - 4, W - pad + 12, y + row_h - 18], fill=C_NEW)
        d.text((pad, y + 2), str(r.get("person") or ""), font=f_name, fill=C_INK)
        d.text((pad + 128, y + 6), str(r.get("store") or ""), font=f_small, fill=C_GRAY)
        what = str(r.get("customer") or "").strip()
        if len(what) > 22:
            what = what[:22] + "…"
        d.text((pad + 128, y + 32), what, font=f_small, fill=C_GRAY)
        amt = _money(r.get("amount"))
        d.text((W - pad - d.textlength(amt, font=f_amt), y + 14), amt, font=f_amt, fill=C_INK)
        if is_new:
            d.ellipse([pad - 30, y + 22, pad - 18, y + 34], fill=C_RED)
        y += row_h
        d.line([pad, y - 12, W - pad, y - 12], fill=C_LINE, width=1)

    if overflow > 0:
        d.text((pad, y + 4), f"还有 {overflow} 单未显示", font=f_small, fill=C_GRAY)

    d.rectangle([0, H - foot_h, W, H], fill=C_SOFT)
    d.text((pad, H - foot_h + 30), "今日累计", font=f_small, fill=C_GRAY)
    t2 = f"{len(rows_all)} 单　{_money(total)} 元"
    d.text((W - pad - d.textlength(t2, font=f_amt), H - foot_h + 24), t2,
           font=f_amt, fill=C_INK)

    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG", optimize=True)
    return out


def send_text(hook: str, rows_new: list, rows_all: list) -> bool:
    total = sum(float(r.get("amount") or 0) for r in rows_all)
    lines = []
    for r in rows_new:
        what = (r.get("customer") or "").strip()
        lines.append(f"**{r.get('person')}**　{r.get('store')}")
        if what:
            lines.append(f"> {what}")
        lines.append(f"> 金额 {_money(r.get('amount'))} 元")
    content = ("## 开单提醒（%d 单）\n" % len(rows_new) + "\n".join(lines)
               + f"\n\n今日累计：{len(rows_all)} 单 / {_money(total)} 元")
    return _post(hook, {"msgtype": "markdown", "markdown": {"content": content}})


def main() -> int:
    hook = (os.environ.get("WECOM_WEBHOOK") or "").strip()
    if not hook:
        print("  没配 WECOM_WEBHOOK，跳过开单提醒")
        return 0

    snap = _load_json(SNAP, None)
    if not snap:
        print(f"  没有快照（{SNAP}），跳过")
        return 0

    recs = snap.get("records") or []
    state = _load_json(STATE, {})
    seen = set(state.get("已通知") or [])

    today = (_dt.datetime.now(_dt.timezone.utc)
             + _dt.timedelta(hours=8)).strftime("%Y-%m-%d")
    todays = [r for r in recs if str(r.get("date") or "")[:10] == today]
    fresh = [r for r in todays
             if str(r.get("no") or "") and str(r.get("no")) not in seen]

    if not fresh:
        print(f"  今天没有新开单（今天共 {len(todays)} 单，都已通知过）")
        return 0

    print(f"  发现 {len(fresh)} 单新开单，准备推送")

    ok = False
    try:
        png = render_card(today, todays, fresh, OUT_PNG)
    except Exception as exc:
        print(f"  画图失败：{exc}")
        png = None
    if png and png.exists():
        raw = png.read_bytes()
        b64 = base64.b64encode(raw).decode("ascii")
        print(f"  图片 {len(raw) / 1024:.0f} KB，开始发送")
        ok = _post(hook, {"msgtype": "image",
                          "image": {"base64": b64, "md5": hashlib.md5(raw).hexdigest()}})
        if not ok:
            print("  图片发送失败，改发文字")
    if not ok:
        ok = send_text(hook, fresh, todays)

    if not ok:
        print("  没发出去，不记状态，下次重试")
        return 1

    for r in fresh:
        no = str(r.get("no") or "")
        if no:
            seen.add(no)
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({
        "已通知": sorted(seen)[-MAX_KEEP:],
        "更新时间": (_dt.datetime.now(_dt.timezone.utc)
                    + _dt.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S"),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  已推送 {len(fresh)} 单")
    return 0


if __name__ == "__main__":
    sys.exit(main())
