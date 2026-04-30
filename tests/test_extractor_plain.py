# tests/test_extractor_plain.py
from src.adapters.extractors.plain import extract_text

def test_extract_text_returns_input():
    assert extract_text("hello") == "hello"
    assert extract_text("  trimmed  ") == "trimmed"
    assert extract_text(None) == ""
