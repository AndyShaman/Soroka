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


def test_init_schema_rebuilds_fts_for_legacy_rows(tmp_path):
    """A DB that pre-dates the FTS triggers can carry rows in `notes`
    that have no entry in `notes_fts`. init_schema must run a one-shot
    rebuild so search starts working without forcing a manual SQL fix."""
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
    legacy.execute(
        "INSERT INTO notes (owner_id, tg_message_id, tg_chat_id, kind, "
        "content, created_at) VALUES (1, 1, -1, 'text', 'legacy body', 1)"
    )
    legacy.commit()
    legacy.close()

    conn = open_db(db_path)
    init_schema(conn)

    rowids = {r[0] for r in conn.execute(
        "SELECT rowid FROM notes_fts WHERE notes_fts MATCH ?",
        ('"legacy"',),
    ).fetchall()}
    assert rowids, "FTS rebuild on migration should index the legacy row"


def test_ensure_fts_coverage_skips_when_user_version_current(tmp_path):
    """A healthy DB must not eat startup time on a no-op rebuild — the
    coverage check stamps user_version after the first rebuild and
    short-circuits on every subsequent init_schema."""
    from src.core.db import _FTS_SCHEMA_VERSION

    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == _FTS_SCHEMA_VERSION

    # A second init_schema must not reset the version or rerun rebuild.
    init_schema(conn)
    version_again = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version_again == _FTS_SCHEMA_VERSION


def test_init_schema_reinjects_sibling_fts_after_rebuild(tmp_path):
    """When a legacy DB carries a sibling pair, the FTS rebuild restores
    individual rows but loses the cross-injected text. The migration
    helper must walk sibling_note_id and re-inject so paired notes can
    still be found by their partner's words."""
    from src.core.notes import insert_note
    from src.core.owners import create_or_get_owner
    from src.core.models import Note

    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    a = insert_note(conn, Note(
        owner_id=1, tg_message_id=1, tg_chat_id=-1,
        kind="text", content="alpha-text", created_at=1,
    ))
    b = insert_note(conn, Note(
        owner_id=1, tg_message_id=2, tg_chat_id=-1,
        kind="text", content="beta-text", created_at=2,
    ))
    conn.execute(
        "UPDATE notes SET sibling_note_id = ? WHERE id = ?", (b, a))
    conn.execute(
        "UPDATE notes SET sibling_note_id = ? WHERE id = ?", (a, b))
    # Reset user_version so init_schema treats this DB as legacy and
    # walks the rebuild + reinjection path; otherwise the second call
    # short-circuits because we already stamped the schema version.
    conn.execute("PRAGMA user_version = 0")
    conn.commit()

    init_schema(conn)

    rowids = {r[0] for r in conn.execute(
        "SELECT rowid FROM notes_fts WHERE notes_fts MATCH ?",
        ('"alpha-text"',),
    ).fetchall()}
    assert a in rowids and b in rowids, (
        "after rebuild, both halves of the pair should match the partner's word"
    )


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
