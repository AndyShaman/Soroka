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
