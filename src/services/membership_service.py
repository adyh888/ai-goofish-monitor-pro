"""会员到期与任务调度联动。

到期 → 该用户所有启用任务暂停（enabled=0，paused_by_membership=1，不删除）；
激活/续期/管理员调整到期时间 → 自动恢复被会员暂停的任务。
"""
from __future__ import annotations

from src.infrastructure.persistence.sqlite_bootstrap import bootstrap_sqlite_storage
from src.infrastructure.persistence.sqlite_connection import sqlite_connection
from src.infrastructure.persistence.user_repository import list_users_sync
from src.services.auth_service import is_membership_active


def set_membership_paused(user_id: int, *, paused: bool) -> int:
    """暂停/恢复某用户被会员状态拦下的任务，返回受影响行数。"""
    bootstrap_sqlite_storage()
    with sqlite_connection() as conn:
        if paused:
            cursor = conn.execute(
                """
                UPDATE tasks
                SET enabled = 0, paused_by_membership = 1, is_running = 0
                WHERE user_id = ? AND enabled = 1 AND paused_by_membership = 0
                """,
                (user_id,),
            )
        else:
            cursor = conn.execute(
                """
                UPDATE tasks
                SET enabled = 1, paused_by_membership = 0
                WHERE user_id = ? AND paused_by_membership = 1
                """,
                (user_id,),
            )
        conn.commit()
        return int(cursor.rowcount or 0)


def apply_membership_state(user_id: int) -> str:
    """根据当前会员状态同步任务暂停位，返回 'resumed' / 'paused' / 'none'。"""
    from src.infrastructure.persistence.user_repository import get_user_by_id_sync

    user = get_user_by_id_sync(user_id)
    if user is None:
        return "none"
    if is_membership_active(user):
        return "resumed" if resume_user_after_activation(user_id) else "none"
    return "paused" if set_membership_paused(user_id, paused=True) else "none"


def pause_expired_user_tasks() -> list[int]:
    """扫描所有已过期用户并暂停其任务，返回受影响的用户 id 列表。"""
    affected: list[int] = []
    now = None
    for user in list_users_sync():
        if user.is_admin or user.status != "active":
            continue
        if is_membership_active(user, now=now):
            continue
        if set_membership_paused(user.id, paused=True) > 0:
            affected.append(user.id)
    return affected


def resume_user_after_activation(user_id: int) -> int:
    """激活/续费后恢复该用户的任务。"""
    return set_membership_paused(user_id, paused=False)


async def sweep_and_get_all_tasks(task_service):
    """供调度器使用的便捷方法：先执行到期扫描，再返回全量任务。"""
    from asyncio import to_thread

    await to_thread(pause_expired_user_tasks)
    return await task_service.get_all_tasks()
