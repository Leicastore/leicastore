# -*- coding: utf-8 -*-
"""看板守护：发现服务没在跑就把它拉起来

为什么需要：计划任务只在登录时触发一次。如果 python 进程因为
任何原因退出（内存、异常、系统更新），看板就一直打不开，
而没人会想到去看计划任务。

用法：
    python zb_watchdog.py              # 检查一次，没跑就拉起
    python zb_watchdog.py --loop       # 常驻，每 2 分钟检查一次

计划任务里应该跑 --loop 这个版本。
"""
from __future__ import annotations

import io
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent


def running() -> bool:
    """有没有 zb_web 进程在跑（必须看命令行，不能只看 python.exe ——
    否则会把自己（守护进程）也算进去，导致永远不拉起）"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Select-Object -ExpandProperty CommandLine"],
            capture_output=True, timeout=25,
        ).stdout.decode("utf-8", "replace")
        for line in out.splitlines():
            if "zb_web" in line and "watchdog" not in line:
                return True
        return False
    except Exception:
        return False


def port_ok() -> bool:
    """8848 端口有没有在监听"""
    import socket
    for host in ("100.92.74.31", "127.0.0.1"):
        try:
            s = socket.create_connection((host, 8848), timeout=3)
            s.close()
            return True
        except Exception:
            continue
    return False


def start() -> None:
    exe = sys.executable
    log = BASE / "数据/缓存/看板服务.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "ab") as fh:
        subprocess.Popen([exe, str(BASE / "zb_web.py")],
                         cwd=str(BASE), stdout=fh, stderr=fh,
                         creationflags=0x00000008)   # DETACHED_PROCESS
    print(f"  [{time.strftime('%H:%M:%S')}] 已拉起 zb_web")


def once() -> None:
    ok = port_ok()
    if ok:
        print(f"  [{time.strftime('%H:%M:%S')}] 正常（8848 在监听）")
        return
    print(f"  [{time.strftime('%H:%M:%S')}] 端口不通，检查进程…")
    if not running():
        start()
        for _ in range(20):
            time.sleep(1)
            if port_ok():
                print(f"  [{time.strftime('%H:%M:%S')}] ✅ 启动成功")
                return
        print(f"  [{time.strftime('%H:%M:%S')}] ⚠ 启动了但端口还不通")


def main() -> int:
    if "--loop" in sys.argv:
        print("  守护进程启动，每 2 分钟检查一次")
        while True:
            try:
                once()
            except Exception as exc:
                print(f"  检查出错: {exc}")
            time.sleep(120)
    once()
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.exit(main())
