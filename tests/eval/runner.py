"""Bootstrap a fresh SQLite fixture from corpus.py and run queries through
the production pipeline (parse_intent -> hybrid_search -> rerank).

Returns ranked top-K note IDs per query so metrics.py can score them.
The DB is created in a temp dir; embeddings are real Jina API calls.
Every note is embedded once at insert time.
"""
import asyncio
import logging
import sqlite3
import tempfile
import time
from pathlib import Path

from src.adapters.jina import JinaClient
from src.adapters.openrouter import OpenRouterClient
from src.core.db import open_db, init_schema
from src.core.intent import parse_intent
from src.core.models import Note
from src.core.notes import insert_note
from src.core.owners import create_or_get_owner
from src.core.search import hybrid_search, rerank
from src.core.vec import upsert_embedding

from tests.eval.corpus import NOTES
from tests.eval.queries import QUERIES

logger = logging.getLogger(__name__)

OWNER_ID = 1
TG_CHAT_ID = -1001234567890
TOP_K = 5
HYBRID_LIMIT = 20


async def bootstrap_db(jina: JinaClient) -> tuple[sqlite3.Connection, Path, dict[str, int]]:
    """Create a temp SQLite, run schema, insert OWNER + 52 notes, embed
    each note via Jina. Returns (conn, db_path, key_to_note_id)."""
    tmp = Path(tempfile.mkdtemp(prefix="soroka-eval-"))
    db_path = tmp / "eval.db"
    conn = open_db(str(db_path))
    init_schema(conn)
    create_or_get_owner(conn, telegram_id=OWNER_ID)

    now = int(time.time())
    key_to_id: dict[str, int] = {}

    for i, entry in enumerate(NOTES):
        note = Note(
            owner_id=OWNER_ID,
            tg_message_id=i + 1,
            tg_chat_id=TG_CHAT_ID,
            kind=entry["kind"],
            title=entry.get("title"),
            content=entry["content"],
            source_url=entry.get("source_url"),
            raw_caption=None,
            created_at=now - i * 3600,
            thin_content=False,
        )
        nid = insert_note(conn, note)
        if nid is None:
            raise RuntimeError(f"insert_note returned None for {entry['key']}")

        embed_text = entry["content"]
        if entry.get("title"):
            embed_text = f"{entry['title']}\n\n{embed_text}"
        embedding = await jina.embed(embed_text[:8000], role="passage")
        upsert_embedding(conn, nid, embedding)

        key_to_id[entry["key"]] = nid
        if (i + 1) % 10 == 0:
            print(f"  embedded {i + 1}/{len(NOTES)}")

    return conn, db_path, key_to_id


async def run_query(
    conn: sqlite3.Connection,
    *,
    jina: JinaClient,
    openrouter: OpenRouterClient,
    primary_model: str,
    fallback_model: str | None,
    raw_query: str,
) -> list[int]:
    """Take a raw user query and return the ranked top-K note IDs that
    the bot would actually show. Pipeline: parse_intent ->
    hybrid_search -> rerank. Empty result returns []."""
    from zoneinfo import ZoneInfo
    intent = parse_intent(raw_query, tz=ZoneInfo("Europe/Moscow"))
    candidates = await hybrid_search(
        conn, jina=jina, owner_id=OWNER_ID,
        clean_query=intent.clean_query, kind=intent.kind, limit=HYBRID_LIMIT,
    )
    if not candidates:
        return []
    reranked = await rerank(
        openrouter, primary=primary_model, fallback=fallback_model,
        query=intent.clean_query, candidates=candidates, top_k=TOP_K,
    )
    return [n.id for n in reranked[:TOP_K]]


async def run_all(
    *,
    jina_key: str,
    openrouter_key: str,
    primary_model: str,
    fallback_model: str | None,
    queries_subset: list[dict] | None = None,
) -> tuple[list[dict], dict[str, int]]:
    """Bootstrap a fresh DB, run all (or a subset of) queries, return
    per-query result dicts ready for metrics.aggregate(). Each result
    dict has: q, tag, expected_ids, predicted_ids."""
    jina = JinaClient(api_key=jina_key)
    openrouter = OpenRouterClient(api_key=openrouter_key)

    print(f"bootstrapping fixture DB with {len(NOTES)} notes...")
    conn, db_path, key_to_id = await bootstrap_db(jina)
    print(f"DB ready at {db_path}")

    queries = queries_subset if queries_subset is not None else QUERIES
    results: list[dict] = []

    for i, q in enumerate(queries):
        print(f"  [{i + 1}/{len(queries)}] {q['q']!r} ({q['tag']})")
        try:
            predicted = await run_query(
                conn,
                jina=jina, openrouter=openrouter,
                primary_model=primary_model, fallback_model=fallback_model,
                raw_query=q["q"],
            )
        except Exception as e:
            logger.exception("query failed: %s", q["q"])
            predicted = []
            print(f"    !! error: {e}")

        expected_ids = [key_to_id[k] for k in q["expected"]]
        results.append({
            "q": q["q"],
            "tag": q["tag"],
            "expected_keys": q["expected"],
            "expected_ids": expected_ids,
            "predicted_ids": predicted,
        })

    conn.close()
    return results, key_to_id
