"""Unit tests for ngo_assistant.llm with a fake standing in for ollama.Client.

No network: the client is injected. The fake responses support both
attribute access (resp.message.content) and item access (resp["message"]["content"]),
like the real ollama response objects, so these tests do not dictate which
style llm.py uses.
"""

import pytest

from ngo_assistant.llm import ChatResult, EmbedResult, LLMClient, ToolCall, add_usage
from ngo_assistant.models import Usage


class Obj:
    """Response stand-in: attribute and item access to the same fields."""

    def __init__(self, **fields):
        self.__dict__.update(fields)

    def __getitem__(self, key):
        return getattr(self, key)

    def __contains__(self, key):
        return key in self.__dict__

    def get(self, key, default=None):
        return getattr(self, key, default)


def chat_response(content="hi", tool_calls=None, prompt_eval_count=12, eval_count=3):
    calls = None
    if tool_calls is not None:
        calls = [Obj(function=Obj(name=name, arguments=args)) for name, args in tool_calls]
    return Obj(
        model="whatever",
        message=Obj(role="assistant", content=content, tool_calls=calls),
        prompt_eval_count=prompt_eval_count,
        eval_count=eval_count,
    )


def embed_response(embeddings=None, prompt_eval_count=7):
    return Obj(model="whatever", embeddings=embeddings or [[0.1, 0.2], [0.3, 0.4]], prompt_eval_count=prompt_eval_count)


class FakeOllama:
    """Records calls; returns canned responses. Signature mirrors ollama.Client."""

    def __init__(self, chat_reply=None, embed_reply=None):
        self.chat_reply = chat_reply or chat_response()
        self.embed_reply = embed_reply or embed_response()
        self.chat_calls = []
        self.embed_calls = []

    def chat(self, model="", messages=None, *, tools=None, **kwargs):
        self.chat_calls.append({"model": model, "messages": messages, "tools": tools, **kwargs})
        return self.chat_reply

    def embed(self, model="", input="", **kwargs):
        self.embed_calls.append({"model": model, "input": input, **kwargs})
        return self.embed_reply


def make_llm(fake=None, chat_model="chat-m", embed_model="embed-m", host="http://test:1"):
    fake = fake or FakeOllama()
    return LLMClient(chat_model=chat_model, embed_model=embed_model, host=host, client=fake), fake


MESSAGES = [{"role": "user", "content": "Hallo?"}]
TOOLS = [{"type": "function", "function": {"name": "search", "parameters": {"type": "object"}}}]


def test_chat_maps_token_counts_to_usage_with_one_model_call():
    llm, _ = make_llm(FakeOllama(chat_reply=chat_response(prompt_eval_count=12, eval_count=3)))
    result = llm.chat(MESSAGES)
    assert isinstance(result, ChatResult)
    assert result.text == "hi"
    assert result.usage.input_tokens == 12
    assert result.usage.output_tokens == 3
    assert result.usage.embed_tokens == 0
    assert result.usage.model_calls == 1


def test_chat_passes_configured_model_messages_and_tools_to_client():
    llm, fake = make_llm(chat_model="llama3.2:3b")
    llm.chat(MESSAGES, tools=TOOLS)
    assert len(fake.chat_calls) == 1
    call = fake.chat_calls[0]
    assert call["model"] == "llama3.2:3b"
    assert call["messages"] == MESSAGES
    assert call["tools"] == TOOLS


def test_chat_without_tool_calls_returns_empty_list():
    llm, _ = make_llm(FakeOllama(chat_reply=chat_response(tool_calls=None)))
    assert llm.chat(MESSAGES).tool_calls == []


def test_chat_parses_tool_calls_into_toolcall_objects():
    reply = chat_response(content="", tool_calls=[("search", {"query": "Moor", "k": 3}), ("fetch", {"id": "s1"})])
    llm, _ = make_llm(FakeOllama(chat_reply=reply))
    result = llm.chat(MESSAGES, tools=TOOLS)
    assert result.tool_calls == [
        ToolCall(name="search", arguments={"query": "Moor", "k": 3}),
        ToolCall(name="fetch", arguments={"id": "s1"}),
    ]


@pytest.mark.parametrize(("prompt_eval_count", "eval_count"), [(None, 5), (8, None), (None, None)])
def test_chat_treats_missing_token_counts_as_zero(prompt_eval_count, eval_count):
    # Ollama omits prompt_eval_count when the prompt is served from cache.
    reply = chat_response(prompt_eval_count=prompt_eval_count, eval_count=eval_count)
    llm, _ = make_llm(FakeOllama(chat_reply=reply))
    usage = llm.chat(MESSAGES).usage
    assert usage.input_tokens == (prompt_eval_count or 0)
    assert usage.output_tokens == (eval_count or 0)
    assert usage.model_calls == 1


def test_embed_returns_vectors_and_embed_usage_with_one_model_call():
    vectors = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    llm, fake = make_llm(FakeOllama(embed_reply=embed_response(embeddings=vectors, prompt_eval_count=9)))
    result = llm.embed(["Klimaschutz", "climate protection"])
    assert isinstance(result, EmbedResult)
    assert result.vectors == vectors
    assert result.usage.embed_tokens == 9
    assert result.usage.model_calls == 1
    assert result.usage.input_tokens == 0
    assert result.usage.output_tokens == 0


def test_embed_uses_configured_embed_model_and_passes_texts():
    llm, fake = make_llm(embed_model="bge-m3")
    llm.embed(["a", "b"])
    assert len(fake.embed_calls) == 1
    assert fake.embed_calls[0]["model"] == "bge-m3"
    assert list(fake.embed_calls[0]["input"]) == ["a", "b"]


def test_embed_treats_missing_token_count_as_zero():
    llm, _ = make_llm(FakeOllama(embed_reply=embed_response(prompt_eval_count=None)))
    usage = llm.embed(["a", "b"]).usage
    assert usage.embed_tokens == 0
    assert usage.model_calls == 1


def test_add_usage_sums_every_field():
    a = Usage(input_tokens=10, output_tokens=2, embed_tokens=5, model_calls=1)
    b = Usage(input_tokens=30, output_tokens=4, embed_tokens=0, model_calls=2)
    assert add_usage(a, b) == Usage(input_tokens=40, output_tokens=6, embed_tokens=5, model_calls=3)


def test_add_usage_with_empty_usage_is_identity():
    a = Usage(input_tokens=1, output_tokens=2, embed_tokens=3, model_calls=4)
    assert add_usage(a, Usage()) == a
    assert add_usage(Usage(), a) == a


def test_llm_client_reads_defaults_from_env_when_not_given(monkeypatch):
    monkeypatch.delenv("NGO_CHAT_MODEL", raising=False)
    monkeypatch.delenv("NGO_EMBED_MODEL", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    fake = FakeOllama()
    llm = LLMClient(chat_model=None, embed_model=None, host=None, client=fake)
    assert llm.host == "http://127.0.0.1:11434"
    llm.chat(MESSAGES)
    llm.embed(["x"])
    assert fake.chat_calls[0]["model"] == "llama3.2:1b"
    assert fake.embed_calls[0]["model"] == "bge-m3"


def test_llm_client_env_overrides_defaults(monkeypatch):
    monkeypatch.setenv("NGO_CHAT_MODEL", "llama3.2:3b")
    monkeypatch.setenv("NGO_EMBED_MODEL", "other-embed")
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama:11434")
    fake = FakeOllama()
    llm = LLMClient(client=fake)
    assert llm.host == "http://ollama:11434"
    llm.chat(MESSAGES)
    llm.embed(["x"])
    assert fake.chat_calls[0]["model"] == "llama3.2:3b"
    assert fake.embed_calls[0]["model"] == "other-embed"


def test_explicit_arguments_win_over_env(monkeypatch):
    monkeypatch.setenv("NGO_CHAT_MODEL", "from-env")
    llm, fake = make_llm(chat_model="explicit")
    llm.chat(MESSAGES)
    assert fake.chat_calls[0]["model"] == "explicit"


def test_context_length_env_is_forwarded_as_num_ctx_to_chat_and_embed(monkeypatch):
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", "8192")
    llm, fake = make_llm()
    llm.chat(MESSAGES)
    llm.embed(["x"])
    assert fake.chat_calls[0]["options"] == {"num_ctx": 8192}
    assert fake.embed_calls[0]["options"] == {"num_ctx": 8192}


@pytest.mark.parametrize("value", [None, ""])
def test_context_length_unset_or_empty_sends_no_options(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH", raising=False)
    else:
        monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", value)
    llm, fake = make_llm()
    llm.chat(MESSAGES)
    llm.embed(["x"])
    assert fake.chat_calls[0]["options"] is None
    assert fake.embed_calls[0]["options"] is None


def test_invalid_context_length_raises_value_error(monkeypatch):
    # Documented behaviour: a non-integer value fails loudly instead of being ignored,
    # so variants A and B can never silently run with different context budgets.
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", "lots")
    llm, fake = make_llm()
    with pytest.raises(ValueError):
        llm.chat(MESSAGES)
    assert fake.chat_calls == []


class RecordingClientFactory:
    """Stands in for ollama.Client; records constructor kwargs."""

    def __init__(self):
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return FakeOllama()


def test_real_client_is_built_with_default_timeout_of_300s(monkeypatch):
    monkeypatch.delenv("NGO_LLM_TIMEOUT_S", raising=False)
    factory = RecordingClientFactory()
    monkeypatch.setattr("ngo_assistant.llm.ollama.Client", factory)
    LLMClient(host="http://test:1")
    assert factory.kwargs == {"host": "http://test:1", "timeout": 300.0}


def test_real_client_timeout_comes_from_env(monkeypatch):
    monkeypatch.setenv("NGO_LLM_TIMEOUT_S", "12.5")
    factory = RecordingClientFactory()
    monkeypatch.setattr("ngo_assistant.llm.ollama.Client", factory)
    LLMClient(host="http://test:1")
    assert factory.kwargs["timeout"] == 12.5


def test_invalid_timeout_env_raises_value_error(monkeypatch):
    monkeypatch.setenv("NGO_LLM_TIMEOUT_S", "soon")
    monkeypatch.setattr("ngo_assistant.llm.ollama.Client", RecordingClientFactory())
    with pytest.raises(ValueError):
        LLMClient(host="http://test:1")


# ----------------------------------------------------------------------------- format, model_digests, warm_up

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]}


class FakeOllamaWithList(FakeOllama):
    """Adds client.list(): response shape from docs/tech.md section 12 (models[].model / .digest)."""

    def __init__(self, models, **kwargs):
        super().__init__(**kwargs)
        self.models = models

    def list(self):
        return Obj(models=[Obj(model=name, digest=digest, size=1) for name, digest in self.models])


def test_chat_passes_format_schema_through_to_the_client():
    llm, fake = make_llm()
    llm.chat(MESSAGES, format=SCHEMA)
    assert fake.chat_calls[0]["format"] == SCHEMA
    assert fake.chat_calls[0]["tools"] is None


def test_chat_without_format_sends_no_format():
    llm, fake = make_llm()
    llm.chat(MESSAGES)
    assert fake.chat_calls[0].get("format") is None


def test_chat_with_tools_and_format_together_raises_value_error_before_calling_the_server():
    llm, fake = make_llm()
    with pytest.raises(ValueError):
        llm.chat(MESSAGES, tools=TOOLS, format=SCHEMA)
    assert fake.chat_calls == []


@pytest.mark.parametrize(("tools", "fmt"), [([], SCHEMA), (TOOLS, {}), ([], {})])
def test_chat_guard_uses_is_not_none_so_empty_values_are_also_rejected(tools, fmt):
    llm, fake = make_llm()
    with pytest.raises(ValueError):
        llm.chat(MESSAGES, tools=tools, format=fmt)
    assert fake.chat_calls == []


def test_model_digests_maps_configured_models_to_list_digests():
    fake = FakeOllamaWithList([("chat-m", "sha-chat"), ("embed-m:latest", "sha-embed"), ("other", "sha-other")])
    llm, _ = make_llm(fake)
    assert llm.model_digests() == {"chat-m": "sha-chat", "embed-m": "sha-embed"}


def test_model_digests_uses_unknown_for_a_model_that_is_not_listed():
    fake = FakeOllamaWithList([("chat-m", "sha-chat")])
    llm, _ = make_llm(fake)
    assert llm.model_digests() == {"chat-m": "sha-chat", "embed-m": "unknown"}


def test_warm_up_sends_one_tiny_chat_call_with_one_token_and_returns_its_usage(monkeypatch):
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH", raising=False)
    llm, fake = make_llm(FakeOllama(chat_reply=chat_response(prompt_eval_count=5, eval_count=1)))
    usage = llm.warm_up()
    [call] = fake.chat_calls
    assert call["messages"][-1]["content"] == "ok"
    assert call["options"]["num_predict"] == 1
    assert call.get("tools") is None
    assert usage == Usage(input_tokens=5, output_tokens=1, model_calls=1)


def test_warm_up_keeps_the_context_length_option(monkeypatch):
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", "8192")
    llm, fake = make_llm()
    llm.warm_up()
    assert fake.chat_calls[0]["options"] == {"num_ctx": 8192, "num_predict": 1}
