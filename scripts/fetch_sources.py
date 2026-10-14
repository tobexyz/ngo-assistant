#!/usr/bin/env python3
"""Fetch the real (non-synthetic) sources listed in a tenant file into data/raw/.

Polite by design (CLAUDE.md hard rules): fetches ONLY the listed URLs, checks robots.txt
first (unreachable robots.txt = disallow), honours Crawl-delay (minimum 1 s per host),
never follows redirects to another host, caps response size, skips existing files.
Stdlib only for networking; the tenant is loaded with ngo_assistant.config.load_tenant.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
import urllib.robotparser
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

USER_AGENT = (
    "ngo-assistant-course-project/0.1 (educational RAG project; respects robots.txt; fetches single pages only)"
)
TIMEOUT_S = 30.0
MAX_BYTES = 25 * 1024 * 1024
MIN_DELAY_S = 1.0
MAX_REDIRECTS = 5
SAFE_ID = re.compile(r"[a-z0-9][a-z0-9._-]*")  # same rule as ngo_assistant.config.Source.id


class FetchError(Exception):
    """Network-level problem (unreachable, too large, bad redirect)."""


@dataclass(frozen=True)
class Response:
    status: int
    headers: dict[str, str]  # lower-case keys
    body: bytes


# A raw fetcher performs exactly one HTTP request, never follows redirects, and raises
# FetchError if the body exceeds max_bytes. Tests inject fakes.
RawFetch = Callable[[str, str, float, int], Response]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        return None


def urllib_fetch(url: str, user_agent: str, timeout: float, max_bytes: int) -> Response:
    opener = urllib.request.build_opener(_NoRedirect)
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    try:
        resp = opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as e:  # includes 3xx (no redirect handler) and 4xx/5xx
        resp = e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise FetchError(f"request failed: {e}") from e
    try:
        body = resp.read(max_bytes + 1)
    except (TimeoutError, OSError) as e:
        raise FetchError(f"read failed: {e}") from e
    finally:
        resp.close()
    if len(body) > max_bytes:
        raise FetchError(f"response larger than {max_bytes} bytes")
    headers = {k.lower(): v for k, v in resp.headers.items()}
    return Response(status=resp.status if hasattr(resp, "status") else resp.code, headers=headers, body=body)


def valid_id(source_id: str) -> bool:
    return bool(SAFE_ID.fullmatch(source_id)) and ".." not in source_id


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def is_http(url: str) -> bool:
    return urlsplit(url).scheme in ("http", "https")


def extension_for(content_type: str) -> str:
    ct = content_type.lower()
    if "html" in ct:
        return "html"
    if "pdf" in ct:
        return "pdf"
    return "bin"


class Fetcher:
    """Rate-limited, redirect-restricted fetching with an injectable transport and clock."""

    def __init__(
        self,
        raw_fetch: RawFetch = urllib_fetch,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        user_agent: str = USER_AGENT,
        timeout: float = TIMEOUT_S,
        max_bytes: int = MAX_BYTES,
    ) -> None:
        self.raw_fetch = raw_fetch
        self.sleep = sleep
        self.clock = clock
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.crawl_delay: dict[str, float] = {}  # host -> seconds from robots.txt
        self._last: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    def _wait(self, host: str) -> None:
        delay = max(MIN_DELAY_S, self.crawl_delay.get(host, 0.0))
        if host in self._last:
            remaining = delay - (self.clock() - self._last[host])
            if remaining > 0:
                self.sleep(remaining)
        self._last[host] = self.clock()

    def get(self, url: str) -> Response:
        """GET one URL; follow redirects only within the same host. Raises FetchError."""
        host = host_of(url)
        for _ in range(MAX_REDIRECTS + 1):
            self._wait(host)
            resp = self.raw_fetch(url, self.user_agent, self.timeout, self.max_bytes)
            if len(resp.body) > self.max_bytes:
                raise FetchError(f"response larger than {self.max_bytes} bytes")
            if resp.status in (301, 302, 303, 307, 308):
                loc = resp.headers.get("location")
                if not loc:
                    raise FetchError(f"HTTP {resp.status} without Location")
                url = urljoin(url, loc)
                if not is_http(url) or host_of(url) != host:
                    raise FetchError(f"redirect to another host refused: {url}")
                continue
            return resp
        raise FetchError("too many redirects")

    def robots(self, url: str) -> urllib.robotparser.RobotFileParser | None:
        """Parsed robots.txt for the URL's host, or None if unreachable (= disallow all).

        4xx (e.g. 404) means no robots.txt exists, which allows everything (RFC 9309).
        5xx and network errors count as unreachable.
        """
        parts = urlsplit(url)
        host = parts.hostname or ""
        if host in self._robots:
            return self._robots[host]
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        rp: urllib.robotparser.RobotFileParser | None
        try:
            resp = self.get(robots_url)
        except FetchError:
            rp = None
        else:
            if resp.status >= 500:
                rp = None
            else:
                rp = urllib.robotparser.RobotFileParser()
                if resp.status >= 400:
                    rp.parse([])
                else:
                    rp.parse(resp.body.decode("utf-8", errors="replace").splitlines())
                delay = rp.crawl_delay(self.user_agent)
                if delay is not None:
                    self.crawl_delay[host] = float(delay)
        self._robots[host] = rp
        return rp

    def allowed(self, url: str) -> bool:
        rp = self.robots(url)
        return rp is not None and rp.can_fetch(self.user_agent, url)


def existing_file(out: Path, source_id: str) -> Path | None:
    for p in sorted(out.glob(f"{source_id}.*")):
        if not p.name.endswith(".meta.json"):
            return p
    return None


def fetch_source(
    source: Any, out: Path, fetcher: Fetcher, now: Callable[[], datetime] | None = None
) -> tuple[str, str]:
    """Fetch one source. Returns (status, detail); status is OK, SKIP or FAIL."""
    if not valid_id(source.id):
        return "FAIL", f"invalid source id {source.id!r}"
    out_root = out.resolve()
    for name in (f"{source.id}.html", f"{source.id}.meta.json"):
        if not (out_root / name).resolve().is_relative_to(out_root):
            return "FAIL", f"output path outside {out}: {name}"
    if existing_file(out, source.id) is not None:
        return "SKIP", f"already exists: {existing_file(out, source.id)}"
    if not fetcher.allowed(source.url):
        if fetcher.robots(source.url) is None:
            return "FAIL", "robots.txt unreachable, treated as disallow"
        return "FAIL", "refused: disallowed by robots.txt"
    try:
        resp = fetcher.get(source.url)
    except FetchError as e:
        return "FAIL", str(e)
    if resp.status != 200:
        return "FAIL", f"HTTP {resp.status}"
    content_type = resp.headers.get("content-type", "")
    target = out / f"{source.id}.{extension_for(content_type)}"
    out.mkdir(parents=True, exist_ok=True)
    target.write_bytes(resp.body)
    fetched_at = (now or (lambda: datetime.now(UTC)))()
    meta = {
        "id": source.id,
        "url": source.url,
        "fetched_at": fetched_at.isoformat(),
        "http_status": resp.status,
        "content_type": content_type,
        "sha256": hashlib.sha256(resp.body).hexdigest(),
        "licence": source.licence,
        "licence_url": source.licence_url,
        "redistributable": source.redistributable,
    }
    (out / f"{source.id}.meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return "OK", f"{target} ({len(resp.body)} bytes)"


def select_sources(sources: Sequence[Any], only: Sequence[str]) -> list[Any]:
    chosen = [s for s in sources if getattr(s, "kind", "") != "synthetic" and is_http(s.url)]
    if only:
        chosen = [s for s in chosen if s.id in only]
    return chosen


def run(
    args: argparse.Namespace, fetcher: Fetcher | None = None, out_stream: Any = None, err_stream: Any = None
) -> int:
    out_stream = out_stream or sys.stdout
    err_stream = err_stream or sys.stderr
    from ngo_assistant.config import load_tenant

    tenant = load_tenant(args.tenant)
    known = {s.id for s in tenant.sources}
    unknown = [i for i in args.only if i not in known]
    if unknown:
        print(f"unknown source id(s): {unknown}", file=err_stream)
        return 2
    out = Path(args.out)
    sources = select_sources(tenant.sources, args.only)
    fetcher = fetcher or Fetcher()
    failed = 0
    for s in sources:
        if not s.redistributable:
            print(
                f"NOTE {s.id}: not redistributable (licence: {s.licence}). The file must stay out of git "
                f"(data/raw/ is gitignored).",
                file=err_stream,
            )
        if args.dry_run:
            print(
                f"DRY  {s.id}: would fetch {s.url} -> {out}/{s.id}.<html|pdf|bin> "
                f"(redistributable={s.redistributable}, crawl delay unknown without network; "
                f"min {MIN_DELAY_S:.0f} s between requests)",
                file=out_stream,
            )
            continue
        status, detail = fetch_source(s, out, fetcher)
        print(f"{status:<4} {s.id}: {detail}", file=out_stream)
        if status == "FAIL":
            failed += 1
    print(f"{len(sources)} source(s) considered, {failed} failed", file=out_stream)
    return 1 if failed else 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tenant", required=True, help="path to the tenant YAML file")
    p.add_argument("--out", default="data/raw", help="output directory (default: data/raw)")
    p.add_argument("--dry-run", action="store_true", help="no network access; print what would be fetched")
    p.add_argument("--only", action="append", default=[], metavar="ID", help="fetch only this source id (repeatable)")
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    return run(parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
