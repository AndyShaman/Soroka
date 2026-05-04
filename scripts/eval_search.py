"""Search quality evaluation runner.

Usage:
    python -m scripts.eval_search [--db /app/data/soroka.db] [--owner <id>]

Reads tests/eval/golden_queries.yaml. Each entry has `query` (str) and
`expected_ids` (list[int]) — the note IDs that the engineer manually
verified must be in the top-K. Prints recall@5 and MRR per case and
average. Stores result to tests/eval/last_run.json so subsequent runs
can show deltas vs baseline.
"""
import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.db import open_db, init_schema
from src.core.owners import get_owner
from src.core.search import hybrid_search
from src.adapters.jina import JinaClient


@dataclass
class GoldenCase:
    query: str
    expected_ids: list[int]


def compute_recall_at_k(case: GoldenCase, returned_ids: list[int], k: int) -> float:
    if not case.expected_ids:
        return 0.0
    top_k = set(returned_ids[:k])
    hits = sum(1 for nid in case.expected_ids if nid in top_k)
    return hits / len(case.expected_ids)


def compute_mrr(case: GoldenCase, returned_ids: list[int]) -> float:
    """Reciprocal rank of the first expected id in returned_ids."""
    for rank, nid in enumerate(returned_ids, start=1):
        if nid in case.expected_ids:
            return 1.0 / rank
    return 0.0


def load_golden(path: Path) -> list[GoldenCase]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [GoldenCase(query=r["query"], expected_ids=list(r["expected_ids"])) for r in raw]


async def run_case(conn, owner, jina, case: GoldenCase, k: int = 5):
    notes = await hybrid_search(
        conn, jina=jina, owner_id=owner.telegram_id,
        clean_query=case.query, kind=None, limit=k,
    )
    return [n.id for n in notes]


async def main_async(db_path: str, owner_id: int, golden_path: Path,
                     out_path: Path) -> dict[str, Any]:
    conn = open_db(db_path)
    init_schema(conn)
    owner = get_owner(conn, owner_id)
    if owner is None or not owner.jina_api_key:
        print("ERROR: owner has no jina_api_key configured", file=sys.stderr)
        sys.exit(2)
    jina = JinaClient(api_key=owner.jina_api_key)

    cases = load_golden(golden_path)
    results = []
    for case in cases:
        returned = await run_case(conn, owner, jina, case, k=5)
        recall = compute_recall_at_k(case, returned, k=5)
        mrr = compute_mrr(case, returned)
        results.append({
            "query": case.query, "expected": case.expected_ids,
            "returned": returned, "recall@5": recall, "mrr": mrr,
        })
        marker = "✓" if recall == 1.0 else ("~" if recall > 0 else "✗")
        print(f"  {marker} '{case.query}' → recall@5={recall:.2f} mrr={mrr:.2f}")

    avg_recall = sum(r["recall@5"] for r in results) / max(len(results), 1)
    avg_mrr = sum(r["mrr"] for r in results) / max(len(results), 1)
    print(f"\n  average recall@5 = {avg_recall:.3f}")
    print(f"  average MRR      = {avg_mrr:.3f}")

    summary = {"avg_recall_at_5": avg_recall, "avg_mrr": avg_mrr, "cases": results}
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=os.environ.get("SOROKA_DB", "/app/data/soroka.db"))
    p.add_argument("--owner", type=int, default=int(os.environ.get("OWNER_TELEGRAM_ID", "0")))
    p.add_argument("--golden", default="tests/eval/golden_queries.yaml")
    p.add_argument("--out", default="tests/eval/last_run.json")
    args = p.parse_args()

    if not args.owner:
        print("ERROR: pass --owner <telegram_id> or set OWNER_TELEGRAM_ID", file=sys.stderr)
        sys.exit(2)

    asyncio.run(main_async(args.db, args.owner, Path(args.golden), Path(args.out)))


if __name__ == "__main__":
    main()
