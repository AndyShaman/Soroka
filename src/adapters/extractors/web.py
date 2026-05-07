import ipaddress
import re
import socket
from urllib.parse import urlparse

import httpx
import trafilatura

URL_RE = re.compile(r"^https?://", re.IGNORECASE)

# Match an http(s) URL anywhere in the text. URLs end at whitespace.
_URL_FIND_RE = re.compile(r"https?://\S+", re.IGNORECASE)
# Trailing punctuation that's almost never part of the URL itself: people
# write "see https://foo.com/bar?" or end a sentence with a period.
_URL_TRAIL = "?.,!;:()[]<>«»\""

# SSRF / DoS guards for the web fetcher. Limits picked to fit a personal
# knowledge-base bot: articles rarely exceed 5 MB, and a 10 s budget is
# generous before we'd rather give up than block the ingest pipeline.
_MAX_BYTES = 5 * 1024 * 1024
_TIMEOUT = 10.0
_MAX_REDIRECTS = 5


class UnsafeURL(Exception):
    """Raised when a URL targets internal/private infrastructure or
    otherwise fails the safety check. Treated as a soft failure by the
    extractor (returns no text) so the caller still ingests the message."""


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


def _check_url_safety(url: str) -> None:
    """Reject URLs that would let a remote message hit the bot's own
    network: non-HTTP schemes, embedded credentials, hosts that resolve
    to private/loopback/link-local/multicast/reserved/unspecified IPs.

    Note: this is a check-once guard. A hostile resolver could still
    flip its answer between this call and httpx's connect (TOCTOU), but
    for a single-owner personal bot the check protects against the only
    realistic threat — accidentally pasting an internal URL.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise UnsafeURL(f"unsupported scheme: {parsed.scheme!r}")
    if parsed.username or parsed.password:
        raise UnsafeURL("URL must not contain credentials")
    host = parsed.hostname
    if not host:
        raise UnsafeURL("URL must have a host")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise UnsafeURL(f"DNS resolution failed: {e}")
    for info in infos:
        ip_str = info[4][0]
        try:
            addr = ipaddress.ip_address(ip_str)
        except ValueError as e:
            raise UnsafeURL(f"unparseable IP from DNS: {ip_str!r}") from e
        if (addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_multicast or addr.is_reserved
                or addr.is_unspecified):
            raise UnsafeURL(f"host resolves to internal IP: {ip_str}")


def _safe_fetch(url: str) -> str | None:
    """Fetch `url` with a per-hop safety check, capped body size, and
    timeout. Returns the response body as text (best-effort decoded), or
    None on a non-200 response. Raises UnsafeURL when any hop targets
    internal infra or the response exceeds the size cap."""
    current = url
    for _ in range(_MAX_REDIRECTS + 1):
        _check_url_safety(current)
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=False) as client:
            with client.stream("GET", current) as resp:
                if resp.is_redirect:
                    location = resp.headers.get("location")
                    if not location:
                        return None
                    current = str(httpx.URL(current).join(location))
                    continue
                if resp.status_code != 200:
                    return None
                buf = bytearray()
                for chunk in resp.iter_bytes():
                    buf.extend(chunk)
                    if len(buf) > _MAX_BYTES:
                        raise UnsafeURL("response exceeds max body size")
                encoding = resp.encoding or "utf-8"
                return bytes(buf).decode(encoding, errors="replace")
    raise UnsafeURL("too many redirects")


def extract_web(url: str) -> tuple[str | None, str]:
    """Returns (title, body_text). On any safety/HTTP failure returns
    (None, "") so the caller can fall back to plain-text ingestion."""
    try:
        html = _safe_fetch(url)
    except (UnsafeURL, httpx.HTTPError):
        return None, ""
    if not html:
        return None, ""
    text = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
    metadata = trafilatura.extract_metadata(html)
    title = metadata.title if metadata else None
    return title, text
