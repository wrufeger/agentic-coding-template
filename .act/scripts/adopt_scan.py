#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Read-only sighting of an existing project's documentation and AI-tooling material,
#          before adoption (skill `act-adopt`). Walks the target tree and classifies
#          every documentation-like file and every AI-tool unit (agent, skill, command, script,
#          hook) it finds into one of: ai-config, ai-machinery, work, log, project-doc, predecessor
#          (a part of the previous template, see PREDECESSOR in the help text), unknown.
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
#          "never bridge"; a tracked unit folder with git-ignored files inside carries "contains
#          git-ignored files: <first>". Several notes on one row are joined with "; ".
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
#     (plus " (note: <note>)" and/or " (hint: <class>?)" when a row carries one, "  [<origin>]" with
#     a predecessor template, and "  -> <proposed action>"), a per-class count
#     line, one informational line per git submodule ("not scanned: submodule <path>"), and — if
#     the target has a predecessor template (a .claude/template.json) — one hint line naming its
#     base_commit. Never a finding/judgement, just a sighting.
#   --json: the same content as {"target", "generated", "predecessor_hint", "info": [...],
#     "rows": [...], "counts": {<class>: <n>, ...}}, one object per row: {"path", "kind", "size",
#     "age", "class", "reason", "note", "hint", "origin", "proposed"} (note/hint/origin are null
#     unless set; proposed is the starting point of the table, never binding). This is exactly
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
# A tracked unit folder with git-ignored files inside (never the whole folder ignored — that is
# LOCAL_NOTE): moved or removed only with the owner's confirmation, the files rescued first.
IGNORED_INSIDE_NOTE = "contains git-ignored files"
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
# ADR and wiki folders (plus any "<name>.wiki" folder, a GitHub wiki clone): an ADR folder is often
# named decisions/ (notes/decisions/0001-use-sqlite.md), never only adr/.
DOC_PLACE_SEGMENTS = {"adr", "adrs", "decisions", "decision-records", "wiki"}
DOCS_SEGMENT = "docs"

# log: a dated file (name starts YYYY-MM-DD) in a journal folder at the root or directly in docs/
# — two signals together, so a blog's content/journal/ (a content tree) never matches.
JOURNAL_DIRS = ("journal/", "journals/", "docs/journal/", "docs/journals/")
DATED_NAME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


# ---------------------------------------------------------------------------
# Predecessor template — a project made from the previous template carries .claude/template.json
# (base_commit, the placeholder values). Its own files are class "predecessor"; every row gets an
# "origin" compared with the base_commit and a proposed action.
# ---------------------------------------------------------------------------

PREDECESSOR_FILE = ".claude/template.json"
# Parts of the previous template's tooling that are no documents — sighted by name, proposed delete.
PREDECESSOR_TOOL_FILES = {".mcp.json.example", ".claude/mcp-katalog.md"}
# Its example files among the ai-config rows: proposed delete as well.
PREDECESSOR_EXAMPLES = {".claude/settings.local.json.example"}
# Its documentation, known by name — used even when the base_commit is not reachable.
PREDECESSOR_DOCS = {
    "docs/ai/README.md", "docs/ai/checklists.md", "docs/ai/config-guide.md",
    "docs/ai/ai-config-hilfe.md", "docs/ai/resources.md",
}
PREDECESSOR_PREFIXES = ("docs/ai/template-feedback/",)
PLACEHOLDER_RE = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")
ORIGIN_TEMPLATE = "template only"
ORIGIN_UNKNOWN = "unknown (base_commit not reachable)"

# Places init.py writes itself: an old file there is proposed adopt (merged into the template's
# version), or legacy when it holds nothing of its own.
INIT_WRITES = {"docs/README.md", "docs/project/coding_rules.md"}
SKILL_AGENT_PARENTS = {".claude/skills", ".codex/skills", ".claude/agents", ".codex/agents", ".github/agents"}


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
    origin: Optional[str] = None    # with a predecessor template: "template only" | "own text: n lines" | unknown
    proposed: Optional[str] = None  # the proposed action (adopt | legacy | keep | delete), never binding

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
        elif self.git_files is not None and rel in self.git_dirs:
            # Part of the unit is tracked, part only on disk (a local credentials file next to a
            # skill): adopt.py refuses to move or remove the unit without an explicit confirmation.
            ignored = [f for f in files if not f.endswith((".pyc", ".pyo")) and f not in self.git_files]
            if ignored:
                note = f"{IGNORED_INSIDE_NOTE}: {ignored[0]}" + (f" (+{len(ignored) - 1})" if len(ignored) > 1 else "")
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

    # -- allow-list: a dated file in a journal folder at the root or directly in docs/ --
    if rel_posix.startswith(JOURNAL_DIRS) and DATED_NAME_RE.match(name) and _is_document(rel_posix):
        return "log", "dated file in a journal folder", None, None

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

def predecessor_hint(root: Path, pred: Optional["Predecessor"] = None) -> Optional[str]:
    path = root / ".claude" / "template.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "predecessor template detected (base_commit unknown — template.json not readable)"
    base_commit = data.get("base_commit") if isinstance(data, dict) else None
    reach = ""
    if pred is not None and base_commit:
        reach = ", in the history" if pred.tree is not None else ", NOT in the history: origin unknown"
    return f"predecessor template detected (base_commit {base_commit or 'unknown'}{reach})"


@dataclass
class Predecessor:
    base_commit: Optional[str]
    values: dict             # placeholder name -> the value the project put in (template.json § values)
    tree: Optional[set]      # files of the base_commit, relative to the scan root; None: not reachable
    repo_top: Optional[Path]
    prefix: str              # the scan root relative to repo_top ("" at the toplevel)

    def is_part(self, rel: str) -> bool:
        return (rel in PREDECESSOR_DOCS or rel in PREDECESSOR_TOOL_FILES or rel.startswith(PREDECESSOR_PREFIXES)
                or (self.tree is not None and rel in self.tree))


def load_predecessor(root: Path) -> Optional[Predecessor]:
    """The predecessor template, if the target has a .claude/template.json (not a link). Its
    base_commit tree is read with one `git ls-tree` call; tree None if the commit is not in the
    target's history (a shallow clone, a squashed import) — origins then say "unknown"."""
    if not _exists_exact(root, PREDECESSOR_FILE) or link_target(root, PREDECESSOR_FILE):
        return None
    try:
        data = json.loads((root / PREDECESSOR_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    data = data if isinstance(data, dict) else {}
    base = data.get("base_commit") if isinstance(data.get("base_commit"), str) else None
    raw_values = data.get("values") if isinstance(data.get("values"), dict) else {}
    values = {str(k): str(v) for k, v in raw_values.items() if isinstance(v, (str, int, float))}
    repo_top = _git_repo_top(root)
    prefix = _relative_prefix(root, repo_top) if repo_top else None
    pred = Predecessor(base_commit=base, values=values, tree=None, repo_top=repo_top, prefix=prefix or "")
    if not base or repo_top is None or prefix is None:
        return pred
    try:
        result = subprocess.run(["git", "-c", "core.quotePath=false", "-C", str(repo_top), "ls-tree", "-r",
                                 "-z", "--name-only", f"{base}^{{commit}}"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.SubprocessError):
        return pred
    if result.returncode != 0:
        return pred
    head = f"{prefix}/" if prefix else ""
    pred.tree = {p[len(head):] for p in result.stdout.split("\0") if p and p.startswith(head)}
    return pred


def read_base_texts(pred: Predecessor, paths: list[str]) -> dict[str, str]:
    """path -> its text in the base_commit, for every path of `paths` in the base tree (one
    `git cat-file --batch` call)."""
    wanted = [p for p in dict.fromkeys(paths) if pred.tree is not None and p in pred.tree]
    if not wanted or pred.repo_top is None:
        return {}
    head = f"{pred.prefix}/" if pred.prefix else ""
    request = "".join(f"{pred.base_commit}:{head}{p}\n" for p in wanted).encode("utf-8")
    try:
        result = subprocess.run(["git", "-C", str(pred.repo_top), "cat-file", "--batch"],
                                input=request, capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return {}
    out, pos, texts = result.stdout, 0, {}
    for path in wanted:
        end = out.find(b"\n", pos)
        if end < 0:
            break
        header = out[pos:end].split()
        pos = end + 1
        if len(header) < 3 or header[1] != b"blob":
            continue
        size = int(header[2])
        texts[path] = out[pos:pos + size].decode("utf-8", errors="replace")
        pos += size + 1
    return texts


def _norm_lines(text: str) -> list[str]:
    return [line.rstrip() for line in text.splitlines() if line.strip()]


def own_line_count(current: str, base: Optional[str], values: dict) -> int:
    """Non-blank lines of `current` found neither in the base text as the template wrote it nor
    with the project's values put in for its {{PLACEHOLDERS}} — lines the predecessor's own
    setup or updates removed never count as own text."""
    if base is None:
        return len(_norm_lines(current))
    filled = PLACEHOLDER_RE.sub(lambda m: values.get(m.group(1), m.group(0)), base)
    known = set(_norm_lines(base)) | set(_norm_lines(filled))
    # Independent of line breaks: a value longer or shorter than its placeholder re-wraps the
    # paragraph, so a line that is a stretch of one of the base's paragraphs (whitespace
    # collapsed) is no own text either — only for lines long enough not to match by chance.
    corpus = "\n".join(_paragraphs(base) + _paragraphs(filled))
    count = 0
    for line in _norm_lines(current):
        words = " ".join(line.split())
        if line in known or (len(words) >= REWRAP_MIN and words in corpus):
            continue
        count += 1
    return count


REWRAP_MIN = 20  # shorter lines only count as the template's when they match a whole line


def _paragraphs(text: str) -> list[str]:
    """Runs of non-blank lines, each joined into one line with its whitespace collapsed."""
    out, current = [], []
    for line in text.splitlines():
        if line.strip():
            current.append(line.strip())
        elif current:
            out.append(" ".join(" ".join(current).split()))
            current = []
    if current:
        out.append(" ".join(" ".join(current).split()))
    return out


def _row_files(root: Path, row: Row) -> list[str]:
    if row.kind == "file":
        return [row.path]
    return [f for f in _walk_files(root, root / row.path, {"__pycache__"}, [])
            if not f.endswith((".pyc", ".pyo"))]


def set_origins(root: Path, pred: Predecessor, rows: list[Row]) -> None:
    """row.origin for every row that is not a link: "template only" when every line is the
    predecessor's (after putting its values in), "own text: n lines" otherwise, unknown when the
    base_commit is not in the history."""
    targets = [r for r in rows if not (r.note and ("link to " in r.note or "contains link " in r.note))]
    if pred.tree is None:
        for r in targets:
            r.origin = ORIGIN_UNKNOWN
        return
    files = {r.path: _row_files(root, r) for r in targets}
    base_paths = {p for r in targets for p in files[r.path]}
    if any(r.kind == "dir" for r in targets):
        base_paths |= {p for p in pred.tree for r in targets if r.kind == "dir" and p.startswith(r.path + "/")}
    texts = read_base_texts(pred, sorted(base_paths))
    for r in targets:
        own = 0
        for rel in files[r.path]:
            try:
                current = (root / rel).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            own += own_line_count(current, texts.get(rel), pred.values)
        in_base = any(p in pred.tree for p in files[r.path])
        if own == 0 and in_base:
            r.origin = ORIGIN_TEMPLATE
        else:
            r.origin = f"own text: {own} line{'s' if own != 1 else ''}" + ("" if in_base else " (not in the predecessor template)")


# ---------------------------------------------------------------------------
# Proposed action per row — what the table starts from; the owner decides
# ---------------------------------------------------------------------------

def propose(row: Row, pred: Optional[Predecessor]) -> str:
    note, origin, path = row.note or "", row.origin or "", row.path
    template_only = origin == ORIGIN_TEMPLATE
    own = origin.startswith("own text")
    if any(marker in note for marker in ("never bridge", "git-ignored/local", "local, git-ignored",
                                          "link to ", "contains link ")):
        return "keep"
    if row.cls in ("log", "work"):
        return "legacy"
    if row.cls == "ai-config":
        if path in (".claude/settings.json", SETTINGS_LOCAL):
            return "keep"  # init.py merges its hook entries into settings.json
        if path in PREDECESSOR_EXAMPLES:
            return ("delete" if template_only else "legacy") if pred else "keep"
        return "legacy" if template_only else "adopt"
    if row.cls == "ai-machinery":
        if template_only:
            return "delete"
        if pred and not own:
            return "keep"  # origin unknown: nothing is proposed for removal blind
        return "adopt" if str(PurePosixPath(path).parent) in SKILL_AGENT_PARENTS else "keep"
    if row.cls == "project-doc":
        if path in INIT_WRITES:
            return "legacy" if template_only else "adopt"
        return "keep"  # a root README.md too: init.py never replaces a foreign one, adopt into it is refused
    if row.cls == "predecessor":
        if (path in PREDECESSOR_TOOL_FILES or not _is_document(path)) and template_only:
            return "delete"  # with own text (own MCP servers in an example): legacy, as below
        return "legacy"  # its docs stay readable in the archive; own lines show in the origin
    return "keep"


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

CLASS_ORDER = ["ai-config", "ai-machinery", "work", "log", "project-doc", "predecessor", "unknown"]


def mark_predecessor(scan: Scan, pred: Predecessor, rows: list[Row]) -> list[Row]:
    """Rows that would be "unknown" but are the predecessor template's own files become class
    "predecessor"; its non-document tooling (PREDECESSOR_TOOL_FILES) is sighted here by name."""
    seen = {r.path for r in rows}
    for r in rows:
        if r.cls == "unknown" and pred.is_part(r.path) and not (r.note and "link" in r.note):
            where = "in its base_commit" if pred.tree is not None and r.path in pred.tree else "a known part"
            r.cls, r.reason, r.hint = "predecessor", f"part of the predecessor template ({where})", None
    for rel in sorted(PREDECESSOR_TOOL_FILES - seen):
        if _exists_exact(scan.root, rel) and not link_target(scan.root, rel):
            rows.append(scan.file_row(rel, "predecessor", "tooling file of the predecessor template"))
    return rows


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
    pred = load_predecessor(root)
    if pred is not None:
        rows = mark_predecessor(scan, pred, rows)
        set_origins(root, pred, rows)
    for r in rows:
        r.proposed = propose(r, pred)
    rows.sort(key=lambda r: (CLASS_ORDER.index(r.cls) if r.cls in CLASS_ORDER else len(CLASS_ORDER), r.path))
    info = [f"not scanned: submodule {path}" for path in submodules]
    return rows, predecessor_hint(root, pred), info


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
            suffix += f"  [{r.origin}]" if r.origin else ""
            suffix += f"  -> {r.proposed}" if r.proposed else ""
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
                docs/ai/: names with ledger/journal/protokoll/archive/archiv, template-feedback/sent/**;
                a dated file (YYYY-MM-DD*) in journal(s)/ or docs/journal(s)/
  work          root TODO.md, TODO; in a signed docs/ai/: names with task(s)/aufgabe(n)/backlog/
                question(s)/frage(n)/board/inbox
Signed docs/ai/: holds at least two of board.md, tasks.md, ledger.md, questions.md, backlog.md,
or the target has .claude/template.json. Any keyword hit elsewhere yields only "unknown" with a
hint ("log?"). A symlink/junction at an allow-listed place is one "unknown" row ("link to …"),
never followed. Git-ignored rows keep their class and get a "git-ignored/local" note.
project-doc also covers ADR folders: adr/, adrs/, decisions/, decision-records/.

PREDECESSOR (the target has .claude/template.json): a row that would be "unknown" but is in the
base_commit tree, or is one of the predecessor's known parts (docs/ai/README.md, checklists.md,
config-guide.md, ai-config-hilfe.md, resources.md, template-feedback/, .claude/mcp-katalog.md,
.mcp.json.example), is class "predecessor". Every row gets an origin: "template only" (each line
is the base_commit's, after putting in the values of template.json § values; lines removed since
do not count), "own text: n lines", or "unknown" when the base_commit is not in the history.

PROPOSED ACTION (column "-> …", JSON "proposed"; the owner decides): log, work -> legacy;
ai-config -> adopt, legacy if template only, keep for .claude/settings*.json and protected rows,
for .claude/settings.local.json.example of a predecessor delete if template only, else legacy;
ai-machinery -> delete if
template only, keep if its origin is unknown, else adopt (skills, agents) or keep (the rest);
project-doc -> keep (a root README.md too), docs/README.md and docs/project/coding_rules.md adopt
(legacy if template only); predecessor -> delete (tooling, examples: template only), else legacy
(docs, own lines included — the origin shows them); unknown -> keep. A link or protected row is
always keep. Line breaks do not count: a line that is a stretch of a base paragraph (whitespace
collapsed, at least 20 characters) is the template's.
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
