import logging

from telegram import Update
from telegram.ext import Application, ApplicationBuilder

from src.core.db import open_db, init_schema
from src.core.settings import load_settings
from src.bot.handlers.commands import register_command_handlers
from src.bot.handlers.setup import register_setup_handlers
from src.bot.handlers.channel import register_channel_handlers
from src.bot.handlers.search import register_search_handlers
from src.bot.handlers.search_callbacks import register_search_callbacks

ALLOWED_UPDATES = [
    Update.MESSAGE,
    Update.EDITED_MESSAGE,
    Update.CHANNEL_POST,
    Update.EDITED_CHANNEL_POST,
    Update.CALLBACK_QUERY,
]


def build_app(settings, conn) -> Application:
    app = ApplicationBuilder().token(settings.telegram_bot_token).build()
    app.bot_data["settings"] = settings
    app.bot_data["conn"] = conn

    register_setup_handlers(app)
    register_command_handlers(app)
    register_channel_handlers(app)
    register_search_handlers(app)
    register_search_callbacks(app)
    return app


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = load_settings()
    conn = open_db(settings.db_path)
    init_schema(conn)
    app = build_app(settings, conn)
    app.run_polling(allowed_updates=ALLOWED_UPDATES)


if __name__ == "__main__":
    main()
