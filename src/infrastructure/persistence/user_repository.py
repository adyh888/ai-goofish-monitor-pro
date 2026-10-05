"""用户与会员仓储实现。

admin 账号（expired_at 为 NULL 且 role='admin'）永不过期；
普通用户 expired_at 为 NULL 表示从未激活。
"""
from __future__ import annotations

from dataclasses import dataclass

from src.infrastructure.persistence.sqlite_bootstrap import bootstrap_sqlite_storage
from src.infrastructure.persistence.sqlite_connection import sqlite_connection
from src.services.security import hash_password, utc_now_iso


@dataclass
class User:
    id: int
    username: str
    password_hash: str
    role: str
    status: str
    expired_at: str | None
    created_at: str
    last_login_at: str | None

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def _row_to_user(row) -> User:
    return User(
        id=row["id"],
        username=row["username"],
        password_hash=row["password_hash"],
        role=row["role"],
        status=row["status"],
        expired_at=row["expired_at"],
        created_at=row["created_at"],
        last_login_at=row["last_login_at"],
    )


def get_user_by_id_sync(user_id: int) -> User | None:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_user(row) if row else None


def get_user_by_username_sync(username: str) -> User | None:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
    return _row_to_user(row) if row else None


class UsernameTakenError(ValueError):
    pass


def create_user_sync(
    *,
    username: str,
    password: str,
    role: str = "user",
    expired_at: str | None = None,
) -> User:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone()
        if exists:
            raise UsernameTakenError(f"用户名 '{username}' 已被注册")
        conn.execute(
            """
            INSERT INTO users (username, password_hash, role, status, expired_at, created_at)
            VALUES (?, ?, ?, 'active', ?, ?)
            """,
            (username, hash_password(password), role, expired_at, utc_now_iso()),
        )
        conn.commit()
    return get_user_by_username_sync(username)


def list_users_sync() -> list[User]:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY id ASC").fetchall()
    return [_row_to_user(row) for row in rows]


def update_user_sync(
    user_id: int,
    *,
    status: str | None = None,
    expired_at: str | None = ...,  # type: ignore[assignment]
    password_hash: str | None = None,
    last_login_at: str | None = None,
) -> User | None:
    """expired_at 传 None 表示清除（未激活），不传该参数表示保持不变。"""
    bootstrap_sqlite_storage()
    fields: dict[str, str | None] = {}
    if status is not None:
        fields["status"] = status
    if expired_at is not ...:
        fields["expired_at"] = expired_at
    if password_hash is not None:
        fields["password_hash"] = password_hash
    if last_login_at is not None:
        fields["last_login_at"] = last_login_at
    if not fields:
        return get_user_by_id_sync(user_id)

    with sqlite_connection() as conn:
        set_clause = ", ".join(f"{col} = ?" for col in fields)
        conn.execute(
            f"UPDATE users SET {set_clause} WHERE id = ?",
            (*fields.values(), user_id),
        )
        conn.commit()
    return get_user_by_id_sync(user_id)


def ensure_bootstrap_admin_sync() -> None:
    """首次启动时用 WEB_USERNAME/WEB_PASSWORD 创建管理员账号（仅 users 表为空时）。"""
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        row = conn.execute("SELECT COUNT(1) AS total FROM users").fetchone()
        if row is not None and int(row["total"]) > 0:
            return

        from src.infrastructure.config.settings import settings as app_settings

        username = (app_settings.web_username or "admin").strip()
        password = app_settings.web_password or "admin123"
        conn.execute(
            """
            INSERT INTO users (username, password_hash, role, status, expired_at, created_at)
            VALUES (?, ?, 'admin', 'active', NULL, ?)
            """,
            (username, hash_password(password), utc_now_iso()),
        )
        conn.commit()
