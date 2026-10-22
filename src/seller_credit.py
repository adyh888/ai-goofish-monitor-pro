"""卖家信用等级解析、门槛校验与判据改写。"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

CREDIT_RANK_BY_LABEL = {
    "极好": 4,
    "优秀": 3,
    "良好": 2,
    "一般": 1,
    "中等": 1,
    "较差": 0,
}

THRESHOLD_MIN_RANK = {
    "any": None,
    "good": 2,
    "excellent": 3,
    "perfect": 4,
}

THRESHOLD_LABELS = {
    "any": "不限",
    "good": "良好及以上",
    "excellent": "优秀及以上",
    "perfect": "极好",
}

_CREDIT_RULE_TEXT = {
    "any": "`卖家信用等级` 仅作参考，不得作为否决理由；为“暂无”或缺失时按人工确认处理。",
    "good": "`卖家信用等级` 达到 **'卖家信用良好'** 及以上（良好/优秀/极好）视为满足；仅低于良好时可因信用否决。",
    "excellent": "`卖家信用等级` 达到 **'卖家信用优秀'** 及以上（优秀/极好）视为满足；仅为良好及以下时可因信用否决。",
    "perfect": "`卖家信用等级` 必须为 **'卖家信用极好'**。",
}

_CREDIT_PHRASE = {
    "any": "卖家信用不限",
    "good": "卖家信用良好及以上",
    "excellent": "卖家信用优秀及以上",
    "perfect": "卖家信用极好",
}

_BULLET_LINE_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<marker>(?:[-*+]|\d+[.)、]))[ \t]*(?P<body>.*)$"
)
_SELLER_CREDIT_RE = re.compile(r"卖家信用|seller\s*credit", re.IGNORECASE)


def normalize_seller_credit_min(value: Any) -> str:
    """把任务配置归一化为 any/good/excellent/perfect。"""
    threshold = str(value or "any").strip().lower()
    return threshold if threshold in THRESHOLD_MIN_RANK else "any"


def parse_seller_credit_rank(credit_text: Optional[str]) -> Optional[int]:
    """解析“卖家信用极好/优秀/良好/一般/中等/较差”，无法识别时返回 None。"""
    text = str(credit_text or "").strip()
    if not text or text.lower() in {"暂无", "未知", "无", "none", "null", "n/a"}:
        return None
    for label, rank in CREDIT_RANK_BY_LABEL.items():
        if label in text:
            return rank
    return None


def seller_credit_meets_threshold(credit_text: Optional[str], seller_credit_min: Any) -> bool:
    """信用达到门槛或信息缺失时返回 True（缺失按放行处理）。"""
    threshold = normalize_seller_credit_min(seller_credit_min)
    min_rank = THRESHOLD_MIN_RANK[threshold]
    if min_rank is None:
        return True
    rank = parse_seller_credit_rank(credit_text)
    if rank is None:
        return True
    return rank >= min_rank


def build_credit_rejection_reason(credit_text: Optional[str], seller_credit_min: Any) -> str:
    threshold = normalize_seller_credit_min(seller_credit_min)
    current = str(credit_text or "暂无").strip() or "暂无"
    return (
        f"卖家信用未达门槛（当前：{current}，"
        f"要求：{THRESHOLD_LABELS[threshold]}）。"
    )


def rewrite_seller_credit_rules(criteria_text: str, seller_credit_min: Any) -> str:
    """按任务门槛改写判据正文中的卖家信用硬规则，避免与任务设置冲突。"""
    if not criteria_text:
        return criteria_text
    threshold = normalize_seller_credit_min(seller_credit_min)
    if threshold == "perfect":
        return criteria_text

    rewritten_lines = []
    for raw_line in criteria_text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        newline = raw_line[len(line):]
        rewritten_lines.append(
            _rewrite_credit_line(line, threshold) + newline
        )
    return "".join(rewritten_lines)


def _rewrite_credit_line(line: str, threshold: str) -> str:
    if "卖家信用" not in line and not _SELLER_CREDIT_RE.search(line):
        return line

    matched = _BULLET_LINE_RE.match(line)
    if matched:
        indent = matched.group("indent")
        marker = matched.group("marker")
        body = matched.group("body")
        is_rule = (
            "：" in body
            or ":" in body
            or "必须" in body
            or "keep" in body.lower()
        )
        if is_rule and _SELLER_CREDIT_RE.search(body):
            return f"{indent}{marker} **卖家信用**: {_CREDIT_RULE_TEXT[threshold]}"

    if "卖家信用极好" in line:
        return line.replace("卖家信用极好", _CREDIT_PHRASE[threshold])
    return line


def enforce_seller_credit_result(
    result: Dict[str, Any],
    credit_text: Optional[str],
    seller_credit_min: Any,
) -> Dict[str, Any]:
    """代码兜底：信用低于门槛时强制不推荐；缺失或达到门槛时不干预。"""
    if seller_credit_meets_threshold(credit_text, seller_credit_min):
        return result

    updated = dict(result or {})
    updated["is_recommended"] = False
    reason = str(updated.get("reason") or "").strip()
    prefix = build_credit_rejection_reason(credit_text, seller_credit_min)
    updated["reason"] = f"{prefix}{reason}".strip()
    updated["credit_threshold"] = normalize_seller_credit_min(seller_credit_min)
    updated["seller_credit_text"] = str(credit_text or "").strip()
    return updated
