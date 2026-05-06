"""Shared formatter for search-result cards.

`search.py` (initial render) and `search_callbacks.py` (pagination /
re-render after period change / exclusion) both display the same kind
of card. Keeping the implementation here means the two handlers can't
silently drift apart.

Public entry point: ``format_hit(note)``.
The other helpers are exposed only for tests.
"""

import re

from src.core.links import message_link

# Telegram file-id-style titles like "photo_AQADlhJrG72ZqEt-.jpg" or
# "document_42.pdf" — these are placeholders we generated when no caption
# was supplied, never anything the user typed.
_FILE_ID_TITLE_RE = re.compile(r"^(photo_|file_|document_)", re.IGNORECASE)

# Bare file names: "notebooklm_script_v3_final.md.pdf", "IMG_*.JPG", etc.
# Match strings that consist only of file-name-safe characters and end in
# a known extension; treat them as junk titles.
_FILE_NAME_TITLE_RE = re.compile(
    r"^[\w.\- ]+\."
    r"(pdf|md|docx|xlsx|txt|jpg|jpeg|png|mp3|ogg|opus|wav|mp4)$",
    re.IGNORECASE,
)

# Characters that count as bullet decoration when they appear at the very
# start of a line. We strip up to two of these (separated by whitespace)
# so visually busy posts ("⚪🔵 …") get tidied without eating real content.
_BULLET_EMOJIS = "⚪🔵🔴🟢🟡🟠🟣🟤⚫▪◼◻●○•◦►▶→⇒➤"
# Variation selectors and the U+FE0F emoji-presentation marker frequently
# accompany the squares (▪️/◼️/◻️/▫️) — strip them too.
_BULLET_TRAILERS = "️⃣"
_LEADING_BULLET_RE = re.compile(
    rf"^[{re.escape(_BULLET_EMOJIS)}▫{_BULLET_TRAILERS}]"
    rf"[{_BULLET_TRAILERS}]*\s*"
)

# Separator chars to strip between a stripped duplicate title and the
# remaining snippet body.
_SEPARATOR_CHARS = " .,:;—–-"

_SENTENCE_BOUNDARY_RE = re.compile(r"[.!?\n]")


def _clean_title(raw: str | None) -> str:
    """Drop junk titles (file-id placeholders, bare file names); cap real
    titles at 80 chars."""
    title = (raw or "").strip()
    if not title:
        return ""
    if _FILE_ID_TITLE_RE.match(title):
        return ""
    if _FILE_NAME_TITLE_RE.match(title):
        return ""
    return title[:80]


def _strip_leading_bullets(line: str) -> str:
    """Remove up to two leading bullet-emoji tokens (Fix #5)."""
    s = line
    for _ in range(2):
        m = _LEADING_BULLET_RE.match(s)
        if not m:
            break
        s = s[m.end():]
    return s


def _clean_snippet(raw: str) -> str:
    """OCR output is often visually noisy: 1-char lines, repeated blank
    lines, leading punctuation, leading bullet emojis. Squash that for
    display only — the raw content stays in the DB unchanged."""
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if not s:
            continue
        s = _strip_leading_bullets(s).strip()
        if not s:
            continue
        # Drop orphan single-character lines (OCR artefacts: "к", "-", "=").
        if len(s) <= 2 and not s.isalnum():
            continue
        if len(s) == 1:
            continue
        lines.append(s)
    return " ".join(lines)


def _first_meaningful_line(content: str) -> str:
    """Derive a synthetic title from the first sentence-or-line of cleaned
    content. Used when the real title is missing or junk (Fix #3)."""
    cleaned = _clean_snippet(content)
    if not cleaned:
        return ""
    # Find the earliest sentence-ending boundary, capped at 100 chars.
    head = cleaned[:100]
    m = _SENTENCE_BOUNDARY_RE.search(head)
    cut = m.start() if m else len(head)
    return head[:cut].strip()


def _strip_title_prefix(snippet: str, title: str) -> str:
    """If `snippet` starts with `title` (case-sensitive), drop the title
    plus any leading separators (Fix #1)."""
    if not title or not snippet.startswith(title):
        return snippet
    rest = snippet[len(title):]
    return rest.lstrip(_SEPARATOR_CHARS).lstrip()


def _find_url_span(text: str, pos: int) -> tuple[int, int] | None:
    """If `pos` falls inside an http(s) URL in `text`, return that URL's
    (start, end) span; otherwise None. URL ends at the next whitespace."""
    # Search every URL once; in display strings there are usually 0–2.
    for m in re.finditer(r"https?://", text):
        start = m.start()
        # URL ends at the next whitespace char (or EOS).
        ws = re.search(r"\s", text[m.end():])
        end = m.end() + ws.start() if ws else len(text)
        if start <= pos < end:
            return (start, end)
    return None


def _truncate_smart(text: str, limit: int = 200) -> str:
    """Cut `text` to <= limit chars without splitting words or URLs (Fix #4).

    1. If text fits, return as-is.
    2. Otherwise walk back from `limit` to the last whitespace.
    3. If that cut lands inside an http(s) URL, move the cut to the start
       of that URL — drop the partial URL entirely.
    4. Append a Unicode horizontal ellipsis.
    """
    if len(text) <= limit:
        return text

    cut = limit
    # If `limit` itself sits inside a URL, retreat to the URL's start.
    span = _find_url_span(text, cut)
    if span is not None:
        cut = span[0]
    else:
        # Walk back to the last whitespace at or before `cut`.
        ws_idx = text.rfind(" ", 0, cut)
        if ws_idx > 0:
            cut = ws_idx
        # After that retreat, re-check for URL containment in case the
        # whitespace landed inside one (rare, but possible).
        span = _find_url_span(text, cut)
        if span is not None:
            cut = span[0]

    head = text[:cut].rstrip(_SEPARATOR_CHARS).rstrip()
    return f"{head}…"


# Per-card body cap, chosen so 5 cards fit Telegram's 4096-char limit
# with comfortable margin. Source-url row eats ~80-110 chars of header
# space, so the default body cap dropped from 700 → 620 to stay within
# the same total per-card envelope (5 × 620 + separators ≈ 3.2 KB).
_BODY_CAP_DEFAULT = 620
# With a Russian summary (≤200 chars) AND a source-url row, the body
# shrinks further: 620 - 200 = 420.
_BODY_CAP_WITH_SUMMARY = 420
# Hard cap on the source_url row so a pathological URL with a long
# query string can't blow the per-card budget.
_SOURCE_URL_MAX = 110


def _format_source_url(raw: str | None, message_link_url: str) -> str:
    """Return the row to render for the note's external URL, or empty.

    Skipped when the note has no source_url, when it equals the Telegram
    message link (already shown), or when it is just a `tg://` deep link.
    Long URLs are hard-clipped at `_SOURCE_URL_MAX` so a pathological
    query string can't break the per-card budget.
    """
    url = (raw or "").strip()
    if not url or url == message_link_url:
        return ""
    if len(url) > _SOURCE_URL_MAX:
        url = url[:_SOURCE_URL_MAX - 1].rstrip() + "…"
    return url


def format_hit(note) -> str:
    """Render one search-result card.

    Format: kind tag, Telegram link, optional source URL (when the post
    pointed to an external page), optional Russian summary (for foreign-
    language URL captures), full text body. The source URL row helps the
    reader recognise where a captured link points without scrolling
    through the body — important when the body is the extracted article
    text and never repeats the URL itself.

    Per-card body is capped so five cards comfortably fit Telegram's
    4096-char message limit. The cap shrinks when a summary row eats
    into that budget."""
    link = message_link(note.tg_chat_id, note.tg_message_id)
    header = f"📌 [{note.kind}]"
    source_url_row = _format_source_url(getattr(note, "source_url", None), link)
    ru_summary = (getattr(note, "ru_summary", None) or "").strip()
    body_cap = _BODY_CAP_WITH_SUMMARY if ru_summary else _BODY_CAP_DEFAULT
    body = _truncate_smart(_clean_snippet(note.content or ""), limit=body_cap)

    parts = [header, link]
    if source_url_row:
        parts.append(source_url_row)
    if ru_summary:
        parts.append(f"🇷🇺 {ru_summary}")
    if body:
        parts.append(body)
    return "\n".join(parts)
