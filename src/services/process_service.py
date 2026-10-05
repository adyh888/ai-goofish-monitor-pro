"""
进程管理服务
负责管理爬虫进程的启动和停止
"""

import asyncio
import contextlib
import os
import signal
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Awaitable, Callable, Dict, TextIO

from src.ai_handler import send_ntfy_notification
from src.failure_guard import FailureGuard, build_task_key
from src.infrastructure.persistence.sqlite_task_repository import (
    find_task_by_id_sync,
    find_task_by_name_sync,
)
from src.utils import build_task_log_path

STOP_TIMEOUT_SECONDS = 20
SPIDER_DEBUG_LIMIT_ENV = "SPIDER_DEBUG_LIMIT"


def _global_concurrency_limit() -> int:
    try:
        return max(1, int(os.getenv("GLOBAL_SPIDER_CONCURRENCY", "5")))
    except (TypeError, ValueError):
        return 5
LifecycleHook = Callable[[int], Awaitable[None] | None]


@dataclass
class StartTaskOutcome:
    """start_task 的结果：started 为 False 时 status/detail 说明具体原因"""

    started: bool
    status: str  # started / already_running / guard_paused / spawn_failed
    detail: str = ""


class ProcessService:
    """进程管理服务"""

    def __init__(self):
        self.processes: Dict[int, asyncio.subprocess.Process] = {}
        self.log_paths: Dict[int, str] = {}
        self.log_handles: Dict[int, TextIO] = {}
        self.task_names: Dict[int, str] = {}
        self.exit_watchers: Dict[int, asyncio.Task] = {}
        self.failure_guard = FailureGuard()
        self._on_started: LifecycleHook | None = None
        self._on_stopped: LifecycleHook | None = None

    def set_lifecycle_hooks(
        self,
        *,
        on_started: LifecycleHook | None = None,
        on_stopped: LifecycleHook | None = None,
    ) -> None:
        self._on_started = on_started
        self._on_stopped = on_stopped

    async def _invoke_hook(self, hook: LifecycleHook | None, task_id: int) -> None:
        if hook is None:
            return
        result = hook(task_id)
        if asyncio.iscoroutine(result):
            await result

    def _resolve_cookie_path(self, task_name: str, user_id: int | None = None) -> str | None:
        """Best-effort cookie/state path for a task（按用户隔离）。"""
        try:
            task = find_task_by_name_sync(task_name, user_id)
            if task and isinstance(task.account_state_file, str) and task.account_state_file.strip():
                return task.account_state_file.strip()
        except Exception:
            pass

        from src.utils import get_user_state_file

        state_file = get_user_state_file(user_id)
        return state_file if os.path.exists(state_file) else None

    def _resolve_task_owner(self, task_id: int) -> int:
        """任务归属人（爬虫子进程与用户级配置都以它为准）。"""
        try:
            task = find_task_by_id_sync(task_id)
            if task and task.user_id:
                return int(task.user_id)
        except Exception:
            pass
        return 1

    def _membership_blocked(self, user_id: int) -> bool:
        if user_id <= 1:
            return False  # admin 永不放行阻断
        try:
            from src.infrastructure.persistence.user_repository import (
                get_user_by_id_sync,
            )
            from src.services.auth_service import is_membership_active

            user = get_user_by_id_sync(user_id)
            if user is None or user.status != "active":
                return True
            return not is_membership_active(user)
        except Exception:
            return False

    def is_running(self, task_id: int) -> bool:
        """检查任务是否正在运行"""
        process = self.processes.get(task_id)
        return process is not None and process.returncode is None

    async def _drain_finished_process(self, task_id: int) -> None:
        process = self.processes.get(task_id)
        if process is None or process.returncode is None:
            return

        watcher = self.exit_watchers.get(task_id)
        if watcher is not None:
            await asyncio.shield(watcher)
            return

        self._cleanup_runtime(task_id, process)
        await self._invoke_hook(self._on_stopped, task_id)

    def _open_log_file(self, task_id: int, task_name: str) -> tuple[str, TextIO]:
        os.makedirs("logs", exist_ok=True)
        log_file_path = build_task_log_path(task_id, task_name)
        log_file_handle = open(log_file_path, "a", encoding="utf-8")
        return log_file_path, log_file_handle

    def _build_spawn_command(self, task_id: int, task_name: str, user_id: int = 1) -> list[str]:
        command = [
            sys.executable,
            "-u",
            "spider_v2.py",
            # --task-id 优先按 ID 精确取配置；--task-name 仅用于日志展示与兼容旧调用
            "--task-id",
            str(task_id),
            "--task-name",
            task_name,
            "--user-id",
            str(user_id),
        ]
        debug_limit = str(os.getenv(SPIDER_DEBUG_LIMIT_ENV, "")).strip()
        if debug_limit.isdigit() and int(debug_limit) > 0:
            command.extend(["--debug-limit", debug_limit])
        return command

    async def _spawn_process(
        self,
        task_id: int,
        task_name: str,
        log_file_handle: TextIO,
        user_id: int = 1,
    ) -> asyncio.subprocess.Process:
        preexec_fn = os.setsid if sys.platform != "win32" else None
        child_env = os.environ.copy()
        child_env["PYTHONIOENCODING"] = "utf-8"
        child_env["PYTHONUTF8"] = "1"
        child_env["SPIDER_USER_ID"] = str(user_id)
        self._apply_user_env(child_env, user_id)
        return await asyncio.create_subprocess_exec(
            *self._build_spawn_command(task_id, task_name, user_id),
            stdout=log_file_handle,
            stderr=log_file_handle,
            preexec_fn=preexec_fn,
            env=child_env,
        )

    def _apply_user_env(self, child_env: dict, user_id: int) -> None:
        """把该用户的轮换/代理配置注入子进程环境（与平台 .env 隔离）。

        代理池策略（混合模式）：用户自有代理优先；未填时按平台开关
        （PLATFORM_PROXY_POOL_ENABLED，默认开）回落到平台共享池。
        """
        try:
            from src.infrastructure.persistence.user_config_repository import (
                load_rotation_config_sync,
            )

            values = load_rotation_config_sync(user_id)
        except Exception as exc:
            print(f"[用户环境] 读取用户 #{user_id} 轮换配置失败，沿用平台默认: {exc}")
            return

        for key, value in values.items():
            if key == "PROXY_POOL":
                continue
            child_env[key] = ("true" if value else "false") if isinstance(value, bool) else str(value)

        user_pool = str(values.get("PROXY_POOL") or "").strip()
        platform_enabled = os.getenv("PLATFORM_PROXY_POOL_ENABLED", "true").strip().lower() in {
            "1", "true", "yes", "on",
        }
        if user_pool:
            child_env["PROXY_POOL"] = user_pool
        elif not platform_enabled:
            child_env.pop("PROXY_POOL", None)

    def _register_runtime(
        self,
        task_id: int,
        task_name: str,
        process: asyncio.subprocess.Process,
        log_file_path: str,
        log_file_handle: TextIO,
    ) -> None:
        self.processes[task_id] = process
        self.log_paths[task_id] = log_file_path
        self.log_handles[task_id] = log_file_handle
        self.task_names[task_id] = task_name
        self.exit_watchers[task_id] = asyncio.create_task(self._watch_process_exit(process))

    async def start_task(self, task_id: int, task_name: str) -> StartTaskOutcome:
        """启动任务进程"""
        await self._drain_finished_process(task_id)
        if self.is_running(task_id):
            print(f"任务 '{task_name}' (ID: {task_id}) 已在运行中")
            return StartTaskOutcome(False, "already_running", "任务已在运行中")

        user_id = self._resolve_task_owner(task_id)
        if self._membership_blocked(user_id):
            return StartTaskOutcome(
                False,
                "membership_expired",
                "该账号会员已过期，任务已停止调度；激活卡密后将自动恢复。",
            )

        running_now = sum(
            1 for process in self.processes.values()
            if process is not None and process.returncode is None
        )
        if running_now >= _global_concurrency_limit():
            return StartTaskOutcome(
                False,
                "global_busy",
                f"系统繁忙：全局已有 {running_now} 个任务在运行（上限 {_global_concurrency_limit()}），请稍后再试。",
            )

        decision = self.failure_guard.should_skip_start(
            build_task_key(user_id, task_name),
            cookie_path=self._resolve_cookie_path(task_name, user_id),
        )
        if decision.skip:
            await self._notify_skip(task_name, decision, user_id)
            paused_until = (
                decision.paused_until.strftime("%Y-%m-%d %H:%M")
                if decision.paused_until
                else "稍后自动恢复"
            )
            detail = (
                f"已触发失败保护：连续失败 {decision.consecutive_failures}/"
                f"{self.failure_guard.threshold} 次，任务暂停至 {paused_until}。"
                f"最近失败原因：{decision.reason}。"
                "更新登录态(Cookie)后会自动解除暂停。"
            )
            return StartTaskOutcome(False, "guard_paused", detail)

        log_file_path = ""
        log_file_handle = None
        try:
            log_file_path, log_file_handle = self._open_log_file(task_id, task_name)
            process = await self._spawn_process(task_id, task_name, log_file_handle, user_id)
        except Exception as exc:
            self._close_log_handle(log_file_handle)
            print(f"启动任务 '{task_name}' 失败: {exc}")
            return StartTaskOutcome(False, "spawn_failed", str(exc))

        self._register_runtime(task_id, task_name, process, log_file_path, log_file_handle)
        print(f"启动任务 '{task_name}' (PID: {process.pid})")
        await self._invoke_hook(self._on_started, task_id)
        return StartTaskOutcome(True, "started")

    async def _notify_skip(self, task_name: str, decision, user_id: int = 1) -> None:
        print(
            f"[FailureGuard] 跳过启动任务 '{task_name}'，已暂停重试 "
            f"(连续失败 {decision.consecutive_failures}/{self.failure_guard.threshold})"
        )
        if not decision.should_notify:
            return
        try:
            await send_ntfy_notification(
                {
                    "商品标题": f"[任务暂停] {task_name}",
                    "当前售价": "N/A",
                    "商品链接": "#",
                },
                "任务处于暂停状态，将跳过执行。\n"
                f"原因: {decision.reason}\n"
                f"连续失败: {decision.consecutive_failures}/{self.failure_guard.threshold}\n"
                f"暂停到: {decision.paused_until.strftime('%Y-%m-%d %H:%M:%S') if decision.paused_until else 'N/A'}\n"
                "修复方法: 更新登录态/cookies文件后会自动恢复。",
                user_id=user_id,
            )
        except Exception as exc:
            print(f"发送任务暂停通知失败: {exc}")

    async def _watch_process_exit(self, process: asyncio.subprocess.Process) -> None:
        await process.wait()
        task_id = self._find_task_id_by_process(process)
        if task_id is None:
            return
        self._cleanup_runtime(task_id, process)
        await self._invoke_hook(self._on_stopped, task_id)

    def _find_task_id_by_process(self, process: asyncio.subprocess.Process) -> int | None:
        for task_id, current_process in self.processes.items():
            if current_process is process:
                return task_id
        return None

    def _cleanup_runtime(
        self,
        task_id: int,
        process: asyncio.subprocess.Process,
    ) -> None:
        if self.processes.get(task_id) is not process:
            return
        self.processes.pop(task_id, None)
        self.log_paths.pop(task_id, None)
        self.task_names.pop(task_id, None)
        self._close_log_handle(self.log_handles.pop(task_id, None))
        self.exit_watchers.pop(task_id, None)

    def _close_log_handle(self, log_handle: TextIO | None) -> None:
        if log_handle is None:
            return
        with contextlib.suppress(Exception):
            log_handle.close()

    def _append_stop_marker(self, log_path: str | None) -> None:
        if not log_path:
            return
        try:
            timestamp = datetime.now().strftime(" %Y-%m-%d %H:%M:%S")
            with open(log_path, "a", encoding="utf-8") as log_file:
                log_file.write(f"[{timestamp}] !!! 任务已被终止 !!!\n")
        except Exception as exc:
            print(f"写入任务终止标记失败: {exc}")

    async def stop_task(self, task_id: int) -> bool:
        """停止任务进程"""
        await self._drain_finished_process(task_id)
        process = self.processes.get(task_id)
        if process is None:
            print(f"任务 ID {task_id} 没有正在运行的进程")
            return False
        if process.returncode is not None:
            await self._await_exit_watcher(task_id)
            print(f"任务进程 {process.pid} (ID: {task_id}) 已退出，略过停止")
            return False

        try:
            await self._terminate_process(process, task_id)
            self._append_stop_marker(self.log_paths.get(task_id))
            await self._await_exit_watcher(task_id)
            print(f"任务进程 {process.pid} (ID: {task_id}) 已终止")
            return True
        except ProcessLookupError:
            print(f"进程 (ID: {task_id}) 已不存在")
            return False
        except Exception as exc:
            print(f"停止任务进程 (ID: {task_id}) 时出错: {exc}")
            return False

    async def _terminate_process(
        self,
        process: asyncio.subprocess.Process,
        task_id: int,
    ) -> None:
        if sys.platform != "win32":
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        else:
            process.terminate()

        try:
            await asyncio.wait_for(process.wait(), timeout=STOP_TIMEOUT_SECONDS)
            return
        except asyncio.TimeoutError:
            print(
                f"任务进程 {process.pid} (ID: {task_id}) 未在 "
                f"{STOP_TIMEOUT_SECONDS} 秒内退出，准备强制终止..."
            )

        if sys.platform != "win32":
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        else:
            process.kill()
        await process.wait()

    async def _await_exit_watcher(self, task_id: int) -> None:
        watcher = self.exit_watchers.get(task_id)
        if watcher is None:
            return
        await asyncio.shield(watcher)

    def reindex_after_delete(self, deleted_task_id: int) -> None:
        """删除任务后同步重排运行时索引，避免任务下标漂移。"""
        self.processes = self._reindex_mapping(self.processes, deleted_task_id)
        self.log_paths = self._reindex_mapping(self.log_paths, deleted_task_id)
        self.log_handles = self._reindex_mapping(self.log_handles, deleted_task_id)
        self.task_names = self._reindex_mapping(self.task_names, deleted_task_id)
        self.exit_watchers = self._reindex_mapping(self.exit_watchers, deleted_task_id)

    def _reindex_mapping(self, mapping: Dict[int, object], deleted_task_id: int) -> Dict[int, object]:
        reindexed: Dict[int, object] = {}
        for task_id, value in mapping.items():
            if task_id == deleted_task_id:
                continue
            next_task_id = task_id - 1 if task_id > deleted_task_id else task_id
            reindexed[next_task_id] = value
        return reindexed

    async def stop_all(self) -> None:
        """停止所有任务进程"""
        task_ids = list(self.processes.keys())
        for task_id in task_ids:
            await self.stop_task(task_id)
