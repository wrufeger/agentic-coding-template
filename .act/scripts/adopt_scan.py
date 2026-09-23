#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Read-only sighting of an existing project's documentation and AI-tooling material,
#          before adoption (docs/project/concepts/ai-dev-app/11-build-decisions.md § "Stufe 6",
#          07-build-plan.md, in the template-pflege repo). Walks the target tree and classifies
#          every documentation-like file and every AI-tool unit (agent, skill, command, script,
#          hook) it finds into one of: ai-config, ai-machinery, work, log, project-doc, unknown.
#          Writes nothing but its own report under <target>/.act-local/adopt/ — the classified
#          table is later turned into an action per class (adopt/legacy/keep/delete) by a human
#          and by adopt.py (a later build step), never here. Runtime application logs (a
#          "logs/" folder, an arbitrary *.log file) are not sources and are skipped outright. Stdlib only.
#
#          The four classes with a downstream action — ai-config (overwritten with a bridge),
#          ai-machinery (deleted by default), work (parsed into entries), log (moved to a legacy
#          archive) — come ONLY from an explicit allow-list of exact locations (see the constants
#          below and ALLOW-LIST in the help text). Every heuristic — a keyword in a file name, a
#          folder name or a first heading — may at most yield "unknown" plus a "hint" field such
#          as "log?", with a reason; the owner decides. "project-doc" is the class for known doc
#          places (root README*/CHANGELOG*/CONTRIBUTING*/LICENSE*, a docs/ folder, ADR and wiki
#          folders). Keyword-based log/work is only trusted inside a SIGNED AI work folder: the
#          target's own docs/ai/ holding at least two of board.md, tasks.md, ledger.md,
#          questions.md, backlog.md, or any docs/ai/ in a target with a .claude/template.json.
#          An allow-listed place (or anything below it) that is a symlink/junction, or resolves
#          outside where it appears, is never followed: one "unknown" row, note "link to <target>".
#          A row found only on disk (git-ignored in a git target) keeps its class but carries the
#          note "git-ignored/local: …"; CLAUDE.local.md, .mcp.json, .cursor/mcp.json always carry
#          "never bridge". Several notes on one row are joined with "; ".
#
# Usage:
#   python .act/scripts/adopt_scan.py                    # scan the current project (see below)
#   python .act/scripts/adopt_scan.py --target <dir>      # scan <dir> instead — the normal case:
#                                                          # run from a template checkout against
#                                                          # a foreign project that has no .act/
#                                                          # of its own yet
#   python .act/scripts/adopt_scan.py --json               # print the JSON payload instead of the
#                                                          # human-readable table (still writes it)
#
# Output format:
#   Default: a table grouped by class, each row "<path>  [<kind>]  size=<n>  age=<date>  -- <reason>"
#     (plus " (note: <note>)" and/or " (hint: <class>?)" when a row carries one), a per-class count
#     line, one informational line per git submodule ("not scanned: submodule <path>"), and — if
#     the target has a predecessor template (a .claude/template.json) — one hint line naming its
#     base_commit. Never a finding/judgement, just a sighting.
#   --json: the same content as {"target", "generated", "predecessor_hint", "info": [...],
#     "rows": [...], "counts": {<class>: <n>, ...}}, one object per row: {"path", "kind", "size",
#     "age", "class", "reason", "note", "hint"} (note/hint are null unless set). This is exactly
#     what is written to <target>/.act-local/adopt/scan.json.
#   Exit 0 on a normal run (there is no pass/fail here, only a sighting); 2 if the target does not
#   exist or is not a directory, or if run without --target outside any template-managed project.

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Optional

import actlib


# ---------------------------------------------------------------------------
# What to skip outright — never a source, regardless of class
# ---------------------------------------------------------------------------

SKIP_DIR_NAMES = {
    ".git", "node_modules", "vendor", "__pycache__", ".venv", "venv", "env",
    "dist", "build", "out", ".act", ".act-local", "logs", ".idea", ".vscode", ".cache",
    ".pytest_cache", ".tox", ".mypy_cache", "site-packages",
}

# Only for the plain walk of a target that is not a git repo (inside a repo, .gitignore already
# keeps generated output out; a tracked folder with one of these names may well be real content).
WALK_ONLY_SKIP_DIR_NAMES = {"coverage", ".next", "target", ".nuxt", ".output"}

# A directory whose relative path (posix, from the target root) starts with one of these is never
# walked into for the generic doc/candidate scan — a copy of the whole project can legitimately
# live there (a worktree) and must never be re-sighted as if it were the project itself.
ALWAYS_SKIP_PREFIXES = (".claude/worktrees",)

DOC_EXTENSIONS = {".md", ".txt", ".rst", ".adoc"}

# .txt is common in source/test/content trees for reasons that have nothing to do with project
# documentation (a fixture, a template string) — only trust it inside docs/ or at the project root.
TXT_ALLOWED_TOP_DIR = "docs"


# ---------------------------------------------------------------------------
# ALLOW-LIST — the only way into ai-config, ai-machinery, work and log. Exact, case-sensitive.
# ---------------------------------------------------------------------------

# ai-config: exact names directly at the target root.
ROOT_AI_CONFIG = {
    "AGENTS.md", "CLAUDE.md", "CLAUDE.local.md", "GEMINI.md", "CONVENTIONS.md", "AI-CONFIG.md",
    ".aider.conf.yml", ".cursorrules", ".clinerules", ".windsurfrules", ".mcp.json",
}
# ai-config: exact nested paths.
FIXED_AI_CONFIG = {
    ".github/copilot-instructions.md",
    ".claude/settings.json",
    ".claude/settings.local.json",
    ".claude/settings.local.json.example",
    ".cursor/mcp.json",
    ".gemini/settings.json",
    ".junie/guidelines.md",
}
SETTINGS_LOCAL = ".claude/settings.local.json"
SETTINGS_LOCAL_NOTE = "local, git-ignored: never bridge or delete"
# Personal/secret-bearing ai-config files: adopted at most by hand, never replaced by a bridge.
NEVER_BRIDGE = {"CLAUDE.local.md", ".mcp.json", ".cursor/mcp.json"}
NEVER_BRIDGE_NOTE = "never bridge"
# Any row found only on disk, i.e. git-ignored in a git target: its class stays, the note warns.
LOCAL_NOTE = "git-ignored/local: never bridge, delete or move into tracked legacy"
# A nested CLAUDE.md/AGENTS.md (a scaffold template, a sample, a module named "agents") is never
# allow-listed: it gets "unknown" + hint "ai-config?" like any other heuristic hit.

# ai-machinery: one row per direct child (skill folder / agent file / script / hook / command).
MACHINERY_DIRS = (
    (".claude/agents", "agent file"),
    (".claude/skills", "skill folder"),
    (".claude/commands", "command file"),
    (".claude/scripts", "script"),
    (".claude/hooks", "hook"),
    (".github/agents", "agent file"),
    (".github/prompts", "prompt file"),
    (".gemini/commands", "command file"),
    (".codex/agents", "agent file"),
    (".codex/skills", "skill folder"),
    (".codex/commands", "command file"),
    (".codex/scripts", "script"),
    (".codex/hooks", "hook"),
)

# Directories fully consumed by the ai-config/ai-machinery passes — pruned from the generic walk
# so a skill's SKILL.md, or an agent's own prose, is never also listed a second time as a doc.
PRUNED_DIRS = {base for base, _ in MACHINERY_DIRS} | {".cursor", ".github/instructions", ".claude/rules"}

# log: the template's own session log, at the root only.
ROOT_LOG = {"ai.log", "ai.log.state.json", "ai.log.raw.jsonl"}
ROOT_LOG_BAK_RE = re.compile(r"^ai\.log\..+\.bak$")
# work: at the root only.
ROOT_WORK = {"TODO.md", "TODO"}

# The signed AI work folder: docs/ai/ relative to the target root (never a nested package's).
AI_WORK_DIR = "docs/ai"
AI_WORK_SIGNATURE = {"board.md", "tasks.md", "ledger.md", "questions.md", "backlog.md"}
AI_WORK_SIGNATURE_MIN = 2  # one lone board.md is not enough to trust keyword-based log/work
SENT_PROTOCOLS_PREFIX = "docs/ai/template-feedback/sent/"
# Whole-token matches inside the signed folder only (file stem plus every folder segment below
# docs/ai/, each split into tokens). log is checked before work: tasks_archive.md is an archive.
SIGNED_LOG_TOKENS = {"ledger", "journal", "protokoll", "archive", "archiv"}
SIGNED_WORK_TOKENS = {
    "task", "tasks", "aufgabe", "aufgaben", "backlog", "question", "questions",
    "frage", "fragen", "board", "inbox",
}


# ---------------------------------------------------------------------------
# Known doc places — project-doc (no downstream action of its own)
# ---------------------------------------------------------------------------

ROOT_DOC_PREFIXES = ("README", "CHANGELOG", "CONTRIBUTING", "LICENSE")
DOC_PLACE_SEGMENTS = {"adr", "adrs", "wiki"}  # plus any "<name>.wiki" folder (a GitHub wiki clone)
DOCS_SEGMENT = "docs"


# ---------------------------------------------------------------------------
# Heuristics — they only ever produce a hint on an "unknown" row, never a class of their own.
# Whole-token matches (never substrings: "general-ledger" matches "ledger", "roadrunner" does not
# match "adr"); a name is split on `-_. ` into tokens, every folder segment likewise.
# ---------------------------------------------------------------------------

_TOKEN_SPLIT_RE = re.compile(r"[-_.\s]+")

HINT_AI_CONFIG_NAMES = {name.lower() for name in ROOT_AI_CONFIG} | {"copilot-instructions.md"}
HINT_AI_LOG_RE = re.compile(r"^ai\.log(\..+\.bak|\.state\.json|\.raw\.jsonl)?$", re.IGNORECASE)
HINT_LOG_TOKENS = SIGNED_LOG_TOKENS
HINT_WORK_TOKENS = SIGNED_WORK_TOKENS | {"todo"}
HINT_MACHINERY_SEGMENTS = {"agents", "skills", "commands", "prompts", "hooks", "scripts", "rules"}
LOG_HEADING_KEYWORDS = {"ledger", "journal", "protokoll", "archiv", "archive"}
WORK_HEADING_KEYWORDS = {"aufgaben", "tasks", "backlog", "fragen", "questions", "todo"}

# Read at most this many bytes of a file's head once, for the heading scan — never per-line, never
# twice (a one-line file used to trigger a second full re-open due to a StopIteration edge case).
HEAD_BYTES = 8192


# ---------------------------------------------------------------------------
# Data shape
# ---------------------------------------------------------------------------

@dataclass
class Row:
    path: str
    kind: str    # "file" | "dir"
    size: int    # bytes for a file, file count for a dir
    age: str     # "YYYY-MM-DD"
    cls: str
    reason: str
    note: Optional[str] = None  # caution for the later adoption step (T51), e.g. "never delete"
    hint: Optional[str] = None  # only on "unknown": what a heuristic suspects, e.g. "log?"

    def as_dict(self) -> dict:
        d = asdict(self)
        d["class"] = d.pop("cls")
        return d


# ---------------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------------

def resolve_target(target_arg: Optional[str]) -> Path:
    """The directory to scan: `--target` if given (no requirement that it already has a `.act/`
    of its own — the normal case is a foreign, not-yet-adopted project), else the project root of
    wherever this is run from (actlib.repo_root(), same lookup doctor.py/entries.py use)."""
    if target_arg:
        return Path(target_arg).expanduser().resolve()
    return actlib.repo_root()


def _exists_exact(root: Path, rel_posix: str, want_dir: bool = False) -> bool:
    """Like is_file()/is_dir(), but every path segment must match case-sensitively — on Windows
    and macOS the file system would happily say yes to ".GitHub/Copilot-Instructions.md"."""
    current = root
    for part in rel_posix.split("/"):
        try:
            names = os.listdir(current)
        except OSError:
            return False
        if part not in names:
            return False
        current = current / part
    return current.is_dir() if want_dir else current.is_file()


# ---------------------------------------------------------------------------
# Git awareness — one subprocess call per need for the whole tree, not one per file. `root` may be
# a subdirectory of a larger repo (scanning a package inside a monorepo): every path returned here
# is relative to `root`, not to the repo's toplevel.
# ---------------------------------------------------------------------------

def _git_repo_top(root: Path) -> Optional[Path]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    top = result.stdout.strip()
    return Path(top) if top else None


def _relative_prefix(root: Path, repo_top: Path) -> Optional[str]:
    """The posix path of `root` relative to `repo_top` ("" if root IS the toplevel), or None if
    the two cannot be related (different drive, a substituted path) — callers then fall back to
    the plain walk / mtime instead of misreading every repo path as relative to root."""
    try:
        rel = root.resolve().relative_to(repo_top.resolve()).as_posix()
    except ValueError:
        return None
    return "" if rel == "." else rel


def build_git_dates(root: Path) -> dict[str, str]:
    """path (posix, relative to root) -> last commit date ("YYYY-MM-DD") touching it, from a
    single `git log --name-only` call (newest commit first, so the first time a path is seen is
    its most recent date). Returns {} if root is not inside a git repo, or git is unavailable/
    fails — callers fall back to mtime per file in that case, never raise."""
    repo_top = _git_repo_top(root)
    if repo_top is None:
        return {}
    prefix = _relative_prefix(root, repo_top)
    if prefix is None:
        return {}
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotePath=false", "-C", str(repo_top),
             "log", "--name-only", "--pretty=format:%x01%ad", "--date=short"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    if result.returncode != 0:
        return {}
    prefix_slash = f"{prefix}/" if prefix else ""
    dates: dict[str, str] = {}
    current_date: Optional[str] = None
    for line in result.stdout.splitlines():
        if line.startswith("\x01"):
            current_date = line[1:].strip()
            continue
        path = line.strip()
        if not path or current_date is None:
            continue
        if prefix_slash:
            if not path.startswith(prefix_slash):
                continue
            path = path[len(prefix_slash):]
        dates.setdefault(path, current_date)
    return dates


def list_git_candidates(root: Path) -> Optional[list[str]]:
    """Tracked + untracked-not-ignored files under `root` (posix, relative to `root`), from a
    single `git ls-files -co --exclude-standard` call — so generated/ignored material
    (.pytest_cache/, a venv, …) never has to be recognized by name at all. Returns None if `root`
    is not inside a git repo, or git is unavailable/fails — callers fall back to a plain walk."""
    repo_top = _git_repo_top(root)
    if repo_top is None:
        return None
    prefix = _relative_prefix(root, repo_top)
    if prefix is None:
        return None
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotePath=false", "-C", str(repo_top),
             "ls-files", "-co", "--exclude-standard"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    prefix_slash = f"{prefix}/" if prefix else ""
    out: list[str] = []
    for line in result.stdout.splitlines():
        path = line.strip()
        if not path:
            continue
        if prefix_slash:
            if not path.startswith(prefix_slash):
                continue
            path = path[len(prefix_slash):]
        out.append(path)
    return sorted(out)


def list_submodules(root: Path) -> list[str]:
    """Submodule paths from the target's own .gitmodules — never scanned, one info line each."""
    path = root / ".gitmodules"
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found = re.findall(r"^\s*path\s*=\s*(.+?)\s*$", text, flags=re.MULTILINE)
    return sorted({p.strip().strip("/").replace("\\", "/") for p in found if p.strip()})


def _isjunction(path: Path) -> bool:
    check = getattr(os.path, "isjunction", None)  # Python 3.12+
    return bool(check and check(path))


def entry_link(path: Path) -> Optional[str]:
    """The real target if `path` itself is a symlink/junction, or resolves somewhere other than
    its own parent + name (a junction on Python < 3.12, a link further up), else None."""
    try:
        if os.path.islink(path) or _isjunction(path):
            return os.path.realpath(path)
        real = os.path.realpath(path)
        expected = os.path.join(os.path.realpath(path.parent), path.name)
    except (OSError, ValueError):
        return None
    return real if os.path.normcase(real) != os.path.normcase(expected) else None


def link_target(root: Path, rel_posix: str) -> Optional[str]:
    """Like entry_link(), but for every segment of `rel_posix` below `root`: a linked parent
    (.claude/ itself a junction) makes every place below it a link too."""
    current = root
    for part in rel_posix.split("/"):
        current = current / part
        found = entry_link(current)
        if found:
            return found
    return None


def _walk_files(root: Path, start: Path, skip: set[str], links: Optional[list[str]] = None) -> list[str]:
    """Files below `start` (posix, relative to root). A linked directory is never descended into;
    with `links` given, linked directories and files go there instead of into the result."""
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(start):
        current = Path(dirpath)
        rel_dir = current.relative_to(root)
        rel_dir_posix = "" if str(rel_dir) == "." else rel_dir.as_posix()
        for d in list(dirnames):
            if d.lower() in skip:
                dirnames.remove(d)
            elif entry_link(current / d):
                dirnames.remove(d)
                if links is not None:
                    links.append(f"{rel_dir_posix}/{d}" if rel_dir_posix else d)
        for fname in filenames:
            rel = f"{rel_dir_posix}/{fname}" if rel_dir_posix else fname
            if links is not None and entry_link(current / fname):
                links.append(rel)
            else:
                out.append(rel)
    return out


def _walk_candidates(root: Path) -> list[str]:
    """Fallback for a target that is not a git repo: a plain walk, pruned by SKIP_DIR_NAMES plus
    the build-output folders a .gitignore would otherwise have kept out."""
    return sorted(_walk_files(root, root, SKIP_DIR_NAMES | WALK_ONLY_SKIP_DIR_NAMES))


def _is_excluded(rel_posix: str, blocked: list[str]) -> bool:
    """Second line of defense, applied to EVERY candidate regardless of where the list came from:
    a path component that is a known skip-dir, a directory another pass already consumes unit by
    unit, a submodule, a linked docs/ai/, or the worktrees folder — which must never be re-sighted
    even if a project's own .gitignore forgot to exclude it (belt and suspenders)."""
    parts = rel_posix.split("/")
    for part in parts[:-1]:
        if part.lower() in SKIP_DIR_NAMES:
            return True
    for prefix in (*ALWAYS_SKIP_PREFIXES, *blocked):
        if rel_posix == prefix or rel_posix.startswith(prefix + "/"):
            return True
    joined = ""
    for part in parts[:-1]:
        joined = part if not joined else f"{joined}/{part}"
        if joined in PRUNED_DIRS:
            return True
    return False


def is_signed_ai_folder(root: Path) -> bool:
    if not _exists_exact(root, AI_WORK_DIR, want_dir=True) or link_target(root, AI_WORK_DIR):
        return False
    if _exists_exact(root, ".claude/template.json") and not link_target(root, ".claude/template.json"):
        return True
    try:
        names = set(os.listdir(root / AI_WORK_DIR))
    except OSError:
        return False
    present = [n for n in AI_WORK_SIGNATURE if n in names and (root / AI_WORK_DIR / n).is_file()]
    return len(present) >= AI_WORK_SIGNATURE_MIN


def _is_root_allow_listed(name: str) -> bool:
    return (name in ROOT_AI_CONFIG or name in ROOT_LOG or bool(ROOT_LOG_BAK_RE.match(name))
            or name in ROOT_WORK or name.upper().startswith(ROOT_DOC_PREFIXES))


# ---------------------------------------------------------------------------
# Scan context — everything one row needs besides its own path
# ---------------------------------------------------------------------------

@dataclass
class Scan:
    root: Path
    git_dates: dict
    git_files: Optional[set]  # None: not a git target, "found only on disk" cannot be told
    git_dirs: set

    def is_local(self, rel: str) -> bool:
        return self.git_files is not None and rel not in self.git_files and rel not in self.git_dirs

    def notes(self, rel: str, *extra: Optional[str]) -> Optional[str]:
        found = [n for n in extra if n]
        if rel in NEVER_BRIDGE:
            found.append(NEVER_BRIDGE_NOTE)
        if self.is_local(rel) and SETTINGS_LOCAL_NOTE not in found:
            found.append(LOCAL_NOTE)
        return "; ".join(dict.fromkeys(found)) or None

    def file_row(self, rel: str, cls: str, reason: str, note: Optional[str] = None,
                 hint: Optional[str] = None) -> Row:
        return Row(path=rel, kind="file", size=(self.root / rel).stat().st_size,
                   age=age_for(self.root, rel, False, self.git_dates), cls=cls, reason=reason,
                   note=self.notes(rel, note), hint=hint)

    def dir_row(self, rel: str, cls: str, reason: str, hint: Optional[str] = None) -> Row:
        """A unit folder; if anything below it is a link, the whole unit becomes unknown."""
        links: list[str] = []
        files = _walk_files(self.root, self.root / rel, {"__pycache__"}, links)
        size = sum(1 for f in files if not f.endswith((".pyc", ".pyo")))
        note = None
        if links:
            note = f"contains link {links[0]} -> {entry_link(self.root / links[0])}"
            cls, reason, hint = "unknown", f"{reason}, but contains a symlink/junction", f"{cls}?"
        return Row(path=rel, kind="dir", size=size, age=age_for(self.root, rel, True, self.git_dates),
                   cls=cls, reason=reason, note=self.notes(rel, note), hint=hint)

    def link_row(self, rel: str, target: str, would_be: Optional[str]) -> Row:
        """A link at an allow-listed place: listed once, never followed (no rows below it)."""
        full = self.root / rel
        try:
            info = os.lstat(full)
            age = date.fromtimestamp(info.st_mtime).isoformat()
            size = 0 if full.is_dir() else info.st_size
        except OSError:
            age, size = "unknown", 0
        return Row(path=rel, kind="dir" if full.is_dir() else "file", size=size, age=age, cls="unknown",
                   reason="symlink/junction at an allow-listed place, not followed",
                   note=self.notes(rel, f"link to {target}"), hint=would_be)


def list_candidates(scan: Scan, git_list: Optional[list[str]], signed_ai: bool,
                    blocked: list[str]) -> tuple[list[str], list[str]]:
    """(candidates, linked entries inside the signed docs/ai/)."""
    root = scan.root
    found = set(git_list if git_list is not None else _walk_candidates(root))
    # Allow-listed places are looked at on disk too: a root ai.log or a signed folder's local-only
    # send protocol is usually git-ignored and would otherwise never be seen.
    try:
        found.update(n for n in os.listdir(root) if _is_root_allow_listed(n) and (root / n).is_file())
    except OSError:
        pass
    links: list[str] = []
    if signed_ai:
        found.update(_walk_files(root, root / AI_WORK_DIR, SKIP_DIR_NAMES, links))
    return sorted(c for c in found if not _is_excluded(c, blocked + links)), links


def age_for(root: Path, rel_posix: str, is_dir: bool, git_dates: dict[str, str]) -> str:
    if not is_dir:
        found = git_dates.get(rel_posix)
        if found:
            return found
        try:
            return date.fromtimestamp((root / rel_posix).stat().st_mtime).isoformat()
        except OSError:
            return "unknown"
    # A directory unit (a skill folder): the most recent date among its files (links not followed).
    best: Optional[str] = None
    for file_rel in _walk_files(root, root / rel_posix, {"__pycache__"}, []):
        found = git_dates.get(file_rel)
        if found is None:
            try:
                found = date.fromtimestamp((root / file_rel).stat().st_mtime).isoformat()
            except OSError:
                continue
        if best is None or found > best:
            best = found
    return best or "unknown"


# ---------------------------------------------------------------------------
# ai-config pass — root names, fixed paths, the config folders (all exact)
# ---------------------------------------------------------------------------

def scan_ai_config(scan: Scan) -> tuple[list[Row], set[str]]:
    root = scan.root
    rows: list[Row] = []
    consumed: set[str] = set()

    def add_file(rel: str, reason: str, note: Optional[str] = None) -> None:
        target = link_target(root, rel)
        if target:
            rows.append(scan.link_row(rel, target, "ai-config?"))
        else:
            rows.append(scan.file_row(rel, "ai-config", reason, note=note))
        consumed.add(rel)

    try:
        root_names = sorted(os.listdir(root))
    except OSError:
        root_names = []
    for name in root_names:
        if name in ROOT_AI_CONFIG and (root / name).is_file():
            add_file(name, f"ai-config file '{name}' at the root")

    cursor_link = link_target(root, ".cursor") if _exists_exact(root, ".cursor", want_dir=True) else None
    for rel in sorted(FIXED_AI_CONFIG):
        if rel.startswith(".cursor/") and cursor_link:
            continue  # the linked .cursor/ itself gets the one row, see scan_ai_machinery
        if _exists_exact(root, rel):
            add_file(rel, "fixed ai-config path", SETTINGS_LOCAL_NOTE if rel == SETTINGS_LOCAL else None)

    # Everything else in .claude/ that looks like a settings file is suspicious, never allow-listed.
    if _exists_exact(root, ".claude", want_dir=True) and not link_target(root, ".claude"):
        for entry in sorted((root / ".claude").iterdir()):
            rel = f".claude/{entry.name}"
            if entry.is_file() and rel not in consumed and entry.name.lower().startswith("settings"):
                rows.append(scan.file_row(rel, "unknown", "settings-like file in .claude/, not an allow-listed name",
                                          hint="ai-config?"))
                consumed.add(rel)

    for folder, suffix, label in ((".github/instructions", ".instructions.md", "Copilot custom-instructions file"),
                                  (".claude/rules", ".md", "Claude Code rules file")):
        if not _exists_exact(root, folder, want_dir=True):
            continue
        target = link_target(root, folder)
        if target:
            rows.append(scan.link_row(folder, target, "ai-config?"))
            continue
        links: list[str] = []
        for rel in sorted(_walk_files(root, root / folder, {"__pycache__"}, links)):
            if rel.count("/") == folder.count("/") + 1 and rel.endswith(suffix):
                rows.append(scan.file_row(rel, "ai-config", label))
            else:
                rows.append(scan.file_row(rel, "unknown", f"in {folder}/, but not a direct '*{suffix}' file",
                                          hint="ai-config?"))
            consumed.add(rel)
        rows.extend(scan.link_row(rel, entry_link(root / rel) or "?", "ai-config?") for rel in sorted(links))

    if _exists_exact(root, ".cursor/rules", want_dir=True) and not cursor_link:
        target = link_target(root, ".cursor/rules")
        if target:
            rows.append(scan.link_row(".cursor/rules", target, "ai-config?"))
        else:
            rows.append(scan.dir_row(".cursor/rules", "ai-config", "Cursor rules directory"))

    return rows, consumed


# ---------------------------------------------------------------------------
# ai-machinery pass — one row per unit, not per byte
# ---------------------------------------------------------------------------

def _machinery_units(scan: Scan, base_rel: str, label: str, skip_names: tuple = ()) -> list[Row]:
    root = scan.root
    target = link_target(root, base_rel)
    if target:
        return [scan.link_row(base_rel, target, "ai-machinery?")]
    rows: list[Row] = []
    for entry in sorted((root / base_rel).iterdir()):
        if entry.name == "__pycache__" or entry.suffix in (".pyc", ".pyo") or entry.name in skip_names:
            continue
        rel = f"{base_rel}/{entry.name}"
        linked = entry_link(entry)
        if linked:
            rows.append(scan.link_row(rel, linked, "ai-machinery?"))
        elif entry.is_dir():
            rows.append(scan.dir_row(rel, "ai-machinery", label))
        elif entry.is_file():
            rows.append(scan.file_row(rel, "ai-machinery", label))
    return rows


def scan_ai_machinery(scan: Scan) -> list[Row]:
    rows: list[Row] = []
    for base_rel, label in MACHINERY_DIRS:
        if _exists_exact(scan.root, base_rel, want_dir=True):
            rows.extend(_machinery_units(scan, base_rel, f"{label} under {base_rel}/"))
    if _exists_exact(scan.root, ".cursor", want_dir=True):
        # rules/ and mcp.json are ai-config (scan_ai_config); a linked .cursor/ is one row here
        rows.extend(_machinery_units(scan, ".cursor", "Cursor tooling", skip_names=("rules", "mcp.json")))
    return rows


# ---------------------------------------------------------------------------
# Everything else: allow-listed root/docs-ai names, known doc places, heuristics as hints only
# ---------------------------------------------------------------------------

def _read_head(path: Path, max_bytes: int = HEAD_BYTES) -> str:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read(max_bytes)
    except OSError:
        return ""


def _tokens(name: str) -> set[str]:
    return {t for t in _TOKEN_SPLIT_RE.split(name.lower()) if t}


def _path_tokens(stem: str, folders: list[str]) -> set[str]:
    out = _tokens(stem)
    for folder in folders:
        out |= _tokens(folder)
    return out


def _first_heading_tokens(head_text: str) -> set[str]:
    """Only the file's first heading (its title) counts: a section heading such as "## Protokoll
    und Wartung" in a guide says nothing about what the whole file is."""
    for line in head_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return _tokens(stripped.lstrip("#"))
    return set()


def _is_document(rel_posix: str) -> bool:
    return PurePosixPath(rel_posix).suffix.lower() in DOC_EXTENSIONS


def heuristic_hint(root: Path, rel_posix: str) -> Optional[tuple[str, str]]:
    """(hint, reason) if a name/folder/first-heading keyword suggests a class, else None. The
    result is only ever attached to an "unknown" row — it never decides a class."""
    p = PurePosixPath(rel_posix)
    folders = list(p.parts[:-1])
    if p.name.lower() in HINT_AI_CONFIG_NAMES:
        return "ai-config?", f"name '{p.name}' looks like AI configuration, but not at an allow-listed place"
    if HINT_AI_LOG_RE.match(p.name):
        return "log?", f"name '{p.name}' looks like the AI session log, but not at the root"
    tokens = _path_tokens(p.stem, folders)
    for hint, keywords in (("log?", HINT_LOG_TOKENS), ("work?", HINT_WORK_TOKENS)):
        hit = sorted(tokens & keywords)
        if hit:
            return hint, f"name/folder keyword '{hit[0]}'"
    for index, folder in enumerate(folders[:-1]):
        if folder.startswith(".") and folders[index + 1].lower() in HINT_MACHINERY_SEGMENTS:
            return "ai-machinery?", f"folder '{folder}/{folders[index + 1]}' looks like AI tooling"
    if _is_document(rel_posix):
        heading = _first_heading_tokens(_read_head(root / rel_posix))
        for hint, keywords in (("log?", LOG_HEADING_KEYWORDS), ("work?", WORK_HEADING_KEYWORDS)):
            hit = sorted(heading & keywords)
            if hit:
                return hint, f"first heading keyword '{hit[0]}'"
    return None


def _is_doc_place(folders: list[str]) -> bool:
    return any(f.lower() in DOC_PLACE_SEGMENTS or f.lower().endswith(".wiki") for f in folders)


def classify_doc(root: Path, rel_posix: str, signed_ai: bool) -> tuple[str, str, Optional[str], Optional[str]]:
    """(class, reason, note, hint) for one generic candidate."""
    p = PurePosixPath(rel_posix)
    name = p.name
    folders = list(p.parts[:-1])

    # -- allow-list: root --
    if not folders:
        if name in ROOT_LOG or ROOT_LOG_BAK_RE.match(name):
            return "log", "AI session log at the root", None, None
        if name in ROOT_WORK:
            return "work", f"'{name}' at the root", None, None
        if name.upper().startswith(ROOT_DOC_PREFIXES):
            return "project-doc", f"'{name}' at the root", None, None

    # -- an ai-config name below the root (a package's CLAUDE.md, a scaffold template, an archived
    # copy under docs/ai/archive/) is never allow-listed; checked before docs/ai on purpose --
    if folders and name.lower() in HINT_AI_CONFIG_NAMES:
        return ("unknown", f"'{name}' below the root: package config, sample or copy — owner decides",
                None, "ai-config?")

    # -- allow-list: the signed AI work folder --
    if signed_ai and rel_posix.startswith(AI_WORK_DIR + "/"):
        if rel_posix.startswith(SENT_PROTOCOLS_PREFIX):
            return "log", "sent template-feedback protocol (signed docs/ai/)", None, None
        found = heuristic_hint(root, rel_posix)
        hint = found[0] if found else None
        if not _is_document(rel_posix):
            return "unknown", "file in the signed docs/ai/, not a document", "not a document", hint
        tokens = _path_tokens(p.stem, folders[2:])
        log_hit = sorted(tokens & SIGNED_LOG_TOKENS)
        if log_hit:
            return "log", f"signed docs/ai/, name/folder token '{log_hit[0]}'", None, None
        work_hit = sorted(tokens & SIGNED_WORK_TOKENS)
        if work_hit:
            return "work", f"signed docs/ai/, name/folder token '{work_hit[0]}'", None, None
        reason = "signed docs/ai/, no allow-listed name" + (f"; {found[1]}" if found else "")
        return "unknown", reason, None, hint

    # -- known doc places (explicit folders win over any heuristic) --
    if _is_doc_place(folders):
        return "project-doc", "in an ADR or wiki folder", None, None

    # -- heuristics: at most unknown + hint --
    found = heuristic_hint(root, rel_posix)
    if found:
        return "unknown", found[1], None, found[0]

    if any(f.lower() == DOCS_SEGMENT for f in folders):
        return "project-doc", "located under a docs/ folder", None, None

    return "unknown", "docs-like file, no rule matched", None, None


def _is_candidate(rel_posix: str, signed_ai: bool) -> bool:
    p = PurePosixPath(rel_posix)
    folders = list(p.parts[:-1])
    ext = p.suffix.lower()
    if signed_ai and rel_posix.startswith(AI_WORK_DIR + "/"):
        return True
    if not folders and (p.name in ROOT_LOG or ROOT_LOG_BAK_RE.match(p.name) or p.name in ROOT_WORK
                        or p.name.upper().startswith(ROOT_DOC_PREFIXES)):
        return True
    if p.name.lower() in HINT_AI_CONFIG_NAMES or HINT_AI_LOG_RE.match(p.name):
        return True
    if ext == ".txt" and folders and folders[0].lower() != TXT_ALLOWED_TOP_DIR:
        # A bare .txt inside a source or test tree is far more likely a fixture or a template string.
        return False
    return ext in DOC_EXTENSIONS


DESTRUCTIVE_CLASSES = {"ai-config", "ai-machinery", "work", "log"}


def scan_docs(scan: Scan, consumed_files: set[str], candidates: list[str], signed_ai: bool) -> list[Row]:
    root = scan.root
    rows: list[Row] = []
    for rel_posix in candidates:
        if rel_posix in consumed_files or not _is_candidate(rel_posix, signed_ai):
            continue
        if not (root / rel_posix).is_file():
            continue  # e.g. a submodule gitlink or a directory entry from git
        cls, reason, note, hint = classify_doc(root, rel_posix, signed_ai)
        try:
            target = link_target(root, rel_posix) if cls in DESTRUCTIVE_CLASSES else None
            if target:
                rows.append(scan.link_row(rel_posix, target, f"{cls}?"))
            else:
                rows.append(scan.file_row(rel_posix, cls, reason, note=note, hint=hint))
        except OSError:
            continue
    return rows


# ---------------------------------------------------------------------------
# Predecessor-template hint (informational only — never a class, never a row)
# ---------------------------------------------------------------------------

def predecessor_hint(root: Path) -> Optional[str]:
    path = root / ".claude" / "template.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "predecessor template detected (base_commit unknown — template.json not readable)"
    base_commit = data.get("base_commit") if isinstance(data, dict) else None
    return f"predecessor template detected (base_commit {base_commit or 'unknown'})"


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

CLASS_ORDER = ["ai-config", "ai-machinery", "work", "log", "project-doc", "unknown"]


def run(root: Path) -> tuple[list[Row], Optional[str], list[str]]:
    git_list = list_git_candidates(root)
    git_dirs: set[str] = set()
    for path in git_list or ():
        parts = path.split("/")
        git_dirs.update("/".join(parts[:i]) for i in range(1, len(parts)))
    scan = Scan(root=root, git_dates=build_git_dates(root),
                git_files=set(git_list) if git_list is not None else None, git_dirs=git_dirs)
    submodules = list_submodules(root)
    blocked = list(submodules)
    link_rows: list[Row] = []
    if _exists_exact(root, AI_WORK_DIR, want_dir=True):
        target = link_target(root, AI_WORK_DIR)
        if target:
            blocked.append(AI_WORK_DIR)
            link_rows.append(scan.link_row(AI_WORK_DIR, target, None))
    signed_ai = is_signed_ai_folder(root)
    candidates, ai_links = list_candidates(scan, git_list, signed_ai, blocked)
    link_rows += [scan.link_row(rel, entry_link(root / rel) or "?", None) for rel in ai_links]
    config_rows, consumed = scan_ai_config(scan)
    machinery_rows = scan_ai_machinery(scan)
    doc_rows = scan_docs(scan, consumed, candidates, signed_ai)
    rows = config_rows + machinery_rows + doc_rows + link_rows
    rows.sort(key=lambda r: (CLASS_ORDER.index(r.cls) if r.cls in CLASS_ORDER else len(CLASS_ORDER), r.path))
    info = [f"not scanned: submodule {path}" for path in submodules]
    return rows, predecessor_hint(root), info


def write_scan_json(root: Path, rows: list[Row], hint: Optional[str], info: list[str]) -> dict:
    payload = {
        "target": str(root),
        "generated": datetime.now().isoformat(timespec="seconds"),
        "predecessor_hint": hint,
        "info": info,
        "rows": [r.as_dict() for r in rows],
        "counts": {cls: sum(1 for r in rows if r.cls == cls) for cls in CLASS_ORDER},
    }
    dest = root / ".act-local" / "adopt" / "scan.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def render_human(rows: list[Row], hint: Optional[str], info: list[str]) -> str:
    lines: list[str] = []
    if hint:
        lines.append(f"-- {hint} --")
    lines.extend(f"-- {line} --" for line in info)
    if hint or info:
        lines.append("")
    for cls in CLASS_ORDER:
        group = [r for r in rows if r.cls == cls]
        if not group:
            continue
        lines.append(f"== {cls} ({len(group)}) ==")
        for r in group:
            suffix = f"  (note: {r.note})" if r.note else ""
            suffix += f"  (hint: {r.hint})" if r.hint else ""
            lines.append(f"{r.path}  [{r.kind}]  size={r.size}  age={r.age}  -- {r.reason}{suffix}")
        lines.append("")
    lines.append(f"{len(rows)} source(s) sighted.")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

EPILOG = """\
ALLOW-LIST (exact, case-sensitive) — the only way into the four classes with a downstream action:
  ai-config     root AGENTS.md CLAUDE.md CLAUDE.local.md GEMINI.md CONVENTIONS.md AI-CONFIG.md
                .aider.conf.yml .cursorrules .clinerules .windsurfrules .mcp.json;
                .github/copilot-instructions.md, .github/instructions/*.instructions.md,
                .claude/settings.json, .claude/settings.local.json (never bridge or delete),
                .claude/settings.local.json.example, .claude/rules/*.md, .cursor/rules/,
                .cursor/mcp.json, .gemini/settings.json, .junie/guidelines.md (never a nested one)
  ai-machinery  one row per unit under .claude/{agents,skills,commands,scripts,hooks}/,
                .github/agents/, .github/prompts/, .codex/{agents,skills,commands,scripts,hooks}/,
                .gemini/commands/, and .cursor/ except rules/ and mcp.json
  log           root ai.log, ai.log.*.bak, ai.log.state.json, ai.log.raw.jsonl; in a signed
                docs/ai/: names with ledger/journal/protokoll/archive/archiv, template-feedback/sent/**
  work          root TODO.md, TODO; in a signed docs/ai/: names with task(s)/aufgabe(n)/backlog/
                question(s)/frage(n)/board/inbox
Signed docs/ai/: holds at least two of board.md, tasks.md, ledger.md, questions.md, backlog.md,
or the target has .claude/template.json. Any keyword hit elsewhere yields only "unknown" with a
hint ("log?"). A symlink/junction at an allow-listed place is one "unknown" row ("link to …"),
never followed. Git-ignored rows keep their class and get a "git-ignored/local" note.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adopt_scan.py",
        description="Read-only sighting of an existing project's documentation/AI-tooling sources before adoption.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--target", metavar="DIR", help="directory to scan (default: this project's root)")
    parser.add_argument("--json", action="store_true", help="print the JSON payload instead of the human-readable table")
    return parser


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    args = build_parser().parse_args(argv)

    try:
        root = resolve_target(args.target)
    except RuntimeError as exc:
        print(f"adopt_scan.py: {exc}", file=sys.stderr)
        return 2

    if not root.is_dir():
        print(f"adopt_scan.py: target is not a directory: {root}", file=sys.stderr)
        return 2

    rows, hint, info = run(root)
    payload = write_scan_json(root, rows, hint, info)

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        sys.stdout.write(render_human(rows, hint, info))

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
