import re
import trafilatura

URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def is_url(text: str) -> bool:
    return bool(URL_RE.match(text.strip()))


def extract_web(url: str) -> tuple[str | None, str]:
    """Returns (title, body_text)."""
    html = trafilatura.fetch_url(url)
    if not html:
        return None, ""
    text = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
    metadata = trafilatura.extract_metadata(html)
    title = metadata.title if metadata else None
    return title, text
