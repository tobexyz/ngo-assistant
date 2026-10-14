# Infrastructure and open-licence corpus — design

## Context
Scaffold commit bfb000f. User decisions on 2026-10-14: research sources for them; fantasy NGO name;
build infrastructure now, hold variants until the test set exists. Chat model chosen by the user:
`llama3.2:1b` (ollama.com/library/llama3.2, checked 2026-10-14: 1.3 GB, 128K context, "tools" tag,
German officially supported; licence not stated on that page -> verify on Meta's page).

## Decision

### Runtime: docker compose (Ollama + pgvector)
- `ollama/ollama:0.40.0` (pushed 2026-10-06) and `pgvector/pgvector:0.8.7-pg17-trixie` (2026-10-01),
  both pinned by `@sha256` digest. Ollama models persist in a named volume.
- Ports bound to `127.0.0.1` only. DB password from `.env` (gitignored), `.env.example` committed.
- CPU only; no GPU reservation. Resource limits so the 1B model + Postgres fit in 15 GB.
- Rejected: installing Ollama in the devcontainer (not reproducible for others); a cloud model
  (breaks "same local model" and the token-as-resource story).

### LLM client: official `ollama` Python package, wrapped
- `src/ngo_assistant/llm.py`: `LLMClient` with `chat(messages, tools=None) -> ChatResult` and
  `embed(texts) -> EmbedResult`. Each result carries `Usage` (input = `prompt_eval_count`,
  output = `eval_count`; embedding input tokens from the embed response if present, else counted as
  documented in `docs/tech.md`) and the raw tool calls.
- The client is injected (constructor arg) so unit tests use a fake; no network in unit tests.
- Model names come from config/env (`NGO_CHAT_MODEL`, default `llama3.2:1b`; `NGO_EMBED_MODEL`), never
  hard-coded in variants -> the 3b control run is a config change, not a code change.
- Rejected: raw httpx (re-implementing a maintained client); LangChain/LlamaIndex (hides token counts
  and tool-call failures we need to measure).

### Cost / resource metric
- `Usage` gains `embed_tokens: int = 0` and `model_calls: int = 0` (defaults keep old data valid).
- `summarize()` adds `total_tokens_mean`, `embed_tokens_mean`, `model_calls_mean`, and
  `api_cost_eur = 0.0` stated explicitly as "local inference, no API price". No kWh numbers: tokens and
  wall-clock are the resource proxy (brief: "not real energy").

### Fictional tenant
- One fantasy name, checked with a web search to not match a real environmental NGO; recorded in ADR-005
  with the check date. Tenant file `tenants/<slug>.yaml`; `tenants/demo.yaml` is replaced by it.
- NGO-specific content = our own synthetic documents in `data/synthetic/` (licence: own work, CC BY 4.0,
  redistributable), clearly marked fictional in a header line. Some contain deliberate traps for the
  test set: an outdated figure later corrected, a greenwashing-prone partner claim, 2-3 injection docs
  with unique canary strings.
- `Source.kind` gains `"synthetic"` so synthetic and real documents are distinguishable in reports.

### Corpus research
- 8-10 real sources; candidate publishers with known open licences (EEA, UBA/Umweltbundesamt, IPCC,
  Our World in Data, Wikipedia, Copernicus, EU publications) — each MUST be verified on its own licence
  page, with URL and date; anything unclear is excluded. robots.txt checked for any site we fetch.
- Output: filled `docs/source-inventory.md`, sources added to the tenant file,
  `scripts/fetch_sources.py` that downloads into `data/raw/` (gitignored) — run later, not now.

### Embedding model
- Candidate `bge-m3` (Ollama library: 567m, multilingual). Record as Proposed in ADR-004 with
  alternatives (`nomic-embed-text-v2-moe`, `snowflake-arctic-embed2`, `paraphrase-multilingual`).
  The final choice belongs to Variant B's spec; it is pulled now only so the smoke test can embed.

## Technical Approach
```
docker compose ──> ollama:11434  (llama3.2:1b, [llama3.2:3b], bge-m3)
                └> postgres:5432 (pgvector extension created by init SQL)

Answerer (A/B, later) ──> LLMClient ──> ollama
                                  └──> Usage per call ──summed──> Answer.usage
runner ──> latency ; metrics.summarize ──> tokens, calls, cost proxy
```

## Interfaces & Contracts
```python
class ChatResult(BaseModel):
    text: str
    tool_calls: list[ToolCall]      # name: str, arguments: dict
    usage: Usage                    # model_calls == 1
class EmbedResult(BaseModel):
    vectors: list[list[float]]
    usage: Usage                    # embed_tokens, model_calls == 1
class LLMClient:
    def __init__(self, chat_model: str | None = None, embed_model: str | None = None, host: str | None = None, client: ollama.Client | None = None): ...  # None -> env -> default; public .host
    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatResult: ...
    def embed(self, texts: list[str]) -> EmbedResult: ...
def add_usage(a: Usage, b: Usage) -> Usage   # summing helper for the agentic loop
```
Env: `OLLAMA_HOST` (default `http://127.0.0.1:11434`), `NGO_CHAT_MODEL`, `NGO_EMBED_MODEL`,
`DATABASE_URL`, `POSTGRES_PASSWORD`.

## Risks
- 1B tool-calling unreliability -> measured as `tool_call_failures`; 3b control run planned.
- Ollama may not report embed token counts -> documented fallback in `docs/tech.md`, flagged as approximate.
- CPU-only latency high -> fine for ~50 cases; note in README.
- Licence nuance (e.g. NC, ND, no redistribution) -> per-source fields; redistributable=false means fetch script only.
- Fantasy name collides with a real org -> web check recorded in ADR-005.
