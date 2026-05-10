import json
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

# Owner-table columns that hold secrets or identity data we never ship in
# an export. The DB snapshot is written via sqlite3.Connection.backup(),
# which is WAL-aware (so we don't ship a half-written file), and then the
# copy is scrubbed before being added to the zip.
_SECRET_COLUMNS = (
    "jina_api_key",
    "deepgram_api_key",
    "openrouter_key",
    "github_token",
    "github_mirror_repo",
    "vps_host",
    "vps_user",
    "inbox_chat_id",
    # The daily backup job stores raw HTTP error bodies here. GitHub
    # responses can echo URL fragments or tokens in failure cases, so we
    # treat the column as untrusted and strip it on export.
    "last_backup_error",
)


def build_export(*, db_path: Path, attachments_dir: Optional[Path],
                 output_path: Path, lite: bool = False) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="soroka-export-") as tmp:
        safe_db = Path(tmp) / "soroka.db"
        _make_safe_db_copy(db_path, safe_db)
        # Read notes from the snapshot, not the live DB. Reading from live
        # races with concurrent writers and can produce a notes.json that
        # disagrees with the bundled soroka.db (a write that landed between
        # the two reads is in one but not the other).
        notes = _read_notes(safe_db)

        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.write(safe_db, arcname="soroka.db")
            z.writestr("notes.json", json.dumps(notes, ensure_ascii=False, indent=2))
            z.writestr("README.md", _readme())

            if not lite and attachments_dir and attachments_dir.exists():
                for path in attachments_dir.rglob("*"):
                    if path.is_file():
                        arc = "attachments/" + str(path.relative_to(attachments_dir))
                        z.write(path, arcname=arc)
    return output_path


def _make_safe_db_copy(src: Path, dst: Path) -> None:
    """Atomic snapshot via sqlite3 .backup() (handles WAL), then redact
    secrets from the copy. Caller never touches the live DB file directly,
    so we don't need a writer lock on src."""
    src_conn = sqlite3.connect(str(src))
    try:
        dst_conn = sqlite3.connect(str(dst))
        try:
            src_conn.backup(dst_conn)
            sets = ", ".join(f"{c}=NULL" for c in _SECRET_COLUMNS)
            dst_conn.execute(f"UPDATE owners SET {sets}")
            dst_conn.execute("UPDATE owners SET setup_step='jina'")
            dst_conn.commit()
            dst_conn.execute("VACUUM")
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


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
        "- `soroka.db` — SQLite snapshot (FTS5+vec). API keys and identity "
        "fields are stripped; restoring requires re-running setup.\n"
        "- `notes.json` — flat JSON dump of notes.\n"
        "- `attachments/` — files referenced by notes (omitted in lite export).\n"
    )
