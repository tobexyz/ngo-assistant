"""Tests for scripts/build_corpus.py. Small fixtures only; no network, no real data."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import re
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "build_corpus", Path(__file__).resolve().parents[1] / "scripts" / "build_corpus.py"
)
assert _SPEC and _SPEC.loader
bc = importlib.util.module_from_spec(_SPEC)
sys.modules["build_corpus"] = bc
_SPEC.loader.exec_module(bc)

PAGE = """<html><head><title>T</title><style>.x{color:red}</style><script>var secret = 1;</script></head>
<body><header>SITE HEADER</header><nav><a href="/">Menu item</a></nav>
<main><h1>Main  title</h1><p>First   paragraph with &amp; entity &uuml;ber &#8364;5.</p>
<h2>Sub</h2><ul><li>one</li><li>two <b>bold</b></li></ul>
<table><tr><th>Year</th><th>Value</th></tr><tr><td>2020</td><td>42,5</td></tr></table>
<form><input type="text"> FORM TEXT</form><noscript>NOSCRIPT TEXT</noscript>
<svg><text>SVG TEXT</text></svg></main>
<aside>ASIDE TEXT</aside><footer>FOOTER TEXT</footer></body></html>"""

WIKI = """<html><body><div id="siteSub">chrome</div><div id="mw-content-text"><div class="x">
<p>Article <i>body</i> text.</p><div><p>Nested paragraph.</p></div></div></div>
<div id="catlinks">Categories</div></body></html>"""


def convert(html: str, **kw: object) -> str:
    text, _ = bc.html_to_text(html, **kw)  # type: ignore[arg-type]
    return text


def test_nav_script_and_chrome_stripped() -> None:
    text = convert(PAGE)
    for gone in (
        "SITE HEADER",
        "Menu item",
        "secret",
        "color:red",
        "FORM TEXT",
        "NOSCRIPT",
        "SVG TEXT",
        "ASIDE",
        "FOOTER",
    ):
        assert gone not in text


def test_headings_lists_table_and_entities_kept() -> None:
    text = convert(PAGE)
    lines = text.splitlines()
    assert "# Main title" in lines
    assert "## Sub" in lines
    assert "First paragraph with & entity über €5." in lines
    assert "- one" in lines
    assert "- two bold" in lines
    assert "Year | Value" in lines
    assert "2020 | 42,5" in lines


def test_blocks_are_blank_line_separated() -> None:
    assert "# Main title\n\nFirst paragraph" in convert(PAGE)


def test_wikipedia_keeps_only_article_body() -> None:
    text, found = bc.html_to_text(WIKI, root_id="mw-content-text")
    assert found is True
    assert "Article body text." in text and "Nested paragraph." in text
    assert "chrome" not in text and "Categories" not in text


def test_missing_wikipedia_container_reported() -> None:
    text, found = bc.html_to_text("<body><p>Plain</p></body>", root_id="mw-content-text")
    assert found is False and text == ""
    assert bc.html_to_text("<body><p>Plain</p></body>") == ("Plain", True)


def test_pdf_detected_by_magic_bytes() -> None:
    assert bc.detect_kind("bin", b"%PDF-1.7 rest") == "pdf"
    assert bc.detect_kind("bin", b"<html>") == "html"
    assert bc.detect_kind("html", b"<html>") == "html"
    assert bc.detect_kind("pdf", b"%PDF-1.4") == "pdf"


def test_pdf_pages_marked_with_injected_extractor() -> None:
    text = bc.pdf_to_text(b"%PDF-", extract_pdf_text=lambda data: ["alpha", "beta"])
    assert text == "[page 1]\nalpha\n\n[page 2]\nbeta"


def test_pypdf_extracts_from_generated_pdf() -> None:
    pypdf = pytest.importorskip("pypdf", reason="pypdf not installed (extra 'corpus')")
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    assert bc.extract_pdf_text(buf.getvalue()) == [""]


def src(sid: str, url: str, kind: str = "web", lang: str = "en") -> SimpleNamespace:
    return SimpleNamespace(id=sid, url=url, kind=kind, language=lang)


def run_build(
    tmp_path: Path, sources: list[SimpleNamespace], min_chars: int = 5, **kw: object
) -> tuple[int, str, Path]:
    raw, out = tmp_path / "raw", tmp_path / "corpus"
    raw.mkdir(exist_ok=True)
    buf = io.StringIO()
    code = bc.build(sources, raw, out, min_chars, root=tmp_path, out_stream=buf, **kw)  # type: ignore[arg-type]
    return code, buf.getvalue(), out


def test_build_writes_text_and_index(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "a.html").write_text(PAGE, encoding="utf-8")
    code, _, out = run_build(tmp_path, [src("a", "https://x.example/a")])
    assert code == 0
    assert "# Main title" in (out / "a.txt").read_text(encoding="utf-8")
    index = (out / "INDEX.md").read_text(encoding="utf-8")
    assert "| a | en | web |" in index and "Main title" in index


def test_bin_pdf_uses_injected_extractor(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "p.bin").write_bytes(b"%PDF-1.7 fake")
    code, _, out = run_build(
        tmp_path, [src("p", "https://x.example/p", kind="pdf")], extract_pdf_text=lambda d: ["hello world"]
    )
    assert code == 0
    assert "[page 1]\nhello world" in (out / "p.txt").read_text(encoding="utf-8")


def test_thin_output_flagged_exit_1(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "a.html").write_text("<p>tiny</p>", encoding="utf-8")
    code, text, out = run_build(tmp_path, [src("a", "https://x.example/a")], min_chars=500)
    assert code == 1
    assert "THIN" in text and "a" in text
    assert "THIN" in (out / "INDEX.md").read_text(encoding="utf-8")


def test_missing_raw_listed_and_others_processed(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "b.html").write_text(PAGE, encoding="utf-8")
    code, text, out = run_build(tmp_path, [src("a", "https://x.example/a"), src("b", "https://x.example/b")])
    assert code == 1
    assert "FAIL" in text and "a:" in text
    assert (out / "b.txt").exists() and not (out / "a.txt").exists()


def test_wikipedia_source_uses_body_only(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "w.html").write_text(WIKI, encoding="utf-8")
    code, _, out = run_build(tmp_path, [src("w", "https://de.wikipedia.org/wiki/X", lang="de")])
    assert code == 0
    assert "chrome" not in (out / "w.txt").read_text(encoding="utf-8")


def test_wikipedia_fallback_noted_in_index(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "w.html").write_text("<body><p>Whole page</p></body>", encoding="utf-8")
    run_build(tmp_path, [src("w", "https://de.wikipedia.org/wiki/X")], min_chars=1)
    assert "mw-content-text not found" in (tmp_path / "corpus" / "INDEX.md").read_text(encoding="utf-8")


def test_synthetic_copied_unchanged(tmp_path: Path) -> None:
    syn = tmp_path / "data" / "synthetic"
    syn.mkdir(parents=True)
    content = "# Über uns\r\n\r\nText  with   spaces\n".encode()
    (syn / "s.md").write_bytes(content)
    code, _, out = run_build(
        tmp_path, [src("syn-s", "data/synthetic/s.md", kind="synthetic", lang="de")], min_chars=10_000
    )
    assert code == 0  # synthetic sources are exempt from --min-chars
    assert (out / "syn-s.txt").read_bytes() == content


def test_invalid_id_and_path_containment(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    code, text, out = run_build(tmp_path, [src("../evil", "https://x.example/e")])
    assert code == 1 and "invalid source id" in text
    assert not (tmp_path / "evil.txt").exists()
    # synthetic path escaping the root is refused
    (tmp_path.parent / "outside.md").write_text("secret", encoding="utf-8")
    code, text, _ = run_build(tmp_path, [src("syn-x", "../outside.md", kind="synthetic")])
    assert code == 1 and "outside" in text


def test_main_with_tenant_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    tenant = tmp_path / "t.yaml"
    tenant.write_text(
        "slug: t\nname: T\nlanguages: [en]\nsystem_prompt: p\nsources:\n"
        "  - {id: a, title: A, url: 'https://x.example/a', language: en, kind: web, licence: CC BY 4.0,\n"
        "     licence_url: 'https://x.example/l', redistributable: true, checked_on: 2026-10-14}\n",
        encoding="utf-8",
    )
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "a.html").write_text(PAGE, encoding="utf-8")
    (tmp_path / "raw" / "a.meta.json").write_text(json.dumps({"id": "a"}), encoding="utf-8")
    code = bc.main(
        [
            "--tenant",
            str(tenant),
            "--raw",
            str(tmp_path / "raw"),
            "--out",
            str(tmp_path / "c"),
            "--min-chars",
            "10",
            "--root",
            str(tmp_path),
        ]
    )
    assert code == 0
    assert (tmp_path / "c" / "a.txt").exists()


def test_unclosed_table_cells_do_not_fuse() -> None:
    text = convert("<table><tr><td>A<td>B<tr><td>C<td>D</table>")
    assert text.split("\n\n") == ["A | B", "C | D"]


def test_unclosed_th_and_last_row_without_end_tags() -> None:
    text = convert("<table><tr><th>Year<th>Value<tr><td>2020<td>42")
    assert text.split("\n\n") == ["Year | Value", "2020 | 42"]


def test_end_tr_flushes_open_cell_and_buffer() -> None:
    text = convert("<table><tr><td>A<td>B</tr><tr><td>C</tr></table><p>after</p>")
    assert text.split("\n\n") == ["A | B", "C", "after"]


def test_unclosed_p_and_li_stay_separate() -> None:
    assert convert("<p>one<p>two").split("\n\n") == ["one", "two"]
    assert convert("<ul><li>a<li>b</ul>").split("\n\n") == ["- a", "- b"]


def test_header_with_h1_or_p_is_kept_chrome_header_dropped() -> None:
    owid = "<body><header><h1>Biodiversity</h1><p>Intro text.</p></header><p>Body.</p></body>"
    assert convert(owid).split("\n\n") == ["# Biodiversity", "Intro text.", "Body."]
    chrome = "<body><header><div>Logo</div><nav><a>Menu</a></nav><button>Go</button></header><p>Body.</p></body>"
    assert convert(chrome) == "Body."
    mixed = "<body><header><nav><p>Menu para</p></nav><h1>Title</h1></header><p>Body.</p></body>"
    assert convert(mixed).split("\n\n") == ["# Title", "Body."]


def test_nested_chrome_still_dropped_inside_kept_header() -> None:
    html = "<header><nav>MENU</nav><h1>T</h1><form>FORM</form></header><footer>F</footer><aside>A</aside>"
    assert convert(html) == "# T"


# --- PDF ligature repair -------------------------------------------------------------------


def test_ligature_code_points_mapped() -> None:
    text, unresolved = bc.repair_pdf_text("ﬀ ﬁ ﬂ ﬃ ﬄ ﬅ ﬆ")
    assert text == "ff fi fl ffi ffl st st"
    assert unresolved == []


def test_nul_resolved_from_same_document_vocabulary() -> None:
    doc = "A signi\0cant gap. The re\0ect idea, o\0cial text. Also significant, reflect and official."
    text, unresolved = bc.repair_pdf_text(doc)
    assert text.startswith("A significant gap. The reflect idea, official text.")
    assert "\0" not in text and unresolved == []


def test_candidate_order_prefers_fi_then_fl_then_ff() -> None:
    # both "fi" and "fl" spellings exist in the document: the first in order wins
    text, _ = bc.repair_pdf_text("x\0 xfi xfl")
    assert text.startswith("xfi ")


def test_multiple_nul_in_one_token_resolved() -> None:
    text, unresolved = bc.repair_pdf_text("de\0ne and the\0\0 plus define theflfi")
    assert text.startswith("define and theflfi")
    assert unresolved == []


def test_unresolved_falls_back_to_fi_and_is_reported() -> None:
    text, unresolved = bc.repair_pdf_text("zzz\0zzz stays")
    assert text == "zzzfizzz stays"
    assert unresolved == ["zzz\0zzz"]


def test_extra_vocabulary_from_other_documents() -> None:
    text, unresolved = bc.repair_pdf_text("e\0ciency", extra_vocab=frozenset({"efficiency"}))
    assert text == "efficiency" and unresolved == []


def test_nul_without_letters_removed_and_reported() -> None:
    text, unresolved = bc.repair_pdf_text("end\n\0. Next")
    assert text == "end\n. Next"
    assert unresolved == ["\0."]


def test_text_without_nul_unchanged_and_repair_idempotent() -> None:
    plain = "Nothing to fix here, e.g. fi and fl.\n\nüöä"
    assert bc.repair_pdf_text(plain) == (plain, [])
    once, _ = bc.repair_pdf_text("signi\0cant significant ﬁ zz\0z")
    twice, unresolved = bc.repair_pdf_text(once)
    assert twice == once and unresolved == []


def test_repair_is_deterministic() -> None:
    doc = "o\0cial oficial zz\0z re\0ect reflect"
    assert bc.repair_pdf_text(doc) == bc.repair_pdf_text(doc)


def test_build_repairs_pdf_only_and_notes_unresolved(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "p.pdf").write_bytes(b"%PDF-1.7 fake")
    code, _, out = run_build(
        tmp_path,
        [src("p", "https://x.example/p", kind="pdf")],
        extract_pdf_text=lambda d: ["signi\0cant significant zz\0z"],
    )
    assert code == 0
    assert "significant significant zzfiz" in (out / "p.txt").read_text(encoding="utf-8")
    index = (out / "INDEX.md").read_text(encoding="utf-8")
    assert "unresolved ligature" in index and "zz\\x00z" in index


def test_build_uses_vocabulary_of_other_sources(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "a.html").write_text("<p>Energy efficiency matters a great deal</p>", encoding="utf-8")
    (tmp_path / "raw" / "p.pdf").write_bytes(b"%PDF-1.7 fake")
    code, _, out = run_build(
        tmp_path,
        [src("p", "https://x.example/p", kind="pdf"), src("a", "https://x.example/a")],
        extract_pdf_text=lambda d: ["e\0ciency"],
    )
    assert code == 0
    assert "[page 1]\nefficiency" in (out / "p.txt").read_text(encoding="utf-8")


def test_html_with_nul_exits_1_listing_source(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "a.html").write_text("<p>bad \0 byte here</p>", encoding="utf-8")
    code, text, out = run_build(tmp_path, [src("a", "https://x.example/a")])
    assert code == 1
    assert "FAIL a" in text and "NUL" in text
    assert "NUL" in (out / "INDEX.md").read_text(encoding="utf-8")


def test_hyphenated_token_resolved_by_part() -> None:
    text, unresolved = bc.repair_pdf_text("gap-\0lled and gap-filled")
    assert text == "gap-filled and gap-filled" and unresolved == []


# --- kind "file" sources (filesystem crawler, contracts.md "Addendum: Filesystem crawler") -------------
# Interface decisions made here (beyond contracts.md), to be confirmed by the orchestrator:
# - a file source is passed to bc.build as an object with id, url, kind="file", language, path, file_sha256, file_bytes
#   (the tests use SimpleNamespace, like the existing ones);
# - the Office path is tested end to end with small generated files (not by patching names inside build_corpus);
# - a missing file gives status FAIL with a note matching "missing" or "not found";
# - a text file with a NUL byte gives FAIL (the extract_plain_text ExtractError is reported per source).

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
ODF_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"'
)


def fsrc(path: Path, sid: str = "r-file", lang: str = "de", sha: str | None = "auto", **kw: object) -> SimpleNamespace:
    """A crawled source for the existing file `path`; sha256 and size are those of the file right now."""
    data = path.read_bytes() if path.is_file() else b""
    return SimpleNamespace(
        id=sid,
        title=path.stem,
        url=f"file:r/{path.name}",
        kind="file",
        language=lang,
        path=str(path),
        file_sha256=hashlib.sha256(data).hexdigest() if sha == "auto" else sha,
        file_bytes=len(data),
        **kw,
    )


def make_docx(path: Path, paragraphs: list[str]) -> Path:
    body = "".join(f"<w:p><w:r><w:t>{t}</w:t></w:r></w:p>" for t in paragraphs)
    xml = f'<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>{body}</w:body></w:document>'
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", xml)
    return path


def make_odt(path: Path, paragraphs: list[str]) -> Path:
    body = "".join(f"<text:p>{t}</text:p>" for t in paragraphs)
    xml = (f'<?xml version="1.0"?><office:document-content {ODF_NS}><office:body><office:text>{body}'
           "</office:text></office:body></office:document-content>")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        z.writestr("content.xml", xml)
    return path


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    d = tmp_path / "docs"
    d.mkdir()
    return d


@pytest.mark.parametrize("name", ["note.txt", "note.md", "note.markdown", "NOTE.TXT"])
def test_file_source_plain_text_is_converted_unchanged(tmp_path: Path, docs: Path, name: str) -> None:
    content = "# Moorschutz\n\nMoore speichern Kohlenstoff, äöü ß – 42,5 %.\n"
    p = docs / name
    p.write_bytes(content.encode())
    code, text, out = run_build(tmp_path, [fsrc(p, "r-plain")])
    assert code == 0, text
    assert (out / "r-plain.txt").read_text(encoding="utf-8").strip() == content.strip()
    assert "OK" in text and "r-plain" in text


def test_file_source_html_uses_the_html_converter(tmp_path: Path, docs: Path) -> None:
    p = docs / "page.html"
    p.write_text(PAGE, encoding="utf-8")
    code, text, out = run_build(tmp_path, [fsrc(p, "r-page", lang="en")])
    assert code == 0, text
    converted = (out / "r-page.txt").read_text(encoding="utf-8")
    assert "# Main title" in converted and "2020 | 42,5" in converted
    assert "SITE HEADER" not in converted and "secret" not in converted


@pytest.mark.parametrize("ext", ["html", "htm", "HTM"])
def test_file_source_html_extensions_and_meta_charset(tmp_path: Path, docs: Path, ext: str) -> None:
    p = docs / f"latin.{ext}"
    p.write_bytes('<html><head><meta charset="iso-8859-1"></head><body><p>Grüße über Moore</p></body></html>'
                  .encode("iso-8859-1"))
    code, _, out = run_build(tmp_path, [fsrc(p, "r-latin")])
    assert code == 0
    assert "Grüße über Moore" in (out / "r-latin.txt").read_text(encoding="utf-8")


def test_file_source_pdf_uses_the_pdf_path_with_ligature_repair(tmp_path: Path, docs: Path) -> None:
    p = docs / "report.PDF"
    p.write_bytes(b"%PDF-1.7 fake bytes of a report")
    code, text, out = run_build(
        tmp_path, [fsrc(p, "r-pdf")], extract_pdf_text=lambda d: ["signi\0cant significant", "second page"]
    )
    assert code == 0, text
    converted = (out / "r-pdf.txt").read_text(encoding="utf-8")
    assert "[page 1]\nsignificant significant" in converted and "[page 2]\nsecond page" in converted
    assert "\0" not in converted
    assert "pdf" in (out / "INDEX.md").read_text(encoding="utf-8")


def test_file_source_pdf_receives_the_bytes_of_the_file(tmp_path: Path, docs: Path) -> None:
    p = docs / "r.pdf"
    p.write_bytes(b"%PDF-1.7 unique-bytes-xyz")
    seen: list[bytes] = []
    run_build(tmp_path, [fsrc(p, "r-pdf")], extract_pdf_text=lambda d: seen.append(d) or ["text of the pdf"])
    assert seen == [b"%PDF-1.7 unique-bytes-xyz"]


def test_file_source_docx_goes_through_the_office_extractor(tmp_path: Path, docs: Path) -> None:
    p = make_docx(docs / "bericht.docx", ["Unique docx paragraph about Hochmoore.", "Second docx paragraph."])
    code, text, out = run_build(tmp_path, [fsrc(p, "r-docx")])
    assert code == 0, text
    converted = (out / "r-docx.txt").read_text(encoding="utf-8")
    assert "Unique docx paragraph about Hochmoore.\n\nSecond docx paragraph." in converted
    assert "PK" not in converted


def test_file_source_odt_goes_through_the_office_extractor(tmp_path: Path, docs: Path) -> None:
    p = make_odt(docs / "brief.odt", ["Odt paragraph about Niedermoore.", "Another odt paragraph."])
    code, text, out = run_build(tmp_path, [fsrc(p, "r-odt")])
    assert code == 0, text
    assert "Odt paragraph about Niedermoore." in (out / "r-odt.txt").read_text(encoding="utf-8")


def test_file_source_corrupt_office_file_fails_alone_without_leaking_content(tmp_path: Path, docs: Path) -> None:
    bad = docs / "broken.docx"
    bad.write_bytes(b"CORRUPT-MARKER-5521 this is not a zip file at all")
    good = docs / "fine.txt"
    good.write_text("A perfectly fine text file.", encoding="utf-8")
    code, text, out = run_build(tmp_path, [fsrc(bad, "r-bad"), fsrc(good, "r-good")])
    assert code == 1
    assert "FAIL" in text and "r-bad" in text
    assert "CORRUPT-MARKER-5521" not in text and "Traceback" not in text
    assert not (out / "r-bad.txt").exists()
    assert (out / "r-good.txt").exists()


def test_changed_file_fails_with_reason_while_other_sources_proceed(tmp_path: Path, docs: Path) -> None:
    changed = docs / "changed.txt"
    changed.write_text("Original text of the changed file.", encoding="utf-8")
    other = docs / "other.txt"
    other.write_text("Text of the other file stays the same.", encoding="utf-8")
    sources = [fsrc(changed, "r-changed"), fsrc(other, "r-other")]
    changed.write_text("Modified text after the crawl happened.", encoding="utf-8")
    code, text, out = run_build(tmp_path, sources)
    assert code == 1
    assert "FAIL" in text and "r-changed" in text
    assert "file changed since crawl" in text
    assert "re-run crawl" in text
    assert not (out / "r-changed.txt").exists()
    assert (out / "r-other.txt").read_text(encoding="utf-8").strip() == "Text of the other file stays the same."
    index = (out / "INDEX.md").read_text(encoding="utf-8")
    assert "file changed since crawl" in index


def test_file_with_the_same_size_but_other_content_is_detected(tmp_path: Path, docs: Path) -> None:
    p = docs / "same-size.txt"
    p.write_text("aaaaaaaaaa bbbbbbbbbb", encoding="utf-8")
    source = fsrc(p, "r-same")
    p.write_text("bbbbbbbbbb aaaaaaaaaa", encoding="utf-8")
    code, text, _ = run_build(tmp_path, [source])
    assert code == 1 and "file changed since crawl" in text


def test_missing_file_fails(tmp_path: Path, docs: Path) -> None:
    p = docs / "gone.txt"
    p.write_text("exists for the crawl only", encoding="utf-8")
    source = fsrc(p, "r-gone")
    p.unlink()
    other = docs / "stay.txt"
    other.write_text("This one is still there.", encoding="utf-8")
    code, text, out = run_build(tmp_path, [source, fsrc(other, "r-stay")])
    assert code == 1
    assert "FAIL" in text and "r-gone" in text
    assert re.search(r"missing|not found", text)
    assert not (out / "r-gone.txt").exists() and (out / "r-stay.txt").exists()


def test_file_source_without_a_recorded_hash_fails_instead_of_converting(tmp_path: Path, docs: Path) -> None:
    p = docs / "nohash.txt"
    p.write_text("text without a recorded hash", encoding="utf-8")
    code, text, out = run_build(tmp_path, [fsrc(p, "r-nohash", sha=None)])
    assert code == 1 and "FAIL" in text
    assert not (out / "r-nohash.txt").exists()


def test_file_source_needs_no_raw_copy_and_no_meta_file(tmp_path: Path, docs: Path) -> None:
    p = docs / "inplace.txt"
    p.write_text("Read in place, never copied.", encoding="utf-8")
    code, _, out = run_build(tmp_path, [fsrc(p, "r-inplace")])
    assert code == 0
    assert list((tmp_path / "raw").iterdir()) == []
    assert (out / "r-inplace.txt").is_file()
    assert sorted(x.name for x in out.iterdir()) == ["INDEX.md", "r-inplace.txt"]


def test_file_source_row_in_the_index_has_kind_file(tmp_path: Path, docs: Path) -> None:
    p = docs / "indexed.md"
    p.write_text("# Indexed heading\n\nBody text of the indexed file.", encoding="utf-8")
    run_build(tmp_path, [fsrc(p, "r-indexed", lang="en")])
    index = (tmp_path / "corpus" / "INDEX.md").read_text(encoding="utf-8")
    assert "| r-indexed | en | file |" in index and "Indexed heading" in index


def test_nul_in_a_file_source_html_output_fails_as_before(tmp_path: Path, docs: Path) -> None:
    p = docs / "nul.html"
    p.write_bytes(b"<p>bad \x00 byte here</p>")
    code, text, out = run_build(tmp_path, [fsrc(p, "r-nul")])
    assert code == 1
    assert "FAIL r-nul" in text and "NUL" in text
    assert "NUL" in (out / "INDEX.md").read_text(encoding="utf-8")


def test_nul_in_a_plain_text_file_source_fails(tmp_path: Path, docs: Path) -> None:
    p = docs / "nul.txt"
    p.write_bytes(b"first line\x00second line")
    code, text, out = run_build(tmp_path, [fsrc(p, "r-nul")])
    assert code == 1 and "FAIL r-nul" in text
    assert not (out / "r-nul.txt").exists()


def test_thin_file_source_is_flagged_like_any_other(tmp_path: Path, docs: Path) -> None:
    p = docs / "tiny.txt"
    p.write_text("tiny", encoding="utf-8")
    code, text, _ = run_build(tmp_path, [fsrc(p, "r-tiny")], min_chars=500)
    assert code == 1 and "THIN" in text


def test_large_file_source_is_hashed_and_converted(tmp_path: Path, docs: Path) -> None:
    p = docs / "large.txt"
    p.write_text("".join(f"Line number {i} about peat bogs.\n" for i in range(60_000)), encoding="utf-8")
    code, text, out = run_build(tmp_path, [fsrc(p, "r-large")])
    assert code == 0, text
    assert "Line number 59999 about peat bogs." in (out / "r-large.txt").read_text(encoding="utf-8")


def test_file_source_with_unsafe_id_is_refused(tmp_path: Path, docs: Path) -> None:
    p = docs / "x.txt"
    p.write_text("some text", encoding="utf-8")
    code, text, _ = run_build(tmp_path, [fsrc(p, "../evil")])
    assert code == 1 and "invalid source id" in text
    assert not (tmp_path / "evil.txt").exists()


def test_file_source_pointing_at_a_directory_fails(tmp_path: Path, docs: Path) -> None:
    sub = docs / "folder.txt"
    sub.mkdir()
    code, text, _ = run_build(tmp_path, [fsrc(sub, "r-dir", sha="0" * 64)])
    assert code == 1 and "FAIL r-dir" in text


def test_file_sources_and_web_sources_in_one_build(tmp_path: Path, docs: Path) -> None:
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw" / "a.html").write_text(PAGE, encoding="utf-8")
    p = docs / "mine.txt"
    p.write_text("My own file in the same build run.", encoding="utf-8")
    code, text, out = run_build(tmp_path, [src("a", "https://x.example/a"), fsrc(p, "r-mine")])
    assert code == 0, text
    assert (out / "a.txt").exists() and (out / "r-mine.txt").exists()


def test_main_builds_file_sources_from_the_generated_listing(tmp_path: Path, docs: Path) -> None:
    p = docs / "listed.txt"
    p.write_text("Listed in the generated crawl file, converted by main.", encoding="utf-8")
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    listing = tmp_path / "t.crawled.yaml"
    listing.write_text(
        "# GENERATED by ngo-assistant crawl; do not edit; gitignored\nsources:\n"
        f"  - {{id: r-listed, title: listed, url: 'file:r/listed.txt', language: en, kind: file,\n"
        f"     licence: Own work, licence_url: 'internal:declared-by-owner', redistributable: false,\n"
        f"     checked_on: 2026-10-16, path: '{p}', file_sha256: '{sha}', file_bytes: {p.stat().st_size}}}\n",
        encoding="utf-8",
    )
    tenant = tmp_path / "t.yaml"
    tenant.write_text(
        "slug: t\nname: T\nlanguages: [en]\nsystem_prompt: p\n"
        f"crawl:\n  - {{id: r, path: '{docs}', licence: Own work, licence_url: 'internal:declared-by-owner',\n"
        "     checked_on: 2026-10-16}\n"
        f"crawled_sources: '{listing}'\n",
        encoding="utf-8",
    )
    code = bc.main(["--tenant", str(tenant), "--raw", str(tmp_path / "raw"), "--out", str(tmp_path / "c"),
                    "--min-chars", "10", "--root", str(tmp_path)])
    assert code == 0
    assert "converted by main" in (tmp_path / "c" / "r-listed.txt").read_text(encoding="utf-8")
