import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock

from telegram.error import BadRequest, TelegramError

from src.core.db import open_db, init_schema
from src.core.notes import insert_note, soft_delete_note
from src.core.owners import create_or_get_owner
from src.core.models import Note
from src.core import sync_deleted


def _mk_note(owner_id, msg_id, *, created_at, kind="text", chat_id=-1001234):
    return Note(
        owner_id=owner_id, tg_message_id=msg_id, tg_chat_id=chat_id,
        kind=kind, title=None, content="x" * 10,
        raw_caption=None, created_at=created_at, thin_content=False,
    )


def _setup_db(tmp_path, owner_id=42):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=owner_id)
    return conn


def test_iter_window_excludes_old(tmp_path):
    """Notes older than the cutoff are not returned for the daily run."""
    conn = _setup_db(tmp_path)
    now = int(time.time())
    fresh = insert_note(conn, _mk_note(42, 1, created_at=now - 86400))
    old = insert_note(conn, _mk_note(42, 2, created_at=now - 30 * 86400))

    ids = [n.id for n in sync_deleted.iter_active_notes_in_window(
        conn, owner_id=42, days=14, now=now,
    )]
    assert fresh in ids
    assert old not in ids


def test_iter_window_excludes_soft_deleted(tmp_path):
    conn = _setup_db(tmp_path)
    now = int(time.time())
    a = insert_note(conn, _mk_note(42, 1, created_at=now - 3600))
    b = insert_note(conn, _mk_note(42, 2, created_at=now - 3600))
    soft_delete_note(conn, a, reason="manual")

    ids = [n.id for n in sync_deleted.iter_active_notes_in_window(
        conn, owner_id=42, days=14, now=now,
    )]
    assert a not in ids
    assert b in ids


def test_iter_window_none_means_full_sweep(tmp_path):
    """days=None returns every active note regardless of age."""
    conn = _setup_db(tmp_path)
    now = int(time.time())
    a = insert_note(conn, _mk_note(42, 1, created_at=now - 365 * 86400))
    b = insert_note(conn, _mk_note(42, 2, created_at=now - 3600))

    ids = [n.id for n in sync_deleted.iter_active_notes_in_window(
        conn, owner_id=42, days=None, now=now,
    )]
    assert {a, b} <= set(ids)


@pytest.mark.asyncio
async def test_probe_returns_deleted_on_forward_not_found():
    bot = MagicMock()
    bot.forward_message = AsyncMock(side_effect=BadRequest(
        "Message to forward not found"
    ))
    bot.delete_message = AsyncMock()
    note = MagicMock(tg_chat_id=-1001234, tg_message_id=42)
    result = await sync_deleted.probe_message_exists(
        bot, owner_telegram_id=42, note=note,
    )
    assert result == "deleted"
    bot.delete_message.assert_not_called()


@pytest.mark.asyncio
async def test_probe_returns_exists_and_cleans_up_forward():
    bot = MagicMock()
    forwarded = MagicMock(message_id=999)
    bot.forward_message = AsyncMock(return_value=forwarded)
    bot.delete_message = AsyncMock()
    note = MagicMock(tg_chat_id=-1001234, tg_message_id=42)

    result = await sync_deleted.probe_message_exists(
        bot, owner_telegram_id=42, note=note,
    )
    assert result == "exists"
    bot.delete_message.assert_awaited_once_with(chat_id=42, message_id=999)


@pytest.mark.asyncio
async def test_probe_returns_unknown_on_other_error():
    bot = MagicMock()
    bot.forward_message = AsyncMock(side_effect=TelegramError("Forbidden"))
    bot.delete_message = AsyncMock()
    note = MagicMock(tg_chat_id=-1001234, tg_message_id=42)
    result = await sync_deleted.probe_message_exists(
        bot, owner_telegram_id=42, note=note,
    )
    assert result == "unknown"


@pytest.mark.asyncio
async def test_probe_classifies_message_id_invalid_as_deleted():
    bot = MagicMock()
    bot.forward_message = AsyncMock(side_effect=BadRequest("MESSAGE_ID_INVALID"))
    bot.delete_message = AsyncMock()
    note = MagicMock(tg_chat_id=-1001234, tg_message_id=42)
    assert await sync_deleted.probe_message_exists(
        bot, owner_telegram_id=42, note=note,
    ) == "deleted"
