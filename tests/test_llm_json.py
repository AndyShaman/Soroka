import pytest
from src.core.llm_json import parse_loose_json


def test_parses_clean_json_object():
    assert parse_loose_json('{"clean_query": "x", "kind": null}') == {
        "clean_query": "x", "kind": None,
    }


def test_parses_clean_json_array():
    assert parse_loose_json("[1, 2, 3]") == [1, 2, 3]


def test_strips_json_fence():
    """Gemini and other models often ignore 'JSON only' instructions and
    wrap their output in ```json ... ``` fences. Strip them transparently."""
    raw = '```json\n{"clean_query": "x", "kind": null}\n```'
    assert parse_loose_json(raw) == {"clean_query": "x", "kind": None}


def test_strips_unlabelled_fence():
    raw = '```\n[5, 8, 3]\n```'
    assert parse_loose_json(raw) == [5, 8, 3]


def test_extracts_json_from_chatty_response():
    """Sometimes the model adds a friendly preamble. Pull out the first
    well-formed JSON block."""
    raw = 'Here is your result:\n{"clean_query": "паста", "kind": null}\nHope this helps!'
    assert parse_loose_json(raw) == {"clean_query": "паста", "kind": None}


def test_extracts_array_after_explanation():
    raw = 'After ranking the candidates: [3, 7, 1]'
    assert parse_loose_json(raw) == [3, 7, 1]


def test_none_raises():
    """openrouter.complete sometimes returns None when a model refuses."""
    with pytest.raises(ValueError, match="None"):
        parse_loose_json(None)


def test_empty_string_raises():
    with pytest.raises(ValueError, match="empty"):
        parse_loose_json("")


def test_pure_garbage_raises():
    with pytest.raises(ValueError, match="no JSON"):
        parse_loose_json("Sorry, I can't do that.")
