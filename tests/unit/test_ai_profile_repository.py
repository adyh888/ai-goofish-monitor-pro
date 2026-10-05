import pytest

from src.infrastructure.persistence.ai_profile_repository import (
    create_profile_sync,
    delete_profile_sync,
    get_profile_sync,
    list_enabled_profiles_active_first_sync,
    list_profiles_sync,
    move_profile_sync,
    set_active_profile_sync,
    set_profile_enabled_sync,
    update_profile_sync,
)


@pytest.fixture()
def profile_db(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATABASE_FILE", str(tmp_path / "profiles.sqlite3"))
    return tmp_path


def test_first_created_profile_becomes_active(profile_db):
    first = create_profile_sync(
        name="主模型", base_url="https://a.example.com", model_name="model-a", api_key="sk-a"
    )
    second = create_profile_sync(
        name="备用模型", base_url="https://b.example.com", model_name="model-b"
    )

    assert first.is_active is True
    assert second.is_active is False


def test_activate_switches_active_flag(profile_db):
    first = create_profile_sync(name="A", base_url="https://a.example.com", model_name="m-a")
    second = create_profile_sync(name="B", base_url="https://b.example.com", model_name="m-b")

    set_active_profile_sync(second.id)
    profiles = list_profiles_sync()
    by_id = {p.id: p for p in profiles}
    assert by_id[first.id].is_active is False
    assert by_id[second.id].is_active is True


def test_failover_order_puts_active_first(profile_db):
    first = create_profile_sync(name="A", base_url="https://a.example.com", model_name="m-a")
    second = create_profile_sync(name="B", base_url="https://b.example.com", model_name="m-b")
    third = create_profile_sync(name="C", base_url="https://c.example.com", model_name="m-c")

    set_active_profile_sync(third.id)
    order = [p.name for p in list_enabled_profiles_active_first_sync()]
    assert order == ["C", "A", "B"]


def test_disabling_active_profile_transfers_activation(profile_db):
    first = create_profile_sync(name="A", base_url="https://a.example.com", model_name="m-a")
    second = create_profile_sync(name="B", base_url="https://b.example.com", model_name="m-b")
    set_active_profile_sync(second.id)

    set_profile_enabled_sync(second.id, False)

    profiles = {p.name: p for p in list_profiles_sync()}
    assert profiles["B"].enabled is False
    assert profiles["B"].is_active is False
    assert profiles["A"].is_active is True


def test_move_swaps_priority(profile_db):
    first = create_profile_sync(name="A", base_url="https://a.example.com", model_name="m-a")
    create_profile_sync(name="B", base_url="https://b.example.com", model_name="m-b")

    move_profile_sync(first.id, "down")

    assert [p.name for p in list_profiles_sync()] == ["B", "A"]


def test_delete_active_profile_falls_back_to_next_enabled(profile_db):
    first = create_profile_sync(name="A", base_url="https://a.example.com", model_name="m-a")
    second = create_profile_sync(name="B", base_url="https://b.example.com", model_name="m-b")
    set_active_profile_sync(second.id)

    delete_profile_sync(second.id)

    profiles = list_profiles_sync()
    assert [p.name for p in profiles] == ["A"]
    assert profiles[0].is_active is True


def test_update_keeps_api_key_when_not_provided(profile_db):
    profile = create_profile_sync(
        name="A", base_url="https://a.example.com", model_name="m-a", api_key="sk-secret"
    )

    updated = update_profile_sync(profile.id, name="A2")

    assert updated.name == "A2"
    assert updated.api_key == "sk-secret"


def test_profile_roundtrip_keeps_user_id(profile_db):
    """回归：AiProfile 必须带 user_id，否则归属校验路由会 500。"""
    created = create_profile_sync(
        name="会员模型",
        base_url="https://api.example.com",
        model_name="model-a",
        api_key="sk-a",
        user_id=7,
    )
    assert created.user_id == 7

    fetched = get_profile_sync(created.id)
    assert fetched is not None
    assert fetched.user_id == 7

    owned = list_profiles_sync(7)
    assert [p.id for p in owned] == [created.id]
