import json

import pytest

from ngo_assistant.eval.runner import run, write_results
from ngo_assistant.eval.schema import EvalCase
from ngo_assistant.models import Answer


def one_case():
    return [
        EvalCase.model_validate(
            {"id": "q1", "category": "answerable", "language": "en", "question": "q?",
             "expected_answer": "a", "source_ids": ["s1"]}
        )
    ]


class Fake:
    name = "fake"

    def answer(self, question: str, language: str) -> Answer:
        return Answer(text="hello")


class Crashing:
    name = "crashing"

    def answer(self, question: str, language: str) -> Answer:
        raise TimeoutError("model too slow")


class Unfinished:
    name = "unfinished"

    def answer(self, question: str, language: str) -> Answer:
        raise NotImplementedError


def test_runner_measures_latency():
    [result] = run(Fake(), one_case())
    assert result.answer.text == "hello"
    assert result.answer.latency_s >= 0.0


def test_runner_records_errors_instead_of_crashing():
    [result] = run(Crashing(), one_case())
    assert result.answer.error == "TimeoutError: model too slow"


def test_runner_lets_unfinished_stubs_fail_loudly():
    with pytest.raises(NotImplementedError):
        run(Unfinished(), one_case())


def test_write_results_creates_jsonl(tmp_path):
    results = run(Fake(), one_case())
    out = tmp_path / "nested" / "run.jsonl"
    write_results(results, out)
    row = json.loads(out.read_text(encoding="utf-8").splitlines()[0])
    assert row["case_id"] == "q1"
    assert row["answer"]["text"] == "hello"


def test_result_row_has_the_documented_keys_and_matches_write_results(tmp_path):
    from ngo_assistant.eval.runner import result_row

    results = run(Fake(), one_case())
    row = result_row(results[0])
    assert set(row) == {"case_id", "category", "question", "answer", "correct", "grounded"}
    assert row["category"] == "answerable"
    out = tmp_path / "run.jsonl"
    write_results(results, out)
    assert json.loads(out.read_text(encoding="utf-8").splitlines()[0]) == row
