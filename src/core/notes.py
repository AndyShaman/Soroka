import json
import logging
import sqlite3
import time
from typing import Optional

from src.core.models import Note


def _dump_extracted_urls(urls: Optional[list[str]]) -> Optional[str]:
    """Serialize an optional URL list to JSON for storage. Returns None
    for empty/missing lists so the column stays NULL on legacy paths."""
    if not urls:
        return None
    return json.dumps(urls, ensure_ascii=False)


def _load_extracted_urls(raw: Optional[str]) -> Optional[list[str]]:
    """Parse the JSON column back into a Python list. Tolerates bad
    payloads (returns None) since older rows pre-date the column and
    a hand-edited DB might have anything in it."""
    if not raw:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(value, list):
        return None
    return [str(u) for u in value if u]

logger = logging.getLogger(__name__)


def insert_note(conn: sqlite3.Connection, note: Note, *,
                 commit: bool = True) -> Optional[int]:
    """Insert a note. Returns the new id, or None if a note with the same
    (owner_id, tg_chat_id, tg_message_id) already exists.

    Duplicates are logged so that operators can distinguish them from
    silent ingest bugs. Edits are handled by `update_note_by_message`,
    not by re-inserting.

    Pass ``commit=False`` when the caller bundles this insert with later
    work (e.g. an embedding upsert) inside a single transaction so a
    failure further down can roll back the note row too.
    """
    cur = conn.execute(
        """INSERT OR IGNORE INTO notes
           (owner_id, tg_message_id, tg_chat_id, kind, title, content,
            source_url, raw_caption, created_at, thin_content, ru_summary,
            extracted_urls)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (note.owner_id, note.tg_message_id, note.tg_chat_id, note.kind,
         note.title, note.content, note.source_url, note.raw_caption,
         note.created_at, 1 if note.thin_content else 0, note.ru_summary,
         _dump_extracted_urls(note.extracted_urls)),
    )
    if commit:
        conn.commit()
    if cur.rowcount == 0:
        logger.info(
            "note duplicate: owner=%s chat=%s msg=%s kind=%s — skipping reinsert",
            note.owner_id, note.tg_chat_id, note.tg_message_id, note.kind,
        )
        return None
    return cur.lastrowid


_NOTE_COLUMNS = (
    "id, owner_id, tg_message_id, tg_chat_id, kind, title, content, "
    "source_url, raw_caption, created_at, "
    "COALESCE(thin_content, 0), deleted_at, ru_summary, extracted_urls"
)
_NOTE_FIELDS = (
    "id owner_id tg_message_id tg_chat_id kind title content "
    "source_url raw_caption created_at thin_content deleted_at "
    "ru_summary extracted_urls"
).split()


def _row_to_note(row) -> Note:
    data = dict(zip(_NOTE_FIELDS, row))
    data["thin_content"] = bool(data["thin_content"])
    data["extracted_urls"] = _load_extracted_urls(data.get("extracted_urls"))
    return Note(**data)


def get_note(conn: sqlite3.Connection, note_id: int) -> Optional[Note]:
    cur = conn.execute(
        f"""SELECT {_NOTE_COLUMNS}
           FROM notes WHERE id = ? AND deleted_at IS NULL""",
        (note_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return _row_to_note(row)


def find_note_id_by_message(conn: sqlite3.Connection, owner_id: int,
                             tg_chat_id: int, tg_message_id: int) -> Optional[int]:
    """Look up a note's id by its Telegram coordinates. Used by the
    edited-post handler to decide between update and insert."""
    row = conn.execute(
        """SELECT id FROM notes
           WHERE owner_id = ? AND tg_chat_id = ? AND tg_message_id = ?""",
        (owner_id, tg_chat_id, tg_message_id),
    ).fetchone()
    return row[0] if row else None


_UNSET = object()


def update_note_content(conn: sqlite3.Connection, note_id: int, *,
                         kind: str, title: Optional[str], content: str,
                         source_url: Optional[str], raw_caption: Optional[str],
                         ru_summary=_UNSET, commit: bool = True) -> None:
    """Overwrite a note's mutable fields. The notes_au trigger refreshes
    FTS automatically; the caller is responsible for re-embedding via
    upsert_embedding.

    `ru_summary` uses a sentinel default so callers that don't manage it
    (e.g. older edit paths) leave the column untouched. Pass an explicit
    value (including ``None``) to overwrite.

    Pass ``commit=False`` when the caller bundles this update with a
    follow-up embedding call inside one transaction; the caller is then
    responsible for the commit/rollback boundary.
    """
    if ru_summary is _UNSET:
        conn.execute(
            """UPDATE notes
               SET kind = ?, title = ?, content = ?, source_url = ?, raw_caption = ?
               WHERE id = ?""",
            (kind, title, content, source_url, raw_caption, note_id),
        )
    else:
        conn.execute(
            """UPDATE notes
               SET kind = ?, title = ?, content = ?, source_url = ?,
                   raw_caption = ?, ru_summary = ?
               WHERE id = ?""",
            (kind, title, content, source_url, raw_caption, ru_summary, note_id),
        )
    if commit:
        conn.commit()


def list_recent_notes(conn: sqlite3.Connection, owner_id: int, limit: int = 20,
                      kind: Optional[str] = None) -> list[Note]:
    if kind is not None:
        cur = conn.execute(
            f"""SELECT {_NOTE_COLUMNS}
               FROM notes WHERE owner_id = ? AND kind = ? AND deleted_at IS NULL
               ORDER BY created_at DESC LIMIT ?""",
            (owner_id, kind, limit),
        )
    else:
        cur = conn.execute(
            f"""SELECT {_NOTE_COLUMNS}
               FROM notes WHERE owner_id = ? AND deleted_at IS NULL
               ORDER BY created_at DESC LIMIT ?""",
            (owner_id, limit),
        )
    return [_row_to_note(row) for row in cur.fetchall()]


def soft_delete_note(conn: sqlite3.Connection, note_id: int, *, reason: str) -> bool:
    """Mark a note as deleted without removing the row. Searches and
    list-recent skip soft-deleted notes; the row stays for possible
    restoration via raw SQL. Returns True if a row was affected.

    If this note was paired with a sibling (comment+forward injection),
    clear the sibling's `sibling_note_id` — the trailing UPDATE fires
    the notes_au trigger, which rewrites the sibling's FTS row from
    its own un-injected content. That prevents BM25 from continuing to
    score the survivor on text that came from the deleted partner."""
    sibling_row = conn.execute(
        "SELECT sibling_note_id FROM notes WHERE id = ?", (note_id,),
    ).fetchone()
    sibling_id = sibling_row[0] if sibling_row else None
    # A row pointing at itself would feed `rebuild_solo_fts` a junk
    # combined string and try to delete an FTS row that never existed
    # in that form. Treat it as an unpaired note instead.
    if sibling_id == note_id:
        sibling_id = None

    cur = conn.execute(
        "UPDATE notes SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
        (int(time.time()), note_id),
    )
    if cur.rowcount == 0:
        conn.commit()
        return False

    if sibling_id is not None:
        from src.core.sibling_index import rebuild_solo_fts
        rebuild_solo_fts(
            conn, survivor_id=sibling_id, deleted_partner_id=note_id,
        )
        conn.execute(
            "UPDATE notes SET sibling_note_id = NULL WHERE id IN (?, ?)",
            (sibling_id, note_id),
        )
    conn.commit()
    logger.info("note soft-deleted: id=%s reason=%s", note_id, reason)
    return True
