"""Config additions of the filesystem crawler (contracts.md "Addendum: Filesystem crawler").

Interface decisions made here (beyond contracts.md), to be confirmed by the orchestrator:
- `crawled_sources` is given as an ABSOLUTE path in these tests; how a relative path is resolved is not tested;
- whether `CrawlRoot.path` must exist is not tested at validation time (the CLI tests cover a missing directory);
- a duplicate id between hand-written and crawled sources raises a ValueError (pydantic ValidationError) whose
  message contains "duplicate".
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from ngo_assistant.config import CrawlRoot, Source, Tenant, load_tenant

ROOT = Path(__file__).resolve().parent.parent


def root_dict(**overrides):
    base = {
        "id": "docs",
        "path": "/srv/ngo/documents",
        "licence": "Own work, all rights reserved",
        "licence_url": "internal:declared-by-owner",
        "checked_on": "2026-10-16",
    }
    return {**base, **overrides}


def file_source(**overrides):
    base = {
        "id": "docs-a-txt",
        "title": "A",
        "url": "file:docs/a.txt",
        "language": "en",
        "kind": "file",
        "licence": "Own work, all rights reserved",
        "licence_url": "internal:declared-by-owner",
        "redistributable": False,
        "checked_on": "2026-10-16",
    }
    return {**base, **overrides}


def web_source(**overrides):
    base = {
        "id": "hand-a",
        "title": "Hand written",
        "url": "https://example.org/a",
        "language": "en",
        "kind": "web",
        "licence": "CC BY 4.0",
        "licence_url": "https://example.org/licence",
        "redistributable": True,
        "checked_on": "2026-10-14",
    }
    return {**base, **overrides}


def tenant_dict(**extra):
    return {"slug": "t", "name": "T", "languages": ["en", "de"], "system_prompt": "x", **extra}


# ----------------------------------------------------------------------------- CrawlRoot


def test_valid_root_is_accepted_with_documented_defaults():
    r = CrawlRoot.model_validate(root_dict())
    assert r.id == "docs"
    assert r.path == "/srv/ngo/documents"
    assert r.include == [] and r.exclude == []
    assert r.language == "auto"
    assert r.redistributable is False
    assert r.max_file_bytes == 26214400
    assert r.checked_on == date(2026, 10, 16)


def test_root_overrides_are_kept():
    r = CrawlRoot.model_validate(
        root_dict(include=["docs/*.txt"], exclude=["drafts/*"], language="de", redistributable=True,
                  max_file_bytes=1234)
    )
    assert r.include == ["docs/*.txt"] and r.exclude == ["drafts/*"]
    assert r.language == "de" and r.redistributable is True and r.max_file_bytes == 1234


@pytest.mark.parametrize("good", ["a", "0", "my-root-1", "a" * 20])
def test_valid_root_ids(good):
    assert CrawlRoot.model_validate(root_dict(id=good)).id == good


@pytest.mark.parametrize("bad", ["", "A", "-a", "a_b", "a.b", "a b", "a/b", "a" * 21, "a\n", "ü", "../x"])
def test_invalid_root_ids_are_rejected(bad):
    with pytest.raises(ValidationError):
        CrawlRoot.model_validate(root_dict(id=bad))


@pytest.mark.parametrize("bad", ["relative/dir", "docs", "./docs", "~/docs", ""])
def test_path_must_be_absolute(bad):
    with pytest.raises(ValidationError):
        CrawlRoot.model_validate(root_dict(path=bad))


@pytest.mark.parametrize("missing", ["licence", "licence_url", "checked_on", "path", "id"])
def test_required_fields_are_required(missing):
    data = root_dict()
    del data[missing]
    with pytest.raises(ValidationError, match=missing):
        CrawlRoot.model_validate(data)


@pytest.mark.parametrize("value", ["unclear", "Unclear", "UNCLEAR", "  unclear  "])
def test_unclear_licence_is_rejected_case_insensitively(value):
    with pytest.raises(ValidationError, match="unclear"):
        CrawlRoot.model_validate(root_dict(licence=value))


def test_licence_that_merely_contains_the_word_unclear_is_accepted():
    r = CrawlRoot.model_validate(root_dict(licence="Own work (origin unclear for 2 images, excluded)"))
    assert r.licence.startswith("Own work")


@pytest.mark.parametrize("value", ["fr", "AUTO", "", None])
def test_invalid_language_is_rejected(value):
    with pytest.raises(ValidationError):
        CrawlRoot.model_validate(root_dict(language=value))


def test_tenant_rejects_duplicate_root_ids():
    with pytest.raises(ValidationError, match="duplicate"):
        Tenant.model_validate(tenant_dict(crawl=[root_dict(), root_dict(path="/srv/other")]))


def test_tenant_accepts_two_distinct_roots():
    t = Tenant.model_validate(tenant_dict(crawl=[root_dict(), root_dict(id="more", path="/srv/more")]))
    assert [r.id for r in t.crawl] == ["docs", "more"]


def test_tenant_without_crawl_section_has_no_roots_and_no_listing():
    t = Tenant.model_validate(tenant_dict())
    assert not t.crawl
    assert t.crawled_sources is None


# ----------------------------------------------------------------------------- Source kind "file"


def test_file_source_is_accepted_without_the_generated_fields():
    s = Source.model_validate(file_source())
    assert s.kind == "file"
    assert s.path is None and s.file_sha256 is None and s.file_bytes is None
    assert s.published is None


def test_file_source_keeps_the_generated_fields():
    s = Source.model_validate(file_source(path="/srv/ngo/documents/a.txt", file_sha256="ab" * 32, file_bytes=42))
    assert s.path == "/srv/ngo/documents/a.txt"
    assert s.file_sha256 == "ab" * 32
    assert s.file_bytes == 42


@pytest.mark.parametrize("bad", ["files", "File", "dir", "local", ""])
def test_unknown_kinds_are_still_rejected(bad):
    with pytest.raises(ValidationError):
        Source.model_validate(file_source(kind=bad))


def test_file_source_with_unclear_licence_is_rejected():
    with pytest.raises(ValidationError, match="unclear"):
        Source.model_validate(file_source(licence="unclear"))


def test_hand_written_kinds_are_unchanged():
    for kind in ("web", "pdf", "report", "docs", "synthetic"):
        assert Source.model_validate(web_source(kind=kind)).kind == kind


# ----------------------------------------------------------------------------- load_tenant merge


def write_yaml(path: Path, data) -> Path:
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_load_tenant_merges_the_generated_listing(tmp_path):
    listing = write_yaml(
        tmp_path / "t.crawled.yaml",
        {"sources": [file_source(id="docs-a-txt"), file_source(id="docs-b-txt", url="file:docs/b.txt")]},
    )
    tenant_file = write_yaml(
        tmp_path / "t.yaml",
        tenant_dict(sources=[web_source()], crawl=[root_dict()], crawled_sources=str(listing)),
    )
    t = load_tenant(tenant_file)
    assert [s.id for s in t.sources] == ["hand-a", "docs-a-txt", "docs-b-txt"]
    assert [s.kind for s in t.sources] == ["web", "file", "file"]
    assert t.source_ids() == {"hand-a", "docs-a-txt", "docs-b-txt"}


def test_load_tenant_tolerates_a_missing_listing(tmp_path):
    tenant_file = write_yaml(
        tmp_path / "t.yaml",
        tenant_dict(sources=[web_source()], crawl=[root_dict()], crawled_sources=str(tmp_path / "absent.yaml")),
    )
    t = load_tenant(tenant_file)
    assert [s.id for s in t.sources] == ["hand-a"]


def test_load_tenant_ignores_an_existing_listing_when_crawled_sources_is_not_set(tmp_path):
    write_yaml(tmp_path / "t.crawled.yaml", {"sources": [file_source()]})
    tenant_file = write_yaml(tmp_path / "t.yaml", tenant_dict(sources=[web_source()]))
    assert [s.id for s in load_tenant(tenant_file).sources] == ["hand-a"]


def test_duplicate_id_between_hand_written_and_crawled_sources_is_rejected(tmp_path):
    listing = write_yaml(tmp_path / "t.crawled.yaml", {"sources": [file_source(id="hand-a")]})
    tenant_file = write_yaml(
        tmp_path / "t.yaml",
        tenant_dict(sources=[web_source(id="hand-a")], crawl=[root_dict()], crawled_sources=str(listing)),
    )
    with pytest.raises(ValueError, match="duplicate"):
        load_tenant(tenant_file)


def test_unclear_licence_inside_the_generated_listing_is_rejected(tmp_path):
    listing = write_yaml(tmp_path / "t.crawled.yaml", {"sources": [file_source(licence="unclear")]})
    tenant_file = write_yaml(tmp_path / "t.yaml", tenant_dict(crawl=[root_dict()], crawled_sources=str(listing)))
    with pytest.raises(ValueError, match="unclear"):
        load_tenant(tenant_file)


def test_listing_of_a_tenant_with_hand_written_sources_only_keeps_them_in_order(tmp_path):
    tenant_file = write_yaml(
        tmp_path / "t.yaml",
        tenant_dict(sources=[web_source(id="z-1"), web_source(id="a-1", url="https://example.org/b")]),
    )
    assert [s.id for s in load_tenant(tenant_file).sources] == ["z-1", "a-1"]


@pytest.mark.parametrize("name", ["demo.yaml", "moorfunke.yaml"])
def test_existing_tenant_files_still_load(name):
    t = load_tenant(ROOT / "tenants" / name)
    assert t.slug
    assert not t.crawl and t.crawled_sources is None
    assert all(s.kind != "file" for s in t.sources)
