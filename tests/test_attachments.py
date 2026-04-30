# tests/test_attachments.py
from src.core.db import open_db, init_schema
from src.core.owners import create_or_get_owner
from src.core.notes import insert_note
from src.core.attachments import insert_attachment, list_attachments
from src.core.models import Note, Attachment

def test_insert_and_list_attachment(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    note_id = insert_note(conn, Note(
        owner_id=1, tg_message_id=1, tg_chat_id=-1,
        kind="pdf", content="x", created_at=1,
    ))
    insert_attachment(conn, Attachment(
        note_id=note_id, file_path="data/x.pdf",
        file_size=10, original_name="x.pdf",
    ))
    attachments = list_attachments(conn, note_id)
    assert len(attachments) == 1
    assert attachments[0].original_name == "x.pdf"
