"""Shared data shapes. Both retrieval variants return the same Answer."""

from __future__ import annotations

from pydantic import BaseModel


class Citation(BaseModel):
    source_id: str  # must match a Source.id of the tenant
    quote: str | None = None  # short supporting passage
    location: str | None = None  # page, section or anchor


class Usage(BaseModel):
    """Token counts summed over ALL model calls for one answer.

    For the agentic variant this includes every tool-call round trip,
    not only the final message.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    # embed_tokens: reported by the server, 0 when omitted (no estimate inside embed())
    embed_tokens: int = 0
    model_calls: int = 0  # chat + embed requests sent to the model server


class Answer(BaseModel):
    text: str
    citations: list[Citation] = []
    abstained: bool = False  # the assistant said it does not know
    usage: Usage = Usage()
    latency_s: float = 0.0  # set by the runner, not by the variant
    tool_calls: int = 0
    tool_call_failures: int = 0  # malformed call, loop, or no call when one was needed
    error: str | None = None  # set by the runner if the variant raised
    tool_trace: list[dict] = []  # agentic variant: one entry per tool call; empty for vector
    # cited ids dropped: not a known source id (checked against ALL tenant source ids, not the retrieved set)
    invalid_citations: int = 0
    tool_call_repairs: int = 0  # tool calls made valid by normalize_tool_arguments (number of repairs)
    repaired_citations: int = 0  # malformed citation strings mapped to exactly one known source id
