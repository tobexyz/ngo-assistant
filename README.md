# NGO Assistant (white-label)

A retrieval assistant for environmental NGOs, built as a measured comparison:

- **Variant A:** agentic retrieval (the model searches and reads sources with tools).
- **Variant B:** vector retrieval (embeddings in PostgreSQL with pgvector).
- **Variant C (optional hybrid):** the same agent loop as A, but with `vector_search` (semantic, returns chunks) and
  `read_source` as tools and a 3000-token budget for all tool results (`docs/adr/010-hybrid-variant.md`).

All variants use the same local model (Ollama), the same system prompt and the same test set.
The decision is made with numbers: correctness, groundedness, abstention, tokens, latency, tool-call failures.

White label means: the pipeline and the eval harness are the product. Everything NGO-specific lives in one
file under `tenants/`. A second NGO is a new file, not new code.

## Status

What exists:

- Local runtime: Ollama (CPU only) and Postgres with pgvector, via `docker-compose.yml`.
- Corpus for the fictional tenant **Moorfunke e.V.** (`tenants/moorfunke.yaml`): 22 sources, 12 real
  (6 German, 6 English, open licences verified, see `docs/source-inventory.md`) and 10 synthetic documents
  in `data/synthetic/` (all marked fictional; some contain deliberate traps and hidden injections).
- `ngo_assistant.llm.LLMClient`: thin Ollama client for chat and embeddings with per-call token accounting.
- Cost metric: tokens and model calls per answer, API cost fixed at 0 (`docs/adr/006-cost-metric.md`).
- `scripts/fetch_sources.py`: polite downloader for the real sources.
- Eval schema, runner and metrics from the scaffold.
- `scripts/build_corpus.py`: converts the downloads into plain text for reading and verification.
- The 48-case test set `evals/testset.jsonl` (written 2026-10-14 against the 22 converted sources), with
  `scripts/verify_testset.py` to check it mechanically and the hand-check sheet `evals/handcheck.md`.
  Distribution and rules: `docs/testset-guide.md`.

Also built: ingest (chunking, embeddings, pgvector and full-text tables), all three variants (A: agentic retrieval
with tools, B: vector retrieval, C: hybrid agent with vector search), the `ngo-assistant` CLI (`ingest`, `manifest`, `ask`, `chat`, `eval`) and the
`Makefile` that chains the steps. See `docs/architecture.md`.

Not done yet: the real-data run (ingest of the fetched corpus and the full eval of all three variants) has no results
here, so **no quality, latency or cost numbers exist yet**. The LLM judge for correctness and groundedness, the
comparison report are not built; eval runs leave correctness and groundedness unjudged.

The test set has been checked mechanically and by an independent blind reader, but the human hand-check in
`evals/handcheck.md` (tick every case after reading its source) is still open until you do it; see
"Reproduce the data".

## Setup

Requires Python 3.11+, Docker with the compose plugin, and `openssl`.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# edit .env: set POSTGRES_PASSWORD, for example to the output of
openssl rand -hex 24

docker compose up -d
scripts/pull-models.sh                  # pulls NGO_CHAT_MODEL and NGO_EMBED_MODEL
# optional control model for later runs:
scripts/pull-models.sh llama3.2:3b
```

`docker compose up -d` refuses to start without `POSTGRES_PASSWORD`. Compose reads `.env` automatically;
`.env` is gitignored. Both services bind to `127.0.0.1` only. `scripts/pull-models.sh` needs the `ollama`
service running and accepts extra model names as arguments.

### Environment variables

Set them in `.env` (compose reads it) or in your shell.

| Variable | Default | Meaning |
|---|---|---|
| `OLLAMA_HOST` | `http://127.0.0.1:11434` | Ollama server used by `LLMClient`. |
| `NGO_CHAT_MODEL` | `llama3.2:1b` | Chat model. Switching to `llama3.2:3b` is only this variable. |
| `NGO_EMBED_MODEL` | `bge-m3` | Embedding model, default bge-m3 (ADR-004, proposed). |
| `OLLAMA_CONTEXT_LENGTH` | `8192` | Context window in tokens. Read by the compose file for the server and, when set in the client's environment, sent as `num_ctx` on every request. See below. |
| `NGO_LLM_TIMEOUT_S` | `300` | Client timeout in seconds. The `ollama` client has no timeout by default and CPU inference is slow. |
| `POSTGRES_PASSWORD` | none, required | Password of the Postgres user (`POSTGRES_USER`, `POSTGRES_DB` default to `ngo`). |
| `DATABASE_URL` | none | Connection string used by the Postgres integration test, for example `postgresql://ngo:<POSTGRES_PASSWORD>@127.0.0.1:5432/ngo`. The test is skipped when unset. |

Why `OLLAMA_CONTEXT_LENGTH` is 8192: on this CPU-only host Ollama 0.40.0 picks a 4096-token context by
default (`docs/tech.md` section 2.2), which would silently truncate long retrieval prompts and cap embedding
input below bge-m3's 8192 tokens. 8192 is a project choice, the same for Variants A, B and C so the comparison
stays fair (`docs/adr/004-models.md`). Record the value with every run.

`NGO_LLM_TIMEOUT_S` and `OLLAMA_CONTEXT_LENGTH` can be set in `.env` like the other variables. To make them
reach Python and the integration tests, load `.env` into the shell (next section).

### Tests

```bash
pytest                                    # unit tests, no network, no containers
set -a; source .env; set +a               # load .env into the shell for the integration tests
pytest -m integration                     # needs the stack running and models pulled
```

`pytest` excludes tests marked `integration` by default. The integration tests call the real chat and embed
models, check that the embedding has 1024 dimensions (override with `NGO_EMBED_DIM` if you change
`NGO_EMBED_MODEL`), and check the `vector` extension in Postgres (needs `DATABASE_URL`). Lint and types:
`ruff check .` and `mypy src`.

### Hardware and latency

The stack runs on CPU only (the project host has 4 CPU cores, 15 GB RAM, no GPU). Compose limits Ollama to
8 GB and Postgres to 1 GB. One measurement on that host with `llama3.2:1b`, `OLLAMA_CONTEXT_LENGTH=8192`
and one short German question (2026-10-14, `.claude/specs/2026-10-14-infra-and-corpus/decisions.md`,
"Group 3 smoke test"):

| | cold (after Ollama restart, includes model load) | warm |
|---|---|---|
| Chat answer | 12.9 s | 5.7 s |

With `llama3.2:1b` and `bge-m3` both loaded, the Ollama container used about 2.8 GiB. This is a single
measurement, not a benchmark; expect other numbers on other hardware. The 3b control model was not measured.

## Fetching the real sources

The 12 real sources are downloaded into the gitignored `data/raw/`, not committed:

```bash
python scripts/fetch_sources.py --tenant tenants/moorfunke.yaml --dry-run   # no network, prints the plan
python scripts/fetch_sources.py --tenant tenants/moorfunke.yaml             # real download
python scripts/fetch_sources.py --tenant tenants/moorfunke.yaml --only owid-co2-emissions
```

Options: `--out DIR` (default `data/raw`), `--only ID` (repeatable). The script fetches only the URLs listed
in the tenant file, checks `robots.txt` first (an unreachable `robots.txt` counts as disallow), identifies
itself with a descriptive User-Agent, waits at least 1 s between requests to a host and longer when
`robots.txt` sets a crawl delay (Destatis: 30 s, UBA: 10 s, so a full run takes several minutes), refuses
redirects to another host, and skips files that already exist. Each download gets a `<id>.meta.json` with
URL, time, hash and licence.

Licence handling:

- `data/raw/` is gitignored. Never commit its content.
- Sources with `redistributable: false` must never leave your machine. These are the two UBA pages
  (CC BY-NC-ND 4.0). They are included by the project owner's decision, with the project treated as
  non-commercial; the risk (NC conflicts with commercial use, ND with chunking) is written down in
  `docs/source-inventory.md`. Remove them before any commercial use.
- The de.wikipedia pages (CC BY-SA 4.0) are pinned to a revision. A copy you publish must stay CC BY-SA 4.0
  with attribution.
- Other sources are CC BY 4.0 or a Destatis attribution licence: keep the attribution.

## Running the variants

```bash
set -a; . ./.env; set +a
ngo-assistant ask "Wie hat sich der Anteil erneuerbarer Energien am Strom entwickelt?" --variant hybrid
make eval-smoke      # 6 cases per variant into results/smoke/{vector,agentic,hybrid}
make eval            # all cases of all three variants into results/$(RUN)/{vector,agentic,hybrid}
```

`--variant vector|agentic|hybrid` works for `ask`, `chat` (also `/variant hybrid`) and `eval`. Measured results
are in the eval output, not in this README. All make targets: `docs/architecture.md` section 11.4.

## Reproduce the data

The test set was written against the source files fetched on 2026-10-14. Steps from a clean checkout:

```bash
python scripts/fetch_sources.py --tenant tenants/moorfunke.yaml            # network; robots.txt and crawl delays, several minutes
pip install -e ".[dev,corpus]"                                              # "corpus" adds pypdf, needed for the EEA PDF
python scripts/build_corpus.py --tenant tenants/moorfunke.yaml --raw data/raw --out data/corpus
python scripts/verify_testset.py --testset evals/testset.jsonl --tenant tenants/moorfunke.yaml \
  --corpus data/corpus --evidence evals/evidence.jsonl
```

What each step prints and returns:

- `fetch_sources.py`: one status line per source, a `<id>.meta.json` per file (URL, time, sha256, licence).
  Exit 0, 1 if any download failed, 2 for an unknown `--only` id.
- `build_corpus.py`: one `OK` line per source (characters) and a summary line; writes `data/corpus/<id>.txt`
  and `INDEX.md`. Exit 0, or 1 if a source is missing, unreadable or thinner than `--min-chars` (default 500).
  No network. The 10 synthetic documents are copied unchanged from `data/synthetic/`.
- `verify_testset.py`: prints one line per problem and nothing when all is well. Exit 0 = no problems,
  1 = problems found, 2 = an input file could not be read or parsed. No network. It checks that every
  evidence quote (8 to 400 characters) occurs verbatim in the cited source text, that every number in an
  expected answer occurs in a quote, that unanswerable cases have no corpus hit for their absence terms, and
  that ids and dates match the tenant file. Add `--write-sheet evals/handcheck.md` to regenerate the
  hand-check sheet (`--date YYYY-MM-DD` fixes the date in its header). The sheet starts with a generated
  header that lists the cited sources and their licences.

What is reproducible and what is not:

- The test set, the tenant file, the synthetic documents and the scripts are in git. Synthetic sources and
  the schema checks reproduce exactly.
- The real pages may have changed since 2026-10-14. A fresh fetch can fail the quote check (changed text) or
  the number check even though the test set is unchanged. The fetched files of 2026-10-14 are recorded with
  their sha256 in `data/raw/*.meta.json`; compare the hash of a new download with it to see whether a page
  changed. A committed manifest of these hashes comes with the assistant spec.
- `evals/evidence.jsonl` is in git: per claim the character offsets and sha256 of the quote in the normalised
  corpus text, and the quote itself only for redistributable sources (`quote: null` for UBA). So
  `verify_testset.py` runs from a clean checkout after fetch + build. The full-quote file
  `data/corpus/evidence.jsonl` stays local; `--export-public-evidence` regenerates the public file from it.

Gitignored, never to be committed: `data/raw/` and `data/corpus/` (including the full-quote `evidence.jsonl` and the
blind-check files). Reasons: the UBA pages are CC BY-NC-ND 4.0 (no redistribution), OWID text must not be
edited (CC BY 4.0, "You must not edit the material"), de.wikipedia is CC BY-SA 4.0 (share-alike). The
committed `evals/handcheck.md` prints a quote only when every cited source is redistributable; other quotes
are withheld there. See `docs/adr/001-scope-and-data.md`.

## Layout

| Path | Purpose |
|---|---|
| `tenants/moorfunke.yaml` | The working tenant: fictional NGO Moorfunke e.V., 22 sources (12 real, 10 synthetic). |
| `tenants/demo.yaml` | Generic, empty white-label example. Kept because `tests/test_config.py` loads it. |
| `src/ngo_assistant/config.py` | Tenant and source schema. The loader rejects unclear licences. |
| `src/ngo_assistant/models.py` | `Answer`, `Citation`, `Usage` shared by all variants. |
| `src/ngo_assistant/llm.py` | `LLMClient` (chat and embed against Ollama), `add_usage`, `approx_embed_tokens`. |
| `src/ngo_assistant/retrieval/` | `Answerer` contract, Variant B (`vector.py`), Variant A and the shared tool loop (`agentic.py`, tools in `tools.py`). |
| `src/ngo_assistant/retrieval/hybrid.py` | Variant C: the A loop with `vector_search` and `read_source` and a cumulative 3000-token budget. |
| `src/ngo_assistant/eval/` | Test-set schema, runner, metrics (including the cost metric). |
| `docker-compose.yml` | Ollama (CPU) and Postgres + pgvector, images pinned by digest. |
| `docker/postgres/init.sql` | Enables the `vector` extension on first start. |
| `scripts/pull-models.sh` | Pulls the chat and embedding models into the running Ollama container. |
| `scripts/fetch_sources.py` | Downloads the real sources into `data/raw/`. |
| `scripts/build_corpus.py` | Converts `data/raw/` into plain text in `data/corpus/` (HTML via stdlib parser, PDF via pypdf). |
| `scripts/verify_testset.py` | Mechanical check of the test set against the corpus and evidence; writes the hand-check sheet. |
| `evals/testset.jsonl` | The 48 test cases, one JSON object per line. |
| `evals/handcheck.md` | Generated hand-check sheet: per case the question, expected answer, sources and (where licensed) quotes, with two boxes to tick. |
| `data/raw/` | Gitignored. Downloads and `.meta.json` files from `fetch_sources.py`. |
| `data/corpus/` | Gitignored. Converted texts, `INDEX.md`, `evidence.jsonl` and blind-check files. |
| `data/synthetic/` | Fictional Moorfunke documents, including injection documents. `CANARIES.md` lists the canary strings. |
| `tests/` | Unit tests; `tests/integration/` needs the stack (`pytest -m integration`). |
| `docs/tech.md` | Verified SDK, server and model facts with sources and dates. |
| `docs/architecture.md` | How the assistant works: pipeline, schema, chunking, all variants, prompt-injection defence, reproducibility, CLI. |
| `docs/adr/` | Architecture decision records (004 models, 005 fictional tenant, 006 cost metric are new). |
| `docs/source-inventory.md` | Verified sources and licences. |
| `docs/testset-guide.md` | Final distribution, evidence rules, process and how to extend the test set. |

## Model licence notice

The chat model is Llama 3.2. Its licence (Llama 3.2 Community License) asks, when you distribute a product or
documentation that uses it, to prominently display "Built with Llama" and to include the notice
"Llama 3.2 is licensed under the Llama 3.2 Community License, Copyright (c) Meta Platforms, Inc. All Rights
Reserved." The Acceptable Use Policy also expects that users are told answers are AI-generated and that
hallucination risk is disclosed. Details and sources: `docs/tech.md` section 4. This is an obligation to
check before publishing the project or any UI, not legal advice. The assistant has no UI yet.

## Not decided yet (on purpose)

Chunking and top-k defaults are untuned, and reranking is not done. Each becomes an ADR with a reason. The chat
model, the embedding model and the context length are proposed in `docs/adr/004-models.md` (status Proposed).
Check current Ollama models against the Ollama library before changing them. Do not choose from memory.

## Data policy

Only sources with a verified open licence. No scraping without written permission and a checked robots.txt.
See `docs/adr/001-scope-and-data.md`.
