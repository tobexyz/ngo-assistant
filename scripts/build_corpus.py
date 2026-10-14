#!/usr/bin/env python3
"""Convert the raw downloads (data/raw/) into plain-text corpus files (data/corpus/).

HTML -> text with the stdlib html.parser (chrome removed, headings/lists/table rows kept),
PDF -> text per page with pypdf (optional extra "corpus"), synthetic sources copied unchanged.
No summarising and no rewriting: quotes must match the page text. PDF text gets a deterministic
ligature repair (see repair_pdf_text). Writes INDEX.md and exits 1 if any source is missing,
unreadable, thinner than --min-chars or its output still contains a NUL byte.
"""

from __future__ import annotations

import argparse
import io
import itertools
import json
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

SAFE_ID = re.compile(r"[a-z0-9][a-z0-9._-]*")  # same rule as scripts/fetch_sources.py
SKIP_TAGS = {"script", "style", "noscript", "nav", "footer", "aside", "form", "svg", "iframe"}
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr",
}  # fmt: skip
BLOCK_TAGS = {
    "p", "div", "li", "ul", "ol", "tr", "table", "blockquote", "pre", "dt", "dd", "dl", "section", "article",
    "main", "figure", "figcaption", "caption", "h1", "h2", "h3", "h4", "h5", "h6",
}  # fmt: skip
HEADINGS = {f"h{i}" for i in range(1, 7)}
WIKI_ROOT_ID = "mw-content-text"

LIGATURE_CODE_POINTS = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st",
}  # fmt: skip
NUL_CANDIDATES = ("fi", "fl", "ff", "ffi", "ffl")  # order of preference for a NUL left by a ligature glyph
_EDGE = re.compile(r"^[^\w\0]+|[^\w\0]+$")


def _word_parts(token: str) -> list[str]:
    """Lowercase words of a token: edge punctuation stripped, split at hyphens; NUL kept."""
    return [p for p in _EDGE.sub("", token).lower().split("-") if p]


def vocabulary(text: str) -> frozenset[str]:
    """Lowercase words (and hyphen parts) of the NUL-free tokens of `text`."""
    words: set[str] = set()
    for token in text.split():
        if "\0" not in token:
            words.update(_word_parts(token))
    return frozenset(words)


def _fill(token: str, combo: Sequence[str]) -> str:
    it = iter(combo)
    return re.sub("\0", lambda _: next(it), token)


def repair_pdf_text(text: str, extra_vocab: frozenset[str] = frozenset()) -> tuple[str, list[str]]:
    """Repair ligature damage of pypdf text. Returns (repaired text, unresolved tokens).

    Deterministic, no network, no dictionaries. Rules:
    1. U+FB00..FB06 become ff, fi, fl, ffi, ffl, st, st.
    2. pypdf emits NUL (0x00) for ligature glyphs without a Unicode mapping ("signi\\0cant"). For each
       whitespace-delimited token containing NUL, every NUL is replaced by one of NUL_CANDIDATES
       (fi, fl, ff, ffi, ffl); combinations are tried in that order (first NUL varies slowest) and the first
       one whose word (the hyphen parts that contained a NUL, lowercased, edge punctuation stripped) occurs
       in the vocabulary wins. Vocabulary = NUL-free tokens of the SAME document, then `extra_vocab`
       (words of the other corpus files of the build run).
    3. No match: the token gets fi everywhere and is reported as unresolved. A token with no letter at
       all (a symbol glyph such as a bullet) loses its NUL and is reported as unresolved too.
    Text without NUL or ligature code points is returned unchanged; the repair is idempotent.
    """
    for lig, plain in LIGATURE_CODE_POINTS.items():
        text = text.replace(lig, plain)
    if "\0" not in text:
        return text, []
    vocab = vocabulary(text) | extra_vocab
    unresolved: list[str] = []
    cache: dict[str, str] = {}

    def resolve(token: str) -> str:
        if not re.search(r"[^\W\d_]", token):
            unresolved.append(token)
            return token.replace("\0", "")
        count = token.count("\0")
        nul_parts = [i for i, p in enumerate(_word_parts(token)) if "\0" in p]
        for combo in itertools.product(NUL_CANDIDATES, repeat=count):
            candidate = _fill(token, combo)
            parts = _word_parts(candidate)
            if all(parts[i] in vocab for i in nul_parts):
                return candidate
        unresolved.append(token)
        return _fill(token, ["fi"] * count)

    def fix(match: re.Match[str]) -> str:
        token = match.group()
        if token not in cache:
            cache[token] = resolve(token)
        return cache[token]

    repaired = re.sub(r"\S*\0\S*", fix, text)
    return repaired, list(dict.fromkeys(unresolved))


PdfExtractor = Callable[[bytes], list[str]]


def valid_id(source_id: str) -> bool:
    return bool(SAFE_ID.fullmatch(source_id)) and ".." not in source_id


def collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


class TextExtractor(HTMLParser):
    """Collects blocks of text; optionally only inside the element with id `root_id`."""

    def __init__(self, root_id: str | None = None) -> None:
        super().__init__(convert_charrefs=True)
        self.root_id = root_id
        self.root_found = False
        self.blocks: list[str] = []
        self._stack: list[str] = []
        self._root_depth: int | None = None  # stack length at which the root element sits
        self._skip_depth: int | None = None
        self._buf: list[str] = []
        self._prefix = ""
        self._cells: list[str] | None = None
        self._cell_open = False
        # <header> is kept only if it holds an h1 or p (OWID puts title and intro there); else dropped.
        self._header: tuple[int, int, bool] | None = None  # (stack depth, len(blocks) at start, has h1/p)

    @property
    def _active(self) -> bool:
        return (self.root_id is None or self._root_depth is not None) and self._skip_depth is None

    def _flush(self) -> None:
        text = collapse("".join(self._buf))
        self._buf = []
        if text:
            self.blocks.append(self._prefix + text)
        self._prefix = ""

    def _end_cell(self) -> None:
        if self._cells is not None and self._cell_open:
            self._cells.append(collapse("".join(self._buf)))
            self._buf = []
        self._cell_open = False

    def _end_row(self) -> None:
        if self._cells is None:
            return
        self._end_cell()
        cells = [c for c in self._cells if c]
        if cells:
            self.blocks.append(" | ".join(cells))
        self._cells = None
        self._buf = []

    def _end_header(self) -> None:
        if self._header is None:
            return
        _, mark, keep = self._header
        self._header = None
        if keep:
            self._flush()
        else:
            del self.blocks[mark:]
            self._buf = []
            self._prefix = ""

    def _prefix_for_stack(self) -> str:
        for tag in reversed(self._stack):
            if tag in HEADINGS:
                return "#" * int(tag[1]) + " "
            if tag == "li":
                return "- "
        return ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in VOID_TAGS:
            if tag == "br" and self._active:
                self._buf.append(" ")
            return
        if tag in ("td", "th", "tr") and self._active and self._cells is not None:
            if tag == "tr":
                self._end_row()
            else:
                self._end_cell()
            while self._stack and self._stack[-1] in ("td", "th"):  # implicitly closed cell
                self._stack.pop()
        self._stack.append(tag)
        if self.root_id is not None and self._root_depth is None and dict(attrs).get("id") == self.root_id:
            self._root_depth = len(self._stack)
            self.root_found = True
        if self._skip_depth is None and tag in SKIP_TAGS:
            self._skip_depth = len(self._stack)
            return
        if not self._active:
            return
        if tag == "header" and self._header is None:
            self._flush()
            self._header = (len(self._stack), len(self.blocks), False)
        elif self._header is not None and tag in ("h1", "p"):
            self._header = (self._header[0], self._header[1], True)
        if tag in BLOCK_TAGS:
            self._flush()
        if tag == "tr":
            self._cells = []
            self._cell_open = False
        elif tag in ("td", "th") and self._cells is not None:
            self._cell_open = True
            self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag in VOID_TAGS or tag not in self._stack:
            return
        active_before = self._active
        if active_before and tag == "table":
            self._end_row()  # a row left open by a missing </tr>
        if active_before and tag in BLOCK_TAGS | {"td", "th"}:
            if tag in ("td", "th"):
                self._end_cell()
            elif tag == "tr":
                self._end_row()
            else:
                self._flush()
        if (
            tag == "header"
            and self._header is not None
            and self._header[0] == len(self._stack) - self._stack[::-1].index("header")
        ):
            self._end_header()
        while self._stack:  # close implicitly unclosed children, e.g. <p> or <li> without end tag
            popped = self._stack.pop()
            depth = len(self._stack) + 1
            if self._skip_depth == depth:
                self._skip_depth = None
            if self._root_depth == depth:
                self._root_depth = None
            if popped == tag:
                break

    def handle_data(self, data: str) -> None:
        if not self._active or not data:
            return
        if not "".join(self._buf).strip():
            self._prefix = self._prefix_for_stack()
        self._buf.append(data)

    def close(self) -> None:
        super().close()
        self._end_row()
        self._end_header()
        self._flush()


def html_to_text(html: str, root_id: str | None = None) -> tuple[str, bool]:
    """Return (plain text, root_found). With root_id=None root_found is True."""
    parser = TextExtractor(root_id)
    parser.feed(html)
    parser.close()
    return "\n\n".join(parser.blocks), (root_id is None or parser.root_found)


def extract_pdf_text(data: bytes) -> list[str]:
    """Text of each page via pypdf (extra 'corpus')."""
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise RuntimeError('pypdf is not installed; run: pip install -e ".[corpus]"') from e
    reader = PdfReader(io.BytesIO(data))
    return [page.extract_text() or "" for page in reader.pages]


def pdf_to_text(data: bytes, extract_pdf_text: PdfExtractor = extract_pdf_text) -> str:
    pages = extract_pdf_text(data)
    return "\n\n".join(f"[page {i}]\n{t.strip()}" for i, t in enumerate(pages, start=1))


def detect_kind(extension: str, data: bytes) -> str:
    """'pdf' or 'html'; the content wins over the file extension (fetch writes .bin for unknown types)."""
    if data.lstrip()[:5] == b"%PDF-":
        return "pdf"
    return "pdf" if extension == "pdf" and data.lstrip()[:1] != b"<" else "html"


def decode_html(data: bytes, meta: dict[str, Any]) -> str:
    charset = None
    m = re.search(r"charset=([\w-]+)", str(meta.get("content_type", "")), re.I)
    if m:
        charset = m.group(1)
    else:
        m2 = re.search(rb"<meta[^>]+charset=[\"']?([\w-]+)", data[:4096], re.I)
        if m2:
            charset = m2.group(1).decode("ascii", "replace")
    try:
        return data.decode(charset or "utf-8", errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


def first_heading(text: str) -> str:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not re.fullmatch(r"\[page \d+\]", ln.strip())]
    for ln in lines:
        if ln.startswith("#"):
            return ln.lstrip("#").strip()[:100]
    return lines[0][:100] if lines else ""


@dataclass
class Result:
    id: str
    language: str
    kind: str
    status: str  # OK, THIN or FAIL
    chars: int = 0
    heading: str = ""
    notes: str = ""
    text: str = field(default="", repr=False)
    is_pdf: bool = False


def find_raw(raw: Path, source_id: str) -> Path | None:
    for p in sorted(raw.glob(f"{source_id}.*")):
        if not p.name.endswith(".meta.json"):
            return p
    return None


def read_meta(raw: Path, source_id: str) -> dict[str, Any]:
    try:
        data = json.loads((raw / f"{source_id}.meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def contained(path: Path, base: Path) -> bool:
    return path.resolve().is_relative_to(base.resolve())


def is_pdf_source(source: Any, raw: Path) -> bool:
    if source.kind == "synthetic" or not valid_id(source.id):
        return False
    raw_file = find_raw(raw, source.id)
    if raw_file is None:
        return False
    try:
        return detect_kind(raw_file.suffix.lstrip("."), raw_file.read_bytes()) == "pdf"
    except OSError:
        return False


def convert_source(
    source: Any,
    raw: Path,
    out: Path,
    min_chars: int,
    root: Path,
    pdf_extractor: PdfExtractor,
    extra_vocab: frozenset[str] = frozenset(),
) -> Result:
    res = Result(source.id, source.language, source.kind, "FAIL")
    if not valid_id(source.id):
        res.notes = f"invalid source id {source.id!r}"
        return res
    target = out / f"{source.id}.txt"
    if not contained(target, out):
        res.notes = f"output path outside {out}"
        return res
    if source.kind == "synthetic":
        src_path = root / source.url
        if not contained(src_path, root):
            res.notes = f"synthetic path outside {root}: {source.url}"
            return res
        if not src_path.is_file():
            res.notes = f"synthetic file missing: {source.url}"
            return res
        data = src_path.read_bytes()
        out.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        text = data.decode("utf-8", errors="replace")
        res.status, res.chars, res.heading, res.notes = "OK", len(text), first_heading(text), "copied unchanged"
        res.text = text
        if "\0" in text:
            res.status, res.notes = "FAIL", "output contains NUL (0x00) bytes"
        return res
    raw_file = find_raw(raw, source.id)
    if raw_file is None:
        res.notes = f"raw file missing: {raw}/{source.id}.<html|pdf|bin>"
        return res
    data = raw_file.read_bytes()
    notes: list[str] = []
    try:
        if detect_kind(raw_file.suffix.lstrip("."), data) == "pdf":
            res.is_pdf = True
            text, unresolved = repair_pdf_text(pdf_to_text(data, pdf_extractor), extra_vocab)
            notes.append("pdf")
            if unresolved:
                shown = ", ".join(repr(t) for t in unresolved[:20])
                more = f" (+{len(unresolved) - 20} more)" if len(unresolved) > 20 else ""
                notes.append(f"unresolved ligature tokens ({len(unresolved)}): {shown}{more}")
        else:
            wiki = (urlsplit(source.url).hostname or "").lower().endswith("wikipedia.org")
            text, found = html_to_text(decode_html(data, read_meta(raw, source.id)), WIKI_ROOT_ID if wiki else None)
            if not found:
                text, _ = html_to_text(decode_html(data, read_meta(raw, source.id)))
                notes.append(f"{WIKI_ROOT_ID} not found, whole body used")
    except Exception as e:  # noqa: BLE001 - report any converter failure per source, keep going
        res.notes = f"conversion failed: {e}"
        return res
    out.mkdir(parents=True, exist_ok=True)
    target.write_text(text + "\n", encoding="utf-8")
    res.chars, res.heading, res.notes = len(text), first_heading(text), "; ".join(notes)
    res.text = text
    res.status = "OK" if res.chars >= min_chars else "THIN"
    if "\0" in text:
        res.status = "FAIL"
        res.notes = "; ".join([*notes, f"output still contains {text.count(chr(0))} NUL (0x00) byte(s)"])
    return res


def write_index(out: Path, results: list[Result], min_chars: int) -> None:
    lines = [
        "# Corpus index",
        "",
        "| id | language | kind | chars | first heading | notes |",
        "|---|---|---|---|---|---|",
    ]
    for r in results:
        cells = [r.id, r.language, r.kind, str(r.chars), r.heading, r.notes]
        lines.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
    bad = [r for r in results if r.status != "OK"]
    if bad:
        lines.append("")
    for r in bad:
        lines.append(f"- {r.status} {r.id}: {r.chars} chars (min {min_chars}) {r.notes}".rstrip())
    out.mkdir(parents=True, exist_ok=True)
    (out / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build(
    sources: Sequence[Any],
    raw: Path,
    out: Path,
    min_chars: int,
    root: Path = Path("."),
    out_stream: Any = None,
    extract_pdf_text: PdfExtractor = extract_pdf_text,
) -> int:
    out_stream = out_stream or sys.stdout
    # Phase 1: everything except PDFs; phase 2: PDFs, repaired with the words of phase 1 as extra vocabulary.
    done: dict[str, Result] = {}
    for phase in (1, 2):
        vocab = frozenset().union(*(vocabulary(r.text) for r in done.values())) if phase == 2 else frozenset()
        for s in sources:
            if s.id in done:
                continue
            if phase == 1 and is_pdf_source(s, raw):
                continue
            done[s.id] = convert_source(s, raw, out, min_chars, root, extract_pdf_text, vocab)
    results = [done[s.id] for s in sources]
    write_index(out, results, min_chars)
    failed = 0
    for r in results:
        print(f"{r.status:<4} {r.id}: {r.chars} chars {r.notes}".rstrip(), file=out_stream)
        failed += r.status != "OK"
    print(f"{len(results)} source(s), {failed} failed or thin", file=out_stream)
    return 1 if failed else 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tenant", required=True, help="path to the tenant YAML file")
    p.add_argument("--raw", default="data/raw", help="directory with the fetched files (default: data/raw)")
    p.add_argument("--out", default="data/corpus", help="output directory (default: data/corpus)")
    p.add_argument("--min-chars", type=int, default=500, help="minimum characters per real source (default: 500)")
    p.add_argument("--root", default=".", help="base directory for synthetic source paths (default: .)")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    from ngo_assistant.config import load_tenant

    tenant = load_tenant(args.tenant)
    return build(tenant.sources, Path(args.raw), Path(args.out), args.min_chars, root=Path(args.root))


if __name__ == "__main__":
    sys.exit(main())
