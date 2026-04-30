import sqlite3
from typing import Optional

from src.core.models import Note


def insert_note(conn: sqlite3.Connection, note: Note) -> Optional[int]:
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


def list_recent_notes(conn: sqlite3.Connection, owner_id: int, limit: int = 20,
                      kind: Optional[str] = None) -> list[Note]:
    if kind:
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
