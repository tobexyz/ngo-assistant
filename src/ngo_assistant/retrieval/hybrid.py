"""Variant C: hybrid. The A tool loop with `vector_search` (semantic) and `read_source`.

Same loop rules as variant A (shared `ToolLoopAnswerer`). Differences: the tool set (`HYBRID_TOOLS`), the hint,
the executor (embedding + chunk search; its embed usage is added to the answer's usage) and a cumulative
context budget over all tool results (contracts.md "Addendum: Variant C").
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ngo_assistant.config import Tenant
from ngo_assistant.llm import LLMClient, add_usage
from ngo_assistant.retrieval.agentic import LoopState, ToolLoopAnswerer
from ngo_assistant.retrieval.tools import HYBRID_TOOLS, execute_tool
from ngo_assistant.retrieval.vector import _top_k_from_env, estimate_tokens

if TYPE_CHECKING:
    from ngo_assistant.db import Store

HYBRID_TOOL_HINT = (
    "Use vector_search to find relevant passages for this question; use read_source only if you need more of "
    "one document; after you have found what you need, answer."
)
BUDGET_MESSAGE = "context budget reached"


class HybridAnswerer(ToolLoopAnswerer):
    name = "hybrid"
    tools = HYBRID_TOOLS
    hint = HYBRID_TOOL_HINT

    def __init__(
        self,
        tenant: Tenant,
        store: Store,
        llm: LLMClient,
        top_k: int | None = None,
        max_tool_calls: int = 6,
        max_context_tokens: int = 3000,
    ) -> None:
        super().__init__(tenant, store, llm, max_tool_calls)
        self.top_k = _top_k_from_env() if top_k is None else top_k
        self.max_context_tokens = max_context_tokens

    def _exhausted(self, state: LoopState) -> bool:
        return state.used_tokens >= self.max_context_tokens

    def _execute(self, name: str, arguments: dict[str, Any], state: LoopState) -> dict[str, Any]:
        remaining = self.max_context_tokens - state.used_tokens
        if name == "vector_search":
            embedded = self.llm.embed([arguments["query"]])
            state.usage = add_usage(state.usage, embedded.usage)
            chunks = self.store.search_chunks(embedded.vectors[0], self.top_k)
            results: list[dict[str, Any]] = []
            for chunk in chunks:  # rank order; drop from the end at the first chunk that does not fit
                cost = estimate_tokens(chunk.text)
                if cost > remaining:
                    break
                remaining -= cost
                state.used_tokens += cost
                results.append(
                    {
                        "source_id": chunk.source_id,
                        "title": chunk.title,
                        "heading": chunk.heading,
                        "published": chunk.published.isoformat() if chunk.published is not None else None,
                        "text": chunk.text,
                    }
                )
            if not results:
                return {"results": [], "message": BUDGET_MESSAGE}
            return {"results": results}

        result = execute_tool(self.store, name, arguments)
        text = result.get("text")
        if isinstance(text, str):
            if estimate_tokens(text) > remaining:
                text = text[: 4 * remaining]
                result = {**result, "text": text, "truncated": True}
            state.used_tokens += estimate_tokens(text)
        return result
