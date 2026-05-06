"""Russian summarisation for non-Russian extracted content.

Used by ingest to attach a short Russian description to web/youtube
notes whose body is in another language. The summary helps the owner
recognise what a foreign-language link is about at a glance and boosts
recall on Russian queries (the summary is concatenated into the
embedding text alongside the original body).

The module is best-effort: any LLM/network failure returns ``None`` and
the caller proceeds without a summary. Ingest must never block on this.
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Cyrillic-ratio heuristic. Cheap, no model call. Threshold tuned so that
# Russian articles with a few English brand names still register as RU,
# while English articles with a sprinkle of transliterated Russian don't.
_CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
_LETTER_RE = re.compile(r"[A-Za-zЀ-ӿ]")
_RU_THRESHOLD = 0.30

# Sample window: the opening of any reasonable article is plenty to
# decide language. Keeps CPU bounded on long extracts.
_SAMPLE_CHARS = 2000


def is_russian(text: str) -> bool:
    """True if `text` reads as Russian by Cyrillic-letter share.

    Returns False on empty/symbol-only text — there is no language to
    detect, and we'd rather skip summarisation than mis-trigger it.
    """
    if not text:
        return False
    sample = text[:_SAMPLE_CHARS]
    letters = _LETTER_RE.findall(sample)
    if not letters:
        return False
    cyr = _CYRILLIC_RE.findall(sample)
    return len(cyr) / len(letters) >= _RU_THRESHOLD


_SUMMARY_PROMPT = (
    "Опиши в 1-2 коротких предложениях по-русски, о чём этот текст. "
    "Не более 200 символов. Без вступлений вроде \"Этот текст\" — "
    "сразу по сути. Ответь только описанием, без кавычек и оформления.\n\n"
    "Текст:\n"
)

# Cap the prompt body. The opening of the extract carries the topic;
# sending more burns tokens without changing the answer.
_PROMPT_BODY_CHARS = 4000

# Hard cap on the saved summary. The model is asked for ≤200 chars but
# we trim defensively in case it overshoots.
_DEFAULT_MAX_CHARS = 200


async def summarize_ru(openrouter, primary: str, fallback: Optional[str],
                       text: str, *, max_chars: int = _DEFAULT_MAX_CHARS,
                       ) -> Optional[str]:
    """Generate a short Russian summary of `text` via OpenRouter.

    Returns None if `openrouter` is None, the input is empty, or the
    LLM call fails for any reason. Callers must treat the result as
    optional and proceed without it on None.
    """
    if openrouter is None or not primary:
        return None
    if not text or not text.strip():
        return None

    sample = text[:_PROMPT_BODY_CHARS]
    try:
        # `reasoning.enabled=false` keeps hybrid models (GLM-4.5, qwen-thinking,
        # gpt-oss-with-effort) from spending the output budget on hidden
        # reasoning tokens. Pure non-reasoning models ignore the field.
        raw = await openrouter.complete(
            primary=primary, fallback=fallback,
            messages=[{"role": "user", "content": _SUMMARY_PROMPT + sample}],
            max_tokens=120,
            extra_body={"reasoning": {"enabled": False}},
        )
    except Exception as e:
        logger.warning("ru_summary failed (%s); skipping", e)
        return None

    cleaned = (raw or "").strip()
    # Models occasionally wrap the answer in quotes; strip a single
    # matched pair if present. `«»` are asymmetric (different open/close)
    # so we handle them as an explicit pair rather than via equality.
    if len(cleaned) >= 2:
        if cleaned[0] == cleaned[-1] and cleaned[0] in "\"'":
            cleaned = cleaned[1:-1].strip()
        elif cleaned[0] == "«" and cleaned[-1] == "»":
            cleaned = cleaned[1:-1].strip()
    if not cleaned:
        return None
    # Hard-cap defensively in case the model overshoots its instruction.
    # The trimmed string ends in U+2026 (1 char), so the budget for the
    # body is `max_chars - 1` to keep total length ≤ max_chars.
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars - 1].rstrip() + "…"
    return cleaned
