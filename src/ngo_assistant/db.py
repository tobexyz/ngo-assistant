"""Retrieval store: types, the `Store` protocol and the PostgreSQL + pgvector implementation.

Contract: .claude/specs/2026-10-14-assistant/contracts.md (retrieval store + addendum).
SQL syntax verified in docs/tech.md sections 14-16. All identifiers (schema) go through
`psycopg.sql.Identifier` after validation; all data values are bound parameters.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Any, Protocol

import psycopg
from pgvector import Vector
from pgvector.psycopg import register_vector
from psycopg import sql

if TYPE_CHECKING:
    from ngo_assistant.chunking import Chunk

SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
SNIPPET_MAX_CHARS = 300
EF_SEARCH = 40  # pgvector default (docs/tech.md section 14), set explicitly per query
_MARK_START, _MARK_STOP = "⦉", "⦊"  # ts_headline markers, stripped again in Python


# ----------------------------------------------------------------------------- types


@dataclass(frozen=True)
class RetrievedChunk:
    source_id: str
    title: str
    published: date | None
    heading: str | None
    text: str
    distance: float


@dataclass(frozen=True)
class SearchHit:
    source_id: str
    title: str
    published: date | None
    snippet: str


@dataclass(frozen=True)
class DocInfo:
    source_id: str
    title: str
    language: str
    published: date | None


@dataclass(frozen=True)
class DocumentPart:
    source_id: str
    part: int
    parts_total: int
    text: str


@dataclass(frozen=True)
class DocumentRecord:
    source_id: str
    title: str
    url: str
    language: str
    published: date | None
    licence: str
    redistributable: bool
    kind: str
    sha256: str
    text: str
    ingest_key: str | None = None  # sha256 over text hash, chunk params and embed model (ingest.ingest_key)


@dataclass(frozen=True)
class StoredChunk:
    chunk: Chunk
    embedding: list[float]


class Store(Protocol):
    # retrieval side
    def search_chunks(self, embedding: list[float], k: int) -> list[RetrievedChunk]: ...
    def search_documents(self, query: str, limit: int) -> list[SearchHit]: ...
    def read_document(self, source_id: str, part: int, part_chars: int = 1500) -> DocumentPart | None: ...
    def list_documents(self) -> list[DocInfo]: ...

    # ingest side
    def document_sha(self, source_id: str) -> str | None: ...
    def document_ingest_key(self, source_id: str) -> str | None: ...
    def upsert_document(self, doc: DocumentRecord) -> None: ...
    def replace_chunks(self, source_id: str, chunks: list[StoredChunk]) -> None: ...
    def store_document(self, doc: DocumentRecord, chunks: list[StoredChunk]) -> None: ...
    def chunk_hashes(self) -> list[tuple[str, int, str]]: ...
    def record_run(self, record: dict[str, Any]) -> None: ...
    def last_ingest_run(self) -> dict[str, Any] | None: ...
    def counts(self) -> dict[str, int]: ...


# ----------------------------------------------------------------------------- PostgresStore


def _embed_dim() -> int:
    raw = os.environ.get("NGO_EMBED_DIM", "1024")
    try:
        dim = int(raw)
    except ValueError as exc:
        raise ValueError(f"NGO_EMBED_DIM must be an integer, got {raw!r}") from exc
    if not 1 <= dim <= 2000:  # pgvector HNSW limit (docs/tech.md section 14)
        raise ValueError(f"NGO_EMBED_DIM must be between 1 and 2000, got {dim}")
    return dim


def _clean_snippet(raw: str) -> str:
    text = raw.replace(_MARK_START, "").replace(_MARK_STOP, "")
    text = " ".join(text.split())
    return text[:SNIPPET_MAX_CHARS]


class PostgresStore:
    """pgvector + full-text store. One lazily opened connection, autocommit off, explicit transactions."""

    def __init__(self, database_url: str, schema: str = "public") -> None:
        if not SCHEMA_RE.fullmatch(schema):
            raise ValueError(f"invalid schema name {schema!r}: must match {SCHEMA_RE.pattern}")
        self._url = database_url
        self.schema = schema
        self._conn: psycopg.Connection[Any] | None = None

    # -- connection and identifiers
    def _connection(self) -> psycopg.Connection[Any]:
        if self._conn is None or self._conn.closed:
            conn = psycopg.connect(self._url, autocommit=False)
            try:
                with conn.transaction():
                    conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
                register_vector(conn)
            except Exception:
                conn.close()
                raise
            self._conn = conn
        return self._conn

    def close(self) -> None:
        if self._conn is not None and not self._conn.closed:
            self._conn.close()
        self._conn = None

    def _t(self, table: str) -> sql.Composable:
        return sql.SQL("{}.{}").format(sql.Identifier(self.schema), sql.Identifier(table))

    # -- schema
    def create_schema(self) -> None:
        dim = _embed_dim()
        s = sql.Identifier(self.schema)
        docs, chunks, runs = self._t("documents"), self._t("chunks"), self._t("ingest_runs")
        statements: list[sql.Composed] = [
            sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(s),
            sql.SQL(
                "CREATE TABLE IF NOT EXISTS {} ("
                "source_id text PRIMARY KEY, title text NOT NULL, url text NOT NULL, language text NOT NULL, "
                "published date, licence text NOT NULL, redistributable boolean NOT NULL, kind text NOT NULL, "
                "sha256 text NOT NULL, text text NOT NULL, "
                "tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED)"
            ).format(docs),
            sql.SQL("CREATE INDEX IF NOT EXISTS {} ON {} USING gin (tsv)").format(
                sql.Identifier("documents_tsv_gin"), docs),
            sql.SQL(
                "CREATE TABLE IF NOT EXISTS {} ("
                "source_id text NOT NULL REFERENCES {} (source_id) ON DELETE CASCADE, "
                "ord integer NOT NULL, heading text, text text NOT NULL, char_start integer NOT NULL, "
                "char_end integer NOT NULL, sha256 text NOT NULL, embedding vector({}) NOT NULL, "
                "PRIMARY KEY (source_id, ord))"
            ).format(chunks, docs, sql.SQL(str(dim))),  # dim is a validated int
            sql.SQL(
                "CREATE INDEX IF NOT EXISTS {} ON {} USING hnsw (embedding vector_cosine_ops) "
                "WITH (m = 16, ef_construction = 64)"
            ).format(sql.Identifier("chunks_embedding_hnsw"), chunks),
            sql.SQL(
                "CREATE TABLE IF NOT EXISTS {} (id bigserial PRIMARY KEY, "
                "started_at timestamptz NOT NULL DEFAULT now(), record jsonb NOT NULL)"
            ).format(runs),
            # additive: databases created before ingest keys keep working (NULL key = changed)
            sql.SQL("ALTER TABLE {} ADD COLUMN IF NOT EXISTS ingest_key text").format(docs),
        ]
        conn = self._connection()
        with conn.transaction():
            for stmt in statements:
                conn.execute(stmt)

    # -- retrieval side
    def search_chunks(self, embedding: list[float], k: int) -> list[RetrievedChunk]:
        if k <= 0:
            return []
        vec = Vector(embedding)
        query = sql.SQL(
            "SELECT c.source_id, d.title, d.published, c.heading, c.text, c.distance FROM ("
            "SELECT source_id, ord, heading, text, embedding <=> %s AS distance FROM {chunks} "
            "ORDER BY embedding <=> %s LIMIT %s) c "
            "JOIN {docs} d ON d.source_id = c.source_id ORDER BY c.distance, c.source_id, c.ord"
        ).format(chunks=self._t("chunks"), docs=self._t("documents"))
        conn = self._connection()
        with conn.transaction():
            conn.execute("SELECT set_config('hnsw.ef_search', %s, true)", (str(EF_SEARCH),))  # SET LOCAL
            rows = conn.execute(query, (vec, vec, k)).fetchall()
        return [RetrievedChunk(source_id=r[0], title=r[1], published=r[2], heading=r[3], text=r[4],
                               distance=float(r[5])) for r in rows]

    def search_documents(self, query: str, limit: int) -> list[SearchHit]:
        if not query.strip() or limit <= 0:
            return []
        stmt = sql.SQL(
            "SELECT r.source_id, r.title, r.published, "
            "ts_headline('simple', d.text, plainto_tsquery('simple', %(q)s), "
            "%(opts)s) AS snippet FROM ("
            "SELECT source_id, title, published, ts_rank(tsv, plainto_tsquery('simple', %(q)s)) AS rank "
            "FROM {docs} WHERE tsv @@ plainto_tsquery('simple', %(q)s) "
            "ORDER BY rank DESC, source_id LIMIT %(limit)s) r "
            "JOIN {docs} d ON d.source_id = r.source_id ORDER BY r.rank DESC, r.source_id"
        ).format(docs=self._t("documents"))
        opts = f"MaxWords=30, MinWords=10, MaxFragments=1, StartSel={_MARK_START}, StopSel={_MARK_STOP}"
        conn = self._connection()
        with conn.transaction():
            rows = conn.execute(stmt, {"q": query, "opts": opts, "limit": limit}).fetchall()
        return [SearchHit(source_id=r[0], title=r[1], published=r[2], snippet=_clean_snippet(r[3])) for r in rows]

    def read_document(self, source_id: str, part: int, part_chars: int = 1500) -> DocumentPart | None:
        if part_chars <= 0:
            raise ValueError("part_chars must be positive")
        part = max(part, 0)
        stmt = sql.SQL("SELECT char_length(text), substr(text, %s, %s) FROM {docs} WHERE source_id = %s").format(
            docs=self._t("documents"))
        conn = self._connection()
        with conn.transaction():
            row = conn.execute(stmt, (part * part_chars + 1, part_chars, source_id)).fetchone()
        if row is None:
            return None
        total = max(1, math.ceil(row[0] / part_chars))
        return DocumentPart(source_id=source_id, part=part, parts_total=total, text=row[1])

    def list_documents(self) -> list[DocInfo]:
        stmt = sql.SQL(
            'SELECT source_id, title, language, published FROM {docs} ORDER BY source_id COLLATE "C"'
        ).format(docs=self._t("documents"))
        conn = self._connection()
        with conn.transaction():
            rows = conn.execute(stmt).fetchall()
        return [DocInfo(source_id=r[0], title=r[1], language=r[2], published=r[3]) for r in rows]

    # -- ingest side
    def document_sha(self, source_id: str) -> str | None:
        stmt = sql.SQL("SELECT sha256 FROM {docs} WHERE source_id = %s").format(docs=self._t("documents"))
        conn = self._connection()
        with conn.transaction():
            row = conn.execute(stmt, (source_id,)).fetchone()
        return None if row is None else str(row[0])

    def document_ingest_key(self, source_id: str) -> str | None:
        stmt = sql.SQL("SELECT ingest_key FROM {docs} WHERE source_id = %s").format(docs=self._t("documents"))
        conn = self._connection()
        with conn.transaction():
            row = conn.execute(stmt, (source_id,)).fetchone()
        return None if row is None or row[0] is None else str(row[0])

    def _upsert_stmt(self) -> sql.Composed:
        return sql.SQL(
            "INSERT INTO {docs} (source_id, title, url, language, published, licence, redistributable, kind, "
            "sha256, text, ingest_key) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (source_id) DO UPDATE SET title = EXCLUDED.title, url = EXCLUDED.url, "
            "language = EXCLUDED.language, published = EXCLUDED.published, licence = EXCLUDED.licence, "
            "redistributable = EXCLUDED.redistributable, kind = EXCLUDED.kind, sha256 = EXCLUDED.sha256, "
            "text = EXCLUDED.text, ingest_key = EXCLUDED.ingest_key"
        ).format(docs=self._t("documents"))

    @staticmethod
    def _doc_params(doc: DocumentRecord) -> tuple[Any, ...]:
        return (doc.source_id, doc.title, doc.url, doc.language, doc.published, doc.licence, doc.redistributable,
                doc.kind, doc.sha256, doc.text, doc.ingest_key)

    def _replace_chunks_in(self, conn: psycopg.Connection[Any], source_id: str, chunks: list[StoredChunk]) -> None:
        delete = sql.SQL("DELETE FROM {chunks} WHERE source_id = %s").format(chunks=self._t("chunks"))
        insert = sql.SQL(
            "INSERT INTO {chunks} (source_id, ord, heading, text, char_start, char_end, sha256, embedding) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
        ).format(chunks=self._t("chunks"))
        rows = [(source_id, s.chunk.ord, s.chunk.heading, s.chunk.text, s.chunk.char_start, s.chunk.char_end,
                 s.chunk.sha256, Vector(s.embedding)) for s in chunks]
        conn.execute(delete, (source_id,))
        if rows:
            with conn.cursor() as cur:
                cur.executemany(insert, rows)

    def upsert_document(self, doc: DocumentRecord) -> None:
        conn = self._connection()
        with conn.transaction():
            conn.execute(self._upsert_stmt(), self._doc_params(doc))

    def replace_chunks(self, source_id: str, chunks: list[StoredChunk]) -> None:
        conn = self._connection()
        with conn.transaction():
            self._replace_chunks_in(conn, source_id, chunks)

    def store_document(self, doc: DocumentRecord, chunks: list[StoredChunk]) -> None:
        """Upsert the document and replace its chunks in ONE transaction (all or nothing)."""
        conn = self._connection()
        with conn.transaction():
            conn.execute(self._upsert_stmt(), self._doc_params(doc))
            self._replace_chunks_in(conn, doc.source_id, chunks)

    def chunk_hashes(self) -> list[tuple[str, int, str]]:
        stmt = sql.SQL(
            'SELECT source_id, ord, sha256 FROM {chunks} ORDER BY source_id COLLATE "C", ord'
        ).format(chunks=self._t("chunks"))
        conn = self._connection()
        with conn.transaction():
            rows = conn.execute(stmt).fetchall()
        return [(str(r[0]), int(r[1]), str(r[2])) for r in rows]

    def record_run(self, record: dict[str, Any]) -> None:
        stmt = sql.SQL("INSERT INTO {runs} (record) VALUES (%s::jsonb)").format(runs=self._t("ingest_runs"))
        conn = self._connection()
        with conn.transaction():
            conn.execute(stmt, (json.dumps(record, default=str),))

    def last_ingest_run(self) -> dict[str, Any] | None:
        stmt = sql.SQL("SELECT record FROM {runs} ORDER BY id DESC LIMIT 1").format(runs=self._t("ingest_runs"))
        conn = self._connection()
        with conn.transaction():
            row = conn.execute(stmt).fetchone()
        if row is None:
            return None
        record = row[0]
        if isinstance(record, str):
            record = json.loads(record)
        return record if isinstance(record, dict) else None

    def counts(self) -> dict[str, int]:
        stmt = sql.SQL("SELECT (SELECT count(*) FROM {docs}), (SELECT count(*) FROM {chunks})").format(
            docs=self._t("documents"), chunks=self._t("chunks"))
        conn = self._connection()
        with conn.transaction():
            row = conn.execute(stmt).fetchone()
        assert row is not None
        return {"documents": int(row[0]), "chunks": int(row[1])}
