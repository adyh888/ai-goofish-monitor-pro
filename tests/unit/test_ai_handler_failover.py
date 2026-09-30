"""多模型 failover 逻辑测试。"""
import asyncio
import json
from types import SimpleNamespace

import pytest

import src.ai_handler as ai_handler
from src.infrastructure.persistence.ai_profile_repository import AiProfile


def _profile(pid: int, name: str, model_name: str) -> AiProfile:
    return AiProfile(
        id=pid,
        name=name,
        base_url=f"https://{name}.example.com",
        api_key=f"sk-{name}",
        model_name=model_name,
        proxy_url="",
        enabled=True,
        is_active=False,
        sort_order=pid,
    )


def _valid_response() -> SimpleNamespace:
    payload = {
        "prompt_version": "EagleEye-V6.4",
        "is_recommended": True,
        "reason": "ok",
        "risk_tags": [],
        "criteria_analysis": {"seller_type": {"status": "PASS"}},
    }
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
    )


@pytest.fixture()
def no_db_profiles(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DATABASE_FILE", str(tmp_path / "ai.sqlite3"))
    monkeypatch.setattr(ai_handler, "_load_enabled_profiles", lambda: [])


def test_failover_to_next_profile_on_error(monkeypatch, no_db_profiles):
    profile_a = _profile(1, "primary", "model-a")
    profile_b = _profile(2, "backup", "model-b")
    monkeypatch.setattr(ai_handler, "_load_enabled_profiles", lambda: [profile_a, profile_b])

    created_clients = []
    monkeypatch.setattr(
        ai_handler,
        "_build_profile_client",
        lambda p: created_clients.append(p.name) or SimpleNamespace(name=p.name),
    )

    activated = []

    def fake_activate(profile_id):
        activated.append(profile_id)
        return None

    import src.infrastructure.persistence.ai_profile_repository as repo

    monkeypatch.setattr(repo, "set_active_profile_sync", fake_activate)

    async def fake_create(client, api_mode, params):
        if getattr(client, "name", "") == "primary":
            raise RuntimeError("Insufficient Balance")
        return _valid_response()

    monkeypatch.setattr(ai_handler, "create_ai_response_async", fake_create)

    result = asyncio.run(
        ai_handler.get_ai_analysis(
            {"商品信息": {"商品ID": "1", "商品标题": "测试"}},
            image_paths=[],
            prompt_text="请输出JSON",
        )
    )

    assert result is not None
    assert result["is_recommended"] is True
    assert created_clients == ["primary", "backup"]
    assert activated == [profile_b.id]


def test_all_profiles_failed_raises(monkeypatch, no_db_profiles):
    profile_a = _profile(1, "primary", "model-a")
    monkeypatch.setattr(ai_handler, "_load_enabled_profiles", lambda: [profile_a])
    monkeypatch.setattr(
        ai_handler, "_build_profile_client", lambda p: SimpleNamespace(name=p.name)
    )

    async def fake_create(client, api_mode, params):
        raise RuntimeError("boom")

    monkeypatch.setattr(ai_handler, "create_ai_response_async", fake_create)

    with pytest.raises(RuntimeError):
        asyncio.run(
            ai_handler.get_ai_analysis(
                {"商品信息": {"商品ID": "1", "商品标题": "测试"}},
                image_paths=[],
                prompt_text="请输出JSON",
            )
        )


def test_legacy_env_path_used_when_no_profiles(monkeypatch, no_db_profiles):
    fake_client = SimpleNamespace(name="legacy")
    monkeypatch.setattr(ai_handler, "client", fake_client)
    monkeypatch.setattr(ai_handler, "MODEL_NAME", "legacy-model")

    seen = {}

    async def fake_create(client, api_mode, params):
        seen["model"] = params["model"]
        seen["client"] = client
        return _valid_response()

    monkeypatch.setattr(ai_handler, "create_ai_response_async", fake_create)

    result = asyncio.run(
        ai_handler.get_ai_analysis(
            {"商品信息": {"商品ID": "1", "商品标题": "测试"}},
            image_paths=[],
            prompt_text="请输出JSON",
        )
    )

    assert result is not None
    assert seen["model"] == "legacy-model"
    assert seen["client"] is fake_client
