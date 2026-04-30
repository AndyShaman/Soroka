from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from src.bot.auth import is_owner
from src.core.owners import get_owner

HELP_TEXT = (
    "*Soroka — команды*\n\n"
    "Канал «Избранное 2» — кидай туда что угодно.\n"
    "DM (этот чат) — пиши/говори запрос для поиска.\n\n"
    "/start — мастер настройки\n"
    "/status — текущие настройки\n"
    "/setjina — заменить ключ Jina\n"
    "/setdeepgram — заменить ключ Deepgram\n"
    "/setkey — заменить ключ OpenRouter\n"
    "/models — выбрать модели primary/fallback\n"
    "/setgithub — заменить GitHub-токен и репо\n"
    "/setvps — задать IP/юзера VPS (для /mcp)\n"
    "/setinbox — сменить канал-инбокс\n"
    "/export — выгрузить базу архивом\n"
    "/mcp — конфиг для Claude Desktop\n"
    "/cancel — прервать текущий мастер"
)


async def help_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        return
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")


async def status_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        return

    owner = get_owner(conn, settings.owner_telegram_id)
    if not owner:
        await update.message.reply_text("Бот ещё не настроен. /start")
        return

    notes_count = conn.execute(
        "SELECT count(*) FROM notes WHERE owner_id = ?",
        (owner.telegram_id,),
    ).fetchone()[0]

    def _mask(v: str | None) -> str:
        if not v:
            return "❌"
        return f"…{v[-4:]} ✓"

    text = (
        f"*Soroka /status*\n\n"
        f"🔑 Jina:       {_mask(owner.jina_api_key)}\n"
        f"🔑 Deepgram:   {_mask(owner.deepgram_api_key)}\n"
        f"🔑 OpenRouter: {_mask(owner.openrouter_key)}\n"
        f"🟢 primary:    `{owner.primary_model or '—'}`\n"
        f"🟡 fallback:   `{owner.fallback_model or '—'}`\n"
        f"💾 GitHub:     `{owner.github_mirror_repo or '—'}`\n"
        f"📺 Inbox:      `{owner.inbox_chat_id or '—'}`\n"
        f"📊 Notes:       {notes_count}\n"
        f"⚙ Setup step:  `{owner.setup_step}`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cancel_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        return
    # Clear pending diag state if any (set by /set* commands)
    ctx.user_data.pop("pending_set", None)
    await update.message.reply_text("Отменено.")


def register_command_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
