from pathlib import Path
from pypdf import PdfReader


def extract_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(p.strip() for p in parts if p.strip())
