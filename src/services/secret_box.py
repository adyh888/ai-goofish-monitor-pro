"""敏感配置加密盒。

对落库的敏感字段（AI Key、代理凭据、通知 Token 等）做 Fernet 对称加密。
密钥优先取环境变量 MASTER_KEY（容器部署时显式配置）；
未配置时由持久化的 JWT 密钥派生，保证重启后可解密。
注意：更换 MASTER_KEY 会使既有密文不可读（按空值处理）。
"""
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


def get_encryption_key() -> bytes:
    master = (os.getenv("MASTER_KEY") or "").strip()
    if not master:
        from src.services.security import get_jwt_secret

        master = get_jwt_secret()
    digest = hashlib.sha256(master.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def _fernet() -> Fernet:
    return Fernet(get_encryption_key())


def encrypt_text(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_text(ciphertext: str) -> str:
    return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def try_decrypt_text(ciphertext: str | None) -> str | None:
    if not ciphertext:
        return None
    try:
        return decrypt_text(ciphertext)
    except (InvalidToken, ValueError):
        return None
