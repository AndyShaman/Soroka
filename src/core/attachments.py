import sqlite3
from src.core.models import Attachment


def insert_attachment(conn: sqlite3.Connection, att: Attachment) -> int:
    cur = conn.execute(
        """INSERT INTO attachments
           (note_id, file_path, file_size, mime_type, original_name, is_oversized)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (att.note_id, att.file_path, att.file_size, att.mime_type,
         att.original_name, int(att.is_oversized)),
    )
    conn.commit()
    assert cur.lastrowid is not None
    return cur.lastrowid


def list_attachments(conn: sqlite3.Connection, note_id: int) -> list[Attachment]:
    cur = conn.execute(
        """SELECT id, note_id, file_path, file_size, mime_type, original_name, is_oversized
           FROM attachments WHERE note_id = ?""",
        (note_id,),
    )
    fields = "id note_id file_path file_size mime_type original_name is_oversized".split()
    out = []
    for row in cur.fetchall():
        d = dict(zip(fields, row))
        d["is_oversized"] = bool(d["is_oversized"])
        out.append(Attachment(**d))
    return out
