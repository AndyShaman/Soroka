import sqlite3
import struct


def _serialize(embedding: list[float]) -> bytes:
    if len(embedding) != 1024:
        raise ValueError(f"expected 1024 dims, got {len(embedding)}")
    return struct.pack(f"{len(embedding)}f", *embedding)


def upsert_embedding(conn: sqlite3.Connection, note_id: int, embedding: list[float]) -> None:
    blob = _serialize(embedding)
    conn.execute("DELETE FROM notes_vec WHERE note_id = ?", (note_id,))
    conn.execute(
        "INSERT INTO notes_vec (note_id, embedding) VALUES (?, ?)",
        (note_id, blob),
    )
    conn.commit()


def search_similar(conn: sqlite3.Connection, query_embedding: list[float],
                   limit: int = 30) -> list[tuple[int, float]]:
    blob = _serialize(query_embedding)
    cur = conn.execute(
        """SELECT note_id, distance FROM notes_vec
           WHERE embedding MATCH ? AND k = ? ORDER BY distance""",
        (blob, limit),
    )
    return [(row[0], row[1]) for row in cur.fetchall()]
