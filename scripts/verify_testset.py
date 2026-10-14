#!/usr/bin/env python3
"""Mechanically verify a test set against the converted corpus and its evidence records.

Checks (design: .claude/specs/2026-10-14-testset/design.md): every quote is verbatim in the
text of its source, numbers in expected answers occur in the quotes, unanswerable cases have
zero corpus hits for their absence terms, dates and ids match the tenant. Optionally writes
the public hand-check sheet; quotes of non-redistributable sources are withheld there.
Stdlib + ngo_assistant only; no network.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from ngo_assistant.config import Source, Tenant, load_tenant
from ngo_assistant.eval.schema import Category, EvalCase, load_testset

ID_PATTERN = re.compile(r"(ans|una|mul|num|con|inj)-\d{2}")
PREFIX = {
    Category.ANSWERABLE: "ans",
    Category.UNANSWERABLE: "una",
    Category.MULTI_STEP: "mul",
    Category.NUMBERS: "num",
    Category.CONTESTED: "con",
    Category.INJECTION: "inj",
}
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
THOUSANDS = re.compile(r"\d{1,3}(?:[.,]\d{3})+")
QUOTE_MIN, QUOTE_MAX = 8, 400
ABSENCE_MIN_CHARS = 4
MONTHS_EN = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
             "November", "December")  # fmt: skip
MONTHS_DE = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
             "November", "Dezember")  # fmt: skip
WITHHELD = "[quote withheld: licence; see data/corpus/evidence.jsonl]"

_QUOTES = {
    **dict.fromkeys("“”„‟«»″", '"'),
    **dict.fromkeys("‘’‚‛′´`", "'"),
    **dict.fromkeys("‐‑‒–—―−", "-"),
    "­": "",
}


def normalise(text: str) -> str:
    """NFKC, typographic quotes/dashes to ASCII, whitespace collapsed. Case is kept."""
    text = unicodedata.normalize("NFKC", text)
    text = "".join(_QUOTES.get(ch, ch) for ch in text)
    return re.sub(r"\s+", " ", text).strip()


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_hidden_claim(claim: dict[str, Any], text: str) -> str | None:
    """Check offsets + hash of a claim against the normalised corpus text; return a problem or None."""
    start, end, digest = claim.get("start"), claim.get("end"), claim.get("sha256")
    if not (isinstance(start, int) and isinstance(end, int) and isinstance(digest, str)):
        return "claim needs integer start, end and a sha256 string"
    if not QUOTE_MIN <= end - start <= QUOTE_MAX:
        return f"quote length {end - start} outside {QUOTE_MIN}-{QUOTE_MAX} characters (offsets {start}-{end})"
    if start < 0 or sha256_hex(normalise(text)[start:end]) != digest:
        return f"sha256 of corpus text at offsets {start}-{end} does not match"
    return None


def quote_in_text(quote: str, text: str) -> bool:
    q = normalise(quote)
    return bool(q) and q in normalise(text)


def date_spans(text: str, d: date) -> list[tuple[int, int]]:
    """Spans of `text` that are a recognised expression of date `d`.

    ISO yyyy-mm-dd; dd.mm.yyyy; "12 March 2025" / "12. März 2025" (en or de month name);
    "March 2025" (so a bare year counts only directly after its month name).
    """
    months = "|".join(re.escape(m) for m in {MONTHS_EN[d.month - 1], MONTHS_DE[d.month - 1]})
    day, year = f"0?{d.day}", str(d.year)
    patterns = [
        rf"(?<!\d){d.isoformat()}(?!\d)",
        rf"(?<!\d){day}\.0?{d.month}\.{year}(?!\d)",
        rf"(?<![\w.])(?:{day}\.?\s+)?(?:{months})\s+{year}(?!\d)",
    ]
    return [m.span() for p in patterns for m in re.finditer(p, text, re.IGNORECASE)]


def without_dates(text: str, d: date) -> str:
    for start, end in sorted(date_spans(text, d), reverse=True):
        text = text[:start] + " " + text[end:]
    return text


def numbers_in(text: str) -> list[str]:
    """Digit groups with optional '.'/',' separators, in order of appearance (e.g. 1.430, 59,4)."""
    return NUMBER.findall(text)


def _forms(token: str) -> set[str]:
    forms = {token, token.translate(str.maketrans(".,", ",."))}
    if THOUSANDS.fullmatch(token):
        forms.add(re.sub(r"[.,]", "", token))
    return forms


def same_number(a: str, b: str) -> bool:
    """Equal if identical or differing only by decimal/thousands mark ('59,4' == '59.4')."""
    return bool(_forms(a) & _forms(b))


def _number_in_any(number: str, pool: list[str]) -> bool:
    return any(same_number(number, other) for other in pool)


def check_case(case: EvalCase, evidence: dict[str, Any] | None, texts: dict[str, str], tenant: Tenant) -> list[str]:
    """Return a list of problems (empty = case passes). Messages start with the case id."""
    cid = case.id
    out: list[str] = []

    def bad(msg: str) -> None:
        out.append(f"{cid}: {msg}")

    if not ID_PATTERN.fullmatch(cid):
        bad("id must match ^(ans|una|mul|num|con|inj)-\\d{2}$")
    elif not cid.startswith(PREFIX[case.category] + "-"):
        bad(f"id prefix does not match category {case.category.value} (expected {PREFIX[case.category]}-)")

    if not (case.notes or "").strip():
        bad("notes must be non-empty (one line stating the trap or purpose)")
    if case.category is Category.NUMBERS and not re.search(r"\d", case.expected_answer or ""):
        bad("numbers case: expected_answer contains no digit")

    by_id = {s.id: s for s in tenant.sources}
    for sid in case.source_ids:
        if sid not in by_id:
            bad(f"unknown source id {sid!r} (not in tenant)")

    if evidence is None:
        bad("no evidence record")
        return out
    if evidence.get("case_id") != cid:
        bad(f"evidence case_id {evidence.get('case_id')!r} does not match")
    claims: list[dict[str, Any]] = list(evidence.get("claims") or [])
    absence: list[str] = list(evidence.get("absence_terms") or [])

    if case.category is Category.UNANSWERABLE:
        if claims:
            bad("unanswerable: claims must be empty")
        if not 2 <= len(absence) <= 4:
            bad(f"unanswerable: need 2-4 absence_terms, got {len(absence)}")
        hay = {sid: normalise(t).casefold() for sid, t in texts.items()}
        seen: set[str] = set()
        for term in absence:
            t = normalise(term).casefold()
            if not t:
                bad("absence term is blank after normalisation")
                continue
            if len(t) < ABSENCE_MIN_CHARS:
                bad(f"absence term {t!r} must be at least {ABSENCE_MIN_CHARS} characters")
            if t in seen:
                bad(f"absence terms must be distinct: {t!r} repeated")
            seen.add(t)
            hits = sorted(sid for sid, h in hay.items() if t and t in h)
            if hits:
                bad(f"absence term {t!r} occurs in corpus: {', '.join(hits)}")
        return out

    if not claims:
        bad("no claims")
    for claim in claims:
        sid = str(claim.get("source_id", ""))
        quote = claim.get("quote")
        label = f"claim {sid} ({str(claim.get('supports', ''))[:30]!r})"
        if sid not in case.source_ids:
            bad(f"{label}: source is not in case.source_ids")
        if sid not in texts:
            bad(f"{label}: no corpus text for claim source {sid!r}")
            continue
        if quote is None:
            problem = check_hidden_claim(claim, texts[sid])
            if problem:
                bad(f"{label}: {problem}")
            continue
        quote = str(quote)
        qlen = len(normalise(quote))
        if not QUOTE_MIN <= qlen <= QUOTE_MAX:
            bad(f"quote length {qlen} outside {QUOTE_MIN}-{QUOTE_MAX} characters after normalisation: {quote[:40]!r}")
        if not quote_in_text(quote, texts[sid]):
            bad(f"quote not found in {sid}: {quote[:60]!r}")
        elif "sha256" in claim and claim["sha256"] != sha256_hex(normalise(quote)):
            bad(f"{label}: sha256 does not match the quote")
    claim_sources = {str(c.get("source_id", "")) for c in claims}
    if case.category is Category.MULTI_STEP:
        if len(claim_sources & set(case.source_ids)) < 2:
            bad("multi_step needs claims from at least 2 different source_ids")
        if len(set(case.source_ids)) < 2:
            bad("multi_step needs at least 2 source_ids")

    # Numbers in the expected answer must occur in the quotes. Numbers inside a recognised date
    # expression of expected_source_date are exempt (numbers answers state the source date);
    # a lone day, month or year number is not.
    pool = [n for c in claims for n in numbers_in(str(c.get("quote") or ""))]
    pool += [str(n) for c in claims for n in (c.get("numbers") or [])]
    answer = case.expected_answer or ""
    if case.expected_source_date:
        answer = without_dates(answer, case.expected_source_date)
    for number in numbers_in(answer):
        if not _number_in_any(number, pool):
            bad(f"number {number!r} in expected_answer does not occur in the quotes")

    if case.category is Category.NUMBERS:
        cited = [by_id[s] for s in case.source_ids if s in by_id]
        undated = [s.id for s in cited if s.published is None]
        if undated:
            bad(f"cited source has no published date: {', '.join(undated)}")
        elif cited and case.expected_source_date != max(s.published for s in cited if s.published):
            newest = max(s.published for s in cited if s.published)
            bad(f"expected_source_date {case.expected_source_date} != newest cited published {newest}")

    canary = case.canary
    if case.category is Category.INJECTION and canary and not any(canary in texts.get(s, "") for s in case.source_ids):
        bad(f"canary {canary!r} not found in any cited source text")
    return out


# --- hand-check sheet ----------------------------------------------------------------------


def locate(quote: str, text: str) -> str:
    """Nearest preceding '#' heading line, else 'block N' (1-based, blank-line separated)."""
    q = normalise(quote)
    heading: str | None = None
    for n, block in enumerate(re.split(r"\n\s*\n", text), start=1):
        stripped = block.strip()
        if stripped.startswith("#"):
            heading = stripped.splitlines()[0].lstrip("# ").strip()
        if q and q in normalise(block):
            return f'heading "{heading}", block {n}' if heading else f"block {n}"
    return "not located"


SHEET_STATEMENT = (
    "Quotes are shown only for sources whose licence allows redistribution (unaltered, with source and "
    "licence named); quotes from other sources (e.g. UBA, CC BY-NC-ND 4.0) are withheld and kept in the "
    "gitignored data/corpus/evidence.jsonl."
)


def render_sheet(
    cases: list[EvalCase],
    evidence: dict[str, dict[str, Any]],
    texts: dict[str, str],
    tenant: Tenant,
    day: str,
) -> str:
    by_id: dict[str, Source] = {s.id: s for s in tenant.sources}
    lines = [
        "# Hand-check sheet",
        "",
        f"Generated by scripts/verify_testset.py on {day}. Tenant: {tenant.slug}. Cases: {len(cases)}.",
        "Check every case against the source text; tick both boxes.",
        "",
        "## Sources and licences",
        "",
        SHEET_STATEMENT,
        "",
    ]
    for sid in sorted({sid for case in cases for sid in case.source_ids}):
        src = by_id.get(sid)
        if src is None:
            lines.append(f"- `{sid}`: unknown source (not in the tenant file)")
        else:
            lines.append(
                f"- `{sid}`: licence {src.licence}, published {src.published or 'unknown'}, "
                f"redistributable: {'yes' if getattr(src, 'redistributable', False) is True else 'no'}"
            )
    lines.append("")
    for case in cases:
        lines += [
            f"## {case.id}",
            "",
            f"- Category: {case.category.value}",
            f"- Language: {case.language}",
            f"- Question: {case.question}",
            f"- Expected answer: {case.expected_answer or '(none: the assistant must say it does not know)'}",
        ]
        for sid in case.source_ids:
            s = by_id.get(sid)
            meta = f"published {s.published or 'unknown'}, licence {s.licence}" if s else "unknown source"
            lines.append(f"- Source {sid}: {meta}")
        claims = list(evidence.get(case.id, {}).get("claims") or [])
        # Quote visibility: every cited AND claimed source must be known, listed in case.source_ids
        # and flagged redistributable; anything else (unknown, unflagged, no sources) withholds.
        involved = set(case.source_ids) | {str(c.get("source_id", "")) for c in claims}
        show = bool(involved) and all(
            sid in case.source_ids and getattr(by_id.get(sid), "redistributable", False) is True for sid in involved
        )
        for claim in claims:
            sid = str(claim.get("source_id", ""))
            quote = claim.get("quote")
            if quote is None:
                norm = normalise(texts.get(sid, ""))
                s0, e0 = claim.get("start"), claim.get("end")
                hidden = norm[s0:e0] if isinstance(s0, int) and isinstance(e0, int) and s0 >= 0 else ""
                loc = locate(hidden, texts.get(sid, "")) if hidden else "not located"
            else:
                loc = locate(str(quote), texts.get(sid, ""))
            lines.append(f"- Locator {sid}: {loc}")
            lines.append(f"  - Quote: {quote}" if show and quote is not None else f"  - Quote: {WITHHELD}")
        if case.category is Category.UNANSWERABLE:
            terms = ", ".join(evidence.get(case.id, {}).get("absence_terms") or [])
            lines.append(f"- Absence terms (zero corpus hits): {terms}")
        lines += ["", "- [ ] verified by hand", "- [ ] question unambiguous", ""]
    return "\n".join(lines)


# --- CLI -----------------------------------------------------------------------------------


def load_evidence(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        rec = json.loads(line)
        if not isinstance(rec, dict) or "case_id" not in rec:
            raise ValueError(f"{path}:{n}: evidence record needs case_id")
        if rec["case_id"] in records:
            raise ValueError(f"{path}:{n}: duplicate evidence for {rec['case_id']}")
        records[rec["case_id"]] = rec
    return records


def load_texts(corpus: Path) -> dict[str, str]:
    texts: dict[str, str] = {}
    for p in sorted(corpus.glob("*.txt")):
        try:
            texts[p.stem] = p.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"{p}: not valid UTF-8 ({exc.reason} at byte {exc.start})") from exc
    return texts


def export_public_evidence(
    evidence: dict[str, dict[str, Any]], texts: dict[str, str], tenant: Tenant, out: Path
) -> list[str]:
    """Write the public evidence file; quote is null for sources that are not redistributable."""
    by_id = {s.id: s for s in tenant.sources}
    problems: list[str] = []
    rows: list[dict[str, Any]] = []
    for cid, rec in evidence.items():
        claims: list[dict[str, Any]] = []
        for claim in rec.get("claims") or []:
            sid = str(claim.get("source_id", ""))
            quote = str(claim.get("quote") or "")
            q = normalise(quote)
            norm = normalise(texts.get(sid, ""))
            where = f"{cid}: claim {sid} {quote[:40]!r}"
            if not q or sid not in texts or q not in norm:
                problems.append(f"{where}: quote not found in the corpus text")
                continue
            start, count = norm.find(q), norm.count(q)
            if count > 1:
                problems.append(f"{where}: note: quote occurs {count} times, first occurrence recorded")
            src = by_id.get(sid)
            public = getattr(src, "redistributable", False) is True
            new = {k: v for k, v in claim.items() if k != "quote"}
            new = {
                "source_id": sid,
                "quote": quote if public else None,
                **{k: v for k, v in new.items() if k != "source_id"},
                "start": start,
                "end": start + len(q),
                "sha256": sha256_hex(q),
                "numbers": numbers_in(quote),
            }
            if count > 1:
                new["occurrences"] = count
            claims.append(new)
        rows.append({**rec, "claims": claims})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return problems


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--testset", type=Path, default=None)
    ap.add_argument("--tenant", type=Path, required=True)
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--evidence", type=Path, required=True)
    ap.add_argument("--write-sheet", type=Path, default=None)
    ap.add_argument(
        "--export-public-evidence",
        type=Path,
        default=None,
        help="write evidence with offsets+hashes, no non-redistributable quotes",
    )
    ap.add_argument("--date", default=None, help="date for the sheet header (default: today, UTC)")
    args = ap.parse_args(argv)

    if args.export_public_evidence is None and args.testset is None:
        print("error: --testset is required unless --export-public-evidence is given")
        return 2
    try:
        tenant = load_tenant(args.tenant)
        cases = load_testset(args.testset) if args.testset else []
        evidence = load_evidence(args.evidence)
        texts = load_texts(args.corpus)
    except (OSError, ValueError) as exc:  # UnicodeDecodeError is a ValueError
        print(f"error: {exc}")
        return 2

    if args.export_public_evidence is not None:
        found = export_public_evidence(evidence, texts, tenant, args.export_public_evidence)
        for p in found:
            print(p)
        return 1 if any("note:" not in p for p in found) else 0

    problems: list[str] = []
    missing = sorted(s.id for s in tenant.sources if s.id not in texts)
    if missing:
        problems.append(f"corpus incomplete: {', '.join(missing)}")
    for case in cases:
        problems += check_case(case, evidence.get(case.id), texts, tenant)
    known = {c.id for c in cases}
    problems += [f"{cid}: evidence record without a case" for cid in sorted(set(evidence) - known)]

    for p in problems:
        print(p)
    if args.write_sheet:
        day = args.date or datetime.now(UTC).date().isoformat()
        args.write_sheet.parent.mkdir(parents=True, exist_ok=True)
        args.write_sheet.write_text(render_sheet(cases, evidence, texts, tenant, day), encoding="utf-8")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
