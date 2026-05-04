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
