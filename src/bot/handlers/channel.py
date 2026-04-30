import logging
from pathlib import Path

from telegram import Update
from telegram.ext import Application, MessageHandler, ContextTypes, filters

from src.adapters.deepgram import DeepgramClient
from src.adapters.jina import JinaClient
from src.adapters.tg_files import is_oversized
from src.bot.handlers.reactions import (
    set_reaction, PROCESSING, SUCCESS, FAILURE, OVERSIZED,
)
from src.core.ingest import ingest_text, ingest_voice, ingest_document
from src.core.kind import detect_kind_from_message
from src.core.owners import get_owner

logger = logging.getLogger(__name__)


async def channel_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    owner = get_owner(conn, settings.owner_telegram_id)

    if not owner or owner.setup_step != "done":
        return  # bot not configured yet
    if owner.inbox_chat_id is None or update.channel_post.chat.id != owner.inbox_chat_id:
        return

    msg = update.channel_post
    chat_id = msg.chat.id
    msg_id = msg.message_id

    await set_reaction(ctx.bot, chat_id, msg_id, PROCESSING)
    try:
        await _route_and_ingest(ctx, conn, owner, msg)
        await set_reaction(ctx.bot, chat_id, msg_id, SUCCESS)
    except _OversizedFile:
        await set_reaction(ctx.bot, chat_id, msg_id, OVERSIZED)
    except Exception:
        logger.exception("ingest failed")
        await set_reaction(ctx.bot, chat_id, msg_id, FAILURE)


class _OversizedFile(Exception):
    pass


async def _route_and_ingest(ctx, conn, owner, msg) -> None:
    kind = detect_kind_from_message(msg)
    jina = JinaClient(api_key=owner.jina_api_key)
    deepgram = DeepgramClient(api_key=owner.deepgram_api_key)

    if kind in ("text", "web", "youtube"):
        text = msg.text or msg.caption or ""
        await ingest_text(
            conn, jina=jina, owner_id=owner.telegram_id,
            tg_chat_id=msg.chat.id, tg_message_id=msg.message_id,
            text=text, caption=msg.caption, created_at=int(msg.date.timestamp()),
        )
        return

    if kind == "voice":
        voice = msg.voice
        if is_oversized(voice.file_size or 0):
            raise _OversizedFile
        f = await ctx.bot.get_file(voice.file_id)
        audio = await f.download_as_bytearray()
        await ingest_voice(
            conn, deepgram=deepgram, jina=jina, owner_id=owner.telegram_id,
            tg_chat_id=msg.chat.id, tg_message_id=msg.message_id,
            audio_bytes=bytes(audio), mime=voice.mime_type or "audio/ogg",
            caption=msg.caption, created_at=int(msg.date.timestamp()),
        )
        return

    if kind in ("pdf", "docx", "xlsx"):
        doc = msg.document
        size = doc.file_size or 0
        if is_oversized(size):
            await ingest_document(
                conn, jina=jina, owner_id=owner.telegram_id,
                tg_chat_id=msg.chat.id, tg_message_id=msg.message_id,
                local_path=None, original_name=doc.file_name,
                kind="oversized", file_size=size,
                caption=msg.caption, created_at=int(msg.date.timestamp()),
                is_oversized=True,
            )
            raise _OversizedFile

        f = await ctx.bot.get_file(doc.file_id)
        local_dir = Path("/app/data/attachments") / str(msg.message_id)
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / doc.file_name
        await f.download_to_drive(custom_path=str(local_path))

        await ingest_document(
            conn, jina=jina, owner_id=owner.telegram_id,
            tg_chat_id=msg.chat.id, tg_message_id=msg.message_id,
            local_path=local_path, original_name=doc.file_name,
            kind=kind, file_size=size,
            caption=msg.caption, created_at=int(msg.date.timestamp()),
            is_oversized=False,
        )
        return

    if kind == "image":
        photo = msg.photo[-1]  # largest
        size = photo.file_size or 0
        if is_oversized(size):
            raise _OversizedFile
        f = await ctx.bot.get_file(photo.file_id)
        local_dir = Path("/app/data/attachments") / str(msg.message_id)
        local_dir.mkdir(parents=True, exist_ok=True)
        local_path = local_dir / f"photo_{photo.file_unique_id}.jpg"
        await f.download_to_drive(custom_path=str(local_path))

        await ingest_document(
            conn, jina=jina, owner_id=owner.telegram_id,
            tg_chat_id=msg.chat.id, tg_message_id=msg.message_id,
            local_path=local_path, original_name=local_path.name,
            kind="image", file_size=size,
            caption=msg.caption, created_at=int(msg.date.timestamp()),
            is_oversized=False,
        )
        return


def register_channel_handlers(app: Application) -> None:
    app.add_handler(MessageHandler(filters.UpdateType.CHANNEL_POST, channel_handler))
