def extract_text(text: str | None) -> str:
    if not text:
        return ""
    return text.strip()
