"""
任务管理路由
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from typing import List
import os
import aiofiles
from src.api.dependencies import (
    get_current_user,
    get_process_service,
    get_scheduler_service,
    get_task_generation_service,
    get_task_service,
)
from src.infrastructure.persistence.user_repository import User


def _env_int(name: str, default: int) -> int:
    import os as _os

    try:
        return max(1, int(_os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


async def _enforce_task_quota(service: "TaskService", current_user: "User") -> None:
    """每用户任务数量上限（管理员不受限）。"""
    if current_user.is_admin:
        return
    limit = _env_int("PER_USER_TASK_LIMIT", 10)
    existing = await service.get_all_tasks(current_user.id)
    if len(existing) >= limit:
        raise HTTPException(
            status_code=400,
            detail=f"已达到任务数量上限（{limit} 个），请先清理不需要的任务。",
        )


def _ensure_task_access(task, current_user: User) -> None:
    """非本人且非管理员访问他人任务时返回 404，避免泄露任务存在性。"""
    if current_user.is_admin:
        return
    if task.user_id is not None and task.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="任务未找到")
from src.services.task_service import TaskService, DuplicateTaskNameError
from src.services.process_service import ProcessService
from src.services.scheduler_service import SchedulerService
from src.services.task_generation_service import TaskGenerationService
from src.services.task_generation_runner import (
    build_task_create,
    resolve_task_prompt_paths,
    run_ai_generation_job,
)
from src.services.task_payloads import serialize_task, serialize_tasks
from src.domain.models.task import TaskCreate, TaskUpdate, TaskGenerateRequest
from src.prompt_utils import generate_criteria
from src.utils import resolve_task_log_path
from src.services.account_strategy_service import normalize_account_strategy
from src.infrastructure.persistence.storage_names import build_result_filename
from src.services.price_history_service import delete_price_snapshots
from src.services.result_storage_service import delete_result_file_records
router = APIRouter(prefix="/api/tasks", tags=["tasks"])

async def _reload_scheduler_if_needed(
    task_service: TaskService,
    scheduler_service: SchedulerService,
):
    tasks = await task_service.get_all_tasks()
    await scheduler_service.reload_jobs(tasks)


def _has_keyword_rules(rules) -> bool:
    return bool(rules and len(rules) > 0)


def _validate_final_account_strategy(existing_task, task_update: TaskUpdate) -> None:
    account_state_file = (
        task_update.account_state_file
        if task_update.account_state_file is not None
        else existing_task.account_state_file
    )
    account_strategy = normalize_account_strategy(
        task_update.account_strategy,
        account_state_file,
    )
    task_update.account_strategy = account_strategy
    if account_strategy == "fixed" and not account_state_file:
        raise HTTPException(status_code=400, detail="固定账号模式下必须选择账号。")
@router.get("", response_model=List[dict])
async def get_tasks(
    service: TaskService = Depends(get_task_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的任务列表（管理员可见全部）"""
    user_scope = None if current_user.is_admin else current_user.id
    tasks = await service.get_all_tasks(user_scope)
    return serialize_tasks(tasks, scheduler_service)
@router.get("/{task_id}", response_model=dict)
async def get_task(
    task_id: int,
    service: TaskService = Depends(get_task_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
    current_user: User = Depends(get_current_user),
):
    """获取单个任务"""
    task = await service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务未找到")
    _ensure_task_access(task, current_user)
    return serialize_task(task, scheduler_service)
@router.post("/", response_model=dict)
async def create_task(
    task_create: TaskCreate,
    service: TaskService = Depends(get_task_service),
    current_user: User = Depends(get_current_user),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
):
    """创建新任务"""
    await _enforce_task_quota(service, current_user)
    scoped_create = resolve_task_prompt_paths(task_create, current_user.id)
    try:
        task = await service.create_task(scoped_create, user_id=current_user.id)
    except DuplicateTaskNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await _reload_scheduler_if_needed(service, scheduler_service)
    return {"message": "任务创建成功", "task": serialize_task(task, scheduler_service)}
@router.post("/generate", response_model=dict)
async def generate_task(
    req: TaskGenerateRequest,
    service: TaskService = Depends(get_task_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
    generation_service: TaskGenerationService = Depends(get_task_generation_service),
    current_user: User = Depends(get_current_user),
):
    """创建任务。AI模式会生成分析标准，关键词模式直接保存规则。"""
    print(f"收到任务生成请求: {req.task_name}，模式: {req.decision_mode}")
    await _enforce_task_quota(service, current_user)

    try:
        mode = req.decision_mode or "ai"
        if mode == "ai":
            job = await generation_service.create_job(req.task_name)
            generation_service.track(
                run_ai_generation_job(
                    job_id=job.job_id,
                    req=req,
                    task_service=service,
                    scheduler_service=scheduler_service,
                    generation_service=generation_service,
                    user_id=current_user.id,
                )
            )
            return JSONResponse(
                status_code=202,
                content={
                    "message": "AI 任务生成已开始。",
                    "job": job.model_dump(mode="json"),
                },
            )

        task = await service.create_task(
            resolve_task_prompt_paths(build_task_create(req, ""), current_user.id),
            user_id=current_user.id,
        )
        await _reload_scheduler_if_needed(service, scheduler_service)
        return {"message": "任务创建成功。", "task": serialize_task(task, scheduler_service)}

    except HTTPException:
        raise
    except DuplicateTaskNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        error_msg = f"AI任务生成API发生未知错误: {str(e)}"
        print(error_msg)
        import traceback
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=error_msg)
@router.get("/generate-jobs/{job_id}", response_model=dict)
async def get_task_generation_job(
    job_id: str,
    generation_service: TaskGenerationService = Depends(get_task_generation_service),
):
    """获取任务生成作业状态"""
    job = await generation_service.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务生成作业未找到")
    return {"job": job.model_dump(mode="json")}
@router.patch("/{task_id}", response_model=dict)
async def update_task(
    task_id: int,
    task_update: TaskUpdate,
    service: TaskService = Depends(get_task_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
    current_user: User = Depends(get_current_user),
):
    """更新任务"""
    try:
        existing_task = await service.get_task(task_id)
        if not existing_task:
            raise HTTPException(status_code=404, detail="任务未找到")
        _ensure_task_access(existing_task, current_user)
        _validate_final_account_strategy(existing_task, task_update)

        current_mode = getattr(existing_task, "decision_mode", "ai") or "ai"
        target_mode = task_update.decision_mode or current_mode
        description_changed = (
            task_update.description is not None
            and task_update.description != existing_task.description
        )
        switched_to_ai = current_mode != "ai" and target_mode == "ai"

        if target_mode == "keyword":
            final_rules = (
                task_update.keyword_rules
                if task_update.keyword_rules is not None
                else getattr(existing_task, "keyword_rules", [])
            )
            if not _has_keyword_rules(final_rules):
                raise HTTPException(status_code=400, detail="关键词模式下至少需要一个关键词。")
        if target_mode == "ai" and (description_changed or switched_to_ai):
            print(f"检测到任务 {task_id} 需要刷新 AI 标准文件，开始重新生成...")
            try:
                description_for_ai = (
                    task_update.description
                    if task_update.description is not None
                    else existing_task.description
                )
                if not str(description_for_ai or "").strip():
                    raise HTTPException(status_code=400, detail="AI 模式下详细需求不能为空。")
                safe_keyword = "".join(
                    c for c in existing_task.keyword.lower().replace(' ', '_')
                    if c.isalnum() or c in "_-"
                ).rstrip()
                from src.utils import get_user_prompt_dir

                output_filename = os.path.join(
                    get_user_prompt_dir(current_user.id),
                    f"{safe_keyword}_criteria.txt",
                )
                print(f"目标文件路径: {output_filename}")
                print("开始调用 AI 生成新的分析标准...")
                from src.services.ai_client_factory import build_user_ai_client

                generated_criteria = await generate_criteria(
                    user_description=description_for_ai,
                    reference_file_path="prompts/macbook_criteria.txt",
                    ai_client=build_user_ai_client(current_user.id),
                )
                if not generated_criteria or len(generated_criteria.strip()) == 0:
                    print("AI 返回的内容为空")
                    raise HTTPException(status_code=500, detail="AI 未能生成分析标准，返回内容为空。")
                print(f"保存新的分析标准到: {output_filename}")
                os.makedirs(os.path.dirname(output_filename) or "prompts", exist_ok=True)
                async with aiofiles.open(output_filename, 'w', encoding='utf-8') as f:
                    await f.write(generated_criteria)
                print(f"新的分析标准已保存")
                task_update.ai_prompt_criteria_file = output_filename
                print(f"已更新 ai_prompt_criteria_file 字段为: {output_filename}")
            except HTTPException:
                raise
            except Exception as e:
                error_msg = f"重新生成 criteria 文件时出错: {str(e)}"
                print(error_msg)
                import traceback
                print(traceback.format_exc())
                raise HTTPException(status_code=500, detail=error_msg)
        task = await service.update_task(task_id, task_update)
        await _reload_scheduler_if_needed(service, scheduler_service)
        return {"message": "任务更新成功", "task": serialize_task(task, scheduler_service)}
    except DuplicateTaskNameError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
@router.delete("/{task_id}", response_model=dict)
async def delete_task(
    task_id: int,
    service: TaskService = Depends(get_task_service),
    process_service: ProcessService = Depends(get_process_service),
    scheduler_service: SchedulerService = Depends(get_scheduler_service),
    current_user: User = Depends(get_current_user),
):
    """删除任务"""
    task = await service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务未找到")
    _ensure_task_access(task, current_user)

    await process_service.stop_task(task_id)
    success = await service.delete_task(task_id)
    if not success:
        raise HTTPException(status_code=404, detail="任务未找到")
    await _reload_scheduler_if_needed(service, scheduler_service)
    try:
        keyword = (task.keyword or "").strip()
        if keyword:
            remaining_tasks = await service.get_all_tasks()
            keyword_still_in_use = any(
                (remaining_task.keyword or "").strip() == keyword
                for remaining_task in remaining_tasks
            )
            owner_scope = task.user_id if not current_user.is_admin else task.user_id
            if not keyword_still_in_use:
                await delete_result_file_records(
                    build_result_filename(keyword), user_id=owner_scope
                )
                delete_price_snapshots(keyword, user_id=owner_scope)
            else:
                # 关键词仍被他人任务占用，只清理本人数据
                await delete_result_file_records(
                    build_result_filename(keyword), user_id=task.user_id
                )
                delete_price_snapshots(keyword, user_id=task.user_id)
    except Exception as e:
        print(f"删除任务结果文件时出错: {e}")

    try:
        log_file_path = resolve_task_log_path(task_id, task.task_name)
        if os.path.exists(log_file_path):
            os.remove(log_file_path)
    except Exception as e:
        print(f"删除任务日志文件时出错: {e}")
    return {"message": "任务删除成功"}
@router.post("/start/{task_id}", response_model=dict)
async def start_task(
    task_id: int,
    task_service: TaskService = Depends(get_task_service),
    process_service: ProcessService = Depends(get_process_service),
    current_user: User = Depends(get_current_user),
):
    """启动单个任务"""
    task = await task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务未找到")
    _ensure_task_access(task, current_user)
    if not current_user.is_admin:
        # 每用户同时运行 1 个任务
        own_tasks = await task_service.get_all_tasks(current_user.id)
        running_own = sum(1 for t in own_tasks if t.is_running and t.id != task.id)
        if running_own >= _env_int("PER_USER_CONCURRENT_RUNNING", 1):
            raise HTTPException(
                status_code=400,
                detail="每个账号同时只能运行 1 个任务，请先停止正在运行的任务。",
            )
    if not task.enabled:
        raise HTTPException(status_code=400, detail="任务已被禁用，无法启动")
    if task.is_running:
        raise HTTPException(status_code=400, detail="任务已在运行中")
    outcome = await process_service.start_task(task_id, task.task_name)
    if not outcome.started:
        if outcome.status == "global_busy":
            raise HTTPException(status_code=429, detail=outcome.detail)
        if outcome.status == "guard_paused":
            # 失败保护暂停属预期状态，返回 409 并给出明确原因供前端展示
            raise HTTPException(status_code=409, detail=outcome.detail)
        if outcome.status == "membership_expired":
            raise HTTPException(status_code=403, detail=outcome.detail)
        if outcome.status == "already_running":
            raise HTTPException(status_code=400, detail="任务已在运行中")
        raise HTTPException(
            status_code=500,
            detail=outcome.detail or "启动任务失败，请查看后端日志",
        )
    return {"message": f"任务 '{task.task_name}' 已启动"}
@router.post("/stop/{task_id}", response_model=dict)
async def stop_task(
    task_id: int,
    task_service: TaskService = Depends(get_task_service),
    process_service: ProcessService = Depends(get_process_service),
    current_user: User = Depends(get_current_user),
):
    """停止单个任务"""
    task = await task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务未找到")
    _ensure_task_access(task, current_user)
    await process_service.stop_task(task_id)
    return {"message": f"任务ID {task_id} 已发送停止信号"}
