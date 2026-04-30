import sqlite3
from typing import Optional

from src.core.kind import detect_kind_from_text
from src.core.models import Note
from src.core.notes import insert_note
from src.core.vec import upsert_embedding


async def ingest_text(conn: sqlite3.Connection, *, jina, owner_id: int,
                      tg_chat_id: int, tg_message_id: int,
                      text: str, caption: Optional[str], created_at: int) -> Optional[int]:
    if not text.strip():
        return None
    raw = text.strip()
    kind = detect_kind_from_text(raw)

    title: Optional[str] = None
    body = raw
    source_url: Optional[str] = None

    if kind == "web":
        from src.adapters.extractors.web import extract_web
        title, body = extract_web(raw)
        source_url = raw
        body = body or raw
    elif kind == "youtube":
        from src.adapters.extractors.youtube import extract_youtube
        title, body = extract_youtube(raw)
        source_url = raw
        body = body or raw
    else:
        title = _make_title(raw)

    note = Note(
        owner_id=owner_id, tg_message_id=tg_message_id, tg_chat_id=tg_chat_id,
        kind=kind, title=title, content=body.strip(),
        source_url=source_url, raw_caption=caption, created_at=created_at,
    )
    note_id = insert_note(conn, note)
    if note_id is None:
        return None
    embedding = await jina.embed(body.strip()[:8000], role="passage")
    upsert_embedding(conn, note_id, embedding)
    return note_id


def _make_title(text: str) -> str:
    first_line = text.strip().splitlines()[0]
    return first_line[:80]
