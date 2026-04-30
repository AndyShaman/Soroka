from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from src.adapters.openrouter import OpenRouterClient
from src.core.owners import get_owner, update_owner_field, advance_setup_step

PAGE_SIZE = 5


def _format_button(m) -> str:
    if m.is_free:
        prefix = "🆓"
        price = "free"
    else:
        prefix = " "
        price = f"${m.prompt_price * 1_000_000:.2f}/M"
    return f"{prefix} {price}  {m.id[:40]}"


def _keyboard(models: list, page: int, role: str) -> InlineKeyboardMarkup:
    start = page * PAGE_SIZE
    chunk = models[start:start + PAGE_SIZE]
    rows = [
        [InlineKeyboardButton(_format_button(m), callback_data=f"pick:{role}:{m.id}")]
        for m in chunk
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"page:{role}:{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{(len(models)-1)//PAGE_SIZE + 1}",
                                    callback_data="noop"))
    if start + PAGE_SIZE < len(models):
        nav.append(InlineKeyboardButton("▶️", callback_data=f"page:{role}:{page+1}"))
    rows.append(nav)
    return InlineKeyboardMarkup(rows)


async def models_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    owner = get_owner(conn, settings.owner_telegram_id)
    if not owner or not owner.openrouter_key:
        await update.message.reply_text("Сначала настрой ключ OpenRouter (/start).")
        return

    client = OpenRouterClient(api_key=owner.openrouter_key)
    models = await client.list_models()
    ctx.application.bot_data["model_list"] = models

    role = "primary" if not owner.primary_model else "fallback"
    label = "основную" if role == "primary" else "fallback"
    await update.message.reply_text(
        f"Выбери {label} модель:",
        reply_markup=_keyboard(models, 0, role),
    )


async def model_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "noop":
        return

    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    models = ctx.application.bot_data.get("model_list", [])

    if data.startswith("page:"):
        _, role, page_str = data.split(":")
        await query.edit_message_reply_markup(
            reply_markup=_keyboard(models, int(page_str), role),
        )
        return

    if data.startswith("pick:"):
        _, role, model_id = data.split(":", 2)
        field = "primary_model" if role == "primary" else "fallback_model"
        update_owner_field(conn, settings.owner_telegram_id, field, model_id)
        await query.edit_message_text(f"✓ {role}: {model_id}")

        owner = get_owner(conn, settings.owner_telegram_id)
        if role == "primary":
            await query.message.reply_text(
                "Теперь выбери fallback (на случай если основная упадёт):",
                reply_markup=_keyboard(models, 0, "fallback"),
            )
        else:
            # both selected
            if owner.setup_step == "models":
                advance_setup_step(conn, settings.owner_telegram_id, "github")
                from src.bot.handlers.setup import PROMPTS
                await query.message.reply_text(PROMPTS["github"])


def register_model_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("models", models_command))
    app.add_handler(CallbackQueryHandler(model_callback, pattern=r"^(pick|page|noop):"))
