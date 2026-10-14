# Tasks: Test set (48 cases) from the real corpus

Plan: `.claude/specs/2026-10-14-testset/requirements.md` and `design.md`

New dependency: `pypdf==6.20.1` (released 2026-10-12, security patch exempt from the 7-day rule, see decisions.md), optional extra `corpus`.
Writers read ONLY converted text in `data/corpus/` and synthetic files; no knowledge from memory.

## Group 1: Research, download, corpus converter, verify script, test skeletons

- [x] 1.1 Research pypdf and conversion APIs | `docs/tech.md`
  - **Packages**: `pypdf==6.20.1`
  - **Accept**: `docs/tech.md` has a section with source URL + date for: pypdf version/date/advisories (PyPI JSON, GitHub advisories), `PdfReader(path)`, `.pages[i].extract_text()` signatures from `inspect.signature()` in a scratch venv; `html.parser.HTMLParser` hooks used; the de.wikipedia article-body container (`mw-content-text`) checked against the downloaded pinned revision when available (otherwise noted UNVERIFIED).
  - **Verify**: signatures pasted from a scratch venv; every row has URL or command output.
  - **Constraints**: no facts from memory; edit only docs/tech.md.
- [x] 1.2 Download the 12 real sources | `data/raw/` (gitignored), `.claude/specs/2026-10-14-testset/decisions.md`
  - **Accept**: one run of `scripts/fetch_sources.py --tenant tenants/moorfunke.yaml` (user approved the real download on 2026-10-14; script honours robots.txt and crawl delays UBA 10 s, Destatis 30 s); per-source result table in decisions.md (status, bytes, content type, sha256 from meta.json); failed sources retried once, then reported, not worked around; no file committed or staged.
  - **Verify**: `ls -l data/raw/`; `git status --short data/ | head` shows nothing under data/raw; `git check-ignore data/raw/x`.
  - **Constraints**: no code changes; do not bypass robots.txt or use another tool to fetch; do not run the script twice for the same source except the single retry.
- [x] 1.3 Corpus converter | `scripts/build_corpus.py`, `tests/test_build_corpus.py`, `pyproject.toml`
  - **Packages**: `pypdf==6.20.1` (extra `corpus`)
  - **Accept**: converts html/pdf to text per design.md ("Pipeline"); copies synthetic files; writes `data/corpus/INDEX.md` (id, language, chars, first heading); `--min-chars` check; tests with small fixtures (nav/script stripped, headings and table cells kept, Wikipedia body only, PDF fixture generated in test or skipped with reason if pypdf missing).
  - **Verify**: `.venv/bin/pip install --no-input -e ".[dev,corpus]" && .venv/bin/pytest tests/test_build_corpus.py -q && .venv/bin/ruff check . && .venv/bin/mypy src`
  - **Constraints**: stdlib + pypdf only; do not run it on the real files in this task (Group 2); pyproject pins exact.
- [x] 1.4 Verification script | `scripts/verify_testset.py`, `tests/test_verify_testset.py`
  - **Accept**: implements the contract in design.md ("Interfaces & Contracts"): quote-in-text with normalisation, numbers-in-quotes, absence check, multi-step needs 2 sources, tenant ids, date rule; `--write-sheet` generates `evals/handcheck.md` with withheld quotes for non-redistributable sources; tests with fixtures cover each failure type.
  - **Verify**: `.venv/bin/pytest tests/test_verify_testset.py -q && .venv/bin/ruff check . && .venv/bin/mypy src`
  - **Constraints**: stdlib + ngo_assistant only; no network.
- [x] 1.5 Test-set test skeleton | `tests/test_testset.py`
  - **Accept**: encodes the checks listed in design.md for `tests/test_testset.py`; fails (red) only because `evals/testset.jsonl` does not exist yet, with a clear message.
  - **Verify**: `.venv/bin/pytest tests/test_testset.py -q` fails with the file-missing message, no syntax errors.
  - **Constraints**: do not create `evals/testset.jsonl`; the NGO-specific rule counts cases citing any `syn-*` id.

## Group 2: Convert and inspect the corpus

- [x] 2.1 Convert real sources to text and report quality | `data/corpus/` (gitignored), decisions.md
  - **Accept**: `scripts/build_corpus.py` run on `data/raw/`; table of chars per source in decisions.md; for each source a one-line judgment (usable / thin / unusable) with the reason; for thin or unusable sources a proposal (retry with other URL of the same page is NOT allowed without a decision; report to the orchestrator).
  - **Verify**: `.venv/bin/python scripts/build_corpus.py --tenant tenants/moorfunke.yaml --raw data/raw --out data/corpus; echo $?` and `wc -c data/corpus/*.txt`
  - **Constraints**: no edits to texts by hand; no commit.

## Group 3: Write the cases (three writers in parallel, disjoint files)

- [x] 3.1 answerable (12) + unanswerable (7) | `evals/parts/answerable-unanswerable.jsonl`, `data/corpus/evidence-au.jsonl`
  - **Accept**: cases per design.md rules; evidence for every case; about 4 NGO-specific; at least 1 cross-language; `load_testset` passes on the part file.
  - **Verify**: `.venv/bin/python scripts/verify_testset.py --testset evals/parts/answerable-unanswerable.jsonl --tenant tenants/moorfunke.yaml --corpus data/corpus --evidence data/corpus/evidence-au.jsonl`
- [x] 3.2 multi_step (8) + numbers (8) | `evals/parts/multistep-numbers.jsonl`, `data/corpus/evidence-mn.jsonl`
  - **Accept**: same rules; multi_step uses at least 2 documents each (incl. at least 2 cross-language); numbers cite a date equal to the tenant's `published`; the EEA and Destatis pairs appear in at least one case each.
  - **Verify**: same script with these files.
- [x] 3.3 contested (8) + injection (5) | `evals/parts/contested-injection.jsonl`, `data/corpus/evidence-ci.jsonl`
  - **Accept**: contested covers every pair in docs/testset-guide.md (EEA, Destatis, UBA, synthetic 142->128 ha) and the greenwashing partner claim plus at least 1 OWID/Wikipedia age-or-caveat case; injection cases per design.md (5 cases over 3 canary documents, both languages, at least 2 with a second legitimate document); canaries read from CANARIES.md and checked with grep.
  - **Verify**: same script with these files.
  - **Constraints (all of 3.x)**: write from the converted texts and synthetic files only; quotes verbatim; `expected_answer` never copies more than a short phrase from OWID/UBA text; no hand-editing of data/corpus texts; unique ids `<cat>-NN`; do not touch other writers' files.

## Group 4: Merge, verify, blind check

- [x] 4.1 Merge and mechanical verification | `evals/testset.jsonl`, `evals/handcheck.md`, `data/corpus/evidence.jsonl`
  - **Accept**: parts merged (sorted by category then id), `load_testset` returns 48 with the required distribution; `verify_testset.py` exits 0; `evals/handcheck.md` generated; `tests/test_testset.py` green.
  - **Verify**: `.venv/bin/pytest -q && .venv/bin/python scripts/verify_testset.py --testset evals/testset.jsonl --tenant tenants/moorfunke.yaml --corpus data/corpus --evidence data/corpus/evidence.jsonl --write-sheet evals/handcheck.md`
- [x] 4.2 Independent blind check | `data/corpus/blindcheck.jsonl`, decisions.md
  - **Accept**: a different agent answers all 48 questions from the corpus without seeing expected answers or evidence; comparison table in decisions.md; every material disagreement lists the case id and the proposed resolution (fix expected answer, rewrite question, or mark as intended ambiguity for contested cases).
  - **Constraints**: the blind agent must not read `evals/` or `data/corpus/evidence*.jsonl`, `data/corpus/blindcheck*`.

## Group 5: Resolve disagreements, documentation

- [x] 5.1 Apply resolutions and re-verify | `evals/testset.jsonl`, `data/corpus/evidence.jsonl`, `evals/handcheck.md`
  - **Accept**: all disagreements resolved per decisions.md; verify script exit 0; pytest green.
  - **Verify**: same as 4.1.
- [x] 5.2 Update documentation for plan changes | `README.md`, `docs/testset-guide.md`, `docs/`
  - **Accept**: README layout/status/commands cover corpus build, verify script, `evals/` files and the hand-check step; testset-guide records the final distribution and the evidence rules; ADR-001 consequences note quotes of non-redistributable sources stay out of git.
  - **Verify**: `grep -rn 'TODO\|FIXME\|PLACEHOLDER' README.md docs/ || true` no plan-related placeholders.
  - **Constraints**: do not document Variants A/B as implemented.

## Fix Group 1: Address review cycle 1

- [x] F1.1 Converter: unclosed table cells, OWID header text | `scripts/build_corpus.py`, `tests/test_build_corpus.py`
  - **Accept**: unclosed `<td>`/`<th>`/`<tr>` no longer fuse cell text (`<tr><td>A<td>B<tr>...` -> `A | B`; last row without `</td>` keeps its text; `</tr>` flushes the buffer); tests for unclosed p, li, td, th, tr; `<header>` content is kept when it contains an `h1` or `p` (OWID puts the title and intro paragraph there) while site-chrome headers without them are still dropped; same for nothing else stripped by accident.
  - **Verify**: `.venv/bin/pytest tests/test_build_corpus.py -q && .venv/bin/ruff check . && .venv/bin/mypy src`
- [x] F1.2 Record pypdf 6.20.1 facts | `docs/tech.md`
  - **Accept**: section 7 is titled for 6.20.1 (the pinned version) and records, from a scratch venv with `pypdf==6.20.1`: signatures of `PdfReader.__init__` and `PageObject.extract_text`, and the real-file run on `data/raw/eea-ghg-trends-2024.pdf` (page count and chars per page, no text pasted); the 6.19.0 findings stay as history, clearly labelled; section 10 title no longer duplicates section 6's; the release dates stated match PyPI (6.19.0 on 2026-09-16, 6.20.1 on 2026-10-12).
  - **Verify**: signatures pasted from command output; `grep -n "6.20.1" docs/tech.md`.
- [x] F1.3 Verify script gaps | `scripts/verify_testset.py`, `tests/test_verify_testset.py`
  - **Accept**: (a) quote length bounds: at least 8 characters after normalisation and at most 400; (b) absence terms must be non-blank after normalisation, at least 4 characters long, and distinct; (c) every non-synthetic AND synthetic tenant source must have a corpus text file, otherwise a problem is reported once ("corpus incomplete: <ids>") before the absence check, so an empty corpus cannot pass vacuously; (d) the sheet decides quote visibility from the union of `case.source_ids` and every claim's `source_id`, treats unknown ids and sources missing the redistributable flag as NOT redistributable, and never prints a quote when the case has problems about sources; (e) the date exemption applies only to numbers inside a recognised date expression of `expected_source_date` (ISO yyyy-mm-dd, dd.mm.yyyy, "12 March 2025", "12. März 2025", "March 2025"), plus a bare year only when directly preceded by a month name; a bare "5" equal to the day is NOT exempt; (f) numbers cases need at least one digit in `expected_answer`; `notes` must be non-empty for every case; (g) decode errors on corpus files exit 2 with a message, no traceback. Tests for each.
  - **Verify**: `.venv/bin/pytest tests/test_verify_testset.py -q && .venv/bin/ruff check . && .venv/bin/mypy src`
  - **Constraints**: also add the `notes` and digit rules to `tests/test_testset.py` ONLY if F1.3 agent is told; otherwise leave it (separate task below).
- [x] F1.4 Test-set test: notes and digits | `tests/test_testset.py`
  - **Accept**: tests that every case has non-empty `notes` and that numbers cases contain a digit in `expected_answer`; still red only because the file is missing; still passes against the throwaway valid set via NGO_TESTSET_PATH (build one in the scratchpad, then delete it).
  - **Verify**: `.venv/bin/pytest tests/test_testset.py -q` (24+ errors with the missing-file message) and `.venv/bin/ruff check tests`.
