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


WINDOW_MIN = 1
WINDOW_MAX = 10


def get_context(
    conn: sqlite3.Connection,
    *,
    owner_id: int,
    note_id: int,
    window: int = 3,
) -> list[Note]:
    """Sibling messages around `note_id` in the same Telegram chat.

    Selects active (not soft-deleted) notes in the same `tg_chat_id`
    where `tg_message_id` is within ±window of the source. Excludes the
    source itself. `thin_content` is intentionally NOT filtered — short
    replies and reactions are exactly the kind of context callers want.

    `window` is clamped to [1, 10]. Returns [] for missing or
    cross-owner `note_id`. Sorted ascending by `tg_message_id`.
    """
    window = max(WINDOW_MIN, min(WINDOW_MAX, window))

    src = conn.execute(
        "SELECT tg_chat_id, tg_message_id FROM notes "
        "WHERE id = ? AND owner_id = ? AND deleted_at IS NULL",
        (note_id, owner_id),
    ).fetchone()
    if not src:
        return []
    src_chat, src_msg = src

    cur = conn.execute(
        f"SELECT {_SELECT_NOTE_COLUMNS} FROM notes "
        f"WHERE owner_id = ? AND deleted_at IS NULL "
        f"AND tg_chat_id = ? "
        f"AND tg_message_id BETWEEN ? AND ? "
        f"AND id != ? "
        f"ORDER BY tg_message_id ASC",
        (owner_id, src_chat, src_msg - window, src_msg + window, note_id),
    )
    return [_row_to_note(row) for row in cur.fetchall()]


async def find_similar(
    conn: sqlite3.Connection,
    *,
    owner_id: int,
    note_id: int,
    limit: int = 5,
) -> list[Note]:
    """Vector neighbors of `note_id` within the owner's active notes.

    Excludes the source itself, soft-deleted notes, and thin_content
    notes. Returns at most `limit` notes ordered by ascending vector
    distance. Returns [] if `note_id` has no embedding row, does not
    exist, or belongs to another owner.
    """
    src_row = conn.execute(
        "SELECT embedding FROM notes_vec WHERE note_id = ?",
        (note_id,),
    ).fetchone()
    if not src_row:
        return []
    src_blob = src_row[0]

    # Pull more than we need so we can filter the source/deleted/thin/cross-owner
    # rows out without coming back short.
    k = limit + 5
    cur = conn.execute(
        "SELECT note_id FROM notes_vec WHERE embedding MATCH ? AND k = ? "
        "ORDER BY distance",
        (src_blob, k),
    )
    candidate_ids = [row[0] for row in cur.fetchall() if row[0] != note_id]
    if not candidate_ids:
        return []

    placeholders = ",".join("?" * len(candidate_ids))
    rows = conn.execute(
        f"SELECT {_SELECT_NOTE_COLUMNS} FROM notes "
        f"WHERE owner_id = ? AND deleted_at IS NULL "
        f"AND COALESCE(thin_content, 0) = 0 "
        f"AND id IN ({placeholders})",
        (owner_id, *candidate_ids),
    ).fetchall()
    by_id = {row[0]: _row_to_note(row) for row in rows}
    ordered = [by_id[i] for i in candidate_ids if i in by_id]
    return ordered[:limit]
