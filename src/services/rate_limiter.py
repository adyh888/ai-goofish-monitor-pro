"""进程内滑动窗口限流器。

单实例部署下够用：登录/注册/激活等敏感端点按 IP+账号维度限流，
防止卡密与密码爆破。多实例部署时应替换为 Redis 实现。
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict

from fastapi import HTTPException, Request


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, list[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window_seconds: float = 60.0) -> bool:
        """未超限返回 True 并记录本次访问；超限返回 False。"""
        now = time.monotonic()
        with self._lock:
            bucket = [t for t in self._hits[key] if now - t < window_seconds]
            if len(bucket) >= limit:
                self._hits[key] = bucket
                return False
            bucket.append(now)
            self._hits[key] = bucket
            return True


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def enforce_rate_limit(
    limiter: SlidingWindowLimiter,
    *,
    scope: str,
    request: Request,
    limit: int,
    identity: str | None = None,
) -> None:
    key = f"{scope}:{client_ip(request)}"
    if identity:
        key += f":{identity}"
    if not limiter.check(key, limit=limit):
        raise HTTPException(status_code=429, detail="操作过于频繁，请稍后再试")
