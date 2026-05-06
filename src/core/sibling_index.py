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
    note_a_id: int, note_b_id: int,
) -> None:
    """Mutually inject sibling text into FTS and embedding for both notes.

    Reads each note's stored `content` from `notes` so that the merge
    uses the post-extraction body (e.g. a web page's extracted article
    text rather than the bare URL the user posted).

    Best-effort: failure of either half is logged but never raised.
    A Jina rate-limit shouldn't kill the FTS half — dense and BM25 are
    independent retrieval signals and either one alone still helps RRF
    surface the right notes."""
    a = _read_note_text(conn, note_a_id)
    b = _read_note_text(conn, note_b_id)
    if a is None and b is None:
        return  # both vanished; nothing to do

    text_a = (a[0] if a else "") or ""
    text_b = (b[0] if b else "") or ""
    sum_a = (a[1] if a else "") or ""
    sum_b = (b[1] if b else "") or ""

    combined_a = f"{text_a}\n\n{text_b}".strip()
    combined_b = f"{text_b}\n\n{text_a}".strip()

    # FTS stays content-only — ru_summary lives outside the BM25 index by
    # design (no trigger covers it). The dense embedding gets both sides'
    # summaries so RU queries can recover foreign-language paired notes.
    _reindex_fts(conn, note_a_id, combined_a)
    _reindex_fts(conn, note_b_id, combined_b)

    summaries = "\n\n".join(s for s in (sum_a, sum_b) if s)
    embed_a = f"{combined_a}\n\n{summaries}".strip() if summaries else combined_a
    embed_b = f"{combined_b}\n\n{summaries}".strip() if summaries else combined_b

    for note_id, embed_text in ((note_a_id, embed_a), (note_b_id, embed_b)):
        if not embed_text:
            continue
        try:
            embedding = await jina.embed(embed_text[:8000], role="passage")
            upsert_embedding(conn, note_id, embedding)
        except Exception:
            logger.exception("sibling reindex: embed for note=%s failed", note_id)

    logger.info("sibling pair reindexed: a=%s b=%s", note_a_id, note_b_id)


def _read_note_text(conn: sqlite3.Connection, note_id: int) -> tuple[str, str] | None:
    """Return (content, ru_summary) for a note, or None if it vanished.

    ru_summary may be NULL in the DB; we surface it as an empty string
    so callers can concat unconditionally.
    """
    row = conn.execute(
        "SELECT content, ru_summary FROM notes WHERE id = ?", (note_id,),
    ).fetchone()
    if row is None:
        return None
    return (row[0] or "", row[1] or "")


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
