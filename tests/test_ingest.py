"""Ingest and manifest against FakeStore / FakeLLM and tmp_path files (contracts.md "ingest.py and manifest").

Interface decisions beyond contracts.md, made here and to be confirmed by the orchestrator:
- the raw directory used for drift checks inside ingest() is `corpus_dir.parent / "raw"` (data/corpus -> data/raw);
- a raw file is the single file `raw_dir/<id>.<ext>` that is not `<id>.meta.json`;
- `IngestResult.documents` counts documents written in this run (skipped ones are in `skipped`);
- build_manifest takes sha256 from the meta file, `bytes` from the raw file size.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

import pytest

from fakes import FakeLLM, FakeStore, make_source, make_tenant
from ngo_assistant.chunking import ChunkParams, chunk_document
from ngo_assistant.config import Tenant
from ngo_assistant.ingest import IngestResult, build_manifest, check_manifest, ingest, manifest_sha256

TEXT_A = "# Moore\n\n" + "Moore speichern Kohlenstoff. " * 20 + "\n\n" + "Entwässerung setzt CO2 frei. " * 20
TEXT_B = "River basins matter.\n\n" + "Water quality improved in 2024. " * 30


def sha(data: str | bytes) -> str:
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


@pytest.fixture
def corpus(tmp_path):
    d = tmp_path / "corpus"
    d.mkdir()
    (d / "a.txt").write_text(TEXT_A, encoding="utf-8")
    (d / "b.txt").write_text(TEXT_B, encoding="utf-8")
    return d


def run(corpus, store=None, llm=None, tenant=None, **kwargs):
    store = store if store is not None else FakeStore()
    llm = llm if llm is not None else FakeLLM()
    tenant = tenant or make_tenant("a", "b")
    return ingest(tenant, store, llm, corpus, **kwargs), store, llm


# ----------------------------------------------------------------------------- first run


def test_first_run_counts_documents_chunks_and_embed_tokens(corpus):
    result, store, llm = run(corpus)
    assert isinstance(result, IngestResult)
    assert result.documents == 2
    assert result.skipped == 0
    assert store.counts() == {"documents": 2, "chunks": result.chunks}
    assert result.chunks == len(chunk_document(TEXT_A, "Title of a")) + len(chunk_document(TEXT_B, "Title of b"))
    assert result.embed_tokens == llm.embed_tokens_per_text * result.chunks
    assert result.drift == []


def test_document_record_carries_tenant_metadata_text_and_sha(corpus):
    _, store, _ = run(corpus)
    doc = store.documents["a"]
    assert doc.title == "Title of a"
    assert doc.language == "en"
    assert doc.licence == "CC BY 4.0"
    assert doc.redistributable is True
    assert doc.kind == "web"
    assert doc.published == date(2025, 1, 1)
    assert doc.text == TEXT_A
    assert doc.sha256 == sha(TEXT_A)


def test_stored_chunks_equal_the_chunker_output_with_one_embedding_each(corpus):
    _, store, _ = run(corpus)
    expected = chunk_document(TEXT_A, "Title of a")
    assert [c.chunk for c in store.chunks["a"]] == expected
    assert all(len(c.embedding) == 4 for c in store.chunks["a"])


def test_embedding_inputs_are_title_plus_heading_plus_text(corpus):
    _, _, llm = run(corpus)
    texts = llm.embedded_texts()
    assert any(t.startswith("Title of a - ") for t in texts)  # chunks under the "Moore" heading
    assert any(t.startswith("Title of b\n") or t.startswith("Title of b - ") for t in texts)


def test_embeddings_are_requested_in_batches_of_batch_size(tmp_path):
    d = tmp_path / "corpus"
    d.mkdir()
    (d / "a.txt").write_text("\n\n".join(chr(97 + i) * 1000 for i in range(5)), encoding="utf-8")  # 5 chunks
    _, _, llm = run(d, tenant=make_tenant("a"), batch_size=2)
    assert [len(call) for call in llm.embed_calls] == [2, 2, 1]


def test_ingest_records_one_run(corpus):
    _, store, _ = run(corpus)
    assert len(store.runs) == 1
    assert store.runs[0]["tenant"] == "t"


def test_custom_chunk_params_change_the_chunks(corpus):
    small, _, _ = run(corpus, params=ChunkParams(max_chars=200, overlap_chars=0))
    default, _, _ = run(corpus)
    assert small.chunks > default.chunks


# ----------------------------------------------------------------------------- idempotency


def test_second_run_changes_nothing_and_embeds_nothing(corpus):
    store, llm = FakeStore(), FakeLLM()
    first, _, _ = run(corpus, store, llm)
    hashes, writes, embeds = store.chunk_hashes(), list(store.writes), len(llm.embed_calls)
    second, _, _ = run(corpus, store, llm)
    assert (second.documents, second.chunks, second.skipped, second.embed_tokens) == (0, 0, 2, 0)
    assert store.chunk_hashes() == hashes
    assert store.writes == writes
    assert len(llm.embed_calls) == embeds
    assert first.documents == 2


def test_changed_document_is_re_embedded_and_others_are_skipped(corpus):
    store, llm = FakeStore(), FakeLLM()
    run(corpus, store, llm)
    before = store.chunk_hashes()
    llm.embed_calls.clear()
    (corpus / "a.txt").write_text(TEXT_A + "\n\nA new paragraph about peat.", encoding="utf-8")
    result, _, _ = run(corpus, store, llm)
    assert (result.documents, result.skipped) == (1, 1)
    assert result.embed_tokens > 0
    assert store.documents["a"].sha256 == sha(TEXT_A + "\n\nA new paragraph about peat.")
    after = store.chunk_hashes()
    assert [h for h in after if h[0] == "b"] == [h for h in before if h[0] == "b"]
    assert [h for h in after if h[0] == "a"] != [h for h in before if h[0] == "a"]
    assert all("new paragraph" in t or "Title of a" in t for t in llm.embedded_texts())
    assert not any(t.startswith("Title of b") for t in llm.embedded_texts())


def test_rebuild_re_embeds_everything_and_gives_identical_chunk_hashes(corpus):
    store, llm = FakeStore(), FakeLLM()
    run(corpus, store, llm)
    before = store.chunk_hashes()
    result, _, _ = run(corpus, store, llm, rebuild=True)
    assert (result.documents, result.skipped) == (2, 0)
    assert result.embed_tokens > 0
    assert store.chunk_hashes() == before


def test_replaced_chunks_do_not_leave_stale_rows(corpus):
    store, llm = FakeStore(), FakeLLM()
    run(corpus, store, llm)
    (corpus / "a.txt").write_text("Only one short paragraph now.", encoding="utf-8")
    run(corpus, store, llm)
    assert len(store.chunks["a"]) == 1


# ----------------------------------------------------------------------------- missing files


def test_missing_corpus_files_are_all_named_before_any_write(corpus):
    (corpus / "b.txt").unlink()
    store, llm = FakeStore(), FakeLLM()
    with pytest.raises(FileNotFoundError) as excinfo:
        ingest(make_tenant("a", "b", "c"), store, llm, corpus)
    message = str(excinfo.value)
    assert "b" in message and "c" in message
    assert store.writes == []
    assert store.runs == []
    assert llm.embed_calls == []


def test_synthetic_sources_are_ingested_like_any_other(corpus):
    (corpus / "s.txt").write_text("Synthetic note about the Heron Marsh Trust.", encoding="utf-8")
    result, store, _ = run(corpus, tenant=make_tenant("a", "b", synthetic=("s",)))
    assert result.documents == 3
    assert store.documents["s"].kind == "synthetic"


# ----------------------------------------------------------------------------- drift


def write_raw(raw_dir, source_id, content=b"<html>raw</html>", ext="html", meta_sha=None):
    raw_dir.mkdir(exist_ok=True)
    (raw_dir / f"{source_id}.{ext}").write_bytes(content)
    meta = {"id": source_id, "url": f"https://example.org/{source_id}", "sha256": meta_sha or sha(content),
            "fetched_at": "2026-10-14T19:31:46+00:00"}
    (raw_dir / f"{source_id}.meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_drift_lists_sources_whose_raw_file_differs_from_the_manifest_but_does_not_fail(tmp_path, corpus):
    raw = tmp_path / "raw"
    write_raw(raw, "a", b"raw a")
    write_raw(raw, "b", b"raw b")
    manifest = {"generated": "2026-10-14", "sources": {"a": {"sha256": sha(b"raw a")}, "b": {"sha256": sha(b"old b")}}}
    result, store, _ = run(corpus, manifest=manifest)
    assert result.drift == ["b"]
    assert result.documents == 2  # ingest still happened
    assert store.counts()["documents"] == 2


def test_no_manifest_means_no_drift(corpus):
    result, _, _ = run(corpus)
    assert result.drift == []


def test_manifest_matching_raw_files_has_no_drift(tmp_path, corpus):
    raw = tmp_path / "raw"
    write_raw(raw, "a", b"raw a")
    manifest = {"generated": "2026-10-14", "sources": {"a": {"sha256": sha(b"raw a")}}}
    assert run(corpus, manifest=manifest)[0].drift == []


# ----------------------------------------------------------------------------- manifest


def test_build_manifest_reads_meta_files_of_non_synthetic_sources(tmp_path):
    raw = tmp_path / "raw"
    write_raw(raw, "a", b"hello raw")
    tenant = make_tenant("a", synthetic=("s",))  # s has no meta file and must be skipped
    manifest = build_manifest(raw, tenant)
    date.fromisoformat(manifest["generated"])
    assert set(manifest["sources"]) == {"a"}
    entry = manifest["sources"]["a"]
    assert entry["url"] == "https://example.org/a"
    assert entry["sha256"] == sha(b"hello raw")
    assert entry["bytes"] == len(b"hello raw")
    assert entry["fetched_at"] == "2026-10-14T19:31:46+00:00"
    json.dumps(manifest)


def test_build_manifest_names_a_source_without_meta_file(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    with pytest.raises(FileNotFoundError, match="a"):
        build_manifest(raw, make_tenant("a"))


def test_check_manifest_returns_nothing_when_all_hashes_match(tmp_path):
    raw = tmp_path / "raw"
    write_raw(raw, "a", b"one")
    write_raw(raw, "b", b"two")
    manifest = build_manifest(raw, make_tenant("a", "b"))
    assert check_manifest(manifest, raw) == []


def test_check_manifest_reports_changed_and_missing_raw_files(tmp_path):
    raw = tmp_path / "raw"
    write_raw(raw, "a", b"one")
    write_raw(raw, "b", b"two")
    write_raw(raw, "c", b"three")
    manifest = build_manifest(raw, make_tenant("a", "b", "c"))
    (raw / "a.html").write_bytes(b"changed")
    (raw / "c.html").unlink()
    assert sorted(check_manifest(manifest, raw)) == ["a", "c"]


def test_manifest_sha256_is_canonical_over_sorted_keys():
    m1 = {"generated": "2026-10-14", "sources": {"a": {"sha256": "1", "url": "u"}, "b": {"sha256": "2", "url": "v"}}}
    m2 = {"sources": {"b": {"url": "v", "sha256": "2"}, "a": {"url": "u", "sha256": "1"}}, "generated": "2026-10-14"}
    assert manifest_sha256(m1) == manifest_sha256(m2)
    assert len(manifest_sha256(m1)) == 64
    changed = json.loads(json.dumps(m1))
    changed["sources"]["a"]["sha256"] = "9"
    assert manifest_sha256(changed) != manifest_sha256(m1)


# ----------------------------------------------------------------------------- ingest keys (review cycle 1)


def test_ingest_key_is_canonical_and_depends_on_text_params_and_model():
    from ngo_assistant.ingest import ingest_key

    base = ingest_key("abc", ChunkParams(), "m")
    assert base == ingest_key("abc", ChunkParams(), "m")
    assert len(base) == 64
    assert base != ingest_key("abd", ChunkParams(), "m")
    assert base != ingest_key("abc", ChunkParams(max_chars=800), "m")
    assert base != ingest_key("abc", ChunkParams(), "other")


def test_document_record_stores_the_ingest_key(corpus):
    from ngo_assistant.ingest import ingest_key

    _, store, llm = run(corpus)
    assert store.documents["a"].ingest_key == ingest_key(sha(TEXT_A), ChunkParams(), llm.embed_model)
    assert store.document_ingest_key("a") == store.documents["a"].ingest_key
    assert store.document_ingest_key("nope") is None


def test_same_text_with_other_chunk_params_is_re_chunked_and_re_embedded(corpus):
    store, llm = FakeStore(), FakeLLM()
    run(corpus, store, llm)
    before = store.chunk_hashes()
    result, _, _ = run(corpus, store, llm, params=ChunkParams(max_chars=300, overlap_chars=0))
    assert (result.documents, result.skipped) == (2, 0)
    assert result.embed_tokens > 0
    assert store.chunk_hashes() != before
    assert store.counts()["chunks"] == result.chunks
    again, _, _ = run(corpus, store, llm, params=ChunkParams(max_chars=300, overlap_chars=0))
    assert (again.documents, again.skipped, again.embed_tokens) == (0, 2, 0)


def test_same_text_with_other_embed_model_is_re_embedded(corpus):
    store = FakeStore()
    run(corpus, store, FakeLLM(embed_model="embed-m"))
    result, _, _ = run(corpus, store, FakeLLM(embed_model="embed-other"))
    assert (result.documents, result.skipped) == (2, 0)
    assert result.embed_tokens > 0


def test_null_stored_key_counts_as_changed(corpus):
    store, llm = FakeStore(), FakeLLM()
    run(corpus, store, llm)
    from dataclasses import replace

    store.documents["a"] = replace(store.documents["a"], ingest_key=None)
    result, _, _ = run(corpus, store, llm)
    assert (result.documents, result.skipped) == (1, 1)
    assert store.document_ingest_key("a") is not None


def test_too_few_embedding_vectors_raise_naming_the_source_and_write_nothing_for_it(corpus):
    from ngo_assistant.llm import EmbedResult
    from ngo_assistant.models import Usage

    llm = FakeLLM([EmbedResult(vectors=[], usage=Usage(embed_tokens=1, model_calls=1))])
    store = FakeStore()
    with pytest.raises(RuntimeError, match="a"):
        ingest(make_tenant("a", "b"), store, llm, corpus)
    assert store.writes == []
    assert store.runs == []


def test_store_document_failure_leaves_previous_document_and_chunks_intact(corpus):
    from dataclasses import replace

    from ngo_assistant.db import StoredChunk

    store = FakeStore()
    run(corpus, store)
    doc, chunks = store.documents["a"], list(store.chunks["a"])
    bad = [StoredChunk(chunk=chunks[0].chunk, embedding=[1.0])]  # wrong dimension
    with pytest.raises(ValueError):
        store.store_document(replace(doc, sha256="new", text="new text"), bad)
    assert store.documents["a"] == doc
    assert store.chunks["a"] == chunks


def test_nul_in_corpus_text_raises_naming_all_sources_before_any_write(tmp_path):
    d = tmp_path / "corpus"
    d.mkdir()
    (d / "a.txt").write_text("clean text", encoding="utf-8")
    (d / "b.txt").write_text("signi\0cant", encoding="utf-8")
    (d / "c.txt").write_text("ful\0ll", encoding="utf-8")
    store, llm = FakeStore(), FakeLLM()
    with pytest.raises(ValueError, match=r"b.*c|c.*b") as exc:
        ingest(make_tenant("a", "b", "c"), store, llm, d)
    assert "a," not in str(exc.value).split(":")[-1]
    assert store.writes == [] and llm.embed_calls == [] and store.runs == []


def test_run_record_has_manifest_hash_model_digest_and_git_commit(corpus):
    manifest = {"generated": "2026-10-15", "sources": {}}
    _, store, _ = run(corpus, manifest=manifest)
    rec = store.runs[0]
    assert rec["manifest_sha256"] == manifest_sha256(manifest)
    assert rec["embed_model_digest"] == "digest-embed"
    assert "git_commit" in rec


def test_run_record_fields_are_null_when_unknown(corpus):
    _, store, _ = run(corpus)
    assert store.runs[0]["manifest_sha256"] is None


def test_fake_store_read_document_clamps_negative_part():
    store = FakeStore()
    store.seed("a", "x" * 3000)
    assert store.read_document("a", -3).part == 0
    assert store.read_document("a", -3).text == store.read_document("a", 0).text


# ----------------------------------------------------------------------------- file sources (crawler)
# Interface decisions made here (beyond contracts.md), to be confirmed by the orchestrator:
# - file drift is reported even when no manifest is passed (it does not depend on the raw manifest);
# - drift entries are exactly "<id> (changed on disk)" / "<id> (missing on disk)", listed after the ids that the
#   manifest check reports;
# - a file source without a recorded sha256 produces no drift entry.

TEXT_F = "Crawled file text. " * 30


def file_tenant(tmp_path, content: bytes | None = b"original bytes of the crawled file", sha_of=None):
    """Tenant with the web source `a` and the crawled file source `r-f`; returns (tenant, path of the file)."""
    f = tmp_path / "files" / "doc.txt"
    f.parent.mkdir(exist_ok=True)
    if content is not None:
        f.write_bytes(content)
    recorded = sha(sha_of if sha_of is not None else (content or b""))
    file_source = make_source("r-f", kind="file", published=None).model_copy(
        update={"url": "file:r/doc.txt", "path": str(f), "file_sha256": recorded, "file_bytes": len(content or b"")}
    )
    base = make_tenant("a")
    tenant = Tenant(slug="t", name="T", languages=["de", "en"], system_prompt=base.system_prompt,
                    sources=[*base.sources, file_source])
    return tenant, f


@pytest.fixture
def file_corpus(corpus):
    (corpus / "r-f.txt").write_text(TEXT_F, encoding="utf-8")
    return corpus


def test_build_manifest_ignores_file_sources(tmp_path):
    raw = tmp_path / "raw"
    write_raw(raw, "a", b"hello raw")
    tenant, _ = file_tenant(tmp_path)  # r-f has neither a raw file nor a meta file
    manifest = build_manifest(raw, tenant)
    assert set(manifest["sources"]) == {"a"}


def test_build_manifest_with_only_file_sources_is_empty(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    tenant, _ = file_tenant(tmp_path)
    only_files = Tenant(slug="t", name="T", languages=["en"], system_prompt="x", sources=[tenant.sources[1]])
    assert build_manifest(raw, only_files)["sources"] == {}


def test_check_manifest_does_not_mention_file_sources(tmp_path):
    raw = tmp_path / "raw"
    write_raw(raw, "a", b"one")
    tenant, _ = file_tenant(tmp_path)
    manifest = build_manifest(raw, tenant)
    assert check_manifest(manifest, raw) == []


def test_file_source_is_ingested_like_any_other(tmp_path, file_corpus):
    tenant, _ = file_tenant(tmp_path)
    result, store, _ = run(file_corpus, tenant=tenant)
    assert result.documents == 2
    doc = store.documents["r-f"]
    assert doc.kind == "file" and doc.text == TEXT_F and doc.published is None


def test_unchanged_file_has_no_drift(tmp_path, file_corpus):
    tenant, _ = file_tenant(tmp_path)
    assert run(file_corpus, tenant=tenant)[0].drift == []


def test_changed_file_is_reported_as_drift_and_ingest_still_runs(tmp_path, file_corpus):
    tenant, f = file_tenant(tmp_path)
    f.write_bytes(b"different bytes after the crawl")
    result, store, _ = run(file_corpus, tenant=tenant)
    assert result.drift == ["r-f (changed on disk)"]
    assert result.documents == 2 and store.counts()["documents"] == 2


def test_missing_file_is_reported_as_drift_and_ingest_still_runs(tmp_path, file_corpus):
    tenant, f = file_tenant(tmp_path)
    f.unlink()
    result, store, _ = run(file_corpus, tenant=tenant)
    assert result.drift == ["r-f (missing on disk)"]
    assert store.counts()["documents"] == 2


def test_file_drift_is_reported_without_a_manifest_and_after_manifest_drift(tmp_path, file_corpus):
    raw = tmp_path / "raw"
    write_raw(raw, "a", b"raw a")
    tenant, f = file_tenant(tmp_path)
    f.write_bytes(b"changed")
    manifest = {"generated": "2026-10-14", "sources": {"a": {"sha256": sha(b"old a")}}}
    result, _, _ = run(file_corpus, tenant=tenant, manifest=manifest)
    assert result.drift == ["a", "r-f (changed on disk)"]


def test_drift_check_never_raises_for_odd_paths(tmp_path, file_corpus):
    tenant, f = file_tenant(tmp_path)
    f.unlink()
    f.mkdir()  # the recorded path is now a directory
    result, _, _ = run(file_corpus, tenant=tenant)
    assert len(result.drift) == 1 and result.drift[0].startswith("r-f (")


def test_file_source_without_recorded_hash_gives_no_drift(tmp_path, file_corpus):
    tenant, _ = file_tenant(tmp_path)
    tenant.sources[1] = tenant.sources[1].model_copy(update={"file_sha256": None})
    assert run(file_corpus, tenant=tenant)[0].drift == []


def test_drift_is_stored_in_the_run_record(tmp_path, file_corpus):
    tenant, f = file_tenant(tmp_path)
    f.write_bytes(b"changed")
    _, store, _ = run(file_corpus, tenant=tenant)
    assert store.last_ingest_run()["drift"] == ["r-f (changed on disk)"]
