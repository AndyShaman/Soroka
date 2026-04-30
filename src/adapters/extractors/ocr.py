from pathlib import Path
import pytesseract
from PIL import Image


def extract_ocr(path: Path, lang: str = "rus+eng") -> str:
    img = Image.open(str(path))
    return pytesseract.image_to_string(img, lang=lang).strip()
