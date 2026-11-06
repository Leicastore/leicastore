# -*- coding: utf-8 -*-
"""给每个人一个单独的访问码（不用装 APP、不花钱、单独撤销）

原理
----
数据只用一把"数据钥匙" K 加密（K 就是 DASHBOARD_PASSWORD）。
每个人的访问码不直接解数据，而是"包"住 K：

    每人的码  →  用他的码把 K 加密一份  →  存进页面

页面拿到输入的码，先算一个指纹（SHA-256 前 8 位）找到对应那一份，
再用这个码解开，得到 K，最后用 K 解密看板数据。

好处
----
- 谁走了，把那个人的条目删掉、重新生成 → 他的码立刻作废，别人不受影响
- 码不是共享的，泄露了只影响那一个人
- 页面里存的是"用各自密码加密的 K"，没有码解不出来

用法
----
    python zb_codes.py 列表
    python zb_codes.py 加 张三         # 自动生成随机码并打印
    python zb_codes.py 加 李四 abc12345
    python zb_codes.py 删 张三
    python zb_codes.py 清空

码表本身也是加密存的（数据/缓存/访问码.json，用 K 加密），不会明文进仓库。
"""
from __future__ import annotations

import hashlib
import io
import json
import secrets
import string
import sys
from pathlib import Path

import zb_crypt as C

CODES_REL = "数据/缓存/访问码.json"


def _path() -> Path:
    import zbom_core as core
    return core.BASE / CODES_REL


def load_table() -> dict[str, str]:
    p = _path()
    if not p.exists():
        return {}
    got = C.load_json(p, default={}) or {}
    return {str(k): str(v) for k, v in got.items()}


def save_table(t: dict[str, str]) -> None:
    C.save_json(_path(), t)
    print(f"  已保存 {len(t)} 个访问码 → {CODES_REL}")


def hint_of(code: str) -> str:
    """页面上用来快速定位的指纹（不是密钥，只是索引）"""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()[:10]


def gen_code(n: int = 10) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def build_keys(table: dict[str, str], data_key: str) -> list[dict]:
    """把数据钥匙按每个人的码各加密一份，给页面用"""
    out = []
    for name, code in table.items():
        if not code:
            continue
        out.append({
            "h": hint_of(code),
            "n": name,
            "w": C.encrypt_bytes(data_key.encode("utf-8"), code),
        })
    return out


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("列表", "list"):
        t = load_table()
        if not t:
            print("  还没有单独的访问码（页面用 DASHBOARD_PASSWORD 那个总码）")
            return 0
        print(f"  共 {len(t)} 个：")
        for name, code in sorted(t.items()):
            masked = code[:2] + "*" * (len(code) - 4) + code[-2:] if len(code) > 4 else "****"
            print(f"    {name:<10}  {masked}")
        return 0

    cmd = args[0]
    if cmd in ("加", "add"):
        if len(args) < 2:
            print("  用法: python zb_codes.py 加 张三 [访问码]")
            return 1
        name = args[1]
        code = args[2] if len(args) > 2 else gen_code()
        t = load_table()
        t[name] = code
        save_table(t)
        print()
        print(f"  {name} 的访问码：  {code}")
        print("  把这个发给本人，别发群里。")
        return 0

    if cmd in ("删", "del"):
        if len(args) < 2:
            print("  用法: python zb_codes.py 删 张三")
            return 1
        name = args[1]
        t = load_table()
        if name in t:
            t.pop(name)
            save_table(t)
            print(f"  ✅ 已作废 {name} 的访问码（重新生成后生效）")
        else:
            print(f"  没有 {name}")
        return 0

    if cmd in ("清空", "clear"):
        save_table({})
        return 0

    print("  用法：")
    print("    python zb_codes.py 列表")
    print("    python zb_codes.py 加 张三 [访问码]")
    print("    python zb_codes.py 删 张三")
    return 1


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.exit(main())
