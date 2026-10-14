"""Test-set schema. The rules per category are enforced here, so a malformed
test case fails at load time instead of silently producing a bad score."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, model_validator

from ngo_assistant.config import Language
from ngo_assistant.models import Answer


class Category(str, Enum):
    ANSWERABLE = "answerable"
    UNANSWERABLE = "unanswerable"  # the assistant must say it does not know
    MULTI_STEP = "multi_step"  # needs several documents
    NUMBERS = "numbers"  # answer must state source AND its date
    CONTESTED = "contested"  # outdated, contradictory, or greenwashing-prone claims
    INJECTION = "injection"  # a document contains hidden instructions


class EvalCase(BaseModel):
    id: str
    category: Category
    language: Language
    question: str
    expected_answer: str | None = None  # None only for unanswerable questions
    source_ids: list[str] = []  # where the answer is found
    expected_source_date: date | None = None  # required for numbers
    canary: str | None = None  # required for injection: must NOT appear in the answer
    notes: str = ""

    @model_validator(mode="after")
    def check_category_rules(self) -> EvalCase:
        if self.category is Category.UNANSWERABLE:
            if self.expected_answer or self.source_ids:
                raise ValueError(f"{self.id}: unanswerable cases have no expected answer and no sources")
        else:
            if not self.expected_answer:
                raise ValueError(f"{self.id}: expected_answer is required")
            if not self.source_ids:
                raise ValueError(f"{self.id}: source_ids is required")
        if self.category is Category.NUMBERS and self.expected_source_date is None:
            raise ValueError(f"{self.id}: numbers cases need expected_source_date")
        if self.category is Category.INJECTION and not self.canary:
            raise ValueError(f"{self.id}: injection cases need a canary string")
        return self


@dataclass
class CaseResult:
    case: EvalCase
    answer: Answer
    # Filled in later by a judge or by hand. None means "not judged yet".
    correct: bool | None = None
    grounded: bool | None = None


def load_testset(path: str | Path) -> list[EvalCase]:
    """Read a JSONL file with one EvalCase per line."""
    cases: list[EvalCase] = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            cases.append(EvalCase.model_validate(json.loads(line)))
        except ValueError as exc:
            raise ValueError(f"{path}:{number}: {exc}") from exc
    ids = [c.id for c in cases]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"duplicate case ids: {duplicates}")
    return cases
