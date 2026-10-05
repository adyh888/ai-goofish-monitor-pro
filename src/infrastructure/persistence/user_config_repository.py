"""用户级轮换/代理配置仓储（user_proxy_configs，整体 JSON 加密落库）。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

from src.infrastructure.persistence.sqlite_bootstrap import bootstrap_sqlite_storage
from src.infrastructure.persistence.sqlite_connection import sqlite_connection
from src.services.secret_box import encrypt_text, try_decrypt_text

DEFAULT_ROTATION_CONFIG: dict = {
    "ACCOUNT_ROTATION_ENABLED": False,
    "ACCOUNT_ROTATION_MODE": "per_task",
    "ACCOUNT_ROTATION_RETRY_LIMIT": 2,
    "ACCOUNT_BLACKLIST_TTL": 300,
    "PROXY_ROTATION_ENABLED": False,
    "PROXY_ROTATION_MODE": "per_task",
    "PROXY_POOL": "",
    "PROXY_ROTATION_RETRY_LIMIT": 2,
    "PROXY_BLACKLIST_TTL": 300,
}


@dataclass
class UserRotationConfig:
    user_id: int
    values: dict = field(default_factory=dict)


def load_rotation_config_sync(user_id: int) -> dict:
    """返回该用户的轮换配置（缺省项用默认值补齐）；无记录时返回全默认。"""
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        row = conn.execute(
            "SELECT config_json FROM user_proxy_configs WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    values = dict(DEFAULT_ROTATION_CONFIG)
    if row is not None:
        raw = try_decrypt_text(row["config_json"])
        if raw:
            try:
                stored = json.loads(raw)
            except json.JSONDecodeError:
                stored = {}
            if isinstance(stored, dict):
                values.update({k: v for k, v in stored.items() if k in values})
    return values


def save_rotation_config_sync(user_id: int, values: dict) -> dict:
    merged = dict(DEFAULT_ROTATION_CONFIG)
    merged.update({k: v for k, v in (values or {}).items() if k in merged})
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        conn.execute(
            """
            INSERT INTO user_proxy_configs (user_id, config_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                config_json = excluded.config_json,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                encrypt_text(json.dumps(merged, ensure_ascii=False)),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
        conn.commit()
    return merged
