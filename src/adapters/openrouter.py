import logging
from dataclasses import dataclass
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class OpenRouterError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class EmptyContentError(OpenRouterError):
    """Raised when the LLM returns 200 OK with an empty content field.

    Reasoning models (gpt-5*, gpt-oss-*, R1, …) consume their output
    budget on hidden reasoning tokens and can return an empty `content`
    string. Treat that as a transient failure so `complete()` falls back
    to the secondary model just like it does for 5xx/429.
    """


# Keys that callers MUST NOT override via extra_body — they are managed
# by complete()/_call() and overriding them would silently subvert the
# fallback chain or change the call shape.
_RESERVED_BODY_KEYS = frozenset({"model", "messages", "max_tokens"})


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
        if r.status_code == 200:
            return True
        if r.status_code in (401, 403):
            return False
        raise OpenRouterError(
            f"transient error {r.status_code}: {r.text[:200]}",
            status_code=r.status_code,
        )

    async def list_models(self) -> list[ModelInfo]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.get(f"{self.BASE}/models")
        if r.status_code != 200:
            raise OpenRouterError(f"{r.status_code}: {r.text[:200]}", status_code=r.status_code)
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
                       messages: list[dict], max_tokens: int = 1000,
                       extra_body: Optional[dict] = None) -> str:
        try:
            return await self._call(primary, messages, max_tokens, extra_body)
        except OpenRouterError:
            if not fallback:
                raise
            return await self._call(fallback, messages, max_tokens, extra_body)

    async def _call(self, model: str, messages: list[dict], max_tokens: int,
                     extra_body: Optional[dict] = None) -> str:
        body = {"model": model, "messages": messages, "max_tokens": max_tokens}
        if extra_body:
            reserved = _RESERVED_BODY_KEYS & extra_body.keys()
            if reserved:
                raise ValueError(
                    f"extra_body must not override reserved keys: {sorted(reserved)}"
                )
            body.update(extra_body)
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            r = await client.post(
                f"{self.BASE}/chat/completions",
                headers={"Authorization": f"Bearer {self._api_key}"},
                json=body,
            )
        if r.status_code in self.HTTP_RETRY_STATUSES or r.status_code >= 500:
            raise OpenRouterError(f"{r.status_code}: {r.text[:200]}", status_code=r.status_code)
        if r.status_code != 200:
            raise OpenRouterError(f"{r.status_code}: {r.text[:200]}", status_code=r.status_code)
        content = r.json()["choices"][0]["message"].get("content")
        if not content:
            # Reasoning models can return 200 OK with empty content when the
            # output budget is fully consumed by hidden reasoning tokens.
            # Surface this as a retryable error so the fallback model fires.
            logger.warning("openrouter %s returned empty content (max_tokens=%d)",
                           model, max_tokens)
            raise EmptyContentError(f"empty content from {model}")
        return content
