"""
设置管理路由
"""
import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.dependencies import get_process_service
from src.infrastructure.config.env_manager import env_manager
from src.infrastructure.config.settings import (
    AISettings,
    reload_settings,
    scraper_settings,
)
from src.services.ai_request_compat import (
    CHAT_COMPLETIONS_API_MODE,
    RESPONSES_API_MODE,
    build_ai_request_params,
    create_ai_response_sync,
    is_chat_completions_api_unsupported_error,
    is_responses_api_unsupported_error,
)
from src.services.ai_response_parser import extract_ai_response_content
from src.services.notification_config_service import (
    NotificationSettingsValidationError,
    build_configured_channels,
    build_notification_settings_response,
    build_notification_status_flags,
    load_notification_settings,
    model_dump,
    prepare_notification_test_settings,
    prepare_notification_settings_update,
)
from src.services.notification_service import build_notification_service
from src.services.process_service import ProcessService


router = APIRouter(prefix="/api/settings", tags=["settings"])
AI_TEST_PROMPT = "Reply with OK only."
AI_TEST_MAX_OUTPUT_TOKENS = 32


def _reload_env() -> None:
    load_dotenv(dotenv_path=env_manager.env_file, override=True)
    reload_settings()


def _env_bool(key: str, default: bool = False) -> bool:
    value = env_manager.get_value(key)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(key: str, default: int) -> int:
    value = env_manager.get_value(key)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _normalize_bool_value(value: bool) -> str:
    return "true" if value else "false"


class NotificationSettingsModel(BaseModel):
    """通知设置模型"""

    NTFY_TOPIC_URL: Optional[str] = None
    GOTIFY_URL: Optional[str] = None
    GOTIFY_TOKEN: Optional[str] = None
    BARK_URL: Optional[str] = None
    WX_BOT_URL: Optional[str] = None
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    TELEGRAM_CHAT_ID: Optional[str] = None
    TELEGRAM_API_BASE_URL: Optional[str] = None
    WEBHOOK_URL: Optional[str] = None
    WEBHOOK_METHOD: Optional[str] = None
    WEBHOOK_HEADERS: Optional[str] = None
    WEBHOOK_CONTENT_TYPE: Optional[str] = None
    WEBHOOK_QUERY_PARAMETERS: Optional[str] = None
    WEBHOOK_BODY: Optional[str] = None
    PCURL_TO_MOBILE: Optional[bool] = None


class NotificationTestRequest(BaseModel):
    """通知测试请求"""

    channel: Optional[str] = None
    settings: NotificationSettingsModel = Field(default_factory=NotificationSettingsModel)


class AISettingsModel(BaseModel):
    """AI设置模型"""

    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: Optional[str] = None
    OPENAI_MODEL_NAME: Optional[str] = None
    SKIP_AI_ANALYSIS: Optional[bool] = None
    PROXY_URL: Optional[str] = None


class RotationSettingsModel(BaseModel):
    ACCOUNT_ROTATION_ENABLED: Optional[bool] = None
    ACCOUNT_ROTATION_MODE: Optional[str] = None
    ACCOUNT_ROTATION_RETRY_LIMIT: Optional[int] = None
    ACCOUNT_BLACKLIST_TTL: Optional[int] = None
    ACCOUNT_STATE_DIR: Optional[str] = None
    PROXY_ROTATION_ENABLED: Optional[bool] = None
    PROXY_ROTATION_MODE: Optional[str] = None
    PROXY_POOL: Optional[str] = None
    PROXY_ROTATION_RETRY_LIMIT: Optional[int] = None
    PROXY_BLACKLIST_TTL: Optional[int] = None


@router.get("/notifications")
async def get_notification_settings():
    return build_notification_settings_response(load_notification_settings())


@router.put("/notifications")
async def update_notification_settings(settings: NotificationSettingsModel):
    try:
        updates, deletions, merged_settings = prepare_notification_settings_update(
            model_dump(settings, exclude_unset=True),
            load_notification_settings(),
        )
    except NotificationSettingsValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    success = env_manager.apply_changes(updates=updates, deletions=deletions)
    if not success:
        raise HTTPException(status_code=500, detail="更新通知设置失败")

    _reload_env()
    return {
        "message": "通知设置已成功更新",
        "configured_channels": build_configured_channels(merged_settings),
    }


@router.post("/notifications/test")
async def test_notification_settings(payload: NotificationTestRequest):
    try:
        merged_settings = prepare_notification_test_settings(
            model_dump(payload.settings, exclude_unset=True),
            load_notification_settings(),
            channel=payload.channel,
        )
    except NotificationSettingsValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    service = build_notification_service(merged_settings)
    if not service.clients:
        if payload.channel:
            raise HTTPException(
                status_code=422,
                detail=f"渠道 {payload.channel} 未配置或不受支持",
            )
        raise HTTPException(status_code=422, detail="请至少配置一个可用的通知渠道")

    results = await service.send_test_notification()
    if payload.channel:
        if payload.channel not in results:
            raise HTTPException(
                status_code=422,
                detail=f"渠道 {payload.channel} 未配置或不受支持",
            )
        results = {payload.channel: results[payload.channel]}

    return {
        "message": "测试通知已执行",
        "results": results,
    }


@router.get("/rotation")
async def get_rotation_settings():
    return {
        "ACCOUNT_ROTATION_ENABLED": _env_bool("ACCOUNT_ROTATION_ENABLED", False),
        "ACCOUNT_ROTATION_MODE": env_manager.get_value("ACCOUNT_ROTATION_MODE", "per_task"),
        "ACCOUNT_ROTATION_RETRY_LIMIT": _env_int("ACCOUNT_ROTATION_RETRY_LIMIT", 2),
        "ACCOUNT_BLACKLIST_TTL": _env_int("ACCOUNT_BLACKLIST_TTL", 300),
        "ACCOUNT_STATE_DIR": env_manager.get_value("ACCOUNT_STATE_DIR", "state"),
        "PROXY_ROTATION_ENABLED": _env_bool("PROXY_ROTATION_ENABLED", False),
        "PROXY_ROTATION_MODE": env_manager.get_value("PROXY_ROTATION_MODE", "per_task"),
        "PROXY_POOL": env_manager.get_value("PROXY_POOL", ""),
        "PROXY_ROTATION_RETRY_LIMIT": _env_int("PROXY_ROTATION_RETRY_LIMIT", 2),
        "PROXY_BLACKLIST_TTL": _env_int("PROXY_BLACKLIST_TTL", 300),
    }


@router.put("/rotation")
async def update_rotation_settings(settings: RotationSettingsModel):
    updates = {}
    payload = model_dump(settings, exclude_unset=True)
    for key, value in payload.items():
        if isinstance(value, bool):
            updates[key] = _normalize_bool_value(value)
        else:
            updates[key] = str(value)
    success = env_manager.update_values(updates)
    if not success:
        raise HTTPException(status_code=500, detail="更新轮换设置失败")
    _reload_env()
    return {"message": "轮换设置已成功更新"}


@router.get("/status")
async def get_system_status(
    process_service: ProcessService = Depends(get_process_service),
):
    state_file = "xianyu_state.json"
    login_state_exists = os.path.exists(state_file)
    env_file_exists = os.path.exists(env_manager.env_file)
    openai_api_key = env_manager.get_value("OPENAI_API_KEY", "")
    openai_base_url = env_manager.get_value("OPENAI_BASE_URL", "")
    openai_model_name = env_manager.get_value("OPENAI_MODEL_NAME", "")
    ai_settings = AISettings()
    notification_settings = load_notification_settings()
    running_task_ids = [
        task_id
        for task_id, process in process_service.processes.items()
        if process and process.returncode is None
    ]

    return {
        "ai_configured": ai_settings.is_configured(),
        "notification_configured": notification_settings.has_any_notification_enabled(),
        "headless_mode": scraper_settings.run_headless,
        "running_in_docker": scraper_settings.running_in_docker,
        "scraper_running": len(running_task_ids) > 0,
        "running_task_ids": running_task_ids,
        "login_state_file": {
            "exists": login_state_exists,
            "path": state_file,
        },
        "env_file": {
            "exists": env_file_exists,
            "openai_api_key_set": bool(openai_api_key),
            "openai_base_url_set": bool(openai_base_url),
            "openai_model_name_set": bool(openai_model_name),
            **build_notification_status_flags(notification_settings),
        },
        "configured_notification_channels": build_configured_channels(notification_settings),
    }


@router.get("/ai")
async def get_ai_settings():
    return {
        "OPENAI_BASE_URL": env_manager.get_value("OPENAI_BASE_URL", ""),
        "OPENAI_MODEL_NAME": env_manager.get_value("OPENAI_MODEL_NAME", ""),
        "SKIP_AI_ANALYSIS": env_manager.get_value("SKIP_AI_ANALYSIS", "false").lower() == "true",
        "PROXY_URL": env_manager.get_value("PROXY_URL", ""),
    }


@router.put("/ai")
async def update_ai_settings(settings: AISettingsModel):
    updates = {}
    if settings.OPENAI_API_KEY is not None:
        updates["OPENAI_API_KEY"] = settings.OPENAI_API_KEY
    if settings.OPENAI_BASE_URL is not None:
        updates["OPENAI_BASE_URL"] = settings.OPENAI_BASE_URL
    if settings.OPENAI_MODEL_NAME is not None:
        updates["OPENAI_MODEL_NAME"] = settings.OPENAI_MODEL_NAME
    if settings.SKIP_AI_ANALYSIS is not None:
        updates["SKIP_AI_ANALYSIS"] = str(settings.SKIP_AI_ANALYSIS).lower()
    if settings.PROXY_URL is not None:
        updates["PROXY_URL"] = settings.PROXY_URL

    success = env_manager.update_values(updates)
    if not success:
        raise HTTPException(status_code=500, detail="更新AI设置失败")
    _reload_env()
    return {"message": "AI设置已成功更新"}


@router.post("/ai/models")
async def list_ai_models(settings: dict):
    """从服务商拉取可用模型列表（OpenAI 兼容 /models 接口）。

    body 可传 profile_id：用已保存模型配置的 Base URL / API Key / 代理
    （用于编辑时 API Key 不回显的场景），否则用 body 里的显式值。
    """
    try:
        from openai import OpenAI
        import httpx

        profile_id = settings.get("profile_id")
        profile = None
        if profile_id:
            from src.infrastructure.persistence.ai_profile_repository import (
                get_profile_sync,
            )

            profile = get_profile_sync(int(profile_id))
            if profile is None:
                return {"success": False, "models": [], "message": "模型配置不存在"}

        base_url = (
            (settings.get("OPENAI_BASE_URL") or "").strip()
            or (profile.base_url if profile else "")
        )
        if not base_url:
            return {"success": False, "models": [], "message": "请先填写 API Base URL"}

        stored_api_key = env_manager.get_value("OPENAI_API_KEY", "")
        submitted_api_key = settings.get("OPENAI_API_KEY", "")
        api_key = (
            submitted_api_key
            or (profile.api_key if profile else "")
            or stored_api_key
            or "no-key-required"
        )

        client_params = {
            "api_key": api_key,
            "base_url": base_url,
            "timeout": httpx.Timeout(30.0),
        }

        proxy_url = (
            settings.get("PROXY_URL") or (profile.proxy_url if profile else "") or ""
        )
        if proxy_url:
            client_params["http_client"] = httpx.Client(proxy=proxy_url)

        client = OpenAI(**client_params)
        models = client.models.list()
        model_ids = sorted({m.id for m in models.data if getattr(m, "id", None)})
        if not model_ids:
            return {
                "success": False,
                "models": [],
                "message": "服务商未返回任何模型，可能不支持 /models 接口，请手动填写模型名称",
            }
        return {"success": True, "models": model_ids, "message": ""}
    except Exception as exc:
        return {
            "success": False,
            "models": [],
            "message": f"获取模型列表失败: {exc}",
        }


def _perform_ai_test(client, model_name: str) -> str:
    """用给定客户端执行一次最小的 AI 调用，返回响应文本（含 API 模式回退）。"""
    api_mode = CHAT_COMPLETIONS_API_MODE
    try:
        response = create_ai_response_sync(
            client,
            api_mode,
            build_ai_request_params(
                api_mode,
                model=model_name,
                messages=[{"role": "user", "content": AI_TEST_PROMPT}],
                max_output_tokens=AI_TEST_MAX_OUTPUT_TOKENS,
            ),
        )
    except Exception as exc:
        if not is_chat_completions_api_unsupported_error(exc):
            raise
        api_mode = RESPONSES_API_MODE
        response = create_ai_response_sync(
            client,
            api_mode,
            build_ai_request_params(
                api_mode,
                model=model_name,
                messages=[{"role": "user", "content": AI_TEST_PROMPT}],
                max_output_tokens=AI_TEST_MAX_OUTPUT_TOKENS,
            ),
        )
    return extract_ai_response_content(response)


@router.post("/ai/test")
async def test_ai_settings(settings: dict):
    """测试AI模型设置是否有效"""
    try:
        from openai import OpenAI
        import httpx

        stored_api_key = env_manager.get_value("OPENAI_API_KEY", "")
        submitted_api_key = settings.get("OPENAI_API_KEY", "")
        api_key = submitted_api_key or stored_api_key

        client_params = {
            "api_key": api_key,
            "base_url": settings.get("OPENAI_BASE_URL", ""),
            "timeout": httpx.Timeout(30.0),
        }

        proxy_url = settings.get("PROXY_URL", "")
        if proxy_url:
            client_params["http_client"] = httpx.Client(proxy=proxy_url)

        model_name = settings.get("OPENAI_MODEL_NAME", "")
        client = OpenAI(**client_params)

        response_text = _perform_ai_test(client, model_name)
        return {
            "success": True,
            "message": "AI模型连接测试成功！",
            "response": response_text,
        }
    except Exception as exc:
        return {
            "success": False,
            "message": f"AI模型连接测试失败: {exc}",
        }


class AIProfileModel(BaseModel):
    """AI 模型配置（多模型）"""

    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model_name: Optional[str] = None
    proxy_url: Optional[str] = None
    enabled: Optional[bool] = None


def _mask_profile(profile):
    key = profile.api_key or ""
    return {
        "id": profile.id,
        "name": profile.name,
        "base_url": profile.base_url,
        "model_name": profile.model_name,
        "proxy_url": profile.proxy_url,
        "enabled": profile.enabled,
        "is_active": profile.is_active,
        "sort_order": profile.sort_order,
        "has_api_key": bool(key),
        "api_key_hint": (f"****{key[-4:]}" if len(key) >= 8 else ""),
    }


def _validate_profile_payload(payload: dict, *, require_all: bool) -> tuple[dict, str | None]:
    data = {}
    name = payload.get("name")
    base_url = (payload.get("base_url") or "").strip() if payload.get("base_url") is not None else None
    model_name = (payload.get("model_name") or "").strip() if payload.get("model_name") is not None else None
    if require_all and (not name or not str(name).strip()):
        return {}, "请填写备注名"
    if require_all and not base_url:
        return {}, "请填写 API Base URL"
    if require_all and not model_name:
        return {}, "请填写模型名称"
    if name is not None:
        data["name"] = str(name).strip()
    if base_url is not None:
        data["base_url"] = base_url
    if model_name is not None:
        data["model_name"] = model_name
    if payload.get("api_key") is not None:
        data["api_key"] = str(payload["api_key"]).strip()
    if payload.get("proxy_url") is not None:
        data["proxy_url"] = str(payload["proxy_url"]).strip()
    if payload.get("enabled") is not None:
        data["enabled"] = bool(payload["enabled"])
    return data, None


@router.get("/ai/profiles")
async def get_ai_profiles():
    from src.infrastructure.persistence.ai_profile_repository import list_profiles_sync

    return {"profiles": [_mask_profile(p) for p in list_profiles_sync()]}


@router.post("/ai/profiles")
async def create_ai_profile(payload: AIProfileModel):
    from src.infrastructure.persistence.ai_profile_repository import create_profile_sync

    data, error = _validate_profile_payload(
        payload.model_dump(exclude_none=True), require_all=True
    )
    if error:
        raise HTTPException(status_code=422, detail=error)
    profile = create_profile_sync(**data)
    return {"message": f"模型配置 [{profile.name}] 已添加", "profile": _mask_profile(profile)}


@router.put("/ai/profiles/{profile_id}")
async def update_ai_profile(profile_id: int, payload: AIProfileModel):
    from src.infrastructure.persistence.ai_profile_repository import (
        get_profile_sync,
        update_profile_sync,
    )

    if get_profile_sync(profile_id) is None:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    data, error = _validate_profile_payload(payload.model_dump(exclude_none=True), require_all=False)
    if error:
        raise HTTPException(status_code=422, detail=error)
    profile = update_profile_sync(profile_id, **data)
    return {"message": f"模型配置 [{profile.name}] 已更新", "profile": _mask_profile(profile)}


@router.delete("/ai/profiles/{profile_id}")
async def delete_ai_profile(profile_id: int):
    from src.infrastructure.persistence.ai_profile_repository import delete_profile_sync

    if not delete_profile_sync(profile_id):
        raise HTTPException(status_code=404, detail="模型配置不存在")
    return {"message": "模型配置已删除"}


@router.post("/ai/profiles/{profile_id}/activate")
async def activate_ai_profile(profile_id: int):
    from src.infrastructure.persistence.ai_profile_repository import (
        set_active_profile_sync,
    )

    profile = set_active_profile_sync(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    return {"message": f"当前模型已切换为 [{profile.name}]", "profile": _mask_profile(profile)}


@router.post("/ai/profiles/{profile_id}/enabled")
async def toggle_ai_profile(profile_id: int, payload: dict):
    from src.infrastructure.persistence.ai_profile_repository import (
        set_profile_enabled_sync,
    )

    enabled = bool(payload.get("enabled"))
    profile = set_profile_enabled_sync(profile_id, enabled)
    if profile is None:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    return {
        "message": f"模型 [{profile.name}] 已{'启用' if enabled else '停用'}",
        "profile": _mask_profile(profile),
    }


@router.post("/ai/profiles/{profile_id}/move")
async def move_ai_profile(profile_id: int, payload: dict):
    from src.infrastructure.persistence.ai_profile_repository import (
        move_profile_sync,
        get_profile_sync,
    )

    direction = payload.get("direction")
    if direction not in ("up", "down"):
        raise HTTPException(status_code=422, detail="direction 仅支持 up/down")
    if get_profile_sync(profile_id) is None:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    profiles = move_profile_sync(profile_id, direction)
    return {"message": "排序已更新", "profiles": [_mask_profile(p) for p in profiles]}


@router.post("/ai/profiles/{profile_id}/test")
async def test_ai_profile(profile_id: int):
    """用已保存的模型配置（含不回显的 API Key）测试连接"""
    from src.infrastructure.persistence.ai_profile_repository import get_profile_sync

    profile = get_profile_sync(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    try:
        from openai import OpenAI
        import httpx

        client_params = {
            "api_key": profile.api_key or "no-key-required",
            "base_url": profile.base_url,
            "timeout": httpx.Timeout(30.0),
        }
        if profile.proxy_url:
            client_params["http_client"] = httpx.Client(proxy=profile.proxy_url)
        client = OpenAI(**client_params)
        response_text = _perform_ai_test(client, profile.model_name)
        return {
            "success": True,
            "message": f"模型 [{profile.name}] 连接测试成功！",
            "response": response_text,
        }
    except Exception as exc:
        return {
            "success": False,
            "message": f"模型 [{profile.name}] 连接测试失败: {exc}",
        }
