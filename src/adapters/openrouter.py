from dataclasses import dataclass
from typing import Optional

import httpx


class OpenRouterError(Exception):
    pass


@dataclass(frozen=True)
class ModelInfo:
    id: str
    name: str
    prompt_price: float       # USD per token (prompt)
    completion_price: float   # USD per token (completion)
    context_length: int
    is_free: bool


class OpenRouterClient:
    BASE = "https://openrouter.ai/api/v1"
    HTTP_RETRY_STATUSES = {429, 500, 502, 503, 504}

    def __init__(self, api_key: str, timeout: float = 60.0):
        self._api_key = api_key
        self._timeout = timeout

    async def validate_key(self) -> bool:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(
                f"{self.BASE}/auth/key",
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        return r.status_code == 200

    async def list_models(self) -> list[ModelInfo]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(f"{self.BASE}/models")
        if r.status_code != 200:
            raise OpenRouterError(f"{r.status_code}: {r.text[:200]}")
        models = []
        for d in r.json()["data"]:
            try:
                prompt = float(d["pricing"]["prompt"])
                completion = float(d["pricing"]["completion"])
            except (KeyError, ValueError, TypeError):
                continue
            models.append(ModelInfo(
                id=d["id"],
                name=d.get("name", d["id"]),
                prompt_price=prompt,
                completion_price=completion,
                context_length=d.get("context_length", 0) or 0,
                is_free=d["id"].endswith(":free") or prompt == 0,
            ))
        return sorted(models, key=lambda m: (not m.is_free, m.prompt_price))

    async def complete(self, primary: str, fallback: Optional[str],
                       messages: list[dict], max_tokens: int = 1000) -> str:
        try:
            return await self._call(primary, messages, max_tokens)
        except OpenRouterError:
            if not fallback:
                raise
            return await self._call(fallback, messages, max_tokens)

    async def _call(self, model: str, messages: list[dict], max_tokens: int) -> str:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                f"{self.BASE}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"model": model, "messages": messages, "max_tokens": max_tokens},
            )
        if r.status_code in self.HTTP_RETRY_STATUSES or r.status_code >= 500:
            raise OpenRouterError(f"{r.status_code}: {r.text[:200]}")
        if r.status_code != 200:
            raise OpenRouterError(f"{r.status_code}: {r.text[:200]}")
        return r.json()["choices"][0]["message"]["content"]
