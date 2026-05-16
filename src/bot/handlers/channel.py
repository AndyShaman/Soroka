import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters

from src.adapters.deepgram import DeepgramClient
from src.adapters.jina import JinaClient
from src.adapters.openrouter import OpenRouterClient
from src.adapters.tg_files import is_oversized
from src.bot.handlers import media_group
from src.bot.handlers.reactions import (
    set_reaction, PROCESSING, SUCCESS, FAILURE, OVERSIZED, THIN,
)
from src.core import sibling_index
from src.core.ingest import ingest_text, ingest_voice, ingest_document
from src.core.kind import detect_kind_from_message
from src.core.owners import get_owner

logger = logging.getLogger(__name__)


# Tight pair-detection window: in practice "type comment, immediately
# forward" finishes in under a second. 2 s leaves room for slow taps
# without admitting unrelated posts the user dropped a moment apart.
_PAIR_WINDOW_SEC = 2.0


@dataclass
class _RecentSolo:
    note_id: int
    is_forward: bool
    date_ts: float
    chat_id: int


# Process-local buffer of "last single-message ingest per chat", used
# only by the comment+forward pair detector. Keyed by chat_id so two
# unrelated chats never accidentally pair across each other.
_recent_solo: dict[int, _RecentSolo] = {}


async def channel_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    owner = get_owner(conn, settings.owner_telegram_id)

    if not owner or owner.setup_step != "done":
        return  # bot not configured yet

    msg = update.channel_post or update.edited_channel_post
    if msg is None:
        return
    is_edit = update.edited_channel_post is not None

    if owner.inbox_chat_id is None or msg.chat.id != owner.inbox_chat_id:
        return

    # Self-forward filter: /sync probes work by forwarding a channel post
    # back into the same channel (then deleting the copy ~100ms later).
    # Without this guard the bot would re-ingest its own probe before the
    # delete arrives, creating a duplicate note. forward_origin.chat.id
    # equal to the current chat id reliably identifies a self-forward;
    # forward_from_chat is a legacy fallback for older Bot API payloads.
    fwd_origin = getattr(msg, "forward_origin", None)
    if fwd_origin is not None:
        origin_chat = getattr(fwd_origin, "chat", None)
        if origin_chat is not None and origin_chat.id == msg.chat.id:
            return
    fwd_chat = getattr(msg, "forward_from_chat", None)
    if fwd_chat is not None and fwd_chat.id == msg.chat.id:
        return

    text = msg.text or msg.caption or ""
    if text.startswith("/"):
        return  # commands meant for the owner, not knowledge-base content

    chat_id = msg.chat.id
    msg_id = msg.message_id

    if msg.media_group_id is not None:
        # Album: defer ingest, let media_group.buffer_message collect every
        # message of the group and flush once as a single note.
        await set_reaction(ctx.bot, chat_id, msg_id, PROCESSING)
        await media_group.buffer_message(
            msg, ctx, flush_callback=media_group.flush_album,
        )
        return

    await set_reaction(ctx.bot, chat_id, msg_id, PROCESSING)
    try:
        note_id = await _route_and_ingest(ctx, conn, owner, msg, is_edit=is_edit)
        emoji = SUCCESS
        if isinstance(note_id, int):
            from src.core.notes import get_note
            note = get_note(conn, note_id)
            if note and note.thin_content:
                emoji = THIN
        await set_reaction(ctx.bot, chat_id, msg_id, emoji)
    except _OversizedFile:
        await set_reaction(ctx.bot, chat_id, msg_id, OVERSIZED)
        return
    except Exception:
        logger.exception("ingest failed")
        await set_reaction(ctx.bot, chat_id, msg_id, FAILURE)
        return

    # Pair-detection runs only on edits-to-fresh-content paths where we
    # actually have a note id. Edits don't form new pairs (the original
    # message was either already paired at first ingest or not paired
    # at all — re-pairing on edit would re-embed gratuitously).
    if isinstance(note_id, int) and not is_edit:
        await _maybe_pair_with_previous(ctx, conn, owner, msg, note_id)


class _OversizedFile(Exception):
    pass


async def _maybe_pair_with_previous(ctx, conn, owner, msg, note_id: int) -> None:
    """If the previous solo ingest in this chat was within 2 s and forms
    a "exactly 1 text + 1 forward" pair with the current message, mutually
    reindex the two notes so each one's FTS row and embedding contain
    the other's text. Then update the buffer to point at this message.

    All buffer updates happen even when no pair fires — the next message
    looks back at *this* one."""
    chat_id = msg.chat.id
    this_is_forward = sibling_index.is_forward(msg)
    this_ts = msg.date.timestamp()

    prev = _recent_solo.get(chat_id)
    pair_eligible = (
        prev is not None
        and abs(this_ts - prev.date_ts) <= _PAIR_WINDOW_SEC
        and prev.is_forward != this_is_forward
    )
    if pair_eligible:
        try:
            jina = JinaClient(api_key=owner.jina_api_key)
            await sibling_index.reindex_pair(
                conn, jina=jina,
                note_a_id=prev.note_id, note_b_id=note_id,
            )
        except Exception:
            logger.exception(
                "sibling reindex failed for %s + %s", prev.note_id, note_id,
            )

    _recent_solo[chat_id] = _RecentSolo(
        note_id=note_id, is_forward=this_is_forward,
        date_ts=this_ts, chat_id=chat_id,
    )


def _safe_filename(raw: str | None, fallback_id: str) -> str:
    """Strip path components from a Telegram-supplied filename.

    Telegram passes document.file_name as the user named it on their device.
    A name like `../../etc/passwd` would let an attacker write files outside
    the per-message attachment directory. Path(...).name keeps only the
    basename; empty results fall back to the unique file id.
    """
    if raw:
        base = Path(raw).name
        if base and base not in (".", ".."):
            return base
    return f"document_{fallback_id}"


def _extract_entity_urls(msg) -> list[str]:
    """Lift URLs out of message entities — both the text-level and
    caption-level lists. Telegram exposes two entity kinds we care about:

    - `text_link`: a Markdown embed like `[Watch](https://...)`. The URL
      lives on `entity.url`; the plain text has only the visible label,
      so URL-detecting extractors miss it entirely. This is what causes
      forwarded "📱 Смотреть на YouTube" posts to lose the link.
    - `url`: a plain URL the user typed in the visible text. We capture
      it here too so the column reliably holds every URL Telegram
      believes the message contains, even when the body text wouldn't
      survive later sanitization.

    Returns URLs in document order, deduplicated, preserving first
    occurrence. Returns an empty list when the message carries no
    relevant entities.
    """
    seen: set[str] = set()
    out: list[str] = []

    def _absorb(text: Optional[str], entities) -> None:
        if not entities:
            return
        for ent in entities:
            url = getattr(ent, "url", None)
            if not url and ent.type == "url" and text is not None:
                url = text[ent.offset:ent.offset + ent.length]
            if url and url not in seen:
                seen.add(url)
                out.append(url)

    _absorb(getattr(msg, "text", None), getattr(msg, "entities", None))
    _absorb(getattr(msg, "caption", None), getattr(msg, "caption_entities", None))
    return out


async def _route_and_ingest(ctx, conn, owner, msg, *, is_edit: bool = False) -> Optional[int]:
    kind = detect_kind_from_message(msg)
    jina = JinaClient(api_key=owner.jina_api_key)
    deepgram = DeepgramClient(api_key=owner.deepgram_api_key)

    # Capture entity URLs once per message; passed unchanged into every
    # ingest path that takes them (text + document + post). None if no
    # entities carried a URL so the column stays NULL on plain messages.
    entity_urls = _extract_entity_urls(msg) or None

    if kind in ("text", "web", "youtube"):
        text = msg.text or msg.caption or ""
        # Build the OpenRouter client only when summarisation is even
        # possible: the owner has a key and a primary model. ingest_text
        # treats openrouter=None as "skip RU summary", so plain text and
        # under-configured owners just pass through unchanged.
        openrouter = (
            OpenRouterClient(api_key=owner.openrouter_key)
            if owner.openrouter_key and owner.primary_model
            else None
        )
        return await ingest_text(
            conn, jina=jina, owner_id=owner.telegram_id,
            tg_chat_id=msg.chat.id, tg_message_id=msg.message_id,
            text=text, caption=msg.caption, created_at=int(msg.date.timestamp()),
            is_edit=is_edit,
            openrouter=openrouter,
            primary_model=owner.primary_model,
            fallback_model=owner.fallback_model,
            extracted_urls=entity_urls,
        )

    if kind == "voice":
        voice = msg.voice
        if is_oversized(voice.file_size or 0):
            raise _OversizedFile
        f = await ctx.bot.get_file(voice.file_id)
        audio = await f.download_as_bytearray()
        return await ingest_voice(
            conn, deepgram=deepgram, jina=jina, owner_id=owner.telegram_id,
            tg_chat_id=msg.chat.id, tg_message_id=msg.message_id,
            audio_bytes=bytes(audio), mime=voice.mime_type or "audio/ogg",
            caption=msg.caption, created_at=int(msg.date.timestamp()),
            is_edit=is_edit,
        )

    if kind in ("pdf", "docx", "xlsx", "text_file"):
        doc = msg.document
        size = doc.file_size or 0
        if is_oversized(size):
            await ingest_document(
                conn, jina=jina, owner_id=owner.telegram_id,
                tg_chat_id=msg.chat.id, tg_message_id=msg.message_id,
                local_path=None, original_name=doc.file_name,
                kind="oversized", file_size=size,
                caption=msg.caption, created_at=int(msg.date.timestamp()),
                is_oversized=True, is_edit=is_edit,
                extracted_urls=entity_urls,
            )
            raise _OversizedFile

        f = await ctx.bot.get_file(doc.file_id)
        local_dir = Path("/app/data/attachments") / str(msg.message_id)
        local_dir.mkdir(parents=True, exist_ok=True)
        safe_name = _safe_filename(doc.file_name, doc.file_unique_id)
        local_path = local_dir / safe_name
        # On caption-only edits Telegram does not redeliver the file.
        if not (is_edit and local_path.exists()):
            await f.download_to_drive(custom_path=str(local_path))

        return await ingest_document(
            conn, jina=jina, owner_id=owner.telegram_id,
            tg_chat_id=msg.chat.id, tg_message_id=msg.message_id,
            local_path=local_path, original_name=doc.file_name,
            kind=kind, file_size=size,
            caption=msg.caption, created_at=int(msg.date.timestamp()),
            is_oversized=False, is_edit=is_edit,
            extracted_urls=entity_urls,
        )

    if kind in ("image", "post"):
        photo = msg.photo[-1]  # largest
        size = photo.file_size or 0
        if is_oversized(size):
            raise _OversizedFile
        f = await ctx.bot.get_file(photo.file_id)
        local_dir = Path("/app/data/attachments") / str(msg.message_id)
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / f"photo_{photo.file_unique_id}.jpg"
        if not (is_edit and local_path.exists()):
            await f.download_to_drive(custom_path=str(local_path))

        return await ingest_document(
            conn, jina=jina, owner_id=owner.telegram_id,
            tg_chat_id=msg.chat.id, tg_message_id=msg.message_id,
            local_path=local_path, original_name=local_path.name,
            kind=kind, file_size=size,
            caption=msg.caption, created_at=int(msg.date.timestamp()),
            is_oversized=False, is_edit=is_edit,
            extracted_urls=entity_urls,
        )


def register_channel_handlers(app: Application) -> None:
    app.add_handler(MessageHandler(
        filters.UpdateType.CHANNEL_POST | filters.UpdateType.EDITED_CHANNEL_POST,
        channel_handler,
    ))
