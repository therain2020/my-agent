"""Tests for jsonutil.py — safe JSON extraction from LLM responses."""

import pytest

from therain2020.jsonutil import safe_parse_json


def test_plain_object():
    assert safe_parse_json('{"a": 1}') == {"a": 1}


def test_plain_array():
    assert safe_parse_json('[1, 2, 3]') == [1, 2, 3]


def test_markdown_code_block():
    result = safe_parse_json('```json\n{"x": "y"}\n```')
    assert result == {"x": "y"}


def test_leading_text():
    result = safe_parse_json('Here is the result: {"ok": true}')
    assert result == {"ok": True}


def test_trailing_text():
    result = safe_parse_json('{"ok": true}\nThat is all.')
    assert result == {"ok": True}


def test_nested_braces():
    result = safe_parse_json('{"data": {"nested": [1, {"deep": true}]}}')
    assert result == {"data": {"nested": [1, {"deep": True}]}}


def test_string_with_braces():
    result = safe_parse_json('{"text": "hello { world }"}')
    assert result == {"text": "hello { world }"}


def test_escaped_quotes():
    result = safe_parse_json('{"text": "he said \\"hello\\""}')
    assert result == {"text": 'he said "hello"'}  # account for the escaped quotes
    # Actually the string is: {"text": "he said \"hello\""}
    # After JSON parse, the text value is: he said "hello"


def test_first_object_wins():
    result = safe_parse_json('{"first": 1} {"second": 2}')
    assert result == {"first": 1}


def test_empty_string_raises():
    with pytest.raises(ValueError):
        safe_parse_json("")


def test_no_json_raises():
    with pytest.raises(ValueError):
        safe_parse_json("This is just plain text with no JSON at all")


def test_invalid_json_raises():
    with pytest.raises(ValueError):
        safe_parse_json('{"key": }')
