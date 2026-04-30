# tests/test_extractor_ocr.py
import pytest
import shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from src.adapters.extractors.ocr import extract_ocr


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="tesseract not installed")
def test_extract_ocr(tmp_path):
    img_path = tmp_path / "x.png"
    img = Image.new("RGB", (400, 80), "white")
    draw = ImageDraw.Draw(img)
    # Use default font; result is OK enough to recognize ASCII
    draw.text((10, 20), "Hello OCR", fill="black")
    img.save(img_path)

    text = extract_ocr(img_path, lang="eng")
    assert "Hello" in text or "OCR" in text
