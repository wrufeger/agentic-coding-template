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
# More start points: the `hreflang` alternates of every page and the entries of the site's sitemap are followed
#          too, so translated pages that no link leads to (a language switch built as a <select>) are reached. The
#          sitemap is read from `<link rel="sitemap">`, else from `sitemap-index.xml` or `sitemap.xml` in the folder
#          of the start URL (an index and its files up to a limit), and only when a page hints at one: a sitemap
#          link, hreflang links or an absolute canonical link on another host. An alternate or sitemap entry on
#          the production address (the host of the page's absolute canonical link) with a path under the start
#          URL's folder is mapped to the crawl origin; anything else on another host is not followed.
#   warning  sitemap-not-reached (some sitemap URLs were not reached: count and examples)
#   info     trailing-slash-variant (`/de` and `/de/` return the same page: reported once with the linking page
#            instead of as duplicate title, duplicate description or orphan page; the checks run on one form)
#
# Public site (--public): the same crawl against a domain on the internet, read-only and throttled: at least
#          --delay seconds (default 1) between two requests to the site, internal ones included, and a
#          default of 100 pages. On top of the page findings it checks the HTTP headers: HSTS, Content-Security-
#          Policy, X-Content-Type-Options and Referrer-Policy on the HTML pages (one finding per header, with the
#          number of pages it is missing on), compression of the start page and of up to --max-assets scripts and
#          stylesheets (one extra GET each, body never read), caching of those assets and of the HTML, and
#          whether plain `http://` leads to `https://`. TTFB is then a real measurement from this machine (one
#          request per page, not a series; it includes network and TLS time). Findings added by this mode:
#   warning  missing-hsts, missing-nosniff, no-compression, asset-not-cached, no-https-redirect
#   info     missing-csp, missing-referrer-policy, weak-hsts, asset-short-cache, html-no-cache-header,
#            asset-blocked (an asset answered 401/403/429 to the check)
#          Nothing is written, nothing is sent but the requests above; no page content leaves the machine.
#
# Library use: `crawl(base_url, CrawlOptions(...))` returns the report dict; `Fetcher.fetch` is the one place
#   that talks to the network and is replaceable.
#
# Usage:
#   python .act/scripts/seo_crawl.py BASE_URL [--max-pages N] [--max-depth N] [--timeout SEC] [--max-bytes N]
#                                    [--no-external] [--external-delay SEC] [--max-external N]
#                                    [--slow-ttfb MS] [--dup-threshold X] [--dup-min-words N] [--json]
#                                    [--public] [--delay SEC] [--max-assets N]
#
# Exit code: 0 no warning or error, 1 at least one warning or error, 2 usage problem (bad URL or option),
#            4 the start page gave no response or leads to another site (nothing is crawled there).

from __future__ import annotations

import argparse
import html as html_module
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
DEFAULT_MAX_ASSETS = 10
PUBLIC_DELAY = 1.0
PUBLIC_MAX_PAGES = 100
HTTPS_HOPS = 3  # same-host steps over http followed when checking the redirect to https
SHORT_CACHE_SECONDS = 86400  # an asset cached for less than a day is reported
HSTS_MIN_SECONDS = 15552000  # 180 days
MAX_SITEMAP_FILES = 20  # sitemap files read (an index counts as one)
MAX_SITEMAP_URLS = 5000
COMPRESS_MIN_BYTES = 1400  # below roughly one packet compression gains nothing
COMPRESSIBLE_TYPES = ("text/", "application/javascript", "application/json", "application/xml",
                      "image/svg+xml", "application/xhtml+xml", "application/manifest+json")

EXIT_FINDINGS = 1
EXIT_USAGE = 2
EXIT_NO_DATA = 4

CRAWL_SEVERITY: Dict[str, str] = {
    "broken-link": "error", "fetch-failed": "error", "redirect-loop": "error",
    "redirect-chain": "warning", "external-link-broken": "warning",
    "external-link-unreachable": "warning", "response-too-large": "warning",
    "redirect": "info", "redirect-external": "info", "slow-ttfb": "info", "external-link-blocked": "info",
    "crawl-limit": "info", "origin-changed": "info", "unparsed-encoding": "info",
    "missing-hsts": "warning", "missing-nosniff": "warning", "no-compression": "warning",
    "asset-not-cached": "warning", "no-https-redirect": "warning",
    "missing-csp": "info", "missing-referrer-policy": "info", "weak-hsts": "info",
    "asset-short-cache": "info", "html-no-cache-header": "info", "asset-blocked": "info",
    "sitemap-not-reached": "warning", "trailing-slash-variant": "info",
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
    public: bool = False  # header checks, assets, http -> https; throttled
    delay: Optional[float] = None  # seconds between two requests to the site itself; None = 0, with public 1
    max_assets: int = DEFAULT_MAX_ASSETS

    def __post_init__(self) -> None:
        if self.delay is None:
            self.delay = PUBLIC_DELAY if self.public else 0.0


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
              max_bytes: int = DEFAULT_MAX_BYTES, accept_encoding: str = "identity") -> Response:
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
                                                "Accept-Encoding": accept_encoding, "Connection": "close"})
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
        self.assets: List[str] = []  # script src and stylesheet href, as written
        self.sitemap_hrefs: List[str] = []  # <link rel="sitemap"> targets, as written

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        super().handle_starttag(tag, attrs)
        values = {k.lower(): (v or "") for k, v in attrs}
        if tag == "base" and not self.base_href:
            self.base_href = values.get("href", "")
        elif tag == "script" and values.get("src", "").strip():
            self.assets.append(values["src"].strip())
        elif tag == "link" and "stylesheet" in values.get("rel", "").lower().split() and values.get("href", "").strip():
            self.assets.append(values["href"].strip())
        elif tag == "link" and "sitemap" in values.get("rel", "").lower().split() and values.get("href", "").strip():
            self.sitemap_hrefs.append(values["href"].strip())


def sitemap_locs(text: str) -> Tuple[bool, List[str]]:
    """(is a sitemap index, the `<loc>` entries) of a sitemap file. Regular expressions, no XML parser: a sitemap
    comes from the network and must not be able to expand entities."""
    is_index = bool(re.search(r"<(?:\w+:)?sitemapindex[\s>]", text, re.I))
    locs = [html_module.unescape(m.strip()) for m in re.findall(r"<(?:\w+:)?loc\s*>(.*?)</(?:\w+:)?loc\s*>", text, re.I | re.S)]
    return is_index, [loc for loc in locs if loc]


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
          throttle: Optional[Throttle] = None, clock: Callable[[], float] = time.monotonic,
          site_throttle: Optional[Throttle] = None) -> dict:
    """Crawl the site of `base_url` and return the report dict (see render_text for the shape).
    `start_error` in the report is set when the start page gave no usable answer or leads to a foreign site."""
    options = options or CrawlOptions()
    fetcher = fetcher or Fetcher(options.timeout)
    throttle = throttle or Throttle(options.external_delay)
    site_throttle = site_throttle or Throttle(options.delay)
    start = validate_base(base_url)
    site = origin_of(start)
    began = clock()
    deadline = began + options.max_time
    findings: List[dict] = []
    notes: List[str] = []
    start_error = ""
    results: Dict[str, PageResult] = {}
    html: Dict[str, str] = {}
    page_assets: Dict[str, List[str]] = {}  # asset URL -> pages that load it (public mode)
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
    base_path = urlsplit(start).path or "/"
    base_path = base_path[:base_path.rfind("/") + 1]  # the directory the crawl starts in, e.g. /docs/
    prod_origins: set = set()  # origins named by absolute canonical links that are not the crawl origin
    page_prod: Dict[str, tuple] = {}  # page -> origin of its own canonical, when that is not the crawl origin
    alt_pending: List[Tuple[str, List[Tuple[str, str]]]] = []  # (page, hreflang entries) not yet followed
    rel_sitemaps: List[str] = []  # <link rel="sitemap"> targets, as written
    alt_pages: set = set()  # pages that carry hreflang links
    alt_reached: set = set()  # pages first found through an hreflang link (no anchor leads there)
    seeded = {"sitemap": False}

    def to_site(target: str, prods: set) -> Optional[str]:
        """`target` on the crawl origin: itself when already there; when its origin is one of `prods` (the
        production address) and its path lies under the base, the same path on the crawl origin."""
        origin = origin_of(target)
        if origin == site:
            return target
        parts = urlsplit(target)
        if origin not in prods or not parts.path.startswith(base_path):
            return None
        return rebuild(SplitResult(site[0], site_netloc(), parts.path, parts.query, ""))

    def site_netloc() -> str:
        host = f"[{site[1]}]" if ":" in site[1] else site[1]
        return host if site[2] == DEFAULT_PORTS.get(site[0]) else f"{host}:{site[2]}"

    def drain() -> None:
        nonlocal timed_out, start_error, site
        while queue:
            if len(results) >= options.max_pages:
                return
            if clock() > deadline:
                timed_out = True
                return
            url, depth = queue.popleft()
            if options.delay > 0:
                site_throttle.wait(origin_of(url)[1])
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
                        return
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
            for src in parser.assets:
                asset = normalize(links_base or url, src)
                if asset and origin_of(asset) == site:
                    note_edge(page_assets, asset, url)
            for href in parser.info.links:
                target = normalize(links_base or url, href)
                if target:
                    enqueue(target, url, depth + 1, follow=depth < options.max_depth)
            canonical = normalize(links_base or url, parser.info.canonical_href) if parser.info.canonical_href else None
            if canonical and origin_of(canonical) != site:
                prod_origins.add(origin_of(canonical))
                page_prod[url] = origin_of(canonical)
            if parser.info.hreflangs:
                alt_pages.add(url)
                alt_pending.append((url, [(code, normalize(links_base or url, href) or "")
                                          for code, href in parser.info.hreflangs]))
            for href in parser.sitemap_hrefs:
                target = normalize(links_base or url, href)
                if target and target not in rel_sitemaps:
                    rel_sitemaps.append(target)

    def seed_from_alternates() -> None:
        """hreflang alternates are start points; one on the page's production address is mapped to the crawl origin."""
        while alt_pending:
            page_url, entries = alt_pending.pop(0)
            own_prod = {page_prod[page_url]} if page_url in page_prod else set()
            for _code, target in entries:
                mapped = to_site(target, own_prod) if target else None
                if mapped and mapped not in queued and mapped not in results:
                    alt_reached.add(mapped)
                if mapped:
                    enqueue(mapped, page_url, 1)

    sitemap_entries: List[Tuple[str, Optional[str]]] = []  # (loc as written, URL on the crawl origin or None)
    sitemap_used = ""

    def seed_from_sitemap() -> None:
        """Entries of the sitemap (or sitemap index) under the base are start points, mapped like hreflang."""
        nonlocal sitemap_used
        seeded["sitemap"] = True
        if not (rel_sitemaps or alt_pages or prod_origins):
            return  # nothing hints at a sitemap or a production address: no extra request
        candidates = [m for m in (to_site(r, prod_origins) for r in rel_sitemaps) if m]
        for name in ("sitemap-index.xml", "sitemap.xml"):
            default = rebuild(SplitResult(site[0], site_netloc(), base_path + name, "", ""))
            if default not in candidates:
                candidates.append(default)
        todo = deque(candidates)
        seen_maps: set = set()
        fetched_maps = 0
        while todo and fetched_maps < MAX_SITEMAP_FILES and len(sitemap_entries) < MAX_SITEMAP_URLS:
            if clock() > deadline:
                notes.append("stopped at --max-time: the sitemap was not read completely")
                break
            map_url = todo.popleft()
            if map_url in seen_maps:
                continue
            seen_maps.add(map_url)
            if sitemap_used and map_url in candidates:
                continue  # a sitemap was found: the other default names are not tried
            if options.delay > 0:
                site_throttle.wait(origin_of(map_url)[1])
            resp = fetcher.fetch(map_url, "GET", True, options.max_bytes)
            if resp.error or resp.status != 200:
                continue
            is_index, locs = sitemap_locs(decode_body(resp))
            if not locs and not is_index:
                continue
            fetched_maps += 1
            sitemap_used = sitemap_used or map_url
            for loc in locs:
                target = normalize(map_url, loc)
                if not target:
                    continue
                mapped = to_site(target, prod_origins)
                if is_index:
                    if mapped:
                        todo.append(mapped)
                    continue
                if len(sitemap_entries) < MAX_SITEMAP_URLS:
                    sitemap_entries.append((target, mapped))
                if mapped:
                    enqueue(mapped, sitemap_used, 1)
        if sitemap_used:
            notes.append(f"sitemap read from {sitemap_used}: {len(sitemap_entries)} URLs")

    drain()
    while not start_error and not timed_out and len(results) < options.max_pages:
        before = len(queue)
        seed_from_alternates()
        if not seeded["sitemap"]:
            seed_from_sitemap()
        if len(queue) == before:
            break
        drain()
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
    merge_slash_variants(html, sources, findings)
    check_sitemap(sitemap_entries, sitemap_used, results, findings)

    ttfbs = [r.ttfb_ms for r in results.values() if r.status and not r.error]
    if is_loopback(site[1]):
        notes.append("TTFB was measured on localhost: it says nothing about the hosting (no network, TLS or CDN)")
    else:
        notes.append("TTFB includes network and TLS time of this machine, not the visitors'; "
                     "a single request is not a measurement series")
    if options.public and not start_error:
        check_public(results, html, page_assets, start, site, fetcher, site_throttle, options, findings, notes,
                     deadline, clock)

    # the page checks, including duplicate content against the canonical rule, run in seo_check
    seo_report = seo_check.check_documents(html, seo_check.Options(options.dup_threshold, options.dup_min_words))
    findings.extend(f for f in seo_report["findings"]
                    if not (f["type"] == "orphan-page" and f["file"] in alt_reached))  # linked by hreflang
    notes.extend(seo_report["notes"])

    if start_error:
        notes.append(start_error)
    elif options.external:
        check_external(external, fetcher, throttle, options, findings, notes, deadline, clock,
                       site_throttle, site[1])
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
        "base_url": start, "public": options.public, "crawl_origin": f"{site[0]}://{site[1]}:{site[2]}", "start_error": start_error,
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


def merge_slash_variants(html: Dict[str, str], sources: Mapping[str, Sequence[str]], findings: List[dict]) -> None:
    """URLs that differ only in the trailing slash and return the same HTML are one page: the variant with fewer
    links (the one with a slash on a tie) is dropped from `html`, so the page checks see the page once, and one
    info finding names the page that links to it. Different content under the two forms stays as it is."""
    groups: Dict[tuple, List[str]] = {}
    for url in html:
        parts = urlsplit(url)
        groups.setdefault((parts.netloc, parts.path.rstrip("/") or "/", parts.query), []).append(url)
    for urls in groups.values():
        if len(urls) < 2:
            continue
        keep = max(urls, key=lambda u: (len(sources.get(u, ())), u.endswith("/")))
        for url in urls:
            if url == keep or html[url] != html[keep]:
                continue
            del html[url]
            linkers = [s for s in sources.get(url, ()) if s != url]
            more = f" (and {len(linkers) - 1} more pages)" if len(linkers) > 1 else ""
            add_finding(findings, "trailing-slash-variant", linkers[0] if linkers else url,
                        f"{'links to' if linkers else 'lists'} {url}{more}, which returns the same page as {keep}; "
                        "this server answers both, most hosts redirect one to the other. Link to one form only; "
                        "the page checks ran on one of them")


def check_sitemap(entries: Sequence[Tuple[str, Optional[str]]], sitemap: str, results: Mapping[str, PageResult],
                  findings: List[dict]) -> None:
    """How many sitemap URLs the crawl did not reach: not on the crawl origin or the production address, not
    fetched (limits), or answering an error."""
    missed: List[str] = []
    for loc, mapped in entries:
        result = results.get(mapped) if mapped else None
        if mapped is None or result is None or result.error or result.status >= 400 or not result.status:
            missed.append(loc)
    if missed:
        shown = ", ".join(missed[:3]) + (f" (+{len(missed) - 3})" if len(missed) > 3 else "")
        add_finding(findings, "sitemap-not-reached", sitemap,
                    f"{len(missed)} of {len(entries)} sitemap URLs were not reached by the crawl, e.g. {shown}. "
                    "Their host may differ from the one crawled and from the canonical address of the pages, "
                    "or the path may lie outside the start URL's folder; start at the site's base path, crawl "
                    "each language start page, or raise --max-pages")


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


def header_issue_kinds(headers: Mapping[str, str], https: bool) -> List[Tuple[str, str]]:
    """(finding type, header description) for the security headers a response lacks or sets weakly. Pure."""
    issues: List[Tuple[str, str]] = []
    if https:
        hsts = headers.get("strict-transport-security", "")
        match = re.search(r"max-age\s*=\s*\"?(\d+)", hsts, re.I)
        if not hsts:
            issues.append(("missing-hsts", "Strict-Transport-Security"))
        elif not match or int(match.group(1)) < HSTS_MIN_SECONDS:
            issues.append(("weak-hsts", f"Strict-Transport-Security {hsts!r}: max-age missing or under 180 days"))
    if "content-security-policy" not in headers:
        issues.append(("missing-csp", "Content-Security-Policy"))
    if "nosniff" not in re.split(r"[,;\s]+", headers.get("x-content-type-options", "").lower()):
        issues.append(("missing-nosniff", "X-Content-Type-Options: nosniff"))
    if "referrer-policy" not in headers:
        issues.append(("missing-referrer-policy", "Referrer-Policy"))
    return issues


def max_age_of(cache_control: str) -> Optional[int]:
    match = re.search(r"(?:^|[\s,])max-age\s*=\s*\"?(\d+)", cache_control, re.I)
    return int(match.group(1)) if match else None


def is_compressible(content_type: str) -> bool:
    return content_type.startswith(COMPRESSIBLE_TYPES)


def check_public(results: Mapping[str, PageResult], html: Mapping[str, str],
                 page_assets: Mapping[str, Sequence[str]], start: str, site: tuple, fetcher: Fetcher,
                 site_throttle: Throttle, options: CrawlOptions, findings: List[dict], notes: List[str],
                 deadline: float, clock: Callable[[], float]) -> None:
    """HTTP header checks for a public site: security headers on the HTML pages, compression and caching of the
    start page and a sample of assets, and the http -> https redirect. Every extra request goes through the
    same throttle as the crawl."""
    https = site[0] == "https"
    pages = [u for u in html if u in results]
    if not https:
        notes.append("the site is served over http: Strict-Transport-Security and the http -> https redirect "
                     "were not checked")
    # security headers: one finding per header, with the number of pages it is missing on
    missing: Dict[str, Tuple[str, List[str]]] = {}
    for url in pages:
        for kind, reason in header_issue_kinds(results[url].headers, https):
            missing.setdefault(kind, (reason, []))[1].append(url)
    for kind, (reason, urls) in missing.items():
        shown = ", ".join(urls[:2]) + (f" (+{len(urls) - 2})" if len(urls) > 2 else "")
        if kind == "weak-hsts":
            add_finding(findings, kind, urls[0], f"{reason}; on {len(urls)} of {len(pages)} HTML pages")
        else:
            add_finding(findings, kind, urls[0], f"response header {reason} is missing on {len(urls)} of "
                        f"{len(pages)} HTML pages, e.g. {shown}")
    # caching of the HTML pages: some way to revalidate or expire
    no_cache = [u for u in pages if not any(h in results[u].headers for h in
                                            ("cache-control", "etag", "last-modified", "expires"))]
    if no_cache:
        add_finding(findings, "html-no-cache-header", no_cache[0],
                    f"no Cache-Control, ETag, Last-Modified or Expires on {len(no_cache)} of {len(pages)} HTML pages")
    # compression and caching of the start page and a sample of assets, with compression requested
    entry = start if start in html else next(iter(html), "")  # a start page that redirects: its target
    sample: List[Tuple[str, List[str]]] = [(entry, [])] if entry else []
    sample += [(a, list(p)) for a, p in list(page_assets.items())[:options.max_assets]]
    if len(page_assets) > options.max_assets:
        notes.append(f"only the first {options.max_assets} of {len(page_assets)} assets were checked (--max-assets)")
    for url, loaded_by in sample:
        if clock() > deadline:
            notes.append("stopped at --max-time: remaining assets not checked")
            break
        if options.delay > 0:
            site_throttle.wait(origin_of(url)[1])
        resp = fetcher.fetch(url, "GET", False, options.max_bytes, accept_encoding="gzip, br")
        is_asset = bool(loaded_by)
        where = loaded_by[0] if loaded_by else url
        if resp.status in BLOCKED_STATUS:
            if is_asset:
                add_finding(findings, "asset-blocked", url,
                            f"status {resp.status} for this check, loaded by {where}; open it by hand")
            continue
        if resp.error or resp.status >= 400:
            if is_asset:
                add_finding(findings, "broken-link", where,
                            f"-> {url}  ({resp.error or 'status ' + str(resp.status)})")
            continue
        if not 200 <= resp.status < 300:
            continue
        ctype = resp.content_type
        length = resp.headers.get("content-length", "")
        encoded = resp.headers.get("content-encoding", "").strip().lower() not in ("", "identity")
        if is_compressible(ctype) and not encoded and length.isdigit() and int(length) >= COMPRESS_MIN_BYTES:
            add_finding(findings, "no-compression", url, f"{ctype}, {length} bytes sent without Content-Encoding "
                        "although gzip and br were accepted")
        if is_asset:
            cache = resp.headers.get("cache-control", "")
            age = max_age_of(cache)
            if not cache and "expires" not in resp.headers:
                add_finding(findings, "asset-not-cached", url, f"no Cache-Control or Expires (loaded by {where})")
            elif re.search(r"no-store|no-cache", cache, re.I) or (age is not None and age < SHORT_CACHE_SECONDS):
                add_finding(findings, "asset-short-cache", url,
                            f"Cache-Control {cache!r}: under a day (a fingerprinted file can be cached for a year)")
    if https and site[2] == 443:
        parts = urlsplit(start)
        plain = f"http://{site[1]}{parts.path or '/'}" + (f"?{parts.query}" if parts.query else "")
        chain = [plain]
        while True:  # a step on the same host over http (apex -> www) is followed, up to HTTPS_HOPS times
            if options.delay > 0:
                site_throttle.wait(site[1])
            resp = fetcher.fetch(chain[-1], "GET", False, options.max_bytes)
            target = normalize(chain[-1], resp.headers.get("location", "")) if 300 <= resp.status < 400 else None
            if (target and not target.startswith("https://") and len(chain) <= HTTPS_HOPS
                    and same_site_host(urlsplit(target).hostname or "", site[1]) and target not in chain):
                chain.append(target)
                continue
            break
        shown = "  ->  ".join(chain)
        if resp.error and not resp.status:
            notes.append(f"{shown} gave no answer ({resp.error}); the http -> https redirect was not verified")
        elif target and target.startswith("https://"):
            notes.append(f"{shown} redirects to {target} ({resp.status})")
        else:
            what = f"redirects to {target}" if target else f"answers {resp.status} instead of redirecting"
            add_finding(findings, "no-https-redirect", plain, f"{shown} {what}; plain http should lead to https")
    elif https:
        notes.append("the site runs on a non-default port: the http -> https redirect was not checked")


def check_external(external: Mapping[str, Sequence[str]], fetcher: Fetcher, throttle: Throttle,
                   options: CrawlOptions, findings: List[dict], notes: List[str], deadline: float,
                   clock: Callable[[], float], site_throttle: Optional[Throttle] = None,
                   site_host: str = "") -> None:
    """External links are asked by HEAD. A link to the site's own host (another scheme or port counts as
    external) also waits on the site's throttle, so the pace set for the site holds for it too."""
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
        own_host = site_throttle is not None and options.delay and same_site_host(host, site_host)

        def pace() -> None:
            throttle.wait(host)
            if own_host:
                site_throttle.wait(site_host)  # type: ignore[union-attr]

        pace()
        resp = fetcher.fetch(url, "HEAD", False, options.max_bytes)
        if resp.status == 405 and not resp.error:
            pace()
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
    lines = [f"crawl of {report['base_url']}{' (public mode)' if report.get('public') else ''}: {report['pages_fetched']} URLs fetched, "
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
    p.add_argument("--max-pages", type=int, default=None,
                   help=f"internal URLs fetched at most (default {DEFAULT_MAX_PAGES}, with --public {PUBLIC_MAX_PAGES})")
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
    p.add_argument("--public", action="store_true",
                   help="the site is on the internet: read-only and throttled (--delay, default 1 s between "
                        "requests, 100 pages unless --max-pages), plus HTTP header checks (HSTS, CSP, "
                        "X-Content-Type-Options, Referrer-Policy), compression and caching of HTML and assets, "
                        "the http -> https redirect, and a real TTFB. Extra requests: one GET for http:// and "
                        "one per sampled asset, headers only")
    p.add_argument("--delay", type=float, default=None,
                   help="seconds between two requests to the site itself (default 0, with --public 1)")
    p.add_argument("--max-assets", type=int, default=DEFAULT_MAX_ASSETS,
                   help="scripts and stylesheets sampled for compression and caching with --public "
                        "(default %(default)s)")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    problems = []
    if args.max_pages is None:
        args.max_pages = PUBLIC_MAX_PAGES if args.public else DEFAULT_MAX_PAGES
    if args.delay is None:
        args.delay = PUBLIC_DELAY if args.public else 0.0
    if args.delay < 0 or args.max_assets < 0:
        problems.append("--delay and --max-assets must not be negative")
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
                           args.dup_threshold, args.dup_min_words, args.public, args.delay, args.max_assets)
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
    try:
        from usage import count_script_run
        count_script_run(__file__)
    except ImportError:
        pass
    sys.exit(main())
