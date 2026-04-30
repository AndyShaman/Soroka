import sqlite3
import time
from typing import Optional

from src.core.models import Owner, SetupStep

ALLOWED_FIELDS = {
    "jina_api_key", "deepgram_api_key", "openrouter_key",
    "primary_model", "fallback_model",
    "github_token", "github_mirror_repo",
    "vps_host", "vps_user", "inbox_chat_id", "setup_step",
}


def create_or_get_owner(conn: sqlite3.Connection, telegram_id: int) -> Owner:
    conn.execute(
        "INSERT OR IGNORE INTO owners (telegram_id, created_at) VALUES (?, ?)",
        (telegram_id, int(time.time())),
    )
    conn.commit()
    return get_owner(conn, telegram_id)


def get_owner(conn: sqlite3.Connection, telegram_id: int) -> Optional[Owner]:
    cur = conn.execute(
        """SELECT telegram_id, jina_api_key, deepgram_api_key, openrouter_key,
                  primary_model, fallback_model, github_token, github_mirror_repo,
                  vps_host, vps_user, inbox_chat_id, setup_step, created_at
           FROM owners WHERE telegram_id = ?""",
        (telegram_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    fields = (
        "telegram_id jina_api_key deepgram_api_key openrouter_key "
        "primary_model fallback_model github_token github_mirror_repo "
        "vps_host vps_user inbox_chat_id setup_step created_at"
    ).split()
    return Owner(**dict(zip(fields, row)))


def update_owner_field(conn: sqlite3.Connection, telegram_id: int, field: str, value) -> None:
    if field not in ALLOWED_FIELDS:
        raise ValueError(f"unknown field: {field}")
    conn.execute(
        f"UPDATE owners SET {field} = ? WHERE telegram_id = ?",
        (value, telegram_id),
    )
    conn.commit()


def advance_setup_step(conn: sqlite3.Connection, telegram_id: int, step: SetupStep) -> None:
    update_owner_field(conn, telegram_id, "setup_step", step)
