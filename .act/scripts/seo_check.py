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
# Usage:
#   python .act/scripts/seo_check.py [--root DIR] [--json]
#
# Exit code: 0 no finding above info, 1 at least one warning or error, 2 usage problem.

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from dataclasses import asdict, dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterator, Optional
from urllib.parse import urlparse

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
}
GENERATORS = ("sitemap", "robots")  # package/config names that generate these files at build time


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


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.info = PageInfo("", "document")
        self._in_title = False
        self._title_parts: list[str] = []
        self._skip = 0  # inside script/style
        self._heading_open = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        info = self.info
        if tag in ("script", "style"):
            self._skip += 1
        if tag == "html" and "lang" in a:
            info.lang_seen = True
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = (a.get("name") or a.get("property") or "").lower()
            content = a.get("content", "")
            if name == "description":
                info.description = content
            elif name.startswith("og:") and content.strip():
                info.og.add(name)
            elif name == "robots" and "noindex" in content.lower():
                info.noindex = True
        elif tag == "link" and "canonical" in a.get("rel", "").lower().split():
            info.canonical = True
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            info.headings.append(int(tag[1]))
        elif tag == "img":
            raw = self.get_starttag_text() or ""
            if not re.search(r"\balt\b", raw, re.I) and not TEMPLATE_SYNTAX.search(raw):
                info.images_without_alt += 1
        elif tag == "a" and a.get("href"):
            info.links.append(a["href"])
        elif tag == "div" and a.get("id") in ("app", "root", "__nuxt", "__next"):
            info.shell = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
            self.info.title = "".join(self._title_parts).strip()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)
        elif not self._skip:
            self.info.body_text += len(data.strip())


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


def run(root: Path) -> dict:
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
    for attr, kind in (("title", "duplicate-title"), ("description", "duplicate-description")):
        seen: dict[str, list[str]] = {}
        for page in documents:
            value = getattr(page, attr)
            if value and value.strip() and not TEMPLATE_SYNTAX.search(value):
                seen.setdefault(value.strip().lower(), []).append(page.file)
        for value, files in seen.items():
            if len(files) > 1:
                findings.append(Finding(kind, files[0], f"same {attr} on {len(files)} pages: {', '.join(files)}"))
    check_site(root, [p for p in pages if p.kind == "page"], generated, findings,
               [p for p in documents if p.kind == "document"])
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
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"Not a directory: {root}", file=sys.stderr)
        return 2
    report = run(root)
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.json else render(report))
    return 1 if any(f["severity"] in ("error", "warning") for f in report["findings"]) else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
