from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.bot.auth import is_owner, owner_only


def test_is_owner_match():
    assert is_owner(user_id=42, owner_id=42)


def test_is_owner_mismatch():
    assert not is_owner(user_id=43, owner_id=42)


def _make_ctx(owner_id: int = 100):
    settings = SimpleNamespace(owner_telegram_id=owner_id)
    application = SimpleNamespace(bot_data={"settings": settings})
    return SimpleNamespace(application=application)


def _make_update(user_id):
    user = SimpleNamespace(id=user_id) if user_id is not None else None
    return SimpleNamespace(effective_user=user)


@pytest.mark.asyncio
async def test_owner_only_calls_handler_for_owner():
    inner = AsyncMock()
    decorated = owner_only(inner)
    await decorated(_make_update(user_id=100), _make_ctx(owner_id=100))
    inner.assert_awaited_once()


@pytest.mark.asyncio
async def test_owner_only_blocks_stranger():
    inner = AsyncMock()
    decorated = owner_only(inner)
    await decorated(_make_update(user_id=999), _make_ctx(owner_id=100))
    inner.assert_not_awaited()


@pytest.mark.asyncio
async def test_owner_only_blocks_anonymous_update():
    inner = AsyncMock()
    decorated = owner_only(inner)
    await decorated(_make_update(user_id=None), _make_ctx(owner_id=100))
    inner.assert_not_awaited()
