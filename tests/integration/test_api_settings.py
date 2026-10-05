from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import dependencies as deps
from src.api.routes import settings
from src.infrastructure.config.env_manager import env_manager


_SETTINGS_ENV_KEYS = [
    "ACCOUNT_ROTATION_ENABLED",
    "ACCOUNT_ROTATION_MODE",
    "ACCOUNT_ROTATION_RETRY_LIMIT",
    "ACCOUNT_BLACKLIST_TTL",
    "ACCOUNT_STATE_DIR",
    "PROXY_ROTATION_ENABLED",
    "PROXY_ROTATION_MODE",
    "PROXY_POOL",
    "PROXY_ROTATION_RETRY_LIMIT",
    "PROXY_BLACKLIST_TTL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "OPENAI_MODEL_NAME",
    "SKIP_AI_ANALYSIS",
    "PROXY_URL",
    "NTFY_TOPIC_URL",
    "GOTIFY_URL",
    "GOTIFY_TOKEN",
    "BARK_URL",
    "WX_BOT_URL",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_API_BASE_URL",
    "WEBHOOK_URL",
    "WEBHOOK_METHOD",
    "WEBHOOK_HEADERS",
    "WEBHOOK_CONTENT_TYPE",
    "WEBHOOK_QUERY_PARAMETERS",
    "WEBHOOK_BODY",
    "PCURL_TO_MOBILE",
]


class _IdleProcessService:
    def __init__(self) -> None:
        self.processes = {}


def _fake_admin_user():
    from src.infrastructure.persistence.user_repository import User

    return User(
        id=1,
        username="test-admin",
        password_hash="x",
        role="admin",
        status="active",
        expired_at=None,
        created_at="2026-01-01T00:00:00",
        last_login_at=None,
    )


def _build_settings_client() -> TestClient:
    app = FastAPI()
    app.include_router(settings.router)
    app.dependency_overrides[deps.get_process_service] = _IdleProcessService
    app.dependency_overrides[deps.get_current_user] = _fake_admin_user
    return TestClient(app)


def _clear_settings_env(monkeypatch) -> None:
    for key in _SETTINGS_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_rotation_settings_include_account_rotation_fields(tmp_path, monkeypatch):
    _clear_settings_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "ACCOUNT_ROTATION_ENABLED=false",
                "ACCOUNT_ROTATION_MODE=per_task",
                "ACCOUNT_ROTATION_RETRY_LIMIT=2",
                "ACCOUNT_BLACKLIST_TTL=300",
                "ACCOUNT_STATE_DIR=state",
                "PROXY_ROTATION_ENABLED=false",
                "PROXY_ROTATION_MODE=per_task",
                "PROXY_ROTATION_RETRY_LIMIT=2",
                "PROXY_BLACKLIST_TTL=300",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(env_manager, "env_file", env_file)
    env_snapshot = env_file.read_text(encoding="utf-8")

    client = _build_settings_client()

    response = client.get("/api/settings/rotation")
    assert response.status_code == 200
    payload = response.json()
    # 多用户改造后：轮换配置按用户存取（DB），ACCOUNT_STATE_DIR 由后端强制按用户隔离
    assert payload["ACCOUNT_ROTATION_ENABLED"] is False
    assert payload["ACCOUNT_ROTATION_MODE"] == "per_task"
    assert payload["PROXY_POOL_SET"] is False

    update_response = client.put(
        "/api/settings/rotation",
        json={
            "ACCOUNT_ROTATION_ENABLED": True,
            "ACCOUNT_ROTATION_MODE": "on_failure",
            "ACCOUNT_ROTATION_RETRY_LIMIT": 4,
            "ACCOUNT_BLACKLIST_TTL": 900,
            "PROXY_POOL": "http://user-proxy.example.com:7890",
        },
    )
    assert update_response.status_code == 200

    # 轮换配置改为按用户落库，.env 不应被改动
    assert env_file.read_text(encoding="utf-8") == env_snapshot

    refreshed = client.get("/api/settings/rotation").json()
    assert refreshed["ACCOUNT_ROTATION_ENABLED"] is True
    assert refreshed["ACCOUNT_ROTATION_MODE"] == "on_failure"
    assert refreshed["ACCOUNT_ROTATION_RETRY_LIMIT"] == 4
    assert refreshed["ACCOUNT_BLACKLIST_TTL"] == 900
    assert refreshed["PROXY_POOL_SET"] is True
    assert refreshed["PROXY_POOL"] == ""  # 代理列表不回显


def test_notification_settings_redact_sensitive_values_and_expose_flags(tmp_path, monkeypatch):
    _clear_settings_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "NTFY_TOPIC_URL=https://ntfy.sh/demo-topic",
                "GOTIFY_URL=https://gotify.example.com",
                "GOTIFY_TOKEN=secret-token",
                "BARK_URL=https://api.day.app/private-key/",
                "WX_BOT_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=secret",
                "TELEGRAM_BOT_TOKEN=telegram-secret",
                "TELEGRAM_CHAT_ID=123456",
                "TELEGRAM_API_BASE_URL=https://tg.example.com/proxy",
                "WEBHOOK_URL=https://hooks.example.com/notify?token=secret",
                'WEBHOOK_HEADERS={"Authorization":"Bearer secret"}',
                'WEBHOOK_BODY={"message":"{{content}}"}',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(env_manager, "env_file", env_file)
    client = _build_settings_client()

    response = client.get("/api/settings/notifications")

    assert response.status_code == 200
    payload = response.json()
    assert payload["NTFY_TOPIC_URL"] == "https://ntfy.sh/demo-topic"
    assert payload["GOTIFY_URL"] == "https://gotify.example.com"
    assert payload["TELEGRAM_CHAT_ID"] == "123456"
    assert payload["TELEGRAM_API_BASE_URL"] == "https://tg.example.com/proxy"
    assert payload["BARK_URL"] == ""
    assert payload["WX_BOT_URL"] == ""
    assert payload["GOTIFY_TOKEN"] == ""
    assert payload["TELEGRAM_BOT_TOKEN"] == ""
    assert payload["WEBHOOK_URL"] == ""
    assert payload["WEBHOOK_HEADERS"] == ""
    assert payload["BARK_URL_SET"] is True
    assert payload["WX_BOT_URL_SET"] is True
    assert payload["GOTIFY_TOKEN_SET"] is True
    assert payload["TELEGRAM_BOT_TOKEN_SET"] is True
    assert payload["WEBHOOK_URL_SET"] is True
    assert payload["WEBHOOK_HEADERS_SET"] is True
    assert payload["WEBHOOK_BODY"] == '{"message":"{{content}}"}'


def test_update_notification_settings_rejects_invalid_channel_config(tmp_path, monkeypatch):
    _clear_settings_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(env_manager, "env_file", env_file)
    client = _build_settings_client()

    gotify_response = client.put(
        "/api/settings/notifications",
        json={"GOTIFY_URL": "https://gotify.example.com"},
    )
    assert gotify_response.status_code == 422
    assert "GOTIFY_TOKEN" in gotify_response.text

    telegram_proxy_response = client.put(
        "/api/settings/notifications",
        json={"TELEGRAM_API_BASE_URL": "not-a-url"},
    )
    assert telegram_proxy_response.status_code == 422
    assert "TELEGRAM_API_BASE_URL" in telegram_proxy_response.text

    webhook_response = client.put(
        "/api/settings/notifications",
        json={
            "WEBHOOK_URL": "https://hooks.example.com/notify",
            "WEBHOOK_METHOD": "POST",
            "WEBHOOK_CONTENT_TYPE": "JSON",
            "WEBHOOK_HEADERS": '{"Authorization": "Bearer secret"',
        },
    )
    assert webhook_response.status_code == 422
    assert "WEBHOOK_HEADERS" in webhook_response.text


def test_system_status_includes_notification_channel_flags(tmp_path, monkeypatch):
    _clear_settings_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "NTFY_TOPIC_URL=https://ntfy.sh/demo-topic",
                "GOTIFY_URL=https://gotify.example.com",
                "GOTIFY_TOKEN=secret-token",
                "BARK_URL=https://api.day.app/private-key/",
                "WX_BOT_URL=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=secret",
                "TELEGRAM_BOT_TOKEN=telegram-secret",
                "TELEGRAM_CHAT_ID=123456",
                "WEBHOOK_URL=https://hooks.example.com/notify",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(env_manager, "env_file", env_file)
    client = _build_settings_client()

    response = client.get("/api/settings/status")

    assert response.status_code == 200
    env_payload = response.json()["env_file"]
    assert env_payload["ntfy_topic_url_set"] is True
    assert env_payload["gotify_url_set"] is True
    assert env_payload["gotify_token_set"] is True
    assert env_payload["bark_url_set"] is True
    assert env_payload["wx_bot_url_set"] is True
    assert env_payload["telegram_bot_token_set"] is True
    assert env_payload["telegram_chat_id_set"] is True
    assert env_payload["webhook_url_set"] is True


def test_notification_test_endpoint_merges_stored_secret_values(tmp_path, monkeypatch):
    _clear_settings_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=stored-token",
                "TELEGRAM_CHAT_ID=10001",
                "TELEGRAM_API_BASE_URL=https://tg-proxy.example.com/base",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(env_manager, "env_file", env_file)
    client = _build_settings_client()

    captured = {}

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    def _fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        return _FakeResponse()

    monkeypatch.setattr("requests.post", _fake_post)

    response = client.post(
        "/api/settings/notifications/test",
        json={
            "channel": "telegram",
            "settings": {
                "TELEGRAM_CHAT_ID": "20002",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"]["telegram"]["success"] is True
    assert captured["url"] == "https://tg-proxy.example.com/base/botstored-token/sendMessage"
    assert captured["json"]["chat_id"] == "20002"


def test_notification_test_endpoint_ignores_other_channel_dirty_fields(tmp_path, monkeypatch):
    _clear_settings_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "NTFY_TOPIC_URL=https://ntfy.sh/demo-topic\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(env_manager, "env_file", env_file)
    client = _build_settings_client()

    captured = []

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

    def _fake_post(url, data=None, headers=None, timeout=None, **kwargs):
        captured.append({
            "url": url,
            "data": data,
            "headers": headers,
        })
        return _FakeResponse()

    monkeypatch.setattr("requests.post", _fake_post)

    response = client.post(
        "/api/settings/notifications/test",
        json={
            "channel": "ntfy",
            "settings": {
                "GOTIFY_URL": "not-a-url",
                "WEBHOOK_BODY": '{"message":"{{content}}"}',
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert list(payload["results"]) == ["ntfy"]
    assert payload["results"]["ntfy"]["success"] is True
    assert len(captured) == 1
    assert captured[0]["url"] == "https://ntfy.sh/demo-topic"


def test_ai_settings_fall_back_to_runtime_environment_when_env_file_missing(tmp_path, monkeypatch):
    _clear_settings_env(monkeypatch)
    env_file = tmp_path / ".env"
    monkeypatch.setattr(env_manager, "env_file", env_file)
    monkeypatch.setenv("OPENAI_API_KEY", "runtime-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://runtime.example.com/v1")
    monkeypatch.setenv("OPENAI_MODEL_NAME", "runtime-model")
    monkeypatch.setenv("PROXY_URL", "http://127.0.0.1:7890")
    client = _build_settings_client()

    ai_response = client.get("/api/settings/ai")
    assert ai_response.status_code == 200
    assert ai_response.json() == {
        "OPENAI_BASE_URL": "https://runtime.example.com/v1",
        "OPENAI_MODEL_NAME": "runtime-model",
        "SKIP_AI_ANALYSIS": False,
        "PROXY_URL": "http://127.0.0.1:7890",
    }

    status_response = client.get("/api/settings/status")
    assert status_response.status_code == 200
    env_payload = status_response.json()["env_file"]
    assert env_payload["exists"] is False
    assert env_payload["openai_api_key_set"] is True
    assert env_payload["openai_base_url_set"] is True
    assert env_payload["openai_model_name_set"] is True


def test_notification_settings_fall_back_to_runtime_environment_when_env_file_missing(
    tmp_path, monkeypatch
):
    _clear_settings_env(monkeypatch)
    env_file = tmp_path / ".env"
    monkeypatch.setattr(env_manager, "env_file", env_file)
    monkeypatch.setenv("NTFY_TOPIC_URL", "https://ntfy.sh/runtime-topic")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "runtime-telegram-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "20001")
    monkeypatch.setenv("TELEGRAM_API_BASE_URL", "https://runtime-tg-proxy.example.com")
    monkeypatch.setenv("BARK_URL", "https://api.day.app/runtime-secret/")
    client = _build_settings_client()

    response = client.get("/api/settings/notifications")

    assert response.status_code == 200
    payload = response.json()
    assert payload["NTFY_TOPIC_URL"] == "https://ntfy.sh/runtime-topic"
    assert payload["TELEGRAM_CHAT_ID"] == "20001"
    assert payload["TELEGRAM_API_BASE_URL"] == "https://runtime-tg-proxy.example.com"
    assert payload["BARK_URL"] == ""
    assert payload["BARK_URL_SET"] is True
    assert payload["TELEGRAM_BOT_TOKEN_SET"] is True
    assert sorted(payload["CONFIGURED_CHANNELS"]) == ["bark", "ntfy", "telegram"]


def test_ai_test_endpoint_falls_back_to_responses_when_chat_completions_api_404(
    tmp_path, monkeypatch
):
    _clear_settings_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")
    monkeypatch.setattr(env_manager, "env_file", env_file)
    client = _build_settings_client()
    request_history = []

    class _FakeOpenAI:
        def __init__(self, **_kwargs):
            self.responses = type(
                "_Responses",
                (),
                {"create": self._responses_create},
            )()
            self.chat = type(
                "_Chat",
                (),
                {
                    "completions": type(
                        "_Completions",
                        (),
                        {"create": self._chat_create},
                    )()
                },
            )()

        def _responses_create(self, **kwargs):
            request_history.append(("responses", kwargs))
            return type(
                "_Response",
                (),
                {"output_text": "OK"},
            )()

        def _chat_create(self, **kwargs):
            request_history.append(("chat", kwargs))
            raise Exception("Error code: 404 - page not found")

    import openai

    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)

    response = client.post(
        "/api/settings/ai/test",
        json={
            "OPENAI_API_KEY": "demo",
            "OPENAI_BASE_URL": "https://example.com/v1/",
            "OPENAI_MODEL_NAME": "demo-model",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["response"] == "OK"
    assert request_history[0][0] == "chat"
    assert request_history[0][1]["messages"][0]["content"] == settings.AI_TEST_PROMPT
    assert request_history[1][0] == "responses"
    assert request_history[1][1]["input"][0]["content"][0]["text"] == settings.AI_TEST_PROMPT


def _mock_transport(handler):
    import httpx

    return httpx.MockTransport(handler)


def test_fetch_model_ids_parses_openai_style_payload():
    import httpx

    from src.api.routes.settings import _fetch_model_ids

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        assert request.headers["Authorization"] == "Bearer sk-test"
        return httpx.Response(
            200,
            json={"object": "list", "data": [{"id": "model-b"}, {"id": "model-a"}]},
        )

    result = _fetch_model_ids(
        "https://api.example.com/v1", "sk-test", transport=_mock_transport(handler)
    )

    assert result == {"success": True, "models": ["model-a", "model-b"], "message": ""}


def test_fetch_model_ids_accepts_bare_list_and_name_fields():
    import httpx

    from src.api.routes.settings import _fetch_model_ids

    def handler(request):
        return httpx.Response(200, json=[{"name": "llama3"}, {"id": "qwen"}])

    result = _fetch_model_ids(
        "https://api.example.com", "k", transport=_mock_transport(handler)
    )

    assert result["success"] is True
    assert result["models"] == ["llama3", "qwen"]


def test_fetch_model_ids_translates_html_response_into_actionable_hint():
    """openai SDK 遇到 200+HTML 会抛出
    "'str' object has no attribute '_set_private_attributes'"，
    这里应返回可操作的提示（Base URL 填成了官网地址）。"""
    import httpx

    from src.api.routes.settings import _fetch_model_ids

    def handler(request):
        return httpx.Response(
            200,
            text="<!DOCTYPE html><html><body>index</body></html>",
            headers={"content-type": "text/html; charset=utf-8"},
        )

    result = _fetch_model_ids(
        "https://platform.example.com", "k", transport=_mock_transport(handler)
    )

    assert result["success"] is False
    assert "网页" in result["message"]
    assert "Base URL" in result["message"]


def test_fetch_model_ids_translates_http_error_statuses():
    import httpx

    from src.api.routes.settings import _fetch_model_ids

    cases = {
        401: "API Key 无效",
        404: "/models 接口",
        429: "限流",
        503: "HTTP 503",
    }
    for status, keyword in cases.items():
        result = _fetch_model_ids(
            "https://api.example.com/v1",
            "k",
            transport=_mock_transport(lambda request, s=status: httpx.Response(s)),
        )
        assert result["success"] is False
        assert keyword in result["message"]


def test_fetch_model_ids_translates_network_failures():
    import httpx

    from src.api.routes.settings import _fetch_model_ids

    def timeout_handler(request):
        raise httpx.ConnectTimeout("timed out")

    result = _fetch_model_ids(
        "https://api.example.com/v1", "k", transport=_mock_transport(timeout_handler)
    )
    assert result["success"] is False
    assert "超时" in result["message"]

    def connect_error_handler(request):
        raise httpx.ConnectError("connection refused")

    result = _fetch_model_ids(
        "https://api.example.com/v1", "k", transport=_mock_transport(connect_error_handler)
    )
    assert result["success"] is False
    assert "无法连接" in result["message"]


def test_list_ai_models_endpoint_passes_resolved_credentials(monkeypatch):
    from src.api.routes import settings as settings_routes

    captured = {}

    def fake_fetch(base_url, api_key, proxy_url=None, transport=None):
        captured.update(base_url=base_url, api_key=api_key, proxy_url=proxy_url)
        return {"success": True, "models": ["m1"], "message": ""}

    monkeypatch.setattr(settings_routes, "_fetch_model_ids", fake_fetch)

    client = _build_settings_client()
    response = client.post(
        "/api/settings/ai/models",
        json={
            "OPENAI_BASE_URL": "https://api.example.com/v1/",
            "OPENAI_API_KEY": "sk-live",
            "PROXY_URL": "",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"success": True, "models": ["m1"], "message": ""}
    assert captured["base_url"] == "https://api.example.com/v1/"
    assert captured["api_key"] == "sk-live"
    assert captured["proxy_url"] is None


def test_fetch_model_ids_detects_anthropic_protocol_endpoint():
    """DeepSeek /anthropic 是 Anthropic 协议专用端点（无 OpenAI /models），
    应探测 {base}/v1/models 并提示改用 OpenAI 兼容地址。"""
    import httpx

    from src.api.routes.settings import _fetch_model_ids

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/anthropic/models":
            return httpx.Response(404, json={"error": {"message": "not found"}})
        if request.url.path == "/anthropic/v1/models":
            assert request.headers["x-api-key"] == "sk-test"
            assert request.headers["anthropic-version"] == "2023-06-01"
            return httpx.Response(
                200,
                json={"data": [{"id": "deepseek-chat", "type": "model"}], "has_more": False},
            )
        return httpx.Response(404)

    result = _fetch_model_ids(
        "https://api.example.com/anthropic", "sk-test", transport=_mock_transport(handler)
    )

    assert result["success"] is False
    assert "Anthropic" in result["message"]
    assert "https://api.deepseek.com" in result["message"]


def test_fetch_model_ids_keeps_generic_404_hint_when_anthropic_probe_misses():
    import httpx

    from src.api.routes.settings import _fetch_model_ids

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": {"message": "not found"}})

    result = _fetch_model_ids(
        "https://api.example.com/v2", "sk-test", transport=_mock_transport(handler)
    )

    assert result["success"] is False
    assert "/models 接口" in result["message"]


def _fake_member_user():
    from src.infrastructure.persistence.user_repository import User

    return User(
        id=7,
        username="test-member",
        password_hash="x",
        role="user",
        status="active",
        expired_at=None,
        created_at="2026-01-01T00:00:00",
        last_login_at=None,
    )


def test_ai_profile_test_endpoint_does_not_500_for_member_owner(monkeypatch):
    """回归：AiProfile 缺 user_id 时，会员用户点「测试」等归属校验接口全部 500。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.api import dependencies as deps
    from src.api.routes import settings as settings_routes
    from src.infrastructure.persistence.ai_profile_repository import create_profile_sync

    profile = create_profile_sync(
        name="会员模型",
        base_url="https://api.example.com",
        model_name="deepseek-chat",
        api_key="sk-member",
        user_id=7,
    )

    app = FastAPI()
    app.include_router(settings_routes.router)
    app.dependency_overrides[deps.get_current_user] = _fake_member_user
    client = TestClient(app)

    class _FakeOpenAI:
        def __init__(self, **kwargs):
            assert kwargs["api_key"] == "sk-member"
            self.chat = type(
                "_Chat",
                (),
                {
                    "completions": type(
                        "_Completions",
                        (),
                        {
                            "create": lambda self, **kw: type(
                                "_Msg", (), {"choices": []}
                            )()
                        },
                    )()
                },
            )()

    import openai

    monkeypatch.setattr(openai, "OpenAI", _FakeOpenAI)

    response = client.post(f"/api/settings/ai/profiles/{profile.id}/test")

    assert response.status_code == 200
    payload = response.json()
    # 假客户端返回空 choices 会让 _perform_ai_test 报"空响应"之类业务失败，
    # 但关键是归属校验不再 500。
    assert payload["success"] is False
    assert "会员模型" in payload["message"]
