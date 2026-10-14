"""Checks on the 48-case test set that need neither the corpus nor the network.

Written first (red phase): evals/testset.jsonl is produced in Group 3-4 of spec 2026-10-14-testset.
Set NGO_TESTSET_PATH to run the same checks against another file.
"""

import os
import re
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from ngo_assistant.config import Tenant, load_tenant
from ngo_assistant.eval.schema import Category, EvalCase, load_testset

ROOT = Path(__file__).resolve().parent.parent
TESTSET_PATH = Path(os.environ.get("NGO_TESTSET_PATH") or ROOT / "evals" / "testset.jsonl")
MISSING = "evals/testset.jsonl missing: written in Group 3-4 of spec 2026-10-14-testset"

EXPECTED_COUNTS = {
    Category.ANSWERABLE: 12,
    Category.UNANSWERABLE: 7,
    Category.MULTI_STEP: 8,
    Category.NUMBERS: 8,
    Category.CONTESTED: 8,
    Category.INJECTION: 5,
}
PREFIX = {
    Category.ANSWERABLE: "ans",
    Category.UNANSWERABLE: "una",
    Category.MULTI_STEP: "mul",
    Category.NUMBERS: "num",
    Category.CONTESTED: "con",
    Category.INJECTION: "inj",
}
DATED_PAIRS = [
    ("eea-ghg-trends-2024", "eea-ghg-trends-2025"),
    ("destatis-strom-2024", "destatis-strom-2025"),
    ("uba-erneuerbare-pm-2024", "uba-erneuerbare-2025"),
    ("syn-annual-report-2024", "syn-newsletter-2026-04"),
]


@pytest.fixture(scope="module")
def cases() -> list[EvalCase]:
    if not TESTSET_PATH.exists():
        pytest.fail(MISSING, pytrace=False)
    return load_testset(TESTSET_PATH)


@pytest.fixture(scope="module")
def tenant() -> Tenant:
    return load_tenant(ROOT / "tenants" / "moorfunke.yaml")


def ids(selected) -> list[str]:
    return [c.id for c in selected]


def of(cases, category: Category) -> list[EvalCase]:
    return [c for c in cases if c.category is category]


def canaries_from_markdown() -> set[str]:
    text = (ROOT / "data" / "synthetic" / "CANARIES.md").read_text(encoding="utf-8")
    return set(re.findall(r"^\|\s*(MF-CANARY-[0-9a-f]+)\s*\|", text, flags=re.MULTILINE))


def synthetic_text(tenant: Tenant, source_id: str) -> str:
    """Text of a synthetic source; empty for real sources (their text is not in the repo)."""
    source = next(s for s in tenant.sources if s.id == source_id)
    if source.kind != "synthetic":
        return ""
    return (ROOT / source.url).read_text(encoding="utf-8")


def test_total_is_48(cases):
    assert len(cases) == 48


def test_category_counts_are_exact(cases):
    counts = Counter(c.category for c in cases)
    assert {k: counts.get(k, 0) for k in EXPECTED_COUNTS} == EXPECTED_COUNTS


def test_ids_are_unique(cases):
    duplicates = sorted({i for i in ids(cases) if ids(cases).count(i) > 1})
    assert not duplicates, f"duplicate ids: {duplicates}"


def test_id_prefix_matches_category(cases):
    bad = [c.id for c in cases if not re.fullmatch(rf"{PREFIX[c.category]}-\d{{2}}", c.id)]
    assert not bad, f"ids with wrong prefix or format: {bad}"


@pytest.mark.parametrize("language", ["de", "en"])
def test_language_share_is_balanced(cases, language):
    share = sum(c.language == language for c in cases) / len(cases)
    assert 0.4 <= share <= 0.6, f"{language} share is {share:.0%}"


def test_every_source_id_exists_in_tenant(cases, tenant):
    known = {s.id for s in tenant.sources}
    bad = {c.id: sorted(set(c.source_ids) - known) for c in cases if set(c.source_ids) - known}
    assert not bad, f"unknown source ids: {bad}"


def test_at_least_three_cross_language_cases(cases, tenant):
    lang = {s.id: s.language for s in tenant.sources}
    cross = [c.id for c in cases if any(lang[s] != c.language for s in c.source_ids if s in lang)]
    assert len(cross) >= 3, f"cross-language cases: {cross}"


def test_ngo_specific_cases_are_8_to_10(cases):
    ngo = [c.id for c in cases if any(s.startswith("syn-") for s in c.source_ids)]
    assert 8 <= len(ngo) <= 10, f"{len(ngo)} cases cite syn-* sources: {ngo}"


def test_multi_step_cites_two_distinct_sources(cases):
    bad = [c.id for c in of(cases, Category.MULTI_STEP) if len(set(c.source_ids)) < 2]
    assert not bad, f"multi_step with fewer than 2 distinct sources: {bad}"


def test_contested_cites_a_source(cases):
    bad = [c.id for c in of(cases, Category.CONTESTED) if not c.source_ids]
    assert not bad, f"contested without sources: {bad}"


def test_unanswerable_cites_nothing(cases):
    bad = [c.id for c in of(cases, Category.UNANSWERABLE) if c.source_ids]
    assert not bad, f"unanswerable with sources: {bad}"


def test_numbers_source_date_is_newest_cited_publication(cases, tenant):
    published = {s.id: s.published for s in tenant.sources}
    undated = [c.id for c in of(cases, Category.NUMBERS) if any(published.get(s) is None for s in c.source_ids)]
    assert not undated, f"numbers cases citing a source without published date: {undated}"
    wrong = {
        c.id: (c.expected_source_date, max(published[s] for s in c.source_ids))
        for c in of(cases, Category.NUMBERS)
        if c.source_ids and c.expected_source_date != max(d for d in (published[s] for s in c.source_ids) if d)
    }
    assert not wrong, f"expected_source_date vs newest published: {wrong}"


def test_injection_canary_is_listed_in_canaries_md(cases):
    listed = canaries_from_markdown()
    assert len(listed) == 3, f"expected 3 canaries in CANARIES.md, parsed {listed}"
    bad = [c.id for c in of(cases, Category.INJECTION) if c.canary not in listed]
    assert not bad, f"canary not in CANARIES.md: {bad}"


def test_injection_canary_is_in_a_cited_synthetic_document(cases, tenant):
    synthetic = {s.id for s in tenant.sources if s.kind == "synthetic"}
    bad = [
        c.id
        for c in of(cases, Category.INJECTION)
        if not any(s in synthetic and c.canary in synthetic_text(tenant, s) for s in c.source_ids)
    ]
    assert not bad, f"canary not found in any cited synthetic source: {bad}"


def test_at_least_two_injection_cases_cite_a_second_document(cases, tenant):
    with_second = []
    for c in of(cases, Category.INJECTION):
        holders = {s for s in c.source_ids if c.canary and c.canary in synthetic_text(tenant, s)}
        if set(c.source_ids) - holders:
            with_second.append(c.id)
    assert len(with_second) >= 2, f"injection cases with a second source: {with_second}"


def test_injection_cases_use_both_languages(cases):
    assert {c.language for c in of(cases, Category.INJECTION)} == {"de", "en"}


def test_injection_cases_use_all_three_canaries(cases):
    used = {c.canary for c in of(cases, Category.INJECTION)}
    assert used == canaries_from_markdown(), f"canaries used: {sorted(used, key=str)}"


@pytest.mark.parametrize(("older", "newer"), DATED_PAIRS)
def test_dated_pair_is_cited_together(cases, older, newer):
    assert any({older, newer} <= set(c.source_ids) for c in cases), f"no case cites both {older} and {newer}"


def test_expected_answer_stays_short(cases):
    long = {c.id: len(c.expected_answer) for c in cases if c.expected_answer and len(c.expected_answer) > 600}
    assert not long, f"expected_answer over 600 characters: {long}"


def test_expected_source_date_type(cases):
    # guards against load_testset returning strings for dates
    assert all(isinstance(c.expected_source_date, date) for c in of(cases, Category.NUMBERS))


def test_every_case_has_notes(cases):
    bad = [c.id for c in cases if not c.notes.strip()]
    assert not bad, f"cases with empty notes: {bad}"


def test_numbers_expected_answer_contains_a_digit(cases):
    bad = [c.id for c in of(cases, Category.NUMBERS) if not re.search(r"\d", c.expected_answer or "")]
    assert not bad, f"numbers cases without a digit in expected_answer: {bad}"
