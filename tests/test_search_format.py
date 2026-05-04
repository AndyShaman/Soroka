from src.bot.handlers._search_format import (
    _clean_title,
    _clean_snippet,
    _truncate_smart,
    format_hit,
)
from src.core.models import Note


# ---------- _clean_title ---------------------------------------------------

def test_clean_title_drops_file_ids():
    """photo_AQADlhJrG72ZqEt-.jpg is the Telegram file-id we picked when
    no caption was provided — useless to show to the user."""
    assert _clean_title("photo_AQADlhJrG72ZqEt-.jpg") == ""
    assert _clean_title("file_55.jpg") == ""
    assert _clean_title("document_42.pdf") == ""


def test_clean_title_keeps_real_titles():
    assert _clean_title("Чиабатта без замеса") == "Чиабатта без замеса"


def test_clean_title_handles_empty():
    assert _clean_title(None) == ""
    assert _clean_title("") == ""


def test_clean_title_drops_pdf_filename():
    """Fix #2 — bare file names are junk titles, drop them so the synthetic
    title from content can take over."""
    assert _clean_title("notebooklm_script_v3_final.md.pdf") == ""


def test_clean_title_drops_image_filename():
    """Case-insensitive: IMG_*.JPG is just as junky as img_*.jpg."""
    assert _clean_title("IMG_20240101_153045.JPG") == ""


def test_clean_title_keeps_normal_title():
    """Real headings with a colon must survive — only bare file names go."""
    assert _clean_title("Сценарий: NotebookLM") == "Сценарий: NotebookLM"


# ---------- _clean_snippet -------------------------------------------------

def test_clean_snippet_collapses_ocr_noise():
    """Tesseract output for stylized images often looks like
    'к\\n-\\n=\\n\\nextreme\\n\\nBag OT клещей' — orphan symbols and
    blank lines should be hidden in the snippet, not stored differently."""
    raw = "к\n-\n=\n\nextreme\n\nBag OT клещей\n\nдля обработки\nодежды"
    cleaned = _clean_snippet(raw)
    assert cleaned == "extreme Bag OT клещей для обработки одежды"


def test_clean_snippet_keeps_normal_text():
    raw = "Warp отдали в Open Source\n\nЭто тот самый терминал."
    cleaned = _clean_snippet(raw)
    assert cleaned == "Warp отдали в Open Source Это тот самый терминал."


def test_clean_snippet_strips_leading_bullet_emoji():
    """Fix #5 — bullet-emojis at start of a line are formatting, not content."""
    cleaned = _clean_snippet("⚪ Tencent Cloud is great\n🔵 second line")
    assert cleaned == "Tencent Cloud is great second line"


# ---------- _truncate_smart ------------------------------------------------

def test_truncate_smart_short_text_unchanged():
    """Fix #4 — short text (<= limit) returned verbatim."""
    assert _truncate_smart("hello world", limit=200) == "hello world"


def test_truncate_smart_breaks_on_word_boundary():
    """Fix #4 — never split a word; cut at the last whitespace before limit."""
    text = "раз два три четыре пять шесть семь восемь девять автор книги"
    # Position past the start of "книги" so cutting at limit lands inside it.
    limit = text.index("книги") + 3  # mid-word "книг"
    out = _truncate_smart(text, limit=limit)
    assert out.endswith("…")
    assert "книг" not in out  # no mid-word "книг…"
    assert out.rstrip("…").rstrip().endswith("автор")


def test_truncate_smart_does_not_split_url():
    """Fix #4 — if cut would land inside a URL, drop the URL entirely."""
    text = "see https://github.com/warpdotdev/warp/issues/123 for more"
    out = _truncate_smart(text, limit=30)
    assert out.endswith("…")
    assert "github.com" not in out
    assert "https://" not in out
    assert out.startswith("see")


# ---------- format_hit -----------------------------------------------------

def test_format_hit_omits_snippet_line_when_empty():
    note = Note(
        id=1, owner_id=1, tg_chat_id=-100, tg_message_id=1,
        kind="image", title=None, content="",
        created_at=1,
    )
    out = format_hit(note)
    lines = out.splitlines()
    # Two lines only: header + link, no trailing empty snippet line.
    assert len(lines) == 2
    assert lines[0].startswith("📌 [image]")
    assert "(без подписи)" in lines[0]


def test_format_hit_falls_back_to_content_when_title_is_file_id():
    """Image without caption: title is a file-id, content has OCR text.
    The synthetic title must come from the first meaningful line of content,
    NOT from the literal '(без подписи)' placeholder."""
    note = Note(
        id=2, owner_id=1, tg_chat_id=-100, tg_message_id=484,
        kind="image", title="photo_AQADlhJrG72ZqEt-.jpg",
        content="к\n-\n=\n\nextreme\n\nBag OT клещей",
        created_at=1,
    )
    out = format_hit(note)
    assert "photo_AQADlhJrG72ZqEt" not in out
    assert "(без подписи)" not in out
    assert "extreme" in out


def test_format_hit_drops_duplicate_title_prefix():
    """Fix #1 — when content starts with the title, strip it from snippet."""
    note = Note(
        id=3, owner_id=1, tg_chat_id=-100, tg_message_id=10,
        kind="post", title="POV: Claude перенёсся на 6 месяцев вперёд",
        content=(
            "POV: Claude перенёсся на 6 месяцев вперёд и рассказал, "
            "почему твой следующий шаг уже провалился."
        ),
        created_at=1,
    )
    out = format_hit(note)
    lines = out.splitlines()
    # Snippet line is the third one (header, link, snippet).
    assert len(lines) == 3
    snippet = lines[2]
    assert not snippet.startswith("POV:")
    assert snippet.startswith("и рассказал")


def test_format_hit_falls_back_to_first_content_line():
    """Fix #3 — file-name title + real content → synthetic title from content."""
    note = Note(
        id=4, owner_id=1, tg_chat_id=-100, tg_message_id=20,
        kind="pdf", title="notebooklm_script_v3_final.md.pdf",
        content="Сценарий: NotebookLM. Хронометраж 12 минут.",
        created_at=1,
    )
    out = format_hit(note)
    first_line = out.splitlines()[0]
    assert first_line == "📌 [pdf] Сценарий: NotebookLM"


def test_format_hit_keeps_in_text_emoji():
    """Fix #5 boundary — only LEADING bullet emojis are stripped; emojis
    inside sentences must survive."""
    note = Note(
        id=5, owner_id=1, tg_chat_id=-100, tg_message_id=30,
        kind="post", title="Cloud news",
        content="Cloud is 🔵 awesome",
        created_at=1,
    )
    out = format_hit(note)
    assert "🔵" in out
