"""AI base_url 安全校验（BYOK 防护）。

两层防护：
1. 始终拒绝指向内网/本机/链路本地地址的 URL（SSRF 核心防护）；
2. 可选域名白名单：环境变量 AI_BASE_URL_WHITELIST（逗号分隔，支持 *.example.com 通配，
   "*" 或留空表示不限制——默认不限制，兼容常见的 OpenAI 兼容聚合网关）。
"""
from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlparse


class BaseUrlNotAllowedError(ValueError):
    pass


_PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

_BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
}


def _is_private_host(hostname: str) -> bool:
    host = hostname.strip().lower().rstrip(".")
    if not host:
        return True
    if host in _BLOCKED_HOSTNAMES:
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return any(address in network for network in _PRIVATE_NETWORKS)


def _load_whitelist() -> list[str]:
    raw = (os.getenv("AI_BASE_URL_WHITELIST") or "").strip()
    if not raw:
        return []
    return [entry.strip().lower() for entry in raw.split(",") if entry.strip()]


def _host_allowed_by_whitelist(hostname: str, whitelist: list[str]) -> bool:
    if not whitelist or "*" in whitelist:
        return True
    host = hostname.strip().lower().rstrip(".")
    for entry in whitelist:
        if entry == "*":
            return True
        if entry.startswith("*."):
            suffix = entry[1:]  # ".example.com"
            if host.endswith(suffix) and host != suffix.lstrip("."):
                return True
        elif host == entry:
            return True
    return False


def validate_ai_base_url(base_url: str | None) -> str:
    """校验并返回规范化后的 base_url；不合规抛 BaseUrlNotAllowedError。"""
    url = (base_url or "").strip()
    if not url:
        raise BaseUrlNotAllowedError("API Base URL 不能为空")
    parsed = urlparse(url)
    if parsed.scheme != "https" and parsed.scheme != "http":
        raise BaseUrlNotAllowedError("API Base URL 必须以 http(s):// 开头")
    hostname = parsed.hostname or ""
    if not hostname:
        raise BaseUrlNotAllowedError("API Base URL 缺少域名")
    if _is_private_host(hostname):
        raise BaseUrlNotAllowedError(
            "API Base URL 不允许指向内网/本机地址（安全限制）"
        )
    whitelist = _load_whitelist()
    if not _host_allowed_by_whitelist(hostname, whitelist):
        raise BaseUrlNotAllowedError(
            "API Base URL 不在平台允许的域名白名单内，请联系管理员"
        )
    return url
