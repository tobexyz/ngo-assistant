"""Variant A: agentic retrieval. The model searches and reads sources with tools, then answers.

The loop itself lives in `ToolLoopAnswerer` and is shared with variant C (retrieval/hybrid.py), which only
swaps the tool set, the hint, the executor and adds a context budget.

Loop rules (contracts.md): tool-enabled chat calls without `format`; the loop ends when the model replies
without a tool call, the cap is reached or an identical call is requested twice; then ONE final call without
tools and with `format=ANSWER_SCHEMA` (tool messages stay in the context as text).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ngo_assistant.config import Tenant
from ngo_assistant.llm import ChatResult, LLMClient, add_usage
from ngo_assistant.models import Answer, Usage
from ngo_assistant.prompt import ANSWER_SCHEMA, build_system_prompt, parse_answer
from ngo_assistant.retrieval.tools import (
    TOOLS,
    UNKNOWN_SOURCE_ERROR,
    execute_tool,
    format_tool_result,
    normalize_tool_arguments,
    validate_tool_call,
)

if TYPE_CHECKING:
    from ngo_assistant.db import Store

# The only difference between the two variants' prompts (appended to the user message).
TOOL_HINT = (
    "You may call the tools to find sources for this question; after you have found what you need, answer."
)
TRACE_STRING_CHARS = 200
TRACE_NAME_CHARS = 100


def _truncate(value: Any) -> Any:
    if isinstance(value, str):
        return value[:TRACE_STRING_CHARS]
    if isinstance(value, dict):
        return {str(k)[:TRACE_STRING_CHARS]: _truncate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_truncate(v) for v in value]
    return value


def _key(name: str, arguments: dict[str, Any]) -> str:
    return json.dumps([name, arguments], sort_keys=True, default=str)


@dataclass
class LoopState:
    """Per-answer mutable state handed to the hooks of a ToolLoopAnswerer."""

    usage: Usage = field(default_factory=Usage)
    seen: set[str] = field(default_factory=set)
    used_tokens: int = 0  # cumulative estimate of tool-result sizes (only used by budgeted variants)


class ToolLoopAnswerer:
    """Shared tool loop. Subclasses set `name`, `tools`, `hint` and override `_execute` (and `_exhausted`)."""

    name = ""
    tools: list[dict[str, Any]] = TOOLS
    hint = TOOL_HINT

    def __init__(self, tenant: Tenant, store: Store, llm: LLMClient, max_tool_calls: int = 6) -> None:
        self.tenant = tenant
        self.store = store
        self.llm = llm
        self.max_tool_calls = max_tool_calls

    # -- hooks
    def _execute(self, name: str, arguments: dict[str, Any], state: LoopState) -> dict[str, Any]:
        """Run a validated call; may raise (counted as a failure, class name only). May add to state.usage."""
        return execute_tool(self.store, name, arguments)

    def _exhausted(self, state: LoopState) -> bool:
        """True when no further tool call may run (context budget); the loop then ends with the final call."""
        return False

    # -- loop
    def answer(self, question: str, language: str) -> Answer:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_prompt(self.tenant)},
            {"role": "user", "content": f"Question (language: {language}): {question}\n\n{self.hint}"},
        ]
        state = LoopState()
        trace: list[dict[str, Any]] = []
        requested = failures = repairs_total = 0

        stop = False
        while requested < self.max_tool_calls and not stop:
            if self._exhausted(state):
                trace.append({"event": "budget_exhausted"})
                break
            result: ChatResult = self.llm.chat(messages, tools=self.tools)
            state.usage = add_usage(state.usage, result.usage)
            if not result.tool_calls:
                if not result.text.strip():
                    failures += 1  # no content and no tool call
                break
            budget = self.max_tool_calls - requested
            calls = result.tool_calls[:budget]
            messages.append(
                {
                    "role": "assistant",
                    "content": result.text,
                    "tool_calls": [{"function": {"name": c.name, "arguments": c.arguments}} for c in calls],
                }
            )
            for call in calls:
                if self._exhausted(state):
                    trace.append({"event": "budget_exhausted"})
                    stop = True
                    break
                requested += 1
                ok, error, payload, loop, repairs = self._run_call(call.name, call.arguments, state)
                stop = stop or loop
                failures += 0 if ok else 1
                repairs_total += len(repairs)
                entry: dict[str, Any] = {
                    "event": "tool_call",
                    "name": call.name[:TRACE_NAME_CHARS],
                    "arguments": _truncate(call.arguments),
                    "ok": ok,
                }
                if not ok:
                    entry["error"] = error
                if repairs:
                    entry["repairs"] = repairs
                trace.append(entry)
                messages.append(
                    {
                        "role": "tool",
                        "tool_name": call.name[:TRACE_NAME_CHARS],
                        "content": format_tool_result(call.name[:TRACE_NAME_CHARS], payload),
                    }
                )

        final = self.llm.chat(messages, format=ANSWER_SCHEMA)
        usage = add_usage(state.usage, final.usage)
        trace.append({"event": "final"})
        parsed = parse_answer(final.text, self.tenant.source_ids())
        if parsed.parse_error is not None:
            trace.append({"event": "format_error", "detail": parsed.parse_error})
        return Answer(
            text=parsed.text,
            citations=parsed.citations,
            abstained=parsed.abstained,
            usage=usage,
            tool_calls=requested,
            tool_call_failures=failures,
            tool_call_repairs=repairs_total,
            tool_trace=trace,
            invalid_citations=parsed.invalid_citations,
            repaired_citations=parsed.repaired_citations,
        )

    def _run_call(
        self, name: str, arguments: dict[str, Any], state: LoopState
    ) -> tuple[bool, str | None, dict[str, Any], bool, list[str]]:
        """Normalise, validate and execute one call.

        Returns (ok, error, result payload for the model, is_loop, repairs); repairs are kept on failure too.
        """
        normalized, repairs = normalize_tool_arguments(name, arguments, self.tools)
        check = validate_tool_call(name, normalized, self.tools)
        if not check.ok:
            error = check.error or "invalid tool call"
            return False, error, {"error": error}, False, repairs
        key = _key(name, check.arguments)
        if key in state.seen:
            error = "repeated call"
            return False, error, {"error": error}, True, repairs
        state.seen.add(key)
        try:
            result = self._execute(name, check.arguments, state)
        except Exception as exc:  # store/embed failure: class name only, never the message text
            error = type(exc).__name__
            return False, error, {"error": "tool execution failed"}, False, repairs
        if name == "read_source" and result.get("error") == UNKNOWN_SOURCE_ERROR:
            return False, UNKNOWN_SOURCE_ERROR, result, False, repairs  # the model still sees the error result
        return True, None, result, False, repairs


class AgenticAnswerer(ToolLoopAnswerer):
    name = "agentic"
