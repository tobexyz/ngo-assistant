# Assistant — design

## Context
Previous specs complete or closing: infra (stack, `LLMClient`, tenant, fetch script), test set (48 cases,
`evals/testset.jsonl`, corpus texts in `data/corpus/`). Contract: `Answerer.answer(question, language) -> Answer`
(ADR-003). Existing: `eval/runner.py`, `eval/metrics.py`, `llm.py`.

## Decision

### Layout
```
src/ngo_assistant/
  db.py            `Store` protocol + `PostgresStore` (DATABASE_URL, schema creation, register_vector, retrieval and ingest queries)
  chunking.py      deterministic chunker (pure functions)
  ingest.py        manifest check, documents + chunks + embeddings load, run record
  prompt.py        shared system prompt assembly, source block formatting, answer schema, citation parsing
  retrieval/vector.py   VectorAnswerer (B)
  retrieval/agentic.py  AgenticAnswerer (A) + tools.py (tool schemas, allowlist, validation, execution)
  cli.py           `ngo-assistant` entry point: ingest | ask | chat | eval | manifest
  runinfo.py       run configuration record (models + digests, params, prompt hash, git commit)
Makefile           up, models, fetch, corpus, ingest, data, test, eval-smoke, eval
data/MANIFEST.json committed hashes of fetched raw files
```

### Database (PostgreSQL 17 + pgvector 0.8.7)
- `documents(source_id pk, title, url, language, published, licence, redistributable, kind, sha256, text, tsv)`;
  `tsv` = `to_tsvector('simple', text)` generated column + GIN index (Variant A search; no embeddings needed).
- `chunks(source_id fk, ord, heading, text, char_start, char_end, sha256, embedding vector(1024))` with
  HNSW index `vector_cosine_ops` (Variant B). Primary key (source_id, ord).
- `documents` also has `ingest_key text` (nullable; NULL counts as changed).
- `ingest_runs(id bigserial, started_at timestamptz, record jsonb)`; everything else (tenant, params, counts,
  skipped, drift, embed model and digest, manifest sha256, git commit) is inside `record`.
- Idempotent: a document is skipped when its stored `ingest_key` equals the current one. The key is a sha256 over
  the document text hash, the chunk parameters and the embed model name (not the title and not the chunker code
  version). Otherwise the document row is upserted and its chunks are replaced in one transaction.
  `--rebuild` ignores the key and replaces every document's chunks the same way; nothing is dropped
  (documents removed from the tenant stay in the database). Source of truth for text: `data/corpus/<id>.txt` (built by `build_corpus.py`).

### Chunking (defaults, untuned; ADR-007)
Heading-aware: split corpus text into blocks (blank-line separated, as build_corpus writes them), keep the
nearest preceding `#` heading as chunk metadata, pack blocks up to 1200 characters, 150 characters overlap by
repeating the last block when it fits; a block longer than 1200 is split at the last sentence end or newline
within the 1200-character window, and hard-split at 1200 when neither exists. Chunk text is
prefixed in the embedding input with `title - heading` (a hyphen; just `title` before the first heading), separated
from the text by a newline; the prefix is not part of the stored text. Parameters live in one frozen
dataclass `ChunkParams` recorded in the `ingest_runs` record. EEA banner lines and Wikipedia edit markers are NOT
stripped (decision of the test-set spec: same noisy text for both variants).

### Shared answer contract (ADR-008)
Both variants end with ONE final model call using Ollama structured output (`format` = JSON schema):
`{"answer": str, "citations": [source_id,...], "abstain": bool}`; `Answer.text`, `citations`, `abstained`
are filled from it. A citation string that equals a tenant source id is kept. A string that merely CONTAINS exactly one known
source id (observed with llama3.2:1b: it put the whole `<source>` element into `citations`, tech.md section 11)
is mapped to that id and counted in `repaired_citations`. Anything else is dropped and counted in
`invalid_citations`. Both counters are in the run record (never silently kept). `abstain` is recorded as the model
sets it; no heuristic overrides it (measured behaviour, tech.md: one observation of an unsupported 'Canberra'
answer with abstain=false). The system prompt = tenant `system_prompt` + a fixed instruction block
(format, cite source ids, state source and date for numbers, say "I do not know" via abstain=true).
Variant B places retrieved text in a `<sources>` block of `<source id=".." title=".." published="..">...</source>`
elements with an explicit line that everything inside is untrusted data. Variant A has no `<sources>` block: its
retrieved text arrives as `<tool_result>` elements (below). The system prompt and the final call are the same for
A and B; the user message of A additionally ends with `TOOL_HINT` (one sentence telling the model it may call the
tools), the only prompt difference. Context budget: only Variant B has a token budget, at most 3000 tokens of
retrieved text (estimated as characters / 4; whole chunks are dropped from the end of the ranking when they would
exceed it). Variant A is bounded by its tool limits instead (below). Reference measurement: cold prefill on this CPU was about 22 tokens/s, 268 s for one measured prompt of about 6000 tokens, tech.md
sections 11-18, single observation, so a bigger budget makes the eval impractical), top-k default 4 chunks of at
most 1200 characters (`NGO_TOP_K` overrides it). Before the first question, `ask`/`chat`/`eval` send one warm-up call (loads the model, fills
the system-prompt prefix cache). The CLI sets `NGO_LLM_TIMEOUT_S` to 900 when unset (explicit env wins).

### Variant B
embed(question) -> top-k by cosine distance (`<=>`) -> source block (chunks in rank order, within the 3000-token
budget) -> final call.
Usage = embed call + final call.

### Variant A
Loop with tool calling (`LLMClient.chat(messages, tools)`), tools over `documents`:
- `list_sources()` -> ids, titles, languages, published dates (all documents, 22 for the Moorfunke tenant; not capped).
- `search_sources(query: str, limit: int = 5)` -> up to 5 hits {source_id, title, published, snippet<=300 chars}
  via `plainto_tsquery('simple', ..)` + `ts_rank` + `ts_headline`.
- `read_source(source_id: str, part: int = 0)` -> part*1500 .. +1500 characters of the document text plus
  `parts_total`.
Limits (the bound on A's context instead of a token budget): max 6 tool calls, each `read_source` result at most
1500 characters and each snippet at most 300, same (name, args) twice = loop; at the cap or on loop, the next call is the forced
final answer call without tools. A tool call is a FAILURE (counted in `tool_call_failures`) when: unknown tool
name, arguments not valid against the schema (including extra arguments), argument type error, tool raised,
or the model returns neither a valid tool call nor a final answer. No tool call at all before an answer is
NOT a failure but is recorded as `tool_calls == 0` (the metric shows it). Tool results are wrapped in the
untrusted `<tool_result>` block. Same final call and format as B.

### CLI and reproducibility
- `ngo-assistant ingest --tenant tenants/moorfunke.yaml [--rebuild]`, `manifest --write|--check`.
- `ask`: prints answer, citations, abstained, usage, tool trace (for A) and latency; `--json` for machines.
- `chat`: REPL with variant switch `/variant vector|agentic`, `/quit`; keeps no memory between questions
  (each question is independent, as in the eval).
- `eval --variant X --testset ... --out results/<run> [--limit N] [--resume]`: `--out` is a directory holding
  `<variant>.jsonl` and `config.json` (the Makefile passes `results/<run>/<variant>` so the two variants do not
  overwrite each other's `config.json`). Uses `eval.runner`, writes one JSON line per case immediately (resumable),
  a `config.json` with the run record,
  prints `summarize()`. Unjudged correctness/groundedness stay None.
- Makefile targets chain the steps; `make data` needs network once (fetch); `make reproduce-offline` re-ingests
  from `data/raw` + manifest check without network.

## Interfaces & Contracts
```python
@dataclass(frozen=True)
class ChunkParams: max_chars: int = 1200; overlap_chars: int = 150
def chunk_document(text: str, title: str, params: ChunkParams) -> list[Chunk]   # deterministic
def ingest(tenant: Tenant, store: Store, llm: LLMClient, corpus_dir: Path, params: ChunkParams = ChunkParams(),
           rebuild=False, ...) -> IngestResult   # Store: retrieval-store protocol in db.py (PostgresStore)
class VectorAnswerer: __init__(tenant, store, llm, top_k=4, max_context_tokens=3000)  # name = "vector"
class AgenticAnswerer: __init__(tenant, store, llm, max_tool_calls=6) # name = "agentic"
def validate_tool_call(name: str, arguments: dict) -> ToolCallValidation  # allowlist + JSON-schema-like checks
```
`Answer` gains `tool_trace: list[dict] = []` and `invalid_citations: int = 0` (defaults keep old data valid).

## Risks
- llama3.2:1b may fail structured output or tool calls often: measured (tool_call_failures), not hidden;
  the 3b control run is an env switch (ADR-004).
- 8192 context vs the 3000-token retrieved budget (Variant B) plus prompt, and Variant A's multi-turn tool context:
  checked by an integration test with the largest case.
- Full eval is slow on CPU (cold prefill about 22 tokens/s; the previous spec measured 5.7 s warm for a short call;
  A makes several calls per case, later calls share a cached prefix: unverified for multi-turn): resumable runs,
  `--limit`, warm-up call, long timeout. The smoke eval in Group 4 measures the real time per case.
- Prompt injection from retrieved text: tested by the 5 injection cases; the system prompt is not weakened.
- Chunk and top-k defaults are not tuned; the report must say so.
