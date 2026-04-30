# tests/test_deepgram.py
import pytest
from src.adapters.deepgram import DeepgramClient

@pytest.mark.asyncio
async def test_validate_key_success(httpx_mock):
    httpx_mock.add_response(
        url="https://api.deepgram.com/v1/projects",
        json={"projects": []},
    )
    c = DeepgramClient(api_key="ok")
    assert await c.validate_key() is True

@pytest.mark.asyncio
async def test_transcribe_returns_text(httpx_mock):
    httpx_mock.add_response(
        url="https://api.deepgram.com/v1/listen?model=nova-3&language=multi&smart_format=true",
        json={"results": {"channels": [{"alternatives": [{"transcript": "привет мир"}]}]}},
    )
    c = DeepgramClient(api_key="ok")
    text = await c.transcribe(b"FAKE_AUDIO_BYTES", mime="audio/ogg")
    assert text == "привет мир"


from src.adapters.deepgram import DeepgramError


@pytest.mark.asyncio
async def test_validate_key_unauthorized(httpx_mock):
    httpx_mock.add_response(
        url="https://api.deepgram.com/v1/projects",
        status_code=401,
        text="invalid key",
    )
    c = DeepgramClient(api_key="bad")
    assert await c.validate_key() is False


@pytest.mark.asyncio
async def test_validate_key_propagates_5xx(httpx_mock):
    httpx_mock.add_response(
        url="https://api.deepgram.com/v1/projects",
        status_code=503,
        text="down",
    )
    c = DeepgramClient(api_key="ok")
    with pytest.raises(DeepgramError) as exc:
        await c.validate_key()
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_transcribe_raises_on_error_status(httpx_mock):
    httpx_mock.add_response(
        url="https://api.deepgram.com/v1/listen?model=nova-3&language=multi&smart_format=true",
        status_code=429,
        text="rate limit",
    )
    c = DeepgramClient(api_key="ok")
    with pytest.raises(DeepgramError) as exc:
        await c.transcribe(b"FAKE", mime="audio/ogg")
    assert exc.value.status_code == 429
