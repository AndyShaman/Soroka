import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    owner_telegram_id: int
    db_path: str


def load_settings() -> Settings:
    load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    owner_str = os.environ.get("OWNER_TELEGRAM_ID", "").strip()
    if not token or not owner_str:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN and OWNER_TELEGRAM_ID must be set in .env"
        )
    return Settings(
        telegram_bot_token=token,
        owner_telegram_id=int(owner_str),
        db_path=os.environ.get("SOROKA_DB_PATH", "/app/data/soroka.db"),
    )
