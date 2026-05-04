"""Neighbor lookups: similar notes, in-chat context, batch reads.

These are read-only helpers used by both the MCP server (so the agent can
explore the knowledge base) and — eventually — the Telegram bot. Owner
isolation and the soft-delete filter are enforced inside every query;
callers don't have to remember.
"""
import sqlite3

from src.core.models import Note

MAX_BATCH_IDS = 100


_SELECT_NOTE_COLUMNS = (
    "id, owner_id, tg_message_id, tg_chat_id, kind, title, content, "
    "source_url, raw_caption, created_at, COALESCE(thin_content, 0), deleted_at"
)
_NOTE_FIELDS = (
    "id owner_id tg_message_id tg_chat_id kind title content "
    "source_url raw_caption created_at thin_content deleted_at"
).split()


def _row_to_note(row) -> Note:
    data = dict(zip(_NOTE_FIELDS, row))
    data["thin_content"] = bool(data["thin_content"])
    return Note(**data)


def get_by_ids(
    conn: sqlite3.Connection,
    *,
    owner_id: int,
    ids: list[int],
) -> list[Note]:
    """Batch-load active notes by id. Cross-owner / deleted / missing ids are
    silently dropped. Duplicates collapse — each unique id appears at most once
    in the output, at the position of its first occurrence in `ids`. Returns
    notes in input order. Caps input at MAX_BATCH_IDS (100) — raises ValueError
    on overflow before deduplication, so 101 copies of the same id still raise."""
    if not ids:
        return []
    if len(ids) > MAX_BATCH_IDS:
        raise ValueError(f"get_by_ids accepts at most {MAX_BATCH_IDS} ids")

    placeholders = ",".join("?" * len(ids))
    cur = conn.execute(
        f"SELECT {_SELECT_NOTE_COLUMNS} FROM notes "
        f"WHERE owner_id = ? AND deleted_at IS NULL "
        f"AND id IN ({placeholders})",
        (owner_id, *ids),
    )
    by_id = {row[0]: _row_to_note(row) for row in cur.fetchall()}
    seen: set[int] = set()
    result: list[Note] = []
    for i in ids:
        if i in by_id and i not in seen:
            result.append(by_id[i])
            seen.add(i)
    return result
