from functools import wraps
from typing import Awaitable, Callable

from telegram import Update
from telegram.ext import ContextTypes


def is_owner(user_id: int, owner_id: int) -> bool:
    return user_id == owner_id


Handler = Callable[[Update, ContextTypes.DEFAULT_TYPE], Awaitable[None]]


def owner_only(handler: Handler) -> Handler:
    """Drop updates whose effective_user is not the configured owner.

    Telegram bots respond to anyone who knows the @username; without this
    guard, a stranger can trigger commands or callbacks that operate on
    the owner's record (and burn the owner's API keys).
    """
    @wraps(handler)
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        settings = ctx.application.bot_data["settings"]
        user = update.effective_user
        if user is None or not is_owner(user.id, settings.owner_telegram_id):
            return
        await handler(update, ctx)
    return wrapper
