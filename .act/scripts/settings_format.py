#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Data model, parser and serializer for the settings file ("settings.md") — the portable
#          snapshot of a project's own rule deviations (and, in later stages, agents/skills/
#          scripts/checklists), used by `act-export-settings`/`act-load-settings` and by
#          `act-export-settings --profile` (writes the same shape to the Owner's profile instead
#          of a file). The full format is documented in the sections below.
#
#          This module has no CLI of its own — it is imported by settings_export.py (this build
#          stage) and, later, by a settings_import.py built on the same parse()/serialize() pair.
#          Three things live here:
#            - the data model (SettingsFile / SettingsHeader / SettingsArea / SettingsGroup /
#              SettingsEntry);
#            - parse(text) -> SettingsFile and serialize(settings) -> text, a lossless round trip
#              for anything this module itself produces (parse(serialize(x)) == x);
#            - scan(text)/redact(settings), the "review before sharing" secrets check run before
#              a settings file is written (`Q61d`).
#
#          Areas are logical categories, not tool paths (`rules`, `coding`, `agents`, `skills`,
#          `scripts`, `checklists`, `topics` — `Q61a`). Two of them
#          (`rules`, `coding`) are what this build stage's exporter fills in; the parser reads
#          every area structurally the same way ("[symbol] id — inline" + an optional indented or
#          fenced body), so an area this build does not yet *write* (agents, skills, ...) still
#          round-trips if a later stage or a hand-edited file supplies one. An area whose body does
#          not contain a single recognizable entry line is never guessed at — it is kept verbatim
#          in `SettingsArea.raw` instead of being dropped, and `SettingsFile.unmodeled_areas()`
#          reports which ones that happened for, so a caller can log/print it instead of a silent
#          loss ("don't swallow unmodeled areas, report them").
#
# Usage: not run directly — imported, e.g. `import settings_format` from a script in the same
#        directory (.act/scripts/, which adds itself to sys.path automatically).
#
# Output format: this module prints nothing; see the docstrings of parse()/serialize()/scan() for
#        the exact text shape each one produces/consumes.

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

SYMBOLS = ("=", "~", "-", "+")  # unchanged, overridden, switched off, own addition
KNOWN_AREAS = ("rules", "coding", "agents", "skills", "scripts", "checklists", "topics")


@dataclass
class SettingsHeader:
    version: str = ""
    commit: str = ""
    date: str = ""
    source: str = ""


@dataclass
class SettingsEntry:
    symbol: str                    # one of SYMBOLS
    id: str
    inline: Optional[str] = None   # short one-line content, rendered after " — " on the entry line
    body: Optional[str] = None     # multi-line content, rendered indented below the entry (fenced
                                    # as ```text when symbol == "~", plain indented text otherwise)


@dataclass
class SettingsGroup:
    label: Optional[str]                          # e.g. a coding set name ("typescript"); None
                                                    # for an area/entry run with no sub-grouping
    entries: list[SettingsEntry] = field(default_factory=list)


@dataclass
class SettingsArea:
    name: str
    groups: list[SettingsGroup] = field(default_factory=list)
    raw: Optional[str] = None      # verbatim body text for a shape this build does not model

    def is_modeled(self) -> bool:
        return self.raw is None


@dataclass
class SettingsFile:
    header: SettingsHeader
    areas: list[SettingsArea] = field(default_factory=list)
    setup_required: list[str] = field(default_factory=list)  # one rendered line per finding

    def area(self, name: str) -> Optional[SettingsArea]:
        return next((a for a in self.areas if a.name == name), None)

    def unmodeled_areas(self) -> list[str]:
        """Names of areas present in the file whose body could not be parsed into groups/entries
        (no recognizable "[symbol] id" line) — kept in `.raw` instead of being dropped."""
        return [a.name for a in self.areas if not a.is_modeled()]


# ---------------------------------------------------------------------------
# Line grammar
# ---------------------------------------------------------------------------

_RE_HEADER_KV = re.compile(r"^(?P<key>[\w-]+):\s*(?P<value>.*)$")
_RE_AREA_HEADING = re.compile(r"^##\s+(?P<name>\S+)\s*$")
_RE_SETUP_HEADING = re.compile(r"^##\s+setup-required\s*$")
_RE_ENTRY = re.compile(r"^\[(?P<symbol>[=~+-])\]\s+(?P<id>\S+)(?:\s+—\s+(?P<inline>.*))?\s*$")
_RE_FENCE = re.compile(r"^(?P<fence>`{3,}|~{3,})\s*\S*\s*$")
_RE_SETUP_ITEM = re.compile(r"^-\s+(?P<text>.*)$")


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse(text: str) -> SettingsFile:
    """Parse a settings.md document (front matter + '## <area>' blocks + an optional
    '## setup-required' list) into a SettingsFile. Tolerant by design: a missing front-matter
    field is left as "", and an area whose body does not look like a "[symbol] id" list at all is
    kept verbatim (see SettingsArea.raw) instead of raising — the only thing this function ever
    raises for is a front matter that is not properly fenced by two "---" lines."""
    lines = text.splitlines()
    header, rest = _parse_header(lines)

    areas: list[SettingsArea] = []
    setup_required: list[str] = []
    i = 0
    n = len(rest)
    while i < n:
        line = rest[i]
        if _RE_SETUP_HEADING.match(line.strip()):
            i += 1
            while i < n:
                item = _RE_SETUP_ITEM.match(rest[i].strip())
                if item:
                    setup_required.append(item.group("text"))
                i += 1
            continue
        heading = _RE_AREA_HEADING.match(line.strip())
        if heading:
            name = heading.group("name")
            i += 1
            block: list[str] = []
            while i < n and not rest[i].strip().startswith("## "):
                block.append(rest[i])
                i += 1
            areas.append(_parse_area(name, block))
            continue
        i += 1  # blank line or stray text between areas — not part of any area, ignored

    return SettingsFile(header=header, areas=areas, setup_required=setup_required)


def _parse_header(lines: list[str]) -> tuple[SettingsHeader, list[str]]:
    i = 0
    n = len(lines)
    while i < n and not lines[i].strip():
        i += 1
    if i >= n or lines[i].strip() != "---":
        raise ValueError("settings.md: missing front matter (expected a leading '---' block)")
    i += 1
    fields: dict[str, str] = {}
    while i < n and lines[i].strip() != "---":
        match = _RE_HEADER_KV.match(lines[i].strip())
        if match:
            fields[match.group("key")] = match.group("value").strip()
        i += 1
    if i >= n:
        raise ValueError("settings.md: front matter not closed with a second '---' line")
    i += 1  # past the closing '---'
    header = SettingsHeader(
        version=fields.get("version", ""),
        commit=fields.get("commit", ""),
        date=fields.get("date", ""),
        source=fields.get("source", ""),
    )
    return header, lines[i:]


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _dedent_lines(lines: list[str]) -> str:
    """Join `lines` back into one string, stripping the smallest common leading indent of the
    non-blank lines (a plain dedent, not textwrap.dedent, so a fenced code block's own internal
    indentation survives untouched)."""
    non_blank = [ln for ln in lines if ln.strip()]
    if not non_blank:
        return ""
    common = min(_indent_of(ln) for ln in non_blank)
    return "\n".join(ln[common:] if len(ln) >= common else ln.lstrip(" ") for ln in lines).strip("\n")


def _parse_area(name: str, block: list[str]) -> SettingsArea:
    groups: list[SettingsGroup] = []
    current_group: Optional[SettingsGroup] = None
    current_entry: Optional[SettingsEntry] = None
    body_lines: list[str] = []
    fence: Optional[str] = None
    saw_entry = False
    unrecognized = False

    def close_body() -> None:
        nonlocal body_lines
        if current_entry is not None and body_lines:
            current_entry.body = _dedent_lines(body_lines)
        body_lines = []

    for raw in block:
        if fence is not None:
            if raw.strip().startswith(fence):
                fence = None
            else:
                body_lines.append(raw)
            continue

        stripped = raw.strip()
        if not stripped:
            close_body()
            continue

        indent = _indent_of(raw)
        entry_match = _RE_ENTRY.match(stripped)
        if entry_match:
            close_body()
            saw_entry = True
            if indent == 0 and (current_group is None or current_group.label is not None):
                current_group = SettingsGroup(label=None)
                groups.append(current_group)
            elif indent > 0 and current_group is None:
                current_group = SettingsGroup(label=None)
                groups.append(current_group)
            entry = SettingsEntry(
                symbol=entry_match.group("symbol"), id=entry_match.group("id"),
                inline=entry_match.group("inline"),
            )
            current_group.entries.append(entry)
            current_entry = entry
            continue

        fence_match = _RE_FENCE.match(stripped)
        if fence_match and current_entry is not None:
            close_body()
            fence = fence_match.group("fence")[0] * 3
            continue

        if indent == 0:
            close_body()
            current_group = SettingsGroup(label=stripped)
            groups.append(current_group)
            current_entry = None
            continue

        if current_entry is not None:
            body_lines.append(raw)
            continue

        unrecognized = True

    close_body()

    if not saw_entry or unrecognized:
        return SettingsArea(name=name, raw="\n".join(block).strip("\n"))
    return SettingsArea(name=name, groups=groups)


# ---------------------------------------------------------------------------
# Serializing
# ---------------------------------------------------------------------------

def serialize(settings: SettingsFile) -> str:
    """Render a SettingsFile back into settings.md text. Always ends with a single trailing
    newline. For a modeled area (SettingsArea.raw is None), entries are rendered as
    "[symbol] id[ — inline]", followed by an indented body when set: a fenced ```text block for a
    "~" entry, a plain indented block otherwise. An unmodeled area is written back exactly as its
    `.raw` text."""
    out: list[str] = ["---", "act-settings: 1"]
    if settings.header.version:
        out.append(f"version: {settings.header.version}")
    if settings.header.commit:
        out.append(f"commit: {settings.header.commit}")
    if settings.header.date:
        out.append(f"date: {settings.header.date}")
    if settings.header.source:
        out.append(f"source: {settings.header.source}")
    out.append("---")
    out.append("")

    for area in settings.areas:
        out.append(f"## {area.name}")
        out.append("")
        if not area.is_modeled():
            if area.raw:
                out.append(area.raw)
                out.append("")
            continue
        for group in area.groups:
            indent = "  " if group.label is not None else ""
            if group.label is not None:
                out.append(group.label)
            for entry in group.entries:
                head = f"{indent}[{entry.symbol}] {entry.id}"
                if entry.inline:
                    head += f" — {entry.inline}"
                out.append(head)
                if entry.body:
                    body_indent = indent + "    "
                    if entry.symbol == "~":
                        out.append(f"{body_indent}```text")
                        out.extend(f"{body_indent}{ln}" if ln else "" for ln in entry.body.splitlines())
                        out.append(f"{body_indent}```")
                    else:
                        out.extend(f"{body_indent}{ln}" if ln else "" for ln in entry.body.splitlines())
            out.append("")

    if settings.setup_required:
        out.append("## setup-required")
        out.append("")
        out.extend(f"- {line}" for line in settings.setup_required)
        out.append("")

    text = "\n".join(out)
    while text.endswith("\n\n"):
        text = text[:-1]
    return text if text.endswith("\n") else text + "\n"


# ---------------------------------------------------------------------------
# Secrets/local-machine-specifics scan ("review before sharing", Q61d)
# ---------------------------------------------------------------------------

@dataclass
class ScanFinding:
    kind: str          # "secret" | "mail" | "ip" | "path" | "hex" | "host"
    placeholder: str   # e.g. "<setup:SECRET>", numbered "<setup:SECRET-2>" from the 2nd hit on
    hint: str           # short description of what belongs there, for a "## setup-required" line


@dataclass
class ScanResult:
    text: str                    # `text` with every match replaced by its placeholder
    findings: list[ScanFinding]  # in the order the matches were found


# A credential word is only flagged together with an assigned value ("api_key = ..." /
# "password: ..."), not on its own — a rule that merely *talks about* passwords must stay
# readable. Kept close to the pattern list in
# template-agentic-coding-project/.claude/scripts/feedback.py (~L208-260), extended with an
# assignment requirement and Windows/UNC/home-directory paths, which that script does not need.
#
# The captured "secretval" group is what _looks_like_secret() judges — the whole match (keyword +
# separator + value) is still what gets replaced, so a rejected match ("Token: jede Anfrage")
# leaves prose untouched instead of only un-redacting the value.
_SECRET_ASSIGN = re.compile(
    r"(?i)\b(?:pass(?:word|wort)|secret|token|api[_-]?key|credential|zugangsdaten|private[_-]?key)"
    r"\b\s*[:=]\s*(?P<secretval>\S+)"
)
# "Das Passwort ist hunter2" / "the token is ..." — a credential named in prose, not an
# assignment. Any single word here counts (no length/character-class gate): the sentence shape
# itself is the signal, unlike a bare "key: value" line that "Token: jede Anfrage" also matches.
_SECRET_WORD_ASSIGN = re.compile(
    r"(?i)\b(?:pass(?:word|wort)|secret|token|api[_-]?key|credential|zugangsdaten|private[_-]?key)"
    r"\b\s+(?:ist|is)\s+(?P<secretval>\S+)"
)
_GITHUB_TOKEN = re.compile(r"\b(?:ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b")
_AWS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN[ \w]*PRIVATE KEY-----[\s\S]*?-----END[ \w]*PRIVATE KEY-----"
)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b")
_BEARER_TOKEN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-_.=]{8,}\b")
_SLACK_TOKEN = re.compile(r"\bxox[bap]-[A-Za-z0-9-]+\b")
_OPENAI_KEY = re.compile(r"\bsk-[A-Za-z0-9]{16,}\b")
_MAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
# Octets 0-255 only, and not an IP at all right after "version"/"v" (the "ip" guard in scan()
# checks the text immediately before a match for that) — a semantic-version-looking "1.2.3.4"
# after "Version "/"v" is not flagged.
_IP = re.compile(r"\b(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)(?:\.(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)){3}\b")
_UNC_PATH = re.compile(r"\\\\[^\s\\]+(?:\\[^\s\\]+)+")
_WIN_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s'\"]*")
# Only an actual "/home/<user>/…", "/Users/<user>/…" (a bare "~/..." is left alone — "~/.claude/
# agents" is normal prose about a tool's own config path, not a local secret path; a Windows
# "C:\Users\<user>\..." is already caught by _WIN_PATH above).
_HOME_PATH = re.compile(r"(?<![\w.])(?:/home/|/Users/)[^\s'\"/]+(?:/[^\s'\"]*)?")
_LONG_HEX = re.compile(r"\b[0-9a-fA-F]{32,}\b")
_URL = re.compile(r"https?://[^\s)]+")
# Project-neutral references the template itself uses everywhere and must never be touched.
_SAFE_PREFIX = re.compile(r"^(?:\.act/|docs/ai/|docs/project/)")
_HOST_TABU = re.compile(
    r"^(?:localhost$|127\.|10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.|\[?::1)"
    r"|\.(?:local|internal|intern|lan|home|test|invalid|example)$", re.I,
)
_VERSION_PREFIX = re.compile(r"(?i)\bv(?:ersion)?\.?\s*$")


def _looks_like_secret(value: str) -> bool:
    """True for a `_SECRET_ASSIGN` value that looks like an actual credential rather than
    ordinary prose: quoted, or at least 8 characters with a digit or a symbol mixed in (plain-
    letter words, however capitalized, are not enough — that is what makes them "normal words")."""
    core = value[1:-1] if len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0] else value
    quoted = core is not value
    if len(core) < 8:
        return False
    has_digit = any(c.isdigit() for c in core)
    has_symbol = any(not c.isalnum() for c in core)
    return quoted or has_digit or has_symbol


# (kind, pattern, hint, needs_secret_check) — the last only True for _SECRET_ASSIGN, whose match
# may be ordinary prose ("Token: jede Anfrage"); every other pattern here is specific enough
# (a structured token format, or a keyword stated in a sentence) to always redact its match.
_PLAIN_PATTERNS: tuple[tuple[str, "re.Pattern[str]", str, bool], ...] = (
    ("secret", _SECRET_ASSIGN, "a credential value (password/token/API key/...)", True),
    ("secret", _SECRET_WORD_ASSIGN, "a credential named in prose (\"... ist/is ...\")", False),
    ("secret", _GITHUB_TOKEN, "a GitHub access token", False),
    ("secret", _AWS_KEY, "an AWS access key id", False),
    ("secret", _PRIVATE_KEY_BLOCK, "a private key block", False),
    ("secret", _JWT, "a JWT", False),
    ("secret", _BEARER_TOKEN, "a bearer token", False),
    ("secret", _SLACK_TOKEN, "a Slack token", False),
    ("secret", _OPENAI_KEY, "an API key (sk-...)", False),
    ("mail", _MAIL, "a mail address", False),
    ("ip", _IP, "an IP address", False),
    ("path", _UNC_PATH, "a local UNC network path", False),
    ("path", _WIN_PATH, "a local Windows path", False),
    ("path", _HOME_PATH, "a local home directory path", False),
    ("hex", _LONG_HEX, "a long hex value (key or hash?)", False),
)


def scan(text: Optional[str]) -> ScanResult:
    """Scan one piece of free text for likely secrets and local-machine specifics. Returns the
    text with every match replaced by a "<setup:KIND>" placeholder (numbered from the second hit
    of the same kind on: "<setup:KIND-2>", ...) plus the list of findings, in the order the
    matches were made. Pure string function — no notion of *where* this text came from; the
    caller (redact()) supplies that when it turns a finding into a "## setup-required" line."""
    if not text:
        return ScanResult(text=text or "", findings=[])

    out = text
    findings: list[ScanFinding] = []
    counters: dict[str, int] = {}

    def placeholder_for(kind: str) -> str:
        counters[kind] = counters.get(kind, 0) + 1
        suffix = "" if counters[kind] == 1 else f"-{counters[kind]}"
        return f"<setup:{kind.upper()}{suffix}>"

    for kind, pattern, hint, needs_check in _PLAIN_PATTERNS:
        def repl(match: "re.Match[str]", _kind: str = kind, _hint: str = hint, _needs_check: bool = needs_check) -> str:
            value = match.group(0)
            if _kind == "path" and _SAFE_PREFIX.match(value):
                return value
            if _kind == "ip" and _VERSION_PREFIX.search(out[:match.start()]):
                return value
            if _needs_check and not _looks_like_secret(match.group("secretval")):
                return value
            token = placeholder_for(_kind)
            findings.append(ScanFinding(kind=_kind, placeholder=token, hint=_hint))
            return token
        out = pattern.sub(repl, out)

    def repl_url(match: "re.Match[str]") -> str:
        url = match.group(0)
        rest = re.sub(r"(?i)^https?://", "", url)
        host = rest.split("/", 1)[0].split("@")[-1].split(":", 1)[0]
        if not _HOST_TABU.search(host):
            return url
        token = placeholder_for("host")
        findings.append(ScanFinding(kind="host", placeholder=token, hint="an internal/local URL"))
        return token
    out = _URL.sub(repl_url, out)

    return ScanResult(text=out, findings=findings)


def redact(settings: SettingsFile) -> tuple[SettingsFile, list[tuple[str, ScanFinding]]]:
    """Run scan() over every free-text piece of `settings` (entry inline/body text and every
    unmodeled area's raw text) and return (redacted_copy, located_findings) — a new SettingsFile
    with matches replaced by placeholders, and each finding paired with a short location string
    ("<area>" or "<area>: `<id>`") for the caller to render as a "## setup-required" line. The
    input is never mutated; `redacted_copy.setup_required` starts empty — filling it in is the
    caller's choice (see settings_export.py), so a --strict run can inspect the findings first and
    abort before ever calling serialize()."""
    located: list[tuple[str, ScanFinding]] = []
    new_areas: list[SettingsArea] = []

    for area in settings.areas:
        if not area.is_modeled():
            result = scan(area.raw)
            for finding in result.findings:
                located.append((area.name, finding))
            new_areas.append(SettingsArea(name=area.name, raw=result.text))
            continue

        new_groups: list[SettingsGroup] = []
        for group in area.groups:
            new_entries: list[SettingsEntry] = []
            for entry in group.entries:
                location = f"{area.name}: `{entry.id}`"
                inline_result = scan(entry.inline) if entry.inline else None
                body_result = scan(entry.body) if entry.body else None
                if inline_result:
                    for finding in inline_result.findings:
                        located.append((location, finding))
                if body_result:
                    for finding in body_result.findings:
                        located.append((location, finding))
                new_entries.append(SettingsEntry(
                    symbol=entry.symbol, id=entry.id,
                    inline=inline_result.text if inline_result else entry.inline,
                    body=body_result.text if body_result else entry.body,
                ))
            new_groups.append(SettingsGroup(label=group.label, entries=new_entries))
        new_areas.append(SettingsArea(name=area.name, groups=new_groups))

    redacted = SettingsFile(header=settings.header, areas=new_areas, setup_required=[])
    return redacted, located


def setup_required_lines(located: list[tuple[str, ScanFinding]]) -> list[str]:
    """Render redact()'s (location, finding) pairs as the text of "## setup-required" bullet
    lines: "<location> — <hint> (<placeholder>)"."""
    return [f"{location} — {finding.hint} ({finding.placeholder})" for location, finding in located]
