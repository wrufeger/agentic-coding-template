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
#               the bridge no longer defines (outdated or a duplicate left over from before the
#               merge fix) — only checked when "claude-code" is one of the project's configured
#               tools, per docs/ai/config.md.
#            9. .act/MANIFEST.json drift against the .act/ tree on disk, wherever a MANIFEST.json
#               exists to compare against — a project that hand-edited .act/ since its last
#               update, or the template's own checkout if its maintainer forgot `manifest.py
#               --write` before committing an .act/ change.
#           10. a short id (T<n>/B<n>/Q<n>) assigned to more than one entry file under
#               docs/ai/work/ or docs/ai/inbox/ — the merge-safety net for team work,
#               reusing entries.py's own scan (entries.find_duplicate_ids()) rather than repeating
#               it here; plus, from the same scan, an entry file that isn't valid UTF-8 at all
#               (entries.find_unreadable_entries()) — this template never lets a decode failure
#               abort a run, here or in entries.py itself.
#           11. an outdated config.md key: the single `language` still in place of
#               `language-chat`/`language-docs` — still read, one note to replace it.
#           12. an entry whose `status:` header value is none the mechanism knows (open, answered,
#               done) — e.g. translated along with the scaffold; board.py and the session start
#               count only those values (R-work-language).
#           13. a hook command or a `Bash(...)` permission entry in .claude/settings.json (and,
#               read-only, .claude/settings.local.json) that names a project script path which no
#               longer exists — left over after an adoption replaced the old template's scripts
#               (the old scripts are gone). Never touches either file, only reports.
#           14. an @-import Claude Code cannot follow from CLAUDE.md (relative to the
#               importing file, at most four hops, rules.resolve_imports), every rule file
#               under .act/rules/shared|orchestrator/ docs/ai/rules.md names but does not import,
#               and every checked coding set that does not load.
#           15. leftover files under docs/ai/questions/ (besides its own README.md) — questions
#               live in docs/ai/inbox/ (kind: question) since the one-inbox format; a project
#               someone still writes to at the old location with an older checkout falls here.
#           16. a role/tier whose recorded usage.py outcomes cross a threshold
#               raise proposed once 30 outcomes are recorded and 60%+ of the last 30 are reworked/escalated — a finding (with
#               --inbox an inbox question of its own with options, filed once and not again until
#               30 more outcomes are recorded), never a live change to docs/ai/config.md. A lower tier is never proposed: a run of
#               accepted outcomes says nothing about whether a cheaper tier would have done as well.
#           17. a git remote whose address points at the template repository (its repository name is
#               exactly `agentic-coding-template`, or equals the source in .act-lock.json) while the current
#               branch has no upstream: a plain `git push`/`git pull` then goes to the template, not
#               to the project's own repository. Reported only — removing the remote stays with the
#               owner (`git remote remove <name>`).
#          18. a skill description or body that breaks the pattern in .act/skills/README.md § "Writing
#               a skill description" (skills.py --check, lint_skill()): too long or short, no
#               trigger sentence, a summary of steps, a "When to use" heading, a long SKILL.md with
#               no references/ folder. In a project only its own skills (docs/ai/local/skills/) are
#               checked — it cannot fix a template skill; the template's own checkout checks all.
#          19. the frontmatter of skills (.act/skills/, docs/ai/local/skills/) and roles
#               (.act/bridges/agents/, docs/ai/local/agents/, generated .claude/agents/): a value a strict
#               YAML parser rejects or reads differently (unquoted ': ' or ' #', a reserved first
#               character), a missing `name`/`description`, a `name` that differs from its folder or
#               file, an invalid `tier`/`reasoning`/`tools`/`model`/`effort`, and a field or tool name
#               no known tool reads (reported like every finding: it counts and sets exit 1, and
#               may be a newer tool's field). In a project only its own skills/roles are checked; the
#               template's checkout checks all.
#          19b. a file under docs/ai/local/ whose counterpart under .act/ is gone (the template
#               renamed or removed it, so the override has no effect), with the most similar name
#               there; and an archive collection file (docs/ai/work/archive/<kind>-<YYYY-MM>.md) with
#               a code block that is never closed.
#          20. a `revisit: YYYY-MM-DD` line under a decision in docs/project/decisions.md or
#               docs/project/decisions/*.md whose date has passed (today is not yet due), or that is not
#               a valid date. Nothing for a decision without the line or with a future date.
#          21. worker rules that need more parts than there are SubagentStart hook entries
#               (rules.py worker_overflow_warning): the parts beyond the last entry never reach a
#               worker, so the named rule files need shortening. Nothing without the overflow.
#          22. the order of the project docs (R-docs-order, switch `docs-order` in docs/ai/config.md
#               § Checks: warn (default) | block (= warn) | off): a folder under docs/project/ with
#               five or more entries and no README.md, a file or subfolder its README.md does not
#               name (docs-index-missing); an index line of such a README.md whose path names
#               nothing (docs-index-stale); a dead relative link or `docs/project/...md` path in
#               docs/README.md and docs/project/ (docs-link-dead); a concept under
#               docs/project/concepts/ whose questions are all answered or gone, with no open one
#               (docs-concept-decided); a file under docs/project/ of about 300 lines or more
#               (docs-file-long); a docs/README.md index line pointing below a subfolder of docs/
#               (docs-index-deep). Nothing with the switch off.
#          23. the size of the always-loaded own rules (the sections marked `act:own-rules` in
#               docs/ai/rules.md and docs/project/coding_rules.md together): one warning above the
#               budget `own-rules-budget` in docs/ai/config.md (default 6000 characters, `off` or `0`
#               skips it), with the characters, the budget, about 0.386 tokens per character and up to
#               five lines that read like history (a date, an entry identifier, "formerly ... since
#               ..."). Counted like any finding, never a block.
#          24. the working methods (`methods` in docs/ai/config.md, files in .act/methods/): an entry that
#               is no method name, a name no file backs (misspelled or removed), and a methods section in
#               docs/project/coding_rules.md that does not match the row — with the command that enters it
#               (rules.py --sync-methods).
#          25. the length of the entries under `## [Unreleased]` in CHANGELOG.md (switch
#               `changelog-length` in docs/ai/config.md § Checks: warn (default) | block (= warn) |
#               off): one warning when an entry (a `- ` item, its continuation lines joined with one
#               space, counted without the `- `) is over 250 characters, with the count and up to five
#               entries (first words, line, length). Nothing without a CHANGELOG.md, with `changelog`
#               set to `off` or `release-notes-only`, without an `[Unreleased]` section, or with the
#               switch off. The template's own checkout has no docs/ai/config.md, so the defaults
#               apply and its own CHANGELOG.md is checked too. Counted like any finding, never a block.
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
#   python .act/scripts/doctor.py --inbox            # also write a report-<YYYYMMDD-HHMM>-doctor.md entry
#                                                     # under docs/ai/inbox/, if there are findings
#                                                     # (a second run with the same findings updates
#                                                     # that same entry instead of adding another),
#                                                     # and one question per new tier proposal (16),
#                                                     # not part of the report, and one question per
#                                                     # check that refused workers at least 3 times in
#                                                     # 7 days (usage.py counts every refusal silently;
#                                                     # the proposal tells the worker beforehand what the
#                                                     # check does not allow, it never loosens the check)
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
import difflib
import hashlib
import json
import os
import posixpath
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import actlib
import entries
import frontmatter
import init
import manifest as manifest_mod
import rules
import script_docs
import settings_load
import skills
import tiers


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
    "duplicate-id": "Duplicate entry ids (task/backlog/question/todo)",
    "entry-unreadable": "Entry files that cannot be read as UTF-8",
    "orphan-file": "Files in the inbox or concept folder that no Markdown file under docs/ links",
    "override-orphan": "Override files under docs/ai/local/ whose template counterpart under .act/ is gone",
    "archive-fence": "Archive collection files with a code block that is never closed",
    "hook": "Missing hook entries",
    "settings-script": "Hook/permission entries pointing at a missing script",
    "manifest": ".act/MANIFEST.json drift",
    "script-docs": ".act/scripts/README.md out of date (script_docs.py)",
    "unknown-tool": "Unknown tool id(s) in docs/ai/config.md (`tools`)",
    "config-key": "Outdated keys in docs/ai/config.md",
    "config-value": "Invalid values in docs/ai/config.md",
    "methods": "Working methods (`methods` in docs/ai/config.md) that are unknown or not entered in the coding rules",
    "status-value": "Unknown `status:` values in entry headers",
    "legacy-questions-dir": "docs/ai/questions/ still in use (obsolete since the one-inbox format)",
    "local-risky-frontmatter": "Hand-written own role/skill with elevated-permission frontmatter keys",
    "tier-proposal": "Tier proposals from worker outcomes (R-role-outcome)",
    "template-remote": "Git remote pointing at the template while the branch has no upstream",
    "skill-lint": "Skill descriptions or bodies that break the writing pattern (skills.py --check)",
    "frontmatter-yaml": "Skill/role frontmatter that is not valid YAML",
    "frontmatter-field": "Skill/role frontmatter with missing, mismatched or invalid fields",
    "frontmatter-unknown": "Skill/role frontmatter fields or tool names no known tool reads (maybe newer than this check)",
    "revisit-due": "Decisions whose `revisit:` date has passed",
    "revisit-invalid": "Decisions with a `revisit:` line that is not a YYYY-MM-DD date",
    "worker-rules": "Worker rules that do not fit into the SubagentStart hook entries",
    "docs-index-missing": "Project docs without an index line (or a folder without README.md)",
    "docs-index-stale": "Index lines of a project docs README.md that name nothing",
    "docs-link-dead": "Dead relative links and paths in the project docs",
    "docs-file-long": "Project docs files of about 300 lines or more (split into a folder)",
    "docs-index-deep": "docs/README.md index lines that point below a subfolder of docs/",
    "docs-concept-decided": "Concepts whose questions are all answered (archive once built)",
    "own-rules-size": "Always-loaded own rules over the size budget (own-rules-budget)",
    "changelog-length": "Changelog entries under [Unreleased] over the length limit (changelog-length)",
}
KIND_ORDER = list(KIND_LABELS)

# German counterpart of KIND_LABELS, same keys — used only for the report *written under docs/*
# (write_inbox(), R-work-language via actlib.localized()); the console printer (_print_report)
# stays in KIND_LABELS' own English regardless of `language-docs`, since terminal output is not a
# file under docs/ and so outside that rule's scope.
KIND_LABELS_DE: dict[str, str] = {
    "validate": "Schema- und Satz-/Gruppenverweise (rules.py --validate)",
    "import": "Regeldateien, die Claude Code nicht lädt (rules.py --imports)",
    "dead-id": "Tote Kennungen (überschrieben/aus, aber aus der Vorlage verschwunden)",
    "use-missing": "Abgewählter Regelsatz mit fehlendem Ziel",
    "override-stale": "Überschriebene Regel, deren Vorlagentext sich geändert hat",
    "ref-missing": "Kaputte Verweise",
    "duplicate-unit": "Doppelte Scripte/Agenten/Skills",
    "duplicate-id": "Doppelte Eintragskennungen (Aufgabe/Backlog/Frage)",
    "entry-unreadable": "Eintragsdateien, die sich nicht als UTF-8 lesen lassen",
    "orphan-file": "Dateien in Inbox oder Konzeptordner, auf die keine Markdown-Datei unter docs/ verweist",
    "override-orphan": "Override-Dateien unter docs/ai/local/, deren Gegenstück der Vorlage unter .act/ fehlt",
    "archive-fence": "Sammeldateien des Archivs mit einem Codeblock, der nie geschlossen wird",
    "hook": "Fehlende Hook-Einträge",
    "settings-script": "Hook-/Berechtigungseinträge, die auf ein fehlendes Script zeigen",
    "manifest": ".act/MANIFEST.json weicht ab",
    "script-docs": ".act/scripts/README.md veraltet (script_docs.py)",
    "unknown-tool": "Unbekannte Werkzeugkennung(en) in docs/ai/config.md (`tools`)",
    "config-key": "Veraltete Schlüssel in docs/ai/config.md",
    "config-value": "Ungültige Werte in docs/ai/config.md",
    "methods": "Arbeitsmuster (`methods` in docs/ai/config.md), die unbekannt oder nicht in den Coding-Regeln eingetragen sind",
    "status-value": "Unbekannte `status:`-Werte in Eintragsköpfen",
    "legacy-questions-dir": "docs/ai/questions/ noch in Gebrauch (überholt seit dem Ein-Postfach-Format)",
    "local-risky-frontmatter": "Handgeschriebene eigene Rolle/Skill mit Frontmatter-Schlüsseln erhöhter Berechtigung",
    "tier-proposal": "Stufenvorschläge aus Worker-Ergebnissen (R-role-outcome)",
    "template-remote": "Git-Remote zeigt auf die Vorlage, obwohl der Branch keinen Upstream hat",
    "skill-lint": "Skill-Beschreibungen oder -Rümpfe, die das Schreibmuster verletzen (skills.py --check)",
    "frontmatter-yaml": "Skill-/Rollen-Frontmatter, das kein gültiges YAML ist",
    "frontmatter-field": "Skill-/Rollen-Frontmatter mit fehlenden, abweichenden oder ungültigen Feldern",
    "frontmatter-unknown": "Skill-/Rollen-Frontmatter-Felder oder Werkzeugnamen, die kein bekanntes Werkzeug liest (evtl. neuer als diese Prüfung)",
    "revisit-due": "Entscheidungen, deren `revisit:`-Datum verstrichen ist",
    "revisit-invalid": "Entscheidungen mit einer `revisit:`-Zeile, die kein Datum JJJJ-MM-TT ist",
    "worker-rules": "Worker-Regeln, die nicht in die SubagentStart-Hook-Einträge passen",
    "docs-index-missing": "Projektdoku ohne Indexzeile (oder Ordner ohne README.md)",
    "docs-index-stale": "Indexzeilen eines README.md der Projektdoku, die nichts benennen",
    "docs-link-dead": "Tote relative Verweise und Pfade in der Projektdoku",
    "docs-file-long": "Dateien der Projektdoku ab etwa 300 Zeilen (in einen Ordner aufteilen)",
    "docs-index-deep": "Indexzeilen in docs/README.md, die unter einen Unterordner von docs/ zeigen",
    "docs-concept-decided": "Konzepte, deren Fragen alle beantwortet sind (archivieren, sobald gebaut)",
    "own-rules-size": "Immer geladene eigene Regeln über dem Größenbudget (own-rules-budget)",
    "changelog-length": "Changelog-Einträge unter [Unreleased] über der Längengrenze (changelog-length)",
}


def _kind_label(kind: str, language: str) -> str:
    """The heading text for `kind` in the docs/ report (write_inbox()), picked by `language`
    (`language-docs`) via actlib.localized() — KIND_LABELS' own English for any language that
    resolves to it, KIND_LABELS_DE for German."""
    return actlib.localized(language, KIND_LABELS[kind], KIND_LABELS_DE[kind])


_rel = actlib.rel_posix


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
    unreadable: list[tuple[Path, str]] = field(default_factory=list)  # (file, reason): present, but not readable UTF-8


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
        else sorted([*(act_dir / "coding").glob("*.md"),
                     *(p for p in (act_dir / rules.METHODS_DIR).glob("*.md") if p.stem.lower() != "readme")])
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
    unreadable: list[tuple[Path, str]] = []
    for path, origin in _template_files(root, area_name):
        try:
            tset = rules.parse_template_set(path, origin)
        except (OSError, UnicodeDecodeError) as exc:
            unreadable.append((path, f"{exc.__class__.__name__}: {exc}"))
            continue
        for gid, group in tset.groups.items():
            ids.setdefault(gid, (path, origin))
            groups.setdefault(gid, group)
        for rid in _read_retired_ids(path):
            retired.setdefault(rid, []).append(path)
    return TemplateCorpus(ids=ids, retired=retired, groups=groups, unreadable=unreadable)


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

    for bad_path, reason in corpus.unreadable:
        findings.append(Finding(
            path=_rel(bad_path, root), line=None, kind="validate",
            message=f"rule set file cannot be read as UTF-8 ({reason}); its rules are not checked",
        ))

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
        try:
            found = rules.resolve_template_set(pset)
        except (OSError, UnicodeDecodeError) as exc:
            findings.append(Finding(
                path=project_rel, line=pset.line, kind="use-missing",
                message=f"switched-off use: target cannot be read: {pset.path} ({exc.__class__.__name__}: {exc})",
            ))
            continue
        if found is None:
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


RE_RULE_ID_HEADING = re.compile(r"^#{1,6}\s+`([\w-]+)`")


def _rule_ids_in_file(path: Path) -> set[str]:
    """IDs defined by `## \\`R-name\\` — ...`-style headings in a rules/coding-rules file (the
    convention used across `.act/rules/` and `.act/coding/`)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    ids: set[str] = set()
    for line in text.splitlines():
        match = RE_RULE_ID_HEADING.match(line)
        if match:
            ids.add(match.group(1))
    return ids


def _target_exists(root: Path, target: str) -> bool:
    base, _, anchor = target.partition("#")
    if base.startswith(".act/"):
        found = actlib.resolve(rules.strip_template_prefix(base))
        if found is None:
            return False
        resolved = found[0]
    else:
        resolved = root / base
        if not resolved.is_file():
            return False
    if anchor and resolved.suffix == ".md":
        return anchor in _rule_ids_in_file(resolved)
    return True


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
    every skill's file is named SKILL.md."""
    tools = _configured_tools(actlib.read_config())
    lock = actlib.read_lock()
    copy_dests = set(init.copy_targets(root, tools).keys()) | set(lock.get("copies", {}).keys())
    bridge_dests = set(init.agent_bridge_targets(root, tools).keys())
    # an own skill's file under docs/ai/local/ is explained once a copy recorded in the lock names it as source
    copy_sources = {
        entry["source"] for entry in lock.get("copies", {}).values()
        if isinstance(entry, dict) and isinstance(entry.get("source"), str)
    }

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
            if label == "local" and rel in copy_sources:
                continue  # source of a recorded tool copy (own skill) — expected
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
#     on top of the filename-as-identity scheme itself.
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


def check_legacy_questions_dir(root: Path) -> list[Finding]:
    """15. A project still has docs/ai/questions/ files besides its own README.md — e.g. a
    colleague on a checkout from before the one-inbox format still filing a question there. Questions
    live in docs/ai/inbox/ (kind: question) since that format; no update step moves them any more, so
    this per-project drift check is the only place that notices a file left at the old location."""
    questions_dir = root / "docs" / "ai" / "questions"
    if not questions_dir.is_dir():
        return []
    leftover = [p for p in sorted(questions_dir.iterdir()) if p.is_file() and p.name != "README.md"]
    if not leftover:
        return []
    return [Finding(
        path=_rel(questions_dir, root), line=None, kind="legacy-questions-dir",
        message=(f"{len(leftover)} file(s) still here; obsolete since the one-inbox format — "
                 "questions live in docs/ai/inbox/ (kind: question)"),
    )]


def check_local_role_frontmatter(root: Path) -> list[Finding]:
    """A hand-written own role or skill under docs/ai/local/agents/*.md or
    docs/ai/local/skills/*/SKILL.md may carry the same risky frontmatter keys settings_load.py's
    import validator already refuses on the bundled-import path (_AGENT_RISKY_KEYS/
    _SKILL_RISKY_KEYS) — reused here rather than a second copy of the list, so the two stay in
    sync. A hand-written unit never goes through that validator at all, so this is the only place
    that ever looks; a finding is informational (this is init.py's own worker/high-permission
    role territory, allowed by hand), not an error."""
    findings: list[Finding] = []
    local_dir = root / "docs" / "ai" / "local"
    candidates: list[tuple[Path, tuple[str, ...]]] = []
    agents_dir = local_dir / "agents"
    if agents_dir.is_dir():
        for path in sorted(agents_dir.glob("*.md")):
            if path.name.lower() != "readme.md":
                candidates.append((path, settings_load._AGENT_RISKY_KEYS))
    skills_dir = local_dir / "skills"
    if skills_dir.is_dir():
        for skill_path in sorted(skills_dir.iterdir()):
            skill_md = skill_path / "SKILL.md"
            if skill_path.is_dir() and skill_md.is_file():
                candidates.append((skill_md, settings_load._SKILL_RISKY_KEYS))
    for path, risky_keys in candidates:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        fields, ok, _error = settings_load._strict_frontmatter(text)
        if not ok:
            continue  # unparseable frontmatter is its own concern, not this check's to report
        found = [k for k in risky_keys if k.lower() in fields]
        if found:
            findings.append(Finding(
                path=_rel(path, root), line=None, kind="local-risky-frontmatter",
                message=f"hand-written unit carries elevated-permission key(s): {', '.join(found)}",
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


ORPHAN_SCAN_DIRS = ("docs/ai/inbox", "docs/ai/concept")


def check_orphan_files(root: Path) -> list[Finding]:
    """A pasted image or attachment left beside the entries: a non-Markdown file under the inbox or
    concept folder that no Markdown file under docs/ links. Dot-files (.gitkeep) are left out. Any
    Markdown file under docs/ counts as a link, the archive too: a picture an archived entry still
    shows is not left over. `entries.py archive` moves such files along with their entry; this finds
    what a hand-made move or an unfinished idea take-over left behind."""
    docs = root / "docs"
    if not docs.is_dir():
        return []
    linked: set[Path] = set()
    for markdown in docs.rglob("*.md"):
        try:
            text = markdown.read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue  # reported by check_unreadable_entries()
        linked |= entries.linked_local_files(text, markdown.parent)
    findings: list[Finding] = []
    for rel in ORPHAN_SCAN_DIRS:
        base = root / rel
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if (path.is_file() and path.suffix.lower() != ".md" and not path.name.startswith(".")
                    and Path(os.path.normpath(path)) not in linked):
                findings.append(Finding(
                    path=_rel(path, root), line=None, kind="orphan-file",
                    message="no Markdown file under docs/ links it — archive it with its entry "
                            "(entries.py archive) or delete it",
                ))
    return findings


# Sub-folders of docs/ai/local/ that are not file-for-file overrides: rule overrides work on
# sections of a rule file (found by their ids, checked by the dead-id check), and own roles live
# under agents/.
_OVERRIDE_SKIP_DIRS = ("rules", "agents")
_OVERRIDE_SIMILAR_CUTOFF = 0.6


def _strictly_similar(own: str, other: str) -> bool:
    """True when one file name is a prefix of the other (`workflow.js` / `workflow.js.txt`) or both
    have the same stem with another extension."""
    if own == other:
        return False
    if own.startswith(other) or other.startswith(own):
        return True
    own_stem, other_stem = Path(own).stem, Path(other).stem
    return bool(own_stem) and own_stem == other_stem


def check_override_orphans(root: Path) -> list[Finding]:
    """A file under docs/ai/local/ is the override of the file at the same path under .act/. When
    the template renames or removes that file, the override silently stops working. Reported:
    every such file whose counterpart is missing, with the most similar name under .act/. Left out:
    the rules/ and agents/ sub-folders (see _OVERRIDE_SKIP_DIRS), README.md files, files directly
    in docs/ai/local/, and a file of an own skill (its skill folder is not in the template at
    all). Any other file with no counterpart (an own script or coding set, say) is reported only when
    .act/ has a file of a strictly similar name - one name a prefix of the other, or the same stem
    with another extension - since otherwise it is most likely the project's own. Inside a skill
    folder a fuzzy name match is enough."""
    local = root / "docs" / "ai" / "local"
    act = root / ".act"
    if not local.is_dir() or not act.is_dir():
        return []
    findings: list[Finding] = []
    for path in sorted(local.rglob("*")):
        if not path.is_file() or path.name.lower() == "readme.md" or "__pycache__" in path.parts:
            continue
        rel = path.relative_to(local)
        if len(rel.parts) < 2 or rel.parts[0] in _OVERRIDE_SKIP_DIRS:
            continue
        if (act / rel).exists():
            continue
        in_skill = rel.parts[0] == "skills" and len(rel.parts) >= 3
        if in_skill and not (act / "skills" / rel.parts[1]).is_dir():
            continue  # an own skill
        # candidates: the files next to where the counterpart would be (a skill: the whole skill)
        scope = act / "skills" / rel.parts[1] if in_skill else act / rel.parent
        names = {c.name: c.relative_to(act).as_posix() for c in sorted(scope.rglob("*"))
                 if c.is_file() and "__pycache__" not in c.parts} if scope.is_dir() else {}
        wanted = rel.as_posix()
        # compare the file names only: the shared folder prefix would make every name look alike
        if in_skill:
            close = [names[name] for name in
                     difflib.get_close_matches(path.name, list(names), n=1, cutoff=_OVERRIDE_SIMILAR_CUTOFF)]
        else:
            close = [names[name] for name in sorted(names) if _strictly_similar(path.name, name)][:1]
        if not close and not in_skill:
            continue
        hint = (f"; the most similar name there is `.act/{close[0]}`" if close
                else f"; `.act/skills/{rel.parts[1]}/` has no file of a similar name")
        findings.append(Finding(
            path=_rel(path, root), line=None, kind="override-orphan",
            message=(f"note: this override has no counterpart `.act/{wanted}` any more, so it has no effect"
                     f"{hint} - move the change there or delete the override"),
        ))
    return findings


_ARCHIVE_COLLECTION_NAME = re.compile(r"^[A-Za-z]+-\d{4}-\d{2}\.md$")


def check_archive_fences(root: Path) -> list[Finding]:
    """A code block in an archive collection file (docs/ai/work/archive/<kind>-<YYYY-MM>.md) that
    is opened and never closed swallows the rest of the file, so the anchors after it no longer
    count. Reported with the line of the opening fence."""
    archive = root / "docs" / "ai" / "work" / "archive"
    if not archive.is_dir():
        return []
    findings: list[Finding] = []
    for path in sorted(archive.iterdir()):
        if not path.is_file() or not _ARCHIVE_COLLECTION_NAME.match(path.name):
            continue
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeDecodeError):
            continue  # reported by check_unreadable_entries()
        state: actlib.FenceState = None
        opened_at = 0
        for number, line in enumerate(lines, start=1):
            before = state
            state = actlib.fence_step(state, line)
            if before is None and state is not None:
                opened_at = number
        if state is not None:
            findings.append(Finding(
                path=_rel(path, root), line=opened_at, kind="archive-fence",
                message=(f"code block opened here is never closed (expected `{actlib.fence_closer(state)}`): "
                         "the anchors after it no longer count as found"),
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
    if not actlib.is_valid_hooks_container(settings):
        # hooks: null, settings.json not an object, an entry that isn't one, ... — same shape
        # init.py's/update.py's merge already refuses to touch; doctor
        # reports it the same way rather than crashing or half-comparing against it.
        return [Finding(path=_rel(settings_path, root), line=None, kind="hook",
                         message="not a valid hooks structure, left unchanged")]

    existing_hooks = settings.get("hooks", {}) if isinstance(settings, dict) else {}
    bridge_hooks = bridge.get("hooks", {}) if isinstance(bridge, dict) else {}

    findings = []
    # The union, not just the bridge's own events: a "ours" hook can sit
    # under an event the bridge no longer defines at all (the template retired the whole event),
    # not only under one where it still defines *other* entries — that case must be reported too.
    for event in sorted(set(bridge_hooks) | set(existing_hooks)):
        bridge_entries = bridge_hooks.get(event, [])
        existing_entries = existing_hooks.get(event, [])
        # Classified and counted per *hook*, not per entry: a project hook
        # sharing an entry with a template hook (same matcher) must never make that whole entry
        # count as "ours", and an extra copy of a hook the bridge still wants exactly once
        # (a duplicate) needs counting, not just membership, to be caught at all.
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
        # stale duplicate left over from before the merge logic was fixed. update.py reconciles
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
#     complains about a dead permission or hook command.
# ---------------------------------------------------------------------------

# A relative script path such as ".claude/scripts/foo.py" or ".act/hooks/dispatch.py" embedded in a
# hook command string or a "Bash(...)" entry. The lookbehind/lookahead keep it from matching inside
# a longer glob ("scripts/*") or an absolute/parent path ("/usr/...", "../other-repo/...": the
# latter is filtered explicitly below, since ".." itself is a valid character in the class).
RE_SETTINGS_SCRIPT_PATH = re.compile(
    r"(?<![\w./-])((?:[\w.-]+/)+[\w.-]+\.(?:py|sh|bash|ps1|js|mjs|cjs|ts))(?![\w.-])"
)

# Claude Code expands `$CLAUDE_PROJECT_DIR` (also written `${CLAUDE_PROJECT_DIR}`, quoted
# `"$CLAUDE_PROJECT_DIR"`, or with a bash default-value fallback `${CLAUDE_PROJECT_DIR:-.}`, this
# template's own form) to the project root in a hook command — all these forms name a
# script relative to `root`, same as a plain relative path, but none of them match
# RE_SETTINGS_SCRIPT_PATH above: the plain form matches it *without* the "$" and is then checked
# as the literal (nonexistent) path "CLAUDE_PROJECT_DIR/...", and the quoted/braced/default-value
# forms don't match at all (a quoted form once slipped through).
RE_PROJECT_DIR_SCRIPT = re.compile(
    r'"?\$\{?CLAUDE_PROJECT_DIR(?::-[^}]*)?\}?"?/((?:[\w.-]+/)*[\w.-]+\.(?:py|sh|bash|ps1|js|mjs|cjs|ts))'
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
    set of paths first-seen order, deduplicated (an earlier single list conflated the two —
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
        # utf-8-sig strips a BOM when present (plain "utf-8" left it in front of "{" and
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


# Unknown tool identifiers configured in docs/ai/config.md's `tools` value — a typo, or
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
    """One note for a config.md from before the split: the single `language` key still counts (for
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


def check_config_values(root: Path) -> list[Finding]:
    """One finding per config.md key of actlib.CONFIG_SCHEMA with a list of values or a pattern whose
    value fits neither. An empty value means the default; free-text keys accept everything."""
    config = actlib.read_config(root)
    findings: list[Finding] = []
    for key, entry in actlib.CONFIG_SCHEMA.items():
        if entry.values is None and entry.pattern is None:
            continue
        value = config.get(key, "").strip().strip("`").strip()
        if value and not actlib.config_value_ok(entry, value):
            allowed = " | ".join(entry.values) if entry.values else ""
            if entry.pattern:
                allowed = f"{allowed} | format {entry.pattern}" if allowed else f"format {entry.pattern}"
            findings.append(Finding(
                path="docs/ai/config.md", line=None, kind="config-value",
                message=f"`{key}` is {value!r} — use {allowed}",
            ))
    return findings


def check_methods(root: Path) -> list[Finding]:
    """The working methods (`methods` row of docs/ai/config.md, .act/methods/): an entry that is no
    method name, a name without a file (dead or misspelled), and a methods section in
    docs/project/coding_rules.md that does not match the row — each with the command that fixes it
    (rules.method_findings). Nothing for a project that uses no method."""
    return [Finding(path=path, line=None, kind="methods", message=message)
            for path, message in rules.method_findings(root)]


_UNRESOLVED_RE = re.compile(r"^(?P<path>.*?):(?P<line>\d+): (?P<message>.*)$")


def check_imports(root: Path) -> list[Finding]:
    """14. What Claude Code actually loads, followed from CLAUDE.md exactly the way it does
    (rules.resolve_imports): every import it cannot follow, and every rule file that should load
    but does not — a rule file under .act/rules/shared|orchestrator/ (named in docs/ai/rules.md
    but not imported, or not named there at all) and every checked coding set. Formerly the
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
            # Only a file docs/ai/rules.md names without importing it (backticks, the older
            # "@.act/..." form) — one whose line was dropped is switched off on purpose, as the
            # bridge offers ("drop an import line to switch off its whole area"); a file new in
            # the template reaches an unchanged copy through the bridge refresh.
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
        wanted_path = rules.loaded_set_path(pset.path, root)
        if pset.enabled and wanted_path not in loaded:
            findings.append(Finding(
                path=rules.AREAS["coding"].project_file, line=pset.line, kind="import",
                message=(f"checked set {pset.path} is not loaded by Claude Code — write it as "
                         f"{rules.import_path(pset.path, coding_rel, root)} (the session start does this)"),
            ))
    return findings


def check_worker_rules(root: Path) -> list[Finding]:
    """Worker rules that need more parts than there are SubagentStart hook entries: the parts
    beyond the last entry never reach a worker. Skipped without a CLAUDE.md."""
    if not (root / "CLAUDE.md").is_file():
        return []
    try:
        warning = rules.worker_overflow_warning(rules.worker_rule_parts(root))
    except Exception:  # noqa: BLE001 - a check that cannot assemble the parts says nothing here
        return []
    if not warning:
        return []
    return [Finding(path="CLAUDE.md", line=None, kind="worker-rules",
                    message=warning.removeprefix("warning: "))]


STATUS_SCAN_DIRS = ("docs/ai/inbox", "docs/ai/proposals", "docs/ai/work")
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
# 20. `revisit:` dates on decisions — a decision may carry a line `revisit: YYYY-MM-DD` under its
#     heading: the day to look at it again.
#     Read: docs/project/decisions.md and docs/project/decisions/*.md (that folder only, not
#     subfolders such as an archive); never docs/ai/, so archived inbox entries cannot match.
#     Accepted line forms: `revisit: ...`, optionally after a list marker (`- `, `* `, `+ `, `1. `)
#     and with the word bold (`**revisit:** ...`); not in a quote (`> revisit:`). Only a date counts:
#     prose such as `Revisit: when the API is stable` is revisit-invalid. A line belongs to the
#     nearest heading above it; one in a fenced code block is an example and ignored. A line before
#     the first heading (header fields above `# Title`) is ignored in decisions.md and belongs to the
#     first heading of a decisions/ file (its file name if it has none). A file that is not UTF-8 is
#     skipped without a finding.
# ---------------------------------------------------------------------------

DECISION_FILES = ("docs/project/decisions.md",)
DECISION_DIRS = ("docs/project/decisions",)
_REVISIT_RE = re.compile(
    r"^\s*(?:(?:[-*+]|\d+[.)])\s+)?(?:\*\*|__)?revisit:(?:\*\*|__)?[ \t]*(.*?)\s*$", re.IGNORECASE)
_REVISIT_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?=\s|$)")
_HEADING_RE = re.compile(r"^ {0,3}#{1,6}\s+(.*?)\s*#*\s*$")
_FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def _decision_files(root: Path) -> list[tuple[Path, bool]]:
    """(path, is_single_decision_file): decisions.md holds many decisions, a decisions/ file one."""
    found = [(root / rel, False) for rel in DECISION_FILES if (root / rel).is_file()]
    for rel in DECISION_DIRS:
        base = root / rel
        if base.is_dir():
            found += [(p, True) for p in sorted(base.glob("*.md")) if p.is_file()]
    return found


def _revisit_lines(lines: list[str]) -> tuple[list[tuple[int, str, Optional[str]]], Optional[str]]:
    """((line number, value, heading or None) for each `revisit:` line outside fenced code, the
    first heading of the file outside fenced code)."""
    hits: list[tuple[int, str, Optional[str]]] = []
    heading: Optional[str] = None
    first: Optional[str] = None
    fence = ""  # the opening run, e.g. "```" or "~~~~"; empty outside a fence
    for number, line in enumerate(lines, start=1):
        fence_match = _FENCE_RE.match(line)
        if fence:
            # CommonMark: a closing fence uses the same character, is at least as long, has no text.
            if (fence_match and fence_match.group(1)[0] == fence[0]
                    and len(fence_match.group(1)) >= len(fence) and not fence_match.group(2).strip()):
                fence = ""
            continue
        if fence_match:
            fence = fence_match.group(1)
            continue
        head = _HEADING_RE.match(line)
        if head:
            heading = head.group(1)
            first = first or heading
            continue
        match = _REVISIT_RE.match(line)
        if match:
            hits.append((number, match.group(1), heading))
    return hits, first


def check_revisit_dates(root: Path, today: Optional[date] = None) -> list[Finding]:
    """A `revisit:` date in a decision record that has passed (kind revisit-due) or is not a real
    YYYY-MM-DD date (kind revisit-invalid — it would otherwise never fire). Today counts as not yet
    due; a decision without the line is fine. See the section comment above for the accepted forms."""
    today = today or date.today()
    findings = []
    for path, single in _decision_files(root):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue  # not UTF-8: skipped, no finding (check_unreadable_entries() covers docs/ai/ only)
        hits, first_heading = _revisit_lines(lines)
        for number, value, heading in hits:
            if heading is None and single:
                heading = first_heading or path.stem
            if heading is None:
                continue
            date_match = _REVISIT_DATE_RE.match(value)
            parsed: Optional[date] = None
            if date_match:
                try:
                    parsed = date(*(int(g) for g in date_match.groups()))
                except ValueError:
                    parsed = None
            if parsed is None:
                findings.append(Finding(
                    path=_rel(path, root), line=number, kind="revisit-invalid",
                    message=(f"decision \"{heading}\": `revisit: {value}` is not a date — "
                             f"only YYYY-MM-DD counts, put any reason on its own line"),
                ))
            elif parsed < today:
                findings.append(Finding(
                    path=_rel(path, root), line=number, kind="revisit-due",
                    message=f"decision \"{heading}\" was due for a second look on {parsed.isoformat()}",
                ))
    return findings


# ---------------------------------------------------------------------------
# 8b. Order of the project docs (R-docs-order) — the layout under docs/project/ stays findable:
#     a README.md with one line per entry in every folder of five or more entries, no index line
#     without its file, no dead relative link, no concept that is decided but still lying around.
# ---------------------------------------------------------------------------

DOCS_ORDER_MIN_ENTRIES = 5
_DOCS_PATH_TOKEN_RE = re.compile(r"^[\w.\-/]+$")
_DOCS_TICK_RE = re.compile(r"`([^`\n]+)`")
_DOCS_LINK_TARGET_RE = re.compile(r"\]\(<?([^)<>\s]+)")
_DOCS_PROJECT_PATH_RE = re.compile(r"^docs/project/[\w.\-/]+\.md$")
_DOCS_PLACEHOLDER_RE = re.compile(r"YYYY|MM-DD|NNN|[<>*{}]")  # a pattern such as YYYY-MM-DD_title.md, not a path
_QUESTION_ID_RE = re.compile(r"`Q(\d+)`")  # only an identifier in backticks is a question, not a quarter in prose
_STATUS_LINE_RE = re.compile(r"(?im)^status:\s*(.*?)\s*$")
# the header line of a collection section: `status: done · archived: 2026-10-01 · file: ...` in inline code
_SECTION_STATUS_RE = re.compile(r"(?i)(?:^|[`\s·])status:\s*([^·`]*?)\s*(?:·|`|$)")


def docs_order_enabled(root: Path) -> bool:
    """False only for `docs-order` set to `off`; a missing row, `warn` and `block` all report."""
    return actlib.read_config(root).get("docs-order", "").strip().strip("`").strip().lower() != "off"


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None  # reported by check_unreadable_entries() where it is an entry


def _unfenced(text: str) -> list[tuple[int, str]]:
    """(line number, line) of every line outside a fenced code block, fence lines left out."""
    out: list[tuple[int, str]] = []
    fence = None
    for number, line in enumerate(text.split("\n"), start=1):
        was_fenced, fence = fence is not None, actlib.fence_step(fence, line)
        if not was_fenced and fence is None:
            out.append((number, line))
    return out


def _git_ignored(root: Path) -> list[Path]:
    """What Git ignores below docs/ (a folder that is wholly ignored once, as the folder); empty
    without Git or outside a repository, so then nothing is skipped."""
    try:
        result = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "-o", "-i", "--exclude-standard",
                                 "--directory", "--", "docs"], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    return [root / item.rstrip("/") for item in result.stdout.split("\0") if item]


def _is_ignored(path: Path, ignored: list[Path]) -> bool:
    return any(path == item or item in path.parents for item in ignored)


def _docs_folders(project: Path, ignored: list[Path]) -> list[Path]:
    """docs/project and every visible folder below it that Git does not ignore, in path order."""
    folders = [project]
    for path in sorted(project.rglob("*")):
        if (path.is_dir() and not any(part.startswith(".") for part in path.relative_to(project).parts)
                and not _is_ignored(path, ignored)):
            folders.append(path)
    return folders


def _folder_entries(folder: Path, ignored: list[Path]) -> list[Path]:
    """The Markdown files and the folders with content directly in `folder`, README.md left out;
    what Git ignores is not an entry."""
    out: list[Path] = []
    for path in sorted(folder.iterdir()):
        if path.name.startswith(".") or _is_ignored(path, ignored):
            continue
        if path.is_file() and path.suffix.lower() == ".md" and path.name.lower() != "readme.md":
            out.append(path)
        elif path.is_dir() and any(not child.name.startswith(".") and not _is_ignored(child, ignored)
                                   for child in path.rglob("*") if child.is_file()):
            out.append(path)
    return out


def _names_in(text: str, name: str, folder: bool = False) -> bool:
    """`name` appears in `text` outside a fenced block. A folder counts only as `name/` or in
    backticks: the plain word ("data as of ...") is not the folder."""
    quoted = re.escape(name)
    if folder:
        pattern = r"(?<![\w.\-])" + quoted + r"/|`" + quoted + r"`"
    else:
        pattern = r"(?<![\w.\-])" + quoted + r"(?![\w\-])"
    return any(re.search(pattern, line) for _number, line in _unfenced(text))


def _index_path(line: str) -> Optional[str]:
    """The first path token (link target or backticks) of a list item, or of the FIRST CELL of a table
    row, that looks like a Markdown file or a folder, else None. Later cells of a table row are
    content (a decision's link, an old -> new mapping), not index entries."""
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:].split("|", 1)[0].strip()
    elif not re.match(r"[-*+]\s", stripped):
        return None
    first: Optional[tuple[int, str]] = None
    for regex in (_DOCS_TICK_RE, _DOCS_LINK_TARGET_RE):
        match = regex.search(stripped)
        if match and (first is None or match.start() < first[0]):
            first = (match.start(), match.group(1).strip())
    if first is None:
        return None
    token = first[1]
    if (not _DOCS_PATH_TOKEN_RE.match(token) or _DOCS_PLACEHOLDER_RE.search(token)
            or not (token.endswith(".md") or token.endswith("/"))):
        return None
    return token


def _check_docs_indexes(root: Path, project: Path, ignored: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for folder in _docs_folders(project, ignored):
        entries_here = _folder_entries(folder, ignored)
        readme = folder / "README.md"
        if not readme.is_file():
            if len(entries_here) >= DOCS_ORDER_MIN_ENTRIES:
                findings.append(Finding(
                    path=_rel(folder, root), line=None, kind="docs-index-missing",
                    message=(f"{len(entries_here)} entries but no README.md — add one with a line per "
                             "file and subfolder (R-docs-order)"),
                ))
            continue
        text = _read_text(readme)
        if text is None:
            continue
        for entry in entries_here:
            name = entry.name
            if not _names_in(text, name, entry.is_dir()):
                findings.append(Finding(
                    path=_rel(entry, root), line=None, kind="docs-index-missing",
                    message=f"{_rel(readme, root)} has no line for {name}{'/' if entry.is_dir() else ''}",
                ))
        for number, line in _unfenced(text):
            token = _index_path(line)
            if token is None:
                continue
            base = root if token.startswith("docs/") else folder
            if not (base / token).exists():
                findings.append(Finding(
                    path=_rel(readme, root), line=number, kind="docs-index-stale",
                    message=f"index line names {token}, which does not exist",
                ))
    return findings


def _check_docs_links(root: Path, docs: Path, ignored: list[Path]) -> list[Finding]:
    """Dead relative Markdown links and `docs/project/...md` paths in docs/README.md and docs/project/
    (decisions.md and the decisions/ folder: links only, their records name files that were deleted later;
    ignored files skipped)."""
    files = [docs / "README.md"] if (docs / "README.md").is_file() else []
    project = docs / "project"
    if project.is_dir():
        files += [item for item in sorted(project.rglob("*.md")) if not _is_ignored(item, ignored)]
    findings: list[Finding] = []
    for path in files:
        text = _read_text(path)
        if text is None:
            continue
        dead: list[str] = []

        def note(target: str, resolved: Path) -> None:
            if not resolved.exists() and target not in dead:
                dead.append(target)

        entries._rewrite_links(text, path.parent, lambda target, resolved: note(target, resolved))
        lines = text.split("\n")
        for target in dead:
            at = next((i for i, line in enumerate(lines, start=1) if target in line), None)
            findings.append(Finding(
                path=_rel(path, root), line=at, kind="docs-link-dead",
                message=f"link target {target} does not exist",
            ))
        seen: set[str] = set()
        records = path == project / "decisions.md" or (project / "decisions") in path.parents
        for number, line in ([] if records else _unfenced(text)):
            for match in _DOCS_TICK_RE.finditer(line):
                token = match.group(1).strip()
                if (_DOCS_PROJECT_PATH_RE.match(token) and not _DOCS_PLACEHOLDER_RE.search(token)
                        and token not in seen and not (root / token).exists()):
                    seen.add(token)
                    findings.append(Finding(
                        path=_rel(path, root), line=number, kind="docs-link-dead",
                        message=f"path {token} does not exist",
                    ))
    return findings


def _question_states(root: Path) -> dict[str, str]:
    """canonical question id -> status ("open", "answered", "done" or "") for every entry file."""
    states: dict[str, str] = {}
    for path in entries._entry_files(root):
        text = entries._safe_read(path)
        if text is None:
            continue
        if actlib.is_collection(text):  # one header per section: the inline-code line under its heading
            lines = text.removeprefix("\ufeff").split("\n")
            for entry_id, anchor_line in actlib.collection_sections(text):
                header = lines[anchor_line + 1] if anchor_line + 1 < len(lines) else ""
                found = _SECTION_STATUS_RE.search(header)
                states.setdefault(entry_id, found.group(1).lower() if found else "")
            continue
        match = _STATUS_LINE_RE.search(actlib.header_block(text))
        for entry_id in actlib.entry_ids(text):
            states.setdefault(entry_id, match.group(1).lower() if match else "")
    return states


def _check_decided_concepts(root: Path, project: Path) -> list[Finding]:
    concepts = project / "concepts"
    if not concepts.is_dir():
        return []
    states: Optional[dict[str, str]] = None
    reserved: set[str] = set()
    findings: list[Finding] = []
    for path in sorted(concepts.rglob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        text = _read_text(path)
        if text is None:
            continue
        numbers = sorted({int(m.group(1)) for _n, line in _unfenced(text) for m in _QUESTION_ID_RE.finditer(line)})
        if not numbers:
            continue
        if states is None:
            states = _question_states(root)
            reserved = {i for i in entries.reserved_ids(root).get("Q", set())}
        open_ids: list[str] = []
        resolved = 0
        for number in numbers:
            status = states.get(f"Q{number}")
            if status is None:
                resolved += 1 if f"Q{number}" in reserved else 0  # gone but once assigned; else not ours
            elif status == "open" or status not in actlib.STATUS_VALUES:
                open_ids.append(f"Q{number}")
            else:
                resolved += 1
        if open_ids or not resolved:
            continue
        findings.append(Finding(
            path=_rel(path, root), line=None, kind="docs-concept-decided",
            message=("every question it names is answered or gone — once decided, move what the build "
                     "needs into its backlog item or task and the reason into a decision record, then "
                     "archive the concept with `entries.py archive <file>` (R-docs-order)"),
        ))
    return findings


DOCS_FILE_LONG_LINES = 300


def _check_docs_file_length(root: Path, project: Path, ignored: list[Path]) -> list[Finding]:
    """A Markdown file under docs/project/ of DOCS_FILE_LONG_LINES lines or more."""
    findings: list[Finding] = []
    for path in sorted(project.rglob("*.md")):
        if _is_ignored(path, ignored) or any(part.startswith(".") for part in path.relative_to(project).parts):
            continue
        text = _read_text(path)
        count = len(text.splitlines()) if text is not None else 0
        if count >= DOCS_FILE_LONG_LINES:
            findings.append(Finding(
                path=_rel(path, root), line=None, kind="docs-file-long",
                message=(f"{count} lines (about {DOCS_FILE_LONG_LINES} is the limit) — split it into a folder "
                         "with a README.md and parts (R-docs-order)"),
            ))
    return findings


def _check_docs_index_depth(root: Path, docs: Path) -> list[Finding]:
    """An index line of docs/README.md whose first path points below a subfolder of docs/: that file
    names folders and top-level files only."""
    readme = docs / "README.md"
    text = _read_text(readme) if readme.is_file() else None
    if text is None:
        return []
    findings: list[Finding] = []
    for number, line in _unfenced(text):
        token = _index_path(line)
        if token is None:
            continue
        if f"]({token}" in line:  # a link is read relative to docs/, the folder of this README
            relative = token
        elif token.startswith("docs/"):  # a path in backticks counts only when it starts with docs/
            relative = token[len("docs/"):]
        else:
            continue
        parts = [part for part in posixpath.normpath(relative).split("/") if part and part != "."]
        if not parts or parts[0] == ".." or parts[0] == "ai":  # outside docs/; docs/ai/ is the scaffold's own area
            continue
        if len(parts) >= 2:
            findings.append(Finding(
                path=_rel(readme, root), line=number, kind="docs-index-deep",
                message=(f"index line names {token}, below a subfolder of docs/ — docs/README.md names "
                         "folders and top-level files only; move the line to that folder's README.md (R-docs-order)"),
            ))
    return findings


def check_docs_order(root: Path) -> list[Finding]:
    """The kinds of R-docs-order; nothing while `docs-order` is off or docs/ is missing."""
    docs = root / "docs"
    if not docs.is_dir() or not docs_order_enabled(root):
        return []
    findings: list[Finding] = []
    project = docs / "project"
    ignored = _git_ignored(root)
    if project.is_dir():
        findings += _check_docs_indexes(root, project, ignored)
        findings += _check_docs_file_length(root, project, ignored)
    findings += _check_docs_index_depth(root, docs)
    findings += _check_docs_links(root, docs, ignored)
    if project.is_dir():
        findings += _check_decided_concepts(root, project)
    return findings


# ---------------------------------------------------------------------------
# 8c. Size of the always-loaded own rules — the "Own rules" sections of docs/ai/rules.md and
#     docs/project/coding_rules.md load at every start, so a long one costs in every session. One
#     warning above a budget (`own-rules-budget` in docs/ai/config.md, default 6000 characters,
#     `off` or `0` skips the check), never a block; with it up to five lines that read like history.
# ---------------------------------------------------------------------------

OWN_RULES_BUDGET_DEFAULT = 6000
OWN_RULES_TOKENS_PER_CHAR = 0.386
OWN_RULES_FILES = ("docs/ai/rules.md", "docs/project/coding_rules.md")
OWN_RULES_HISTORY_MAX = 5
_OWN_HISTORY_PATTERNS = (
    re.compile(r"\b20\d\d-\d\d-\d\d\b"),  # a date
    re.compile(r"\b(?:[BQTU]\d{1,5}|ADR-\d+)\b"),  # an entry or decision identifier
    re.compile(r"(?i)\b(?:früher|formerly|previously)\b.*\b(?:seit|since)\b"),  # "formerly ... since ..."
)


def own_rules_budget(root: Path) -> Optional[int]:
    """The budget in characters; None while the check is off. A missing, empty or unreadable value
    means the default."""
    value = actlib.read_config(root).get("own-rules-budget", "").strip().strip("`").strip().lower()
    if value == "off" or (re.fullmatch(r"\d+", value) and int(value) == 0):
        return None
    return int(value) if re.fullmatch(r"\d+", value) else OWN_RULES_BUDGET_DEFAULT


def _own_rules_section(path: Path) -> tuple[int, list[tuple[int, str]]]:
    """(line of the section's mark, [(line number, text)] of what the section holds after it): from
    the `<!-- act:own-rules -->` mark to the next `## ` heading or other mark, outside code fences.
    Found by the mark; only a file without it falls back to a heading named like the English one."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return 0, []
    start = None
    for number, raw in enumerate(lines):
        mark = rules.RE_SECTION_MARK.match(raw.strip())
        if mark and rules.MARK_TO_SECTION.get(mark.group("name").lower()) == "own-rules":
            start = number
            break
    if start is None:
        for number, raw in enumerate(lines):
            heading = rules.RE_TOP_HEADING.match(raw.rstrip())
            if heading and rules.HEADING_TO_SECTION_FALLBACK.get(heading.group("title").strip().lower()) == "own-rules":
                start = number
                break
    if start is None:
        return 0, []
    body: list[tuple[int, str]] = []
    fence: Optional[str] = None
    for number in range(start + 1, len(lines)):
        raw = lines[number]
        fence_match = RE_FENCE.match(raw.strip())
        if fence is None and fence_match:
            fence = fence_match.group(1)[0]
        elif fence is not None and fence_match and fence_match.group(1)[0] == fence:
            fence = None
        elif fence is None and (rules.RE_TOP_HEADING.match(raw.rstrip()) or rules.RE_SECTION_MARK.match(raw.strip())):
            break
        body.append((number + 1, raw))
    return start + 1, body


def check_own_rules_size(root: Path) -> list[Finding]:
    budget = own_rules_budget(root)
    if budget is None:
        return []
    sizes: dict[str, int] = {}
    history: list[tuple[int, int, str, int, str]] = []  # (-hits, order, file, line, text)
    for rel in OWN_RULES_FILES:
        path = root / rel
        if not path.is_file():
            continue
        _, body = _own_rules_section(path)
        if not body:
            continue
        # Claude Code drops block-level comments (on lines of their own) before the text reaches the
        # model, so they count neither towards the size nor as history lines.
        loaded: list[tuple[int, str, bool]] = []  # (line, text, inside a code fence)
        in_fence: Optional[str] = None
        in_comment = False
        for number, text in body:
            stripped = text.strip()
            fence_match = RE_FENCE.match(stripped)
            if not in_comment and fence_match:
                in_fence = None if in_fence else fence_match.group(1)
                loaded.append((number, text, True))
                continue
            if in_fence:
                loaded.append((number, text, True))
                continue
            if in_comment:
                in_comment = "-->" not in stripped
                continue
            if stripped.startswith("<!--"):
                in_comment = "-->" not in stripped[4:]
                continue
            loaded.append((number, text, False))
        sizes[rel] = len("\n".join(text for _, text, _ in loaded).strip())
        for number, text, fenced in loaded:
            if fenced:
                continue
            hits = sum(1 for pattern in _OWN_HISTORY_PATTERNS if pattern.search(text))
            if hits:
                history.append((-hits, len(history), rel, number, text.strip()))
    total = sum(sizes.values())
    if total <= budget:
        return []
    parts = ", ".join(f"{rel} {size:,}" for rel, size in sizes.items())
    findings = [Finding(
        path=max(sizes, key=lambda rel: sizes[rel]), line=None, kind="own-rules-size",
        message=(f"the always-loaded own rules are {total:,} characters (about {round(total * OWN_RULES_TOKENS_PER_CHAR):,} "
                 f"tokens) in every session, over the budget of {budget:,} ({parts}) — keep a one-line rule each, "
                 "move incident, evidence and identifiers into the project docs (table in the Own rules "
                 "section of .act/bridges/coding_rules.md); `own-rules-budget` in docs/ai/config.md raises the "
                 "limit, `off` skips the check"),
    )]
    chosen = sorted(history)[:OWN_RULES_HISTORY_MAX]
    for _, _, rel, number, text in sorted(chosen, key=lambda item: (item[2], item[3])):
        shown = text if len(text) <= 100 else text[:100] + "…"
        findings.append(Finding(path=rel, line=number, kind="own-rules-size",
                                message=f"reads like history (date, identifier or \"formerly … since\"): {shown}"))
    if len(history) > len(chosen):
        findings.append(Finding(path=findings[0].path, line=None, kind="own-rules-size",
                                message=f"{len(history) - len(chosen)} more line(s) like these"))
    return findings


# ---------------------------------------------------------------------------
# 8d. Length of the changelog entries — an entry under `## [Unreleased]` in CHANGELOG.md is read by
#     everyone who updates, so a long one costs. One warning when an entry is over 250 characters
#     (switch `changelog-length` in docs/ai/config.md: warn (default) | block (= warn) | off), never a
#     block. The template's own checkout has no docs/ai/config.md, so the defaults apply there.
# ---------------------------------------------------------------------------

CHANGELOG_ENTRY_MAX = 250
CHANGELOG_SHOWN_MAX = 5
CHANGELOG_WORDS_WIDTH = 40
RE_UNRELEASED = re.compile(r"^##\s+\[unreleased\]", re.IGNORECASE)


def _config_word(root: Path, key: str, default: str) -> str:
    value = actlib.read_config(root).get(key, "").strip().strip("`").strip().lower()
    return value or default


def changelog_entries(lines: list[str]) -> list[tuple[int, str]]:
    """[(line number, text)] of the list items under `## [Unreleased]`: an item runs from its `- `
    (or `* `, `+ `) line to the next item, a heading or a blank line; its continuation lines are
    stripped and joined with one space; the text is what follows the marker. Fenced code blocks are
    skipped."""
    start = None
    for number, line in enumerate(lines):
        if RE_UNRELEASED.match(line.strip()):
            start = number + 1
            break
    if start is None:
        return []
    found: list[tuple[int, str]] = []
    current: list[str] = []
    first = 0
    fence: Optional[str] = None
    for number in range(start, len(lines)):
        line = lines[number]
        stripped = line.strip()
        fence_match = RE_FENCE.match(stripped)
        if fence is None and fence_match:  # a code block is skipped and ends the entry before it
            fence = fence_match.group(1)[0]
            if current:
                found.append((first, " ".join(current)))
            current = []
            continue
        if fence is not None:
            if fence_match and fence_match.group(1)[0] == fence:
                fence = None
            continue
        if line.startswith("## "):
            break
        if line[:2] in ("- ", "* ", "+ "):
            if current:
                found.append((first, " ".join(current)))
            current, first = [line[2:].strip()], number + 1
        elif current and stripped and not stripped.startswith("#"):
            current.append(stripped)
        else:
            if current:
                found.append((first, " ".join(current)))
            current = []
    if current:
        found.append((first, " ".join(current)))
    return found


def _first_words(text: str) -> str:
    """The start of `text`, cut at a word boundary within about CHANGELOG_WORDS_WIDTH characters."""
    if len(text) <= CHANGELOG_WORDS_WIDTH:
        return text
    cut = text[:CHANGELOG_WORDS_WIDTH]
    if text[CHANGELOG_WORDS_WIDTH] != " " and " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip() + "…"


def check_changelog_length(root: Path) -> list[Finding]:
    if _config_word(root, "changelog-length", "warn") == "off":
        return []
    if _config_word(root, "changelog", "file") in ("off", "release-notes-only"):
        return []
    path = root / "CHANGELOG.md"
    if not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    long_ones = [(number, text) for number, text in changelog_entries(lines) if len(text) > CHANGELOG_ENTRY_MAX]
    if not long_ones:
        return []
    shown = "; ".join(f"line {number}, {len(text)} characters: {_first_words(text)}"
                      for number, text in long_ones[:CHANGELOG_SHOWN_MAX])
    more = len(long_ones) - CHANGELOG_SHOWN_MAX
    count = len(long_ones)
    return [Finding(
        path="CHANGELOG.md", line=long_ones[0][0], kind="changelog-length",
        message=(f"{count} entr{'y' if count == 1 else 'ies'} under [Unreleased] "
                 f"{'is' if count == 1 else 'are'} longer than {CHANGELOG_ENTRY_MAX} characters "
                 f"(a list item with its lines joined) — {shown}"
                 + (f"; {more} more" if more > 0 else "")
                 + ". Shorten them; `changelog-length` in docs/ai/config.md set to `off` skips the check"),
    )]


# ---------------------------------------------------------------------------
# 9. .act/MANIFEST.json drift — a project's .act/ hand-edited since the last update, or, in the
#    template's own checkout, .act/ changed without re-running `manifest.py --write` before
#    committing (the template ships its own MANIFEST.json now, so this same comparison
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


# ---------------------------------------------------------------------------
# 16. Tier proposals from recorded worker outcomes
# ---------------------------------------------------------------------------

# Thresholds are this check's own proposal, not a fixed standard: over the last 30 outcomes of a
# role/tier (the window; fewer outcomes, no proposal), 60% (18 of 30) or more reworked or
# escalated suggests raising the tier; older outcomes drop out of the window. It
# only ever writes a finding, or with --inbox an inbox question -- never docs/ai/config.md itself
# (a tier is never silently switched). There is no proposal in the other direction: accepted
# outcomes cannot show that a cheaper tier would have found the same, least of all for a
# reviewing role, so lowering a tier stays the owner's own idea.
_TIER_PROPOSAL_WINDOW = 30
_TIER_PROPOSAL_RAISE_RATIO = 0.6
# A proposal that was already filed is not filed again until at least this many further outcomes
# have been recorded for the same role/tier -- new material, not the same count after the owner
# decided to leave the tier as it is: a whole new window.
_TIER_PROPOSAL_RENEW_AFTER = _TIER_PROPOSAL_WINDOW
_TIER_MEMORY_FILE = Path(".act-local") / "tier-proposals.json"


def _tier_memory(root: Path) -> dict[str, tuple[int, str]]:
    """role|tier -> (number of outcomes, date YYYY-MM-DD) when that proposal was last filed (empty
    if there is no memory yet or it cannot be read -- then every proposal counts as new). The
    older form, a bare count, reads as filed on an unknown day ("")."""
    try:
        data = json.loads((root / _TIER_MEMORY_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    memory: dict[str, tuple[int, str]] = {}
    for key, value in data.items():
        if isinstance(value, int) and not isinstance(value, bool):
            memory[str(key)] = (value, "")
        elif (isinstance(value, dict) and isinstance(value.get("count"), int)
              and not isinstance(value["count"], bool)):
            filed = value.get("filed")
            memory[str(key)] = (value["count"], filed if isinstance(filed, str) else "")
    return memory


def _recent_window(store: dict, role: str, tier: str) -> list[str]:
    """The last outcomes recorded for role/tier, oldest first, at most _TIER_PROPOSAL_WINDOW of
    them. Empty when usage.json has no order for this role/tier (a file written before the order
    was kept): there is then no window and no proposal until new outcomes fill it."""
    recent = (store.get("roles", {}).get(role) or {}).get("recent")
    items = recent.get(tier) if isinstance(recent, dict) else None
    if not isinstance(items, list):
        return []
    return [item for item in items if item in ("accepted", "reworked", "escalated")][-_TIER_PROPOSAL_WINDOW:]


def _window_counts(store: dict, role: str, tier: str) -> tuple[int, int, int]:
    """(accepted, reworked, escalated) within the window of role/tier."""
    window = _recent_window(store, role, tier)
    return window.count("accepted"), window.count("reworked"), window.count("escalated")


def _tier_proposals(root: Path) -> list[tuple[str, int, Finding]]:
    """(role|tier key, outcomes counted in total, finding) for every role/tier whose window of
    the last _TIER_PROPOSAL_WINDOW outcomes is full and over the ratio, filed before or not."""
    try:
        import usage
    except ImportError:
        return []
    store = usage.consolidate(root)
    found: list[tuple[str, int, Finding]] = []
    for role in sorted(store.get("roles", {})):
        outcomes = store["roles"][role].get("outcomes") or {}
        for tier in sorted(outcomes):
            counts = outcomes[tier] if isinstance(outcomes[tier], dict) else {}
            overall = sum(counts.get(kind) if isinstance(counts.get(kind), int)
                          and not isinstance(counts.get(kind), bool) else 0
                          for kind in ("accepted", "reworked", "escalated"))
            window = _recent_window(store, role, tier)
            trouble = window.count("reworked") + window.count("escalated")
            tier_label = tier or "(no tier)"
            if (len(window) >= _TIER_PROPOSAL_WINDOW
                    and trouble / len(window) >= _TIER_PROPOSAL_RAISE_RATIO):
                found.append((f"{role}|{tier}", max(overall, len(window)), Finding(
                    path=".act-local/usage.json", line=None, kind="tier-proposal",
                    message=(f"role `{role}` at tier `{tier_label}`: {trouble} of the last {len(window)} "
                             "outcomes reworked or escalated -- consider a higher tier "
                             "(R-role-outcome)"),
                )))
    return found


def _new_tier_proposals(root: Path) -> list[tuple[str, int, Finding]]:
    """The proposals not filed yet, or filed when far fewer outcomes were recorded. Counts only
    grow, so fewer outcomes than remembered means usage.json was reset: the memory no longer
    applies and the proposal counts as new."""
    memory = _tier_memory(root)
    return [(key, total, finding) for key, total, finding in _tier_proposals(root)
            if key not in memory or total < memory[key][0]
            or total >= memory[key][0] + _TIER_PROPOSAL_RENEW_AFTER]


# The tiers a role moves up through, one step at a time. .act/tiers.json maps each name to a model
# per tool but does not order them (its "high" entry is a reasoning bump, not a step), so the
# order lives here.
_TIER_LADDER = ("light", "standard", "elevated", "expert")
# Columns of the table under <!-- act:roles --> in docs/ai/config.md (Role, Tier, Reasoning, Model).
_ROLES_TABLE_COLUMNS = 4


def _next_tier(tier: str) -> Optional[str]:
    """The tier one step above `tier`, or None for the top tier, an empty or an unknown one."""
    if tier not in _TIER_LADDER:
        return None
    index = _TIER_LADDER.index(tier) + 1
    return _TIER_LADDER[index] if index < len(_TIER_LADDER) else None


def _outcome_counts(store: dict, role: str, tier: str) -> tuple[int, int, int]:
    """(accepted, reworked, escalated) recorded for role/tier in usage.json's `store`."""
    outcomes = (store.get("roles", {}).get(role) or {}).get("outcomes") or {}
    counts = outcomes.get(tier) if isinstance(outcomes.get(tier), dict) else {}
    accepted, reworked, escalated = (
        counts.get(kind) if isinstance(counts.get(kind), int) and not isinstance(counts.get(kind), bool)
        else 0 for kind in ("accepted", "reworked", "escalated"))
    return accepted, reworked, escalated


def _related_roles(role: str, store: dict) -> list[str]:
    """`role` itself, then its counterpart that has recorded outcomes: the base role of an
    `<x>-high` variant, or the `<x>-high` variant of a base role."""
    other = role[:-len("-high")] if role.endswith("-high") else f"{role}-high"
    roles = [role]
    if other and other in store.get("roles", {}) and (store["roles"][other].get("outcomes") or {}):
        roles.append(other)
    return roles


def _tier_facts(store: dict, role: str, tier: str) -> dict:
    """The numbers of one tier proposal, from `store` (usage.json) and this check's threshold
    constants, never from fixed text."""
    accepted, reworked, escalated = _window_counts(store, role, tier)
    trouble = reworked + escalated
    return {"trouble": trouble, "window_size": accepted + trouble,
            "total": sum(_outcome_counts(store, role, tier)),
            "percent": round(_TIER_PROPOSAL_RAISE_RATIO * 100), "nxt": _next_tier(tier)}


def _config_role(role: str) -> str:
    # A generated `<x>-high` variant has no row of its own in § Roles: it runs at its base role's
    # tier, one reasoning step further (init.py), so only the base role's row raises it.
    return role[:-len("-high")] if role.endswith("-high") else role


def tier_report_text(store: dict, role: str, tier: str, language: str) -> tuple[str, str]:
    """(title, body) of the inbox report that carries the numbers of the tier proposal for `role`
    at `tier`: the finding, the table, what applying it means. The question names this report."""
    def loc(en: str, de: str) -> str:
        return actlib.localized(language, en, de)

    facts = _tier_facts(store, role, tier)
    trouble, window_size, total = facts["trouble"], facts["window_size"], facts["total"]
    percent, nxt = facts["percent"], facts["nxt"]
    no_tier = loc("(no tier)", "(ohne Stufe)")
    title = loc(f"Tier proposal numbers: {role}", f"Zahlen zum Stufenvorschlag: {role}")
    at_tier = loc(f"at tier `{tier}`", f"auf der Stufe `{tier}`") if tier else loc("with no tier", "ohne Stufe")
    rows = [loc("| Role | Tier | accepted | reworked | escalated | reworked or escalated, since the start "
                f"| reworked or escalated, last {_TIER_PROPOSAL_WINDOW} |",
                "| Rolle | Stufe | angenommen | nachgearbeitet | eskaliert | nachgearbeitet oder eskaliert, "
                f"seit Beginn | nachgearbeitet oder eskaliert, letzte {_TIER_PROPOSAL_WINDOW} |"),
            "| :--- | :--- | ---: | ---: | ---: | ---: | ---: |"]
    def ladder_order(tier_name: str) -> tuple[int, str]:
        rank = _TIER_LADDER.index(tier_name) if tier_name in _TIER_LADDER else len(_TIER_LADDER)
        return rank, tier_name

    for name in _related_roles(role, store):
        for tier_name in sorted(store["roles"][name].get("outcomes") or {}, key=ladder_order):
            a, r, e = _outcome_counts(store, name, tier_name)
            tier_cell = f"`{tier_name}`" if tier_name else no_tier
            wa, wr, we = _window_counts(store, name, tier_name)
            rows.append(f"| `{name}` | {tier_cell} | {a} | {r} | {e} | {r + e}/{a + r + e} | "
                        f"{wr + we}/{wa + wr + we} |")
    empty_cells = " |" * (_ROLES_TABLE_COLUMNS - 2)
    config_role = _config_role(role)
    next_numbers = ""
    if nxt:
        na, nr, ne = _outcome_counts(store, role, nxt)
        if na + nr + ne:
            next_numbers = " " + loc(
                f"On `{nxt}`, `{role}` has {na + nr + ne} outcomes, {nr + ne} of them reworked or escalated.",
                f"Auf `{nxt}` hat `{role}` {na + nr + ne} Ergebnisse, davon {nr + ne} nachgearbeitet oder eskaliert.")
        applied = loc(f"Applied, that is a row in `docs/ai/config.md` § Roles: `| {config_role} | {nxt} |{empty_cells}`.",
                      f"Umgesetzt wäre das diese Zeile in `docs/ai/config.md` § Rollen: "
                      f"`| {config_role} | {nxt} |{empty_cells}`.")
    else:
        applied = loc(f"Applied, that means setting a higher tier for `{config_role}` in `docs/ai/config.md` § Roles.",
                      f"Umgesetzt hieße das, eine höhere Stufe für `{config_role}` in `docs/ai/config.md` § Rollen "
                      "zu setzen.")
    if config_role != role:
        applied += " " + loc(
            f"`{role}` has no row of its own: it runs at the tier of `{config_role}`, so the row raises both.",
            f"`{role}` hat keine eigene Zeile: Die Rolle läuft auf der Stufe von `{config_role}`, die Zeile hebt "
            "also beide an.")
        if nxt == _TIER_LADDER[-1]:
            applied += " " + loc(
                f"On `{nxt}` there is no `{role}` any more; `{config_role}` takes its work.",
                f"Auf `{nxt}` entfällt `{role}`, `{config_role}` übernimmt seine Arbeit.")
    applied += " " + loc(f"Every run of `{config_role}` gets more expensive.",
                         f"Jeder Lauf von `{config_role}` wird damit teurer.")
    lines = [
        loc(f"**Finding (`R-role-outcome`):** Role `{role}` has {total} outcomes {at_tier}; of the last "
            f"{window_size}, {trouble} were reworked or escalated. Once {_TIER_PROPOSAL_WINDOW} outcomes are "
            f"recorded, the doctor proposes a higher tier when at least {percent}% of the last "
            f"{_TIER_PROPOSAL_WINDOW} were reworked or escalated; older outcomes drop out. The numbers from "
            "`.act-local/usage.json`:",
            f"**Befund (`R-role-outcome`):** Die Rolle `{role}` hat {at_tier} {total} Ergebnisse; von den "
            f"letzten {window_size} wurden {trouble} nachgearbeitet oder eskaliert. Sind {_TIER_PROPOSAL_WINDOW} "
            f"Ergebnisse erfasst, schlägt der Doctor eine höhere Stufe vor, wenn mindestens {percent} % der "
            f"letzten {_TIER_PROPOSAL_WINDOW} nachgearbeitet oder eskaliert wurden; ältere fallen heraus. "
            "Die Zahlen aus `.act-local/usage.json`:"),
        "", *rows, "",
        loc("The numbers do not show what caused the rework: an unclear assignment or a model that is too weak.",
            "Die Zahlen zeigen nicht, woran die Nacharbeit lag: an einem unklaren Auftrag oder an einem zu schwachen Modell.")
        + next_numbers,
        "", applied,
    ]
    return title, "\n".join(lines) + "\n"


def tier_question_text(store: dict, role: str, tier: str, language: str, report_name: str) -> tuple[str, str]:
    """(title, body) of the inbox question for the proposal to raise `role` at `tier`. The hint is
    two sentences and names the report `report_name`, which holds the numbers (tier_report_text).
    The recommended option comes first, as a), opening with the bold label."""
    def loc(en: str, de: str) -> str:
        return actlib.localized(language, en, de)

    facts = _tier_facts(store, role, tier)
    trouble, window_size, percent, nxt = facts["trouble"], facts["window_size"], facts["percent"], facts["nxt"]
    total = facts["total"]
    empty_cells = " |" * (_ROLES_TABLE_COLUMNS - 2)
    config_role = _config_role(role)
    title = loc(f"{role}: {trouble} of the last {window_size} outcomes reworked or escalated - raise the tier?",
                f"{role}: {trouble} der letzten {window_size} Ergebnisse nachgearbeitet oder eskaliert - "
                "Stufe anheben?")
    if nxt:
        raise_tier = loc(f"Raise the tier: put the row `| {config_role} | {nxt} |{empty_cells}` into "
                         "`docs/ai/config.md` § Roles.",
                         f"Stufe anheben: die Zeile `| {config_role} | {nxt} |{empty_cells}` in "
                         "`docs/ai/config.md` § Rollen eintragen.")
    else:
        raise_tier = loc(f"Raise the tier: set a higher tier for `{config_role}` in `docs/ai/config.md` § Roles.",
                         f"Stufe anheben: eine höhere Stufe für `{config_role}` in `docs/ai/config.md` § Rollen "
                         "setzen.")
    renew_at = total + _TIER_PROPOSAL_RENEW_AFTER
    hint = loc(f"`{role}` had {trouble} of its last {window_size} outcomes reworked or escalated "
               f"(`R-role-outcome`; a proposal starts at {percent}% of the last {_TIER_PROPOSAL_WINDOW}). "
               f"The numbers, the table and what a higher tier costs are in the report `{report_name}` in this inbox.",
               f"`{role}` hatte {trouble} der letzten {window_size} Ergebnisse nachgearbeitet oder eskaliert "
               f"(`R-role-outcome`; ein Vorschlag beginnt bei {percent} % der letzten {_TIER_PROPOSAL_WINDOW}). "
               f"Die Zahlen, die Tabelle und was eine höhere Stufe kostet, stehen im Bericht `{report_name}` "
               "in diesem Eingang.")
    lines = [
        hint, "",
        "- **a)** " + loc("**Recommended:** Look at the cases first: check the journal and transcripts of the reworked "
                          "and escalated runs for the cause, then decide. Effort: about 15 minutes of reading. The "
                          "numbers alone do not show whether a higher tier helps.",
                          "**Empfehlung:** Erst die Fälle ansehen: Journal und Transkripte der nachgearbeiteten und "
                          "eskalierten Läufe auf die Ursache prüfen, dann entscheiden. Aufwand: etwa 15 Minuten "
                          "Lesen. Die Zahlen allein zeigen nicht, ob eine höhere Stufe hilft."),
        "",
        f"- **b)** {raise_tier} " + loc("Effort: one table row, a minute.", "Aufwand: eine Tabellenzeile, eine Minute."),
        "",
        "- **c)** " + loc(f"Leave it. The proposal comes back after {_TIER_PROPOSAL_RENEW_AFTER} more outcomes, at "
                          f"{renew_at}, if at least {percent}% of the then last {_TIER_PROPOSAL_WINDOW} are reworked "
                          "or escalated. Effort: none.",
                          f"So lassen. Der Vorschlag kommt nach {_TIER_PROPOSAL_RENEW_AFTER} weiteren Ergebnissen wieder, "
                          f"also bei {renew_at}, wenn dann noch mindestens {percent} % der letzten "
                          f"{_TIER_PROPOSAL_WINDOW} nachgearbeitet oder eskaliert sind. Aufwand: keiner."),
        "",
    ]
    return title, "\n".join(lines) + "\n"


def file_tier_questions(root: Path) -> list[Path]:
    """Write one inbox question (kind: question, answer line last) for every proposal not filed
    yet, each preceded by an inbox report (kind: report) with its numbers that the question names,
    note the outcome count of each one actually written, and return the files (report, then question). A proposal
    whose question is written never comes back until _TIER_PROPOSAL_RENEW_AFTER more outcomes are
    recorded, however many reports are written or archived meanwhile. Each question is noted right
    after it is written. Best effort: a question that cannot be written is skipped with a warning
    and returns with the next run; a memory that cannot be written is warned about, since the same
    question would then be filed again with every run."""
    new = _new_tier_proposals(root)
    if not new:
        return []
    try:
        import usage
    except ImportError:
        return []
    store = usage.consolidate(root)
    language = actlib.docs_language(root)
    written: list[Path] = []
    for key, total, _ in new:
        role, _, tier = key.partition("|")
        report_title, report_body = tier_report_text(store, role, tier, language)
        report_path: Optional[Path] = None
        try:
            # The report first: the question names it, and without it the numbers would be lost.
            report_path, _ = entries.create_entry(
                root, "report", report_title, recipient="all", body=report_body,
                slug=f"tier-numbers-{role}-{tier or 'none'}")
            title, body = tier_question_text(store, role, tier, language, report_path.name)
            path, _ = entries.create_entry(root, "question", title, body=body, answer_block=True)
        except (OSError, ValueError) as exc:
            if report_path is not None:  # no orphan report, and no second one with the next run
                report_path.unlink(missing_ok=True)
            print(f"doctor.py: tier proposal {key!r} not filed as a question: {exc}", file=sys.stderr)
            continue
        written += [report_path, path]
        if not remember_tier_proposals(root, {key: total}):
            print(f"doctor.py: could not write {_TIER_MEMORY_FILE.as_posix()} -- the question for {key!r} "
                  "will be filed again with the next run", file=sys.stderr)
    return written


def remember_tier_proposals(root: Path, filed: dict[str, int]) -> bool:
    """Note the outcome count of each proposal whose question was written (key -> count), so the
    same proposal does not come back with each run until new outcomes have piled up. An unreadable
    memory is replaced by one holding `filed`. Returns False if the memory cannot be written."""
    if not filed:
        return True
    memory = _tier_memory(root)
    today = date.today().isoformat()
    memory.update({key: (total, today) for key, total in filed.items()})
    path = root / _TIER_MEMORY_FILE
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {key: {"count": count, "filed": filed_on} for key, (count, filed_on) in memory.items()}
        path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


# --- Worker refusals ------------------------------------------------------------------------------
# The dispatcher counts every refusal of a check silently (usage.py record_refusal). When the same check refused
# workers at least _REFUSAL_THRESHOLD times within _REFUSAL_WINDOW_DAYS days, --inbox files one question. The
# proposal in it never loosens the check: it is one sentence for the worker's role file or the assignment header
# that tells the worker beforehand what the check does not allow (the sentences are listed in
# .act/rules/topics/checks.md, "Refusals counted"). Not filed again while a question about the check is open, nor
# within _REFUSAL_WINDOW_DAYS days of the last one; a count is only identifiers, no command, no path.
_REFUSAL_WINDOW_DAYS = 7
_REFUSAL_THRESHOLD = 3
_REFUSAL_MEMORY_FILE = Path(".act-local") / "refusal-proposals.json"
_WORKER_LINE_RE = re.compile(r"^- `([a-z_]+)`: (.+)$")


def _worker_lines(root: Path) -> dict[str, str]:
    """check module name -> the one sentence a worker is told beforehand, from topics/checks.md."""
    try:
        text = (root / ".act" / "rules" / "topics" / "checks.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    start = text.find("The sentences are these")
    lines: dict[str, str] = {}
    for line in (text[start:].splitlines()[1:] if start >= 0 else []):
        match = _WORKER_LINE_RE.match(line)
        if match:
            lines[match.group(1)] = match.group(2).strip()
        elif line.strip() and not line.startswith("- "):
            break
    return lines


def _refusal_memory(root: Path) -> dict[str, str]:
    """check -> date (YYYY-MM-DD) its question was last filed; empty when there is none or it cannot be read."""
    try:
        data = json.loads((root / _REFUSAL_MEMORY_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(key): value for key, value in data.items() if isinstance(value, str)} if isinstance(data, dict) else {}


def _refusal_question_open(root: Path, check: str) -> bool:
    inbox = root / actlib.INBOX_DIR
    slug = entries._slugify(f"worker-refusals-{check}")
    for path in inbox.glob(f"*-{slug}.md") if inbox.is_dir() else []:
        try:
            if re.search(r"^status:\s*open\b", path.read_text(encoding="utf-8"), re.MULTILINE):
                return True
        except (OSError, UnicodeDecodeError):
            continue
    return False


def _new_refusal_proposals(root: Path) -> list[tuple[str, dict[str, int]]]:
    """(check, {worker role: refusals}) for each check that refused workers at least _REFUSAL_THRESHOLD times in
    the window and has no open question and none filed within the window. The main session's refusals are not
    counted: they are the human's own work."""
    try:
        import usage
        counts = usage.refusal_counts(root, _REFUSAL_WINDOW_DAYS)
    except Exception:  # noqa: BLE001 -- no counts, no question
        return []
    memory = _refusal_memory(root)
    first_again = date.today().toordinal() - _REFUSAL_WINDOW_DAYS
    found: list[tuple[str, dict[str, int]]] = []
    for check in sorted(counts):
        workers = {role: number for role, number in counts[check].items() if role != "main"}
        if sum(workers.values()) < _REFUSAL_THRESHOLD or _refusal_question_open(root, check):
            continue
        try:
            if date.fromisoformat(memory.get(check, "")).toordinal() > first_again:
                continue
        except ValueError:
            pass
        found.append((check, workers))
    return found


def refusal_question_text(check: str, workers: dict[str, int], line: str, language: str) -> tuple[str, str]:
    """(title, body) of the question for a check that refused workers often. The first option, the
    recommended one, adopts `line`; no option changes the check."""
    def loc(en: str, de: str) -> str:
        return actlib.localized(language, en, de)

    total = sum(workers.values())
    split = ", ".join(f"`{role}` {number}" for role, number in sorted(workers.items(), key=lambda item: (-item[1], item[0])))
    top = sorted(workers.items(), key=lambda item: (-item[1], item[0]))[0][0]
    title = loc(f"`{check}` refused workers {total} times in {_REFUSAL_WINDOW_DAYS} days: tell them beforehand?",
                f"`{check}` hat Worker in {_REFUSAL_WINDOW_DAYS} Tagen {total}-mal gesperrt: ihnen vorher sagen, was nicht geht?")
    hint = loc(f"The check `{check}` refused workers {total} times in the last {_REFUSAL_WINDOW_DAYS} days ({split}); only "
               "the counts are kept, no command and no path. A refusal shows that the check works, so the check stays as "
               "it is. The proposal is to tell the worker beforehand what the check does not allow, so it does not run "
               "into it.",
               f"Die Prüfung `{check}` hat in den letzten {_REFUSAL_WINDOW_DAYS} Tagen Worker {total}-mal gesperrt "
               f"({split}); gezählt wird nur, nie ein Befehl oder Pfad. Eine Sperre zeigt, dass die Prüfung greift, "
               "sie bleibt also, wie sie ist. Vorgeschlagen ist, dem Worker vorher zu sagen, was die Prüfung nicht "
               "erlaubt, damit er gar nicht erst in die Sperre läuft.")
    if top == "worker":  # no role name is known, so there is no role file to name
        where_en = "into the text of the assignment header (the brief)"
        where_de = "in den Text des Auftragskopfs (die Beauftragung) aufnehmen"
    else:
        where_en = (f"into the role file of `{top}` (a project version under `docs/ai/local/agents/{top}.md`) "
                    "or into the text of the assignment header")
        where_de = (f"in die Rollendatei von `{top}` (Projektfassung unter `docs/ai/local/agents/{top}.md`) "
                    "oder in den Text des Auftragskopfs aufnehmen")
    lines = [
        hint, "",
        "- **a)** " + loc(f"**Recommended:** Adopt: put this sentence {where_en}: \"{line}\" "
                          "Effort: one line, a few minutes.",
                          f"**Empfehlung:** Übernehmen: diesen Satz {where_de}: \"{line}\" "
                          "Aufwand: eine Zeile, ein paar Minuten."),
        "",
        "- **b)** " + loc("Reword: say in the answer how the sentence should read or where it belongs. Effort: one "
                          "sentence from you.",
                          "Anders formulieren: in der Antwort sagen, wie der Satz lauten soll oder wo er hingehört. "
                          "Aufwand: ein Satz von dir."),
        "",
        "- **c)** " + loc(f"Do nothing. The check stays unchanged; a new question about `{check}` comes at the earliest "
                          f"{_REFUSAL_WINDOW_DAYS} days after this one, if it keeps refusing workers. Effort: none.",
                          f"Nichts tun. Die Prüfung bleibt unverändert; eine neue Frage zu `{check}` kommt frühestens "
                          f"{_REFUSAL_WINDOW_DAYS} Tage nach dieser, wenn sie weiter Worker sperrt. Aufwand: keiner."),
        "",
    ]
    return title, "\n".join(lines) + "\n"


def file_refusal_questions(root: Path) -> list[Path]:
    """Write one inbox question for every check that refused workers often (see above) and note the day. Best
    effort: a question that cannot be written is skipped with a warning and returns with the next run."""
    new = _new_refusal_proposals(root)
    if not new:
        return []
    language = actlib.docs_language(root)
    lines = _worker_lines(root)
    written: list[Path] = []
    for check, workers in new:
        line = lines.get(check) or (f"Before a call that `{check}` may refuse, read what it allows in "
                                    "`.act/rules/topics/checks.md`; a refusal is not retried another way.")
        title, body = refusal_question_text(check, workers, line, language)
        try:
            path, _ = entries.create_entry(root, "question", title, body=body, answer_block=True,
                                           slug=f"worker-refusals-{check}")
        except (OSError, ValueError) as exc:
            print(f"doctor.py: refusal question for {check!r} not filed: {exc}", file=sys.stderr)
            continue
        written.append(path)
        memory = _refusal_memory(root)
        memory[check] = date.today().isoformat()
        try:
            (root / _REFUSAL_MEMORY_FILE).parent.mkdir(parents=True, exist_ok=True)
            actlib.write_text_atomic(root / _REFUSAL_MEMORY_FILE, json.dumps(memory, indent=2, sort_keys=True) + "\n")
        except OSError:
            print(f"doctor.py: could not write {_REFUSAL_MEMORY_FILE.as_posix()}", file=sys.stderr)
    return written


def check_tier_proposal(root: Path) -> list[Finding]:
    """Reads .act-local/usage.json's per-role/tier outcome counts (usage.py --outcome, recorded by
    the orchestrator per R-role-outcome after every worker acceptance/rework/escalation) and
    proposes raising a role's tier once its outcomes cross the threshold above.
    A proposal only, surfaced as a finding -- deciding and editing docs/ai/config.md stays with the
    human/orchestrator. With --inbox the proposal becomes an inbox question (file_tier_questions)
    instead of a line in the report; one already filed stays quiet until new outcomes have piled
    up. Silent if usage.py cannot be imported or the store is empty."""
    return [finding for _, _, finding in _new_tier_proposals(root)]


def _git_out(root: Path, *args: str) -> Optional[str]:
    """Stdout of a read-only git call in `root`, or None if it fails (no repo, no git, timeout)."""
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def check_template_remote(root: Path) -> list[Finding]:
    """A remote that points at the template repository while the current branch has no upstream:
    a bare `git push`/`git pull` (also from an IDE) then falls back to that remote. Only a derived
    project is checked (it has .act-lock.json); the template checkout itself legitimately has the
    template as its origin. A finding only, never a change to the repository."""
    if not (root / ".act-lock.json").is_file():
        return []
    branch = (_git_out(root, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    if not branch or branch == "HEAD":
        return []
    # The configured upstream (`branch.<name>.remote`), not a resolvable remote-tracking ref: one
    # set with `git push -u` counts even before the first fetch.
    if (_git_out(root, "config", "--get", f"branch.{branch}.remote") or "").strip():
        return []
    try:
        lock = json.loads((root / ".act-lock.json").read_text(encoding="utf-8"))
        locked = str((lock.get("template") or {}).get("source") or "").strip()
    except (OSError, ValueError, AttributeError):
        locked = ""
    findings: list[Finding] = []
    for name in (_git_out(root, "remote") or "").split():
        url = (_git_out(root, "remote", "get-url", name) or "").strip()
        if url and actlib.is_template_repo_url(url, locked):
            findings.append(Finding(
                path=".git/config", line=None, kind="template-remote",
                message=(f"remote `{name}` points at the template repository ({url}) and branch "
                         f"`{branch}` has no upstream: `git push`/`git pull` without a target goes there. "
                         f"Remove it with `git remote remove {name}` (updates use the source in "
                         ".act-lock.json), or set the project's own remote as upstream."),
            ))
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


def check_skill_lint(root: Path) -> list[Finding]:
    # A project can only fix its own skills (marker "own"/"overridden"); the template's skills
    # arrive with an update, so they are linted only in the template's own checkout (no
    # .act-lock.json there, same test as check_script_docs()). Reported only, never fixed. A
    # project's own skills get the language-neutral checks only: they may be written in the
    # project's language and may be tiny, so the English trigger-first and step checks would be noise.
    in_project = (root / ".act-lock.json").is_file()
    findings: list[Finding] = []
    for skill, found in skills.lint(root, language_neutral=in_project):
        if in_project and not skill.marker:
            continue
        findings.append(Finding(path=_rel(skill.path, root), line=None, kind="skill-lint",
                                message=f"{found.level.lower()}: {found.message}"))
    return findings


# ---------------------------------------------------------------------------
# Frontmatter of skills and roles
# ---------------------------------------------------------------------------

# Fields a skill's frontmatter may carry: what Claude Code reads plus what the other tools the
# bridges feed (Agent Skills standard: license, compatibility, metadata) read. Anything else is
# reported as `frontmatter-unknown` — a newer tool may know a field this list does not.
_SKILL_FIELDS = frozenset({
    "name", "description", "disable-model-invocation", "user-invocable", "allowed-tools", "model",
    "effort", "context", "agent", "hooks", "argument-hint", "when_to_use", "paths", "shell",
    "metadata", "license", "compatibility", "version",
})
# The template's role fields (name, description, tier, reasoning, high-variant, tools), the ones tiers.py
# generates (model, effort, variant-of) and the ones Claude Code adds on top.
_ROLE_FIELDS = frozenset({
    "name", "description", "tier", "reasoning", "high-variant", "tools", "model", "effort", "variant-of",
    "permissionMode", "hooks", "mcpServers", "color", "disallowedTools", "skills", "memory",
    "maxTurns", "background", "isolation", "initialPrompt", "omitClaudeMd",
})
_KNOWN_TOOL_NAMES = frozenset({
    "Read", "Write", "Edit", "MultiEdit", "Bash", "Grep", "Glob", "WebFetch", "WebSearch",
    "NotebookEdit", "NotebookRead", "TodoWrite", "Task", "Agent", "BashOutput", "KillShell",
    "SlashCommand", "Skill", "ExitPlanMode", "EnterPlanMode", "LS", "AskUserQuestion", "Monitor",
    "TaskOutput", "TaskStop", "TaskCreate", "TaskGet", "TaskList", "TaskUpdate", "SendMessage",
    "LSP", "ToolSearch", "PowerShell", "ListMcpResourcesTool", "ReadMcpResourceTool",
    "CronCreate", "CronDelete", "CronList", "EnterWorktree", "ExitWorktree", "SendUserFile",
})
_KNOWN_TOOL_BY_LOWER = {name.lower(): name for name in _KNOWN_TOOL_NAMES}
# A block scalar header: `|` or `>` with an optional indentation digit and chomping sign, either order.
_BLOCK_HEADER_RE = re.compile(r"^[|>](?:[1-9][+-]?|[+-][1-9]?)?(?:\s+#.*)?$")
_PLAIN_START_BAD = "&*!%@`"  # a plain scalar cannot start with these (quotes are handled apart)
_MODEL_VALUE_RE = re.compile(r"^[A-Za-z0-9._:\[\]=-]+$")
_FIELD_LINE_RE = re.compile(r"^(?P<key>[^\s#][^:]*?)\s*:(?:\s+(?P<value>.*?))?\s*$")


def _frontmatter_span(lines: list[str]) -> Optional[tuple[int, int]]:
    """(index of the opening '---', index of the closing '---') or None without a block."""
    start = 0
    while start < len(lines) and lines[start].strip() == "":
        start += 1
    if start >= len(lines) or lines[start].strip() != "---":
        return None
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == "---":
            return start, i
    return None


def _plain_value_problem(value: str) -> Optional[str]:
    """Why `value` — the right-hand side of a top-level frontmatter line — is not valid YAML or
    does not mean what it reads like; None when it is fine. Mirrors frontmatter.quote_value()."""
    if value == "":
        return None
    if value[0] in "|>":
        if _BLOCK_HEADER_RE.match(value):
            return None
        return f"block scalar indicator {value[0]!r} followed by text on the same line — start the text on the next line"
    if value[0] == '"':
        body = re.sub(r"\\.", "", value[1:])
        if not body.endswith('"') or '"' in body[:-1]:
            return 'double-quoted value with an unescaped " inside or no closing quote'
        return None
    if value[0] == "'":
        body = value[1:].replace("''", "")
        if not body.endswith("'") or "'" in body[:-1]:
            return "single-quoted value with an unescaped ' inside or no closing quote"
        return None
    if value[0] in "[{":
        return None  # a flow list/map (`tools: [Read, Grep]`), valid YAML
    if ": " in value or value.endswith(":"):
        return "unquoted value contains ': ' (YAML reads a nested mapping) — put the value in quotes"
    if " #" in value:
        return "unquoted value contains ' #' (YAML treats the rest as a comment) — put the value in quotes"
    if value[0] in _PLAIN_START_BAD:
        return f"unquoted value starts with {value[0]!r}, which YAML reserves — put the value in quotes"
    if value.startswith(("- ", "? ")):
        return f"unquoted value starts with {value[:2]!r}, a YAML list/key marker — put the value in quotes"
    return None


def _frontmatter_yaml_problems(lines: list[str], start: int, close: int) -> list[tuple[int, str]]:
    """(line number, problem) for each top-level line between the fences that a strict YAML parser
    would reject or read differently. Hand-rolled on purpose (stdlib only): the lenient reader in
    frontmatter.py takes 'key: a: b' as the value 'a: b', which is how such a head went unnoticed."""
    problems: list[tuple[int, str]] = []
    plain_open = False  # the last top-level key holds a plain (unquoted) scalar that may continue
    skip_until = -1  # lines up to here belong to a multi-line quoted value already checked
    for i in range(start + 1, close):
        raw = lines[i]
        if i <= skip_until or raw.strip() == "":
            continue
        if raw[:1] in (" ", "\t"):
            text = raw.strip()
            if plain_open and not text.startswith("#") and (": " in text or text.endswith(":")):
                problems.append((i + 1, "continuation line of a plain value contains ': '"))
            continue
        if raw.lstrip().startswith("#"):
            continue
        plain_open = False
        match = _FIELD_LINE_RE.match(raw)
        if not match:
            problems.append((i + 1, f"line is not 'key: value' ({raw.strip()[:40]!r})"))
            continue
        value = (match.group("value") or "").strip()
        plain_open = bool(value) and value[0] not in "\"'[{|>"
        problem = _plain_value_problem(value)
        if problem and value[0] in "\"'":
            # a quoted scalar may span several lines: try again with the following lines joined on
            joined, last = value, i
            while problem and last + 1 < close:
                last += 1
                joined += " " + lines[last].strip()
                problem = _plain_value_problem(joined)
            if not problem:
                skip_until = last
                continue
            problem = _plain_value_problem(value)
        if problem:
            problems.append((i + 1, f"{match.group('key')}: {problem}"))
    return problems


def _valid_role_values(root: Path) -> tuple[set[str], set[str], set[str]]:
    """(tiers, reasoning levels, claude-code model aliases) read from .act/tiers.json — never a
    list of its own. Empty sets when the file is missing or unreadable (then nothing is checked)."""
    data = tiers.load_tiers(root)
    tier_set: set[str] = set()
    reasoning_set: set[str] = set()
    models: set[str] = set()
    for tool, entry in data.items():
        if not isinstance(entry, dict):
            continue
        table = entry.get("tiers") or {}
        tier_set.update(table)
        reasoning_set.update(entry.get("reasoning_scale") or [])
        if tool == "claude-code":
            models.update(v.get("model", "") for v in table.values() if isinstance(v, dict))
    models.discard("")
    return tier_set, reasoning_set, models


def _tool_name_list(value: str) -> list[str]:
    """The bare tool names of a `tools` value: a comma list, a flow list, or a "- Name" list the
    lenient reader joins with " - ". Split only outside parentheses, so `Bash(git log:*, git diff:*)`
    and `Bash(npm run test - x)` stay one entry; the argument part is dropped."""
    text = value.strip().strip("[]")
    parts: list[str] = []
    depth, current = 0, ""
    for i, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        if depth == 0 and (char == "," or (
                char == "-" and (i == 0 or text[i - 1].isspace()) and text[i + 1:i + 2].isspace())):
            parts.append(current)
            current = ""
            continue
        current += char
    parts.append(current)
    return [p.split("(", 1)[0].strip("\"' \t") for p in parts if p.strip()]


def check_frontmatter(root: Path) -> list[Finding]:
    """19. The frontmatter of every skill (.act/skills/*, docs/ai/local/skills/*) and role
    (.act/bridges/agents/*, docs/ai/local/agents/*, generated .claude/agents/*): strict-YAML
    validity of each line, required `name`/`description`, `name` equal to its folder or file name,
    the values of `tier`/`reasoning`/`tools` and `model`/`effort`, and a hint for each field no
    known tool reads. In a project only its own skills and roles (docs/ai/local/) and the generated
    .claude/agents/ are checked, as in check_skill_lint(). Only stdlib: strict YAML is approximated line by line, see
    _plain_value_problem()."""
    tier_set, reasoning_set, models = _valid_role_values(root)
    findings: list[Finding] = []

    in_project = (root / ".act-lock.json").is_file()  # the template's own files are checked only in its checkout
    units: list[tuple[Path, str, str]] = []  # (file, "skill" or "role", expected name)
    skill_bases = [root / "docs" / "ai" / "local" / "skills"]
    role_bases = [root / "docs" / "ai" / "local" / "agents", root / ".claude" / "agents"]
    if not in_project:
        skill_bases.insert(0, root / ".act" / "skills")
        role_bases.insert(0, root / ".act" / "bridges" / "agents")
    for base in skill_bases:
        if base.is_dir():
            for folder in sorted(p for p in base.iterdir() if p.is_dir()):
                if (folder / "SKILL.md").is_file():
                    units.append((folder / "SKILL.md", "skill", folder.name))
    for base in role_bases:
        if base.is_dir():
            for path in sorted(base.glob("*.md")):
                if path.name.lower() != "readme.md":
                    units.append((path, "role", path.stem))

    for path, unit_kind, expected_name in units:
        rel = _rel(path, root)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        lines = text.lstrip("﻿").splitlines()
        span = _frontmatter_span(lines)

        def add(kind: str, message: str, line: Optional[int] = None) -> None:
            findings.append(Finding(path=rel, line=line, kind=kind, message=message))

        if span is None:
            add("frontmatter-field", f"no frontmatter block; a {unit_kind} needs `name` and `description`")
            continue
        for number, problem in _frontmatter_yaml_problems(lines, *span):
            add("frontmatter-yaml", problem, number)
        parsed = frontmatter.parse_frontmatter(text)
        if not parsed.ok:
            add("frontmatter-yaml", f"frontmatter cannot be read: {parsed.error}")
            continue
        fields = parsed.fields
        for required in ("name", "description"):
            if not fields.get(required, "").strip():
                add("frontmatter-field", f"required field `{required}` is missing or empty")
        name = fields.get("name", "").strip()
        if name and name != expected_name:
            where = "folder" if unit_kind == "skill" else "file"
            add("frontmatter-field", f"`name: {name}` differs from its {where} name `{expected_name}`")

        unknown_tools: list[str] = []
        if unit_kind == "role":
            tier = fields.get("tier", "").strip()
            if tier and tier_set and tier not in tier_set:
                add("frontmatter-field", f"`tier: {tier}` is none of {', '.join(sorted(tier_set))} (.act/tiers.json)")
            level = fields.get("reasoning", "").strip()
            if level and reasoning_set and level not in reasoning_set:
                add("frontmatter-field", f"`reasoning: {level}` is none of {', '.join(sorted(reasoning_set))} (.act/tiers.json)")
            for bare in _tool_name_list(fields.get("tools", "")):
                if bare == "*" or bare in _KNOWN_TOOL_NAMES or bare.startswith("mcp__"):
                    continue
                if bare.lower() in _KNOWN_TOOL_BY_LOWER:
                    add("frontmatter-field", f"`tools` spells `{bare}`; the tool is called `{_KNOWN_TOOL_BY_LOWER[bare.lower()]}`")
                else:
                    unknown_tools.append(bare)
            model = fields.get("model", "").strip()
            if model and model not in models and not _MODEL_VALUE_RE.match(model):
                add("frontmatter-field", f"`model: {model}` is not a model alias or id")
            effort = fields.get("effort", "").strip()
            if effort and reasoning_set and effort not in reasoning_set:
                add("frontmatter-field", f"`effort: {effort}` is none of {', '.join(sorted(reasoning_set))} (.act/tiers.json)")

        allowed = _SKILL_FIELDS if unit_kind == "skill" else _ROLE_FIELDS
        unknown = [k for k in dict.fromkeys(parsed.order) if k not in allowed]
        if unknown:
            add("frontmatter-unknown",
                f"field(s) no known tool reads: {', '.join(unknown)} — a typo, or newer than this check")
        if unknown_tools:
            add("frontmatter-unknown",
                f"`tools` names no tool this check knows: {', '.join(unknown_tools)} — a typo, or newer than this check")
    return findings


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------

def write_inbox(root: Path, findings: list[Finding]) -> Optional[Path]:
    # A tool's own report of what it found (finding 12 in the module docstring is one input to
    # this, not a decision by itself) — no action is asked of anyone but reading it, so `kind:
    # report` (a plain notice), never `todo`. A re-run today
    # replaces today's own file rather than piling up near-duplicates — but only while that file
    # is still `status: open` and unread: once a person has answered it (or it is from an earlier
    # day), overwriting it would erase their words under it (R-human-text) and silently reopen a
    # closed entry, so a fresh file is written instead.
    if not findings:
        return None
    inbox_dir = root / actlib.INBOX_DIR
    today_stamp_prefix = f"report-{date.today().strftime('%Y%m%d')}-"
    dest = None
    if inbox_dir.is_dir():
        for candidate in sorted(inbox_dir.glob("report-*-doctor.md")):
            if not candidate.name.startswith(today_stamp_prefix):
                continue
            try:
                text = candidate.read_text(encoding="utf-8")
            except OSError:
                continue
            match = re.search(r"(?im)^status:\s*(.*?)\s*$", actlib.header_block(text))
            if match and match.group(1).strip() == "open":
                dest = candidate
    if dest is None:
        # Within the same minute as a report that must not be reused (answered, or no longer
        # open), the stamped name is the same — count up instead of writing over it.
        stamp = actlib.entry_stamp()
        dest = inbox_dir / actlib.inbox_entry_filename("report", "doctor")
        n = 2
        while dest.exists():  # the counter goes before the slug, so the glob above still finds it
            dest = inbox_dir / f"report-{stamp}-{n}-doctor.md"
            n += 1
    language = actlib.docs_language(root)
    title = actlib.localized(language, "# doctor findings", "# Doctor-Befunde")
    header = actlib.format_header(["kind: report", "for: all", "status: open", f"created: {actlib.created_stamp()}"],
                                  actlib.writes_frontmatter("report"))
    lines = [header.rstrip("\n"), "", title, ""]
    for kind in KIND_ORDER:
        group = [f for f in findings if f.kind == kind]
        if not group:
            continue
        lines.append(f"## {_kind_label(kind, language)}")
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
    findings += check_legacy_questions_dir(root)
    findings += check_local_role_frontmatter(root)
    findings += check_unreadable_entries(root)
    findings += check_orphan_files(root)
    findings += check_override_orphans(root)
    findings += check_archive_fences(root)
    findings += check_hooks(root)
    findings += check_settings_scripts(root)
    findings += check_unknown_tools(root)
    findings += check_legacy_config_keys(root)
    findings += check_config_values(root)
    findings += check_methods(root)
    findings += check_imports(root)
    findings += check_worker_rules(root)
    findings += check_status_values(root)
    findings += check_revisit_dates(root)
    findings += check_docs_order(root)
    findings += check_own_rules_size(root)
    findings += check_changelog_length(root)
    findings += check_manifest_drift(root)
    findings += check_script_docs(root)
    findings += check_skill_lint(root)
    findings += check_frontmatter(root)
    findings += check_tier_proposal(root)
    findings += check_template_remote(root)

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
    parser.add_argument("--inbox", action="store_true", help="also write docs/ai/inbox/report-<YYYYMMDD-HHMM>-doctor.md if there are findings, and one inbox question per new tier proposal and per check that refused workers often")
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
        # A tier proposal is a decision, so it goes into a question of its own, not into the
        # doctor report; its numbers go into a report of their own that the question names. The
        # doctor report carries the other findings and is skipped when there are none.
        for question in file_tier_questions(root) + file_refusal_questions(root):
            print(f"doctor.py: wrote {_rel(question, root)}")
        written = write_inbox(root, [f for f in findings if f.kind != "tier-proposal"])
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
    try:
        from usage import count_script_run
        count_script_run(__file__)
    except ImportError:
        pass
    sys.exit(main(sys.argv[1:]))
