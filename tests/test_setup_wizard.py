import pytest
from unittest.mock import AsyncMock, patch

from src.core.db import open_db, init_schema
from src.core.owners import create_or_get_owner, get_owner
from src.bot.handlers.setup import process_setup_message

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
