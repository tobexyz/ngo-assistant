"""In-memory fakes shared by the unit tests (docs: .claude/specs/2026-10-14-assistant/contracts.md).

FakeLLM stands in for ngo_assistant.llm.LLMClient, FakeStore for the Store protocol of ngo_assistant.db.
Both are deliberately strict: an unexpected call is a test failure, not a silent default.

Contract types (db.py, chunking.py) are imported lazily inside methods so each test module collects on its own.
FakeStore differs from PostgresStore in two known ways: search_documents is a case-insensitive substring match
ordered by id (not full-text ranked), and store_document checks the embedding dimension in Python to simulate a
failing transaction.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from ngo_assistant.config import Source, Tenant
from ngo_assistant.llm import ChatResult, EmbedResult, ToolCall
from ngo_assistant.models import Usage

if TYPE_CHECKING:  # contract modules are imported lazily so each test module collects on its own
    from ngo_assistant.db import DocInfo, DocumentPart, DocumentRecord, RetrievedChunk, SearchHit, StoredChunk

DIM = 4  # embedding dimension of the fakes


# ----------------------------------------------------------------------------- tenants


def make_source(source_id: str, *, kind: str = "web", published: date | None = date(2025, 1, 1),
                title: str | None = None):
    return Source(
        id=source_id,
        title=title or f"Title of {source_id}",
        url=f"https://example.org/{source_id}",
        language="en",
        kind=kind,
        licence="CC BY 4.0",
        licence_url="https://example.org/licence",
        redistributable=True,
        checked_on=date(2026, 10, 14),
        published=published,
    )


def make_tenant(*source_ids: str, system_prompt: str = "You answer from the sources only.", synthetic=()) -> Tenant:
    sources = [make_source(i) for i in source_ids] + [make_source(i, kind="synthetic") for i in synthetic]
    return Tenant(slug="t", name="T", languages=["de", "en"], system_prompt=system_prompt, sources=sources)


def write_tenant_yaml(path: Path, tenant: Tenant) -> Path:
    path.write_text(yaml.safe_dump(json.loads(tenant.model_dump_json()), allow_unicode=True), encoding="utf-8")
    return path


# ----------------------------------------------------------------------------- scripted chat results


def answer_json(answer: str = "An answer.", citations: list[str] | tuple[str, ...] = (), abstain: bool = False) -> str:
    return json.dumps({"answer": answer, "citations": list(citations), "abstain": abstain})


def chat_result(text: str = "", calls: list[tuple[str, dict[str, Any]]] | None = None, input_tokens: int = 10,
                output_tokens: int = 2) -> ChatResult:
    return ChatResult(
        text=text,
        tool_calls=[ToolCall(name=n, arguments=a) for n, a in (calls or [])],
        usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens, model_calls=1),
    )


def final_result(answer: str = "An answer.", citations: list[str] | tuple[str, ...] = (), abstain: bool = False,
                 input_tokens: int = 20, output_tokens: int = 5) -> ChatResult:
    return chat_result(answer_json(answer, citations, abstain), input_tokens=input_tokens, output_tokens=output_tokens)


def tool_result(name: str, **arguments: Any) -> ChatResult:
    return chat_result("", [(name, arguments)])


# ----------------------------------------------------------------------------- FakeLLM


def _hash_vector(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    raw = [digest[i] + 1.0 for i in range(DIM)]
    norm = math.sqrt(sum(x * x for x in raw))
    return [x / norm for x in raw]


class FakeLLM:
    """Scripted stand-in for LLMClient.

    `script` is consumed in order by chat(); every item is a ChatResult, or an exception instance that is
    raised. An EmbedResult at the head of the script is consumed by the next embed() call; without one,
    embed() returns fixed 4-dimensional vectors (`embed_vectors[text]` when given, else derived from the text)
    with Usage(embed_tokens=n, model_calls=1), n = `embed_tokens_per_text` per text.
    Calling chat() more often than scripted raises AssertionError.
    """

    def __init__(self, script: list[Any] | None = None, *, chat_model: str = "chat-m", embed_model: str = "embed-m",
                 embed_vectors: dict[str, list[float]] | None = None, embed_tokens_per_text: int = 3):
        self.script = list(script or [])
        self.chat_model = chat_model
        self.embed_model = embed_model
        self.embed_vectors = embed_vectors or {}
        self.embed_tokens_per_text = embed_tokens_per_text
        self.chat_calls: list[dict[str, Any]] = []
        self.embed_calls: list[list[str]] = []
        self.warm_ups = 0

    # -- LLMClient surface
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None,
             format: dict[str, Any] | None = None) -> ChatResult:  # noqa: A002 - mirrors LLMClient
        self.chat_calls.append({"messages": messages, "tools": tools, "format": format})
        if not self.script:
            raise AssertionError(f"FakeLLM.chat called {len(self.chat_calls)} times, script had fewer responses")
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        if not isinstance(item, ChatResult):
            raise AssertionError(f"FakeLLM.chat expected a ChatResult next in the script, got {type(item).__name__}")
        return item

    def embed(self, texts: list[str]) -> EmbedResult:
        self.embed_calls.append(list(texts))
        if self.script and isinstance(self.script[0], EmbedResult):
            return self.script.pop(0)
        vectors = [list(self.embed_vectors.get(t) or _hash_vector(t)) for t in texts]
        return EmbedResult(
            vectors=vectors,
            usage=Usage(embed_tokens=self.embed_tokens_per_text * len(texts), model_calls=1),
        )

    def model_digests(self) -> dict[str, str]:
        return {self.chat_model: "digest-chat", self.embed_model: "digest-embed"}

    def warm_up(self) -> Usage:
        self.warm_ups += 1
        return Usage(input_tokens=1, output_tokens=1, model_calls=1)

    # -- helpers for assertions
    @property
    def remaining(self) -> int:
        return len(self.script)

    def embedded_texts(self) -> list[str]:
        return [t for call in self.embed_calls for t in call]


# ----------------------------------------------------------------------------- FakeStore


class FakeStore:
    """In-memory implementation of the whole Store protocol.

    `writes` logs every mutating call (kind, source_id) so tests can assert that nothing was written.
    `search_error` makes search_documents raise (tool execution failure).
    """

    def __init__(self) -> None:
        self.documents: dict[str, DocumentRecord] = {}
        self.chunks: dict[str, list[StoredChunk]] = {}
        self.runs: list[dict[str, Any]] = []
        self.writes: list[tuple[str, str]] = []
        self.search_calls: list[tuple[str, int]] = []
        self.chunk_searches: list[tuple[list[float], int]] = []
        self.search_error: Exception | None = None

    # -- test seeding without going through ingest
    def seed(self, source_id: str, text: str, *, title: str | None = None, published: date | None = date(2025, 1, 1),
             language: str = "en", chunks: list[tuple[str, list[float]]] | None = None,
             heading: str | None = None) -> None:
        from ngo_assistant.chunking import Chunk
        from ngo_assistant.db import DocumentRecord, StoredChunk

        self.documents[source_id] = DocumentRecord(
            source_id=source_id, title=title or f"Title of {source_id}", url=f"https://example.org/{source_id}",
            language=language, published=published, licence="CC BY 4.0", redistributable=True, kind="web",
            sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(), text=text,
        )
        stored = []
        for n, (chunk_text, vector) in enumerate(chunks or []):
            chunk = Chunk(ord=n, heading=heading, text=chunk_text, char_start=0, char_end=len(chunk_text),
                          sha256=hashlib.sha256(chunk_text.encode("utf-8")).hexdigest())
            stored.append(StoredChunk(chunk=chunk, embedding=vector))
        self.chunks[source_id] = stored

    # -- retrieval side
    def search_chunks(self, embedding: list[float], k: int) -> list[RetrievedChunk]:
        from ngo_assistant.db import RetrievedChunk

        self.chunk_searches.append((list(embedding), k))
        scored = []
        for source_id, stored in self.chunks.items():
            doc = self.documents[source_id]
            for item in stored:
                distance = 1.0 - sum(a * b for a, b in zip(embedding, item.embedding, strict=True))
                scored.append((distance, source_id, item.chunk.ord, RetrievedChunk(
                    source_id=source_id, title=doc.title, published=doc.published, heading=item.chunk.heading,
                    text=item.chunk.text, distance=distance)))
        scored.sort(key=lambda t: (t[0], t[1], t[2]))
        return [t[3] for t in scored[:k]]

    def search_documents(self, query: str, limit: int) -> list[SearchHit]:
        from ngo_assistant.db import SearchHit

        self.search_calls.append((query, limit))
        if self.search_error is not None:
            raise self.search_error
        needle = query.lower()
        hits = []
        for source_id in sorted(self.documents):
            doc = self.documents[source_id]
            pos = doc.text.lower().find(needle)
            if pos >= 0:
                # deliberately long (up to 500 chars): execute_tool must truncate to 300
                hits.append(SearchHit(source_id=source_id, title=doc.title, published=doc.published,
                                      snippet=doc.text[pos:pos + 500]))
        return hits[:limit]

    def read_document(self, source_id: str, part: int, part_chars: int = 1500) -> DocumentPart | None:
        from ngo_assistant.db import DocumentPart

        doc = self.documents.get(source_id)
        if doc is None:
            return None
        total = max(1, math.ceil(len(doc.text) / part_chars))
        part = max(0, part)  # like PostgresStore: a negative part is clamped to 0
        text = doc.text[part * part_chars:(part + 1) * part_chars]  # out-of-range part gives empty text
        return DocumentPart(source_id=source_id, part=part, parts_total=total, text=text)

    def list_documents(self) -> list[DocInfo]:
        from ngo_assistant.db import DocInfo

        return [DocInfo(source_id=d.source_id, title=d.title, language=d.language, published=d.published)
                for d in (self.documents[k] for k in sorted(self.documents))]

    # -- ingest side
    def document_sha(self, source_id: str) -> str | None:
        doc = self.documents.get(source_id)
        return doc.sha256 if doc else None

    def document_ingest_key(self, source_id: str) -> str | None:
        doc = self.documents.get(source_id)
        return doc.ingest_key if doc else None

    def store_document(self, doc: DocumentRecord, chunks: list[StoredChunk]) -> None:
        """All or nothing: validate every chunk first, then swap in document and chunks together."""
        for item in chunks:
            if len(item.embedding) != DIM:
                raise ValueError(f"embedding dimension {len(item.embedding)} != {DIM} (source {doc.source_id})")
        self.writes.append(("store_document", doc.source_id))
        self.documents[doc.source_id] = doc
        self.chunks[doc.source_id] = list(chunks)

    def upsert_document(self, doc: DocumentRecord) -> None:
        self.writes.append(("upsert_document", doc.source_id))
        self.documents[doc.source_id] = doc

    def replace_chunks(self, source_id: str, chunks: list[StoredChunk]) -> None:
        self.writes.append(("replace_chunks", source_id))
        self.chunks[source_id] = list(chunks)

    def chunk_hashes(self) -> list[tuple[str, int, str]]:
        return sorted((sid, c.chunk.ord, c.chunk.sha256) for sid, items in self.chunks.items() for c in items)

    def record_run(self, record: dict[str, Any]) -> None:
        self.runs.append(record)

    def last_ingest_run(self) -> dict[str, Any] | None:
        return self.runs[-1] if self.runs else None

    def counts(self) -> dict[str, int]:
        return {"documents": len(self.documents), "chunks": sum(len(v) for v in self.chunks.values())}
