import sqlite3
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters,
)

from src.adapters.jina import JinaClient
from src.adapters.deepgram import DeepgramClient
from src.adapters.openrouter import OpenRouterClient
from src.core.owners import (
    create_or_get_owner, get_owner, update_owner_field, advance_setup_step,
)
from src.bot.auth import is_owner
from src.bot.handlers.setup_models import register_model_handlers

PROMPTS = {
    "jina":      "Шаг 1/6 — ключ Jina.\nЗайди на jina.ai → API → Free tier.\nПришли ключ сообщением.",
    "deepgram":  "Шаг 2/6 — ключ Deepgram.\nЗайди на deepgram.com, создай API key.\nПришли ключ сообщением.",
    "openrouter":"Шаг 3/6 — ключ OpenRouter.\nЗайди на openrouter.ai/keys.\nПришли ключ сообщением.",
    "models":    "Шаг 4/6 — выбор моделей. Сейчас покажу список — нажимай кнопки.",
    "github":    ("Шаг 5/6 — резервное копирование на GitHub.\n"
                  "1) Создай **приватный** репозиторий вида `username/soroka-data` на github.com/new\n"
                  "2) Сгенерируй Personal Access Token на github.com/settings/tokens/new с правами `repo`\n"
                  "3) Пришли одной строкой: `ghp_xxx username/soroka-data`\n"
                  "Чтобы пропустить (не рекомендую) — /skip"),
    "channel":   ("Шаг 6/6 — канал-инбокс.\n"
                  "Создай **приватный** канал «Избранное 2», добавь меня админом\n"
                  "(права `Post Messages` + `Add Reactions`),\n"
                  "затем форварднь сюда любое сообщение из этого канала."),
}

DONE_MESSAGE = (
    "Готово! Поехали.\n"
    "• /help — справка\n"
    "• /status — текущие настройки\n"
    "• /export — экспорт базы\n"
    "• /mcp — конфиг для Claude Desktop\n"
    "Кидай в канал что угодно — я индексирую. Ищи прямо здесь, в DM."
)


async def process_setup_message(conn: sqlite3.Connection, owner_id: int,
                                 text: str) -> str:
    """Pure logic of the setup wizard. Returns the next prompt to send."""
    owner = get_owner(conn, owner_id)
    step = owner.setup_step or "jina"

    if step == "jina":
        client = JinaClient(api_key=text.strip())
        if not await client.validate_key():
            return "Ключ Jina не подошёл. Попробуй ещё раз."
        update_owner_field(conn, owner_id, "jina_api_key", text.strip())
        advance_setup_step(conn, owner_id, "deepgram")
        return PROMPTS["deepgram"]

    if step == "deepgram":
        client = DeepgramClient(api_key=text.strip())
        if not await client.validate_key():
            return "Ключ Deepgram не подошёл. Попробуй ещё раз."
        update_owner_field(conn, owner_id, "deepgram_api_key", text.strip())
        advance_setup_step(conn, owner_id, "openrouter")
        return PROMPTS["openrouter"]

    if step == "openrouter":
        client = OpenRouterClient(api_key=text.strip())
        if not await client.validate_key():
            return "Ключ OpenRouter не подошёл. Попробуй ещё раз."
        update_owner_field(conn, owner_id, "openrouter_key", text.strip())
        advance_setup_step(conn, owner_id, "models")
        return "Ключ принят. Сейчас покажу список моделей — отправь /models."

    if step == "github":
        # Parsed in Task 17 (github step handler)
        from src.bot.handlers.setup_github import handle_github_step
        return await handle_github_step(conn, owner_id, text)

    if step == "channel":
        # Set via forward handler — see Task 18
        return "Жду форвард сообщения из канала «Избранное 2»."

    if step == "done" or step == "models":
        return ""  # ignore — handled by other handlers

    return "Не понимаю. Попробуй /start."


async def forward_inbox_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        return

    owner = get_owner(conn, settings.owner_telegram_id)
    if owner.setup_step != "channel":
        return  # other handlers (search) take over

    msg = update.message
    if not msg.forward_origin or msg.forward_origin.type != "channel":
        await msg.reply_text("Это не форвард из канала. Форвардни сообщение прямо из канала «Избранное 2».")
        return

    chat_id = msg.forward_origin.chat.id
    update_owner_field(conn, settings.owner_telegram_id, "inbox_chat_id", chat_id)
    advance_setup_step(conn, settings.owner_telegram_id, "done")

    # Test publish into the channel
    try:
        sent = await ctx.bot.send_message(
            chat_id=chat_id,
            text="✅ Soroka подключилась.",
        )
        # Schedule deletion after 10s — best-effort
        ctx.job_queue.run_once(
            lambda c: c.bot.delete_message(chat_id, sent.message_id),
            when=10,
        )
    except Exception:
        await msg.reply_text("⚠ Не могу публиковать в канал. Проверь права админа.")
        return

    await msg.reply_text(DONE_MESSAGE)


async def skip_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    owner = get_owner(conn, settings.owner_telegram_id)
    if owner and owner.setup_step == "github":
        from src.bot.handlers.setup_github import handle_skip_github
        msg = await handle_skip_github(conn, settings.owner_telegram_id)
        await update.message.reply_text(msg)
    else:
        await update.message.reply_text("Сейчас нечего пропускать.")


async def start_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]

    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        await update.message.reply_text("Бот настроен на одного владельца.")
        return

    create_or_get_owner(conn, telegram_id=settings.owner_telegram_id)
    owner = get_owner(conn, settings.owner_telegram_id)

    if owner.setup_step == "done":
        await update.message.reply_text(DONE_MESSAGE)
        return

    if owner.setup_step is None:
        advance_setup_step(conn, settings.owner_telegram_id, "jina")
        owner = get_owner(conn, settings.owner_telegram_id)

    await update.message.reply_text(
        "Привет! Я Soroka. Настроим за 5 минут.\n\n" + PROMPTS[owner.setup_step]
    )


def register_setup_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("skip", skip_handler))
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.FORWARDED,
        forward_inbox_handler,
    ))
    register_model_handlers(app)
