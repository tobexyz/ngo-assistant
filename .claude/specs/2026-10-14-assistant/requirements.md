# The assistant: ingest, vector variant, agentic variant, chat CLI, eval CLI

## Problem Statement
There is no assistant yet: Variants A and B are stubs, nothing loads the corpus into the database, and there
is no one-command path from a clean checkout to a working, measurable assistant. A result that cannot be
reproduced by someone else is of no use for the comparison.

## Goals
- `make data` (or the documented equivalent) takes a clean checkout with Docker to: stack up, models pulled,
  sources fetched, corpus built, documents + chunks + embeddings loaded into PostgreSQL/pgvector. Re-running
  is idempotent and produces the same rows (same chunk boundaries and hashes) when the inputs are unchanged.
- A committed `data/MANIFEST.json` (source id, url, sha256 of the fetched bytes, bytes, fetch date) records
  exactly which bytes the test set was written against; ingest verifies hashes and reports drift.
- Variant B (vector): embed question, top-k chunks from pgvector, one answer call.
- Variant A (agentic): the model uses tools (`list_sources`, `search_sources`, `read_source`) over the same
  loaded documents, with an allowlist, argument validation and a tool-call cap.
- Both variants: same model, same system prompt, same answer format, same context budget, token usage summed
  over every model call (embedding included for B), citations as source ids, abstention flag.
- `ngo-assistant ask "..." --variant vector|agentic` (non-interactive), `ngo-assistant chat` (interactive
  REPL for a human), `ngo-assistant eval --variant ... --testset evals/testset.jsonl` writing JSONL results
  and printing `summarize()` metrics (abstention, over-abstention, injection leaks, tokens, latency, tool-call
  failures, citation validity). LLM-as-judge and the comparison report are a later spec.
- Every run records its configuration (model names and digests, chunk parameters, top-k, context length,
  prompt hash, git commit, manifest hash) next to the results, so a result can be traced and repeated.

## Non-Goals
- LLM-as-judge, the Variant C hybrid, reranking, a web UI, authentication, multi-tenancy.
- Tuning chunk size, top-k or prompts (defaults are documented as untuned; tuning is a measured follow-up).
- Cost in money (local inference, 0 EUR) or energy (tokens and latency are the proxy).

## Success Metrics
- On a clean checkout, `make data` then `make test` then `make eval-smoke` run without manual steps
  (apart from stating the `.env` password) and the smoke eval (5 cases per variant) writes results.
- `pytest -q` green (unit tests need no network and no stack); `pytest -m integration` green with the stack.
- Ingest twice: row counts and chunk hashes identical.
- Full eval of all 48 cases runs for both variants (hours on CPU are acceptable; resumable, see design).

## Constraints
- CPU only, 4 CPUs, 15 GB RAM. `llama3.2:1b` chat model, `bge-m3` embeddings (ADR-004), context 8192.
- Document text is data, never instructions: retrieved text and tool results are delimited and labelled as
  untrusted in the prompt; tool arguments from the model are untrusted (allowlist + schema validation).
- Licences (ADR-001): the database holds corpus text including UBA (non-redistributable); the database volume
  and dumps are never committed or published. Only MANIFEST.json (hashes) is committed.
- Exact pins, 7-day quarantine for new dependencies, non-interactive commands for agents, tests first.
- Never invent facts about library versions or model behaviour: verify in docs/tech.md before coding.
