import json
import re

# Strip ```json ... ``` or ``` ... ``` fences that LLMs (especially Gemini)
# wrap structured output in despite explicit instructions not to.
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)
_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


def parse_loose_json(raw: str | None):
    """Best-effort JSON parsing for LLM output. Tries direct parse, then
    fence-stripping, then regex extraction of the first {...} or [...].
    Raises ValueError if nothing parseable is found.
    """
    if raw is None:
        raise ValueError("LLM returned None (likely refusal or empty content)")
    s = raw.strip()
    if not s:
        raise ValueError("LLM returned empty string")

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass

    cleaned = _FENCE_RE.sub("", s).strip()
    if cleaned and cleaned != s:
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

    for pattern in (_OBJECT_RE, _ARRAY_RE):
        m = pattern.search(cleaned or s)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                continue

    raise ValueError(f"no JSON found in LLM response: {s[:120]!r}")
