import logging
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from src.adapters.deepgram import DeepgramClient
from src.adapters.jina import JinaClient
from src.adapters.openrouter import OpenRouterClient
from src.bot.auth import is_owner
from src.core.intent import parse_intent
from src.core.links import message_link
from src.core.owners import get_owner
from src.core.search import hybrid_search, rerank

logger = logging.getLogger(__name__)


async def search_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]

    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        return

    owner = get_owner(conn, settings.owner_telegram_id)
    if not owner or owner.setup_step != "done":
        return  # setup wizard takes priority

    msg = update.message
    if msg.text and msg.text.startswith("/"):
        return  # commands handled elsewhere

    query_text = await _query_text(msg, owner, ctx)
    if not query_text.strip():
        return

    openrouter = OpenRouterClient(api_key=owner.openrouter_key)
    jina = JinaClient(api_key=owner.jina_api_key)

    intent = await parse_intent(
        openrouter, primary=owner.primary_model,
        fallback=owner.fallback_model, query=query_text,
    )

    candidates = await hybrid_search(
        conn, jina=jina, owner_id=owner.telegram_id,
        clean_query=intent.clean_query, kind=intent.kind, limit=15,
    )
    if not candidates:
        await msg.reply_text("Не нашёл ничего. Попробуй уточнить запрос.")
        return

    reranked = await rerank(
        openrouter, primary=owner.primary_model, fallback=owner.fallback_model,
        query=intent.clean_query, candidates=candidates, top_k=5,
    )
    if not reranked:
        await msg.reply_text("Не нашёл ничего релевантного.")
        return

    chunks = [_format_hit(n) for n in reranked]
    await msg.reply_text("\n\n─────\n\n".join(chunks),
                         disable_web_page_preview=True)


async def _query_text(msg, owner, ctx) -> str:
    if msg.voice:
        deepgram = DeepgramClient(api_key=owner.deepgram_api_key)
        f = await ctx.bot.get_file(msg.voice.file_id)
        audio = await f.download_as_bytearray()
        return await deepgram.transcribe(bytes(audio), mime=msg.voice.mime_type or "audio/ogg")
    return msg.text or ""


def _format_hit(note) -> str:
    link = message_link(note.tg_chat_id, note.tg_message_id)
    title = (note.title or "")[:80]
    snippet = note.content[:200]
    return f"📌 [{note.kind}] {title}\n{link}\n{snippet}"


def register_search_handlers(app: Application) -> None:
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & ~filters.FORWARDED & ~filters.COMMAND,
        search_handler,
    ))
