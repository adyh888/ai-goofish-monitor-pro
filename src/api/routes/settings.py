"""
设置管理路由
"""
import os
from typing import Optional

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.dependencies import get_current_user, get_process_service, require_admin
from src.infrastructure.config.env_manager import env_manager
from src.infrastructure.persistence.user_repository import User
from src.services.ai_url_whitelist import BaseUrlNotAllowedError, validate_ai_base_url
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
async def get_notification_settings(current_user: User = Depends(get_current_user)):
    return build_notification_settings_response(
        load_notification_settings(current_user.id)
    )


@router.put("/notifications")
async def update_notification_settings(
    settings: NotificationSettingsModel,
    current_user: User = Depends(get_current_user),
):
    """保存当前用户的通知配置（加密落库，不再写 .env）。"""
    from src.services.notification_config_service import (
        save_notification_settings_for_user,
    )

    try:
        _, _, merged_settings = prepare_notification_settings_update(
            model_dump(settings, exclude_unset=True),
            load_notification_settings(current_user.id),
        )
    except NotificationSettingsValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    save_notification_settings_for_user(current_user.id, merged_settings)
    return {
        "message": "通知设置已成功更新",
        "configured_channels": build_configured_channels(merged_settings),
    }


@router.post("/notifications/test")
async def test_notification_settings(
    payload: NotificationTestRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        merged_settings = prepare_notification_test_settings(
            model_dump(payload.settings, exclude_unset=True),
            load_notification_settings(current_user.id),
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


def _mask_proxy_pool(pool: str) -> str:
    pool = (pool or "").strip()
    if not pool:
        return ""
    first_line = pool.splitlines()[0]
    if len(first_line) <= 12:
        return "****"
    return f"****{first_line[-6:]}"


def _coerce_rotation_value(key: str, value):
    if key in {"ACCOUNT_ROTATION_ENABLED", "PROXY_ROTATION_ENABLED"}:
        return bool(value)
    if key in {
        "ACCOUNT_ROTATION_RETRY_LIMIT",
        "ACCOUNT_BLACKLIST_TTL",
        "PROXY_ROTATION_RETRY_LIMIT",
        "PROXY_BLACKLIST_TTL",
    }:
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return None
    return (str(value) or "").strip()


@router.get("/rotation")
async def get_rotation_settings(current_user: User = Depends(get_current_user)):
    from src.infrastructure.persistence.user_config_repository import (
        load_rotation_config_sync,
    )

    values = load_rotation_config_sync(current_user.id)
    response = dict(values)
    response["PROXY_POOL"] = ""
    response["PROXY_POOL_SET"] = bool(values.get("PROXY_POOL"))
    response["PROXY_POOL_HINT"] = _mask_proxy_pool(values.get("PROXY_POOL") or "")
    return response


@router.put("/rotation")
async def update_rotation_settings(
    settings: RotationSettingsModel,
    current_user: User = Depends(get_current_user),
):
    """保存当前用户的账号/IP 轮换配置（代理列表加密落库，仅本用户的任务使用）。"""
    from src.infrastructure.persistence.user_config_repository import (
        load_rotation_config_sync,
        save_rotation_config_sync,
    )

    current = load_rotation_config_sync(current_user.id)
    payload = model_dump(settings, exclude_unset=True)
    for key, raw_value in payload.items():
        if key == "PROXY_POOL":
            text = str(raw_value or "").strip()
            if text and "****" in text:
                continue  # 前端回显的掩码值：保持原值不变
            current[key] = text
        else:
            coerced = _coerce_rotation_value(key, raw_value)
            if coerced is not None:
                current[key] = coerced
    save_rotation_config_sync(current_user.id, current)
    return {"message": "轮换设置已成功更新"}


@router.get("/status")
async def get_system_status(
    process_service: ProcessService = Depends(get_process_service),
    current_user: User = Depends(get_current_user),
):
    """当前用户的运行状态：自己的登录态、自己的通知配置、自己的 AI 配置。"""
    from src.utils import get_user_state_file

    state_file = get_user_state_file(current_user.id)
    env_file_exists = os.path.exists(env_manager.env_file)
    login_state_exists = os.path.exists(state_file)
    notification_settings = load_notification_settings(current_user.id)
    running_task_ids = [
        task_id
        for task_id, process in process_service.processes.items()
        if process and process.returncode is None
    ]

    ai_configured = False
    try:
        from src.infrastructure.persistence.ai_profile_repository import (
            get_active_profile_sync,
        )

        ai_configured = get_active_profile_sync(current_user.id) is not None
    except Exception:
        ai_configured = False
    if not ai_configured and current_user.is_admin:
        ai_configured = AISettings().is_configured()

    response = {
        "ai_configured": ai_configured,
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
            **build_notification_status_flags(notification_settings),
        },
        "configured_notification_channels": build_configured_channels(notification_settings),
    }
    if current_user.is_admin:
        response["env_file"]["openai_api_key_set"] = bool(
            env_manager.get_value("OPENAI_API_KEY", "")
        )
        response["env_file"]["openai_base_url_set"] = bool(
            env_manager.get_value("OPENAI_BASE_URL", "")
        )
        response["env_file"]["openai_model_name_set"] = bool(
            env_manager.get_value("OPENAI_MODEL_NAME", "")
        )
    return response


@router.get("/ai")
async def get_ai_settings(current_user: User = Depends(require_admin)):
    return {
        "OPENAI_BASE_URL": env_manager.get_value("OPENAI_BASE_URL", ""),
        "OPENAI_MODEL_NAME": env_manager.get_value("OPENAI_MODEL_NAME", ""),
        "SKIP_AI_ANALYSIS": env_manager.get_value("SKIP_AI_ANALYSIS", "false").lower() == "true",
        "PROXY_URL": env_manager.get_value("PROXY_URL", ""),
    }


@router.put("/ai")
async def update_ai_settings(settings: AISettingsModel, current_user: User = Depends(require_admin)):
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
async def list_ai_models(settings: dict, current_user: User = Depends(get_current_user)):
    """从服务商拉取可用模型列表（OpenAI 兼容 /models 接口）。

    body 可传 profile_id：用已保存模型配置的 Base URL / API Key / 代理
    （用于编辑时 API Key 不回显的场景），否则用 body 里的显式值。
    仅限访问当前用户自己的模型配置。
    """
    try:
        profile_id = settings.get("profile_id")
        profile = None
        if profile_id:
            from src.infrastructure.persistence.ai_profile_repository import (
                get_profile_sync,
            )

            profile = get_profile_sync(int(profile_id))
            if profile is None or (
                not current_user.is_admin and profile.user_id != current_user.id
            ):
                return {"success": False, "models": [], "message": "模型配置不存在"}

        base_url = (
            (settings.get("OPENAI_BASE_URL") or "").strip()
            or (profile.base_url if profile else "")
        )
        try:
            base_url = validate_ai_base_url(base_url)
        except BaseUrlNotAllowedError as exc:
            return {"success": False, "models": [], "message": str(exc)}

        stored_api_key = (
            env_manager.get_value("OPENAI_API_KEY", "") if current_user.is_admin else ""
        )
        submitted_api_key = settings.get("OPENAI_API_KEY", "")
        api_key = (
            submitted_api_key
            or (profile.api_key if profile else "")
            or stored_api_key
            or "no-key-required"
        )

        proxy_url = (
            settings.get("PROXY_URL") or (profile.proxy_url if profile else "") or ""
        )
        return _fetch_model_ids(base_url, api_key, proxy_url or None)
    except Exception as exc:
        return {
            "success": False,
            "models": [],
            "message": f"获取模型列表失败: {exc}",
        }


def _models_error(message: str) -> dict:
    return {"success": False, "models": [], "message": message}


def _probe_anthropic_models(base_url: str, api_key: str, proxy_url=None, transport=None) -> str:
    """/models 404 时探测该地址是否为 Anthropic 协议端点（GET {base}/v1/models）。

    Anthropic 协议用 x-api-key（Claude Code 也用 Bearer），与 OpenAI 协议的
    路径和鉴权头都不同；探测成功说明用户填的是 Anthropic 专用地址，
    返回对应的中文提示，否则返回空串走通用 404 提示。
    """
    import httpx

    url = base_url.rstrip("/") + "/v1/models"
    headers = {
        "x-api-key": api_key,
        "Authorization": f"Bearer {api_key}",
        "anthropic-version": "2023-06-01",
        "Accept": "application/json",
    }
    try:
        with httpx.Client(
            timeout=httpx.Timeout(15.0),
            proxy=proxy_url or None,
            follow_redirects=True,
            transport=transport,
        ) as client:
            response = client.get(url, headers=headers)
    except httpx.HTTPError:
        return ""
    if response.status_code != 200 or "json" not in response.headers.get(
        "content-type", ""
    ).lower():
        return ""
    try:
        payload = response.json()
    except ValueError:
        return ""
    items = payload.get("data") if isinstance(payload, dict) else payload
    if isinstance(items, list) and items:
        return (
            "该地址是 Anthropic 协议端点（能列出模型，供 Claude Code 等使用），"
            "但本系统使用 OpenAI 协议调用 AI，此地址无法完成分析。"
            "请改用服务商的 OpenAI 兼容地址（DeepSeek 填 https://api.deepseek.com）"
        )
    return ""


def _fetch_model_ids(base_url: str, api_key: str, proxy_url=None, transport=None) -> dict:
    """直连 OpenAI 兼容 /models 接口，返回统一结构的成功/失败结果。

    不经 openai SDK：SDK 对非 JSON 响应（如把官网地址当 API 地址时拿到的
    HTML 页面）会把原始文本传给分页解析器，抛出难以理解的
    "'str' object has no attribute '_set_private_attributes'"。
    这里直接请求并把各类失败翻译成可操作的提示。
    """
    import httpx

    url = base_url.rstrip("/") + "/models"
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    try:
        with httpx.Client(
            timeout=httpx.Timeout(30.0),
            proxy=proxy_url or None,
            follow_redirects=True,
            transport=transport,
        ) as client:
            response = client.get(url, headers=headers)
    except httpx.TimeoutException:
        return _models_error("连接服务商超时，请检查网络或代理设置")
    except httpx.HTTPError as exc:
        return _models_error(f"无法连接服务商，请检查网络、代理或 Base URL 是否正确（{exc}）")

    if response.status_code in (401, 403):
        return _models_error(
            f"API Key 无效或无权限（HTTP {response.status_code}），请检查 API Key"
        )
    if response.status_code == 404:
        anthropic_hit = _probe_anthropic_models(base_url, api_key, proxy_url, transport)
        if anthropic_hit:
            return _models_error(anthropic_hit)
        return _models_error(
            "服务商不存在 /models 接口（HTTP 404）："
            "Base URL 通常应以 /v1 结尾；若填的是 .../anthropic 这类 Anthropic 协议地址"
            "（供 Claude Code 等使用），请改用 OpenAI 兼容地址"
            "（DeepSeek 填 https://api.deepseek.com），或手动填写模型名称"
        )
    if response.status_code == 429:
        return _models_error("请求被服务商限流（HTTP 429），请稍后重试")
    if response.status_code >= 400:
        return _models_error(f"服务商返回 HTTP {response.status_code}，请检查 Base URL 与 API Key")

    content_type = response.headers.get("content-type", "")
    if "json" not in content_type.lower() or not response.text.lstrip().startswith(
        ("{", "[")
    ):
        return _models_error(
            "服务商返回的是网页而非 JSON：Base URL 很可能填成了官网地址"
            "（如 DeepSeek 应填 https://api.deepseek.com，而非 platform.deepseek.com），"
            "或网络/代理返回了拦截页"
        )
    try:
        payload = response.json()
    except ValueError:
        return _models_error("服务商返回了无法解析的 JSON，请检查 Base URL 是否正确")

    if isinstance(payload, dict):
        items = payload.get("data")
        if not isinstance(items, list):
            items = payload.get("models")
    else:
        items = payload
    if not isinstance(items, list):
        items = []

    raw_ids = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id") or item.get("name") or ""
        if raw_id:
            raw_ids.add(str(raw_id).strip())
    if not raw_ids:
        return _models_error(
            "服务商未返回任何模型，可能不支持 /models 接口，请手动填写模型名称"
        )
    return {"success": True, "models": sorted(raw_ids), "message": ""}


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
async def test_ai_settings(settings: dict, current_user: User = Depends(get_current_user)):
    """测试AI模型设置是否有效（base_url 受 SSRF/白名单校验）"""
    try:
        from openai import OpenAI
        import httpx

        try:
            base_url = validate_ai_base_url(settings.get("OPENAI_BASE_URL", ""))
        except BaseUrlNotAllowedError as exc:
            return {"success": False, "message": str(exc)}

        stored_api_key = (
            env_manager.get_value("OPENAI_API_KEY", "") if current_user.is_admin else ""
        )
        submitted_api_key = settings.get("OPENAI_API_KEY", "")
        api_key = submitted_api_key or stored_api_key

        client_params = {
            "api_key": api_key,
            "base_url": base_url,
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


def _get_owned_profile_or_404(profile_id: int, current_user: User):
    """读取模型配置并校验归属（管理员可访问任意配置）。"""
    from src.infrastructure.persistence.ai_profile_repository import get_profile_sync

    profile = get_profile_sync(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    if not current_user.is_admin and profile.user_id != current_user.id:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    return profile


@router.get("/ai/profiles")
async def get_ai_profiles(current_user: User = Depends(get_current_user)):
    from src.infrastructure.persistence.ai_profile_repository import list_profiles_sync

    return {
        "profiles": [
            _mask_profile(p)
            for p in list_profiles_sync(
                None if current_user.is_admin else current_user.id
            )
        ]
    }


@router.post("/ai/profiles")
async def create_ai_profile(payload: AIProfileModel, current_user: User = Depends(get_current_user)):
    from src.infrastructure.persistence.ai_profile_repository import create_profile_sync

    data, error = _validate_profile_payload(
        payload.model_dump(exclude_none=True), require_all=True
    )
    if error:
        raise HTTPException(status_code=422, detail=error)
    try:
        data["base_url"] = validate_ai_base_url(data.get("base_url"))
    except BaseUrlNotAllowedError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    profile = create_profile_sync(**data, user_id=current_user.id)
    return {"message": f"模型配置 [{profile.name}] 已添加", "profile": _mask_profile(profile)}


@router.put("/ai/profiles/{profile_id}")
async def update_ai_profile(
    profile_id: int,
    payload: AIProfileModel,
    current_user: User = Depends(get_current_user),
):
    from src.infrastructure.persistence.ai_profile_repository import update_profile_sync

    _get_owned_profile_or_404(profile_id, current_user)
    data, error = _validate_profile_payload(payload.model_dump(exclude_none=True), require_all=False)
    if error:
        raise HTTPException(status_code=422, detail=error)
    if data.get("base_url"):
        try:
            data["base_url"] = validate_ai_base_url(data["base_url"])
        except BaseUrlNotAllowedError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    profile = update_profile_sync(profile_id, **data)
    return {"message": f"模型配置 [{profile.name}] 已更新", "profile": _mask_profile(profile)}


@router.delete("/ai/profiles/{profile_id}")
async def delete_ai_profile(profile_id: int, current_user: User = Depends(get_current_user)):
    from src.infrastructure.persistence.ai_profile_repository import delete_profile_sync

    _get_owned_profile_or_404(profile_id, current_user)
    if not delete_profile_sync(profile_id):
        raise HTTPException(status_code=404, detail="模型配置不存在")
    return {"message": "模型配置已删除"}


@router.post("/ai/profiles/{profile_id}/activate")
async def activate_ai_profile(profile_id: int, current_user: User = Depends(get_current_user)):
    from src.infrastructure.persistence.ai_profile_repository import (
        set_active_profile_sync,
    )

    _get_owned_profile_or_404(profile_id, current_user)
    profile = set_active_profile_sync(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    return {"message": f"当前模型已切换为 [{profile.name}]", "profile": _mask_profile(profile)}


@router.post("/ai/profiles/{profile_id}/enabled")
async def toggle_ai_profile(
    profile_id: int,
    payload: dict,
    current_user: User = Depends(get_current_user),
):
    from src.infrastructure.persistence.ai_profile_repository import (
        set_profile_enabled_sync,
    )

    _get_owned_profile_or_404(profile_id, current_user)
    enabled = bool(payload.get("enabled"))
    profile = set_profile_enabled_sync(profile_id, enabled)
    if profile is None:
        raise HTTPException(status_code=404, detail="模型配置不存在")
    return {
        "message": f"模型 [{profile.name}] 已{'启用' if enabled else '停用'}",
        "profile": _mask_profile(profile),
    }


@router.post("/ai/profiles/{profile_id}/move")
async def move_ai_profile(
    profile_id: int,
    payload: dict,
    current_user: User = Depends(get_current_user),
):
    from src.infrastructure.persistence.ai_profile_repository import (
        move_profile_sync,
    )

    _get_owned_profile_or_404(profile_id, current_user)
    direction = payload.get("direction")
    if direction not in ("up", "down"):
        raise HTTPException(status_code=422, detail="direction 仅支持 up/down")
    profiles = move_profile_sync(profile_id, direction)
    return {"message": "排序已更新", "profiles": [_mask_profile(p) for p in profiles]}


@router.post("/ai/profiles/{profile_id}/test")
async def test_ai_profile(profile_id: int, current_user: User = Depends(get_current_user)):
    """用已保存的模型配置（含不回显的 API Key）测试连接"""
    profile = _get_owned_profile_or_404(profile_id, current_user)
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
