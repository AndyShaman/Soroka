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


@pytest.mark.asyncio
async def test_validate_key_propagates_5xx(httpx_mock):
    httpx_mock.add_response(
        url="https://api.jina.ai/v1/embeddings",
        method="POST",
        status_code=503,
        text="service down",
    )
    c = JinaClient(api_key="test")
    with pytest.raises(JinaError) as exc:
        await c.validate_key()
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_embed_rejects_wrong_dim(httpx_mock):
    httpx_mock.add_response(
        url="https://api.jina.ai/v1/embeddings",
        json={"data": [{"embedding": [0.1] * 512}]},
    )
    c = JinaClient(api_key="test")
    with pytest.raises(JinaError, match="unexpected embedding dim"):
        await c.embed("hello")
