#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: `act-load-settings` — import a portable settings file (or several) into this project:
#          the counterpart to settings_export.py. Runs the same three-way check the Abgleich-Skill
#          runs after a template update (docs/project/concepts/ai-dev-app/05-update-and-overrides.md
#          § "Gegenseite act-load-settings" in the template-pflege repo), except the "other side" is
#          a settings file instead of a new template state: deckungsgleich -> nichts doppelt,
#          neu -> übernehmen, widersprüchlich -> Inbox (or a config-key resolution).
#
#          Split as decided (`Q69a`): this script does every *mechanical* judgement itself (new,
#          identical, dead/retired/stale identifiers, cross-file collisions, an own rule repeated
#          across files) and writes the result. Anything that needs *content* judgement — does an
#          imported rule merely restate, extend, or actually contradict one of this project's own
#          rules under a different identifier — it cannot decide alone: `plan` only proposes
#          candidate pairs (same area, own-rule/override text against the project's own-rule/
#          override text) for a model to look at; `apply` takes the verdicts back via --judgments
#          and only then writes. Without --judgments, a candidate pair is left "unreviewed" in the
#          inbox rather than silently applied.
#
#          Built on settings_format.py (parse/serialize, reused read-only), rules.py (project file
#          parser + the same [=]/[~]/[-]/[+] semantics), doctor.py's dead/retired-id corpus
#          (`doctor._build_corpus`, read-only reuse — nothing here writes through doctor.py), and
#          update.py's branch hint (`update._maybe_print_branch_hint`). See docs/project/concepts/
#          ai-dev-app/05-update-and-overrides.md and 08-new-project.md § "Settings-Datei: Export und
#          Import" in the template-pflege repo for the full spec.
#
# Usage:
#   python .act/scripts/settings_load.py plan <file...> [--candidates-out PATH] [--json]
#       Parse and mechanically check every given file (order = argument order) against the current
#       project and against each other. Writes nothing to the project; --candidates-out writes the
#       candidate-pair list for a model to judge (see "Candidates JSON" below) to that path.
#   python .act/scripts/settings_load.py apply <file...> [--judgments PATH] [--yes] [--non-interactive]
#       Same analysis, then writes: new/identical/judged-non-contradicting rules into
#       docs/ai/rules.md / docs/project/coding_rules.md, mitgegebene scripts/checklists into
#       docs/ai/local/<area>/<name> (shown before writing unless --yes), "## setup-required" lines
#       and every unresolved finding into one docs/ai/inbox/<date>-settings-<slug>.md. --judgments
#       supplies verdicts for the candidate pairs `plan --candidates-out` produced (see "Judgments
#       JSON" below); a candidate with no verdict stays unapplied and unreviewed in the inbox. A
#       contradiction is resolved automatically, without --judgments, only when
#       docs/ai/config.md sets `settings-conflict-<area>` to `project` or `import` — resolved
#       either way, but always reported, never silent.
#
# Candidates JSON (--candidates-out, and the "candidates" key of `plan --json`):
#   {"candidates": [{"key": "<area>:<import_id>::<target_id>", "area": "rules"|"coding",
#                     "import_file": "<source file>", "import_id": "...", "import_text": "...",
#                     "target_id": "...", "target_text": "..."}, ...]}
#   `key` is what --judgments looks entries up by.
#
# Judgments JSON (--judgments):
#   {"<key>": "same"|"extends"|"contradicts"|"unrelated", ...}
#   A key not listed counts as unjudged. "same"/"contradicts" hold the import entry back (the
#   latter unless a config key resolves it); "extends"/"unrelated" let it be applied.
#
# Output format:
#   plan (default): one section per finding kind, then the candidate pairs, then a summary line.
#     --json: {"findings": [...], "candidates": [...], "setup_required": [...], "counts": {...}}.
#   apply: one line per file/rule actually written, then the same finding sections for whatever
#     was held back, then the inbox file path if one was written, then a summary line.
#   Exit 0 always for a syntactically valid run (findings are not "errors" — that's the point of an
#   inbox); 2 on a fatal error (no .act/ found, an input file that will not parse), never a
#   traceback.

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import actlib
import doctor
import rules
import settings_format as sf
import update


# ---------------------------------------------------------------------------
# Reading the input file(s) — .md or .zip, told apart by suffix (spec § "Transport")
#
# A .zip is untrusted input (it travels between projects/machines), so it gets two independent
# checks before anything from it is trusted: _scan_zip_entries() refuses an oversized/too-large/
# symlinked archive outright (nothing read), and _safe_member_relpath() refuses any "files/..."
# member whose area or path could point outside docs/ai/local/<area>/ — belt (here, structural)
# and suspenders (plan_files()'s dest.resolve() containment check, once `root` is known).
# ---------------------------------------------------------------------------

_MAX_ZIP_ENTRIES = 200
_MAX_ZIP_ENTRY_BYTES = 5 * 1024 * 1024
_MAX_ZIP_TOTAL_BYTES = 20 * 1024 * 1024
_ALLOWED_FILE_AREAS = ("scripts", "checklists")
_UNSAFE_RELPATH_CHARS = re.compile(r"[:\\]")


@dataclass
class SourceFile:
    label: str                       # for messages/inbox: the file name as given on the command line
    settings: sf.SettingsFile
    payload: dict[str, dict[str, str]]  # area -> {relpath: text}, only for "scripts"/"checklists"


def _scan_zip_entries(zf: zipfile.ZipFile, path: Path) -> None:
    """Refuse the whole archive (raises ValueError, nothing is read) if it is too big to be a
    settings transfer at all, or if any entry is a symlink — a symlinked entry's "content" is a
    target path chosen by whoever built the zip, not file data, and extracting it as if it were
    text would follow that path instead of writing one."""
    infos = zf.infolist()
    if len(infos) > _MAX_ZIP_ENTRIES:
        raise ValueError(f"{path}: {len(infos)} entries — more than the {_MAX_ZIP_ENTRIES} a settings zip can hold")
    total = 0
    for info in infos:
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError(f"{path}: {info.filename} is a symlink entry — refused")
        if info.file_size > _MAX_ZIP_ENTRY_BYTES:
            raise ValueError(f"{path}: {info.filename} is larger than {_MAX_ZIP_ENTRY_BYTES // (1024 * 1024)} MB")
        total += info.file_size
        if total > _MAX_ZIP_TOTAL_BYTES:
            raise ValueError(f"{path}: uncompressed contents exceed {_MAX_ZIP_TOTAL_BYTES // (1024 * 1024)} MB")


def _safe_member_relpath(name: str, path: Path) -> tuple[str, str]:
    """Validate one "files/<area>/<relpath>" zip member name and split it into (area, relpath).
    Raises ValueError — refusing the whole archive, not just this member — for anything that
    could resolve outside docs/ai/local/<area>/: an area other than "scripts"/"checklists", an
    absolute or drive-letter path, a backslash (this relpath is always "/"-joined, coming from a
    zip), or any ".."/empty path segment."""
    _, area, relpath = name.split("/", 2)
    if area not in _ALLOWED_FILE_AREAS:
        raise ValueError(f"{path}: {name}: area {area!r} is not one of {_ALLOWED_FILE_AREAS} — refused")
    if not relpath or relpath.startswith("/") or _UNSAFE_RELPATH_CHARS.search(relpath):
        raise ValueError(f"{path}: unsafe path in zip: {name!r}")
    if any(part in ("", "..") for part in relpath.split("/")):
        raise ValueError(f"{path}: unsafe path in zip: {name!r}")
    return area, relpath


def _declared_file_ids(settings: sf.SettingsFile) -> dict[str, set[str]]:
    """The relpaths settings.md itself lists as a "[+] <relpath>" entry, per scripts/checklists
    area — a zip member not named here is never written, even if it otherwise passed
    _safe_member_relpath() (spec: only write what the settings file itself declares)."""
    out: dict[str, set[str]] = {}
    for area_name in _ALLOWED_FILE_AREAS:
        area = settings.area(area_name)
        ids: set[str] = set()
        if area is not None and area.is_modeled():
            for group in area.groups:
                ids.update(e.id for e in group.entries if e.symbol == "+")
        out[area_name] = ids
    return out


def load_source(path: Path) -> SourceFile:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            _scan_zip_entries(zf, path)
            names = zf.namelist()
            if "settings.md" not in names:
                raise ValueError(f"{path}: no settings.md at the root of the zip")
            text = zf.read("settings.md").decode("utf-8")
            settings = sf.parse(text)
            declared = _declared_file_ids(settings)
            payload: dict[str, dict[str, str]] = {}
            for name in names:
                if not name.startswith("files/") or name.endswith("/"):
                    continue
                area, relpath = _safe_member_relpath(name, path)
                if relpath not in declared.get(area, ()):
                    continue  # not listed as a "[+]" entry in this area of settings.md — ignored
                try:
                    payload.setdefault(area, {})[relpath] = zf.read(name).decode("utf-8")
                except UnicodeDecodeError:
                    payload.setdefault(area, {})[relpath] = ""  # binary — reported, never written
        return SourceFile(label=path.name, settings=settings, payload=payload)

    text = path.read_text(encoding="utf-8")
    return SourceFile(label=path.name, settings=sf.parse(text), payload={})


# ---------------------------------------------------------------------------
# One line of a settings file, flattened to a comparable shape
# ---------------------------------------------------------------------------

_RE_REPLACES_PREFIX = re.compile(r"^replaces:\s*")
_FENCE_LINE = re.compile(r"^\s*(?:`{3,}|~{3,})", re.MULTILINE)


@dataclass
class ImportEntry:
    file_label: str
    area: str
    group_label: Optional[str]   # coding set name for a nested group, None for a flat entry
    symbol: str                  # "=" "~" "-" "+"
    id: str
    inline: Optional[str]
    body: Optional[str]

    @property
    def text(self) -> str:
        parts = [p for p in (self.inline, self.body) if p]
        return "\n".join(parts).strip()

    def flat_text(self) -> str:
        """Single-line rendering for a project file (rules.py's own-rule/replaces lines are
        single-line only — see the header comment of _write_own_rule/_write_replaces). A "~"
        entry's `inline` carries a "replaces:" marker (settings_export.py writes it for both the
        one-line and the multi-line shape) — stripped here, *before* joining with `body`, so a
        multi-line override neither keeps the marker as its own flattened segment nor leaves a
        bare "/ " behind once _replaces_line() removes it afterwards (both were the same bug: the
        marker has to go before flattening, not after)."""
        inline = _RE_REPLACES_PREFIX.sub("", self.inline) if self.inline else self.inline
        parts = [p for p in (inline, self.body) if p]
        text = "\n".join(parts).strip()
        return " / ".join(line.strip() for line in text.splitlines() if line.strip())

    def has_fenced_content(self) -> bool:
        """True if `body` itself contains a code-fence line (the settings.md transport fence
        around a "~" body is already stripped by the parser — this catches a fence that is part
        of the actual rule text, e.g. a code example inside an override). Flattening such an
        entry to one project-file line loses that structure; the caller notes it in the inbox."""
        return bool(self.body and _FENCE_LINE.search(self.body))


def collect_entries(source: SourceFile) -> list[ImportEntry]:
    out: list[ImportEntry] = []
    for area in source.settings.areas:
        if not area.is_modeled():
            continue
        for group in area.groups:
            for entry in group.entries:
                out.append(ImportEntry(
                    file_label=source.label, area=area.name, group_label=group.label,
                    symbol=entry.symbol, id=entry.id, inline=entry.inline, body=entry.body,
                ))
    return out


# ---------------------------------------------------------------------------
# Findings — one shape for both plan output and the inbox
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    kind: str
    area: str
    message: str

    def render(self) -> str:
        return f"[{self.area}] {self.message}"


KIND_LABELS: dict[str, str] = {
    "dead-id": "Dead or retired identifiers (not applied)",
    "changed-since-export": "Template text changed since the export (not applied, review by hand)",
    "id-collision": "Same identifier, different content than the project's own (not applied)",
    "cross-file-collision": "Two of the given files disagree on the same identifier (not applied)",
    "template-candidate": "The same own rule appears in more than one file (a template candidate)",
    "unreviewed-candidate": "Content overlap with a project rule, not yet judged (not applied)",
    "contradicts": "Judged to contradict a project rule (not applied)",
    "conflict-resolved": "Contradiction resolved via docs/ai/config.md `settings-conflict-<area>`",
    "same": "Judged to already say the same thing as a project rule (not applied)",
    "setup-required": "Needs configuration before use",
    "file-collision": "A mitgegebene file has the same name as an existing one (not written)",
    "template-shadowed": "A mitgegebene file has the same name as a template file (would shadow it)",
    "not-supported": "Area not supported yet by this build",
    "unresolved-off": "Switched-off entry has no matching set/group in this project (not applied)",
    "set-switch-declined": "Import wants to switch off a coding set that is active here (kept on, not applied)",
    "invalid-id": "Own-rule identifier uses characters a project file cannot render (not applied)",
    "flattened-content": "Multi-line text contains a code fence that flattening would lose (review by hand)",
}
KIND_ORDER = list(KIND_LABELS)


# ---------------------------------------------------------------------------
# Template corpus (dead/retired ids) — reuses doctor.py's own corpus builder read-only
# ---------------------------------------------------------------------------

def _corpus(root: Path, area_name: str) -> "doctor.TemplateCorpus":
    return doctor._build_corpus(root, area_name)


# The settings file's area names ("rules", "coding" — logical categories, spec § "Format — Aufbau")
# do not match rules.py's area keys ("core", "coding" — its two project-file layouts). Translated
# at the one seam between the two vocabularies; everywhere else (Finding.area, candidate keys,
# `settings-conflict-<area>`) keeps the settings-file name, since that is what a settings.md/the
# config key actually says.
SETTINGS_TO_RULES_AREA = {"rules": "core", "coding": "coding"}


# ---------------------------------------------------------------------------
# Target project state
# ---------------------------------------------------------------------------

@dataclass
class TargetArea:
    area: rules.Area
    project: Optional[rules.ProjectFile]
    own_by_id: dict[str, str] = field(default_factory=dict)     # id -> text, id-bearing own rules
    own_texts: list[tuple[Optional[str], str]] = field(default_factory=list)  # every own rule
    override_by_id: dict[str, str] = field(default_factory=dict)


def load_target(root: Path) -> dict[str, TargetArea]:
    """Keyed by the settings-file area name ("rules"/"coding"), not rules.py's own ("core"/"coding")
    — see SETTINGS_TO_RULES_AREA."""
    out: dict[str, TargetArea] = {}
    for area_name, rules_area_name in SETTINGS_TO_RULES_AREA.items():
        area = rules.AREAS[rules_area_name]
        path = root / area.project_file
        project = rules.parse_project_file(path, area) if path.is_file() else None
        ta = TargetArea(area=area, project=project)
        if project is not None:
            for own in project.own_rules:
                if own.id:
                    ta.own_by_id[own.id] = own.text
                ta.own_texts.append((own.id, own.text))
            for override in project.overrides:
                ta.override_by_id[override.id] = override.text
        out[area_name] = ta
    return out


# ---------------------------------------------------------------------------
# Analysis result
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    key: str
    area: str
    import_file: str
    import_id: str
    import_text: str
    target_id: str
    target_text: str

    def as_dict(self) -> dict:
        return {
            "key": self.key, "area": self.area, "import_file": self.import_file,
            "import_id": self.import_id, "import_text": self.import_text,
            "target_id": self.target_id, "target_text": self.target_text,
        }


@dataclass
class Resolution:
    entry: ImportEntry
    action: str            # "apply" | "skip"
    reason: str
    candidates: list[str] = field(default_factory=list)  # candidate keys touching this entry


@dataclass
class Analysis:
    resolutions: list[Resolution] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    setup_required: list[str] = field(default_factory=list)   # "<file>: <line>"
    file_plan: list[dict] = field(default_factory=list)        # scripts/checklists to write
    not_supported: set[str] = field(default_factory=set)


# A handful of very common words, so the candidate-pair fallback keyword filter (only used when a
# project has enough own rules that pairing everything would be noisy — see analyze()) does not
# treat "the"/"a rule about" as a shared topic.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "in", "on", "to", "is", "are", "be", "no", "not",
    "all", "for", "with", "code", "rule", "rules", "project", "source", "get", "gets",
}


def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Z]{4,}", text.lower()) if w not in _STOPWORDS}


# Above this many own-rule/override entries on the target side, pairing every import entry
# against every one of them gets noisy — fall back to a shared-keyword prefilter. Below it, every
# combination is offered as a candidate: real settings-file own-rule counts are small, and a
# genuine collision (see the JSDoc/"no comments" example in the spec) need not share a single word.
_CANDIDATE_FULL_CROSS_LIMIT = 40


def _target_candidates_for(ta: TargetArea) -> list[tuple[str, str]]:
    """(id, text) for every target own rule (id-bearing or not — an unlabeled one gets a
    synthetic id) and override, the candidate-pairing pool for one area."""
    out: list[tuple[str, str]] = []
    for i, (oid, text) in enumerate(ta.own_texts):
        out.append((oid or f"(unlabeled-{i})", text))
    for oid, text in ta.override_by_id.items():
        out.append((oid, text))
    return out


def _candidate_pairs(entry: ImportEntry, pool: list[tuple[str, str]]) -> list[tuple[str, str]]:
    if not pool:
        return []
    if len(pool) <= _CANDIDATE_FULL_CROSS_LIMIT:
        return [(tid, ttext) for tid, ttext in pool if tid != entry.id]
    kws = _keywords(entry.text)
    return [(tid, ttext) for tid, ttext in pool if tid != entry.id and kws & _keywords(ttext)]


# ---------------------------------------------------------------------------
# Dead / retired / "changed since export" — shared by "~" and "-" entries
# ---------------------------------------------------------------------------

def _template_status(root: Path, area_name: str, gid: str, header: sf.SettingsHeader,
                      corpus: "doctor.TemplateCorpus", is_whole_set: bool = False) -> Optional[str]:
    """None if the id is alive and (as far as this project can tell) unchanged since the export;
    otherwise the Finding kind that applies ("dead-id" or "changed-since-export"). `is_whole_set`
    is set for a coding "[-] <set-name> — entire rule set switched off" entry: its id is a coding
    set's file basename (e.g. "bash"), not a template group id, so it is checked against the
    template's coding sets instead of `corpus.ids` (which only holds *group* ids)."""
    if is_whole_set:
        if actlib.resolve(f"coding/{gid}.md") is None:
            return "dead-id"
        return None  # a coding set has no "retired:"/version-hash tracking of its own
    if gid not in corpus.ids:
        return "dead-id"  # covers both "never existed" and "retired:" (doctor._build_corpus folds
        # "retired:" into corpus.retired, checked next) — checked together, message differs below
    lock = actlib.read_lock()
    current_version = (lock.get("template") or {}).get("version", "")
    if header.version and current_version and header.version != current_version:
        # Best-effort proxy: a target project shares no git history with the settings file's
        # source (ADR-5 — "kein Merge, keine gemeinsame Historie"), so the old rule text at the
        # export's commit cannot be diffed against here. A version mismatch is reported instead of
        # silently trusting a rule the current template may have changed since.
        return "changed-since-export"
    return None


def _dead_message(gid: str, corpus: "doctor.TemplateCorpus", kind: str) -> str:
    if gid in corpus.retired:
        return f"`{gid}` is retired in the current template — not applied"
    return f"`{gid}` no longer exists in the current template — not applied"


# An own-rule id becomes a backtick-wrapped Markdown identifier in docs/ai/rules.md /
# docs/project/coding_rules.md ("- `<id>`: ..."); a backtick, pipe or newline in it would break
# that rendering (or, for a pipe, a table row elsewhere), so anything outside this set is refused
# rather than written verbatim.
_VALID_OWN_ID = re.compile(r"^[A-Za-z0-9._-]+$")


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyze(root: Path, sources: list[SourceFile]) -> Analysis:
    result = Analysis()
    targets = load_target(root)
    corpora = {name: _corpus(root, rname) for name, rname in SETTINGS_TO_RULES_AREA.items()}

    all_entries: list[ImportEntry] = []
    header_by_file: dict[str, sf.SettingsHeader] = {}
    for source in sources:
        all_entries.extend(collect_entries(source))
        header_by_file[source.label] = source.settings.header
        for line in source.settings.setup_required:
            result.setup_required.append(f"{source.label}: {line}")

    # Areas this build does not write at all yet.
    for entry in all_entries:
        if entry.area not in ("rules", "coding", "scripts", "checklists"):
            result.not_supported.add(entry.area)

    # --- cross-file collisions: same (area, id) from >1 file, different symbol or text ---------
    # "-"/"~"/"+" all count — two files disagreeing on *what to do* with an id (e.g. one drops
    # it, the other overrides it) is as much a collision as two files overriding it differently.
    by_area_id: dict[tuple[str, str], list[ImportEntry]] = {}
    for entry in all_entries:
        if entry.symbol == "=":
            continue
        by_area_id.setdefault((entry.area, entry.id), []).append(entry)

    excluded_ids: set[tuple[str, str]] = set()
    for (area_name, gid), group in by_area_id.items():
        files = sorted({e.file_label for e in group})
        if len(files) <= 1:
            continue
        symbols = sorted({e.symbol for e in group})
        if len(symbols) > 1:
            excluded_ids.add((area_name, gid))
            result.findings.append(Finding(
                kind="cross-file-collision", area=area_name,
                message=f"`{gid}` — {', '.join(files)} disagree on what to do with it "
                        f"({'/'.join(symbols)}) — not applied from either",
            ))
            continue
        texts = {e.flat_text() for e in group}
        if len(texts) > 1:
            excluded_ids.add((area_name, gid))
            result.findings.append(Finding(
                kind="cross-file-collision", area=area_name,
                message=f"`{gid}` differs between {', '.join(files)} — not applied from either",
            ))
        elif group[0].symbol == "+":
            result.findings.append(Finding(
                kind="template-candidate", area=area_name,
                message=f"`{gid}` — same own rule repeated across {', '.join(files)}; "
                        "candidate to move into the template",
            ))

    seen_ids: set[tuple[str, str]] = set()  # first occurrence wins once cross-file-collision is excluded

    for entry in all_entries:
        area_name = entry.area

        if entry.symbol == "=":
            continue  # unchanged from the template — nothing to write, not a finding

        if area_name in ("scripts", "checklists"):
            continue  # handled separately, in plan_files()

        if area_name not in ("rules", "coding"):
            continue  # reported once via not_supported above

        key_id = (area_name, entry.id)
        if entry.symbol in ("+", "~", "-"):
            if key_id in excluded_ids:
                continue
            if key_id in seen_ids:
                continue  # a later file repeating an already-resolved id — first file wins
            seen_ids.add(key_id)

        ta = targets[area_name]
        corpus = corpora[area_name]

        if entry.symbol == "-":
            is_whole_set = area_name == "coding" and entry.group_label is None
            status = _template_status(root, area_name, entry.id, header_by_file[entry.file_label], corpus, is_whole_set)
            if status:
                result.findings.append(Finding(
                    kind=status, area=area_name, message=_dead_message(entry.id, corpus, status)
                    if status == "dead-id" else f"`{entry.id}` — {KIND_LABELS[status].lower()}",
                ))
                result.resolutions.append(Resolution(entry, "skip", status))
                continue
            active_pset = _whole_set_pset(ta.project, entry.id) if is_whole_set and ta.project is not None else None
            if active_pset is not None and active_pset.enabled:
                result.findings.append(Finding(
                    kind="set-switch-declined", area=area_name,
                    message=f"`{entry.id}` — this coding set is active here; an import never "
                            "switches off an active set, review and switch it off by hand if wanted",
                ))
                result.resolutions.append(Resolution(entry, "skip", "set-switch-declined"))
                continue
            result.resolutions.append(Resolution(entry, "apply", "off"))
            continue

        if entry.symbol == "~":
            status = _template_status(root, area_name, entry.id, header_by_file[entry.file_label], corpus)
            if status:
                result.findings.append(Finding(
                    kind=status, area=area_name, message=_dead_message(entry.id, corpus, status)
                    if status == "dead-id" else f"`{entry.id}` — {KIND_LABELS[status].lower()}",
                ))
                result.resolutions.append(Resolution(entry, "skip", status))
                continue
            existing = ta.override_by_id.get(entry.id)
            if existing is not None:
                if existing.strip() == entry.flat_text().strip():
                    result.resolutions.append(Resolution(entry, "skip", "same"))
                else:
                    result.findings.append(Finding(
                        kind="id-collision", area=area_name,
                        message=f"`{entry.id}` — project already overrides this with different text",
                    ))
                    result.resolutions.append(Resolution(entry, "skip", "id-collision"))
                continue
            # new override — subject to candidate pairing against the project's own rules/overrides
        elif entry.symbol == "+":
            if entry.id and not _VALID_OWN_ID.match(entry.id):
                result.findings.append(Finding(
                    kind="invalid-id", area=area_name,
                    message=f"`{entry.id}` — id uses characters other than letters, digits, "
                            "`.`, `_`, `-`; not applied",
                ))
                result.resolutions.append(Resolution(entry, "skip", "invalid-id"))
                continue
            existing = ta.own_by_id.get(entry.id) if entry.id else None
            if existing is not None:
                if existing.strip() == entry.flat_text().strip():
                    result.resolutions.append(Resolution(entry, "skip", "same"))
                    continue
                result.findings.append(Finding(
                    kind="id-collision", area=area_name,
                    message=f"`{entry.id}` — project already has an own rule with this id and different text",
                ))
                result.resolutions.append(Resolution(entry, "skip", "id-collision"))
                continue
            same_text = next((tid for tid, ttext in ta.own_texts if ttext.strip() == entry.flat_text().strip()), None)
            if same_text is not None:
                result.resolutions.append(Resolution(entry, "skip", "same"))
                continue
            # new own rule — subject to candidate pairing

        if entry.has_fenced_content():
            result.findings.append(Finding(
                kind="flattened-content", area=area_name,
                message=f"`{entry.id}` — contains a code fence; would be flattened to a single "
                        "project-file line if applied, review by hand",
            ))

        pool = _target_candidates_for(ta)
        pairs = _candidate_pairs(entry, pool)
        cand_keys: list[str] = []
        for tid, ttext in pairs:
            key = f"{area_name}:{entry.id}::{tid}"
            cand_keys.append(key)
            result.candidates.append(Candidate(
                key=key, area=area_name, import_file=entry.file_label,
                import_id=entry.id, import_text=entry.text,
                target_id=tid, target_text=ttext,
            ))
        result.resolutions.append(Resolution(entry, "apply", "new", candidates=cand_keys))

    return result


# ---------------------------------------------------------------------------
# Applying judgments (apply only) — refines "apply"/"new" resolutions that carry candidates
# ---------------------------------------------------------------------------

def apply_judgments(root: Path, result: Analysis, judgments: dict[str, str]) -> None:
    conflict_cache: dict[str, str] = {}

    def conflict_side(area_name: str) -> Optional[str]:
        if area_name not in conflict_cache:
            config = actlib.read_config()
            value = config.get(f"settings-conflict-{area_name}", "").strip().lower()
            conflict_cache[area_name] = value
        value = conflict_cache[area_name]
        return value if value in ("project", "import") else None

    for res in result.resolutions:
        if res.action != "apply" or not res.candidates:
            continue
        verdicts = [(key, judgments.get(key)) for key in res.candidates]
        judged = [(key, v) for key, v in verdicts if v]
        contradicts = [key for key, v in judged if v == "contradicts"]
        same = [key for key, v in judged if v == "same"]
        unjudged = [key for key, v in verdicts if not v]

        if same:
            res.action, res.reason = "skip", "same"
            result.findings.append(Finding(
                kind="same", area=res.entry.area,
                message=f"`{res.entry.id}` — judged the same as {same[0].split('::', 1)[1]}, not applied",
            ))
            continue

        if contradicts:
            side = conflict_side(res.entry.area)
            target_id = contradicts[0].split("::", 1)[1]
            if side == "import":
                result.findings.append(Finding(
                    kind="conflict-resolved", area=res.entry.area,
                    message=f"`{res.entry.id}` contradicts `{target_id}` — "
                            f"settings-conflict-{res.entry.area}=import: applied anyway",
                ))
                # res.action stays "apply"
            elif side == "project":
                res.action, res.reason = "skip", "conflict-resolved"
                result.findings.append(Finding(
                    kind="conflict-resolved", area=res.entry.area,
                    message=f"`{res.entry.id}` contradicts `{target_id}` — "
                            f"settings-conflict-{res.entry.area}=project: kept the project's rule",
                ))
            else:
                res.action, res.reason = "skip", "contradicts"
                result.findings.append(Finding(
                    kind="contradicts", area=res.entry.area,
                    message=f"`{res.entry.id}` judged to contradict `{target_id}` — not applied",
                ))
            continue

        if unjudged:
            res.action, res.reason = "skip", "unreviewed"
            keys = ", ".join(k.split("::", 1)[1] for k in unjudged)
            result.findings.append(Finding(
                kind="unreviewed-candidate", area=res.entry.area,
                message=f"`{res.entry.id}` — content overlap with {keys}, not yet judged, not applied",
            ))
        # "extends"/"unrelated" and everything already judged and not contradicting/same: applied as-is


def mark_unreviewed_without_judgments(result: Analysis) -> None:
    """No --judgments at all: every candidate pair stays unreviewed — same effect as
    apply_judgments() with an empty dict, kept separate so `plan` never has to build one."""
    apply_judgments(Path("."), result, {})


# ---------------------------------------------------------------------------
# Writing rules/coding files
# ---------------------------------------------------------------------------

def _insert_after_heading(lines: list[str], heading: str, new_lines: list[str]) -> list[str]:
    idx = next((i for i, ln in enumerate(lines) if ln.strip() == heading), None)
    if idx is None:
        out = list(lines)
        if out and out[-1].strip():
            out.append("")
        out.append(heading)
        out.append("")
        out.extend(new_lines)
        return out
    insert_at = len(lines)
    for i in range(idx + 1, len(lines)):
        if lines[i].strip().startswith("## "):
            insert_at = i
            break
    out = list(lines)
    out[insert_at:insert_at] = new_lines
    return out


def _own_rule_line(entry: ImportEntry) -> str:
    return f"- `{entry.id}`: {entry.flat_text()}"


def _replaces_line(entry: ImportEntry) -> str:
    # flat_text() already strips the "replaces:" marker (before flattening — see its docstring),
    # so there is nothing left to clean up here.
    return f"- replaces `{entry.id}`: {entry.flat_text()}"


def _whole_set_pset(project: rules.ProjectFile, set_label: str) -> Optional[rules.ProjectSet]:
    """The project's ProjectSet whose basename is `set_label` ("bash" for .act/coding/bash.md),
    or None if the project does not import that set at all — the same basename rule
    `_toggle_group_off()` uses to find a whole-set checkbox line, factored out so analyze() can
    ask "is this set currently active?" without duplicating it (Q69a follow-up: an import must
    never switch off a set the project actively uses — see the "-" branch in analyze())."""
    for pset in project.sets:
        label = rules.strip_template_prefix(pset.path).rsplit("/", 1)[-1].removesuffix(".md")
        if label == set_label:
            return pset
    return None


def _toggle_group_off(root: Path, project: rules.ProjectFile, gid: str) -> Optional[tuple[str, bool]]:
    """Flip the project's checkbox for coding group `gid` (or the whole set, if `gid` matches a
    set's basename) to off, in place. Returns (message, applied) — `applied` is False when the
    checkbox was already off (nothing written), so the caller's summary line does not count a
    no-op as a change; returns None if the project does not import that set/group at all (nothing
    to toggle). The whole-set branch below is only reachable for a set analyze() found inactive —
    an active whole set is turned back by analyze() itself (`set-switch-declined`) before a
    resolution ever reaches here."""
    for pset in project.sets:
        set_label = rules.strip_template_prefix(pset.path).rsplit("/", 1)[-1].removesuffix(".md")
        if set_label == gid:
            if not pset.enabled:
                return f"{set_label}: already switched off", False
            lines = project.path.read_text(encoding="utf-8").splitlines()
            lines[pset.line - 1] = re.sub(r"\[[ xX]\]", "[ ]", lines[pset.line - 1], count=1)
            project.path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
            return f"{set_label}: whole set switched off", True
        if gid in pset.groups:
            group = pset.groups[gid]
            if not group.enabled:
                return f"`{gid}`: already switched off", False
            lines = project.path.read_text(encoding="utf-8").splitlines()
            lines[group.line - 1] = re.sub(r"\[[ xX]\]", "[ ]", lines[group.line - 1], count=1)
            project.path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
            return f"`{gid}`: group switched off (in {set_label})", True
        if pset.enabled:
            # The project uses this set but never mentions `gid` — it counts as "on" (rules.classify
            # default). Insert a fresh "off" checkbox line right after the set line.
            template = rules.resolve_template_set(pset)
            if template is not None and gid in template.groups:
                lines = project.path.read_text(encoding="utf-8").splitlines()
                lines.insert(pset.line, f"  - [ ] `{gid}`")
                project.path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
                return f"`{gid}`: added and switched off (in {set_label})", True
    return None


def write_resolutions(root: Path, result: Analysis) -> list[tuple[str, bool]]:
    """Writes docs/ai/rules.md and docs/project/coding_rules.md for every resolution marked
    "apply". Returns one (message, applied) pair per rule touched — `applied` is False for a
    no-op report ("already switched off") so a caller's summary line does not count it as a
    change (see _toggle_group_off)."""
    messages: list[tuple[str, bool]] = []
    to_apply = [r for r in result.resolutions if r.action == "apply"]
    if not to_apply:
        return messages

    by_area: dict[str, list[Resolution]] = {}
    for res in to_apply:
        by_area.setdefault(res.entry.area, []).append(res)

    for area_name, resolutions in by_area.items():
        rules_area = rules.AREAS[SETTINGS_TO_RULES_AREA[area_name]]
        path = root / rules_area.project_file
        lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
        own_lines = [_own_rule_line(r.entry) for r in resolutions if r.entry.symbol == "+"]
        replaces_lines = [_replaces_line(r.entry) for r in resolutions if r.entry.symbol == "~"]
        if own_lines:
            lines = _insert_after_heading(lines, "## Own rules", own_lines)
        if replaces_lines:
            lines = _insert_after_heading(lines, "## Overrides", replaces_lines)
        if own_lines or replaces_lines:
            path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
            for r in resolutions:
                if r.entry.symbol in ("+", "~"):
                    messages.append((f"{area_name}: `{r.entry.id}` — applied", True))

        off_entries = [r for r in resolutions if r.entry.symbol == "-"]
        if off_entries:
            project = rules.parse_project_file(path, rules_area)
            for r in off_entries:
                outcome = _toggle_group_off(root, project, r.entry.id)
                if outcome is None:
                    result.findings.append(Finding(
                        kind="unresolved-off", area=area_name,
                        message=f"`{r.entry.id}` — this project does not use that coding set, nothing to switch off",
                    ))
                else:
                    message, applied = outcome
                    messages.append((f"{area_name}: {message}", applied))
                    if applied:
                        project = rules.parse_project_file(path, rules_area)  # re-read: lines shifted

    return messages


# ---------------------------------------------------------------------------
# Mitgegebene Dateien (scripts / checklists)
# ---------------------------------------------------------------------------

def plan_files(root: Path, sources: list[SourceFile], result: Analysis) -> None:
    local_root = (root / "docs" / "ai" / "local").resolve()
    for source in sources:
        for area_name, contents in source.payload.items():
            area_root = local_root / area_name
            for relpath, text in contents.items():
                dest = root / "docs" / "ai" / "local" / area_name / relpath
                # Second, independent check that `dest` cannot land outside docs/ai/local/<area>/
                # — load_source()'s _safe_member_relpath() already refused an unsafe zip member
                # name; this re-checks the resolved filesystem path itself before anything is
                # planned to be written there.
                if dest.resolve() != area_root and area_root not in dest.resolve().parents:
                    raise ValueError(f"{source.label}: {relpath}: resolves outside docs/ai/local/{area_name}/ — refused")
                if dest.is_file():
                    existing = dest.read_text(encoding="utf-8")
                    if existing == text:
                        status = "same"
                    else:
                        status = "collision"
                        result.findings.append(Finding(
                            kind="file-collision", area=area_name,
                            message=f"docs/ai/local/{area_name}/{relpath} already exists with different content — not written",
                        ))
                else:
                    status = "new"
                if (root / ".act" / area_name / relpath).is_file():
                    result.findings.append(Finding(
                        kind="template-shadowed", area=area_name,
                        message=f"docs/ai/local/{area_name}/{relpath} — a template file of the same "
                                f"name exists (.act/{area_name}/{relpath}); this import would shadow it",
                    ))
                result.file_plan.append({
                    "file": source.label, "area": area_name, "path": relpath,
                    "dest": f"docs/ai/local/{area_name}/{relpath}", "status": status, "text": text,
                })


def write_files(root: Path, result: Analysis, yes: bool) -> list[str]:
    messages: list[str] = []
    interactive = actlib.is_interactive()
    for item in result.file_plan:
        if item["status"] != "new":
            continue
        dest = root / item["dest"]
        if not yes:
            if interactive:
                print(f"--- {item['dest']} ({item['file']}) ---")
                print(item["text"])
                answer = input(f"Write {item['dest']}? [y/N]: ").strip().lower()
                if answer != "y":
                    result.findings.append(Finding(
                        kind="file-collision", area=item["area"],
                        message=f"{item['dest']} — declined interactively, not written",
                    ))
                    continue
            else:
                result.findings.append(Finding(
                    kind="file-collision", area=item["area"],
                    message=f"{item['dest']} — needs --yes or an interactive run, not written",
                ))
                continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(item["text"], encoding="utf-8")
        messages.append(f"{item['dest']}: written")
    return messages


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------

def write_inbox(
    root: Path, findings: list[Finding], setup_required: list[str], sources: list[SourceFile],
) -> tuple[Optional[Path], bool]:
    """Returns (path, is_new). `is_new` is False when an inbox file with the exact same body
    already exists — recognized by a content hash kept in an HTML-comment footer (invisible once
    rendered, so it does not disturb the "opens with two header fields" shape every other inbox
    entry has, per .act/skeleton/inbox/README.md). Without this, re-running the same import
    against a target that has not changed piled up a fresh, identically-worded inbox file every
    time (Q69a follow-up)."""
    if not findings and not setup_required:
        return None, False

    lines = ["for: all", "status: open", "", "# settings import findings", "",
             "Source file(s): " + ", ".join(s.label for s in sources), ""]
    for kind in KIND_ORDER:
        group = [f for f in findings if f.kind == kind]
        if not group:
            continue
        lines.append(f"## {KIND_LABELS[kind]}")
        lines.append("")
        lines.extend(f"- {f.render()}" for f in group)
        lines.append("")
    if setup_required:
        lines.append("## Needs configuration before use")
        lines.append("")
        lines.extend(f"- {line}" for line in setup_required)
        lines.append("")

    body = "\n".join(lines).rstrip("\n") + "\n"
    marker = f"<!-- settings-import-sha256: {hashlib.sha256(body.encode('utf-8')).hexdigest()} -->"

    base = root / "docs" / "ai" / "inbox"
    if base.is_dir():
        for existing in sorted(base.glob("*-settings-*.md")):
            try:
                if marker in existing.read_text(encoding="utf-8"):
                    return existing, False
            except OSError:
                continue

    slug = re.sub(r"[^a-z0-9]+", "-", (sources[0].settings.header.source or "import").lower()).strip("-") or "import"
    dest = base / f"{date.today().isoformat()}-settings-{slug}.md"
    n = 2
    while dest.is_file():
        dest = base / f"{date.today().isoformat()}-settings-{slug}-{n}.md"
        n += 1

    base.mkdir(parents=True, exist_ok=True)
    dest.write_text(body + marker + "\n", encoding="utf-8")
    return dest, True


# ---------------------------------------------------------------------------
# Human-readable rendering (plan and the part of apply that mirrors it)
# ---------------------------------------------------------------------------

def render_findings(findings: list[Finding]) -> str:
    lines: list[str] = []
    for kind in KIND_ORDER:
        group = [f for f in findings if f.kind == kind]
        if not group:
            continue
        lines.append(f"== {KIND_LABELS[kind]} ==")
        lines.extend(f.render() for f in group)
        lines.append("")
    return "\n".join(lines)


def render_plan(result: Analysis) -> str:
    lines = [render_findings(result.findings)]
    applied = [r for r in result.resolutions if r.action == "apply"]
    if applied:
        lines.append("== Would apply ==")
        for r in applied:
            note = f" ({len(r.candidates)} candidate pair(s))" if r.candidates else ""
            lines.append(f"[{r.entry.area}] {r.entry.symbol} `{r.entry.id}`{note}")
        lines.append("")
    if result.file_plan:
        lines.append("== Mitgegebene Dateien ==")
        for item in result.file_plan:
            lines.append(f"[{item['area']}] {item['dest']} — {item['status']}")
        lines.append("")
    if result.not_supported:
        lines.append("== Not supported yet ==")
        for area_name in sorted(result.not_supported):
            lines.append(f"'{area_name}' — not supported yet, entries left unread")
        lines.append("")
    lines.append(
        f"{len(result.findings)} finding(s), {len(applied)} rule(s) ready to apply, "
        f"{len(result.candidates)} candidate pair(s), {len(result.setup_required)} setup-required line(s)."
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_plan(args: argparse.Namespace) -> int:
    root = actlib.repo_root()
    sources = [load_source(Path(p)) for p in args.files]
    result = analyze(root, sources)
    plan_files(root, sources, result)
    mark_unreviewed_without_judgments(result)

    if args.candidates_out:
        payload = {"candidates": [c.as_dict() for c in result.candidates]}
        Path(args.candidates_out).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        # Status line, not part of the report: kept off stdout so `--json` output stays parseable
        # even when combined with --candidates-out in the same run.
        print(f"settings_load.py: wrote {len(result.candidates)} candidate pair(s) to {args.candidates_out}", file=sys.stderr)

    if args.json:
        payload = {
            "findings": [{"kind": f.kind, "area": f.area, "message": f.message} for f in result.findings],
            "candidates": [c.as_dict() for c in result.candidates],
            "setup_required": result.setup_required,
            "counts": {
                "findings": len(result.findings),
                "apply": len([r for r in result.resolutions if r.action == "apply"]),
                "candidates": len(result.candidates),
            },
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        sys.stdout.write(render_plan(result))
    return 0


_VALID_JUDGMENT_VALUES = {"same", "extends", "contradicts", "unrelated"}


def _load_judgments(path: Path) -> dict[str, str]:
    """Parse and validate --judgments: must be a JSON object mapping a candidate key to one of
    _VALID_JUDGMENT_VALUES. Raises ValueError — caught by main() and turned into a clean exit 2
    — for anything else (a list, a non-string key/value, an unknown verdict), instead of letting
    a malformed file surface as a traceback further down in apply_judgments()."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: --judgments must be a JSON object of {{key: verdict}}")
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str) or value not in _VALID_JUDGMENT_VALUES:
            raise ValueError(
                f"{path}: invalid judgment {key!r}: {value!r} — expected one of {sorted(_VALID_JUDGMENT_VALUES)}"
            )
    return data


def cmd_apply(args: argparse.Namespace) -> int:
    root = actlib.repo_root()
    sources = [load_source(Path(p)) for p in args.files]
    result = analyze(root, sources)
    plan_files(root, sources, result)

    judgments: dict[str, str] = {}
    if args.judgments:
        judgments = _load_judgments(Path(args.judgments))
    apply_judgments(root, result, judgments)

    notes: list[str] = []
    update._maybe_print_branch_hint(root, notes)
    for note in notes:
        print(f"[act] {note}")

    rule_messages = write_resolutions(root, result)
    file_messages = write_files(root, result, args.yes)
    for message, _applied in rule_messages:
        print(f"settings_load.py: {message}")
    for message in file_messages:
        print(f"settings_load.py: {message}")

    inbox_path, inbox_is_new = write_inbox(root, result.findings, result.setup_required, sources)
    if inbox_path is not None:
        if inbox_is_new:
            print(f"settings_load.py: wrote {inbox_path.relative_to(root).as_posix()}")
        else:
            print(f"settings_load.py: same findings already recorded in {inbox_path.relative_to(root).as_posix()}")

    if result.findings:
        sys.stdout.write(render_findings(result.findings))
    if result.not_supported:
        for area_name in sorted(result.not_supported):
            print(f"settings_load.py: area '{area_name}' — not supported yet, entries left unread")

    applied_rules = sum(1 for _message, applied in rule_messages if applied)
    print(
        f"settings_load.py: {applied_rules} rule(s), {len(file_messages)} file(s) applied; "
        f"{len(result.findings)} finding(s) in the inbox."
    )
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="settings_load.py",
        description="Import a settings file (act-export-settings' output) into this project.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="check only, write nothing to the project")
    plan.add_argument("files", nargs="+", help="settings.md or settings.zip file(s), in order")
    plan.add_argument("--candidates-out", metavar="PATH", help="write the candidate-pair list here as JSON")
    plan.add_argument("--json", action="store_true", help="machine-readable output")

    apply_p = sub.add_parser("apply", help="check, then write what is mechanically clear or judged")
    apply_p.add_argument("files", nargs="+", help="settings.md or settings.zip file(s), in order")
    apply_p.add_argument("--judgments", metavar="PATH", help="JSON verdicts for plan --candidates-out's pairs")
    apply_p.add_argument("--yes", action="store_true", help="write mitgegebene Dateien without asking first")
    apply_p.add_argument("--non-interactive", action="store_true", help="never prompt (same effect as omitting --yes when stdin is not a terminal)")

    return parser


def main(argv: list[str]) -> int:
    # Same Windows console-encoding fix as every other script here (em dash throughout).
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
        if args.command == "plan":
            return cmd_plan(args)
        return cmd_apply(args)
    except (RuntimeError, ValueError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"settings_load.py: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
