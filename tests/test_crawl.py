"""Filesystem crawler (contracts.md "Addendum: Filesystem crawler"). Trees are built in tmp_path.

Interface decisions made here (beyond contracts.md), to be confirmed by the orchestrator:
- the slug of a file id is taken from the relative path INCLUDING its extension ("docs/a b.txt" -> "docs-a-b-txt");
- the 60 character cut applies to the slug alone (the root id and the `-` after it come on top; the 6 hex suffix
  is appended as `-xxxxxx`);
- on a collision both ids stay unique and valid; at least one carries the suffix (which one is not specified);
- a skipped directory is ONE `Skipped` entry whose relpath is the directory (its files are not listed);
- `node_modules` and `__pycache__` give reason `excluded`; `.git` and `.venv` give `hidden` or `excluded`;
- dot-named credential files (`.env`, `.ssh`, ...) give `credential_pattern` or `hidden`; every other credential
  name gives `credential_pattern` (this check wins over `unsupported_type` and `not_included`);
- `CrawlResult.files` / `.skipped` are sorted by plain string order of the NFC relative path;
- `CrawlLimitError` and `CrawlLimits`/`CrawlResult`/`CrawledFile`/`Skipped` live in `ngo_assistant.crawl`;
  `Skipped` has attributes `relpath` and `reason`;
- the depth of a top-level file is 0, of a file in `a/` is 1; a directory deeper than `max_depth` is skipped with
  reason `depth`;
- `write_crawled_sources` renames with `os.replace`, `os.rename` or `Path.replace`/`Path.rename`; the failure test
  patches all of them; a failed write leaves neither the target nor a temp file behind.
"""

from __future__ import annotations

import builtins
import hashlib
import io
import os
import re
import unicodedata
from datetime import date
from pathlib import Path

import pytest
import yaml

from ngo_assistant.config import CrawlRoot, Tenant, load_tenant
from ngo_assistant.crawl import (
    CrawlLimitError,
    CrawlLimits,
    crawl_root,
    write_crawled_sources,
)

ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]*")
SUPPORTED = [".txt", ".md", ".markdown", ".html", ".htm", ".pdf", ".docx", ".pptx", ".xlsx", ".odt", ".ods", ".odp"]


def make_root(path: Path, **kw) -> CrawlRoot:
    data = {
        "id": "r",
        "path": str(path),
        "licence": "Own work, all rights reserved",
        "licence_url": "internal:declared-by-owner",
        "checked_on": date(2026, 10, 16),
    }
    data.update(kw)
    return CrawlRoot.model_validate(data)


@pytest.fixture
def tree(tmp_path) -> Path:
    d = tmp_path / "tree"
    d.mkdir()
    return d


def put(base: Path, rel: str, content: str | bytes = None) -> Path:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if content is None:
        content = f"distinct content of {rel}\n"
    if isinstance(content, str):
        p.write_text(content, encoding="utf-8")
    else:
        p.write_bytes(content)
    return p


def crawl(base: Path, limits: CrawlLimits | None = None, **kw):
    root = make_root(base, **kw)
    return root, (crawl_root(root, limits) if limits else crawl_root(root))


def rels(result) -> list[str]:
    return [f.source.url.removeprefix("file:").split("/", 1)[1] for f in result.files]


def skipped(result) -> dict[str, str]:
    return {s.relpath: s.reason for s in result.skipped}


def symlink(target: Path, link: Path, directory: bool = False) -> None:
    try:
        os.symlink(target, link, target_is_directory=directory)
    except (OSError, NotImplementedError):
        pytest.skip("this platform or user may not create symlinks")


# ----------------------------------------------------------------------------- discovery


def test_every_supported_extension_is_found_in_lower_and_upper_case(tree):
    for i, ext in enumerate(SUPPORTED):
        put(tree, f"low{i}{ext}", f"lower case number {i}")
        put(tree, f"UP{i}{ext.upper()}", f"upper case number {i}")
    _, result = crawl(tree)
    assert sorted(rels(result)) == sorted([f"low{i}{e}" for i, e in enumerate(SUPPORTED)]
                                          + [f"UP{i}{e.upper()}" for i, e in enumerate(SUPPORTED)])
    assert result.skipped == []


def test_files_in_subdirectories_are_found_with_forward_slash_relpaths(tree):
    put(tree, "a/b/c.txt", "deep one")
    put(tree, "top.md", "top one")
    _, result = crawl(tree)
    assert sorted(rels(result)) == ["a/b/c.txt", "top.md"]


def test_files_and_skipped_are_sorted_by_relative_path(tree):
    for name in ["b.txt", "a/z.txt", "a.txt", "B.txt", "c/d/e.md"]:
        put(tree, name)
    put(tree, "x.bin", "unsupported one")
    put(tree, "A.bin", "unsupported two")
    _, result = crawl(tree)
    assert rels(result) == ["B.txt", "a.txt", "a/z.txt", "b.txt", "c/d/e.md"]
    assert [s.relpath for s in result.skipped] == ["A.bin", "x.bin"]


def test_two_runs_give_identical_results(tree):
    for name in ["m.txt", "n/o.md", "n/p.html", "Q.PDF", "skipme.bin", ".hid.txt"]:
        put(tree, name)
    root = make_root(tree)
    first, second = crawl_root(root), crawl_root(root)
    assert [f.source.model_dump() for f in first.files] == [f.source.model_dump() for f in second.files]
    assert [(s.relpath, s.reason) for s in first.skipped] == [(s.relpath, s.reason) for s in second.skipped]


def test_source_fields_for_a_file(tree):
    content = "Moore speichern Kohlenstoff.\n"
    p = put(tree, "Sub Dir/Jahres_bericht-2024.txt", content)
    root, result = crawl(tree, language="de", redistributable=False)
    [f] = result.files
    s = f.source
    assert s.kind == "file"
    assert s.id == "r-sub-dir-jahres-bericht-2024-txt"
    assert s.url == "file:r/Sub Dir/Jahres_bericht-2024.txt"
    assert s.title == "Jahres bericht 2024"
    assert s.language == "de"
    assert s.published is None
    assert s.licence == root.licence and s.licence_url == root.licence_url
    assert s.redistributable is False
    assert s.checked_on == date(2026, 10, 16)
    assert s.path == str(p)
    assert s.file_sha256 == hashlib.sha256(content.encode()).hexdigest()
    assert s.file_bytes == len(content.encode())


def test_url_is_a_pseudo_url_without_the_absolute_path(tree):
    put(tree, "a/b.txt")
    _, result = crawl(tree)
    url = result.files[0].source.url
    assert url == "file:r/a/b.txt"
    assert str(tree) not in url and not url.startswith("file:/")


def test_title_is_the_file_name_without_extension_with_spaces_for_dashes_and_underscores(tree):
    put(tree, "Annual_report-2024.final.txt")
    _, result = crawl(tree)
    assert result.files[0].source.title == "Annual report 2024.final"


def test_sha256_and_size_of_a_larger_binary_file_are_correct(tree):
    data = bytes(range(256)) * 5000 + b"tail"  # larger than one hashing chunk of typical size
    put(tree, "big.pdf", data)
    _, result = crawl(tree)
    s = result.files[0].source
    assert s.file_sha256 == hashlib.sha256(data).hexdigest()
    assert s.file_bytes == len(data)


@pytest.mark.parametrize("text,expected", [
    ("Die Moore speichern viel Kohlenstoff und das ist für das Klima wichtig. Wir schützen die Moore.", "de"),
    ("The peatlands store a lot of carbon and this is important for the climate. We protect the bogs.", "en"),
])
def test_language_auto_is_detected_from_text_like_files(tree, text, expected):
    put(tree, "doc.txt", text)
    _, result = crawl(tree, language="auto")
    assert result.files[0].source.language == expected


def test_language_auto_falls_back_to_english_when_nothing_is_detectable(tree):
    put(tree, "only.pdf", b"%PDF-1.4 binary-ish")
    _, result = crawl(tree, language="auto")
    assert result.files[0].source.language == "en"


def test_fixed_root_language_overrides_the_content(tree):
    put(tree, "doc.txt", "The peatlands store a lot of carbon and this is important for the climate.")
    _, result = crawl(tree, language="de")
    assert result.files[0].source.language == "de"


# ----------------------------------------------------------------------------- ids


def test_id_is_root_id_plus_slug_and_matches_the_source_id_pattern(tree):
    put(tree, "Docs/Bericht 2024 (final).PDF")
    _, result = crawl(tree)
    sid = result.files[0].source.id
    assert sid == "r-docs-bericht-2024-final-pdf"
    assert ID_PATTERN.fullmatch(sid) and ".." not in sid


def test_unicode_names_are_slugged_to_ascii(tree):
    put(tree, "Müller Übersicht.txt")
    _, result = crawl(tree)
    assert result.files[0].source.id == "r-m-ller-bersicht-txt"


def test_names_without_ascii_letters_still_give_valid_distinct_ids(tree):
    put(tree, "日本語.txt", "japanese name")
    put(tree, "中文.txt", "chinese name")
    _, result = crawl(tree)
    ids = [f.source.id for f in result.files]
    assert len(ids) == 2 and len(set(ids)) == 2
    assert all(ID_PATTERN.fullmatch(i) and i.startswith("r-") for i in ids)


def h6(relpath: str) -> str:
    return hashlib.sha256(unicodedata.normalize("NFC", relpath).encode("utf-8")).hexdigest()[:6]


def test_very_long_names_are_cut_to_60_chars_and_get_a_hash_suffix(tree):
    name = "a" * 100 + ".txt"
    put(tree, name)
    _, result = crawl(tree)
    sid = result.files[0].source.id
    assert sid == "r-" + "a" * 60 + "-" + h6(name)
    assert ID_PATTERN.fullmatch(sid)


def test_exactly_60_char_slug_is_not_cut_and_has_no_suffix(tree):
    name = "b" * 56 + ".txt"  # slug "b"*56 + "-txt" = 60 chars
    put(tree, name)
    _, result = crawl(tree)
    assert result.files[0].source.id == "r-" + "b" * 56 + "-txt"


def test_colliding_slugs_stay_unique_and_deterministic(tree):
    put(tree, "a b.txt", "with a space")
    put(tree, "a-b.txt", "with a dash")
    put(tree, "a_b.txt", "with an underscore")
    root = make_root(tree)
    first = {f.source.url: f.source.id for f in crawl_root(root).files}
    second = {f.source.url: f.source.id for f in crawl_root(root).files}
    assert first == second
    assert len(set(first.values())) == 3
    assert all(ID_PATTERN.fullmatch(i) and i.startswith("r-a-b-txt") for i in first.values())
    suffixed = [(u, i) for u, i in first.items() if i != "r-a-b-txt"]
    assert len(suffixed) >= 2
    for url, sid in suffixed:
        assert sid == "r-a-b-txt-" + h6(url.split("/", 1)[1])


def test_ids_are_stable_when_unrelated_files_are_added(tree):
    put(tree, "stable.txt")
    before = crawl(tree)[1].files[0].source.id
    put(tree, "zzz/other.txt")
    after = {f.source.url: f.source.id for f in crawl(tree)[1].files}
    assert after["file:r/stable.txt"] == before


# ----------------------------------------------------------------------------- hidden, excluded directories


def test_hidden_files_and_directories_are_skipped_with_reason_hidden(tree):
    put(tree, ".hidden.txt")
    put(tree, ".cache/inside.txt")
    put(tree, "visible.txt")
    _, result = crawl(tree)
    assert rels(result) == ["visible.txt"]
    sk = skipped(result)
    assert sk[".hidden.txt"] == "hidden"
    assert sk[".cache"] == "hidden"


@pytest.mark.parametrize("dirname", ["node_modules", "__pycache__"])
def test_tooling_directories_are_skipped_with_reason_excluded(tree, dirname):
    put(tree, f"{dirname}/lib.txt")
    put(tree, f"sub/{dirname}/lib2.txt")
    put(tree, "keep.txt")
    _, result = crawl(tree)
    assert rels(result) == ["keep.txt"]
    sk = skipped(result)
    assert sk[dirname] == "excluded"
    assert sk[f"sub/{dirname}"] == "excluded"


@pytest.mark.parametrize("dirname", [".git", ".venv"])
def test_dot_tooling_directories_are_skipped(tree, dirname):
    put(tree, f"{dirname}/notes.txt")
    put(tree, "keep.txt")
    _, result = crawl(tree)
    assert rels(result) == ["keep.txt"]
    assert skipped(result)[dirname] in {"hidden", "excluded"}


# ----------------------------------------------------------------------------- credentials


@pytest.mark.parametrize("name", ["server.pem", "id_rsa", "id_rsa.pub", "id_ed25519", "x.key", "cert.p12",
                                  "cert.pfx", "vault.kdbx", "app.keystore", "id_rsa.txt", "SERVER.PEM"])
def test_credential_names_are_always_skipped_even_when_include_lists_them(tree, name):
    put(tree, name, "credential-ish content, harmless text")
    put(tree, "ok.txt")
    _, result = crawl(tree, include=["*"])
    assert rels(result) == ["ok.txt"]
    assert skipped(result)[name] == "credential_pattern"


@pytest.mark.parametrize("name", [".env", ".env.local", ".env.production"])
def test_dot_env_files_are_never_crawled_even_when_include_lists_them(tree, name):
    put(tree, name, "TOKEN=abc")
    put(tree, "ok.txt")
    _, result = crawl(tree, include=["*", ".env*"])
    assert rels(result) == ["ok.txt"]
    assert skipped(result)[name] in {"credential_pattern", "hidden"}


@pytest.mark.parametrize("dirname", ["secrets", ".ssh", ".aws", ".kube", ".gnupg"])
def test_credential_directories_are_never_entered(tree, dirname):
    put(tree, f"{dirname}/notes.txt", "harmless text inside")
    put(tree, "ok.txt")
    _, result = crawl(tree, include=["*"])
    assert rels(result) == ["ok.txt"]
    assert skipped(result)[dirname] in ({"credential_pattern"} if dirname == "secrets"
                                        else {"credential_pattern", "hidden"})


def test_credential_directory_nested_deeper_is_skipped_too(tree):
    put(tree, "project/secrets/passwords.txt", "harmless text inside")
    _, result = crawl(tree)
    assert result.files == []
    assert skipped(result)["project/secrets"] == "credential_pattern"


def test_credential_names_are_not_overridable_by_exclude_or_include_order(tree):
    put(tree, "server.pem", "harmless text")
    _, result = crawl(tree, include=["server.pem"], exclude=[])
    assert result.files == []
    assert skipped(result)["server.pem"] == "credential_pattern"


PEM_BODY = "MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC\n-----END PRIVATE KEY-----\n"


@pytest.mark.parametrize("header", ["-----BEGIN PRIVATE KEY-----", "-----BEGIN RSA PRIVATE KEY-----",
                                    "-----BEGIN OPENSSH PRIVATE KEY-----", "-----BEGIN ENCRYPTED PRIVATE KEY-----",
                                    "-----BEGIN EC PRIVATE KEY-----", "-----BEGIN DSA PRIVATE KEY-----",
                                    "-----BEGIN PGP PRIVATE KEY BLOCK-----"])
def test_text_file_with_pem_private_key_header_is_skipped(tree, header):
    put(tree, "notes.txt", f"Meeting notes\n{header}\n{PEM_BODY}")
    put(tree, "ok.txt")
    _, result = crawl(tree)
    assert rels(result) == ["ok.txt"]
    assert skipped(result)["notes.txt"] == "private_key_header"


def test_pem_header_inside_the_first_64_kib_is_found_even_late(tree):
    put(tree, "late.md", "x" * 60000 + "\n-----BEGIN PRIVATE KEY-----\n" + PEM_BODY)
    _, result = crawl(tree)
    assert result.files == []
    assert skipped(result)["late.md"] == "private_key_header"


def test_pem_header_after_64_kib_is_not_looked_for(tree):
    put(tree, "beyond.md", "y" * 70000 + "\n-----BEGIN PRIVATE KEY-----\n" + PEM_BODY)
    _, result = crawl(tree)
    assert rels(result) == ["beyond.md"]


def test_prose_about_private_keys_is_not_skipped(tree):
    put(tree, "guide.md", "How to protect a private key: never share your PRIVATE KEY; begin with a passphrase.\n")
    put(tree, "pub.txt", "-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----\n")
    put(tree, "pgp.txt", "-----BEGIN PGP PUBLIC KEY BLOCK-----\nmQENBF\n-----END PGP PUBLIC KEY BLOCK-----\n")
    put(tree, "pubkey.txt", "-----BEGIN PUBLIC KEY-----\nMIIBIj\n-----END PUBLIC KEY-----\n")
    _, result = crawl(tree)
    assert rels(result) == ["guide.md", "pgp.txt", "pub.txt", "pubkey.txt"]


# ----------------------------------------------------------------------------- symlinks


def test_symlinked_file_is_skipped_and_never_followed(tree):
    real = put(tree, "real.txt")
    symlink(real, tree / "link.txt")
    _, result = crawl(tree)
    assert rels(result) == ["real.txt"]
    assert skipped(result)["link.txt"] == "symlink"


def test_symlinked_directory_is_skipped_and_its_content_not_listed(tree, tmp_path):
    real_dir = tmp_path / "elsewhere"
    put(real_dir, "inner.txt")
    symlink(real_dir, tree / "linked", directory=True)
    put(tree, "keep.txt")
    _, result = crawl(tree)
    assert rels(result) == ["keep.txt"]
    assert skipped(result)["linked"] == "symlink"


def test_symlink_loop_terminates_and_is_skipped(tree):
    put(tree, "a/file.txt")
    symlink(tree, tree / "a" / "loop", directory=True)
    symlink(Path("a"), tree / "selfref", directory=True)
    _, result = crawl(tree)
    assert rels(result) == ["a/file.txt"]
    sk = skipped(result)
    assert sk["a/loop"] == "symlink" and sk["selfref"] == "symlink"


def test_dangling_symlink_is_skipped_as_symlink(tree):
    symlink(tree / "does-not-exist.txt", tree / "dangling.txt")
    put(tree, "ok.txt")
    _, result = crawl(tree)
    assert rels(result) == ["ok.txt"]
    assert skipped(result)["dangling.txt"] == "symlink"


@pytest.fixture
def opened(monkeypatch):
    """Records every path passed to open() / io.open() / os.open()."""
    seen: list[str] = []
    real_builtin, real_io, real_os = builtins.open, io.open, os.open

    def spy(real):
        def inner(file, *a, **k):
            seen.append(str(file))
            return real(file, *a, **k)
        return inner

    monkeypatch.setattr(builtins, "open", spy(real_builtin))
    monkeypatch.setattr(io, "open", spy(real_io))
    monkeypatch.setattr(os, "open", spy(real_os))
    return seen


def test_symlink_pointing_outside_the_root_is_never_read(tree, tmp_path, opened):
    outside = put(tmp_path, "outside_secret.txt", "TOP SECRET CONTENT outside the root")
    symlink(outside, tree / "innocent.txt")
    outside_dir = tmp_path / "outside_dir"
    put(outside_dir, "inner_secret.txt", "TOP SECRET CONTENT inside outside dir")
    symlink(outside_dir, tree / "innocent_dir", directory=True)
    put(tree, "ok.txt")
    _, result = crawl(tree)
    assert rels(result) == ["ok.txt"]
    sk = skipped(result)
    assert sk["innocent.txt"] == "symlink" and sk["innocent_dir"] == "symlink"
    assert not [p for p in opened if "innocent" in p or "outside_secret" in p or "inner_secret" in p]


def test_symlinks_never_raise_even_when_a_loop_makes_is_dir_fail(tree):
    symlink(Path("loop-a"), tree / "loop-b")
    symlink(Path("loop-b"), tree / "loop-a")
    put(tree, "ok.txt")
    _, result = crawl(tree)
    assert rels(result) == ["ok.txt"]
    sk = skipped(result)
    assert sk["loop-a"] == "symlink" and sk["loop-b"] == "symlink"


def test_root_given_through_a_symlink_is_crawled_and_contained_by_real_paths(tree, tmp_path):
    put(tree, "inside/one.txt", "reachable through the root link")
    link = tmp_path / "root-link"
    symlink(tree, link, directory=True)
    _, result = crawl(link)
    assert rels(result) == ["inside/one.txt"]
    real_root = os.path.realpath(link)
    for f in result.files:
        assert Path(os.path.realpath(f.source.path)).is_relative_to(real_root)


def test_unreadable_directory_is_skipped_as_unreadable_without_failing(tree):
    put(tree, "locked/inside.txt", "hidden by permissions")
    put(tree, "open.txt")
    (tree / "locked").chmod(0)
    try:
        try:
            os.listdir(tree / "locked")
        except PermissionError:
            pass
        else:
            pytest.skip("permissions are not enforced here (running as root?)")
        _, result = crawl(tree)
    finally:
        (tree / "locked").chmod(0o755)
    assert rels(result) == ["open.txt"]
    assert skipped(result)["locked"] == "unreadable"


def test_real_path_of_every_entry_stays_inside_the_root(tree, tmp_path):
    put(tree, "a/one.txt")
    put(tree, "b/c/two.md")
    outside = put(tmp_path, "outside.txt")
    symlink(outside, tree / "a" / "out.txt")
    _, result = crawl(tree)
    base = tree.resolve()
    assert result.files
    for f in result.files:
        assert Path(f.source.path).resolve().is_relative_to(base)
        assert Path(f.source.path).resolve() == Path(f.source.path)


# ----------------------------------------------------------------------------- other skip reasons


def test_too_large_files_are_skipped_at_the_limit(tree):
    put(tree, "exact.txt", "x" * 100)
    put(tree, "over.txt", "y" * 101)
    _, result = crawl(tree, max_file_bytes=100)
    assert rels(result) == ["exact.txt"]
    assert skipped(result)["over.txt"] == "too_large"


def test_empty_files_are_skipped(tree):
    put(tree, "empty.txt", "")
    put(tree, "one.txt", "z")
    _, result = crawl(tree)
    assert rels(result) == ["one.txt"]
    assert skipped(result)["empty.txt"] == "empty"


@pytest.mark.parametrize("name", ["old.doc", "old.xls", "old.ppt", "OLD.DOC", "Old.Xls"])
def test_legacy_office_formats_are_reported(tree, name):
    put(tree, name, b"\xd0\xcf\x11\xe0 legacy")
    _, result = crawl(tree)
    assert result.files == []
    assert skipped(result)[name] == "legacy_office_format"


@pytest.mark.parametrize("name", ["image.png", "tool.exe", "data.json", "archive.zip", "README", "x.docm"])
def test_unsupported_types_are_reported(tree, name):
    put(tree, name, b"some bytes")
    _, result = crawl(tree)
    assert result.files == []
    assert skipped(result)[name] == "unsupported_type"


def test_include_globs_restrict_files_and_report_not_included(tree):
    put(tree, "docs/a.txt")
    put(tree, "docs/c.md")
    put(tree, "other/b.txt")
    _, result = crawl(tree, include=["docs/*.txt"])
    assert rels(result) == ["docs/a.txt"]
    sk = skipped(result)
    assert sk["docs/c.md"] == "not_included"
    assert sk["other/b.txt"] == "not_included"


def test_exclude_globs_win_over_include_and_report_excluded(tree):
    put(tree, "notes.md")
    put(tree, "drafts/x.txt")
    put(tree, "final/y.txt")
    _, result = crawl(tree, exclude=["*.md", "drafts/*"])
    assert rels(result) == ["final/y.txt"]
    sk = skipped(result)
    assert sk["notes.md"] == "excluded"
    assert sk["drafts/x.txt"] == "excluded" or sk.get("drafts") == "excluded"


def test_empty_include_means_all_supported_extensions(tree):
    put(tree, "a.txt")
    put(tree, "b.docx", b"PK\x03\x04")
    _, result = crawl(tree, include=[])
    assert rels(result) == ["a.txt", "b.docx"]


def test_depth_limit(tree):
    put(tree, "top.txt")
    put(tree, "a/near.txt")
    put(tree, "a/b/c/d/deep.txt")
    _, result = crawl(tree, CrawlLimits(max_depth=2))
    assert "top.txt" in rels(result) and "a/near.txt" in rels(result)
    assert "a/b/c/d/deep.txt" not in rels(result)
    assert "depth" in set(skipped(result).values())


def test_unreadable_files_are_skipped_not_fatal(tree):
    bad = put(tree, "bad.txt", "cannot be read")
    put(tree, "good.txt")
    bad.chmod(0)
    try:
        try:
            bad.read_bytes()
        except PermissionError:
            pass
        else:
            pytest.skip("permissions are not enforced here (running as root?)")
        _, result = crawl(tree)
    finally:
        bad.chmod(0o644)
    assert rels(result) == ["good.txt"]
    assert skipped(result)["bad.txt"] == "unreadable"


# ----------------------------------------------------------------------------- limits


def test_more_than_max_files_raises_and_exactly_max_files_does_not(tree):
    for i in range(4):
        put(tree, f"f{i}.txt", f"file number {i}")
    with pytest.raises(CrawlLimitError):
        crawl(tree, CrawlLimits(max_files=3))
    for p in (tree / "f3.txt",):
        p.unlink()
    assert len(crawl(tree, CrawlLimits(max_files=3))[1].files) == 3


def test_skipped_files_do_not_count_against_max_files(tree):
    for i in range(3):
        put(tree, f"f{i}.txt", f"file number {i}")
    for i in range(5):
        put(tree, f"u{i}.png", f"png {i}")
    put(tree, ".hidden.txt", "hidden")
    assert len(crawl(tree, CrawlLimits(max_files=3))[1].files) == 3


def test_more_than_max_total_bytes_raises(tree):
    put(tree, "a.txt", "a" * 10)
    put(tree, "b.txt", "b" * 10)
    with pytest.raises(CrawlLimitError):
        crawl(tree, CrawlLimits(max_total_bytes=15))
    assert len(crawl(tree, CrawlLimits(max_total_bytes=20))[1].files) == 2


def test_crawl_limit_error_is_an_exception_with_a_message(tree):
    put(tree, "a.txt")
    put(tree, "b.txt", "other")
    with pytest.raises(CrawlLimitError) as info:
        crawl(tree, CrawlLimits(max_files=1))
    assert str(info.value)
    assert isinstance(info.value, Exception)


def test_default_limits():
    d = CrawlLimits()
    assert (d.max_files, d.max_total_bytes, d.max_depth) == (5000, 2 * 1024**3, 20)


# ----------------------------------------------------------------------------- write_crawled_sources


def tenant_for(tmp_path: Path, tree: Path, listing: Path) -> Tenant:
    return Tenant.model_validate({
        "slug": "t", "name": "T", "languages": ["de", "en"], "system_prompt": "x",
        "crawl": [make_root(tree).model_dump(mode="json")],
        "crawled_sources": str(listing),
    })


def test_write_creates_listing_with_header_and_round_trips_through_load_tenant(tree, tmp_path):
    put(tree, "a/one.txt", "first distinct text")
    put(tree, "two.md", "# second distinct text")
    root, result = crawl(tree)
    listing = tmp_path / "t.crawled.yaml"
    tenant = tenant_for(tmp_path, tree, listing)
    write_crawled_sources(listing, tenant, {root.id: result})
    text = listing.read_text(encoding="utf-8")
    assert text.startswith("#")
    assert "GENERATED by ngo-assistant crawl" in text.splitlines()[0]
    assert "gitignored" in text.splitlines()[0]
    data = yaml.safe_load(text)
    assert [s["id"] for s in data["sources"]] == [f.source.id for f in result.files]
    assert all(s["kind"] == "file" for s in data["sources"])
    tenant_file = tmp_path / "t.yaml"
    tenant_file.write_text(yaml.safe_dump({
        "slug": "t", "name": "T", "languages": ["de", "en"], "system_prompt": "x",
        "crawl": [make_root(tree).model_dump(mode="json")], "crawled_sources": str(listing),
    }), encoding="utf-8")
    loaded = load_tenant(tenant_file)
    assert [s.model_dump() for s in loaded.sources] == [f.source.model_dump() for f in result.files]


def test_write_replaces_an_existing_listing_completely(tree, tmp_path):
    put(tree, "only.txt", "only file")
    root, result = crawl(tree)
    listing = tmp_path / "t.crawled.yaml"
    listing.write_text("sources:\n  - id: stale-entry\n", encoding="utf-8")
    write_crawled_sources(listing, tenant_for(tmp_path, tree, listing), {root.id: result})
    assert "stale-entry" not in listing.read_text(encoding="utf-8")


def test_write_is_atomic_a_failing_rename_leaves_no_partial_file(tree, tmp_path, monkeypatch):
    put(tree, "only.txt", "only file")
    root, result = crawl(tree)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    listing = out_dir / "t.crawled.yaml"

    def boom(*a, **k):
        raise OSError("simulated failure")

    for target in (os, "replace"), (os, "rename"), (Path, "replace"), (Path, "rename"):
        monkeypatch.setattr(*target, boom)
    with pytest.raises(OSError):
        write_crawled_sources(listing, tenant_for(tmp_path, tree, listing), {root.id: result})
    assert not listing.exists()
    assert list(out_dir.iterdir()) == []


def test_failing_rename_keeps_the_previous_listing_intact(tree, tmp_path, monkeypatch):
    put(tree, "only.txt", "only file")
    root, result = crawl(tree)
    listing = tmp_path / "t.crawled.yaml"
    listing.write_text("# previous\nsources: []\n", encoding="utf-8")

    def boom(*a, **k):
        raise OSError("simulated failure")

    for target in (os, "replace"), (os, "rename"), (Path, "replace"), (Path, "rename"):
        monkeypatch.setattr(*target, boom)
    with pytest.raises(OSError):
        write_crawled_sources(listing, tenant_for(tmp_path, tree, listing), {root.id: result})
    assert listing.read_text(encoding="utf-8") == "# previous\nsources: []\n"
    assert [p.name for p in tmp_path.iterdir() if p.name.startswith("t.crawled")] == ["t.crawled.yaml"]


def test_write_merges_the_results_of_several_roots(tmp_path):
    a, b = tmp_path / "ra", tmp_path / "rb"
    put(a, "x.txt", "text in a")
    put(b, "y.txt", "text in b")
    ra, rb = make_root(a, id="ra"), make_root(b, id="rb")
    results = {"ra": crawl_root(ra), "rb": crawl_root(rb)}
    listing = tmp_path / "t.crawled.yaml"
    tenant = Tenant.model_validate({
        "slug": "t", "name": "T", "languages": ["en"], "system_prompt": "x",
        "crawl": [ra.model_dump(mode="json"), rb.model_dump(mode="json")], "crawled_sources": str(listing),
    })
    write_crawled_sources(listing, tenant, results)
    ids = [s["id"] for s in yaml.safe_load(listing.read_text(encoding="utf-8"))["sources"]]
    assert ids == ["ra-x-txt", "rb-y-txt"]
