import pytest


@pytest.mark.asyncio
async def test_status_does_not_show_notes_count(tmp_path, monkeypatch):
    """/status should not include 'Notes:' — that's /stats territory now."""
    from src.bot.handlers.commands import status_command
    from src.core.db import open_db, init_schema
    from src.core.owners import create_or_get_owner
    from unittest.mock import AsyncMock, MagicMock

    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)

    update = MagicMock()
    update.effective_user.id = 42
    update.message.reply_text = AsyncMock()
    ctx = MagicMock()
    ctx.application.bot_data = {
        "settings": MagicMock(owner_telegram_id=42),
        "conn": conn,
    }

    await status_command(update, ctx)

    text = update.message.reply_text.call_args[0][0]
    assert "Notes" not in text
    assert "📊 Notes" not in text
