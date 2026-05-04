import time

import pytest

from src.core.db import open_db, init_schema
from src.core.owners import create_or_get_owner
from src.core.stats import compute_stats, Stats


def _insert_note(conn, *, id, owner_id, kind="post", chat_id=-100, msg_id=None,
                 created_at=None, deleted_at=None, thin=0,
                 title=None, content="c"):
    msg_id = msg_id if msg_id is not None else id
    created_at = created_at if created_at is not None else int(time.time())
    conn.execute(
        """INSERT INTO notes (id, owner_id, tg_message_id, tg_chat_id, kind,
                              title, content, created_at, thin_content, deleted_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (id, owner_id, msg_id, chat_id, kind, title, content,
         created_at, thin, deleted_at),
    )
    conn.commit()


@pytest.fixture
def conn(tmp_path):
    c = open_db(str(tmp_path / "x.db"))
    init_schema(c)
    create_or_get_owner(c, telegram_id=42)
    return c


def test_compute_stats_empty_db(conn):
    s = compute_stats(conn, owner_id=42)
    assert s == Stats(
        total=0, last_day=0, last_week=0, last_month=0,
        by_kind={}, oldest_at=None, newest_at=None,
    )


def test_compute_stats_total_excludes_deleted(conn):
    _insert_note(conn, id=1, owner_id=42)
    _insert_note(conn, id=2, owner_id=42, deleted_at=int(time.time()))
    s = compute_stats(conn, owner_id=42)
    assert s.total == 1


def test_compute_stats_isolates_owner(conn):
    create_or_get_owner(conn, telegram_id=99)
    _insert_note(conn, id=1, owner_id=42)
    _insert_note(conn, id=2, owner_id=99)
    _insert_note(conn, id=3, owner_id=99)
    s = compute_stats(conn, owner_id=42)
    assert s.total == 1


def test_compute_stats_time_windows(conn):
    now = int(time.time())
    DAY = 86400
    _insert_note(conn, id=1, owner_id=42, created_at=now - 100)              # last day
    _insert_note(conn, id=2, owner_id=42, created_at=now - 3 * DAY)          # last week, not last day
    _insert_note(conn, id=3, owner_id=42, created_at=now - 20 * DAY)         # last month, not last week
    _insert_note(conn, id=4, owner_id=42, created_at=now - 60 * DAY)         # older than month
    s = compute_stats(conn, owner_id=42)
    assert s.total == 4
    assert s.last_day == 1
    assert s.last_week == 2
    assert s.last_month == 3


def test_compute_stats_by_kind_only_nonzero_sorted_desc(conn):
    for i in range(1, 6):
        _insert_note(conn, id=i, owner_id=42, kind="post")
    for i in range(6, 8):
        _insert_note(conn, id=i, owner_id=42, kind="voice")
    _insert_note(conn, id=8, owner_id=42, kind="pdf")
    s = compute_stats(conn, owner_id=42)
    assert s.by_kind == {"post": 5, "voice": 2, "pdf": 1}


def test_compute_stats_oldest_newest_only_active(conn):
    now = int(time.time())
    _insert_note(conn, id=1, owner_id=42, created_at=1_700_000_000)
    _insert_note(conn, id=2, owner_id=42, created_at=1_800_000_000)
    _insert_note(conn, id=3, owner_id=42, created_at=1_500_000_000,
                 deleted_at=now)
    s = compute_stats(conn, owner_id=42)
    assert s.oldest_at == 1_700_000_000
    assert s.newest_at == 1_800_000_000
