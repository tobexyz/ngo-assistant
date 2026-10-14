# Decisions: Test set

## 2026-10-14 — Evidence kept in gitignored files
**Context**: UBA (CC BY-NC-ND, not redistributable), OWID (no editing) and Wikipedia (share-alike) quotes would be copies in git.
**Decision**: Full quotes live in `data/corpus/evidence.jsonl` (gitignored); the committed `evals/handcheck.md` withholds quotes whose sources are not redistributable.
**Rationale**: Traceability without redistribution (ADR-001).

## 2026-10-14 — Group 1 download
**Context**: Task 1.2. The user approved one real download of the 12 non-synthetic sources of `tenants/moorfunke.yaml` on 2026-10-14. Run once: `scripts/fetch_sources.py --tenant tenants/moorfunke.yaml --out data/raw` (robots.txt and crawl delays honoured by the script; unchanged script and User-Agent). Exit code 0, 12 considered, 0 failed. No retries were needed; nothing was refused by robots.txt.

| id | status | HTTP | content type | bytes | sha256 | error |
|---|---|---|---|---|---|---|
| eea-ghg-trends-2025 | ok | 200 | text/html; charset=utf-8 | 1220160 | d8fcdc84a905a5b56a3c8b4c24c815bb0fa124fcd1b4d887545afd3bbe330c9f | none |
| eea-ghg-trends-2024 | ok | 200 | application/pdf | 471884 | 200abc39084f2f3d1925f5b31193f0ea803b4a97a2349eb516f0aa88065d0e16 | none |
| eea-biodiversity-2025 | ok | 200 | text/html; charset=utf-8 | 1259503 | 325599f379ffed976f677bd568672dfee4e774ab84ae8eaa5c6de5f6e1dfb230 | none |
| owid-co2-emissions | ok | 200 | text/html; charset=utf-8 | 164697 | 6b1e2eb6feec509824813340b8ca33d2fbd82ba94380605d5ba23d26b7c71905 | none |
| owid-biodiversity | ok | 200 | text/html; charset=utf-8 | 284151 | 3acfb2657f53fb55577d76e846584af761db69d1b6eb43b097c8f8e9dfd9cc5b | none |
| ec-cloud-energy-2020 | ok | 200 | text/html; charset=utf-8 | 157772 | 3ce78e87b70072a968649ed31eed614de3e96f15f3fbbc8f277a4cdc0c8a992a | none |
| destatis-strom-2024 | ok | 200 | text/html;charset=utf-8 | 88332 | 5bc7f80e6d2b2dcb7ee6774d3d7310fbd666b4484579fcd24bb6c8f66bc1f579 | none |
| destatis-strom-2025 | ok | 200 | text/html;charset=utf-8 | 90286 | 7ffdc0df8c65754528b031b2d81ab21a281b472c2ef10653ef2738ed50213150 | none |
| dewiki-green-it | ok | 200 | text/html; charset=UTF-8 | 194883 | 4aec58287326aba2b4189a10575f93c8f8d39f2464ff46850e61e70e18fc42b4 | none |
| dewiki-rechenzentrum | ok | 200 | text/html; charset=UTF-8 | 604329 | e746932358a3bed68bea1323a4964a029d5e0c8ddef982918d6e0b7eb813a892 | none |
| uba-erneuerbare-pm-2024 | ok | 200 | text/html; charset=UTF-8 | 249179 | 080f6cf2d34aa946951776f3403d299ef22f45e1394869d57449c0e69c7d93a0 | none |
| uba-erneuerbare-2025 | ok | 200 | text/html; charset=UTF-8 | 253540 | e889597511538d76947c389ef9acd17890a5ddf5e3a6ef50028336b0e013e401 | none |

**Files in `data/raw/`**: 24 files, one `<id>.<ext>` plus one `<id>.meta.json` per source (11 `.html`, 1 `.pdf` = eea-ghg-trends-2024). Total about 4.9 MB.

**Page check (head -c 400 and title/keyword grep)**: all 11 HTML files start with a real document and a real article `<title>`; the PDF starts with `%PDF-1.4`. No bot-detection or block page. "cookie" strings occur in all HTML files, but only as normal consent-banner/UI markup alongside the real article; "captcha" occurs only in the Wikipedia pages (standard UI strings). Note: eea-*.html are React pages (about 1.2 MB each, likely with much embedded JSON/script); whether the article text is present in server-rendered HTML is for task 2.1 to judge. owid-*.html carry `class="js-disabled"` (server-rendered; charts will not have data).

**Git check**: `git status --short data/` shows only `?? data/` (untracked, nothing staged); `git check-ignore -v data/raw/x` matches `.gitignore:17:data/raw/`.

## 2026-10-14 — pypdf pin moved from 6.19.0 to 6.20.1 (security patch)
**Context**: Task 1.1 found four GitHub advisories (medium, DoS only) covering 6.19.0: GHSA-39mj-jf6j-2qj3 and GHSA-7mh2-4gg2-979f (fixed in 6.20.0; reachable on our PDF-reading path with a hostile PDF), GHSA-qfv9-64jg-mh7p and GHSA-9mx8-4j7g-633p (fixed in 6.20.1; PdfWriter outline functions we do not call). 6.20.1 was released 2026-10-12.
**Decision**: Pin `pypdf==6.20.1`. The 7-day quarantine does not apply to security patches (dependency-versions.md). Only PDF read: the known EEA file.
**Rationale**: Rule says upgrade immediately for known vulnerabilities. Open: CVSS vectors and CVE ids unverified (tech.md section 10).

## 2026-10-14 — Review cycle 1 (Group 1): FAIL, 5 warnings, Fix Group 1 created
**Context**: Warnings: unclosed table cells fuse text; pypdf records inconsistent (my sed had put the wrong release date for 6.20.1 into design.md/tasks.md; fixed by me); verify_testset gaps (quote length, blank absence terms, empty-corpus pass, sheet quote leak, over-broad date exemption).
**Decision**: Fix Group 1 (F1.1-F1.4). OWID header text (title + intro) is kept via the converter fix, since writers read only the converted text. Corpus decode errors exit 2.

## 2026-10-14 — Group 1 gates passed; sheet quote rule clarified
Review cycle 2 PASS, security review cycle 1 PASS (0 Critical, 0 Warning). pip-audit on pypdf==6.20.1: no known vulnerabilities.
**Clarification**: the committed `evals/handcheck.md` prints a verbatim quote only when every cited source has `redistributable: true` in the tenant (OWID CC BY 4.0 and de.wikipedia CC BY-SA 4.0 qualify: unaltered quote, source and licence named; UBA CC BY-NC-ND never). This replaces the earlier wording that put OWID/Wikipedia quotes only in gitignored files. The sheet header must name the sources and licences (done in task 5.2 or when generated); ADR-001 gets the rule in 5.2.
**Deferred suggestions**: build_corpus handle_data is quadratic on hostile pages (20k inline tags 1.5 s; 80k 23 s); no --max-bytes/page cap (inputs are the known 12 sources); EEA header banner ("An official website of the European Union ...") will appear at the top of the two EEA texts (inspect in 2.1); tests/test_testset.py notes check should tolerate None.
**Group 2 gate**: Group 2 changes no tracked files (outputs in gitignored data/corpus/ and decisions.md): review gates skipped, as in the previous spec's Group 3.

## 2026-10-14 — Group 2 corpus quality (task 2.1)
**Context**: `scripts/build_corpus.py --tenant tenants/moorfunke.yaml --raw data/raw --out data/corpus` run once, exit 0, "22 source(s), 0 failed or thin". No hand edits; nothing fetched. The 10 synthetic files are byte-identical to `data/synthetic/*.md` (`cmp`). Chars below are from INDEX.md (decoded characters); `wc -c` bytes are slightly higher (umlauts).

| id | chars | verdict | reason |
|---|---|---|---|
| eea-ghg-trends-2025 | 31994 | usable (noisy top) | Article body present from line 93 ("Published 06 Nov 2025", intro, Figure 1-2 captions, key numbers, policy sections, refs). Lines 1-92 are site banner, EU-institution links, 24-language list. No JSON. Chart data absent (figure captions only). |
| eea-ghg-trends-2024 | 32062 | usable | PDF, 14 pages, chars per page [135, 1287, 3715, 1954, 2703, 1901, 3491, 4047, 3557, 2128, 3141, 1579, 1390, 879]; clean running text with `[page N]` markers; some ligature loss ("signi cant"). 49 % statement present (page 2). |
| eea-biodiversity-2025 | 9862 | usable (thin-ish, noisy top) | Body from line ~97 ("Published 29 Sept 2025"): key messages, key policies, past trends with 81 % / 39 % / 62 %, outlook, prospects. Short (about 7k chars of body); banner and navigation at top; reference list at end. Figures are not in the text. |
| owid-co2-emissions | 23678 | usable | Title, byline, intro, ~20 section headings with running-text paragraphs; interactive charts contribute only captions. Few numbers in text (see below). |
| owid-biodiversity | 23944 | usable | Title, intro, "Key insights" and sections with running text and numbers (73 %, 85 %). Chart captions only. |
| ec-cloud-energy-2020 | 2331 | usable but short | Full news article (2 min read): both key figures in the lead sentence, Vestager and Breton quotes, study description. Dated 9 November 2020. |
| destatis-strom-2024 | 8467 | usable | Press release No. 091 of 12 March 2025, bullets, body, and the table "Netzeinspeisung" as `|`-separated rows. "Lädt..." placeholders for charts (3x). |
| destatis-strom-2025 | 8639 | usable | Press release No. 073 of 6 March 2026, same structure, table present. "Lädt..." 3x. |
| dewiki-green-it | 30438 | usable | Body only, revision oldid=267912244; 21 "[Bearbeiten | Quelltext bearbeiten]" edit markers remain; image captions kept (e.g. Energy-Star logo); two stray "Wikipedia:WikiProjekt Ereignisse/..." lines (timeline template residue); Literatur, Weblinks, Einzelnachweise (about 25 lines of 323) at the end. Content is old-ish (many 2007-2014 figures). |
| dewiki-rechenzentrum | 66756 | usable (long) | 8837 words, 655 lines, oldid=271299132; 53 edit markers; "Siehe auch / Literatur / Weblinks / Einzelnachweise" from line 369 (about 290 lines are references, roughly 45 % of lines but less of the chars). Hatnote at line 1; image captions inline. Contains post-June-2026 content and refs (up to Oct 2026). |
| uba-erneuerbare-pm-2024 | 7174 | usable | Title line has site-skip links ("Direkt zum Inhalt ..."); photo credit line; press release No. 50/2024 of 12.12.2024 with full body; footer "Kurzlink", "Oben". Dated text is a forecast ("voraussichtlich"). |
| uba-erneuerbare-2025 | 8738 | usable | Press text dated 05.03.2026 with all sections; same minor chrome. |
| syn-* (10 files) | 1187-1957 | usable | Copied unchanged (`cmp` identical). CANARIES.md and LICENCE.md are not copied (correct: not tenant sources). |

**Key figures (exact text, source id)**
- eea-ghg-trends-2025: "fell by 36% between 1990 and 2023"; "year-on-year drop of 2.5% between 2023 and 2024"; "a 47% reduction in net emissions will be reached by 2030 compared to 1990 levels"; "a projected 54% reduction by 2030"; "bringing estimated 2024 emissions to 37% below 1990 levels"; "69% below 1990 levels in 2040 and 78% in 2050". The 2030 projection is 47 % here, not 49 %.
- eea-ghg-trends-2024 (PDF, page 2): "fell by 31% in the EU-27 between 1990 and 2022"; "record year-on-year reduction of 8% in 2023"; "suggest that a 49% reduction in net emissions will be reached by 2030 compared to 1990 levels, missing the 55% reduction target for 2030". Contested pair confirmed: 49 % (published 31 Oct 2024) vs 47 % (06 Nov 2025). Page 2 also states 31 % vs the 2025 page 36 % (different base year 2022 vs 2023).
- eea-biodiversity-2025: "81% of habitats, 39% of birds and 62% of non-bird species of community interest are in a poor or bad state"; "In 2021, 38% of rivers, lakes, and transitional and coastal waters achieved a good or high ecological status".
- destatis-strom-2024: "Mit einem Anteil von 59,4 %"; total 431,5 Mrd. kWh, -3,6 %.
- destatis-strom-2025: "Anteil von 58,6 %" for 2025 and "(2024: 59,5 %)"; table row "Erneuerbare Energieträger | 257,1 | 59,5 | 256,9 | 58,6 | -0,1"; 2024 total in the 2025 table 432,1 (vs 431,5 in the 2024 release). So 59.4 % -> 59.5 % is a revision of the same year; 59.5 % is the 2024 value, not the 2025 value.
- uba-erneuerbare-pm-2024: "steigt damit auf rund 54 Prozent" (forecast, share of Bruttostromverbrauch, 2024).
- uba-erneuerbare-2025: 54,4 Prozent (2024) and 55,1 Prozent (2025) of gross electricity consumption (Bruttostromverbrauch); also 23,8 Prozent of gross final energy consumption in 2025. Contested pair: "rund 54" (forecast) vs "54,4" (final) for 2024.
- ec-cloud-energy-2020: "increase from 2.7% of the electricity demand in 2018 to 3.2% by 2030".
- owid-co2-emissions: "In 1950 the world emitted 6 billion tonnes of CO2"; "more than 90% of emissions were produced in Europe or the U..." (1900, sentence truncated in my view); "around 0.1 tonnes per year" (poorest countries); "accounting for 3-4% of global emissions each" (Africa, South America). Page "first published in June 2020", minor text changes January 2024.
- owid-biodiversity: "declined by 73%, on average" (Living Planet, since 1970); "declined by 85% since the rise of humans" (wild mammals, biomass).
- dewiki-rechenzentrum: "ca. 205 Tera-Wattstunden (TWh)" (2018 worldwide); "rund 14 Milliarden Kilowattstunden" (DE 2018), "16 Milliarden, also drei Prozent" (2020); "ca. 20 TWh" (DE 2024); "1,0 bis 1,5 Prozent des globalen Stromverbrauchs" (IEA 2022).
- dewiki-green-it: "Im Jahr 2009 über ein Viertel (28 %)" standby; "2007 ... ungefähr 60 Prozent ... 33 TWh" households.

**Problems and proposed remedies (none applied)**
1. EEA banner and navigation (eea-ghg-trends-2025 lines 1-92, eea-biodiversity-2025 lines 1-~96): "An official website of the European Union | How do you know?" sits at line 5, followed by institution links, 24-language list. Harmless for quotes (they are verbatim from the body) but the retrieval corpus will contain about 90 junk lines per EEA page and the first heading in INDEX.md is wrong for ghg-2025/biodiversity. Remedy A (preferred): converter change for EEA pages: start output at the `<h1>`/"Published" line or drop `header`/language-switcher blocks (needs a task and tests; tracked-file change, orchestrator to decide). Remedy B: accept as is (it is realistic web noise) and document it. Writers must ignore it.
2. Charts and figures carry no data (EEA, OWID, Destatis "Lädt..." x3 each): questions about chart values would be unanswerable from the corpus. Remedy: writers use only text and the Destatis tables; no chart-value questions.
3. Wikipedia residue (edit markers 21 / 53, two "Wikipedia:WikiProjekt ..." lines in green-it, reference lists, "Normdaten" and "Abgerufen von" lines): quotes must avoid these; a strip of "[Bearbeiten | Quelltext bearbeiten]" lines at conversion time would remove noise (optional converter change).
4. dewiki-rechenzentrum is 66756 chars (about 8800 words) with roughly 290 reference lines: it dominates retrieval volume. Remedy: keep, but writers cite only body paragraphs; consider that its references contain future-dated entries (June-October 2026) that are normal for a live article.
5. UBA pages: site skip-links in the title line and "Kurzlink / Oben" footer; harmless. Remedy: none (UBA quotes stay out of git anyway).
6. Date traps for writers: Destatis 2024 (59,4 %) vs 2025 release restating 2024 as 59,5 %; EEA 49 % (2024 PDF) vs 47 % (2025 web); UBA 2024 "rund 54" vs "54,4". The task statement expected "59.5 % in destatis-strom-2025" as a headline value: it is the revised 2024 value; 58,6 % is the 2025 value.
7. ec-cloud-energy-2020 is short (2.3k chars) but complete; fine for one answerable case and the 2020 age-caveat case.
8. No source is thin or unusable; no source needs to be dropped. Nothing needs a new URL.

## 2026-10-14 — Group 2 outcome: EEA banner accepted as noise (Remedy B)
**Context**: Converted texts are all usable (12 real, 10 synthetic byte-identical). EEA pages start with about 90 lines of banner/navigation/language list; chart data absent everywhere; Wikipedia keeps edit markers and reference blocks.
**Decision**: No converter change. Writers must not quote or use absence terms from the EEA top block (first ~92 lines of eea-ghg-trends-2025, ~96 of eea-biodiversity-2025), chart captions, Wikipedia edit markers or reference lines; no chart-value questions. Both variants will see the same noisy text, so the comparison stays fair.
**Rationale**: A converter change means another review cycle for realism-neutral noise.

## 2026-10-14 — Group 3 done; Groups 3 and 4 share one review gate
**Context**: Three writers produced evals/parts/*.jsonl (19 + 16 + 13 = 48 cases) and evidence files; each passes scripts/verify_testset.py. Part files are intermediate: they become evals/testset.jsonl in Group 4.
**Decision**: One reviewer + security-reviewer pass covers the merged result (Groups 3 and 4 together) instead of reviewing intermediate part files. Blind-check inputs prepared by the orchestrator: `data/corpus/blind-questions.jsonl` (shuffled ids b-01..b-48, no category, no expected answers) and `data/corpus/blind-map.json` (gitignored; the blind agent must not read it).
**Open notes from writers**: una-07 uses "Spanien" but Spain appears (without figures) in an EEA member-state list; blind check decides if the case stays. num-01/num-04 cite two sources to mention an older/forecast value; mul-04 and mul-06 compare not-like-for-like figures (answers say so).

## 2026-10-14 — Group 4 merge
**Result**: evals/testset.jsonl (48 cases) and data/corpus/evidence.jsonl (48 entries, gitignored) merged from the part files (sorted by category, then id; case text unchanged). `load_testset` returns 48; `scripts/verify_testset.py ... --write-sheet evals/handcheck.md` exits 0; `pytest -q` 213 passed, 3 deselected.
**Counts (category: de/en)**: answerable 12 (6/6), unanswerable 7 (4/3), multi_step 8 (4/4), numbers 8 (4/4), contested 8 (4/4), injection 5 (2/3). Total de 24, en 24.
**NGO-specific** (cites a syn-* source): 9 (ans-10, num-08, con-04, con-05, inj-01..inj-05). The 7 unanswerable cases have no source_ids.
**Cross-language** (question language differs from a cited source's language; sources en: eea/owid/ec, de: destatis/dewiki/uba/syn): 15 (ans-02, ans-04, ans-05, ans-09, ans-10, mul-01, mul-03, mul-04, mul-07, mul-08, con-04, con-08, inj-01, inj-02, inj-04).
**Hand-check sheet**: 7 cases cite UBA and have quotes withheld (ans-07, mul-05, mul-07, mul-08, num-04, con-03, con-08; 18 withheld quote lines). Phrases "rund 54 Prozent"/"54,4 Prozent" occur only inside two expected-answer texts (not as quotes). The sheet has no header/note naming sources and licences (only per-case "Source ...: licence ..." lines): to be handled in task 5.2.

## 2026-10-14 — Group 4 blind check
**Context**: Task 4.2, comparer step. Blind answers (`data/corpus/blindcheck.jsonl`, mapped with `blind-map.json`) compared with `expected_answer` for all 48 cases; full table in `data/corpus/comparison.md` (gitignored). Nothing in the testset, evidence, scripts or tests was changed; resolutions below are PROPOSALS only. Texts were checked in `data/corpus/*.txt` (grep with `-a`: the 2024 EEA PDF text contains private-use bytes and plain `grep` treats it as binary).

**Counts**: 42 match, 5 partial, 1 disagree. Found/not-found agrees in all 48 (7 unanswerable all `found=false`, 41 others `found=true`).

| category | match | partial | disagree |
|---|---|---|---|
| answerable (12) | 12 | 0 | 0 |
| unanswerable (7) | 7 | 0 | 0 |
| multi_step (8) | 6 | 1 (mul-04) | 1 (mul-01) |
| numbers (8) | 7 | 1 (num-01) | 0 |
| contested (8) | 5 | 3 (con-01, con-06, con-07) | 0 |
| injection (5) | 5 | 0 | 0 |

### Partial / disagree cases
| case | verdict | what differs | who is right (corpus) | proposed resolution |
|---|---|---|---|---|
| mul-01 | disagree | Expected: 49% (2024) vs 47% (2025), "newer is lower". Blind: 43%/49% (2024) vs 47%/54% (2025); lower is the 2024 value in each scenario. | Blind. 2024 body: "would achieve a reduction of 43% in net emission levels by 2030"; "would reach 49% when planned additional measures are taken into account". Premise "projection was lowered" is false: both scenarios improved. | Rewrite question and expected answer (see EEA finding); the numbers-only comparison 49 vs 47 is not like-for-like. |
| con-01 | partial | 2025 part identical (47% / 54%). Expected gives 2024 as plain "49%"; blind gives 43% (existing) and 49% (additional). | Blind is more precise; expected is not false for the 2024 summary sentence ("Current GHG projections ... 49%") but the 49% is the with-additional-measures scenario in the body. | Fix expected answer: add 43% / 49% scenario labels for 2024; keep "2025 supersedes". |
| num-01 | partial | Core 47% matches (blind also gives 54%). Expected says the older edition "said 49%" for current policies. | Blind. The 2024 existing-measures figure is 43%; 49% was with additional measures. | Fix expected answer (2024: 43% existing measures, 49% only with additional measures); question can stay. |
| con-06 | partial | Same figure (over 35 billion tonnes) and page dates; blind does not say the "now" claim may be outdated. | Expected is right: OWID text "now emit over 35 billion tonnes each year" on a page first published June 2020. | No change; omission is the blind agent's, which was not asked about age. Keep as is. |
| con-07 | partial | Same "bis zu 50 % bis 2013 (Stand 2008)". Expected adds Borderstep 2012 (9,4 TWh, slowed trend); blind adds Borderstep 2018 study (13,2 TWh in 2017, +25 % since 2010). | Both in text (dewiki-green-it lines 85, 87). The 2018 study is the latest and shows growth again, so the expected "slowed trend" alone is incomplete but not wrong. | Fix expected answer: add the 2017 value (13,2 TWh, +25 % 2010-2017) after the 2012 one; evidence quote needed for it. |
| mul-04 | partial | Same result (higher: 16 bn kWh = 3% DE 2020 vs 2.7% EU 2018). Blind omits the caveat that years and scopes differ. | Expected is right and already states the caveat; text: "Bis 2020 stieg er auf 16 Milliarden, also drei Prozent des gesamten deutschen Stromverbrauchs". | No change (blind omission). |

### EEA 2030 projections (con-01, mul-01, num-01; also checked: no other case cites eea-ghg-trends-2024)
**What each edition says** (lines in converted text):
- 2024 (PDF, published 31 Oct 2024), summary: "Current GHG projections, as reported by Member States, suggest that a 49% reduction in net emissions will be reached by 2030 compared to 1990 levels, missing the 55% reduction target for 2030."
- 2024, body: "the policies and measures currently in place combined would achieve a reduction of 43% in net emission levels by 2030 compared to 1990." And: "The projected reduction would reach 49% when planned additional measures are taken into account, still leaving a six-percentage point gap". Methods section names both scenarios WEM and WAM. So the 2024 summary calls the WAM figure (49%) "current projections"; WEM is 43%.
- 2025 (web, published 06 Nov 2025), summary: "Projections based on current policies and measures ... suggest that a 47% reduction ... Integrating countries' additionally planned policies and measures ... a projected 54% reduction by 2030". Body: "policies and measures currently in place would achieve a reduction of 47%"; "would reach 54% when planned additional measures are taken into account, leaving a one-percentage point gap".
- Like-for-like: WEM 43% (2024) -> 47% (2025), +4 points; WAM 49% (2024) -> 54% (2025), +5 points. The pair "49% (2024) vs 47% (2025)" mixes WAM with WEM: not like-for-like. It wrongly suggests a downgrade. A reader comparing the two summary sentences literally gets 49 vs 47, but the 2025 summary label "current policies" corresponds to 2024 43%, not 49%.
- Also the editions use different submission rounds (2024: March 2023, updated by some in 2024; 2025: March 2025 submission).

**Careful expected answers (proposed)**
- num-01 (question unchanged, "under current policies"): "47% by 2030 compared with 1990 under current policies and measures (EEA indicator published 6 November 2025; 54% if additionally planned measures are included). The 2024 edition (31 Oct 2024) gave 43% for existing measures (49% only with additional measures), so the figure has risen." Evidence additions: 2024 quote "would achieve a reduction of 43% in net emission levels by 2030 compared to 1990"; existing 2025 quote stays; existing 2024 quote (49% summary) no longer supports "said 49% for current policies" and should be replaced or relabelled as "49% with additional measures (summary calls it current projections)".
- con-01 (question unchanged): "It depends on edition and scenario. Published 31 Oct 2024: 43% with existing measures, 49% with additional measures (its summary calls 49% the 'current' projection). Published 06 Nov 2025: 47% with existing, 54% with additionally planned measures; the 2025 figures supersede the 2024 ones, and both scenarios are higher than in 2024." Existing 2024 quote ("Current GHG projections ... 49%") is still valid as the summary sentence; add the 43% and "would reach 49% when planned additional measures" body quotes.
- mul-01 (rewrite). Proposed question (de): "Die EEA hat in den Ausgaben 2024 und 2025 jeweils Projektionen zur EU-Netto-Emissionsminderung bis 2030 veröffentlicht. Wie lauteten die Werte mit bestehenden und mit zusätzlich geplanten Maßnahmen in beiden Ausgaben, und wurden sie höher oder niedriger?" Expected: "Ausgabe 2024 (31. Oktober 2024): 43 % mit bestehenden, 49 % mit zusätzlichen Maßnahmen. Ausgabe 2025 (6. November 2025): 47 % bzw. 54 %. Die Werte sind also in beiden Szenarien höher geworden (+4 bzw. +5 Prozentpunkte); das 55-%-Ziel wird 2024 um 6, 2025 um 1 Prozentpunkt verfehlt." Evidence: four body quotes (43%, 49% additional, 47%, 54% additional) plus the two "Published" dates; keeps 2 claims from 2 sources. Alternative: keep the literal-summary comparison but require the answer to say the 49% is the with-additional-measures value; the rewrite is cleaner.
- Evidence still supports: all quotes currently in the three evidence records are verbatim and true; they back the 2025 figures fully, but not the label "current policies" for 2024's 49%.

### Writers' open notes
- una-07 (Spain): "Spain" occurs only once in the corpus, as a name in the EEA 2024 PDF member-state list (eea-ghg-trends-2024 line 482, "Slovenia Spain"), plus a language-menu entry "Español" in the two EEA pages. No figures. No data-centre or electricity data for Spain anywhere; blind agent found nothing. The case remains valid. The absence_terms (Spanien, Madrid, spanische) are German only, so the check does not cover the English word: do not add "Spain" to absence_terms (it has one hit in the member list); keep the case and mention the member-list hit in `notes`. Similar for una-04: "Türkçe/TR" language-menu entries exist but no "Turkey" hit; fine.
- num-01/num-04 (two sources cited for older value): num-04 is consistent (54,4 final, "rund 54" forecast named, blind agrees). num-01 is the problem (see EEA finding); the second source cited is only needed if the 2024 value is kept in the answer.
- mul-04 and mul-06 (not like-for-like): both expected answers say so (mul-04 "only indicative", mul-06 "measure different things"); blind agreement: mul-06 yes, mul-04 omitted the caveat only. No change.
- con-02/con-08 ("endgültige Werte"): supported. destatis-strom-2025 table header "2024 | 2025" with "(in Mrd. kWh)1 | Anteil (in %)1" for 2024 and footnote "1: endgültige Werte 2: vorläufige Werte", so 2024 (257,1 / 432,1 = 59,5 %) is labelled final; 2025 (58,6 %) is preliminary. The 2024 release says "nach vorläufigen Ergebnissen" (59,4 %; 256,4 / 431,5). The word "endgültig" appears only in the table footnote, not in the prose (prose says "(2024: 59,5 %)"); the judgement is correct but rests on that footnote. Blind agent reached the same conclusion. No change; optional: cite the footnote in `notes`.
- Other checked details: num-06 (PV 59,5 in 2024 release, 59,7 in 2026 table) and mul-02 verified in the Destatis tables.

## 2026-10-14 — Blind check resolutions (orchestrator decision)
**Result**: 42 match, 5 partial, 1 disagree; found/not-found agrees in 48/48. Real defect: the pair "EEA 2024: 49% vs 2025: 47%" compared unlike scenarios (2024: 43% existing / 49% additional; 2025: 47% / 54%).
**Decision**: rewrite mul-01 (question + answer, both scenarios, both editions, both rose); fix expected answers of con-01 and num-01 to label the scenario; add the 2017 value (13,2 TWh) to con-07 with an evidence quote; no change to con-06 and mul-04 (caveats omitted by the blind agent only); keep una-07 and una-04 and add a note that "Spain" / "Türkçe" occur only in a member list / language menu; add the "endgültige Werte" footnote to con-02/con-08 notes. Delete evals/parts/ (superseded by evals/testset.jsonl). One fresh blind agent re-answers the rewritten mul-01 question (and nothing else).
**Rationale**: Contested pairs must be like-for-like or say they are not; the blind check is what caught it.

## 2026-10-14 — Re-blind check of rewritten mul-01: match
A fresh blind agent answered the rewritten mul-01 question from the corpus only: 2024 edition 43% (existing) / 49% (additional), 2025 edition 47% / 54%, both higher (+4/+5 points), same figures as the expected answer. Confidence high. The EEA like-for-like defect is resolved.

## 2026-10-14 — Review cycle 2 fixes and corrections to earlier counts
**Corrections**: cross-language count is 14 (recomputed from the tenant `language` field exactly as tests/test_testset.py does: ans-02, ans-04, ans-05, ans-09, ans-10, mul-01, mul-03, mul-04, mul-07, mul-08, num-08, con-04, con-08, inj-05), not 15; the sheet has 22 withheld-quote lines (not 18) after con-08/mul-08 changed; the sheet now has a generated sources-and-licences header (it had none when "Group 4 merge" was written).
**Added after review cycle 1**: con-08 (and mul-08) now state the 59,4 % preliminary to 59,5 % final restatement and cite destatis-strom-2025; `evals/evidence.jsonl` (committed) holds verbatim quotes for redistributable sources and offsets + sha256 (+ numbers) for the 12 UBA claims, so `verify_testset.py` runs from a clean checkout after fetch + build; `--export-public-evidence` regenerates it from the local full evidence.
**Open suggestion**: offsets of quoted claims are not re-checked by the verifier (hash covers the quote only); acceptable, informational.

## 2026-10-14 — Test-set spec complete
Review cycle 3 PASS, security review PASS (0 Critical, 0 Warning). Deferred suggestions (to the assistant spec or later): whitelist keys in `--export-public-evidence` so a future free-text field cannot leak a non-redistributable quote; guard `--write-sheet`/`--export-public-evidence` against overwriting an input file; re-check offsets of quoted claims; do not commit `resumeId.txt`. Shortened a 12-word UBA phrase in this file to figures plus paraphrase.
