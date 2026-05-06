import logging
from dataclasses import dataclass
from typing import Optional

from src.core.llm_json import parse_loose_json

logger = logging.getLogger(__name__)

PROMPT = """Ты — парсер поисковых запросов для личной базы знаний.
Извлеки из запроса пользователя:
- clean_query: основные ключевые слова без шума ("найди", "покажи", "что я сохранял про")
- kind: если фильтр по типу контента очевиден, верни одно из: text|voice|youtube|web|pdf|docx|xlsx|image|post. Иначе null.

Верни ТОЛЬКО валидный JSON, ничего больше. Пример: {"clean_query": "паста рецепт", "kind": null}.

Запрос: """


@dataclass(frozen=True)
class IntentResult:
    clean_query: str
    kind: Optional[str]


async def parse_intent(openrouter, primary: str, fallback: Optional[str],
                       query: str) -> IntentResult:
    try:
        raw = await openrouter.complete(
            primary=primary, fallback=fallback,
            messages=[{"role": "user", "content": PROMPT + query}],
            max_tokens=200,
            extra_body={"reasoning": {"enabled": False}},
        )
        data = parse_loose_json(raw)
        clean = data.get("clean_query", query) or query
        kind = data.get("kind")
        if kind not in {"text", "voice", "youtube", "web", "pdf", "docx", "xlsx", "image", "post"}:
            kind = None
        return IntentResult(clean_query=clean, kind=kind)
    except Exception as e:
        logger.warning("intent parse failed (%s); falling back to passthrough", e)
        return IntentResult(clean_query=query, kind=None)
