"""Tests for the entity-URL extraction pipeline: Markdown link embeds
(`[Watch](https://...)`) ride along `MessageEntity.text_link`, never
appear in plain text, and used to be lost on ingest. This file pins
the contract that those URLs now reach the DB."""

import json
from unittest.mock import MagicMock

import pytest

from src.bot.handlers.channel import _extract_entity_urls
from src.core.db import open_db, init_schema
from src.core.models import Note
from src.core.notes import get_note, insert_note


def _entity(type_: str, offset: int, length: int, url: str | None = None):
    """A duck-typed stand-in for telegram.MessageEntity that exposes the
    handful of attrs `_extract_entity_urls` reads. Using MagicMock here
    lets the test stay framework-free."""
    ent = MagicMock()
    ent.type = type_
    ent.offset = offset
    ent.length = length
    ent.url = url
    return ent


def _msg(*, text=None, caption=None, entities=None, caption_entities=None):
    msg = MagicMock()
    msg.text = text
    msg.caption = caption
    msg.entities = entities
    msg.caption_entities = caption_entities
    return msg


def test_extracts_text_link_from_text():
    """`[label](URL)` embeds expose `.url` on the entity. The visible text
    has only the label, so URL-detecting extractors miss it — this is the
    case `_extract_entity_urls` exists to fix."""
    msg = _msg(
        text="Look at this article",
        entities=[_entity("text_link", 8, 7, url="https://example.com/a")],
    )
    assert _extract_entity_urls(msg) == ["https://example.com/a"]


def test_extracts_plain_url_entity_from_text():
    """A `type=url` entity has no `.url` field — the URL is a slice of the
    visible text. We capture it too so the column reflects every URL the
    message provably contains."""
    msg = _msg(
        text="Open https://example.com/b please",
        entities=[_entity("url", 5, 21, url=None)],
    )
    assert _extract_entity_urls(msg) == ["https://example.com/b"]


def test_extracts_from_caption_entities_on_media_post():
    """The forwarded-channel-post case from real life: photo + caption,
    URL hidden behind a Markdown embed in the caption (not the text)."""
    msg = _msg(
        caption="📱 Смотреть на YouTube",
        caption_entities=[_entity("text_link", 0, 22, url="https://youtu.be/abc")],
    )
    assert _extract_entity_urls(msg) == ["https://youtu.be/abc"]


def test_text_and_caption_entities_combine_deduped():
    """When both text-level and caption-level entities are present, URLs
    accumulate in document order and duplicates collapse to the first
    occurrence — keeps the column compact and stable."""
    msg = _msg(
        text="A https://one.example",
        entities=[_entity("url", 2, 19)],
        caption="B link",
        caption_entities=[
            _entity("text_link", 2, 4, url="https://two.example"),
            _entity("text_link", 2, 4, url="https://one.example"),  # dup
        ],
    )
    assert _extract_entity_urls(msg) == [
        "https://one.example",
        "https://two.example",
    ]


def test_returns_empty_for_messages_without_entities():
    """No entities at all — the column should stay NULL in the caller
    (channel_handler turns [] into None before passing to ingest)."""
    msg = _msg(text="just words")
    assert _extract_entity_urls(msg) == []


def test_ignores_non_link_entity_types():
    """`bold`, `mention`, `code`, etc. carry no URL — must not leak
    placeholder strings into the column."""
    msg = _msg(
        text="bold mention #tag",
        entities=[
            _entity("bold", 0, 4),
            _entity("mention", 5, 7),
            _entity("hashtag", 13, 4),
        ],
    )
    assert _extract_entity_urls(msg) == []


def test_migration_adds_extracted_urls_column(tmp_path):
    """A fresh DB built via init_schema must expose the new column even
    on first install (not just on a migration from an older one)."""
    db_path = str(tmp_path / "soroka.db")
    conn = open_db(db_path)
    init_schema(conn)
    cols = [row[1] for row in conn.execute("PRAGMA table_info(notes)")]
    assert "extracted_urls" in cols


def test_notes_roundtrip_through_db(tmp_path):
    """Sanity: a Note carrying extracted_urls survives an insert/select
    cycle as a real Python list (not a JSON string and not lost as
    None). Pins the JSON-serialization contract in core.notes."""
    db_path = str(tmp_path / "soroka.db")
    conn = open_db(db_path)
    init_schema(conn)
    # Owner FK target — minimal row, only the column NOT NULL requires.
    conn.execute(
        "INSERT INTO owners (telegram_id, created_at) VALUES (?, ?)",
        (1, 0),
    )
    note = Note(
        owner_id=1, tg_message_id=10, tg_chat_id=-100123, kind="post",
        title="t", content="body", created_at=0,
        extracted_urls=["https://a.example", "https://b.example"],
    )
    note_id = insert_note(conn, note)
    assert note_id is not None
    loaded = get_note(conn, note_id)
    assert loaded is not None
    assert loaded.extracted_urls == [
        "https://a.example", "https://b.example",
    ]


def test_notes_roundtrip_with_no_urls_stays_null(tmp_path):
    """Legacy path: Note.extracted_urls=None must NOT serialize as the
    string `"null"`. The column should remain SQL NULL so older sync
    tooling reading the column gets a Python None back."""
    db_path = str(tmp_path / "soroka.db")
    conn = open_db(db_path)
    init_schema(conn)
    conn.execute(
        "INSERT INTO owners (telegram_id, created_at) VALUES (?, ?)",
        (2, 0),
    )
    note = Note(
        owner_id=2, tg_message_id=11, tg_chat_id=-100123, kind="text",
        title="t", content="body", created_at=0,
    )
    note_id = insert_note(conn, note)
    raw = conn.execute(
        "SELECT extracted_urls FROM notes WHERE id = ?", (note_id,),
    ).fetchone()[0]
    assert raw is None
    loaded = get_note(conn, note_id)
    assert loaded.extracted_urls is None
