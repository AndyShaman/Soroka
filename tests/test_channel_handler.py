from datetime import datetime, timezone

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.core.db import open_db, init_schema
from src.core.owners import create_or_get_owner, advance_setup_step, update_owner_field
from src.bot.handlers.channel import channel_handler, _safe_filename


def _make_ctx(conn, owner_id=42):
    settings = MagicMock(owner_telegram_id=owner_id)
    ctx = MagicMock()
    ctx.application.bot_data = {"settings": settings, "conn": conn}
    ctx.bot.set_message_reaction = AsyncMock()
    return ctx


def _make_update(chat_id, text=None, caption=None, edited=False, message_id=100,
                 forward_chat_id=None, date_ts=None):
    """edited=True puts the message under edited_channel_post; channel_post
    is then None — matches how PTB delivers EDITED_CHANNEL_POST updates."""
    update = MagicMock()
    if edited:
        update.channel_post = None
        post = update.edited_channel_post
    else:
        update.edited_channel_post = None
        post = update.channel_post
    post.chat.id = chat_id
    post.message_id = message_id
    post.text = text
    post.caption = caption
    post.media_group_id = None
    if forward_chat_id is not None:
        post.forward_origin = MagicMock()
        post.forward_from_chat = MagicMock(id=forward_chat_id)
    else:
        post.forward_origin = None
        post.forward_from_chat = None
    if date_ts is not None:
        post.date = datetime.fromtimestamp(date_ts, tz=timezone.utc)
    return update


@pytest.fixture(autouse=True)
def _reset_recent_solo():
    """Each test starts with an empty pair-detection buffer so the
    cross-test order doesn't change behaviour."""
    from src.bot.handlers import channel as channel_module
    channel_module._recent_solo.clear()
    yield
    channel_module._recent_solo.clear()


@pytest.mark.asyncio
async def test_channel_handler_ignores_slash_commands(tmp_path):
    """Regression: posts that start with `/` (e.g. /export typed in the
    inbox channel by mistake) must NOT be indexed as notes. Previously
    they were ingested as text and polluted search results."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    advance_setup_step(conn, 42, "done")
    update_owner_field(conn, 42, "inbox_chat_id", -1001234)

    ctx = _make_ctx(conn)
    update = _make_update(chat_id=-1001234, text="/export")

    with patch("src.bot.handlers.channel._route_and_ingest", new=AsyncMock()) as routed:
        await channel_handler(update, ctx)
        routed.assert_not_called()
    ctx.bot.set_message_reaction.assert_not_called()


@pytest.mark.asyncio
async def test_channel_handler_ingests_normal_text(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    advance_setup_step(conn, 42, "done")
    update_owner_field(conn, 42, "inbox_chat_id", -1001234)

    ctx = _make_ctx(conn)
    update = _make_update(chat_id=-1001234, text="biohacker notes about DNA")

    with patch("src.bot.handlers.channel._route_and_ingest", new=AsyncMock()) as routed:
        await channel_handler(update, ctx)
        routed.assert_awaited_once()


def test_safe_filename_keeps_normal_name():
    assert _safe_filename("report.pdf", "abc") == "report.pdf"


def test_safe_filename_strips_path_traversal():
    assert _safe_filename("../../etc/passwd", "abc") == "passwd"
    assert _safe_filename("/etc/passwd", "abc") == "passwd"
    assert _safe_filename("../secret.txt", "abc") == "secret.txt"


def test_safe_filename_falls_back_for_empty_or_dotonly():
    assert _safe_filename(None, "abc") == "document_abc"
    assert _safe_filename("", "abc") == "document_abc"
    assert _safe_filename("..", "abc") == "document_abc"
    assert _safe_filename(".", "abc") == "document_abc"
    assert _safe_filename("../", "abc") == "document_abc"


def test_safe_filename_unicode_basename():
    assert _safe_filename("отчёт.pdf", "abc") == "отчёт.pdf"
    assert _safe_filename("../../отчёт с пробелами.pdf", "abc") == "отчёт с пробелами.pdf"


@pytest.mark.asyncio
async def test_channel_handler_routes_edited_post_with_is_edit_flag(tmp_path):
    """An edited channel post must reach _route_and_ingest with is_edit=True
    so that ingest does an UPDATE (not a silent INSERT-OR-IGNORE that
    discards the new content)."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    advance_setup_step(conn, 42, "done")
    update_owner_field(conn, 42, "inbox_chat_id", -1001234)

    ctx = _make_ctx(conn)
    update = _make_update(chat_id=-1001234, text="updated text", edited=True)

    with patch("src.bot.handlers.channel._route_and_ingest", new=AsyncMock()) as routed:
        await channel_handler(update, ctx)
        routed.assert_awaited_once()
        assert routed.await_args.kwargs["is_edit"] is True


@pytest.mark.asyncio
async def test_channel_handler_routes_new_post_with_is_edit_false(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    advance_setup_step(conn, 42, "done")
    update_owner_field(conn, 42, "inbox_chat_id", -1001234)

    ctx = _make_ctx(conn)
    update = _make_update(chat_id=-1001234, text="fresh note", edited=False)

    with patch("src.bot.handlers.channel._route_and_ingest", new=AsyncMock()) as routed:
        await channel_handler(update, ctx)
        routed.assert_awaited_once()
        assert routed.await_args.kwargs["is_edit"] is False


@pytest.mark.asyncio
async def test_channel_handler_sets_thin_reaction_on_thin_extract(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    advance_setup_step(conn, 42, "done")
    update_owner_field(conn, 42, "inbox_chat_id", -1001234)

    ctx = _make_ctx(conn)
    update = _make_update(chat_id=-1001234, text="https://example.com/empty")

    async def thin_route(*a, **kw):
        from src.core.notes import insert_note
        from src.core.models import Note
        return insert_note(conn, Note(
            owner_id=42, tg_chat_id=-1001234, tg_message_id=100,
            kind="web", title="x", content="short.",
            source_url="https://example.com/empty", raw_caption=None,
            created_at=1, thin_content=True,
        ))

    with patch("src.bot.handlers.channel._route_and_ingest", new=thin_route):
        await channel_handler(update, ctx)

    last_call = ctx.bot.set_message_reaction.await_args_list[-1]
    reaction_list = last_call.kwargs["reaction"]
    assert reaction_list[0].emoji == "🤷"


@pytest.mark.asyncio
async def test_channel_handler_routes_media_group_to_buffer(tmp_path):
    """A message with media_group_id must NOT take the single-message
    path (_route_and_ingest); it goes to the album buffer instead."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    advance_setup_step(conn, 42, "done")
    update_owner_field(conn, 42, "inbox_chat_id", -1001234)

    ctx = _make_ctx(conn)
    update = _make_update(chat_id=-1001234, caption="album", message_id=500)
    update.channel_post.media_group_id = "mg-1"
    update.channel_post.photo = [
        MagicMock(file_id="x", file_unique_id="x", file_size=1)
    ]

    with patch(
        "src.bot.handlers.channel._route_and_ingest", new=AsyncMock()
    ) as routed, patch(
        "src.bot.handlers.channel.media_group.buffer_message",
        new=AsyncMock(),
    ) as buffered:
        await channel_handler(update, ctx)
        routed.assert_not_called()
        buffered.assert_awaited_once()


@pytest.mark.asyncio
async def test_channel_handler_single_message_unchanged(tmp_path):
    """Regression: a normal single message (media_group_id=None) still
    goes through _route_and_ingest as before."""
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    advance_setup_step(conn, 42, "done")
    update_owner_field(conn, 42, "inbox_chat_id", -1001234)

    ctx = _make_ctx(conn)
    update = _make_update(chat_id=-1001234, text="just text", message_id=600)

    with patch(
        "src.bot.handlers.channel._route_and_ingest",
        new=AsyncMock(return_value=None),
    ) as routed, patch(
        "src.bot.handlers.channel.media_group.buffer_message",
        new=AsyncMock(),
    ) as buffered:
        await channel_handler(update, ctx)
        routed.assert_awaited_once()
        buffered.assert_not_called()


# ============================================================
# Comment + forward pair indexing
# ============================================================

def _setup_owner(tmp_path, *, owner_id=42, chat_id=-1001234):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=owner_id)
    advance_setup_step(conn, owner_id, "done")
    update_owner_field(conn, owner_id, "inbox_chat_id", chat_id)
    return conn


@pytest.mark.asyncio
async def test_channel_handler_pairs_comment_then_forward(tmp_path):
    """Within 2 s: text-only post followed by a forward → reindex_pair
    is invoked once with both note ids."""
    conn = _setup_owner(tmp_path)
    ctx = _make_ctx(conn)

    u1 = _make_update(chat_id=-1001234, text="это про агентов лучшие решения",
                      message_id=100, date_ts=1_700_000_000)
    u2 = _make_update(chat_id=-1001234, text="forwarded body", message_id=101,
                      forward_chat_id=-100999, date_ts=1_700_000_001)

    with patch(
        "src.bot.handlers.channel._route_and_ingest",
        new=AsyncMock(side_effect=[10, 20]),
    ), patch(
        "src.bot.handlers.channel.sibling_index.reindex_pair",
        new=AsyncMock(),
    ) as reindexed:
        await channel_handler(u1, ctx)
        await channel_handler(u2, ctx)
        reindexed.assert_awaited_once()
        kw = reindexed.await_args.kwargs
        assert kw["note_a_id"] == 10
        assert kw["note_b_id"] == 20


@pytest.mark.asyncio
async def test_channel_handler_pairs_forward_then_comment(tmp_path):
    """Order doesn't matter — forward first, then comment within 2 s."""
    conn = _setup_owner(tmp_path)
    ctx = _make_ctx(conn)

    u1 = _make_update(chat_id=-1001234, text="forwarded body", message_id=100,
                      forward_chat_id=-100999, date_ts=1_700_000_000)
    u2 = _make_update(chat_id=-1001234, text="мой коммент", message_id=101,
                      date_ts=1_700_000_001)

    with patch(
        "src.bot.handlers.channel._route_and_ingest",
        new=AsyncMock(side_effect=[30, 40]),
    ), patch(
        "src.bot.handlers.channel.sibling_index.reindex_pair",
        new=AsyncMock(),
    ) as reindexed:
        await channel_handler(u1, ctx)
        await channel_handler(u2, ctx)
        reindexed.assert_awaited_once()


@pytest.mark.asyncio
async def test_channel_handler_no_pair_when_window_exceeded(tmp_path):
    """5 s gap > 2 s window → not a pair."""
    conn = _setup_owner(tmp_path)
    ctx = _make_ctx(conn)

    u1 = _make_update(chat_id=-1001234, text="a", message_id=100,
                      date_ts=1_700_000_000)
    u2 = _make_update(chat_id=-1001234, text="b", message_id=101,
                      forward_chat_id=-100999, date_ts=1_700_000_005)

    with patch(
        "src.bot.handlers.channel._route_and_ingest",
        new=AsyncMock(side_effect=[1, 2]),
    ), patch(
        "src.bot.handlers.channel.sibling_index.reindex_pair",
        new=AsyncMock(),
    ) as reindexed:
        await channel_handler(u1, ctx)
        await channel_handler(u2, ctx)
        reindexed.assert_not_called()


@pytest.mark.asyncio
async def test_channel_handler_no_pair_two_forwards(tmp_path):
    """Two forwards in 1 s → both indexed as singletons, no pairing."""
    conn = _setup_owner(tmp_path)
    ctx = _make_ctx(conn)

    u1 = _make_update(chat_id=-1001234, text="a", message_id=100,
                      forward_chat_id=-100111, date_ts=1_700_000_000)
    u2 = _make_update(chat_id=-1001234, text="b", message_id=101,
                      forward_chat_id=-100222, date_ts=1_700_000_001)

    with patch(
        "src.bot.handlers.channel._route_and_ingest",
        new=AsyncMock(side_effect=[1, 2]),
    ), patch(
        "src.bot.handlers.channel.sibling_index.reindex_pair",
        new=AsyncMock(),
    ) as reindexed:
        await channel_handler(u1, ctx)
        await channel_handler(u2, ctx)
        reindexed.assert_not_called()


@pytest.mark.asyncio
async def test_channel_handler_no_pair_two_comments(tmp_path):
    """Two text-only posts in 1 s → not a pair."""
    conn = _setup_owner(tmp_path)
    ctx = _make_ctx(conn)

    u1 = _make_update(chat_id=-1001234, text="first", message_id=100,
                      date_ts=1_700_000_000)
    u2 = _make_update(chat_id=-1001234, text="second", message_id=101,
                      date_ts=1_700_000_001)

    with patch(
        "src.bot.handlers.channel._route_and_ingest",
        new=AsyncMock(side_effect=[1, 2]),
    ), patch(
        "src.bot.handlers.channel.sibling_index.reindex_pair",
        new=AsyncMock(),
    ) as reindexed:
        await channel_handler(u1, ctx)
        await channel_handler(u2, ctx)
        reindexed.assert_not_called()


@pytest.mark.asyncio
async def test_channel_handler_no_pair_across_chats(tmp_path):
    """Pairing is scoped per chat. The owner's only inbox is one chat,
    but we still defend against accidental cross-chat coupling."""
    conn = _setup_owner(tmp_path)
    ctx = _make_ctx(conn)

    u1 = _make_update(chat_id=-1001234, text="solo a", message_id=100,
                      date_ts=1_700_000_000)
    # Different chat id — handler will reject non-inbox chats anyway,
    # but the recent_solo bookkeeping must not cross chats.
    u2 = _make_update(chat_id=-1009999, text="solo b", message_id=101,
                      forward_chat_id=-100222, date_ts=1_700_000_001)

    with patch(
        "src.bot.handlers.channel._route_and_ingest",
        new=AsyncMock(return_value=1),
    ), patch(
        "src.bot.handlers.channel.sibling_index.reindex_pair",
        new=AsyncMock(),
    ) as reindexed:
        await channel_handler(u1, ctx)
        await channel_handler(u2, ctx)
        reindexed.assert_not_called()


@pytest.mark.asyncio
async def test_channel_handler_pair_only_uses_immediate_predecessor(tmp_path):
    """Buffer holds only the most recent solo. Sequence text → text →
    forward (each within 1 s) should NOT pair the FIRST text with the
    forward — only the second text vs. forward are checked, and that's
    a valid pair."""
    conn = _setup_owner(tmp_path)
    ctx = _make_ctx(conn)

    u1 = _make_update(chat_id=-1001234, text="first text", message_id=100,
                      date_ts=1_700_000_000)
    u2 = _make_update(chat_id=-1001234, text="second text", message_id=101,
                      date_ts=1_700_000_001)
    u3 = _make_update(chat_id=-1001234, text="fwd body", message_id=102,
                      forward_chat_id=-100222, date_ts=1_700_000_002)

    with patch(
        "src.bot.handlers.channel._route_and_ingest",
        new=AsyncMock(side_effect=[1, 2, 3]),
    ), patch(
        "src.bot.handlers.channel.sibling_index.reindex_pair",
        new=AsyncMock(),
    ) as reindexed:
        await channel_handler(u1, ctx)
        await channel_handler(u2, ctx)
        await channel_handler(u3, ctx)
        # Pair fires for (text=2, forward=3); the first text (1) is
        # already overwritten in the buffer and never paired.
        reindexed.assert_awaited_once()
        kw = reindexed.await_args.kwargs
        assert kw["note_a_id"] == 2
        assert kw["note_b_id"] == 3
