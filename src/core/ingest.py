import sqlite3
from pathlib import Path
from typing import Optional

from src.core.kind import detect_kind_from_text
from src.core.models import Note, Attachment
from src.core.notes import insert_note
from src.core.vec import upsert_embedding
from src.core.attachments import insert_attachment
from src.adapters.extractors.web import extract_web
from src.adapters.extractors.pdf import extract_pdf
from src.adapters.extractors.docx import extract_docx
from src.adapters.extractors.xlsx import extract_xlsx
from src.adapters.extractors.ocr import extract_ocr


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


async def ingest_voice(conn: sqlite3.Connection, *, deepgram, jina,
                        owner_id: int, tg_chat_id: int, tg_message_id: int,
                        audio_bytes: bytes, mime: str,
                        caption: Optional[str], created_at: int) -> Optional[int]:
    transcript = await deepgram.transcribe(audio_bytes, mime=mime)
    if not transcript.strip():
        return None

    note = Note(
        owner_id=owner_id, tg_message_id=tg_message_id, tg_chat_id=tg_chat_id,
        kind="voice", title=_make_title(transcript), content=transcript.strip(),
        raw_caption=caption, created_at=created_at,
    )
    note_id = insert_note(conn, note)
    if note_id is None:
        return None
    embedding = await jina.embed(transcript[:8000], role="passage")
    upsert_embedding(conn, note_id, embedding)
    return note_id


async def ingest_document(conn: sqlite3.Connection, *, jina, owner_id: int,
                          tg_chat_id: int, tg_message_id: int,
                          local_path: Optional[Path], original_name: str,
                          kind: str, file_size: int,
                          caption: Optional[str], created_at: int,
                          is_oversized: bool) -> Optional[int]:
    if is_oversized:
        body = f"[oversized] {original_name} ({file_size} bytes)\n{caption or ''}"
        title = original_name
    elif kind == "pdf":
        body = extract_pdf(local_path)
        title = original_name
    elif kind == "docx":
        body = extract_docx(local_path)
        title = original_name
    elif kind == "xlsx":
        body = extract_xlsx(local_path)
        title = original_name
    elif kind == "image":
        body = extract_ocr(local_path) or original_name
        title = caption or original_name
    else:
        body = caption or original_name
        title = original_name

    note = Note(
        owner_id=owner_id, tg_message_id=tg_message_id, tg_chat_id=tg_chat_id,
        kind=kind, title=title, content=body.strip() or original_name,
        raw_caption=caption, created_at=created_at,
    )
    note_id = insert_note(conn, note)
    if note_id is None:
        return None

    insert_attachment(conn, Attachment(
        note_id=note_id,
        file_path=str(local_path) if local_path else "",
        file_size=file_size,
        original_name=original_name,
        is_oversized=is_oversized,
    ))

    if not is_oversized and body.strip():
        embedding = await jina.embed(body.strip()[:8000], role="passage")
        upsert_embedding(conn, note_id, embedding)
    return note_id
