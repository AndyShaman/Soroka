import os
from src.core.settings import load_settings

def test_load_settings(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1234:abc")
    monkeypatch.setenv("OWNER_TELEGRAM_ID", "999")
    s = load_settings()
    assert s.telegram_bot_token == "1234:abc"
    assert s.owner_telegram_id == 999

def test_missing_env_raises(monkeypatch):
    import pytest
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("OWNER_TELEGRAM_ID", raising=False)
    with pytest.raises(RuntimeError):
        load_settings()
