import pytest
from unittest.mock import AsyncMock
from src.core.db import open_db, init_schema
from src.core.owners import create_or_get_owner
from src.core.notes import insert_note
from src.core.vec import upsert_embedding
from src.core.models import Note
from src.core.search import hybrid_search


def _seed(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    docs = [
        ("cats love tuna fish", [1.0, 0.0] + [0.0] * 1022),
        ("dogs eat bones daily", [0.0, 1.0] + [0.0] * 1022),
        ("tuna sushi recipe", [0.9, 0.1] + [0.0] * 1022),
    ]
    for i, (content, emb) in enumerate(docs):
        nid = insert_note(conn, Note(
            owner_id=1, tg_message_id=i, tg_chat_id=-1,
            kind="text", content=content, created_at=1,
        ))
        upsert_embedding(conn, nid, emb)
    return conn


@pytest.mark.asyncio
async def test_hybrid_search_finds_relevant(tmp_path):
    conn = _seed(tmp_path)
    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[1.0, 0.0] + [0.0] * 1022)

    results = await hybrid_search(
        conn, jina=fake_jina, owner_id=1,
        clean_query="tuna", kind=None, limit=5,
    )
    contents = [r.content for r in results]
    assert any("tuna" in c.lower() for c in contents)
