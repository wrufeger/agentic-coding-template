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
#
# Output format:
#   Default and <id>: Markdown, meant to be pasted into a model's context.
#   --list: "[symbol] id — summary" per set, one indented "[symbol] id[ — reason]" per group below
#     it (symbols: "=" unchanged, "~" overridden, "-" switched off, "+" own addition).
#   --validate: one finding per line as "<path>:<line>: <message>", nothing printed and exit 0 if
#     there are no findings.
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

RE_CHECKBOX = re.compile(r"^(?P<indent>\s*)-\s*\[(?P<mark>[ xX])\]\s*(?P<rest>.*)$")
RE_CHECKBOX_LOOSE = re.compile(r"^(?P<indent>\s*)-\s*\[(?P<mark>[^\]]*)\]\s*(?P<rest>.*)$")
RE_USE = re.compile(r"^use:\s*(?P<path>\S+)\s*$")
RE_GROUP_ID = re.compile(r"^`(?P<id>[^`]+)`\s*(?:—\s*(?P<reason>.+))?$")
RE_REPLACES = re.compile(r"^-\s*replaces\s+`(?P<id>[^`]+)`:\s*(?P<text>.*)$")
RE_REPLACES_LOOSE = re.compile(r"^-\s*replaces\b.*$")
RE_CORE_SET = re.compile(r"^@?`?(?P<path>\.act/\S+?\.md)`?$")
RE_OWN = re.compile(r"^-\s+(?:`(?P<id>[^`]+)`:\s*)?(?P<text>.*)$")
RE_HEADING = re.compile(r"^##\s+`(?P<id>[^`]+)`\s*(?:—\s*(?P<title>.+))?\s*$")
RE_HEADER_FIELD = re.compile(r"^(?P<key>summary|requires|retired):\s*(?P<value>.*)$", re.IGNORECASE)


def strip_template_prefix(path: str) -> str:
    """Turn a set path as written in the project file (e.g. ".act/coding/nuxt.md") into the
    template-relative path actlib.resolve() expects (e.g. "coding/nuxt.md")."""
    if path.startswith(".act/"):
        return path[len(".act/"):]
    return path


# ---------------------------------------------------------------------------
# Parsing the project file (docs/project/coding_rules.md or docs/ai/rules.md)
# ---------------------------------------------------------------------------

def parse_project_file(path: Path, area: Area) -> ProjectFile:
    lines = path.read_text(encoding="utf-8").splitlines()
    sets: list[ProjectSet] = []
    overrides: list[Override] = []
    own_rules: list[OwnRule] = []
    findings: list[tuple[int, str]] = []
    current_set: Optional[ProjectSet] = None

    for i, raw in enumerate(lines, start=1):
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue

        checkbox = RE_CHECKBOX.match(line)
        if checkbox:
            indent, mark, rest = checkbox.group("indent"), checkbox.group("mark"), checkbox.group("rest")
            enabled = mark in ("x", "X")
            if indent == "":
                if area.name != "coding":
                    findings.append((i, "a checkbox set line ('use:') is only valid for --area coding"))
                    current_set = None
                    continue
                use = RE_USE.match(rest)
                if not use:
                    findings.append((i, "expected '- [ ] use: <path>'"))
                    current_set = None
                    continue
                current_set = ProjectSet(path=use.group("path"), enabled=enabled, line=i)
                sets.append(current_set)
            else:
                group = RE_GROUP_ID.match(rest)
                if not group:
                    findings.append((i, "expected '  - [ ] `ID`' with an optional ' — reason'"))
                    continue
                if current_set is None:
                    findings.append((i, "group checkbox with no preceding set line"))
                    continue
                current_set.groups[group.group("id")] = ProjectGroup(
                    enabled=enabled, reason=group.group("reason"), line=i,
                )
            continue

        loose = RE_CHECKBOX_LOOSE.match(line)
        if loose:
            findings.append((i, "invalid checkbox mark, expected '[ ]' or '[x]'"))
            continue

        if line[:1] not in (" ", "\t"):
            if area.name == "core":
                core_set = RE_CORE_SET.match(stripped)
                if core_set:
                    current_set = ProjectSet(path=core_set.group("path"), enabled=True, line=i)
                    sets.append(current_set)
                    continue
                if stripped.startswith(".act/") or stripped.startswith("@.act/"):
                    findings.append((i, "expected '@<path>.md' or '`<path>.md`'"))
                    continue

            replaces = RE_REPLACES.match(stripped)
            if replaces:
                overrides.append(Override(id=replaces.group("id"), text=replaces.group("text"), line=i))
                continue
            if RE_REPLACES_LOOSE.match(stripped):
                findings.append((i, "expected '- replaces `ID`: <text>'"))
                continue

            if stripped.startswith("- "):
                own = RE_OWN.match(stripped)
                own_rules.append(OwnRule(id=own.group("id") if own else None,
                                          text=(own.group("text") if own else stripped[2:]).strip(),
                                          line=i))
                continue
            # heading or prose in the project's own language — not read by the mechanism.

    return ProjectFile(path=path, sets=sets, overrides=overrides, own_rules=own_rules, findings=findings)


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

    if args.id is not None and (args.list or args.validate):
        print("rules.py: an id argument cannot be combined with --list or --validate", file=sys.stderr)
        return 2

    area = AREAS[args.area]

    try:
        root = actlib.repo_root()
    except RuntimeError as exc:
        print(f"rules.py: {exc}", file=sys.stderr)
        return 1

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
        if findings:
            print("\n".join(findings))
            return 1
        return 0

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
