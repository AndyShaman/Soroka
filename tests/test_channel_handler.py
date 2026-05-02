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


def _make_update(chat_id, text=None, caption=None, edited=False, message_id=100):
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
    return update


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
