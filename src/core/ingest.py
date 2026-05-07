import logging
import sqlite3
from pathlib import Path
from typing import Optional

from src.core.kind import detect_kind_from_text
from src.core.models import Note, Attachment
from src.core.notes import (
    insert_note, find_note_id_by_message, update_note_content,
)
from src.core.translate import is_russian, summarize_ru
from src.core.vec import upsert_embedding
from src.core.attachments import insert_attachment
from src.adapters.extractors.web import extract_web, find_first_url
from src.adapters.extractors.pdf import extract_pdf
from src.adapters.extractors.docx import extract_docx
from src.adapters.extractors.xlsx import extract_xlsx
from src.adapters.extractors.ocr import extract_ocr
from src.adapters.extractors.text import extract_text_file

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
    """Insert (or update on edit) a note and embed it as one atomic
    unit. If the Jina call fails, the note write is rolled back so we
    never end up with a BM25-only row that dense search can't see.

    Returns the resulting note id, or None if a new-post insert lost a
    duplicate race."""
    if is_edit:
        existing_id = find_note_id_by_message(
            conn, note.owner_id, note.tg_chat_id, note.tg_message_id,
        )
        if existing_id is not None:
            try:
                update_note_content(
                    conn, existing_id,
                    kind=note.kind, title=note.title, content=note.content,
                    source_url=note.source_url, raw_caption=note.raw_caption,
                    ru_summary=note.ru_summary, commit=False,
                )
                if embed_text.strip():
                    embedding = await jina.embed(embed_text[:8000], role="passage")
                    upsert_embedding(conn, existing_id, embedding)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            logger.info(
                "note edited: id=%s owner=%s chat=%s msg=%s",
                existing_id, note.owner_id, note.tg_chat_id, note.tg_message_id,
            )
            return existing_id
        # Edit of a message we never saw (bot was offline) — fall through
        # to a fresh insert.

    try:
        note_id = insert_note(conn, note, commit=False)
        if note_id is None:
            conn.rollback()
            return None
        if embed_text.strip():
            embedding = await jina.embed(embed_text[:8000], role="passage")
            upsert_embedding(conn, note_id, embedding)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return note_id


async def ingest_text(conn: sqlite3.Connection, *, jina, owner_id: int,
                      tg_chat_id: int, tg_message_id: int,
                      text: str, caption: Optional[str], created_at: int,
                      is_edit: bool = False,
                      openrouter=None, primary_model: Optional[str] = None,
                      fallback_model: Optional[str] = None,
                      ) -> Optional[int]:
    if not text.strip():
        return None
    raw = text.strip()
    kind = detect_kind_from_text(raw)

    title: Optional[str] = None
    body = raw
    source_url: Optional[str] = None
    extracted_only = ""  # Body of the linked article only, for language detection.

    if kind == "web":
        url = find_first_url(raw) or raw
        title, extracted = extract_web(url)
        source_url = url
        body = _merge_user_text_with_extract(raw, url, extracted)
        extracted_only = (extracted or "").strip()
        # Thin only when the extractor itself produced nothing useful;
        # the user's wrap text doesn't make the linked article richer,
        # so it shouldn't disguise an extractor failure.
        is_thin = _is_thin(extracted_only)
    elif kind == "youtube":
        from src.adapters.extractors.youtube import extract_youtube
        url = find_first_url(raw) or raw
        title, extracted = extract_youtube(url)
        source_url = url
        body = _merge_user_text_with_extract(raw, url, extracted)
        extracted_only = (extracted or "").strip()
        is_thin = _is_thin(extracted_only)
    else:
        title = _make_title(raw)
        is_thin = False

    # For URL kinds (web/youtube) whose extracted body is non-Russian, ask
    # the LLM for a short Russian description. Skipped silently if the
    # caller didn't pass an openrouter client (tests, edit-replay paths).
    #
    # Edit-cache: if this is an edit of a note that already carries a
    # summary for the same source_url, reuse it. Caption-only edits are
    # frequent (typo fixes, hashtag cleanup) and re-billing OpenRouter
    # for them produces the same answer at extra cost and latency.
    ru_summary: Optional[str] = None
    if (kind in ("web", "youtube")
            and extracted_only
            and not is_russian(extracted_only)):
        cached = _existing_summary_for_url(
            conn, owner_id=owner_id, tg_chat_id=tg_chat_id,
            tg_message_id=tg_message_id, source_url=source_url,
        ) if is_edit else None
        if cached:
            ru_summary = cached
        else:
            ru_summary = await summarize_ru(
                openrouter, primary=primary_model, fallback=fallback_model,
                text=extracted_only,
            )

    # Concat the Russian summary into the embedding text so RU queries
    # surface foreign-language links via the dense index too. Stored body
    # stays untouched — display logic decides where to show the summary.
    embed_text = body.strip()
    if ru_summary:
        embed_text = f"{embed_text}\n\n{ru_summary}"

    note = Note(
        owner_id=owner_id, tg_message_id=tg_message_id, tg_chat_id=tg_chat_id,
        kind=kind, title=title, content=body.strip(),
        source_url=source_url, raw_caption=caption, created_at=created_at,
        thin_content=is_thin, ru_summary=ru_summary,
    )
    return await _save_or_update_note(conn, jina=jina, note=note,
                                       is_edit=is_edit, embed_text=embed_text)


def _existing_summary_for_url(conn: sqlite3.Connection, *, owner_id: int,
                                tg_chat_id: int, tg_message_id: int,
                                source_url: Optional[str]) -> Optional[str]:
    """Return the existing note's ru_summary iff it was captured for the
    same source_url. Used by ingest's edit path to short-circuit a fresh
    LLM call when only the caption changed.

    Returns None when no row exists, the URL changed, or the previous
    ingest didn't produce a summary.
    """
    if source_url is None:
        return None
    row = conn.execute(
        """SELECT source_url, ru_summary FROM notes
           WHERE owner_id = ? AND tg_chat_id = ? AND tg_message_id = ?""",
        (owner_id, tg_chat_id, tg_message_id),
    ).fetchone()
    if row is None:
        return None
    prev_url, prev_summary = row
    if prev_url != source_url or not prev_summary:
        return None
    return prev_summary


def _make_title(text: str) -> str:
    first_line = text.strip().splitlines()[0]
    return first_line[:80]


def _merge_user_text_with_extract(raw: str, url: str, extracted: str) -> str:
    """Combine the user's wrap-around text with the extractor body.

    Bare URL ("https://..."): keeps prior behaviour — body is the extracted
    article (or the URL itself if extraction came back empty).

    Wrapped URL ("Пробовали https://...?"): we want both signals in
    `content`. The user's note tells search what *they* think the link
    is about; the extracted article gives keywords from the linked page.
    Joining them lets either side surface the note in BM25/dense search.
    """
    raw_stripped = raw.strip()
    extracted = (extracted or "").strip()
    if raw_stripped == url:
        return extracted or url
    if not extracted:
        return raw_stripped
    return f"{raw_stripped}\n\n{extracted}"


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
        # Voice transcripts are never thin: a successful STT result is
        # genuine content even when it's a curt "да" or "через час".
        # thin_content stays as the marker for "extractor produced
        # nothing", and STT didn't.
        thin_content=False,
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
    elif kind == "text_file":
        # Plain-text file: caption (if any) is the user's own commentary
        # and goes first so it leads the snippet; the file body follows.
        # A short file with real content the user picked deliberately is
        # not thin — only mark thin when both the file body and the user
        # caption come back empty (binary garbage / empty .txt), so that
        # row stays out of default search results.
        file_body = extract_text_file(local_path) if local_path else ""
        caption_text = (caption or "").strip()
        parts = [caption_text, file_body]
        body = "\n\n".join(p for p in parts if p) or original_name
        title = original_name
        is_thin = not file_body and not caption_text
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
