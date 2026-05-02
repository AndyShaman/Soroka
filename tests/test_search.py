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


@pytest.mark.asyncio
async def test_hybrid_search_filters_distant_vec_hits(tmp_path):
    """Regression: a note that is semantically far from the query (distance
    above VEC_DISTANCE_MAX) must NOT surface via vec channel just because
    sqlite-vec returns the global top-30. Without the threshold, /export
    commands and OCR-garbage notes would always appear in results.
    """
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)

    near_id = insert_note(conn, Note(
        owner_id=1, tg_message_id=1, tg_chat_id=-1,
        kind="text", content="biohacker dna sequencing notes",
        created_at=1,
    ))
    upsert_embedding(conn, near_id, [1.0, 0.0] + [0.0] * 1022)

    far_id = insert_note(conn, Note(
        owner_id=1, tg_message_id=2, tg_chat_id=-1,
        kind="text", content="completely unrelated railway timetable",
        created_at=1,
    ))
    upsert_embedding(conn, far_id, [0.0, 1.0] + [0.0] * 1022)  # L2 dist ≈ √2 ≈ 1.41

    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[1.0, 0.0] + [0.0] * 1022)

    results = await hybrid_search(
        conn, jina=fake_jina, owner_id=1,
        clean_query="biohacker", kind=None, limit=5,
    )
    ids = [r.id for r in results]
    assert near_id in ids
    assert far_id not in ids, (
        "vec hit at distance ≈1.41 must be cut by VEC_DISTANCE_MAX (1.25)"
    )


@pytest.mark.asyncio
async def test_rerank_orders_by_llm_response(tmp_path):
    conn = _seed(tmp_path)
    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[1.0, 0.0] + [0.0] * 1022)
    fake_or = AsyncMock()
    # LLM returns a JSON list of ids in best-first order
    fake_or.complete = AsyncMock(return_value="[3, 1]")

    from src.core.search import rerank, hybrid_search
    candidates = await hybrid_search(
        conn, jina=fake_jina, owner_id=1,
        clean_query="tuna", kind=None, limit=5,
    )
    reranked = await rerank(
        fake_or, primary="x", fallback="y",
        query="tuna sushi", candidates=candidates, top_k=2,
    )
    assert [n.id for n in reranked] == [3, 1]
