# tests/test_openrouter.py
import pytest
from src.adapters.openrouter import OpenRouterClient, ModelInfo

@pytest.mark.asyncio
async def test_validate_key_success(httpx_mock):
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/auth/key",
        json={"data": {"limit": 1.0}},
    )
    c = OpenRouterClient(api_key="ok")
    assert await c.validate_key() is True

@pytest.mark.asyncio
async def test_list_models_sorts_free_first(httpx_mock):
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/models",
        json={"data": [
            {"id": "anthropic/claude-3.5-haiku", "name": "Haiku",
             "pricing": {"prompt": "0.0000008", "completion": "0.000004"},
             "context_length": 200000},
            {"id": "google/gemini-2.0-flash-exp:free", "name": "Gemini Free",
             "pricing": {"prompt": "0", "completion": "0"},
             "context_length": 1000000},
            {"id": "meta-llama/llama-3.3-70b", "name": "Llama 3.3",
             "pricing": {"prompt": "0.00000059", "completion": "0.00000079"},
             "context_length": 131072},
        ]},
    )
    c = OpenRouterClient(api_key="ok")
    models = await c.list_models()
    assert models[0].id.endswith(":free")
    assert [m.id for m in models[1:]] == [
        "meta-llama/llama-3.3-70b",
        "anthropic/claude-3.5-haiku",
    ]

@pytest.mark.asyncio
async def test_complete_falls_back_on_primary_error(httpx_mock):
    # First call (primary) returns 503
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/chat/completions",
        match_json={"model": "primary/x", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1000},
        status_code=503,
        json={"error": "down"},
    )
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/chat/completions",
        match_json={"model": "fallback/y", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1000},
        json={"choices": [{"message": {"content": "ok"}}]},
    )
    c = OpenRouterClient(api_key="k")
    out = await c.complete(
        primary="primary/x", fallback="fallback/y",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert out == "ok"


from src.adapters.openrouter import OpenRouterError


@pytest.mark.asyncio
async def test_validate_key_unauthorized(httpx_mock):
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/auth/key",
        status_code=401,
        text="bad",
    )
    c = OpenRouterClient(api_key="bad")
    assert await c.validate_key() is False


@pytest.mark.asyncio
async def test_validate_key_propagates_5xx(httpx_mock):
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/auth/key",
        status_code=503,
        text="down",
    )
    c = OpenRouterClient(api_key="ok")
    with pytest.raises(OpenRouterError) as exc:
        await c.validate_key()
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_complete_no_fallback_raises(httpx_mock):
    httpx_mock.add_response(
        url="https://openrouter.ai/api/v1/chat/completions",
        match_json={"model": "primary/x", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 1000},
        status_code=503,
        text="down",
    )
    c = OpenRouterClient(api_key="k")
    with pytest.raises(OpenRouterError) as exc:
        await c.complete(
            primary="primary/x", fallback=None,
            messages=[{"role": "user", "content": "hi"}],
        )
    assert exc.value.status_code == 503
