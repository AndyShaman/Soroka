import asyncio
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock

from src.bot.handlers import media_group
from src.core.db import open_db, init_schema
from src.core.owners import (
    create_or_get_owner, advance_setup_step, update_owner_field,
)
from src.core.attachments import list_attachments


def _make_msg(chat_id: int, msg_id: int, mgid: str, caption=None):
    m = MagicMock()
    m.chat.id = chat_id
    m.message_id = msg_id
    m.media_group_id = mgid
    m.caption = caption
    return m


def _make_album_msg(chat_id, msg_id, mgid, file_unique_id,
                    caption=None, file_size=2048):
    m = MagicMock()
    m.chat.id = chat_id
    m.message_id = msg_id
    m.media_group_id = mgid
    m.caption = caption
    m.text = None
    m.voice = None
    m.document = None
    m.date.timestamp.return_value = 1700000000
    photo = MagicMock()
    photo.file_id = f"fid-{file_unique_id}"
    photo.file_unique_id = file_unique_id
    photo.file_size = file_size
    m.photo = [photo]
    return m


def _setup_db(tmp_path):
    conn = open_db(str(tmp_path / "x.db"))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=42)
    advance_setup_step(conn, 42, "done")
    update_owner_field(conn, 42, "inbox_chat_id", -1001234)
    return conn


@pytest.mark.asyncio
async def test_buffer_accumulates_messages_with_same_mgid():
    """Two messages with the same media_group_id land in the same bucket."""
    media_group._reset_for_tests()
    flush_calls = []

    async def flush(msgs, ctx):
        flush_calls.append(list(msgs))

    ctx = MagicMock()
    msg1 = _make_msg(chat_id=10, msg_id=1, mgid="abc", caption="hello")
    msg2 = _make_msg(chat_id=10, msg_id=2, mgid="abc")

    await media_group.buffer_message(msg1, ctx, flush_callback=flush, delay=0.05)
    await media_group.buffer_message(msg2, ctx, flush_callback=flush, delay=0.05)

    await asyncio.sleep(0.1)

    assert len(flush_calls) == 1
    assert {m.message_id for m in flush_calls[0]} == {1, 2}


@pytest.mark.asyncio
async def test_timer_resets_when_new_message_arrives():
    """Each new message of the same group resets the flush countdown,
    so a slow album doesn't get split. The flush should fire only after
    quiescence — one logical event, not one per message."""
    media_group._reset_for_tests()
    flush_calls = []

    async def flush(msgs, ctx):
        flush_calls.append(len(msgs))

    ctx = MagicMock()
    delay = 0.1

    for i in range(1, 4):
        await media_group.buffer_message(
            _make_msg(chat_id=10, msg_id=i, mgid="x"), ctx,
            flush_callback=flush, delay=delay,
        )
        await asyncio.sleep(delay / 2)

    assert flush_calls == []
    await asyncio.sleep(delay * 1.5)
    assert flush_calls == [3]


@pytest.mark.asyncio
async def test_two_groups_are_independent():
    """Different media_group_ids → independent buckets, independent flushes."""
    media_group._reset_for_tests()
    flush_calls = []

    async def flush(msgs, ctx):
        flush_calls.append(msgs[0].media_group_id)

    ctx = MagicMock()

    await media_group.buffer_message(
        _make_msg(chat_id=10, msg_id=1, mgid="a"), ctx,
        flush_callback=flush, delay=0.05,
    )
    await media_group.buffer_message(
        _make_msg(chat_id=10, msg_id=99, mgid="b"), ctx,
        flush_callback=flush, delay=0.05,
    )
    await asyncio.sleep(0.15)

    assert sorted(flush_calls) == ["a", "b"]


def test_pick_anchor_uses_smallest_message_id():
    """Anchor is the smallest message_id — deterministic regardless of
    the order Telegram delivered them in. We need a single anchor because
    notes.tg_message_id has UNIQUE(owner_id, chat_id, tg_message_id)."""
    msgs = [
        _make_msg(chat_id=10, msg_id=12, mgid="x"),
        _make_msg(chat_id=10, msg_id=11, mgid="x"),
        _make_msg(chat_id=10, msg_id=13, mgid="x"),
    ]
    anchor = media_group._pick_anchor(msgs)
    assert anchor.message_id == 11


def test_merged_caption_takes_the_one_thats_set():
    """Telegram puts the post caption on exactly one of the messages in a
    media group. The other messages have caption=None."""
    msgs = [
        _make_msg(chat_id=10, msg_id=1, mgid="x", caption=None),
        _make_msg(chat_id=10, msg_id=2, mgid="x", caption="real text"),
        _make_msg(chat_id=10, msg_id=3, mgid="x", caption=None),
    ]
    assert media_group._merged_caption(msgs) == "real text"


def test_merged_caption_concatenates_if_multiple():
    """Defensive: if Telegram ever delivers more than one caption (it
    doesn't today), join them so we don't silently drop one."""
    msgs = [
        _make_msg(chat_id=10, msg_id=1, mgid="x", caption="one"),
        _make_msg(chat_id=10, msg_id=2, mgid="x", caption="two"),
    ]
    assert media_group._merged_caption(msgs) == "one\n\ntwo"


def test_merged_caption_none_when_no_captions():
    msgs = [_make_msg(chat_id=10, msg_id=1, mgid="x", caption=None)]
    assert media_group._merged_caption(msgs) is None


def test_build_body_caption_first_then_ocr_fragments():
    """Caption dominates the embedding/BM25 because it goes first. OCR
    from each photo is appended as a separate paragraph if it has real
    content (>20 chars after strip)."""
    body = media_group._build_body(
        caption="Главный текст поста",
        ocr_fragments=["Sam Altman: voice models", "noise"],  # 2nd is <20
    )
    assert body.startswith("Главный текст поста")
    assert "Sam Altman: voice models" in body
    assert "noise" not in body  # too short, dropped


def test_build_body_truncates_ocr_per_fragment():
    """500-char cap per photo: a single noisy screenshot can't drown the
    caption when there are 5+ photos in the album."""
    long_ocr = "a" * 1500
    body = media_group._build_body(caption="hi", ocr_fragments=[long_ocr])
    assert body == "hi\n\n" + "a" * 500


def test_build_body_no_caption_uses_ocr_only():
    body = media_group._build_body(
        caption=None,
        ocr_fragments=["enough text here to keep this fragment around"],
    )
    assert body == "enough text here to keep this fragment around"


def test_build_body_empty_when_nothing():
    assert media_group._build_body(caption=None, ocr_fragments=[]) == ""
    assert media_group._build_body(caption="", ocr_fragments=["x"]) == ""


def test_kind_post_when_caption_long():
    """Same threshold as the existing single-photo rule: caption ≥30
    chars OR contains a URL → 'post'; else 'image'."""
    long_caption = "a" * 30
    assert media_group._album_kind(long_caption) == "post"


def test_kind_post_when_caption_has_url():
    assert media_group._album_kind("see https://example.com") == "post"


def test_kind_image_when_caption_short():
    assert media_group._album_kind("котики") == "image"


def test_kind_image_when_no_caption():
    assert media_group._album_kind(None) == "image"
    assert media_group._album_kind("") == "image"


@pytest.mark.asyncio
async def test_flush_album_creates_one_note_with_n_attachments(tmp_path, monkeypatch):
    """Three photos with a caption land as one note (kind=post) with three
    rows in the attachments table."""
    conn = _setup_db(tmp_path)

    settings = MagicMock(owner_telegram_id=42)
    ctx = MagicMock()
    ctx.application.bot_data = {"settings": settings, "conn": conn}
    ctx.bot.set_message_reaction = AsyncMock()

    fake_file = AsyncMock()
    fake_file.download_to_drive = AsyncMock()
    ctx.bot.get_file = AsyncMock(return_value=fake_file)

    monkeypatch.setattr(
        "src.bot.handlers.media_group.PHOTO_DIR_ROOT", tmp_path / "attachments",
    )
    monkeypatch.setattr(
        "src.bot.handlers.media_group.extract_ocr",
        lambda _path: "screenshot text " * 5,
    )
    monkeypatch.setattr(
        "src.bot.handlers.media_group.JinaClient",
        lambda api_key: MagicMock(embed=AsyncMock(return_value=[0.0] * 1024)),
    )
    update_owner_field(conn, 42, "jina_api_key", "fake")
    update_owner_field(conn, 42, "deepgram_api_key", "fake")

    long_caption = "Подборка статей про RAG-системы и эмбеддинги"
    msgs = [
        _make_album_msg(chat_id=-1001234, msg_id=200, mgid="g1",
                         file_unique_id="u1", caption=long_caption),
        _make_album_msg(chat_id=-1001234, msg_id=201, mgid="g1",
                         file_unique_id="u2"),
        _make_album_msg(chat_id=-1001234, msg_id=202, mgid="g1",
                         file_unique_id="u3"),
    ]

    await media_group.flush_album(msgs, ctx)

    rows = conn.execute("SELECT id, kind, content FROM notes").fetchall()
    assert len(rows) == 1
    note_id, kind, content = rows[0]
    assert kind == "post"
    assert content.startswith(long_caption)
    assert "screenshot text" in content

    attachments = list_attachments(conn, note_id)
    assert len(attachments) == 3
    assert {a.original_name for a in attachments} == {
        "photo_u1.jpg", "photo_u2.jpg", "photo_u3.jpg",
    }


@pytest.mark.asyncio
async def test_flush_album_tolerates_failed_download(tmp_path, monkeypatch):
    """One photo's get_file raises; the note still saves with the photos
    that succeeded — better partial than nothing."""
    conn = _setup_db(tmp_path)

    settings = MagicMock(owner_telegram_id=42)
    ctx = MagicMock()
    ctx.application.bot_data = {"settings": settings, "conn": conn}
    ctx.bot.set_message_reaction = AsyncMock()

    fake_file = AsyncMock()
    fake_file.download_to_drive = AsyncMock()

    call_count = {"n": 0}
    async def get_file(_fid):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise RuntimeError("flaky network")
        return fake_file

    ctx.bot.get_file = AsyncMock(side_effect=get_file)
    monkeypatch.setattr(
        "src.bot.handlers.media_group.PHOTO_DIR_ROOT", tmp_path / "attachments",
    )
    monkeypatch.setattr(
        "src.bot.handlers.media_group.extract_ocr", lambda _p: "ok ok ok ok ok ok",
    )
    monkeypatch.setattr(
        "src.bot.handlers.media_group.JinaClient",
        lambda api_key: MagicMock(embed=AsyncMock(return_value=[0.0] * 1024)),
    )
    update_owner_field(conn, 42, "jina_api_key", "fake")

    msgs = [
        _make_album_msg(chat_id=-1001234, msg_id=300, mgid="g2",
                         file_unique_id="a", caption="three photos in this album"),
        _make_album_msg(chat_id=-1001234, msg_id=301, mgid="g2",
                         file_unique_id="b"),
        _make_album_msg(chat_id=-1001234, msg_id=302, mgid="g2",
                         file_unique_id="c"),
    ]

    await media_group.flush_album(msgs, ctx)

    rows = conn.execute("SELECT id FROM notes").fetchall()
    assert len(rows) == 1
    attachments = list_attachments(conn, rows[0][0])
    assert len(attachments) == 2  # one was lost
