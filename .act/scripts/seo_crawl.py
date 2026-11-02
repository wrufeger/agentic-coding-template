#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Crawl of a running site — the crawl half of skill `act-seo`. Starts at one base URL, follows the
#          internal links of the same origin (scheme, host, port) and reports per page the status code, the
#          redirects (chain, loop, target outside the site), the time to first byte, broken internal links
#          with the page they sit on, broken external links, and the same text under several URLs without a
#          shared canonical. Then it runs the page checks of `seo_check.py` (imported, not copied) on the
#          rendered HTML and merges all findings into one report by severity.
#          Starts no server (give it the URL of a site that already runs, e.g. the production build on the
#          test port), fixes nothing, writes no file, sends and stores no cookie.
#
# What goes out: requests to the base URL's origin (GET, redirects are not followed automatically but
#          recorded) and, unless --no-external, one `HEAD` request per external link. Only if a server
#          answers 405 to `HEAD` the same link is asked once with `GET`; its body is never read. External
#          requests are throttled per host (--external-delay, default 1 s between two requests to one host).
#          No page content leaves the machine. Only http and https are accepted; URLs with credentials
#          (`user:password@host`) are refused.
#
# Limits (options): --max-pages (internal URLs fetched, default 500), --max-depth (link hops from the
#          start page, default 10), --timeout (seconds per socket operation, default 10; a whole response must arrive within 3 x this), --max-bytes
#          (response size read, default 5 MB; a larger page is not parsed), --max-external, --max-time (whole crawl, default 30 min). Only responses
#          of type `text/html` are parsed; other internal targets are fetched for their status only.
#          The request carries its own User-Agent and no Cookie header.
#
# TTFB: time from sending the request to the end of the response headers. On localhost it says nothing about
#          the hosting (no network, no TLS, no CDN); the report says so.
#
# Findings (type, severity):
#   error    broken-link (an internal link answers 4xx/5xx or not at all; one finding per linking page),
#            fetch-failed (a Location-less redirect, or a URL nobody links to gave no answer), redirect-loop
#   warning  redirect-chain (more than one hop), external-link-broken (404/410/5xx),
#            external-link-unreachable (DNS, timeout), response-too-large
#   info     redirect (single hop), redirect-external (target outside the site), slow-ttfb,
#            external-link-blocked (401/403/429 and the like: probably a bot filter, check by hand),
#            crawl-limit (stopped at --max-pages, --max-external or --max-time), origin-changed (the start
#            page leads to the same host with another scheme, port or `www.`; the crawl continues there),
#            unparsed-encoding (Content-Encoding other than identity)
#   plus every finding type of seo_check.py, computed on the rendered pages (file = the page's URL), among
#   them duplicate-content: the same text under several URLs without a shared canonical (noindex pages
#   are left out).
#   A start page that leads to another site is not followed: exit 4.
#
# Library use: `crawl(base_url, CrawlOptions(...))` returns the report dict; `Fetcher.fetch` is the one place
#   that talks to the network and is replaceable (a later mode against a public URL reads `Response.headers`
#   and `Response.ttfb` from there).
#
# Usage:
#   python .act/scripts/seo_crawl.py BASE_URL [--max-pages N] [--max-depth N] [--timeout SEC] [--max-bytes N]
#                                    [--no-external] [--external-delay SEC] [--max-external N]
#                                    [--slow-ttfb MS] [--dup-threshold X] [--dup-min-words N] [--json]
#
# Exit code: 0 no warning or error, 1 at least one warning or error, 2 usage problem (bad URL or option),
#            4 the start page gave no response or leads to another site (nothing is crawled there).

from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import re
import statistics
import sys
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Deque, Dict, List, Mapping, Optional, Sequence, Tuple
from urllib.parse import SplitResult, quote, urldefrag, urljoin, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import seo_check  # noqa: E402  (sibling script, imported so the page checks exist once)

USER_AGENT = "act-seo-crawl/1.0 (site check of its owner; no cookies)"
DEFAULT_MAX_PAGES = 500
DEFAULT_MAX_DEPTH = 10
DEFAULT_TIMEOUT = 10.0
DEFAULT_MAX_BYTES = 5_000_000
DEFAULT_EXTERNAL_DELAY = 1.0
DEFAULT_MAX_EXTERNAL = 200
DEFAULT_SLOW_TTFB_MS = 600.0
MAX_REDIRECT_HOPS = 10
CHUNK = 65536
DEFAULT_PORTS = {"http": 80, "https": 443}
SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "sms:", "ftp:", "file:", "blob:", "about:")
BLOCKED_STATUS = {401, 403, 407, 429, 999}
DEFAULT_MAX_TIME = 1800.0

EXIT_FINDINGS = 1
EXIT_USAGE = 2
EXIT_NO_DATA = 4

CRAWL_SEVERITY: Dict[str, str] = {
    "broken-link": "error", "fetch-failed": "error", "redirect-loop": "error",
    "redirect-chain": "warning", "external-link-broken": "warning",
    "external-link-unreachable": "warning", "response-too-large": "warning",
    "redirect": "info", "redirect-external": "info", "slow-ttfb": "info", "external-link-blocked": "info",
    "crawl-limit": "info", "origin-changed": "info", "unparsed-encoding": "info",
}
SEVERITY: Dict[str, str] = {**CRAWL_SEVERITY, **seo_check.SEVERITY}
SEVERITY_ORDER = ("error", "warning", "info")


class UsageError(Exception):
    """An argument the script refuses to run with."""


@dataclass
class CrawlOptions:
    max_pages: int = DEFAULT_MAX_PAGES
    max_depth: int = DEFAULT_MAX_DEPTH
    timeout: float = DEFAULT_TIMEOUT
    max_bytes: int = DEFAULT_MAX_BYTES
    external: bool = True
    external_delay: float = DEFAULT_EXTERNAL_DELAY
    max_external: int = DEFAULT_MAX_EXTERNAL
    max_time: float = DEFAULT_MAX_TIME  # seconds for the whole crawl including external links
    slow_ttfb_ms: float = DEFAULT_SLOW_TTFB_MS
    dup_threshold: float = seo_check.Options.dup_threshold
    dup_min_words: int = seo_check.Options.dup_min_words


@dataclass
class Response:
    """One answer (or none). `ttfb` is seconds until the response headers arrived."""
    url: str
    status: int = 0
    headers: Dict[str, str] = field(default_factory=dict)  # lower-case names
    body: bytes = b""
    ttfb: float = 0.0
    truncated: bool = False
    error: str = ""

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()


@dataclass
class PageResult:
    url: str
    depth: int
    status: int = 0
    content_type: str = ""
    ttfb_ms: float = 0.0
    bytes: int = 0
    redirect_to: str = ""
    error: str = ""
    headers: Dict[str, str] = field(default_factory=dict)


class Fetcher:
    """The only code that opens a connection. No redirects followed, no cookies, own User-Agent."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT, user_agent: str = USER_AGENT,
                 clock: Callable[[], float] = time.perf_counter) -> None:
        self.timeout = timeout
        self.user_agent = user_agent
        self.clock = clock

    def fetch(self, url: str, method: str = "GET", read_body: bool = True,
              max_bytes: int = DEFAULT_MAX_BYTES) -> Response:
        parts = urlsplit(url)
        path = quote(parts.path or "/", safe="/%:@!$&'()*+,;=~-._")
        if parts.query:
            path += "?" + quote(parts.query, safe="%:@!$&'()*+,;=~-._/?")
        cls = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        resp = Response(url)
        conn = None
        try:
            conn = cls(parts.hostname or "", parts.port, timeout=self.timeout)
            started = self.clock()
            conn.request(method, path, headers={"User-Agent": self.user_agent, "Accept": "text/html,*/*;q=0.5",
                                                "Accept-Encoding": "identity", "Connection": "close"})
            raw = conn.getresponse()
            resp.ttfb = self.clock() - started
            resp.status = raw.status
            resp.headers = {k.lower(): v for k, v in raw.getheaders()}
            if read_body and method != "HEAD":
                deadline = started + self.timeout * 3  # the whole response, however slowly it trickles in
                chunks: List[bytes] = []
                size = 0
                while size <= max_bytes:
                    remaining = deadline - self.clock()
                    if remaining <= 0:
                        resp.error = f"response not complete after {self.timeout * 3:g} s"
                        break
                    if conn.sock is not None:
                        conn.sock.settimeout(remaining)
                    chunk = raw.read1(min(CHUNK, max_bytes + 1 - size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                data = b"".join(chunks)
                if len(data) > max_bytes:
                    resp.truncated = True
                    data = data[:max_bytes]
                resp.body = data
        except (OSError, http.client.HTTPException, ValueError) as exc:
            resp.error = f"{type(exc).__name__}: {exc}"
        finally:
            if conn is not None:
                conn.close()
        return resp


class Throttle:
    """At least `interval` seconds between the starts of two requests to one host."""

    def __init__(self, interval: float, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self.interval = interval
        self.clock = clock
        self.sleep = sleep
        self.last: Dict[str, float] = {}

    def wait(self, host: str) -> None:
        if host in self.last:
            remaining = self.last[host] + self.interval - self.clock()
            if remaining > 0:
                self.sleep(remaining)
        self.last[host] = self.clock()


def origin_of(url: str) -> Tuple[str, str, int]:
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    return scheme, (parts.hostname or "").lower(), parts.port or DEFAULT_PORTS.get(scheme, 0)


def rebuild(parts: SplitResult) -> str:
    """Canonical form: scheme and host in lower case, no user info, no default port, empty path -> `/`.
    A password in a link never reaches the output."""
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if ":" in host:
        host = f"[{host}]"
    port = parts.port
    netloc = host if port is None or port == DEFAULT_PORTS.get(scheme) else f"{host}:{port}"
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, ""))


def validate_base(url: str) -> str:
    """The normalized start URL, or UsageError naming what is wrong."""
    try:
        parts = urlsplit(url.strip())
        _ = parts.port  # raises ValueError on a bad port
    except ValueError as exc:
        raise UsageError(f"not a valid URL: {url!r} ({exc})")
    if parts.scheme not in ("http", "https"):
        raise UsageError(f"only http and https URLs are accepted, got {url!r}")
    if not parts.hostname:
        raise UsageError(f"no host in URL {url!r}")
    if parts.username is not None or parts.password is not None:
        raise UsageError("a URL with credentials (user:password@host) is refused; use the environment, "
                         "never the command line")
    return rebuild(parts)


def normalize(base: str, href: str) -> Optional[str]:
    """Canonical absolute http(s) URL without fragment for an href found on page `base`; None for anything else."""
    href = href.strip()
    if not href or href.startswith("#") or href.lower().startswith(SKIP_SCHEMES):
        return None
    try:
        parts = urlsplit(urldefrag(urljoin(base, href))[0])
        _ = parts.port  # raises ValueError on a bad port
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    return rebuild(parts)


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return address.is_loopback or address.is_unspecified


def same_site_host(a: str, b: str) -> bool:
    """Same host, or the same apart from a leading `www.` (apex <-> www)."""
    def strip(host: str) -> str:
        return host[4:] if host.startswith("www.") else host
    return bool(a) and strip(a) == strip(b)


class CrawlParser(seo_check.PageParser):
    """PageParser that also reads `<base href>`, against which the links of the page are resolved."""

    def __init__(self) -> None:
        super().__init__()
        self.base_href = ""

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        super().handle_starttag(tag, attrs)
        if tag == "base" and not self.base_href:
            self.base_href = dict(attrs).get("href") or ""


def decode_body(resp: Response) -> str:
    """Decode with the charset of the header, else of a `<meta>` in the first bytes, else UTF-8."""
    names = []
    match = re.search(r"charset=\s*[\"']?([\w.-]+)", resp.headers.get("content-type", ""), re.I)
    if match:
        names.append(match.group(1))
    meta = re.search(rb"<meta[^>]+charset\s*=\s*[\"']?\s*([\w.-]+)", resp.body[:2048], re.I)
    if meta:
        names.append(meta.group(1).decode("ascii", errors="ignore"))
    for enc in names + ["utf-8"]:
        try:
            return resp.body.decode(enc, errors="replace")
        except LookupError:
            continue
    return resp.body.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------------------------------------
# Crawl
# --------------------------------------------------------------------------------------------------------

def add_finding(findings: List[dict], kind: str, file: str, detail: str) -> None:
    findings.append({"type": kind, "file": file, "detail": detail, "severity": SEVERITY[kind]})


def crawl(base_url: str, options: Optional[CrawlOptions] = None, fetcher: Optional[Fetcher] = None,
          throttle: Optional[Throttle] = None, clock: Callable[[], float] = time.monotonic) -> dict:
    """Crawl the site of `base_url` and return the report dict (see render_text for the shape).
    `start_error` in the report is set when the start page gave no usable answer or leads to a foreign site."""
    options = options or CrawlOptions()
    fetcher = fetcher or Fetcher(options.timeout)
    throttle = throttle or Throttle(options.external_delay)
    start = validate_base(base_url)
    site = origin_of(start)
    began = clock()
    deadline = began + options.max_time
    findings: List[dict] = []
    notes: List[str] = []
    start_error = ""
    results: Dict[str, PageResult] = {}
    html: Dict[str, str] = {}
    sources: Dict[str, List[str]] = {}  # internal target -> pages (or redirecting URLs) that lead to it
    external: Dict[str, List[str]] = {}  # external link -> pages that carry it
    queue: Deque[Tuple[str, int]] = deque([(start, 0)])
    queued = {start}
    start_chain = {start}  # the start URL and the redirects it leads through

    def note_edge(table: Dict[str, List[str]], target: str, source: str) -> None:
        listed = table.setdefault(target, [])
        if source not in listed:
            listed.append(source)

    def enqueue(target: str, source: str, depth: int, follow: bool = True) -> None:
        if origin_of(target) == site:
            note_edge(sources, target, source)
            if follow and target not in queued:
                queued.add(target)
                queue.append((target, depth))
        else:
            note_edge(external, target, source)

    timed_out = False
    while queue:
        if len(results) >= options.max_pages:
            break
        if clock() > deadline:
            timed_out = True
            break
        url, depth = queue.popleft()
        resp = fetcher.fetch(url, "GET", True, options.max_bytes)
        result = PageResult(url, depth, resp.status, resp.content_type, round(resp.ttfb * 1000, 1),
                            len(resp.body), error=resp.error, headers=resp.headers)
        results[url] = result
        if resp.error:
            continue  # reported once by check_status, with the page that links here
        if 300 <= resp.status < 400:
            location = resp.headers.get("location", "")
            target = normalize(url, location) if location else None
            if target is None:
                add_finding(findings, "fetch-failed", url,
                            f"status {resp.status} without a usable Location header")
                continue
            result.redirect_to = target
            if url in start_chain and origin_of(target) != site:
                if same_site_host(origin_of(target)[1], site[1]):
                    add_finding(findings, "origin-changed", url, f"the start page leads to {target}; "
                                "the crawl continues there (same host, other scheme, port or www)")
                    site = origin_of(target)
                else:
                    start_error = f"the start page redirects to another site ({target}); nothing was crawled there"
                    break
            if url in start_chain:
                start_chain.add(target)
            enqueue(target, url, depth)
            continue
        if resp.status >= 400 or resp.content_type != "text/html":
            continue
        if resp.truncated:
            add_finding(findings, "response-too-large", url,
                        f"more than {options.max_bytes} bytes; not parsed, its links are not followed")
            continue
        if resp.headers.get("content-encoding", "identity").strip().lower() not in ("", "identity"):
            add_finding(findings, "unparsed-encoding", url, f"Content-Encoding {resp.headers['content-encoding']!r} "
                        "although identity was requested; not parsed")
            continue
        parser = CrawlParser()
        try:
            parser.feed(decode_body(resp))
            parser.close()
        except (AssertionError, ValueError, RecursionError):
            pass
        parser.info.file = url
        parser.info.kind = "document"
        html[url] = decode_body(resp)
        links_base = normalize(url, parser.base_href) if parser.base_href else None
        for href in parser.info.links:
            target = normalize(links_base or url, href)
            if target:
                enqueue(target, url, depth + 1, follow=depth < options.max_depth)
    unfetched = [u for u, _ in queue] if not start_error else []
    if unfetched:
        why = "the time limit --max-time" if timed_out else f"--max-pages {options.max_pages}"
        notes.append(f"stopped at {why}: {len(unfetched)} known URLs were not fetched")
        add_finding(findings, "crawl-limit", start, f"{len(unfetched)} URLs left in the queue at {why}; "
                    "raise it to see them")
    deeper = [t for t in sources if t not in results and t not in queued]
    if deeper:
        notes.append(f"{len(deeper)} links beyond --max-depth {options.max_depth} were not fetched")

    check_status(results, sources, findings, options, start)
    check_redirects(results, site, findings)

    ttfbs = [r.ttfb_ms for r in results.values() if r.status and not r.error]
    if is_loopback(site[1]):
        notes.append("TTFB was measured on localhost: it says nothing about the hosting (no network, TLS or CDN)")
    else:
        notes.append("TTFB includes network and TLS time of this machine, not the visitors'; "
                     "a single request is not a measurement series")

    # the page checks, including duplicate content against the canonical rule, run in seo_check
    seo_report = seo_check.check_documents(html, seo_check.Options(options.dup_threshold, options.dup_min_words))
    findings.extend(seo_report["findings"])
    notes.extend(seo_report["notes"])

    if start_error:
        notes.append(start_error)
    elif options.external:
        check_external(external, fetcher, throttle, options, findings, notes, deadline, clock)
    else:
        notes.append(f"external links were not checked (--no-external): {len(external)} found")

    order = {kind: i for i, kind in enumerate(SEVERITY)}
    findings.sort(key=lambda f: (SEVERITY_ORDER.index(f["severity"]), order.get(f["type"], 999)))
    statuses: Dict[str, int] = {}
    for r in results.values():
        key = str(r.status) if r.status and not r.error else "no response"
        statuses[key] = statuses.get(key, 0) + 1
    first = results.get(start)
    if not start_error and (first is None or (first.error and not first.status)):
        start_error = f"no response from the start page {start}"
    return {
        "base_url": start, "crawl_origin": f"{site[0]}://{site[1]}:{site[2]}", "start_error": start_error,
        "pages_fetched": len(results), "pages_parsed": len(html),
        "external_links": len(external), "statuses": statuses,
        "ttfb_ms": {"median": round(statistics.median(ttfbs), 1), "max": round(max(ttfbs), 1)} if ttfbs else {},
        "notes": notes, "pages": [_page_row(r) for r in results.values()],
        "findings": findings,
    }


def _page_row(r: PageResult) -> dict:
    row = asdict(r)
    row.pop("headers")  # kept on the PageResult for library users, not part of the report
    return row


def check_status(results: Mapping[str, PageResult], sources: Mapping[str, Sequence[str]],
                 findings: List[dict], options: CrawlOptions, start: str) -> None:
    """One finding per failing URL and linking page: broken-link where a page links to it, fetch-failed
    for a URL nobody links to (the start page)."""
    for url, r in results.items():
        if r.error or r.status >= 400:
            what = r.error if r.error else f"status {r.status}"
            linked_from = sources.get(url)
            if linked_from:
                for src in linked_from:
                    add_finding(findings, "broken-link", src, f"-> {url}  ({what})")
            elif r.error and not r.status:
                add_finding(findings, "fetch-failed", url, what)
            else:
                add_finding(findings, "broken-link", "(start page)", f"-> {url}  ({what})")
        elif r.status and not r.redirect_to and r.ttfb_ms > options.slow_ttfb_ms:
            add_finding(findings, "slow-ttfb", url, f"{r.ttfb_ms:.0f} ms to the first byte "
                        f"(limit {options.slow_ttfb_ms:.0f} ms)")


def check_redirects(results: Mapping[str, PageResult], site: tuple, findings: List[dict]) -> None:
    done_loops: set = set()
    for url, r in results.items():
        if not r.redirect_to:
            continue
        chain = [url]
        current = url
        loop = False
        while True:
            step = results.get(current)
            if step is None or not step.redirect_to:
                break
            current = step.redirect_to
            if current in chain:
                loop = True
                chain.append(current)
                break
            chain.append(current)
            if len(chain) > MAX_REDIRECT_HOPS:
                break
        shown = "  ->  ".join(chain)
        if loop:
            members = frozenset(chain[chain.index(chain[-1]):])
            if members not in done_loops:
                done_loops.add(members)
                add_finding(findings, "redirect-loop", url, shown)
        elif len(chain) > 2:
            add_finding(findings, "redirect-chain", url, f"{len(chain) - 1} hops: {shown}")
        elif origin_of(r.redirect_to) != site:
            add_finding(findings, "redirect-external", url, f"{r.status} -> {r.redirect_to}")
        else:
            add_finding(findings, "redirect", url, f"{r.status} -> {r.redirect_to}")
        if not loop and len(chain) > 2 and origin_of(chain[-1]) != site:
            add_finding(findings, "redirect-external", url, f"the chain ends outside the site: {chain[-1]}")


def check_external(external: Mapping[str, Sequence[str]], fetcher: Fetcher, throttle: Throttle,
                   options: CrawlOptions, findings: List[dict], notes: List[str], deadline: float,
                   clock: Callable[[], float]) -> None:
    targets = list(external)
    if len(targets) > options.max_external:
        notes.append(f"only the first {options.max_external} of {len(targets)} external links were checked "
                     "(--max-external)")
        add_finding(findings, "crawl-limit", "(external links)",
                    f"{len(targets) - options.max_external} external links not checked (--max-external)")
        targets = targets[:options.max_external]
    for done, url in enumerate(targets):
        if clock() > deadline:
            notes.append(f"stopped at --max-time: {len(targets) - done} external links not checked")
            break
        host = (urlsplit(url).hostname or "").lower()
        throttle.wait(host)
        resp = fetcher.fetch(url, "HEAD", False, options.max_bytes)
        if resp.status == 405 and not resp.error:
            throttle.wait(host)
            resp = fetcher.fetch(url, "GET", False, options.max_bytes)  # headers only, body never read
        where = ", ".join(external[url][:3]) + (f" (+{len(external[url]) - 3})" if len(external[url]) > 3 else "")
        if resp.error and not resp.status:
            add_finding(findings, "external-link-unreachable", external[url][0],
                        f"{url}  ({resp.error})  also on: {where}" if len(external[url]) > 1 else f"{url}  ({resp.error})")
        elif resp.status in BLOCKED_STATUS:
            add_finding(findings, "external-link-blocked", external[url][0],
                        f"{url}  (status {resp.status}, probably refuses scripts; open it by hand)")
        elif resp.status >= 400:
            for src in external[url]:
                add_finding(findings, "external-link-broken", src, f"-> {url}  (status {resp.status})")


# --------------------------------------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------------------------------------

def render_text(report: dict) -> str:
    lines = [f"crawl of {report['base_url']}: {report['pages_fetched']} URLs fetched, "
             f"{report['pages_parsed']} HTML pages checked, {report['external_links']} external links found",
             "status codes: " + ", ".join(f"{k}: {v}" for k, v in sorted(report["statuses"].items()))]
    if report["ttfb_ms"]:
        lines.append(f"TTFB: median {report['ttfb_ms']['median']} ms, max {report['ttfb_ms']['max']} ms")
    lines += [f"note: {n}" for n in report["notes"]]
    findings = report["findings"]
    if not findings:
        lines.append("\nNo findings.")
        return "\n".join(lines)
    for severity in SEVERITY_ORDER:
        of_severity = [f for f in findings if f["severity"] == severity]
        if not of_severity:
            continue
        lines.append(f"\n{severity.upper()} ({len(of_severity)})")
        for kind in SEVERITY:
            items = [f for f in of_severity if f["type"] == kind]
            if not items:
                continue
            lines.append(f"{kind}: {len(items)}")
            for item in items[:30]:
                lines.append(f"  {item['file']}  - {item['detail']}")
            if len(items) > 30:
                lines.append(f"  ... {len(items) - 30} more (use --json)")
    return "\n".join(lines)


def exit_code(report: dict) -> int:
    if report["start_error"]:
        return EXIT_NO_DATA
    return EXIT_FINDINGS if any(f["severity"] in ("error", "warning") for f in report["findings"]) else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Crawl a running site from one base URL (same origin only): status codes, redirects, TTFB, "
                    "broken internal and external links, duplicate pages, then the seo_check.py page checks on "
                    "the rendered HTML. Starts no server and writes no file. Outgoing traffic: GET requests to "
                    "the site itself and, unless --no-external, one HEAD request per external link (throttled "
                    "per host; GET only after a 405, headers only). No cookie, no page content leaves the "
                    "machine.")
    p.add_argument("base_url", help="http(s) URL of the running site, e.g. http://127.0.0.1:3100/")
    p.add_argument("--max-pages", type=int, default=DEFAULT_MAX_PAGES,
                   help="internal URLs fetched at most (default %(default)s)")
    p.add_argument("--max-depth", type=int, default=DEFAULT_MAX_DEPTH,
                   help="link hops from the start page (default %(default)s)")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="seconds per request (default %(default)s)")
    p.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES,
                   help="largest response read; a larger page is not parsed (default %(default)s)")
    p.add_argument("--no-external", action="store_true", help="do not check external links (nothing leaves the site)")
    p.add_argument("--external-delay", type=float, default=DEFAULT_EXTERNAL_DELAY,
                   help="seconds between two requests to one external host (default %(default)s)")
    p.add_argument("--max-external", type=int, default=DEFAULT_MAX_EXTERNAL,
                   help="external links checked at most (default %(default)s)")
    p.add_argument("--max-time", type=float, default=DEFAULT_MAX_TIME,
                   help="seconds for the whole crawl, external links included (default %(default)s)")
    p.add_argument("--slow-ttfb", type=float, default=DEFAULT_SLOW_TTFB_MS,
                   help="TTFB in ms from which a page is reported (default %(default)s)")
    p.add_argument("--dup-threshold", type=float, default=seo_check.Options.dup_threshold,
                   help="share of identical text for the near-copy check of seo_check (default %(default)s)")
    p.add_argument("--dup-min-words", type=int, default=seo_check.Options.dup_min_words,
                   help="pages with fewer words are not compared (default %(default)s)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    problems = []
    if args.max_pages < 1:
        problems.append("--max-pages must be at least 1")
    if args.max_depth < 0:
        problems.append("--max-depth must be 0 or more")
    if args.timeout <= 0:
        problems.append("--timeout must be above 0")
    if args.max_bytes < 1:
        problems.append("--max-bytes must be at least 1")
    if args.external_delay < 0 or args.max_external < 0 or args.slow_ttfb < 0 or args.max_time <= 0:
        problems.append("--external-delay, --max-external and --slow-ttfb must not be negative, --max-time above 0")
    if not 0 < args.dup_threshold <= 1 or args.dup_min_words < 1:
        problems.append("--dup-threshold must be above 0 and at most 1, --dup-min-words at least 1")
    if problems:
        print("seo_crawl: " + "; ".join(problems), file=sys.stderr)
        return EXIT_USAGE
    options = CrawlOptions(args.max_pages, args.max_depth, args.timeout, args.max_bytes, not args.no_external,
                           args.external_delay, args.max_external, args.max_time, args.slow_ttfb,
                           args.dup_threshold, args.dup_min_words)
    try:
        report = crawl(args.base_url, options)
    except UsageError as exc:
        print(f"seo_crawl: {exc}", file=sys.stderr)
        return EXIT_USAGE
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else render_text(report))
    code = exit_code(report)
    if code == EXIT_NO_DATA:
        print(f"seo_crawl: {report['start_error']}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
