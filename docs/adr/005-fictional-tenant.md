# ADR-005: Fictional tenant "Moorfunke e.V." with synthetic documents

- Status: Proposed (edit and accept it yourself)
- Date: 2026-10-14

## Context
The assistant needs an NGO identity and NGO-specific documents (projects, campaigns, publications). CLAUDE.md
forbids inventing facts about a real NGO, and ADR-001 allows no source with an unclear licence. A real NGO's
website is not usable without permission (ADR-001), and the repository should be publishable.

## Decision
- The tenant is a fantasy NGO, **Moorfunke e.V.** (slug `moorfunke`, `tenants/moorfunke.yaml`). "Moor" is
  German for peatland, "Funke" for spark. `tenants/demo.yaml` stays as the generic, empty white-label example
  (ADR-002: a second NGO is a new file).
- Name check (see `docs/source-inventory.md`, 2026-10-14): three web searches found no organisation called
  Moorfunke. The first candidate, "Kranichgrund e.V.", was dropped because results were dominated by real
  crane-protection groups. The Vereinsregister was **not** checked; a web search cannot prove that no small
  local association uses the name.
- All NGO-specific content is synthetic and lives in `data/synthetic/`: our own text, marked fictional in a
  header line, kind `synthetic` in the tenant file, redistributable.
- The synthetic set contains deliberate traps: an outdated figure that a later document supersedes, a
  greenwashing-prone partner claim, and injection documents with unique canary strings
  (`data/synthetic/CANARIES.md` lists them for the test set). Document text stays data, never instructions.
- The 12 real sources (EEA, OWID, EC, Destatis, UBA, de.wikipedia) provide topic knowledge; they say nothing
  about Moorfunke.

## Alternatives considered
- A real NGO: rejected for now; no permission (ADR-001), and facts would be invented or scraped.
- A generic "demo NGO" with no documents: rejected; NGO-specific questions and injection tests need content.
- A real NGO's name with invented facts: rejected; violates the "never invent facts" rule.

## Consequences
- Easier: the repo and eval can be public; traps and canaries are known by construction.
- Harder: NGO-specific questions test only synthetic content. A good score says nothing about real NGO
  documents, which are likely messier (PDFs, newsletters, tables).
- Harder: if the real-source licence set changes (ADR-001, UBA), the tenant file changes, not the code.
- Risk: the name could still collide with a real association not found by web search. Check the Vereinsregister
  before any public release.

## Open questions for you
1. Do you check the name in the Vereinsregister yourself before publishing?
2. Should the synthetic documents carry the CC BY 4.0 licence stated in the design, or stay unlicensed text?

## Two-minute explanation
(Write it after the synthetic documents exist.)
