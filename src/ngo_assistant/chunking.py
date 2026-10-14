"""Deterministic, heading-aware chunker (contracts.md "chunking.py", design.md "Chunking").

Pure functions, stdlib only. The corpus text is split into blank-line separated blocks (as
`scripts/build_corpus.py` writes them). Blocks are packed into chunks of at most `max_chars`
characters; a chunk is always a contiguous slice of the input, so `text[char_start:char_end]`
equals `chunk.text`. A block longer than `max_chars` is split at sentence ends or newlines and, as
a last resort, hard-split at `max_chars`.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

_BLOCK_SEPARATOR = re.compile(r"\n[ \t\r]*\n\s*")
_SENTENCE_END = re.compile(r"[.?!](?=\s)")
_MAX_HEADING_CHARS = 200


@dataclass(frozen=True)
class ChunkParams:
    """Chunking parameters; recorded in the ingest run record."""

    max_chars: int = 1200
    overlap_chars: int = 150


DEFAULT_PARAMS = ChunkParams()


@dataclass(frozen=True)
class Chunk:
    """One chunk: `text` is exactly `source[char_start:char_end]`; `sha256` hashes `text` (UTF-8)."""

    ord: int
    heading: str | None
    text: str
    char_start: int
    char_end: int
    sha256: str


@dataclass(frozen=True)
class _Unit:
    """A packable span of the input (a block, or a piece of an oversized block)."""

    start: int
    end: int
    heading: str | None
    is_heading: bool


def _block_spans(text: str) -> list[tuple[int, int]]:
    """Return (start, end) of every non-empty blank-line separated block, whitespace trimmed."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for sep in [*_BLOCK_SEPARATOR.finditer(text), None]:
        raw_end = sep.start() if sep else len(text)
        segment = text[pos:raw_end]
        stripped = segment.strip()
        if stripped:
            start = pos + (len(segment) - len(segment.lstrip()))
            spans.append((start, start + len(stripped)))
        if sep:
            pos = sep.end()
    return spans


def _split_long(text: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    """Split text[start:end] into pieces of at most max_chars at sentence ends, newlines, or hard."""
    pieces: list[tuple[int, int]] = []
    while end - start > max_chars:
        window = text[start : start + max_chars + 1]
        cut = 0
        for match in _SENTENCE_END.finditer(window):
            if match.end() <= max_chars:
                cut = max(cut, match.end())
        newline = window.rfind("\n", 0, max_chars + 1)
        if newline > 0:
            cut = max(cut, newline)
        if cut <= 0:
            cut = max_chars
        piece = text[start : start + cut]
        piece_end = start + len(piece.rstrip())
        if piece_end > start:
            pieces.append((start, piece_end))
        start += cut
        while start < end and text[start].isspace():
            start += 1
    if start < end:
        pieces.append((start, end))
    return pieces


def _heading_label(block: str) -> str:
    return block.lstrip("#").strip()


def _is_heading_block(block: str, max_chars: int) -> bool:
    """A heading block starts with `#`, is a single line of at most 200 chars (and fits a chunk)."""
    return (
        block.startswith("#")
        and len(block) <= _MAX_HEADING_CHARS
        and len(block) <= max_chars
        and "\n" not in block
    )


def _units(text: str, max_chars: int) -> list[_Unit]:
    units: list[_Unit] = []
    heading: str | None = None
    for start, end in _block_spans(text):
        block = text[start:end]
        if _is_heading_block(block, max_chars):
            heading = _heading_label(block) or None
            units.append(_Unit(start, end, heading, True))
            continue
        spans = [(start, end)] if end - start <= max_chars else _split_long(text, start, end, max_chars)
        units.extend(_Unit(s, e, heading, False) for s, e in spans)
    return units


def chunk_document(text: str, title: str, params: ChunkParams = DEFAULT_PARAMS) -> list[Chunk]:
    """Split `text` into deterministic chunks; empty or whitespace-only input gives `[]`.

    `title` is not part of the chunk text (see `embedding_input`). The chunk heading is the
    nearest preceding heading block without the leading `#` (a single-line `#` block of at most
    200 characters; longer or multi-line `#` blocks are ordinary text and may be split), `None`
    before the first heading. The last unit of a chunk is repeated at the start of the next one
    when it is at most
    `overlap_chars` long (and the repeat still fits); `overlap_chars=0` disables the overlap.
    """
    if params.max_chars < 1:
        raise ValueError("max_chars must be at least 1")
    units = _units(text, params.max_chars)
    chunks: list[Chunk] = []
    current: list[_Unit] = []

    def flush() -> None:
        first, last = current[0], current[-1]
        body = text[first.start : last.end]
        chunks.append(
            Chunk(
                ord=len(chunks),
                heading=first.heading,
                text=body,
                char_start=first.start,
                char_end=last.end,
                sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
            )
        )

    for unit in units:
        if current and unit.end - current[0].start > params.max_chars:
            flush()
            last = current[-1]
            carry = (
                params.overlap_chars > 0
                and last.end - last.start <= params.overlap_chars
                and unit.end - last.start <= params.max_chars
            )
            current = [last] if carry else []
        current.append(unit)
    if current:
        flush()
    return chunks


def embedding_input(title: str, chunk: Chunk) -> str:
    """Text sent to the embedding model: `"{title} - {heading}\\n{text}"` (heading part optional)."""
    prefix = title if chunk.heading is None else f"{title} - {chunk.heading}"
    return f"{prefix}\n{chunk.text}"
