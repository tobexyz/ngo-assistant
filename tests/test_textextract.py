"""Office and plain-text extraction (contracts.md "Addendum: Filesystem crawler", textextract.py).

Minimal OOXML / ODF files are generated with zipfile and hand-written XML (no sample files, no new dependency).
The tests assert behaviour (extracted text, markers, order, limits), not the exact internals.

Interface decisions made here (beyond contracts.md), to be confirmed by the orchestrator:
- `ext` is passed WITH the leading dot (".docx");
- `ExtractError`, `ExtractLimits`, `extract_office_text`, `extract_plain_text` live in `ngo_assistant.textextract`;
- `ExtractLimits(max_member_bytes, max_total_uncompressed, max_ratio)` are keyword arguments with those names;
- a member exceeding `max_member_bytes`, an archive exceeding `max_total_uncompressed` (sum of the member sizes)
  and a member whose inflate ratio exceeds `max_ratio` all raise ExtractError (decompression is measured while
  reading, not trusted from the header);
- `extract_plain_text` raises ExtractError when the FILE is larger than `max_bytes` (no silent truncation);
- more than 20000 spreadsheet cells and ODF repeated cells with text are either capped or raise ExtractError;
  the tests accept both, but never a result with more than 20000 cells / a huge output;
- a DOCTYPE/entity declaration either raises ExtractError or is parsed without resolving external entities;
  the tests accept both and only forbid that the external content shows up;
- xlsx sheets are mapped through `xl/_rels/workbook.xml.rels` (rId -> worksheet part), not by file number;
- pptx speaker notes are found through the slide's relationship file and appear after the slide's text as a
  line starting with `Notes:`;
- the heading line for docx styles whose NAME (in word/styles.xml) is heading/title/titel/Ueberschrift starts with
  `# ` (the level is not asserted beyond a leading `#` for levels above 1); non-heading styles never get a `#`;
  without word/styles.xml a pStyle id that is not itself a heading name gives no heading;
- pptx markers are lines `[slide N]` where N is not asserted (position or file number): the tests only count the
  markers and check the order of the slide texts;
- ODF repeat attributes are capped at 10 (test: 1 <= copies <= 10), non-integer repeat counts count as 1;
- a lying zip header is tested by forging the uncompressed size of the central directory and the local header
  to a small value; any ExtractError is accepted (truncated read, CRC or XML error);
- a duplicate member name is created with zipfile (which warns) and must raise ExtractError.

Fixtures follow docs/tech.md sections 19-23 and the verified samples of task 7.1.
"""

from __future__ import annotations

import os
import random
import re
import warnings
import zipfile
from pathlib import Path

import pytest

from ngo_assistant.textextract import ExtractError, ExtractLimits, extract_office_text, extract_plain_text

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
P = "http://schemas.openxmlformats.org/presentationml/2006/main"
S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
ODF_NS = (
    'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
    'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
    'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
    'xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"'
)
MARKER = "SECRET-MARKER-7f3a91"


def make_zip(path: Path, members: dict[str, str | bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in members.items():
            z.writestr(name, data)
    return path


def lines(text: str) -> list[str]:
    return text.splitlines()


# ----------------------------------------------------------------------------- builders


STYLES = {  # styleId -> w:name, as Word writes them
    "Heading1": "heading 1", "Heading2": "heading 2", "Title": "Title", "Titel": "Titel",
    "Ueb1": "Überschrift 1", "Ueb2": "überschrift 2", "BodyText": "Body Text", "ListParagraph": "List Paragraph",
}


def styles_xml(styles: dict[str, str]) -> str:
    items = "".join(f'<w:style w:type="paragraph" w:styleId="{i}"><w:name w:val="{n}"/></w:style>'
                    for i, n in styles.items())
    return f'<?xml version="1.0" encoding="UTF-8"?><w:styles xmlns:w="{W}">{items}</w:styles>'


def docx(tmp_path: Path, body: str, name: str = "t.docx", extra: dict | None = None,
         styles: dict[str, str] | None = STYLES) -> Path:
    xml = f'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="{W}"><w:body>{body}</w:body></w:document>'
    members: dict[str, str | bytes] = {"[Content_Types].xml": "<Types/>", "word/document.xml": xml}
    if styles is not None:
        members["word/styles.xml"] = styles_xml(styles)
    return make_zip(tmp_path / name, {**members, **(extra or {})})


def wp(text: str, style: str | None = None) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}<w:r><w:t>{text}</w:t></w:r></w:p>"


def pptx_slide(*paragraphs: str) -> str:
    ps = "".join(f"<a:p><a:r><a:t>{t}</a:t></a:r></a:p>" for t in paragraphs)
    return (f'<p:sld xmlns:a="{A}" xmlns:p="{P}" xmlns:r="{R}"><p:cSld><p:spTree><p:sp><p:txBody><a:bodyPr/>'
            f"{ps}</p:txBody></p:sp></p:spTree></p:cSld></p:sld>")


def pptx_notes(*paragraphs: str) -> str:
    ps = "".join(f"<a:p><a:r><a:t>{t}</a:t></a:r></a:p>" for t in paragraphs)
    return (f'<p:notes xmlns:a="{A}" xmlns:p="{P}"><p:cSld><p:spTree><p:sp><p:txBody><a:bodyPr/>'
            f"{ps}</p:txBody></p:sp></p:spTree></p:cSld></p:notes>")


def slide_rels(n: int) -> str:
    return (f'<Relationships xmlns="{PKG_REL}"><Relationship Id="rId1" Type="{R}/notesSlide" '
            f'Target="../notesSlides/notesSlide{n}.xml"/></Relationships>')


def odf(tmp_path: Path, name: str, mimetype: str, body: str, root: str) -> Path:
    content = (f'<?xml version="1.0" encoding="UTF-8"?><office:document-content {ODF_NS}><office:body>'
               f"<office:{root}>{body}</office:{root}></office:body></office:document-content>")
    return make_zip(tmp_path / name, {"mimetype": mimetype, "content.xml": content})


def odt(tmp_path: Path, body: str) -> Path:
    return odf(tmp_path, "t.odt", "application/vnd.oasis.opendocument.text", body, "text")


def ods(tmp_path: Path, body: str) -> Path:
    return odf(tmp_path, "t.ods", "application/vnd.oasis.opendocument.spreadsheet", body, "spreadsheet")


def odp(tmp_path: Path, body: str) -> Path:
    return odf(tmp_path, "t.odp", "application/vnd.oasis.opendocument.presentation", body, "presentation")


def ocell(text: str, repeat: int | None = None) -> str:
    rep = f' table:number-columns-repeated="{repeat}"' if repeat else ""
    inner = f"<text:p>{text}</text:p>" if text else ""
    return f'<table:table-cell office:value-type="string"{rep}>{inner}</table:table-cell>'


def orow(*cells: str, repeat: int | None = None) -> str:
    rep = f' table:number-rows-repeated="{repeat}"' if repeat else ""
    return f"<table:table-row{rep}>{''.join(cells)}</table:table-row>"


def xlsx(tmp_path: Path, sheets: list[tuple[str, str]], shared: list[str] | None = None) -> Path:
    """sheets: (name, sheetData xml). The workbook order is the list order; the parts are numbered in REVERSE
    so that a reader taking sheetN.xml in file order gets the wrong sheet."""
    n = len(sheets)
    members: dict[str, str | bytes] = {"[Content_Types].xml": "<Types/>"}
    wb_sheets, rels = "", ""
    for i, (name, data) in enumerate(sheets):
        part = n - i
        wb_sheets += f'<sheet name="{name}" sheetId="{i + 1}" r:id="rId{i + 1}"/>'
        rels += (f'<Relationship Id="rId{i + 1}" Type="{R}/worksheet" Target="worksheets/sheet{part}.xml"/>')
        members[f"xl/worksheets/sheet{part}.xml"] = (
            f'<worksheet xmlns="{S}"><sheetData>{data}</sheetData></worksheet>')
    members["xl/workbook.xml"] = f'<workbook xmlns="{S}" xmlns:r="{R}"><sheets>{wb_sheets}</sheets></workbook>'
    members["xl/_rels/workbook.xml.rels"] = f'<Relationships xmlns="{PKG_REL}">{rels}</Relationships>'
    if shared is not None:
        si = "".join(f"<si><t>{s}</t></si>" for s in shared)
        members["xl/sharedStrings.xml"] = f'<sst xmlns="{S}">{si}</sst>'
    return make_zip(tmp_path / "t.xlsx", members)


# ----------------------------------------------------------------------------- docx


def test_docx_paragraphs_headings_and_blank_line_separation(tmp_path):
    body = (wp("Jahresbericht Moore", "Heading1") + wp("Erster Absatz mit Umlauten äöü.")
            + wp("Zweiter Absatz.", "BodyText"))
    text = extract_office_text(docx(tmp_path, body), ".docx")
    assert text.strip() == "# Jahresbericht Moore\n\nErster Absatz mit Umlauten äöü.\n\nZweiter Absatz."


@pytest.mark.parametrize("style", ["Heading1", "Heading2", "Title", "Titel", "Ueb1", "Ueb2"])
def test_docx_heading_styles_are_found_through_the_style_names(tmp_path, style):
    text = extract_office_text(docx(tmp_path, wp("Kapitel A", style) + wp("body text")), ".docx")
    heading = [ln for ln in lines(text) if "Kapitel A" in ln]
    assert len(heading) == 1 and heading[0].startswith("#") and heading[0].endswith(" Kapitel A")
    assert "body text" in lines(text)


def test_docx_german_style_name_ueberschrift_gives_a_heading_although_the_id_is_opaque(tmp_path):
    text = extract_office_text(docx(tmp_path, wp("Deutsches Kapitel", "Ueb1")), ".docx")
    assert "# Deutsches Kapitel" in lines(text)


def test_docx_style_id_is_resolved_through_its_name_not_its_id(tmp_path):
    styles = {"Custom1": "heading 3", "Heading1": "Normal Text"}  # the id Heading1 is NOT a heading here
    body = wp("By name", "Custom1") + wp("By id only", "Heading1")
    ls = lines(extract_office_text(docx(tmp_path, body, styles=styles), ".docx"))
    assert any(ln.startswith("#") and ln.endswith("By name") for ln in ls)
    assert "By id only" in ls


def test_docx_without_styles_xml_has_no_headings_and_no_error(tmp_path):
    body = wp("Opaque style text", "Ueb1") + wp("Other text")
    text = extract_office_text(docx(tmp_path, body, styles=None), ".docx")
    assert "#" not in text
    assert "Opaque style text" in lines(text) and "Other text" in lines(text)


def test_docx_first_level_heading_is_exactly_hash_space(tmp_path):
    assert "# Wasser" in lines(extract_office_text(docx(tmp_path, wp("Wasser", "Heading1")), ".docx"))


def test_docx_non_heading_style_gets_no_hash(tmp_path):
    text = extract_office_text(docx(tmp_path, wp("Plain words", "ListParagraph") + wp("Headless")), ".docx")
    assert "#" not in text and "Plain words" in text


def test_docx_runs_are_concatenated_tabs_and_breaks_converted(tmp_path):
    body = ("<w:p><w:r><w:t>Hel</w:t></w:r><w:r><w:t>lo</w:t></w:r><w:r><w:tab/></w:r><w:r><w:t>tabbed</w:t></w:r>"
            "<w:r><w:br/></w:r><w:r><w:t>next line</w:t></w:r></w:p>")
    text = extract_office_text(docx(tmp_path, body), ".docx")
    assert "Hello\ttabbed\nnext line" in text


def test_docx_table_rows_are_joined_with_pipes(tmp_path):
    def cell(t):
        return f"<w:tc>{wp(t)}</w:tc>"

    tbl = ("<w:tbl><w:tr>" + cell("Jahr") + cell("Wert") + "</w:tr><w:tr>" + cell("2020") + cell("42,5")
           + "</w:tr></w:tbl>")
    text = extract_office_text(docx(tmp_path, wp("Vor der Tabelle") + tbl + wp("Nach der Tabelle")), ".docx")
    rows = lines(text)
    assert "Jahr | Wert" in rows and "2020 | 42,5" in rows
    assert text.index("Vor der Tabelle") < text.index("Jahr | Wert") < text.index("2020 | 42,5") \
        < text.index("Nach der Tabelle")


def test_docx_table_cell_paragraphs_are_not_repeated_as_separate_paragraphs(tmp_path):
    def cell(t):
        return f"<w:tc>{wp(t)}</w:tc>"

    tbl = "<w:tbl><w:tr>" + cell("Zelle-Eins") + cell("Zelle-Zwei") + "</w:tr></w:tbl>"
    text = extract_office_text(docx(tmp_path, wp("Absatz davor") + tbl + wp("Absatz danach")), ".docx")
    assert text.count("Zelle-Eins") == 1 and text.count("Zelle-Zwei") == 1
    assert "Zelle-Eins" not in lines(text) and "Zelle-Zwei" not in lines(text)
    assert text.count("Absatz davor") == 1 and text.count("Absatz danach") == 1


def test_docx_table_with_multi_paragraph_cell_and_empty_cell(tmp_path):
    cell1 = f"<w:tc>{wp('erste Zeile')}{wp('zweite Zeile')}</w:tc>"
    tbl = f"<w:tbl><w:tr>{cell1}<w:tc>{wp('rechts')}</w:tc></w:tr></w:tbl>"
    text = extract_office_text(docx(tmp_path, tbl), ".docx")
    assert text.count("erste Zeile") == 1 and text.count("zweite Zeile") == 1 and text.count("rechts") == 1
    assert text.index("erste Zeile") < text.index("zweite Zeile") < text.index("rechts")


def test_docx_special_characters_are_unescaped(tmp_path):
    text = extract_office_text(docx(tmp_path, wp("Fish &amp; Chips &lt;3 &#8364;5")), ".docx")
    assert "Fish & Chips <3 €5" in text


def test_extraction_writes_nothing_to_disk(tmp_path):
    path = docx(tmp_path, wp("some text"))
    before = sorted(os.listdir(tmp_path))
    extract_office_text(path, ".docx")
    assert sorted(os.listdir(tmp_path)) == before


def test_docx_without_main_part_raises(tmp_path):
    path = make_zip(tmp_path / "t.docx", {"[Content_Types].xml": "<Types/>", "word/other.xml": "<x/>"})
    with pytest.raises(ExtractError):
        extract_office_text(path, ".docx")


# ----------------------------------------------------------------------------- pptx


def presentation_parts(order: list[int], rid_offset: int = 100) -> dict[str, str]:
    """presentation.xml listing the slides in `order` (by file number) and the matching .rels."""
    ids = "".join(f'<p:sldId id="{256 + i}" r:id="rId{rid_offset + n}"/>' for i, n in enumerate(order))
    rels = "".join(f'<Relationship Id="rId{rid_offset + n}" Type="{R}/slide" Target="slides/slide{n}.xml"/>'
                   for n in order)
    return {
        "ppt/presentation.xml": f'<p:presentation xmlns:p="{P}" xmlns:r="{R}"><p:sldIdLst>{ids}</p:sldIdLst>'
                                "</p:presentation>",
        "ppt/_rels/presentation.xml.rels": f'<Relationships xmlns="{PKG_REL}">{rels}</Relationships>',
    }


def build_pptx(tmp_path: Path, with_presentation: bool = False) -> Path:
    members: dict[str, str | bytes] = {"[Content_Types].xml": "<Types/>"}
    # written in an order that is neither numeric nor the natural zip order
    for n, paras in ((10, ["Tenth slide title"]), (2, ["Second slide title", "Second bullet"]),
                     (9, ["Ninth slide title"]), (1, ["First slide title", "Bullet one", "Bullet two"])):
        members[f"ppt/slides/slide{n}.xml"] = pptx_slide(*paras)
    members["ppt/slides/_rels/slide2.xml.rels"] = slide_rels(7)  # the notes part number differs from the slide number
    members["ppt/notesSlides/notesSlide7.xml"] = pptx_notes("Remember to mention the budget")
    if with_presentation:
        members.update(presentation_parts([1, 2, 9, 10]))
    return make_zip(tmp_path / "t.pptx", members)


def slide_markers(text: str) -> list[str]:
    return [ln for ln in lines(text) if re.fullmatch(r"\[slide \d+\]", ln)]


def test_pptx_without_presentation_xml_falls_back_to_numeric_order(tmp_path):
    text = extract_office_text(build_pptx(tmp_path), ".pptx")
    assert len(slide_markers(text)) == 4
    positions = [text.index(t) for t in ("First slide title", "Second slide title", "Ninth slide title",
                                          "Tenth slide title")]
    assert positions == sorted(positions)  # slide10 follows slide9, not slide1


def test_pptx_order_follows_sldidlst_and_not_the_file_numbers(tmp_path):
    members: dict[str, str | bytes] = {"[Content_Types].xml": "<Types/>"}
    for n in (1, 2, 3):
        members[f"ppt/slides/slide{n}.xml"] = pptx_slide(f"Text of file {n}")
    members.update(presentation_parts([3, 1, 2]))
    text = extract_office_text(make_zip(tmp_path / "t.pptx", members), ".pptx")
    assert len(slide_markers(text)) == 3
    assert text.index("Text of file 3") < text.index("Text of file 1") < text.index("Text of file 2")


def test_pptx_with_unreadable_presentation_xml_falls_back_to_numeric_order(tmp_path):
    members: dict[str, str | bytes] = {"[Content_Types].xml": "<Types/>"}
    for n in (10, 9, 2):
        members[f"ppt/slides/slide{n}.xml"] = pptx_slide(f"Text of file {n}")
    members["ppt/presentation.xml"] = "<p:presentation><unclosed>"
    members["ppt/_rels/presentation.xml.rels"] = "not xml at all"
    text = extract_office_text(make_zip(tmp_path / "t.pptx", members), ".pptx")
    assert text.index("Text of file 2") < text.index("Text of file 9") < text.index("Text of file 10")


def test_pptx_text_per_paragraph_stays_with_its_slide(tmp_path):
    text = extract_office_text(build_pptx(tmp_path), ".pptx")
    first = text[text.index("First slide title"):text.index("Second slide title")]
    assert "Bullet one" in first.splitlines() and "Bullet two" in first.splitlines()
    assert "Second bullet" not in first


def test_pptx_speaker_notes_are_found_through_the_slide_rels(tmp_path):
    for with_pres in (False, True):
        text = extract_office_text(build_pptx(tmp_path, with_presentation=with_pres), ".pptx")
        second = text[text.index("Second slide title"):text.index("Ninth slide title")]
        assert re.search(r"^Notes:\s*Remember to mention the budget", second, re.M)
        assert second.index("Second bullet") < second.index("Notes:")
        assert text.count("Notes:") == 1


def test_pptx_notes_fall_back_to_the_part_with_the_same_number(tmp_path):
    members: dict[str, str | bytes] = {"[Content_Types].xml": "<Types/>"}
    members["ppt/slides/slide1.xml"] = pptx_slide("Slide without rels")
    members["ppt/notesSlides/notesSlide1.xml"] = pptx_notes("Note matched by number")
    members["ppt/slides/slide2.xml"] = pptx_slide("Slide without any notes")
    text = extract_office_text(make_zip(tmp_path / "t.pptx", members), ".pptx")
    assert re.search(r"^Notes:\s*Note matched by number", text, re.M)
    assert text.index("Slide without rels") < text.index("Notes:") < text.index("Slide without any notes")


# ----------------------------------------------------------------------------- xlsx


def srow(r: int, *cells: str) -> str:
    return f'<row r="{r}">{"".join(cells)}</row>'


def test_xlsx_sheets_in_workbook_order_with_headings_and_rows(tmp_path):
    first = (srow(1, '<c r="A1" t="s"><v>0</v></c>', '<c r="B1" t="s"><v>1</v></c>')
             + srow(2, '<c r="A2" t="s"><v>2</v></c>', '<c r="B2"><v>42.5</v></c>'))
    second = srow(1, '<c r="A1" t="inlineStr"><is><t>inline value</t></is></c>', '<c r="B1"><v>7</v></c>')
    path = xlsx(tmp_path, [("Budget", first), ("Data 2", second)], shared=["Posten", "Betrag", "Moorschutz"])
    text = extract_office_text(path, ".xlsx")
    ls = lines(text)
    assert "## Budget" in ls and "## Data 2" in ls
    assert ls.index("## Budget") < ls.index("## Data 2")
    assert "Posten | Betrag" in ls and "Moorschutz | 42.5" in ls
    assert "inline value | 7" in ls
    assert ls.index("Moorschutz | 42.5") < ls.index("## Data 2") < ls.index("inline value | 7")


def test_xlsx_rich_text_shared_string_and_formula_cached_value(tmp_path):
    sheet = srow(1, '<c r="A1" t="s"><v>0</v></c>', '<c r="B1"><f>SUM(1,2)*1000</f><v>3000</v></c>')
    path = xlsx(tmp_path, [("S", sheet)])
    with zipfile.ZipFile(path, "a") as z:
        z.writestr("xl/sharedStrings.xml",
                   f'<sst xmlns="{S}"><si><r><t>Rich </t></r><r><t>text</t></r></si></sst>')
    text = extract_office_text(path, ".xlsx")
    assert "Rich text | 3000" in lines(text)
    assert "SUM" not in text


def test_xlsx_all_cell_types(tmp_path):
    sheet = srow(1,
                 '<c r="A1" t="s"><v>0</v></c>',
                 '<c r="B1" t="inlineStr"><is><t>inline</t></is></c>',
                 '<c r="C1" t="str"><f>A1&amp;"x"</f><v>cached formula str</v></c>',
                 '<c r="D1" t="b"><v>1</v></c>',
                 '<c r="E1" t="b"><v>0</v></c>',
                 '<c r="F1"><v>42.5</v></c>',
                 '<c r="G1" s="1"><v>45000</v></c>',
                 '<c r="H1" t="e"><v>#DIV/0!</v></c>',
                 '<c r="I1" t="n"><v>007</v></c>',
                 '<c r="J1" t="d"><v>2026-10-16T00:00:00</v></c>')
    text = extract_office_text(xlsx(tmp_path, [("Data", sheet)], shared=["shared text"]), ".xlsx")
    assert ("shared text | inline | cached formula str | TRUE | FALSE | 42.5 | 45000 | #DIV/0! | 007 "
            "| 2026-10-16T00:00:00") in lines(text)


def test_xlsx_empty_cells_are_skipped(tmp_path):
    sheet = srow(1, '<c r="A1"><v>1</v></c>', '<c r="B1"/>', '<c r="C1" t="inlineStr"><is><t></t></is></c>',
                 '<c r="D1"><v>4</v></c>') + srow(2, '<c r="A2"/>')
    text = extract_office_text(xlsx(tmp_path, [("S", sheet)]), ".xlsx")
    assert "1 | 4" in lines(text)
    assert "| |" not in text


def test_xlsx_cell_cap_ends_the_text_with_a_truncation_line(tmp_path):
    rows = "".join(srow(r, *[f'<c r="A{r}"><v>{r * 100 + c}</v></c>' for c in range(10)]) for r in range(1, 2601))
    path = xlsx(tmp_path, [("Big", rows)])
    text = extract_office_text(path, ".xlsx")
    assert lines(text.rstrip())[-1] == "[truncated: cell limit]"
    values = re.findall(r"\b\d{3,6}\b", text)
    assert 19000 < len(values) <= 20000


def test_xlsx_below_the_cell_cap_has_no_truncation_line(tmp_path):
    rows = "".join(srow(r, '<c r="A1"><v>1</v></c>', '<c r="B1"><v>2</v></c>') for r in range(1, 50))
    assert "truncated" not in extract_office_text(xlsx(tmp_path, [("S", rows)]), ".xlsx")


# ----------------------------------------------------------------------------- ODF


def test_odt_headings_paragraphs_spans_and_tables(tmp_path):
    body = ('<text:h text:outline-level="1">Moorbericht</text:h>'
            "<text:p>Erster <text:span>fetter</text:span> Absatz.</text:p>"
            '<text:h text:outline-level="2">Unterkapitel</text:h>'
            "<text:p>Zweiter Absatz.</text:p>"
            "<table:table><table:table-row>" + ocell("Jahr") + ocell("Wert") + "</table:table-row>"
            "<table:table-row>" + ocell("2020") + ocell("42,5") + "</table:table-row></table:table>")
    text = extract_office_text(odt(tmp_path, body), ".odt")
    ls = lines(text)
    assert "# Moorbericht" in ls
    assert any(ln.startswith("#") and ln.endswith("Unterkapitel") for ln in ls)
    assert "Erster fetter Absatz." in ls
    assert "Jahr | Wert" in ls and "2020 | 42,5" in ls
    assert text.index("Moorbericht") < text.index("Zweiter Absatz.") < text.index("Jahr | Wert")


def test_odt_blocks_are_separated_by_blank_lines(tmp_path):
    body = "<text:p>one block</text:p><text:p>another block</text:p>"
    assert extract_office_text(odt(tmp_path, body), ".odt").strip() == "one block\n\nanother block"


def test_ods_rows_and_cells(tmp_path):
    body = ('<table:table table:name="Sheet One">' + orow(ocell("Name"), ocell("Fläche")) + orow(ocell("Moor A"),
            ocell("12,5")) + "</table:table>")
    text = extract_office_text(ods(tmp_path, body), ".ods")
    assert "Name | Fläche" in lines(text) and "Moor A | 12,5" in lines(text)


def test_ods_trailing_empty_repeated_cells_and_rows_do_not_explode(tmp_path):
    body = ('<table:table table:name="S">' + orow(ocell("A"), ocell("B"), ocell("", repeat=1048576))
            + orow(ocell("", repeat=1048576), repeat=1048576) + orow(ocell("C"), ocell("D")) + "</table:table>")
    text = extract_office_text(ods(tmp_path, body), ".ods")
    assert "A | B" in lines(text) and "C | D" in lines(text)
    assert len(text) < 1_000


def test_ods_repeated_cell_with_text_is_capped_at_ten(tmp_path):
    body = '<table:table table:name="S">' + orow(ocell("A"), ocell("rep", repeat=1_000_000)) + "</table:table>"
    text = extract_office_text(ods(tmp_path, body), ".ods")
    assert 1 <= text.count("rep") <= 10
    assert "A" in text


def test_ods_repeated_rows_with_text_are_capped_at_ten(tmp_path):
    body = '<table:table table:name="S">' + orow(ocell("rowtext"), repeat=1_000_000) + "</table:table>"
    text = extract_office_text(ods(tmp_path, body), ".ods")
    assert 1 <= text.count("rowtext") <= 10


def test_ods_small_repeat_counts_are_honoured(tmp_path):
    body = '<table:table table:name="S">' + orow(ocell("x", repeat=3)) + "</table:table>"
    assert extract_office_text(ods(tmp_path, body), ".ods").count("x") == 3


@pytest.mark.parametrize("bad", ["abc", "", "-5", "1e9", "0x10", "3.5"])
def test_ods_non_integer_repeat_counts_are_treated_as_one(tmp_path, bad):
    cell = ('<table:table-cell office:value-type="string" '
            f'table:number-columns-repeated="{bad}"><text:p>once</text:p></table:table-cell>')
    row = f'<table:table-row table:number-rows-repeated="{bad}">{cell}</table:table-row>'
    body = f'<table:table table:name="S">{row}</table:table>'
    assert extract_office_text(ods(tmp_path, body), ".ods").count("once") == 1


def test_odf_text_s_tab_line_break_and_tails(tmp_path):
    body = ('<text:p>Para <text:s text:c="2"/>with<text:tab/>tab<text:line-break/>next'
            '<text:span>span</text:span>tail<text:s/>end</text:p>')
    text = extract_office_text(odt(tmp_path, body), ".odt")
    assert "Para   with\ttab\nnextspantail end" in text


def test_odf_text_s_count_is_capped_at_100(tmp_path):
    body = '<text:p>left<text:s text:c="1000000"/>right</text:p>'
    text = extract_office_text(odt(tmp_path, body), ".odt")
    assert text.startswith("left") and "right" in text
    gap = text.index("right") - len("left")
    assert 1 <= gap <= 100


def test_odf_text_s_with_a_bad_count_is_one_space(tmp_path):
    body = '<text:p>a<text:s text:c="many"/>b</text:p>'
    assert "a b" in extract_office_text(odt(tmp_path, body), ".odt")


def test_odp_text_of_all_pages_in_order(tmp_path):
    def page(name, *paras):
        ps = "".join(f"<text:p>{t}</text:p>" for t in paras)
        return (f'<draw:page draw:name="{name}"><draw:frame><draw:text-box>{ps}</draw:text-box></draw:frame>'
                "</draw:page>")

    body = page("page1", "Opening title", "Opening bullet") + page("page2", "Closing title")
    text = extract_office_text(odp(tmp_path, body), ".odp")
    assert "Opening title" in lines(text) and "Opening bullet" in lines(text) and "Closing title" in lines(text)
    assert text.index("Opening title") < text.index("Closing title")


def test_odf_without_content_xml_raises(tmp_path):
    path = make_zip(tmp_path / "t.odt", {"mimetype": "application/vnd.oasis.opendocument.text", "meta.xml": "<m/>"})
    with pytest.raises(ExtractError):
        extract_office_text(path, ".odt")


# ----------------------------------------------------------------------------- limits and hostile input


def test_default_limits():
    d = ExtractLimits()
    assert (d.max_member_bytes, d.max_total_uncompressed, d.max_ratio) == (52428800, 209715200, 200)


def test_zip_bomb_by_ratio_with_default_limits_raises(tmp_path):
    path = docx(tmp_path, wp("A" * (12 * 1024 * 1024)))  # 12 MB of one letter deflates about 1000:1
    with zipfile.ZipFile(path) as z:
        info = z.getinfo("word/document.xml")
        assert info.file_size / max(info.compress_size, 1) > 200
    with pytest.raises(ExtractError):
        extract_office_text(path, ".docx")


def test_member_larger_than_max_member_bytes_raises_even_with_a_modest_ratio(tmp_path):
    filler = "".join(f"{i:06d} " for i in range(5000))  # about 35 KB, hard to compress
    path = docx(tmp_path, wp(filler))
    with pytest.raises(ExtractError):
        extract_office_text(path, ".docx", ExtractLimits(max_member_bytes=10_000, max_ratio=10**9))
    assert filler[:20] in extract_office_text(path, ".docx", ExtractLimits(max_member_bytes=10**6, max_ratio=10**9))


def test_total_uncompressed_size_over_the_limit_raises(tmp_path):
    filler = "".join(f"{i:05d}," for i in range(700))  # 4200 bytes per member
    path = docx(tmp_path, wp(filler), extra={"word/media.bin": filler})
    limits = ExtractLimits(max_member_bytes=10**6, max_total_uncompressed=5_000, max_ratio=10**9)
    with pytest.raises(ExtractError):
        extract_office_text(path, ".docx", limits)
    ok = ExtractLimits(max_member_bytes=10**6, max_total_uncompressed=10**6, max_ratio=10**9)
    assert "00000,00001" in extract_office_text(path, ".docx", ok)


def test_ratio_limit_is_configurable(tmp_path):
    path = docx(tmp_path, wp("B" * 200_000))
    with pytest.raises(ExtractError):
        extract_office_text(path, ".docx", ExtractLimits(max_ratio=5))
    assert "B" * 100 in extract_office_text(path, ".docx", ExtractLimits(max_ratio=10**6))


def set_encrypted_flag(path: Path) -> None:
    """Sets general purpose bit 0 in every local file header and central directory entry."""
    data = bytearray(path.read_bytes())
    for sig, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        pos = data.find(sig)
        while pos != -1:
            data[pos + offset] |= 0x01
            pos = data.find(sig, pos + 4)
    path.write_bytes(bytes(data))


def test_encrypted_flag_raises(tmp_path):
    path = docx(tmp_path, wp("would be ciphertext"), name="enc.docx")
    set_encrypted_flag(path)
    with zipfile.ZipFile(path) as z:
        assert all(i.flag_bits & 0x1 for i in z.infolist())  # the fixture really carries the flag
    with pytest.raises(ExtractError) as info:
        extract_office_text(path, ".docx")
    assert not isinstance(info.value, RuntimeError)


def test_encrypted_member_runtime_error_is_converted(tmp_path, monkeypatch):
    path = docx(tmp_path, wp("text"), name="rt.docx")

    def refuse(self, *a, **k):
        raise RuntimeError("File 'word/document.xml' is encrypted, password required for extraction")

    monkeypatch.setattr(zipfile.ZipFile, "open", refuse)
    monkeypatch.setattr(zipfile.ZipFile, "read", refuse)
    with pytest.raises(ExtractError):
        extract_office_text(path, ".docx")


def test_zip_bomb_of_nul_bytes_at_the_member_limit_is_stopped_by_the_ratio(tmp_path):
    path = make_zip(tmp_path / "t.docx", {"word/document.xml": bytes(50 * 1024 * 1024)})
    with pytest.raises(ExtractError):
        extract_office_text(path, ".docx")


def test_duplicate_member_names_are_rejected(tmp_path):
    path = tmp_path / "dup.docx"
    xml = f'<w:document xmlns:w="{W}"><w:body>{wp("first copy")}</w:body></w:document>'
    evil = f'<w:document xmlns:w="{W}"><w:body>{wp("second copy")}</w:body></w:document>'
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("word/document.xml", xml)
            z.writestr("word/document.xml", evil)
    with pytest.raises(ExtractError):
        extract_office_text(path, ".docx")


def test_bad_crc_raises_extract_error(tmp_path):
    path = tmp_path / "crc.docx"
    xml = f'<w:document xmlns:w="{W}"><w:body>{wp("ZZZUNIQUEMARK content")}</w:body></w:document>'
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        z.writestr("word/document.xml", xml)
    raw = path.read_bytes()
    assert b"ZZZUNIQUEMARK" in raw
    path.write_bytes(raw.replace(b"ZZZUNIQUEMARK", b"ZZZUNIQUEMARX"))  # still well-formed XML, wrong CRC
    with pytest.raises(ExtractError) as info:
        extract_office_text(path, ".docx")
    assert "ZZZUNIQUE" not in str(info.value)


def test_lying_header_cannot_bypass_the_member_limit(tmp_path):
    path = tmp_path / "lie.docx"
    filler = "".join(f"{i:06d} " for i in range(5000))  # about 35 KB
    xml = f'<w:document xmlns:w="{W}"><w:body>{wp(filler)}</w:body></w:document>'
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as z:
        z.writestr("word/document.xml", xml)
    data = bytearray(path.read_bytes())
    for sig, offset in ((b"PK\x03\x04", 22), (b"PK\x01\x02", 24)):  # uncompressed size fields
        pos = data.find(sig)
        data[pos + offset:pos + offset + 4] = (100).to_bytes(4, "little")
    path.write_bytes(bytes(data))
    with pytest.raises(ExtractError):
        extract_office_text(path, ".docx", ExtractLimits(max_member_bytes=10_000, max_ratio=10**9))


@pytest.mark.parametrize("ext", [".docx", ".pptx", ".xlsx", ".odt", ".ods", ".odp"])
def test_non_zip_files_raise_and_the_message_has_no_file_content(tmp_path, ext):
    path = tmp_path / f"bad{ext}"
    path.write_bytes(f"{MARKER} this is not a zip archive".encode())
    with pytest.raises(ExtractError) as info:
        extract_office_text(path, ext)
    assert MARKER not in str(info.value) and str(info.value)


def test_truncated_zip_raises_without_content_in_the_message(tmp_path):
    good = docx(tmp_path, wp(MARKER + " body"), name="good.docx").read_bytes()
    cut = tmp_path / "cut.docx"
    cut.write_bytes(good[: len(good) // 2])
    with pytest.raises(ExtractError) as info:
        extract_office_text(cut, ".docx")
    assert MARKER not in str(info.value)


def test_invalid_xml_raises_without_content_in_the_message(tmp_path):
    xml = f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>{MARKER}</w:t></w:r></w:p>'  # never closed
    path = make_zip(tmp_path / "t.docx", {"word/document.xml": xml})
    with pytest.raises(ExtractError) as info:
        extract_office_text(path, ".docx")
    assert MARKER not in str(info.value)


def test_invalid_xml_in_odf_raises_without_content_in_the_message(tmp_path):
    path = make_zip(tmp_path / "t.odt", {"content.xml": f"<office:document-content {ODF_NS}><text:p>{MARKER}</text:q>"})
    with pytest.raises(ExtractError) as info:
        extract_office_text(path, ".odt")
    assert MARKER not in str(info.value)


def garbage_inputs() -> list[bytes]:
    rng = random.Random(20261016)
    valid = b"PK\x03\x04" + bytes(range(30))
    return [b"", b"\x00" * 64, b"PK\x03\x04", b"PK\x05\x06" + b"\x00" * 18, valid, rng.randbytes(10),
            rng.randbytes(4096), b"PK\x03\x04" + rng.randbytes(2000), b"%PDF-1.4\n" + rng.randbytes(300)]


@pytest.mark.parametrize("ext", [".docx", ".pptx", ".xlsx", ".odt", ".ods", ".odp"])
def test_garbage_raises_only_extract_error(tmp_path, ext):
    for i, blob in enumerate(garbage_inputs()):
        path = tmp_path / f"fuzz{i}{ext}"
        path.write_bytes(blob)
        with pytest.raises(ExtractError):
            extract_office_text(path, ext)


@pytest.mark.parametrize("ext", [".docx", ".pptx", ".xlsx", ".odt", ".ods", ".odp"])
def test_valid_zip_with_garbage_members_raises_only_extract_error(tmp_path, ext):
    rng = random.Random(7)
    names = ["word/document.xml", "ppt/slides/slide1.xml", "xl/workbook.xml", "xl/sharedStrings.xml",
             "xl/worksheets/sheet1.xml", "content.xml"]
    path = make_zip(tmp_path / f"junk{ext}", {n: rng.randbytes(300) for n in names})
    with pytest.raises(ExtractError):
        extract_office_text(path, ext)


def test_doctype_with_external_entity_raises_and_reads_nothing(tmp_path):
    secret = tmp_path / "private.txt"
    secret.write_text("EXTERNAL-ENTITY-CONTENT-9d2c", encoding="utf-8")
    xml = (f'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY xxe SYSTEM "{secret.as_uri()}">]>'
           f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>before &xxe; after</w:t></w:r></w:p></w:body>'
           "</w:document>")
    path = make_zip(tmp_path / "t.docx", {"word/document.xml": xml})
    with pytest.raises(ExtractError) as info:
        extract_office_text(path, ".docx")
    assert "EXTERNAL-ENTITY-CONTENT-9d2c" not in str(info.value)


def test_doctype_with_parameter_entity_in_odf_raises(tmp_path):
    secret = tmp_path / "private2.txt"
    secret.write_text("PARAMETER-ENTITY-CONTENT-41ab", encoding="utf-8")
    xml = (f'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY % p SYSTEM "{secret.as_uri()}"> %p;'
           f'<!ENTITY xxe SYSTEM "{secret.as_uri()}">]><office:document-content {ODF_NS}><office:body>'
           "<office:text><text:p>x &xxe; y</text:p></office:text></office:body></office:document-content>")
    path = make_zip(tmp_path / "t.odt", {"content.xml": xml})
    with pytest.raises(ExtractError):
        extract_office_text(path, ".odt")


@pytest.mark.parametrize("decl", ['<!DOCTYPE w:document>', '<!DOCTYPE w:document [<!ENTITY x "INTERNAL-VALUE">]>',
                                  '<!DOCTYPE w:document SYSTEM "http://127.0.0.1:9/evil.dtd">'])
def test_any_doctype_in_any_xml_part_raises(tmp_path, decl):
    xml = (f'<?xml version="1.0"?>{decl}<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>&amp;</w:t></w:r></w:p>'
           "</w:body></w:document>")
    with pytest.raises(ExtractError):
        extract_office_text(make_zip(tmp_path / "t.docx", {"word/document.xml": xml}), ".docx")
    styles = f'<!DOCTYPE s [<!ENTITY y "v">]><w:styles xmlns:w="{W}"/>'
    members = {"word/document.xml": f'<w:document xmlns:w="{W}"><w:body>{wp("ok")}</w:body></w:document>',
               "word/styles.xml": styles}
    with pytest.raises(ExtractError):
        extract_office_text(make_zip(tmp_path / "u.docx", members), ".docx")


def test_billion_laughs_raises(tmp_path):
    lol = "".join(f'<!ENTITY l{i} "' + f"&l{i - 1};" * 10 + '">' for i in range(1, 9))
    xml = (f'<?xml version="1.0"?><!DOCTYPE d [<!ENTITY l0 "lol">{lol}]>'
           f'<w:document xmlns:w="{W}"><w:body><w:p><w:r><w:t>&l8;</w:t></w:r></w:p></w:body></w:document>')
    path = make_zip(tmp_path / "t.docx", {"word/document.xml": xml})
    with pytest.raises(ExtractError):
        extract_office_text(path, ".docx")


# ----------------------------------------------------------------------------- extract_plain_text


def test_plain_text_is_read_as_utf8_unchanged(tmp_path):
    p = tmp_path / "a.md"
    p.write_bytes("# Überschrift\n\nMoore speichern CO₂ – 42,5 %\n".encode())
    assert extract_plain_text(p, 10_000) == "# Überschrift\n\nMoore speichern CO₂ – 42,5 %\n"


def test_plain_text_strips_a_utf8_bom(tmp_path):
    p = tmp_path / "bom.txt"
    p.write_bytes(b"\xef\xbb\xbfHello BOM")
    out = extract_plain_text(p, 1000)
    assert out == "Hello BOM" and not out.startswith("﻿")


def test_plain_text_replaces_invalid_utf8_bytes(tmp_path):
    p = tmp_path / "bad.txt"
    p.write_bytes(b"abc \xff\xfe def \xc3")
    out = extract_plain_text(p, 1000)
    assert out.startswith("abc ") and " def " in out
    assert "�" in out and "\xff" not in out


def test_plain_text_with_nul_raises_without_content_in_the_message(tmp_path):
    p = tmp_path / "nul.txt"
    p.write_bytes(f"{MARKER}\x00 trailing".encode())
    with pytest.raises(ExtractError) as info:
        extract_plain_text(p, 1000)
    assert MARKER not in str(info.value)


def test_plain_text_respects_max_bytes(tmp_path):
    p = tmp_path / "big.txt"
    p.write_text("x" * 100 + "y" * 100, encoding="utf-8")
    assert extract_plain_text(p, 200).startswith("x" * 100)
    with pytest.raises(ExtractError):
        extract_plain_text(p, 199)
