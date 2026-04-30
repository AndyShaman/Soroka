# tests/test_kind.py
from src.core.kind import detect_kind_from_text, detect_kind_from_message

def test_detect_text():
    assert detect_kind_from_text("just thinking aloud") == "text"

def test_detect_youtube():
    assert detect_kind_from_text("https://youtu.be/dQw4w9WgXcQ") == "youtube"

def test_detect_web():
    assert detect_kind_from_text("https://example.com/article") == "web"
