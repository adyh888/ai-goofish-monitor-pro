"""按用户构建 AI 客户端（BYOK）。

优先用该用户"当前激活"的模型配置；用户未配置时：
- admin（user_id=1）回退 .env 平台配置；
- 普通用户返回未配置的客户端（上层报"请先配置 AI 模型"）。
"""
from __future__ import annotations

from src.infrastructure.external.ai_client import AIClient


def build_user_ai_client(user_id: int) -> AIClient:
    from src.infrastructure.persistence.ai_profile_repository import (
        get_active_profile_sync,
    )

    profile = get_active_profile_sync(user_id)
    if profile is not None:
        return AIClient(profile=profile)
    return AIClient()
