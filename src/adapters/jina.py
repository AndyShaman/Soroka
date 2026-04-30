from typing import Literal

import httpx


class JinaError(Exception):
    pass


class JinaClient:
    URL = "https://api.jina.ai/v1/embeddings"
    MODEL = "jina-embeddings-v3"

    def __init__(self, api_key: str, timeout: float = 30.0):
        self._api_key = api_key
        self._timeout = timeout

    async def validate_key(self) -> bool:
        try:
            await self.embed("ping", role="passage")
            return True
        except JinaError:
            return False

    async def embed(self, text: str, role: Literal["passage", "query"] = "passage") -> list[float]:
        task = "retrieval.passage" if role == "passage" else "retrieval.query"
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                self.URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": self.MODEL, "task": task, "input": [text]},
            )
        if r.status_code != 200:
            raise JinaError(f"{r.status_code}: {r.text[:200]}")
        return r.json()["data"][0]["embedding"]
