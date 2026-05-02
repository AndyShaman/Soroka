from src.bot.handlers.search import _clean_title, _clean_snippet, _format_hit
from src.core.models import Note


def test_clean_title_drops_file_ids():
    """photo_AQADlhJrG72ZqEt-.jpg is the Telegram file-id we picked when
    no caption was provided — useless to show to the user."""
    assert _clean_title("photo_AQADlhJrG72ZqEt-.jpg") == ""
    assert _clean_title("file_55.jpg") == ""
    assert _clean_title("document_42.pdf") == ""


def test_clean_title_keeps_real_titles():
    assert _clean_title("Чиабатта без замеса") == "Чиабатта без замеса"
    assert _clean_title("doc.pdf") == "doc.pdf"


def test_clean_title_handles_empty():
    assert _clean_title(None) == ""
    assert _clean_title("") == ""


def test_clean_snippet_collapses_ocr_noise():
    """Tesseract output for stylized images often looks like
    'к\\n-\\n=\\n\\nextreme\\n\\nBag OT клещей' — orphan symbols and
    blank lines should be hidden in the snippet, not stored differently."""
    raw = "к\n-\n=\n\nextreme\n\nBag OT клещей\n\nдля обработки\nодежды"
    cleaned = _clean_snippet(raw)
    assert cleaned == "extreme Bag OT клещей для обработки одежды"


def test_clean_snippet_keeps_normal_text():
    raw = "Warp отдали в Open Source\n\nЭто тот самый терминал."
    cleaned = _clean_snippet(raw)
    assert cleaned == "Warp отдали в Open Source Это тот самый терминал."


def test_format_hit_uses_placeholder_when_title_is_file_id():
    """Image without caption: title is a file-id, body is OCR noise.
    The result line must still be readable, with '(без подписи)' as
    label so the user can tell where the kind ends and the link begins."""
    note = Note(
        id=2, owner_id=1, tg_chat_id=-100, tg_message_id=484,
        kind="image", title="photo_AQADlhJrG72ZqEt-.jpg",
        content="к\n-\n=\n\nextreme\n\nBag OT клещей",
        created_at=1,
    )
    out = _format_hit(note)
    assert "[image] (без подписи)" in out
    assert "photo_AQADlhJrG72ZqEt" not in out
    assert "к\n-\n=" not in out
    assert "extreme Bag OT клещей" in out


def test_format_hit_omits_snippet_line_when_empty():
    note = Note(
        id=1, owner_id=1, tg_chat_id=-100, tg_message_id=1,
        kind="image", title=None, content="",
        created_at=1,
    )
    out = _format_hit(note)
    lines = out.splitlines()
    # Two lines only: header + link, no trailing empty snippet line.
    assert len(lines) == 2
    assert lines[0].startswith("📌 [image]")
