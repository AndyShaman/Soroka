# tests/test_extractor_ocr.py
import pytest
import shutil
from pathlib import Path
from unittest.mock import patch

import pytesseract
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


def test_extract_ocr_returns_empty_on_missing_file(tmp_path):
    """ingest must continue with caption-only when the image file is
    gone — a hard error here would cancel the whole note save."""
    assert extract_ocr(tmp_path / "does-not-exist.png") == ""


def test_extract_ocr_returns_empty_on_corrupt_file(tmp_path):
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not a real image")
    assert extract_ocr(bad) == ""


def test_extract_ocr_returns_empty_when_tesseract_missing(tmp_path):
    img_path = tmp_path / "x.png"
    Image.new("RGB", (10, 10), "white").save(img_path)
    with patch("pytesseract.image_to_string",
               side_effect=pytesseract.TesseractNotFoundError()):
        assert extract_ocr(img_path) == ""


def test_extract_ocr_returns_empty_on_timeout(tmp_path):
    img_path = tmp_path / "x.png"
    Image.new("RGB", (10, 10), "white").save(img_path)
    # pytesseract surfaces the kill-on-timeout as RuntimeError
    with patch("pytesseract.image_to_string",
               side_effect=RuntimeError("Tesseract process timeout")):
        assert extract_ocr(img_path) == ""
