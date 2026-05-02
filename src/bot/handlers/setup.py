import logging
import sqlite3
from typing import Optional

from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters,
)

logger = logging.getLogger(__name__)

from src.adapters.jina import JinaClient
from src.adapters.deepgram import DeepgramClient
from src.adapters.openrouter import OpenRouterClient
from src.core.owners import (
    create_or_get_owner, get_owner, update_owner_field, advance_setup_step,
)
from src.bot.auth import is_owner, owner_only
from src.bot.handlers.setup_models import register_model_handlers

PROMPTS = {
    "jina":      "Шаг 1/6 — ключ Jina.\nЗайди на jina.ai → API → Free tier.\nПришли ключ сообщением.",
    "deepgram":  "Шаг 2/6 — ключ Deepgram.\nЗайди на deepgram.com, создай API key.\nПришли ключ сообщением.",
    "openrouter":"Шаг 3/6 — ключ OpenRouter.\nЗайди на openrouter.ai/keys.\nПришли ключ сообщением.",
    "models":    "Шаг 4/6 — выбор моделей. Сейчас покажу рекомендуемые — нажимай кнопки.",
    "github":    ("Шаг 5/6 — резервное копирование на GitHub (можно /skip).\n\n"
                  "Сначала создай **приватный** репозиторий на github.com/new "
                  "(имя любое, например `soroka-data`).\n\n"
                  "Когда создашь — пришли его сюда в формате `username/repo`."),
    "channel":   ("Шаг 6/6 — твой канал-инбокс.\n\n"
                  "Это твоё личное место в Telegram, куда ты будешь скидывать всё, "
                  "что хочешь сохранить (статьи, голосовые, ссылки, файлы). "
                  "Я индексирую каждое сообщение и потом ищу по ним.\n\n"
                  "Что нужно сделать:\n"
                  "1) Создай **приватный канал** в Telegram (название любое, "
                  "например «Избранное»).\n"
                  "2) Добавь меня в канал администратором с правами:\n"
                  "   • Post Messages (публиковать сообщения)\n"
                  "   • Add Reactions (ставить реакции)\n"
                  "3) Опубликуй в канале любое сообщение и **перешли его сюда** "
                  "(долгое нажатие на сообщение → «Переслать» → выбери этот чат)."),
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


async def setup_text_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Routes private text messages into the wizard while it is in progress.
    Search handler ignores anything before setup_step == 'done', so without
    this dispatcher API keys submitted during /start were silently dropped."""
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        return

    owner = get_owner(conn, settings.owner_telegram_id)
    if not owner or owner.setup_step in (None, "done", "channel"):
        return  # search / forward handlers take over

    text = update.message.text or ""

    if owner.setup_step == "models":
        from src.bot.handlers.setup_models import handle_custom_model_text
        await handle_custom_model_text(ctx, text, update.message)
        return

    try:
        reply = await process_setup_message(conn, settings.owner_telegram_id, text)
    except Exception:
        logger.exception("setup wizard step %s crashed", owner.setup_step)
        await update.message.reply_text(
            "Что-то сломалось на этом шаге. Попробуй ещё раз или /cancel."
        )
        return

    if reply:
        await update.message.reply_text(reply, parse_mode="Markdown")


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
        await msg.reply_text(
            "Это не пересланное сообщение из канала.\n\n"
            "Открой свой приватный канал, нажми на любое сообщение → "
            "«Переслать» → выбери этот чат с ботом."
        )
        return

    chat_id = msg.forward_origin.chat.id
    chat_title = msg.forward_origin.chat.title or str(chat_id)

    # Probe write access before persisting anything. If the bot is not an
    # admin, send_message returns 403 and we stay at step='channel' so the
    # user can fix the rights and forward again — instead of silently
    # locking them into a broken inbox_chat_id.
    try:
        sent = await ctx.bot.send_message(chat_id=chat_id, text="✅ Soroka подключилась.")
    except Exception:
        await msg.reply_text(
            f"Не могу публиковать в канал «{chat_title}» — скорее всего, "
            "я там не админ.\n\n"
            "Что сделать:\n"
            "1) Открой канал → ⋮ → Управление каналом → Администраторы\n"
            "2) Добавь меня администратором\n"
            "3) Дай права: Post Messages, Add Reactions\n"
            "4) Перешли сюда любое сообщение из канала ещё раз"
        )
        return

    update_owner_field(conn, settings.owner_telegram_id, "inbox_chat_id", chat_id)
    advance_setup_step(conn, settings.owner_telegram_id, "done")

    ctx.job_queue.run_once(
        lambda c: c.bot.delete_message(chat_id, sent.message_id),
        when=10,
    )
    await msg.reply_text(DONE_MESSAGE)


@owner_only
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
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & filters.TEXT & ~filters.FORWARDED & ~filters.COMMAND,
        setup_text_handler,
    ))
    register_model_handlers(app)
