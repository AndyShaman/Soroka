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
