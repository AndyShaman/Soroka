# tests/test_extractor_pdf.py
from pathlib import Path
from src.adapters.extractors.pdf import extract_pdf


def test_extract_pdf(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "sample.pdf"
    text = extract_pdf(fixture)
    assert "Hello PDF world from Soroka" in text
