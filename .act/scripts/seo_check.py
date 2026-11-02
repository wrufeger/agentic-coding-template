#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Code-only SEO checks over a project's HTML, templates, Markdown pages and framework config —
#          the mechanical half of skill `act-seo`. Reads files, never fetches a page, never talks to a
#          search engine or Search Console, writes nothing. What a rendered page looks like is out of scope.
#
# What is read: `*.html`/`*.htm` and template files (`.vue`, `.astro`, `.svelte`, `.njk`, `.twig`,
#          `.liquid`, `.erb`, `.blade.php`, `.jsx`/`.tsx` pages) with the stdlib HTML parser, Markdown
#          pages with front matter, `robots.txt`, `sitemap.xml`, `package.json` for the stack. Files under
#          `node_modules`, build output and vendored folders are skipped.
#          A file is a "document" if it has `<html`/`<!doctype`, a "page" if it is a route file under
#          `pages/`, otherwise a fragment (only image alt text is checked there).
#
# Findings (type, severity):
#   missing-title (error), empty-title (error), title-length (info, over 60 characters)
#   missing-description (warning), description-length (info, over 160), duplicate-title and
#   duplicate-description (warning, across pages; titles with template syntax are ignored)
#   missing-h1 / multiple-h1 / heading-order (warning)
#   missing-lang (warning)   missing-canonical (info)   missing-og (info: og:title/description/image)
#   noindex (info)   client-rendered (info: an empty `#app`/`#root` shell, crawlers may see no content)
#   img-alt-missing (warning; `alt=""` is fine, a decorative image)
#   broken-internal-link (warning; only where routes follow from files, see notes in the report)
#   missing-robots / robots-blocks-all / robots-no-sitemap, missing-sitemap / sitemap-url-missing-page /
#   page-not-in-sitemap (warning, warning, info, warning, warning, info)
#
# Further findings (hreflang, JSON-LD, duplicate content, image size, viewport, orphans, translations):
#   hreflang-missing / hreflang-invalid / hreflang-no-self / hreflang-no-return / hreflang-lang-mismatch (warning)
#   jsonld-invalid / jsonld-incomplete (warning: bad JSON, no @context or @type)
#   duplicate-content (warning: same text in `main`, else in the body without header/nav/footer; pages whose
#   canonical points at each other or at the same page are fine)   img-size-missing (warning: no width/height)
#   missing-viewport (warning)   orphan-page (warning: no other page links to it)
#   translation-* (the findings of i18n_check.py, same severity there)
#
# Library use: `check_documents({path_or_url: html, ...}, Options())` runs the page checks on rendered
#   documents without touching the disk and returns the same report dict as `run`.
#
# Usage:
#   python .act/scripts/seo_check.py [--root DIR] [--json] [--dup-threshold X] [--dup-min-words N]
#
# Exit code: 0 no finding above info, 1 at least one warning or error, 2 usage problem.

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import os
import re
import stat
import sys
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterator, Mapping, Optional
from urllib.parse import urljoin, urlparse

SKIP_DIRS = {
    ".git", "node_modules", "vendor", "dist", "build", ".venv", "venv", "__pycache__", ".act", ".act-local",
    ".nuxt", ".next", ".output", "coverage", "target", ".claude", ".agents", ".idea", ".vscode", "_site",
    ".svelte-kit", ".astro", ".cache", "tests", "test", "__tests__",
}
MAX_FILE_BYTES = 2_000_000
HTML_SUFFIXES = {".html", ".htm"}
TEMPLATE_SUFFIXES = {".vue", ".astro", ".svelte", ".njk", ".twig", ".liquid", ".erb", ".jsx", ".tsx", ".hbs"}
PAGE_DIRS = {"pages"}
STATIC_ROOTS = ("", "public", "static", "src", "web", "www")
TEMPLATE_SYNTAX = re.compile(r"\{\{|\{%|<\?|\$\{|<%|\{#|@if|@foreach|v-bind|:alt|\[alt\]|\{\.\.\.")
MARKDOWN_DIRS = {"content", "posts", "_posts", "pages", "articles", "blog"}
SEVERITY = {
    "missing-title": "error", "empty-title": "error",
    "missing-description": "warning", "duplicate-title": "warning", "duplicate-description": "warning",
    "missing-h1": "warning", "multiple-h1": "warning", "heading-order": "warning", "missing-lang": "warning",
    "img-alt-missing": "warning", "broken-internal-link": "warning", "missing-robots": "warning",
    "robots-blocks-all": "warning", "missing-sitemap": "warning", "sitemap-url-missing-page": "warning",
    "title-length": "info", "description-length": "info", "missing-canonical": "info", "missing-og": "info",
    "noindex": "info", "client-rendered": "info", "robots-no-sitemap": "info", "page-not-in-sitemap": "info",
    # hreflang, JSON-LD, duplicate content, image size, viewport, orphans
    "hreflang-missing": "warning", "hreflang-invalid": "warning", "hreflang-no-self": "warning",
    "hreflang-no-return": "warning", "hreflang-lang-mismatch": "warning",
    "jsonld-invalid": "warning", "jsonld-incomplete": "warning", "duplicate-content": "warning",
    "img-size-missing": "warning", "missing-viewport": "warning", "orphan-page": "warning",
    # translation findings of i18n_check.py, same severity as there
    "translation-parse-error": "error", "translation-placeholder-mismatch": "error",
    "translation-used-undefined": "error", "translation-missing": "warning", "translation-extra": "warning",
    "translation-empty": "warning", "translation-unused": "info",
}
GENERATORS = ("sitemap", "robots")  # package/config names that generate these files at build time
HREFLANG_CODE = re.compile(r"^(?:x-default|[a-z]{2,3}(?:-[a-z0-9]{2,8})*)$", re.I)
ERROR_PAGE_NAMES = {"401", "403", "404", "410", "500", "503", "error", "not-found", "_error"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
CHROME_TAGS = {"header", "nav", "footer", "aside"}
CHROME_ROLES = {"navigation", "banner", "contentinfo", "complementary"}
HEAD_FROM_FRAMEWORK = {".vue", ".jsx", ".tsx", ".astro", ".svelte"}  # <Head>/<Html> components set the head
DUP_MAX_POSTING = 50  # a word group on more pages than this is boilerplate, not evidence of a near copy
DUP_SHINGLE = 4  # words per shingle for the duplicate-content comparison
DUP_SKETCH = 8  # smallest word-group hashes kept per page to find pages built from the same boilerplate
DUP_BAND = 2  # sketch entries per band: two pages share a band when these entries are equal
DUP_MAX_COMPARE = 20  # originals one page is compared against at most
DUP_EXACT_ONLY_ABOVE = 800  # more different pages than this: only identical texts are compared


@dataclass
class Options:
    """Settings of the extended checks."""
    dup_threshold: float = 0.9  # share of shared word groups (0..1] from which two pages count as duplicates
    dup_min_words: int = 25  # pages with fewer words are not compared


@dataclass
class Finding:
    type: str
    file: str
    detail: str
    severity: str = ""

    def __post_init__(self) -> None:
        self.severity = SEVERITY[self.type]


@dataclass
class PageInfo:
    file: str
    kind: str  # document | page | fragment | markdown
    title: Optional[str] = None
    description: Optional[str] = None
    lang_seen: bool = False
    canonical: bool = False
    og: set[str] = field(default_factory=set)
    noindex: bool = False
    headings: list[int] = field(default_factory=list)
    images_without_alt: int = 0
    links: list[str] = field(default_factory=list)
    shell: bool = False
    body_text: int = 0
    canonical_href: str = ""
    hreflangs: list[tuple[str, str]] = field(default_factory=list)  # (language code, href) of rel=alternate links
    html_lang: str = ""
    jsonld: list[str] = field(default_factory=list)  # raw text of each application/ld+json block
    viewport: Optional[str] = None
    images_without_size: int = 0
    has_main: bool = False
    has_head: bool = False
    text_main: list[str] = field(default_factory=list)  # text inside <main>, outside header/nav/footer
    text_body: list[str] = field(default_factory=list)  # all text outside header/nav/footer


def _norm_attr(name: str) -> str:
    """`:width`, `v-bind:width`, `[width]`, `[attr.width]` -> `width` (template bindings still set the attribute)."""
    name = name.lower()
    for prefix in ("v-bind:", "[attr.", "[", ":", "@"):
        if name.startswith(prefix):
            name = name[len(prefix):]
    return name.rstrip("]")


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.info = PageInfo("", "document")
        self._in_title = False
        self._title_parts: list[str] = []
        self._skip = 0  # inside script/style
        self._heading_open = False
        self._chrome = 0  # inside header/nav/footer/aside or a navigation/banner/contentinfo role
        self._main = 0  # inside main
        self._stack: list[tuple[str, bool, bool]] = []  # open (tag, chrome, main)
        self._ld: Optional[list[str]] = None  # open application/ld+json block

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        info = self.info
        if tag in ("script", "style"):
            self._skip += 1
        if tag == "script" and a.get("type", "").strip().lower() == "application/ld+json":
            self._ld = []
        if tag == "head":
            info.has_head = True
        if tag not in VOID_TAGS:
            is_chrome = tag in CHROME_TAGS or a.get("role", "").strip().lower() in CHROME_ROLES
            is_main = tag == "main"
            self._stack.append((tag, is_chrome, is_main))
            self._chrome += is_chrome
            self._main += is_main
            if is_main:
                info.has_main = True
        if tag == "html" and "lang" in a:
            info.lang_seen = True
            info.html_lang = a["lang"].strip()
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            content = a.get("content", "")
            if name == "description":
                info.description = content
            elif name == "viewport":
                info.viewport = content
            elif name.startswith("og:") and content.strip():
                info.og.add(name)
            elif name == "robots" and "noindex" in content.lower():
                info.noindex = True
        elif tag == "link":
            rel = a.get("rel", "").lower().split()
            if "canonical" in rel:
                info.canonical = True
                info.canonical_href = a.get("href", "").strip()
            elif "alternate" in rel and "hreflang" in a:
                info.hreflangs.append((a["hreflang"].strip(), a.get("href", "").strip()))
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            info.headings.append(int(tag[1]))
        elif tag == "img":
            raw = self.get_starttag_text() or ""
            if not re.search(r"\balt\b", raw, re.I) and not TEMPLATE_SYNTAX.search(raw):
                info.images_without_alt += 1
            names = {_norm_attr(k) for k in a}
            if not {"width", "height"} <= names and "aspect-ratio" not in a.get("style", "").lower() \
                    and not re.search(r"\{\{|\{%|<\?|<%|v-bind", raw):
                info.images_without_size += 1
        elif tag == "a" and a.get("href"):
            info.links.append(a["href"])
        elif tag == "div" and a.get("id") in ("app", "root", "__nuxt", "__next"):
            info.shell = True

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index][0] == tag:
                for _, was_chrome, was_main in self._stack[index:]:
                    self._chrome -= was_chrome
                    self._main -= was_main
                del self._stack[index:]
                break
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
            if tag == "script" and self._ld is not None:
                self.info.jsonld.append("".join(self._ld))
                self._ld = None
        elif tag == "title":
            self._in_title = False
            self.info.title = "".join(self._title_parts).strip()

    def handle_data(self, data: str) -> None:
        if self._ld is not None:
            self._ld.append(data)
        if self._in_title:
            self._title_parts.append(data)
        elif not self._skip:
            self.info.body_text += len(data.strip())
            if not self._chrome and data.strip():
                self.info.text_body.append(data)
                if self._main:
                    self.info.text_main.append(data)


def walk(root: Path) -> Iterator[tuple[Path, list[str]]]:
    for current, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        yield Path(current), sorted(files)


def rel(root: Path, path: Path) -> str:
    return str(path.relative_to(root)).replace("\\", "/")


def read_text(path: Path) -> str:
    """Text of a regular file, at most MAX_FILE_BYTES. A symlink, FIFO or device is refused without opening it,
    an oversize file is refused after reading one byte too many (ValueError); OSError as usual."""
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"{path.name}: not a regular file (symlink, FIFO or device)")
    with path.open("rb") as handle:
        raw = handle.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError(f"{path.name}: larger than {MAX_FILE_BYTES} bytes")
    return raw.decode("utf-8-sig", "replace")


def read_optional(path: Path) -> str:
    """Like read_text, but an unreadable file gives an empty text."""
    try:
        return read_text(path)
    except (OSError, ValueError):
        return ""


def parse_markup(root: Path, path: Path, kind: str, text: str) -> PageInfo:
    parser = PageParser()
    try:
        parser.feed(text)
        parser.close()
    except (AssertionError, ValueError, RecursionError):  # a template the stdlib parser cannot digest
        pass
    parser.info.file = rel(root, path)
    parser.info.kind = kind
    return parser.info


def parse_markdown(root: Path, path: Path, text: str) -> Optional[PageInfo]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, re.S)
    if not match:
        return None
    info = PageInfo(rel(root, path), "markdown")
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        key, value = key.strip().lower(), value.strip().strip("'\"")
        if key == "title":
            info.title = value
        elif key in ("description", "summary", "excerpt"):
            info.description = info.description or value
        elif key == "noindex" and value.lower() == "true":
            info.noindex = True
        elif key == "robots" and "noindex" in value.lower():
            info.noindex = True
    body = text[match.end():]
    in_fence = False
    for line in body.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        heading = re.match(r"^(#{1,6})\s+\S", line)
        if heading:
            info.headings.append(len(heading.group(1)))
        info.images_without_alt += len(re.findall(r"!\[\s*\]\(", line))
        info.links += re.findall(r"(?<!!)\[[^\]]*\]\(([^)\s]+)", line)
    return info


def detect_stack(root: Path) -> tuple[list[str], str]:
    stack: list[str] = []
    deps_text = ""
    package = root / "package.json"
    if package.is_file():
        try:
            data = json.loads(read_text(package))
            if not isinstance(data, dict):
                raise ValueError("package.json is not an object")
            names: dict[str, object] = {}
            for section in ("dependencies", "devDependencies"):
                value = data.get(section)
                if isinstance(value, dict):
                    names.update(value)
            deps_text = " ".join(str(n) for n in names)
            for hint in ("nuxt", "next", "astro", "gatsby", "@sveltejs/kit", "vitepress", "@11ty/eleventy",
                         "@docusaurus/core", "vue", "react", "svelte", "vite"):
                if hint in names:
                    stack.append(hint)
        except (OSError, ValueError, RecursionError):  # JSON and Unicode decode errors are ValueErrors
            stack.append("package.json (unreadable)")
    for marker, label in (("hugo.toml", "hugo"), ("config.toml", "hugo?"), ("_config.yml", "jekyll"),
                          ("artisan", "laravel"), ("manage.py", "django")):
        if (root / marker).exists():
            stack.append(label)
    config_text = ""
    for name in ("nuxt.config.ts", "nuxt.config.js", "next.config.js", "next.config.mjs", "astro.config.mjs",
                 "astro.config.ts", "gatsby-config.js", "svelte.config.js", "_config.yml", "next-sitemap.config.js"):
        candidate = root / name
        if candidate.is_file():
            config_text += " " + read_optional(candidate)
    return stack, (deps_text + " " + config_text).lower()


def route_regexes(root: Path, files: list[Path]) -> list[re.Pattern[str]]:
    """Routes that follow from file-based page directories (`pages/about.vue` -> `/about`)."""
    patterns: list[re.Pattern[str]] = []
    for path in files:
        parts = list(path.relative_to(root).with_suffix("").parts)
        if "pages" not in parts:
            continue
        parts = parts[parts.index("pages") + 1:]
        if parts and parts[-1] in ("index", "+page", "page"):
            parts = parts[:-1]
        pieces = [r"[^/]+" if re.fullmatch(r"\[.*\]|:.*|_.*", p) else re.escape(p) for p in parts]
        patterns.append(re.compile("^/" + "/".join(pieces) + "/?$"))
    return patterns


def link_target_exists(root: Path, source: Path, href: str, routes: list[re.Pattern[str]]) -> Optional[bool]:
    """True/False if the internal link can be judged from files, None if it cannot (dynamic, external)."""
    if not href or TEMPLATE_SYNTAX.search(href) or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
        return None
    parsed = urlparse(href)
    if parsed.scheme or parsed.netloc:
        return None
    path = parsed.path
    if not path:
        return None
    if re.search(r"[\[\]<>{}$]", path):
        return None
    bases = [root / b for b in STATIC_ROOTS] if path.startswith("/") else [source.parent]
    clean = path.lstrip("/") if path.startswith("/") else path
    for base in bases:
        candidate = (base / clean).resolve()
        for option in (candidate, candidate.with_name(candidate.name + ".html"), candidate / "index.html"):
            if option.is_file():
                return True
    if path.startswith("/") and any(r.match(path) for r in routes):
        return True
    return False


def find_static(root: Path, name: str) -> Optional[Path]:
    for base in ("", "public", "static", "dist", "build", "web", "www", "src"):
        candidate = root / base / name
        if candidate.is_file():
            return candidate
    return None


def check_site(root: Path, pages: list[PageInfo], generated: str, findings: list[Finding], documents: list[PageInfo]
               ) -> None:
    robots = find_static(root, "robots.txt")
    sitemap = find_static(root, "sitemap.xml") or find_static(root, "sitemap_index.xml")
    if not documents and not pages:
        return
    if robots is None:
        if "robots" not in generated:
            findings.append(Finding("missing-robots", "robots.txt", "no robots.txt found (and no generator in the config)"))
    else:
        text = read_optional(robots)
        groups = re.split(r"(?im)^\s*user-agent\s*:", text)[1:]
        for group in groups:
            agent, _, rules = group.partition("\n")
            if agent.strip() == "*" and re.search(r"(?im)^\s*disallow\s*:\s*/\s*$", rules):
                findings.append(Finding("robots-blocks-all", rel(root, robots), "`User-agent: *` with `Disallow: /` "
                                        "blocks the whole site"))
        if not re.search(r"(?im)^\s*sitemap\s*:", text):
            findings.append(Finding("robots-no-sitemap", rel(root, robots), "no `Sitemap:` line"))
    if sitemap is None:
        if "sitemap" not in generated:
            findings.append(Finding("missing-sitemap", "sitemap.xml", "no sitemap.xml found (and no generator in the config)"))
        return
    locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", read_optional(sitemap))
    listed: set[str] = set()
    sitemap_rel = rel(root, sitemap)
    for loc in locs:
        path = urlparse(loc).path or "/"
        listed.add(path.rstrip("/") or "/")
        if path.endswith(".xml"):
            continue
        bare = path.lstrip("/")
        found = any(
            (root / base / bare).is_file() or (root / base / (bare + ".html")).is_file()
            or (root / base / bare / "index.html").is_file()
            for base in STATIC_ROOTS
        )
        if not found and bare and not documents_have_route(documents, path):
            findings.append(Finding("sitemap-url-missing-page", sitemap_rel, f"{loc} has no page in the project"))
    if locs:
        for doc in documents:
            if doc.noindex:
                continue
            routes = {r for r in doc_routes(doc.file)}
            if not routes & listed:
                findings.append(Finding("page-not-in-sitemap", doc.file, "indexable page is not listed in the sitemap"))


def doc_routes(file: str) -> list[str]:
    """Candidate URL paths of a static HTML file, outermost static folder stripped."""
    parts = file.split("/")
    if parts[0] in ("public", "static", "dist", "build", "web", "www", "src"):
        parts = parts[1:]
    path = "/" + "/".join(parts)
    routes = [path]
    if path.endswith(".html"):
        routes.append(path[:-5])
        if path.endswith("/index.html"):
            routes.append(path[: -len("/index.html")] or "/")
    return [r.rstrip("/") or "/" for r in routes]


def documents_have_route(documents: list[PageInfo], path: str) -> bool:
    wanted = path.rstrip("/") or "/"
    return any(wanted in doc_routes(doc.file) for doc in documents)


def check_page(page: PageInfo, findings: list[Finding], root: Path,
               routes: list[re.Pattern[str]], link_check: bool) -> None:
    where = page.file
    if page.images_without_alt:
        findings.append(Finding("img-alt-missing", where, f"{page.images_without_alt} image(s) without an alt attribute"))
    if page.kind == "fragment":
        return
    if page.kind in ("document", "markdown"):
        if page.title is None or (page.kind == "markdown" and not page.title):
            findings.append(Finding("missing-title", where, "no <title>" if page.kind == "document" else "no `title` in front matter"))
        elif page.title == "":
            findings.append(Finding("empty-title", where, "<title> is empty"))
        elif len(page.title) > 60 and not TEMPLATE_SYNTAX.search(page.title):
            findings.append(Finding("title-length", where, f"title has {len(page.title)} characters (about 60 show up in results)"))
        if page.description is None or not page.description.strip():
            findings.append(Finding("missing-description", where, "no meta description"))
        elif len(page.description) > 160 and not TEMPLATE_SYNTAX.search(page.description):
            findings.append(Finding("description-length", where, f"description has {len(page.description)} characters (about 160 show up)"))
    if page.kind == "document":
        if not page.lang_seen:
            findings.append(Finding("missing-lang", where, "<html> has no lang attribute"))
        if not page.canonical:
            findings.append(Finding("missing-canonical", where, "no <link rel=\"canonical\">"))
        missing_og = [n for n in ("og:title", "og:description", "og:image") if n not in page.og]
        if missing_og:
            findings.append(Finding("missing-og", where, "missing " + ", ".join(missing_og)))
    if page.noindex:
        findings.append(Finding("noindex", where, "page is marked noindex"))
    if page.kind == "document" and page.shell and not page.headings and page.body_text < 50:
        findings.append(Finding("client-rendered", where, "empty app shell: content is built in the browser, "
                                "crawlers may see none (consider server-side rendering or prerendering)"))
    else:
        h1 = page.headings.count(1)
        if h1 == 0 and page.kind != "markdown":
            findings.append(Finding("missing-h1", where, "no <h1>"))
        elif h1 > 1:
            findings.append(Finding("multiple-h1", where, f"{h1} <h1> elements, expected one"))
    previous = 0
    for level in page.headings:
        if previous and level > previous + 1:
            findings.append(Finding("heading-order", where, f"h{previous} followed by h{level}"))
            break
        previous = level
    if link_check and page.kind in ("document", "page"):
        source = root / page.file
        broken = [h for h in dict.fromkeys(page.links) if link_target_exists(root, source, h, routes) is False]
        for href in broken:
            findings.append(Finding("broken-internal-link", where, f"{href} points to no file or route in the project"))


def check_duplicate_meta(documents: list[PageInfo], findings: list[Finding]) -> None:
    for attr, kind in (("title", "duplicate-title"), ("description", "duplicate-description")):
        seen: dict[str, list[str]] = {}
        for page in documents:
            value = getattr(page, attr)
            if value and value.strip() and not TEMPLATE_SYNTAX.search(value):
                seen.setdefault(value.strip().lower(), []).append(page.file)
        for value, files in seen.items():
            if len(files) > 1:
                findings.append(Finding(kind, files[0], f"same {attr} on {len(files)} pages: {', '.join(files)}"))


# ---- extended checks: what a rendered page set needs ---------------------------------------------------------

def framework_head(path: str) -> bool:
    """A framework component or document file: its head and image sizes come from the framework."""
    name = path.rstrip("/").rsplit("/", 1)[-1].lower()
    return os.path.splitext(name)[1] in HEAD_FROM_FRAMEWORK or name.startswith("_document.")


def is_template_file(path: str) -> bool:
    name = path.rstrip("/").rsplit("/", 1)[-1].lower()
    return os.path.splitext(name)[1] in TEMPLATE_SUFFIXES or name.endswith(".blade.php")


def check_page_extended(page: PageInfo, findings: list[Finding]) -> None:
    """Checks on one page: viewport, image size, JSON-LD. Fragments are not judged (a component is not a page)."""
    if page.kind not in ("document", "page"):
        return
    where = page.file
    # Only a full HTML document with its own <head> is judged: in a component or layout template the head and the
    # image sizes come from the framework (head config, image component).
    judged = page.kind == "document" and page.has_head and not framework_head(page.file)
    if judged:
        if page.viewport is None:
            findings.append(Finding("missing-viewport", where, "no <meta name=\"viewport\"> (mobile layout and the "
                                    "mobile-friendly test need it)"))
        elif "width=device-width" not in page.viewport.replace(" ", "").lower() \
                and not TEMPLATE_SYNTAX.search(page.viewport):
            findings.append(Finding("missing-viewport", where, f"viewport `{page.viewport}` has no width=device-width"))
    if page.images_without_size and judged:
        findings.append(Finding("img-size-missing", where, f"{page.images_without_size} image(s) without width and "
                                "height (the layout shifts when they load)"))
    template_file = is_template_file(page.file)
    for raw in page.jsonld:
        text = raw.strip()
        if not text or TEMPLATE_SYNTAX.search(raw):
            continue  # empty: the content is set by the framework (v-html, set:html, dangerouslySetInnerHTML)
        if template_file and not re.match(r'[\[{]\s*["\]}]', text):
            continue  # an expression such as {JSON.stringify(data)}, not JSON text
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError) as exc:
            findings.append(Finding("jsonld-invalid", where, f"JSON-LD is not valid JSON: {exc}"))
            continue
        blocks = data if isinstance(data, list) else [data]
        problems: list[str] = []
        if not blocks or not all(isinstance(b, dict) for b in blocks):
            findings.append(Finding("jsonld-invalid", where, "JSON-LD must be an object or a list of objects"))
            continue
        for block in blocks:
            if "@context" not in block:
                problems.append("missing @context")
            graph = block.get("@graph")
            if isinstance(graph, list):
                if any(not isinstance(n, dict) or "@type" not in n for n in graph):
                    problems.append("a node in @graph has no @type")
            elif "@type" not in block:
                problems.append("missing @type")
        if problems:
            findings.append(Finding("jsonld-incomplete", where, "JSON-LD: " + ", ".join(dict.fromkeys(problems))))


def key_routes(key: str) -> list[str]:
    """Candidate URL paths of a document key: a file path (`about/index.html`) or a URL."""
    parsed = urlparse(key)
    if parsed.scheme in ("http", "https"):
        path = parsed.path or "/"
        routes = [path]
        if path.endswith(".html"):
            routes.append(path[:-5])
            if path.endswith("/index.html"):
                routes.append(path[: -len("/index.html")] or "/")
        else:
            routes.append(path.rstrip("/") + ".html")
        return [r.rstrip("/") or "/" for r in routes]
    return doc_routes(key)


def base_url(key: str) -> str:
    if urlparse(key).scheme in ("http", "https"):
        return key
    parts = key.split("/")
    if parts[0] in ("public", "static", "dist", "build", "web", "www", "src") and len(parts) > 1:
        parts = parts[1:]
    return "http://local.invalid/" + "/".join(parts)


def href_route(key: str, href: str, own_hosts: set[str], any_host: bool) -> Optional[str]:
    """URL path an href of document `key` leads to; None for another site or a non-page scheme.
    `any_host` ignores the host of an absolute href (hreflang and canonical name the live address of a file)."""
    if not href or TEMPLATE_SYNTAX.search(href):
        return None
    base = base_url(key)
    parsed = urlparse(urljoin(base, href.strip()))
    if parsed.scheme not in ("http", "https"):
        return None
    if not any_host and parsed.netloc != urlparse(base).netloc and parsed.netloc not in own_hosts:
        return None
    return parsed.path.rstrip("/") or "/"


def page_words(page: PageInfo) -> list[str]:
    """Words of the page content: `main` if there is one, otherwise the body without header, nav and footer."""
    parts = page.text_main if page.has_main and page.text_main else page.text_body
    return re.findall(r"\w+", " ".join(parts).lower())


def _near_copies_of_boilerplate(reps: list[PageInfo], sets: list[set[int]], postings: dict[int, list[int]],
                                threshold: float, reported: set[str], canonical_ok: Callable[[PageInfo, PageInfo], bool],
                                findings: list[Finding]) -> None:
    """Near copies among pages whose text is mostly word groups that occur on many pages (pages built from one
    template with little text of their own). Such groups are no evidence for a single pair, so they are skipped
    in the pairwise search; here a page whose text is at least `threshold` made of them is looked up by a small
    sketch of those groups (the smallest hashes, in bands), and the candidates are confirmed by the full
    similarity. A page is compared only against earlier originals, at most DUP_MAX_COMPARE of them."""
    frequent = {h for h, posting in postings.items() if len(posting) > DUP_MAX_POSTING}
    if not frequent:
        return
    buckets: dict[tuple[int, tuple[int, ...]], list[int]] = {}
    for index, group_set in enumerate(sets):
        common = group_set & frequent
        if not group_set or len(common) < threshold * len(group_set):
            continue  # mostly the page's own text: the pairwise search covers it
        sketch = heapq.nsmallest(DUP_SKETCH, common)
        bands = [(n, tuple(sketch[n * DUP_BAND:(n + 1) * DUP_BAND])) for n in range(max(1, len(sketch) // DUP_BAND))]
        if reps[index].file not in reported:
            candidates: list[int] = []
            for band in bands:
                for other in buckets.get(band, ()):
                    if other not in candidates:
                        candidates.append(other)
            for other in sorted(candidates)[:DUP_MAX_COMPARE]:
                shared = len(group_set & sets[other])
                ratio = shared / (len(sets[other]) + len(group_set) - shared)
                if ratio >= threshold and not canonical_ok(reps[other], reps[index]):
                    findings.append(Finding("duplicate-content", reps[index].file, f"{round(ratio * 100)}% same text as "
                                            f"{reps[other].file} (main content; set a canonical link or merge the pages)"))
                    reported.add(reps[index].file)
                    break
        if reps[index].file not in reported:
            for band in bands:
                buckets.setdefault(band, []).append(index)


def check_page_set(documents: list[PageInfo], findings: list[Finding], notes: list[str], options: Options,
                   orphans: bool = True, orphan_suffixes: Optional[tuple[str, ...]] = None) -> None:
    """Checks across a set of documents: hreflang, duplicate content, orphan pages."""
    routes_of = {d.file: set(key_routes(d.file)) for d in documents}
    by_route: dict[str, str] = {}
    for d in documents:
        for r in sorted(routes_of[d.file]):
            by_route.setdefault(r, d.file)
    own_hosts = {urlparse(d.canonical_href).netloc for d in documents if d.canonical_href}
    own_hosts |= {urlparse(d.file).netloc for d in documents if urlparse(d.file).scheme in ("http", "https")}
    own_hosts.discard("")
    by_file = {d.file: d for d in documents}

    # hreflang
    def templated(d: PageInfo) -> bool:  # codes or URLs built by a template loop: not judged, not counted
        return any(TEMPLATE_SYNTAX.search(c) or TEMPLATE_SYNTAX.search(h) for c, h in d.hreflangs)

    with_hreflang = [d for d in documents if d.hreflangs and not templated(d)]
    for d in documents:
        if d.hreflangs and templated(d):
            continue
        if not d.hreflangs:
            if with_hreflang and d.kind == "document":
                findings.append(Finding("hreflang-missing", d.file, "other pages carry hreflang links, this one has none"))
            continue
        seen: dict[str, str] = {}
        own_entry: Optional[str] = None
        for code, href in d.hreflangs:
            if not HREFLANG_CODE.match(code):
                findings.append(Finding("hreflang-invalid", d.file, f"`{code}` is not a language code (like en, de-AT, x-default)"))
                continue
            if not urlparse(href).netloc:
                findings.append(Finding("hreflang-invalid", d.file, f"hreflang `{code}`: href `{href}` is not an absolute URL"))
                continue
            target = href_route(d.file, href, own_hosts, True)
            if code.lower() in seen and seen[code.lower()] != target:
                findings.append(Finding("hreflang-invalid", d.file, f"`{code}` is given twice with different URLs"))
            seen[code.lower()] = target or ""
            if target in routes_of[d.file] and (own_entry is None or own_entry.lower() == "x-default"):
                own_entry = code
        if own_entry is None:
            findings.append(Finding("hreflang-no-self", d.file, "the hreflang set has no entry for the page itself"))
        elif d.html_lang and own_entry.lower() != "x-default" \
                and own_entry.lower().split("-")[0] != d.html_lang.lower().split("-")[0]:
            findings.append(Finding("hreflang-lang-mismatch", d.file, f"hreflang says `{own_entry}`, <html lang> says "
                                    f"`{d.html_lang}`"))
        for code, href in d.hreflangs:
            target = href_route(d.file, href, own_hosts, True)
            other_file = by_route.get(target) if target else None
            if not other_file or other_file == d.file:
                continue
            back = {href_route(other_file, h, own_hosts, True) for _, h in by_file[other_file].hreflangs}
            if not back & routes_of[d.file]:
                findings.append(Finding("hreflang-no-return", d.file,
                                        f"`{code}` points to {other_file}, which has no hreflang link back"))

    # duplicate content: identical texts are grouped by hash, near copies are found through shared word groups
    def canonical_ok(a: PageInfo, b: PageInfo) -> bool:
        ca = href_route(a.file, a.canonical_href, own_hosts, True) if a.canonical_href else None
        cb = href_route(b.file, b.canonical_href, own_hosts, True) if b.canonical_href else None
        if ca and ca in routes_of[b.file] or cb and cb in routes_of[a.file]:
            return True
        return bool(ca and ca == cb)

    groups: dict[bytes, list[PageInfo]] = {}
    for d in documents:
        if d.kind != "document" or d.noindex:
            continue
        words = page_words(d)
        if len(words) >= options.dup_min_words:
            digest = hashlib.blake2b(" ".join(words).encode("utf-8"), digest_size=16).digest()
            groups.setdefault(digest, []).append(d)
    reported: set[str] = set()  # at most one finding per page, against the first original
    for members in groups.values():
        for position, b in enumerate(members[1:], 1):
            original = next((a for a in members[:position] if not canonical_ok(a, b)), None)
            if original is not None:
                findings.append(Finding("duplicate-content", b.file, f"100% same text as {original.file} "
                                        "(main content; set a canonical link or merge the pages)"))
                reported.add(b.file)
    reps = [members[0] for members in groups.values()]
    if len(reps) > DUP_EXACT_ONLY_ABOVE:
        notes.append(f"duplicate content: {len(reps)} different pages, only identical texts compared")
    elif options.dup_threshold < 1:
        sets: list[set[int]] = []
        for d in reps:
            words = page_words(d)
            n = min(DUP_SHINGLE, len(words))
            sets.append({hash(tuple(words[i:i + n])) for i in range(len(words) - n + 1)})
        postings: dict[int, list[int]] = {}
        for index, group_set in enumerate(sets):
            for h in group_set:
                postings.setdefault(h, []).append(index)
        for index, group_set in enumerate(sets):
            counts: dict[int, int] = {}
            for h in group_set:
                posting = postings[h]
                if len(posting) > DUP_MAX_POSTING:
                    continue  # boilerplate shared by many pages
                for other in posting:
                    if other < index:
                        counts[other] = counts.get(other, 0) + 1
            for other, shared in sorted(counts.items()):
                ratio = shared / (len(sets[other]) + len(group_set) - shared)
                if ratio >= options.dup_threshold and not canonical_ok(reps[other], reps[index])                         and reps[index].file not in reported:
                    findings.append(Finding("duplicate-content", reps[index].file, f"{round(ratio * 100)}% same text as "
                                            f"{reps[other].file} (main content; set a canonical link or merge the pages)"))
                    reported.add(reps[index].file)
                    break
        _near_copies_of_boilerplate(reps, sets, postings, options.dup_threshold, reported, canonical_ok, findings)

    # orphan pages
    if orphans and len(documents) > 1:
        linked: set[str] = set()
        for d in documents:
            for href in d.links:
                target = href_route(d.file, href, own_hosts, False)
                other = by_route.get(target) if target else None
                if other and other != d.file:
                    linked.add(other)
        for d in documents:
            if orphan_suffixes and not d.file.lower().endswith(orphan_suffixes):
                continue  # a template is reached through the pages built from it: only a crawl can tell
            stem = d.file.rstrip("/").rsplit("/", 1)[-1].split(".", 1)[0].lower()
            if d.kind != "document" or d.file in linked or "/" in routes_of[d.file] or stem in ERROR_PAGE_NAMES:
                continue
            findings.append(Finding("orphan-page", d.file, "no other page links to it (crawlers find it only via the sitemap)"))


def check_translations(root: Path, findings: list[Finding], notes: list[str]) -> None:
    """Translation findings from i18n_check.py (called, not copied)."""
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        import i18n_check
    except ImportError as exc:
        notes.append(f"translations not checked: i18n_check.py could not be imported ({exc})")
        return
    report = i18n_check.run(root, None, True)
    if report["groups"]:
        notes.append("translations: " + "; ".join(f"{g['directory']} ({', '.join(g['locales'])})" for g in report["groups"]))
    for item in report["findings"]:
        kind = f"translation-{item['type']}"
        if kind not in SEVERITY:
            continue
        label = f"[{item['locale']}] " if item["locale"] else ""
        findings.append(Finding(kind, item["file"] or "translations", f"{label}{item['key']}  {item['detail']}".strip()))


def check_documents(documents: Mapping[str, str], options: Optional[Options] = None) -> dict:
    """All page checks on rendered documents given as {path or URL: HTML}, nothing read from disk.

    Per page: the usual title/description/heading/lang/canonical/og/alt checks plus viewport, image size and JSON-LD;
    across the set: duplicate title and description, hreflang, duplicate content, orphan pages (a link counts when it
    resolves to another key of the set). Links to files are not judged. Returns the same report dict as `run`."""
    options = options or Options()
    findings: list[Finding] = []
    notes: list[str] = []
    pages: list[PageInfo] = []
    for key, html in documents.items():
        parser = PageParser()
        try:
            parser.feed(html)
            parser.close()
        except (AssertionError, ValueError, RecursionError):
            pass
        parser.info.file = key
        parser.info.kind = "document"
        pages.append(parser.info)
    for page in pages:
        check_page(page, findings, Path("."), [], False)
        check_page_extended(page, findings)
    check_duplicate_meta(pages, findings)
    check_page_set(pages, findings, notes, options)
    return {"root": "", "stack": [], "pages": len(pages), "notes": notes, "findings": [asdict(f) for f in findings]}


def run(root: Path, options: Optional[Options] = None) -> dict:
    options = options or Options()
    findings: list[Finding] = []
    stack, generated = detect_stack(root)
    pages: list[PageInfo] = []
    route_files: list[Path] = []
    for current, files in walk(root):
        parts = set(current.relative_to(root).parts)
        for name in files:
            path = current / name
            suffix = path.suffix.lower()
            lower = name.lower()
            if suffix in HTML_SUFFIXES or suffix in TEMPLATE_SUFFIXES or lower.endswith(".blade.php"):
                try:
                    text = read_text(path)
                except (OSError, ValueError):
                    continue
                head = text[:4000].lower()
                is_route = bool(parts & PAGE_DIRS) or lower in ("+page.svelte", "page.tsx", "page.jsx")
                if "<html" in head or "<!doctype" in head:
                    kind = "document"
                elif is_route and suffix not in HTML_SUFFIXES:
                    kind = "page"
                else:
                    kind = "fragment"
                if is_route:
                    route_files.append(path)
                pages.append(parse_markup(root, path, kind, text))
            elif suffix == ".md" and (parts & MARKDOWN_DIRS) and "ai" not in parts:
                try:
                    info = parse_markdown(root, path, read_text(path))
                except (OSError, ValueError):
                    info = None
                if info:
                    pages.append(info)
    notes: list[str] = []
    has_markdown = any(p.kind == "markdown" for p in pages)
    link_check = not has_markdown
    if has_markdown:
        notes.append("Markdown pages found: internal links are not checked (routes depend on the generator)")
    routes = route_regexes(root, route_files)
    documents = [p for p in pages if p.kind in ("document", "markdown")]
    for page in pages:
        check_page(page, findings, root, routes, link_check)
    check_duplicate_meta(documents, findings)
    check_site(root, [p for p in pages if p.kind == "page"], generated, findings,
               [p for p in documents if p.kind == "document"])
    for page in pages:
        check_page_extended(page, findings)
    check_page_set([p for p in documents if p.kind == "document"], findings, notes, options,
                   orphans=not has_markdown, orphan_suffixes=(".html", ".htm"))
    check_translations(root, findings, notes)
    if not pages:
        notes.append("No HTML, template or Markdown pages found")
    return {"root": str(root), "stack": stack, "pages": len(pages), "notes": notes,
            "findings": [asdict(f) for f in findings]}


def render(report: dict) -> str:
    lines = [f"stack: {', '.join(report['stack']) or 'none detected'}  pages read: {report['pages']}"]
    lines += [f"note: {n}" for n in report["notes"]]
    findings = report["findings"]
    if not findings:
        lines.append("\nNo findings.")
        return "\n".join(lines)
    lines.append("")
    for kind in SEVERITY:
        items = [f for f in findings if f["type"] == kind]
        if not items:
            continue
        lines.append(f"{kind} ({SEVERITY[kind]}): {len(items)}")
        for item in items[:30]:
            lines.append(f"  {item['file']}  - {item['detail']}")
        if len(items) > 30:
            lines.append(f"  ... {len(items) - 30} more (use --json)")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Code-only SEO checks: title, description, headings, lang, "
                                     "canonical, Open Graph, image alt, internal links, robots.txt and sitemap.")
    parser.add_argument("--root", default=".", help="project root (default: current directory)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--dup-threshold", type=float, default=Options.dup_threshold,
                        help="share of identical text from which two pages count as duplicates, 0 < x <= 1 "
                        f"(default {Options.dup_threshold})")
    parser.add_argument("--dup-min-words", type=int, default=Options.dup_min_words,
                        help=f"pages with fewer words are not compared (default {Options.dup_min_words})")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        return 2
    if not 0 < args.dup_threshold <= 1 or args.dup_min_words < 1:
        print("--dup-threshold must be above 0 and at most 1, --dup-min-words at least 1", file=sys.stderr)
        return 2
    report = run(root, Options(args.dup_threshold, args.dup_min_words))
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else render(report))
    return 1 if any(f["severity"] in ("error", "warning") for f in report["findings"]) else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
