"""Probe-based detection of deleted Telegram channel posts.

The bot is not notified when a channel post is deleted (Bot API limitation,
confirmed by Telegram in tdlib/td#3314). We detect deletions by trying to
forward the message to the owner's DM and observing the error response."""
from __future__ import annotations

import logging
import sqlite3
import time
from typing import Iterable, Literal, Optional

from telegram.error import BadRequest, TelegramError

from src.core.models import Note

logger = logging.getLogger(__name__)

ProbeResult = Literal["exists", "deleted", "unknown"]

_DELETED_MARKERS = (
    "message to forward not found",
    "message_id_invalid",
)


async def probe_message_exists(bot, *, owner_telegram_id: int, note) -> ProbeResult:
    """Forward `note` to the owner's DM as a probe, then immediately
    delete the forwarded copy so the owner doesn't see clutter.

    Returns:
      - "exists" if the forward succeeded (delete is best-effort).
      - "deleted" if Telegram says the source message is gone.
      - "unknown" on any other error (rate-limit, forbidden, network…).
    """
    try:
        forwarded = await bot.forward_message(
            chat_id=owner_telegram_id,
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
            chat_id=owner_telegram_id,
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
