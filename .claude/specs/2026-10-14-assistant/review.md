# Review: The assistant

## Groups 1-2 — Cycle 1 — 2026-10-15
Reviewing: Group 1 tasks 1.1-1.3 and Group 2 tasks 2.0-2.6 (chunking, db, ingest, prompt, runinfo, llm, models, retrieval/tools, tests/fakes.py and the new tests, Makefile, pyproject.toml, docs/tech.md sections 11-18).
Out of scope (Group 3, being rewritten in parallel): retrieval/vector.py, retrieval/agentic.py, cli.py, eval/runner.py and their tests. None of the files in scope changed while reviewing (checked by diff against the copy made at the start).

Commands run: `pytest -q --ignore=<3 Group 3 files>` = 373 passed at the start; 384 passed at the end (11 more tests came from the parallel Group 3 work in test_runner.py, not from this scope). `ruff check .` clean, `mypy src` clean (19 files at the end).

### Critical
- none

### Warning
- [src/ngo_assistant/ingest.py:65] Stale chunks are kept silently when the chunk parameters change but the text does not. The skip decision is only `store.document_sha(id) == sha256(text)`. design.md says chunks are replaced when `documents.sha256` OR the chunk params changed; the code has no way to detect changed params (params are only written to `ingest_runs`, never compared), the same for a changed embedding model. `ingest(..., params=ChunkParams(max_chars=600))` on an already loaded database writes nothing, reports `skipped=N`, and the database keeps 1200-char chunks while the run record claims 600. No test covers it (test_ingest.py has `test_custom_chunk_params_change_the_chunks` only on an empty store). Fix: store the params (and embed model) per document or chunk set (e.g. a `chunk_params`/`embed_model` column or compare with the last `ingest_runs` record) and skip only when sha256 AND params match, or document that `--rebuild` is required and make the CLI/ingest warn; add a test "same text, other params -> re-chunked".
- [src/ngo_assistant/ingest.py:82-98 with db.py:261-289] `upsert_document` (new sha256) and `replace_chunks` are two separate transactions. If the process dies or the DB errors between them, the document row carries the new sha256 with the old (or no) chunks and every later run skips it (skip is by sha256), so the stale/missing chunks stay forever without `--rebuild`. Embedding happens before both writes (good), so the window is small but real. Fix: do both writes in one transaction (a store method, or `upsert_document` after a successful `replace_chunks` using a transaction), or write the sha256 last.
- [src/ngo_assistant/chunking.py:104-107, 108] A block that starts with `#` is always one heading unit and is never split, so it can exceed `max_chars` arbitrarily. Reproduced: 50,000 lines of `#` (no blank line) give one chunk of 99,999 characters; the same happens for a long paragraph or table starting with `#`. The contract and task 2.1 accept only "a single unsplittable sentence" above `max_chars`; the embedding input would exceed the model's input and the 3000-token retrieval budget logic assumes at most 1200 chars. Everything else held (see Chunker results). Not triggered by the current corpus (max chunk 1200). Fix: treat a `#` block longer than `max_chars` like any other block for splitting (heading label from its first line only) and add a test.
- [tests/test_ingest.py] No test fails when the embed-vector-count check (`ingest.py:75`) is removed (mutation survived). The check is the only guard against silently pairing chunks with wrong embeddings (`zip(strict=True)` would still catch the length mismatch later, but with a less clear error). Add one test with a fake embed that returns too few vectors.

### Suggestion
- [src/ngo_assistant/runinfo.py:195-203 vs ingest.py:164-166] The manifest hash is computed twice. The two are identical for every input (both `json.loads` the file / take the dict, then `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)` and sha256 of UTF-8), so there is no behavioural bug today, only a drift risk. Make runinfo call `ingest.manifest_sha256(json.loads(...))` (no import cycle: ingest does not import runinfo).
- [src/ngo_assistant/db.py:230-242, retrieval/tools.py:140-145] `part` has no upper bound. A model-sent `part` above about 1.4 million makes `part * 1500 + 1` an int8 value, `substr(text, bigint, integer)` does not exist and the call raises. The answerer counts that as a tool failure, so no crash, only a confusing error. Cap `part` in `validate_tool_call` (e.g. 10,000) or cast in SQL.
- [src/ngo_assistant/ingest.py:102-115] The `ingest_runs` record lacks `manifest_sha256`, `embed_model_digest` and `git_commit`, which design.md lists for `ingest_runs`. contracts.md only requires `tenant`, so this is allowed; but the reproducibility goal is better served by writing them (`build_run_record` already knows how).
- [src/ngo_assistant/ingest.py:62] Sources removed from the tenant file stay in the database (orphan documents/chunks); `--rebuild` does not delete them either. Fine for now, mention in docs or delete them in rebuild.
- [src/ngo_assistant/ingest.py:124-129] `_raw_file` globs `<id>.*`; with ids that contain dots (allowed by the id pattern) `a` also matches `a.b.txt`. Match `<id>.<ext>` with no further dot, or pick by meta.
- [src/ngo_assistant/prompt.py:369] Citation repair: if one known id is a substring of another (`heron-marsh` and `heron-marsh-2`), a string containing the longer id is "ambiguous" and counted invalid. Prefer the longest matching id. Not present in the current tenant files.
- [src/ngo_assistant/llm.py:296] `tools and format` uses truthiness; `format={}` plus tools slips through. Use `is not None` on `format`.
- [tests/fakes.py:1-8] Module docstring is stale (says importing fails until group 2 exists). `FakeStore.read_document` does not clamp a negative `part` (PostgresStore does) and `search_documents` is a substring match ordered by id, not full-text ranked; harmless for the current assertions but worth a comment. The real `SELECT` paths in db.py (SQL text, `substr`, `COLLATE "C"`, ts_headline marker stripping) have no unit test, only the marked integration tests, which were not run (stack not touched by instruction).
- [docs/tech.md:581] Section 17 "Budget" row still says "design.md's 6000 tokens of retrieved text", which decisions.md and design.md replaced by 3000. Update the row.
- [Makefile:48-49] `data` and `reproduce-offline` rely on the listed prerequisite order; with `make -j` the order is not guaranteed. Acceptable (documented usage is serial); a `.NOTPARALLEL:` line would make it explicit.
- [src/ngo_assistant/retrieval/tools.py:188 and prompt.py:288] Two copies of the same `_escape`/`escape`; reuse `prompt.escape`.

### Contracts vs code
All public names and signatures in contracts.md and the Addendum were compared (chunking, db types and `Store`, `PostgresStore(database_url, schema)` with `create_schema`/`close`, ingest/manifest, prompt, tools, runinfo, llm). No divergence found other than: `ChunkParams`/`Chunk` are frozen dataclasses (contract: dataclass or pydantic, fine); design.md's `ChunkParams(BaseModel)` was superseded by contracts.md. Retrieved-text budget: the constant `max_context_tokens: int = 3000` is already in retrieval/vector.py (Group 3 file, not judged here); db/prompt/tools carry no budget, consistent with the contract.

### Chunker results (scratch scripts under the scratchpad, not in the repo)
1 MB single line with spaces: 834 chunks, 0.02 s. 1 MB without any space: 834 chunks, 0.02 s. 1 MB of sentences: 0.07 s. 100k blank lines: `[]`, 0.00 s. 50k tiny blocks: 0.24 s. 5000 characters without spaces: 5 hard-split chunks of at most 1200. Combining characters, emoji, CRLF, `max_chars=1`, `overlap_chars` larger than `max_chars`: no exception, no hang. 3000 random inputs with random params (without `#`): `text[start:end] == chunk.text`, no empty chunk, never longer than `max_chars`, all non-space characters covered, start and end strictly increasing (overlap never endless), deterministic. Only failure: the `#` block case in the Warning above. All 22 corpus files chunk to at most 1200 characters.

### db.py SQL safety
Every value is a bound parameter; the only identifiers (schema, table names) go through `psycopg.sql.Identifier` after `SCHEMA_RE` validation; the vector dimension is a validated int (1..2000) inserted with `sql.SQL`; `ts_headline` options are bound; ts_headline markers are stripped again. `replace_chunks` deletes and inserts inside one `conn.transaction()` (atomic per document). Transaction nesting checked in the psycopg source: `register_vector` leaves the connection idle, so each `conn.transaction()` is an outer commit. `read_document` uses `substr`, clamps negative parts, returns empty text beyond the last part and `None` for an unknown id as the Addendum says. No injection path found. (Not executed against Postgres by instruction; judged from the code and docs/tech.md 14-16.)

### Tests: quality and mutation spot check
The periodic-fixture bug in test_tools is fixed (`"".join(f"{i}," ...)`, 3890 characters, 3 parts, parts 0 and 1 compared against slices). No network in any unit test. Mutations were applied to a COPY in the scratchpad (working tree untouched); result = tests failing (167 tests in the 7 in-scope files, all green at base):

| Mutation | Failing tests |
|---|---|
| chunk overlap disabled | 1 |
| citation repair not counted | 2 |
| invalid citations not counted | 2 |
| extra tool keys accepted | 6 |
| limit range check removed | 5 |
| empty string / 500-char limit / source id pattern checks removed | 2 / 2 / 2 |
| ingest never skips unchanged documents | 4 |
| embed_tokens not summed | 5 |
| `<` not escaped in prompt | 3 |
| `tools`+`format` guard removed | 1 |
| chunk size limit removed | 13 |
| heading metadata removed | 2 |
| citation de-duplication removed | 2 |
| manifest drift not computed | 1 |
| only first source ingested | 7 |
| run record context length dropped | 1 |
| embed vector count check removed | 0 (survived, see Warning) |

Spot check of 10 tests (test_tools execution/validation, test_chunking invariants, test_ingest idempotency/stale rows, test_prompt escaping): each would fail if the behaviour were wrong. Missing: changed-params ingest (Warning above).

### Makefile
`make help`, `make -n data` and `make -n eval-smoke` work. Target order of `data` is `up models fetch corpus manifest ingest`. `.env` guard prints a clear error to stderr and exits 1; recipes `source` `.env` with `set -a` and never echo values (the `make -n` output shows only the guard text and commands). `.SHELLFLAGS` has `-eu -o pipefail`. `pyproject.toml` entry point `ngo_assistant.cli:main` present; dependency pins exact. `cli` is Group 3.

### docs/tech.md sections 11-18
Every row has a source (URL, `inspect.signature` or live output) and the single observations are labelled ("single observation", "one sample", UNVERIFIED lists in section 18). No single sample is stated as a general rule; 11.4 explicitly says "observation, not a general rule". Only the stale 6000-token budget row (Suggestion above).

### Tests
- [x] All tests passing (384 passed, 8 deselected, in-scope files unchanged; the three Group 3 files were excluded as agreed)
- [ ] Coverage adequate for the change: missing tests for changed chunk params with unchanged text, the embed vector-count error and an over-long `#` block (see Warnings)

### Verdict: FAIL
(4 Warnings, 0 Critical. The security review of Groups 1-2 was waived by the user.)
