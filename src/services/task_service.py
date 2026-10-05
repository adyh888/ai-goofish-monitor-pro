"""
任务管理服务
封装任务相关的业务逻辑
"""
from typing import List, Optional
from src.domain.models.task import Task, TaskCreate, TaskUpdate
from src.domain.repositories.task_repository import TaskRepository


class DuplicateTaskNameError(ValueError):
    """同一用户下任务名重复（同名任务会导致子进程按名匹配时串配置）。"""


class TaskService:
    """任务管理服务"""

    def __init__(self, repository: TaskRepository):
        self.repository = repository

    async def get_all_tasks(self, user_id: int | None = None) -> List[Task]:
        """获取任务列表；user_id 为 None 时返回全部（管理员/调度器视角）"""
        return await self.repository.find_all(user_id)

    async def get_task(self, task_id: int) -> Optional[Task]:
        """获取单个任务"""
        return await self.repository.find_by_id(task_id)

    async def _ensure_unique_task_name(
        self,
        task_name: str,
        user_id: int | None,
        *,
        exclude_task_id: int | None = None,
    ) -> None:
        scope = user_id if user_id is not None else 1
        normalized = (task_name or "").strip()
        for task in await self.repository.find_all(scope):
            if exclude_task_id is not None and task.id == exclude_task_id:
                continue
            if (task.task_name or "").strip() == normalized:
                raise DuplicateTaskNameError(
                    f"当前账号下已存在同名任务「{normalized}」，请换一个任务名。"
                )

    async def create_task(self, task_create: TaskCreate, user_id: int | None = None) -> Task:
        """创建新任务（归属当前用户）"""
        await self._ensure_unique_task_name(task_create.task_name, user_id)
        task = Task(**task_create.model_dump(), is_running=False, user_id=user_id)
        return await self.repository.save(task)

    async def update_task(self, task_id: int, task_update: TaskUpdate) -> Task:
        """更新任务"""
        task = await self.repository.find_by_id(task_id)
        if not task:
            raise ValueError(f"任务 {task_id} 不存在")

        if task_update.task_name is not None:
            new_name = task_update.task_name.strip()
            if new_name != (task.task_name or "").strip():
                await self._ensure_unique_task_name(
                    new_name, task.user_id, exclude_task_id=task_id
                )

        updated_task = task.apply_update(task_update)
        return await self.repository.save(updated_task)

    async def delete_task(self, task_id: int) -> bool:
        """删除任务"""
        return await self.repository.delete(task_id)

    async def update_task_status(self, task_id: int, is_running: bool) -> Task:
        """更新任务运行状态"""
        task_update = TaskUpdate(is_running=is_running)
        return await self.update_task(task_id, task_update)
