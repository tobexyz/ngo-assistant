# ADR-002: White label through tenant config files, not multi-tenancy

- Status: Proposed (edit and accept it yourself)
- Date: 2026-10-14

## Context
The product should work for any environmental NGO. The infrastructure does not depend on the NGO's data,
but the evaluation does. We have about 22-27 hours in total, so a multi-tenant runtime (auth, per-tenant
databases, admin UI) is out of reach and would not improve the measured comparison.

## Decision
One tenant is one YAML file in `tenants/`: slug, name, languages, system prompt, sources with licence data.
The code loads one tenant per run. A second NGO means a new file. The reusable eval harness is part of
the product: a new tenant brings a test set and gets a score.

## Alternatives considered
- Database-backed tenants with an admin UI: rejected for now. Large effort, no effect on the comparison.
- Forking the code per NGO: rejected. It breaks reuse and the comparison.

## Consequences
- Easier: adding a tenant is a review of one file. Licence rules are enforced at load time.
- Harder: no tenant isolation at runtime. Do not claim multi-tenancy in the write-up.
- Risk: config grows into a second programming language. Keep logic in code.

## Open questions for you
1. Where is the line between config and code? Is the system prompt config, or code that happens to be text?
2. What would you add first if a real second NGO appeared?

## Two-minute explanation
(Write it after week 4.)
