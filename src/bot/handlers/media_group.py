"""Buffering of Telegram media-group messages so one forwarded post with N
photos lands as exactly one note."""
import asyncio
import logging
from collections import defaultdict
from pathlib import Path

from src.adapters.extractors.ocr import extract_ocr
from src.adapters.jina import JinaClient
from src.adapters.tg_files import is_oversized
from src.bot.handlers.reactions import (
    set_reaction, SUCCESS, FAILURE,
)
from src.core.attachments import insert_attachment
from src.core.ingest import _save_or_update_note
from src.core.kind import _is_post_caption
from src.core.models import Attachment, Note
from src.core.owners import get_owner

logger = logging.getLogger(__name__)

FLUSH_DELAY_SEC = 1.5
PER_PHOTO_OCR_CAP = 500
MIN_OCR_FRAGMENT_CHARS = 20
PHOTO_DIR_ROOT = Path("/app/data/attachments")

_pending: dict[tuple[int, str], list] = defaultdict(list)
_timers: dict[tuple[int, str], asyncio.Task] = {}


def _album_kind(caption: str | None) -> str:
    """An album with a substantive caption is a 'post' (the caption is
    the content); otherwise it's a plain 'image' album. Same rule as the
    existing single-photo path uses, so behaviour stays consistent."""
    return "post" if _is_post_caption(caption) else "image"


def _build_body(caption: str | None, ocr_fragments: list[str]) -> str:
    """Caption first (full), then each OCR fragment (truncated to
    PER_PHOTO_OCR_CAP). Fragments shorter than MIN_OCR_FRAGMENT_CHARS
    after strip are dropped — OCR on stylized images often produces a
    handful of garbage characters that hurt search."""
    parts = []
    if caption and caption.strip():
        parts.append(caption.strip())
    for frag in ocr_fragments:
        s = frag.strip()
        if len(s) < MIN_OCR_FRAGMENT_CHARS:
            continue
        parts.append(s[:PER_PHOTO_OCR_CAP])
    return "\n\n".join(parts)


def _pick_anchor(msgs):
    """The single message we use as the note's tg_message_id. Smallest
    id is deterministic and roughly matches Telegram delivery order."""
    return min(msgs, key=lambda m: m.message_id)


def _merged_caption(msgs):
    """Telegram normally puts the post caption on exactly one message of
    a media group. Concatenate defensively if multiple are present so we
    don't silently lose content."""
    captions = [m.caption.strip() for m in msgs if m.caption and m.caption.strip()]
    if not captions:
        return None
    return "\n\n".join(captions)


def _merged_entity_urls(msgs) -> list[str]:
    """Walk every message in the album and pull URLs from its caption_entities
    (and text/entities for the rare case of a non-photo first message).
    Same dedup-by-first-seen semantics as the single-message path."""
    seen: set[str] = set()
    out: list[str] = []
    for m in msgs:
        for text, entities in (
            (getattr(m, "text", None), getattr(m, "entities", None)),
            (getattr(m, "caption", None), getattr(m, "caption_entities", None)),
        ):
            if not entities:
                continue
            for ent in entities:
                url = getattr(ent, "url", None)
                if not url and ent.type == "url" and text is not None:
                    url = text[ent.offset:ent.offset + ent.length]
                if url and url not in seen:
                    seen.add(url)
                    out.append(url)
    return out


def _reset_for_tests() -> None:
    """Drop all buffered state. Tests call this in setup so module-level
    globals don't leak between cases."""
    for t in _timers.values():
        t.cancel()
    _timers.clear()
    _pending.clear()


async def buffer_message(msg, ctx, *, flush_callback,
                          delay: float = FLUSH_DELAY_SEC) -> None:
    """Add a media-group message to the buffer and (re)start the flush
    timer. Returns immediately; flush_callback runs after `delay` seconds
    of no new messages arriving for the same group."""
    key = (msg.chat.id, msg.media_group_id)
    _pending[key].append(msg)

    existing = _timers.get(key)
    if existing is not None:
        existing.cancel()

    _timers[key] = asyncio.create_task(
        _flush_after(key, ctx, flush_callback, delay)
    )


async def _flush_after(key, ctx, flush_callback, delay: float) -> None:
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        return

    msgs = _pending.pop(key, [])
    _timers.pop(key, None)
    if not msgs:
        return
    try:
        await flush_callback(msgs, ctx)
    except Exception:
        logger.exception("media_group flush failed for key=%s", key)


async def _download_photo(ctx, msg) -> tuple[Path, int] | None:
    """Download the largest variant of msg.photo to its per-message dir.
    Returns (local_path, file_size) on success, None on failure."""
    photo = msg.photo[-1]
    size = photo.file_size or 0
    if is_oversized(size):
        return None
    try:
        f = await ctx.bot.get_file(photo.file_id)
    except Exception:
        logger.exception("get_file failed for photo %s", photo.file_unique_id)
        return None
    local_dir = PHOTO_DIR_ROOT / str(msg.message_id)
    local_dir.mkdir(parents=True, exist_ok=True)
    local_path = local_dir / f"photo_{photo.file_unique_id}.jpg"
    try:
        await f.download_to_drive(custom_path=str(local_path))
    except Exception:
        logger.exception("download failed for photo %s", photo.file_unique_id)
        return None
    return local_path, size


async def _react_all(ctx, msgs, emoji) -> None:
    for m in msgs:
        try:
            await set_reaction(ctx.bot, m.chat.id, m.message_id, emoji)
        except Exception:
            logger.exception("set_reaction failed for %s", m.message_id)


async def flush_album(msgs, ctx) -> None:
    """Take the buffered messages of one media group, download every
    attached photo, run OCR on each, and persist as a single note with
    N rows in the attachments table."""
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    owner = get_owner(conn, settings.owner_telegram_id)
    if owner is None:
        logger.warning("flush_album: no owner")
        return

    anchor = _pick_anchor(msgs)
    caption = _merged_caption(msgs)

    downloaded: list[tuple[object, Path, int]] = []
    ocr_fragments: list[str] = []
    for m in msgs:
        if not m.photo:
            continue
        result = await _download_photo(ctx, m)
        if result is None:
            continue
        path, size = result
        downloaded.append((m, path, size))
        ocr_fragments.append(extract_ocr(path) or "")

    if not downloaded:
        logger.warning("flush_album: no photos saved for group")
        await _react_all(ctx, msgs, FAILURE)
        return

    body = _build_body(caption, ocr_fragments)
    kind = _album_kind(caption)
    fallback_name = downloaded[0][1].name
    title = (caption or "").splitlines()[0][:80] if caption else fallback_name

    jina = JinaClient(api_key=owner.jina_api_key)
    entity_urls = _merged_entity_urls(msgs) or None
    note = Note(
        owner_id=owner.telegram_id,
        tg_message_id=anchor.message_id,
        tg_chat_id=anchor.chat.id,
        kind=kind,
        title=title,
        content=body or fallback_name,
        raw_caption=caption,
        created_at=int(anchor.date.timestamp()),
        thin_content=False,
        extracted_urls=entity_urls,
    )
    note_id = await _save_or_update_note(
        conn, jina=jina, note=note, is_edit=False, embed_text=body,
    )
    if note_id is None:
        logger.warning("flush_album: insert lost a duplicate race")
        return

    for _m, path, size in downloaded:
        insert_attachment(conn, Attachment(
            note_id=note_id,
            file_path=str(path),
            file_size=size,
            original_name=path.name,
            is_oversized=False,
        ))

    await _react_all(ctx, msgs, SUCCESS)
