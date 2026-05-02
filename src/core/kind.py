from src.adapters.extractors.web import is_url
from src.adapters.extractors.youtube import is_youtube_url


def detect_kind_from_text(text: str) -> str:
    s = text.strip()
    if is_youtube_url(s):
        return "youtube"
    if is_url(s):
        return "web"
    return "text"


def detect_kind_from_message(msg) -> str:
    """msg is a telegram.Message."""
    if msg.voice:
        return "voice"
    if msg.photo:
        # A forwarded Telegram post often arrives as a photo with the entire
        # post text in caption — treating it as a plain image throws away
        # the actual content. If the caption looks like a real post (has
        # length or contains a URL), classify as 'post'; otherwise it's a
        # genuine snapshot/screenshot and stays 'image'.
        if _is_post_caption(msg.caption):
            return "post"
        return "image"
    if msg.document:
        name = (msg.document.file_name or "").lower()
        if name.endswith(".pdf"):
            return "pdf"
        if name.endswith(".docx"):
            return "docx"
        if name.endswith(".xlsx") or name.endswith(".xls"):
            return "xlsx"
    if msg.text:
        return detect_kind_from_text(msg.text)
    if msg.caption and (msg.text is None):
        return detect_kind_from_text(msg.caption)
    return "text"


def _is_post_caption(caption: str | None) -> bool:
    """A caption is post-like if it carries real content rather than a
    short label. Threshold is length-based with a URL escape: a single
    URL is enough (it implies the photo is just a preview)."""
    if not caption:
        return False
    text = caption.strip()
    if not text:
        return False
    # 30 chars empirically separates "котики" / "вид из окна" (short labels
    # for genuine images) from "Tencent Cloud сервачок за $10..." (posts).
    if len(text) >= 30:
        return True
    if "http://" in text or "https://" in text:
        return True
    return False
