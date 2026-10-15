import asyncio
import os
import sys
from types import SimpleNamespace

from src.services.process_service import ProcessService


class FakeProcess:
    def __init__(self, pid: int):
        self.pid = pid
        self.returncode = None
        self._done = asyncio.Event()

    async def wait(self):
        await self._done.wait()
        return self.returncode

    def finish(self, returncode: int = 0):
        self.returncode = returncode
        self._done.set()

    def terminate(self):
        self.finish(-15)

    def kill(self):
        self.finish(-9)


def test_process_service_marks_task_stopped_when_process_exits(monkeypatch, tmp_path):
    fake_process = FakeProcess(pid=4321)
    events = []

    async def run_scenario():
        service = ProcessService()
        service.failure_guard.should_skip_start = lambda *args, **kwargs: SimpleNamespace(
            skip=False,
            should_notify=False,
            reason="",
            consecutive_failures=0,
            paused_until=None,
        )

        stopped = asyncio.Event()

        async def on_started(task_id: int):
            events.append(("started", task_id))

        async def on_stopped(task_id: int):
            events.append(("stopped", task_id))
            stopped.set()

        service.set_lifecycle_hooks(on_started=on_started, on_stopped=on_stopped)

        async def fake_create_subprocess_exec(*_args, **_kwargs):
            return fake_process

        monkeypatch.setattr(
            "src.services.process_service.build_task_log_path",
            lambda task_id, _task_name: str(tmp_path / f"task-{task_id}.log"),
        )
        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

        started = await service.start_task(0, "task-a")
        assert started.started is True
        assert started.status == "started"
        assert events == [("started", 0)]
        assert service.is_running(0) is True

        fake_process.finish(0)
        await asyncio.wait_for(stopped.wait(), timeout=1)

        assert ("stopped", 0) in events
        assert service.is_running(0) is False

    asyncio.run(run_scenario())


def test_process_service_reindexes_runtime_maps_after_delete():
    service = ProcessService()
    proc_a = object()
    proc_c = object()
    watcher_a = object()
    watcher_c = object()

    service.processes = {0: proc_a, 2: proc_c}
    service.log_paths = {0: "a.log", 2: "c.log"}
    service.task_names = {0: "A", 2: "C"}
    service.exit_watchers = {0: watcher_a, 2: watcher_c}

    service.reindex_after_delete(1)

    assert service.processes == {0: proc_a, 1: proc_c}
    assert service.log_paths == {0: "a.log", 1: "c.log"}
    assert service.task_names == {0: "A", 1: "C"}
    assert service.exit_watchers == {0: watcher_a, 1: watcher_c}


def test_process_service_adds_debug_limit_arg_when_env_enabled(monkeypatch):
    monkeypatch.setenv("SPIDER_DEBUG_LIMIT", "1")
    service = ProcessService()

    command = service._build_spawn_command(7, "task-a")

    assert command == [
        sys.executable,
        "-u",
        "spider_v2.py",
        "--task-id",
        "7",
        "--task-name",
        "task-a",
        "--user-id",
        "1",
        "--debug-limit",
        "1",
    ]


def test_process_service_spawn_command_prefers_task_id(monkeypatch):
    monkeypatch.delenv("SPIDER_DEBUG_LIMIT", raising=False)
    service = ProcessService()

    command = service._build_spawn_command(7, "task-a", 2)

    assert "--task-id" in command
    assert command[command.index("--task-id") + 1] == "7"
    assert command[command.index("--user-id") + 1] == "2"


def _setup_user_state_dir(tmp_path, monkeypatch, user_id: int):
    state_root = tmp_path / "state"
    user_dir = state_root / f"u{user_id}"
    user_dir.mkdir(parents=True)
    monkeypatch.setenv("ACCOUNT_STATE_DIR", str(state_root))
    return user_dir


def test_resolve_cookie_path_prefers_existing_fixed_account(monkeypatch, tmp_path):
    user_dir = _setup_user_state_dir(tmp_path, monkeypatch, 4)
    fixed_path = user_dir / "fixed.json"
    fixed_path.write_text("{}", encoding="utf-8")
    (user_dir / "newer_named.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        "src.services.process_service.find_task_by_name_sync",
        lambda *_args, **_kwargs: SimpleNamespace(account_state_file=str(fixed_path)),
    )

    service = ProcessService()
    assert service._resolve_cookie_path("task-a", 4) == str(fixed_path)


def test_resolve_cookie_path_prefers_root_state_file(monkeypatch, tmp_path):
    user_dir = _setup_user_state_dir(tmp_path, monkeypatch, 4)
    root_state = user_dir / "xianyu_state.json"
    root_state.write_text("{}", encoding="utf-8")
    (user_dir / "xiaoniu.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        "src.services.process_service.find_task_by_name_sync",
        lambda *_args, **_kwargs: None,
    )

    service = ProcessService()
    assert service._resolve_cookie_path("task-a", 4) == str(root_state)


def test_resolve_cookie_path_falls_back_to_latest_named_account(monkeypatch, tmp_path):
    """auto 策略只有命名账号时，回落到用户目录内最近更新的 .json，
    让失败保护能感知 Cookie 更新并自动解除暂停。"""
    user_dir = _setup_user_state_dir(tmp_path, monkeypatch, 4)
    older = user_dir / "older.json"
    newer = user_dir / "xiaoniu.json"
    older.write_text("{}", encoding="utf-8")
    os.utime(older, (1_000_000_000, 1_000_000_000))
    newer.write_text("{}", encoding="utf-8")
    os.utime(newer, (2_000_000_000, 2_000_000_000))

    monkeypatch.setattr(
        "src.services.process_service.find_task_by_name_sync",
        lambda *_args, **_kwargs: None,
    )

    service = ProcessService()
    assert service._resolve_cookie_path("task-a", 4) == str(newer)


def test_resolve_cookie_path_returns_none_without_any_state(monkeypatch, tmp_path):
    _setup_user_state_dir(tmp_path, monkeypatch, 4)
    monkeypatch.setattr(
        "src.services.process_service.find_task_by_name_sync",
        lambda *_args, **_kwargs: None,
    )

    service = ProcessService()
    assert service._resolve_cookie_path("task-a", 4) is None
