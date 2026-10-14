"""Command line (contracts.md "cli.py"). main() is driven with injected stdin/stdout and a fake Runtime factory.

Interface decisions made here (beyond contracts.md), to be confirmed by the orchestrator:
- expected setup errors print ONE line to stderr (no traceback) and return 2;
- `ingest` reads texts from `data/corpus` relative to the current directory;
- `manifest` never calls the runtime factory (it needs neither database nor Ollama) and takes `--tenant PATH`;
- `manifest --check` returns a non-zero code when files differ or the manifest file is missing.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
from pathlib import Path

import pytest
import yaml

from fakes import FakeLLM, FakeStore, chat_result, final_result, make_tenant, tool_result, write_tenant_yaml
from ngo_assistant.cli import Runtime, main
from ngo_assistant.config import Tenant, load_tenant
from ngo_assistant.eval.schema import load_testset

ROOT = Path(__file__).resolve().parents[1]
JSON_KEYS = {
    "variant", "question", "language", "answer", "citations", "abstained", "usage", "tool_calls",
    "tool_call_failures", "invalid_citations", "repaired_citations", "tool_trace", "latency_s",
}


def chat_plain():
    return chat_result("thinking")


def runtime(script=None, store=None):
    llm = FakeLLM(script)
    store = store if store is not None else FakeStore()
    return Runtime(tenant=make_tenant("a", "b"), store=store, llm=llm), store, llm


def call(argv, rt=None, stdin=""):
    out = io.StringIO()
    rt = rt or runtime()[0]
    code = main(argv, stdin=io.StringIO(stdin), stdout=out, factory=lambda: rt)
    return code, out.getvalue()


def last_json(text: str):
    lines = text.rstrip().splitlines()
    for start in range(len(lines)):
        try:
            return json.loads("\n".join(lines[start:]))
        except ValueError:
            continue
    raise AssertionError(f"no JSON at the end of output: {text!r}")


# ----------------------------------------------------------------------------- ask


def test_ask_json_prints_one_object_with_the_documented_keys():
    rt, _, _ = runtime([final_result("About 412 pairs.", ["a"])])
    code, out = call(["ask", "How many pairs?", "--json", "--language", "en"], rt)
    assert code == 0
    data = json.loads(out)
    assert set(data) == JSON_KEYS
    assert data["variant"] == "vector"
    assert data["question"] == "How many pairs?"
    assert data["language"] == "en"
    assert data["answer"] == "About 412 pairs."
    assert data["citations"] == ["a"]
    assert data["abstained"] is False
    assert set(data["usage"]) == {"input_tokens", "output_tokens", "embed_tokens", "model_calls"}
    assert data["usage"]["model_calls"] == 2
    assert data["tool_calls"] == 0 and data["tool_call_failures"] == 0
    assert (data["invalid_citations"], data["repaired_citations"]) == (0, 0)
    assert data["tool_trace"] == []
    assert data["latency_s"] >= 0


def test_ask_agentic_variant_reports_tool_trace():
    rt, _, llm = runtime([tool_result("list_sources"), chat_plain(), final_result("Done.", ["a"])])
    code, out = call(["ask", "Which sources?", "--variant", "agentic", "--json", "--language", "en"], rt)
    data = json.loads(out)
    assert code == 0
    assert data["variant"] == "agentic"
    assert data["tool_calls"] == 1
    assert data["tool_trace"][0]["name"] == "list_sources"
    assert data["usage"]["model_calls"] == 3


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Wie viel Strom wurde 2024 erzeugt?", "de"),
        ("Welche Größe haben die Moore?", "de"),
        ("Was ist der Unterschied zwischen Moor und Sumpf?", "de"),
        ("How much electricity was produced in 2024?", "en"),
        ("Moor restoration", "en"),
    ],
)
def test_ask_language_default_is_detected_from_umlauts_and_common_german_words(question, expected):
    rt, _, _ = runtime([final_result()])
    _, out = call(["ask", question, "--json"], rt)
    assert json.loads(out)["language"] == expected


def test_ask_explicit_language_wins_over_detection():
    rt, _, _ = runtime([final_result()])
    _, out = call(["ask", "Wie viel Strom?", "--json", "--language", "en"], rt)
    assert json.loads(out)["language"] == "en"


def test_ask_plain_output_shows_answer_and_citations():
    rt, _, _ = runtime([final_result("Peat stores carbon.", ["a"])])
    code, out = call(["ask", "What does peat do?", "--language", "en"], rt)
    assert code == 0
    assert "Peat stores carbon." in out
    assert "a" in out


def test_ask_warms_up_the_model_once_before_the_question():
    rt, _, llm = runtime([final_result()])
    call(["ask", "Question?", "--json"], rt)
    assert llm.warm_ups == 1


# ----------------------------------------------------------------------------- chat


def test_chat_reads_questions_from_stdin_until_quit_and_ignores_empty_lines():
    rt, _, llm = runtime([final_result("Answer one."), final_result("Answer three.")])
    code, out = call(["chat"], rt, stdin="Frage-eins\n\n   \nFrage-zwei\n/quit\nFrage-drei\n")
    assert code == 0
    assert "Answer one." in out and "Answer three." in out
    assert len(llm.chat_calls) == 2
    assert llm.remaining == 0


def test_chat_quit_stops_before_later_lines():
    rt, _, llm = runtime([final_result("Answer one.")])
    code, out = call(["chat"], rt, stdin="Frage-eins\n/quit\nFrage-zwei\n")
    assert code == 0
    assert len(llm.chat_calls) == 1


def test_chat_ends_on_eof_without_quit():
    rt, _, llm = runtime([final_result("Only answer.")])
    code, out = call(["chat"], rt, stdin="Single question")
    assert code == 0
    assert "Only answer." in out
    assert len(llm.chat_calls) == 1


def test_chat_variant_command_switches_the_variant():
    rt, _, llm = runtime([chat_plain(), final_result("From agentic.")])
    code, out = call(["chat"], rt, stdin="/variant agentic\nA question\n/quit\n")
    assert code == 0
    assert "From agentic." in out
    assert llm.chat_calls[0]["tools"] is not None  # agentic loop call first
    assert llm.embed_calls == []  # vector variant would have embedded the question


def test_chat_starts_with_the_variant_given_on_the_command_line():
    rt, _, llm = runtime([chat_plain(), final_result("From agentic.")])
    call(["chat", "--variant", "agentic"], rt, stdin="A question\n")
    assert llm.embed_calls == []


def test_chat_unknown_variant_keeps_the_current_one_and_does_not_crash():
    rt, _, llm = runtime([final_result("Still vector.")])
    code, out = call(["chat"], rt, stdin="/variant nonsense\nA question\n")
    assert code == 0
    assert "Still vector." in out
    assert llm.embed_calls == [["A question"]]


def test_chat_keeps_no_memory_between_questions():
    rt, _, llm = runtime([final_result("One."), final_result("Two.")])
    call(["chat"], rt, stdin="Frage-eins\nFrage-zwei\n")
    assert "Frage-eins" not in json.dumps(llm.chat_calls[1]["messages"])


# ----------------------------------------------------------------------------- eval


def write_testset(path: Path, n: int = 3) -> Path:
    rows = [
        {"id": f"c{i}", "category": "answerable", "language": "en", "question": f"Question number {i}?",
         "expected_answer": "x", "source_ids": ["a"]}
        for i in range(1, n + 1)
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    assert len(load_testset(path)) == n
    return path


def result_rows(out_dir: Path, variant="vector"):
    path = out_dir / f"{variant}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_eval_writes_one_jsonl_row_per_case_and_config_json(tmp_path):
    testset = write_testset(tmp_path / "ts.jsonl")
    rt, _, _ = runtime([final_result(f"Answer {i}", ["a"]) for i in range(3)])
    out_dir = tmp_path / "out"
    code, out = call(["eval", "--variant", "vector", "--testset", str(testset), "--out", str(out_dir)], rt)
    assert code == 0
    rows = result_rows(out_dir)
    assert [r["case_id"] for r in rows] == ["c1", "c2", "c3"]
    assert set(rows[0]) == {"case_id", "category", "question", "answer", "correct", "grounded"}
    assert rows[0]["answer"]["text"] == "Answer 0"
    assert rows[0]["answer"]["latency_s"] >= 0
    config = json.loads((out_dir / "config.json").read_text(encoding="utf-8"))
    assert config["variant"] == "vector"
    assert config["chat_model"] == "chat-m"
    assert config["model_digests"]
    assert "prompt_sha256" in config
    summary = last_json(out)
    assert summary["cases"] == 3
    assert summary["errors"] == 0


def test_eval_appends_each_row_immediately_so_an_interrupted_run_keeps_finished_cases(tmp_path):
    testset = write_testset(tmp_path / "ts.jsonl")
    rt, _, _ = runtime([final_result("Answer 1"), KeyboardInterrupt()])
    out_dir = tmp_path / "out"
    with contextlib.suppress(KeyboardInterrupt):
        call(["eval", "--variant", "vector", "--testset", str(testset), "--out", str(out_dir)], rt)
    rows = result_rows(out_dir)
    assert [r["case_id"] for r in rows] == ["c1"]


def test_eval_limit_runs_only_the_first_n_cases(tmp_path):
    testset = write_testset(tmp_path / "ts.jsonl")
    rt, _, llm = runtime([final_result("A"), final_result("B")])
    out_dir = tmp_path / "out"
    base = ["eval", "--variant", "vector", "--testset", str(testset), "--out", str(out_dir)]
    code, _ = call([*base, "--limit", "2"], rt)
    assert code == 0
    assert [r["case_id"] for r in result_rows(out_dir)] == ["c1", "c2"]
    assert len(llm.chat_calls) == 2


def test_eval_resume_skips_cases_already_in_the_jsonl(tmp_path):
    testset = write_testset(tmp_path / "ts.jsonl")
    out_dir = tmp_path / "out"
    base = ["eval", "--variant", "vector", "--testset", str(testset), "--out", str(out_dir)]
    call(base + ["--limit", "1"], runtime([final_result("first")])[0])
    assert [r["case_id"] for r in result_rows(out_dir)] == ["c1"]
    rt, _, llm = runtime([final_result("second"), final_result("third")])
    code, out = call(base + ["--resume"], rt)
    assert code == 0
    assert [r["case_id"] for r in result_rows(out_dir)] == ["c1", "c2", "c3"]
    assert result_rows(out_dir)[0]["answer"]["text"] == "first"  # not re-run
    assert len(llm.chat_calls) == 2
    assert last_json(out)["cases"] == 3


def test_eval_with_everything_done_and_resume_makes_no_model_call(tmp_path):
    testset = write_testset(tmp_path / "ts.jsonl", n=1)
    out_dir = tmp_path / "out"
    base = ["eval", "--variant", "vector", "--testset", str(testset), "--out", str(out_dir)]
    call(base, runtime([final_result("x")])[0])
    rt, _, llm = runtime([])
    assert call(base + ["--resume"], rt)[0] == 0
    assert llm.chat_calls == []
    assert len(result_rows(out_dir)) == 1


def test_eval_records_a_failing_case_in_the_file_and_still_exits_zero(tmp_path):
    testset = write_testset(tmp_path / "ts.jsonl", n=2)
    rt, _, _ = runtime([RuntimeError("model exploded"), final_result("fine")])
    out_dir = tmp_path / "out"
    code, out = call(["eval", "--variant", "vector", "--testset", str(testset), "--out", str(out_dir)], rt)
    assert code == 0
    rows = result_rows(out_dir)
    assert "model exploded" in rows[0]["answer"]["error"]
    assert rows[1]["answer"]["error"] is None
    assert last_json(out)["errors"] == 1


def test_eval_agentic_variant_writes_its_own_file(tmp_path):
    testset = write_testset(tmp_path / "ts.jsonl", n=1)
    rt, _, _ = runtime([chat_plain(), final_result("Done.")])
    out_dir = tmp_path / "out"
    code, _ = call(["eval", "--variant", "agentic", "--testset", str(testset), "--out", str(out_dir)], rt)
    assert code == 0
    assert result_rows(out_dir, "agentic")[0]["answer"]["text"] == "Done."
    assert json.loads((out_dir / "config.json").read_text(encoding="utf-8"))["variant"] == "agentic"


# ----------------------------------------------------------------------------- ingest


def test_ingest_loads_corpus_files_into_the_store(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    corpus = tmp_path / "data" / "corpus"
    corpus.mkdir(parents=True)
    (corpus / "a.txt").write_text("Text of a.\n\nMore of a.", encoding="utf-8")
    (corpus / "b.txt").write_text("Text of b.", encoding="utf-8")
    tenant_path = write_tenant_yaml(tmp_path / "tenant.yaml", make_tenant("a", "b"))
    rt, store, _ = runtime()
    code, _ = call(["ingest", "--tenant", str(tenant_path)], rt)
    assert code == 0
    assert store.counts()["documents"] == 2
    again, _ = call(["ingest", "--tenant", str(tenant_path)], rt)
    assert again == 0
    assert store.counts()["documents"] == 2


def test_ingest_with_missing_corpus_file_exits_2_with_one_line(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data" / "corpus").mkdir(parents=True)
    tenant_path = write_tenant_yaml(tmp_path / "tenant.yaml", make_tenant("a"))
    code, _ = call(["ingest", "--tenant", str(tenant_path)])
    err = capsys.readouterr().err
    assert code == 2
    assert "Traceback" not in err
    assert len([ln for ln in err.splitlines() if ln.strip()]) == 1


# ----------------------------------------------------------------------------- manifest


def raw_setup(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    content = b"<html>raw a</html>"
    (raw / "a.html").write_bytes(content)
    (raw / "a.meta.json").write_text(
        json.dumps({"id": "a", "url": "https://example.org/a", "sha256": hashlib.sha256(content).hexdigest(),
                    "fetched_at": "2026-10-14T19:31:46+00:00"}),
        encoding="utf-8",
    )
    tenant_path = write_tenant_yaml(tmp_path / "tenant.yaml", make_tenant("a"))
    return raw, tenant_path


def no_runtime():
    raise AssertionError("manifest must not need a runtime")


def run_manifest(args):
    out = io.StringIO()
    code = main(["manifest", *args], stdin=io.StringIO(""), stdout=out, factory=no_runtime)
    return code, out.getvalue()


def test_manifest_write_creates_the_manifest_file(tmp_path):
    raw, tenant_path = raw_setup(tmp_path)
    target = tmp_path / "MANIFEST.json"
    code, _ = run_manifest(["--write", "--raw", str(raw), "--out", str(target), "--tenant", str(tenant_path)])
    assert code == 0
    manifest = json.loads(target.read_text(encoding="utf-8"))
    assert set(manifest["sources"]) == {"a"}
    assert len(manifest["sources"]["a"]["sha256"]) == 64


def test_manifest_check_passes_when_raw_files_match(tmp_path):
    raw, tenant_path = raw_setup(tmp_path)
    target = tmp_path / "MANIFEST.json"
    args = ["--raw", str(raw), "--out", str(target), "--tenant", str(tenant_path)]
    run_manifest(["--write", *args])
    code, _ = run_manifest(["--check", *args])
    assert code == 0


def test_manifest_check_fails_and_names_the_changed_source(tmp_path):
    raw, tenant_path = raw_setup(tmp_path)
    target = tmp_path / "MANIFEST.json"
    args = ["--raw", str(raw), "--out", str(target), "--tenant", str(tenant_path)]
    run_manifest(["--write", *args])
    (raw / "a.html").write_bytes(b"changed")
    code, out = run_manifest(["--check", *args])
    assert code != 0
    assert "a" in out


def test_manifest_check_without_a_manifest_file_fails(tmp_path):
    raw, tenant_path = raw_setup(tmp_path)
    code, _ = run_manifest(["--check", "--raw", str(raw), "--out", str(tmp_path / "none.json"),
                            "--tenant", str(tenant_path)])
    assert code != 0


# ----------------------------------------------------------------------------- setup errors


@pytest.mark.parametrize(
    "argv",
    [["ask", "Question?"], ["chat"], ["eval", "--variant", "vector"], ["ingest", "--tenant", "tenants/moorfunke.yaml"]],
)
def test_unreachable_stack_gives_exit_code_2_and_one_line_without_traceback(argv, capsys):
    def broken_factory():
        raise ConnectionError("could not connect to server")

    code = main(argv, stdin=io.StringIO(""), stdout=io.StringIO(), factory=broken_factory)
    captured = capsys.readouterr()
    assert code == 2
    assert "Traceback" not in captured.err + captured.out
    lines = [ln for ln in captured.err.splitlines() if ln.strip()]
    assert len(lines) == 1
    assert "could not connect" in lines[0]


def test_missing_database_url_gives_exit_code_2_naming_the_variable(monkeypatch, capsys):
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    code = main(["ask", "Question?"], stdin=io.StringIO(""), stdout=io.StringIO())
    captured = capsys.readouterr()
    assert code == 2
    assert "DATABASE_URL" in captured.err
    assert "Traceback" not in captured.err + captured.out


def test_ingest_passes_the_manifest_hash_into_the_run_record(tmp_path, monkeypatch):
    from ngo_assistant.ingest import manifest_sha256

    monkeypatch.chdir(tmp_path)
    corpus = tmp_path / "data" / "corpus"
    corpus.mkdir(parents=True)
    (corpus / "a.txt").write_text("Text of a.", encoding="utf-8")
    manifest = {"generated": "2026-10-15", "sources": {}}
    (tmp_path / "data" / "MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    tenant_path = write_tenant_yaml(tmp_path / "tenant.yaml", make_tenant("a"))
    store = FakeStore()
    rt = Runtime(tenant=make_tenant("a"), store=store, llm=FakeLLM())
    code, _ = call(["ingest", "--tenant", str(tenant_path)], rt)
    assert code == 0
    assert store.runs[0]["manifest_sha256"] == manifest_sha256(manifest)


# ----------------------------------------------------------------------------- run record from the ingest run


def run_eval_config(tmp_path, store):
    testset = write_testset(tmp_path / "ts.jsonl", 1)
    rt, _, _ = runtime([final_result("A", ["a"])], store=store)
    out_dir = tmp_path / "out"
    code, _ = call(["eval", "--variant", "vector", "--testset", str(testset), "--out", str(out_dir)], rt)
    assert code == 0
    return json.loads((out_dir / "config.json").read_text(encoding="utf-8"))


def test_eval_config_records_the_last_ingest_run_from_the_store(tmp_path):
    store = FakeStore()
    store.record_run({"params": {"max_chars": 900, "overlap_chars": 100}, "embed_model": "bge-m3",
                      "embed_model_digest": "d1", "manifest_sha256": "a" * 64, "git_commit": "c1",
                      "finished": "2026-10-14T10:00:00+00:00"})
    config = run_eval_config(tmp_path, store)
    assert config["ingest"]["embed_model_digest"] == "d1"
    assert config["chunk_params"] == {"max_chars": 900, "overlap_chars": 100}
    assert config["chunk_params_source"] == "ingest_run"


def test_eval_without_an_ingest_run_warns_once_on_stderr_and_records_null(tmp_path, capsys):
    config = run_eval_config(tmp_path, FakeStore())
    assert config["ingest"] is None
    assert config["chunk_params_source"] == "defaults"
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and "ingest" in err[0]


def test_manifest_hash_is_resolved_against_the_repo_root_not_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = run_eval_config(tmp_path, FakeStore())
    assert config["manifest_sha256"] is not None


def test_eval_honours_ngo_top_k(tmp_path, monkeypatch):
    monkeypatch.setenv("NGO_TOP_K", "3")
    testset = write_testset(tmp_path / "ts.jsonl", 1)
    rt, store, _ = runtime([final_result("A", ["a"])])
    out_dir = tmp_path / "out"
    call(["eval", "--variant", "vector", "--testset", str(testset), "--out", str(out_dir)], rt)
    assert store.chunk_searches[0][1] == 3
    assert json.loads((out_dir / "config.json").read_text(encoding="utf-8"))["top_k"] == 3


@pytest.mark.parametrize("command", [["ingest"], ["manifest", "--check"], ["eval", "--variant", "vector"]])
def test_tenant_option_is_accepted_by_ingest_manifest_and_eval(command):
    from ngo_assistant.cli import _parser

    assert _parser().parse_args([*command, "--tenant", "x.yaml"]).tenant == "x.yaml"


# ----------------------------------------------------------------------------- abstained display

STANDARD_EN = "I don't know based on the available sources."
STANDARD_DE = "Das lässt sich anhand der Quellen nicht beantworten."


def test_ask_plain_abstained_english_shows_standard_line_and_raw_text():
    rt, _, _ = runtime([final_result("abstain", [], abstain=True)])
    code, out = call(["ask", "What is it?", "--language", "en"], rt)
    assert code == 0
    assert f"{STANDARD_EN} (model output: abstain)" in out.splitlines()
    assert "Abstained: yes" in out


def test_ask_plain_abstained_german_shows_german_standard_line():
    rt, _, _ = runtime([final_result("keine Ahnung", [], abstain=True)])
    code, out = call(["ask", "Was ist das?", "--language", "de"], rt)
    assert code == 0
    assert f"{STANDARD_DE} (model output: keine Ahnung)" in out.splitlines()
    assert STANDARD_EN not in out


def test_ask_plain_abstained_with_empty_text_has_no_parentheses():
    rt, _, _ = runtime([final_result("  ", [], abstain=True)])
    _, out = call(["ask", "What is it?", "--language", "en"], rt)
    assert STANDARD_EN in out.splitlines()
    assert "model output" not in out


def test_ask_plain_not_abstained_is_unchanged():
    rt, _, _ = runtime([final_result("Peat stores carbon.", ["a"])])
    _, out = call(["ask", "What does peat do?", "--language", "en"], rt)
    assert out.splitlines()[0] == "Peat stores carbon."
    assert STANDARD_EN not in out and STANDARD_DE not in out


def test_ask_json_abstained_keeps_raw_text_and_flag():
    rt, _, _ = runtime([final_result("abstain", [], abstain=True)])
    _, out = call(["ask", "What is it?", "--language", "de", "--json"], rt)
    payload = json.loads(out)
    assert payload["answer"] == "abstain" and payload["abstained"] is True
    assert STANDARD_DE not in out and STANDARD_EN not in out


def test_chat_displays_abstained_answers_by_the_detected_language():
    rt, _, _ = runtime([final_result("abstain", [], abstain=True), final_result("nein", [], abstain=True)])
    _, out = call(["chat"], rt, stdin="hello there\nWas ist das für ein Moor?\n/quit\n")
    assert f"{STANDARD_EN} (model output: abstain)" in out
    assert f"{STANDARD_DE} (model output: nein)" in out


# ----------------------------------------------------------------------------- variant C "hybrid"


class StubHybrid:
    """Stands in for ngo_assistant.retrieval.hybrid.HybridAnswerer, injected through the module the CLI imports."""

    name = "hybrid"
    instances: list = []
    abstain = False

    def __init__(self, tenant, store, llm, top_k=None, max_tool_calls=6, max_context_tokens=3000):
        self.args = (tenant, store, llm)
        self.top_k = 7
        self.max_tool_calls = max_tool_calls
        self.questions: list[str] = []
        StubHybrid.instances.append(self)

    def answer(self, question, language):
        from ngo_assistant.models import Answer, Citation

        self.questions.append(question)
        if StubHybrid.abstain:
            return Answer(text="abstain", abstained=True)
        return Answer(text="From hybrid.", citations=[Citation(source_id="a")], tool_calls=1,
                      tool_trace=[{"event": "tool_call", "name": "vector_search", "ok": True}])


@pytest.fixture
def hybrid_stub(monkeypatch):
    import sys
    import types

    StubHybrid.instances = []
    StubHybrid.abstain = False
    module = types.ModuleType("ngo_assistant.retrieval.hybrid")
    module.HybridAnswerer = StubHybrid  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ngo_assistant.retrieval.hybrid", module)
    return StubHybrid


def test_ask_hybrid_builds_the_answerer_with_tenant_store_llm_and_reports_the_variant(hybrid_stub):
    rt, store, llm = runtime()
    code, out = call(["ask", "Which sources?", "--variant", "hybrid", "--json", "--language", "en"], rt)
    data = json.loads(out)
    assert code == 0
    assert set(data) == JSON_KEYS
    assert data["variant"] == "hybrid"
    assert data["answer"] == "From hybrid." and data["citations"] == ["a"]
    assert data["tool_calls"] == 1 and data["tool_trace"][0]["name"] == "vector_search"
    assert hybrid_stub.instances[0].args == (rt.tenant, store, llm)


def test_ask_hybrid_plain_output_prints_the_tool_trace(hybrid_stub):
    code, out = call(["ask", "Which sources?", "--variant", "hybrid", "--language", "en"], runtime()[0])
    assert code == 0
    assert "Tool calls: 1 (0 failed)" in out
    assert "vector_search" in out


def test_ask_hybrid_abstained_display_is_the_same_as_for_the_other_variants(hybrid_stub):
    hybrid_stub.abstain = True
    _, out = call(["ask", "What is it?", "--variant", "hybrid", "--language", "en"], runtime()[0])
    assert f"{STANDARD_EN} (model output: abstain)" in out.splitlines()
    assert "Abstained: yes" in out
    _, js = call(["ask", "What is it?", "--variant", "hybrid", "--language", "en", "--json"], runtime()[0])
    assert json.loads(js)["answer"] == "abstain"


def test_chat_starts_with_hybrid_and_switches_with_variant_command(hybrid_stub):
    rt, _, _ = runtime([final_result("From vector.")])
    stdin = "One?\n/variant vector\nTwo?\n/variant hybrid\nThree?\n"
    code, out = call(["chat", "--variant", "hybrid"], rt, stdin=stdin)
    assert code == 0
    assert out.count("From hybrid.") == 2 and "From vector." in out
    assert "variant: hybrid" in out
    assert [inst.questions for inst in hybrid_stub.instances] == [["One?"], ["Three?"]]


def test_chat_unknown_variant_keeps_hybrid(hybrid_stub):
    code, out = call(["chat", "--variant", "hybrid"], runtime()[0], stdin="/variant bogus\nA question\n")
    assert code == 0
    assert "unknown variant 'bogus'" in out and "still hybrid" in out
    assert "From hybrid." in out
    assert len(hybrid_stub.instances) == 1


def test_eval_hybrid_run_record_takes_top_k_and_max_tool_calls_from_the_answerer(tmp_path, hybrid_stub):
    testset = write_testset(tmp_path / "ts.jsonl", n=2)
    out_dir = tmp_path / "out"
    code, out = call(["eval", "--variant", "hybrid", "--testset", str(testset), "--out", str(out_dir)], runtime()[0])
    assert code == 0
    config = json.loads((out_dir / "config.json").read_text(encoding="utf-8"))
    assert (config["variant"], config["top_k"], config["max_tool_calls"]) == ("hybrid", 7, 6)
    rows = result_rows(out_dir, "hybrid")
    assert [r["case_id"] for r in rows] == ["c1", "c2"]
    assert rows[0]["answer"]["text"] == "From hybrid."
    assert last_json(out)["cases"] == 2


@pytest.mark.parametrize("argv", [["ask", "Q?", "--variant", "bogus"], ["chat", "--variant", "bogus"],
                                  ["eval", "--variant", "bogus"]])
def test_invalid_variant_exits_2_with_a_message_naming_the_choices(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        main(argv, stdin=io.StringIO(""), stdout=io.StringIO(), factory=lambda: runtime()[0])
    assert exc.value.code == 2
    assert "hybrid" in capsys.readouterr().err


# ----------------------------------------------------------------------------- crawl
# Interface decisions made here (beyond contracts.md), to be confirmed by the orchestrator:
# - `crawl` never calls the runtime factory (like `manifest`);
# - the counts are printed as "<reason> <n>" / "<reason>: <n>" / "<reason>=<n>" (tests accept any non-word
#   separator) and files as "files <n>" or "<n> files"; the root id appears on the line of its totals;
# - `--list-skipped` prints one line per skipped entry holding its relpath and its reason;
# - an unknown `--root ID` and a tenant that has a `crawl` section but no `crawled_sources` (without --dry-run)
#   are setup errors: exit 2, one line on stderr naming the id / "crawled_sources";
# - `--dry-run` works without `crawled_sources` and still prints the counts;
# - a limit error writes NOTHING, not even for roots that were crawled before the failing one;
# - `ingest` prints the missing-listing warning on stderr as ONE line containing "crawl".


def crawl_setup(tmp_path, files=None, roots=None, listing=True, extra=None):
    """A tenant file with crawl roots under tmp_path/data/<id>; returns (tenant_path, listing_path)."""
    base = tmp_path / "data"
    roots = roots or {"docs": files if files is not None else {"a.txt": "Alpha distinct text.", "sub/b.md": "# Beta"}}
    crawl_cfg = []
    for rid, content in roots.items():
        d = base / rid
        d.mkdir(parents=True, exist_ok=True)
        for rel, text in content.items():
            f = d / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(text, encoding="utf-8")
        crawl_cfg.append({"id": rid, "path": str(d), "licence": "Own work", "licence_url": "internal:declared-by-owner",
                          "checked_on": "2026-10-16"})
    listing_path = tmp_path / "tenants" / "t.crawled.yaml"
    listing_path.parent.mkdir(exist_ok=True)
    data = {"slug": "t", "name": "T", "languages": ["en", "de"], "system_prompt": "x", "crawl": crawl_cfg}
    if listing:
        data["crawled_sources"] = str(listing_path)
    data.update(extra or {})
    tenant_path = tmp_path / "tenants" / "t.yaml"
    tenant_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return tenant_path, listing_path


def run_crawl(args, capsys=None):
    out = io.StringIO()
    code = main(["crawl", *args], stdin=io.StringIO(""), stdout=out, factory=no_runtime)
    return code, out.getvalue()


def snapshot(path):
    return sorted(str(p.relative_to(path)) for p in path.rglob("*"))


def test_crawl_writes_the_listing_and_prints_counts_per_root(tmp_path):
    tenant_path, listing = crawl_setup(tmp_path, files={"a.txt": "Alpha distinct text.", "b.md": "# Beta heading",
                                                         "skip.bin": "binary", ".hid.txt": "hidden"})
    code, out = run_crawl(["--tenant", str(tenant_path)])
    assert code == 0
    assert listing.is_file()
    assert [s["id"] for s in yaml.safe_load(listing.read_text(encoding="utf-8"))["sources"]] == [
        "docs-a-txt", "docs-b-md"]
    assert "docs" in out
    assert re.search(r"files\W+2\b|\b2\s+files", out)
    assert str(len("Alpha distinct text.") + len("# Beta heading")) in out
    assert re.search(r"unsupported_type\W+1\b", out) and re.search(r"hidden\W+1\b", out)
    assert [s.id for s in load_tenant(tenant_path).sources] == ["docs-a-txt", "docs-b-md"]


def test_crawl_dry_run_writes_nothing_and_prints_counts(tmp_path):
    tenant_path, listing = crawl_setup(tmp_path, files={"a.txt": "Alpha distinct text.", "skip.png": "png"})
    before = snapshot(tmp_path)
    code, out = run_crawl(["--tenant", str(tenant_path), "--dry-run"])
    assert code == 0
    assert not listing.exists()
    assert snapshot(tmp_path) == before
    assert "docs" in out and re.search(r"files\W+1\b|\b1\s+files", out) and re.search(r"unsupported_type\W+1\b", out)


def test_crawl_dry_run_does_not_touch_an_existing_listing(tmp_path):
    tenant_path, listing = crawl_setup(tmp_path)
    listing.write_text("# previous\nsources: []\n", encoding="utf-8")
    code, _ = run_crawl(["--tenant", str(tenant_path), "--dry-run"])
    assert code == 0
    assert listing.read_text(encoding="utf-8") == "# previous\nsources: []\n"


def test_crawl_dry_run_works_without_a_crawled_sources_setting(tmp_path):
    tenant_path, _ = crawl_setup(tmp_path, listing=False)
    code, out = run_crawl(["--tenant", str(tenant_path), "--dry-run"])
    assert code == 0 and "docs" in out


def test_crawl_without_crawled_sources_setting_is_a_setup_error(tmp_path, capsys):
    tenant_path, _ = crawl_setup(tmp_path, listing=False)
    code, _ = run_crawl(["--tenant", str(tenant_path)])
    err = capsys.readouterr().err
    assert code == 2 and "crawled_sources" in err and "Traceback" not in err
    assert len([ln for ln in err.splitlines() if ln.strip()]) == 1


def test_crawl_root_option_restricts_to_one_root(tmp_path):
    roots = {"alpha": {"one.txt": "text one"}, "beta": {"two.txt": "text two"}}
    tenant_path, listing = crawl_setup(tmp_path, roots=roots)
    code, out = run_crawl(["--tenant", str(tenant_path), "--root", "alpha"])
    assert code == 0
    assert "alpha" in out and "beta" not in out
    ids = [s["id"] for s in yaml.safe_load(listing.read_text(encoding="utf-8"))["sources"]]
    assert "alpha-one-txt" in ids and "beta-two-txt" not in ids


def test_crawl_unknown_root_id_is_a_setup_error(tmp_path, capsys):
    tenant_path, listing = crawl_setup(tmp_path)
    code, _ = run_crawl(["--tenant", str(tenant_path), "--root", "nope"])
    err = capsys.readouterr().err
    assert code == 2 and "nope" in err and "Traceback" not in err
    assert not listing.exists()


def test_crawl_list_skipped_prints_every_skipped_entry_with_its_reason(tmp_path):
    tenant_path, _ = crawl_setup(tmp_path, files={"keep.txt": "kept text", "ignored.bin": "x", ".dot.txt": "d",
                                                  "old.doc": "legacy", "empty.txt": ""})
    code, out = run_crawl(["--tenant", str(tenant_path), "--dry-run", "--list-skipped"])
    assert code == 0
    by_name = {name: ln for ln in out.splitlines() for name in ("ignored.bin", ".dot.txt", "old.doc", "empty.txt")
               if name in ln}
    assert "unsupported_type" in by_name["ignored.bin"]
    assert "hidden" in by_name[".dot.txt"]
    assert "legacy_office_format" in by_name["old.doc"]
    assert "empty" in by_name["empty.txt"]
    assert "keep.txt" not in "".join(ln for ln in out.splitlines() if "unsupported_type" in ln)


def test_crawl_without_list_skipped_does_not_print_the_skipped_names(tmp_path):
    tenant_path, _ = crawl_setup(tmp_path, files={"keep.txt": "kept text", "ignored.bin": "x"})
    _, out = run_crawl(["--tenant", str(tenant_path), "--dry-run"])
    assert "ignored.bin" not in out


def test_crawl_exit_1_when_the_tenant_has_no_crawl_section(tmp_path, capsys):
    tenant_path = write_tenant_yaml(tmp_path / "t.yaml", make_tenant("a"))
    code, _ = run_crawl(["--tenant", str(tenant_path)])
    err = capsys.readouterr().err
    assert code == 1 and "crawl" in err and "Traceback" not in err


def test_crawl_exit_1_on_limit_error_and_nothing_is_written_for_any_root(tmp_path, capsys):
    tenant_path, listing = crawl_setup(tmp_path, roots={"small": {"one.txt": "text one"}, "big": {}})
    big = tmp_path / "data" / "big"
    for i in range(5001):  # one more than CrawlLimits.max_files
        (big / f"f{i:05d}.txt").write_text(f"n{i}", encoding="utf-8")
    code, _ = run_crawl(["--tenant", str(tenant_path)])
    err = capsys.readouterr().err
    assert code == 1 and "Traceback" not in err
    assert not listing.exists()
    assert not [p for p in listing.parent.iterdir() if "crawled" in p.name]


def test_crawl_exit_2_for_a_missing_directory(tmp_path, capsys):
    tenant_path, listing = crawl_setup(tmp_path)
    (tmp_path / "data" / "docs" / "a.txt").unlink()
    (tmp_path / "data" / "docs" / "sub" / "b.md").unlink()
    (tmp_path / "data" / "docs" / "sub").rmdir()
    (tmp_path / "data" / "docs").rmdir()
    code, _ = run_crawl(["--tenant", str(tenant_path)])
    err = capsys.readouterr().err
    assert code == 2 and "Traceback" not in err
    assert len([ln for ln in err.splitlines() if ln.strip()]) == 1
    assert not listing.exists()


def test_crawl_exit_2_for_a_path_that_is_a_file(tmp_path, capsys):
    tenant_path, _ = crawl_setup(tmp_path)
    target = tmp_path / "data" / "docs"
    for p in sorted(target.rglob("*"), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()
    target.rmdir()
    target.write_text("not a directory", encoding="utf-8")
    code, _ = run_crawl(["--tenant", str(tenant_path)])
    assert code == 2 and "Traceback" not in capsys.readouterr().err


def test_crawl_exit_2_for_a_bad_tenant_file(tmp_path, capsys):
    tenant_path, _ = crawl_setup(tmp_path, extra={"crawl": [{"id": "docs", "path": "relative/dir",
                                                              "licence": "unclear", "licence_url": "x",
                                                              "checked_on": "2026-10-16"}]})
    code, _ = run_crawl(["--tenant", str(tenant_path)])
    err = capsys.readouterr().err
    assert code == 2 and "Traceback" not in err
    assert len([ln for ln in err.splitlines() if ln.strip()]) == 1


def test_crawl_exit_2_for_a_missing_tenant_file(tmp_path, capsys):
    code, _ = run_crawl(["--tenant", str(tmp_path / "absent.yaml")])
    assert code == 2 and "Traceback" not in capsys.readouterr().err


def test_crawl_listing_has_no_absolute_path_in_the_urls_and_ids_match_the_contract(tmp_path):
    tenant_path, listing = crawl_setup(tmp_path, files={"Sub Dir/Report 2024.txt": "text of the report"})
    assert run_crawl(["--tenant", str(tenant_path)])[0] == 0
    [entry] = yaml.safe_load(listing.read_text(encoding="utf-8"))["sources"]
    assert entry["id"] == "docs-sub-dir-report-2024-txt"
    assert entry["url"] == "file:docs/Sub Dir/Report 2024.txt"
    assert entry["kind"] == "file" and entry["path"].startswith(str(tmp_path))


def test_crawl_twice_gives_an_identical_listing(tmp_path):
    tenant_path, listing = crawl_setup(tmp_path)
    run_crawl(["--tenant", str(tenant_path)])
    first = listing.read_bytes()
    run_crawl(["--tenant", str(tenant_path)])
    assert listing.read_bytes() == first


def ingest_setup(tmp_path, monkeypatch, listing_exists: bool, with_crawl: bool = True):
    monkeypatch.chdir(tmp_path)
    corpus = tmp_path / "data" / "corpus"
    corpus.mkdir(parents=True)
    (corpus / "a.txt").write_text("Text of a.", encoding="utf-8")
    base = make_tenant("a")
    listing = tmp_path / "t.crawled.yaml"
    if listing_exists:
        listing.write_text("# GENERATED by ngo-assistant crawl; do not edit; gitignored\nsources: []\n",
                           encoding="utf-8")
    extra = {}
    if with_crawl:
        from ngo_assistant.config import CrawlRoot  # lazy: the module under test may not have it yet

        extra = {"crawl": [CrawlRoot(id="docs", path=str(tmp_path), licence="Own work",
                                     licence_url="internal:declared-by-owner", checked_on="2026-10-16")],
                 "crawled_sources": str(listing)}
    tenant = Tenant(slug=base.slug, name=base.name, languages=base.languages, system_prompt=base.system_prompt,
                    sources=base.sources, **extra)
    return tenant, write_tenant_yaml(tmp_path / "tenant.yaml", tenant)


def test_ingest_warns_in_one_line_when_crawl_is_configured_but_the_listing_is_missing(tmp_path, monkeypatch, capsys):
    tenant, tenant_path = ingest_setup(tmp_path, monkeypatch, listing_exists=False)
    rt = Runtime(tenant=tenant, store=FakeStore(), llm=FakeLLM())
    code, _ = call(["ingest", "--tenant", str(tenant_path)], rt)
    err = capsys.readouterr().err
    assert code == 0
    warning = [ln for ln in err.splitlines() if "crawl" in ln.lower()]
    assert len(warning) == 1 and "warning" in warning[0].lower()
    assert "Traceback" not in err


def test_ingest_prints_no_crawl_warning_when_the_listing_exists(tmp_path, monkeypatch, capsys):
    tenant, tenant_path = ingest_setup(tmp_path, monkeypatch, listing_exists=True)
    rt = Runtime(tenant=tenant, store=FakeStore(), llm=FakeLLM())
    code, _ = call(["ingest", "--tenant", str(tenant_path)], rt)
    assert code == 0
    assert "crawl" not in capsys.readouterr().err.lower()


def test_ingest_prints_no_crawl_warning_for_a_tenant_without_crawl(tmp_path, monkeypatch, capsys):
    tenant, tenant_path = ingest_setup(tmp_path, monkeypatch, listing_exists=False, with_crawl=False)
    rt = Runtime(tenant=tenant, store=FakeStore(), llm=FakeLLM())
    code, _ = call(["ingest", "--tenant", str(tenant_path)], rt)
    assert code == 0
    assert "crawl" not in capsys.readouterr().err.lower()
