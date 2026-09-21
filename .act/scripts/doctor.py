#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Mechanical half of the "Abgleich-Skill" (docs/project/concepts/ai-dev-app/
#          05-update-and-overrides.md § "Abgleich-Skill" in the template-pflege repo) — the cheap
#          checks that run after every update and on demand, without a model in the loop. Finds:
#            1. everything rules.py --validate already reports, for both areas (core, coding);
#            2. dead identifiers: an override/off of an R-/CR- ID that no longer exists in the
#               template, or that exists only in a `retired:` header field;
#            3. a switched-off coding set whose `use:` target is gone (rules.py --validate skips
#               disabled sets, so this is the one case it cannot see);
#            4. an override/off whose template text has changed since the project last looked at
#               it (tracked as a hash per ID in .act-lock.json § "overrides");
#            5. (info, not a finding) the list of currently effective overrides/off-switches;
#            6. broken references: `act:ref` comments under docs/, and — where they exist —
#               bridge files under .claude/agents|skills/ pointing at a missing .act/ file;
#            7. the same script/agent/skill name present at more than one location, unless it is
#               the intended docs/ai/local/ overlay of the matching .act/ file;
#            8. hook entries .act/bridges/settings.hooks.json defines that .claude/settings.json
#               is missing (only checked when "claude-code" is one of the project's configured
#               tools, per docs/ai/config.md).
#          The content-based half of the Abgleich-Skill (contradictions, near-duplicate rules,
#          the template-vs-project cross-check after an update) is a separate, model-driven step
#          and out of scope here. Stdlib only.
#
# Usage:
#   python .act/scripts/doctor.py                  # run every check, human-readable output
#   python .act/scripts/doctor.py --json            # same, as one JSON object on stdout
#   python .act/scripts/doctor.py --inbox            # also write docs/ai/inbox/<date>-doctor.md
#                                                     # if (and only if) there are findings
#   python .act/scripts/doctor.py --accept ID [...]  # record ID's current template text as the
#                                                     # accepted baseline (clears finding 4 for it)
#   python .act/scripts/doctor.py --accept-all       # same, for every stale override/off found
#
# Output format:
#   Default: findings grouped by kind, one "<path>:<line>: <message>" (or "<path>: <message>" if
#     there is no single line) per finding, followed by the effective-overrides list (info, not
#     counted as a finding) and a closing count line.
#   --json: {"findings": [...], "effective_overrides": [...], "counts": {...}}, each finding as
#     {"path", "line", "kind", "message"}.
#   Exit 0 with no findings, 1 with at least one finding, 2 on a fatal error (no .act/ found, a
#   required project file missing entirely) — never a traceback.

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import actlib
import rules


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    path: str
    line: Optional[int]
    kind: str
    message: str

    def render(self) -> str:
        if self.line is not None:
            return f"{self.path}:{self.line}: {self.message}"
        return f"{self.path}: {self.message}"

    def as_dict(self) -> dict:
        return {"path": self.path, "line": self.line, "kind": self.kind, "message": self.message}


@dataclass
class EffectiveOverride:
    id: str
    area: str
    kind: str  # "off" or "replaces"
    path: str
    line: int


KIND_LABELS: dict[str, str] = {
    "validate": "Schema and set/group references (rules.py --validate)",
    "dead-id": "Dead identifiers (overridden/off, but gone from the template)",
    "use-missing": "Switched-off rule set with a missing target",
    "override-stale": "Overridden rule whose template text has changed",
    "ref-missing": "Broken references",
    "duplicate-unit": "Duplicate scripts/agents/skills",
    "hook": "Missing hook entries",
}
KIND_ORDER = list(KIND_LABELS)


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


# ---------------------------------------------------------------------------
# 1. rules.py --validate, both areas — also hands back the parsed project files, reused below
# ---------------------------------------------------------------------------

def _parse_area(root: Path, area: rules.Area) -> Optional[rules.ProjectFile]:
    path = root / area.project_file
    if not path.is_file():
        return None
    try:
        return rules.parse_project_file(path, area)
    except OSError:
        return None


def check_validate(root: Path, project: rules.ProjectFile, area: rules.Area) -> list[Finding]:
    findings = rules.cmd_validate(project, area, root)
    out = []
    for line in findings:
        # rules.py already renders "<path>:<line>: <message>" — split it back apart so it fits
        # the same Finding shape as every other check instead of carrying a second string format.
        head, _, message = line.partition(": ")
        file_part, _, line_no = head.rpartition(":")
        try:
            line_int: Optional[int] = int(line_no)
        except ValueError:
            file_part, line_int = head, None
        out.append(Finding(path=file_part, line=line_int, kind="validate", message=message))
    return out


# ---------------------------------------------------------------------------
# 2 + 4 + 5. Dead identifiers, stale overrides, effective-overrides list
# ---------------------------------------------------------------------------

@dataclass
class TemplateCorpus:
    ids: dict[str, tuple[Path, str]]        # id -> (source file, origin)
    retired: dict[str, list[Path]]          # id -> files whose header lists it as retired
    groups: dict[str, rules.TemplateGroup]  # id -> the group itself, for hashing its body


def _read_retired_ids(path: Path) -> list[str]:
    """The comma-separated `retired:` header field of a template set file — IDs the file used to
    define but no longer does. Mirrors the header section rules.parse_template_set() scans:
    everything before the first '## `ID`' heading."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for raw in lines:
        if rules.RE_HEADING.match(raw):
            break
        match = rules.RE_HEADER_FIELD.match(raw.strip())
        if match and match.group("key").lower() == "retired":
            return [part.strip() for part in match.group("value").split(",") if part.strip()]
    return []


def _template_files(root: Path, area_name: str) -> list[tuple[Path, str]]:
    """Every rule-set file the template currently ships for `area_name` ("core" ->
    .act/rules/**/*.md, "coding" -> .act/coding/*.md), local override preferred over the template
    default — the same precedence actlib.resolve() uses everywhere else."""
    act_dir = root / ".act"
    template_glob = sorted((act_dir / "rules").rglob("*.md")) if area_name == "core" \
        else sorted((act_dir / "coding").glob("*.md"))
    out: list[tuple[Path, str]] = []
    seen_rel: set[str] = set()
    for path in template_glob:
        rel = path.relative_to(act_dir).as_posix()
        if rel in seen_rel:
            continue
        seen_rel.add(rel)
        resolved = actlib.resolve(rel)
        if resolved:
            out.append(resolved)
    return out


def _build_corpus(root: Path, area_name: str) -> TemplateCorpus:
    ids: dict[str, tuple[Path, str]] = {}
    retired: dict[str, list[Path]] = {}
    groups: dict[str, rules.TemplateGroup] = {}
    for path, origin in _template_files(root, area_name):
        tset = rules.parse_template_set(path, origin)
        for gid, group in tset.groups.items():
            ids.setdefault(gid, (path, origin))
            groups.setdefault(gid, group)
        for rid in _read_retired_ids(path):
            retired.setdefault(rid, []).append(path)
    return TemplateCorpus(ids=ids, retired=retired, groups=groups)


def _off_and_override_entries(project: rules.ProjectFile) -> list[tuple[str, int, str]]:
    """(id, line, kind) for every group the project has switched off — its own checkbox
    unchecked, or the whole set containing it switched off — and every `replaces` override. This
    is the set of IDs findings 2/4 and info 5 care about; `replaces` wins the label if a project
    both unchecks and replaces the same ID (replacing implies switching off)."""
    seen: dict[str, tuple[int, str]] = {}
    for pset in project.sets:
        for gid, group in pset.groups.items():
            if not pset.enabled or not group.enabled:
                seen.setdefault(gid, (group.line, "off"))
    for override in project.overrides:
        seen[override.id] = (override.line, "replaces")
    return [(gid, line, kind) for gid, (line, kind) in sorted(seen.items())]


def check_dead_and_stale(
    root: Path, project: rules.ProjectFile, area: rules.Area, area_name: str,
    accept_ids: set[str], accept_all: bool,
) -> tuple[list[Finding], list[EffectiveOverride], dict[str, str]]:
    """Returns (findings, effective overrides still valid, candidate hashes for the lock file) —
    the hashes are collected here but written once for both areas together by the caller, so a
    single .act-lock.json write covers the whole run."""
    corpus = _build_corpus(root, area_name)
    project_rel = _rel(project.path, root)
    findings: list[Finding] = []
    effective: list[EffectiveOverride] = []
    candidates: dict[str, str] = {}

    for gid, line, kind in _off_and_override_entries(project):
        if gid in corpus.ids:
            effective.append(EffectiveOverride(id=gid, area=area_name, kind=kind, path=project_rel, line=line))
            body = corpus.groups[gid].body
            candidates[gid] = hashlib.sha256(body.encode("utf-8")).hexdigest()
        elif gid in corpus.retired:
            sources = ", ".join(_rel(p, root) for p in corpus.retired[gid])
            findings.append(Finding(
                path=project_rel, line=line, kind="dead-id",
                message=f"`{gid}` is retired in the template (see {sources}) — this {kind} has no effect",
            ))
        else:
            findings.append(Finding(
                path=project_rel, line=line, kind="dead-id",
                message=f"`{gid}` no longer exists in the template — this {kind} has no effect",
            ))

    return findings, effective, candidates


def apply_override_hashes(
    root: Path, candidates: dict[str, tuple[str, str, int]], accept_ids: set[str], accept_all: bool,
) -> list[Finding]:
    """`candidates` maps id -> (new_hash, project_path, project_line). Compares against the
    baseline recorded in .act-lock.json § "overrides"; a first sighting is recorded silently, a
    changed hash becomes a finding unless the ID is accepted this run, in which case the new hash
    replaces the baseline instead. One lock write for the whole run."""
    lock = actlib.read_lock()
    recorded: dict[str, str] = dict(lock.get("overrides") or {})
    # Only IDs still overridden keep their baseline: a dropped and later re-added override
    # starts from a fresh sighting instead of being reported as stale.
    to_write = {gid: h for gid, h in recorded.items() if gid in candidates}
    findings: list[Finding] = []

    for gid, (new_hash, project_path, project_line) in sorted(candidates.items()):
        old_hash = recorded.get(gid)
        if old_hash is None:
            to_write[gid] = new_hash
            continue
        if old_hash == new_hash:
            continue
        if accept_all or gid in accept_ids:
            to_write[gid] = new_hash
            continue
        findings.append(Finding(
            path=project_path, line=project_line, kind="override-stale",
            message=f"`{gid}` — template text changed since this override/off was recorded "
                    f"(run `doctor.py --accept {gid}` once reviewed)",
        ))

    if to_write != recorded:
        actlib.write_lock({"overrides": to_write})
    return findings


# ---------------------------------------------------------------------------
# 3. Switched-off coding set with a missing target (rules.py --validate skips disabled sets)
# ---------------------------------------------------------------------------

def check_disabled_use_missing(root: Path, project: rules.ProjectFile) -> list[Finding]:
    project_rel = _rel(project.path, root)
    findings = []
    for pset in project.sets:
        if pset.enabled:
            continue  # the enabled case is already covered by rules.py --validate
        if rules.resolve_template_set(pset) is None:
            findings.append(Finding(
                path=project_rel, line=pset.line, kind="use-missing",
                message=f"switched-off use: target not found: {pset.path}",
            ))
    return findings


# ---------------------------------------------------------------------------
# 6. Broken references — act:ref comments under docs/, bridge files under .claude/
# ---------------------------------------------------------------------------

RE_ACT_REF = re.compile(r"<!--\s*act:ref\s+(?P<target>\S+)\s*-->")
RE_ACT_PATH = re.compile(r"\.act/[\w.\-/]+\.md")


def _target_exists(root: Path, target: str) -> bool:
    base = target.split("#", 1)[0]
    if base.startswith(".act/"):
        return actlib.resolve(rules.strip_template_prefix(base)) is not None
    return (root / base).is_file()


def check_act_refs(root: Path) -> list[Finding]:
    docs_dir = root / "docs"
    if not docs_dir.is_dir():
        return []
    findings = []
    for path in sorted(docs_dir.rglob("*.md")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, start=1):
            for match in RE_ACT_REF.finditer(line):
                target = match.group("target")
                if not _target_exists(root, target):
                    findings.append(Finding(
                        path=_rel(path, root), line=i, kind="ref-missing",
                        message=f"act:ref target not found: {target}",
                    ))
    return findings


def check_bridge_files(root: Path) -> list[Finding]:
    """Role/skill bridges under .claude/agents/ and .claude/skills/, once they exist, mention the
    .act/ file they wrap in prose (see docs/project/concepts/ai-dev-app/02-directory-plan.md in
    the template-pflege repo). Neither directory exists yet at this build stage — the check is a
    no-op until they do, rather than assuming a fixed layout."""
    findings = []
    for sub in ("agents", "skills"):
        bridge_dir = root / ".claude" / sub
        if not bridge_dir.is_dir():
            continue
        for path in sorted(bridge_dir.glob("*.md")):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines, start=1):
                for match in RE_ACT_PATH.finditer(line):
                    target = match.group(0)
                    if actlib.resolve(rules.strip_template_prefix(target)) is None:
                        findings.append(Finding(
                            path=_rel(path, root), line=i, kind="ref-missing",
                            message=f"bridge target not found: {target}",
                        ))
    return findings


# ---------------------------------------------------------------------------
# 7. Duplicate units — same script/agent/skill name at more than one location
# ---------------------------------------------------------------------------

# (label, sub-directory) pairs this template treats as holding "units": .act/'s own copies, the
# project's docs/ai/local/ overrides/additions (mirrored under the same sub-directory names), and
# the Claude Code bridges once they exist. Any base directory that does not exist is skipped.
_UNIT_BASES = (("act", ".act"), ("local", "docs/ai/local"), ("claude", ".claude"))
_UNIT_SUBDIRS = ("scripts", "agents", "skills")


def _scan_units(root: Path) -> list[tuple[str, str, Path]]:
    """(label, sub-directory, path) for every file under <base>/<subdir>/ for each (label, base)
    in _UNIT_BASES and each subdir in _UNIT_SUBDIRS that exists. label+subdir is the "namespace";
    the path relative to that namespace is what the docs/ai/local/ overlay exception compares."""
    out: list[tuple[str, str, Path]] = []
    for label, base_rel in _UNIT_BASES:
        base = root / base_rel
        for sub in _UNIT_SUBDIRS:
            sub_dir = base / sub
            if not sub_dir.is_dir():
                continue
            for path in sorted(sub_dir.rglob("*")):
                if not path.is_file():
                    continue
                if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
                    continue
                out.append((label, sub, path))
    return out


def check_duplicate_units(root: Path) -> list[Finding]:
    units = _scan_units(root)
    by_name: dict[str, list[tuple[str, str, Path]]] = defaultdict(list)
    for label, sub, path in units:
        by_name[path.name].append((label, sub, path))

    findings = []
    for name, entries in sorted(by_name.items()):
        if len(entries) < 2:
            continue
        if len(entries) == 2:
            (label_a, sub_a, path_a), (label_b, sub_b, path_b) = entries
            rel_a = path_a.relative_to(root / dict(_UNIT_BASES)[label_a] / sub_a).as_posix()
            rel_b = path_b.relative_to(root / dict(_UNIT_BASES)[label_b] / sub_b).as_posix()
            is_overlay = {label_a, label_b} == {"act", "local"} and sub_a == sub_b and rel_a == rel_b
            if is_overlay:
                continue  # the intended docs/ai/local/ override of a template file — info, not a finding
        locations = ", ".join(_rel(path, root) for _, _, path in entries)
        findings.append(Finding(
            path=locations, line=None, kind="duplicate-unit",
            message=f"'{name}' found at more than one location",
        ))
    return findings


# ---------------------------------------------------------------------------
# 8. Missing hook entries (only when "claude-code" is a configured tool)
# ---------------------------------------------------------------------------

def _configured_tools(config: dict[str, str]) -> list[str]:
    raw = config.get("`tools`") or config.get("tools") or ""
    return [part.strip().strip("`").lower() for part in raw.split(",") if part.strip()]


def check_hooks(root: Path) -> list[Finding]:
    if "claude-code" not in _configured_tools(actlib.read_config()):
        return []
    bridge_path = root / ".act" / "bridges" / "settings.hooks.json"
    if not bridge_path.is_file():
        return []
    try:
        bridge = json.loads(bridge_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [Finding(path=_rel(bridge_path, root), line=None, kind="hook",
                         message="not valid JSON, cannot compare against .claude/settings.json")]

    settings_path = root / ".claude" / "settings.json"
    settings: dict = {}
    if settings_path.is_file():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            settings = {}
    existing_hooks = settings.get("hooks", {}) if isinstance(settings, dict) else {}

    findings = []
    for event, entries in bridge.get("hooks", {}).items():
        existing_entries = existing_hooks.get(event, [])
        if any(entry not in existing_entries for entry in entries):
            findings.append(Finding(
                path=_rel(settings_path, root), line=None, kind="hook",
                message=f"hook entry for event '{event}' missing (source: .act/bridges/settings.hooks.json)",
            ))
    return findings


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------

def write_inbox(root: Path, findings: list[Finding]) -> Optional[Path]:
    if not findings:
        return None
    dest = root / "docs" / "ai" / "inbox" / f"{date.today().isoformat()}-doctor.md"
    lines = ["for: all", "status: open", "", "# doctor findings", ""]
    for kind in KIND_ORDER:
        group = [f for f in findings if f.kind == kind]
        if not group:
            continue
        lines.append(f"## {KIND_LABELS[kind]}")
        lines.append("")
        lines.extend(f"- {f.render()}" for f in group)
        lines.append("")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def run(root: Path, accept_ids: set[str], accept_all: bool) -> tuple[list[Finding], list[EffectiveOverride]]:
    findings: list[Finding] = []
    effective: list[EffectiveOverride] = []
    hash_candidates: dict[str, tuple[str, str, int]] = {}

    for area_name, area in rules.AREAS.items():
        project = _parse_area(root, area)
        if project is None:
            continue  # nothing materialized yet for this area — not a finding, just nothing to check
        findings += check_validate(root, project, area)
        dead, area_effective, candidates = check_dead_and_stale(
            root, project, area, area_name, accept_ids, accept_all,
        )
        findings += dead
        effective += area_effective
        project_rel = _rel(project.path, root)
        line_by_id = {o.id: o.line for o in area_effective}
        for gid, new_hash in candidates.items():
            hash_candidates[gid] = (new_hash, project_rel, line_by_id[gid])
        if area_name == "coding":
            findings += check_disabled_use_missing(root, project)

    findings += apply_override_hashes(root, hash_candidates, accept_ids, accept_all)
    findings += check_act_refs(root)
    findings += check_bridge_files(root)
    findings += check_duplicate_units(root)
    findings += check_hooks(root)

    return findings, effective


def render_human(findings: list[Finding], effective: list[EffectiveOverride]) -> str:
    lines: list[str] = []
    for kind in KIND_ORDER:
        group = [f for f in findings if f.kind == kind]
        if not group:
            continue
        lines.append(f"== {KIND_LABELS[kind]} ==")
        lines.extend(f.render() for f in group)
        lines.append("")

    if effective:
        lines.append("-- effective overrides (info, not a finding) --")
        for item in sorted(effective, key=lambda e: (e.area, e.id)):
            lines.append(f"[{item.area}] {item.id} — {item.kind} ({item.path}:{item.line})")
        lines.append("")

    lines.append(f"{len(findings)} finding(s), {len(effective)} effective override(s).")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doctor.py",
        description="Mechanical project/template abgleich — see the header comment for the full list of checks.",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--inbox", action="store_true", help="also write docs/ai/inbox/<date>-doctor.md if there are findings")
    parser.add_argument("--accept", action="append", default=[], metavar="ID", help="accept the current template text for ID (repeatable)")
    parser.add_argument("--accept-all", action="store_true", help="accept the current template text for every stale override/off")
    return parser


def main(argv: list[str]) -> int:
    # Finding text can carry an em dash; on Windows, stdout/stderr otherwise default to the
    # console's legacy code page instead of UTF-8, which would corrupt it. Same fix as
    # .act/scripts/rules.py.
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

    try:
        root = actlib.repo_root()
    except RuntimeError as exc:
        print(f"doctor.py: {exc}", file=sys.stderr)
        return 2

    accept_ids = set(args.accept)
    findings, effective = run(root, accept_ids, args.accept_all)

    if args.inbox:
        written = write_inbox(root, findings)
        if written is not None:
            print(f"doctor.py: wrote {_rel(written, root)}")

    if args.json:
        payload = {
            "findings": [f.as_dict() for f in findings],
            "effective_overrides": [
                {"id": e.id, "area": e.area, "kind": e.kind, "path": e.path, "line": e.line}
                for e in effective
            ],
            "counts": {"findings": len(findings), "effective_overrides": len(effective)},
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        sys.stdout.write(render_human(findings, effective))

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
