import asyncio

import pytest

import src.prompt_utils as prompt_utils
from src.services.ai_response_parser import EmptyAIResponseError


def test_generate_criteria_closes_ai_client_after_success(monkeypatch, tmp_path):
    close_state = {"closed": False}
    reference_file = tmp_path / "reference.txt"
    reference_file.write_text("reference", encoding="utf-8")

    class FakeAIClient:
        def is_available(self):
            return True

        def refresh(self):
            raise AssertionError("refresh should not be called")

        async def _call_ai(self, *_args, **_kwargs):
            return "generated criteria"

        async def close(self):
            close_state["closed"] = True

    monkeypatch.setattr(prompt_utils, "AIClient", FakeAIClient)

    result = asyncio.run(
        prompt_utils.generate_criteria("need a gpu", str(reference_file))
    )

    assert result == "generated criteria"
    assert close_state["closed"] is True


def test_generate_criteria_closes_ai_client_after_ai_failure(monkeypatch, tmp_path):
    close_state = {"closed": False}
    reference_file = tmp_path / "reference.txt"
    reference_file.write_text("reference", encoding="utf-8")

    class FakeAIClient:
        def is_available(self):
            return True

        def refresh(self):
            raise AssertionError("refresh should not be called")

        async def _call_ai(self, *_args, **_kwargs):
            raise EmptyAIResponseError("AI响应内容为空。")

        async def close(self):
            close_state["closed"] = True

    monkeypatch.setattr(prompt_utils, "AIClient", FakeAIClient)

    with pytest.raises(EmptyAIResponseError, match="AI响应内容为空"):
        asyncio.run(prompt_utils.generate_criteria("need a gpu", str(reference_file)))

    assert close_state["closed"] is True


@pytest.mark.parametrize(
    ("threshold", "expected"),
    [
        ("any", "禁止因为卖家信用等级"),
        ("good", "良好及以上"),
        ("excellent", "优秀及以上"),
        ("perfect", "极好"),
    ],
)
def test_apply_seller_credit_override_appends_rule(threshold, expected):
    result = prompt_utils.apply_seller_credit_override("BASE PROMPT", threshold)

    assert result.startswith("BASE PROMPT")
    assert expected in result
    assert "最高优先级" in result


def test_apply_seller_credit_override_keeps_empty_prompt():
    assert prompt_utils.apply_seller_credit_override("", "excellent") == ""
