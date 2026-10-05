"""
认证安全基座：密码哈希、JWT 签发/校验、会员时间工具。

JWT_SECRET 优先取环境变量（多实例/容器部署时显式配置）；
未配置时生成随机密钥并持久化到 app_metadata，保证重启后已签发令牌不失效。
"""
from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

JWT_ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 24
_SECRET_METADATA_KEY = "security:jwt_secret"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat(timespec="seconds")


def parse_iso_datetime(value: str | None) -> datetime | None:
    """解析 ISO 8601 时间字符串；兼容旧的无时区格式（按 UTC 处理）。"""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).strip())
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def get_jwt_secret() -> str:
    env_secret = (os.getenv("JWT_SECRET") or "").strip()
    if env_secret:
        return env_secret

    from src.infrastructure.persistence.sqlite_connection import sqlite_connection

    with sqlite_connection() as conn:
        row = conn.execute(
            "SELECT value FROM app_metadata WHERE key = ?",
            (_SECRET_METADATA_KEY,),
        ).fetchone()
        if row:
            return str(row["value"])
        secret = secrets.token_urlsafe(48)
        conn.execute(
            "INSERT OR REPLACE INTO app_metadata(key, value) VALUES (?, ?)",
            (_SECRET_METADATA_KEY, secret),
        )
        conn.commit()
        return secret


def create_access_token(user_id: int, username: str, role: str) -> str:
    now = utc_now()
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + timedelta(hours=TOKEN_EXPIRE_HOURS),
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.PyJWTError:
        return None
