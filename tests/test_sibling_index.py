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


@pytest.mark.asyncio
async def test_reindex_pair_includes_ru_summary_in_embedding(tmp_path):
    """Foreign-language URL paired with a Russian comment: both notes'
    embeddings must include the Russian summary so dense search via RU
    queries surfaces either side of the pair."""
    conn = _setup(tmp_path)
    a = insert_note(conn, _mk(42, 1, "комментарий про статью"))
    b_note = _mk(42, 2, "English article body about LLMs.")
    b_note.ru_summary = "Статья про большие языковые модели."
    b = insert_note(conn, b_note)

    captured: list[str] = []

    async def fake_embed(text, role):
        captured.append(text)
        return [0.0] * 1024

    jina = MagicMock()
    jina.embed = fake_embed

    await sibling_index.reindex_pair(
        conn, jina=jina, note_a_id=a, note_b_id=b,
    )

    # Both embeddings carry the RU summary so either note can be hit by
    # a Russian dense query.
    assert len(captured) == 2
    for embed_text in captured:
        assert "большие языковые модели" in embed_text


@pytest.mark.asyncio
async def test_reindex_pair_persists_sibling_link(tmp_path):
    """After pairing, both notes should record their partner so a later
    soft_delete on either one can rebuild the survivor's FTS row."""
    conn = _setup(tmp_path)
    a = insert_note(conn, _mk(42, 1, "alpha"))
    b = insert_note(conn, _mk(42, 2, "beta"))

    jina = MagicMock()
    jina.embed = AsyncMock(return_value=[0.0] * 1024)

    await sibling_index.reindex_pair(
        conn, jina=jina, note_a_id=a, note_b_id=b,
    )

    rows = dict(conn.execute(
        "SELECT id, sibling_note_id FROM notes WHERE id IN (?, ?)", (a, b)
    ).fetchall())
    assert rows[a] == b
    assert rows[b] == a


def test_soft_delete_clears_sibling_fts_injection(tmp_path):
    """When one half of a pair is soft-deleted, the survivor's FTS row
    must drop the injected text — otherwise BM25 keeps matching the
    survivor on words that came from the deleted partner."""
    import asyncio
    from src.core.notes import soft_delete_note

    conn = _setup(tmp_path)
    a = insert_note(conn, _mk(42, 1, "alpha"))
    b = insert_note(conn, _mk(42, 2, "beta"))

    jina = MagicMock()
    jina.embed = AsyncMock(return_value=[0.0] * 1024)
    asyncio.run(sibling_index.reindex_pair(
        conn, jina=jina, note_a_id=a, note_b_id=b,
    ))

    # Sanity: before delete, b matches "alpha" via injected text.
    pre = {r[0] for r in conn.execute(
        "SELECT rowid FROM notes_fts WHERE notes_fts MATCH ?", ('"alpha"',),
    ).fetchall()}
    assert b in pre

    soft_delete_note(conn, a, reason="test")

    # After delete: b no longer matches the deleted partner's word, and
    # the link was cleared on both sides.
    post = {r[0] for r in conn.execute(
        "SELECT rowid FROM notes_fts WHERE notes_fts MATCH ?", ('"alpha"',),
    ).fetchall()}
    assert b not in post

    rows = dict(conn.execute(
        "SELECT id, sibling_note_id FROM notes WHERE id IN (?, ?)", (a, b)
    ).fetchall())
    assert rows[a] is None
    assert rows[b] is None


def test_soft_delete_ignores_self_referential_sibling(tmp_path):
    """sibling_note_id pointing at the note's own id is corrupt state
    (data invariant break) — soft_delete_note must not feed it to
    rebuild_solo_fts, which would synthesize junk combined text and
    try to delete an FTS row that never existed in that form."""
    from src.core.notes import soft_delete_note

    conn = _setup(tmp_path)
    a = insert_note(conn, _mk(42, 1, "alpha"))
    conn.execute(
        "UPDATE notes SET sibling_note_id = ? WHERE id = ?", (a, a))
    conn.commit()

    # Should soft-delete cleanly without raising on the self-ref.
    assert soft_delete_note(conn, a, reason="test") is True


def test_soft_delete_unpaired_note_is_noop(tmp_path):
    """Notes that were never paired must soft-delete cleanly without
    touching any other rows — sibling_note_id stays NULL across the
    board."""
    from src.core.notes import soft_delete_note

    conn = _setup(tmp_path)
    a = insert_note(conn, _mk(42, 1, "alpha"))
    b = insert_note(conn, _mk(42, 2, "beta"))

    assert soft_delete_note(conn, a, reason="test") is True
    rows = dict(conn.execute(
        "SELECT id, sibling_note_id FROM notes WHERE id IN (?, ?)", (a, b)
    ).fetchall())
    assert rows[a] is None
    assert rows[b] is None


@pytest.mark.asyncio
async def test_reindex_pair_no_summary_keeps_old_behaviour(tmp_path):
    """If neither note has ru_summary, embed text is identical to the
    pre-feature output (content-only combined)."""
    conn = _setup(tmp_path)
    a = insert_note(conn, _mk(42, 1, "alpha text"))
    b = insert_note(conn, _mk(42, 2, "beta text"))

    captured: list[str] = []

    async def fake_embed(text, role):
        captured.append(text)
        return [0.0] * 1024

    jina = MagicMock()
    jina.embed = fake_embed

    await sibling_index.reindex_pair(
        conn, jina=jina, note_a_id=a, note_b_id=b,
    )

    assert captured == ["alpha text\n\nbeta text", "beta text\n\nalpha text"]
