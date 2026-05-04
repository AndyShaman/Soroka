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
