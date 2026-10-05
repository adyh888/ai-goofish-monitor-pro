"""
Dashboard 概览路由
"""
from fastapi import APIRouter, Depends, HTTPException

from src.api.dependencies import get_current_user, get_task_service
from src.infrastructure.persistence.user_repository import User
from src.services.dashboard_service import build_dashboard_snapshot
from src.services.task_service import TaskService


router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
async def get_dashboard_summary(
    task_service: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_user),
):
    try:
        user_scope = None if current_user.is_admin else current_user.id
        tasks = await task_service.get_all_tasks(user_scope)
        return await build_dashboard_snapshot(tasks, user_id=user_scope)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"加载 dashboard 数据失败: {exc}")
