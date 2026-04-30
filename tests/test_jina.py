import pytest
from src.adapters.jina import JinaClient, JinaError

@pytest.mark.asyncio
async def test_validate_key_success(httpx_mock):
    httpx_mock.add_response(
        url="https://api.jina.ai/v1/embeddings",
        method="POST",
        json={"data": [{"embedding": [0.0] * 1024}]},
    )
    c = JinaClient(api_key="test")
    assert await c.validate_key() is True

@pytest.mark.asyncio
async def test_validate_key_unauthorized(httpx_mock):
    httpx_mock.add_response(
        url="https://api.jina.ai/v1/embeddings",
        method="POST",
        status_code=401,
        json={"error": "unauthorized"},
    )
    c = JinaClient(api_key="bad")
    assert await c.validate_key() is False

@pytest.mark.asyncio
async def test_embed_passage(httpx_mock):
    expected = [0.1] * 1024
    httpx_mock.add_response(
        url="https://api.jina.ai/v1/embeddings",
        json={"data": [{"embedding": expected}]},
    )
    c = JinaClient(api_key="test")
    out = await c.embed("hello", role="passage")
    assert out == expected
