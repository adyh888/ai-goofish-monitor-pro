"""
新架构的主应用入口
整合所有路由和服务
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from src.api.routes import (
    dashboard,
    tasks,
    logs,
    settings,
    prompts,
    results,
    login_state,
    websocket,
    accounts,
    auth as auth_routes,
    admin as admin_routes,
)
from src.api.dependencies import (
    set_process_service,
    set_scheduler_service,
    set_task_generation_service,
    get_current_user,
    require_active_member,
    require_admin,
)
from src.services.task_service import TaskService
from src.services.process_service import ProcessService
from src.services.scheduler_service import SchedulerService
from src.services.task_log_cleanup_service import cleanup_task_logs
from src.services.task_generation_service import TaskGenerationService
from src.infrastructure.persistence.sqlite_bootstrap import bootstrap_sqlite_storage
from src.infrastructure.persistence.sqlite_task_repository import SqliteTaskRepository
from src.infrastructure.persistence.user_repository import ensure_bootstrap_admin_sync
from src.infrastructure.config.settings import settings as app_settings


# 全局服务实例
process_service = ProcessService()
scheduler_service = SchedulerService(process_service)
task_generation_service = TaskGenerationService()


async def _sync_task_runtime_status(task_id: int, is_running: bool) -> None:
    task_service = TaskService(SqliteTaskRepository())
    task = await task_service.get_task(task_id)
    if not task or task.is_running == is_running:
        return
    await task_service.update_task_status(task_id, is_running)
    await websocket.broadcast_message(
        "task_status_changed",
        {"id": task_id, "is_running": is_running},
        user_id=task.user_id,
    )


process_service.set_lifecycle_hooks(
    on_started=lambda task_id: _sync_task_runtime_status(task_id, True),
    on_stopped=lambda task_id: _sync_task_runtime_status(task_id, False),
)

# 设置全局 ProcessService 实例供依赖注入使用
set_process_service(process_service)
set_scheduler_service(scheduler_service)
set_task_generation_service(task_generation_service)


async def _membership_sweep_loop() -> None:
    """每 60 秒扫描过期会员并暂停其任务（续费后由激活接口立即恢复）。"""
    import asyncio

    from src.services.membership_service import pause_expired_user_tasks

    while True:
        await asyncio.sleep(60)
        try:
            affected = await asyncio.to_thread(pause_expired_user_tasks)
            if affected:
                print(f"[会员] 已暂停 {len(affected)} 个过期用户的任务: {affected}")
                tasks_list = await TaskService(SqliteTaskRepository()).get_all_tasks()
                await scheduler_service.reload_jobs(tasks_list)
        except Exception as exc:
            print(f"[会员] 到期扫描失败: {exc}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    print("正在启动应用...")
    bootstrap_sqlite_storage()
    ensure_bootstrap_admin_sync()
    cleanup_task_logs(keep_days=app_settings.task_log_retention_days)

    # 重置所有任务状态为停止
    task_repo = SqliteTaskRepository()
    task_service = TaskService(task_repo)
    tasks_list = await task_service.get_all_tasks()

    for task in tasks_list:
        if task.is_running:
            await task_service.update_task_status(task.id, False)

    # 加载定时任务
    await scheduler_service.reload_jobs(tasks_list)
    scheduler_service.start()

    # 会员到期扫描后台任务
    membership_sweep_task = asyncio.create_task(_membership_sweep_loop())

    print("应用启动完成")

    yield

    # 关闭时
    print("正在关闭应用...")
    membership_sweep_task.cancel()
    scheduler_service.stop()
    await process_service.stop_all()
    print("应用已关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="闲鱼智能监控机器人",
    description="基于AI的闲鱼商品监控系统",
    version="2.0.0",
    lifespan=lifespan
)

# 注册路由
# 会员体系：/api/auth 公开（登录/注册/激活自带限流）；业务路由要求有效会员；
# 平台级配置（系统设置/账号文件/Prompt 库）在 M3 用户化之前仅管理员可访问。
app.include_router(auth_routes.router)
app.include_router(admin_routes.router)
app.include_router(tasks.router, dependencies=[Depends(require_active_member)])
app.include_router(dashboard.router, dependencies=[Depends(require_active_member)])
app.include_router(logs.router, dependencies=[Depends(require_active_member)])
app.include_router(results.router, dependencies=[Depends(require_active_member)])
app.include_router(prompts.router, dependencies=[Depends(require_active_member)])
app.include_router(settings.router, dependencies=[Depends(require_active_member)])
app.include_router(login_state.router, dependencies=[Depends(require_active_member)])
app.include_router(websocket.router)
app.include_router(accounts.router, dependencies=[Depends(require_active_member)])

# 挂载静态文件
# 旧的静态文件目录（用于截图等）
app.mount("/static", StaticFiles(directory="static"), name="static")

# 挂载 Vue 3 前端构建产物
# 注意：需要在所有 API 路由之后挂载，以避免覆盖 API 路由
import os
if os.path.exists("dist"):
    app.mount("/assets", StaticFiles(directory="dist/assets"), name="assets")


# 健康检查端点
@app.get("/health")
async def health_check():
    """健康检查（无需认证）"""
    return {"status": "healthy", "message": "服务正常运行"}


# 主页路由 - 服务 Vue 3 SPA
from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse

@app.get("/")
async def read_root(request: Request):
    """提供 Vue 3 SPA 的主页面"""
    if os.path.exists("dist/index.html"):
        return FileResponse("dist/index.html")
    else:
        return JSONResponse(
            status_code=500,
            content={"error": "前端构建产物不存在，请先运行 cd web-ui && npm run build"}
        )


# Catch-all 路由 - 处理所有前端路由（必须放在最后）
@app.get("/{full_path:path}")
async def serve_spa(request: Request, full_path: str):
    """
    Catch-all 路由，将所有非 API 请求重定向到 index.html
    这样可以支持 Vue Router 的 HTML5 History 模式
    """
    # 如果请求的是静态资源（如 favicon.ico），返回 404
    if full_path.endswith(('.ico', '.png', '.jpg', '.jpeg', '.gif', '.svg', '.css', '.js', '.json')):
        return JSONResponse(status_code=404, content={"error": "资源未找到"})

    # 其他所有路径都返回 index.html，让前端路由处理
    if os.path.exists("dist/index.html"):
        return FileResponse("dist/index.html")
    else:
        return JSONResponse(
            status_code=500,
            content={"error": "前端构建产物不存在，请先运行 cd web-ui && npm run build"}
        )


if __name__ == "__main__":
    import uvicorn
    from src.infrastructure.config.settings import settings

    print(f"启动新架构应用，端口: {app_settings.server_port}")
    uvicorn.run(app, host="0.0.0.0", port=app_settings.server_port)
