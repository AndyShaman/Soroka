import asyncio
import pytest
from unittest.mock import MagicMock

from src.bot.handlers import media_group


def _make_msg(chat_id: int, msg_id: int, mgid: str, caption=None):
    m = MagicMock()
    m.chat.id = chat_id
    m.message_id = msg_id
    m.media_group_id = mgid
    m.caption = caption
    return m


@pytest.mark.asyncio
async def test_buffer_accumulates_messages_with_same_mgid():
    """Two messages with the same media_group_id land in the same bucket."""
    media_group._reset_for_tests()
    flush_calls = []

    async def flush(msgs, ctx):
        flush_calls.append(list(msgs))

    ctx = MagicMock()
    msg1 = _make_msg(chat_id=10, msg_id=1, mgid="abc", caption="hello")
    msg2 = _make_msg(chat_id=10, msg_id=2, mgid="abc")

    await media_group.buffer_message(msg1, ctx, flush_callback=flush, delay=0.05)
    await media_group.buffer_message(msg2, ctx, flush_callback=flush, delay=0.05)

    await asyncio.sleep(0.1)

    assert len(flush_calls) == 1
    assert {m.message_id for m in flush_calls[0]} == {1, 2}


@pytest.mark.asyncio
async def test_timer_resets_when_new_message_arrives():
    """Each new message of the same group resets the flush countdown,
    so a slow album doesn't get split. The flush should fire only after
    quiescence — one logical event, not one per message."""
    media_group._reset_for_tests()
    flush_calls = []

    async def flush(msgs, ctx):
        flush_calls.append(len(msgs))

    ctx = MagicMock()
    delay = 0.1

    for i in range(1, 4):
        await media_group.buffer_message(
            _make_msg(chat_id=10, msg_id=i, mgid="x"), ctx,
            flush_callback=flush, delay=delay,
        )
        await asyncio.sleep(delay / 2)

    assert flush_calls == []
    await asyncio.sleep(delay * 1.5)
    assert flush_calls == [3]


@pytest.mark.asyncio
async def test_two_groups_are_independent():
    """Different media_group_ids → independent buckets, independent flushes."""
    media_group._reset_for_tests()
    flush_calls = []

    async def flush(msgs, ctx):
        flush_calls.append(msgs[0].media_group_id)

    ctx = MagicMock()

    await media_group.buffer_message(
        _make_msg(chat_id=10, msg_id=1, mgid="a"), ctx,
        flush_callback=flush, delay=0.05,
    )
    await media_group.buffer_message(
        _make_msg(chat_id=10, msg_id=99, mgid="b"), ctx,
        flush_callback=flush, delay=0.05,
    )
    await asyncio.sleep(0.15)

    assert sorted(flush_calls) == ["a", "b"]
