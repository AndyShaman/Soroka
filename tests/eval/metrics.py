"""Evaluation metrics for retrieval quality.

We treat top-K from rerank as the answer the user actually sees. For
unordered overlap (recall, precision) we compare against expected as a
set; for MRR we use rank order.

Special cases for empty-expected queries:
  * recall@k: 1.0 if predicted is also empty, 0.0 otherwise
  * precision@k: 1.0 if predicted is also empty, 0.0 otherwise
  * MRR: 1.0 if predicted is empty, 0.0 otherwise

This rewards "блаблабла xyz -> empty" behavior; without the special case
those queries would always score 0 and pull averages down for no reason.
"""
from collections import defaultdict
from typing import Iterable


def recall_at_k(expected: list[int], predicted: list[int], k: int = 5) -> float:
    if not expected:
        return 1.0 if not predicted else 0.0
    top = set(predicted[:k])
    hits = sum(1 for e in expected if e in top)
    return hits / len(expected)


def precision_at_k(expected: list[int], predicted: list[int], k: int = 5) -> float:
    if not expected:
        return 1.0 if not predicted else 0.0
    top = predicted[:k]
    if not top:
        return 0.0
    exp_set = set(expected)
    hits = sum(1 for p in top if p in exp_set)
    return hits / len(top)


def mrr(expected: list[int], predicted: list[int]) -> float:
    if not expected:
        return 1.0 if not predicted else 0.0
    exp_set = set(expected)
    for rank, p in enumerate(predicted, start=1):
        if p in exp_set:
            return 1.0 / rank
    return 0.0


def aggregate(per_query: list[dict]) -> dict:
    """Take a list of per-query result dicts and compute global +
    per-tag means. Each input dict carries: tag, recall, precision, mrr."""
    if not per_query:
        return {"global": {"recall@5": 0, "precision@5": 0, "mrr": 0, "n": 0},
                "by_tag": {}}

    by_tag: dict[str, list[dict]] = defaultdict(list)
    for r in per_query:
        by_tag[r["tag"]].append(r)

    def _mean(rows: Iterable[dict], key: str) -> float:
        rows = list(rows)
        return sum(r[key] for r in rows) / len(rows) if rows else 0.0

    return {
        "global": {
            "recall@5": _mean(per_query, "recall"),
            "precision@5": _mean(per_query, "precision"),
            "mrr": _mean(per_query, "mrr"),
            "n": len(per_query),
        },
        "by_tag": {
            tag: {
                "recall@5": _mean(rows, "recall"),
                "precision@5": _mean(rows, "precision"),
                "mrr": _mean(rows, "mrr"),
                "n": len(rows),
            }
            for tag, rows in by_tag.items()
        },
    }
