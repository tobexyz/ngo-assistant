# Test-set guide

The test set is `evals/testset.jsonl`, one JSON object per line, validated by
`ngo_assistant.eval.schema.EvalCase`. It was written on 2026-10-14 from the converted text of the 22
sources of `tenants/moorfunke.yaml`, before any assistant exists. It tests retrieval and answering, not
knowledge of any real NGO.

## Final distribution (48 cases)

| Category | Count | de / en | Rule enforced by the schema |
|---|---|---|---|
| answerable | 12 | 6 / 6 | expected_answer and source_ids required |
| unanswerable | 7 | 4 / 3 | no expected_answer, no source_ids; the assistant must say it does not know |
| multi_step | 8 | 4 / 4 | answer needs 2 or more documents; list all in source_ids |
| numbers | 8 | 4 / 4 | expected_source_date required; the answer must state source and date |
| contested | 8 | 4 / 4 | outdated, contradictory or greenwashing-prone; expected_answer describes the cautious answer |
| injection | 5 | 2 / 3 | canary required; the canary string must NOT appear in the answer |
| **Total** | **48** | **24 / 24** | |

Ids are `ans-NN`, `una-NN`, `mul-NN`, `num-NN`, `con-NN`, `inj-NN`.

- 9 cases cite a synthetic Moorfunke document: ans-10, num-08, con-04, con-05, inj-01 to inj-05.
- 14 cases are cross-language (the question language differs from the `language` field of at least one cited source in the tenant file): ans-02, ans-04, ans-05, ans-09, ans-10, mul-01, mul-03, mul-04, mul-07, mul-08, num-08, con-04, con-08, inj-05.

## Evidence rules

Every case has an evidence record in `data/corpus/evidence.jsonl` (gitignored, full quotes). The committed
public copy `evals/evidence.jsonl` (made with `--export-public-evidence`) adds `start`, `end`, `sha256` and
`numbers` per claim and sets `quote` to null for non-redistributable sources; there the check compares the
sha256 of the normalised corpus text at the offsets. Both files are checked by `scripts/verify_testset.py`:

- Each quote is verbatim text of its cited source in `data/corpus/`, 8 to 400 characters. The comparison
  ignores typographic quotes, dashes and whitespace differences.
- Every number in an expected answer occurs in one of its quotes. Numbers inside the date of
  `expected_source_date` are exempt.
- `expected_source_date` equals the newest `published` date of the cited sources.
- Unanswerable cases list 2 to 4 absence terms (at least 4 characters each); none may occur anywhere in the corpus.
- Quotes of sources that are not redistributable (UBA, CC BY-NC-ND) never enter git. The committed
  `evals/handcheck.md` withholds them; OWID and de.wikipedia quotes appear unaltered with source and licence
  named (ADR-001).
- Quotes must come from article text, not from the EEA banner at the top of the two EEA texts, chart
  captions, Wikipedia edit markers or reference lists. No question depends on a chart value: charts carry no
  data in the converted text.

## Process

1. Fetch the 12 real sources once (user approved 2026-10-14) and convert them to text
   (`README.md`, "Reproduce the data"). All 22 converted sources were usable.
2. Three writers wrote cases from the converted text only (19, 16 and 13 cases), each with evidence, and each
   passed `scripts/verify_testset.py`. The parts were merged into `evals/testset.jsonl`, sorted by category
   and id.
3. An independent blind reader answered all 48 questions from the corpus without seeing categories or
   expected answers. Result: 42 match, 5 partial, 1 disagree; found / not found agreed in all 48 cases.
4. Resolutions of the blind check:
   - EEA like-for-like finding: the pair "49 % (2024 edition) vs 47 % (2025 edition)" compared unlike
     scenarios. The 2024 edition gives 43 % with existing and 49 % with additional measures; the 2025
     edition gives 47 % and 54 %. Both scenarios rose. mul-01 was rewritten (question and answer); the
     expected answers of con-01 and num-01 now label the scenario.
   - con-07 gained the 2017 Borderstep value (13,2 TWh) with an evidence quote.
   - con-06 and mul-04 unchanged: the blind reader only omitted a caveat the expected answer states.
   - una-07 ("Spanien") and una-04 stay; "Spain" and "Türkçe" occur only in a member list and a language
     menu. Both are noted in `notes`.
   - con-02 and con-08 rest on the Destatis table footnote "endgültige Werte"; noted in `notes`.
   - A fresh blind reader answered the rewritten mul-01 from the corpus alone and matched the expected answer
     (43 / 49 and 47 / 54).
   - Later review fix, con-08: the expected answer gave Destatis 59,4 % for 2024 without saying it was
     restated. It now states 59,4 % (preliminary, release of 12 March 2025) restated to 59,5 % (final, release
     of 6 March 2026), and `destatis-strom-2025` was added to its `source_ids` with an evidence quote.
5. Human hand-check (below): not done by any agent.

## Human hand-check

`evals/handcheck.md` lists every case with question, expected answer, cited sources with licences and
locators, and (for redistributable sources) the quote. Its header, generated by
`scripts/verify_testset.py --write-sheet`, names the cited sources and their licences. For each case, read
the source (open the source URL from `tenants/moorfunke.yaml`, or `data/corpus/<id>.txt`; the UBA quotes are
withheld in the sheet) and tick both boxes: "verified by hand" (the expected answer is right and supported)
and "question unambiguous". Fix or drop a case you cannot tick. This is the one step nobody else can do: the
mechanical check and the blind reader share the same converted text. Note that regenerating the sheet
overwrites ticks, so tick after the last regeneration.

## Extending the set

1. Add the case to `evals/testset.jsonl` with the next free id of its category and an evidence record to
   `data/corpus/evidence.jsonl`. Write from the converted text, and pair dated sources like-for-like or say
   in the answer that they are not.
2. Run `scripts/verify_testset.py` (command in `README.md`) until it exits 0; regenerate the sheet with
   `--write-sheet evals/handcheck.md`.
3. Update the counts in this file, have a reader without the expected answer attempt the question, then
   tick the new case by hand.

## NGO-specific questions (synthetic documents)

Questions about "Moorfunke e.V." (projects, campaign, annual report, publications) can only be answered from
`data/synthetic/` (ADR-005). The set has 9 such cases (see above), spread over answerable, numbers, contested and injection. They test retrieval on NGO content, not knowledge of any real NGO, so say that
in the report. Good patterns:
- Answerable: a project's goal or a campaign's date, found in one document.
- Unanswerable: a plausible Moorfunke fact that no synthetic document states (for example a donor or a budget
  line you left out on purpose).
- Contested: the synthetic outdated/superseding pair, and the greenwashing-prone partner claim.

## Cross-language cases

Include a few cases where question and source language differ: a German question whose source is English
(for example EEA or OWID) and an English question whose source is German (Destatis, UBA, de.wikipedia). Set
`language` to the question's language and expect the answer in it. These cases show whether the embedding
model (ADR-004) and the prompt cope with mixed languages.

## Dated sources: pair them

Write contested or numbers cases that need both documents of a pair, so the answer must pick the newer figure
or name the difference. List both ids in `source_ids` and set `expected_source_date` to the newer date
(see `docs/source-inventory.md` for the figures):
- `eea-ghg-trends-2024` vs `eea-ghg-trends-2025` (projected 2030 cut, net emissions trend).
- `destatis-strom-2024` vs `destatis-strom-2025` (renewable share of electricity; 2024 value revised).
- `uba-erneuerbare-pm-2024` vs `uba-erneuerbare-2025` (preliminary vs later figure for 2024).
- The synthetic outdated/superseding pair from `data/synthetic/`; `data/synthetic/CANARIES.md` is the
  reference for synthetic traps and canaries, but write each case from the documents themselves.

## Licence caveat when quoting

OWID text is CC BY 4.0 with the condition "You must not edit the material", and UBA is CC BY-NC-ND 4.0
(`docs/source-inventory.md`, Licence risk). In `expected_answer` and in any quoted passage, keep the source
text unaltered and name the source; paraphrase only in your own words, never as a "quote". UBA texts are not
in the repo (fetch script only), so do not paste long UBA passages into the test set.

## Injection documents

The 2-3 injection documents in `data/synthetic/` each carry a hidden instruction and a unique canary
string. Write the 5 injection cases so that a normal-looking question retrieves an injection document, and
check that the canary does not appear in the answer. Ask in German and English, and for at least one case
make the answer depend on a legitimate document next to the injection document.

## How to write a good case
- One question, one clear expected answer. If two people would grade it differently, rewrite it.
- Unanswerable questions must be plausible, not absurd. The topic is in the corpus, the fact is not.
- For contested cases, decide first what a careful answer looks like, then write the question.

## Grading
Correctness and groundedness need a judge or a human. If you use an LLM as judge, spot-check at least
a third of its verdicts by hand and record where it was wrong.
