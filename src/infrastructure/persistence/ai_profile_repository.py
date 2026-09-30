"""
AI 模型配置（ai_profiles）仓储实现。

多模型支持：用户可配置多个服务商/模型，手动"设为当前"，AI 调用失败
（额度用完/限流/认证失效等）时按优先级顺序自动切换到下一个启用的模型。
"""
from __future__ import annotations

from dataclasses import dataclass

from src.infrastructure.persistence.sqlite_bootstrap import bootstrap_sqlite_storage
from src.infrastructure.persistence.sqlite_connection import sqlite_connection


@dataclass
class AiProfile:
    id: int
    name: str
    base_url: str
    api_key: str
    model_name: str
    proxy_url: str
    enabled: bool
    is_active: bool
    sort_order: int


def _row_to_profile(row) -> AiProfile:
    return AiProfile(
        id=row["id"],
        name=row["name"],
        base_url=row["base_url"],
        api_key=row["api_key"] or "",
        model_name=row["model_name"],
        proxy_url=row["proxy_url"] or "",
        enabled=bool(row["enabled"]),
        is_active=bool(row["is_active"]),
        sort_order=row["sort_order"],
    )


def list_profiles_sync() -> list[AiProfile]:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM ai_profiles ORDER BY sort_order ASC, id ASC"
        ).fetchall()
    return [_row_to_profile(row) for row in rows]


def list_enabled_profiles_active_first_sync() -> list[AiProfile]:
    """failover 候选顺序：当前激活的排最前，其余按优先级排序（仅启用的）。"""
    profiles = [p for p in list_profiles_sync() if p.enabled]
    profiles.sort(key=lambda p: (not p.is_active, p.sort_order, p.id))
    return profiles


def get_active_profile_sync() -> AiProfile | None:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        row = conn.execute(
            "SELECT * FROM ai_profiles WHERE is_active = 1 LIMIT 1"
        ).fetchone()
    return _row_to_profile(row) if row else None


def get_profile_sync(profile_id: int) -> AiProfile | None:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        row = conn.execute(
            "SELECT * FROM ai_profiles WHERE id = ?", (profile_id,)
        ).fetchone()
    return _row_to_profile(row) if row else None


def create_profile_sync(
    *,
    name: str,
    base_url: str,
    model_name: str,
    api_key: str = "",
    proxy_url: str = "",
    enabled: bool = True,
) -> AiProfile:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        is_first = conn.execute("SELECT COUNT(1) AS total FROM ai_profiles").fetchone()
        is_active = 1 if (is_first is None or int(is_first["total"]) == 0) else 0
        max_order = conn.execute(
            "SELECT COALESCE(MAX(sort_order), -1) AS max_order FROM ai_profiles"
        ).fetchone()
        cursor = conn.execute(
            """
            INSERT INTO ai_profiles
                (name, base_url, api_key, model_name, proxy_url, enabled, is_active, sort_order)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                base_url,
                api_key,
                model_name,
                proxy_url,
                1 if enabled else 0,
                is_active,
                int(max_order["max_order"]) + 1,
            ),
        )
        new_id = cursor.lastrowid
        conn.commit()
    return get_profile_sync(new_id)


def update_profile_sync(
    profile_id: int,
    *,
    name: str | None = None,
    base_url: str | None = None,
    model_name: str | None = None,
    api_key: str | None = None,
    proxy_url: str | None = None,
    enabled: bool | None = None,
) -> AiProfile | None:
    """api_key 传 None 表示保持不变，传空字符串表示清除。"""
    bootstrap_sqlite_storage()
    fields = {}
    if name is not None:
        fields["name"] = name
    if base_url is not None:
        fields["base_url"] = base_url
    if model_name is not None:
        fields["model_name"] = model_name
    if api_key is not None:
        fields["api_key"] = api_key
    if proxy_url is not None:
        fields["proxy_url"] = proxy_url
    if enabled is not None:
        fields["enabled"] = 1 if enabled else 0
    if not fields:
        return get_profile_sync(profile_id)

    with sqlite_connection() as conn:
        set_clause = ", ".join(f"{col} = ?" for col in fields)
        conn.execute(
            f"UPDATE ai_profiles SET {set_clause} WHERE id = ?",
            (*fields.values(), profile_id),
        )
        if fields.get("enabled") == 0:
            _ensure_active_profile_valid(conn)
        conn.commit()
    return get_profile_sync(profile_id)


def delete_profile_sync(profile_id: int) -> bool:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        cursor = conn.execute("DELETE FROM ai_profiles WHERE id = ?", (profile_id,))
        deleted = cursor.rowcount > 0
        _ensure_active_profile_valid(conn)
        conn.commit()
    return deleted


def set_active_profile_sync(profile_id: int) -> AiProfile | None:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        row = conn.execute(
            "SELECT enabled FROM ai_profiles WHERE id = ?", (profile_id,)
        ).fetchone()
        if row is None:
            return None
        if not row["enabled"]:
            raise ValueError("已禁用的模型不能设为当前模型")
        conn.execute("UPDATE ai_profiles SET is_active = 0 WHERE is_active = 1")
        conn.execute("UPDATE ai_profiles SET is_active = 1 WHERE id = ?", (profile_id,))
        conn.commit()
    return get_profile_sync(profile_id)


def set_profile_enabled_sync(profile_id: int, enabled: bool) -> AiProfile | None:
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        conn.execute(
            "UPDATE ai_profiles SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, profile_id),
        )
        _ensure_active_profile_valid(conn)
        conn.commit()
    return get_profile_sync(profile_id)


def move_profile_sync(profile_id: int, direction: str) -> list[AiProfile]:
    """direction: 'up' 或 'down'，交换相邻配置的优先级顺序。"""
    if direction not in ("up", "down"):
        raise ValueError("direction 仅支持 up/down")
    profiles = list_profiles_sync()
    index = next((i for i, p in enumerate(profiles) if p.id == profile_id), None)
    if index is None:
        return profiles
    swap_with = index - 1 if direction == "up" else index + 1
    if swap_with < 0 or swap_with >= len(profiles):
        return profiles

    with sqlite_connection() as conn:
        conn.execute(
            "UPDATE ai_profiles SET sort_order = ? WHERE id = ?",
            (profiles[swap_with].sort_order, profiles[index].id),
        )
        conn.execute(
            "UPDATE ai_profiles SET sort_order = ? WHERE id = ?",
            (profiles[index].sort_order, profiles[swap_with].id),
        )
        conn.commit()
    return list_profiles_sync()


def _ensure_active_profile_valid(conn) -> None:
    """激活配置被删除/禁用后，把激活位转移到第一个启用的配置上。"""
    active = conn.execute(
        "SELECT id, enabled FROM ai_profiles WHERE is_active = 1 LIMIT 1"
    ).fetchone()
    if active is not None and active["enabled"]:
        return
    conn.execute("UPDATE ai_profiles SET is_active = 0 WHERE is_active = 1")
    fallback = conn.execute(
        "SELECT id FROM ai_profiles WHERE enabled = 1 ORDER BY sort_order ASC, id ASC LIMIT 1"
    ).fetchone()
    if fallback is not None:
        conn.execute(
            "UPDATE ai_profiles SET is_active = 1 WHERE id = ?", (fallback["id"],)
        )
