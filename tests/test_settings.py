import os
import pytest
from src.core import settings as settings_module
from src.core.settings import load_settings

@pytest.fixture(autouse=True)
def _no_dotenv(monkeypatch):
    monkeypatch.setattr(settings_module, "load_dotenv", lambda *a, **kw: None)

def test_load_settings(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1234:abc")
    monkeypatch.setenv("OWNER_TELEGRAM_ID", "999")
    monkeypatch.delenv("SOROKA_OWNER_TZ", raising=False)
    s = load_settings()
    assert s.telegram_bot_token == "1234:abc"
    assert s.owner_telegram_id == 999
    assert s.owner_timezone == "Europe/Moscow"

def test_missing_env_raises(monkeypatch):
    import pytest
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("OWNER_TELEGRAM_ID", raising=False)
    with pytest.raises(RuntimeError):
        load_settings()

def test_non_integer_owner_id_raises(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1234:abc")
    monkeypatch.setenv("OWNER_TELEGRAM_ID", "not-a-number")
    with pytest.raises(RuntimeError, match="must be an integer"):
        load_settings()


def test_invalid_timezone_raises(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1234:abc")
    monkeypatch.setenv("OWNER_TELEGRAM_ID", "999")
    monkeypatch.setenv("SOROKA_OWNER_TZ", "Bogus/Whatever")
    with pytest.raises(RuntimeError, match="not a valid IANA timezone"):
        load_settings()


def test_custom_timezone_accepted(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "1234:abc")
    monkeypatch.setenv("OWNER_TELEGRAM_ID", "999")
    monkeypatch.setenv("SOROKA_OWNER_TZ", "America/New_York")
    s = load_settings()
    assert s.owner_timezone == "America/New_York"
