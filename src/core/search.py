import logging
import sqlite3
from typing import Optional

from src.core.llm_json import parse_loose_json
from src.core.notes import get_note
from src.core.vec import search_similar
from src.core.models import Note

logger = logging.getLogger(__name__)

# Probed empirically on Jina v3 1024-dim embeddings against Russian notes:
# direct match ≈ 0.7-1.0, semantically related ≈ 1.0-1.25, unrelated ≥ 1.3.
# 1.25 keeps "биотех → биохакер" (1.20) and cuts unrelated notes (1.33+).
VEC_DISTANCE_MAX = 1.25


async def hybrid_search(conn: sqlite3.Connection, *, jina, owner_id: int,
                        clean_query: str, kind: Optional[str],
                        limit: int = 15) -> list[Note]:
    bm25_ids = _bm25(conn, owner_id, clean_query, kind, k=30)
    embedding = await jina.embed(clean_query, role="query")
    vec_pairs = search_similar(conn, embedding, limit=30)
    vec_ids = [nid for nid, dist in vec_pairs if dist <= VEC_DISTANCE_MAX]
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


RERANK_PROMPT = """Ты — реранкер результатов поиска для личной базы знаний.
Запрос: {query}

Кандидаты (id и фрагмент):
{candidates}

Верни JSON-массив id в порядке релевантности (сначала самый релевантный),
не больше {top_k} элементов. Пример: [12, 5, 8].
Если ни один не релевантен — верни пустой массив [].
ТОЛЬКО JSON, ничего больше.
"""


async def rerank(openrouter, primary: str, fallback: Optional[str],
                 query: str, candidates: list[Note], top_k: int = 5) -> list[Note]:
    if not candidates:
        return []

    blocks = "\n\n".join(
        f"id={n.id}: {(n.title or '')[:80]}\n{n.content[:300]}"
        for n in candidates
    )
    try:
        raw = await openrouter.complete(
            primary=primary, fallback=fallback,
            messages=[{"role": "user", "content": RERANK_PROMPT.format(
                query=query, candidates=blocks, top_k=top_k,
            )}],
            max_tokens=200,
        )
        ids = parse_loose_json(raw)
        if not isinstance(ids, list):
            raise ValueError(f"expected JSON array, got {type(ids).__name__}")
    except Exception as e:
        logger.warning("rerank failed (%s); using hybrid order", e)
        return candidates[:top_k]

    by_id = {n.id: n for n in candidates}
    ordered = [by_id[i] for i in ids if i in by_id]
    return ordered[:top_k]
