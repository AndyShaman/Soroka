import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

DEFAULT_OWNER_TZ = "Europe/Moscow"


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    owner_telegram_id: int
    db_path: str
    owner_timezone: str


def load_settings() -> Settings:
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    owner_str = os.environ.get("OWNER_TELEGRAM_ID", "").strip()
    if not token or not owner_str:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN and OWNER_TELEGRAM_ID must be set in .env"
        )
    try:
        owner_id = int(owner_str)
    except ValueError:
        raise RuntimeError(
            f"OWNER_TELEGRAM_ID must be an integer, got {owner_str!r}"
        ) from None
    tz_name = os.environ.get("SOROKA_OWNER_TZ", DEFAULT_OWNER_TZ).strip() or DEFAULT_OWNER_TZ
    try:
        ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        raise RuntimeError(
            f"SOROKA_OWNER_TZ={tz_name!r} is not a valid IANA timezone "
            f"(e.g. Europe/Moscow, America/New_York)."
        ) from None
    return Settings(
        telegram_bot_token=token,
        owner_telegram_id=owner_id,
        db_path=os.environ.get("SOROKA_DB_PATH", "/app/data/soroka.db"),
        owner_timezone=tz_name,
    )
