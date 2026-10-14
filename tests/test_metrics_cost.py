"""Cost / resource metric: tokens and model calls as the proxy, API cost is 0 (local inference)."""

from ngo_assistant.eval.metrics import summarize
from ngo_assistant.eval.schema import CaseResult, EvalCase
from ngo_assistant.models import Answer, Usage


def make_case(category="answerable", **extra):
    base = {"id": "c", "category": category, "language": "en", "question": "q?"}
    if category != "unanswerable":
        base |= {"expected_answer": "a", "source_ids": ["s1"]}
    if category == "injection":
        base["canary"] = "CANARY-123"
    return EvalCase.model_validate(base | extra)


def make_result(category="answerable", text="ok", **answer_fields):
    return CaseResult(case=make_case(category), answer=Answer(text=text, **answer_fields))


def test_usage_new_fields_default_to_zero_so_old_data_stays_valid():
    u = Usage(input_tokens=5, output_tokens=2)
    assert u.embed_tokens == 0
    assert u.model_calls == 0
    assert Usage.model_validate({"input_tokens": 1, "output_tokens": 1}).model_calls == 0


def test_summarize_reports_total_embed_and_model_call_means():
    results = [
        make_result(usage=Usage(input_tokens=100, output_tokens=10, embed_tokens=20, model_calls=2)),
        make_result(usage=Usage(input_tokens=300, output_tokens=30, embed_tokens=40, model_calls=4)),
    ]
    s = summarize(results)
    assert s["total_tokens_mean"] == (130 + 370) / 2
    assert s["embed_tokens_mean"] == 30
    assert s["model_calls_mean"] == 3


def test_api_cost_is_zero_for_local_inference():
    s = summarize([make_result(usage=Usage(input_tokens=100, output_tokens=10, model_calls=1))])
    assert s["api_cost_eur"] == 0.0


def test_cost_metrics_exclude_errored_cases():
    results = [
        make_result(usage=Usage(input_tokens=10, output_tokens=2, embed_tokens=4, model_calls=1)),
        make_result(text="", error="TimeoutError: slow",
                    usage=Usage(input_tokens=9999, output_tokens=9999, embed_tokens=9999, model_calls=99)),
    ]
    s = summarize(results)
    assert s["total_tokens_mean"] == 16
    assert s["embed_tokens_mean"] == 4
    assert s["model_calls_mean"] == 1


def test_cost_means_are_none_without_non_errored_cases():
    s = summarize([make_result(text="", error="boom")])
    assert s["total_tokens_mean"] is None
    assert s["embed_tokens_mean"] is None
    assert s["model_calls_mean"] is None
    assert s["api_cost_eur"] == 0.0


def test_api_cost_is_zero_for_empty_results():
    assert summarize([])["api_cost_eur"] == 0.0
