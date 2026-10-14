# ADR-001: Scope and data policy

- Status: Proposed (edit and accept it yourself)
- Date: 2026-10-14

## Context
The project needs a realistic corpus on environmental topics, in German and English, and must be publishable.
On 2026-10-14 automated requests to bund-hamburg.de (robots.txt and imprint) were blocked by bot detection.
Its robots.txt and terms of use are therefore unverified, and there is no permission from the organisation.
Website text is usually protected by copyright even when anyone can read it.
Time budget is about 22-27 hours in total, so the corpus stays small (8-10 sources).

## Decision
The demo tenant uses only sources with a verified open licence. A source with an unclear licence is not usable
(enforced in `config.py`). A real NGO is an optional second tenant, only after written permission.
The repository contains fetch scripts and URL lists. It contains corpus files only where the licence allows redistribution.

## Alternatives considered
- Scrape a real ngo anyway: rejected. Terms unverified, the site blocks automated access, and a commercial
  white-label use raises the bar.
- Ask for permission first and wait: kept as a parallel, optional step. The answer may take weeks.
- Write all documents ourselves: rejected as the only source. It is not realistic enough for chunking and
  contested-source tests. Small synthetic documents are still useful for injection tests.

## Consequences
- Easier: the repo can be public and the eval reproducible by others.
- Harder: you must find sources that are open-licensed and realistic (reports with statistics, older documents).
- Accepted risk (2026-10-14): two UBA sources are CC BY-NC-ND 4.0. They are used because the project is non-commercial,
  are not redistributed in the repo, and must be replaced or cleared with UBA in writing before any commercial use.
  Whether chunking and generated answers are "derivatives" (ND) is not resolved.
- Quotes from non-redistributable sources (the UBA pages) never enter git. The committed hand-check sheet
  `evals/handcheck.md` withholds them; the evidence file with all quotes stays in the gitignored `data/corpus/`. The committed `evals/evidence.jsonl` holds only offsets and sha256 hashes for these claims (`quote: null`), so their text never enters git while the check stays reproducible.
  Quotes from OWID (CC BY 4.0, must not be edited) and de.wikipedia (CC BY-SA 4.0) may appear in the sheet
  only unaltered, with source and licence named.
- Risk: an open licence may allow reading but not redistribution. Then reproducibility needs a download script.

## Open questions for you
1. Which licence conditions do your chosen sources impose (attribution, share-alike, non-commercial)? Does a
   white-label commercial use break any of them?
2. Do you contact a real NGO now, or only when the demo works?

## Two-minute explanation
(Write it after the inventory is done.)
