# tests/test_extractor_web.py
from src.adapters.extractors.web import is_url, extract_web, find_first_url

def test_is_url_basic():
    assert is_url("https://example.com")
    assert is_url("http://x.org/a/b")
    assert not is_url("hello")
    assert not is_url("file://etc/passwd")  # only http(s)


def test_find_first_url_returns_none_on_plain_text():
    assert find_first_url("hello world") is None


def test_find_first_url_extracts_embedded():
    assert find_first_url(
        "Пробовали https://github.com/garrytan/gstack ?"
    ) == "https://github.com/garrytan/gstack"


def test_find_first_url_strips_trailing_punct():
    """Common typing pattern: "see https://foo.com/bar." — the period
    belongs to the sentence, not the URL."""
    assert find_first_url("see https://foo.com/bar.") == "https://foo.com/bar"
    assert find_first_url("see https://foo.com/bar?") == "https://foo.com/bar"
    assert find_first_url("(https://foo.com/bar)") == "https://foo.com/bar"


def test_find_first_url_returns_first_of_many():
    assert find_first_url(
        "compare https://a.com/x and https://b.com/y"
    ) == "https://a.com/x"

def test_extract_web_uses_trafilatura(monkeypatch):
    monkeypatch.setattr(
        "src.adapters.extractors.web._safe_fetch",
        lambda url: "<html><body><p>article body</p></body></html>",
    )
    monkeypatch.setattr(
        "src.adapters.extractors.web.trafilatura.extract",
        lambda html, **kw: "article body",
    )
    title, text = extract_web("https://example.com/x")
    assert "article body" in text


def test_extract_web_blocks_loopback_url(monkeypatch):
    """A URL that resolves to 127.0.0.1 must not reach the network — the
    SSRF guard should swallow it and return empty text so ingestion
    silently falls back to plain-text storage."""
    monkeypatch.setattr(
        "src.adapters.extractors.web.socket.getaddrinfo",
        lambda host, port: [(0, 0, 0, "", ("127.0.0.1", 0))],
    )
    title, text = extract_web("http://internal.example/x")
    assert title is None
    assert text == ""


def test_extract_web_blocks_private_ip_url(monkeypatch):
    monkeypatch.setattr(
        "src.adapters.extractors.web.socket.getaddrinfo",
        lambda host, port: [(0, 0, 0, "", ("192.168.1.5", 0))],
    )
    title, text = extract_web("http://router.local/admin")
    assert (title, text) == (None, "")


def test_extract_web_rejects_non_http_scheme():
    """file:// URLs must not be fetched even if the regex accepted them
    upstream — defence in depth in case find_first_url is bypassed."""
    title, text = extract_web("file:///etc/passwd")
    assert (title, text) == (None, "")


def test_extract_web_rejects_userinfo():
    title, text = extract_web("http://user:pass@example.com/")
    assert (title, text) == (None, "")
