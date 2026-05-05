"""Buffering of Telegram media-group messages so one forwarded post with N
photos lands as exactly one note. See
docs/superpowers/specs/2026-05-05-media-groups-ingest-design.md."""
import asyncio
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

FLUSH_DELAY_SEC = 1.5

_pending: dict[tuple[int, str], list] = defaultdict(list)
_timers: dict[tuple[int, str], asyncio.Task] = {}


def _reset_for_tests() -> None:
    """Drop all buffered state. Tests call this in setup so module-level
    globals don't leak between cases."""
    for t in _timers.values():
        t.cancel()
    _timers.clear()
    _pending.clear()


async def buffer_message(msg, ctx, *, flush_callback,
                          delay: float = FLUSH_DELAY_SEC) -> None:
    """Add a media-group message to the buffer and (re)start the flush
    timer. Returns immediately; flush_callback runs after `delay` seconds
    of no new messages arriving for the same group."""
    key = (msg.chat.id, msg.media_group_id)
    _pending[key].append(msg)

    existing = _timers.get(key)
    if existing is not None:
        existing.cancel()

    _timers[key] = asyncio.create_task(
        _flush_after(key, ctx, flush_callback, delay)
    )


async def _flush_after(key, ctx, flush_callback, delay: float) -> None:
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        return

    msgs = _pending.pop(key, [])
    _timers.pop(key, None)
    if not msgs:
        return
    try:
        await flush_callback(msgs, ctx)
    except Exception:
        logger.exception("media_group flush failed for key=%s", key)
