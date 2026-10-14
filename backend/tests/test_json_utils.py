import pytest
from core.json_utils import extract_json


def test_extract_plain_json():
    result = extract_json('{"key": "value"}')
    assert result == {"key": "value"}


def test_extract_json_with_markdown_fences():
    raw = '```json\n{"key": "value"}\n```'
    result = extract_json(raw)
    assert result == {"key": "value"}


def test_extract_json_with_fence_no_language_tag():
    raw = '```\n{"key": "value"}\n```'
    result = extract_json(raw)
    assert result == {"key": "value"}


def test_extract_json_with_literal_newlines_in_string():
    # Simulates the real failure we hit: LLM emits raw newlines inside a
    # JSON string value instead of escaping them as \n
    raw = '{"code": "line one\nline two\nline three"}'
    result = extract_json(raw)
    assert "code" in result
    assert "line one" in result["code"]


def test_extract_json_strips_surrounding_whitespace():
    raw = '   \n  {"key": "value"}  \n  '
    result = extract_json(raw)
    assert result == {"key": "value"}


def test_extract_json_raises_on_truly_invalid_json():
    with pytest.raises(Exception):
        extract_json("this is not json at all")


def test_extract_json_nested_structure():
    raw = '{"outer": {"inner": [1, 2, 3]}}'
    result = extract_json(raw)
    assert result["outer"]["inner"] == [1, 2, 3]