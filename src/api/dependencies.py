"""
FastAPI 依赖注入
提供服务实例的创建和管理
"""
from fastapi import Depends, HTTPException, Request
from src.services.task_service import TaskService
from src.services.notification_service import NotificationService, build_notification_service
from src.services.ai_service import AIAnalysisService
from src.services.process_service import ProcessService
from src.services.scheduler_service import SchedulerService
from src.services.task_generation_service import TaskGenerationService
from src.services.auth_service import MEMBERSHIP_EXPIRED_CODE, is_membership_active
from src.services.security import decode_access_token
from src.infrastructure.persistence.sqlite_task_repository import SqliteTaskRepository
from src.infrastructure.persistence.user_repository import User, get_user_by_id_sync
from src.infrastructure.external.ai_client import AIClient


# 全局 ProcessService 实例（将在 app.py 中设置）
_process_service_instance = None
_scheduler_service_instance = None
_task_generation_service_instance = None


def set_process_service(service: ProcessService):
    """设置全局 ProcessService 实例"""
    global _process_service_instance
    _process_service_instance = service


def set_scheduler_service(service: SchedulerService):
    """设置全局 SchedulerService 实例"""
    global _scheduler_service_instance
    _scheduler_service_instance = service


def set_task_generation_service(service: TaskGenerationService):
    """设置全局 TaskGenerationService 实例"""
    global _task_generation_service_instance
    _task_generation_service_instance = service


# 服务依赖注入
def get_task_service() -> TaskService:
    """获取任务管理服务实例"""
    repository = SqliteTaskRepository()
    return TaskService(repository)


def get_notification_service() -> NotificationService:
    """获取通知服务实例"""
    return build_notification_service()


def get_ai_service() -> AIAnalysisService:
    """获取AI分析服务实例"""
    ai_client = AIClient()
    return AIAnalysisService(ai_client)


def get_process_service() -> ProcessService:
    """获取进程管理服务实例"""
    if _process_service_instance is None:
        raise RuntimeError("ProcessService 未初始化")
    return _process_service_instance


def get_scheduler_service() -> SchedulerService:
    """获取调度服务实例"""
    if _scheduler_service_instance is None:
        raise RuntimeError("SchedulerService 未初始化")
    return _scheduler_service_instance


def get_task_generation_service() -> TaskGenerationService:
    """获取任务生成作业服务实例"""
    if _task_generation_service_instance is None:
        raise RuntimeError("TaskGenerationService 未初始化")
    return _task_generation_service_instance


# ---------------------------------------------------------------------------
# 认证与会员依赖
# ---------------------------------------------------------------------------

def get_current_user(request: Request) -> User:
    """从 Authorization: Bearer <JWT> 解析当前登录用户。"""
    auth_header = request.headers.get("Authorization") or ""
    if not auth_header.startswith("Bearer "):
        raise _unauthorized("未登录或凭证缺失")
    payload = decode_access_token(auth_header[7:].strip())
    if not payload or not payload.get("sub"):
        raise _unauthorized("登录状态已失效，请重新登录")
    user = get_user_by_id_sync(int(payload["sub"]))
    if user is None or user.status != "active":
        raise _unauthorized("账号不存在或已被禁用")
    return user


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=message,
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_active_member(current_user: User = Depends(get_current_user)) -> User:
    """要求当前用户为有效会员（admin 永远放行）。"""
    if not is_membership_active(current_user):
        raise HTTPException(
            status_code=403,
            detail={
                "message": "会员已过期，请激活卡密后继续使用",
                "code": MEMBERSHIP_EXPIRED_CODE,
            },
        )
    return current_user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="仅管理员可访问")
    return current_user
