#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Generate the per-branch board at .act-local/board-<branch>.md — a fully derived
#          snapshot (current branch, last commit, dirty state, recent journal entries, waiting
#          inbox items, open tasks). Nothing here is hand-maintained; every run overwrites the
#          file from scratch. Stdlib only.
#
# Usage:
#   python .act/scripts/board.py
#
# Output format:
#   Writes .act-local/board-<branch>.md (gitignored) and prints one summary line to stdout,
#   e.g. "board: wrote .act-local/board-next.md (branch=next, ledger=3, waiting=2, tasks=5)".
#
# Filename encoding for the branch name: branch names may contain "/" (e.g. "feature/login"),
# which is not valid inside a single path segment on any platform this template targets. The
# branch name is therefore percent-encoded before it is used in the filename, applied in this
# order so the substitution stays unique and reversible:
#   1. "%" -> "%25"
#   2. "/" -> "%2F"
# ("feature/login" -> "board-feature%2Flogin.md"). This is why a plain `git switch` never shows
# the other branch's board: each branch gets its own file, keyed by this encoding.
#
# Missing sources are not an error: if there is no git repository, no journal and no inbox, the
# corresponding section of the board is left out and the file is still written.

from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import actlib

LEDGER_DIR = Path("docs/ai/work/ledger")
LEDGER_FALLBACK = Path("docs/ai/work/ledger.md")
LEDGER_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)\.md$")
INBOX_DIR = Path("docs/ai/inbox")
TASKS_DIR = Path("docs/ai/work/tasks")
FOR_RE = re.compile(r"(?im)^for:\s*(.+?)\s*$")

LEDGER_LIMIT = 10
TASKS_LIMIT = 5


# ---------------------------------------------------------------------------
# Filename encoding
# ---------------------------------------------------------------------------

def sanitize_branch(branch: str) -> str:
    """Percent-encode a branch name into a single, filesystem-safe path segment. See the header
    comment for the exact rule and why it is reversible."""
    return branch.replace("%", "%25").replace("/", "%2F")


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

def run_git(args: list[str], root: Path) -> Optional[str]:
    """Run `git <args>` in `root`. Returns stdout on success, None on any failure (git missing,
    not a repository, command exits non-zero) — callers treat that as "source unavailable"."""
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout


def get_branch(root: Path) -> Optional[str]:
    """Return the current branch name, or None if this is not a git repository. Works even
    before the first commit (git symbolic-ref only reads the ref pointer, not its target)."""
    output = run_git(["symbolic-ref", "--quiet", "--short", "HEAD"], root)
    if output and output.strip():
        return output.strip()
    output = run_git(["rev-parse", "--abbrev-ref", "HEAD"], root)
    if output and output.strip() and output.strip() != "HEAD":
        return output.strip()
    return None


def get_last_commit(root: Path) -> Optional[dict[str, str]]:
    """Return {"hash", "subject", "date"} for the last commit, or None if there is no commit yet
    (or no repository)."""
    output = run_git(["log", "-1", "--format=%h\x1f%s\x1f%as"], root)
    if not output:
        return None
    line = output.strip("\n")
    parts = line.split("\x1f")
    if len(parts) != 3:
        return None
    short_hash, subject, date = parts
    return {"hash": short_hash, "subject": subject, "date": date}


def has_changes(root: Path) -> Optional[bool]:
    """True if the working tree has uncommitted changes, False if clean, None if this is not a
    git repository."""
    output = run_git(["status", "--porcelain"], root)
    if output is None:
        return None
    return bool(output.strip())


# ---------------------------------------------------------------------------
# Sources under docs/ai/
# ---------------------------------------------------------------------------

def _first_heading(path: Path) -> Optional[str]:
    """Return the text of the first Markdown heading ("# ...") in `path`, or None if there is
    none (or the file cannot be read)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return None


def read_ledger_entries(root: Path, limit: int = LEDGER_LIMIT) -> Optional[list[str]]:
    """
    Return up to `limit` "<date> — <title>" strings, newest first, or None if neither ledger
    source exists.

    Primary source: one file per entry under docs/ai/work/ledger/, named YYYY-MM-DD-<slug>.md.
    Sorting filenames in reverse gives newest-first, since the date prefix sorts lexically. The
    title is the file's first Markdown heading, or the slug with hyphens turned into spaces if
    the file has none.

    Fallback: if docs/ai/work/ledger/ does not exist but docs/ai/work/ledger.md does, its first
    `limit` non-blank lines are taken verbatim (the single-file ledger already lists newest-first,
    per AGENTS.md § Grundregeln).
    """
    ledger_dir = root / LEDGER_DIR
    if ledger_dir.is_dir():
        files = sorted(
            (p for p in ledger_dir.glob("*.md") if LEDGER_FILENAME_RE.match(p.name)),
            key=lambda p: p.name,
            reverse=True,
        )
        entries = []
        for path in files[:limit]:
            match = LEDGER_FILENAME_RE.match(path.name)
            date, slug = match.group(1), match.group(2)
            title = _first_heading(path) or slug.replace("-", " ")
            entries.append(f"{date} — {title}")
        return entries

    fallback = root / LEDGER_FALLBACK
    if fallback.is_file():
        try:
            lines = fallback.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        non_blank = [line.strip() for line in lines if line.strip()]
        return non_blank[:limit]

    return None


def read_inbox_counts(root: Path, identity: Optional[str]) -> Optional[dict[str, int]]:
    """
    Count entries in docs/ai/inbox/ by recipient, or None if that directory does not exist.

    Each file's "for: <value>" line (first match, case-insensitive, anywhere in the file) is
    read and sorted into one of three buckets:
      - "mine": value matches `identity` (case-insensitive)
      - "all": value is "all"
      - "other": everything else, including a file with no "for:" line at all

    If `identity` is None (no .act-local/identity.json yet), nothing can match "mine" and those
    entries fall into "other" instead.
    """
    inbox_dir = root / INBOX_DIR
    if not inbox_dir.is_dir():
        return None

    counts = {"mine": 0, "all": 0, "other": 0}
    for path in inbox_dir.glob("*.md"):
        if path.name.lower() == "readme.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        match = FOR_RE.search(text)
        target = match.group(1).strip() if match else None
        if target and target.lower() == "all":
            counts["all"] += 1
        elif target and identity and target.lower() == identity.lower():
            counts["mine"] += 1
        else:
            counts["other"] += 1
    return counts


def read_task_titles(root: Path, limit: int = TASKS_LIMIT) -> Optional[list[str]]:
    """Return up to `limit` task titles from docs/ai/work/tasks/ (filename order — task ids are
    expected to sort meaningfully, e.g. T01-..., T02-...), or None if the directory does not
    exist. Title is the file's first Markdown heading, or the filename stem if there is none."""
    tasks_dir = root / TASKS_DIR
    if not tasks_dir.is_dir():
        return None
    files = sorted(p for p in tasks_dir.glob("*.md") if p.name.lower() != "readme.md")
    return [(_first_heading(path) or path.stem) for path in files[:limit]]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_board(
    branch_label: str,
    commit: Optional[dict[str, str]],
    dirty: Optional[bool],
    ledger_entries: Optional[list[str]],
    inbox_counts: Optional[dict[str, int]],
    task_titles: Optional[list[str]],
    generated_at: str,
) -> str:
    lines: list[str] = [f"# Board — {branch_label}", ""]

    if commit is not None or dirty is not None:
        lines.append("## Status")
        lines.append(f"- Branch: `{branch_label}`")
        if commit:
            lines.append(f"- Last commit: `{commit['hash']}` — {commit['subject']} ({commit['date']})")
        else:
            lines.append("- Last commit: n/a (no commits yet)")
        if dirty is not None:
            lines.append(f"- Working tree: {'has uncommitted changes' if dirty else 'clean'}")
        lines.append("")

    if ledger_entries is not None:
        lines.append("## Recent activity")
        if ledger_entries:
            lines.extend(f"- {entry}" for entry in ledger_entries)
        else:
            lines.append("- (none yet)")
        lines.append("")

    if inbox_counts is not None:
        lines.append("## Waiting")
        lines.append(f"- For me: {inbox_counts['mine']}")
        lines.append(f"- For everyone: {inbox_counts['all']}")
        lines.append(f"- For others: {inbox_counts['other']}")
        lines.append("")

    if task_titles is not None:
        lines.append("## Open tasks")
        if task_titles:
            lines.extend(f"- {title}" for title in task_titles)
        else:
            lines.append("- (none)")
        lines.append("")

    lines.append("---")
    lines.append(f"Generated {generated_at}. This file is generated — edits here are lost on the next run.")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    # Board content can carry an em dash (ledger entries, commit subjects); on Windows,
    # stdout/stderr otherwise default to the console's legacy code page instead of UTF-8, which
    # would corrupt it. Same fix as .act/scripts/rules.py.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    if argv:
        print("usage: board.py", file=sys.stderr)
        return 2

    root = actlib.repo_root()

    branch = get_branch(root)
    commit = get_last_commit(root) if branch is not None else None
    dirty = has_changes(root) if branch is not None else None
    branch_label = branch if branch is not None else "(no git)"
    filename = f"board-{sanitize_branch(branch) if branch is not None else 'no-git'}.md"

    identity_data = actlib.read_identity()
    my_identity = identity_data.get("identity") if identity_data else None

    ledger_entries = read_ledger_entries(root)
    inbox_counts = read_inbox_counts(root, my_identity)
    task_titles = read_task_titles(root)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    content = render_board(
        branch_label, commit, dirty, ledger_entries, inbox_counts, task_titles, generated_at,
    )

    board_path = root / ".act-local" / filename
    board_path.parent.mkdir(parents=True, exist_ok=True)
    board_path.write_text(content, encoding="utf-8")

    ledger_count = len(ledger_entries) if ledger_entries is not None else 0
    waiting_total = sum(inbox_counts.values()) if inbox_counts is not None else 0
    task_count = len(task_titles) if task_titles is not None else 0
    rel = board_path.relative_to(root).as_posix()
    print(
        f"board: wrote {rel} (branch={branch_label}, ledger={ledger_count}, "
        f"waiting={waiting_total}, tasks={task_count})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
