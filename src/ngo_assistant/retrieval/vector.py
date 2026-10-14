"""Variant B: vector retrieval. Embed the question, take the top-k chunks, ask the model once."""

from __future__ import annotations

import math
import os
from typing import Any

from ngo_assistant.config import Tenant
from ngo_assistant.llm import add_usage
from ngo_assistant.models import Answer
from ngo_assistant.prompt import ANSWER_SCHEMA, SourceItem, build_messages, format_sources, parse_answer

DEFAULT_TOP_K = 4


def estimate_tokens(text: str) -> int:
    """Rough token estimate shared with the budget check: ceil(len / 4)."""
    return math.ceil(len(text) / 4)


def _top_k_from_env() -> int:
    raw = os.environ.get("NGO_TOP_K")
    if raw is None:
        return DEFAULT_TOP_K
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value < 1:
        raise ValueError(f"NGO_TOP_K must be a positive integer, got {raw!r}")
    return value


class VectorAnswerer:
    name = "vector"

    def __init__(self, tenant: Tenant, store: Any, llm: Any, top_k: int | None = None,
                 max_context_tokens: int = 3000) -> None:
        if top_k is None:
            top_k = _top_k_from_env()
        self.tenant = tenant
        self.store = store
        self.llm = llm
        self.top_k = top_k
        self.max_context_tokens = max_context_tokens

    def answer(self, question: str, language: str) -> Answer:
        embedded = self.llm.embed([question])
        chunks = self.store.search_chunks(embedded.vectors[0], self.top_k)

        items: list[SourceItem] = []
        used = 0
        for chunk in chunks:  # ranked order; stop at the first chunk that would exceed the budget
            cost = estimate_tokens(chunk.text)
            if used + cost > self.max_context_tokens:
                break
            used += cost
            items.append(SourceItem(chunk.source_id, chunk.title, chunk.published, chunk.text))

        messages = build_messages(self.tenant, question, language, format_sources(items))
        result = self.llm.chat(messages, tools=None, format=ANSWER_SCHEMA)
        parsed = parse_answer(result.text, self.tenant.source_ids())

        trace: list[dict] = []
        if parsed.parse_error is not None:
            trace.append({"event": "format_error", "detail": parsed.parse_error})
        return Answer(
            text=parsed.text,
            citations=parsed.citations,
            abstained=parsed.abstained,
            usage=add_usage(embedded.usage, result.usage),
            tool_trace=trace,
            invalid_citations=parsed.invalid_citations,
            repaired_citations=parsed.repaired_citations,
        )
