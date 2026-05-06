import re
import trafilatura

URL_RE = re.compile(r"^https?://", re.IGNORECASE)

# Match an http(s) URL anywhere in the text. URLs end at whitespace.
_URL_FIND_RE = re.compile(r"https?://\S+", re.IGNORECASE)
# Trailing punctuation that's almost never part of the URL itself: people
# write "see https://foo.com/bar?" or end a sentence with a period.
_URL_TRAIL = "?.,!;:()[]<>«»\""


def is_url(text: str) -> bool:
    return bool(URL_RE.match(text.strip()))


def find_first_url(text: str) -> str | None:
    """Return the first http(s) URL embedded in `text`, or None.

    Trims trailing punctuation so "see https://foo.com/bar?" resolves to
    "https://foo.com/bar" — the question mark belongs to the surrounding
    sentence, not to the URL.
    """
    m = _URL_FIND_RE.search(text)
    if m is None:
        return None
    return m.group(0).rstrip(_URL_TRAIL)


def extract_web(url: str) -> tuple[str | None, str]:
    """Returns (title, body_text)."""
    html = trafilatura.fetch_url(url)
    if not html:
        return None, ""
    text = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
    metadata = trafilatura.extract_metadata(html)
    title = metadata.title if metadata else None
    return title, text
