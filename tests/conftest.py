import pytest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def ensure_fixture_pdf():
    FIXTURES.mkdir(exist_ok=True)
    pdf_path = FIXTURES / "sample.pdf"
    if pdf_path.exists():
        return
    from pypdf import PdfWriter
    from pypdf.generic import RectangleObject
    # Minimal one-page PDF with embedded text via ReportLab fallback
    try:
        from reportlab.pdfgen import canvas
        c = canvas.Canvas(str(pdf_path))
        c.drawString(100, 750, "Hello PDF world from Soroka")
        c.save()
    except ImportError:
        # ReportLab is dev-only; install if missing
        import subprocess, sys
        subprocess.run([sys.executable, "-m", "pip", "install", "reportlab"], check=True)
        from reportlab.pdfgen import canvas
        c = canvas.Canvas(str(pdf_path))
        c.drawString(100, 750, "Hello PDF world from Soroka")
        c.save()
