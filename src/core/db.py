import sqlite3
from pathlib import Path

import sqlite_vec

SCHEMA = """
CREATE TABLE IF NOT EXISTS owners (
    telegram_id            INTEGER PRIMARY KEY,
    jina_api_key           TEXT,
    deepgram_api_key       TEXT,
    openrouter_key         TEXT,
    primary_model          TEXT,
    fallback_model         TEXT,
    github_token           TEXT,
    github_mirror_repo     TEXT,
    vps_host               TEXT,
    vps_user               TEXT,
    inbox_chat_id          INTEGER,
    setup_step             TEXT,
    last_backup_at         TEXT,
    last_backup_error      TEXT,
    backup_failure_count   INTEGER DEFAULT 0,
    created_at             INTEGER NOT NULL
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
    if not _column_exists(conn, "notes", "ru_summary"):
        conn.execute("ALTER TABLE notes ADD COLUMN ru_summary TEXT DEFAULT NULL")
    if not _column_exists(conn, "notes", "sibling_note_id"):
        # Persists the comment+forward pair so soft_delete_note can
        # rebuild the survivor's FTS row when its partner is deleted.
        conn.execute(
            "ALTER TABLE notes ADD COLUMN sibling_note_id INTEGER DEFAULT NULL"
        )
    if not _column_exists(conn, "notes", "extracted_urls"):
        # JSON array of URLs lifted from message entities — covers the
        # invisible-link case where the user forwarded a Markdown embed
        # like `[Watch](https://youtu.be/…)`. The plain-text body the
        # extractors operate on never sees those URLs; this column lets
        # downstream tooling (vault sync, transcript pipelines) recover
        # videos that Telegram hides behind link text.
        conn.execute(
            "ALTER TABLE notes ADD COLUMN extracted_urls TEXT DEFAULT NULL"
        )
    if not _column_exists(conn, "owners", "last_backup_at"):
        conn.execute("ALTER TABLE owners ADD COLUMN last_backup_at TEXT")
    if not _column_exists(conn, "owners", "last_backup_error"):
        conn.execute("ALTER TABLE owners ADD COLUMN last_backup_error TEXT")
    if not _column_exists(conn, "owners", "backup_failure_count"):
        conn.execute(
            "ALTER TABLE owners ADD COLUMN backup_failure_count INTEGER DEFAULT 0"
        )
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


# Bumped whenever a code change makes the FTS index need a rebuild
# (new tokenizer, schema column folded into FTS, etc). On startup we
# rebuild the inverted index once and stamp this value into PRAGMA
# user_version so subsequent runs skip the work.
_FTS_SCHEMA_VERSION = 1


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.executescript(VEC_TABLE)
    conn.commit()
    _migrate(conn)
    _ensure_fts_coverage(conn)


def _ensure_fts_coverage(conn: sqlite3.Connection) -> None:
    """Run an idempotent FTS5 rebuild when the DB's recorded
    user_version trails the current code's _FTS_SCHEMA_VERSION. Old
    DBs created before the FTS triggers existed have rows in `notes`
    that the inverted index doesn't cover; rebuild fixes them.

    A plain `COUNT(*) FROM notes_fts` can't be used as the trigger:
    for an external-content FTS5 table that count returns the source
    row count, not the indexed one, so a stale index is invisible.

    Sibling-pair text was injected manually by reindex_pair; rebuild
    drops it, so we re-inject from sibling_note_id afterward."""
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current >= _FTS_SCHEMA_VERSION:
        return
    conn.execute("INSERT INTO notes_fts(notes_fts) VALUES('rebuild')")
    _reinject_sibling_pairs(conn)
    conn.execute(f"PRAGMA user_version = {_FTS_SCHEMA_VERSION}")
    conn.commit()


def _reinject_sibling_pairs(conn: sqlite3.Connection) -> None:
    """Walk all notes that record a sibling and rewrite each side's
    FTS row to contain the concatenated pair text. Idempotent: rebuild
    just dropped any previous injection, so we start from clean rows."""
    rows = conn.execute(
        "SELECT n.id, n.title, n.content, n.raw_caption, s.content "
        "FROM notes n JOIN notes s ON n.sibling_note_id = s.id "
        "WHERE n.sibling_note_id IS NOT NULL "
        "AND n.deleted_at IS NULL AND s.deleted_at IS NULL"
    ).fetchall()
    for n_id, title, content, raw, sib_content in rows:
        combined = f"{content or ''}\n\n{sib_content or ''}".strip()
        conn.execute(
            "INSERT INTO notes_fts(notes_fts, rowid, title, content, raw_caption) "
            "VALUES ('delete', ?, ?, ?, ?)",
            (n_id, title, content, raw),
        )
        conn.execute(
            "INSERT INTO notes_fts(rowid, title, content, raw_caption) "
            "VALUES (?, ?, ?, ?)",
            (n_id, title, combined, raw),
        )
