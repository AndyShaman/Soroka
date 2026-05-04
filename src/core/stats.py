"""Aggregate stats over the owner's notes. Surface for /stats in the bot
and the matching MCP tool."""
import sqlite3
import time
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Stats:
    total: int
    last_day: int
    last_week: int
    last_month: int
    by_kind: dict[str, int]      # only kinds with count > 0, sorted desc by count
    oldest_at: Optional[int]     # epoch sec, None if total == 0
    newest_at: Optional[int]     # epoch sec, None if total == 0


def compute_stats(conn: sqlite3.Connection, owner_id: int) -> Stats:
    now = int(time.time())
    DAY = 86400
    WEEK = 7 * DAY
    MONTH = 30 * DAY

    base_where = "WHERE owner_id = ? AND deleted_at IS NULL"

    total = conn.execute(
        f"SELECT count(*) FROM notes {base_where}", (owner_id,),
    ).fetchone()[0]

    if total == 0:
        return Stats(0, 0, 0, 0, {}, None, None)

    def _count_since(seconds_ago: int) -> int:
        return conn.execute(
            f"SELECT count(*) FROM notes {base_where} AND created_at >= ?",
            (owner_id, now - seconds_ago),
        ).fetchone()[0]

    last_day = _count_since(DAY)
    last_week = _count_since(WEEK)
    last_month = _count_since(MONTH)

    rows = conn.execute(
        f"SELECT kind, count(*) AS n FROM notes {base_where} "
        f"GROUP BY kind HAVING n > 0 ORDER BY n DESC, kind ASC",
        (owner_id,),
    ).fetchall()
    by_kind = {kind: n for kind, n in rows}

    oldest_at, newest_at = conn.execute(
        f"SELECT MIN(created_at), MAX(created_at) FROM notes {base_where}",
        (owner_id,),
    ).fetchone()

    return Stats(
        total=total,
        last_day=last_day,
        last_week=last_week,
        last_month=last_month,
        by_kind=by_kind,
        oldest_at=oldest_at,
        newest_at=newest_at,
    )
