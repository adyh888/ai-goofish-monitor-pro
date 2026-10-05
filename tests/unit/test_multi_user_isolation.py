"""多用户隔离专项测试：任务归属、AI 配置隔离、结果隔离、会员暂停/恢复。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import dependencies as deps
from src.infrastructure.persistence.user_repository import (
    create_user_sync,
    get_user_by_username_sync,
    update_user_sync,
)
from src.services.auth_service import activate_card_for_user
from src.services.membership_service import (
    apply_membership_state,
    pause_expired_user_tasks,
)
from src.services.security import hash_password
from tests.conftest import _make_test_admin


@pytest.fixture()
def multi_client(api_context):
    """api_context 之上加可切换的当前用户（默认 admin）。"""
    from fastapi.testclient import TestClient

    holder = {"user": _make_test_admin()}

    def override_current_user():
        return holder["user"]

    api_context["app"].dependency_overrides[deps.get_current_user] = override_current_user
    # 让任务服务与模块级查询（find_task_by_id_sync / 会员联动）落在同一个隔离库
    from src.infrastructure.persistence.sqlite_task_repository import SqliteTaskRepository
    from src.services.task_service import TaskService

    default_repo = SqliteTaskRepository(legacy_config_file=None)
    api_context["app"].dependency_overrides[deps.get_task_service] = (
        lambda: TaskService(default_repo)
    )
    api_context["user_holder"] = holder
    api_context["client"] = TestClient(api_context["app"])
    return api_context


def _as(client: TestClient, holder: dict, username: str) -> None:
    user = get_user_by_username_sync(username)
    assert user is not None
    holder["user"] = user


def _auth(username: str, password: str = "pass123"):
    from src.services.auth_service import authenticate
    from src.services.security import create_access_token

    user = authenticate(username, password)
    return {"Authorization": f"Bearer {create_access_token(user.id, user.username, user.role)}"}


class TestTaskOwnership:
    def test_user_cannot_see_or_mutate_others_task(self, multi_client):
        holder = multi_client["user_holder"]
        client: TestClient = multi_client["client"]

        alice = create_user_sync(username="alice_t", password="pass123")
        bob = create_user_sync(username="bob_t", password="pass123")

        # alice 创建任务
        holder["user"] = alice
        create = client.post(
            "/api/tasks/",
            json={
                "task_name": "Alice Task",
                "keyword": "alice-keyword",
                "description": "需求",
                "max_pages": 1,
                "personal_only": True,
                "decision_mode": "keyword",
                "keyword_rules": ["ps5"],
            },
        )
        assert create.status_code == 200, create.text
        task_id = create.json()["task"]["id"]

        # bob 看不到
        holder["user"] = bob
        assert client.get("/api/tasks").json() == []
        assert client.get(f"/api/tasks/{task_id}").status_code == 404
        assert client.post(f"/api/tasks/start/{task_id}").status_code == 404
        assert client.patch(f"/api/tasks/{task_id}", json={"enabled": False}).status_code == 404
        assert client.delete(f"/api/tasks/{task_id}").status_code == 404

        # admin 可见全部
        holder["user"] = _make_test_admin()
        all_tasks = client.get("/api/tasks").json()
        assert any(t["id"] == task_id for t in all_tasks)

    def test_created_task_stores_owner(self, multi_client):
        holder = multi_client["user_holder"]
        client: TestClient = multi_client["client"]
        alice = create_user_sync(username="alice_o", password="pass123")
        holder["user"] = alice
        create = client.post(
            "/api/tasks/",
            json={
                "task_name": "Owner Task",
                "keyword": "owner-keyword",
                "decision_mode": "keyword",
                "keyword_rules": ["switch"],
            },
        )
        assert create.status_code == 200, create.text
        from src.infrastructure.persistence.sqlite_task_repository import (
            find_task_by_id_sync,
        )

        task = find_task_by_id_sync(create.json()["task"]["id"])
        assert task.user_id == alice.id


class TestMembershipPause:
    def test_expired_user_tasks_pause_and_resume(self, multi_client):
        holder = multi_client["user_holder"]
        client: TestClient = multi_client["client"]
        carol = create_user_sync(username="carol_m", password="pass123")

        holder["user"] = carol
        create = client.post(
            "/api/tasks/",
            json={
                "task_name": "Carol Task",
                "keyword": "carol-keyword",
                "decision_mode": "keyword",
                "keyword_rules": ["ipad"],
            },
        )
        assert create.status_code == 200, create.text
        task_id = create.json()["task"]["id"]

        from src.infrastructure.persistence.sqlite_task_repository import (
            find_task_by_id_sync,
        )

        # 会员过期 → 扫描暂停
        update_user_sync(carol.id, expired_at="2020-01-01T00:00:00+00:00")
        assert pause_expired_user_tasks() == [carol.id]
        task = find_task_by_id_sync(task_id)
        assert task.enabled is False
        assert task.paused_by_membership is True

        # 激活卡密 → 自动恢复
        from src.infrastructure.persistence.card_key_repository import (
            generate_cards_sync,
        )

        code = generate_cards_sync(count=1, duration_days=30)[0].code
        renewed, _ = activate_card_for_user(carol, code)
        assert apply_membership_state(carol.id) == "resumed"
        task = find_task_by_id_sync(task_id)
        assert task.enabled is True
        assert task.paused_by_membership is False

    def test_paused_task_cannot_be_started_while_expired(self, multi_client):
        holder = multi_client["user_holder"]
        client: TestClient = multi_client["client"]
        dave = create_user_sync(username="dave_m", password="pass123")
        update_user_sync(dave.id, expired_at="2020-01-01T00:00:00+00:00")
        holder["user"] = dave
        create = client.post(
            "/api/tasks/",
            json={
                "task_name": "Dave Task",
                "keyword": "dave-keyword",
                "decision_mode": "keyword",
                "keyword_rules": ["camera"],
            },
        )
        assert create.status_code == 200, create.text


class TestAiProfileIsolation:
    def test_profiles_scoped_per_user(self, multi_client):
        holder = multi_client["user_holder"]
        client: TestClient = multi_client["client"]
        from fastapi import FastAPI

        from src.api.routes import settings as settings_routes

        app: FastAPI = multi_client["app"]
        route_paths = {
            getattr(r, "path", "") for r in app.routes
        }
        if "/api/settings/ai/profiles" not in route_paths:
            app.include_router(settings_routes.router)

        from src.infrastructure.persistence.ai_profile_repository import (
            create_profile_sync,
            list_profiles_sync,
        )

        alice = create_user_sync(username="alice_ai", password="pass123")
        bob = create_user_sync(username="bob_ai", password="pass123")

        create_profile_sync(
            name="alice-model",
            base_url="https://api.deepseek.com/v1",
            model_name="deepseek-chat",
            api_key="alice-key",
            user_id=alice.id,
        )
        create_profile_sync(
            name="bob-model",
            base_url="https://api.deepseek.com/v1",
            model_name="deepseek-chat",
            api_key="bob-key",
            user_id=bob.id,
        )

        assert [p.name for p in list_profiles_sync(alice.id)] == ["alice-model"]
        assert [p.name for p in list_profiles_sync(bob.id)] == ["bob-model"]

        # API 层：alice 只看到自己的配置
        holder["user"] = alice
        payload = client.get("/api/settings/ai/profiles").json()
        assert [p["name"] for p in payload["profiles"]] == ["alice-model"]
        assert payload["profiles"][0]["has_api_key"] is True
        assert "alice-key" not in str(payload)  # Key 永不回显


class TestResultIsolation:
    def test_same_keyword_two_users_no_collision(self, multi_client):
        from src.services.result_storage_service import (
            load_processed_link_keys,
            save_result_record,
        )

        record = {
            "爬取时间": "2026-01-01T10:00:00",
            "搜索关键字": "shared keyword",
            "任务名称": "Shared",
            "商品信息": {
                "商品ID": "1",
                "商品标题": "Same Item",
                "商品链接": "https://www.goofish.com/item?id=1",
                "当前售价": "¥100",
            },
        }
        import asyncio

        assert asyncio.run(save_result_record(dict(record), "shared keyword", user_id=2))
        assert asyncio.run(save_result_record(dict(record), "shared keyword", user_id=3))

        keys_u2 = load_processed_link_keys("shared keyword", 2)
        keys_u3 = load_processed_link_keys("shared keyword", 3)
        assert keys_u2 == keys_u3 and len(keys_u2) == 1


class TestNotificationIsolation:
    def test_notification_config_scoped_per_user(self):
        from src.services.notification_config_service import (
            load_notification_settings,
            save_notification_settings_for_user,
        )

        alice = create_user_sync(username="alice_n", password="pass123")
        bob = create_user_sync(username="bob_n", password="pass123")

        settings = load_notification_settings(alice.id)
        settings.bark_url = "https://api.day.app/alice-key/"
        save_notification_settings_for_user(alice.id, settings)

        assert load_notification_settings(alice.id).bark_url
        assert load_notification_settings(bob.id).bark_url is None


class TestLoginStateIsolation:
    """回归：API 进程未注入 SPIDER_USER_ID 时，普通用户的登录态/账号
    必须写入自己的 u{uid} 目录，而不是恒落到 u1（曾导致任务启动时报
    “未找到可用的登录状态文件”并被失败保护暂停）。"""

    def test_user_state_helpers_prefer_explicit_user_id(self, tmp_path, monkeypatch):
        from src.utils import get_user_state_dir, get_user_state_file

        monkeypatch.setenv("ACCOUNT_STATE_DIR", str(tmp_path / "state"))
        monkeypatch.setenv("SPIDER_USER_ID", "9")

        assert get_user_state_dir(2) == str(tmp_path / "state" / "u2")
        assert get_user_state_file(2) == str(tmp_path / "state" / "u2" / "xianyu_state.json")
        # 爬虫子进程（未显式传 user_id）仍按 SPIDER_USER_ID 解析
        assert get_user_state_dir().endswith("u9")

    def test_accounts_and_login_state_scoped_per_user(self, multi_client, tmp_path, monkeypatch):
        monkeypatch.setenv("ACCOUNT_STATE_DIR", str(tmp_path / "state"))
        monkeypatch.delenv("SPIDER_USER_ID", raising=False)

        from fastapi import FastAPI

        from src.api.routes import accounts as accounts_routes
        from src.api.routes import login_state as login_state_routes

        app: FastAPI = multi_client["app"]
        route_paths = {getattr(r, "path", "") for r in app.routes}
        if "/api/accounts" not in route_paths:
            app.include_router(accounts_routes.router)
        if "/api/login-state" not in route_paths:
            app.include_router(login_state_routes.router)

        holder = multi_client["user_holder"]
        client: TestClient = multi_client["client"]

        alice = create_user_sync(username="alice_s", password="pass123")
        holder["user"] = alice

        resp = client.post("/api/accounts", json={"name": "shop1", "content": '{"cookies": []}'})
        assert resp.status_code == 200, resp.text
        resp = client.post("/api/login-state", json={"content": '{"cookies": []}'})
        assert resp.status_code == 200, resp.text

        state_dir = tmp_path / "state" / f"u{alice.id}"
        assert (state_dir / "shop1.json").exists()
        assert (state_dir / "xianyu_state.json").exists()
        # 只写入 alice 自己的目录，不污染其他用户目录
        created = {p.name for p in (tmp_path / "state").iterdir()}
        assert created == {f"u{alice.id}"}


class TestTaskNameUniqueness:
    """同用户任务名唯一：同名任务会让爬虫子进程按名匹配时串配置。"""

    def _payload(self, name: str) -> dict:
        return {
            "task_name": name,
            "keyword": "some-keyword",
            "decision_mode": "keyword",
            "keyword_rules": ["kw"],
        }

    def test_same_user_duplicate_name_rejected(self, multi_client):
        holder = multi_client["user_holder"]
        client: TestClient = multi_client["client"]
        alice = create_user_sync(username="alice_n", password="pass123")
        holder["user"] = alice

        first = client.post("/api/tasks/", json=self._payload("Dup Task"))
        assert first.status_code == 200, first.text

        dup = client.post("/api/tasks/", json=self._payload("Dup Task"))
        assert dup.status_code == 400
        assert "同名" in dup.json()["detail"]

    def test_different_users_same_name_allowed(self, multi_client):
        holder = multi_client["user_holder"]
        client: TestClient = multi_client["client"]
        alice = create_user_sync(username="alice_dn", password="pass123")
        bob = create_user_sync(username="bob_dn", password="pass123")

        holder["user"] = alice
        assert client.post("/api/tasks/", json=self._payload("Shared Name")).status_code == 200
        holder["user"] = bob
        assert client.post("/api/tasks/", json=self._payload("Shared Name")).status_code == 200

    def test_rename_collision_rejected(self, multi_client):
        holder = multi_client["user_holder"]
        client: TestClient = multi_client["client"]
        alice = create_user_sync(username="alice_r", password="pass123")
        holder["user"] = alice

        first = client.post("/api/tasks/", json=self._payload("Task A"))
        assert first.status_code == 200, first.text
        second = client.post("/api/tasks/", json=self._payload("Task B"))
        assert second.status_code == 200, second.text
        task_b_id = second.json()["task"]["id"]

        renamed = client.patch(f"/api/tasks/{task_b_id}", json={"task_name": "Task A"})
        assert renamed.status_code == 400
        assert "同名" in renamed.json()["detail"]

        # 改回自己的名字不受影响（排除自身）
        keep = client.patch(f"/api/tasks/{task_b_id}", json={"task_name": "Task B"})
        assert keep.status_code == 200, keep.text
