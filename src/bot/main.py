import asyncio
import datetime
import logging
import tempfile
from pathlib import Path

from telegram import BotCommand, Update
from telegram.error import TelegramError
from telegram.ext import Application, ApplicationBuilder

from src.adapters.github_mirror import GitHubMirror, GitHubMirrorError
from src.core import sync_deleted
from src.core.db import open_db, init_schema
from src.core.export import build_export
from src.core.owners import (
    create_or_get_owner, get_owner, record_backup_failure,
    record_backup_success, reset_backup_failure_count, seed_vps_from_env,
)
from src.core.settings import load_settings
from src.bot.handlers.commands import register_command_handlers
from src.bot.handlers.setup import register_setup_handlers
from src.bot.handlers.channel import register_channel_handlers
from src.bot.handlers.search import register_search_handlers
from src.bot.handlers.search_callbacks import register_search_callbacks
from src.bot.handlers.help_buttons import register_help_buttons

DAILY_BACKUP_TAG = "soroka-daily-latest"
BACKUP_FAILURE_DM_THRESHOLD = 3

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
    BotCommand("sync", "Проверить удалённые сообщения"),
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


async def _daily_github_backup_job(ctx) -> None:
    """Nightly lite-backup of the SQLite database to a single GitHub Release
    tagged DAILY_BACKUP_TAG (replaced on every run). No-op when the owner has
    no GitHub mirror configured or the wizard is still running.

    Lite means: DB + notes.json + README, no attachments. Keeps the repo
    small so the same tag can be rewritten daily without bloat. Full archives
    with attachments stay on the manual /export path.

    Persists last_backup_at / last_backup_error / backup_failure_count on
    the owner row, and DMs the owner once after BACKUP_FAILURE_DM_THRESHOLD
    consecutive failures so silent multi-day outages do not go unnoticed."""
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    log = logging.getLogger(__name__)
    owner_id = settings.owner_telegram_id
    error_text: str | None = None
    try:
        owner = get_owner(conn, owner_id)
        if not owner or owner.setup_step != "done":
            return
        if not (owner.github_token and owner.github_mirror_repo):
            return

        db_path = Path(settings.db_path)
        if not db_path.exists():
            log.warning("daily github backup skipped: db missing at %s", db_path)
            return

        ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S")
        with tempfile.TemporaryDirectory(prefix="soroka-daily-backup-") as tmp:
            asset = Path(tmp) / f"soroka-{ts}-lite.zip"
            await asyncio.to_thread(
                build_export,
                db_path=db_path, attachments_dir=None,
                output_path=asset, lite=True,
            )
            mirror = GitHubMirror(
                token=owner.github_token, repo=owner.github_mirror_repo,
            )
            url = await mirror.upload_release(
                tag=DAILY_BACKUP_TAG,
                title=f"Soroka daily backup {ts}",
                body="Automated lite backup (DB only). Replaced on every run.",
                asset=asset, replace=True,
            )
        record_backup_success(conn, owner_id, ts)
        log.info("daily github backup uploaded: %s", url)
        return
    except GitHubMirrorError as e:
        error_text = f"GitHub: {e}"
        log.warning("daily github backup failed: %s", e)
    except Exception as e:
        error_text = f"unexpected: {e}"
        log.exception("daily github backup crashed")

    if error_text is None:
        return
    failures = record_backup_failure(conn, owner_id, error_text)
    if failures >= BACKUP_FAILURE_DM_THRESHOLD:
        try:
            await ctx.bot.send_message(
                chat_id=owner_id,
                text=(
                    f"⚠ Авто-бэкап в GitHub упал {failures} раза подряд.\n"
                    f"Последняя ошибка: {error_text}\n"
                    "Проверь токен (`/setgithub`) и доступ к репо."
                ),
            )
            reset_backup_failure_count(conn, owner_id)
        except Exception:
            log.exception("daily github backup DM failed")


async def _daily_sync_job(ctx) -> None:
    """Nightly probe of recent notes for deleted Telegram sources.
    Wrapped in try/except so a sync failure cannot crash the bot loop."""
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    try:
        result = await sync_deleted.run_sync(
            ctx.bot, conn,
            owner_id=settings.owner_telegram_id,
            owner_telegram_id=settings.owner_telegram_id,
            days=14,
        )
        logging.getLogger(__name__).info(
            "daily sync done: checked=%d deleted=%d",
            result.checked, result.deleted,
        )
    except sync_deleted.BusyError:
        logging.getLogger(__name__).info("daily sync skipped: already running")
    except Exception:
        logging.getLogger(__name__).exception("daily sync failed")


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

    # 22:00 UTC == 01:00 Moscow time (Russia has no DST since 2014).
    app.job_queue.run_daily(
        _daily_sync_job,
        time=datetime.time(hour=22, minute=0, tzinfo=datetime.timezone.utc),
        name="daily_sync_deleted",
    )
    # Run an hour after the deletion sweep so the backup reflects post-sync
    # state (deleted notes already pruned from the DB before snapshot).
    app.job_queue.run_daily(
        _daily_github_backup_job,
        time=datetime.time(hour=23, minute=0, tzinfo=datetime.timezone.utc),
        name="daily_github_backup",
    )
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
