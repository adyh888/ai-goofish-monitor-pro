"""认证与会员服务：注册、登录、卡密激活、会员状态计算。

会员规则（已确认）：
- 激活/续期：新到期时间 = max(当前时间, 原到期时间) + 卡密天数；
- admin 角色永不过期；普通用户 expired_at 为 NULL 表示从未激活；
- 过期用户的接口层放行范围由路由依赖控制（仅登录、查看自身、激活卡密）。
"""
from __future__ import annotations

import re
from datetime import timedelta

from src.infrastructure.persistence.card_key_repository import (
    CardKey,
    get_card_by_code_sync,
    mark_card_used_sync,
)
from src.infrastructure.persistence.user_repository import (
    User,
    UsernameTakenError,
    create_user_sync,
    get_user_by_username_sync,
    update_user_sync,
)
from src.services.security import (
    hash_password,
    parse_iso_datetime,
    utc_now,
    verify_password,
)

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]{3,32}$")
PASSWORD_MIN_LENGTH = 6
MEMBERSHIP_EXPIRED_CODE = "MEMBERSHIP_EXPIRED"


class AuthError(ValueError):
    """带用户可读 message 的认证/会员错误。"""


def _validate_registration(username: str, password: str) -> None:
    if not USERNAME_PATTERN.match(username or ""):
        raise AuthError("用户名须为 3~32 位字母、数字或下划线")
    if not password or len(password) < PASSWORD_MIN_LENGTH:
        raise AuthError(f"密码长度至少 {PASSWORD_MIN_LENGTH} 位")


def register_user(username: str, password: str) -> User:
    _validate_registration(username, password)
    try:
        user = create_user_sync(username=username.strip(), password=password)
    except UsernameTakenError as exc:
        raise AuthError(str(exc)) from exc
    from src.utils import seed_user_prompts

    seed_user_prompts(user.id)
    return user


def authenticate(username: str, password: str) -> User | None:
    user = get_user_by_username_sync((username or "").strip())
    if user is None or user.status != "active":
        return None
    if not verify_password(password or "", user.password_hash):
        return None
    update_user_sync(user.id, last_login_at=utc_now().isoformat(timespec="seconds"))
    return get_user_by_username_sync(user.username)


def is_membership_active(user: User, now: datetime | None = None) -> bool:
    if user.is_admin:
        return True
    expired_at = parse_iso_datetime(user.expired_at)
    if expired_at is None:
        return False
    return expired_at > (now or utc_now())


def remaining_days(user: User, now: datetime | None = None) -> int | None:
    """剩余会员天数（向上取整）；admin 返回 None 表示不限期，未激活返回 0。"""
    if user.is_admin:
        return None
    expired_at = parse_iso_datetime(user.expired_at)
    if expired_at is None:
        return 0
    delta = expired_at - (now or utc_now())
    if delta.total_seconds() <= 0:
        return 0
    return int(delta.total_seconds() // 86400) + 1


def build_user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "status": user.status,
        "expired_at": user.expired_at,
        "membership_active": is_membership_active(user),
        "remaining_days": remaining_days(user),
    }


def activate_card_for_user(user: User, code: str) -> tuple[User, CardKey]:
    """激活卡密并延长会员期。卡密无效/已用/已禁用统一报同一句错误，不泄露存在性。"""
    card = get_card_by_code_sync(code)
    if card is None or card.status != "unused":
        raise AuthError("卡密无效或已被使用")

    now = utc_now()
    current_expired = parse_iso_datetime(user.expired_at)
    base = max(now, current_expired) if current_expired else now
    new_expired_at = base + timedelta(days=card.duration_days)

    mark_card_used_sync(card.id, user.id)
    updated = update_user_sync(
        user.id,
        expired_at=new_expired_at.isoformat(timespec="seconds"),
    )
    assert updated is not None
    return updated, card


def change_password(user: User, old_password: str, new_password: str) -> User:
    if not verify_password(old_password or "", user.password_hash):
        raise AuthError("当前密码不正确")
    if not new_password or len(new_password) < PASSWORD_MIN_LENGTH:
        raise AuthError(f"新密码长度至少 {PASSWORD_MIN_LENGTH} 位")
    return update_user_sync(user.id, password_hash=hash_password(new_password))
