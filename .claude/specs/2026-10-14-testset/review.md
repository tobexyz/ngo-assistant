# Review: Test set (48 cases) from the real corpus

## Cycle 1 — 2026-10-14
Reviewing: Group 1 tasks 1.1-1.5

### Critical
- none

### Warning
- [scripts/build_corpus.py:94-126] Implicit end tags are only half handled. Unclosed `<p>`/`<li>` are fine (block start flushes), but an unclosed `<td>`/`<th>` fuses cells: `<tr><td>A<td>B<tr>...` gives `AB`, `<th>H1<th>H2` gives `H1H2`, a last row without `</td>` gives `CD`; cells are only collected on `</td>`, and `</tr>` discards the unflushed buffer. tech.md section 8 says end tags are not delivered, and the task asked for tests of unclosed `<p>`/`<td>`: tests/test_build_corpus.py has none (grep "unclosed|implicit" = 0 hits). Fix: close the open cell in handle_starttag for td/th/tr and at `</tr>`/`</table>`; add tests for unclosed p, li, td, tr. The real raw files are well formed (td/p/li open and close counts match), so no loss there today.
- [design.md:23-24, tasks.md:5 vs docs/tech.md:226-262] Inconsistent pypdf records. design.md and tasks.md say `pypdf==6.20.1 (released 2026-09-16)`; tech.md says 6.19.0 is 2026-09-16 and 6.20.1 is 2026-10-12. Section 7 is titled "pypdf 6.19.0", and its signatures and the real-file run are for 6.19.0, with "orchestrator decides" left open; nothing records 6.20.1 signatures (installed .venv has 6.20.1). The decision in decisions.md (security patch exempt) is correct and pyproject.toml has the exact pin `pypdf==6.20.1` in extra `corpus`; fix the dates in design/tasks and add a note or re-run of the signatures on 6.20.1 in section 7.
- [scripts/verify_testset.py:99-119] Bad cases can pass silently. (a) No minimum or maximum quote length: a one-word quote such as "ha" is found in any text (design says max about 300). (b) Blank absence terms: `["", " "]` satisfies the 2-4 count and never hits (`t and ...`). (c) The absence check passes vacuously when the corpus lacks files (empty or partial `data/corpus`, or a tenant source without `.txt`); main() never requires a text for every tenant source, although the design says "occur in NO corpus file". Fix: require quote length >= about 20 chars and <= about 300, reject blank terms (and terms under 4 chars), and fail if any tenant source has no corpus text. Add tests for each.
- [scripts/verify_testset.py:206-207] Sheet quote leak. `show` is computed from `case.source_ids` only, skipping ids not in the tenant and ignoring the claim's own `source_id`. A claim from a non-redistributable source that is not listed in `source_ids` (the check reports it as a problem, but the sheet is still written), or a case with only unknown ids (`all([])` is True), prints the quote. Fix: decide per claim from `by_id[claim.source_id].redistributable`, withhold when the source is unknown, and withhold when any cited or claimed source is non-redistributable. Add tests.
- [scripts/verify_testset.py:152-158] The expected_source_date exemption is broader than needed: any bare number equal to year, month or day (e.g. "10", "6", "2025") is accepted without a quote, so a wrong figure such as "5" passes if the day is 5. Fix: exempt only a number that appears in the answer as part of a date expression (full date or year), or require the date numbers to be matched with the full date string; add a test that a lone month/day number is not exempt. Also a numbers case whose expected_answer has no number at all passes the number check (see Suggestion).

### Suggestion
- [scripts/build_corpus.py] Stripping `header`/`aside`/`form` costs no article text. Measured on data/raw (inspect only): form adds 0 to 8 chars, Destatis header/aside add 0, UBA header adds 14 and aside is "Seitenleiste/Newsletter" only, EEA header is EU/EEA site chrome, EC header is the language picker. One real loss: owid-biodiversity header holds the title, the intro paragraph and byline (about 267 chars), and aside the "Related Topics" list; OWID has no `<main>`. Consider keeping the first `h1` inside `header` for OWID, or note it in decisions.md for task 2.1.
- [tests/test_testset.py] `notes` (design: one line stating the trap) is not checked; add a non-empty and single-line assertion. Group 3 numbers cases should also assert that expected_answer contains a digit (verify script as well).
- [scripts/verify_testset.py:main] Corpus read errors (`UnicodeDecodeError`) occur outside the try block and give a traceback instead of exit 2.
- [docs/tech.md] Sections 1-6 could not be diffed: the file is untracked (`?? docs/tech.md`) and the previous version is not in git. Headings 1-6 and the section 6 summary look intact and sections 7-10 are appended after them; the orchestrator may want to confirm against the earlier commit/copy. Section 10 repeats the title "Summary of UNVERIFIED items" of section 6; rename it.

### Checked and fine
- Accept/Verify 1.1-1.5 otherwise met; 1.2 table in decisions.md matches data/raw (24 files, gitignored). pyproject: exact pins, `corpus = ["pypdf==6.20.1"]`.
- build_corpus: all ten SKIP_TAGS dropped with a depth counter (script/style content via handle_data is covered because skipping is by depth); Wikipedia `mw-content-text` with a noted fallback; PDF detected by `%PDF-` magic bytes over extension; synthetic copied byte for byte; id validation and `contained()` for output and synthetic paths; exit 0/1; INDEX.md has id, language, kind, chars, first heading, notes.
- verify_testset: `1.430`=`1,430`=`1430`, `1.43`!=`1.430`; tokenised numbers so 14 does not match inside 142; absence check over all `*.txt`; exact withheld text; mixed-licence sheet withholds; tests per failure type present.
- test_testset: clear message when the file is missing ("evals/testset.jsonl missing: written in Group 3-4 ..."), honours NGO_TESTSET_PATH, NGO (`syn-*` 8-10), cross-language, canary (listed, in cited doc, 3 used, both languages, 2 with a second doc), 4 dated pairs, numbers date rule. No network in unit tests.

### Tests
- [x] All tests passing, as expected: `pytest -q` = 152 passed, 3 deselected, 24 errors (all in tests/test_testset.py, all "evals/testset.jsonl missing"); `ruff check .` clean; `mypy src` clean.
- [ ] Coverage adequate for the change: missing tests for unclosed td/tr/p/li, quote-length bounds, blank absence terms, vacuous absence check, sheet leak via claim source or unknown id, date exemption.

### Verdict: FAIL

## Cycle 2 — 2026-10-14
Reviewing: Group 1 tasks 1.1-1.5 plus Fix Group 1 (F1.1-F1.4)

### Critical
- none

### Warning
- none

### Suggestion
- [scripts/build_corpus.py header rule] A `<header>` with an `h1`/`p` outside `<nav>` is kept, so site chrome with a `<p>` leaks. Grep + approximation on data/raw (converter not run): eea-ghg-trends-2025 and eea-biodiversity-2025 have a header (about 936 chars after removing nav/aside/form/footer/svg) starting "An official website of the European Union | How do you know? ... Environmental information systems ... WISE marine ..."; this would appear at the top of the two EEA texts. Destatis headers contain `<p>` only inside nav (nothing left after skipping); Wikipedia headers are outside `mw-content-text` (inactive); OWID headers are the wanted title/intro. Impact is noise at the start of EEA texts (absence terms could hit it; quotes would not be taken from it). Task 2.1 should inspect the first lines of the EEA texts in INDEX.md/output and, if needed, drop that block there or add an EU-banner exclusion.
- [tests/test_testset.py:199] `c.notes.strip()` raises AttributeError if `notes` can be None in the schema; use `(c.notes or "").strip()`.
- [docs/tech.md] Sections 1-6 still not diffable (untracked file); unchanged from cycle 1.

### Cycle 1 warnings: status
1. Converter: FIXED. td/th/tr close the open cell/row in handle_starttag, `</tr>`/`</table>` flush; tests for unclosed td, th+last row, `</tr>` flush, p, li, tr exist and pass; header kept only with h1/p, chrome header dropped, nested chrome inside a kept header still dropped.
2. pypdf records: FIXED. pyproject `pypdf==6.20.1`; design.md:24 and tasks.md:5 say released 2026-10-12 and security-patch exempt; tech.md section 7 is "pypdf 6.20.1 (pinned version)" with signatures and real-file run; 6.19.0 kept as "7-history" labelled superseded; 2026-09-16 (6.19.0) and 2026-10-12 (6.20.1) match decisions.md.
3. verify_testset: FIXED. Quote length 8-400 after normalisation, blank/short(<4)/duplicate absence terms flagged, "corpus incomplete: ids" once in main() before cases, so an empty corpus fails; tests present (too short/long, blank, short, duplicate, incomplete reported once, empty corpus cannot pass).
4. Sheet visibility: FIXED. `involved` = source_ids union claim source_ids; each must be in source_ids and have `redistributable is True` (unknown/missing flag withholds); empty set withholds; tests for claim outside source_ids, unknown ids, missing flag, empty source_ids.
5. Date exemption: FIXED. Only ISO, dd.mm.yyyy, "d Month yyyy"/"d. Monat yyyy", "Month yyyy" spans are stripped; parametrised tests show bare day, month, year, wrong day/year/month are not exempt.
Extras: digit rule for numbers cases and non-empty notes in check_case (tested); UnicodeDecodeError converted to ValueError, main exits 2 (test_cli_decode_error_exit_two).

### Regression check
- `case()` helper now sets `notes`; this only satisfies the new notes rule and test_notes_required still covers empty/blank notes. Absence terms were lengthened ("only-one", "term-one"/"term-two") to meet the 4-char rule; the 2-4 count test and claims-must-be-empty test still assert the same messages. No test was weakened.
- tests/test_testset.py has test_every_case_has_notes and test_numbers_expected_answer_contains_a_digit; the suite fails only with "evals/testset.jsonl missing" (26 errors).

### Tests
- [x] All tests passing, as expected: `pytest -q` = 187 passed, 3 deselected, 26 errors (all tests/test_testset.py, missing evals/testset.jsonl); `ruff check .` clean; `mypy src` clean.
- [x] Coverage adequate for the change.

### Verdict: PASS

## Groups 3-5 — Cycle 1 — 2026-10-14
Reviewing: tasks 3.1-3.3, 4.1-4.2, 5.1 (task 5.2 docs excluded)

Mechanical checks: `pytest -q` 213 passed (3 deselected); `ruff check .` clean; `mypy src` clean; `verify_testset.py` on the merged set exits 0; `evals/parts/` is gone; `data/corpus/` is gitignored (evidence.jsonl untracked/ignored).

Independent spot check against `data/corpus/*.txt` (grep -a), 44 of 48 cases read, dates compared with tenant `published`:
ans-01, 02, 03, 05, 06, 07, 08, 09, 10, 11, 12 ok; una-01..07 ok (absence terms grep to zero files; "Spain" only in the EEA 2024 member list, "Türkçe"/"Español" only language menus); mul-01 ok (43/49 vs 47/54, dates 31 Oct 2024 / 06 Nov 2025, +4/+5 points, re-blind agrees); mul-02..08 ok (mul-08 see Suggestion); num-01..08 all ok (all `expected_source_date` = newest cited `published`; 59,5 vs 59,7 PV restatement correct; 54,4 vs rund 54 correct); con-01 ok (scenarios labelled, summary calls 49% "current"); con-02 ok ("endgültige Werte" footnote present); con-03..07 ok (con-07 13,2 TWh / +25 % at dewiki-green-it line 87); con-08 see Warning; inj-01..05 ok (answers match the page text, no canary in any expected answer, no question mentions a hidden instruction).

### Critical
- none

### Warning
- [evals/testset.jsonl con-08] The expected answer gives the Destatis 2024 value as 59,4 % (12 March 2025 release) without saying it was restated. The newer Destatis release (destatis-strom-2025 table, footnote "endgültige Werte") has 59,5 % for 2024, and con-02 correctly treats 59,5 % as the current value. The notes of con-08 even say 59,5 % is final, yet `source_ids` omit destatis-strom-2025. A variant that reads both releases and answers 59,5 % would be graded wrong, and the case contradicts the "newer supersedes" rule used in con-02/num-06. Fix: add destatis-strom-2025 to `source_ids` (plus evidence quote) and state "59,4 % (preliminary, 12 March 2025), restated to 59,5 % (final, 6 March 2026)", or rewrite the question to pin the release.

### Suggestion
- [mul-08] Same 59,4 % vs restated 59,5 % point; the conclusion ("higher") is unaffected, but mention the restatement or pin "in the March 2025 release" in the question.
- [ans-02] "schlechten oder sehr schlechten Zustand" is not in the source ("poor or bad"); use "schlechten Zustand".
- [ans-03 / num-05, con-03 / num-04] Near-duplicate questions on the same fact and source (OWID 1950; UBA 2024 share). Acceptable, but they weight one fact twice.
- [handcheck.md] The locator headings for UBA cases show UBA heading text (short titles, no sentence quotes); acceptable, could be reduced to block numbers only.
- [una-07 notes] Fine, but absence_terms are German only; the notes already document the English "Spain" hit.

### Checks 3-6
- Question quality: no question contains its answer; the 7 unanswerable cases are plausible; injection questions are ordinary.
- Distribution: 12/7/8/8/8/5 = 48; 24 de + 24 en; 9 cases cite syn-* ids; 14 cross-language cases; all four dated pairs cited together (EEA: mul-01, num-01, con-01; Destatis: mul-02, num-06, con-02; UBA: num-04, con-03; synthetic: con-04).
- Licence: longest verbatim run from OWID in any expected answer is 12 words (ans-12), UBA none above the short-phrase level; handcheck.md has no UBA sentence (checked against both UBA texts); all 7 UBA-citing cases carry exactly "[quote withheld: licence; see data/corpus/evidence.jsonl]" for every quote line, no other case does (sheet withholds also the Destatis quote in mul-05/08, con-08, as designed).
- decisions.md records the blind check (42 match / 5 partial / 1 disagree, 48/48 found agreement), the resolutions, and the re-blind of mul-01. The eight named cases (mul-01, con-01, num-01, con-07, una-07, una-04, con-02, con-08) show the changes; con-06 and mul-04 are unchanged. Not mechanically provable which other fields changed, since the pre-resolution set was never committed.

### Tests
- [x] All tests passing
- [x] Coverage adequate for the change (tests/test_testset.py: distribution, ids, languages, cross-language, tenant ids, canaries, dates, notes, digits)

### Verdict: FAIL

## Cycle 2 (Groups 3-5 + public evidence + docs) — 2026-10-15
Reviewing: whole spec, incl. con-08/mul-08 fix, generated sheet header, `evals/evidence.jsonl`, task 5.2 docs.

### Critical
- none

### Warning
- [docs/testset-guide.md:23-25, decisions.md:104] Cross-language count is wrong. Docs say 15 with ids "... con-04, con-08, inj-01, inj-02, inj-04". Recomputed the way tests/test_testset.py does (`any(source language != case language)`, languages from the tenant): 14 cases = ans-02, ans-04, ans-05, ans-09, ans-10, mul-01, mul-03, mul-04, mul-07, mul-08, num-08, con-04, con-08, inj-05. inj-01, inj-02, inj-04 cite only English synthetic sources for English questions (not cross-language); num-08 and inj-05 are missing from the list. Fix: "14" and the list above (also in decisions.md line 104).
- [tasks.md:58] Task 4.2 (independent blind check) is still `[ ]` although decisions.md records it as done (42/5/1 and re-blind of mul-01). All other 15 tasks are `[x]`. Fix: mark `[x]`.

### Suggestion
- [scripts/verify_testset.py:196-201] For claims that carry a quote, `start`/`end` are never checked against the quote (tamper test: ans-04 `start`+1 in a copy of the public file still exits 0). Only the sha256 vs quote is checked (tamper of ans-01 sha256: exit 1, names `ans-01: claim eea-ghg-trends-2025 ('36% fall 1990-2023')`). For quote-null claims both are checked (tamper of ans-07 sha256: exit 1, names `ans-07: claim uba-erneuerbare-2025 ('41 % target for 2030'): sha256 of corpus text at offsets 5900-6063 does not match`). Offsets of quoted claims are informational, so harmless; add `normalise(text)[start:end] == normalise(quote)` for consistency, or state it in the guide.
- [decisions.md:3-6, 105] Stale: the first entry ("Evidence kept in gitignored files") does not mention the later public `evals/evidence.jsonl`, and line 105 says "18 withheld quote lines" (sheet now has 22: 12 UBA claims + 10 in mixed-source cases). No decision entry for the public evidence file or the con-08 fix (only docs/testset-guide.md records it). Add a short entry.
- [README.md:157-166] The `verify_testset.py` description says every evidence quote occurs verbatim; for `quote: null` claims it is an offset+sha256 check, and `--export-public-evidence` is not in the command list (only mentioned under "reproducible"). Add one sentence.
- [resumeId.txt] Untracked stray file in repo root; do not commit.
- [evals/testset.jsonl ans-02] Cycle-1 suggestion still open ("schlechten oder sehr schlechten Zustand" vs source "poor or bad").

### Checks
1. Cycle-1 warning fixed. con-08: source_ids = destatis-strom-2024, destatis-strom-2025, uba-erneuerbare-2025; states 59,4 % preliminary (12 March 2025) restated to 59,5 % final (6 March 2026), UBA 54,4 % of gross consumption (05.03.2026), feed-in vs gross consumption not comparable. Verified: destatis-strom-2024 says "59,4 %" "nach vorläufigen Ergebnissen"; destatis-strom-2025 table row "Erneuerbare Energieträger | 257,1 | 59,5 | ..." with footnote "1: endgültige Werte 2: vorläufige Werte" (2024 columns carry marker 1) and text "(2024: 59,5 %)"; UBA 2025 contains "54,4" and is dated 05.03.2026. mul-08: source_ids include destatis-strom-2025, answer says "later restated to 59.5%", notes the feed-in vs gross-consumption bases and that UBA is a forecast (UBA 2024 PM: "voraussichtlich", Bruttostromverbrauch). OK.
2. `pytest -q`: 228 passed, 3 deselected. `ruff check .` clean. `mypy src` clean (12 files). Verifier with `evals/evidence.jsonl` exit 0; with `data/corpus/evidence.jsonl` exit 0 (checked with the real exit status, no pipe).
3. Public evidence: 48 records; 103 claims with quote, 12 with `quote: null`; null exactly for claims of the two non-redistributable sources (uba-erneuerbare-2025, uba-erneuerbare-pm-2024), no mismatch either way; every claim has start, end, sha256, numbers. `occurrences: 2` only for con-02 and con-08 on destatis-strom-2025 (the table row text occurs twice: text plus table); the hash is of the first occurrence, a true quote, acceptable. 6-word-window comparison of both UBA texts against the three files: evidence.jsonl 0 hits; testset.jsonl 3 hits ("der anteil erneuerbarer energien am bruttostromverbrauch", "54 4 prozent im jahr 2024", a chart title); handcheck.md 8 hits, all headings/titles ("Erneuerbare Energien in Deutschland Wachstum 2025 verhalten", "Erneuerbarer Strom weiterhin Eckpfeiler der Energiewende", the table heading). Short phrases and titles only; no UBA sentence.
4. Sheet: generated header lists 20 cited sources (all cited ones; the two uncited syn sources are not listed) with licence, published date and redistributable yes/no; the 22 "[quote withheld: licence; ...]" lines; quote-null claims never print a quote. 8 randomly chosen sheet quotes (num-08, mul-02, con-01, inj-03, ans-08, ans-11, con-06, mul-01) found verbatim in data/corpus text.
5. Docs: counts 12/7/8/8/8/5, 24/24 (de/en), 9 syn-citing (list ans-10, num-08, con-04, con-05, inj-01..05 correct), 22 sources, 12 real: correct. `--export-public-evidence`, `--write-sheet`, `--date` exist in `--help`; commands and paths exist. Reproducibility statement (fetch + build + verify with evals/evidence.jsonl; pages may change after 2026-10-14) accurate. README says "Variants A and B are still stubs ... assistant does not answer anything yet". No stale "cannot run from a clean checkout" text (grep). testset-guide describes the con-08 fix and the EEA like-for-like finding (43/49 vs 47/54) factually. Exception: cross-language count (Warning above). Note: public evidence file is untracked, not ignored: must be added with the commit.
6. tasks.md: all `[x]` except 4.2.

### Tests
- [x] All tests passing (228 passed, 3 deselected; ruff, mypy clean; both verifier runs exit 0)
- [x] Coverage adequate for the change (tamper detection tested manually above; quoted-claim offsets not covered)

### Verdict: FAIL

## Cycle 3 — 2026-10-15
Reviewing: verification of cycle-2 Warnings and regression

### Critical
- none

### Warning
- none (both cycle-2 Warnings fixed: docs/testset-guide.md:23 lists the 14 cross-language ids, matching an independent recomputation from tenant `language` fields; no "15 cases"/"15 cross" left in README.md, docs/ or spec files; tasks.md has no `- [ ]` or `- [!]`)

### Suggestion
- Open from cycle 2 (informational): offsets of quoted claims are not re-checked by the verifier.

### Tests
- [x] All tests passing (228 passed, 3 deselected; ruff clean; mypy clean; verify_testset.py with evidence.jsonl exits 0)
- [x] Coverage adequate for the change
- decisions.md corrections accurate: `grep -c "quote withheld" evals/handcheck.md` = 22.

### Verdict: PASS
