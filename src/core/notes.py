import logging
import sqlite3
from typing import Optional

from src.core.models import Note

logger = logging.getLogger(__name__)


def insert_note(conn: sqlite3.Connection, note: Note) -> Optional[int]:
    """Insert a note. Returns the new id, or None if a note with the same
    (owner_id, tg_chat_id, tg_message_id) already exists.

    Duplicates are logged so that operators can distinguish them from
    silent ingest bugs. Edits are handled by `update_note_by_message`,
    not by re-inserting.
    """
    cur = conn.execute(
        """INSERT OR IGNORE INTO notes
           (owner_id, tg_message_id, tg_chat_id, kind, title, content,
            source_url, raw_caption, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (note.owner_id, note.tg_message_id, note.tg_chat_id, note.kind,
         note.title, note.content, note.source_url, note.raw_caption,
         note.created_at),
    )
    conn.commit()
    if cur.rowcount == 0:
        logger.info(
            "note duplicate: owner=%s chat=%s msg=%s kind=%s — skipping reinsert",
            note.owner_id, note.tg_chat_id, note.tg_message_id, note.kind,
        )
        return None
    return cur.lastrowid


def get_note(conn: sqlite3.Connection, note_id: int) -> Optional[Note]:
    cur = conn.execute(
        """SELECT id, owner_id, tg_message_id, tg_chat_id, kind, title, content,
                  source_url, raw_caption, created_at
           FROM notes WHERE id = ?""",
        (note_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    fields = "id owner_id tg_message_id tg_chat_id kind title content source_url raw_caption created_at".split()
    return Note(**dict(zip(fields, row)))


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


def update_note_content(conn: sqlite3.Connection, note_id: int, *,
                         kind: str, title: Optional[str], content: str,
                         source_url: Optional[str], raw_caption: Optional[str]) -> None:
    """Overwrite a note's mutable fields. The notes_au trigger refreshes
    FTS automatically; the caller is responsible for re-embedding via
    upsert_embedding."""
    conn.execute(
        """UPDATE notes
           SET kind = ?, title = ?, content = ?, source_url = ?, raw_caption = ?
           WHERE id = ?""",
        (kind, title, content, source_url, raw_caption, note_id),
    )
    conn.commit()


def list_recent_notes(conn: sqlite3.Connection, owner_id: int, limit: int = 20,
                      kind: Optional[str] = None) -> list[Note]:
    if kind is not None:
        cur = conn.execute(
            """SELECT id, owner_id, tg_message_id, tg_chat_id, kind, title, content,
                      source_url, raw_caption, created_at
               FROM notes WHERE owner_id = ? AND kind = ?
               ORDER BY created_at DESC LIMIT ?""",
            (owner_id, kind, limit),
        )
    else:
        cur = conn.execute(
            """SELECT id, owner_id, tg_message_id, tg_chat_id, kind, title, content,
                      source_url, raw_caption, created_at
               FROM notes WHERE owner_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (owner_id, limit),
        )
    fields = "id owner_id tg_message_id tg_chat_id kind title content source_url raw_caption created_at".split()
    return [Note(**dict(zip(fields, row))) for row in cur.fetchall()]
