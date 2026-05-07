from datetime import datetime
from zoneinfo import ZoneInfo

from src.bot.handlers._search_format import (
    _clean_title,
    _clean_snippet,
    _truncate_smart,
    _format_source_url,
    _SOURCE_URL_MAX,
    format_hit,
)
from src.core.models import Note

TZ = ZoneInfo("Europe/Moscow")
# 2026-05-07 14:32 MSK — the timestamp threaded into every fixture so the
# rendered header (`📌 [kind] · 07 мая 2026, 14:32`) is identical across
# tests and stays human-recognisable when reading failure diffs.
TS = int(datetime(2026, 5, 7, 14, 32, tzinfo=TZ).timestamp())
HEADER_DATE = " · 07 мая 2026, 14:32"


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
    raw = "к\n-\n=\n\nextreme\n\nBag OT клещей\n\nдля обработки\nодежды"
    cleaned = _clean_snippet(raw)
    assert cleaned == "extreme Bag OT клещей для обработки одежды"


def test_clean_snippet_keeps_normal_text():
    raw = "Warp отдали в Open Source\n\nЭто тот самый терминал."
    cleaned = _clean_snippet(raw)
    assert cleaned == "Warp отдали в Open Source Это тот самый терминал."


def test_clean_snippet_strips_leading_bullet_emoji():
    cleaned = _clean_snippet("⚪ Tencent Cloud is great\n🔵 second line")
    assert cleaned == "Tencent Cloud is great second line"


# ---------- _truncate_smart ------------------------------------------------

def test_truncate_smart_short_text_unchanged():
    assert _truncate_smart("hello world", limit=200) == "hello world"


def test_truncate_smart_breaks_on_word_boundary():
    text = "раз два три четыре пять шесть семь восемь девять автор книги"
    limit = text.index("книги") + 3
    out = _truncate_smart(text, limit=limit)
    assert out.endswith("…")
    assert "книг" not in out
    assert out.rstrip("…").rstrip().endswith("автор")


def test_truncate_smart_does_not_split_url():
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
        created_at=TS,
    )
    out = format_hit(note, TZ)
    lines = out.splitlines()
    assert lines == [f"📌 [image]{HEADER_DATE}", "https://t.me/c/1/1"]


def test_format_hit_header_includes_date_and_drops_junk_title():
    note = Note(
        id=2, owner_id=1, tg_chat_id=-100, tg_message_id=484,
        kind="image", title="photo_AQADlhJrG72ZqEt-.jpg",
        content="к\n-\n=\n\nextreme\n\nBag OT клещей",
        created_at=TS,
    )
    out = format_hit(note, TZ)
    lines = out.splitlines()
    assert lines[0] == f"📌 [image]{HEADER_DATE}"
    assert "photo_AQADlhJrG72ZqEt" not in out
    assert "(без подписи)" not in out
    assert "extreme" in out


def test_format_hit_link_directly_after_header():
    note = Note(
        id=3, owner_id=1, tg_chat_id=-1001, tg_message_id=10,
        kind="post", title="POV: что-то",
        content="Содержимое поста.",
        created_at=TS,
    )
    out = format_hit(note, TZ)
    lines = out.splitlines()
    assert len(lines) == 3
    assert lines[0] == f"📌 [post]{HEADER_DATE}"
    assert lines[1] == "https://t.me/c/1/10"
    assert lines[2] == "Содержимое поста."


def test_format_hit_shows_full_body_within_cap():
    body = "слово " * 100
    note = Note(
        id=4, owner_id=1, tg_chat_id=-100, tg_message_id=20,
        kind="text", title=None, content=body.strip(),
        created_at=TS,
    )
    out = format_hit(note, TZ)
    assert "…" not in out
    assert out.endswith(body.strip())


def test_format_hit_keeps_in_text_emoji():
    note = Note(
        id=5, owner_id=1, tg_chat_id=-100, tg_message_id=30,
        kind="post", title="Cloud news",
        content="Cloud is 🔵 awesome",
        created_at=TS,
    )
    out = format_hit(note, TZ)
    assert "🔵" in out


def test_format_hit_renders_ru_summary_between_link_and_body():
    note = Note(
        id=6, owner_id=1, tg_chat_id=-1001, tg_message_id=40,
        kind="web", title="Some English title",
        content="This is the English article body about LLMs.",
        source_url="https://example.com/x",
        created_at=TS,
        ru_summary="Статья про большие языковые модели.",
    )
    out = format_hit(note, TZ)
    lines = out.splitlines()
    assert lines[0] == f"📌 [web]{HEADER_DATE}"
    assert lines[1] == "https://t.me/c/1/40"
    assert lines[2] == "https://example.com/x"
    assert lines[3] == "🇷🇺 Статья про большие языковые модели."
    assert lines[4] == "This is the English article body about LLMs."


def test_format_hit_omits_ru_summary_row_when_absent():
    note = Note(
        id=7, owner_id=1, tg_chat_id=-1001, tg_message_id=41,
        kind="text", title=None, content="Обычная заметка.",
        created_at=TS,
    )
    out = format_hit(note, TZ)
    lines = out.splitlines()
    assert "🇷🇺" not in out
    assert len(lines) == 3


def test_format_hit_omits_ru_summary_row_when_blank():
    note = Note(
        id=8, owner_id=1, tg_chat_id=-1001, tg_message_id=42,
        kind="web", title=None, content="body",
        created_at=TS, ru_summary="   ",
    )
    out = format_hit(note, TZ)
    assert "🇷🇺" not in out


def test_format_hit_renders_date_in_owner_timezone():
    """Same epoch displayed in two zones gives different wall-clock —
    `tz` is the only knob that controls it."""
    nyc_tz = ZoneInfo("America/New_York")
    note = Note(
        id=9, owner_id=1, tg_chat_id=-1001, tg_message_id=99,
        kind="text", title=None, content="x", created_at=TS,
    )
    msk_first = format_hit(note, TZ).splitlines()[0]
    nyc_first = format_hit(note, nyc_tz).splitlines()[0]
    assert msk_first != nyc_first
    assert "14:32" in msk_first
    # 14:32 MSK is 07:32 EDT on 2026-05-07.
    assert "07:32" in nyc_first


# ---------- _format_source_url --------------------------------------------

def test_format_source_url_returns_empty_for_none_or_blank():
    assert _format_source_url(None, "https://t.me/c/1/1") == ""
    assert _format_source_url("", "https://t.me/c/1/1") == ""
    assert _format_source_url("   ", "https://t.me/c/1/1") == ""


def test_format_source_url_skips_when_equals_message_link():
    link = "https://t.me/c/1001/55"
    assert _format_source_url(link, link) == ""


def test_format_source_url_returns_url_verbatim_when_short():
    out = _format_source_url("https://github.com/foo/bar", "https://t.me/c/1/1")
    assert out == "https://github.com/foo/bar"


def test_format_source_url_truncates_pathological_query():
    long_url = "https://example.com/path?" + "x=1&" * 80
    out = _format_source_url(long_url, "https://t.me/c/1/1")
    assert len(out) <= _SOURCE_URL_MAX
    assert out.endswith("…")
    assert out.startswith("https://example.com/path")


# ---------- format_hit + source_url row -----------------------------------

def test_format_hit_inserts_source_url_between_link_and_summary():
    note = Note(
        id=10, owner_id=1, tg_chat_id=-1001, tg_message_id=50,
        kind="web", title="GitHub repo", content="English article body.",
        source_url="https://github.com/foo/bar",
        ru_summary="Описание репозитория.",
        created_at=TS,
    )
    lines = format_hit(note, TZ).splitlines()
    assert lines[0] == f"📌 [web]{HEADER_DATE}"
    assert lines[1] == "https://t.me/c/1/50"
    assert lines[2] == "https://github.com/foo/bar"
    assert lines[3] == "🇷🇺 Описание репозитория."
    assert lines[4] == "English article body."


def test_format_hit_source_url_row_without_summary():
    note = Note(
        id=11, owner_id=1, tg_chat_id=-1001, tg_message_id=51,
        kind="web", title=None, content="Текст статьи на русском.",
        source_url="https://habr.com/ru/articles/12345/",
        created_at=TS,
    )
    lines = format_hit(note, TZ).splitlines()
    assert lines == [
        f"📌 [web]{HEADER_DATE}",
        "https://t.me/c/1/51",
        "https://habr.com/ru/articles/12345/",
        "Текст статьи на русском.",
    ]


def test_format_hit_omits_source_url_when_equals_message_link():
    note = Note(
        id=12, owner_id=1, tg_chat_id=-1001, tg_message_id=52,
        kind="web", title=None, content="body",
        source_url="https://t.me/c/1/52",
        created_at=TS,
    )
    out = format_hit(note, TZ)
    assert out.count("https://t.me/c/1/52") == 1


def test_format_hit_no_source_url_row_when_field_missing():
    note = Note(
        id=13, owner_id=1, tg_chat_id=-1001, tg_message_id=53,
        kind="text", title=None, content="Просто текст.",
        created_at=TS,
    )
    lines = format_hit(note, TZ).splitlines()
    assert len(lines) == 3
    assert lines == [f"📌 [text]{HEADER_DATE}", "https://t.me/c/1/53", "Просто текст."]
