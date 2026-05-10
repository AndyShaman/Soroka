"""Inline-button handlers for /help — gives the owner one-tap access
to rare config actions without remembering /set... command names."""
import logging

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
)
from telegram.ext import (
    Application, CallbackQueryHandler, ContextTypes,
)

from src.bot.auth import is_owner
from src.bot.handlers.commands import PENDING_PROMPTS
from src.bot.handlers.setup import start_handler
from src.core.owners import advance_setup_step

logger = logging.getLogger(__name__)


# Mapping from help-button payload to the pending_set kind used in commands.py.
_HELP_TO_KIND = {
    "help:set_jina": "jina",
    "help:set_deepgram": "deepgram",
    "help:set_openrouter": "key",
    "help:set_github": "github",
    "help:set_vps": "vps",
    "help:set_inbox": "inbox",
}


def build_help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Ключ Jina",       callback_data="help:set_jina"),
         InlineKeyboardButton("🔑 Ключ Deepgram",   callback_data="help:set_deepgram")],
        [InlineKeyboardButton("🔑 Ключ OpenRouter", callback_data="help:set_openrouter"),
         InlineKeyboardButton("💾 GitHub-токен",    callback_data="help:set_github")],
        [InlineKeyboardButton("🖥 VPS-доступ",      callback_data="help:set_vps"),
         InlineKeyboardButton("📺 Канал-инбокс",     callback_data="help:set_inbox")],
        [InlineKeyboardButton("⚠️ Первоначальная настройка",
                              callback_data="help:setup_init")],
    ])


def _confirm_setup_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Да, начать", callback_data="help:setup_yes"),
        InlineKeyboardButton("✖ Отмена",      callback_data="help:setup_no"),
    ]])


async def on_help_button(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        await update.callback_query.answer()
        return
    payload = update.callback_query.data
    await update.callback_query.answer()

    if payload == "help:setup_init":
        await update.callback_query.edit_message_text(
            "Подтверди: запустить мастер первоначальной настройки заново?\n"
            "Текущие ключи и настройки останутся в базе, но я проведу тебя "
            "через все шаги ещё раз.",
            reply_markup=_confirm_setup_keyboard(),
        )
        return

    kind = _HELP_TO_KIND.get(payload)
    if not kind:
        return
    # Mirror the /set* commands: clear any half-finished sub-flow state so
    # tapping a config button always starts the wizard from step 1.
    ctx.user_data.pop("github_repo_pending", None)
    ctx.user_data["pending_set"] = kind
    _, prompt = PENDING_PROMPTS[kind]
    await update.callback_query.edit_message_text(prompt, parse_mode="Markdown")


async def on_setup_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    settings = ctx.application.bot_data["settings"]
    conn = ctx.application.bot_data["conn"]
    if not is_owner(update.effective_user.id, settings.owner_telegram_id):
        await update.callback_query.answer()
        return
    payload = update.callback_query.data
    await update.callback_query.answer()

    if payload == "help:setup_no":
        await update.callback_query.edit_message_text(
            "Отменено.", reply_markup=None,
        )
        return

    if payload == "help:setup_yes":
        advance_setup_step(conn, settings.owner_telegram_id, None)
        await update.callback_query.edit_message_text(
            "Запускаю мастер настройки…", reply_markup=None,
        )
        await start_handler(update, ctx)
        return


def register_help_buttons(app: Application) -> None:
    app.add_handler(CallbackQueryHandler(
        on_help_button,
        pattern=r"^help:(set_jina|set_deepgram|set_openrouter|set_github|set_vps|set_inbox|setup_init)$",
    ))
    app.add_handler(CallbackQueryHandler(
        on_setup_confirm,
        pattern=r"^help:setup_(yes|no)$",
    ))
