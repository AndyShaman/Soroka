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


@pytest.mark.asyncio
async def test_run_sync_soft_deletes_only_missing(tmp_path):
    conn = _setup_db(tmp_path)
    now = int(time.time())
    alive = insert_note(conn, _mk_note(42, 100, created_at=now - 3600))
    gone = insert_note(conn, _mk_note(42, 200, created_at=now - 3600))
    other = insert_note(conn, _mk_note(42, 300, created_at=now - 3600))

    bot = MagicMock()
    forwarded = MagicMock(message_id=999)

    async def fake_forward(*, chat_id, from_chat_id, message_id, disable_notification):
        if message_id == 200:
            raise BadRequest("Message to forward not found")
        return forwarded

    bot.forward_message = AsyncMock(side_effect=fake_forward)
    bot.delete_message = AsyncMock()

    result = await sync_deleted.run_sync(
        bot, conn, owner_id=42, owner_telegram_id=42,
        days=14, max_rps=1000,
    )
    assert result.checked == 3
    assert result.deleted == 1

    deleted_at_alive = conn.execute(
        "SELECT deleted_at FROM notes WHERE id=?", (alive,)
    ).fetchone()[0]
    deleted_at_gone = conn.execute(
        "SELECT deleted_at FROM notes WHERE id=?", (gone,)
    ).fetchone()[0]
    deleted_at_other = conn.execute(
        "SELECT deleted_at FROM notes WHERE id=?", (other,)
    ).fetchone()[0]
    assert deleted_at_alive is None
    assert deleted_at_other is None
    assert deleted_at_gone is not None


@pytest.mark.asyncio
async def test_run_sync_lock_prevents_concurrent(tmp_path):
    """Second run_sync while the first is in flight raises BusyError."""
    conn = _setup_db(tmp_path)
    now = int(time.time())
    insert_note(conn, _mk_note(42, 1, created_at=now - 3600))

    started = asyncio.Event()
    release = asyncio.Event()

    bot = MagicMock()

    async def slow_forward(**kw):
        started.set()
        await release.wait()
        raise BadRequest("Message to forward not found")

    bot.forward_message = AsyncMock(side_effect=slow_forward)
    bot.delete_message = AsyncMock()

    first = asyncio.create_task(sync_deleted.run_sync(
        bot, conn, owner_id=42, owner_telegram_id=42,
        days=14, max_rps=1000,
    ))
    await started.wait()
    with pytest.raises(sync_deleted.BusyError):
        await sync_deleted.run_sync(
            bot, conn, owner_id=42, owner_telegram_id=42,
            days=14, max_rps=1000,
        )
    release.set()
    await first


@pytest.mark.asyncio
async def test_daily_sync_callback_invokes_run_sync(tmp_path, monkeypatch):
    """The cron callback wired in build_app must call run_sync with
    days=14 and never raise even if run_sync fails."""
    from src.bot import main as bot_main

    called = {}

    async def fake_run_sync(bot, conn, *, owner_id, owner_telegram_id, days, **kw):
        called["days"] = days
        called["owner_id"] = owner_id
        return sync_deleted.SyncResult(checked=0, deleted=0)

    monkeypatch.setattr(sync_deleted, "run_sync", fake_run_sync)

    conn = _setup_db(tmp_path)

    settings = MagicMock(owner_telegram_id=42)
    ctx = MagicMock()
    ctx.application.bot_data = {"settings": settings, "conn": conn}
    ctx.bot = MagicMock()

    await bot_main._daily_sync_job(ctx)
    assert called["days"] == 14
    assert called["owner_id"] == 42
