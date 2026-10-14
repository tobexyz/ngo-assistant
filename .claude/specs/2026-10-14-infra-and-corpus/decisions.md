# Decisions: Infrastructure and open-licence corpus

## 2026-10-14 — Keep tenants/demo.yaml
**Context**: tests/test_config.py:31 loads tenants/demo.yaml and asserts slug "demo"; task 1.2 originally deleted it.
**Decision**: Keep demo.yaml as the generic white-label example; the fictional NGO gets its own tenant file.
**Rationale**: No test churn; demonstrates "a second NGO is a new file" (ADR-002).

## 2026-10-14 — Plan approved by user
**Context**: User approved plan incl. bge-m3 as smoke-test-only embedding candidate.
**Decision**: Proceed with Group 1. ollama/ollama:0.40.0 kept (8 days old, passes 7-day rule).
**Rationale**: User said "yes".

## 2026-10-14 — Ruff UP042 ignored, Category stays (str, Enum)
**Context**: ruff flags `class Category(str, Enum)` in eval/schema.py; StrEnum changes str()/format() output.
**Decision**: Keep the class; add `ignore = ["UP042"]` to ruff config (applied in Group 2 with 2.1).
**Rationale**: Eval JSON output depends on current behaviour; no benefit worth the risk.

## 2026-10-14 — LLMClient args default to None
**Context**: Tests (task 1.4) call `LLMClient()` and `LLMClient(client=fake)` and expect env defaults and a public `host` attribute.
**Decision**: chat_model, embed_model, host are `str | None = None`, resolved from env (NGO_CHAT_MODEL, NGO_EMBED_MODEL, OLLAMA_HOST) then defaults. `host` is a public attribute. design.md updated.
**Rationale**: Keeps the 3b control run a pure env change.

## 2026-10-14 — 1.3 side effects accepted
**Context**: 1.3 removed quotes from return annotations in config.py:37,51 and eval/schema.py:39 (UP037) and pinned setuptools==84.0.0.
**Decision**: Accepted; both files have `from __future__ import annotations`. 24 existing tests pass.

## 2026-10-14 — Corpus: 10 sources accepted, UBA/IPCC/BfN/Copernicus rejected
**Context**: Task 1.2 verified licences on publisher pages. UBA is CC BY-NC-ND (NC conflicts with white-label use, ND with chunking); IPCC, BfN, Copernicus unclear.
**Decision**: Use 10 sources (EEA, OWID, EC, Destatis, de.wikipedia pinned revisions); fictional NGO "Moorfunke e.V." (slug moorfunke). Share-alike (Wikipedia) copies in the repo stay CC BY-SA 4.0. Destatis fetch needs 30 s crawl delay (task 2.4). Open for user: whether UBA may be used if the project stays non-commercial; Vereinsregister check of the name.
**Rationale**: "unclear" = unusable (ADR-001).

## 2026-10-14 — UBA included by user decision (CC BY-NC-ND 4.0)
**Context**: User said "include UBA" after being told NC conflicts with commercial white-label use and ND with chunking.
**Decision**: Two UBA pages added (uba-erneuerbare-pm-2024, uba-erneuerbare-2025), redistributable=false, fetched to gitignored data/raw/ only. Project treated as non-commercial. Fetch script waits 10 s between UBA requests (30 s for Destatis). Whether RAG chunking/answers are "derivatives" under ND is unresolved legally.
**Rationale**: User's call; risk documented in docs/source-inventory.md. Before any commercial use: replace UBA sources or get written permission.

## 2026-10-14 — Ollama default context is 4096 (verified in tech.md)
**Context**: Task 1.1 saw `default_num_ctx=4096` on 0.40.0 CPU; llama3.2 supports 128K, but the default would silently truncate RAG prompts and bge-m3 input.
**Decision**: Set `OLLAMA_CONTEXT_LENGTH` explicitly in docker-compose (value chosen in the Variant B/A specs; compose default via env var) and record the context used per run. Embedding token fallback `ceil(len/4)` is approximate and flagged as such.
**Rationale**: Equal context budget for A and B is part of a fair comparison (ADR-003 open question 2).

## 2026-10-14 — Review cycle 1 (Group 1): FAIL, 2 warnings, fix group created
**Decision**: OLLAMA_CONTEXT_LENGTH default 8192, env-overridable, same for A and B. Embed dimension asserted at 1024 (bge-m3, tech.md). Duplicated system prompt in moorfunke.yaml vs demo.yaml is deferred (suggestion): revisit when the prompt is revised after injection tests.

## 2026-10-14 — Group 1 gates passed
Review cycle 2 PASS, security review cycle 1 PASS (0 Critical, 0 Warning). Deferred suggestions (not blocking): compose cap_drop/pids_limit/cpus; `.env.example` DATABASE_URL duplicates the password; .gitignore lacks *.key/*.pem/.envrc/secrets/; devcontainer uses `latest` features and an unpinned Claude Code install (user's own environment, out of scope); compose comment cites tech.md section 3 but the 4096 finding is in 2.2 (fixed in Group 2 docs task); measure 8g fit at 8192 ctx via `ollama ps` / `docker stats` in Group 3; run pip-audit in Group 3.

## 2026-10-14 — Embed token fallback is opt-in, not inside embed()
**Context**: design.md/tech.md proposed ceil(len/4) when Ollama omits prompt_eval_count; tests/test_llm.py expects embed_tokens == 0 then. Task 2.1 followed the test and added `approx_embed_tokens(texts)`.
**Decision**: embed() reports only server-reported counts (0 if missing). Variant B decides whether to apply `approx_embed_tokens` and must mark such numbers as approximate in results. Integration test must assert embed_tokens > 0 on the live stack (Group 3) to confirm 0.40.0 reports it.
**Rationale**: Never mix measured and estimated numbers silently (tokens are the resource proxy).

## 2026-10-14 — Review cycle 1 (Group 2): FAIL, 5 warnings, Fix Group 2 created
**Decision**: Fix the synthetic timeline by removing forward references (keeps published dates and the 142->128 ha pair stable for test questions). Source ids validated with `^[a-z0-9][a-z0-9._-]*$` in config.py and in the fetch script. Deferred suggestions: same-host redirect not re-checked against robots.txt; real-transport test; invalid env values raise bare ValueError (covered by F2.3 as documented behaviour).

## 2026-10-14 — Group 2 gates passed
Review cycle 2 PASS, security review cycle 1 PASS (0 Critical, 0 Warning). Deferred suggestions: fetch redirect check ignores scheme/port (https->http downgrade on same host); 30 s timeout is per socket op, not total; robots.txt not re-checked for redirect targets; dangling-symlink write; warn on non-loopback http OLLAMA_HOST; bare ValueError messages for bad env values; donate-page.md "any later correction" wording; NGO_LLM_TIMEOUT_S undocumented. For Variant A: tool dispatch needs a tool-name allowlist and argument schema validation (model output is untrusted). pip-audit ran with --no-deps; transitive deps (e.g. httpx) not audited.

## 2026-10-14 — Group 3 smoke test
**Result**: stack healthy, models pulled, `pytest -m integration` 3 passed (10.2 s). No compose change was needed.
- **Images in use** (index digests, match docker-compose.yml; platform linux/amd64): ollama/ollama:0.40.0 `sha256:1bef639749741b375e9a1eb2c1346fb57ce52f5432de1f74846e44ccc18e1687`; pgvector/pgvector:0.8.7-pg17-trixie `sha256:7a7e9f22015b67edb4bef5c59daeebcd7e74bfa570df6ce60ae01237c8648a84`.
- **Models**: llama3.2:1b (1.3 GB on disk, id baf6a787fdff), bge-m3:latest (1.2 GB, id 790764642607). llama3.2:3b not pulled.
- **`ollama ps`** (after chat + embed calls, OLLAMA_CONTEXT_LENGTH=8192): bge-m3 1.2 GB, 100% CPU, context 8192; llama3.2:1b 1.7 GB, 100% CPU, context 8192; both resident (keep-alive 30m).
- **`docker stats`** (both models loaded): ollama 2.808 GiB / 8 GiB (35%), postgres 34.6 MiB / 1 GiB (3.4%). The 8g limit is ample for 1b + bge-m3 at 8192 ctx; the 3b control fits too in principle (not measured).
- **Latency, llama3.2:1b, one short German question** (after an ollama restart, so cold includes model load): cold 12.9 s, warm 5.7 s (CPU only). Tokens: input 40, output 78 (cold) / 53 (warm). Tool-call requests (157 input tokens): about 2.0-2.5 s warm, 5.0 s first.
- **Embeddings**: bge-m3 dimension 1024; `embed_tokens` = 10 for one short sentence, i.e. > 0. This settles the UNVERIFIED item in docs/tech.md section 6: ollama 0.40.0 + bge-m3 does report prompt_eval_count. Not yet edited in tech.md (docs task). The L2-normalisation question is still open.
- **Sanity answer (German)** to "Was ist ein Moor? Antworte in einem Satz auf Deutsch.": fluent-looking but factually wrong ("ein Moor ist ein flaches, trockenes Gebiet ... in den Alpen, in der Karibik ..."; the cold call gave nonsense about "Moorkalk, Sandstein"). Expect 1b to hallucinate without retrieved context; the German is grammatical. Relevant for the faithfulness metric.
- **Tool-call probe (Variant A risk)**: one trivial tool `get_weather(city)`, 5 tries: 5/5 returned a parseable tool call with correct name and city. In 1 of 5 an extra spurious argument (`properties: '{}'`) appeared, so argument-schema validation and an allowlist are needed (as already noted in the Group 2 gates). This is a trivial one-tool probe, not evidence for multi-tool or multi-step use.

## 2026-10-14 — Group 3 review gates skipped (no code changed)
Group 3 only ran the stack and recorded measurements here; no source, test, config or infra file changed (verified by the ops agent: compose, src, tests untouched). Gates resume with Group 4 (docs).
