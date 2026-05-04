import sqlite3
from pathlib import Path

import sqlite_vec

SCHEMA = """
CREATE TABLE IF NOT EXISTS owners (
    telegram_id        INTEGER PRIMARY KEY,
    jina_api_key       TEXT,
    deepgram_api_key   TEXT,
    openrouter_key     TEXT,
    primary_model      TEXT,
    fallback_model     TEXT,
    github_token       TEXT,
    github_mirror_repo TEXT,
    vps_host           TEXT,
    vps_user           TEXT,
    inbox_chat_id      INTEGER,
    setup_step         TEXT,
    created_at         INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS notes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id        INTEGER NOT NULL REFERENCES owners(telegram_id),
    tg_message_id   INTEGER NOT NULL,
    tg_chat_id      INTEGER NOT NULL,
    kind            TEXT NOT NULL,
    title           TEXT,
    content         TEXT NOT NULL,
    source_url      TEXT,
    raw_caption     TEXT,
    created_at      INTEGER NOT NULL,
    UNIQUE(owner_id, tg_chat_id, tg_message_id)
);

CREATE TABLE IF NOT EXISTS attachments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    note_id         INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    file_path       TEXT NOT NULL,
    file_size       INTEGER NOT NULL,
    mime_type       TEXT,
    original_name   TEXT,
    is_oversized    INTEGER DEFAULT 0
);

CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
    title, content, raw_caption,
    content='notes',
    content_rowid='id',
    tokenize='unicode61 remove_diacritics 0'
);

CREATE TRIGGER IF NOT EXISTS notes_ai AFTER INSERT ON notes BEGIN
    INSERT INTO notes_fts(rowid, title, content, raw_caption)
    VALUES (new.id, new.title, new.content, new.raw_caption);
END;

CREATE TRIGGER IF NOT EXISTS notes_ad AFTER DELETE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, title, content, raw_caption)
    VALUES ('delete', old.id, old.title, old.content, old.raw_caption);
END;

CREATE TRIGGER IF NOT EXISTS notes_au AFTER UPDATE ON notes BEGIN
    INSERT INTO notes_fts(notes_fts, rowid, title, content, raw_caption)
    VALUES ('delete', old.id, old.title, old.content, old.raw_caption);
    INSERT INTO notes_fts(rowid, title, content, raw_caption)
    VALUES (new.id, new.title, new.content, new.raw_caption);
END;
"""

VEC_TABLE = """
CREATE VIRTUAL TABLE IF NOT EXISTS notes_vec USING vec0(
    note_id INTEGER PRIMARY KEY,
    embedding FLOAT[1024]
);
"""


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in cur.fetchall())


def _migrate(conn: sqlite3.Connection) -> None:
    """Idempotent column additions for live databases. SQLite ALTER TABLE
    cannot add UNIQUE/CHECK retroactively but bare columns are fine and
    cheap on tables of any size (metadata-only operation)."""
    if not _column_exists(conn, "notes", "thin_content"):
        conn.execute("ALTER TABLE notes ADD COLUMN thin_content INTEGER DEFAULT 0")
    if not _column_exists(conn, "notes", "deleted_at"):
        conn.execute("ALTER TABLE notes ADD COLUMN deleted_at INTEGER DEFAULT NULL")
    conn.commit()


def open_db(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.executescript(VEC_TABLE)
    conn.commit()
    _migrate(conn)
