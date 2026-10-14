# Tasks: The assistant (ingest, vector variant, agentic variant, chat CLI, eval CLI)

Plan: `.claude/specs/2026-10-14-assistant/requirements.md`, `design.md` and `contracts.md` (authoritative module interfaces for tests and implementations; changes to it are logged in decisions.md)
No new runtime dependency is expected (`ollama`, `psycopg[binary]`, `pgvector`, `pydantic`, `PyYAML` are pinned).
If a task needs one, it stops and reports; the orchestrator decides (7-day rule, exact pin).

## Group 1: Research, entry point, test skeletons (parallel)

- [x] 1.1 Research and document the APIs this spec relies on | `docs/tech.md`
  - **Accept**: `docs/tech.md` has, with source URL or command output and date: Ollama structured outputs (`format` JSON schema in `chat`, Python client parameter and response, behaviour combined with `tools`, verified against the running 0.40.0 stack with `llama3.2:1b` by one real call each, results labelled single observations); `ollama.Client.show`/`list` fields that give a model digest; pgvector 0.8.7 HNSW syntax and parameters (`vector_cosine_ops`, `m`, `ef_construction`, `hnsw.ef_search`) and `<=>` ordering; Postgres 17 full-text search for Variant A (`to_tsvector('simple', ...)` generated column, GIN index, `plainto_tsquery`, `ts_rank`, `ts_headline` options); psycopg 3.3.6 patterns for upserts, `executemany`, transactions and `register_vector`; how to read token counts for a request that uses `format`.
  - **Verify**: each row has a URL or pasted output; the live calls are pasted (short).
  - **Constraints**: no facts from memory; may start nothing except read-only/test calls against the running stack; edit only docs/tech.md.
- [x] 1.2 Entry point, Makefile skeleton, `Answer` fields | `pyproject.toml`, `Makefile`, `src/ngo_assistant/models.py`, `tests/test_models.py`
  - **Accept**: `[project.scripts] ngo-assistant = "ngo_assistant.cli:main"`; Makefile targets `up`, `models`, `fetch`, `corpus`, `ingest`, `data`, `test`, `eval-smoke`, `eval`, `reproduce-offline` with `.PHONY`, `set -e` semantics, `.env` loaded via `include`/`export` guard that fails clearly if `.env` is missing, no secrets echoed; `Answer` gains `tool_trace: list[dict] = []` and `invalid_citations: int = 0` (old data still valid; test).
  - **Verify**: `make -n data` prints the chain; `.venv/bin/pytest tests/test_models.py -q`; `.venv/bin/ruff check . && .venv/bin/mypy src`
  - **Constraints**: targets only call commands that exist after later groups; do not run network targets.
- [x] 1.3 Test skeletons (red) | `tests/test_chunking.py`, `tests/test_prompt.py`, `tests/test_tools.py`, `tests/test_vector_answerer.py`, `tests/test_agentic_answerer.py`, `tests/test_cli.py`, `tests/test_runinfo.py`, `tests/test_ingest.py`, `tests/integration/test_pipeline.py`
  - **Accept**: tests encode design.md contracts using fakes (fake `LLMClient`, in-memory fake store implementing the store interface from design.md): chunking determinism/overlap/limits/heading metadata; prompt block format (untrusted marker, ids, escaping of `</source>` inside text), citation parsing: exact ids kept, strings containing exactly one known id mapped and counted in `repaired_citations`, others dropped and counted in `invalid_citations`; `abstain` taken from the model as is; tool validation (unknown tool, extra args, wrong types, limit bounds); VectorAnswerer usage sums embed + final call and returns abstained from the schema; AgenticAnswerer: cap at 6 calls then forced final call, loop detection, failure counting rules, tool trace content, injection text inside a tool result does not change the loop; CLI: `ask --json` shape, `eval --resume` skips done cases; run record content; ingest idempotency against the fake store; integration test (marked) for real ingest + both variants on the live stack.
  - **Verify**: `.venv/bin/pytest -q` collects; new unit tests fail ONLY for missing implementation; ruff clean.
  - **Constraints**: tests only; do not touch src/ except what 1.2 owns.

## Group 2: Foundations (parallel, disjoint files)

- [x] 2.0 Decouple the shared test fakes | `tests/fakes.py`
  - **Accept**: `tests/fakes.py` imports contract modules lazily or under `TYPE_CHECKING` so each test file can be collected as soon as ITS OWN module exists (for example `tests/test_chunking.py` needs only `ngo_assistant.chunking`; `tests/test_tools.py` needs `retrieval.tools` and `db` types; the fakes build store result objects by importing `ngo_assistant.db` inside the methods that return them); no change to what the tests assert.
  - **Verify**: `.venv/bin/python -c "import ast,sys; ast.parse(open('tests/fakes.py').read())"`; `.venv/bin/pytest tests/test_llm.py -q` still collects; `grep -n "^from ngo_assistant\|^import ngo_assistant" tests/fakes.py` shows only modules that already exist.
  - **Constraints**: run FIRST (alone) before the other Group 2 tasks start; tests only.

- [x] 2.1 Chunker | `src/ngo_assistant/chunking.py`
  - **Accept**: `tests/test_chunking.py` green; deterministic (same input, same chunk sha256 list); no chunk above `max_chars` except a single unsplittable sentence (documented); heading metadata.
  - **Verify**: `.venv/bin/pytest tests/test_chunking.py -q && .venv/bin/ruff check . && .venv/bin/mypy src`
- [x] 2.2 Database store | `src/ngo_assistant/db.py` (types, `Store` protocol, `PostgresStore(database_url, schema)`, schema + indexes, FTS, vector search)
- [x] 2.6 Ingest and manifest | `src/ngo_assistant/ingest.py` (`ingest`, `IngestResult`, `build_manifest`, `check_manifest`, `manifest_sha256`); `data/MANIFEST.json` is generated in Group 4
  - **Accept**: schema and indexes per design.md created idempotently; ingest from `data/corpus/` for every tenant source (real + synthetic), verified against `data/MANIFEST.json` for real sources (drift = warning with ids, not failure); embeddings in batches with token usage summed; idempotent re-run; `--rebuild`; `ingest_runs` row; manifest `write` from `data/raw/*.meta.json`, `check` compares sha256.
  - **Verify**: unit tests green with the fake store; `.venv/bin/ruff check . && .venv/bin/mypy src`
  - **Constraints**: do not run against the real stack in this task (Group 4); parametrised SQL only, no string-built SQL with data.
- [x] 2.3 Prompt, answer contract, run record | `src/ngo_assistant/prompt.py`, `src/ngo_assistant/runinfo.py`, `src/ngo_assistant/models.py` (add `repaired_citations: int = 0` to `Answer` with a test)
  - **Accept**: `tests/test_prompt.py` and `tests/test_runinfo.py` green; the same function builds the system prompt for both variants (hash recorded); answer JSON schema; citation parsing; source block with the untrusted line and escaping; run record gathers model names, digests (via an injected callable), params, prompt hash, git commit (subprocess `git rev-parse`, tolerate absence), manifest hash.
  - **Verify**: as above.
- [x] 2.4 Agentic tools | `src/ngo_assistant/retrieval/tools.py`
  - NOTE: 47/48 tests pass; test_read_source_second_part_continues_the_document is wrong (digit pattern period 10 divides 1500, so parts 0 and 1 are identical).
  - **Accept**: `tests/test_tools.py` green; tool JSON schemas for `list_sources`, `search_sources`, `read_source`; `validate_tool_call` (allowlist, additional properties rejected, types, bounds); execution functions against a store interface (SQL implemented in db.py's store class by task 2.2 contract: `search(query, limit)`, `read(source_id, part)`, `list()`); snippets and parts truncated to the limits.
  - **Verify**: as above.
  - **Constraints**: model output is untrusted; never build SQL from arguments except as bound parameters.

- [x] 2.5 LLM client extensions | `src/ngo_assistant/llm.py`, `tests/test_llm.py`
  - **Accept**: `chat(..., format=...)`, `model_digests()`, `warm_up()` per `contracts.md`; `tools` and `format` together raise `ValueError`; existing llm tests unchanged and green; new tests (written in 1.3) green.
  - **Verify**: `.venv/bin/pytest tests/test_llm.py -q && .venv/bin/ruff check . && .venv/bin/mypy src`
  - **Constraints**: only documented ollama API (docs/tech.md sections 11-12); no behaviour change for existing callers.

## Group 3: Variants and CLI (parallel)

- [x] 3.1 VectorAnswerer | `src/ngo_assistant/retrieval/vector.py`
  - **Accept**: `tests/test_vector_answerer.py` green; uses `prompt.py` for everything shared; usage = embed + final call; top-k from constructor/env `NGO_TOP_K` default 4; context budget check (at most 3000 tokens of retrieved text), warm-up call.
  - **Verify**: pytest, ruff, mypy.
- [x] 3.2 AgenticAnswerer | `src/ngo_assistant/retrieval/agentic.py`
  - **Accept**: `tests/test_agentic_answerer.py` green; loop rules and failure counting per design.md; usage summed over every call; trace recorded; final answer via the shared contract.
  - **Verify**: pytest, ruff, mypy.
- [x] 3.3 CLI | `src/ngo_assistant/cli.py`
  - **Accept**: `tests/test_cli.py` green: `ingest`, `manifest`, `ask` (`--json`), `chat` (REPL, `/variant`, `/quit`, reads stdin lines so it is testable), `eval` (`--limit`, `--resume`, writes `config.json` with the run record and one JSON line per case immediately); exit codes; no stack trace for expected errors (stack down, missing `.env`).
  - **Verify**: pytest, ruff, mypy; `.venv/bin/ngo-assistant --help`.

## Group 4: Real run and reproducibility check (no code changes expected)

- [x] 4.1 Bring the data in from a clean database | `data/MANIFEST.json`, decisions.md
  - **Accept**: stack up; `make models`; `data/MANIFEST.json` written from the existing `data/raw`; `make ingest` loads 22 documents and their chunks; second `make ingest` changes nothing (row counts and chunk hashes equal, recorded); `ingest --rebuild` after dropping the volume gives identical chunk hashes; chunk count, embed tokens and wall time recorded in decisions.md.
  - **Verify**: SQL counts and hash comparison output pasted.
- [!] 4.2 Integration tests and smoke eval | `results/` (gitignored), decisions.md
  - **Accept**: `pytest -m integration` green; `make eval-smoke` (5 cases per variant, chosen as one per category incl. one injection) writes results and metrics for both variants; the injection canary check, tokens, latency and tool-call failures recorded; first impressions (does `llama3.2:1b` call tools? does structured output hold?) noted as single observations.
  - **Verify**: commands and result files listed.
  - NOTE 4.2: 7/8 integration tests pass; test_vector_answerer_returns_a_valid_answer_with_a_citation failed once (1B model answered '412' with no citation). The smoke selection contained no injection case (canary not measured). See decisions.md. Drop-the-volume rebuild not run by the agent (rebuild_check2 schema used instead).

## Group 5: Decisions and documentation (final)

- [ ] 5.1 ADRs | `docs/adr/007-chunking.md`, `008-answer-contract.md`, `009-agentic-tools.md`
  - **Accept**: template followed, cite tech.md and measurements; defaults labelled untuned; open questions for the user.
- [ ] 5.2 Update documentation for plan changes | `README.md`, `docs/`
  - **Accept**: README quick start (`make data`, `ngo-assistant ask`, `chat`, `eval`), reproducibility section (manifest, run record, what needs network), layout, status (what is implemented, what is not: judge, report, hybrid); no stale "stub" text.
  - **Verify**: `grep -rn 'TODO\|FIXME\|PLACEHOLDER' README.md docs/ || true`; every command in the quick start runs.
  - **Constraints**: do not describe unmeasured behaviour as results.


## Fix Group 1: Address review cycle 1 of Groups 1-2 (apply AFTER the Group 4 real run has finished: it rewrites ingest.py and db.py)

- [x] F1.1 Ingest keys, atomic writes, run record fields | `src/ngo_assistant/ingest.py`, `src/ngo_assistant/db.py`, `src/ngo_assistant/cli.py` (pass the manifest hash/model digest into the run record), `tests/fakes.py`, `tests/test_ingest.py`
  - **Accept**: per contracts.md "Addendum from review cycle 1"; tests first: changed chunk params with unchanged text re-chunks and re-embeds; changed embed model re-embeds; unchanged key skips; NULL stored key counts as changed; embed returning too few vectors raises `RuntimeError` naming the source and writes nothing for it; a failure inside `store_document` leaves the previous document and chunks intact (fake and, in a live scratch-schema check, real); run record has the three new fields.
  - **Verify**: `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/mypy src`; live: ingest into a fresh scratch schema twice (second run embeds nothing) and once more with different `ChunkParams` (re-chunks).
- [x] F1.2 Chunker: oversize heading blocks | `src/ngo_assistant/chunking.py`, `tests/test_chunking.py`
  - **Accept**: 50,000 `#` lines without blank line yield chunks no longer than `max_chars`; all other chunker tests unchanged and green; chunk hashes for the 22 real corpus files are IDENTICAL to before (compare sha256 of `chunk_hashes` over the corpus with a scratch script: the change must not alter real chunks).
  - **Verify**: pytest chunking; the corpus comparison.
- [x] F1.3 Small hardening | `src/ngo_assistant/retrieval/tools.py` (cap `part` at 10000, reuse `prompt.escape`), `src/ngo_assistant/llm.py` (`is not None` guard), `Makefile` (`.NOTPARALLEL:`), `docs/tech.md` (section 17: budget now 3000 tokens), `tests/fakes.py` (clamp negative part like PostgresStore; refresh docstring), tests for each
  - **Accept**: tests for the part cap and the `format={}` guard; existing tests green.
  - **Verify**: full suite, ruff, mypy.
- [x] F1.4 PDF text repair, rebuilt corpus, regenerated evidence, ingest NUL guard | `scripts/build_corpus.py`, `tests/test_build_corpus.py`, `data/corpus/*` (gitignored), `data/corpus/evidence.jsonl`, `evals/evidence.jsonl`, `evals/handcheck.md`
  - **Accept**: `data/corpus/eea-ghg-trends-2024.txt` has zero NUL bytes after rebuild; ligature artefacts repaired deterministically (documented rule, tests with fixtures, no network); build_corpus exits 1 listing any source whose output still contains NUL; the other 21 corpus files byte-identical to before; every affected claim in the local and public evidence regenerated; `scripts/verify_testset.py` exits 0 with both evidence files; test-set tests green.
  - **Verify**: `grep -c $'\x00' data/corpus/*.txt` all 0; `.venv/bin/pytest -q`; both verify runs.

## Fix Group 2: Findings from writing docs/architecture.md (apply AFTER the Group 4 real run: they touch cli.py, vector.py, metrics.py used by the run)

- [x] F2.1 Code fixes | `src/ngo_assistant/retrieval/vector.py`, `src/ngo_assistant/cli.py`, `src/ngo_assistant/runinfo.py`, `src/ngo_assistant/db.py` + `tests/fakes.py` (`Store.last_ingest_run() -> dict | None`), `src/ngo_assistant/eval/metrics.py`, `src/ngo_assistant/models.py` (comment), `Makefile`, tests for each
  - **Accept**: (a) `VectorAnswerer(top_k=None)` default resolves env `NGO_TOP_K` then 4; CLI uses it: a test sets the env and sees the retrieval size change; (b) eval `config.json` records the chunk params, embed model, embed model digest, manifest hash and git commit of the LAST INGEST RUN read from the database (`ingest` key) and the manifest hash of `data/MANIFEST.json` resolved against the repo root (not the working directory); a clear `null` plus a warning line when no ingest run exists; (c) `summarize()` adds `invalid_citations_total`, `repaired_citations_total`, `format_error_rate` (ok cases with a `format_error` trace entry / ok cases) and `answers_without_citation_rate` (non-abstained ok answers with zero citations / non-abstained ok answers), None when no data, tests; (d) Makefile passes `--tenant $(TENANT)` to `manifest`, `ingest`, `eval-smoke`, `eval`; (e) fix the `models.py` comment on invalid citations (checked against all tenant ids, not the retrieved set).
  - **Verify**: pytest, ruff, mypy; `make -n eval-smoke TENANT=tenants/demo.yaml` shows the tenant passed through.
- [ ] F2.2 Docs fixes | `.claude/specs/2026-10-14-assistant/design.md`, `README.md`, `docs/architecture.md` (only where F2.1 changes behaviour)
  - **Accept**: design.md matches the implemented design (the 15 disagreements listed in decisions.md "Findings from docs/architecture.md"); README rows corrected (no "stubs", embedding model decided, `docs/architecture.md` row kept); architecture.md updated for F2.1 after it lands.
- [x] F2.3 Tool-argument normalisation with counting | `src/ngo_assistant/retrieval/tools.py`, `src/ngo_assistant/retrieval/agentic.py`, `src/ngo_assistant/models.py`, `src/ngo_assistant/eval/metrics.py`, tests
  - **Accept**: `normalize_tool_arguments(name, arguments) -> (arguments, repairs: list[str])` in tools.py: (1) wrapper unwrapping: when the arguments dict has none of the tool's parameter names but has a `parameters` or `arguments` dict, use that dict (label `unwrapped:parameters` / `unwrapped:arguments`); when it has the wrapper keys `function`/`type`/`name` next to valid parameter keys they are dropped only when they are exactly those wrapper keys (label `dropped_wrapper_keys`); (2) numeric-string coercion for integer-typed parameters only, strings matching `^-?\d+$` (label `coerced_int:<param>`); nothing else is normalised (no float, bool, list, nested coercion, no key renaming, no clipping of ranges). The agentic answerer normalises FIRST, then calls `validate_tool_call` on the result; the repeat-call check uses normalised arguments; a normalised-and-valid call is NOT a failure and increments `tool_call_repairs` by the number of repairs; a call that is still invalid after normalisation is a failure as before (repairs made before the failure are still counted). Tool trace entries gain `repairs: [...]` (only when non-empty). `Answer` gains `tool_call_repairs: int = 0` (old data valid). `summarize()` adds `tool_call_repairs_total` and `tool_call_repair_rate` (repairs / tool calls, None when no calls). Add the new contract text to contracts.md as an addendum.
  - **Verify**: tests first (red): wrapper shapes seen in the real run (`{"function": "search_sources", "parameters": {"query": "x"}, "type": "function"}`; `limit` as `"10"`), strings that must NOT be coerced (`"abc"`, `"1.5"`, `" 5"`, `true`), unknown keys still rejected after unwrapping, ranges still enforced after coercion (`"99"` for limit still invalid), repeat detection with `{"query": "x"}` vs `{"query": "x", "limit": "5"}`; pytest, ruff, mypy.
- [x] F2.4 Clip limit, unknown source_id failure, abstain display | `src/ngo_assistant/retrieval/tools.py`, `src/ngo_assistant/retrieval/agentic.py`, `src/ngo_assistant/cli.py`, tests, `docs/architecture.md`, `contracts.md`
  - **Accept**: per decisions.md "User decisions after reading the agentic chat transcript" (items 1, 2, 4); tests first; existing tests updated only where they encode the old behaviour (list them).
  - **Verify**: pytest, ruff, mypy.

## Group 6: Variant C "hybrid" (contracts.md "Addendum: Variant C")

- [x] 6.1 Hybrid answerer and tool set | `src/ngo_assistant/retrieval/tools.py`, `src/ngo_assistant/retrieval/agentic.py` (refactor into a shared loop only if all existing agentic tests stay green), `src/ngo_assistant/retrieval/hybrid.py`, `tests/test_tools.py`, `tests/test_hybrid_answerer.py`, `tests/fakes.py`
  - **Accept**: per contracts addendum; tests first; every existing test green.
  - **Verify**: `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/mypy src`
- [x] 6.2 CLI and Makefile wiring | `src/ngo_assistant/cli.py`, `Makefile`, `tests/test_cli.py`
  - **Accept**: `--variant hybrid` in ask/chat/eval, `/variant hybrid`, three-variant eval targets with per-variant directories.
  - **Verify**: pytest, ruff, mypy, `make -n eval-smoke`.
- [!] 6.3 Live check of C (stopped by the user; partial results; the user runs it themselves) | decisions.md
  - **Accept**: `ask` with the German electricity question and `make`-style smoke eval of hybrid only (6 cases) run against the live stack; results and single observations recorded.
- [x] 6.4 Documentation | `docs/architecture.md`, `docs/adr/010-hybrid-variant.md`, `README.md`
  - **Accept**: variant C described accurately from the code; ADR-010 (context, decision, alternatives, consequences, open questions); README mentions the third variant and the make targets.

## Group 7: Filesystem crawler (contracts.md "Addendum: Filesystem crawler")

- [x] 7.1 Research | `docs/tech.md` (append section): OOXML and ODF part names and element names used (docx `word/document.xml` w:p/w:t/w:tab/w:br/w:tbl/w:pStyle; pptx `ppt/slides/slideN.xml` a:p/a:t, notes slides; xlsx `xl/workbook.xml`, `xl/sharedStrings.xml`, `xl/worksheets/sheetN.xml` cell types `t="s"` and `<v>`; ODF `content.xml` text:h/text:p/table:table-cell) each with a source URL (ECMA-376 / ISO 29500 / OASIS ODF / Microsoft Open Specifications) and a verified small example generated in a scratch dir; Python `zipfile` warnings on untrusted archives and `xml.etree.ElementTree` XML-vulnerability notes from docs.python.org (version 3.12) and the expat version in the venv (`pyexpat.EXPAT_VERSION`) with the billion-laughs protection fact verified against the docs; how `os.walk`/`os.scandir`/`Path.is_symlink` behave for symlinks and `Path.resolve`; all facts with source and date, UNVERIFIED where not verified.
- [x] 7.2 Test skeletons (red) | `tests/test_crawl.py`, `tests/test_textextract.py`, `tests/test_config_crawl.py`, additions to `tests/test_build_corpus.py`, `tests/test_cli.py`, `tests/test_ingest.py`, `tests/test_fetch_sources.py`
- [ ] 7.3 Config, crawler, gitignore | `src/ngo_assistant/config.py`, `src/ngo_assistant/crawl.py`, `.gitignore`
- [ ] 7.4 Text extraction | `src/ngo_assistant/textextract.py`
- [ ] 7.5 Integration | `scripts/build_corpus.py`, `src/ngo_assistant/ingest.py` (drift), `scripts/fetch_sources.py`, `src/ngo_assistant/cli.py` (`crawl`, ingest warning), `Makefile`
- [ ] 7.5b Tenant `db_schema` and `tenants/testdocs.yaml` | `src/ngo_assistant/config.py`, `src/ngo_assistant/cli.py` (factory uses `tenant.db_schema`), `tenants/testdocs.yaml`, `.gitignore` (`test_documents/` if not ignored), tests (contracts.md "Addendum: tenant database schema and the test_documents tenant")
- [ ] 7.6 Live check on a generated sample tree (all supported types, hidden/credential/symlink/oversize/legacy cases) with a temporary tenant file and a temporary database schema (never `public`), plus the REAL dry run, crawl and corpus build (no ingest) on /workspaces/ngo-assistant/test_documents with `tenants/testdocs.yaml` (the user allowed the crawl) | decisions.md
- [ ] 7.7 Documentation | `docs/architecture.md`, `README.md`, `docs/adr/011-filesystem-crawler.md`
