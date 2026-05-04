import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.bot.handlers.search import search_handler
from src.core.models import Note


def _note(nid: int) -> Note:
    return Note(id=nid, owner_id=1, tg_message_id=nid, tg_chat_id=-1,
                kind="post", title=f"t{nid}", content=f"c{nid}",
                source_url=None, raw_caption=None, created_at=1000)


@pytest.mark.asyncio
async def test_search_handler_caches_reranked_pool_of_20(monkeypatch):
    """First search reranks 20 candidates and stores them in last_search.pool
    so navigation buttons can serve subsequent pages without re-running LLM."""
    pool = [_note(i) for i in range(1, 21)]

    update = MagicMock()
    update.effective_user.id = 1
    update.message.text = "test query"
    update.message.voice = None
    update.message.chat.id = -100

    ctx = MagicMock()
    ctx.user_data = {}
    ctx.application.bot_data = {
        "settings": MagicMock(owner_telegram_id=1),
        "conn": MagicMock(),
    }
    ctx.bot.send_chat_action = AsyncMock()

    owner = MagicMock(setup_step="done", telegram_id=1, jina_api_key="k",
                     openrouter_key="k", primary_model="m", fallback_model=None,
                     deepgram_api_key="k")
    monkeypatch.setattr("src.bot.handlers.search.get_owner", lambda *a, **kw: owner)
    monkeypatch.setattr("src.bot.handlers.search.is_owner", lambda *a, **kw: True)

    intent = MagicMock(clean_query="test query", kind=None)
    monkeypatch.setattr("src.bot.handlers.search.parse_intent",
                        AsyncMock(return_value=intent))
    monkeypatch.setattr("src.bot.handlers.search.hybrid_search",
                        AsyncMock(return_value=pool))
    rerank_mock = AsyncMock(return_value=pool)
    monkeypatch.setattr("src.bot.handlers.search.rerank", rerank_mock)
    update.message.reply_text = AsyncMock()

    await search_handler(update, ctx)

    rerank_mock.assert_awaited_once()
    # rerank must be asked for top_k=20, not 5
    _, kwargs = rerank_mock.call_args
    assert kwargs["top_k"] == 20

    state = ctx.user_data["last_search"]
    assert len(state["pool"]) == 20
    assert state["cursor"] == 5  # first 5 already shown
    assert [n.id for n in state["pool"]] == list(range(1, 21))
    assert state["shown_ids"] == [1, 2, 3, 4, 5]
