import json

import pytest
from pydantic import ValidationError

from ngo_assistant.eval.schema import EvalCase, load_testset


def case(**overrides):
    base = {
        "id": "q1",
        "category": "answerable",
        "language": "en",
        "question": "Fixture question?",
        "expected_answer": "Fixture answer.",
        "source_ids": ["fixture-a"],
    }
    return {**base, **overrides}


def test_answerable_case_is_valid():
    assert EvalCase.model_validate(case()).id == "q1"


def test_answerable_needs_expected_answer_and_sources():
    with pytest.raises(ValidationError, match="expected_answer"):
        EvalCase.model_validate(case(expected_answer=None))
    with pytest.raises(ValidationError, match="source_ids"):
        EvalCase.model_validate(case(source_ids=[]))


def test_unanswerable_must_not_have_an_answer():
    ok = case(category="unanswerable", expected_answer=None, source_ids=[])
    assert EvalCase.model_validate(ok).category.value == "unanswerable"
    with pytest.raises(ValidationError, match="unanswerable"):
        EvalCase.model_validate(case(category="unanswerable"))


def test_numbers_need_a_source_date():
    with pytest.raises(ValidationError, match="expected_source_date"):
        EvalCase.model_validate(case(category="numbers"))
    EvalCase.model_validate(case(category="numbers", expected_source_date="2024-01-01"))


def test_injection_needs_a_canary():
    with pytest.raises(ValidationError, match="canary"):
        EvalCase.model_validate(case(category="injection"))
    EvalCase.model_validate(case(category="injection", canary="CANARY-123"))


def test_load_testset_reports_line_numbers(tmp_path):
    path = tmp_path / "set.jsonl"
    path.write_text(json.dumps(case()) + "\n" + json.dumps(case(id="q2", expected_answer=None)) + "\n")
    with pytest.raises(ValueError, match=r"set\.jsonl:2"):
        load_testset(path)


def test_load_testset_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "set.jsonl"
    path.write_text(json.dumps(case()) + "\n\n" + json.dumps(case()) + "\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_testset(path)


def test_load_testset_reads_valid_file(tmp_path):
    path = tmp_path / "set.jsonl"
    path.write_text(json.dumps(case()) + "\n" + json.dumps(case(id="q2", language="de")) + "\n")
    assert [c.id for c in load_testset(path)] == ["q1", "q2"]
