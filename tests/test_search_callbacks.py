import pytest
from unittest.mock import AsyncMock, MagicMock

from src.bot.handlers.search_callbacks import (
    on_next_page, on_toggle_period, on_exclude_current, on_start_refine,
    PERIODS,
)
from src.core.models import Note


def _note(nid: int) -> Note:
    return Note(id=nid, owner_id=1, tg_message_id=nid, tg_chat_id=-1,
                kind="post", title=f"t{nid}", content=f"c{nid}",
                source_url=None, raw_caption=None, created_at=1000)


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
async def test_start_refine_sets_awaiting_flag():
    state = {"query": "x", "offset": 0, "since_days": None,
             "excluded_ids": [], "last_returned_ids": []}
    ctx = _make_ctx(state)
    update = _make_callback_update("search:refine")
    await on_start_refine(update, ctx)

    assert ctx.user_data.get("awaiting_refinement") is True
    update.callback_query.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_next_page_serves_from_pool_without_rerank(monkeypatch):
    """Fast-path: Ещё 5 takes the next slice from the cached pool — no LLM."""
    pool = [_note(i) for i in range(1, 21)]
    state = {"query": "x", "since_days": None, "excluded_ids": [],
             "pool": pool, "shown_ids": [1, 2, 3, 4, 5], "cursor": 5}
    ctx = _make_ctx(state)
    update = _make_callback_update("search:next")

    rerun = AsyncMock()
    monkeypatch.setattr("src.bot.handlers.search_callbacks._rerun_and_format", rerun)

    await on_next_page(update, ctx)

    rerun.assert_not_awaited()
    assert ctx.user_data["last_search"]["cursor"] == 10
    assert ctx.user_data["last_search"]["shown_ids"] == [6, 7, 8, 9, 10]
    update.callback_query.edit_message_text.assert_awaited_once()


@pytest.mark.asyncio
async def test_next_page_pool_exhausted_shows_message():
    """When cursor reaches the end of the pool, surface a hint and keep buttons."""
    pool = [_note(i) for i in range(1, 21)]
    state = {"query": "x", "since_days": None, "excluded_ids": [],
             "pool": pool, "shown_ids": [16, 17, 18, 19, 20], "cursor": 20}
    ctx = _make_ctx(state)
    update = _make_callback_update("search:next")

    await on_next_page(update, ctx)

    update.callback_query.edit_message_text.assert_awaited_once()
    text_arg = update.callback_query.edit_message_text.call_args[0][0]
    assert "больше" in text_arg.lower() or "уточни" in text_arg.lower()


@pytest.mark.asyncio
async def test_exclude_current_drops_shown_from_pool(monkeypatch):
    """Fast-path: Не то removes shown_ids from pool, advances cursor accordingly."""
    pool = [_note(i) for i in range(1, 21)]
    state = {"query": "x", "since_days": None, "excluded_ids": [],
             "pool": pool, "shown_ids": [1, 2, 3, 4, 5], "cursor": 5}
    ctx = _make_ctx(state)
    update = _make_callback_update("search:exclude")

    rerun = AsyncMock()
    monkeypatch.setattr("src.bot.handlers.search_callbacks._rerun_and_format", rerun)

    await on_exclude_current(update, ctx)

    rerun.assert_not_awaited()
    new_state = ctx.user_data["last_search"]
    assert set(new_state["excluded_ids"]) == {1, 2, 3, 4, 5}
    assert all(n.id not in new_state["excluded_ids"] for n in new_state["pool"])
    assert new_state["shown_ids"] == [6, 7, 8, 9, 10]
