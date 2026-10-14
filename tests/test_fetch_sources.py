"""Tests for scripts/fetch_sources.py. No network: transport, sleep and clock are fakes."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "fetch_sources", Path(__file__).resolve().parents[1] / "scripts" / "fetch_sources.py"
)
assert _SPEC and _SPEC.loader
fs = importlib.util.module_from_spec(_SPEC)
sys.modules["fetch_sources"] = fs
_SPEC.loader.exec_module(fs)

TENANT = """\
slug: t
name: T
languages: [en]
system_prompt: p
sources:
  - {id: a, title: A, url: "https://ok.example/a", language: en, kind: web, licence: CC BY 4.0,
     licence_url: "https://ok.example/l", redistributable: true, checked_on: 2026-10-14}
  - {id: b, title: B, url: "https://slow.example/b", language: de, kind: pdf, licence: CC BY-NC-ND 4.0,
     licence_url: "https://slow.example/l", redistributable: false, checked_on: 2026-10-14}
"""

ROBOTS_OK = b"User-agent: *\nDisallow: /private\n"
HTML = {"content-type": "text/html; charset=utf-8"}


class FakeNet:
    def __init__(self, routes: dict[str, fs.Response | Exception]) -> None:
        self.routes = routes
        self.calls: list[str] = []

    def __call__(self, url: str, ua: str, timeout: float, max_bytes: int) -> fs.Response:
        self.calls.append(url)
        r = self.routes.get(url)
        if r is None:
            return fs.Response(404, {}, b"")
        if isinstance(r, Exception):
            raise r
        return r


def robots(host: str, body: bytes = ROBOTS_OK) -> dict:
    return {f"https://{host}/robots.txt": fs.Response(200, {}, body)}


def make_fetcher(net: FakeNet, sleeps: list[float] | None = None, **kw) -> fs.Fetcher:
    clock = {"t": 0.0}
    sl = sleeps if sleeps is not None else []

    def sleep(s: float) -> None:
        sl.append(s)
        clock["t"] += s

    return fs.Fetcher(raw_fetch=net, sleep=sleep, clock=lambda: clock["t"], **kw)


def src(**kw):
    d = {
        "id": "a",
        "url": "https://ok.example/a",
        "licence": "CC BY 4.0",
        "licence_url": "https://ok.example/l",
        "redistributable": True,
        "kind": "web",
    }
    d.update(kw)
    return SimpleNamespace(**d)


def args(tmp_path: Path, **kw):
    t = tmp_path / "t.yaml"
    t.write_text(TENANT, encoding="utf-8")
    d = {"tenant": str(t), "out": str(tmp_path / "raw"), "dry_run": False, "only": []}
    d.update(kw)
    return SimpleNamespace(**d)


def test_dry_run_does_no_fetch(tmp_path: Path) -> None:
    net = FakeNet({})
    out, err = io.StringIO(), io.StringIO()
    rc = fs.run(args(tmp_path, dry_run=True), make_fetcher(net), out, err)
    assert rc == 0 and net.calls == []
    text = out.getvalue()
    assert "https://ok.example/a" in text and "crawl delay unknown" in text and "redistributable=False" in text
    assert "must stay out of git" in err.getvalue()
    assert not (tmp_path / "raw").exists()


def test_synthetic_and_non_http_skipped() -> None:
    srcs = [src(id="s", kind="synthetic", url="data/synthetic/s.md"), src(id="f", url="file:///x"), src(id="a")]
    assert [s.id for s in fs.select_sources(srcs, [])] == ["a"]
    assert fs.select_sources(srcs, ["zzz"]) == []


def test_fetch_ok_writes_file_and_meta(tmp_path: Path) -> None:
    net = FakeNet({**robots("ok.example"), "https://ok.example/a": fs.Response(200, HTML, b"<html>hi</html>")})
    status, _ = fs.fetch_source(src(), tmp_path, make_fetcher(net))
    assert status == "OK"
    assert (tmp_path / "a.html").read_bytes() == b"<html>hi</html>"
    meta = json.loads((tmp_path / "a.meta.json").read_text(encoding="utf-8"))
    assert meta["url"] == "https://ok.example/a" and meta["http_status"] == 200
    assert meta["content_type"] == HTML["content-type"]
    assert meta["sha256"] == hashlib.sha256(b"<html>hi</html>").hexdigest()
    assert meta["licence"] == "CC BY 4.0" and meta["licence_url"] == "https://ok.example/l"
    assert meta["redistributable"] is True and meta["fetched_at"].endswith("+00:00")


def test_extension_from_content_type() -> None:
    assert fs.extension_for("application/pdf") == "pdf"
    assert fs.extension_for("text/html") == "html"
    assert fs.extension_for("application/octet-stream") == "bin"


def test_disallowed_by_robots_refused(tmp_path: Path) -> None:
    net = FakeNet(robots("ok.example", b"User-agent: *\nDisallow: /a\n"))
    status, detail = fs.fetch_source(src(), tmp_path, make_fetcher(net))
    assert status == "FAIL" and "disallowed" in detail
    assert "https://ok.example/a" not in net.calls and not list(tmp_path.glob("a.*"))


def test_unreachable_robots_is_disallow(tmp_path: Path) -> None:
    net = FakeNet({"https://ok.example/robots.txt": fs.FetchError("down")})
    status, detail = fs.fetch_source(src(), tmp_path, make_fetcher(net))
    assert status == "FAIL" and "unreachable" in detail
    assert net.calls == ["https://ok.example/robots.txt"]


def test_robots_5xx_is_disallow(tmp_path: Path) -> None:
    net = FakeNet({"https://ok.example/robots.txt": fs.Response(503, {}, b"")})
    assert fs.fetch_source(src(), tmp_path, make_fetcher(net))[0] == "FAIL"


def test_existing_file_skipped(tmp_path: Path) -> None:
    (tmp_path / "a.pdf").write_bytes(b"old")
    net = FakeNet({})
    status, _ = fs.fetch_source(src(), tmp_path, make_fetcher(net))
    assert status == "SKIP" and net.calls == [] and (tmp_path / "a.pdf").read_bytes() == b"old"


def test_crawl_delay_honoured(tmp_path: Path) -> None:
    net = FakeNet(
        {
            **robots("slow.example", b"User-agent: *\nCrawl-delay: 10\n"),
            "https://slow.example/b": fs.Response(200, HTML, b"x"),
            "https://slow.example/c": fs.Response(200, HTML, b"y"),
        }
    )
    sleeps: list[float] = []
    f = make_fetcher(net, sleeps)
    assert fs.fetch_source(src(id="b", url="https://slow.example/b"), tmp_path, f)[0] == "OK"
    assert fs.fetch_source(src(id="c", url="https://slow.example/c"), tmp_path, f)[0] == "OK"
    assert f.crawl_delay["slow.example"] == 10.0
    assert sleeps == [10.0, 10.0]  # robots->page, page->page, each exactly the delay (fake clock)


def test_minimum_delay_without_crawl_delay(tmp_path: Path) -> None:
    net = FakeNet({**robots("ok.example"), "https://ok.example/a": fs.Response(200, HTML, b"x")})
    sleeps: list[float] = []
    fs.fetch_source(src(), tmp_path, make_fetcher(net, sleeps))
    assert sleeps == [1.0]


def test_size_cap(tmp_path: Path) -> None:
    net = FakeNet({**robots("ok.example", b""), "https://ok.example/a": fs.Response(200, HTML, b"x" * 11)})
    status, detail = fs.fetch_source(src(), tmp_path, make_fetcher(net, max_bytes=10))
    assert status == "FAIL" and "larger" in detail and not list(tmp_path.glob("a.*"))


def test_redirect_same_host_followed(tmp_path: Path) -> None:
    net = FakeNet(
        {
            **robots("ok.example"),
            "https://ok.example/a": fs.Response(301, {"location": "/a2"}, b""),
            "https://ok.example/a2": fs.Response(200, HTML, b"z"),
        }
    )
    assert fs.fetch_source(src(), tmp_path, make_fetcher(net))[0] == "OK"


def test_redirect_to_other_host_refused(tmp_path: Path) -> None:
    net = FakeNet(
        {
            **robots("ok.example"),
            "https://ok.example/a": fs.Response(302, {"location": "https://evil.example/a"}, b""),
        }
    )
    status, detail = fs.fetch_source(src(), tmp_path, make_fetcher(net))
    assert status == "FAIL" and "another host" in detail
    assert "https://evil.example/a" not in net.calls


def test_http_error_status_fails(tmp_path: Path) -> None:
    net = FakeNet(robots("ok.example"))  # page itself 404
    assert fs.fetch_source(src(), tmp_path, make_fetcher(net))[0] == "FAIL"


def test_run_exit_codes(tmp_path: Path) -> None:
    good = FakeNet(
        {
            **robots("ok.example"),
            **robots("slow.example"),
            "https://ok.example/a": fs.Response(200, HTML, b"x"),
            "https://slow.example/b": fs.Response(200, {"content-type": "application/pdf"}, b"%PDF"),
        }
    )
    out = io.StringIO()
    assert fs.run(args(tmp_path), make_fetcher(good), out, io.StringIO()) == 0
    assert (tmp_path / "raw" / "b.pdf").exists()

    bad = FakeNet({**robots("ok.example")})  # a: 404 page, b: robots 404 + page 404
    assert fs.run(args(tmp_path, out=str(tmp_path / "raw2")), make_fetcher(bad), io.StringIO(), io.StringIO()) == 1


def test_only_filter_and_unknown_id(tmp_path: Path) -> None:
    net = FakeNet({**robots("ok.example"), "https://ok.example/a": fs.Response(200, HTML, b"x")})
    assert fs.run(args(tmp_path, only=["a"]), make_fetcher(net), io.StringIO(), io.StringIO()) == 0
    assert not (tmp_path / "raw" / "b.pdf").exists()
    assert fs.run(args(tmp_path, only=["nope"]), make_fetcher(net), io.StringIO(), io.StringIO()) == 2


def test_user_agent_has_no_email() -> None:
    assert "@" not in fs.USER_AGENT and "ngo-assistant" in fs.USER_AGENT


@pytest.mark.parametrize(
    "url,ok", [("https://x/y", True), ("http://x", True), ("file:///x", False), ("data/x.md", False)]
)
def test_is_http(url: str, ok: bool) -> None:
    assert fs.is_http(url) is ok


@pytest.mark.parametrize("bad", ["../../x", "a/b", "a*", "..", "", "A", "a..b", "-a"])
def test_fetch_source_rejects_unsafe_id_without_network(tmp_path: Path, bad: str) -> None:
    net = FakeNet({})
    out = tmp_path / "raw"
    status, detail = fs.fetch_source(src(id=bad), out, make_fetcher(net))
    assert status == "FAIL" and "invalid source id" in detail
    assert net.calls == [] and not list(tmp_path.rglob("*.meta.json"))


def test_output_path_must_stay_inside_out(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Defence in depth: even if the id check were bypassed, the resolved path is verified.
    monkeypatch.setattr(fs, "valid_id", lambda _i: True)
    net = FakeNet({**robots("ok.example"), "https://ok.example/a": fs.Response(200, HTML, b"x")})
    out = tmp_path / "raw"
    status, detail = fs.fetch_source(src(id="../escape"), out, make_fetcher(net))
    assert status == "FAIL" and "outside" in detail
    assert not (tmp_path / "escape.html").exists()


def test_run_rejects_unsafe_id_from_stub_tenant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = SimpleNamespace(sources=[src(id="../../x")])
    monkeypatch.setattr("ngo_assistant.config.load_tenant", lambda _p: stub)
    net = FakeNet({})
    rc = fs.run(args(tmp_path), make_fetcher(net), io.StringIO(), io.StringIO())
    assert rc == 1 and net.calls == []


def test_robots_404_allows_everything(tmp_path: Path) -> None:
    net = FakeNet({"https://ok.example/a": fs.Response(200, HTML, b"x")})  # robots.txt -> 404 default
    f = make_fetcher(net)
    assert f.allowed("https://ok.example/a") is True
    assert fs.fetch_source(src(), tmp_path, f)[0] == "OK"


def test_robots_403_allows(tmp_path: Path) -> None:
    net = FakeNet({"https://ok.example/robots.txt": fs.Response(403, {}, b"")})
    assert make_fetcher(net).allowed("https://ok.example/a") is True


def test_redirect_loop_hits_limit(tmp_path: Path) -> None:
    net = FakeNet(
        {
            **robots("ok.example"),
            "https://ok.example/a": fs.Response(302, {"location": "/b"}, b""),
            "https://ok.example/b": fs.Response(302, {"location": "/a"}, b""),
        }
    )
    status, detail = fs.fetch_source(src(), tmp_path, make_fetcher(net))
    assert status == "FAIL" and "too many redirects" in detail
    assert len([c for c in net.calls if not c.endswith("robots.txt")]) == fs.MAX_REDIRECTS + 1


def test_redirect_without_location_fails(tmp_path: Path) -> None:
    net = FakeNet({**robots("ok.example"), "https://ok.example/a": fs.Response(301, {}, b"")})
    status, detail = fs.fetch_source(src(), tmp_path, make_fetcher(net))
    assert status == "FAIL" and "Location" in detail


def test_file_sources_are_explicitly_skipped_and_never_fetched(tmp_path: Path) -> None:
    srcs = [src(id="r-f", kind="file", url="file:r/doc.txt"), src(id="a")]
    assert [s.id for s in fs.select_sources(srcs, [])] == ["a"]
    # even a file source whose url looks like http is never selected
    sneaky = src(id="r-g", kind="file", url="https://ok.example/should-not-be-fetched")
    assert fs.select_sources([sneaky], []) == []
    assert fs.select_sources([sneaky], ["r-g"]) == []


def test_run_with_file_sources_makes_no_network_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = SimpleNamespace(sources=[src(id="r-f", kind="file", url="file:r/doc.txt", redistributable=False)])
    monkeypatch.setattr("ngo_assistant.config.load_tenant", lambda _p: stub)
    net = FakeNet({})
    out = io.StringIO()
    rc = fs.run(args(tmp_path), make_fetcher(net), out, io.StringIO())
    assert rc == 0 and net.calls == []
    assert not (tmp_path / "raw").exists()
    assert "0 source(s) considered" in out.getvalue()


def test_file_source_ids_are_known_ids_for_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stub = SimpleNamespace(sources=[src(id="r-f", kind="file", url="file:r/doc.txt"), src(id="a")])
    monkeypatch.setattr("ngo_assistant.config.load_tenant", lambda _p: stub)
    net = FakeNet({**robots("ok.example"), "https://ok.example/a": fs.Response(200, HTML, b"x")})
    assert fs.run(args(tmp_path, only=["r-f"]), make_fetcher(net), io.StringIO(), io.StringIO()) == 0
    assert net.calls == []
