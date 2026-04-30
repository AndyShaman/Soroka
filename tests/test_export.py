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
