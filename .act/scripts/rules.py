#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Read the *effective* rules — the template's rule sets after the project's own
#          checkboxes, replacements and additions are applied. One script, one parser, for both
#          rule areas: coding rules (template source .act/coding/<set>.md, project file
#          docs/project/coding_rules.md, IDs "CR-...") and core rules (template source
#          .act/rules/**/*.md, project file docs/ai/rules.md, IDs "R-..."). Both areas use the
#          same schema, described below.
#
#          The parser reads only the language-neutral marks a project file can contain — a
#          checkbox, "use:", a backticked ID, "replaces", an "@path"/"`path`" set reference — and
#          never the surrounding headings or prose, which stay in the project's own language.
#
# Usage:
#   python .act/scripts/rules.py                        # effective rule text for an AI, area=coding
#   python .act/scripts/rules.py --area core             # same, for docs/ai/rules.md
#   python .act/scripts/rules.py --list                  # human overview, one line per set/group
#   python .act/scripts/rules.py CR-nuxt-basics           # one group in full, with its origin
#   python .act/scripts/rules.py --validate               # schema + cross-checks, exit 1 on any finding
#   python .act/scripts/rules.py --imports [--from FILE]  # which files Claude Code loads from CLAUDE.md
#
# Output format:
#   Default and <id>: Markdown, meant to be pasted into a model's context.
#   --list: "[symbol] id — summary" per set, one indented "[symbol] id[ — reason]" per group below
#     it (symbols: "=" unchanged, "~" overridden, "-" switched off, "+" own addition).
#   --validate: one finding per line as "<path>:<line>: <message>", nothing printed and exit 0 if
#     there are no findings. Text under "Own rules" that is not read as a rule (a heading, prose, a
#     table, a code fence) follows as "<path>:<line>: note: <message>", one per run of such lines —
#     a note never changes the exit code. Own rules are "- ", "* " or "+ " bullets.
#   --imports: "reached <n>:" and one indented root-relative path per file Claude Code loads, in
#     load order, then "unresolved <n>:" and one "<file>:<line>: @<target> — <reason>" per import
#     it cannot follow (exit 1 if there is any). Same rule as Claude Code (T64): relative to the
#     importing file, at most four hops below the start file, never inside a code span or block.
#   Errors (unknown area, missing project file, unknown id, bad arguments): one line on stderr,
#     exit 1 (2 for a bad command line), never a traceback.

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import actlib


# ---------------------------------------------------------------------------
# Area configuration — the one place that knows the two file layouts apart
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Area:
    name: str
    project_file: str  # relative to repo root


AREAS = {
    "coding": Area("coding", "docs/project/coding_rules.md"),
    "core": Area("core", "docs/ai/rules.md"),
}


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class ProjectGroup:
    enabled: bool
    reason: Optional[str]
    line: int


@dataclass
class ProjectSet:
    path: str  # as written in the project file, e.g. ".act/coding/nuxt.md"
    enabled: bool
    line: int
    groups: dict[str, ProjectGroup] = field(default_factory=dict)


@dataclass
class Override:
    id: str
    text: str
    line: int


@dataclass
class OwnRule:
    id: Optional[str]
    text: str
    line: int


@dataclass
class ProjectFile:
    path: Path
    sets: list[ProjectSet]
    overrides: list[Override]
    own_rules: list[OwnRule]
    findings: list[tuple[int, str]]  # (line, message) — schema-level problems found while parsing
    # (line, message) — text under "Own rules" that is not read as a rule; a note, never a finding
    hints: list[tuple[int, str]] = field(default_factory=list)


@dataclass
class TemplateGroup:
    id: str
    title: str
    summary: Optional[str]
    body: str  # full text of the section, heading line included
    line: int


@dataclass
class TemplateSet:
    path: Path
    origin: str  # "local" or "template"
    summary: Optional[str]
    requires: list[str]
    groups: dict[str, TemplateGroup]  # insertion order == order in the file


# ---------------------------------------------------------------------------
# Line grammar (see header comment — marks only, headings/prose are never read)
# ---------------------------------------------------------------------------

RE_CHECKBOX = re.compile(r"^(?P<indent>\s*)-\s*\[(?P<mark>[ xX])\](?![(\[])\s*(?P<rest>.*)$")
# A near-miss checkbox ("[X ]", "[-]", "[]") is reported; a Markdown link "- [Text](target)"
# or "- [Text][ref]" never is — only a mark of at most two characters counts as a try.
RE_CHECKBOX_LOOSE = re.compile(r"^(?P<indent>\s*)-\s*\[(?P<mark>[^\]]{0,2})\](?![(\[])\s*(?P<rest>.*)$")
RE_USE = re.compile(r"^use:\s*(?P<path>\S+)\s*$")
# The reason separator is an em dash; an en dash or "--" (what people type instead) counts the same.
RE_GROUP_ID = re.compile(r"^`(?P<id>[^`]+)`\s*(?:(?:—|–|--)\s*(?P<reason>.+))?$")
# "- replaces ..." — and, like an own rule, "* replaces ..." / "+ replaces ..." (Q113).
RE_REPLACES = re.compile(r"^(?:-\s*|[*+]\s+)replaces\s+`(?P<id>[^`]+)`:\s*(?P<text>.*)$")
RE_REPLACES_LOOSE = re.compile(r"^(?:-\s*|[*+]\s+)replaces\b.*$")
# A core set is "@<path>" (imported), "`<path>`" (listed only) or a bare path; the "@" form is
# written relative to docs/ai/ since T64 ("@../../.act/..."), the pre-T64 "@.act/..." still parses.
RE_CORE_SET = re.compile(r"^(?:@(?:\.\./)*|`)?(?P<path>\.act/\S+?\.md)`?$")
# An own rule is a "- ", "* " or "+ " bullet (Q113: a hand-written or adopted "*" list counted as prose
# before and silently dropped every rule in it).
RE_BULLET = re.compile(r"^[-*+]\s+")
# "* * *" / "- - -" is a thematic break, not a bullet.
RE_THEMATIC_BREAK = re.compile(r"^(?:\*\s*){3,}$|^(?:-\s*){3,}$|^(?:\+\s*){3,}$")
RE_OWN = re.compile(r"^[-*+]\s+(?:`(?P<id>[^`]+)`:\s*)?(?P<text>.*)$")
RE_HEADING = re.compile(r"^##\s+`(?P<id>[^`]+)`\s*(?:—\s*(?P<title>.+))?\s*$")
RE_HEADER_FIELD = re.compile(r"^(?P<key>summary|requires|retired):\s*(?P<value>.*)$", re.IGNORECASE)

# Section tracking inside a project file (B-follow-up to B77): "replaces" and bare "- ..." bullets
# at the top level are only read as overrides/own rules while the surrounding top-level ("## ")
# section is actually "## Overrides"/"## Own rules" — never inside "## Known deviations" (own text
# in its own right, one line per accepted deviation, not a rule) or a heading recognized as some
# other section of the template (e.g. "## Rule sets", "## Shared"). The mark comment
# (`<!-- act:... -->`), if present, decides over the heading word. But a heading neither marked nor
# recognized (in particular a translated heading with no mark yet, `R-work-language`) is *not*
# assumed to be some other section — that would silently drop a project's overrides and own rules
# the moment their heading is translated. Such an unrecognized heading falls back to the rule from
# before this section tracking existed: read "replaces"/"- ..." by shape alone, wherever they sit.
# A recognized-other section still gets a --validate finding for a "replaces" line or an own-rule-
# shaped bullet (`- \`ID\`: ...`) found there, instead of silently discarding it.
RE_SECTION_MARK = re.compile(r"^<!--\s*act:(?P<name>[a-z0-9-]+)\s*-->\s*$", re.IGNORECASE)
RE_TOP_HEADING = re.compile(r"^##\s+(?P<title>.+?)\s*$")
MARK_TO_SECTION = {"overrides": "overrides", "own-rules": "own-rules"}
HEADING_TO_SECTION_FALLBACK = {"overrides": "overrides", "own rules": "own-rules"}
# English headings the template actually uses for something other than overrides/own rules — a
# trailing " — ..." (as in "## Shared — every role, including sub-agents") is stripped before the
# lookup. Anything not in here or the fallback above (in particular any translated heading without
# a mark) counts as unrecognized, not as "some other section" (see comment above).
KNOWN_OTHER_HEADINGS = {
    "known deviations", "rule sets", "rule sets from the template",
    "shared", "coding", "orchestrator only",
}


def normalize_set_path(raw: str) -> str:
    """A set path as written in a project file, in any of its forms — "@../../.act/coding/x.md"
    (an import, relative to the project file, T64), the pre-T64 "@.act/coding/x.md", "`...`" or a
    bare ".act/coding/x.md" — as the root-relative ".act/coding/x.md" every other function here
    expects."""
    path = raw.strip().strip("`")
    if path.startswith("@"):
        path = path[1:]
    while path.startswith(("../", "./")):
        path = path[3:] if path.startswith("../") else path[2:]
    return path


def import_path(set_path: str, project_file: str) -> str:
    """Root-relative `set_path` as an "@" import written from `project_file` (root-relative):
    Claude Code resolves imports relative to the importing file, so docs/ai/rules.md imports
    ".act/rules/shared/00-core.md" as "@../../.act/rules/shared/00-core.md"."""
    return "@" + "../" * project_file.count("/") + normalize_set_path(set_path)


def strip_template_prefix(path: str) -> str:
    """Turn a set path as written in the project file (e.g. ".act/coding/nuxt.md") into the
    template-relative path actlib.resolve() expects (e.g. "coding/nuxt.md")."""
    if path.startswith(".act/"):
        return path[len(".act/"):]
    return path


# ---------------------------------------------------------------------------
# Parsing the project file (docs/project/coding_rules.md or docs/ai/rules.md)
# ---------------------------------------------------------------------------

@dataclass
class _UnreadRun:
    """A run of text under "Own rules" that is not read as a rule (hint bookkeeping)."""
    line: int
    count: int
    snippet: str


def _fence_open(line: str) -> Optional[str]:
    """The fence string ("```", "~~~~", ...) if `line` opens a fenced code block, else None. As in
    CommonMark, a backtick fence whose info string contains a backtick is inline code ("```x``` is
    ..."), not a fence."""
    match = RE_FENCE.match(line)
    if not match:
        return None
    fence = match.group("fence")
    if fence[0] == "`" and "`" in line[match.end():]:
        return None
    return fence


def _is_bullet(stripped: str) -> bool:
    return bool(RE_BULLET.match(stripped)) and not RE_THEMATIC_BREAK.match(stripped)


def _is_new_item(raw: str, stripped: str) -> bool:
    """True if `raw` starts a new list item/checkbox rather than continuing the previous one — a
    bullet ("- ...", "* ...", "+ ..." or "- [ ] ...", indented or not) or a near-miss checkbox mark.
    Used by parse_project_file to know where an own rule's continuation lines end (B131)."""
    return _is_bullet(stripped) or bool(RE_CHECKBOX_LOOSE.match(raw))


def parse_project_file(path: Path, area: Area) -> ProjectFile:
    lines = path.read_text(encoding="utf-8").splitlines()
    sets: list[ProjectSet] = []
    overrides: list[Override] = []
    own_rules: list[OwnRule] = []
    findings: list[tuple[int, str]] = []
    current_set: Optional[ProjectSet] = None
    current_section: Optional[str] = None  # None until the first "## " section is seen
    hints: list[tuple[int, str]] = []
    # Text under "Own rules" that is not read as a rule, merged per run (blank lines do not break
    # a run); at most one entry.
    pending: list[_UnreadRun] = []
    fence: Optional[str] = None
    fence_line = 0
    in_comment = False

    def flush_pending() -> None:
        if pending:
            run = pending[0]
            shown = run.snippet if len(run.snippet) <= 40 else run.snippet[:40] + "…"
            hints.append((run.line, f"{run.count} line(s) under 'Own rules' not read as rules (heading, "
                                 f"prose, table or code, starting \"{shown}\") — write each rule as "
                                 "a '- ' bullet, optionally '- `ID`: text'"))
            pending.clear()

    def note_unread(number: int, text: str) -> None:
        if current_section != "own-rules":
            return
        if pending:
            pending[0].count += 1
        else:
            pending.append(_UnreadRun(line=number, count=1, snippet=text))

    total = len(lines)
    i = 0
    while i < total:
        line_no = i + 1
        raw = lines[i]
        i += 1
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        # An HTML comment (the template's own "one item per rule" hint) is neither rule nor text.
        if in_comment:
            in_comment = "-->" not in stripped
            continue
        if fence is None and stripped.startswith("<!--") and not RE_SECTION_MARK.match(stripped):
            in_comment = "-->" not in stripped
            continue

        # A fenced code block is example text: nothing inside is read as a rule, a set line or an
        # override (Q113); under "Own rules" it counts as unread text.
        fence_match = RE_FENCE.match(line)
        if fence is not None:
            if fence_match and fence_match.group("fence")[0] == fence[0] \
                    and len(fence_match.group("fence")) >= len(fence):
                fence = None
            note_unread(line_no, stripped)
            continue
        opened = _fence_open(line)
        if opened is not None:
            fence, fence_line = opened, line_no
            note_unread(line_no, stripped)
            continue

        checkbox = RE_CHECKBOX.match(line)
        if checkbox:
            indent, mark, rest = checkbox.group("indent"), checkbox.group("mark"), checkbox.group("rest")
            enabled = mark in ("x", "X")
            if indent == "":
                if area.name != "coding":
                    findings.append((line_no, "a checkbox set line ('use:') is only valid for --area coding"))
                    current_set = None
                    continue
                use = RE_USE.match(rest)
                if not use:
                    findings.append((line_no, "expected '- [ ] use: <path>'"))
                    current_set = None
                    continue
                current_set = ProjectSet(path=normalize_set_path(use.group("path")), enabled=enabled, line=line_no)
                sets.append(current_set)
            else:
                group = RE_GROUP_ID.match(rest)
                if not group:
                    findings.append((line_no, "expected '  - [ ] `ID`' with an optional ' — reason'"))
                    continue
                if current_set is None:
                    findings.append((line_no, "group checkbox with no preceding set line"))
                    continue
                current_set.groups[group.group("id")] = ProjectGroup(
                    enabled=enabled, reason=group.group("reason"), line=line_no,
                )
            continue

        loose = RE_CHECKBOX_LOOSE.match(line)
        if loose:
            findings.append((line_no, "invalid checkbox mark, expected '[ ]' or '[x]'"))
            continue

        if line[:1] not in (" ", "\t"):
            mark = RE_SECTION_MARK.match(stripped)
            if mark:
                # An explicit mark is always a recognized section, even one this script has no
                # special handling for ("excluded" — see the gating below).
                flush_pending()
                current_section = MARK_TO_SECTION.get(mark.group("name").lower(), "excluded")
                continue
            heading = RE_TOP_HEADING.match(stripped)
            if heading:
                flush_pending()
                title_key = heading.group("title").split("—", 1)[0].strip().lower()
                if title_key in HEADING_TO_SECTION_FALLBACK:
                    current_section = HEADING_TO_SECTION_FALLBACK[title_key]
                elif title_key in KNOWN_OTHER_HEADINGS:
                    current_section = "excluded"
                else:
                    current_section = "unknown"
                continue

            if area.name == "core":
                core_set = RE_CORE_SET.match(stripped)
                if core_set:
                    current_set = ProjectSet(path=core_set.group("path"), enabled=True, line=line_no)
                    sets.append(current_set)
                    continue
                if re.match(r"^@?(?:\.\./)*\.act/", stripped):
                    findings.append((line_no, "expected '@<path>.md' or '`<path>.md`'"))
                    continue

            # "unknown" (no mark, heading not recognized — in particular a translated heading with
            # no mark yet) and "None" (before the first "## " section) fall back to the old,
            # section-agnostic reading, so a project file is never silently stripped of its
            # overrides and own rules just because its headings were translated.
            if current_section in (None, "unknown", "overrides"):
                replaces = RE_REPLACES.match(stripped)
                if replaces:
                    overrides.append(Override(id=replaces.group("id"), text=replaces.group("text"), line=line_no))
                    continue
                if RE_REPLACES_LOOSE.match(stripped):
                    findings.append((line_no, "expected '- replaces `ID`: <text>'"))
                    continue
            elif current_section == "excluded" and RE_REPLACES_LOOSE.match(stripped):
                findings.append((line_no,
                    "'replaces' found outside '## Overrides' (section recognized as something "
                    "else) — ignored"))
                continue

            if current_section in (None, "unknown", "own-rules") and _is_bullet(stripped):
                flush_pending()
                own = RE_OWN.match(stripped)
                text_parts = [(own.group("text") if own else stripped[2:]).strip()]
                # Indented continuation lines (B131) belong to this same rule's text, joined with
                # single spaces, up to the next blank line, the next bullet/checkbox (indented or
                # not — _is_new_item), or the next unindented line (heading or a new top-level
                # entry) — whichever comes first.
                while i < total:
                    cont_raw = lines[i]
                    cont_stripped = cont_raw.strip()
                    if not cont_stripped or cont_raw[:1] not in (" ", "\t") \
                            or _is_new_item(cont_raw, cont_stripped) or _fence_open(cont_raw):
                        break
                    text_parts.append(cont_stripped)
                    i += 1
                own_rules.append(OwnRule(id=own.group("id") if own else None,
                                          text=" ".join(text_parts), line=line_no))
                continue
            if current_section == "excluded" and _is_bullet(stripped):
                own = RE_OWN.match(stripped)
                if own and own.group("id"):
                    findings.append((line_no,
                        "rule-shaped bullet found outside '## Own rules' (section recognized as "
                        "something else) — ignored"))
                    continue
            # heading or prose in the project's own language — not read by the mechanism (under
            # "Own rules" it is reported as a hint, see ProjectFile.hints).
            note_unread(line_no, stripped)
        else:
            # Indented text nothing above consumed (a nested bullet, an indented paragraph or
            # table): under "Own rules" it is not read either — a hint like any other unread text.
            note_unread(line_no, stripped)

    flush_pending()
    if fence is not None:
        findings.append((fence_line, f"unclosed code fence opened at line {fence_line} — rest of "
                                     "the file ignored"))
    return ProjectFile(path=path, sets=sets, overrides=overrides, own_rules=own_rules,
                       findings=findings, hints=hints)


# ---------------------------------------------------------------------------
# Parsing a template set file (.act/coding/<set>.md or .act/rules/**/*.md)
# ---------------------------------------------------------------------------

def parse_template_set(path: Path, origin: str) -> TemplateSet:
    lines = path.read_text(encoding="utf-8").splitlines()
    summary: Optional[str] = None
    requires: list[str] = []
    groups: dict[str, TemplateGroup] = {}

    header_done = False
    current_id: Optional[str] = None
    current_title = ""
    current_summary: Optional[str] = None
    body_lines: list[str] = []
    start_line = 0

    def flush():
        if current_id is not None:
            groups[current_id] = TemplateGroup(
                id=current_id, title=current_title, summary=current_summary,
                body="\n".join(body_lines).strip("\n"), line=start_line,
            )

    for i, raw in enumerate(lines, start=1):
        heading = RE_HEADING.match(raw)
        if heading:
            flush()
            current_id = heading.group("id")
            current_title = (heading.group("title") or "").strip()
            current_summary = None
            body_lines = [raw]
            start_line = i
            header_done = True
            continue

        if not header_done:
            field_match = RE_HEADER_FIELD.match(raw.strip())
            if field_match:
                key, value = field_match.group("key").lower(), field_match.group("value").strip()
                if key == "summary":
                    summary = value
                elif key == "requires":
                    requires = [part.strip() for part in value.split(",") if part.strip()]
            continue

        if current_id is not None:
            if current_summary is None:
                field_match = RE_HEADER_FIELD.match(raw.strip())
                if field_match and field_match.group("key").lower() == "summary":
                    current_summary = field_match.group("value").strip()
                    body_lines.append(raw)
                    continue
            body_lines.append(raw)

    flush()
    return TemplateSet(path=path, origin=origin, summary=summary, requires=requires, groups=groups)


def resolve_template_set(project_set: ProjectSet) -> Optional[TemplateSet]:
    resolved = actlib.resolve(strip_template_prefix(project_set.path))
    if resolved is None:
        return None
    path, origin = resolved
    return parse_template_set(path, origin)


# ---------------------------------------------------------------------------
# Effective status of a group — the four symbols
# ---------------------------------------------------------------------------

def classify(group_id: str, project_group: Optional[ProjectGroup],
             override_by_id: dict[str, Override]) -> str:
    """Return one of "=", "~", "-" for a template group given the project's checkbox/replaces
    state. A group the project file never mentions counts as switched on ("=")."""
    if group_id in override_by_id:
        return "~"
    if project_group is None or project_group.enabled:
        return "="
    return "-"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_effective(project: ProjectFile, area: Area) -> str:
    override_by_id = {o.id: o for o in project.overrides}
    out: list[str] = []
    for pset in project.sets:
        if area.name == "coding" and not pset.enabled:
            continue
        template = resolve_template_set(pset)
        if template is None:
            continue
        for gid, tgroup in template.groups.items():
            symbol = classify(gid, pset.groups.get(gid), override_by_id)
            if symbol == "-":
                continue
            if symbol == "~":
                out.append(f"## `{gid}` (overridden)\n\n{override_by_id[gid].text}")
            else:
                out.append(tgroup.body)
    for own in project.own_rules:
        heading = f"## `{own.id}`" if own.id else "## Own rule"
        out.append(f"{heading}\n\n{own.text}")
    return "\n\n".join(out) + ("\n" if out else "")


def cmd_list(project: ProjectFile, area: Area) -> str:
    override_by_id = {o.id: o for o in project.overrides}
    lines: list[str] = []
    for pset in project.sets:
        template = resolve_template_set(pset)
        set_label = strip_template_prefix(pset.path).rsplit("/", 1)[-1].removesuffix(".md")
        if area.name == "coding" and not pset.enabled:
            summary = f" — {template.summary}" if template and template.summary else ""
            lines.append(f"[-] {set_label}{summary}")
            continue
        summary = f" — {template.summary}" if template and template.summary else ""
        lines.append(f"[=] {set_label}{summary}")
        if template is None:
            lines.append(f"    (use: target not found — {pset.path})")
            continue
        for gid, tgroup in template.groups.items():
            symbol = classify(gid, pset.groups.get(gid), override_by_id)
            gsummary = f" — {tgroup.summary}" if symbol == "=" and tgroup.summary else ""
            if symbol == "-":
                reason = pset.groups.get(gid)
                gsummary = f" — {reason.reason}" if reason and reason.reason else ""
            if symbol == "~":
                gsummary = f" — {override_by_id[gid].text}"
            lines.append(f"    [{symbol}] {gid}{gsummary}")
    for own in project.own_rules:
        label = own.id or (own.text[:40] + ("…" if len(own.text) > 40 else ""))
        lines.append(f"[+] {label}")
    return "\n".join(lines) + ("\n" if lines else "")


def cmd_id(project: ProjectFile, area: Area, target: str, root: Path) -> Optional[str]:
    override_by_id = {o.id: o for o in project.overrides}
    project_rel = project.path.relative_to(root).as_posix()

    if target in override_by_id:
        override = override_by_id[target]
        out = f"[~] `{target}` — overridden ({project_rel}:{override.line})\n\n{override.text}"
        for pset in project.sets:
            template = resolve_template_set(pset)
            if template is None or target not in template.groups:
                continue
            tgroup = template.groups[target]
            rel = template.path.relative_to(root).as_posix()
            out += f"\n\nReplaced template text ({rel}:{tgroup.line}):\n\n{tgroup.body}"
            break
        return out

    for pset in project.sets:
        template = resolve_template_set(pset)
        if template is None or target not in template.groups:
            continue
        tgroup = template.groups[target]
        symbol = classify(target, pset.groups.get(target), override_by_id)
        rel = template.path.relative_to(root).as_posix()
        return f"[{symbol}] `{target}` — source: {rel}:{tgroup.line}\n\n{tgroup.body}"

    for own in project.own_rules:
        if own.id == target:
            return f"[+] `{target}` — source: {project_rel}:{own.line}\n\n{own.text}"

    return None


def cmd_validate(project: ProjectFile, area: Area, root: Path) -> list[str]:
    findings: list[str] = []
    rel = project.path.relative_to(root).as_posix()
    for line, message in project.findings:
        findings.append(f"{rel}:{line}: {message}")

    override_by_id = {o.id: o for o in project.overrides}
    known_ids: set[str] = set()

    for pset in project.sets:
        if area.name == "coding" and not pset.enabled:
            continue
        template = resolve_template_set(pset)
        if template is None:
            findings.append(f"{rel}:{pset.line}: use: target not found: {pset.path}")
            continue
        known_ids.update(template.groups.keys())

        for gid, tgroup in template.groups.items():
            if gid not in pset.groups:
                findings.append(
                    f"{rel}:{pset.line}: group `{gid}` of {pset.path} is missing here "
                    "(counts as switched on)"
                )
        for gid in pset.groups:
            if gid not in template.groups:
                findings.append(
                    f"{rel}:{pset.groups[gid].line}: `{gid}` is not a group of {pset.path}"
                )

    for override in project.overrides:
        if override.id not in known_ids:
            findings.append(
                f"{rel}:{override.line}: `{override.id}` is not part of any included rule set"
            )

    return findings


# ---------------------------------------------------------------------------
# Coding sets as imports (T64) — a checked set is an "@" import, so Claude Code loads it; an
# unchecked one stays a bare path, which Claude Code never follows
# ---------------------------------------------------------------------------

def coding_set_line(line: str) -> str:
    """One "- [x] use: <path>" line of docs/project/coding_rules.md in its canonical form: the
    path as an import when the box is checked, bare when not. Anything after the path, the
    indentation and the checkbox itself are kept; a line that is no set line comes back as is."""
    checkbox = RE_CHECKBOX.match(line)
    if not checkbox or checkbox.group("indent"):
        return line
    use = RE_USE.match(checkbox.group("rest"))
    if not use:
        return line
    set_path = normalize_set_path(use.group("path"))
    wanted = import_path(set_path, AREAS["coding"].project_file) \
        if checkbox.group("mark") in ("x", "X") else set_path
    start, end = checkbox.start("rest") + use.start("path"), checkbox.start("rest") + use.end("path")
    return line[:start] + wanted + line[end:]


def sync_coding_imports(root: Path, write: bool = True) -> int:
    """Bring every set line of docs/project/coding_rules.md into its canonical form
    (coding_set_line), so the checkboxes decide what Claude Code loads. Returns how many lines
    differ (and were rewritten, with write=True); 0 if the file is missing."""
    path = root / AREAS["coding"].project_file
    if not path.is_file():
        return 0
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    fixed = [coding_set_line(line) for line in lines]
    changed = sum(1 for old, new in zip(lines, fixed) if old != new)
    if changed and write:
        with open(path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(fixed) + ("\n" if text.endswith("\n") else ""))
    return changed


# ---------------------------------------------------------------------------
# Import check (T64) — follows "@" imports from CLAUDE.md the way Claude Code does
# (code.claude.com/docs/en/memory.md, "Import additional files"): relative to the file that holds
# the import, absolute and "~/" paths as they are, at most four hops below the start file, never
# inside a code span, a fenced or indented code block, or an HTML comment (Claude Code strips
# those), a "#section" suffix ignored. A target that does not exist is skipped by Claude Code
# without a word — this is where it shows up, as long as it is shaped like a file path (so
# "@someone" or a package name in prose is not counted).
# ---------------------------------------------------------------------------

MAX_IMPORT_HOPS = 4
RE_IMPORT = re.compile(r"(?:^|(?<=[\s*_(\[]))@(?P<target>[^\s*_)\]]+(?:_[^\s*_)\]]+)*)")
RE_FENCE = re.compile(r"^\s{0,3}(?P<fence>`{3,}|~{3,})")
RE_CODE_SPAN = re.compile(r"(?P<ticks>`+).*?(?<!`)(?P=ticks)(?!`)")
RE_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
RE_INDENTED_CODE = re.compile(r"^(?: {4}|\t)")


def _strip_html_comments(text: str) -> str:
    """Blank out every HTML comment, keeping its line breaks so line numbers stay right."""
    return RE_HTML_COMMENT.sub(lambda m: "\n" * m.group(0).count("\n"), text)


def _import_targets(text: str) -> list[tuple[int, str]]:
    """(line number, target) for every "@target" outside code spans, fenced and indented code
    blocks and HTML comments; a trailing "#section" and sentence punctuation are dropped."""
    found: list[tuple[int, str]] = []
    fence: Optional[str] = None
    previous_blank, in_indented = True, False
    for number, line in enumerate(_strip_html_comments(text).splitlines(), start=1):
        fence_match = RE_FENCE.match(line)
        if fence is not None:
            if fence_match and fence_match.group("fence")[0] == fence[0] \
                    and len(fence_match.group("fence")) >= len(fence):
                fence = None
            continue
        if fence_match:
            fence = fence_match.group("fence")
            continue
        if line.strip() and RE_INDENTED_CODE.match(line) and (previous_blank or in_indented):
            in_indented = True  # an indented code block cannot interrupt a paragraph or a list
            continue
        in_indented = in_indented and not line.strip()
        previous_blank = not line.strip()
        for match in RE_IMPORT.finditer(RE_CODE_SPAN.sub(" ", line)):
            target = match.group("target").split("#", 1)[0].rstrip(".,;:!?")
            if target:
                found.append((number, target))
    return found


def _looks_like_path(target: str) -> bool:
    """Only a target shaped like a file path is reported when missing — "@someone" or a package
    name such as "@nuxt/eslint" in prose is not."""
    return target.startswith(("./", "../", "/", "~/")) or target.endswith(".md")


def _show(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def resolve_imports(root: Path, start: str = "CLAUDE.md") -> tuple[list[str], list[str]]:
    """(reached, unresolved) from `start` (root-relative): every file Claude Code loads, in load
    order, root-relative; one "<file>:<line>: @<target> — <reason>" per import it cannot follow.
    A missing start file is itself unresolved."""
    start_path = (root / start).resolve()
    reached: list[str] = []
    unresolved: list[str] = []
    seen: set[Path] = set()

    def visit(path: Path, hops: int) -> None:
        seen.add(path)
        reached.append(_show(path, root))
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            unresolved.append(f"{_show(path, root)}:0: unreadable — {exc.__class__.__name__}")
            return
        for number, target in _import_targets(text):
            where = f"{_show(path, root)}:{number}: @{target}"
            expanded = Path(target).expanduser()
            candidate = (expanded if expanded.is_absolute() else path.parent / expanded).resolve()
            if not candidate.is_file():
                if _looks_like_path(target):
                    unresolved.append(f"{where} — not found (looked for {_show(candidate, root)})")
                continue
            if candidate in seen:
                continue
            if hops >= MAX_IMPORT_HOPS:
                unresolved.append(f"{where} — deeper than {MAX_IMPORT_HOPS} hops, not loaded")
                continue
            visit(candidate, hops + 1)

    if not start_path.is_file():
        return [], [f"{start}:0: start file not found"]
    visit(start_path, 0)
    return reached, unresolved


def other_instruction_files(root: Path) -> list[str]:
    """Files Claude Code loads besides CLAUDE.md and its imports, where they exist:
    CLAUDE.local.md and .claude/rules/**/*.md. Named by --imports, not followed."""
    found = ["CLAUDE.local.md"] if (root / "CLAUDE.local.md").is_file() else []
    rules_dir = root / ".claude" / "rules"
    if rules_dir.is_dir():
        found += sorted(p.relative_to(root).as_posix() for p in rules_dir.rglob("*.md"))
    return found


def cmd_imports(root: Path, start: str) -> tuple[str, bool]:
    reached, unresolved = resolve_imports(root, start)
    lines = [f"reached {len(reached)}:"] + [f"  {path}" for path in reached]
    lines.append(f"unresolved {len(unresolved)}:")
    lines += [f"  {entry}" for entry in unresolved]
    others = other_instruction_files(root)
    if others:
        lines.append(f"also loaded by Claude Code, not followed here ({len(others)}):")
        lines += [f"  {path}" for path in others]
    return "\n".join(lines) + "\n", not unresolved


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rules.py",
        description="Read the effective coding/core rules after the project's checkboxes and "
                     "replacements are applied.",
    )
    parser.add_argument("--area", choices=sorted(AREAS), default="coding",
                         help="which rule area to read (default: coding)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true", help="human overview, one line per set/group")
    mode.add_argument("--validate", action="store_true", help="schema + cross-checks, exit 1 on findings")
    mode.add_argument("--imports", action="store_true",
                      help="files Claude Code loads through @-imports, exit 1 on any it cannot follow")
    parser.add_argument("--from", dest="start", metavar="FILE", default="CLAUDE.md",
                        help="start file for --imports, root-relative (default: CLAUDE.md)")
    parser.add_argument("id", nargs="?", default=None, help="print exactly this group/rule in full")
    return parser


def main(argv: list[str]) -> int:
    # Rule text carries non-ASCII marks (em dash "—") throughout; on Windows, stdout/stderr
    # default to the console's legacy codepage instead of UTF-8, which would otherwise corrupt
    # them. Reconfigure where possible (Python >= 3.7); harmless no-op elsewhere.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    if args.id is not None and (args.list or args.validate or args.imports):
        print("rules.py: an id argument cannot be combined with --list, --validate or --imports", file=sys.stderr)
        return 2

    area = AREAS[args.area]

    try:
        root = actlib.repo_root()
    except RuntimeError as exc:
        print(f"rules.py: {exc}", file=sys.stderr)
        return 1

    if args.imports:
        report, clean = cmd_imports(root, args.start)
        sys.stdout.write(report)
        return 0 if clean else 1

    project_path = root / area.project_file
    if not project_path.is_file():
        print(f"rules.py: {area.project_file} not found — nothing to read", file=sys.stderr)
        return 1

    try:
        project = parse_project_file(project_path, area)
    except OSError as exc:
        print(f"rules.py: could not read {area.project_file}: {exc}", file=sys.stderr)
        return 1

    if args.validate:
        findings = cmd_validate(project, area, root)
        # Hints (text under "Own rules" that is not read as a rule) follow the findings, marked
        # "note:" — they never change the exit code (Q113).
        rel = project.path.relative_to(root).as_posix()
        notes = [f"{rel}:{line}: note: {message}" for line, message in project.hints]
        if findings or notes:
            print("\n".join(findings + notes))
        return 1 if findings else 0

    if args.list:
        sys.stdout.write(cmd_list(project, area))
        return 0

    if args.id is not None:
        result = cmd_id(project, area, args.id, root)
        if result is None:
            print(f"rules.py: unknown id '{args.id}' for --area {area.name}", file=sys.stderr)
            return 1
        print(result)
        return 0

    sys.stdout.write(cmd_effective(project, area))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
