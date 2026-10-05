"""认证与会员体系测试：注册/登录/JWT/卡密激活/管理端。"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.routes import admin as admin_routes
from src.api.routes import auth as auth_routes
from src.infrastructure.persistence.card_key_repository import (
    generate_cards_sync,
    get_card_by_code_sync,
    set_card_status_sync,
)
from src.infrastructure.persistence.user_repository import (
    ensure_bootstrap_admin_sync,
    get_user_by_username_sync,
)
from src.services.auth_service import register_user


@pytest.fixture()
def auth_client():
    # 不走 ensure_bootstrap_admin_sync（它读取模块导入时缓存的 .env 凭据），
    # 直接显式创建测试管理员，保证凭据可控。
    from src.infrastructure.persistence.user_repository import (
        UsernameTakenError,
        create_user_sync,
    )

    try:
        create_user_sync(username="root", password="rootpass123", role="admin")
    except UsernameTakenError:
        pass

    app = FastAPI()
    app.include_router(auth_routes.router)
    app.include_router(admin_routes.router)
    return TestClient(app)


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestRegistrationAndLogin:
    def test_register_returns_token_and_inactive_membership(self, auth_client):
        response = auth_client.post(
            "/api/auth/register", json={"username": "alice", "password": "pass123"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["token"]
        assert body["user"]["username"] == "alice"
        assert body["user"]["membership_active"] is False
        assert body["user"]["remaining_days"] == 0

    def test_register_rejects_invalid_username(self, auth_client):
        response = auth_client.post(
            "/api/auth/register", json={"username": "a", "password": "pass123"}
        )
        assert response.status_code == 400

    def test_register_rejects_duplicate(self, auth_client):
        register_user("bob", "pass123")
        response = auth_client.post(
            "/api/auth/register", json={"username": "bob", "password": "pass123"}
        )
        assert response.status_code == 400

    def test_login_success_and_failure(self, auth_client):
        register_user("carol", "pass123")
        ok = auth_client.post(
            "/api/auth/login", json={"username": "carol", "password": "pass123"}
        )
        assert ok.status_code == 200
        assert ok.json()["token"]

        bad = auth_client.post(
            "/api/auth/login", json={"username": "carol", "password": "wrong!"}
        )
        assert bad.status_code == 401

    def test_me_requires_token(self, auth_client):
        assert auth_client.get("/api/auth/me").status_code == 401

    def test_me_returns_payload(self, auth_client):
        token = auth_client.post(
            "/api/auth/login", json={"username": "root", "password": "rootpass123"}
        ).json()["token"]
        me = auth_client.get("/api/auth/me", headers=_auth_header(token))
        assert me.status_code == 200
        assert me.json()["role"] == "admin"
        assert me.json()["membership_active"] is True

    def test_invalid_token_rejected(self, auth_client):
        response = auth_client.get(
            "/api/auth/me", headers=_auth_header("not-a-jwt")
        )
        assert response.status_code == 401


class TestCardActivation:
    def test_activate_extends_membership(self, auth_client):
        register_user("dave", "pass123")
        token = auth_client.post(
            "/api/auth/login", json={"username": "dave", "password": "pass123"}
        ).json()["token"]
        code = generate_cards_sync(count=1, duration_days=30, batch_no="T1")[0].code

        response = auth_client.post(
            "/api/auth/activate-card", json={"code": code}, headers=_auth_header(token)
        )
        assert response.status_code == 200
        body = response.json()
        assert body["activated_days"] == 30
        assert body["user"]["membership_active"] is True
        assert body["user"]["remaining_days"] == 30

    def test_activate_renewal_stacks_on_current_expiry(self, auth_client):
        user = register_user("erin", "pass123")
        first, second = generate_cards_sync(count=2, duration_days=30, batch_no="T1")
        updated, _ = activate_via_service(user, first.code)
        renewed, _ = activate_via_service(updated, second.code)
        from src.services.security import parse_iso_datetime

        first_expiry = parse_iso_datetime(updated.expired_at)
        second_expiry = parse_iso_datetime(renewed.expired_at)
        assert (second_expiry - first_expiry).days == 30

    def test_card_single_use(self, auth_client):
        register_user("frank", "pass123")
        token = auth_client.post(
            "/api/auth/login", json={"username": "frank", "password": "pass123"}
        ).json()["token"]
        code = generate_cards_sync(count=1, duration_days=7)[0].code

        first = auth_client.post(
            "/api/auth/activate-card", json={"code": code}, headers=_auth_header(token)
        )
        assert first.status_code == 200
        again = auth_client.post(
            "/api/auth/activate-card", json={"code": code}, headers=_auth_header(token)
        )
        assert again.status_code == 400
        assert "卡密无效或已被使用" in again.json()["detail"]

    def test_unknown_card_rejected_without_leaking_existence(self, auth_client):
        register_user("grace", "pass123")
        token = auth_client.post(
            "/api/auth/login", json={"username": "grace", "password": "pass123"}
        ).json()["token"]
        response = auth_client.post(
            "/api/auth/activate-card",
            json={"code": "XYG-AAAA-BBBB-CCCC"},
            headers=_auth_header(token),
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "卡密无效或已被使用"

    def test_disabled_card_rejected(self, auth_client):
        register_user("heidi", "pass123")
        token = auth_client.post(
            "/api/auth/login", json={"username": "heidi", "password": "pass123"}
        ).json()["token"]
        card = generate_cards_sync(count=1, duration_days=7)[0]
        set_card_status_sync(card.id, "disabled")

        response = auth_client.post(
            "/api/auth/activate-card",
            json={"code": card.code},
            headers=_auth_header(token),
        )
        assert response.status_code == 400


def activate_via_service(user, code):
    from src.services.auth_service import activate_card_for_user

    return activate_card_for_user(user, code)


class TestAdminApi:
    def test_admin_routes_require_admin_role(self, auth_client):
        token = auth_client.post(
            "/api/auth/register", json={"username": "mallory", "password": "pass123"}
        ).json()["token"]
        assert (
            auth_client.get("/api/admin/users", headers=_auth_header(token)).status_code
            == 403
        )
        assert (
            auth_client.post(
                "/api/admin/cards/generate",
                json={"count": 1, "duration_days": 30},
                headers=_auth_header(token),
            ).status_code
            == 403
        )

    def test_generate_and_export_cards(self, auth_client):
        admin_token = auth_client.post(
            "/api/auth/login", json={"username": "root", "password": "rootpass123"}
        ).json()["token"]
        headers = _auth_header(admin_token)

        generated = auth_client.post(
            "/api/admin/cards/generate",
            json={"count": 3, "duration_days": 90, "batch_no": "B90", "note": "首发"},
            headers=headers,
        )
        assert generated.status_code == 200
        codes = generated.json()["codes"]
        assert len(codes) == 3
        assert all(code.startswith("XYG-") for code in codes)

        summary = auth_client.get("/api/admin/cards/summary", headers=headers).json()
        assert summary["unused"] == 3

        exported = auth_client.get(
            "/api/admin/cards/export", headers=headers
        ).text.splitlines()
        assert sorted(exported) == sorted(codes)

    def test_disable_unused_card_only(self, auth_client):
        admin_token = auth_client.post(
            "/api/auth/login", json={"username": "root", "password": "rootpass123"}
        ).json()["token"]
        headers = _auth_header(admin_token)
        card = generate_cards_sync(count=1, duration_days=30)[0]

        disabled = auth_client.post(
            f"/api/admin/cards/{card.id}/status",
            json={"status": "disabled"},
            headers=headers,
        )
        assert disabled.status_code == 200
        assert get_card_by_code_sync(card.code).status == "disabled"

    def test_generate_rejects_bad_count(self, auth_client):
        admin_token = auth_client.post(
            "/api/auth/login", json={"username": "root", "password": "rootpass123"}
        ).json()["token"]
        response = auth_client.post(
            "/api/admin/cards/generate",
            json={"count": 0, "duration_days": 30},
            headers=_auth_header(admin_token),
        )
        assert response.status_code == 400

    def test_adjust_user_expiry_and_disable(self, auth_client):
        admin_token = auth_client.post(
            "/api/auth/login", json={"username": "root", "password": "rootpass123"}
        ).json()["token"]
        headers = _auth_header(admin_token)
        register_user("nick", "pass123")
        target = get_user_by_username_sync("nick")

        cleared = auth_client.put(
            f"/api/admin/users/{target.id}/expiry",
            json={"expired_at": None},
            headers=headers,
        )
        assert cleared.status_code == 200
        assert cleared.json()["membership_active"] is False

        future = "2030-01-01T00:00:00+00:00"
        granted = auth_client.put(
            f"/api/admin/users/{target.id}/expiry",
            json={"expired_at": future},
            headers=headers,
        )
        assert granted.status_code == 200
        assert granted.json()["membership_active"] is True

        disabled = auth_client.put(
            f"/api/admin/users/{target.id}/status",
            json={"status": "disabled"},
            headers=headers,
        )
        assert disabled.status_code == 200

    def test_admin_cannot_disable_self(self, auth_client):
        admin_token = auth_client.post(
            "/api/auth/login", json={"username": "root", "password": "rootpass123"}
        ).json()["token"]
        me = auth_client.get("/api/auth/me", headers=_auth_header(admin_token)).json()
        response = auth_client.put(
            f"/api/admin/users/{me['id']}/status",
            json={"status": "disabled"},
            headers=_auth_header(admin_token),
        )
        assert response.status_code == 400

    def test_overview_counts(self, auth_client):
        admin_token = auth_client.post(
            "/api/auth/login", json={"username": "root", "password": "rootpass123"}
        ).json()["token"]
        register_user("olivia", "pass123")
        generate_cards_sync(count=2, duration_days=30)
        overview = auth_client.get(
            "/api/admin/overview", headers=_auth_header(admin_token)
        ).json()
        assert overview["cards_unused"] == 2
        assert overview["total_users"] == 2  # root + olivia（每测试独立数据库）
        assert overview["active_members"] == 1  # 仅 root（admin）
