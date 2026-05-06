from src.adapters.extractors.web import find_first_url
from src.adapters.extractors.youtube import is_youtube_url

# A short message wrapped around a single link ("Пробовали https://...?",
# "интересный пост https://...") should be treated as a link card so the
# extractor pulls the article text. Without this, the URL stays as a bare
# string in `content` and search can't surface it by its own keywords.
# 10 words covers typical "comment + link" snippets but stops short of
# becoming a heuristic for genuine prose that happens to cite a URL.
_URL_WRAP_WORD_LIMIT = 10


def detect_kind_from_text(text: str) -> str:
    s = text.strip()
    url = find_first_url(s)
    if url is None:
        return "text"
    if len(s.split()) > _URL_WRAP_WORD_LIMIT:
        return "text"
    if is_youtube_url(url):
        return "youtube"
    return "web"


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
