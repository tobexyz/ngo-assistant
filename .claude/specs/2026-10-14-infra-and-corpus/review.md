# Review: Infrastructure and open-licence corpus

## Cycle 1 — 2026-10-14
Reviewing: Group 1 tasks (1.1-1.4)

### Critical
None.

### Warning
- [docker-compose.yml:18-20] `OLLAMA_CONTEXT_LENGTH` is not set. docs/tech.md section 2.2 observed `default_num_ctx=4096` on 0.40.0 CPU, and decisions.md (2026-10-14) commits to setting it explicitly. At 4096 tokens RAG prompts and bge-m3 input are silently truncated. Fix: add `OLLAMA_CONTEXT_LENGTH: ${OLLAMA_CONTEXT_LENGTH:-<N>}` (and a line in .env.example). Check that 8g still fits, since RAM scales with NUM_PARALLEL x context.
- [tests/integration/test_stack.py:35-37] Task 1.4 Accept requires the real embed test to assert the documented dimension. docs/tech.md section 5 now documents 1024 (HF card), but the test only asserts `len > 0` and still carries a stale `TODO(task 1.1)`. Fix: assert 1024, conditional on the default `bge-m3` (or via an `NGO_EMBED_DIM` env default of 1024), and remove the TODO.

### Suggestion
- [tests] The `-m 'not integration'` addopts are set. The collection errors for `tests/integration/test_stack.py` still happen on a plain `pytest -q` because the module imports the missing `ngo_assistant.llm`. This is expected in the red phase, but it interrupts the whole run. Group 2 fixes it.
- [pyproject.toml / ruff] `ruff check .` reports 1 error (UP042 on `Category(str, Enum)`). This is already covered by decisions.md, so make sure the ignore lands with 2.1.
- [docs/source-inventory.md:1-4] The heading "(demo tenant)" and the "copy into tenants/demo.yaml" text are stale. Update them to point at moorfunke.yaml.
- [docs/source-inventory.md, OWID quote] OWID says "You must not edit the material". Chunking for retrieval is not editing in the usual sense, but note it next to the UBA ND risk.
- [tenants/moorfunke.yaml] The system_prompt is a copy of demo.yaml. Risk of drift. This is acceptable for now.
- [docker-compose.yml] `docker compose config -q` needs `POSTGRES_PASSWORD` set (by design, `:?`). Make the Verify command in tasks.md say `POSTGRES_PASSWORD=x docker compose config -q`.

### Checks performed
1. Verify commands: `docker compose config -q` passes with `POSTGRES_PASSWORD=x` set. `bash -n scripts/pull-models.sh` is OK (script is executable, `set -euo pipefail`, `exec -T`). `load_tenant('tenants/moorfunke.yaml')` loads 12 sources. The 4 pre-existing test files pass (13 passed together with the new synthetic/cost files). New tests fail only for missing implementation (ModuleNotFoundError `ngo_assistant.llm`; `kind="synthetic"` rejected; KeyError `api_cost_eur`; Usage fields missing), with no syntax errors.
2. Compose: memory limits (ollama 8g, postgres 1g), healthchecks, `127.0.0.1` port bindings, `@sha256` digests, `no-new-privileges`, and `POSTGRES_PASSWORD` required from env are all present. No secrets in the file. `.env.example` could not be read by this reviewer (path is permission-denied); `.gitignore` correctly ignores `.env.*` except `.env.example`, plus `*~` and `*.un~`. OLLAMA_CONTEXT_LENGTH is missing (Warning above).
3. Tenant: no "unclear" licences. The UBA sources are `redistributable: false` and consistent with source-inventory.md, ADR-001 and decisions.md. I fetched three licence claims and they match the inventory: UBA (CC BY-NC-ND 4.0 on the cited page), EEA ("EEA materials are published under the CC-BY license", third-party exception), Destatis PM Nr. 091 of 12 March 2025 with 59.4%. No invented facts found.
4. docs/tech.md: every row has a source; UNVERIFIED items are listed in section 6 and marked at the point of use; none are stated as fact.
5. Test skeletons match the design.md contracts (Usage mapping, model_calls=1, ToolCall, None counts as 0, env defaults, `.host`). They are not over-constraining (fake supports both attribute and item access). The integration tests are marked `integration` and are deselected by default.
6. Pins: all `==`, with no ranges. PyPI upload times checked for ollama (2026-09-29), pytest (2026-06-19), mypy (2026-10-01) and ruff (2026-10-01), all on or before the 2026-10-07 cut-off. Other pins follow tasks.md, which records the 2026-10-14 check.

### Tests
- [x] All tests passing (pre-existing tests green; new tests red as intended for Group 1)
- [ ] Coverage adequate for the change (embed dimension assertion missing)

### Verdict: FAIL

## Cycle 2 — 2026-10-14
Reviewing: Group 1 tasks (1.1-1.4) plus Fix Group 1 (F1.1-F1.3)

### Critical
None.

### Warning
None. Both cycle-1 Warnings are resolved:
1. OLLAMA_CONTEXT_LENGTH: docker-compose.yml:26 sets `${OLLAMA_CONTEXT_LENGTH:-8192}` with a comment on the memory reasoning (marked "not measured", honest). `.env.example` could not be read by this reviewer (deny rule), so that line is user-verified, not reviewer-verified.
2. tests/integration/test_stack.py:35-37 asserts `len(result.vectors[0]) == int(os.environ.get("NGO_EMBED_DIM", "1024"))`. `import os` is present and the stale TODO is gone.

### Suggestion
- [docker-compose.yml:23] Comment cites "docs/tech.md section 3" while cycle 1 saw the 4096 observation in section 2.2. Check that the reference points to the right section.
- [docker-compose.yml:26] The 8g fit at 8192 context is unmeasured. Verify with `ollama ps` and `docker stats` when the stack first runs (Group 2).
- [pytest] A plain `pytest -q` still stops with 2 collection errors (`ngo_assistant.llm` missing). Expected in the red phase, and Group 2 resolves it.
- The cycle-1 suggestions on moorfunke.yaml prompt drift and the OWID edit note are handled (OWID in source-inventory.md) or deferred in decisions.md.

### Checks performed
- `POSTGRES_PASSWORD=x docker compose config -q`: exit 0.
- `.venv/bin/ruff check .`: all checks passed. UP042 is now ignored in pyproject.toml with a justification.
- The pre-existing test files pass: 24 passed.
- `pytest --collect-only -q`: 33 tests collected. The only errors are ModuleNotFoundError `ngo_assistant.llm` in tests/test_llm.py and tests/integration/test_stack.py, which is correct red phase for Group 2.
- Regressions: the pyproject.toml diff pins all deps and build requires exactly (`==`), with ruff/mypy/pytest config and the `integration` marker. The source-inventory.md heading and tenant references now point to moorfunke.yaml, and the OWID edit-condition risk is documented. No regressions found.

### Tests
- [x] All tests passing (24 pass; new tests red as intended for Group 1)
- [x] Coverage adequate for the change

### Verdict: PASS

## Group 2 — Cycle 1 — 2026-10-14
Reviewing: Group 2 tasks (2.1-2.4)

### Critical
None.

### Warning
- [data/synthetic/project-buero-wattwaechter.md:3,17,31 and tenants/moorfunke.yaml:199] Unresolved timeline contradiction (author-reported). The page is dated 9 September 2024 (`published: 2024-09-09`) but says "In the 2024 pilot, 18 offices took part" (the 18 comes from the annual report published 15 March 2025) and "The pilot results are in the annual report". A question such as "when did the pilot finish / how many offices" is ambiguous. Fix: either re-date the page to after 2025-03-15 (and update `published`), or remove the 18-office figure and the annual-report pointer. Same pattern, lower impact: project-schwarzes-bruch.md (3 June 2024) ends with "Aktuelle Flächenzahlen stehen im Jahresbericht und in späteren Newslettern", referring to documents that did not exist yet; reword to avoid forward references.
- [scripts/fetch_sources.py:180-204] Source ids are not sanitised. `source.id` comes from the tenant file (any string; `Source.id` has no pattern) and is used unchanged in `out.glob(f"{id}.*")` and `out / f"{id}.{ext}"` and `.meta.json`. An id such as `../../x` writes outside `--out`, and glob metacharacters change the skip check. Fix: validate ids with `^[a-z0-9][a-z0-9._-]*$` (best in `Source`, otherwise in `select_sources`) and add a test that a traversal id is rejected.
- [src/ngo_assistant/models.py:23] Comment says embed_tokens is "approximate if the server omits them". That contradicts the decision in decisions.md, ADR-006 and tech.md (embed() reports only server counts, 0 if missing, never estimates; approximation is opt-in via `approx_embed_tokens`). The code and tests agree with the decision; this comment is the odd one out. Fix: "0 if the server reports none; see approx_embed_tokens()".
- [docs/adr/004-models.md:25] "The schema column is `vector(1024)`, and the client asserts 1024." No schema exists yet and `LLMClient` does not assert any dimension (only the integration test in tests/integration/test_stack.py does). Fix: "the integration test asserts 1024; the schema column will be vector(1024) in variant B".
- [tests/test_llm.py] No test covers `OLLAMA_CONTEXT_LENGTH` -> `options={"num_ctx": N}` (and `options=None` when unset) or the explicit client timeout (`NGO_LLM_TIMEOUT_S`/default 300 s passed to `ollama.Client`). Both are fairness/robustness requirements of this task (context budget identical for A and B). Fix: two small tests with the fake client / monkeypatched `ollama.Client`.

### Suggestion
- [src/ngo_assistant/llm.py:78,86] `int(os.environ["OLLAMA_CONTEXT_LENGTH"])` and `float(NGO_LLM_TIMEOUT_S)` raise a bare ValueError on bad input; a clear message would help. `NGO_LLM_TIMEOUT_S` is not listed in `.env.example`/docs.
- [scripts/fetch_sources.py:133-141] A same-host redirect target is not re-checked against robots.txt. Low risk, but a redirect into a disallowed path would be fetched.
- [tests/test_fetch_sources.py] Not covered: robots 404 -> allow (the documented intentional behaviour), `urllib_fetch`/`_NoRedirect` (real transport, untestable without a local server or a patched opener), redirect loop limit. Robots 4xx -> allow is only exercised implicitly by the 404 default route in `test_http_error_status_fails`; make it explicit.
- [scripts/fetch_sources.py:254-259] Dry-run says "crawl delay unknown" while decisions.md says UBA waits 10 s and Destatis 30 s; these values come only from robots.txt at run time. Confirm on the first real run (Group 3 or the user), and note it in decisions.md.
- [data/synthetic/annual-report-2024.md:5,35] "Published 15 March 2025" but the text says the members' assembly approved it on 29 March 2025 (after publication). Harmless but a possible trick question; align if unintended.
- [data/synthetic/donate-page.md:19] The EUR 300 receipt threshold mirrors a real-world tax rule stated as fact, even though it is hedged by "check with your tax office". Make it plainly a Moorfunke policy to keep the file free of real-world claims.
- [tenants/moorfunke.yaml partner entry] `contains_statistics: false` although the page has "8.000 Euro" and "100 %" figures; arguably only figures about the world count. Decide on a definition and note it.

### Checks performed
- `.venv/bin/pytest -q`: 69 passed, 3 deselected (integration). `.venv/bin/ruff check .`: all checks passed. `.venv/bin/mypy src`: no issues in 12 files. `pytest --collect-only -q -m integration tests/integration`: 3 tests collected. `fetch_sources.py --tenant tenants/moorfunke.yaml --dry-run`: 12 sources considered, 0 failed, 10 synthetic sources skipped, UBA flagged "not redistributable", no network access.
- llm.py: uses only documented `ollama.Client(host, timeout)`, `chat(model, messages, tools, options)`, `embed(model, input, options)`; None counts -> 0; default timeout 300 s; model names only as defaults/env; nothing is logged; `num_ctx` only from env. embed() has no ceil(len/4) fallback; code, tests (test_llm.py:81,141), ADR-006 and tech.md:101-104 agree (only the models.py comment disagrees, see Warning).
- metrics.py: `*_mean` return None when no ok results, `api_cost_eur` is 0.0 with the explanatory comment, existing keys unchanged; `Usage` defaults keep old data valid. `Source.kind` accepts "synthetic". UP037 annotation edits are covered by decisions.md.
- fetch_sources.py: robots.txt required (unreachable/5xx = disallow, 4xx = allow, as documented), Crawl-delay honoured with a 1 s floor, redirects limited to the same host (max 5), 25 MiB cap enforced in transport and in `get`, single URL per source, no credentials or cookies, User-Agent has no personal data (tested), skips existing files, synthetic and non-http sources excluded; meta.json holds id, url, fetched_at (UTC), status, content type, sha256, licence, licence_url, redistributable. Only the id-sanitisation gap is a Warning.
- data/synthetic: all 12 files (10 docs, CANARIES.md, LICENCE.md) start with the FICTIONAL line. Canaries in files: MF-CANARY-082ba2 (press-page, HTML comment), MF-CANARY-14f643 (freiwilligen-faq, zero-size white span), MF-CANARY-0d0dab (donate-page, footer); CANARIES.md lists exactly these three, each unique, each with a real hidden instruction. The 142 -> 128 ha correction is arithmetically consistent (142 - 14 = 128; 71+14+15 = 100 %). No real NGO or person named, no real-world statistics. All 10 tenant url paths exist, all `published` dates are before 2026-10-14, languages match the text, `contains_statistics` is true for the four documents with figures that matter (see suggestion for partner page). Task 2.2 count (7 content + 3 injection docs) is met.
- ADRs 004-006 follow the template (Status "Proposed", Date, all sections; "Two-minute explanation" left as a placeholder by design). Spot-checks against tech.md: llama3.2 1.3GB/2.0GB/128K/tools (tech.md:171), Meta page 404 (tech.md:173), bge-m3 567m/1.2GB/8K/MIT/1024 (tech.md:184-185), 4096 default (tech.md:136): all match. Unverified items (alternative embedding models, L2 normalisation, prompt-cache effect on counts) are marked as such. Only the "client asserts 1024" claim is wrong (Warning).
- testset-guide.md: 12+7+8+8+8+5 = 48, matches the Total row; category rules (unanswerable without sources, numbers need `expected_source_date`, injection needs `canary`) match `eval/schema.py`; the file ids named for dated pairs exist in the tenant.
- docker-compose.yml: only comments differ in this group's scope; the tech.md section reference there is now correct (2.2).

### Tests
- [x] All tests passing (69 passed, 3 integration deselected)
- [ ] Coverage adequate for the change (num_ctx/timeout paths in llm.py untested; no traversal-id test for the fetch script)

### Verdict: FAIL

## Group 2 — Cycle 2 — 2026-10-14
Reviewing: Group 2 tasks (2.1-2.4) plus Fix Group 2 (F2.1-F2.3), verifying the five cycle-1 Warnings

### Critical
None.

### Warning
None. All five cycle-1 Warnings are resolved:
1. Timeline: project-buero-wattwaechter.md (9 Sep 2024) now says "The pilot is just starting" and no longer cites the 18 offices or the annual report. project-schwarzes-bruch.md (3 Jun 2024) ends with "Flächenzahlen veröffentlichen wir, sobald sie geprüft sind." No document refers to a later-published one; the annual report (15 Mar 2025) says the assembly "will vote" on 29 Mar 2025; the newsletter (20 Apr 2026) is the only document that refers back. Published dates in tenants/moorfunke.yaml, the 142 -> 128 ha pair and the 151 ha figure are unchanged. 6 MF-CANARY lines (3 in files, 3 in CANARIES.md); CANARIES.md lists exactly the three present.
2. Id sanitisation: `Source.id` validator in config.py (pattern plus no `..`), `valid_id` and a resolved-path containment check in fetch_sources.py. Tests: test_config.py (unsafe/safe parametrised, demo and moorfunke tenants both load, 22 sources), test_fetch_sources.py (unsafe id with no network call, containment test with the id check monkeypatched out, stub-tenant `run` returns 1). All 22 moorfunke ids and the demo ids match the regex.
3. models.py: comment now reads "reported by the server, 0 when omitted (no estimate inside embed())".
4. ADR-004: "The integration test asserts 1024; the schema column will be vector(1024) in variant B."
5. test_llm.py: num_ctx forwarded to chat and embed, unset/empty sends no options, invalid value raises ValueError, real client built with default timeout 300 s, env timeout, invalid timeout. Tests check observable behaviour (kwargs passed to a stubbed client).

### Suggestion
- [data/synthetic/donate-page.md:21] "any later correction published by the association" is a generic hedge, not a hard forward reference, but it hints at the 2026-04 correction that is dated after the page (2026-02-10). Consider removing "later".
- [src/ngo_assistant/llm.py:85-88] The earlier suggestion remains: `NGO_LLM_TIMEOUT_S` is not documented in `.env.example`.
- [scripts/fetch_sources.py] Same-host redirects are still not re-checked against robots.txt (carried over from cycle 1; low risk).
- [scripts/fetch_sources.py:231] The containment check only tests `.html` and `.meta.json` names; the final extension may be pdf or bin, but the stem is validated, so this is equivalent in practice.

### Checks performed
- `.venv/bin/pytest -q`: 105 passed, 3 deselected (integration). `.venv/bin/ruff check .`: all checks passed. `.venv/bin/mypy src`: no issues in 12 files. `pytest --collect-only -q -m integration tests/integration`: 3 tests collected. `fetch_sources.py --tenant tenants/moorfunke.yaml --dry-run`: 12 sources considered, 0 failed, no network.
- Regression check: the id regex change affects only ids; both tenant files load; the `-> Source`/`-> Tenant` annotation edits are cosmetic (`from __future__ import annotations`).

### Tests
- [x] All tests passing (105 passed, 3 integration deselected)
- [x] Coverage adequate for the change

### Verdict: PASS

## Group 4 — Cycle 1 — 2026-10-14
Reviewing: Group 4 task 4.1 (README.md, docs/tech.md, docs/adr/004-models.md, docs/adr/006-cost-metric.md, docs/source-inventory.md)

Verified: `bash -n scripts/pull-models.sh` OK; `POSTGRES_PASSWORD=x docker compose config -q` OK; `fetch_sources.py --help` shows --tenant/--out/--dry-run/--only as documented. Env table matches llm.py (llama3.2:1b, bge-m3, http://127.0.0.1:11434, 300 s, num_ctx from OLLAMA_CONTEXT_LENGTH) and compose (8192). Counts match tenants/moorfunke.yaml (22 = 12 real [6 de, 6 en] + 10 synthetic). Layout paths exist; `evals/` correctly documented as absent. Measurements (12.9/5.7 s, 2.8 GiB of 8, 1024 dims, embed_tokens 10, probe 5/5 + 1 spurious arg) match decisions.md and are labelled single measurement / probe. No claim that Variants A/B work; Llama notice phrased as obligation to check, consistent with tech.md section 4. No TODO/FIXME/PLACEHOLDER. `.env.example` could not be read (permission deny), so the DATABASE_URL example and the OLLAMA_CONTEXT_LENGTH entry there are unchecked.

### Critical
- none

### Warning
- [docker-compose.yml:24-25] Stale comment: says the 8g fit is "Not measured; check `ollama ps` and `docker stats`", but Group 3 measured it. Replace with: "Measured once on 2026-10-14: 2.81 GiB of 8 GiB with llama3.2:1b + bge-m3 at 8192 context (decisions.md, Group 3 smoke test); the 3b control was not measured."

### Suggestion
- [README.md:72] States OLLAMA_CONTEXT_LENGTH can be set in `.env`; F1.1 note says `.env.example` was never updated with it. Add the entry manually.
- [docs/adr/004-models.md:35] "must reach the README and UI (Group 4)": README part is done; reword to "README done; UI pending".

### Tests
- [x] All tests passing (105 passed, 3 integration deselected; ruff clean; mypy clean)
- [x] Coverage adequate for the change (docs only)

### Verdict: FAIL

## Group 4 — Cycle 2 — 2026-10-14
Reviewing: fix for Cycle 1 Warning (docker-compose.yml comment) and ADR-004 suggestion

### Critical
- none

### Warning
- none

### Suggestion
- [docker-compose.yml] The file is untracked, so `git diff` cannot prove the change is comment-only. Checked by inspection instead: lines 24-27 are `#` comments only, the functional keys are intact, and `docker compose config -q` passes. Commit the file so later changes can be diffed.
- [decisions.md:64] The measurement is recorded as 2.808 GiB; the comment rounds it to 2.81 GiB. This is consistent.

### Verified
- Cycle 1 Warning fixed: the comment now reads "Measured once on 2026-10-14: 2.81 GiB of 8 GiB with llama3.2:1b + bge-m3 at 8192 context (decisions.md, Group 3 smoke test); the 3b control was not measured."
- ADR-004:38 now says "(README done; UI pending)".
- No leftover "Not measured" or "Scaffold only" claims. The remaining "not measured" hits are accurate (3b control, multi-input embed count, wattage).
- All 16 tasks in tasks.md (1.1-1.4, 2.1-2.4, 3.1, 4.1, F1.1-F1.3, F2.1-F2.3) are [x].
- `POSTGRES_PASSWORD=x docker compose config -q`: OK. `.venv/bin/pytest -q`: 105 passed, 3 deselected. `.venv/bin/ruff check .`: clean. `.venv/bin/mypy src`: no issues in 12 files.

### Tests
- [x] All tests passing
- [x] Coverage adequate for the change (docs and comments only)

### Verdict: PASS
