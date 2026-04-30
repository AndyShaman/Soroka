from src.core.db import open_db, init_schema
from src.core.owners import create_or_get_owner
from src.core.notes import insert_note, get_note, list_recent_notes
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

def test_list_recent_notes_orders_desc(tmp_path):
    conn = _fixture_conn(tmp_path)
    for i in range(3):
        insert_note(conn, Note(
            owner_id=1, tg_message_id=i, tg_chat_id=-100,
            kind="text", content=f"n{i}", created_at=1000 + i,
        ))
    rows = list_recent_notes(conn, owner_id=1, limit=10)
    assert [n.content for n in rows] == ["n2", "n1", "n0"]
