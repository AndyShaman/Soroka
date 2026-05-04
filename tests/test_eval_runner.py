import pytest
import yaml
from pathlib import Path

from scripts.eval_search import compute_recall_at_k, compute_mrr, GoldenCase


def test_recall_at_k_full_match():
    case = GoldenCase(query="x", expected_ids=[1, 2])
    returned_ids = [1, 2, 3, 4, 5]
    assert compute_recall_at_k(case, returned_ids, k=5) == 1.0


def test_recall_at_k_partial_match():
    case = GoldenCase(query="x", expected_ids=[1, 2])
    returned_ids = [1, 9, 8, 7, 6]
    assert compute_recall_at_k(case, returned_ids, k=5) == 0.5


def test_recall_at_k_zero():
    case = GoldenCase(query="x", expected_ids=[1, 2])
    returned_ids = [9, 8, 7, 6, 5]
    assert compute_recall_at_k(case, returned_ids, k=5) == 0.0


def test_mrr_first_position():
    case = GoldenCase(query="x", expected_ids=[1])
    assert compute_mrr(case, [1, 2, 3, 4, 5]) == 1.0


def test_mrr_third_position():
    case = GoldenCase(query="x", expected_ids=[3])
    assert compute_mrr(case, [1, 2, 3, 4, 5]) == pytest.approx(1.0 / 3)


def test_mrr_no_match():
    case = GoldenCase(query="x", expected_ids=[99])
    assert compute_mrr(case, [1, 2, 3, 4, 5]) == 0.0


def test_golden_yaml_parses(tmp_path):
    yml = tmp_path / "golden.yaml"
    yml.write_text(
        "- query: 'тест'\n"
        "  expected_ids: [1, 2]\n"
        "- query: 'другой'\n"
        "  expected_ids: [5]\n"
    )
    cases = yaml.safe_load(yml.read_text())
    assert len(cases) == 2
    assert cases[0]["query"] == "тест"
