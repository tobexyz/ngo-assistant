"""Ingest the tenant corpus into the store, and build/check the raw-data manifest.

Contract: .claude/specs/2026-10-14-assistant/contracts.md ("ingest.py and manifest" and the Addendum).
No network, no shell: only local files, the LLM client's embed() and the store.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ngo_assistant.chunking import ChunkParams, chunk_document, embedding_input
from ngo_assistant.config import Tenant
from ngo_assistant.db import DocumentRecord, Store, StoredChunk
from ngo_assistant.runinfo import default_git_commit


@dataclass(frozen=True)
class IngestResult:
    documents: int  # documents written in this run
    chunks: int  # chunks written in this run
    skipped: int  # documents whose sha256 was unchanged
    embed_tokens: int
    drift: list[str] = field(default_factory=list)  # source ids whose raw file differs from the manifest


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ingest_key(text_sha256: str, params: ChunkParams, embed_model: str) -> str:
    """sha256 over everything that decides a document's stored chunks: text, chunk parameters, embed model."""
    canonical = json.dumps(
        {"text": text_sha256, "chunk_params": asdict(params), "embed_model": embed_model},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return _sha256_text(canonical)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def ingest(
    tenant: Tenant,
    store: Store,
    llm: Any,
    corpus_dir: Path,
    params: ChunkParams = ChunkParams(),  # noqa: B008 - frozen dataclass
    rebuild: bool = False,
    manifest: dict[str, Any] | None = None,
    batch_size: int = 16,
) -> IngestResult:
    """Ingest `corpus_dir/<id>.txt` for every tenant source; unchanged documents are skipped."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    started = _now_iso()

    missing = [s.id for s in tenant.sources if not (corpus_dir / f"{s.id}.txt").is_file()]
    if missing:
        raise FileNotFoundError(f"corpus files missing in {corpus_dir}: {', '.join(missing)}")

    texts = {s.id: (corpus_dir / f"{s.id}.txt").read_text(encoding="utf-8") for s in tenant.sources}
    with_nul = [sid for sid, text in texts.items() if "\x00" in text]
    if with_nul:
        raise ValueError(
            f"corpus text contains NUL (0x00) characters, PostgreSQL cannot store them: {', '.join(with_nul)}"
        )

    drift = check_manifest(manifest, corpus_dir.parent / "raw") if manifest is not None else []

    documents = chunks_written = skipped = embed_tokens = 0
    embed_model = getattr(llm, "embed_model", None)
    model_name = str(embed_model)

    for source in tenant.sources:
        text = texts[source.id]
        digest = _sha256_text(text)
        key = ingest_key(digest, params, model_name)
        if not rebuild and store.document_ingest_key(source.id) == key:
            skipped += 1
            continue

        chunks = chunk_document(text, source.title, params)
        inputs = [embedding_input(source.title, c) for c in chunks]
        vectors: list[list[float]] = []
        for start in range(0, len(inputs), batch_size):
            batch = inputs[start : start + batch_size]
            result = llm.embed(batch)
            if len(result.vectors) != len(batch):
                raise RuntimeError(
                    f"embed returned {len(result.vectors)} vectors for {len(batch)} inputs (source {source.id})"
                )
            vectors.extend(result.vectors)
            embed_tokens += result.usage.embed_tokens

        store.store_document(
            DocumentRecord(
                source_id=source.id,
                title=source.title,
                url=source.url,
                language=source.language,
                published=source.published,
                licence=source.licence,
                redistributable=source.redistributable,
                kind=source.kind,
                sha256=digest,
                text=text,
                ingest_key=key,
            ),
            [StoredChunk(chunk=c, embedding=v) for c, v in zip(chunks, vectors, strict=True)],
        )
        documents += 1
        chunks_written += len(chunks)

    store.record_run(
        {
            "tenant": tenant.slug,
            "started": started,
            "finished": _now_iso(),
            "params": {"max_chars": params.max_chars, "overlap_chars": params.overlap_chars},
            "documents": documents,
            "chunks": chunks_written,
            "skipped": skipped,
            "embed_tokens": embed_tokens,
            "drift": drift,
            "embed_model": embed_model,
            "embed_model_digest": _embed_digest(llm, embed_model),
            "manifest_sha256": manifest_sha256(manifest) if manifest is not None else None,
            "git_commit": default_git_commit(),
        }
    )
    return IngestResult(
        documents=documents, chunks=chunks_written, skipped=skipped, embed_tokens=embed_tokens, drift=drift
    )


def _embed_digest(llm: Any, embed_model: Any) -> str | None:
    if embed_model is None or not hasattr(llm, "model_digests"):
        return None
    return str(llm.model_digests().get(embed_model, "unknown"))


# ----------------------------------------------------------------------------- manifest


def _raw_file(raw_dir: Path, source_id: str) -> Path | None:
    """The single `raw_dir/<id>.<ext>` that is not `<id>.meta.json`."""
    for path in sorted(raw_dir.glob(f"{source_id}.*")):
        if path.name != f"{source_id}.meta.json" and path.is_file():
            return path
    return None


def build_manifest(raw_dir: Path, tenant: Tenant) -> dict[str, Any]:
    """Manifest of the raw files of all non-synthetic sources, from `<id>.meta.json`."""
    sources: dict[str, dict[str, Any]] = {}
    for source in tenant.sources:
        if source.kind == "synthetic":
            continue
        meta_path = raw_dir / f"{source.id}.meta.json"
        if not meta_path.is_file():
            raise FileNotFoundError(f"no meta file for source {source.id}: {meta_path}")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        raw = _raw_file(raw_dir, source.id)
        if raw is None:
            raise FileNotFoundError(f"no raw file for source {source.id} in {raw_dir}")
        sources[source.id] = {
            "url": meta["url"],
            "sha256": meta["sha256"],
            "bytes": raw.stat().st_size,
            "fetched_at": meta["fetched_at"],
        }
    return {"generated": datetime.now(UTC).date().isoformat(), "sources": sources}


def check_manifest(manifest: dict[str, Any], raw_dir: Path) -> list[str]:
    """Ids whose raw file is missing or whose sha256 differs from the manifest."""
    changed: list[str] = []
    for source_id, entry in manifest.get("sources", {}).items():
        raw = _raw_file(raw_dir, source_id)
        if raw is None or hashlib.sha256(raw.read_bytes()).hexdigest() != entry.get("sha256"):
            changed.append(source_id)
    return changed


def manifest_sha256(manifest: dict[str, Any]) -> str:
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
