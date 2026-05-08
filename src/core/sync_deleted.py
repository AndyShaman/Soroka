"""Probe-based detection of deleted Telegram channel posts.

The bot is not notified when a channel post is deleted (Bot API limitation,
confirmed by Telegram in tdlib/td#3314). We detect deletions by trying to
forward the message to the owner's DM and observing the error response."""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Iterable, Literal, Optional

from telegram.error import BadRequest, TelegramError

from src.core.models import Note
from src.core.notes import soft_delete_note

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    checked: int
    deleted: int


class BusyError(RuntimeError):
    """A sync run is already in flight."""


_lock = asyncio.Lock()

ProbeResult = Literal["exists", "deleted", "unknown"]

_DELETED_MARKERS = (
    "message to forward not found",
    "message_id_invalid",
)


async def probe_message_exists(bot, *, owner_telegram_id: int, note) -> ProbeResult:
    """Forward `note` back into its source channel as a probe, then
    immediately delete the forwarded copy.

    Probe target is the source channel itself, not the owner's DM:
    forward+delete in DM produced a visible "flicker" the owner could
    not avoid seeing (each probe = one DM message appearing for
    ~100 ms then vanishing). The source channel is already an active
    surface (bot is admin, ingests posts there) and the owner reads
    notes via the bot's DM, not the channel — so transient probe
    posts in the channel are invisible during normal use.

    `owner_telegram_id` is kept in the signature for backward compat
    with callers; it is no longer used by the probe itself.

    Returns:
      - "exists" if the forward succeeded (delete is best-effort).
      - "deleted" if Telegram says the source message is gone.
      - "unknown" on any other error (rate-limit, forbidden, network…).
    """
    try:
        forwarded = await bot.forward_message(
            chat_id=note.tg_chat_id,
            from_chat_id=note.tg_chat_id,
            message_id=note.tg_message_id,
            disable_notification=True,
        )
    except BadRequest as e:
        text = str(e).lower()
        if any(m in text for m in _DELETED_MARKERS):
            return "deleted"
        logger.warning("probe BadRequest other than deletion: %s", e)
        return "unknown"
    except TelegramError as e:
        logger.warning("probe TelegramError: %s", e)
        return "unknown"

    try:
        await bot.delete_message(
            chat_id=note.tg_chat_id,
            message_id=forwarded.message_id,
        )
    except TelegramError:
        logger.exception("probe cleanup delete failed")
    return "exists"


def iter_active_notes_in_window(
    conn: sqlite3.Connection, *, owner_id: int,
    days: Optional[int], now: Optional[int] = None,
) -> Iterable[Note]:
    """Yield active (non-soft-deleted) notes for the given owner whose
    created_at falls inside [now - days*86400, now]. days=None means no
    filter (full database sweep, used by manual /sync)."""
    now = now if now is not None else int(time.time())
    if days is None:
        cur = conn.execute(
            """SELECT id, owner_id, tg_message_id, tg_chat_id, kind, title, content,
                      source_url, raw_caption, created_at,
                      COALESCE(thin_content, 0), deleted_at
               FROM notes WHERE owner_id = ? AND deleted_at IS NULL
               ORDER BY created_at DESC""",
            (owner_id,),
        )
    else:
        cutoff = now - days * 86400
        cur = conn.execute(
            """SELECT id, owner_id, tg_message_id, tg_chat_id, kind, title, content,
                      source_url, raw_caption, created_at,
                      COALESCE(thin_content, 0), deleted_at
               FROM notes
               WHERE owner_id = ? AND deleted_at IS NULL AND created_at >= ?
               ORDER BY created_at DESC""",
            (owner_id, cutoff),
        )
    fields = ("id owner_id tg_message_id tg_chat_id kind title content "
              "source_url raw_caption created_at thin_content deleted_at").split()
    for row in cur.fetchall():
        data = dict(zip(fields, row))
        data["thin_content"] = bool(data["thin_content"])
        yield Note(**data)


async def run_sync(
    bot, conn: sqlite3.Connection, *,
    owner_id: int, owner_telegram_id: int,
    days: Optional[int], max_rps: int = 10,
) -> SyncResult:
    """Probe every active note in window; soft-delete those that come
    back as 'deleted'. The 'unknown' bucket is intentionally left alone
    so transient Telegram errors never nuke live notes."""
    if _lock.locked():
        raise BusyError("sync already running")

    async with _lock:
        return await _run_sync_locked(
            bot, conn,
            owner_id=owner_id, owner_telegram_id=owner_telegram_id,
            days=days, max_rps=max_rps,
        )


async def _run_sync_locked(
    bot, conn, *, owner_id, owner_telegram_id, days, max_rps,
) -> SyncResult:
    delay = 1.0 / max_rps if max_rps > 0 else 0.0
    checked = 0
    deleted = 0
    for note in iter_active_notes_in_window(conn, owner_id=owner_id, days=days):
        checked += 1
        result = await probe_message_exists(
            bot, owner_telegram_id=owner_telegram_id, note=note,
        )
        if result == "deleted":
            if soft_delete_note(conn, note.id, reason="channel_post_deleted"):
                deleted += 1
        if delay:
            await asyncio.sleep(delay)
    logger.info("sync run done: checked=%d deleted=%d", checked, deleted)
    return SyncResult(checked=checked, deleted=deleted)
