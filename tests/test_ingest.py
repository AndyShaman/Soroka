# tests/test_ingest.py
import pytest
from unittest.mock import AsyncMock
from src.core.db import open_db, init_schema
from src.core.owners import create_or_get_owner, update_owner_field
from src.core.ingest import ingest_text
from src.core.notes import get_note


@pytest.mark.asyncio
async def test_ingest_text_stores_note_and_embedding(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    update_owner_field(conn, 1, "jina_api_key", "k")

    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.1] * 1024)

    note_id = await ingest_text(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-100, tg_message_id=42,
        text="привет мир", caption=None, created_at=1000,
    )
    assert note_id is not None
    n = get_note(conn, note_id)
    assert n.content == "привет мир"
    assert n.kind == "text"
    fake_jina.embed.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingest_text_edit_overwrites_content_and_reembeds(tmp_path):
    """A second ingest_text call with is_edit=True for the same Telegram
    message must update the note content and refresh the embedding —
    not silently drop the new content (the old INSERT-OR-IGNORE bug)."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    update_owner_field(conn, 1, "jina_api_key", "k")

    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.1] * 1024)

    first = await ingest_text(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-100, tg_message_id=42,
        text="первая версия", caption=None, created_at=1000,
    )
    second = await ingest_text(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-100, tg_message_id=42,
        text="вторая версия после правки", caption=None, created_at=1000,
        is_edit=True,
    )
    assert second == first  # same id, updated in place
    n = get_note(conn, first)
    assert n.content == "вторая версия после правки"
    assert fake_jina.embed.await_count == 2  # initial + re-embed on edit


@pytest.mark.asyncio
async def test_ingest_text_edit_inserts_when_message_not_seen(tmp_path):
    """Edit of a message the bot never saw (offline during the original
    send) should fall back to a fresh insert."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    update_owner_field(conn, 1, "jina_api_key", "k")

    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.1] * 1024)

    note_id = await ingest_text(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-100, tg_message_id=999,
        text="edited but never seen before", caption=None,
        created_at=1000, is_edit=True,
    )
    assert note_id is not None
    assert get_note(conn, note_id).content == "edited but never seen before"


@pytest.mark.asyncio
async def test_ingest_url_uses_web_extractor(tmp_path, monkeypatch):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)

    monkeypatch.setattr(
        "src.core.ingest.extract_web",
        lambda url: ("Title", "Article body text"),
    )

    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)

    note_id = await ingest_text(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=1,
        text="https://example.com/x", caption=None, created_at=1,
    )
    n = get_note(conn, note_id)
    assert n.kind == "web"
    assert n.title == "Title"
    assert "Article body text" in n.content
    assert n.source_url == "https://example.com/x"


@pytest.mark.asyncio
async def test_ingest_short_text_with_url_extracts_link(tmp_path, monkeypatch):
    """Short note ("Пробовали <url> ?") — the URL is embedded but the
    message is link-card-shaped. Extractor receives just the URL (not the
    surrounding words) and the saved content keeps both the user's text
    and the extracted body so search hits via either side."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)

    captured_urls: list[str] = []

    def fake_extract(url):
        captured_urls.append(url)
        return ("gstack", "gstack — agentic dev workflow CLI")

    monkeypatch.setattr("src.core.ingest.extract_web", fake_extract)

    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)

    note_id = await ingest_text(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=2,
        text="Пробовали https://github.com/garrytan/gstack ?",
        caption=None, created_at=1,
    )
    n = get_note(conn, note_id)
    assert n.kind == "web"
    assert n.title == "gstack"
    assert n.source_url == "https://github.com/garrytan/gstack"
    # User's wrap text AND extracted body are both in content.
    assert "Пробовали" in n.content
    assert "gstack — agentic dev workflow CLI" in n.content
    # Extractor was called with the bare URL, not the whole message.
    assert captured_urls == ["https://github.com/garrytan/gstack"]


@pytest.mark.asyncio
async def test_ingest_long_text_with_url_stays_text(tmp_path, monkeypatch):
    """Long prose that mentions a URL should NOT trigger extraction —
    `extract_web` must not be called and `kind` stays 'text'."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)

    extracted_calls: list[str] = []
    monkeypatch.setattr(
        "src.core.ingest.extract_web",
        lambda url: extracted_calls.append(url) or ("T", "B"),
    )

    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)

    text = (
        "один два три четыре пять шесть семь восемь девять десять "
        "https://example.com/x"
    )
    note_id = await ingest_text(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=3,
        text=text, caption=None, created_at=1,
    )
    n = get_note(conn, note_id)
    assert n.kind == "text"
    assert n.source_url is None
    assert n.content == text
    assert extracted_calls == []


@pytest.mark.asyncio
async def test_ingest_voice_transcribes_and_stores(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)

    fake_dg = AsyncMock()
    fake_dg.transcribe = AsyncMock(return_value="голосовая заметка")
    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)

    from src.core.ingest import ingest_voice
    note_id = await ingest_voice(
        conn, deepgram=fake_dg, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=10,
        audio_bytes=b"FAKE", mime="audio/ogg", caption=None, created_at=1,
    )
    n = get_note(conn, note_id)
    assert n.kind == "voice"
    assert n.content == "голосовая заметка"


@pytest.mark.asyncio
async def test_ingest_document_pdf(tmp_path, monkeypatch):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)

    monkeypatch.setattr(
        "src.core.ingest.extract_pdf",
        lambda path: "PDF content text",
    )
    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)

    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-")

    from src.core.ingest import ingest_document
    note_id = await ingest_document(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=20,
        local_path=pdf_path, original_name="doc.pdf",
        kind="pdf", file_size=5,
        caption="мой пдф", created_at=1, is_oversized=False,
    )
    from src.core.notes import get_note
    from src.core.attachments import list_attachments
    n = get_note(conn, note_id)
    assert n.kind == "pdf"
    assert "PDF content text" in n.content
    atts = list_attachments(conn, note_id)
    assert atts[0].original_name == "doc.pdf"


@pytest.mark.asyncio
async def test_ingest_image_combines_caption_and_ocr(tmp_path, monkeypatch):
    """Caption (user's own words) is the strongest semantic signal — it
    must be combined with OCR, not replaced by it. Stylized images often
    yield garbage OCR; without the caption the note is unfindable.
    """
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)

    monkeypatch.setattr(
        "src.core.ingest.extract_ocr",
        lambda path: "blurry OCR garbage X1@",
    )
    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)

    img_path = tmp_path / "p.jpg"
    img_path.write_bytes(b"\xff\xd8\xff\xe0")

    from src.core.ingest import ingest_document
    note_id = await ingest_document(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=30,
        local_path=img_path, original_name="p.jpg",
        kind="image", file_size=4,
        caption="скрин claude.md инструкций",
        created_at=1, is_oversized=False,
    )
    from src.core.notes import get_note
    n = get_note(conn, note_id)
    assert "claude.md инструкций" in n.content
    assert "blurry OCR garbage" in n.content


@pytest.mark.asyncio
async def test_ingest_image_without_caption_falls_back_to_ocr(tmp_path, monkeypatch):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)

    monkeypatch.setattr(
        "src.core.ingest.extract_ocr",
        lambda path: "readable text on the image",
    )
    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)

    img_path = tmp_path / "p.jpg"
    img_path.write_bytes(b"\xff\xd8\xff\xe0")

    from src.core.ingest import ingest_document
    note_id = await ingest_document(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=31,
        local_path=img_path, original_name="p.jpg",
        kind="image", file_size=4,
        caption=None, created_at=1, is_oversized=False,
    )
    from src.core.notes import get_note
    n = get_note(conn, note_id)
    assert n.content == "readable text on the image"


@pytest.mark.asyncio
async def test_ingest_post_treats_caption_as_main_content(tmp_path, monkeypatch):
    """A forwarded Telegram post arrives as kind='post'. Caption IS the
    note (it's the actual text the user wanted to save); OCR is only
    appended if it surfaced something readable."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)

    monkeypatch.setattr(
        "src.core.ingest.extract_ocr",
        lambda path: "github.com/warpdotdev/warp",  # readable, > 20 chars
    )
    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)

    img_path = tmp_path / "p.jpg"
    img_path.write_bytes(b"\xff\xd8\xff\xe0")

    from src.core.ingest import ingest_document
    note_id = await ingest_document(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=40,
        local_path=img_path, original_name=img_path.name,
        kind="post", file_size=4,
        caption="Warp отдали в Open Source\n\nЭто тот самый терминал.",
        created_at=1, is_oversized=False,
    )
    from src.core.notes import get_note
    n = get_note(conn, note_id)
    assert n.kind == "post"
    assert n.title == "Warp отдали в Open Source"
    assert "Warp отдали в Open Source" in n.content
    assert "Это тот самый терминал" in n.content
    assert "github.com/warpdotdev/warp" in n.content


@pytest.mark.asyncio
async def test_ingest_post_skips_garbage_ocr(tmp_path, monkeypatch):
    """Stylized hero images often produce garbage OCR. If OCR is short
    (≤20 chars), don't pollute the post body with it."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)

    monkeypatch.setattr("src.core.ingest.extract_ocr", lambda path: "X1@")
    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)

    img_path = tmp_path / "p.jpg"
    img_path.write_bytes(b"\xff\xd8\xff\xe0")

    from src.core.ingest import ingest_document
    note_id = await ingest_document(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=41,
        local_path=img_path, original_name=img_path.name,
        kind="post", file_size=4,
        caption="Чистый текст поста без шума",
        created_at=1, is_oversized=False,
    )
    from src.core.notes import get_note
    n = get_note(conn, note_id)
    assert n.content == "Чистый текст поста без шума"


@pytest.mark.asyncio
async def test_ingest_oversized_records_metadata_only(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)

    from src.core.ingest import ingest_document
    note_id = await ingest_document(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=21,
        local_path=None, original_name="big.zip",
        kind="oversized", file_size=99_000_000,
        caption="архив", created_at=1, is_oversized=True,
    )
    from src.core.notes import get_note
    n = get_note(conn, note_id)
    assert n.kind == "oversized"
    assert "big.zip" in n.content


@pytest.mark.asyncio
async def test_ingest_text_marks_thin_content_when_web_extract_fails(tmp_path, monkeypatch):
    """If trafilatura returns < 200 chars / < 30 words, the note must be
    persisted with thin_content=1 so downstream code can flag it."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)

    monkeypatch.setattr(
        "src.core.ingest.extract_web",
        lambda url: ("Some Title", "Short."),
    )
    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)

    note_id = await ingest_text(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=70,
        text="https://example.com/x", caption=None, created_at=1,
    )
    n = get_note(conn, note_id)
    assert n.thin_content is True


@pytest.mark.asyncio
async def test_ingest_text_does_not_mark_thin_for_normal_extract(tmp_path, monkeypatch):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)

    monkeypatch.setattr(
        "src.core.ingest.extract_web",
        lambda url: ("Some Title", "lorem ipsum " * 50),
    )
    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)

    note_id = await ingest_text(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=71,
        text="https://example.com/long", caption=None, created_at=1,
    )
    n = get_note(conn, note_id)
    assert n.thin_content is False


@pytest.mark.asyncio
async def test_ingest_text_user_text_is_never_thin(tmp_path):
    """User-typed plain text (kind='text') reflects what the user wrote,
    not what an extractor produced — never flag it as thin."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)

    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)

    note_id = await ingest_text(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=72,
        text="короткая мысль", caption=None, created_at=1,
    )
    n = get_note(conn, note_id)
    assert n.thin_content is False


# ---------- ru_summary on web/youtube --------------------------------------

@pytest.mark.asyncio
async def test_ingest_url_generates_ru_summary_for_foreign_extract(tmp_path, monkeypatch):
    """English-language extracted body triggers a Russian summary via
    OpenRouter; the summary is saved on the Note and concatenated into
    the embedding text."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)

    monkeypatch.setattr(
        "src.core.ingest.extract_web",
        lambda url: ("English Title",
                     "This is the English article body about LLMs and "
                     "modern software engineering practices for builders."),
    )

    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)
    fake_or = AsyncMock()
    fake_or.complete = AsyncMock(return_value="Статья про LLM и инженерию.")

    note_id = await ingest_text(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=100,
        text="https://example.com/llm", caption=None, created_at=1,
        openrouter=fake_or, primary_model="m1", fallback_model="m2",
    )
    n = get_note(conn, note_id)
    assert n.ru_summary == "Статья про LLM и инженерию."
    fake_or.complete.assert_awaited_once()
    # Embedding text contains the summary so RU queries hit the dense index.
    embed_arg = fake_jina.embed.call_args.args[0]
    assert "Статья про LLM и инженерию." in embed_arg


@pytest.mark.asyncio
async def test_ingest_url_skips_summary_for_russian_extract(tmp_path, monkeypatch):
    """Already-Russian extracted body should not invoke the LLM."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)

    monkeypatch.setattr(
        "src.core.ingest.extract_web",
        lambda url: ("Заголовок",
                     "Это русская статья про языковые модели и разработку."),
    )

    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)
    fake_or = AsyncMock()
    fake_or.complete = AsyncMock(return_value="should not be called")

    note_id = await ingest_text(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=101,
        text="https://example.com/ru", caption=None, created_at=1,
        openrouter=fake_or, primary_model="m1", fallback_model="m2",
    )
    n = get_note(conn, note_id)
    assert n.ru_summary is None
    fake_or.complete.assert_not_called()


@pytest.mark.asyncio
async def test_ingest_url_survives_summary_llm_failure(tmp_path, monkeypatch):
    """LLM exception must not block ingest — the note saves with
    ru_summary=None."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)

    monkeypatch.setattr(
        "src.core.ingest.extract_web",
        lambda url: ("English Title",
                     "This is a long English article about engineering."),
    )

    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)
    fake_or = AsyncMock()
    fake_or.complete = AsyncMock(side_effect=Exception("openrouter down"))

    note_id = await ingest_text(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=102,
        text="https://example.com/en", caption=None, created_at=1,
        openrouter=fake_or, primary_model="m1", fallback_model="m2",
    )
    assert note_id is not None
    n = get_note(conn, note_id)
    assert n.ru_summary is None
    assert n.kind == "web"
    assert "engineering" in n.content


@pytest.mark.asyncio
async def test_ingest_url_skips_summary_when_no_openrouter(tmp_path, monkeypatch):
    """Backwards-compat: callers that don't pass an openrouter client
    skip summarisation entirely (existing tests exercise this path)."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)

    monkeypatch.setattr(
        "src.core.ingest.extract_web",
        lambda url: ("English Title",
                     "Long English body about engineering practices."),
    )

    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)

    note_id = await ingest_text(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=103,
        text="https://example.com/x", caption=None, created_at=1,
    )
    n = get_note(conn, note_id)
    assert n.ru_summary is None


@pytest.mark.asyncio
async def test_ingest_url_edit_reuses_summary_when_url_unchanged(tmp_path, monkeypatch):
    """Caption-only edit of a foreign URL reuses the existing ru_summary
    and does NOT re-bill OpenRouter — the cached summary is identical
    to what the LLM would return again."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)

    monkeypatch.setattr(
        "src.core.ingest.extract_web",
        lambda url: ("Title",
                     "English article body about software engineering."),
    )

    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)
    fake_or = AsyncMock()
    fake_or.complete = AsyncMock(return_value="Первая сводка.")

    first = await ingest_text(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=104,
        text="https://example.com/edit", caption=None, created_at=1,
        openrouter=fake_or, primary_model="m1", fallback_model="m2",
    )
    second = await ingest_text(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=104,
        text="https://example.com/edit", caption="фикс опечатки", created_at=1,
        is_edit=True,
        openrouter=fake_or, primary_model="m1", fallback_model="m2",
    )
    assert second == first
    n = get_note(conn, first)
    assert n.ru_summary == "Первая сводка."
    # LLM was called exactly once — second pass hit the cache.
    assert fake_or.complete.await_count == 1


@pytest.mark.asyncio
async def test_ingest_youtube_generates_ru_summary_for_foreign_extract(tmp_path, monkeypatch):
    """YouTube path mirrors the web path — non-Russian title/description
    triggers Russian summarisation."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)

    monkeypatch.setattr(
        "src.adapters.extractors.youtube.extract_youtube",
        lambda url: ("How to build agents",
                     "A long English description about building autonomous "
                     "AI agents with LLMs and modern tooling for engineers."),
    )

    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)
    fake_or = AsyncMock()
    fake_or.complete = AsyncMock(return_value="Видео про создание AI-агентов.")

    note_id = await ingest_text(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=200,
        text="https://youtu.be/abc123", caption=None, created_at=1,
        openrouter=fake_or, primary_model="m1", fallback_model="m2",
    )
    n = get_note(conn, note_id)
    assert n.kind == "youtube"
    assert n.ru_summary == "Видео про создание AI-агентов."
    fake_or.complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingest_url_edit_resummarizes_when_url_changes(tmp_path, monkeypatch):
    """If the user edits to a different URL, the cache must miss and a
    fresh summary is generated."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)

    monkeypatch.setattr(
        "src.core.ingest.extract_web",
        lambda url: ("Title",
                     "English article body about software engineering."),
    )

    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)
    fake_or = AsyncMock()
    fake_or.complete = AsyncMock(side_effect=["Первая сводка.", "Вторая сводка."])

    first = await ingest_text(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=104,
        text="https://example.com/a", caption=None, created_at=1,
        openrouter=fake_or, primary_model="m1", fallback_model="m2",
    )
    await ingest_text(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-1, tg_message_id=104,
        text="https://example.com/b", caption=None, created_at=1,
        is_edit=True,
        openrouter=fake_or, primary_model="m1", fallback_model="m2",
    )
    n = get_note(conn, first)
    assert n.ru_summary == "Вторая сводка."
    assert fake_or.complete.await_count == 2
