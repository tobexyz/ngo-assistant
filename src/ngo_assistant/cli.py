"""Command line: ingest, manifest, ask, chat, eval (contracts.md "cli.py").

Expected setup problems (database or Ollama unreachable, DATABASE_URL unset, missing corpus files) print ONE
line to stderr and return exit code 2, never a traceback. Environment values and the database URL are never
printed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from ngo_assistant.chunking import ChunkParams
from ngo_assistant.config import Tenant, load_tenant
from ngo_assistant.eval.metrics import summarize
from ngo_assistant.eval.runner import result_row, run
from ngo_assistant.eval.schema import CaseResult, EvalCase, load_testset
from ngo_assistant.ingest import build_manifest, check_manifest, ingest
from ngo_assistant.models import Answer
from ngo_assistant.retrieval.base import Answerer
from ngo_assistant.runinfo import build_run_record

DEFAULT_TENANT = "tenants/moorfunke.yaml"
DEFAULT_TESTSET = "evals/testset.jsonl"
CORPUS_DIR = Path("data/corpus")
RAW_DIR = Path("data/raw")
MANIFEST_PATH = Path("data/MANIFEST.json")


def repo_root() -> Path:
    """Directory containing pyproject.toml, found by walking up from this file (not the working directory)."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return Path.cwd()
VARIANTS = ("vector", "agentic", "hybrid")
TOOL_VARIANTS = ("agentic", "hybrid")  # variants whose plain output shows the tool trace

_GERMAN_WORDS = frozenset(
    [
        "der", "die", "das", "und", "ist", "wie", "was", "welche", "nicht",
        "ein", "eine", "wird", "werden", "laut", "im", "für", "von", "zu",
    ]
)
_AMBIGUOUS_WORDS = frozenset({"was"})  # English "was": counts as German only as the first word of the text


@dataclass
class Runtime:
    tenant: Tenant
    store: Any  # ngo_assistant.db.Store
    llm: Any  # ngo_assistant.llm.LLMClient (or a fake)


class SetupError(Exception):
    """An expected problem with the environment; reported as one line, exit code 2."""


def detect_language(text: str) -> str:
    """'de' when the text has an umlaut or sharp s, or contains one of a few common German function words
    (der, die, das, und, ist, wie, was, welche, nicht, ein, eine, wird, werden, laut, im, für, von, zu);
    otherwise 'en'. 'was' counts only as the first word, because it is also an English verb."""
    if re.search("[äöüÄÖÜß]", text):
        return "de"
    words = re.findall(r"[^\W\d_]+", text.lower())
    for position, word in enumerate(words):
        if word in _GERMAN_WORDS and (word not in _AMBIGUOUS_WORDS or position == 0):
            return "de"
    return "en"


# ----------------------------------------------------------------------------- runtime


def _real_runtime(tenant_path: str) -> Runtime:
    from ngo_assistant.db import PostgresStore
    from ngo_assistant.llm import LLMClient

    tenant = load_tenant(tenant_path)
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SetupError("DATABASE_URL is not set (copy .env.example to .env and export it, e.g. via make)")
    # Local CPU inference is slow on a cold model; the default client timeout is too short for a full eval.
    os.environ.setdefault("NGO_LLM_TIMEOUT_S", "900")
    return Runtime(tenant=tenant, store=PostgresStore(database_url), llm=LLMClient())


def _one_line(exc: BaseException) -> str:
    text = " ".join(str(exc).split()) or type(exc).__name__
    secret = os.environ.get("DATABASE_URL")
    if secret:
        text = text.replace(secret, "[REDACTED]")
    return text


def _setup_errors() -> tuple[type[BaseException], ...]:
    import httpx
    import ollama
    import psycopg

    return (SetupError, ConnectionError, OSError, ValueError, psycopg.Error, httpx.TransportError,
            ollama.ResponseError)


def _build_answerer(variant: str, rt: Runtime) -> Answerer:
    if variant == "vector":
        from ngo_assistant.retrieval.vector import VectorAnswerer

        return VectorAnswerer(rt.tenant, rt.store, rt.llm)
    if variant == "agentic":
        from ngo_assistant.retrieval.agentic import AgenticAnswerer

        return AgenticAnswerer(rt.tenant, rt.store, rt.llm)
    if variant == "hybrid":
        from ngo_assistant.retrieval.hybrid import HybridAnswerer

        return HybridAnswerer(rt.tenant, rt.store, rt.llm)
    raise ValueError(f"unknown variant {variant!r}; choose one of: {', '.join(VARIANTS)}")


# ----------------------------------------------------------------------------- output


def _citation_ids(answer: Answer) -> list[str]:
    return [c.source_id for c in answer.citations]


def _json_payload(variant: str, question: str, language: str, answer: Answer) -> dict[str, Any]:
    usage = answer.usage
    return {
        "variant": variant,
        "question": question,
        "language": language,
        "answer": answer.text,
        "citations": _citation_ids(answer),
        "abstained": answer.abstained,
        "usage": {
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "embed_tokens": usage.embed_tokens,
            "model_calls": usage.model_calls,
        },
        "tool_calls": answer.tool_calls,
        "tool_call_failures": answer.tool_call_failures,
        "invalid_citations": answer.invalid_citations,
        "repaired_citations": answer.repaired_citations,
        "tool_trace": answer.tool_trace,
        "latency_s": answer.latency_s,
    }


ABSTAIN_LINES = {
    "en": "I don't know based on the available sources.",
    "de": "Das lässt sich anhand der Quellen nicht beantworten.",
}


def _display_text(answer: Answer, language: str) -> str:
    """Display only: an abstained answer shows the standard line plus the model's raw text in parentheses."""
    if not answer.abstained:
        return answer.text
    line = ABSTAIN_LINES.get(language, ABSTAIN_LINES["en"])
    raw = answer.text.strip()
    return f"{line} (model output: {raw})" if raw else line


def _print_plain(out: TextIO, variant: str, answer: Answer, language: str = "en") -> None:
    usage = answer.usage
    print(_display_text(answer, language), file=out)
    print(f"Citations: {', '.join(_citation_ids(answer)) or '-'}", file=out)
    print(f"Abstained: {'yes' if answer.abstained else 'no'}", file=out)
    print(
        f"Usage: input {usage.input_tokens}, output {usage.output_tokens}, embed {usage.embed_tokens}, "
        f"model calls {usage.model_calls}; latency {answer.latency_s:.1f} s",
        file=out,
    )
    if variant in TOOL_VARIANTS:
        print(f"Tool calls: {answer.tool_calls} ({answer.tool_call_failures} failed)", file=out)
        for entry in answer.tool_trace:
            print("  " + json.dumps(entry, ensure_ascii=False), file=out)
    if answer.invalid_citations or answer.repaired_citations:
        print(f"Citations dropped: {answer.invalid_citations}, repaired: {answer.repaired_citations}", file=out)


def _ask_one(answerer: Answerer, question: str, language: str) -> Answer:
    start = time.perf_counter()
    answer = answerer.answer(question, language)
    return answer.model_copy(update={"latency_s": time.perf_counter() - start})


# ----------------------------------------------------------------------------- commands


def _cmd_ingest(args: argparse.Namespace, rt: Runtime, out: TextIO) -> int:
    manifest = None
    if MANIFEST_PATH.is_file():
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    create_schema = getattr(rt.store, "create_schema", None)
    if callable(create_schema):
        create_schema()
    result = ingest(rt.tenant, rt.store, rt.llm, CORPUS_DIR, rebuild=args.rebuild, manifest=manifest)
    print(
        f"documents written: {result.documents}, skipped: {result.skipped}, chunks: {result.chunks}, "
        f"embed tokens: {result.embed_tokens}",
        file=out,
    )
    if result.drift:
        print(f"drift (raw file differs from the manifest or is missing): {', '.join(result.drift)}", file=out)
    return 0


def _cmd_manifest(args: argparse.Namespace, out: TextIO) -> int:
    raw_dir, target = Path(args.raw), Path(args.out)
    if args.write:
        manifest = build_manifest(raw_dir, load_tenant(args.tenant))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
                          encoding="utf-8")
        print(f"wrote {target} ({len(manifest['sources'])} sources)", file=out)
        return 0
    if not target.is_file():
        print(f"manifest file missing: {target}", file=out)
        return 1
    changed = check_manifest(json.loads(target.read_text(encoding="utf-8")), raw_dir)
    if changed:
        print(f"changed or missing sources: {', '.join(changed)}", file=out)
        return 1
    print("manifest matches the raw files", file=out)
    return 0


def _cmd_ask(args: argparse.Namespace, rt: Runtime, out: TextIO) -> int:
    answerer = _build_answerer(args.variant, rt)
    language = args.language or detect_language(args.question)
    rt.llm.warm_up()
    answer = _ask_one(answerer, args.question, language)
    if args.json:
        print(json.dumps(_json_payload(args.variant, args.question, language, answer), ensure_ascii=False), file=out)
    else:
        _print_plain(out, args.variant, answer, language)
    return 0


def _cmd_chat(args: argparse.Namespace, rt: Runtime, stdin: TextIO, out: TextIO) -> int:
    variant = args.variant
    answerer = _build_answerer(variant, rt)
    rt.llm.warm_up()
    for raw in stdin:
        line = raw.strip()
        if not line:
            continue
        if line == "/quit":
            break
        if line.startswith("/variant"):
            name = line[len("/variant"):].strip()
            if name in VARIANTS:
                variant, answerer = name, _build_answerer(name, rt)
                print(f"variant: {variant}", file=out)
            else:
                print(f"unknown variant {name!r}; choose one of: {', '.join(VARIANTS)} (still {variant})", file=out)
            continue
        language = detect_language(line)
        answer = _ask_one(answerer, line, language)
        _print_plain(out, variant, answer, language)
    return 0


def select_cases(cases: list[EvalCase], limit: int | None) -> list[EvalCase]:
    """First `limit` cases in file order; when `limit` is at most the number of categories, the first case of
    each category in order of appearance (round-robin), so a smoke run touches every category it can. The
    selection is returned in file order."""
    if limit is None or limit >= len(cases):
        return list(cases)
    categories: list[Any] = []
    for case in cases:
        if case.category not in categories:
            categories.append(case.category)
    if limit > len(categories):
        return cases[:limit]
    queues = [[c for c in cases if c.category == cat] for cat in categories]
    chosen: set[str] = set()
    depth = 0
    while len(chosen) < limit:
        for queue in queues:
            if depth < len(queue) and len(chosen) < limit:
                chosen.add(queue[depth].id)
        depth += 1
    return [c for c in cases if c.id in chosen]


def _read_rows(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                rows[row["case_id"]] = row
    return rows


def _cmd_eval(args: argparse.Namespace, rt: Runtime, out: TextIO) -> int:
    cases = select_cases(load_testset(args.testset), args.limit)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / f"{args.variant}.jsonl"
    answerer = _build_answerer(args.variant, rt)

    done = _read_rows(results_path) if args.resume else {}
    if not args.resume:
        results_path.write_text("", encoding="utf-8")
    ingest_record = rt.store.last_ingest_run()
    if ingest_record is None:
        print("warning: no ingest run found in the database; chunk parameters and embedding model of the "
              "indexed data are unknown (config.json: ingest = null)", file=sys.stderr)
    record = build_run_record(
        rt.tenant, rt.llm, variant=args.variant, chunk_params=ChunkParams(), ingest_record=ingest_record,
        top_k=getattr(answerer, "top_k", None), max_tool_calls=getattr(answerer, "max_tool_calls", None),
        manifest_path=repo_root() / MANIFEST_PATH,
    )
    (out_dir / "config.json").write_text(json.dumps(record, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
                                         encoding="utf-8")

    pending = [c for c in cases if c.id not in done]
    if pending:
        rt.llm.warm_up()
    results: dict[str, CaseResult] = {}
    for case in cases:
        row = done.get(case.id)
        if row is not None:
            results[case.id] = CaseResult(case=case, answer=Answer.model_validate(row["answer"]),
                                          correct=row.get("correct"), grounded=row.get("grounded"))
    with results_path.open("a", encoding="utf-8") as fh:
        for case in pending:
            [result] = run(answerer, [case])
            fh.write(json.dumps(result_row(result), ensure_ascii=False) + "\n")
            fh.flush()
            results[case.id] = result
    print(json.dumps(summarize([results[c.id] for c in cases]), ensure_ascii=False), file=out)
    return 0


# ----------------------------------------------------------------------------- parser and main


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ngo-assistant", description="White-label assistant for environmental NGOs.")
    sub = parser.add_subparsers(dest="command", required=True)

    def tenant_arg(p: argparse.ArgumentParser) -> None:
        p.add_argument("--tenant", default=DEFAULT_TENANT, help="tenant YAML file (default: %(default)s)")

    p = sub.add_parser("ingest", help="chunk, embed and store the corpus (data/corpus) in postgres")
    tenant_arg(p)
    p.add_argument("--rebuild", action="store_true", help="re-chunk and re-embed unchanged documents too")

    p = sub.add_parser("manifest", help="write or check data/MANIFEST.json (raw file hashes)")
    tenant_arg(p)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="write the manifest from the raw files")
    mode.add_argument("--check", action="store_true", help="list sources whose raw file differs; exit 1 if any")
    p.add_argument("--raw", default=str(RAW_DIR), help="raw directory (default: %(default)s)")
    p.add_argument("--out", default=str(MANIFEST_PATH), help="manifest file (default: %(default)s)")

    p = sub.add_parser("ask", help="answer one question")
    tenant_arg(p)
    p.add_argument("question")
    p.add_argument("--variant", choices=VARIANTS, default="vector")
    p.add_argument("--language", choices=("de", "en"),
                   help="default: detected from the question (de for umlauts or common German words, else en)")
    p.add_argument("--json", action="store_true", help="print one JSON object")

    p = sub.add_parser("chat", help="read questions from stdin, one per line (/variant NAME, /quit); no memory")
    tenant_arg(p)
    p.add_argument("--variant", choices=VARIANTS, default="vector")

    p = sub.add_parser("eval", help="run a variant over the test set")
    tenant_arg(p)
    p.add_argument("--variant", choices=VARIANTS, required=True)
    p.add_argument("--testset", default=DEFAULT_TESTSET)
    p.add_argument("--limit", type=int, help="first N cases in file order; when N is at most the number of "
                   "categories, the first case of each category in turn, so a smoke run touches every category")
    p.add_argument("--out", default="results/run", help="output directory: <variant>.jsonl and config.json")
    p.add_argument("--resume", action="store_true", help="skip case ids already present in <variant>.jsonl")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    factory: Callable[[], Runtime] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    stdin = stdin if stdin is not None else sys.stdin
    out = stdout if stdout is not None else sys.stdout
    try:
        if args.command == "manifest":
            return _cmd_manifest(args, out)
        rt = (factory or (lambda: _real_runtime(args.tenant)))()
        try:
            if args.command == "ingest":
                return _cmd_ingest(args, rt, out)
            if args.command == "ask":
                return _cmd_ask(args, rt, out)
            if args.command == "chat":
                return _cmd_chat(args, rt, stdin, out)
            return _cmd_eval(args, rt, out)
        finally:
            close = getattr(rt.store, "close", None)
            if callable(close):
                close()
    except _setup_errors() as exc:
        print(f"error: {_one_line(exc)}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
