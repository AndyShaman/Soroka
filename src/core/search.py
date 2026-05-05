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
# direct match ≈ 0.7-1.0, semantically related ≈ 1.0-1.4, unrelated ≥ 1.45.
# Raised from 1.25 to 1.4 after tests/eval/run_eval showed semantic queries
# without token overlap ("здоровое питание", "спорт") losing recall when
# relevant docs sat in the 1.25-1.4 band. The wider net relies on the
# strict rerank prompt below to drop weakly-related candidates instead of
# padding the top-K — measured trade-off: recall +5, precision flat.
VEC_DISTANCE_MAX = 1.4

RRF_K = 60
W_BM25 = 0.4
W_VEC = 0.4
W_RECENCY = 0.2
RECENCY_HALFLIFE_DAYS = 180


def _rrf_score(rank: int, k: int = RRF_K) -> float:
    return 1.0 / (k + rank + 1)


def _recency_score(created_at: int, now: int) -> float:
    """Smooth decay so a 6-month-old note has half the boost of a fresh one.
    Hardcoded vs configurable: keep it static until eval suite shows we
    need to tune it. recency_score in [0, 1]."""
    age_days = max(0, (now - created_at) / 86400)
    return 1.0 / (1.0 + age_days / RECENCY_HALFLIFE_DAYS)


def _fuse_with_recency(conn: sqlite3.Connection,
                       bm25_ids: list[int], vec_ids: list[int],
                       now: int) -> list[int]:
    """Combine BM25 + dense via RRF, then add a recency component
    weighted at 0.2. Returns ids sorted by combined score desc."""
    scores: dict[int, float] = {}
    for rank, nid in enumerate(bm25_ids):
        scores[nid] = scores.get(nid, 0.0) + W_BM25 * _rrf_score(rank)
    for rank, nid in enumerate(vec_ids):
        scores[nid] = scores.get(nid, 0.0) + W_VEC * _rrf_score(rank)
    if scores:
        placeholders = ",".join("?" * len(scores))
        rows = conn.execute(
            f"SELECT id, created_at FROM notes WHERE id IN ({placeholders})",
            list(scores.keys()),
        ).fetchall()
        for nid, created_at in rows:
            scores[nid] = scores.get(nid, 0.0) + W_RECENCY * _recency_score(created_at, now)
    return [nid for nid, _ in sorted(scores.items(), key=lambda x: -x[1])]

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
                        include_thin: bool = False,
                        created_after: Optional[int] = None,
                        created_before: Optional[int] = None) -> list[Note]:
    """Hybrid BM25 + dense search with filters and source diversification.

    since_days   : only notes created within N days of now
    exclude_ids  : note IDs to drop (used by 'exclude' navigation)
    offset       : how many top results to skip after diversification
    include_thin : whether to include extractor-flagged thin_content notes
                   (default False — thin notes are functionally empty)
    """
    bm25_ids = _bm25(conn, owner_id, clean_query, kind, k=30,
                     since_days=since_days, include_thin=include_thin,
                     created_after=created_after, created_before=created_before)
    embedding = await jina.embed(clean_query, role="query")
    vec_pairs = search_similar(conn, embedding, limit=30)
    vec_ids = [nid for nid, dist in vec_pairs if dist <= VEC_DISTANCE_MAX]
    now = int(time.time())
    fused = _fuse_with_recency(conn, bm25_ids, vec_ids, now)

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
            cutoff = now - since_days * 86400
            if n.created_at < cutoff:
                continue
        if created_after is not None and n.created_at < created_after:
            continue
        if created_before is not None and n.created_at > created_before:
            continue
        notes.append(n)

    diversified = _diversify_by_source(notes, max_per_url=2)
    return diversified[offset:offset + limit]


def _bm25(conn: sqlite3.Connection, owner_id: int,
          query: str, kind: Optional[str], k: int,
          since_days: Optional[int] = None,
          include_thin: bool = False,
          created_after: Optional[int] = None,
          created_before: Optional[int] = None) -> list[int]:
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
    if created_after is not None:
        sql += " AND n.created_at >= ?"
        params.append(created_after)
    if created_before is not None:
        sql += " AND n.created_at <= ?"
        params.append(created_before)
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

Верни JSON-массив id ТОЛЬКО реально релевантных кандидатов в порядке
убывания релевантности (сначала самый релевантный). Не больше {top_k}.

Важно:
- Не дополняй список до {top_k} слабо-связанными кандидатами. Лучше
  вернуть 2 действительно релевантных, чем 5 с тремя "почти подходит".
- Релевантный = напрямую отвечает на запрос или содержит запрашиваемое
  понятие. Тематически похожее, но не отвечающее запросу — НЕ релевантно.
- Если ни один кандидат не релевантен — верни пустой массив [].

ТОЛЬКО JSON, ничего больше. Пример: [12, 5, 8] или [].
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
