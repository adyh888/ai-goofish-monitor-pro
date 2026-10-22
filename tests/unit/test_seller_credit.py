"""卖家信用门槛解析、校验与判据改写测试。"""
import pytest

from src.seller_credit import (
    build_credit_rejection_reason,
    enforce_seller_credit_result,
    normalize_seller_credit_min,
    parse_seller_credit_rank,
    rewrite_seller_credit_rules,
    seller_credit_meets_threshold,
)


@pytest.mark.parametrize(
    ("label", "rank"),
    [
        ("卖家信用极好", 4),
        ("卖家信用优秀", 3),
        ("卖家信用良好", 2),
        ("卖家信用一般", 1),
        ("卖家信用中等", 1),
        ("卖家信用较差", 0),
    ],
)
def test_parse_seller_credit_rank(label, rank):
    assert parse_seller_credit_rank(label) == rank


@pytest.mark.parametrize("missing", ["", "暂无", "未知", None, "无"])
def test_parse_seller_credit_rank_missing_returns_none(missing):
    assert parse_seller_credit_rank(missing) is None


def test_normalize_seller_credit_min_fallback():
    assert normalize_seller_credit_min("bad-value") == "any"
    assert normalize_seller_credit_min(None) == "any"
    assert normalize_seller_credit_min("EXCELLENT") == "excellent"


@pytest.mark.parametrize(
    ("credit", "threshold", "expected"),
    [
        ("卖家信用极好", "any", True),
        ("卖家信用优秀", "any", True),
        ("暂无", "good", True),  # 缺失放行
        ("卖家信用较差", "good", False),
        ("卖家信用良好", "good", True),
        ("卖家信用优秀", "excellent", True),
        ("卖家信用良好", "excellent", False),
        ("卖家信用极好", "perfect", True),
        ("卖家信用优秀", "perfect", False),
    ],
)
def test_seller_credit_meets_threshold(credit, threshold, expected):
    assert seller_credit_meets_threshold(credit, threshold) is expected


def test_enforce_credit_result_meets_threshold_unchanged():
    result = {"is_recommended": True, "reason": "ok"}
    assert enforce_seller_credit_result(result, "卖家信用极好", "good") == result


def test_enforce_credit_result_below_threshold_forces_reject():
    result = enforce_seller_credit_result(
        {"is_recommended": True, "reason": "ok"}, "卖家信用一般", "good"
    )
    assert result["is_recommended"] is False
    assert "卖家信用未达门槛" in result["reason"]
    assert result["credit_threshold"] == "good"


def test_enforce_credit_result_missing_credit_passes():
    result = {"is_recommended": True, "reason": "ok"}
    assert enforce_seller_credit_result(result, "暂无", "good") == result


def test_rewrite_credit_rules_any_removes_hard_rule():
    criteria = (
        "2. **一票否决硬性原则**:\n"
        "    * **卖家信用**: 卖家信用等级 必须是 **'卖家信用极好'**。\n"
        "    * **版本要求**: 必须国行。\n"
    )
    rewritten = rewrite_seller_credit_rules(criteria, "any")
    assert "必须是" not in rewritten.split("一票否决")[1].split("版本")[0]
    assert "不得作为否决理由" in rewritten
    assert "必须国行" in rewritten  # 其他规则不受影响


def test_rewrite_credit_rules_perfect_keeps_unchanged():
    criteria = "* **卖家信用**: 卖家信用等级 必须是 **'卖家信用极好'**。"
    assert rewrite_seller_credit_rules(criteria, "perfect") == criteria


def test_rewrite_credit_rules_non_rule_mention_untouched():
    criteria = "卖家画像极为优秀（信用极好、描述诚恳）"
    assert rewrite_seller_credit_rules(criteria, "any") == criteria