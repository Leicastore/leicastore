# -*- coding: utf-8 -*-
"""有新开单就发一条到企业微信群机器人。

工作原理
--------
企业微信的「群机器人」给一个 webhook 地址，往它 POST 一段 JSON
消息就出现在群里。**不需要账号密码**，只要那个 key 别外泄。

判断「新开单」靠一个状态文件（数据/缓存/已通知.json）：
每次跑的时候拿这次快照里的合同号，跟文件里记的比，
不在里面的就是新单 —— 发出去，然后记下来。
所以机器人重启、断网、漏跑几次都不会重复发。

用法
----
  set WECOM_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx
  python zb_notify.py

不给 WECOM_WEBHOOK 就直接跳过（退出码 0），不会报错。
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
SNAP = BASE / "数据/缓存/看板快照.json"
STATE = BASE / "数据/缓存/已通知.json"
MAX_KEEP = 800          # 状态文件最多记多少个合同号


def _money(v) -> str:
    try:
        return f"{float(v):,.2f}"
    except Exception:
        return str(v)


def _load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def _post(hook: str, payload: dict) -> bool:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        hook, data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            body = r.read().decode("utf-8", "replace")
        ok = '"errcode":0' in body.replace(" ", "")
        if not ok:
            print(f"  企业微信返回：{body[:200]}")
        return ok
    except Exception as exc:
        print(f"  发送失败：{exc}")
        return False


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
    if not recs:
        print("  快照里没有合同明细，跳过")
        return 0

    state = _load_json(STATE, {})
    seen = set(state.get("已通知") or [])

    # 只看今天签的 —— 补历史数据时不要把半年前的单全发一遍
    today = (_dt.datetime.now(_dt.timezone.utc)
             + _dt.timedelta(hours=8)).strftime("%Y-%m-%d")
    fresh, today_all = [], []
    for r in recs:
        no = str(r.get("no") or "")
        d = str(r.get("date") or "")[:10]
        if d != today:
            continue
        today_all.append(r)
        if no and no not in seen:
            fresh.append(r)

    if not fresh:
        print(f"  今天没有新开单（今天共 {len(today_all)} 单，都已通知过）")
        return 0

    total = sum(float(r.get("amount") or 0) for r in today_all)
    lines = []
    for r in fresh:
        who = r.get("person") or "?"
        store = r.get("store") or ""
        amt = _money(r.get("amount"))
        what = (r.get("customer") or "").strip()
        lines.append(f"**{who}**　{store}")
        if what:
            lines.append(f"> {what}")
        lines.append(f"> 金额 {amt} 元")

    content = (
        f"## 开单提醒（{len(fresh)} 单）\n"
        + "\n".join(lines)
        + f"\n\n今日累计：{len(today_all)} 单 / {_money(total)} 元"
    )
    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    print(f"  发现 {len(fresh)} 单新开单，推送中…")
    print("  ---- 消息内容 ----")
    for ln in content.split("\n"):
        print("    " + ln)
    print("  ------------------")

    if not _post(hook, payload):
        # 发失败就不记状态，下次还会重试
        return 1

    for r in fresh:
        no = str(r.get("no") or "")
        if no:
            seen.add(no)
    keep = sorted(seen)[-MAX_KEEP:]
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({
        "已通知": keep,
        "更新时间": (_dt.datetime.now(_dt.timezone.utc)
                    + _dt.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S"),
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  已推送 {len(fresh)} 单新开单")
    return 0


if __name__ == "__main__":
    sys.exit(main())
