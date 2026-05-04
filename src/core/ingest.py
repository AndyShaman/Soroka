import logging
import sqlite3
from pathlib import Path
from typing import Optional

from src.core.kind import detect_kind_from_text
from src.core.models import Note, Attachment
from src.core.notes import (
    insert_note, find_note_id_by_message, update_note_content,
)
from src.core.vec import upsert_embedding
from src.core.attachments import insert_attachment
from src.adapters.extractors.web import extract_web
from src.adapters.extractors.pdf import extract_pdf
from src.adapters.extractors.docx import extract_docx
from src.adapters.extractors.xlsx import extract_xlsx
from src.adapters.extractors.ocr import extract_ocr

logger = logging.getLogger(__name__)

THIN_MIN_CHARS = 200
THIN_MIN_WORDS = 30


def _is_thin(body: str) -> bool:
    """An extractor result counts as 'thin' when there's not enough
    text to embed meaningfully. Short user-typed text doesn't go through
    extractors, so it never reaches this check."""
    s = body.strip()
    return len(s) < THIN_MIN_CHARS or len(s.split()) < THIN_MIN_WORDS


async def _save_or_update_note(conn: sqlite3.Connection, *, jina,
                                note: Note, is_edit: bool,
                                embed_text: str) -> Optional[int]:
    """Insert a new note or, on edit, update the existing one in place
    and re-embed. Returns the resulting note id, or None if a new-post
    insert lost a duplicate race."""
    if is_edit:
        existing_id = find_note_id_by_message(
            conn, note.owner_id, note.tg_chat_id, note.tg_message_id,
        )
        if existing_id is not None:
            update_note_content(
                conn, existing_id,
                kind=note.kind, title=note.title, content=note.content,
                source_url=note.source_url, raw_caption=note.raw_caption,
            )
            if embed_text.strip():
                embedding = await jina.embed(embed_text[:8000], role="passage")
                upsert_embedding(conn, existing_id, embedding)
            logger.info(
                "note edited: id=%s owner=%s chat=%s msg=%s",
                existing_id, note.owner_id, note.tg_chat_id, note.tg_message_id,
            )
            return existing_id
        # Edit of a message we never saw (bot was offline) — fall through
        # to a fresh insert.

    note_id = insert_note(conn, note)
    if note_id is None:
        return None
    if embed_text.strip():
        embedding = await jina.embed(embed_text[:8000], role="passage")
        upsert_embedding(conn, note_id, embedding)
    return note_id


async def ingest_text(conn: sqlite3.Connection, *, jina, owner_id: int,
                      tg_chat_id: int, tg_message_id: int,
                      text: str, caption: Optional[str], created_at: int,
                      is_edit: bool = False) -> Optional[int]:
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
        is_thin = _is_thin(body)
    elif kind == "youtube":
        from src.adapters.extractors.youtube import extract_youtube
        title, body = extract_youtube(raw)
        source_url = raw
        body = body or raw
        is_thin = _is_thin(body)
    else:
        title = _make_title(raw)
        is_thin = False

    note = Note(
        owner_id=owner_id, tg_message_id=tg_message_id, tg_chat_id=tg_chat_id,
        kind=kind, title=title, content=body.strip(),
        source_url=source_url, raw_caption=caption, created_at=created_at,
        thin_content=is_thin,
    )
    return await _save_or_update_note(conn, jina=jina, note=note,
                                       is_edit=is_edit, embed_text=body.strip())


def _make_title(text: str) -> str:
    first_line = text.strip().splitlines()[0]
    return first_line[:80]


async def ingest_voice(conn: sqlite3.Connection, *, deepgram, jina,
                        owner_id: int, tg_chat_id: int, tg_message_id: int,
                        audio_bytes: bytes, mime: str,
                        caption: Optional[str], created_at: int,
                        is_edit: bool = False) -> Optional[int]:
    transcript = await deepgram.transcribe(audio_bytes, mime=mime)
    if not transcript.strip():
        return None

    note = Note(
        owner_id=owner_id, tg_message_id=tg_message_id, tg_chat_id=tg_chat_id,
        kind="voice", title=_make_title(transcript), content=transcript.strip(),
        raw_caption=caption, created_at=created_at,
        thin_content=_is_thin(transcript),
    )
    return await _save_or_update_note(conn, jina=jina, note=note,
                                       is_edit=is_edit, embed_text=transcript)


async def ingest_document(conn: sqlite3.Connection, *, jina, owner_id: int,
                          tg_chat_id: int, tg_message_id: int,
                          local_path: Optional[Path], original_name: str,
                          kind: str, file_size: int,
                          caption: Optional[str], created_at: int,
                          is_oversized: bool,
                          is_edit: bool = False) -> Optional[int]:
    if is_oversized:
        body = f"[oversized] {original_name} ({file_size} bytes)\n{caption or ''}"
        title = original_name
        is_thin = False
    elif kind == "pdf":
        body = extract_pdf(local_path)
        title = original_name
        is_thin = _is_thin(body or "")
    elif kind == "docx":
        body = extract_docx(local_path)
        title = original_name
        is_thin = _is_thin(body or "")
    elif kind == "xlsx":
        body = extract_xlsx(local_path)
        title = original_name
        is_thin = _is_thin(body or "")
    elif kind == "image":
        ocr = extract_ocr(local_path) or ""
        # Caption (user's own words) is the strongest semantic signal; OCR
        # is supplementary and often noisy on stylized images.
        parts = [p for p in (caption or "", ocr) if p.strip()]
        body = "\n\n".join(parts) or original_name
        title = caption or original_name
        is_thin = (caption or "").strip() == "" and _is_thin(ocr)
    elif kind == "post":
        # Forwarded Telegram post: caption IS the content; the photo is
        # just a link preview. OCR is rarely useful here (logos, hero
        # images), so we add it only if it surfaced something readable.
        ocr = extract_ocr(local_path) or ""
        parts = [(caption or "").strip()]
        if len(ocr.strip()) > 20:
            parts.append(ocr.strip())
        body = "\n\n".join(p for p in parts if p) or original_name
        title = (caption or "").splitlines()[0][:80] if caption else original_name
        is_thin = False
    else:
        body = caption or original_name
        title = original_name
        is_thin = False

    note = Note(
        owner_id=owner_id, tg_message_id=tg_message_id, tg_chat_id=tg_chat_id,
        kind=kind, title=title, content=body.strip() or original_name,
        raw_caption=caption, created_at=created_at,
        thin_content=is_thin,
    )
    embed_text = "" if is_oversized else body.strip()
    note_id = await _save_or_update_note(
        conn, jina=jina, note=note, is_edit=is_edit, embed_text=embed_text,
    )
    if note_id is None:
        return None

    # On edit the attachment row already exists from the original ingest;
    # Telegram doesn't replace the file on caption edits.
    if not is_edit:
        insert_attachment(conn, Attachment(
            note_id=note_id,
            file_path=str(local_path) if local_path else "",
            file_size=file_size,
            original_name=original_name,
            is_oversized=is_oversized,
        ))
    return note_id
