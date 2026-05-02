import logging
from pathlib import Path

import pytesseract
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

# Hard cap on tesseract subprocess time. Stylized images or huge photos
# can otherwise pin a CPU core indefinitely and block ingest.
OCR_TIMEOUT_SEC = 30


def extract_ocr(path: Path, lang: str = "rus+eng") -> str:
    """OCR an image. Returns "" on any failure — ingest must continue
    even if tesseract is missing, crashes, or hangs. The caller already
    treats empty OCR as "no extra text" so a silent empty string is the
    correct degraded behaviour."""
    try:
        img = Image.open(str(path))
    except (FileNotFoundError, UnidentifiedImageError, OSError) as e:
        logger.warning("ocr: cannot open %s: %s", path, e)
        return ""
    try:
        return pytesseract.image_to_string(img, lang=lang, timeout=OCR_TIMEOUT_SEC).strip()
    except RuntimeError as e:
        # pytesseract raises RuntimeError on timeout
        logger.warning("ocr: timeout after %ss on %s: %s", OCR_TIMEOUT_SEC, path, e)
        return ""
    except pytesseract.TesseractNotFoundError:
        logger.warning("ocr: tesseract binary not found in PATH")
        return ""
    except Exception as e:
        logger.warning("ocr: unexpected failure on %s: %s", path, e)
        return ""
