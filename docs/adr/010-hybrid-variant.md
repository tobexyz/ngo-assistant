# ADR-010: Variant C "hybrid": the agent loop with vector search

- Status: Proposed (edit and accept it yourself)
- Date: 2026-10-16

## Context
The project compares variant A (agentic retrieval with keyword tools) and variant B (plain vector retrieval).
One earlier chat transcript on the live stack (single observation, 2026-10-15, not a measurement) suggested a
weakness of A: its `search_sources` returns snippets of at most 300 characters, and the 1B chat model often did
not follow up with `read_source`, so it answered from fragments. Variant C is an optional third variant that
tests whether an LLM-driven loop helps when its search is semantic and returns whole chunks. It does not
replace A or B.

## Decision
- `HybridAnswerer` (`name = "hybrid"`, `retrieval/hybrid.py`) runs the same tool loop as A. Both classes share
  `ToolLoopAnswerer` (`retrieval/agentic.py`): tool-enabled calls without `format`, at most 6 tool calls, repeat
  detection, argument normalisation and validation, failure and repair counting, and one forced final call
  without tools and with the answer schema.
- Tools: `vector_search(query)` and `read_source(source_id, part)` (`HYBRID_TOOLS` in `retrieval/tools.py`).
  `list_sources` and `search_sources` are not offered.
- `vector_search` embeds the query and returns the top-k chunks. top-k comes from configuration, like B
  (constructor argument, then `NGO_TOP_K`, then 4). The model cannot set it.
- All tool results together are capped at a cumulative 3000 estimated tokens (`ceil(characters / 4)`), the same
  budget and estimate as B. When it is used up, the loop ends with the final call.
- Embedding usage inside tool calls is counted: `Answer.usage` sums every chat call and every embed call.
- Same chat model and same system prompt as A and B. Only the sentence appended to the user message differs
  (`HYBRID_TOOL_HINT`), because it names the tools.

## Alternatives considered
- Add `vector_search` to A's tool set: rejected. A would then no longer be the keyword-tool agent and the A
  versus B comparison would blur.
- A router in front (decide per question whether to use the loop or plain retrieval): rejected. It adds a model
  decision that changes which questions reach which path and would contaminate the abstention metrics.
- Always retrieve chunks before the loop and then let the model call tools: that is B plus tools; B already is
  "always retrieve chunks", so C would not isolate what the loop adds.
- Let the model choose top-k: rejected. A 1B model setting a numeric parameter is another failure source, and
  top-k is a configuration value for B.

## Consequences
- What C measures: does an LLM loop add value over plain vector retrieval when both use the same retrieval
  backend? C against B shows the loop's effect; C against A shows the effect of semantic chunks over keyword
  snippets.
- Cost: at least two model calls per question (one tool-enabled call, one final call) plus one embed call per
  `vector_search`; more calls mean more latency than B on CPU.
- The tool-use weakness of the 1B model still applies: invalid arguments, repeated calls or no tool call at all
  are possible and are counted as in A (`tool_call_failures`, `tool_call_repairs`).
- Because the budget is shared with B's size, C sees at most as much text as B in total; A has no such budget.
- Measured results are in the eval output (`results/<run>/hybrid`) and in `decisions.md`, not here.
- Risk: if the model never calls `vector_search`, C answers from no context and likely abstains or answers from
  its own knowledge; the comparison then measures tool-use failure rather than retrieval quality. Read C's
  `tool_calls` and `tool_call_failures` together with its correctness numbers.

## Open questions for you
1. Is a cumulative 3000-token budget the right limit, or should C get the same per-answer context as A's loop
   without a cap?
2. Should the router and a CLI input guard (not part of this change) be reconsidered once C has results?
3. Is a hybrid worth keeping if C does not beat B on the full test set?

## Two-minute explanation
(Write it after the first measurement.)
