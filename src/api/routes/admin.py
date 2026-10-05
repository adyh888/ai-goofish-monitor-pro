"""管理员路由：卡密管理、用户管理。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from src.api.dependencies import require_admin, get_scheduler_service, get_task_service
from src.services.membership_service import apply_membership_state
from src.infrastructure.persistence.card_key_repository import (
    generate_cards_sync,
    list_cards_sync,
    list_unused_codes_sync,
    set_card_status_sync,
)
from src.infrastructure.persistence.user_repository import (
    User,
    UsernameTakenError,
    create_user_sync,
    list_users_sync,
    update_user_sync,
)
from src.services.auth_service import (
    AuthError,
    build_user_payload,
    is_membership_active,
)
from src.services.security import parse_iso_datetime

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin)])


class GenerateCardsRequest(BaseModel):
    count: int
    duration_days: int
    batch_no: str = ""
    note: str = ""


class CardStatusRequest(BaseModel):
    status: str


class UserExpiryRequest(BaseModel):
    expired_at: str | None = None


class UserStatusRequest(BaseModel):
    status: str


class UserPasswordRequest(BaseModel):
    new_password: str


class CreateUserRequest(BaseModel):
    username: str
    password: str
    role: str = "user"


class GenerateCardsResponse(BaseModel):
    batch_no: str
    duration_days: int
    codes: list[str]


@router.post("/cards/generate")
async def admin_generate_cards(payload: GenerateCardsRequest):
    try:
        cards = generate_cards_sync(
            count=payload.count,
            duration_days=payload.duration_days,
            batch_no=payload.batch_no.strip(),
            note=payload.note.strip(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "batch_no": payload.batch_no.strip(),
        "duration_days": payload.duration_days,
        "codes": [card.code for card in cards],
    }


@router.get("/cards")
async def admin_list_cards(
    status: str | None = None,
    batch_no: str | None = None,
    limit: int = 500,
):
    cards = list_cards_sync(status=status, batch_no=batch_no, limit=min(max(limit, 1), 2000))
    return {
        "items": [card.__dict__ for card in cards],
        "total": len(cards),
    }


@router.get("/cards/export", response_class=PlainTextResponse)
async def admin_export_cards(batch_no: str | None = None):
    """导出未使用卡密（一行一码），可直接对接发卡平台。"""
    codes = list_unused_codes_sync(batch_no=batch_no)
    return "\n".join(codes)


@router.post("/cards/{card_id}/status")
async def admin_set_card_status(card_id: int, payload: CardStatusRequest):
    try:
        card = set_card_status_sync(card_id, payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if card is None:
        raise HTTPException(status_code=404, detail="卡密不存在")
    return card.__dict__


@router.get("/cards/summary")
async def admin_cards_summary():
    from src.infrastructure.persistence.card_key_repository import count_cards_sync

    return {
        "unused": count_cards_sync(status="unused"),
        "used": count_cards_sync(status="used"),
        "disabled": count_cards_sync(status="disabled"),
    }


@router.get("/users")
async def admin_list_users():
    users = list_users_sync()
    return {"items": [build_user_payload(user) for user in users]}


@router.post("/users")
async def admin_create_user(payload: CreateUserRequest):
    if payload.role not in ("user", "admin"):
        raise HTTPException(status_code=400, detail="角色仅支持 user/admin")
    try:
        user = create_user_sync(
            username=payload.username.strip(),
            password=payload.password,
            role=payload.role,
        )
    except (UsernameTakenError, AuthError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return build_user_payload(user)


@router.put("/users/{user_id}/expiry")
async def admin_set_user_expiry(
    user_id: int,
    payload: UserExpiryRequest,
    scheduler_service=Depends(get_scheduler_service),
    task_service=Depends(get_task_service),
):
    """直接调整到期时间：传 ISO 时间或 null（清除会员）。同步暂停/恢复任务。"""
    expired_at = None
    if payload.expired_at:
        parsed = parse_iso_datetime(payload.expired_at)
        if parsed is None:
            raise HTTPException(status_code=400, detail="时间格式无效，应为 ISO 8601")
        expired_at = parsed.isoformat(timespec="seconds")
    user = update_user_sync(user_id, expired_at=expired_at)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    apply_membership_state(user.id)
    tasks = await task_service.get_all_tasks()
    await scheduler_service.reload_jobs(tasks)
    return build_user_payload(user)


@router.put("/users/{user_id}/status")
async def admin_set_user_status(
    user_id: int,
    payload: UserStatusRequest,
    current_user: User = Depends(require_admin),
    scheduler_service=Depends(get_scheduler_service),
    task_service=Depends(get_task_service),
):
    if payload.status not in ("active", "disabled"):
        raise HTTPException(status_code=400, detail="状态仅支持 active/disabled")
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="不能禁用自己的账号")
    user = update_user_sync(user_id, status=payload.status)
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if payload.status == "disabled":
        from src.services.membership_service import set_membership_paused

        set_membership_paused(user.id, paused=True)
    else:
        apply_membership_state(user.id)
    tasks = await task_service.get_all_tasks()
    await scheduler_service.reload_jobs(tasks)
    return build_user_payload(user)


@router.put("/users/{user_id}/password")
async def admin_reset_user_password(user_id: int, payload: UserPasswordRequest):
    from src.services.security import hash_password

    if not payload.new_password or len(payload.new_password) < 6:
        raise HTTPException(status_code=400, detail="新密码长度至少 6 位")
    user = update_user_sync(user_id, password_hash=hash_password(payload.new_password))
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return {"message": "密码已重置"}


PLATFORM_SETTING_KEYS = {
    "REGISTRATION_ENABLED": "bool",
    "AI_BASE_URL_WHITELIST": "text",
    "PLATFORM_PROXY_POOL_ENABLED": "bool",
    "PER_USER_TASK_LIMIT": "int",
    "PER_USER_CONCURRENT_RUNNING": "int",
    "GLOBAL_SPIDER_CONCURRENCY": "int",
}

_PLATFORM_DEFAULTS = {
    "REGISTRATION_ENABLED": True,
    "AI_BASE_URL_WHITELIST": "",
    "PLATFORM_PROXY_POOL_ENABLED": True,
    "PER_USER_TASK_LIMIT": 10,
    "PER_USER_CONCURRENT_RUNNING": 1,
    "GLOBAL_SPIDER_CONCURRENCY": 5,
}


class PlatformSettingsRequest(BaseModel):
    REGISTRATION_ENABLED: bool | None = None
    AI_BASE_URL_WHITELIST: str | None = None
    PLATFORM_PROXY_POOL_ENABLED: bool | None = None
    PER_USER_TASK_LIMIT: int | None = None
    PER_USER_CONCURRENT_RUNNING: int | None = None
    GLOBAL_SPIDER_CONCURRENCY: int | None = None


@router.get("/platform")
async def admin_get_platform_settings():
    import os

    from src.infrastructure.config.env_manager import env_manager

    values = {}
    for key, kind in PLATFORM_SETTING_KEYS.items():
        raw = env_manager.get_value(key)
        if raw is None:
            values[key] = _PLATFORM_DEFAULTS[key]
        elif kind == "bool":
            values[key] = str(raw).strip().lower() in {"1", "true", "yes", "on"}
        elif kind == "int":
            try:
                values[key] = max(1, int(raw))
            except (TypeError, ValueError):
                values[key] = _PLATFORM_DEFAULTS[key]
        else:
            values[key] = str(raw)
    return {"settings": values}


@router.put("/platform")
async def admin_update_platform_settings(payload: PlatformSettingsRequest):
    """平台级设置：写回 .env 并即时生效（无需重启）。"""
    import os

    from dotenv import load_dotenv

    from src.infrastructure.config.env_manager import env_manager

    updates = {}
    patch = payload.model_dump(exclude_none=True)
    for key, value in patch.items():
        if key in ("PER_USER_TASK_LIMIT", "PER_USER_CONCURRENT_RUNNING", "GLOBAL_SPIDER_CONCURRENCY"):
            try:
                value = max(1, int(value))
            except (TypeError, ValueError):
                raise HTTPException(status_code=400, detail=f"{key} 必须是正整数")
        if isinstance(value, bool):
            updates[key] = "true" if value else "false"
        else:
            updates[key] = str(value).strip()
    if not env_manager.update_values(updates):
        raise HTTPException(status_code=500, detail="写入平台设置失败")
    load_dotenv(dotenv_path=env_manager.env_file, override=True)
    return {"message": "平台设置已保存并即时生效"}


@router.get("/overview")
async def admin_overview():
    """平台概览：用户数、有效会员数、卡密余量。"""
    users = list_users_sync()
    from src.infrastructure.persistence.card_key_repository import count_cards_sync

    return {
        "total_users": len(users),
        "active_members": sum(
            1 for user in users if user.status == "active" and is_membership_active(user)
        ),
        "cards_unused": count_cards_sync(status="unused"),
        "cards_used": count_cards_sync(status="used"),
    }
