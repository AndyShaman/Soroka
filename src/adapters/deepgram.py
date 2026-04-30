import httpx


class DeepgramError(Exception):
    pass


class DeepgramClient:
    BASE = "https://api.deepgram.com/v1"
    MODEL = "nova-3"

    def __init__(self, api_key: str, timeout: float = 60.0):
        self._api_key = api_key
        self._timeout = timeout

    async def validate_key(self) -> bool:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(
                f"{self.BASE}/projects",
                headers={"Authorization": f"Token {self._api_key}"},
            )
        return r.status_code == 200

    async def transcribe(self, audio_bytes: bytes, mime: str = "audio/ogg") -> str:
        params = {"model": self.MODEL, "language": "multi", "smart_format": "true"}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                f"{self.BASE}/listen",
                params=params,
                headers={
                    "Authorization": f"Token {self._api_key}",
                    "Content-Type": mime,
                },
                content=audio_bytes,
            )
        if r.status_code != 200:
            raise DeepgramError(f"{r.status_code}: {r.text[:200]}")
        data = r.json()
        try:
            return data["results"]["channels"][0]["alternatives"][0]["transcript"]
        except (KeyError, IndexError) as e:
            raise DeepgramError(f"unexpected response: {e}") from e
