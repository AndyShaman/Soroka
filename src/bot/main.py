import logging

from telegram import BotCommand, Update
from telegram.error import TelegramError
from telegram.ext import Application, ApplicationBuilder

from src.core.db import open_db, init_schema
from src.core.owners import create_or_get_owner, seed_vps_from_env
from src.core.settings import load_settings
from src.bot.handlers.commands import register_command_handlers
from src.bot.handlers.setup import register_setup_handlers
from src.bot.handlers.channel import register_channel_handlers
from src.bot.handlers.search import register_search_handlers
from src.bot.handlers.search_callbacks import register_search_callbacks
from src.bot.handlers.help_buttons import register_help_buttons

ALLOWED_UPDATES = [
    Update.MESSAGE,
    Update.EDITED_MESSAGE,
    Update.CHANNEL_POST,
    Update.EDITED_CHANNEL_POST,
    Update.CALLBACK_QUERY,
]


BOT_MENU_COMMANDS = [
    BotCommand("help", "Справка"),
    BotCommand("status", "Мои настройки"),
    BotCommand("stats", "Статистика по заметкам"),
    BotCommand("mcp", "Конфиг для MCP-сервера"),
    BotCommand("export", "Скачать архив базы"),
    BotCommand("models", "Сменить AI-модели"),
    BotCommand("reset", "Сбросить состояние диалога"),
]


async def _setup_bot_menu(app) -> None:
    """Publish the dropdown menu next to the input field. Called once at
    startup; idempotent — Telegram caches the list per-bot."""
    try:
        await app.bot.set_my_commands(BOT_MENU_COMMANDS)
        logging.getLogger(__name__).info(
            "bot menu published: %d commands", len(BOT_MENU_COMMANDS),
        )
    except TelegramError as e:
        logging.getLogger(__name__).warning("bot menu publish failed: %s", e)


def build_app(settings, conn) -> Application:
    app = ApplicationBuilder().token(settings.telegram_bot_token).build()
    app.bot_data["settings"] = settings
    app.bot_data["conn"] = conn
    app.post_init = _setup_bot_menu

    register_setup_handlers(app)
    register_command_handlers(app)
    register_channel_handlers(app)
    register_search_handlers(app)
    register_search_callbacks(app)
    register_help_buttons(app)
    return app


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = load_settings()
    conn = open_db(settings.db_path)
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=settings.owner_telegram_id)
    seed_vps_from_env(conn, settings.owner_telegram_id)
    app = build_app(settings, conn)
    app.run_polling(allowed_updates=ALLOWED_UPDATES)


if __name__ == "__main__":
    main()
