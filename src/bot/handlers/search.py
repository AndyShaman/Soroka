import logging

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from src.adapters.deepgram import DeepgramClient
from src.adapters.jina import JinaClient
from src.adapters.openrouter import OpenRouterClient
from src.bot.auth import is_owner
from src.bot.handlers._search_format import format_hit
from src.core.intent import parse_intent
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

    # Refinement flow: if we asked the user to refine, treat this message as
    # new query that piggybacks on the previous filters.
    prev = ctx.user_data.get("last_search")
    if ctx.user_data.pop("awaiting_refinement", False) and prev:
        query_text = f"{prev['query']} {query_text}".strip()

    await ctx.bot.send_chat_action(chat_id=msg.chat.id, action="typing")

    openrouter = OpenRouterClient(api_key=owner.openrouter_key)
    jina = JinaClient(api_key=owner.jina_api_key)

    intent = await parse_intent(
        openrouter, primary=owner.primary_model,
        fallback=owner.fallback_model, query=query_text,
    )

    await ctx.bot.send_chat_action(chat_id=msg.chat.id, action="typing")
    candidates = await hybrid_search(
        conn, jina=jina, owner_id=owner.telegram_id,
        clean_query=intent.clean_query, kind=intent.kind, limit=20,
    )
    if not candidates:
        await msg.reply_text("Не нашёл ничего. Попробуй уточнить запрос.")
        return

    await ctx.bot.send_chat_action(chat_id=msg.chat.id, action="typing")
    reranked = await rerank(
        openrouter, primary=owner.primary_model, fallback=owner.fallback_model,
        query=intent.clean_query, candidates=candidates, top_k=20,
    )
    if not reranked:
        await msg.reply_text("Не нашёл ничего релевантного.")
        return

    first_page = reranked[:5]
    chunks = [format_hit(n) for n in first_page]
    text = "\n\n─────\n\n".join(chunks)

    new_state = {
        "query": intent.clean_query,
        "since_days": None,
        "excluded_ids": [],
        "pool": reranked,
        "shown_ids": [n.id for n in first_page],
        "cursor": len(first_page),
    }
    ctx.user_data["last_search"] = new_state

    from src.bot.handlers.search_callbacks import make_keyboard
    await msg.reply_text(
        text, reply_markup=make_keyboard(new_state), disable_web_page_preview=True,
    )


async def _query_text(msg, owner, ctx) -> str:
    if msg.voice:
        deepgram = DeepgramClient(api_key=owner.deepgram_api_key)
        f = await ctx.bot.get_file(msg.voice.file_id)
        audio = await f.download_as_bytearray()
        return await deepgram.transcribe(bytes(audio), mime=msg.voice.mime_type or "audio/ogg")
    return msg.text or ""


def register_search_handlers(app: Application) -> None:
    # group=1 so the setup wizard's text handler (group=0) gets the first
    # crack at active steps; this handler picks up DMs once setup is 'done'.
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & ~filters.FORWARDED & ~filters.COMMAND,
        search_handler,
    ), group=1)
