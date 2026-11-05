# -*- coding: utf-8 -*-
"""把看板数据加密成「要密码才能看」的格式。

为什么不用 AES
--------------
本机和 GitHub 机器都装不上加密库（PyPI 连不上），浏览器虽然有 WebCrypto 的 AES，
但 Python 这边没有对称加密实现，两边对不上。所以用**两边原生都有**的构件自己拼：

    密钥 = PBKDF2-HMAC-SHA256(密码, 盐, 迭代次数, 64 字节)
           → 前 32 字节做加密，后 32 字节做校验
    密钥流 = HMAC-SHA256(加密钥, 盐 || 计数器) 逐块拼（就是标准的 CTR 模式）
    密文   = 明文 XOR 密钥流
    校验   = HMAC-SHA256(校验钥, 密文)     ← 密码错时这里必然对不上

这套结构就是教科书里的「PRF 计数器模式 + Encrypt-then-MAC」，
虽然不如 AES-GCM 常见，但安全性只依赖 HMAC-SHA256 的伪随机性，
而且 Python / WebCrypto 都能一行命令算出来。

每次生成都用新的随机盐，密钥流不会重复使用。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os

ITERATIONS = 200_000
SALT_LEN = 16


# ---------------------------------------------------------------- 基础构件
def _derive(pwd: str, salt: bytes, iterations: int = ITERATIONS) -> tuple[bytes, bytes]:
    """密码 → (加密钥, 校验钥)"""
    raw = hashlib.pbkdf2_hmac("sha256", pwd.encode("utf-8"), salt, iterations, dklen=64)
    return raw[:32], raw[32:]


def _keystream(enc_key: bytes, salt: bytes, n: int) -> bytes:
    """HMAC-SHA256 计数器模式，生成 n 字节密钥流"""
    out = bytearray()
    counter = 0
    while len(out) < n:
        block = hmac.new(enc_key, salt + counter.to_bytes(8, "big"),
                         hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(out[:n])


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b))


# ---------------------------------------------------------------- 对外接口
def encrypt_bytes(plain: bytes, password: str, iterations: int = ITERATIONS) -> dict:
    salt = os.urandom(SALT_LEN)
    enc_key, mac_key = _derive(password, salt, iterations)
    cipher = _xor(plain, _keystream(enc_key, salt, len(plain)))
    tag = hmac.new(mac_key, cipher, hashlib.sha256).digest()
    return {
        "v": 1,
        "n": iterations,
        "s": base64.b64encode(salt).decode(),
        "c": base64.b64encode(cipher).decode(),
        "m": base64.b64encode(tag).decode(),
    }


def decrypt_bytes(blob: dict, password: str) -> bytes:
    salt = base64.b64decode(blob["s"])
    cipher = base64.b64decode(blob["c"])
    tag = base64.b64decode(blob["m"])
    enc_key, mac_key = _derive(password, salt, int(blob["n"]))
    if not hmac.compare_digest(hmac.new(mac_key, cipher, hashlib.sha256).digest(), tag):
        raise ValueError("密码不对")
    return _xor(cipher, _keystream(enc_key, salt, len(cipher)))


def encrypt_json(obj, password: str) -> dict:
    raw = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
    return encrypt_bytes(raw, password)


def decrypt_json(blob: dict, password: str):
    return json.loads(decrypt_bytes(blob, password).decode("utf-8"))


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    demo = {"hello": "世界", "n": list(range(50)), "s": "x" * 5000}
    blob = encrypt_json(demo, "test123")
    ok = json.loads(decrypt_bytes(blob, "test123").decode()) == demo
    print(f"  往返正确: {ok}")
    print(f"  密文大小: {len(blob['c'])} 字符（原 {len(json.dumps(demo))} 字符）")
    try:
        decrypt_bytes(blob, "wrong")
        print("  错误密码居然解开了 ✗")
    except ValueError:
        print("  错误密码被拒绝 ✅")
