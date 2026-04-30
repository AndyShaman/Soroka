# tests/test_extractor_web.py
from src.adapters.extractors.web import is_url, extract_web

def test_is_url_basic():
    assert is_url("https://example.com")
    assert is_url("http://x.org/a/b")
    assert not is_url("hello")
    assert not is_url("file://etc/passwd")  # only http(s)

def test_extract_web_uses_trafilatura(monkeypatch):
    monkeypatch.setattr(
        "src.adapters.extractors.web.trafilatura.fetch_url",
        lambda url, **kw: "<html><body><p>article body</p></body></html>",
    )
    monkeypatch.setattr(
        "src.adapters.extractors.web.trafilatura.extract",
        lambda html, **kw: "article body",
    )
    title, text = extract_web("https://example.com/x")
    assert "article body" in text
