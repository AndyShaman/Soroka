import logging

from src.core.db import open_db, init_schema
from src.core.owners import create_or_get_owner
from src.core.notes import (
    insert_note, get_note, list_recent_notes, find_note_id_by_message,
)
from src.core.models import Note

def _fixture_conn(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    return conn

def test_insert_note_returns_id(tmp_path):
    conn = _fixture_conn(tmp_path)
    n = Note(owner_id=1, tg_message_id=10, tg_chat_id=-100,
             kind="text", content="hello", created_at=1)
    note_id = insert_note(conn, n)
    assert note_id == 1
    fetched = get_note(conn, note_id)
    assert fetched.content == "hello"

def test_insert_note_dedupes_by_message(tmp_path):
    conn = _fixture_conn(tmp_path)
    n = Note(owner_id=1, tg_message_id=10, tg_chat_id=-100,
             kind="text", content="hello", created_at=1)
    insert_note(conn, n)
    second_id = insert_note(conn, n)
    assert second_id is None  # duplicate


def test_insert_note_logs_duplicate(tmp_path, caplog):
    """Operators need to see duplicates in logs to distinguish them from
    silent ingest bugs (e.g. unhandled kind, parse failure)."""
    conn = _fixture_conn(tmp_path)
    n = Note(owner_id=1, tg_message_id=10, tg_chat_id=-100,
             kind="text", content="hello", created_at=1)
    insert_note(conn, n)
    with caplog.at_level(logging.INFO, logger="src.core.notes"):
        insert_note(conn, n)
    assert any("duplicate" in r.message for r in caplog.records)


def test_find_note_id_by_message(tmp_path):
    conn = _fixture_conn(tmp_path)
    n = Note(owner_id=1, tg_message_id=10, tg_chat_id=-100,
             kind="text", content="hello", created_at=1)
    new_id = insert_note(conn, n)
    assert find_note_id_by_message(conn, 1, -100, 10) == new_id
    assert find_note_id_by_message(conn, 1, -100, 999) is None
    assert find_note_id_by_message(conn, 2, -100, 10) is None  # different owner

def test_list_recent_notes_orders_desc(tmp_path):
    conn = _fixture_conn(tmp_path)
    for i in range(3):
        insert_note(conn, Note(
            owner_id=1, tg_message_id=i, tg_chat_id=-100,
            kind="text", content=f"n{i}", created_at=1000 + i,
        ))
    rows = list_recent_notes(conn, owner_id=1, limit=10)
    assert [n.content for n in rows] == ["n2", "n1", "n0"]

def test_list_recent_notes_filters_by_kind(tmp_path):
    conn = _fixture_conn(tmp_path)
    insert_note(conn, Note(
        owner_id=1, tg_message_id=1, tg_chat_id=-100,
        kind="text", content="text-note", created_at=1,
    ))
    insert_note(conn, Note(
        owner_id=1, tg_message_id=2, tg_chat_id=-100,
        kind="web", content="web-note", source_url="https://example.com",
        created_at=2,
    ))
    text_only = list_recent_notes(conn, owner_id=1, kind="text")
    assert [n.content for n in text_only] == ["text-note"]


def test_list_recent_notes_preserves_thin_content(tmp_path):
    """list_recent_notes must surface thin_content correctly so MCP/CLI
    consumers don't get a silent rassinhron with the actual DB state."""
    import time
    conn = _fixture_conn(tmp_path)
    insert_note(conn, Note(
        owner_id=1, tg_message_id=1, tg_chat_id=1,
        kind="post", title="thin", content="x",
        source_url=None, raw_caption=None,
        created_at=int(time.time()), thin_content=True,
    ))
    insert_note(conn, Note(
        owner_id=1, tg_message_id=2, tg_chat_id=1,
        kind="post", title="full", content="lots of content",
        source_url=None, raw_caption=None,
        created_at=int(time.time()), thin_content=False,
    ))

    notes = list_recent_notes(conn, owner_id=1, limit=10)
    by_title = {n.title: n for n in notes}
    assert by_title["thin"].thin_content is True
    assert by_title["full"].thin_content is False


def test_soft_delete_note_sets_deleted_at_and_get_returns_none(tmp_path):
    from src.core.notes import soft_delete_note

    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    nid = insert_note(conn, Note(
        owner_id=1, tg_chat_id=-1, tg_message_id=1, kind="text",
        title="t", content="контент", raw_caption=None, created_at=1,
    ))

    soft_delete_note(conn, nid, reason="duplicate")

    assert get_note(conn, nid) is None
    row = conn.execute(
        "SELECT deleted_at FROM notes WHERE id = ?", (nid,)
    ).fetchone()
    assert row is not None and row[0] is not None
