"""Runs one variant over the test set. Latency is measured here, so no
variant can forget or fake it. A crashing case is recorded, not fatal,
except NotImplementedError: an unfinished stub should fail loudly."""

from __future__ import annotations

import json
import time
from pathlib import Path

from ngo_assistant.eval.schema import CaseResult, EvalCase
from ngo_assistant.models import Answer
from ngo_assistant.retrieval.base import Answerer


def run(answerer: Answerer, cases: list[EvalCase]) -> list[CaseResult]:
    results: list[CaseResult] = []
    for case in cases:
        start = time.perf_counter()
        try:
            answer = answerer.answer(case.question, case.language)
        except NotImplementedError:
            raise
        except Exception as exc:  # noqa: BLE001 - one bad case must not lose the whole run
            answer = Answer(text="", error=f"{type(exc).__name__}: {exc}")
        elapsed = time.perf_counter() - start
        results.append(CaseResult(case=case, answer=answer.model_copy(update={"latency_s": elapsed})))
    return results


def result_row(result: CaseResult) -> dict:
    """The JSON-serialisable result row shared by write_results and the CLI's incremental writer."""
    return {
        "case_id": result.case.id,
        "category": result.case.category.value,
        "question": result.case.question,
        "answer": result.answer.model_dump(mode="json"),
        "correct": result.correct,
        "grounded": result.grounded,
    }


def write_results(results: list[CaseResult], path: str | Path) -> None:
    """One JSON line per case, so runs can be diffed and spot-checked by hand."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for r in results:
            fh.write(json.dumps(result_row(r), ensure_ascii=False) + "\n")
