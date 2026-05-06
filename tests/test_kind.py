# tests/test_kind.py
from unittest.mock import MagicMock

from src.core.kind import detect_kind_from_text, detect_kind_from_message

def test_detect_text():
    assert detect_kind_from_text("just thinking aloud") == "text"

def test_detect_youtube():
    assert detect_kind_from_text("https://youtu.be/dQw4w9WgXcQ") == "youtube"

def test_detect_web():
    assert detect_kind_from_text("https://example.com/article") == "web"


def test_detect_short_wrapped_url_is_web():
    """Two words around a URL — short enough that the extractor should
    pull the article. Otherwise the link's vocabulary stays unsearchable."""
    assert detect_kind_from_text(
        "Пробовали https://github.com/garrytan/gstack ?"
    ) == "web"


def test_detect_short_wrapped_youtube_is_youtube():
    """Same threshold applies to YouTube links."""
    assert detect_kind_from_text(
        "глянь https://youtu.be/dQw4w9WgXcQ что думаешь"
    ) == "youtube"


def test_detect_url_at_word_threshold_still_extracts():
    """10-word boundary is inclusive — a 10-word note around a URL still
    extracts. 11+ words is treated as prose that mentions a URL."""
    ten_words = "один два три четыре пять шесть семь восемь девять https://example.com/x"
    assert len(ten_words.split()) == 10
    assert detect_kind_from_text(ten_words) == "web"


def test_detect_url_above_threshold_stays_text():
    """Long prose that happens to cite a URL is a regular note, not a
    link card. We don't want the extractor pulling random sites that the
    user merely referenced in a longer thought."""
    eleven_words = (
        "один два три четыре пять шесть семь восемь девять десять "
        "https://example.com/x"
    )
    assert len(eleven_words.split()) == 11
    assert detect_kind_from_text(eleven_words) == "text"


def _msg(*, photo=False, caption=None, text=None):
    m = MagicMock()
    m.voice = None
    m.document = None
    m.photo = [MagicMock()] if photo else None
    m.text = text
    m.caption = caption
    return m


def test_photo_with_long_caption_is_post():
    """Forwarded Telegram post: 1 preview photo + caption full of content.
    Must classify as 'post' so caption becomes the searchable body."""
    m = _msg(photo=True, caption=(
        "Warp отдали в Open Source (!!!) Omfg. Неожиданно. "
        "Это тот самый терминал, который стал агентной средой!"
    ))
    assert detect_kind_from_message(m) == "post"


def test_photo_with_url_caption_is_post():
    """Even a short caption with a link (typical for re-shares) means
    the photo is a preview — treat the message as a post."""
    m = _msg(photo=True, caption="https://github.com/warpdotdev/warp")
    assert detect_kind_from_message(m) == "post"


def test_photo_with_short_label_caption_stays_image():
    """Genuine snapshot the user labelled — no URL, short caption."""
    m = _msg(photo=True, caption="вид из окна")
    assert detect_kind_from_message(m) == "image"


def test_photo_without_caption_stays_image():
    m = _msg(photo=True, caption=None)
    assert detect_kind_from_message(m) == "image"
