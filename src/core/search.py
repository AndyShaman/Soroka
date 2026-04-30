import sqlite3
from typing import Optional

from src.core.notes import get_note
from src.core.vec import search_similar
from src.core.models import Note


async def hybrid_search(conn: sqlite3.Connection, *, jina, owner_id: int,
                        clean_query: str, kind: Optional[str],
                        limit: int = 15) -> list[Note]:
    bm25_ids = _bm25(conn, owner_id, clean_query, kind, k=30)
    embedding = await jina.embed(clean_query, role="query")
    vec_pairs = search_similar(conn, embedding, limit=30)
    vec_ids = [pair[0] for pair in vec_pairs]
    fused = _rrf(bm25_ids, vec_ids)[:limit]
    notes = [get_note(conn, nid) for nid in fused]
    notes = [n for n in notes if n and n.owner_id == owner_id]
    if kind:
        notes = [n for n in notes if n.kind == kind]
    return notes[:limit]


def _bm25(conn: sqlite3.Connection, owner_id: int,
          query: str, kind: Optional[str], k: int) -> list[int]:
    sql = """SELECT n.id
             FROM notes_fts
             JOIN notes n ON n.id = notes_fts.rowid
             WHERE notes_fts MATCH ? AND n.owner_id = ?"""
    params: list = [_sanitize_fts(query), owner_id]
    if kind:
        sql += " AND n.kind = ?"
        params.append(kind)
    sql += " ORDER BY rank LIMIT ?"
    params.append(k)
    return [row[0] for row in conn.execute(sql, params).fetchall()]


def _sanitize_fts(query: str) -> str:
    # Quote tokens to avoid FTS5 syntax errors on punctuation.
    tokens = [t for t in query.split() if t]
    return " ".join(f'"{t}"' for t in tokens) or '""'


def _rrf(*ranked_lists: list[int], k: int = 60) -> list[int]:
    scores: dict[int, float] = {}
    for ranked in ranked_lists:
        for rank, doc_id in enumerate(ranked):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return [doc_id for doc_id, _ in sorted(scores.items(), key=lambda x: -x[1])]
