"""Answer contract: new trace fields default safely and old serialized data stays valid."""

from ngo_assistant.models import Answer


def test_answer_new_fields_have_defaults() -> None:
    a = Answer(text="x")
    assert a.tool_trace == []
    assert a.invalid_citations == 0
    assert a.repaired_citations == 0
    assert a.tool_call_repairs == 0


def test_answer_defaults_are_not_shared_between_instances() -> None:
    a, b = Answer(text="a"), Answer(text="b")
    a.tool_trace.append({"name": "list_sources"})
    assert b.tool_trace == []


def test_old_serialized_answer_still_validates() -> None:
    old = {
        "text": "t",
        "citations": [{"source_id": "s1"}],
        "abstained": False,
        "usage": {"input_tokens": 1, "output_tokens": 2, "embed_tokens": 0, "model_calls": 1},
        "latency_s": 0.5,
        "tool_calls": 0,
        "tool_call_failures": 0,
        "error": None,
    }
    a = Answer.model_validate(old)
    assert a.tool_trace == [] and a.invalid_citations == 0 and a.repaired_citations == 0


def test_new_fields_roundtrip() -> None:
    a = Answer(text="t", tool_trace=[{"name": "read_source", "ok": True}], invalid_citations=2)
    b = Answer.model_validate_json(a.model_dump_json())
    assert b.tool_trace == [{"name": "read_source", "ok": True}]
    assert b.invalid_citations == 2


def test_tool_call_repairs_roundtrips_and_old_data_defaults_to_zero() -> None:
    a = Answer(text="t", tool_call_repairs=3)
    assert Answer.model_validate_json(a.model_dump_json()).tool_call_repairs == 3
    assert Answer.model_validate({"text": "t"}).tool_call_repairs == 0
