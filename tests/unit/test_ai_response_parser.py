import pytest

from src.services.ai_response_parser import (
    extract_ai_response_content,
    parse_ai_response_json,
    EmptyAIResponseError,
)


def test_parse_ai_response_json_uses_first_object_when_multiple_json_objects_are_concatenated():
    content = """```json
{"is_recommended": true, "reason": "first"}
{"is_recommended": false, "reason": "second"}
```"""

    result = parse_ai_response_json(content)

    assert result == {"is_recommended": True, "reason": "first"}


def test_parse_ai_response_json_extracts_json_from_wrapped_text():
    content = """分析结果如下：

```json
{"is_recommended": true, "reason": "wrapped"}
```

请按第一份结果处理。"""

    result = parse_ai_response_json(content)

    assert result == {"is_recommended": True, "reason": "wrapped"}


def test_parse_ai_response_json_raises_when_no_json_exists():
    with pytest.raises(ValueError):
        parse_ai_response_json("没有任何 JSON 内容")


def test_parse_ai_response_json_repairs_missing_trailing_brace():
    """回归：DeepSeek json_object 模式偶发丢右括号，补齐后应拿到完整结果而非片段。"""
    content = (
        '{"prompt_version":"V1","is_recommended":false,"reason":"不推荐",'
        '"risk_tags":["容量不符"],"criteria_analysis":{"seller_type":{"status":"PASS"}}'
    )

    result = parse_ai_response_json(content)

    assert result["is_recommended"] is False
    assert result["criteria_analysis"]["seller_type"]["status"] == "PASS"
    assert result["risk_tags"] == ["容量不符"]


def test_parse_ai_response_json_repairs_multiple_missing_closers():
    content = (
        '{"is_recommended":true,"reason":"ok",'
        '"risk_tags":[],'
        '"criteria_analysis":{"seller_type":{"status":"PASS"}'
    )

    result = parse_ai_response_json(content)

    assert result["is_recommended"] is True
    assert result["criteria_analysis"]["seller_type"]["status"] == "PASS"


def test_parse_ai_response_json_does_not_repair_broken_structure():
    """引号未闭合/括号交错等真损坏不应被“修复”，保持既有失败行为。"""
    with pytest.raises(ValueError):
        parse_ai_response_json('{"is_recommended":false,"reason":"字符串没闭合')

    with pytest.raises(ValueError):
        parse_ai_response_json('{"a":]}')


def test_parse_ai_response_json_repair_only_adopted_with_marker_keys():
    """补齐出的对象必须含结果特征字段才采纳，否则维持原片段兜底契约。"""
    content = '{"foo": {"bar": 1}'

    result = parse_ai_response_json(content)

    # 不含特征字段 → 不采纳修复结果，按原契约返回第一个可解析片段
    assert result == {"bar": 1}


def test_extract_ai_response_content_with_none_content_but_valid_reasoning_content():
    """当 content 为 None 但 reasoning_content 有值时，应该成功提取 reasoning_content 的内容"""
    # 创建 mock 对象模拟 OpenAI 风格的响应
    message = type('Message', (), {
        'content': None,
        'reasoning_content': '这是推理内容'
    })()
    choice = type('Choice', (), {'message': message})()
    response = type('Response', (), {'choices': [choice]})()

    result = extract_ai_response_content(response)

    assert result == '这是推理内容'


def test_extract_ai_response_content_raises_when_content_and_reasoning_content_are_empty():
    """当 content 和 reasoning_content 都为空时，应该抛出 EmptyAIResponseError"""
    # 创建 mock 对象
    message = type('Message', (), {
        'content': None,
        'reasoning_content': None
    })()
    choice = type('Choice', (), {'message': message})()
    response = type('Response', (), {'choices': [choice]})()

    with pytest.raises(EmptyAIResponseError):
        extract_ai_response_content(response)
