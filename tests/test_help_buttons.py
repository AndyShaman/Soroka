import pytest
from unittest.mock import AsyncMock, MagicMock

from src.bot.handlers.help_buttons import (
    on_help_button, on_setup_confirm, build_help_keyboard,
)


def _ctx_with_owner():
    ctx = MagicMock()
    ctx.user_data = {}
    ctx.application.bot_data = {
        "settings": MagicMock(owner_telegram_id=1),
        "conn": MagicMock(),
    }
    return ctx


def _callback(data: str):
    update = MagicMock()
    update.effective_user.id = 1
    update.callback_query.data = data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    update.callback_query.message.reply_text = AsyncMock()
    return update


def test_help_keyboard_has_seven_buttons():
    kb = build_help_keyboard()
    flat = [b for row in kb.inline_keyboard for b in row]
    assert len(flat) == 7
    payloads = [b.callback_data for b in flat]
    assert "help:set_jina" in payloads
    assert "help:set_deepgram" in payloads
    assert "help:set_openrouter" in payloads
    assert "help:set_github" in payloads
    assert "help:set_vps" in payloads
    assert "help:set_inbox" in payloads
    assert "help:setup_init" in payloads


@pytest.mark.asyncio
async def test_help_button_set_jina_starts_pending_set():
    """Tapping a config button enters the same pending_set state as /setjina."""
    update = _callback("help:set_jina")
    ctx = _ctx_with_owner()

    await on_help_button(update, ctx)

    assert ctx.user_data.get("pending_set") == "jina"
    update.callback_query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_help_button_setup_init_asks_for_confirmation():
    """Setup-init is destructive — must show 'Да / Отмена' before resetting."""
    update = _callback("help:setup_init")
    ctx = _ctx_with_owner()

    await on_help_button(update, ctx)

    update.callback_query.edit_message_text.assert_awaited_once()
    kwargs = update.callback_query.edit_message_text.call_args.kwargs
    assert kwargs.get("reply_markup") is not None
    text = update.callback_query.edit_message_text.call_args[0][0]
    assert "уверен" in text.lower() or "подтверди" in text.lower()


@pytest.mark.asyncio
async def test_setup_confirm_yes_resets_step_to_none(monkeypatch):
    """Confirming the destructive setup-init clears setup_step in DB."""
    update = _callback("help:setup_yes")
    ctx = _ctx_with_owner()

    advance = MagicMock()
    monkeypatch.setattr("src.bot.handlers.help_buttons.advance_setup_step", advance)
    monkeypatch.setattr(
        "src.bot.handlers.help_buttons.start_handler",
        AsyncMock(),
    )

    await on_setup_confirm(update, ctx)

    advance.assert_called_once()
    args = advance.call_args[0]
    # advance_setup_step(conn, owner_id, value) — value must be None
    assert args[2] is None


@pytest.mark.asyncio
async def test_setup_confirm_cancel_just_edits_message():
    """Cancel button on confirmation removes the keyboard, doesn't touch DB."""
    update = _callback("help:setup_no")
    ctx = _ctx_with_owner()

    await on_setup_confirm(update, ctx)

    update.callback_query.edit_message_text.assert_awaited_once()
    kwargs = update.callback_query.edit_message_text.call_args.kwargs
    assert kwargs.get("reply_markup") is None
