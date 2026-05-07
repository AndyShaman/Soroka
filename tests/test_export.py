# tests/test_export.py
import json
from pathlib import Path
import zipfile
from src.core.db import open_db, init_schema
from src.core.owners import create_or_get_owner
from src.core.notes import insert_note
from src.core.models import Note
from src.core.export import build_export


def test_build_export_zip(tmp_path):
    db_path = tmp_path / "x.db"
    conn = open_db(str(db_path))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    insert_note(conn, Note(
        owner_id=1, tg_message_id=1, tg_chat_id=-1,
        kind="text", content="hello", created_at=1,
    ))
    conn.close()

    out = tmp_path / "export.zip"
    build_export(
        db_path=db_path,
        attachments_dir=tmp_path / "atts",
        output_path=out,
    )
    assert out.exists()
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert "soroka.db" in names
        assert "notes.json" in names
        with z.open("notes.json") as f:
            data = json.load(f)
        assert data[0]["content"] == "hello"


def test_export_excludes_soft_deleted_notes(tmp_path):
    """A note that was soft-deleted must not appear in the JSON dump.
    The SQLite snapshot still contains it (raw recovery is intentional),
    but the user-facing flat JSON respects the deletion."""
    import time
    from src.core.notes import soft_delete_note

    db_path = tmp_path / "soroka.db"
    conn = open_db(str(db_path))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    keep = insert_note(conn, Note(
        owner_id=1, tg_message_id=1, tg_chat_id=1,
        kind="post", title="keep", content="kept",
        source_url=None, raw_caption=None,
        created_at=int(time.time()),
    ))
    drop = insert_note(conn, Note(
        owner_id=1, tg_message_id=2, tg_chat_id=1,
        kind="post", title="drop", content="dropped",
        source_url=None, raw_caption=None,
        created_at=int(time.time()),
    ))
    soft_delete_note(conn, drop, reason="test")
    conn.close()

    zip_path = tmp_path / "out.zip"
    build_export(db_path=db_path, attachments_dir=None,
                 output_path=zip_path, lite=True)

    with zipfile.ZipFile(zip_path) as z:
        with z.open("notes.json") as f:
            data = json.load(f)
    ids = {n["id"] for n in data}
    assert keep in ids
    assert drop not in ids
    for n in data:
        assert n["thin_content"] in (0, 1)  # COALESCE keeps it numeric, not bool


def test_export_strips_owner_secrets(tmp_path):
    """Exported DB must not leak API keys, GitHub tokens, VPS host/user,
    inbox_chat_id, or mirror repo. setup_step is reset so a recipient is
    forced through the wizard before the bot can run."""
    import sqlite3
    import zipfile

    db_path = tmp_path / "soroka.db"
    conn = open_db(str(db_path))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    conn.execute(
        "UPDATE owners SET jina_api_key=?, deepgram_api_key=?, openrouter_key=?, "
        "github_token=?, github_mirror_repo=?, vps_host=?, vps_user=?, "
        "inbox_chat_id=?, setup_step='done' WHERE telegram_id=1",
        ("jina-secret", "dg-secret", "or-secret", "ghp-token",
         "user/repo", "host.example.com", "ubuntu", -100123),
    )
    conn.commit()
    conn.close()

    out = tmp_path / "export.zip"
    build_export(db_path=db_path, attachments_dir=None,
                 output_path=out, lite=True)

    with zipfile.ZipFile(out) as z:
        z.extract("soroka.db", path=tmp_path / "extracted")
    extracted = sqlite3.connect(tmp_path / "extracted" / "soroka.db")
    try:
        row = extracted.execute(
            "SELECT jina_api_key, deepgram_api_key, openrouter_key, github_token, "
            "github_mirror_repo, vps_host, vps_user, inbox_chat_id, setup_step "
            "FROM owners WHERE telegram_id=1"
        ).fetchone()
    finally:
        extracted.close()

    (jina, dg, oroute, ghtok, repo, host, user, inbox, step) = row
    assert jina is None
    assert dg is None
    assert oroute is None
    assert ghtok is None
    assert repo is None
    assert host is None
    assert user is None
    assert inbox is None
    assert step == "jina"


def test_export_captures_uncheckpointed_wal_writes(tmp_path):
    """Live DB in WAL mode may have pending writes that haven't reached
    the main file yet. The export must use sqlite3 .backup() so those
    writes are captured — a raw file copy would silently miss them."""
    import sqlite3
    import time
    import zipfile

    db_path = tmp_path / "soroka.db"
    conn = open_db(str(db_path))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    nid = insert_note(conn, Note(
        owner_id=1, tg_message_id=99, tg_chat_id=-1,
        kind="text", content="written-to-wal-only",
        created_at=int(time.time()),
    ))
    # Don't close the connection; keep the WAL hot. checkpoint wouldn't
    # be triggered automatically until the WAL is full or someone reads.
    out = tmp_path / "export.zip"
    build_export(db_path=db_path, attachments_dir=None,
                 output_path=out, lite=True)
    conn.close()

    with zipfile.ZipFile(out) as z:
        z.extract("soroka.db", path=tmp_path / "extracted")
    extracted = sqlite3.connect(tmp_path / "extracted" / "soroka.db")
    try:
        cur = extracted.execute(
            "SELECT content FROM notes WHERE id=?", (nid,))
        row = cur.fetchone()
    finally:
        extracted.close()
    assert row is not None and row[0] == "written-to-wal-only"


def test_export_includes_ru_summary(tmp_path):
    """Russian summaries on foreign-language URL captures must round-trip
    through the flat JSON dump so external consumers can see them."""
    db_path = tmp_path / "soroka.db"
    conn = open_db(str(db_path))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    nid = insert_note(conn, Note(
        owner_id=1, tg_message_id=1, tg_chat_id=1,
        kind="web", title="EN title", content="EN body",
        source_url="https://example.com/x",
        created_at=1, ru_summary="Сводка по-русски.",
    ))
    conn.close()

    zip_path = tmp_path / "out.zip"
    build_export(db_path=db_path, attachments_dir=None,
                 output_path=zip_path, lite=True)
    with zipfile.ZipFile(zip_path) as z:
        with z.open("notes.json") as f:
            data = json.load(f)
    rec = next(n for n in data if n["id"] == nid)
    assert rec["ru_summary"] == "Сводка по-русски."
