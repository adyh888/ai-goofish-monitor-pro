"""认证与会员路由：注册 / 登录 / 个人信息 / 卡密激活 / 修改密码。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from src.api.dependencies import get_current_user, get_scheduler_service, get_task_service
from src.services.membership_service import apply_membership_state
from src.services.auth_service import (
    AuthError,
    activate_card_for_user,
    authenticate,
    build_user_payload,
    change_password,
    register_user,
)
from src.services.rate_limiter import SlidingWindowLimiter, enforce_rate_limit
from src.services.security import create_access_token
from src.infrastructure.persistence.user_repository import User

router = APIRouter(prefix="/api/auth", tags=["auth"])

_login_limiter = SlidingWindowLimiter()
_register_limiter = SlidingWindowLimiter()
_activate_limiter = SlidingWindowLimiter()

REGISTRATION_DISABLED_MESSAGE = "当前未开放注册，请联系管理员开通账号"


class RegisterRequest(BaseModel):
    username: str
    password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class ActivateCardRequest(BaseModel):
    code: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


def _registration_enabled() -> bool:
    import os

    return (os.getenv("REGISTRATION_ENABLED", "true") or "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _token_response(user: User) -> dict:
    token = create_access_token(user.id, user.username, user.role)
    return {"token": token, "user": build_user_payload(user)}


@router.post("/register")
async def register(payload: RegisterRequest, request: Request):
    enforce_rate_limit(_register_limiter, scope="register", request=request, limit=5)
    if not _registration_enabled():
        raise HTTPException(status_code=403, detail=REGISTRATION_DISABLED_MESSAGE)
    try:
        user = register_user(payload.username, payload.password)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _token_response(user)


@router.post("/login")
async def login(payload: LoginRequest, request: Request):
    enforce_rate_limit(
        _login_limiter,
        scope="login",
        request=request,
        limit=10,
        identity=payload.username.strip().lower(),
    )
    user = authenticate(payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return _token_response(user)


@router.get("/me")
async def me(current_user: User = Depends(get_current_user)):
    return build_user_payload(current_user)


@router.post("/activate-card")
async def activate_card(
    payload: ActivateCardRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    scheduler_service=Depends(get_scheduler_service),
    task_service=Depends(get_task_service),
):
    """激活/续期会员。已过期的用户仍可调用（用于续费）。"""
    enforce_rate_limit(
        _activate_limiter,
        scope="activate",
        request=request,
        limit=10,
        identity=str(current_user.id),
    )
    try:
        updated_user, card = activate_card_for_user(current_user, payload.code)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # 激活后自动恢复被会员暂停的任务并重载调度
    state = apply_membership_state(updated_user.id)
    if state == "resumed":
        tasks = await task_service.get_all_tasks()
        await scheduler_service.reload_jobs(tasks)

    return {
        "user": build_user_payload(updated_user),
        "activated_days": card.duration_days,
        "message": f"激活成功，会员已延长 {card.duration_days} 天",
    }


@router.post("/change-password")
async def change_own_password(
    payload: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
):
    try:
        change_password(current_user, payload.old_password, payload.new_password)
    except AuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"message": "密码已更新"}
