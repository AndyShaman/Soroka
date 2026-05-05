import pytest
from unittest.mock import AsyncMock, MagicMock

from src.bot.main import _setup_bot_menu


@pytest.mark.asyncio
async def test_setup_bot_menu_publishes_expected_commands():
    """post_init wires up the dropdown 'Меню' next to the input field."""
    app = MagicMock()
    app.bot.set_my_commands = AsyncMock()

    await _setup_bot_menu(app)

    app.bot.set_my_commands.assert_awaited_once()
    cmds = app.bot.set_my_commands.call_args[0][0]
    names = [c.command for c in cmds]
    assert names == [
        "help", "status", "stats", "mcp", "export", "models", "sync", "reset",
    ]
    # All entries must have a description (non-empty)
    assert all(c.description for c in cmds)


@pytest.mark.asyncio
async def test_setup_bot_menu_swallows_telegram_failure():
    """If Telegram rejects (e.g. transient API error), bot startup must continue."""
    from telegram.error import TelegramError
    app = MagicMock()
    app.bot.set_my_commands = AsyncMock(side_effect=TelegramError("boom"))

    # Should not raise.
    await _setup_bot_menu(app)


def test_bot_menu_includes_stats():
    from src.bot.main import BOT_MENU_COMMANDS
    names = [c.command for c in BOT_MENU_COMMANDS]
    assert "stats" in names
