# ADR-004: Chat model llama3.2:1b, llama3.2:3b as control, bge-m3 as embedding candidate

- Status: Proposed (edit and accept it yourself)
- Date: 2026-10-14

## Context
Both variants (ADR-003) need a local chat model and variant B needs an embedding model. The host is CPU-only
(4 CPU, 15 GB RAM, no GPU). You chose `llama3.2:1b`. Facts below come from `docs/tech.md` (verified 2026-10-14;
sections 4 and 5 have the URLs). A 1B model may handle tool calling badly, and variant A depends on it.

## Decision
- **Chat model: `llama3.2:1b`.** Ollama library: 1.3GB, 128K context window, capability tag `tools`, German
  officially supported. Licence: Llama 3.2 Community Licence (text from Meta's GitHub repo, because Meta's own
  page returned 404 on 2026-10-14). Obligations as recorded in `docs/tech.md` section 4: show "Built with Llama"
  and the licence notice in README/UI, and follow the Acceptable Use Policy (say that answers are AI-generated,
  disclose hallucination risk). The EU clause covers multimodal models only; 1b and 3b are text-only.
- **Control run: `llama3.2:3b`** (Ollama library: 2.0GB). The switch is configuration only:
  `NGO_CHAT_MODEL=llama3.2:3b`; no code change. Purpose: if variant A fails with 1b, the 3b run helps separate
  "the approach fails" from "the model is too small". The prompt and retrieval budget stay identical (ADR-003).
- **Embedding model candidate: `bge-m3`** (Ollama library: 567m, 1.2GB, 8K context, "more than 100 working
  languages"; model card: MIT licence, 1024 dimensions). Variant B's spec makes the final choice; the model
  is pulled now so the smoke test can embed. The integration test (`tests/integration/test_stack.py`) asserts 1024; the schema column will be `vector(1024)` in variant B.
- **Context length is set explicitly.** Ollama 0.40.0 on this CPU-only host defaulted to 4096 tokens
  (`default_num_ctx=4096`, `docs/tech.md` section 2.2), far below the 128K of llama3.2. That would silently
  truncate RAG prompts and cap bge-m3 input below its 8192 tokens. `OLLAMA_CONTEXT_LENGTH` defaults to 8192
  in `docker-compose.yml`, env-overridable, and is the same for A and B. Record the value used per run.

## Alternatives considered
- Embedding `nomic-embed-text-v2-moe`, `snowflake-arctic-embed2`, `paraphrase-multilingual`: named as
  alternatives in the design. Their licence, dimension and context length are **not verified** here; check each
  against its Ollama page and model card before variant B picks one.
- A larger chat model than 3b: not considered; it would not fit the CPU-only budget in a useful time.
- A cloud model: rejected in the design; it breaks "same local model" and the token-as-resource story (ADR-006).
- Skipping the 3b control: rejected. Without it a failed variant A is hard to interpret.

## Consequences
- Easier: model swaps are an env var; token counts come from Ollama for every call.
- Harder: the licence obligations (attribution, AUP) must reach the README and UI (README done; UI pending).
- Harder: 8192 context on CPU raises RAM and latency. Measured once on 2026-10-14 (smoke test, `decisions.md`
  "Group 3 smoke test"): with `llama3.2:1b` and `bge-m3` both loaded at 8192 context, `ollama ps` showed
  1.7 GB and 1.2 GB, both 100% CPU; `docker stats` showed the ollama container at 2.8 GiB of the 8 GiB limit.
  The 3b control was not measured.
- Confirmed live: bge-m3 returns 1024-dimensional vectors, and Ollama 0.40.0 reports embed token counts
  (10 for one short sentence).
- Observed: `llama3.2:1b` answered a short German factual question ("Was ist ein Moor?") fluently but wrongly
  without retrieved context (one question, two calls). Expect hallucination without context; this matters for
  the faithfulness metric.
- Probe, not a benchmark: 5 of 5 tool-call requests to one trivial tool were parseable, 1 of 5 with a spurious
  extra argument (`docs/tech.md` section 4.1). Variant A needs a tool allowlist and argument validation.
- Unverified (`docs/tech.md` section 6): whether Ollama-served bge-m3 vectors are L2-normalised; cosine is our
  choice, not a documented requirement.
- Risk: a 1B model may produce malformed or missing tool calls, so variant A may be unusable. This is measured
  as `tool_call_failures` and, if it happens, "A does not work with a 1B model" is a valid finding, checked
  by the 3b control run.

## Open questions for you
1. Is 8192 the right shared context budget, or should A and B get a smaller retrieval budget inside it?
2. Do you want the 3b control run for all test cases or only for the cases where 1b fails?
3. Which embedding alternative, if any, do you want checked besides bge-m3 before variant B's spec?

## Two-minute explanation
(Write it after the first measurement.)
