import pytest
from unittest.mock import AsyncMock
from src.core.intent import parse_intent, IntentResult


@pytest.mark.asyncio
async def test_parse_intent_passthrough_when_llm_fails():
    fake = AsyncMock()
    fake.complete = AsyncMock(side_effect=Exception("down"))
    out = await parse_intent(fake, primary="x", fallback="y", query="что я сохранял про пасту")
    assert out.clean_query == "что я сохранял про пасту"
    assert out.kind is None


@pytest.mark.asyncio
async def test_parse_intent_extracts_kind_filter():
    fake = AsyncMock()
    fake.complete = AsyncMock(return_value='{"clean_query": "паста рецепт", "kind": "voice"}')
    out = await parse_intent(fake, primary="x", fallback="y",
                              query="голосовуха про пасту")
    assert out.clean_query == "паста рецепт"
    assert out.kind == "voice"


@pytest.mark.asyncio
async def test_parse_intent_disables_reasoning():
    fake = AsyncMock()
    fake.complete = AsyncMock(return_value='{"clean_query": "паста", "kind": null}')
    await parse_intent(fake, primary="x", fallback="y", query="паста")
    kwargs = fake.complete.call_args.kwargs
    assert kwargs["extra_body"] == {"reasoning": {"enabled": False}}
