"""CLI entry point for the search-quality eval suite.

Usage:
    python -m tests.eval.run_eval                    # full set, baseline pipeline
    python -m tests.eval.run_eval --tag morphology   # subset by tag
    python -m tests.eval.run_eval --primary-model anthropic/claude-haiku-4-5

Required env (loaded via dotenv from .env):
    JINA_API_KEY        — Jina embeddings key (free tier OK)
    OPENROUTER_API_KEY  — OpenRouter key for intent parsing + rerank

Optional env:
    EVAL_PRIMARY_MODEL  — defaults to anthropic/claude-haiku-4-5
    EVAL_FALLBACK_MODEL — defaults to openai/gpt-4o-mini
"""
import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv

from tests.eval.metrics import (
    aggregate, mrr, precision_at_k, recall_at_k,
)
from tests.eval.queries import QUERIES
from tests.eval.runner import run_all


def _format_pct(x: float) -> str:
    return f"{x * 100:5.1f}%"


def _print_report(results: list[dict]) -> None:
    scored = []
    for r in results:
        scored.append({
            "q": r["q"],
            "tag": r["tag"],
            "recall": recall_at_k(r["expected_ids"], r["predicted_ids"], k=5),
            "precision": precision_at_k(r["expected_ids"], r["predicted_ids"], k=5),
            "mrr": mrr(r["expected_ids"], r["predicted_ids"]),
            "expected_keys": r["expected_keys"],
            "expected_ids": r["expected_ids"],
            "predicted_ids": r["predicted_ids"],
        })

    summary = aggregate(scored)

    print()
    print("=" * 70)
    print("EVAL REPORT")
    print("=" * 70)
    g = summary["global"]
    print(f"Global  (n={g['n']:>2})  "
          f"recall@5={_format_pct(g['recall@5'])}  "
          f"precision@5={_format_pct(g['precision@5'])}  "
          f"MRR={g['mrr']:.3f}")
    print()
    print("By tag:")
    for tag, m in sorted(summary["by_tag"].items()):
        print(f"  {tag:<22} (n={m['n']:>2})  "
              f"R={_format_pct(m['recall@5'])}  "
              f"P={_format_pct(m['precision@5'])}  "
              f"MRR={m['mrr']:.3f}")

    print()
    print("Per-query (recall=0 first — these are the failures):")
    scored.sort(key=lambda x: (x["recall"], x["mrr"]))
    for r in scored:
        marker = "FAIL" if r["recall"] == 0 and r["expected_ids"] else (
            "OK" if r["recall"] >= 0.5 else "weak"
        )
        print(
            f"  [{marker:>4}] R={_format_pct(r['recall'])} "
            f"P={_format_pct(r['precision'])} "
            f"MRR={r['mrr']:.2f} "
            f"| {r['tag']:<18} | {r['q']!r}"
        )
        print(f"            expected={r['expected_keys']}")
        print(f"            predicted_ids={r['predicted_ids']}")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Search-quality eval")
    parser.add_argument("--tag", help="run only queries with this tag")
    parser.add_argument(
        "--primary-model",
        default=os.environ.get("EVAL_PRIMARY_MODEL", "anthropic/claude-haiku-4-5"),
    )
    parser.add_argument(
        "--fallback-model",
        default=os.environ.get("EVAL_FALLBACK_MODEL", "openai/gpt-4o-mini"),
    )
    args = parser.parse_args()

    load_dotenv()
    jina_key = os.environ.get("JINA_API_KEY", "").strip()
    openrouter_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not jina_key:
        print("ERROR: JINA_API_KEY missing. Put it in .env or export it.",
              file=sys.stderr)
        return 2
    if not openrouter_key:
        print("ERROR: OPENROUTER_API_KEY missing. Put it in .env or export it.",
              file=sys.stderr)
        return 2

    queries_subset = None
    if args.tag:
        queries_subset = [q for q in QUERIES if q["tag"] == args.tag]
        if not queries_subset:
            print(f"ERROR: no queries match tag {args.tag!r}", file=sys.stderr)
            return 2
        print(f"running {len(queries_subset)} queries with tag={args.tag!r}")

    print(f"primary_model={args.primary_model}")
    print(f"fallback_model={args.fallback_model}")

    results, _ = await run_all(
        jina_key=jina_key,
        openrouter_key=openrouter_key,
        primary_model=args.primary_model,
        fallback_model=args.fallback_model,
        queries_subset=queries_subset,
    )
    _print_report(results)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
