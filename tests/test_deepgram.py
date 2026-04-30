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
