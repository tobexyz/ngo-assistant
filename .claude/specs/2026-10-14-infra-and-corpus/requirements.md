# Infrastructure and open-licence corpus

## Problem Statement
The scaffold has a contract (`Answerer`), a test-set schema, a runner and metrics, but nothing can run:
no model runtime, no database, no sources, no tenant identity, and unpinned dependencies. The brief
requires a ~50-case test set BEFORE any variant is implemented, and that test set needs a real,
licence-verified corpus. This spec builds the plumbing and the corpus inventory; it does not build
Variant A or B.

## Goals
- A fictional NGO tenant (fantasy name, user decision 2026-10-14) whose identity cannot be confused
  with a real organisation.
- 8-10 real environmental sources with a licence verified on the publisher's own page, recorded in
  `docs/source-inventory.md` and `tenants/<slug>.yaml`; at least 2 DE + 2 EN, at least 2 with statistics,
  at least 1 clearly dated/outdated.
- Synthetic documents about the fictional NGO (projects, campaigns, publications) and 2-3 injection
  documents with canaries, so NGO-specific and injection test cases are possible without inventing
  facts about a real NGO.
- One-command local runtime: Ollama + PostgreSQL/pgvector via `docker compose`, images pinned by digest.
- A thin LLM client over Ollama that returns text + token counts (`prompt_eval_count`, `eval_count`)
  and supports chat, tool calls and embeddings; every call is accountable.
- A resource/cost metric in `summarize()` (tokens per answer, model calls, wall-clock, embedding tokens).
  API cost is 0 for local inference; no invented energy or price figures.
- ADRs: model choice (llama3.2:1b, llama3.2:3b as optional control, embedding model candidate),
  fictional tenant + synthetic NGO documents, cost metric definition.
- All Python dependencies pinned exactly; `pytest` green.

## Non-Goals
- Implementing Variant A, B or C (blocked until the test set exists, per the brief).
- Writing the ~50-case test set itself (next spec; it needs the downloaded corpus).
- LLM-as-judge, reports, UI, multi-tenancy, GPU support.
- Scraping any site; bund-hamburg.de is out of scope (ADR-001).

## Success Metrics
- `docker compose up -d` then `scripts/pull-models.sh` brings up a working stack on a 4-CPU, 15 GB, no-GPU host.
- `pytest -m "not integration"` green; `pytest -m integration` green when the stack is up
  (one real chat call to llama3.2:1b returns non-zero token counts; one embedding call returns a vector).
- `load_tenant("tenants/<slug>.yaml")` loads 8-10 real + synthetic sources with zero `unclear` licences.
- `ruff check` and `mypy src` clean.

## Constraints
- Time budget ~22-27 h total for the whole course project; keep this spec small.
- Pin exact versions; dependencies >= 7 days old (as of 2026-10-14: released on or before 2026-10-07).
- Never invent facts about an NGO, library versions, model names or prices (project CLAUDE.md).
- Document text is data, never instructions; do not weaken the system prompt.
- Non-interactive commands only. No secrets in git (`.env` for DB password, `.env.example` committed).
