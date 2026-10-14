# Tasks: Infrastructure and open-licence corpus

Plan: `.claude/specs/2026-10-14-infra-and-corpus/requirements.md` and `design.md`

Version cut-off for new deps: released on or before 2026-10-07 (checked 2026-10-14):
`ollama==0.6.3`, `pydantic==2.13.5`, `PyYAML==6.0.3`, `psycopg[binary]==3.3.6`, `pgvector==0.5.0`,
dev: `pytest==9.1.1`, `ruff==0.16.10`, `mypy==2.4.0`, `types-PyYAML==6.0.12.20260906`.
Images: `ollama/ollama:0.40.0`, `pgvector/pgvector:0.8.7-pg17-trixie`, pinned by digest.

## Group 1: Research, runtime scaffolding, test skeletons

- [x] 1.1 Research and document SDK/framework APIs | `docs/tech.md`
  - **Packages**: `ollama==0.6.3`, `psycopg[binary]==3.3.6`, `pgvector==0.5.0`, images above
  - **Accept**: `docs/tech.md` has, with source URL + verification date per item: `ollama.Client(host=...)`
    signature; `chat()` params incl. `tools`, response fields (`message.content`, `message.tool_calls`,
    `prompt_eval_count`, `eval_count`, durations); `embed()` params/response and whether it reports token
    counts (if not, the documented fallback); Ollama env vars relevant to CPU (`OLLAMA_NUM_PARALLEL`,
    `OLLAMA_KEEP_ALIVE`, context length); pgvector `register_vector` with psycopg 3, `CREATE EXTENSION vector`;
    Llama 3.2 licence name + URL from Meta's own page; bge-m3 model card facts (dims, languages, licence).
  - **Verify**: install the pinned packages in a scratch venv and paste `inspect.signature()` output for
    `ollama.Client.__init__`, `.chat`, `.embed`, `pgvector.psycopg.register_vector` into tech.md.
  - **Constraints**: no facts from memory; every row cites a URL or signature output. Do not edit code.

- [x] 1.2 Research open-licence corpus and fantasy NGO name | `docs/source-inventory.md`, `tenants/<slug>.yaml` (keep `tenants/demo.yaml`: tests/test_config.py:31 depends on it)
  - **Accept**: one fantasy NGO name + slug, with a web search showing no real environmental NGO of that
    name (queries + date recorded in source-inventory.md). 8-10 real sources meeting the corpus requirements
    in source-inventory.md (≥2 DE, ≥2 EN, ≥2 with statistics, ≥1 dated/outdated), each with licence verified
    on the publisher's licence page (URL + quote + date), redistributable yes/no, robots.txt result for any
    site to be fetched. New tenant file with those sources and the existing system prompt unchanged except
    for the NGO name. Rejected candidates listed with the reason.
  - **Verify**: `python -c "from ngo_assistant.config import load_tenant; t=load_tenant('tenants/<slug>.yaml'); print(t.name, len(t.sources))"`
  - **Constraints**: do not scrape or bulk-download; only read licence pages, robots.txt and landing pages.
    Licence "unclear" = excluded. No bund-hamburg.de. Do not invent publication dates; leave `published` null if unknown.

- [x] 1.3 Pin deps and add docker compose runtime | `pyproject.toml`, `docker-compose.yml`, `.env.example`, `.gitignore`, `scripts/pull-models.sh`, `docker/postgres/init.sql`
  - **Packages**: exactly the versions listed at the top of this file
  - **Accept**: pyproject pins every dep with `==`; dev extra adds ruff/mypy/types-PyYAML; pytest marker
    `integration` registered and `addopts = "-m 'not integration'"`; ruff + mypy config. Compose: ollama +
    postgres pinned by `@sha256` digest, ports on 127.0.0.1, named volumes, healthchecks, memory limits,
    `POSTGRES_PASSWORD` from `.env`; init.sql runs `CREATE EXTENSION IF NOT EXISTS vector`. `pull-models.sh`
    pulls `${NGO_CHAT_MODEL:-llama3.2:1b}` and `${NGO_EMBED_MODEL:-bge-m3}` via `docker compose exec -T`,
    with `set -euo pipefail`. `.gitignore` adds `*.un~`, `*~`, `.env.*` except `.env.example`.
  - **Verify**: `python3 -m venv .venv && .venv/bin/pip install --no-input -e ".[dev]" && .venv/bin/pytest -q` (existing tests green);
    `POSTGRES_PASSWORD=x docker compose config -q`; `bash -n scripts/pull-models.sh`
  - **Constraints**: do not start containers or pull models in this task. No secrets committed. No GPU config.

- [x] 1.4 Write failing test skeletons | `tests/test_llm.py`, `tests/test_metrics_cost.py`, `tests/test_config_synthetic.py`, `tests/integration/test_stack.py`
  - **Accept**: tests encode design.md contracts: LLMClient maps `prompt_eval_count`/`eval_count` to Usage,
    sets `model_calls=1`, parses tool calls into `ToolCall(name, arguments)`, handles missing counts as 0,
    embed returns vectors + usage; `add_usage` sums all fields; uses an injected fake client (no network).
    `summarize()` returns `total_tokens_mean`, `embed_tokens_mean`, `model_calls_mean`, `api_cost_eur == 0.0`.
    `Source(kind="synthetic")` is valid. Integration tests (marked `integration`): real chat to
    `NGO_CHAT_MODEL` returns text and input/output tokens > 0; real embed returns a vector of the documented
    dimension; Postgres has the `vector` extension.
  - **Verify**: `.venv/bin/pytest -q` collects all new tests and they fail only for missing implementation (ImportError/AttributeError), not syntax.
  - **Constraints**: do not touch `src/` or `pyproject.toml`. Test names describe behaviour.

## Group 2: Implementation, synthetic corpus, ADRs

- [x] 2.1 LLM client, Usage fields, cost metric, synthetic kind | `src/ngo_assistant/llm.py`, `models.py`, `config.py`, `eval/metrics.py`
  - **Accept**: `pytest tests/test_llm.py tests/test_metrics_cost.py tests/test_config_synthetic.py tests/` all green; models from env with defaults per design.md.
  - **Verify**: `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/mypy src`
  - **Constraints**: use APIs exactly as documented in `docs/tech.md`. Old result data must stay valid (defaults). No LangChain.

- [x] 2.2 Synthetic NGO documents and injection documents | `data/synthetic/*.md`, `tenants/<slug>.yaml`
  - **Accept**: 5-7 short documents about the fictional NGO (about, 2-3 projects, a campaign, an annual
    report with numbers + date, one outdated figure later corrected, one greenwashing-prone partner claim),
    each starting with a "FICTIONAL — synthetic test document" line; 2-3 injection documents, each with one
    hidden instruction and a unique canary (listed in `data/synthetic/CANARIES.md`). All added to the tenant
    file as `kind: synthetic`, licence `CC BY 4.0 (own work)`, redistributable true.
  - **Verify**: tenant loads (command from 1.2); `grep -c FICTIONAL data/synthetic/*.md`
  - **Constraints**: content must not reference real NGOs or real people; facts about the real world must be
    general and uncontroversial or attributed to a real corpus source.

- [x] 2.3 ADRs and test-set guide | `docs/adr/004-models.md`, `005-fictional-tenant.md`, `006-cost-metric.md`, `docs/testset-guide.md`
  - **Accept**: ADRs follow `000-template.md`, Status "Proposed", cite `docs/tech.md`/ollama.com with dates;
    004 covers llama3.2:1b, the 3b control, bge-m3 candidate + alternatives; 006 states api_cost=0 and tokens/
    wall-clock as proxy, no energy figures. Test-set guide rescaled to ~50 cases (brief) and lists NGO-specific
    questions against synthetic docs and cross-language cases.
  - **Verify**: `grep -L "Status:" docs/adr/00[4-6]*.md` prints nothing
  - **Constraints**: no facts that are not in tech.md, source-inventory.md or the spec.

- [x] 2.4 Fetch script for the corpus | `scripts/fetch_sources.py`, `tests/test_fetch_sources.py`
  - **Accept**: reads the tenant file, downloads only non-synthetic sources into `data/raw/<id>.<ext>`, skips
    existing files, sets a descriptive User-Agent, honours robots.txt via `urllib.robotparser`, timeouts,
    `--dry-run`. Unit tests with a mocked opener (no network).
  - **Verify**: `.venv/bin/pytest tests/test_fetch_sources.py -q && .venv/bin/python scripts/fetch_sources.py --tenant tenants/<slug>.yaml --dry-run`
  - **Constraints**: stdlib only. Do not run a real download in this task.

## Group 3: Stack smoke test

- [x] 3.1 Bring up the stack and pass integration tests | no code changes expected
  - **Accept**: `docker compose up -d` healthy; models pulled; `pytest -m integration` green; observed token
    counts, embed dimension and first-call latency recorded in `decisions.md`.
  - **Verify**: `docker compose ps`, `scripts/pull-models.sh`, `.venv/bin/pytest -m integration -q`
  - **Constraints**: leave the stack running only if the user wants; record image digests actually used.

## Group 4: Documentation update

- [x] 4.1 Update documentation for plan changes | `README.md`, `docs/`
  - **Accept**: README covers stack setup, env vars, model pull, test markers, fictional tenant, new layout
    entries; status section accurate (variants still stubs, test set next).
  - **Verify**: `grep -rn 'TODO\|FIXME\|PLACEHOLDER' README.md docs/ || true` returns no plan-related placeholders
  - **Constraints**: do not document Variant A/B behaviour; nothing descoped.
  - **Group 4 — fix**: docker-compose.yml comment now cites the 2026-10-14 measurement (2.81 GiB of 8 GiB; comment text only); docs/adr/004-models.md licence-obligation line now reads "README done; UI pending".

## Fix Group 1: Address review cycle 1

- [x] F1.1 Set Ollama context length explicitly | `docker-compose.yml`, `.env.example`
  - **Note**: docker-compose.yml part done and verified. `.env.example` could not be read or edited (deny rule on cat/sed and Read); add `OLLAMA_CONTEXT_LENGTH=8192` with a comment manually.
  - **Accept**: compose sets `OLLAMA_CONTEXT_LENGTH: ${OLLAMA_CONTEXT_LENGTH:-8192}`; `.env.example` lists it with a comment (default 4096 on CPU would truncate RAG prompts; same value for variants A and B); 8g ollama limit still plausible for llama3.2:1b + bge-m3 at that context (state the reasoning in a compose comment, no invented numbers).
  - **Verify**: `POSTGRES_PASSWORD=x docker compose config -q && POSTGRES_PASSWORD=x docker compose config | grep OLLAMA_CONTEXT_LENGTH`
  - **Constraints**: do not start containers.
- [x] F1.2 Assert embedding dimension in integration test | `tests/integration/test_stack.py`
  - **Accept**: real embed test asserts 1024 for the default bge-m3 (per docs/tech.md section 5), overridable via env `NGO_EMBED_DIM`; stale TODO removed.
  - **Verify**: `.venv/bin/pytest --collect-only -q -m integration tests/integration` (collection error on missing `ngo_assistant.llm` is expected until Group 2) and `.venv/bin/ruff check tests`
- [x] F1.3 Ruff ignore and doc nits | `pyproject.toml`, `docs/source-inventory.md`, `.claude/specs/.../tasks.md`
  - **Accept**: `ignore = ["UP042"]` under `[tool.ruff.lint]` (decisions.md); source-inventory.md header says "Moorfunke tenant" and points at `tenants/moorfunke.yaml` instead of demo; OWID "must not edit the material" noted next to the UBA ND risk; task 1.3 Verify command in tasks.md uses `POSTGRES_PASSWORD=x docker compose config -q`.
  - **Verify**: `.venv/bin/ruff check .` prints no errors; `.venv/bin/pytest -q tests/test_config.py tests/test_eval_schema.py tests/test_metrics.py tests/test_runner.py` green.
  - **Constraints**: leave the suggestion about the duplicated system prompt for task 2.1 (decision below).

## Fix Group 2: Address Group 2 review cycle 1

- [x] F2.1 Fix synthetic timeline and fixture nits | `data/synthetic/*.md`, `tenants/moorfunke.yaml`
  - **Accept**: no document refers to something published after its own date (project-buero-wattwaechter.md 2024-09-09 -> annual report 2025-03; project-schwarzes-bruch.md 2024-06-03 -> "spätere Newsletter"); fix by removing forward references (keep published dates and the 142->128 ha correction pair unchanged); annual report "Published 15 Mar 2025" vs "approved 29 Mar 2025" made consistent; donate page: EUR 300 receipt threshold phrased as Moorfunke's own fictional policy, not a real tax rule; `contains_statistics` for partner-nordlicht-energie.md set truthfully in the tenant file; CANARIES.md still matches the files.
  - **Verify**: `.venv/bin/python -c "from ngo_assistant.config import load_tenant; print(len(load_tenant('tenants/moorfunke.yaml').sources))"` prints 22; `grep -rn "MF-CANARY" data/synthetic | wc -l` unchanged vs before; grep each document for dates later than its own published date.
- [x] F2.2 Sanitise source ids; fix models.py comment | `src/ngo_assistant/config.py`, `scripts/fetch_sources.py`, `tests/test_fetch_sources.py`, `tests/test_config.py`, `src/ngo_assistant/models.py`
  - **Accept**: `Source.id` must match `^[a-z0-9][a-z0-9._-]*$` and must not contain `..` (validator in config.py, test in test_config.py); fetch_sources.py also validates ids and verifies the resolved output path stays inside `--out` (test with an id like `../../x` bypassing the model, e.g. via a stub source object); models.py comment on `embed_tokens` says: reported by the server, 0 when omitted (no estimate inside embed()); add tests for robots-404-allows and a redirect loop/limit. All 22 ids in tenants/moorfunke.yaml and tenants/demo.yaml still load.
  - **Verify**: `.venv/bin/pytest -q && .venv/bin/ruff check . && .venv/bin/mypy src`
- [x] F2.3 Correct ADR-004 and add missing llm tests | `docs/adr/004-models.md`, `tests/test_llm.py`
  - **Accept**: ADR-004 line 25 says the integration test (not the client) asserts the 1024 dimension; tests added for `OLLAMA_CONTEXT_LENGTH` -> `options={"num_ctx": N}` (None/absent when unset, and a clear error or documented behaviour for an invalid value), and for the explicit client timeout (`NGO_LLM_TIMEOUT_S`, default 300, building the real client with a stubbed `ollama.Client`). If a test reveals a bug in llm.py, fix llm.py minimally and say so.
  - **Verify**: `.venv/bin/pytest -q tests/test_llm.py && .venv/bin/ruff check . && .venv/bin/mypy src`
