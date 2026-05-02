from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from src.adapters.openrouter import OpenRouterClient
from src.bot.auth import owner_only
from src.core.owners import get_owner, update_owner_field, advance_setup_step

OPENROUTER_MODELS_URL = "https://openrouter.ai/models"

RECOMMENDED_FREE = [
    "nvidia/nemotron-3-super-120b-a12b:free",
    "z-ai/glm-4.5-air:free",
    "qwen/qwen3-next-80b-a3b-instruct:free",
    "qwen/qwen3-coder:free",
    "minimax/minimax-m2.5:free",
]

RECOMMENDED_PAID = [
    "openai/gpt-5-nano",
    "google/gemini-2.5-flash-lite",
    "openai/gpt-5-mini",
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


@owner_only
async def models_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    owner = get_owner(conn, settings.owner_telegram_id)
    if not owner:
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
    app.add_handler(CallbackQueryHandler(model_callback, pattern=r"^(pick|page|custom):"))
