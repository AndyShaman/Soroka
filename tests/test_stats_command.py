import time

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.core.db import open_db, init_schema
from src.core.owners import create_or_get_owner


def _ctx_and_update(conn, owner_id=42):
    update = MagicMock()
    update.effective_user.id = owner_id
    update.message.reply_text = AsyncMock()
    ctx = MagicMock()
    ctx.application.bot_data = {
        "settings": MagicMock(owner_telegram_id=owner_id),
        "conn": conn,
    }
    return ctx, update


def _insert_note(conn, *, id, owner_id, kind="post", chat_id=-100, msg_id=None,
                 created_at=None, deleted_at=None, content="c"):
    msg_id = msg_id if msg_id is not None else id
    created_at = created_at if created_at is not None else int(time.time())
    conn.execute(
        """INSERT INTO notes (id, owner_id, tg_message_id, tg_chat_id, kind,
                              content, created_at, deleted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (id, owner_id, msg_id, chat_id, kind, content, created_at, deleted_at),
    )
    conn.commit()


@pytest.mark.asyncio
async def test_stats_command_empty_db(tmp_path):
    from src.bot.handlers.commands import stats_command
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)

    ctx, update = _ctx_and_update(conn)
    await stats_command(update, ctx)

    text = update.message.reply_text.call_args[0][0]
    assert "Всего: 0 заметок" in text
    # Empty DB should NOT have time-window block or by-kind block
    assert "За день" not in text
    assert "По типам" not in text


@pytest.mark.asyncio
async def test_stats_command_pluralization(tmp_path):
    from src.bot.handlers.commands import _pluralize_zametki
    assert _pluralize_zametki(0) == "0 заметок"
    assert _pluralize_zametki(1) == "1 заметка"
    assert _pluralize_zametki(2) == "2 заметки"
    assert _pluralize_zametki(4) == "4 заметки"
    assert _pluralize_zametki(5) == "5 заметок"
    assert _pluralize_zametki(11) == "11 заметок"
    assert _pluralize_zametki(12) == "12 заметок"
    assert _pluralize_zametki(14) == "14 заметок"
    assert _pluralize_zametki(21) == "21 заметка"
    assert _pluralize_zametki(22) == "22 заметки"
    assert _pluralize_zametki(25) == "25 заметок"
    assert _pluralize_zametki(101) == "101 заметка"
    assert _pluralize_zametki(111) == "111 заметок"


@pytest.mark.asyncio
async def test_stats_command_full_output(tmp_path):
    from src.bot.handlers.commands import stats_command
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)

    now = int(time.time())
    DAY = 86400
    for i in range(1, 4):
        _insert_note(conn, id=i, owner_id=42, kind="post", created_at=now - 100)
    _insert_note(conn, id=4, owner_id=42, kind="voice", created_at=now - 3 * DAY)
    _insert_note(conn, id=5, owner_id=42, kind="pdf",
                 created_at=now - 60 * DAY)

    ctx, update = _ctx_and_update(conn)
    await stats_command(update, ctx)

    text = update.message.reply_text.call_args[0][0]
    assert "Всего: 5 заметок" in text
    assert "За день:" in text
    assert "По типам:" in text
    # Sorted desc, one of each line
    assert "post" in text and "voice" in text and "pdf" in text
    # Oldest/newest dates
    assert "Самая старая:" in text
    assert "Самая новая:" in text


@pytest.mark.asyncio
async def test_stats_command_owner_only(tmp_path):
    """Non-owner gets no reply (silent ignore — same pattern as /status)."""
    from src.bot.handlers.commands import stats_command
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)

    ctx, update = _ctx_and_update(conn, owner_id=42)
    update.effective_user.id = 999  # different user

    await stats_command(update, ctx)
    update.message.reply_text.assert_not_awaited()
