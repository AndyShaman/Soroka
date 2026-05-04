import pytest
from unittest.mock import AsyncMock, MagicMock

from src.bot.handlers.commands import reset_command


@pytest.mark.asyncio
async def test_reset_command_clears_volatile_state():
    update = MagicMock()
    update.effective_user.id = 1
    update.message.reply_text = AsyncMock()

    ctx = MagicMock()
    ctx.user_data = {
        "pending_set": "jina",
        "last_search": {"query": "x"},
        "awaiting_refinement": True,
    }
    ctx.application.bot_data = {"settings": MagicMock(owner_telegram_id=1)}

    await reset_command(update, ctx)

    assert "pending_set" not in ctx.user_data
    assert "last_search" not in ctx.user_data
    assert "awaiting_refinement" not in ctx.user_data
    update.message.reply_text.assert_awaited_once()
    msg = update.message.reply_text.call_args[0][0]
    assert "сброше" in msg.lower()


@pytest.mark.asyncio
async def test_reset_command_idempotent_on_empty_state():
    update = MagicMock()
    update.effective_user.id = 1
    update.message.reply_text = AsyncMock()
    ctx = MagicMock()
    ctx.user_data = {}
    ctx.application.bot_data = {"settings": MagicMock(owner_telegram_id=1)}

    await reset_command(update, ctx)

    update.message.reply_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_reset_command_ignores_non_owner():
    update = MagicMock()
    update.effective_user.id = 999  # not owner
    update.message.reply_text = AsyncMock()
    ctx = MagicMock()
    ctx.user_data = {"pending_set": "jina"}
    ctx.application.bot_data = {"settings": MagicMock(owner_telegram_id=1)}

    await reset_command(update, ctx)

    assert "pending_set" in ctx.user_data  # untouched
    update.message.reply_text.assert_not_awaited()
