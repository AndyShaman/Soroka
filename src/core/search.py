import logging
import sqlite3
import time
from typing import Optional
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

from src.core.llm_json import parse_loose_json
from src.core.notes import get_note
from src.core.vec import search_similar
from src.core.models import Note

logger = logging.getLogger(__name__)

# Probed empirically on Jina v3 1024-dim embeddings against Russian notes:
# direct match ≈ 0.7-1.0, semantically related ≈ 1.0-1.25, unrelated ≥ 1.3.
# 1.25 keeps "биотех → биохакер" (1.20) and cuts unrelated notes (1.33+).
VEC_DISTANCE_MAX = 1.25

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "yclid", "ref",
}


def _normalize_url(url: Optional[str]) -> Optional[str]:
    """Normalize a URL for source-deduplication purposes only.
    Lowercases scheme+host, strips tracking params, drops trailing slash
    on path. NEVER use this for actual fetching — it loses information."""
    if not url:
        return None
    try:
        p = urlparse(url.strip())
    except Exception:
        return url
    scheme = (p.scheme or "https").lower()
    netloc = p.netloc.lower()
    path = p.path.rstrip("/") or ""
    qs = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
          if k.lower() not in _TRACKING_PARAMS]
    return urlunparse((scheme, netloc, path, "", urlencode(qs), ""))


def _diversify_by_source(notes: list[Note], max_per_url: int = 2) -> list[Note]:
    """After RRF, cap how many results we keep per normalized source URL.
    Notes without a source_url (plain text, voice) bypass the cap because
    they are inherently distinct."""
    seen: dict[str, int] = {}
    out: list[Note] = []
    for n in notes:
        key = _normalize_url(n.source_url)
        if key is None:
            out.append(n)
            continue
        if seen.get(key, 0) >= max_per_url:
            continue
        seen[key] = seen.get(key, 0) + 1
        out.append(n)
    return out


async def hybrid_search(conn: sqlite3.Connection, *, jina, owner_id: int,
                        clean_query: str, kind: Optional[str],
                        limit: int = 15,
                        since_days: Optional[int] = None,
                        exclude_ids: Optional[list[int]] = None,
                        offset: int = 0,
                        include_thin: bool = False) -> list[Note]:
    """Hybrid BM25 + dense search with filters and source diversification.

    since_days   : only notes created within N days of now
    exclude_ids  : note IDs to drop (used by 'exclude' navigation)
    offset       : how many top results to skip after diversification
    include_thin : whether to include extractor-flagged thin_content notes
                   (default False — thin notes are functionally empty)
    """
    bm25_ids = _bm25(conn, owner_id, clean_query, kind, k=30,
                     since_days=since_days, include_thin=include_thin)
    embedding = await jina.embed(clean_query, role="query")
    vec_pairs = search_similar(conn, embedding, limit=30)
    vec_ids = [nid for nid, dist in vec_pairs if dist <= VEC_DISTANCE_MAX]
    fused = _rrf(bm25_ids, vec_ids)

    excl = set(exclude_ids or [])
    notes: list[Note] = []
    for nid in fused:
        if nid in excl:
            continue
        n = get_note(conn, nid)
        if n is None:
            continue
        if n.owner_id != owner_id:
            continue
        if kind and n.kind != kind:
            continue
        if not include_thin and n.thin_content:
            continue
        if since_days is not None:
            cutoff = int(time.time()) - since_days * 86400
            if n.created_at < cutoff:
                continue
        notes.append(n)

    diversified = _diversify_by_source(notes, max_per_url=2)
    return diversified[offset:offset + limit]


def _bm25(conn: sqlite3.Connection, owner_id: int,
          query: str, kind: Optional[str], k: int,
          since_days: Optional[int] = None,
          include_thin: bool = False) -> list[int]:
    sql = """SELECT n.id
             FROM notes_fts
             JOIN notes n ON n.id = notes_fts.rowid
             WHERE notes_fts MATCH ? AND n.owner_id = ?
               AND n.deleted_at IS NULL"""
    params: list = [_sanitize_fts(query), owner_id]
    if kind:
        sql += " AND n.kind = ?"
        params.append(kind)
    if not include_thin:
        sql += " AND COALESCE(n.thin_content, 0) = 0"
    if since_days is not None:
        sql += " AND n.created_at >= ?"
        params.append(int(time.time()) - since_days * 86400)
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
