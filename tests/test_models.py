# tests/test_models.py
from src.core.models import Owner, Note, Attachment

def test_owner_has_optional_setup_fields():
    o = Owner(telegram_id=1, created_at=1700000000)
    assert o.jina_api_key is None
    assert o.setup_step is None

def test_note_kind_is_validated():
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Note(
            owner_id=1, tg_message_id=1, tg_chat_id=1,
            kind="invalid", content="x", created_at=1,
        )

def test_attachment_default_not_oversized():
    a = Attachment(note_id=1, file_path="x", file_size=1)
    assert a.is_oversized is False
