"""Inline-button handlers attached to search results in DM.

State is per-chat in `ctx.user_data["last_search"]` and is volatile —
on bot restart, old buttons stop working (they no-op gracefully).

Schema of last_search:
    query           : str — the cleaned query that was searched for
    kind            : Optional[str] — kind filter from intent
    since_days      : Optional[int] — rolling-window filter
    created_after   : Optional[int] — explicit lower bound (epoch UTC)
    created_before  : Optional[int] — explicit upper bound (epoch UTC, exclusive)
    list_mode       : bool — filter-only path, skips dense/rerank
    excluded_ids    : list[int] — ids the user said are 'not it'
    pool            : list[Note] — reranked pool (up to 20) cached on first search
    cursor          : int — next index into pool to render from
    shown_ids       : list[int] — ids displayed in the latest render
"""
import logging
from typing import Optional
from zoneinfo import ZoneInfo

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, ContextTypes

from src.adapters.jina import JinaClient
from src.adapters.openrouter import OpenRouterClient
from src.bot.auth import is_owner
from src.bot.handlers._search_format import format_hit
from src.core.owners import get_owner
from src.core.search import hybrid_search, list_by_filters, rerank

logger = logging.getLogger(__name__)

PAGE_SIZE = 5
PERIODS: list[Optional[int]] = [None, 30, 90, 365]
PERIOD_LABELS = {None: "📅 Всё время", 30: "📅 За месяц",
                 90: "📅 За 3 мес", 365: "📅 За год"}


def make_keyboard(state: dict) -> InlineKeyboardMarkup:
    period_label = PERIOD_LABELS.get(state.get("since_days"), "📅 Период")
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Ещё 5", callback_data="search:next"),
        InlineKeyboardButton(period_label, callback_data="search:period"),
    ], [
        InlineKeyboardButton("❌ Не то", callback_data="search:exclude"),
        InlineKeyboardButton("💬 Уточнить", callback_data="search:refine"),
    ]])


async def _rebuild_pool_and_render(ctx, state: dict) -> tuple[str, list]:
    """Slow-path: rerun search with current state filters, refresh the
    pool, return the first PAGE_SIZE rendered. Returns (text, pool).

    Routes through `list_by_filters` when `list_mode` is set so that
    filter-only sessions stay on the deterministic SQL path even after
    pagination/period changes.
    """
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    tz = ZoneInfo(settings.owner_timezone)
    owner = get_owner(conn, settings.owner_telegram_id)
    if owner is None:
        return ("Не удалось получить настройки.", [])

    if state.get("list_mode"):
        notes = list_by_filters(
            conn, owner_id=owner.telegram_id,
            kind=state.get("kind"),
            since_days=state.get("since_days"),
            created_after=state.get("created_after"),
            created_before=state.get("created_before"),
            exclude_ids=state.get("excluded_ids") or [],
            limit=20,
        )
        if not notes:
            return ("Больше ничего не нашёл с этими фильтрами.", [])
        text = "\n\n─────\n\n".join(format_hit(n, tz) for n in notes[:PAGE_SIZE])
        return (text, notes)

    jina = JinaClient(api_key=owner.jina_api_key)
    openrouter = OpenRouterClient(api_key=owner.openrouter_key)

    candidates = await hybrid_search(
        conn, jina=jina, owner_id=owner.telegram_id,
        clean_query=state["query"], kind=state.get("kind"),
        limit=20,
        since_days=state.get("since_days"),
        created_after=state.get("created_after"),
        created_before=state.get("created_before"),
        exclude_ids=state.get("excluded_ids") or [],
    )
    if not candidates:
        return ("Больше ничего не нашёл с этими фильтрами.", [])

    reranked = await rerank(
        openrouter, primary=owner.primary_model, fallback=owner.fallback_model,
        query=state["query"], candidates=candidates, top_k=20,
    )
    if not reranked:
        return ("Не нашёл релевантного.", [])

    first_page = reranked[:PAGE_SIZE]
    text = "\n\n─────\n\n".join(format_hit(n, tz) for n in first_page)
    return (text, reranked)


async def _guard(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> Optional[dict]:
    settings = ctx.application.bot_data["settings"]
    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        await _safe_answer(update.callback_query)
        return None
    state = ctx.user_data.get("last_search")
    if not state:
        await _safe_answer(update.callback_query, "Поиск устарел — начни новый.")
        return None
    ok = await _safe_answer(update.callback_query)
    if not ok:
        return None
    return state


async def _safe_answer(callback_query, text: Optional[str] = None) -> bool:
    """answer() can fail with BadRequest if the query expired (>15s).
    Swallow that — the user already sees no spinner anyway.
    Returns True on success, False if the query was stale."""
    try:
        if text is None:
            await callback_query.answer()
        else:
            await callback_query.answer(text)
        return True
    except BadRequest as e:
        logger.info("stale callback_query.answer ignored: %s", e)
        return False


def _tz_from(ctx) -> ZoneInfo:
    return ZoneInfo(ctx.application.bot_data["settings"].owner_timezone)


async def on_next_page(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = await _guard(update, ctx)
    if not state:
        return
    pool = state.get("pool") or []
    cursor = state.get("cursor", 0)
    next_slice = pool[cursor:cursor + PAGE_SIZE]
    if not next_slice:
        await update.callback_query.edit_message_text(
            "Больше из этого пула нет. Смени период или уточни запрос.",
            reply_markup=make_keyboard(state),
            disable_web_page_preview=True,
        )
        return
    state["cursor"] = cursor + len(next_slice)
    state["shown_ids"] = [n.id for n in next_slice]
    tz = _tz_from(ctx)
    text = "\n\n─────\n\n".join(format_hit(n, tz) for n in next_slice)
    await update.callback_query.edit_message_text(
        text, reply_markup=make_keyboard(state), disable_web_page_preview=True,
    )


async def on_toggle_period(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = await _guard(update, ctx)
    if not state:
        return
    cur = state.get("since_days")
    idx = PERIODS.index(cur) if cur in PERIODS else 0
    state["since_days"] = PERIODS[(idx + 1) % len(PERIODS)]
    # Manual period override wipes any temporal range parsed from the
    # original query — otherwise «в мае» + period button would AND two
    # date filters and confuse the user.
    state["created_after"] = None
    state["created_before"] = None

    # Mid-state edit: show «Ищу…» so the user sees instant feedback.
    await update.callback_query.edit_message_text(
        "🔍 Ищу с новым периодом…", reply_markup=None,
    )
    await ctx.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing",
    )

    text, pool = await _rebuild_pool_and_render(ctx, state)
    state["pool"] = pool
    state["cursor"] = min(PAGE_SIZE, len(pool))
    state["shown_ids"] = [n.id for n in pool[:PAGE_SIZE]]
    await update.callback_query.edit_message_text(
        text, reply_markup=make_keyboard(state), disable_web_page_preview=True,
    )


async def on_exclude_current(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = await _guard(update, ctx)
    if not state:
        return
    excl = list(state.get("excluded_ids") or [])
    excl.extend(state.get("shown_ids") or [])
    state["excluded_ids"] = excl
    # Drop the excluded notes from the pool so the next slice skips them.
    pool = [n for n in (state.get("pool") or []) if n.id not in set(excl)]
    state["pool"] = pool
    state["cursor"] = 0
    next_slice = pool[:PAGE_SIZE]
    if not next_slice:
        await update.callback_query.edit_message_text(
            "После исключений ничего не осталось. Уточни запрос.",
            reply_markup=make_keyboard(state),
            disable_web_page_preview=True,
        )
        return
    state["cursor"] = len(next_slice)
    state["shown_ids"] = [n.id for n in next_slice]
    tz = _tz_from(ctx)
    text = "\n\n─────\n\n".join(format_hit(n, tz) for n in next_slice)
    await update.callback_query.edit_message_text(
        text, reply_markup=make_keyboard(state), disable_web_page_preview=True,
    )


async def on_start_refine(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    state = await _guard(update, ctx)
    if state is None:
        return
    ctx.user_data["awaiting_refinement"] = True
    await update.callback_query.edit_message_text(
        "Опиши точнее — какой именно результат ищешь? Я переформулирую.",
        reply_markup=None,
    )


def register_search_callbacks(app: Application) -> None:
    app.add_handler(CallbackQueryHandler(on_next_page, pattern=r"^search:next$"))
    app.add_handler(CallbackQueryHandler(on_toggle_period, pattern=r"^search:period$"))
    app.add_handler(CallbackQueryHandler(on_exclude_current, pattern=r"^search:exclude$"))
    app.add_handler(CallbackQueryHandler(on_start_refine, pattern=r"^search:refine$"))
