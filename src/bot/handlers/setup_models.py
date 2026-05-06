from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from src.adapters.openrouter import OpenRouterClient
from src.bot.auth import owner_only
from src.core.owners import get_owner, update_owner_field, advance_setup_step

OPENROUTER_MODELS_URL = "https://openrouter.ai/models"

# Defaults pre-filled at the "models" wizard step so a brand-new owner can
# advance with one tap. Both are non-reasoning (or hybrid-controllable via
# `reasoning.enabled=false`, which OpenRouterClient passes for every call):
# reasoning models silently consume `max_tokens` on hidden reasoning and
# return empty `content`, breaking ru_summary, rerank and intent-parse.
DEFAULT_PRIMARY = "z-ai/glm-4.5-air:free"
DEFAULT_FALLBACK = "google/gemma-4-31b-it:free"

# Free-tier picks restricted to non-reasoning / hybrid-controllable models.
# Reasoning-by-default IDs (nvidia nemotron-reasoning, gpt-oss without
# effort, DeepSeek R1, …) intentionally absent — they will not return
# usable summaries even with `reasoning.enabled=false`, since OpenRouter
# does not guarantee that flag is honoured by every provider.
RECOMMENDED_FREE = [
    DEFAULT_PRIMARY,
    DEFAULT_FALLBACK,
    "google/gemma-4-26b-a4b-it:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "inclusionai/ling-2.6-1t:free",
]

RECOMMENDED_PAID = [
    "google/gemini-2.5-flash-lite",
    "google/gemini-3.1-flash-lite-preview",
    "google/gemini-3-flash-preview",
]


def _format_label(m) -> str:
    if m.is_free:
        return f"🆓 {m.id}"
    return f"💰 ${m.prompt_price * 1_000_000:.2f}/M  {m.id}"


def _keyboard(by_id: dict, page: str, role: str) -> InlineKeyboardMarkup:
    ids = RECOMMENDED_FREE if page == "free" else RECOMMENDED_PAID
    rows = []
    for mid in ids:
        m = by_id.get(mid)
        if m is None:
            continue
        rows.append([InlineKeyboardButton(_format_label(m), callback_data=f"pick:{role}:{mid}")])
    if page == "free":
        toggle = InlineKeyboardButton("💰 Платные →", callback_data=f"page:{role}:paid")
    else:
        toggle = InlineKeyboardButton("← 🆓 Free", callback_data=f"page:{role}:free")
    rows.append([toggle, InlineKeyboardButton("✏️ Своя модель", callback_data=f"custom:{role}")])
    return InlineKeyboardMarkup(rows)


async def _send_role_picker(reply_target, ctx: ContextTypes.DEFAULT_TYPE, role: str) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    owner = get_owner(conn, settings.owner_telegram_id)
    if not owner or not owner.openrouter_key:
        await reply_target.reply_text("Сначала настрой ключ OpenRouter (/start).")
        return
    client = OpenRouterClient(api_key=owner.openrouter_key)
    models = await client.list_models()
    by_id = {m.id: m for m in models}
    ctx.application.bot_data["model_list"] = models
    ctx.application.bot_data["model_by_id"] = by_id
    label = "основную" if role == "primary" else "fallback"
    await reply_target.reply_text(
        f"Выбери {label} модель:",
        reply_markup=_keyboard(by_id, "free", role),
    )


def _defaults_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✓ Использовать", callback_data="defaults:use"),
        InlineKeyboardButton("✏️ Изменить", callback_data="defaults:change"),
    ]])


def _defaults_prompt() -> str:
    return (
        "Рекомендую такие модели — обе бесплатные, проверены на этом боте:\n\n"
        f"🟢 primary:  `{DEFAULT_PRIMARY}`\n"
        f"🔵 fallback: `{DEFAULT_FALLBACK}`\n\n"
        "Можно использовать как есть или выбрать другие."
    )


@owner_only
async def models_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    owner = get_owner(conn, settings.owner_telegram_id)
    if not owner:
        return
    # During the initial wizard offer the recommended pair as a one-tap
    # accept; post-setup /models always opens the manual picker so re-edits
    # don't get blocked behind the dialog.
    if owner.setup_step == "models" and not owner.primary_model:
        await update.message.reply_text(
            _defaults_prompt(),
            reply_markup=_defaults_keyboard(),
            parse_mode="Markdown",
        )
        return
    role = "primary" if not owner.primary_model else "fallback"
    await _send_role_picker(update.message, ctx, role)


async def _save_and_advance(conn, ctx: ContextTypes.DEFAULT_TYPE, owner_id: int,
                             role: str, model_id: str, reply_target) -> None:
    field = "primary_model" if role == "primary" else "fallback_model"
    update_owner_field(conn, owner_id, field, model_id)
    if role == "primary":
        await _send_role_picker(reply_target, ctx, "fallback")
        return
    owner = get_owner(conn, owner_id)
    if owner.setup_step == "models":
        advance_setup_step(conn, owner_id, "github")
        from src.bot.handlers.setup import PROMPTS
        await reply_target.reply_text(PROMPTS["github"], parse_mode="Markdown")


@owner_only
async def defaults_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    owner = get_owner(conn, settings.owner_telegram_id)
    if not owner:
        return

    if query.data == "defaults:use":
        # Persist only after the user confirms — abandoned dialogs leave the
        # wizard in a re-runnable state instead of half-saving defaults.
        update_owner_field(conn, owner.telegram_id, "primary_model", DEFAULT_PRIMARY)
        update_owner_field(conn, owner.telegram_id, "fallback_model", DEFAULT_FALLBACK)
        await query.edit_message_text(
            f"✓ primary: {DEFAULT_PRIMARY}\n✓ fallback: {DEFAULT_FALLBACK}"
        )
        owner = get_owner(conn, owner.telegram_id)
        if owner.setup_step == "models":
            advance_setup_step(conn, owner.telegram_id, "github")
            from src.bot.handlers.setup import PROMPTS
            await query.message.reply_text(PROMPTS["github"], parse_mode="Markdown")
        return

    if query.data == "defaults:change":
        await query.edit_message_text("Выбери свои модели:")
        await _send_role_picker(query.message, ctx, "primary")
        return


@owner_only
async def model_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    by_id = ctx.application.bot_data.get("model_by_id", {})

    if data.startswith("page:"):
        _, role, page = data.split(":", 2)
        if not by_id:
            return
        await query.edit_message_reply_markup(reply_markup=_keyboard(by_id, page, role))
        return

    if data.startswith("custom:"):
        _, role = data.split(":", 1)
        ctx.application.bot_data["awaiting_custom_model"] = role
        await query.edit_message_text(
            f"Открой {OPENROUTER_MODELS_URL} — там список всех моделей с ценами.\n"
            "Скопируй ID целиком (например `anthropic/claude-haiku-4-5`) и пришли сообщением.",
            parse_mode="Markdown",
        )
        return

    if data.startswith("pick:"):
        _, role, model_id = data.split(":", 2)
        await query.edit_message_text(f"✓ {role}: {model_id}")
        await _save_and_advance(conn, ctx, settings.owner_telegram_id, role, model_id, query.message)


async def handle_custom_model_text(ctx: ContextTypes.DEFAULT_TYPE, text: str, message) -> bool:
    """Process plain text as a custom OpenRouter model ID. Returns True if consumed."""
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    owner = get_owner(conn, settings.owner_telegram_id)
    if not owner or owner.setup_step != "models":
        return False

    role = ctx.application.bot_data.get("awaiting_custom_model")
    if role is None:
        # Restart-recovery: text with a slash during models step is treated as
        # a custom model ID for whichever role is still empty.
        if "/" not in text:
            return False
        role = "primary" if not owner.primary_model else "fallback"

    model_id = text.strip()
    if "/" not in model_id or " " in model_id:
        await message.reply_text(
            "Не похоже на ID модели. Формат: `provider/model-name`.",
            parse_mode="Markdown",
        )
        return True

    by_id = ctx.application.bot_data.get("model_by_id")
    if not by_id:
        client = OpenRouterClient(api_key=owner.openrouter_key)
        models = await client.list_models()
        by_id = {m.id: m for m in models}
        ctx.application.bot_data["model_list"] = models
        ctx.application.bot_data["model_by_id"] = by_id

    if model_id not in by_id:
        await message.reply_text(
            f"OpenRouter не знает модель `{model_id}`. Проверь ID на {OPENROUTER_MODELS_URL}",
            parse_mode="Markdown",
        )
        return True

    ctx.application.bot_data.pop("awaiting_custom_model", None)
    await message.reply_text(f"✓ {role}: {model_id}")
    await _save_and_advance(conn, ctx, settings.owner_telegram_id, role, model_id, message)
    return True


def register_model_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("models", models_command))
    app.add_handler(CallbackQueryHandler(defaults_callback, pattern=r"^defaults:"))
    app.add_handler(CallbackQueryHandler(model_callback, pattern=r"^(pick|page|custom):"))
