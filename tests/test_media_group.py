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
