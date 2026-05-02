from datetime import datetime, timezone

import pytest
from unittest.mock import AsyncMock, patch

from src.core.db import open_db, init_schema
from src.core.owners import create_or_get_owner, get_owner
from src.bot.handlers.setup import process_setup_message, register_setup_handlers

@pytest.mark.asyncio
async def test_jina_step_accepts_valid_key(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    # advance to jina step
    from src.core.owners import advance_setup_step
    advance_setup_step(conn, 1, "jina")

    with patch("src.bot.handlers.setup.JinaClient") as mock_cls:
        mock_cls.return_value.validate_key = AsyncMock(return_value=True)
        next_prompt = await process_setup_message(conn, owner_id=1, text="jina-key-123")

    assert "Шаг 2" in next_prompt or "Deepgram" in next_prompt
    assert get_owner(conn, 1).jina_api_key == "jina-key-123"
    assert get_owner(conn, 1).setup_step == "deepgram"

@pytest.mark.asyncio
async def test_jina_step_rejects_invalid_key(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    from src.core.owners import advance_setup_step
    advance_setup_step(conn, 1, "jina")

    with patch("src.bot.handlers.setup.JinaClient") as mock_cls:
        mock_cls.return_value.validate_key = AsyncMock(return_value=False)
        msg = await process_setup_message(conn, owner_id=1, text="bad-key")

    assert "не подошёл" in msg.lower() or "invalid" in msg.lower()
    assert get_owner(conn, 1).jina_api_key is None
    assert get_owner(conn, 1).setup_step == "jina"


def test_setup_handler_dispatches_private_text():
    """Regression: a plain private text message during setup must be routed
    to a setup handler. Previously process_setup_message existed but no
    MessageHandler called it, so keys submitted to the wizard were silently
    swallowed by search_handler (which returns when setup_step != 'done')."""
    from telegram import Update, Message, Chat, User
    from telegram.ext import ApplicationBuilder, MessageHandler

    app = ApplicationBuilder().token("123:fake").build()
    register_setup_handlers(app)

    update = Update(
        update_id=1,
        message=Message(
            message_id=1,
            date=datetime.now(timezone.utc),
            chat=Chat(id=42, type=Chat.PRIVATE),
            from_user=User(id=42, is_bot=False, first_name="x"),
            text="my-jina-key-text",
        ),
    )

    accepting = [
        h for h in app.handlers.get(0, [])
        if isinstance(h, MessageHandler) and h.check_update(update)
    ]
    assert accepting, (
        "no setup MessageHandler accepts plain private text — "
        "wizard cannot receive API keys"
    )


@pytest.mark.asyncio
async def test_github_step_records_repo_then_asks_for_token(tmp_path):
    """First substep: 'username/repo' is saved into github_mirror_repo,
    response prompts for the token (5b)."""
    from src.core.owners import advance_setup_step
    from src.bot.handlers.setup_github import handle_github_step

    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    advance_setup_step(conn, 1, "github")

    reply = await handle_github_step(conn, 1, "andyshaman/soroka-data")

    assert "5b" in reply or "токен" in reply.lower() or "token" in reply.lower()
    assert get_owner(conn, 1).github_mirror_repo == "andyshaman/soroka-data"
    assert get_owner(conn, 1).github_token is None
    assert get_owner(conn, 1).setup_step == "github"


@pytest.mark.asyncio
async def test_github_step_rejects_malformed_repo(tmp_path):
    from src.core.owners import advance_setup_step
    from src.bot.handlers.setup_github import handle_github_step

    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    advance_setup_step(conn, 1, "github")

    reply = await handle_github_step(conn, 1, "ghp_oh_no_thats_a_token")

    assert "username" in reply or "репозитор" in reply.lower()
    assert get_owner(conn, 1).github_mirror_repo is None


@pytest.mark.asyncio
async def test_github_step_validates_token_and_advances(tmp_path):
    """Second substep: with repo already stored, a valid token validates,
    is saved, and the step advances to 'channel'."""
    from src.core.owners import advance_setup_step, update_owner_field
    from src.bot.handlers.setup_github import handle_github_step

    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    advance_setup_step(conn, 1, "github")
    update_owner_field(conn, 1, "github_mirror_repo", "andyshaman/soroka-data")

    with patch("src.bot.handlers.setup_github.GitHubMirror") as mock_cls:
        mock_cls.return_value.validate = AsyncMock(return_value=None)
        reply = await handle_github_step(conn, 1, "ghp_realToken123")

    assert "подключено" in reply.lower() or "channel" in reply.lower() or "канал" in reply.lower()
    assert get_owner(conn, 1).github_token == "ghp_realToken123"
    assert get_owner(conn, 1).setup_step == "channel"


@pytest.mark.asyncio
async def test_github_step_rejects_non_token_at_substep_2(tmp_path):
    from src.core.owners import advance_setup_step, update_owner_field
    from src.bot.handlers.setup_github import handle_github_step

    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    advance_setup_step(conn, 1, "github")
    update_owner_field(conn, 1, "github_mirror_repo", "andyshaman/soroka-data")

    reply = await handle_github_step(conn, 1, "not-a-token")

    assert "ghp_" in reply
    assert get_owner(conn, 1).github_token is None
    assert get_owner(conn, 1).setup_step == "github"


@pytest.mark.asyncio
async def test_forward_handler_keeps_step_on_publish_failure(tmp_path):
    """Regression: when the bot lacks admin rights in the forwarded channel,
    inbox_chat_id must NOT be saved and setup_step must NOT advance to 'done'.
    Previous code wrote both before testing publish, stranding the user."""
    from unittest.mock import MagicMock, AsyncMock
    from src.core.owners import advance_setup_step
    from src.bot.handlers.setup import forward_inbox_handler

    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    advance_setup_step(conn, 42, "channel")

    settings = MagicMock(owner_telegram_id=42)

    update = MagicMock()
    update.effective_user.id = 42
    update.message.forward_origin.type = "channel"
    update.message.forward_origin.chat.id = -1001234567890
    update.message.forward_origin.chat.title = "Тестовый канал"
    update.message.reply_text = AsyncMock()

    ctx = MagicMock()
    ctx.application.bot_data = {"settings": settings, "conn": conn}
    ctx.bot.send_message = AsyncMock(side_effect=Exception("403 forbidden"))

    await forward_inbox_handler(update, ctx)

    owner = get_owner(conn, 42)
    assert owner.setup_step == "channel"
    assert owner.inbox_chat_id is None
    update.message.reply_text.assert_called_once()
    reply = update.message.reply_text.call_args[0][0]
    assert "Тестовый канал" in reply
    assert "админ" in reply.lower()


@pytest.mark.asyncio
async def test_forward_handler_advances_on_publish_success(tmp_path):
    from unittest.mock import MagicMock, AsyncMock
    from src.core.owners import advance_setup_step
    from src.bot.handlers.setup import forward_inbox_handler

    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    advance_setup_step(conn, 42, "channel")

    settings = MagicMock(owner_telegram_id=42)

    update = MagicMock()
    update.effective_user.id = 42
    update.message.forward_origin.type = "channel"
    update.message.forward_origin.chat.id = -1001234567890
    update.message.forward_origin.chat.title = "Inbox"
    update.message.reply_text = AsyncMock()

    sent = MagicMock(message_id=999)
    ctx = MagicMock()
    ctx.application.bot_data = {"settings": settings, "conn": conn}
    ctx.bot.send_message = AsyncMock(return_value=sent)

    await forward_inbox_handler(update, ctx)

    owner = get_owner(conn, 42)
    assert owner.setup_step == "done"
    assert owner.inbox_chat_id == -1001234567890


@pytest.mark.asyncio
async def test_github_skip_clears_partial_repo(tmp_path):
    """If user typed repo but then /skip'd, the orphan repo string is cleared."""
    from src.core.owners import advance_setup_step, update_owner_field
    from src.bot.handlers.setup_github import handle_skip_github

    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=1)
    advance_setup_step(conn, 1, "github")
    update_owner_field(conn, 1, "github_mirror_repo", "andyshaman/soroka-data")

    await handle_skip_github(conn, 1)

    assert get_owner(conn, 1).github_mirror_repo is None
    assert get_owner(conn, 1).setup_step == "channel"
