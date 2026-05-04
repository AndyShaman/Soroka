import struct
import time

import pytest

from src.core.db import open_db, init_schema
from src.core.owners import create_or_get_owner
from src.core.neighbors import find_similar, get_by_ids, get_context


def _insert_note(conn, *, id, owner_id, kind="post", chat_id=-100, msg_id=None,
                 created_at=None, deleted_at=None, thin=0,
                 title=None, content="c"):
    msg_id = msg_id if msg_id is not None else id
    created_at = created_at if created_at is not None else int(time.time())
    conn.execute(
        """INSERT INTO notes (id, owner_id, tg_message_id, tg_chat_id, kind,
                              title, content, created_at, thin_content, deleted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (id, owner_id, msg_id, chat_id, kind, title, content,
         created_at, thin, deleted_at),
    )
    conn.commit()


@pytest.fixture
def conn(tmp_path):
    c = open_db(str(tmp_path / "x.db"))
    init_schema(c)
    create_or_get_owner(c, telegram_id=42)
    return c


def test_get_by_ids_returns_in_input_order(conn):
    _insert_note(conn, id=1, owner_id=42, content="one")
    _insert_note(conn, id=2, owner_id=42, content="two")
    _insert_note(conn, id=3, owner_id=42, content="three")

    result = get_by_ids(conn, owner_id=42, ids=[3, 1, 2])
    assert [n.id for n in result] == [3, 1, 2]


def test_get_by_ids_drops_missing(conn):
    _insert_note(conn, id=1, owner_id=42)
    result = get_by_ids(conn, owner_id=42, ids=[1, 999, 1000])
    assert [n.id for n in result] == [1]


def test_get_by_ids_drops_deleted(conn):
    _insert_note(conn, id=1, owner_id=42)
    _insert_note(conn, id=2, owner_id=42, deleted_at=int(time.time()))
    result = get_by_ids(conn, owner_id=42, ids=[1, 2])
    assert [n.id for n in result] == [1]


def test_get_by_ids_drops_cross_owner(conn):
    create_or_get_owner(conn, telegram_id=99)
    _insert_note(conn, id=1, owner_id=42)
    _insert_note(conn, id=2, owner_id=99)
    result = get_by_ids(conn, owner_id=42, ids=[1, 2])
    assert [n.id for n in result] == [1]


def test_get_by_ids_empty_input_returns_empty(conn):
    assert get_by_ids(conn, owner_id=42, ids=[]) == []


def test_get_by_ids_raises_over_100(conn):
    with pytest.raises(ValueError, match="at most 100"):
        get_by_ids(conn, owner_id=42, ids=list(range(1, 102)))


def test_get_by_ids_collapses_duplicates(conn):
    _insert_note(conn, id=1, owner_id=42)
    _insert_note(conn, id=2, owner_id=42)
    result = get_by_ids(conn, owner_id=42, ids=[1, 2, 1, 2, 1])
    assert [n.id for n in result] == [1, 2]


def test_get_by_ids_accepts_exactly_100(conn):
    for i in range(1, 101):
        _insert_note(conn, id=i, owner_id=42)
    result = get_by_ids(conn, owner_id=42, ids=list(range(1, 101)))
    assert len(result) == 100


def test_get_context_returns_window_around_note(conn):
    # 5 messages in the same chat: ids 10, 11, 12 (source), 13, 14
    for msg in [10, 11, 12, 13, 14]:
        _insert_note(conn, id=msg, owner_id=42, msg_id=msg, chat_id=-100)
    result = get_context(conn, owner_id=42, note_id=12, window=2)
    assert [n.tg_message_id for n in result] == [10, 11, 13, 14]


def test_get_context_excludes_source(conn):
    _insert_note(conn, id=1, owner_id=42, msg_id=100, chat_id=-100)
    _insert_note(conn, id=2, owner_id=42, msg_id=101, chat_id=-100)
    result = get_context(conn, owner_id=42, note_id=2, window=3)
    assert [n.id for n in result] == [1]


def test_get_context_excludes_deleted_keeps_thin(conn):
    _insert_note(conn, id=1, owner_id=42, msg_id=100, chat_id=-100, thin=1)
    _insert_note(conn, id=2, owner_id=42, msg_id=101, chat_id=-100,
                 deleted_at=int(time.time()))
    _insert_note(conn, id=3, owner_id=42, msg_id=102, chat_id=-100)
    result = get_context(conn, owner_id=42, note_id=3, window=5)
    # thin (id=1) kept; deleted (id=2) dropped
    assert [n.id for n in result] == [1]


def test_get_context_isolates_chat(conn):
    # Source in chat A, neighbor at the SAME tg_message_id in chat B —
    # neighbor must not appear.
    _insert_note(conn, id=1, owner_id=42, msg_id=100, chat_id=-100)
    _insert_note(conn, id=2, owner_id=42, msg_id=101, chat_id=-100)
    _insert_note(conn, id=3, owner_id=42, msg_id=101, chat_id=-200)
    result = get_context(conn, owner_id=42, note_id=1, window=5)
    assert [n.id for n in result] == [2]


def test_get_context_missing_note_returns_empty(conn):
    assert get_context(conn, owner_id=42, note_id=9999, window=3) == []


def test_get_context_cross_owner_returns_empty(conn):
    create_or_get_owner(conn, telegram_id=99)
    _insert_note(conn, id=1, owner_id=99, msg_id=100, chat_id=-100)
    assert get_context(conn, owner_id=42, note_id=1, window=3) == []


def test_get_context_clamps_window(conn):
    # window=999 should be clamped to 10. Build 25 neighbors; expect at most 20.
    for msg in range(1, 26):
        _insert_note(conn, id=msg, owner_id=42, msg_id=msg, chat_id=-100)
    result = get_context(conn, owner_id=42, note_id=13, window=999)
    # window clamped to 10 → ids 3..12 and 14..23 = 20 neighbors
    assert len(result) == 20
    assert min(n.tg_message_id for n in result) == 3
    assert max(n.tg_message_id for n in result) == 23


def _embed(conn, note_id: int, vec: list[float]) -> None:
    """Write a 1024-dim float vector to notes_vec for `note_id`."""
    assert len(vec) == 1024
    blob = struct.pack(f"{len(vec)}f", *vec)
    conn.execute(
        "INSERT INTO notes_vec(note_id, embedding) VALUES (?, ?)",
        (note_id, blob),
    )
    conn.commit()


def _vec(seed: float) -> list[float]:
    """Deterministic 1024-d vector. Two distinct seeds give distinct,
    not-orthogonal vectors so the kNN query has something to rank."""
    return [seed] * 1024


@pytest.mark.asyncio
async def test_find_similar_returns_neighbors_excluding_source(conn):
    _insert_note(conn, id=1, owner_id=42, content="source")
    _insert_note(conn, id=2, owner_id=42, content="close")
    _insert_note(conn, id=3, owner_id=42, content="far")
    _embed(conn, 1, _vec(1.0))
    _embed(conn, 2, _vec(1.01))   # very close to 1
    _embed(conn, 3, _vec(5.0))    # far from 1

    result = await find_similar(conn, owner_id=42, note_id=1, limit=5)
    ids = [n.id for n in result]
    assert 1 not in ids        # source excluded
    assert ids[0] == 2         # closest first
    assert 3 in ids


@pytest.mark.asyncio
async def test_find_similar_excludes_deleted_and_thin(conn):
    _insert_note(conn, id=1, owner_id=42, content="source")
    _insert_note(conn, id=2, owner_id=42, content="thin", thin=1)
    _insert_note(conn, id=3, owner_id=42, content="deleted",
                 deleted_at=int(time.time()))
    _insert_note(conn, id=4, owner_id=42, content="ok")
    for nid, seed in [(1, 1.0), (2, 1.01), (3, 1.02), (4, 1.03)]:
        _embed(conn, nid, _vec(seed))

    result = await find_similar(conn, owner_id=42, note_id=1, limit=5)
    assert [n.id for n in result] == [4]


@pytest.mark.asyncio
async def test_find_similar_isolates_owner(conn):
    create_or_get_owner(conn, telegram_id=99)
    _insert_note(conn, id=1, owner_id=42, content="source")
    _insert_note(conn, id=2, owner_id=99, content="other-owner")
    _embed(conn, 1, _vec(1.0))
    _embed(conn, 2, _vec(1.01))

    assert await find_similar(conn, owner_id=42, note_id=1, limit=5) == []


@pytest.mark.asyncio
async def test_find_similar_no_embedding_returns_empty(conn):
    _insert_note(conn, id=1, owner_id=42)  # no _embed call
    assert await find_similar(conn, owner_id=42, note_id=1, limit=5) == []


@pytest.mark.asyncio
async def test_find_similar_respects_limit(conn):
    _insert_note(conn, id=1, owner_id=42, content="source")
    _embed(conn, 1, _vec(1.0))
    for i in range(2, 12):
        _insert_note(conn, id=i, owner_id=42)
        _embed(conn, i, _vec(1.0 + i * 0.01))

    result = await find_similar(conn, owner_id=42, note_id=1, limit=3)
    assert len(result) == 3
