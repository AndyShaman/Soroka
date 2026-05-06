import json
import sqlite3
import zipfile
from pathlib import Path
from typing import Optional


def build_export(*, db_path: Path, attachments_dir: Optional[Path],
                 output_path: Path, lite: bool = False) -> Path:
    notes = _read_notes(db_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.write(db_path, arcname="soroka.db")
        z.writestr("notes.json", json.dumps(notes, ensure_ascii=False, indent=2))
        z.writestr("README.md", _readme())

        if not lite and attachments_dir and attachments_dir.exists():
            for path in attachments_dir.rglob("*"):
                if path.is_file():
                    arc = "attachments/" + str(path.relative_to(attachments_dir))
                    z.write(path, arcname=arc)
    return output_path


def _read_notes(db_path: Path) -> list[dict]:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT id, owner_id, tg_message_id, tg_chat_id, kind, "
            "title, content, source_url, raw_caption, created_at, "
            "COALESCE(thin_content, 0) AS thin_content, ru_summary "
            "FROM notes WHERE deleted_at IS NULL ORDER BY id"
        )
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def _readme() -> str:
    return (
        "# Soroka export\n\n"
        "- `soroka.db` — full SQLite snapshot (FTS5+vec).\n"
        "- `notes.json` — flat JSON dump of notes.\n"
        "- `attachments/` — files referenced by notes (omitted in lite export).\n"
    )
