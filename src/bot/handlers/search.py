import logging
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

from src.adapters.deepgram import DeepgramClient
from src.adapters.jina import JinaClient
from src.adapters.openrouter import OpenRouterClient
from src.bot.auth import is_owner
from src.bot.handlers._search_format import format_hit
from src.core.intent import parse_intent
from src.core.owners import get_owner
from src.core.search import hybrid_search, list_by_filters, rerank

logger = logging.getLogger(__name__)


async def search_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    tz = ZoneInfo(settings.owner_timezone)

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
    refining = ctx.user_data.pop("awaiting_refinement", False) and prev
    if refining:
        query_text = f"{prev['query']} {query_text}".strip()

    await ctx.bot.send_chat_action(chat_id=msg.chat.id, action="typing")

    intent = parse_intent(query_text, tz=tz)

    # Carry-over filters from prior search when refining (so «уточни» on a
    # «в мае» search keeps the May window even if the refinement text has
    # no temporal token of its own).
    if refining:
        if intent.kind is None and prev.get("kind"):
            intent = _with_field(intent, kind=prev["kind"])
        if (intent.since_days is None and intent.created_after is None
                and (prev.get("since_days") is not None
                     or prev.get("created_after") is not None)):
            intent = _with_field(
                intent,
                since_days=prev.get("since_days"),
                created_after=prev.get("created_after"),
                created_before=prev.get("created_before"),
            )

    has_filter = (
        intent.kind is not None or intent.since_days is not None
        or intent.created_after is not None
    )
    # Refinement may leave `clean_query` empty after merging carry-over
    # filters (e.g. user pressed Уточнить, then typed «по типу» — nothing
    # for hybrid to rank). Force list_mode so we exit through the SQL path
    # instead of issuing an empty FTS5 / dense lookup that would return 0.
    if has_filter and not intent.clean_query and not intent.list_mode:
        intent = _with_field(intent, list_mode=True)
    if not intent.clean_query and not has_filter:
        await msg.reply_text("Уточни запрос — ищу по тексту, голосу или фильтрам.")
        return

    if intent.list_mode:
        notes = list_by_filters(
            conn, owner_id=owner.telegram_id,
            kind=intent.kind, since_days=intent.since_days,
            created_after=intent.created_after,
            created_before=intent.created_before,
            limit=20,
        )
        if not notes:
            await msg.reply_text("Не нашёл ничего по этим фильтрам.")
            return
        pool = notes
    else:
        jina = JinaClient(api_key=owner.jina_api_key)
        candidates = await hybrid_search(
            conn, jina=jina, owner_id=owner.telegram_id,
            clean_query=intent.clean_query, kind=intent.kind, limit=20,
            since_days=intent.since_days,
            created_after=intent.created_after,
            created_before=intent.created_before,
        )
        if not candidates:
            await msg.reply_text("Не нашёл ничего. Попробуй уточнить запрос.")
            return

        await ctx.bot.send_chat_action(chat_id=msg.chat.id, action="typing")
        openrouter = OpenRouterClient(api_key=owner.openrouter_key)
        reranked = await rerank(
            openrouter, primary=owner.primary_model, fallback=owner.fallback_model,
            query=intent.clean_query, candidates=candidates, top_k=20,
        )
        if not reranked:
            await msg.reply_text("Не нашёл ничего релевантного.")
            return
        pool = reranked

    first_page = pool[:5]
    chunks = [format_hit(n, tz) for n in first_page]
    text = "\n\n─────\n\n".join(chunks)

    new_state = {
        "query": intent.clean_query,
        "kind": intent.kind,
        "since_days": intent.since_days,
        "created_after": intent.created_after,
        "created_before": intent.created_before,
        "list_mode": intent.list_mode,
        "excluded_ids": [],
        "pool": pool,
        "shown_ids": [n.id for n in first_page],
        "cursor": len(first_page),
    }
    ctx.user_data["last_search"] = new_state

    from src.bot.handlers.search_callbacks import make_keyboard
    await msg.reply_text(
        text, reply_markup=make_keyboard(new_state), disable_web_page_preview=True,
    )


def _with_field(intent, **changes):
    """Return a copy of `intent` (frozen dataclass) with selected fields
    overridden — used to merge prior filters into a refinement search."""
    from dataclasses import replace
    return replace(intent, **changes)


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
