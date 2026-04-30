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
