"""Run record (contracts.md "runinfo.py"): everything needed to reproduce a run, no network."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from fakes import FakeLLM, make_tenant
from ngo_assistant.chunking import ChunkParams
from ngo_assistant.ingest import manifest_sha256
from ngo_assistant.prompt import system_prompt_sha256
from ngo_assistant.runinfo import build_run_record

NOW = datetime(2026, 10, 15, 12, 0, 0, tzinfo=UTC)
KEYS = {
    "created_at", "variant", "tenant", "chat_model", "embed_model", "model_digests", "chunk_params", "top_k",
    "max_tool_calls", "context_length", "prompt_sha256", "manifest_sha256", "git_commit",
    "ingest", "chunk_params_source",
}


def record(monkeypatch=None, *, variant="vector", manifest_path=None, git_commit=lambda: "abc1234", top_k=4,
           max_tool_calls=None, tenant=None, llm=None, ingest_record=None):
    return build_run_record(
        tenant or make_tenant("a"), llm or FakeLLM(), variant=variant, chunk_params=ChunkParams(), top_k=top_k,
        max_tool_calls=max_tool_calls, manifest_path=manifest_path, git_commit=git_commit, now=lambda: NOW,
        ingest_record=ingest_record,
    )


def test_record_has_exactly_the_documented_keys(monkeypatch):
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH", raising=False)
    assert set(record()) == KEYS


def test_record_is_json_serialisable(monkeypatch):
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH", raising=False)
    json.dumps(record())


def test_record_names_variant_tenant_models_and_digests(monkeypatch):
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH", raising=False)
    rec = record(variant="agentic", llm=FakeLLM(chat_model="llama3.2:1b", embed_model="bge-m3"))
    assert rec["variant"] == "agentic"
    assert rec["tenant"] == "t"
    assert rec["chat_model"] == "llama3.2:1b"
    assert rec["embed_model"] == "bge-m3"
    assert rec["model_digests"] == {"llama3.2:1b": "digest-chat", "bge-m3": "digest-embed"}


def test_record_has_chunk_params_and_retrieval_limits(monkeypatch):
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH", raising=False)
    rec = record(top_k=4, max_tool_calls=None)
    assert rec["chunk_params"] == {"max_chars": 1200, "overlap_chars": 150}
    assert (rec["top_k"], rec["max_tool_calls"]) == (4, None)
    rec = record(variant="agentic", top_k=None, max_tool_calls=6)
    assert (rec["top_k"], rec["max_tool_calls"]) == (None, 6)


def test_created_at_comes_from_the_injected_clock(monkeypatch):
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH", raising=False)
    assert record()["created_at"] == "2026-10-15T12:00:00+00:00"


def test_prompt_hash_is_the_system_prompt_hash_of_the_tenant(monkeypatch):
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH", raising=False)
    tenant = make_tenant("a", system_prompt="special rules")
    assert record(tenant=tenant)["prompt_sha256"] == system_prompt_sha256(tenant)


def test_context_length_comes_from_env_or_is_null(monkeypatch):
    monkeypatch.setenv("OLLAMA_CONTEXT_LENGTH", "8192")
    assert record()["context_length"] == 8192
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH")
    assert record()["context_length"] is None


def test_manifest_hash_is_taken_from_the_manifest_file_or_null(monkeypatch, tmp_path):
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH", raising=False)
    manifest = {"generated": "2026-10-14", "sources": {"a": {"sha256": "1" * 64}}}
    path = tmp_path / "MANIFEST.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert record(manifest_path=path)["manifest_sha256"] == manifest_sha256(manifest)
    assert record(manifest_path=tmp_path / "missing.json")["manifest_sha256"] is None
    assert record(manifest_path=None)["manifest_sha256"] is None


def test_git_commit_comes_from_the_injected_callable_and_none_is_tolerated(monkeypatch):
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH", raising=False)
    assert record(git_commit=lambda: "deadbeef")["git_commit"] == "deadbeef"
    assert record(git_commit=lambda: None)["git_commit"] is None


def test_default_git_lookup_does_not_raise(monkeypatch):
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH", raising=False)
    rec = build_run_record(make_tenant("a"), FakeLLM(), variant="vector", chunk_params=ChunkParams(), top_k=4,
                           max_tool_calls=None, manifest_path=None)
    assert rec["git_commit"] is None or isinstance(rec["git_commit"], str)


INGEST = {
    "tenant": "t", "started": "2026-10-14T10:00:00+00:00", "finished": "2026-10-14T10:05:00+00:00",
    "params": {"max_chars": 900, "overlap_chars": 100}, "documents": 3, "chunks": 10, "skipped": 0,
    "embed_tokens": 99, "drift": [], "embed_model": "bge-m3", "embed_model_digest": "sha-embed",
    "manifest_sha256": "f" * 64, "git_commit": "ingestcommit",
}


def test_ingest_record_is_copied_into_the_ingest_key_with_only_the_documented_fields(monkeypatch):
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH", raising=False)
    rec = record(ingest_record=INGEST)
    assert rec["ingest"] == {
        "params": {"max_chars": 900, "overlap_chars": 100}, "embed_model": "bge-m3",
        "embed_model_digest": "sha-embed", "manifest_sha256": "f" * 64, "git_commit": "ingestcommit",
        "finished": "2026-10-14T10:05:00+00:00",
    }


def test_chunk_params_come_from_the_ingest_run_when_present(monkeypatch):
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH", raising=False)
    rec = record(ingest_record=INGEST)
    assert rec["chunk_params"] == {"max_chars": 900, "overlap_chars": 100}
    assert rec["chunk_params_source"] == "ingest_run"


def test_without_an_ingest_run_chunk_params_are_the_defaults_and_ingest_is_null(monkeypatch):
    monkeypatch.delenv("OLLAMA_CONTEXT_LENGTH", raising=False)
    rec = record(ingest_record=None)
    assert rec["ingest"] is None
    assert rec["chunk_params"] == {"max_chars": 1200, "overlap_chars": 150}
    assert rec["chunk_params_source"] == "defaults"
    json.dumps(record(ingest_record=INGEST))
