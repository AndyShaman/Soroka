import time

import pytest

from src.core.db import open_db, init_schema
from src.core.owners import create_or_get_owner
from src.core.neighbors import get_by_ids


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
