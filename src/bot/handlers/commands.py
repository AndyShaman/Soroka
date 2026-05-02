import datetime as dt
from pathlib import Path

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from src.adapters.github_mirror import GitHubMirror, GitHubMirrorError
from src.bot.auth import is_owner
from src.core.export import build_export
from src.core.owners import get_owner

HELP_TEXT = (
    "*Soroka — команды*\n\n"
    "Канал-инбокс — кидай туда что угодно.\n"
    "DM (этот чат) — пиши/говори запрос для поиска.\n\n"
    "*Иконки на постах в канале*\n"
    "👀 — обрабатываю (скачиваю, делаю OCR/транскрипцию, считаю embeddings)\n"
    "👍 — готово, пост проиндексирован и ищется\n"
    "🤔 — не смог обработать (формат, ошибка адаптера)\n"
    "🤯 — слишком большой файл, пропустил\n"
    "Если иконки нет — бот пост не получил (проверь, что он админ в канале).\n\n"
    "*Команды*\n"
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


PENDING_PROMPTS = {
    "jina":      ("jina_api_key", "Пришли новый ключ Jina."),
    "deepgram":  ("deepgram_api_key", "Пришли новый ключ Deepgram."),
    "key":       ("openrouter_key", "Пришли новый ключ OpenRouter."),
    "github":    ("github_pair", "Пришли одной строкой: `<token> <user>/<repo>`."),
    "vps":       ("vps_pair", "Пришли одной строкой: `<user>@<ip>` (например `user@203.0.113.10`)."),
    "inbox":     ("inbox", "Форвардни сюда сообщение из нового канала."),
}


def _make_set_command(kind: str):
    async def handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        settings = ctx.application.bot_data["settings"]
        if not is_owner(update.effective_user.id, settings.owner_telegram_id):
            return
        ctx.user_data["pending_set"] = kind
        _, prompt = PENDING_PROMPTS[kind]
        await update.message.reply_text(prompt, parse_mode="Markdown")
    return handler


async def pending_set_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        return
    pending = ctx.user_data.get("pending_set")
    if not pending:
        return  # let other handlers (search) act

    text = (update.message.text or "").strip()
    from src.adapters.jina import JinaClient
    from src.adapters.deepgram import DeepgramClient
    from src.adapters.openrouter import OpenRouterClient
    from src.adapters.github_mirror import GitHubMirror, GitHubMirrorError
    from src.core.owners import update_owner_field

    owner_id = settings.owner_telegram_id

    if pending == "jina":
        if not await JinaClient(api_key=text).validate_key():
            await update.message.reply_text("Не подошёл. Попробуй ещё раз или /cancel.")
            return
        update_owner_field(conn, owner_id, "jina_api_key", text)

    elif pending == "deepgram":
        if not await DeepgramClient(api_key=text).validate_key():
            await update.message.reply_text("Не подошёл. /cancel или попробуй ещё раз.")
            return
        update_owner_field(conn, owner_id, "deepgram_api_key", text)

    elif pending == "key":
        if not await OpenRouterClient(api_key=text).validate_key():
            await update.message.reply_text("Не подошёл. /cancel или попробуй ещё раз.")
            return
        update_owner_field(conn, owner_id, "openrouter_key", text)

    elif pending == "github":
        parts = text.split()
        if len(parts) != 2 or "/" not in parts[1]:
            await update.message.reply_text("Формат: `<token> <user>/<repo>`. /cancel или попробуй ещё раз.")
            return
        try:
            await GitHubMirror(token=parts[0], repo=parts[1]).validate()
        except GitHubMirrorError as e:
            await update.message.reply_text(f"GitHub: {e}. /cancel или попробуй ещё раз.")
            return
        update_owner_field(conn, owner_id, "github_token", parts[0])
        update_owner_field(conn, owner_id, "github_mirror_repo", parts[1])

    elif pending == "vps":
        if "@" not in text:
            await update.message.reply_text("Формат: `<user>@<ip>`. /cancel или попробуй ещё раз.")
            return
        user, host = text.split("@", 1)
        update_owner_field(conn, owner_id, "vps_user", user)
        update_owner_field(conn, owner_id, "vps_host", host)

    elif pending == "inbox":
        msg = update.message
        if not msg.forward_origin or msg.forward_origin.type != "channel":
            await update.message.reply_text("Это не форвард из канала. /cancel или попробуй ещё раз.")
            return
        update_owner_field(conn, owner_id, "inbox_chat_id", msg.forward_origin.chat.id)

    ctx.user_data.pop("pending_set", None)
    await update.message.reply_text("✓ Готово.")


async def mcp_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        return

    owner = get_owner(conn, settings.owner_telegram_id)
    if not owner or not owner.vps_host or not owner.vps_user:
        await update.message.reply_text(
            "Сначала задай VPS-доступ через /setvps "
            "(нужны для генерации SSH-команды в конфиге).")
        return

    config = (
        '{\n'
        '  "mcpServers": {\n'
        '    "soroka": {\n'
        '      "command": "ssh",\n'
        f'      "args": ["{owner.vps_user}@{owner.vps_host}", "soroka-mcp"]\n'
        '    }\n'
        '  }\n'
        '}'
    )
    text = (
        "Скопируй этот блок в файл `claude_desktop_config.json`:\n"
        "• Mac: `~/Library/Application Support/Claude/claude_desktop_config.json`\n"
        "• Windows: `%APPDATA%\\Claude\\claude_desktop_config.json`\n\n"
        f"```json\n{config}\n```\n\n"
        "Перезапусти Claude Desktop. В беседе появится инструмент `soroka`."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


TG_FILE_LIMIT = 50 * 1024 * 1024
WORK_DIR = Path("/app/data/exports")


async def export_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        return
    owner = get_owner(conn, settings.owner_telegram_id)
    if not owner:
        return

    await update.message.reply_text("Собираю архив…")
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    full_path = WORK_DIR / f"soroka-{ts}.zip"
    db_path = Path(settings.db_path)
    attachments_dir = db_path.parent / "attachments"

    build_export(db_path=db_path, attachments_dir=attachments_dir,
                  output_path=full_path, lite=False)

    if full_path.stat().st_size <= TG_FILE_LIMIT:
        with full_path.open("rb") as f:
            await update.message.reply_document(document=f, filename=full_path.name)
        return

    if not (owner.github_token and owner.github_mirror_repo):
        lite_path = WORK_DIR / f"soroka-{ts}-lite.zip"
        build_export(db_path=db_path, attachments_dir=None,
                      output_path=lite_path, lite=True)
        with lite_path.open("rb") as f:
            await update.message.reply_document(document=f, filename=lite_path.name)
        await update.message.reply_text(
            f"Полный архив {full_path.stat().st_size//1024//1024}MB не помещается. "
            "Включи зеркало через /setgithub чтобы я мог отдать ссылку.",
        )
        return

    mirror = GitHubMirror(token=owner.github_token, repo=owner.github_mirror_repo)
    try:
        url = await mirror.upload_release(
            tag=f"backup-{ts}", title=f"Soroka backup {ts}",
            body="Automated backup from /export.", asset=full_path,
        )
    except GitHubMirrorError as e:
        await update.message.reply_text(f"GitHub-зеркало отказало: {e}")
        return

    lite_path = WORK_DIR / f"soroka-{ts}-lite.zip"
    build_export(db_path=db_path, attachments_dir=None,
                  output_path=lite_path, lite=True)
    with lite_path.open("rb") as f:
        await update.message.reply_document(document=f, filename=lite_path.name)
    await update.message.reply_text(f"Полный архив тут: {url}")


def register_command_handlers(app: Application) -> None:
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("mcp", mcp_command))
    app.add_handler(CommandHandler("export", export_command))
    for kind in PENDING_PROMPTS:
        app.add_handler(CommandHandler(f"set{kind}", _make_set_command(kind)))
    # The pending-set handler must run BEFORE search handler.
    # python-telegram-bot dispatches by registration order within a group;
    # explicit higher-priority group ensures this.
    app.add_handler(MessageHandler(
        filters.ChatType.PRIVATE & ~filters.COMMAND,
        pending_set_handler,
    ), group=-1)
