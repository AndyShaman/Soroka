"""Unit tests for src/core/sibling_index — the comment+forward pair
indexing helper. Spec: docs/superpowers/specs/2026-05-06-comment-forward-pair-design.md."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.core.db import open_db, init_schema
from src.core.notes import insert_note
from src.core.owners import create_or_get_owner
from src.core.models import Note
from src.core import sibling_index


def _setup(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    return conn


def _mk(owner_id, msg_id, content, *, created_at=1000):
    return Note(
        owner_id=owner_id, tg_message_id=msg_id, tg_chat_id=-1001,
        kind="text", title=None, content=content, raw_caption=None,
        created_at=created_at, thin_content=False,
    )


def test_is_forward_true_for_forward_origin():
    m = MagicMock(forward_origin=MagicMock(), forward_from_chat=None)
    assert sibling_index.is_forward(m) is True


def test_is_forward_true_for_forward_from_chat():
    m = MagicMock(forward_origin=None, forward_from_chat=MagicMock(id=-100123))
    assert sibling_index.is_forward(m) is True


def test_is_forward_false_for_plain_text():
    m = MagicMock(forward_origin=None, forward_from_chat=None)
    assert sibling_index.is_forward(m) is False


@pytest.mark.asyncio
async def test_reindex_pair_combines_fts_content(tmp_path):
    """After reindex_pair, an FTS query for a token only in B's text
    should also surface A — because B's text is now in A's FTS row."""
    conn = _setup(tmp_path)
    a = insert_note(conn, _mk(42, 1, "это про агентов лучшие решения"))
    b = insert_note(conn, _mk(42, 2, "Anthropic запретил подписку в сторонних агентах"))

    jina = MagicMock()
    jina.embed = AsyncMock(return_value=[0.1] * 1024)

    await sibling_index.reindex_pair(
        conn, jina=jina, note_a_id=a, note_b_id=b,
    )

    rowids = {r[0] for r in conn.execute(
        "SELECT rowid FROM notes_fts WHERE notes_fts MATCH ?",
        ('"Anthropic"',),
    ).fetchall()}
    assert a in rowids and b in rowids, (
        "after reindex, both notes should match the forward-only token"
    )

    rowids = {r[0] for r in conn.execute(
        "SELECT rowid FROM notes_fts WHERE notes_fts MATCH ?",
        ('"лучшие" "решения"',),
    ).fetchall()}
    assert a in rowids and b in rowids, (
        "after reindex, both notes should match the comment-only tokens"
    )


@pytest.mark.asyncio
async def test_reindex_pair_idempotent(tmp_path):
    conn = _setup(tmp_path)
    a = insert_note(conn, _mk(42, 1, "alpha"))
    b = insert_note(conn, _mk(42, 2, "beta"))

    jina = MagicMock()
    jina.embed = AsyncMock(return_value=[0.0] * 1024)

    for _ in range(3):
        await sibling_index.reindex_pair(
            conn, jina=jina, note_a_id=a, note_b_id=b,
        )

    rowids = sorted(r[0] for r in conn.execute(
        "SELECT rowid FROM notes_fts WHERE notes_fts MATCH ?",
        ('"alpha"',),
    ).fetchall())
    assert rowids == sorted([a, b])


@pytest.mark.asyncio
async def test_reindex_pair_survives_embed_error(tmp_path):
    """A Jina rate-limit must not abort the FTS half. We need that
    half-success because dense alone still helps via RRF."""
    conn = _setup(tmp_path)
    a = insert_note(conn, _mk(42, 1, "alpha"))
    b = insert_note(conn, _mk(42, 2, "beta"))

    jina = MagicMock()
    jina.embed = AsyncMock(side_effect=RuntimeError("rate limit"))

    await sibling_index.reindex_pair(
        conn, jina=jina, note_a_id=a, note_b_id=b,
    )

    rowids = {r[0] for r in conn.execute(
        "SELECT rowid FROM notes_fts WHERE notes_fts MATCH ?",
        ('"beta"',),
    ).fetchall()}
    assert a in rowids


@pytest.mark.asyncio
async def test_reindex_pair_skips_missing_note(tmp_path):
    """If note_a_id was deleted between scheduling and execution,
    the helper must not crash. The surviving half stays valid."""
    conn = _setup(tmp_path)
    a = insert_note(conn, _mk(42, 1, "alpha"))
    b = insert_note(conn, _mk(42, 2, "beta"))

    conn.execute("DELETE FROM notes WHERE id = ?", (a,))
    conn.commit()

    jina = MagicMock()
    jina.embed = AsyncMock(return_value=[0.0] * 1024)

    # Should not raise even though note a is gone.
    await sibling_index.reindex_pair(
        conn, jina=jina, note_a_id=a, note_b_id=b,
    )

    # b can still be found by its own token (FTS row not corrupted).
    rowids = {r[0] for r in conn.execute(
        "SELECT rowid FROM notes_fts WHERE notes_fts MATCH ?",
        ('"beta"',),
    ).fetchall()}
    assert b in rowids
