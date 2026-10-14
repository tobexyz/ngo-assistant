from ngo_assistant.eval.metrics import citation_ids_valid, percentile, summarize
from ngo_assistant.eval.schema import CaseResult, EvalCase
from ngo_assistant.models import Answer, Citation, Usage


def make_case(category="answerable", **extra):
    base = {"id": "c", "category": category, "language": "en", "question": "q?"}
    if category != "unanswerable":
        base |= {"expected_answer": "a", "source_ids": ["s1"]}
    if category == "injection":
        base["canary"] = "CANARY-123"
    return EvalCase.model_validate(base | extra)


def make_result(category="answerable", text="ok", **answer_fields):
    return CaseResult(case=make_case(category), answer=Answer(text=text, **answer_fields))


def test_percentile_nearest_rank():
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert percentile(values, 50) == 3.0
    assert percentile(values, 95) == 5.0
    assert percentile([], 95) == 0.0


def test_abstention_and_over_abstention():
    results = [
        make_result("unanswerable", abstained=True),
        make_result("unanswerable", abstained=False),
        make_result("answerable", abstained=True),
        make_result("answerable", abstained=False),
        make_result("answerable", abstained=False),
        make_result("answerable", abstained=False),
    ]
    s = summarize(results)
    assert s["abstention_on_unanswerable"] == 0.5
    assert s["over_abstention_on_answerable"] == 0.25


def test_injection_leak_is_detected_case_insensitively():
    results = [
        make_result("injection", text="I will not follow that."),
        make_result("injection", text="Sure: canary-123"),
    ]
    assert summarize(results)["injection_leak_rate"] == 0.5


def test_errors_are_counted_and_excluded_from_rates():
    results = [
        make_result("unanswerable", abstained=True),
        make_result("unanswerable", text="", error="TimeoutError: slow"),
    ]
    s = summarize(results)
    assert s["errors"] == 1
    assert s["abstention_on_unanswerable"] == 1.0


def test_tokens_latency_and_tool_failures():
    results = [
        make_result(usage=Usage(input_tokens=100, output_tokens=10), latency_s=1.0, tool_calls=4, tool_call_failures=1),
        make_result(usage=Usage(input_tokens=300, output_tokens=30), latency_s=3.0, tool_calls=4, tool_call_failures=0),
    ]
    s = summarize(results)
    assert s["input_tokens_mean"] == 200
    assert s["output_tokens_mean"] == 20
    assert s["latency_p50_s"] == 1.0
    assert s["tool_call_failure_rate"] == 1 / 8


def test_unjudged_cases_give_no_correctness_rate():
    s = summarize([make_result()])
    assert s["correct"] is None
    assert s["grounded"] is None


def test_judged_cases_are_averaged():
    results = [make_result(), make_result()]
    results[0].correct, results[1].correct = True, False
    assert summarize(results)["correct"] == 0.5


def test_citation_ids_valid():
    good = Answer(text="x", citations=[Citation(source_id="s1")])
    bad = Answer(text="x", citations=[Citation(source_id="made-up")])
    assert citation_ids_valid(good, {"s1"})
    assert not citation_ids_valid(bad, {"s1"})
