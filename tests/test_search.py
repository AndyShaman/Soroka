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


# ---------------------------------------------------------------------------
# Tests for _normalize_url and _diversify_by_source
# ---------------------------------------------------------------------------

from src.core.search import _diversify_by_source, _normalize_url


def test_normalize_url_strips_utm():
    assert _normalize_url("https://Example.com/path/?utm_source=tg&x=1") \
        == "https://example.com/path?x=1"


def test_normalize_url_strips_trailing_slash():
    assert _normalize_url("https://example.com/path/") \
        == "https://example.com/path"


def test_normalize_url_handles_none():
    assert _normalize_url(None) is None


def test_diversify_caps_to_2_per_url():
    """Five copies of one URL must collapse to 2 in the diversified list."""
    notes = [
        _mk_note(1, "https://a.com"),
        _mk_note(2, "https://a.com/?utm_source=tg"),
        _mk_note(3, "https://a.com"),
        _mk_note(4, "https://b.com"),
        _mk_note(5, "https://a.com/"),
        _mk_note(6, "https://c.com"),
    ]
    out = _diversify_by_source(notes, max_per_url=2)
    a_count = sum(1 for n in out if "a.com" in (n.source_url or ""))
    assert a_count == 2
    assert {n.id for n in out} == {1, 2, 4, 6}  # 3rd and 5th a.com filtered


def test_diversify_keeps_no_url_notes():
    """Notes without a URL (text/voice) are not de-duplicated by URL."""
    notes = [
        _mk_note(1, None),
        _mk_note(2, None),
        _mk_note(3, None),
    ]
    out = _diversify_by_source(notes, max_per_url=2)
    assert len(out) == 3


def _mk_note(id_, url):
    from src.core.models import Note
    return Note(
        id=id_, owner_id=1, tg_chat_id=-1, tg_message_id=id_,
        kind="web" if url else "text", title="", content="x",
        source_url=url, raw_caption=None, created_at=1,
    )


# ---------------------------------------------------------------------------
# Tests for hybrid_search new filter params
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hybrid_search_excludes_deleted(tmp_path):
    from src.core.notes import soft_delete_note
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    n1 = insert_note(conn, Note(
        owner_id=1, tg_chat_id=-1, tg_message_id=1,
        kind="text", title="t", content="кошка на крыше",
        raw_caption=None, created_at=1,
    ))
    n2 = insert_note(conn, Note(
        owner_id=1, tg_chat_id=-1, tg_message_id=2,
        kind="text", title="t", content="кошка ловит мышь",
        raw_caption=None, created_at=2,
    ))

    soft_delete_note(conn, n1, reason="test")

    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)
    notes = await hybrid_search(
        conn, jina=fake_jina, owner_id=1,
        clean_query="кошка", kind=None, limit=15,
    )
    ids = {n.id for n in notes}
    assert n1 not in ids
    assert n2 in ids


@pytest.mark.asyncio
async def test_hybrid_search_excludes_thin_by_default(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    insert_note(conn, Note(
        owner_id=1, tg_chat_id=-1, tg_message_id=1, kind="web",
        title="t", content="кошка на крыше",
        source_url="https://a.com", raw_caption=None,
        created_at=1, thin_content=True,
    ))
    n2 = insert_note(conn, Note(
        owner_id=1, tg_chat_id=-1, tg_message_id=2, kind="web",
        title="t", content="кошка любит сметану — длинная статья " * 10,
        source_url="https://b.com", raw_caption=None,
        created_at=2,
    ))

    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)
    notes = await hybrid_search(
        conn, jina=fake_jina, owner_id=1,
        clean_query="кошка", kind=None, limit=15,
    )
    ids = {n.id for n in notes}
    assert n2 in ids
    assert all(not n.thin_content for n in notes)


@pytest.mark.asyncio
async def test_hybrid_search_exclude_ids(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    n1 = insert_note(conn, Note(
        owner_id=1, tg_chat_id=-1, tg_message_id=1, kind="text",
        title="t", content="кошка на крыше",
        raw_caption=None, created_at=1,
    ))
    n2 = insert_note(conn, Note(
        owner_id=1, tg_chat_id=-1, tg_message_id=2, kind="text",
        title="t", content="кошка ловит мышь",
        raw_caption=None, created_at=2,
    ))
    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)
    notes = await hybrid_search(
        conn, jina=fake_jina, owner_id=1,
        clean_query="кошка", kind=None, limit=15,
        exclude_ids=[n1],
    )
    ids = {n.id for n in notes}
    assert n1 not in ids
    assert n2 in ids


@pytest.mark.asyncio
async def test_hybrid_search_since_days(tmp_path, monkeypatch):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    import time
    now = int(time.time())
    old = insert_note(conn, Note(
        owner_id=1, tg_chat_id=-1, tg_message_id=1, kind="text",
        title="t", content="старая кошка",
        raw_caption=None, created_at=now - 60 * 86400,
    ))
    new = insert_note(conn, Note(
        owner_id=1, tg_chat_id=-1, tg_message_id=2, kind="text",
        title="t", content="свежая кошка",
        raw_caption=None, created_at=now - 5 * 86400,
    ))
    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)
    notes = await hybrid_search(
        conn, jina=fake_jina, owner_id=1,
        clean_query="кошка", kind=None, limit=15,
        since_days=30,
    )
    ids = {n.id for n in notes}
    assert old not in ids
    assert new in ids


def test_fuse_with_recency_uses_parameterized_sql(tmp_path):
    """_fuse_with_recency must bind ids as SQL parameters, not interpolate.
    Regression for the f-string SQL pattern in id-list lookup."""
    import time
    from src.core.search import _fuse_with_recency

    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    now = int(time.time())
    n_old = insert_note(conn, Note(
        owner_id=1, tg_chat_id=-1, tg_message_id=1, kind="text",
        title="", content="alpha", raw_caption=None,
        created_at=now - 365 * 86400,
    ))
    n_new = insert_note(conn, Note(
        owner_id=1, tg_chat_id=-1, tg_message_id=2, kind="text",
        title="", content="beta", raw_caption=None,
        created_at=now - 1 * 86400,
    ))
    # Both notes appear in BM25 with identical rank position (rank 0 in
    # different lists), so RRF contributions tie and recency must break it.
    fused = _fuse_with_recency(conn, [n_old], [n_new], now)
    assert set(fused) == {n_old, n_new}
    assert fused.index(n_new) < fused.index(n_old)


@pytest.mark.asyncio
async def test_hybrid_search_recency_tie_break(tmp_path, monkeypatch):
    """When two notes have identical text (same BM25 + same dense distance),
    the more recent one ranks higher because of recency boost."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    import time
    now = int(time.time())
    old = insert_note(conn, Note(
        owner_id=1, tg_chat_id=-1, tg_message_id=1, kind="text",
        title="", content="redfish blue planet skill",
        raw_caption=None, created_at=now - 365 * 86400,
    ))
    new = insert_note(conn, Note(
        owner_id=1, tg_chat_id=-1, tg_message_id=2, kind="text",
        title="", content="redfish blue planet skill",
        raw_caption=None, created_at=now - 1 * 86400,
    ))
    fake_jina = AsyncMock()
    fake_jina.embed = AsyncMock(return_value=[0.0] * 1024)
    notes = await hybrid_search(
        conn, jina=fake_jina, owner_id=1,
        clean_query="redfish blue planet skill", kind=None, limit=5,
    )
    ids = [n.id for n in notes]
    assert ids.index(new) < ids.index(old)
