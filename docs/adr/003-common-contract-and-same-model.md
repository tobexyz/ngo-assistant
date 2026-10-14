# ADR-003: One Answerer contract, same model and prompt for both variants

- Status: Proposed (edit and accept it yourself)
- Date: 2026-10-14

## Context
We compare agentic retrieval (A) and vector retrieval (B). With a small local model, tool calling may be
unreliable. If A loses, we must be able to tell whether the approach or the model is the cause.
The comparison is only valid if the variants differ in one thing: how context is found.

## Decision
Both variants implement `Answerer`: question and language in, `Answer` out (text, citations, abstained,
token usage, tool calls, tool-call failures). Both use the same model and the same system prompt.
Latency is measured by the runner, not by the variants. Tool-call failures are a separate metric.

## Alternatives considered
- A `Retriever` interface (query in, chunks out): rejected. In variant A the model retrieves by itself,
  so there is no separable retriever.
- A separate harness per variant: rejected. Numbers would not be comparable.
- Different models per variant, each at its best: rejected for the first comparison. It mixes two effects.

## Consequences
- Easier: one runner, one metrics module, one report.
- Harder: token accounting must cover every model call in the agentic loop, and the embedding work in B.
- Risk: a small model may fail tool calling so often that A is unusable. Then the result is "A does not
  work with this model", which is a valid and honest finding.

## Open questions for you
1. Which model and which embedding model? Check current Ollama models with tool-calling support against the
   Ollama library first, then record the choice and the source. (Hardware is still unknown.)
2. Does a fair comparison also need the same retrieval budget (maximum tokens of context) for A and B?

## Two-minute explanation
(Write it after the first measurement.)
