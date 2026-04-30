# tests/test_extractor_youtube.py
from src.adapters.extractors.youtube import is_youtube_url

def test_is_youtube_url_variations():
    assert is_youtube_url("https://www.youtube.com/watch?v=abc")
    assert is_youtube_url("https://youtu.be/abc")
    assert is_youtube_url("https://m.youtube.com/watch?v=abc")
    assert not is_youtube_url("https://example.com/watch?v=abc")
