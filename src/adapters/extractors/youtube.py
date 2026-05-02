import json
import logging
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Match watch?v=, youtu.be/, /shorts/, /embed/, /live/.
YT_RE = re.compile(
    r"^https?://(?:www\.|m\.)?(?:youtube\.com|youtu\.be)/", re.IGNORECASE,
)
YT_ID_RE = re.compile(
    r"(?:v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})",
)

# yt-dlp PR #14078 (Aug 2025) added a fallback: when InnerTube returns
# LOGIN_REQUIRED on datacenter IPs, the watch HTML still embeds a JSON
# blob `var ytInitialData = {...};` containing the full description in
# the engagement panel. This blob is served from the watch URL itself,
# not from /youtubei/v1/player, so it sidesteps the bot-check that kills
# every other approach (oEmbed, og:description, all InnerTube clients).
INITIAL_DATA_RE = re.compile(
    r"var\s+ytInitialData\s*=\s*(\{.+?\})\s*;</script>", re.DOTALL,
)
WATCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


def is_youtube_url(text: str) -> bool:
    return bool(YT_RE.match(text.strip()))


def _extract_video_id(url: str) -> Optional[str]:
    m = YT_ID_RE.search(url)
    return m.group(1) if m else None


def extract_youtube(url: str) -> tuple[Optional[str], str]:
    """Returns (title, body). Two independent endpoints — neither
    requires authentication, and watch-HTML works on VPS IPs where
    InnerTube does not:
      - oEmbed for title + channel name
      - watch HTML's ytInitialData for the full description
    Title falls back to ytInitialData if oEmbed is unreachable.
    """
    title, author = _fetch_oembed(url)

    video_id = _extract_video_id(url)
    initial = _fetch_watch_initial_data(video_id) if video_id else None
    description = _description_from_initial(initial) if initial else ""
    if not title and initial:
        title = _title_from_initial(initial)

    parts: list[str] = []
    if author:
        parts.append(f"Канал: {author}")
    if description:
        parts.append(description)

    return title, "\n\n".join(parts)


def _fetch_oembed(url: str) -> tuple[Optional[str], Optional[str]]:
    try:
        r = httpx.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"},
            timeout=10.0,
        )
        if r.status_code != 200:
            return None, None
        data = r.json()
        return data.get("title"), data.get("author_name")
    except Exception as e:
        logger.warning("youtube oembed failed: %s", e)
        return None, None


def _fetch_watch_initial_data(video_id: str) -> Optional[dict]:
    try:
        r = httpx.get(
            f"https://www.youtube.com/watch?v={video_id}",
            headers=WATCH_HEADERS,
            timeout=15.0,
            follow_redirects=True,
        )
        if r.status_code != 200:
            logger.warning("youtube watch %s: %s", video_id, r.status_code)
            return None
        m = INITIAL_DATA_RE.search(r.text)
        if not m:
            return None
        return json.loads(m.group(1))
    except Exception as e:
        logger.warning("youtube watch fetch failed: %s", e)
        return None


def _description_from_initial(initial: dict) -> str:
    """Walk engagementPanels for the structuredDescriptionContentRenderer
    block — this is the same path yt-dlp uses (#14078)."""
    for panel in initial.get("engagementPanels", []) or []:
        sdcr = (panel.get("engagementPanelSectionListRenderer", {})
                     .get("content", {})
                     .get("structuredDescriptionContentRenderer"))
        if not sdcr:
            continue
        for item in sdcr.get("items", []) or []:
            body = (item.get("expandableVideoDescriptionBodyRenderer", {})
                        .get("attributedDescriptionBodyText") or {})
            content = body.get("content")
            if content:
                return content
    return ""


def _title_from_initial(initial: dict) -> Optional[str]:
    """Fallback title source from videoPrimaryInfoRenderer.title.runs."""
    for content in (initial.get("contents") or {}).get("twoColumnWatchNextResults", {}) \
                                                  .get("results", {}) \
                                                  .get("results", {}) \
                                                  .get("contents", []) or []:
        title_obj = (content.get("videoPrimaryInfoRenderer", {})
                            .get("title") or {})
        runs = title_obj.get("runs") or []
        text = "".join(r.get("text", "") for r in runs)
        if text:
            return text
    return None
