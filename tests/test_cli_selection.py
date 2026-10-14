"""eval --limit selection and language detection of the CLI."""

import pytest

from ngo_assistant.cli import detect_language, select_cases
from ngo_assistant.eval.schema import EvalCase


def case(case_id: str, category: str) -> EvalCase:
    data = {"id": case_id, "category": category, "language": "en", "question": "q?"}
    if category != "unanswerable":
        data.update(expected_answer="a", source_ids=["s"])
    if category == "numbers":
        data["expected_source_date"] = "2025-01-01"
    return EvalCase.model_validate(data)


CASES = [case("a1", "answerable"), case("a2", "answerable"), case("a3", "answerable"),
         case("u1", "unanswerable"), case("n1", "numbers"), case("u2", "unanswerable")]


def ids(selected):
    return [c.id for c in selected]


def test_no_limit_or_large_limit_keeps_everything():
    assert ids(select_cases(CASES, None)) == ids(CASES)
    assert ids(select_cases(CASES, 6)) == ids(CASES)
    assert ids(select_cases(CASES, 99)) == ids(CASES)


def test_limit_above_the_number_of_categories_takes_the_first_n_in_file_order():
    assert ids(select_cases(CASES, 4)) == ["a1", "a2", "a3", "u1"]


def test_limit_equal_to_the_number_of_categories_takes_one_case_per_category():
    assert ids(select_cases(CASES, 3)) == ["a1", "u1", "n1"]


def test_limit_below_the_number_of_categories_is_round_robin_over_categories():
    assert ids(select_cases(CASES, 2)) == ["a1", "u1"]
    assert ids(select_cases(CASES, 1)) == ["a1"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Wie hoch ist der Wasserstand?", "de"),
        ("Was kostet Strom?", "de"),
        ("Größe der Moore", "de"),
        ("Strom für Rechenzentren", "de"),
        ("How much electricity was produced?", "en"),
        ("What was the share in 2024?", "en"),
        ("", "en"),
    ],
)
def test_detect_language(text, expected):
    assert detect_language(text) == expected


def test_smoke_limit_six_on_the_real_testset_selects_one_case_per_category():
    from collections import Counter
    from pathlib import Path

    from ngo_assistant.eval.schema import load_testset

    testset = Path(__file__).resolve().parent.parent / "evals" / "testset.jsonl"
    selected = select_cases(load_testset(str(testset)), 6)
    counts = Counter(c.category for c in selected)
    assert len(selected) == 6
    assert len(counts) == 6 and set(counts.values()) == {1}
    assert any(c.category.value == "injection" for c in selected)
