import os
import sqlite3
import time
from typing import Optional

from src.core.models import Owner, SetupStep

ALLOWED_FIELDS = {
    "jina_api_key", "deepgram_api_key", "openrouter_key",
    "primary_model", "fallback_model",
    "github_token", "github_mirror_repo",
    "vps_host", "vps_user", "inbox_chat_id", "setup_step",
    "last_backup_at", "last_backup_error", "backup_failure_count",
}


def create_or_get_owner(conn: sqlite3.Connection, telegram_id: int) -> Owner:
    conn.execute(
        "INSERT OR IGNORE INTO owners (telegram_id, created_at) VALUES (?, ?)",
        (telegram_id, int(time.time())),
    )
    conn.commit()
    owner = get_owner(conn, telegram_id)
    assert owner is not None  # row guaranteed to exist after INSERT OR IGNORE
    return owner


def get_owner(conn: sqlite3.Connection, telegram_id: int) -> Optional[Owner]:
    cur = conn.execute(
        """SELECT telegram_id, jina_api_key, deepgram_api_key, openrouter_key,
                  primary_model, fallback_model, github_token, github_mirror_repo,
                  vps_host, vps_user, inbox_chat_id, setup_step,
                  last_backup_at, last_backup_error, backup_failure_count,
                  created_at
           FROM owners WHERE telegram_id = ?""",
        (telegram_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    fields = (
        "telegram_id jina_api_key deepgram_api_key openrouter_key "
        "primary_model fallback_model github_token github_mirror_repo "
        "vps_host vps_user inbox_chat_id setup_step "
        "last_backup_at last_backup_error backup_failure_count created_at"
    ).split()
    values = list(row)
    # backup_failure_count column is non-null in fresh schema but might be
    # NULL on rows created before the migration ran — coerce to 0 so the
    # Pydantic model (which types it as int) doesn't reject the load.
    fc_idx = fields.index("backup_failure_count")
    if values[fc_idx] is None:
        values[fc_idx] = 0
    return Owner(**dict(zip(fields, values)))


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


def record_backup_success(conn: sqlite3.Connection, telegram_id: int,
                           timestamp: str) -> None:
    """Mark a successful nightly backup. Resets the consecutive-failure
    counter so the next failure starts a fresh streak (and the threshold
    DM logic in main.py works as intended)."""
    conn.execute(
        """UPDATE owners
              SET last_backup_at = ?,
                  last_backup_error = NULL,
                  backup_failure_count = 0
            WHERE telegram_id = ?""",
        (timestamp, telegram_id),
    )
    conn.commit()


def record_backup_failure(conn: sqlite3.Connection, telegram_id: int,
                           error: str) -> int:
    """Persist the latest backup error and bump the failure counter.
    Returns the new counter value so the caller can decide whether to
    notify the owner."""
    conn.execute(
        """UPDATE owners
              SET last_backup_error = ?,
                  backup_failure_count = COALESCE(backup_failure_count, 0) + 1
            WHERE telegram_id = ?""",
        (error, telegram_id),
    )
    conn.commit()
    cur = conn.execute(
        "SELECT backup_failure_count FROM owners WHERE telegram_id = ?",
        (telegram_id,),
    )
    row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def reset_backup_failure_count(conn: sqlite3.Connection, telegram_id: int) -> None:
    """Used after a threshold-DM has been delivered so the user gets a
    follow-up DM only after another full window of failures, not on every
    nightly tick."""
    conn.execute(
        "UPDATE owners SET backup_failure_count = 0 WHERE telegram_id = ?",
        (telegram_id,),
    )
    conn.commit()


def seed_vps_from_env(conn: sqlite3.Connection, telegram_id: int) -> None:
    """Populate vps_user/vps_host from SOROKA_VPS_USER/SOROKA_VPS_HOST env vars
    if the user has set them in .env manually. A manual /setvps still wins:
    we only write fields that are currently empty in the DB."""
    user = (os.environ.get("SOROKA_VPS_USER") or "").strip()
    host = (os.environ.get("SOROKA_VPS_HOST") or "").strip()
    if not user or not host:
        return
    owner = get_owner(conn, telegram_id)
    if owner is None:
        return
    if not owner.vps_user:
        update_owner_field(conn, telegram_id, "vps_user", user)
    if not owner.vps_host:
        update_owner_field(conn, telegram_id, "vps_host", host)
