"""Chunker contract (contracts.md, design.md "Chunking"). Pure functions, no fakes needed."""

from __future__ import annotations

import hashlib

import pytest

from ngo_assistant.chunking import Chunk, ChunkParams, chunk_document, embedding_input


def paragraphs(*blocks: str) -> str:
    return "\n\n".join(blocks)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_chunk_params_defaults_are_1200_and_150():
    params = ChunkParams()
    assert (params.max_chars, params.overlap_chars) == (1200, 150)


def test_chunk_params_are_frozen():
    with pytest.raises(Exception):  # noqa: B017 - pydantic ValidationError or dataclass FrozenInstanceError
        ChunkParams().max_chars = 10  # type: ignore[misc]


@pytest.mark.parametrize("text", ["", "   ", "\n\n \t\n"])
def test_empty_or_whitespace_input_gives_no_chunks(text):
    assert chunk_document(text, "Title") == []


def test_short_document_is_one_chunk_with_ord_zero_and_no_heading():
    text = "A short paragraph about moors."
    [chunk] = chunk_document(text, "Title")
    assert isinstance(chunk, Chunk)
    assert chunk.ord == 0
    assert chunk.heading is None
    assert chunk.text == text
    assert (chunk.char_start, chunk.char_end) == (0, len(text))
    assert chunk.sha256 == sha(text)


def test_chunking_is_deterministic_including_sha256_list():
    text = paragraphs(*[f"Paragraph {i}. " + "word " * 80 for i in range(12)])
    first = chunk_document(text, "T")
    second = chunk_document(text, "T")
    assert first == second
    assert [c.sha256 for c in first] == [c.sha256 for c in second]
    assert len(first) > 1


def test_ord_counts_from_zero_without_gaps():
    text = paragraphs(*[("abcdefghij"[i] * 500) for i in range(8)])
    chunks = chunk_document(text, "T")
    assert [c.ord for c in chunks] == list(range(len(chunks)))


def test_chunk_sha256_is_sha256_of_chunk_text_utf8():
    text = paragraphs("Größe der Moore in Hektar. " * 3, "Zweiter Absatz über Äcker. " * 3)
    for chunk in chunk_document(text, "T", ChunkParams(max_chars=90, overlap_chars=0)):
        assert chunk.sha256 == sha(chunk.text)


def test_char_offsets_index_into_the_input_text():
    text = paragraphs("Erster Absatz über Moore. " * 4, "Zweiter Absatz über Flüsse. " * 4, "Dritter Absatz. " * 4)
    chunks = chunk_document(text, "T", ChunkParams(max_chars=120, overlap_chars=0))
    assert len(chunks) > 1
    for chunk in chunks:
        assert text[chunk.char_start:chunk.char_end] == chunk.text


def test_no_chunk_exceeds_max_chars_for_normal_paragraphs():
    text = paragraphs(*[f"Block {i}: " + "x" * 290 for i in range(20)])
    chunks = chunk_document(text, "T")
    assert len(chunks) > 1
    assert all(len(c.text) <= 1200 for c in chunks)


def test_blocks_are_packed_up_to_max_chars_not_one_chunk_per_block():
    text = paragraphs("a" * 300, "b" * 300, "c" * 300)  # 904 chars with separators
    assert len(chunk_document(text, "T")) == 1


def test_last_short_block_is_repeated_at_start_of_next_chunk():
    a, b, short, d, e = "A" * 500, "B" * 500, "S" * 100, "D" * 500, "E" * 500
    chunks = chunk_document(paragraphs(a, b, short, d, e), "T")
    assert len(chunks) == 2
    assert chunks[0].text.endswith(short)
    assert chunks[1].text.startswith(short)
    assert chunks[1].text.endswith(e)


def test_last_block_longer_than_overlap_is_not_repeated():
    a, b, c = "A" * 500, "B" * 500, "C" * 500
    chunks = chunk_document(paragraphs(a, b, c), "T")
    assert [ch.text for ch in chunks] == [paragraphs(a, b), c]


def test_overlap_is_off_when_overlap_chars_is_zero():
    a, b, short, d = "A" * 500, "B" * 500, "S" * 100, "D" * 500
    chunks = chunk_document(paragraphs(a, b, short, d), "T", ChunkParams(max_chars=1200, overlap_chars=0))
    assert not chunks[1].text.startswith("S")


def test_long_block_is_split_at_sentence_ends():
    sentences = [f"Sentence number {i:03d} talks about the moor." for i in range(60)]  # ~2700 chars, one block
    text = " ".join(sentences)
    chunks = chunk_document(text, "T")
    assert len(chunks) >= 3
    assert all(len(c.text) <= 1200 for c in chunks)
    assert all(c.text.rstrip().endswith(".") for c in chunks)
    for sentence in sentences:
        assert any(sentence in c.text for c in chunks), sentence


def test_long_block_splits_at_newline_when_no_sentence_end():
    lines = [f"line {i:03d} " + "w" * 40 for i in range(60)]
    chunks = chunk_document("\n".join(lines), "T")
    assert len(chunks) >= 3
    assert all(len(c.text) <= 1200 for c in chunks)
    assert all(not c.text.startswith(" ") for c in chunks)
    for line in lines:
        assert any(line in c.text for c in chunks), line


def test_block_without_any_boundary_is_hard_split_at_max_chars():
    chunks = chunk_document("x" * 3000, "T")
    assert len(chunks) == 3
    assert [len(c.text) for c in chunks] == [1200, 1200, 600]
    assert "".join(c.text for c in chunks) == "x" * 3000


def test_custom_max_chars_is_respected():
    text = paragraphs(*[f"para{i} " + "y" * 40 for i in range(10)])
    chunks = chunk_document(text, "T", ChunkParams(max_chars=100, overlap_chars=0))
    assert len(chunks) > 3
    assert all(len(c.text) <= 100 for c in chunks)


def test_heading_metadata_is_the_nearest_preceding_heading_block():
    intro, p1, p2, p3 = "i" * 55, "p" * 55, "q" * 55, "r" * 55
    text = paragraphs(intro, "# Alpha", p1, p2, "## Beta", p3)
    chunks = chunk_document(text, "T", ChunkParams(max_chars=60, overlap_chars=0))
    by_text = {c.text: c for c in chunks}
    assert by_text[intro].heading is None
    assert "Alpha" in (by_text[p1].heading or "")
    assert "Alpha" in (by_text[p2].heading or "")
    assert "Beta" in (by_text[p3].heading or "")


def test_heading_is_none_when_document_has_no_heading():
    text = paragraphs(*["z" * 500 for _ in range(5)])
    assert all(c.heading is None for c in chunk_document(text, "T"))


def test_embedding_input_prefixes_title_and_heading():
    chunk = Chunk(ord=0, heading="Moor facts", text="Body text.", char_start=0, char_end=10, sha256=sha("Body text."))
    assert embedding_input("EEA report", chunk) == "EEA report - Moor facts\nBody text."


def test_embedding_input_without_heading_has_no_heading_part():
    chunk = Chunk(ord=0, heading=None, text="Body text.", char_start=0, char_end=10, sha256=sha("Body text."))
    assert embedding_input("EEA report", chunk) == "EEA report\nBody text."


# --- oversize `#` blocks (review cycle 1, Warning 3) ---------------------------------------------


def test_fifty_thousand_hash_lines_without_blank_line_stay_within_max_chars():
    text = "\n".join(f"# line {i}" for i in range(50_000))
    chunks = chunk_document(text, "T")
    assert chunks
    assert all(len(c.text) <= 1200 for c in chunks)
    assert all(text[c.char_start : c.char_end] == c.text for c in chunks)


def test_fifty_thousand_hash_lines_run_in_under_one_second():
    import time

    text = "\n".join(f"# line {i}" for i in range(50_000))
    started = time.perf_counter()
    chunk_document(text, "T")
    assert time.perf_counter() - started < 1.0


def test_oversize_hash_block_mixed_with_ordinary_blocks_is_bounded():
    big = "\n".join(f"# line {i}" for i in range(2000))
    text = paragraphs("# Intro", "before " * 20, big, "after " * 20)
    chunks = chunk_document(text, "T", ChunkParams(max_chars=300, overlap_chars=0))
    assert all(len(c.text) <= 300 for c in chunks)
    assert any("after" in c.text for c in chunks)
    assert chunks[0].heading == "Intro"


@pytest.mark.parametrize("body", ["#" + "x" * 4999, "#" + "word\n" * 1000], ids=["no-newlines", "newlines"])
def test_hash_block_of_5000_chars_with_and_without_newlines_is_split(body):
    chunks = chunk_document(body, "T", ChunkParams(max_chars=1200, overlap_chars=0))
    assert len(chunks) >= 4
    assert all(len(c.text) <= 1200 for c in chunks)


def test_long_or_multiline_hash_blocks_are_not_headings():
    long_line = "# " + "h" * 250  # single line, over 200 characters
    multi = "# first line\nsecond line"
    text = paragraphs("# Real heading", long_line, "body one", multi, "body two")
    chunks = chunk_document(text, "T", ChunkParams(max_chars=300, overlap_chars=0))
    assert any("body two" in c.text for c in chunks)
    assert all(c.heading == "Real heading" for c in chunks)


def test_short_single_line_hash_block_is_still_a_heading():
    text = paragraphs("# " + "h" * 198, "body")  # exactly 200 characters
    [chunk] = chunk_document(text, "T")
    assert chunk.heading == "h" * 198
