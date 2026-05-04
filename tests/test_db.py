# tests/test_db.py
import sqlite3
from src.core.db import open_db, init_schema

def test_init_schema_creates_all_tables(tmp_path):
    db_path = tmp_path / "soroka.db"
    conn = open_db(str(db_path))
    init_schema(conn)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','index') ORDER BY name"
    )
    names = {row[0] for row in cur.fetchall()}
    for expected in {"owners", "notes", "attachments", "notes_fts", "notes_vec"}:
        assert expected in names

def test_init_schema_is_idempotent(tmp_path):
    db_path = tmp_path / "soroka.db"
    conn = open_db(str(db_path))
    init_schema(conn)
    init_schema(conn)  # second call must not raise

def test_owners_table_allows_null_keys(tmp_path):
    conn = open_db(str(tmp_path / "soroka.db"))
    init_schema(conn)
    conn.execute(
        "INSERT INTO owners (telegram_id, created_at) VALUES (?, ?)",
        (1, 1700000000),
    )
    conn.commit()
    row = conn.execute("SELECT jina_api_key FROM owners").fetchone()
    assert row[0] is None


def test_init_schema_adds_thin_content_and_deleted_at(tmp_path):
    """A fresh DB must have notes.thin_content and notes.deleted_at."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(notes)").fetchall()}
    assert "thin_content" in cols
    assert "deleted_at" in cols


def test_migrate_is_idempotent_on_legacy_db(tmp_path):
    """A DB created without new columns must be migrated cleanly,
    and a second init_schema call must be a no-op."""
    db_path = str(tmp_path / "legacy.db")
    legacy = sqlite3.connect(db_path)
    legacy.execute("""CREATE TABLE notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        owner_id INTEGER NOT NULL,
        tg_message_id INTEGER NOT NULL,
        tg_chat_id INTEGER NOT NULL,
        kind TEXT NOT NULL,
        title TEXT, content TEXT NOT NULL,
        source_url TEXT, raw_caption TEXT,
        created_at INTEGER NOT NULL,
        UNIQUE(owner_id, tg_chat_id, tg_message_id)
    )""")
    legacy.commit()
    legacy.close()

    conn = open_db(db_path)
    init_schema(conn)
    init_schema(conn)  # idempotent
    cols = {row[1] for row in conn.execute("PRAGMA table_info(notes)").fetchall()}
    assert "thin_content" in cols
    assert "deleted_at" in cols
