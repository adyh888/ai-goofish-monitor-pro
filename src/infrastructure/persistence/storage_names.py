"""
SQLite 持久化相关的统一命名规则。
"""
from __future__ import annotations

import re


DEFAULT_DATABASE_PATH = "data/app.sqlite3"
RESULT_FILE_SUFFIX = "_full_data.jsonl"
# 会破坏 URL 路径或文件路径的字符，统一替换为下划线
UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|#%]+')


def build_result_filename(keyword: str) -> str:
    name = str(keyword or "").replace(" ", "_")
    name = UNSAFE_FILENAME_CHARS.sub("_", name)
    return f"{name}{RESULT_FILE_SUFFIX}"


def normalize_keyword_from_filename(filename: str) -> str:
    return str(filename or "").replace(RESULT_FILE_SUFFIX, "")


def normalize_keyword_slug(keyword: str) -> str:
    text = "".join(
        char for char in str(keyword or "").lower().replace(" ", "_")
        if char.isalnum() or char in "_-"
    ).rstrip("_")
    return text or "unknown"
