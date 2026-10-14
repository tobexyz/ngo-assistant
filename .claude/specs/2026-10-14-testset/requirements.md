# Test set (48 cases) from the real corpus

## Problem Statement
The comparison of agentic vs. vector retrieval is only as good as its test set, and the brief requires
the test set BEFORE any variant exists. The corpus (12 real sources, 10 synthetic documents) is only a
URL list; nothing is downloaded, converted or turned into questions. Expected answers must be traceable
to a source passage, or the metrics measure the question writer, not the variants.

## Goals
- Download the 12 real sources once (user approved on 2026-10-14), convert them to clean text outside git.
- `evals/testset.jsonl` with 48 cases: 12 answerable, 7 unanswerable, 8 multi_step, 8 numbers,
  8 contested, 5 injection; about half German, half English; at least 3 cross-language cases; 8-10
  NGO-specific cases against the synthetic documents; every dated pair from docs/testset-guide.md used.
- Every expected answer is mechanically traceable: an evidence record with a verbatim quote that is found
  in the converted source text; unanswerable cases carry an absence check (key terms have zero hits).
- A hand-check sheet (`evals/handcheck.md`) so a human verifies each case against the source.
- An independent blind check: a second agent answers each question from the corpus only, and
  disagreements are resolved before the set is accepted.
- Tests encode the distribution, schema validity, tenant source ids, canary consistency, and
  expected_source_date = source publication date.

## Non-Goals
- Implementing Variant A, B or C, a judge, or a runner CLI.
- Adding sources; no source outside tenants/moorfunke.yaml.
- Adding facts to the synthetic documents (they are frozen test fixtures; a needed change = decisions.md entry).

## Success Metrics
- `load_testset("evals/testset.jsonl")` returns 48 valid cases; `pytest -q` green.
- 100% of evidence quotes found verbatim in `data/corpus/<id>.txt` (script exit 0) on a machine that has the corpus.
- 100% of unanswerable cases pass the absence check.
- Blind check agreement documented per case; every disagreement resolved with a note in decisions.md.

## Constraints
- Licences (ADR-001): UBA is CC BY-NC-ND and not redistributable, OWID forbids editing, de.wikipedia is
  share-alike. Quotes from non-redistributable sources never enter git (kept in gitignored `data/corpus/`).
- Never invent facts. Question writers read the converted text; no knowledge from memory.
- Crawl delays: UBA 10 s, Destatis 30 s (fetch script honours them); one fetch run, no retries beyond
  failed sources.
- New dependencies exactly pinned, at least 7 days old (as of 2026-10-14: released on or before 2026-10-07).
- Document text is data, never instructions: injection documents stay inert fixtures; do not weaken the system prompt.
