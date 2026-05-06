"""Comment + forward pair indexing.

When the channel owner posts a short comment and immediately forwards
another post (within ~2 s), the two messages are semantically one
thought but Telegram delivers them as two independent channel posts.
This module provides the mechanic for mutually injecting each side's
text into the other's FTS row and Jina embedding so search can hop
between them by either side's vocabulary.

Spec: docs/superpowers/specs/2026-05-06-comment-forward-pair-design.md
"""
from __future__ import annotations

import logging
import sqlite3

from src.core.vec import upsert_embedding

logger = logging.getLogger(__name__)


def is_forward(msg) -> bool:
    """Channel post is a forward when Telegram populated either
    forward_origin (modern) or forward_from_chat (legacy). Either is
    enough — both indicate the body originated elsewhere."""
    if getattr(msg, "forward_origin", None) is not None:
        return True
    if getattr(msg, "forward_from_chat", None) is not None:
        return True
    return False


async def reindex_pair(
    conn: sqlite3.Connection, *, jina,
    note_a_id: int, text_a: str,
    note_b_id: int, text_b: str,
) -> None:
    """Mutually inject sibling text into FTS and embedding for both notes.

    Best-effort: failure of either half is logged but never raised.
    A Jina rate-limit shouldn't kill the FTS half — dense and BM25 are
    independent retrieval signals and either one alone still helps RRF
    surface the right notes."""
    combined_a = f"{text_a}\n\n{text_b}".strip()
    combined_b = f"{text_b}\n\n{text_a}".strip()

    _reindex_fts(conn, note_a_id, combined_a)
    _reindex_fts(conn, note_b_id, combined_b)

    for note_id, combined in ((note_a_id, combined_a), (note_b_id, combined_b)):
        try:
            embedding = await jina.embed(combined[:8000], role="passage")
            upsert_embedding(conn, note_id, embedding)
        except Exception:
            logger.exception("sibling reindex: embed for note=%s failed", note_id)

    logger.info("sibling pair reindexed: a=%s b=%s", note_a_id, note_b_id)


def _reindex_fts(conn: sqlite3.Connection, note_id: int, combined: str) -> None:
    """Replace this note's FTS row so `content` becomes `combined`.

    notes_fts is an external-content FTS5 table, so the 'delete'
    command form needs the old row's stored values verbatim. We pull
    them from notes; if the note was concurrently deleted we silently
    skip — there is nothing to reindex."""
    row = conn.execute(
        "SELECT title, content, raw_caption FROM notes WHERE id = ?",
        (note_id,),
    ).fetchone()
    if row is None:
        return
    old_title, old_content, old_raw = row
    conn.execute(
        "INSERT INTO notes_fts(notes_fts, rowid, title, content, raw_caption) "
        "VALUES ('delete', ?, ?, ?, ?)",
        (note_id, old_title, old_content, old_raw),
    )
    conn.execute(
        "INSERT INTO notes_fts(rowid, title, content, raw_caption) "
        "VALUES (?, ?, ?, ?)",
        (note_id, old_title, combined, old_raw),
    )
    conn.commit()
