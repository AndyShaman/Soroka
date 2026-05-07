# tests/test_e2e.py
import pytest
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from src.core.db import open_db, init_schema
from src.core.owners import create_or_get_owner, update_owner_field
from src.core.ingest import ingest_text
from src.core.search import hybrid_search, rerank
from src.core.intent import parse_intent


@pytest.mark.asyncio
async def test_ingest_then_search_finds_note(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    update_owner_field(conn, 1, "primary_model", "x")
    update_owner_field(conn, 1, "fallback_model", "y")

    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[1.0] + [0.0] * 1023)
    fake_or = AsyncMock()
    # Single rerank call now — intent parsing is local and deterministic.
    fake_or.complete = AsyncMock(return_value="[1]")

    await ingest_text(
        conn, jina=fake_jina, owner_id=1,
        tg_chat_id=-100, tg_message_id=10,
        text="рецепт пасты карбонара", caption=None, created_at=1,
    )

    intent = parse_intent("что я сохранял про пасту", tz=ZoneInfo("Europe/Moscow"))
    candidates = await hybrid_search(
        conn, jina=fake_jina, owner_id=1,
        clean_query=intent.clean_query, kind=intent.kind, limit=15,
    )
    reranked = await rerank(
        fake_or, primary="x", fallback="y",
        query=intent.clean_query, candidates=candidates, top_k=5,
    )
    assert any("карбонара" in n.content for n in reranked)
