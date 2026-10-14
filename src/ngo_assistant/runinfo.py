"""Run record: everything needed to reproduce a run (contracts.md "runinfo.py")."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ngo_assistant.chunking import ChunkParams
from ngo_assistant.config import Tenant
from ngo_assistant.prompt import system_prompt_sha256

_INGEST_KEYS = ("params", "embed_model", "embed_model_digest", "manifest_sha256", "git_commit", "finished")


def default_git_commit() -> str | None:
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    out = proc.stdout.strip()
    return out if proc.returncode == 0 and out else None


def _manifest_hash(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _context_length() -> int | None:
    value = os.environ.get("OLLAMA_CONTEXT_LENGTH")
    try:
        return int(value) if value else None
    except ValueError:
        return None


def build_run_record(
    tenant: Tenant,
    llm: Any,
    *,
    variant: str,
    chunk_params: ChunkParams,
    top_k: int | None,
    max_tool_calls: int | None,
    manifest_path: Path | None,
    git_commit: Callable[[], str | None] | None = None,
    now: Callable[[], datetime] | None = None,
    ingest_record: dict | None = None,
) -> dict:
    """`ingest_record` is the last ingest run read from the store (Store.last_ingest_run()). When present, its
    chunk params describe the data actually searched and replace the code defaults in `chunk_params`."""
    created = (now or (lambda: datetime.now(UTC)))()
    ingest: dict | None = None
    effective_params = asdict(chunk_params)
    params_source = "defaults"
    if ingest_record is not None:
        ingest = {key: ingest_record.get(key) for key in _INGEST_KEYS}
        if isinstance(ingest_record.get("params"), dict):
            effective_params = dict(ingest_record["params"])
            params_source = "ingest_run"
    return {
        "created_at": created.isoformat(),
        "variant": variant,
        "tenant": tenant.slug,
        "chat_model": llm.chat_model,
        "embed_model": llm.embed_model,
        "model_digests": llm.model_digests(),
        "chunk_params": effective_params,
        "chunk_params_source": params_source,
        "ingest": ingest,
        "top_k": top_k,
        "max_tool_calls": max_tool_calls,
        "context_length": _context_length(),
        "prompt_sha256": system_prompt_sha256(tenant),
        "manifest_sha256": _manifest_hash(manifest_path),
        "git_commit": (git_commit or default_git_commit)(),
    }
