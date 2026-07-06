import json

import pytest

from app.llm.client import parse_json


def test_plain_json():
    assert parse_json('{"a": 1}') == {"a": 1}


def test_markdown_fenced_json():
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_json_with_surrounding_prose():
    assert parse_json('Sure! Here you go: {"a": 1} Hope that helps.') == {"a": 1}


def test_garbage_raises():
    with pytest.raises(json.JSONDecodeError):
        parse_json("no json here at all")
