"""卡密（会员激活码）仓储实现。

状态流转：unused → used（激活即绑定用户，不退不换）
          unused → disabled（管理端禁用）→ unused（可恢复）
"""
from __future__ import annotations

import secrets
import string
from dataclasses import dataclass

from src.infrastructure.persistence.sqlite_bootstrap import bootstrap_sqlite_storage
from src.infrastructure.persistence.sqlite_connection import sqlite_connection
from src.services.security import utc_now_iso

# 去掉易混淆字符（0/O、1/I/L）的码表
_CODE_ALPHABET = string.ascii_uppercase + string.digits
_CODE_ALPHABET = "".join(
    ch for ch in _CODE_ALPHABET if ch not in "OIL"
)
_CODE_SEGMENT_LENGTH = 4
_CODE_PREFIX = "XYG"


@dataclass
class CardKey:
    id: int
    code: str
    duration_days: int
    status: str
    batch_no: str
    note: str
    agent_id: int | None
    used_by: int | None
    used_at: str | None
    created_at: str


def _row_to_card(row) -> CardKey:
    return CardKey(
        id=row["id"],
        code=row["code"],
        duration_days=int(row["duration_days"]),
        status=row["status"],
        batch_no=row["batch_no"] or "",
        note=row["note"] or "",
        agent_id=row["agent_id"],
        used_by=row["used_by"],
        used_at=row["used_at"],
        created_at=row["created_at"],
    )


def _generate_code() -> str:
    segments = (
        "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_SEGMENT_LENGTH))
        for _ in range(3)
    )
    return f"{_CODE_PREFIX}-{'-'.join(segments)}"


def generate_cards_sync(
    *,
    count: int,
    duration_days: int,
    batch_no: str = "",
    note: str = "",
) -> list[CardKey]:
    if count < 1 or count > 1000:
        raise ValueError("单次生成数量须在 1~1000 之间")
    if duration_days < 1 or duration_days > 3650:
        raise ValueError("卡密天数须在 1~3650 之间")

    created: list[CardKey] = []
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        for _ in range(count):
            # 碰撞重试：36bit 随机空间下几乎不发生，防御性循环兜底
            for _attempt in range(20):
                code = _generate_code()
                exists = conn.execute(
                    "SELECT 1 FROM card_keys WHERE code = ?", (code,)
                ).fetchone()
                if not exists:
                    break
            else:
                raise RuntimeError("卡密码段生成冲突次数过多，请重试")
            conn.execute(
                """
                INSERT INTO card_keys (code, duration_days, status, batch_no, note, created_at)
                VALUES (?, ?, 'unused', ?, ?, ?)
                """,
                (code, duration_days, batch_no, note, utc_now_iso()),
            )
            created.append(code)
        conn.commit()
        rows = conn.execute(
            "SELECT * FROM card_keys WHERE code IN (%s)"
            % ",".join("?" for _ in created),
            tuple(created),
        ).fetchall()
    by_code = {row["code"]: _row_to_card(row) for row in rows}
    return [by_code[code] for code in created]


def get_card_by_code_sync(code: str) -> CardKey | None:
    normalized = (code or "").strip().upper()
    if not normalized:
        return None
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        row = conn.execute(
            "SELECT * FROM card_keys WHERE code = ?", (normalized,)
        ).fetchone()
    return _row_to_card(row) if row else None


def list_cards_sync(
    *,
    status: str | None = None,
    batch_no: str | None = None,
    limit: int = 500,
) -> list[CardKey]:
    bootstrap_sqlite_storage()
    query = "SELECT * FROM card_keys"
    conditions: list[str] = []
    params: list[object] = []
    if status:
        conditions.append("status = ?")
        params.append(status)
    if batch_no:
        conditions.append("batch_no = ?")
        params.append(batch_no)
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with sqlite_connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return [_row_to_card(row) for row in rows]


def list_unused_codes_sync(batch_no: str | None = None) -> list[str]:
    bootstrap_sqlite_storage()
    query = "SELECT code FROM card_keys WHERE status = 'unused'"
    params: list[object] = []
    if batch_no:
        query += " AND batch_no = ?"
        params.append(batch_no)
    query += " ORDER BY id ASC"
    with sqlite_connection() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
    return [row["code"] for row in rows]


def mark_card_used_sync(card_id: int, user_id: int) -> None:
    with sqlite_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE card_keys
            SET status = 'used', used_by = ?, used_at = ?
            WHERE id = ? AND status = 'unused'
            """,
            (user_id, utc_now_iso(), card_id),
        )
        if cursor.rowcount == 0:
            raise ValueError("卡密已被使用或已禁用")
        conn.commit()


def set_card_status_sync(card_id: int, status: str) -> CardKey | None:
    """unused 与 disabled 之间切换；已使用的卡密不可变更。"""
    if status not in ("unused", "disabled"):
        raise ValueError("目标状态仅支持 unused/disabled")
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        row = conn.execute(
            "SELECT status FROM card_keys WHERE id = ?", (card_id,)
        ).fetchone()
        if row is None:
            return None
        if row["status"] == "used":
            raise ValueError("已使用的卡密不能变更状态")
        conn.execute(
            "UPDATE card_keys SET status = ? WHERE id = ?", (status, card_id)
        )
        conn.commit()
    with sqlite_connection() as conn:
        row = conn.execute(
            "SELECT * FROM card_keys WHERE id = ?", (card_id,)
        ).fetchone()
    return _row_to_card(row) if row else None


def count_cards_sync(*, status: str | None = None) -> int:
    bootstrap_sqlite_storage()
    query = "SELECT COUNT(1) AS total FROM card_keys"
    params: list[object] = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    with sqlite_connection() as conn:
        row = conn.execute(query, tuple(params)).fetchone()
    return int(row["total"]) if row else 0
