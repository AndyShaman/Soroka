"""Probe-based detection of deleted Telegram channel posts.

The bot is not notified when a channel post is deleted (Bot API limitation,
confirmed by Telegram in tdlib/td#3314). We detect deletions by trying to
forward the message to the owner's DM and observing the error response."""
from __future__ import annotations

import logging
import sqlite3
import time
from typing import Iterable, Optional

from src.core.models import Note

logger = logging.getLogger(__name__)


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
