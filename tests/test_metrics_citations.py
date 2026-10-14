"""Citation and format diagnostics in summarize()."""

import pytest

from ngo_assistant.eval.metrics import summarize
from ngo_assistant.eval.schema import CaseResult, EvalCase
from ngo_assistant.models import Answer, Citation

KEYS = ("invalid_citations_total", "repaired_citations_total", "format_error_rate",
        "answers_without_citation_rate", "abstain_text_mismatch_rate")


def result(text="ok", citations=(), abstained=False, error=None, trace=(), invalid=0, repaired=0, calls=0,
           tool_repairs=0):
    case = EvalCase.model_validate({"id": "c", "category": "answerable", "language": "en", "question": "q?",
                                    "expected_answer": "a", "source_ids": ["s"]})
    answer = Answer(text=text, citations=[Citation(source_id=c) for c in citations], abstained=abstained,
                    error=error, tool_trace=list(trace), invalid_citations=invalid, repaired_citations=repaired,
                    tool_calls=calls, tool_call_repairs=tool_repairs)
    return CaseResult(case=case, answer=answer)


def test_all_new_keys_are_none_or_zero_without_ok_cases():
    summary = summarize([result(error="boom", invalid=5)])
    assert summary["invalid_citations_total"] == 0
    assert summary["repaired_citations_total"] == 0
    assert all(summary[k] is None for k in KEYS[2:])
    assert all(k in summarize([]) for k in KEYS)


def test_invalid_and_repaired_totals_sum_over_ok_cases_only():
    summary = summarize([result(invalid=2, repaired=1), result(invalid=1), result(error="x", invalid=9, repaired=9)])
    assert summary["invalid_citations_total"] == 3
    assert summary["repaired_citations_total"] == 1


def test_format_error_rate_counts_ok_cases_with_a_format_error_trace_entry():
    fe = [{"event": "format_error", "detail": "d"}]
    other = [{"event": "final"}]
    summary = summarize([result(trace=fe), result(trace=other + fe), result(trace=other), result(),
                         result(error="x", trace=fe)])
    assert summary["format_error_rate"] == 2 / 4


def test_answers_without_citation_rate_ignores_abstained_answers():
    summary = summarize([result(citations=["s"]), result(), result(), result(abstained=True),
                         result(error="x")])
    assert summary["answers_without_citation_rate"] == 2 / 3


def test_answers_without_citation_rate_is_none_when_everything_abstained():
    assert summarize([result(abstained=True)])["answers_without_citation_rate"] is None


@pytest.mark.parametrize("text", ["abstain", "  Unknown  ", "I do not know", "I don't know",
                                  "Ich weiß es nicht", "weiß ich nicht", "Unbekannt", "NOT IN THE SOURCES",
                                  "  abstain\n"])
def test_abstain_text_mismatch_flags_exact_abstain_phrases_with_abstained_false(text):
    r = result(text=text, abstained=False)
    summary = summarize([r, result(text="A real answer.")])
    assert summary["abstain_text_mismatch_rate"] == 1 / 2
    assert r.answer.abstained is False  # diagnostic only, `abstained` is not touched


def test_abstain_text_mismatch_ignores_abstained_true_and_longer_texts():
    summary = summarize([result(text="unknown", abstained=True), result(text="I do not know the answer")])
    assert summary["abstain_text_mismatch_rate"] == 0.0


def test_abstain_text_mismatch_is_none_without_ok_cases():
    assert summarize([result(error="x")])["abstain_text_mismatch_rate"] is None


def test_tool_call_repair_keys_are_zero_and_none_without_data():
    assert summarize([])["tool_call_repairs_total"] == 0
    assert summarize([])["tool_call_repair_rate"] is None
    assert summarize([result(calls=0, tool_repairs=0)])["tool_call_repair_rate"] is None


def test_tool_call_repairs_total_and_rate_over_ok_cases_only():
    summary = summarize([result(calls=4, tool_repairs=1), result(calls=2, tool_repairs=2),
                         result(calls=10, tool_repairs=7, error="x")])
    assert summary["tool_call_repairs_total"] == 3
    assert summary["tool_call_repair_rate"] == 3 / 6
