#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Mechanical half of the reconcile skill `act-doctor` — the cheap
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
#            7. a script/agent/skill name under docs/ai/local/ or .claude/ that is not explained
#               by a generated skill copy, a role bridge, or the docs/ai/local/ overlay of the
#               matching .act/ file;
#            8. hook entries .act/bridges/settings.hooks.json defines that .claude/settings.json
#               is missing, or a template-generated entry .claude/settings.json still carries that
#               the bridge no longer defines (outdated or a duplicate left over from before T46's
#               merge fix) — only checked when "claude-code" is one of the project's configured
#               tools, per docs/ai/config.md.
#            9. .act/MANIFEST.json drift against the .act/ tree on disk, wherever a MANIFEST.json
#               exists to compare against — a project that hand-edited .act/ since its last
#               update, or the template's own checkout if its maintainer forgot `manifest.py
#               --write` before committing an .act/ change (Q73a).
#           10. a short id (T<n>/B<n>/Q<n>) assigned to more than one entry file under
#               docs/ai/work/ or docs/ai/questions/ — the merge-safety net Q62a/Q65c call for,
#               reusing entries.py's own scan (entries.find_duplicate_ids()) rather than repeating
#               it here; plus, from the same scan, an entry file that isn't valid UTF-8 at all
#               (entries.find_unreadable_entries()) — this template never lets a decode failure
#               abort a run, here or in entries.py itself.
#           11. an outdated config.md key: the single `language` still in place of
#               `language-chat`/`language-docs` (T61) — still read, one note to replace it.
#           12. an entry whose `status:` header value is none the mechanism knows (open, answered,
#               done) — e.g. translated along with the scaffold; board.py and the session start
#               count only those values (R-work-language).
#           13. a hook command or a `Bash(...)` permission entry in .claude/settings.json (and,
#               read-only, .claude/settings.local.json) that names a project script path which no
#               longer exists — left over after an adoption replaced the old template's scripts
#               (T54, D1). Never touches either file, only reports.
#           14. (T64) an @-import Claude Code cannot follow from CLAUDE.md (relative to the
#               importing file, at most four hops, rules.resolve_imports), every rule file
#               under .act/rules/shared|orchestrator/ docs/ai/rules.md names but does not import,
#               and every checked coding set that does not load.
#          Finding 6's `act:ref` scan skips fenced code blocks and inline code spans (D2) — those
#          markers are illustration, not a live reference, and used to be reported as broken.
#          The content-based half of the reconcile skill (contradictions, near-duplicate rules,
#          the template-vs-project cross-check after an update) is a separate, model-driven step
#          and out of scope here. Stdlib only.
#
# Usage:
#   python .act/scripts/doctor.py                  # run every check, human-readable output
#   python .act/scripts/doctor.py --target <dir>    # same, against <dir> instead of this project
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
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import actlib
import entries
import init
import manifest as manifest_mod
import rules
import script_docs


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
    "import": "Rule files Claude Code does not load (rules.py --imports)",
    "dead-id": "Dead identifiers (overridden/off, but gone from the template)",
    "use-missing": "Switched-off rule set with a missing target",
    "override-stale": "Overridden rule whose template text has changed",
    "ref-missing": "Broken references",
    "duplicate-unit": "Duplicate scripts/agents/skills",
    "duplicate-id": "Duplicate entry ids (task/backlog/question)",
    "entry-unreadable": "Entry files that cannot be read as UTF-8",
    "hook": "Missing hook entries",
    "settings-script": "Hook/permission entries pointing at a missing script",
    "manifest": ".act/MANIFEST.json drift",
    "script-docs": ".act/scripts/README.md out of date (script_docs.py)",
    "unknown-tool": "Unknown tool id(s) in docs/ai/config.md (`tools`)",
    "config-key": "Outdated keys in docs/ai/config.md",
    "status-value": "Unknown `status:` values in entry headers",
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
    except (OSError, UnicodeDecodeError):
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
    except (OSError, UnicodeDecodeError):
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
RE_FENCE = re.compile(r"^(`{3,}|~{3,})")
RE_INLINE_CODE = re.compile(r"(`+).*?\1")


def _target_exists(root: Path, target: str) -> bool:
    base = target.split("#", 1)[0]
    if base.startswith(".act/"):
        return actlib.resolve(rules.strip_template_prefix(base)) is not None
    return (root / base).is_file()


def _inline_code_ranges(line: str) -> list[tuple[int, int]]:
    """Start/end offsets of every backtick-delimited inline code span on `line` — approximate
    CommonMark (a run of N backticks, non-greedy content, the same run length to close), good
    enough to tell an example marker inside `` `...` `` apart from a live one (D2)."""
    return [match.span() for match in RE_INLINE_CODE.finditer(line)]


def check_act_refs(root: Path) -> list[Finding]:
    docs_dir = root / "docs"
    if not docs_dir.is_dir():
        return []
    findings = []
    for path in sorted(docs_dir.rglob("*.md")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        in_fence = False
        fence_char = ""
        fence_len = 0
        for i, line in enumerate(lines, start=1):
            fence_match = RE_FENCE.match(line.strip())
            if fence_match:
                marker = fence_match.group(1)
                char, length = marker[0], len(marker)
                if not in_fence:
                    in_fence, fence_char, fence_len = True, char, length
                elif char == fence_char and length >= fence_len:
                    in_fence, fence_char, fence_len = False, "", 0
                continue  # a fence delimiter line never carries a marker itself
            if in_fence:
                continue
            code_ranges = _inline_code_ranges(line)
            for match in RE_ACT_REF.finditer(line):
                if any(start <= match.start() < end for start, end in code_ranges):
                    continue  # inside an inline code span — example, not a live reference
                target = match.group("target")
                if not _target_exists(root, target):
                    findings.append(Finding(
                        path=_rel(path, root), line=i, kind="ref-missing",
                        message=f"act:ref target not found: {target}",
                    ))
    return findings


def check_bridge_files(root: Path) -> list[Finding]:
    """Role/skill bridges under .claude/agents/ and .claude/skills/, once they exist, mention the
    .act/ file they wrap in prose. Neither directory exists yet at this build stage — the check is a
    no-op until they do, rather than assuming a fixed layout."""
    findings = []
    for sub in ("agents", "skills"):
        bridge_dir = root / ".claude" / sub
        if not bridge_dir.is_dir():
            continue
        for path in sorted(bridge_dir.glob("*.md")):
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
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
# 7. Duplicate units — a project-side script/agent/skill file not explained by generation, a role
#    bridge, or the docs/ai/local/ overlay of the matching .act/ file
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
    """A file under docs/ai/local/ or .claude/ is legitimate — no finding — when it is: a skill
    copy init.copy_targets() would (re)write for the project's configured tools, or one already
    recorded under .act-lock.json's "copies" (covers a copy the template stopped shipping that the
    project has since edited — update.py's step 6 keeps exactly that case in the lock and deletes
    the rest, see step_refresh_copies()'s docstring); a role bridge init.agent_bridge_targets()
    names (bridges are never recorded in the lock, see agent_bridge_targets()'s docstring); or,
    for docs/ai/local/, the intended override of a .act/ file at the same relative path (the
    existing overlay rule). README.md files are documentation, never a unit, and skipped outright.
    .act/ itself is always the source and never the finding.

    What remains — grouped **by unit**, since that is what a human would recognize as "the same
    skill/role/script": a skill's unit is its directory name (every file inside one skill
    directory, e.g. SKILL.md plus a reference file, is the same unit — matching how a skill is
    identified everywhere else in this template), an agent's or a script's unit is its bare
    filename (each is a single flat file, no directory of its own) — is only a finding once **two
    or more** locations remain unexplained for that unit: an own role (.claude/agents/db-expert.md)
    or an own script (docs/ai/local/scripts/my_tool.py) with no .act/ counterpart is a single such
    file by itself and not reported; docs/ai/local/skills/x/SKILL.md next to
    .claude/skills/x/SKILL.md, both hand-made with no .act/ template and no copy/bridge/override
    behind either, is two — that one is reported. Grouping by bare filename alone would have
    falsely flagged two unrelated, legitimately hand-made skills as duplicates of each other, since
    every skill's file is named SKILL.md (confirmed 2026-09-22, review of T24)."""
    tools = _configured_tools(actlib.read_config())
    lock = actlib.read_lock()
    copy_dests = set(init.copy_targets(root, tools).keys()) | set(lock.get("copies", {}).keys())
    bridge_dests = set(init.agent_bridge_targets(root, tools).keys())

    units = [u for u in _scan_units(root) if u[2].name.lower() != "readme.md"]
    unit_base_dirs = dict(_UNIT_BASES)
    act_base = root / unit_base_dirs["act"]
    local_base = root / unit_base_dirs["local"]
    act_rels = {
        (sub, path.relative_to(act_base / sub).as_posix())
        for label, sub, path in units if label == "act"
    }

    def unit_key(label: str, sub: str, path: Path) -> tuple[str, str]:
        if sub == "skills":
            sub_dir = root / unit_base_dirs[label] / sub
            return (sub, path.relative_to(sub_dir).parts[0])  # the skill's directory name
        return (sub, path.name)  # a script/agent is a single flat file — its own unit

    by_unit: dict[tuple[str, str], list[tuple[str, str, Path]]] = defaultdict(list)
    for label, sub, path in units:
        by_unit[unit_key(label, sub, path)].append((label, sub, path))

    findings = []
    for (sub, name), entries in sorted(by_unit.items()):
        unexplained: list[Path] = []
        for label, sub_, path in entries:
            if label == "act":
                continue  # the template's own file — always the source, never the finding
            rel = _rel(path, root)
            if label == "claude" and (rel in copy_dests or rel in bridge_dests):
                continue  # generated skill copy or role bridge — expected
            if label == "local":
                own_rel = path.relative_to(local_base / sub_).as_posix()
                if (sub_, own_rel) in act_rels:
                    continue  # the intended docs/ai/local/ override of a template file
            unexplained.append(path)
        if len(unexplained) < 2:
            # a single project-owned unit (an own role, an own script, an own skill) is not a
            # duplicate of anything — only two or more remaining locations are one
            continue
        locations = ", ".join(_rel(path, root) for path in unexplained)
        findings.append(Finding(
            path=locations, line=None, kind="duplicate-unit",
            message=f"'{name}' present without a matching .act/ source, generated copy, or role bridge",
        ))
    return findings


# ---------------------------------------------------------------------------
# 10. Duplicate entry ids — thin wrapper around entries.find_duplicate_ids(), the merge-safety net
#     Q62a/Q65c call for on top of the filename-as-identity scheme itself.
# ---------------------------------------------------------------------------

def check_duplicate_entry_ids(root: Path) -> list[Finding]:
    findings = []
    for entry_id, paths in entries.find_duplicate_ids(root):
        locations = ", ".join(_rel(path, root) for path in paths)
        findings.append(Finding(
            path=locations, line=None, kind="duplicate-id",
            message=f"id '{entry_id}' assigned to more than one entry file",
        ))
    return findings


def check_unreadable_entries(root: Path) -> list[Finding]:
    """A file under an id-bearing entry directory that isn't valid UTF-8 — entries.py itself
    already skips it everywhere rather than crashing (find_unreadable_entries()), but a file that
    can never be scanned for its id is worth a finding of its own, not silence."""
    return [
        Finding(path=_rel(path, root), line=None, kind="entry-unreadable",
                message="not valid UTF-8 — cannot be scanned for its id")
        for path in entries.find_unreadable_entries(root)
    ]


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
    if not actlib.is_valid_hooks_container(settings):
        # hooks: null, settings.json not an object, an entry that isn't one, ... — same shape
        # init.py's/update.py's merge already refuses to touch (T46 review finding 6); doctor
        # reports it the same way rather than crashing or half-comparing against it.
        return [Finding(path=_rel(settings_path, root), line=None, kind="hook",
                         message="not a valid hooks structure, left unchanged")]

    existing_hooks = settings.get("hooks", {}) if isinstance(settings, dict) else {}
    bridge_hooks = bridge.get("hooks", {}) if isinstance(bridge, dict) else {}

    findings = []
    # The union, not just the bridge's own events (T46 review finding 7): a "ours" hook can sit
    # under an event the bridge no longer defines at all (the template retired the whole event),
    # not only under one where it still defines *other* entries — that case must be reported too.
    for event in sorted(set(bridge_hooks) | set(existing_hooks)):
        bridge_entries = bridge_hooks.get(event, [])
        existing_entries = existing_hooks.get(event, [])
        # Classified and counted per *hook*, not per entry (T46 review finding 3): a project hook
        # sharing an entry with a template hook (same matcher) must never make that whole entry
        # count as "ours", and an extra copy of a hook the bridge still wants exactly once (T46's
        # duplicate scenario) needs counting, not just membership, to be caught at all.
        bridge_hook_counts = Counter(
            json.dumps(hook, sort_keys=True)
            for entry in bridge_entries if isinstance(entry, dict)
            for hook in entry.get("hooks", []) if isinstance(hook, dict)
        )
        existing_ours_counts = Counter(
            json.dumps(hook, sort_keys=True)
            for entry in existing_entries if isinstance(entry, dict)
            for hook in entry.get("hooks", []) if actlib.is_ours_hook(hook, event)
        )
        # Both messages name `update.py --catch-up` specifically, not just "update.py": a project
        # whose .act/ already matches the current template (the common case here — nothing left
        # to fetch, only the hook entries are behind) makes a plain `update.py` report "nothing to
        # update" and exit without touching anything; --catch-up is the one that always reconciles
        # regardless (a run with an actual pending template diff self-relaunches under its own
        # fresh code after replacing .act/ and reconciles too, see _relaunch_after_replace).
        if bridge_hook_counts - existing_ours_counts:
            findings.append(Finding(
                path=_rel(settings_path, root), line=None, kind="hook",
                message=(
                    f"hook entry for event '{event}' missing (source: .act/bridges/settings.hooks.json) "
                    "-- run update.py --catch-up to reconcile"
                ),
            ))
        # What's left over in existing_ours_counts once every bridge hook is accounted for: a
        # template-generated hook (recognized by its exact command form, see actlib.is_ours_hook)
        # the bridge no longer wants — either an older matcher/event the template retired, or a
        # stale duplicate left over from before T46's fix to the merge logic. update.py reconciles
        # this; doctor only reports it.
        if existing_ours_counts - bridge_hook_counts:
            findings.append(Finding(
                path=_rel(settings_path, root), line=None, kind="hook",
                message=(
                    f"hook entry for event '{event}' outdated or duplicated against the template "
                    "(source: .act/bridges/settings.hooks.json) -- run update.py --catch-up to reconcile"
                ),
            ))
    return findings


# ---------------------------------------------------------------------------
# 13. Hook commands / Bash(...) permissions in .claude/settings.json (and, read-only,
#     .claude/settings.local.json) naming a project script that no longer exists — left over once
#     an adoption swapped an old template's scripts for this one's, but Claude Code itself never
#     complains about a dead permission or hook command (T54, D1).
# ---------------------------------------------------------------------------

# A relative script path such as ".claude/scripts/foo.py" or ".act/hooks/dispatch.py" embedded in a
# hook command string or a "Bash(...)" entry. The lookbehind/lookahead keep it from matching inside
# a longer glob ("scripts/*") or an absolute/parent path ("/usr/...", "../other-repo/...": the
# latter is filtered explicitly below, since ".." itself is a valid character in the class).
RE_SETTINGS_SCRIPT_PATH = re.compile(
    r"(?<![\w./-])((?:[\w.-]+/)+[\w.-]+\.(?:py|sh|bash|ps1|js|mjs|cjs|ts))(?![\w.-])"
)

# Claude Code expands `$CLAUDE_PROJECT_DIR` (also written `${CLAUDE_PROJECT_DIR}` or quoted,
# `"$CLAUDE_PROJECT_DIR"`) to the project root in a hook command — all three forms name a script
# relative to `root`, same as a plain relative path, but none of them match
# RE_SETTINGS_SCRIPT_PATH above: the plain form matches it *without* the "$" and is then checked
# as the literal (nonexistent) path "CLAUDE_PROJECT_DIR/...", and the quoted/braced forms don't
# match at all (T62 F8 review finding).
RE_PROJECT_DIR_SCRIPT = re.compile(
    r'"?\$\{?CLAUDE_PROJECT_DIR\}?"?/((?:[\w.-]+/)*[\w.-]+\.(?:py|sh|bash|ps1|js|mjs|cjs|ts))'
)


def _script_paths_in(text: str) -> list[str]:
    out = []
    project_dir_spans = []
    for match in RE_PROJECT_DIR_SCRIPT.finditer(text):
        out.append(match.group(1))
        project_dir_spans.append(match.span())
    for match in RE_SETTINGS_SCRIPT_PATH.finditer(text):
        # Same text a $CLAUDE_PROJECT_DIR match above already turned into a proper relative path —
        # without the guard, the plain (unquoted, unbraced) form also matches this regex, missing
        # the leading "$" it cannot see, and would add a second, bogus "CLAUDE_PROJECT_DIR/..."
        # candidate for the very same script.
        if any(start <= match.start() < end for start, end in project_dir_spans):
            continue
        candidate = match.group(1)
        if candidate.split("/", 1)[0] == "..":
            continue  # outside the project — not this check's business
        out.append(candidate)
    return out


def _missing_settings_scripts(root: Path, settings_path: Path) -> tuple[int, list[str]]:
    """(total occurrences, distinct paths) of a script named in `settings_path`'s hook commands or
    Bash(...) permission entries that does not exist under `root` — total counts every hook/
    permission occurrence (a script named twice across entries counts twice), distinct is the same
    set of paths first-seen order, deduplicated (T65: the old single list conflated the two —
    "5 shown, +1 more" claimed to be a count of entries while it was really the count of distinct
    paths, understating a settings file that names the same handful of missing scripts across many
    entries). (0, []) if the file is missing, not valid JSON, or not an object — same "never crash
    on a malformed settings file" stance as check_hooks() above."""
    if not settings_path.is_file():
        return 0, []
    try:
        raw = settings_path.read_bytes()
    except OSError:
        return 0, []
    try:
        # utf-8-sig strips a BOM when present (T62 F7: plain "utf-8" left it in front of "{" and
        # json.loads failed on it, so a BOM'd settings.local.json was silently skipped instead of
        # actually checked) and decodes plain UTF-8 exactly as before. A file in some other
        # encoding still can't be read here — same "skip, never crash" stance as before, just
        # catching the decode error too instead of letting it propagate.
        settings = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return 0, []
    if not isinstance(settings, dict):
        return 0, []

    candidates: list[str] = []
    hooks = settings.get("hooks", {})
    if isinstance(hooks, dict):
        for event_entries in hooks.values():
            if not isinstance(event_entries, list):
                continue
            for entry in event_entries:
                if not isinstance(entry, dict):
                    continue
                for hook in entry.get("hooks", []) or []:
                    if isinstance(hook, dict) and hook.get("type") == "command":
                        candidates += _script_paths_in(str(hook.get("command", "")))

    permissions = settings.get("permissions", {})
    if isinstance(permissions, dict):
        for key in ("allow", "deny", "ask"):
            for item in permissions.get(key, []) or []:
                if isinstance(item, str) and item.startswith("Bash("):
                    candidates += _script_paths_in(item)

    total = 0
    seen: set[str] = set()
    distinct: list[str] = []
    for candidate in candidates:
        if (root / candidate).is_file():
            continue
        total += 1
        if candidate not in seen:
            seen.add(candidate)
            distinct.append(candidate)
    return total, distinct


def check_settings_scripts(root: Path) -> list[Finding]:
    findings = []
    for rel in (".claude/settings.json", ".claude/settings.local.json"):
        total, distinct = _missing_settings_scripts(root, root / rel)
        if not distinct:
            continue
        shown = distinct[:5]
        tail = f", +{len(distinct) - len(shown)} more" if len(distinct) > len(shown) else ""
        findings.append(Finding(
            path=rel, line=None, kind="settings-script",
            message=(
                f"{total} hook/permission entr{'y' if total == 1 else 'ies'} "
                f"{'names' if total == 1 else 'name'} a script that no longer exists in the project "
                f"({len(distinct)} distinct path{'' if len(distinct) == 1 else 's'}): "
                f"{', '.join(shown)}{tail}"
            ),
        ))
    return findings


# Unknown tool identifiers configured in docs/ai/config.md's `tools` value (F10, T60) — a typo, or
# a spelling actlib.normalize_tool() does not recognize either (e.g. one carried over unchanged
# from .act/tiers.json's now-retired "-cli" convention, "gemini-cli" say). Reported here rather
# than only failing silently at init.py's SKILL_TARGET_DIRS gate, since a project can also
# hand-edit `tools` after init. Not in the header docstring's numbered list above (like
# check_script_docs() below, added after that list was last written) — see there for the same gap.
# ---------------------------------------------------------------------------

def check_unknown_tools(root: Path) -> list[Finding]:
    configured = _configured_tools(actlib.read_config())
    unknown = sorted({t for t in configured if actlib.normalize_tool(t) not in actlib.KNOWN_TOOLS})
    if not unknown:
        return []
    return [Finding(
        path="docs/ai/config.md", line=None, kind="unknown-tool",
        message=(
            f"`tools` entry not recognized: {', '.join(unknown)} — known ids: "
            f"{', '.join(sorted(actlib.KNOWN_TOOLS))} (see actlib.TOOL_ALIASES for accepted "
            "variant spellings)"
        ),
    )]


def check_legacy_config_keys(root: Path) -> list[Finding]:
    """One note for a config.md from before T61: the single `language` key still counts (for
    chat and docs alike, actlib.language_settings), but the two keys that replace it are missing."""
    config = actlib.read_config()
    if "language" not in config or "language-chat" in config or "language-docs" in config:
        return []
    chat, docs = actlib.language_settings(config)
    return [Finding(
        path="docs/ai/config.md", line=None, kind="config-key",
        message=(
            f"`language` is still read (as `language-chat` {chat!r} and `language-docs` {docs!r}); "
            "replace it with those two rows (`.act/skeleton/config.md` § Project, `R-work-language`)"
        ),
    )]


_UNRESOLVED_RE = re.compile(r"^(?P<path>.*?):(?P<line>\d+): (?P<message>.*)$")


def check_imports(root: Path) -> list[Finding]:
    """14. (T64) What Claude Code actually loads, followed from CLAUDE.md exactly the way it does
    (rules.resolve_imports): every import it cannot follow, and every rule file that should load
    but does not — a rule file under .act/rules/shared|orchestrator/ (named in docs/ai/rules.md
    but not imported, or not named there at all) and every checked coding set. Before T64 the
    imports resolved against the wrong folder and not one rule file loaded; this is the check
    that would have shown it. Skipped without a CLAUDE.md (Claude Code is not a configured tool)."""
    if not (root / "CLAUDE.md").is_file():
        return []
    reached, unresolved = rules.resolve_imports(root, "CLAUDE.md")
    findings: list[Finding] = []
    reported: set[tuple[str, Optional[int]]] = set()
    for entry in unresolved:
        match = _UNRESOLVED_RE.match(entry)
        path, line, message = (match.group("path"), int(match.group("line")) or None, match.group("message")) \
            if match else ("CLAUDE.md", None, entry)
        reported.add((path, line))
        findings.append(Finding(path=path, line=line, kind="import",
                                message=f"Claude Code does not load this: {message}"))

    loaded = set(reached)
    core = _parse_area(root, rules.AREAS["core"])
    named = {pset.path: pset.line for pset in core.sets} if core is not None else {}
    core_rel = rules.AREAS["core"].project_file
    for layer in ("shared", "orchestrator"):
        for path in sorted((root / ".act" / "rules" / layer).glob("*.md")):
            rel = path.relative_to(root).as_posix()
            if rel in loaded:
                continue
            wanted = rules.import_path(rel, core_rel)
            # Only a file docs/ai/rules.md names without importing it (backticks, the pre-T64
            # "@.act/..." form) — one whose line was dropped is switched off on purpose, as the
            # bridge offers ("drop an import line to switch off its whole area"); a file new in
            # the template reaches an unchanged copy through the bridge refresh (T64, F4).
            if rel not in named or (core_rel, named[rel]) in reported:
                continue  # not named, or already reported above as an import it cannot follow
            findings.append(Finding(
                path=core_rel, line=named[rel], kind="import",
                message=f"{rel} is named but not imported, so Claude Code never loads it — write it as {wanted}",
            ))

    coding_rel = rules.AREAS["coding"].project_file
    coding = _parse_area(root, rules.AREAS["coding"])
    checked = [pset for pset in (coding.sets if coding is not None else []) if pset.enabled]
    if checked and coding_rel not in loaded:
        wanted = "@" + os.path.relpath(coding_rel, os.path.dirname(core_rel)).replace(os.sep, "/")
        return findings + [Finding(
            path=core_rel, line=None, kind="import",
            message=(f"{coding_rel} is not imported, so its {len(checked)} checked set(s) never "
                     f"load — add {wanted} here, or uncheck the sets"),
        )]
    for pset in (coding.sets if coding is not None else []):
        if pset.enabled and pset.path not in loaded:
            findings.append(Finding(
                path=rules.AREAS["coding"].project_file, line=pset.line, kind="import",
                message=(f"checked set {pset.path} is not loaded by Claude Code — write it as "
                         f"{rules.import_path(pset.path, coding_rel)} (the session start does this)"),
            ))
    return findings


STATUS_SCAN_DIRS = ("docs/ai/inbox", "docs/ai/questions", "docs/ai/proposals", "docs/ai/work")
_STATUS_FIELD_RE = re.compile(r"(?im)^status:\s*(.*?)\s*$")


def check_status_values(root: Path) -> list[Finding]:
    """An entry header's `status:` value outside actlib.STATUS_VALUES — the mechanism reads only
    those words (board.py, the session-start count), so a translated value silently drops the
    entry from every count. README files and the legacy archive are not entries."""
    legacy = root / entries.LEGACY_ROOT
    findings = []
    for rel in STATUS_SCAN_DIRS:
        base = root / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.md")):
            if path.name.lower() == "readme.md" or legacy in path.parents:
                continue
            try:
                header = actlib.header_block(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue  # reported by check_unreadable_entries()
            match = _STATUS_FIELD_RE.search(header)
            if match and match.group(1).lower() not in actlib.STATUS_VALUES:
                findings.append(Finding(
                    path=_rel(path, root), line=None, kind="status-value",
                    message=(f"`status: {match.group(1)}` is not one of "
                             f"{', '.join(actlib.STATUS_VALUES)} — header values stay English"),
                ))
    return findings


# ---------------------------------------------------------------------------
# 9. .act/MANIFEST.json drift — a project's .act/ hand-edited since the last update, or, in the
#    template's own checkout, .act/ changed without re-running `manifest.py --write` before
#    committing (Q73a: the template ships its own MANIFEST.json now, so this same comparison
#    that update.py's step 2 already runs against a project's copy also catches the template
#    maintainer's own checkout going stale — one comparison, reused, no separate git-hook wiring
#    to install and keep working across clones/worktrees).
# ---------------------------------------------------------------------------

def check_manifest_drift(root: Path) -> list[Finding]:
    manifest_path = root / ".act" / "MANIFEST.json"
    if not manifest_path.is_file():
        return []
    try:
        recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [Finding(path=_rel(manifest_path, root), line=None, kind="manifest",
                         message="not valid JSON, cannot compare against .act/")]
    if not isinstance(recorded, dict):
        return [Finding(path=_rel(manifest_path, root), line=None, kind="manifest",
                         message="not a JSON object, cannot compare against .act/")]
    # A project (has .act-lock.json) reaches this state through update.py, which rescues a hand
    # edit under .act/ to docs/ai/local/ before overwriting it. Pointing it at `manifest.py
    # --write` instead -- as before -- would make the very next update.py run accept the edit
    # silently, no rescue, no re-review; that advice belongs only to the template's own checkout,
    # which is never a project and so has no lock file.
    is_project = (root / ".act-lock.json").is_file()
    resolve_hint = (
        "run `update.py` to reconcile it (rescues a hand edit to docs/ai/local/); to keep a "
        "change, put it in docs/ai/local/ as an override - never rewrite the manifest here"
    ) if is_project else "run `manifest.py --write`"
    current = manifest_mod.collect_files(root / ".act")
    findings = []
    for path, recorded_hash in sorted(recorded.items()):
        if path not in current:
            findings.append(Finding(path=f".act/{path}", line=None, kind="manifest",
                                     message="missing on disk, still listed in MANIFEST.json"))
        elif current[path] != recorded_hash:
            findings.append(Finding(path=f".act/{path}", line=None, kind="manifest",
                                     message=f"modified since MANIFEST.json was written ({resolve_hint})"))
    for path in sorted(current):
        if path not in recorded:
            findings.append(Finding(path=f".act/{path}", line=None, kind="manifest",
                                     message=f"added since MANIFEST.json was written ({resolve_hint})"))
    return findings


def check_script_docs(root: Path) -> list[Finding]:
    # The generated README.md embeds each script's own `--help` text, whose exact wording depends
    # on the interpreter's argparse (Python 3.9: "optional arguments:", 3.10+: "options:") — a
    # project running a different Python than whatever generated its .act/ could never make this
    # check pass, and the only "fix" available to it would be rewriting a file under .act/, which
    # is exactly what a project is not supposed to hand-edit (.act/MANIFEST.json already guards
    # that via check_manifest_drift() above). So this check only runs in the template's own
    # checkout — recognized the same way check_manifest_drift() tells a project apart from the
    # template above: a project always has .act-lock.json, the template checkout never does.
    if (root / ".act-lock.json").is_file():
        return []
    problems = script_docs.check(root)
    return [
        Finding(path=".act/scripts/README.md", line=None, kind="script-docs", message=problem)
        for problem in problems
    ]


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
    findings += check_duplicate_entry_ids(root)
    findings += check_unreadable_entries(root)
    findings += check_hooks(root)
    findings += check_settings_scripts(root)
    findings += check_unknown_tools(root)
    findings += check_legacy_config_keys(root)
    findings += check_imports(root)
    findings += check_status_values(root)
    findings += check_manifest_drift(root)
    findings += check_script_docs(root)

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
        description="Mechanical project/template reconciliation — see the header comment for the full list of checks.",
    )
    parser.add_argument("--target", metavar="DIR", help="check this project instead of the current checkout")
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

    if args.target:
        root = Path(args.target).expanduser().resolve()
        if not (root / ".act").is_dir():
            print(f"doctor.py: {root} has no .act/ — not a template-managed project", file=sys.stderr)
            return 2
        os.chdir(root)  # actlib's read_config()/resolve()/read_lock() find the project from the cwd
    else:
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
