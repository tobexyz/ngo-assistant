# ADR-006: Cost metric: zero API cost, tokens and wall-clock as resource proxy

- Status: Proposed (edit and accept it yourself)
- Date: 2026-10-14

## Context
The brief asks for a cost comparison between the variants, but all inference is local (Ollama, CPU-only), so
there is no API price. CLAUDE.md forbids inventing prices. Variant A makes several model calls per question;
variant B embeds the question and, at indexing time, the corpus.

## Decision
- `api_cost_eur = 0.0`, stated explicitly in `summarize()`: local inference, no API price.
- The resource proxy is: input tokens, output tokens, embedding tokens (`embed_tokens`), model calls
  (`model_calls`) and wall-clock latency measured by the runner (ADR-003).
- Token sources (`docs/tech.md` section 1.4): input = `prompt_eval_count`, output = `eval_count`, embedding
  tokens = `prompt_eval_count` of `/api/embed`. Missing counts count as 0.
- Embedding tokens are exactly what Ollama returns: `LLMClient.embed()` reports `prompt_eval_count` of
  `/api/embed` and 0 if the server omits it. It does not estimate. `llm.py` offers `approx_embed_tokens(texts)`
  (`ceil(len(text) / 4)`), which variant B may apply; the 4-characters-per-token ratio is a rough heuristic,
  not a documented Ollama or bge-m3 value, so any such number must be marked approximate
  (`embed_tokens_approx`) in results. The smoke test on the live stack (2026-10-14) showed that Ollama 0.40.0
  with bge-m3 does report embed counts (10 for one short sentence; `docs/tech.md` section 1.4).
- No kWh, CO2 or euro-per-token figures. We measured no power draw, and any conversion factor would be
  an invented number. The brief asks for a proxy, not real energy.

## Alternatives considered
- Estimate energy from CPU time and a wattage assumption: rejected; the wattage is not measured or sourced.
- Price tokens at a cloud model's rate: rejected; it is a hypothetical price for a model we do not use.
- Wall-clock only: rejected; it depends on host load, tokens do not.

## Consequences
- Easier: all numbers come from Ollama or the runner and are reproducible.
- Harder: A and B are compared in tokens, calls and seconds, not in money. A reader who wants euros must
  supply their own price assumption outside this repo.
- Unverified (`docs/tech.md` section 1.4, 6): whether chat `prompt_eval_count` drops when Ollama reuses a cached
  prompt prefix across agentic-loop turns; it would understate input tokens of variant A.
- Risk: if Ollama reports no embed count for some input or model, `embed_tokens` is 0 and B looks cheaper than it is; an approximate
  figure from `approx_embed_tokens` must then be reported and flagged `embed_tokens_approx`.

## Open questions for you
1. Is "zero API cost plus tokens, calls and seconds" enough for your brief, or do you want an explicit
   hypothetical price table clearly labelled as an assumption?
2. Should indexing-time embedding tokens be reported separately from per-question tokens?

## Two-minute explanation
(Write it after the first measurement.)
