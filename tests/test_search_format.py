from src.bot.handlers._search_format import (
    _clean_title,
    _clean_snippet,
    _truncate_smart,
    _format_source_url,
    _SOURCE_URL_MAX,
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

def test_format_hit_two_lines_when_body_empty():
    """Empty content → header + link only, no trailing blank line."""
    note = Note(
        id=1, owner_id=1, tg_chat_id=-1001, tg_message_id=1,
        kind="image", title=None, content="",
        created_at=1,
    )
    out = format_hit(note)
    lines = out.splitlines()
    assert lines == ["📌 [image]", "https://t.me/c/1/1"]


def test_format_hit_header_is_kind_only():
    """Header carries the kind tag only — no title, no '(без подписи)'.
    User judges relevance from the body row, not from a derived heading."""
    note = Note(
        id=2, owner_id=1, tg_chat_id=-100, tg_message_id=484,
        kind="image", title="photo_AQADlhJrG72ZqEt-.jpg",
        content="к\n-\n=\n\nextreme\n\nBag OT клещей",
        created_at=1,
    )
    out = format_hit(note)
    lines = out.splitlines()
    assert lines[0] == "📌 [image]"
    assert "photo_AQADlhJrG72ZqEt" not in out
    assert "(без подписи)" not in out
    assert "extreme" in out


def test_format_hit_link_directly_after_header():
    """Tag → link → text. Link must be on the second line so the user sees
    it immediately, before reading the body."""
    note = Note(
        id=3, owner_id=1, tg_chat_id=-1001, tg_message_id=10,
        kind="post", title="POV: что-то",
        content="Содержимое поста.",
        created_at=1,
    )
    out = format_hit(note)
    lines = out.splitlines()
    assert len(lines) == 3
    assert lines[0] == "📌 [post]"
    assert lines[1] == "https://t.me/c/1/10"
    assert lines[2] == "Содержимое поста."


def test_format_hit_shows_full_body_within_cap():
    """A 600-char body fits under the 700-char cap and is shown verbatim."""
    body = "слово " * 100  # 600 chars
    note = Note(
        id=4, owner_id=1, tg_chat_id=-100, tg_message_id=20,
        kind="text", title=None, content=body.strip(),
        created_at=1,
    )
    out = format_hit(note)
    assert "…" not in out
    assert out.endswith(body.strip())


def test_format_hit_keeps_in_text_emoji():
    """Only LEADING bullet emojis are stripped; emojis inside sentences
    must survive."""
    note = Note(
        id=5, owner_id=1, tg_chat_id=-100, tg_message_id=30,
        kind="post", title="Cloud news",
        content="Cloud is 🔵 awesome",
        created_at=1,
    )
    out = format_hit(note)
    assert "🔵" in out


def test_format_hit_renders_ru_summary_between_link_and_body():
    """Foreign-language URL captures get a Russian summary row inserted
    after the source-url row and before the article body."""
    note = Note(
        id=6, owner_id=1, tg_chat_id=-1001, tg_message_id=40,
        kind="web", title="Some English title",
        content="This is the English article body about LLMs.",
        source_url="https://example.com/x",
        created_at=1,
        ru_summary="Статья про большие языковые модели.",
    )
    out = format_hit(note)
    lines = out.splitlines()
    assert lines[0] == "📌 [web]"
    assert lines[1] == "https://t.me/c/1/40"
    assert lines[2] == "https://example.com/x"
    assert lines[3] == "🇷🇺 Статья про большие языковые модели."
    assert lines[4] == "This is the English article body about LLMs."


def test_format_hit_omits_ru_summary_row_when_absent():
    """Notes without ru_summary keep the original 3-line shape."""
    note = Note(
        id=7, owner_id=1, tg_chat_id=-1001, tg_message_id=41,
        kind="text", title=None, content="Обычная заметка.",
        created_at=1,
    )
    out = format_hit(note)
    lines = out.splitlines()
    assert "🇷🇺" not in out
    assert len(lines) == 3


def test_format_hit_omits_ru_summary_row_when_blank():
    """Whitespace-only ru_summary is treated as empty — no row emitted."""
    note = Note(
        id=8, owner_id=1, tg_chat_id=-1001, tg_message_id=42,
        kind="web", title=None, content="body",
        created_at=1, ru_summary="   ",
    )
    out = format_hit(note)
    assert "🇷🇺" not in out


# ---------- _format_source_url --------------------------------------------

def test_format_source_url_returns_empty_for_none_or_blank():
    """Notes without an external URL produce no source-url row."""
    assert _format_source_url(None, "https://t.me/c/1/1") == ""
    assert _format_source_url("", "https://t.me/c/1/1") == ""
    assert _format_source_url("   ", "https://t.me/c/1/1") == ""


def test_format_source_url_skips_when_equals_message_link():
    """If source_url is the Telegram message link itself (already shown
    as line 2), don't echo it again."""
    link = "https://t.me/c/1001/55"
    assert _format_source_url(link, link) == ""


def test_format_source_url_returns_url_verbatim_when_short():
    out = _format_source_url("https://github.com/foo/bar", "https://t.me/c/1/1")
    assert out == "https://github.com/foo/bar"


def test_format_source_url_truncates_pathological_query():
    """A URL longer than _SOURCE_URL_MAX is hard-clipped with an ellipsis
    so a long ?utm_… tail can't blow the per-card budget."""
    long_url = "https://example.com/path?" + "x=1&" * 80  # >>110 chars
    out = _format_source_url(long_url, "https://t.me/c/1/1")
    assert len(out) <= _SOURCE_URL_MAX
    assert out.endswith("…")
    assert out.startswith("https://example.com/path")


# ---------- format_hit + source_url row -----------------------------------

def test_format_hit_inserts_source_url_between_link_and_summary():
    """Order is: header, telegram link, source_url, ru_summary, body."""
    note = Note(
        id=10, owner_id=1, tg_chat_id=-1001, tg_message_id=50,
        kind="web", title="GitHub repo", content="English article body.",
        source_url="https://github.com/foo/bar",
        ru_summary="Описание репозитория.",
        created_at=1,
    )
    lines = format_hit(note).splitlines()
    assert lines[0] == "📌 [web]"
    assert lines[1] == "https://t.me/c/1/50"
    assert lines[2] == "https://github.com/foo/bar"
    assert lines[3] == "🇷🇺 Описание репозитория."
    assert lines[4] == "English article body."


def test_format_hit_source_url_row_without_summary():
    """Russian-language URL captures still get a source_url row even
    though there's no ru_summary."""
    note = Note(
        id=11, owner_id=1, tg_chat_id=-1001, tg_message_id=51,
        kind="web", title=None, content="Текст статьи на русском.",
        source_url="https://habr.com/ru/articles/12345/",
        created_at=1,
    )
    lines = format_hit(note).splitlines()
    assert lines == [
        "📌 [web]",
        "https://t.me/c/1/51",
        "https://habr.com/ru/articles/12345/",
        "Текст статьи на русском.",
    ]


def test_format_hit_omits_source_url_when_equals_message_link():
    """Defensive: if source_url somehow coincides with the message link,
    we don't print the same URL twice."""
    note = Note(
        id=12, owner_id=1, tg_chat_id=-1001, tg_message_id=52,
        kind="web", title=None, content="body",
        source_url="https://t.me/c/1/52",
        created_at=1,
    )
    out = format_hit(note)
    # The telegram link appears exactly once as line 2; no second copy.
    assert out.count("https://t.me/c/1/52") == 1


def test_format_hit_no_source_url_row_when_field_missing():
    """Notes without source_url keep the original 3-line shape."""
    note = Note(
        id=13, owner_id=1, tg_chat_id=-1001, tg_message_id=53,
        kind="text", title=None, content="Просто текст.",
        created_at=1,
    )
    lines = format_hit(note).splitlines()
    assert len(lines) == 3
    assert lines == ["📌 [text]", "https://t.me/c/1/53", "Просто текст."]
