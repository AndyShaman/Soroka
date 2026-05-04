import pytest
from unittest.mock import AsyncMock, MagicMock

from src.bot.handlers.search_callbacks import (
    on_next_page, on_toggle_period, on_exclude_current, on_start_refine,
    PERIODS,
)


def _make_ctx(state: dict):
    ctx = MagicMock()
    ctx.user_data = {"last_search": state}
    ctx.application.bot_data = {"settings": MagicMock(owner_telegram_id=1),
                                  "conn": MagicMock()}
    ctx.bot.send_chat_action = AsyncMock()
    return ctx


def _make_callback_update(callback_data: str):
    update = MagicMock()
    update.effective_user.id = 1
    update.callback_query.data = callback_data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


@pytest.mark.asyncio
async def test_next_page_advances_offset_by_5(monkeypatch):
    state = {"query": "x", "offset": 0, "since_days": None,
             "excluded_ids": [], "last_returned_ids": [1, 2, 3, 4, 5]}
    ctx = _make_ctx(state)
    update = _make_callback_update("search:next")

    rerun = AsyncMock(return_value=("text", [11, 12, 13, 14, 15]))
    monkeypatch.setattr("src.bot.handlers.search_callbacks._rerun_and_format", rerun)

    await on_next_page(update, ctx)

    assert ctx.user_data["last_search"]["offset"] == 5
    rerun.assert_awaited_once()


@pytest.mark.asyncio
async def test_toggle_period_cycles_through_options(monkeypatch):
    state = {"query": "x", "offset": 0, "since_days": None,
             "excluded_ids": [], "last_returned_ids": []}
    ctx = _make_ctx(state)
    rerun = AsyncMock(return_value=("text", []))
    monkeypatch.setattr("src.bot.handlers.search_callbacks._rerun_and_format", rerun)

    update = _make_callback_update("search:period")
    await on_toggle_period(update, ctx)

    assert ctx.user_data["last_search"]["since_days"] == PERIODS[1]


@pytest.mark.asyncio
async def test_exclude_current_adds_returned_ids_to_excluded(monkeypatch):
    state = {"query": "x", "offset": 0, "since_days": None,
             "excluded_ids": [], "last_returned_ids": [10, 11, 12]}
    ctx = _make_ctx(state)
    rerun = AsyncMock(return_value=("text", []))
    monkeypatch.setattr("src.bot.handlers.search_callbacks._rerun_and_format", rerun)

    update = _make_callback_update("search:exclude")
    await on_exclude_current(update, ctx)

    assert set(ctx.user_data["last_search"]["excluded_ids"]) == {10, 11, 12}
    assert ctx.user_data["last_search"]["offset"] == 0


@pytest.mark.asyncio
async def test_start_refine_sets_awaiting_flag():
    state = {"query": "x", "offset": 0, "since_days": None,
             "excluded_ids": [], "last_returned_ids": []}
    ctx = _make_ctx(state)
    update = _make_callback_update("search:refine")
    await on_start_refine(update, ctx)

    assert ctx.user_data.get("awaiting_refinement") is True
    update.callback_query.answer.assert_awaited_once()
