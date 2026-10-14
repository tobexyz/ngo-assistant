"""Thin Ollama client: chat and embed with uniform token accounting.

Written against docs/tech.md (ollama 0.6.3). Every call returns a Usage with
model_calls=1 so the runner can sum a whole agentic loop with add_usage().
No LangChain; the optional `client` argument lets tests inject a fake.
"""

from __future__ import annotations

import math
import os
from typing import Any

import ollama
from pydantic import BaseModel

from ngo_assistant.models import Usage

DEFAULT_CHAT_MODEL = "llama3.2:1b"
DEFAULT_EMBED_MODEL = "bge-m3"
DEFAULT_HOST = "http://127.0.0.1:11434"
# ollama.Client has no timeout by default (docs/tech.md); CPU inference is slow, so be generous.
DEFAULT_TIMEOUT_S = 300.0


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any]


class ChatResult(BaseModel):
    text: str
    tool_calls: list[ToolCall] = []
    usage: Usage = Usage()


class EmbedResult(BaseModel):
    vectors: list[list[float]]
    usage: Usage = Usage()


def add_usage(a: Usage, b: Usage) -> Usage:
    """Sum all fields; used to total every model call of one answer."""
    return Usage(
        input_tokens=a.input_tokens + b.input_tokens,
        output_tokens=a.output_tokens + b.output_tokens,
        embed_tokens=a.embed_tokens + b.embed_tokens,
        model_calls=a.model_calls + b.model_calls,
    )


def approx_embed_tokens(texts: list[str]) -> int:
    """APPROXIMATE token count: sum of ceil(len(text) / 4), the fallback documented in docs/tech.md.

    Not a real tokenizer count. Callers that use it must flag the run as approximate.
    """
    return sum(math.ceil(len(t) / 4) for t in texts)


def _get(obj: Any, key: str) -> Any:
    """Read a field from an ollama response object or a mapping."""
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


class LLMClient:
    """Chat and embedding calls against one Ollama server.

    Arguments left as None come from the environment (NGO_CHAT_MODEL,
    NGO_EMBED_MODEL, OLLAMA_HOST), then from the defaults above.
    """

    def __init__(
        self,
        chat_model: str | None = None,
        embed_model: str | None = None,
        host: str | None = None,
        client: ollama.Client | None = None,
    ):
        self.chat_model = chat_model or os.environ.get("NGO_CHAT_MODEL") or DEFAULT_CHAT_MODEL
        self.embed_model = embed_model or os.environ.get("NGO_EMBED_MODEL") or DEFAULT_EMBED_MODEL
        self.host = host or os.environ.get("OLLAMA_HOST") or DEFAULT_HOST
        if client is None:
            timeout = float(os.environ.get("NGO_LLM_TIMEOUT_S") or DEFAULT_TIMEOUT_S)
            client = ollama.Client(host=self.host, timeout=timeout)
        self._client = client

    @staticmethod
    def _options() -> dict[str, Any] | None:
        # Only forwarded when set client-side; otherwise the server's OLLAMA_CONTEXT_LENGTH applies.
        ctx = os.environ.get("OLLAMA_CONTEXT_LENGTH")
        return {"num_ctx": int(ctx)} if ctx else None

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        format: dict[str, Any] | None = None,  # noqa: A002 - mirrors the ollama argument name
    ) -> ChatResult:
        """One chat call. `format` is a JSON-schema dict (structured output); never combined with `tools`."""
        if tools is not None and format is not None:
            raise ValueError("tools and format must not be combined in one chat call")
        return self._chat(messages, tools, format, self._options())

    def _chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        format: dict[str, Any] | None,  # noqa: A002
        options: dict[str, Any] | None,
    ) -> ChatResult:
        kwargs: dict[str, Any] = {}
        if format is not None:
            kwargs["format"] = format
        resp = self._client.chat(model=self.chat_model, messages=messages, tools=tools, options=options, **kwargs)
        message = _get(resp, "message")
        calls = [
            ToolCall(name=_get(fn, "name"), arguments=dict(_get(fn, "arguments") or {}))
            for tc in (_get(message, "tool_calls") or [])
            for fn in [_get(tc, "function")]
        ]
        usage = Usage(
            input_tokens=_get(resp, "prompt_eval_count") or 0,
            output_tokens=_get(resp, "eval_count") or 0,
            model_calls=1,
        )
        return ChatResult(text=_get(message, "content") or "", tool_calls=calls, usage=usage)

    def model_digests(self) -> dict[str, str]:
        """Digest of the configured chat and embed model from client.list(); "unknown" when not listed.

        An untagged configured name matches a listed `name:latest`.
        """
        listed: dict[str, str] = {}
        for m in _get(self._client.list(), "models") or []:
            name, digest = _get(m, "model"), _get(m, "digest")
            if name and digest:
                listed[str(name)] = str(digest)
        out: dict[str, str] = {}
        for configured in (self.chat_model, self.embed_model):
            candidates = [configured] if ":" in configured else [configured, f"{configured}:latest"]
            out[configured] = next((listed[c] for c in candidates if c in listed), "unknown")
        return out

    def warm_up(self) -> Usage:
        """One tiny chat call (1 output token) to load the model before the first timed question."""
        options = {**(self._options() or {}), "num_predict": 1}
        return self._chat([{"role": "user", "content": "ok"}], None, None, options).usage

    def embed(self, texts: list[str]) -> EmbedResult:
        """Embed texts. embed_tokens is the server's prompt_eval_count (0 if it reports none).

        See approx_embed_tokens() for the documented, approximate fallback.
        """
        resp = self._client.embed(model=self.embed_model, input=texts, options=self._options())
        vectors = [list(v) for v in _get(resp, "embeddings") or []]
        usage = Usage(embed_tokens=_get(resp, "prompt_eval_count") or 0, model_calls=1)
        return EmbedResult(vectors=vectors, usage=usage)
