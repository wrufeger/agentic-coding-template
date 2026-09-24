#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Generate the per-branch board at .act-local/board-<branch>.md — a fully derived
#          snapshot (current branch, last commit, dirty state, recent journal entries, waiting
#          inbox items plus open questions, open tasks, backlog items). Nothing here is
#          hand-maintained; every run overwrites the file from scratch. Stdlib only.
#
#          `--chat-language` instead remembers the chat language recognized for this person on
#          this machine while `language-chat` is `auto` (R-human-language) — per checkout in
#          .act-local/identity.json, never versioned; the session start names it again.
#
# Usage:
#   python .act/scripts/board.py
#   python .act/scripts/board.py --chat-language de   # remember the owner's chat language here
#
# Output format:
#   Writes .act-local/board-<branch>.md (gitignored) and prints one summary line to stdout,
#   e.g. "board: wrote .act-local/board-next.md (branch=next, ledger=3, waiting=2, tasks=5)".
#   --chat-language: one line "board: chat language '<code>' remembered ..."; exit 2 if the value
#   is no language code.
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

import argparse
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
BACKLOG_DIR = Path("docs/ai/work/backlog")
QUESTIONS_DIR = Path("docs/ai/questions")
FOR_RE = re.compile(r"(?im)^for:\s*(.+?)\s*$")
STATUS_RE = re.compile(r"(?im)^status:\s*(\S+)\s*$")
ID_RE = re.compile(r"(?im)^id:\s*(\S+)\s*$")

LEDGER_LIMIT = 10
TASKS_LIMIT = 5
BACKLOG_LIMIT = 5
QUESTIONS_LIMIT = 10


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
    none (or the file cannot be read, or is not valid UTF-8)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
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
    `limit` non-blank lines are taken verbatim (the single-file ledger already lists newest-first).
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
        except (OSError, UnicodeDecodeError):
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
        except (OSError, UnicodeDecodeError):
            continue
        match = FOR_RE.search(actlib.header_block(text))
        target = match.group(1).strip() if match else None
        if target and target.lower() == "all":
            counts["all"] += 1
        elif target and identity and target.lower() == identity.lower():
            counts["mine"] += 1
        else:
            counts["other"] += 1
    return counts


def read_task_titles(root: Path, limit: int = TASKS_LIMIT) -> Optional[list[str]]:
    """Return up to `limit` task titles from docs/ai/work/tasks/ (filename order, oldest first —
    the date prefix already sorts them chronologically), or None if the directory does not exist.
    Title is the file's first Markdown heading, or the filename stem if there is none."""
    tasks_dir = root / TASKS_DIR
    if not tasks_dir.is_dir():
        return None
    files = sorted(p for p in tasks_dir.glob("*.md") if p.name.lower() != "readme.md")
    return [(_first_heading(path) or path.stem) for path in files[:limit]]


def read_backlog_titles(root: Path, limit: int = BACKLOG_LIMIT) -> Optional[list[str]]:
    """Same idea as read_task_titles(), for docs/ai/work/backlog/."""
    backlog_dir = root / BACKLOG_DIR
    if not backlog_dir.is_dir():
        return None
    files = sorted(p for p in backlog_dir.glob("*.md") if p.name.lower() != "readme.md")
    return [(_first_heading(path) or path.stem) for path in files[:limit]]


def read_questions(
    root: Path, limit: int = QUESTIONS_LIMIT,
) -> tuple[Optional[list[str]], Optional[list[str]]]:
    """
    Return (open, answered) — each up to `limit` "<id or filename> — <title>" strings from
    docs/ai/questions/, newest first — or (None, None) if that directory does not exist.

    An entry counts as open unless its "status:" header field reads "answered" (case-insensitive)
    — a missing status field is treated as open too, so a question filed but not yet marked still
    shows up. An answered question is still shown, in its own list — R-work-record-now says the
    assistant processes it, not that it vanishes from the board. The id shown is the assigned
    "id:" field if there is one, else the filename stem (an entry not yet integrated has no id —
    Q65c/Q66).
    """
    questions_dir = root / QUESTIONS_DIR
    if not questions_dir.is_dir():
        return None, None
    open_entries: list[str] = []
    answered_entries: list[str] = []
    for path in sorted(questions_dir.glob("*.md"), reverse=True):
        if path.name.lower() == "readme.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        header = actlib.header_block(text)
        status_match = STATUS_RE.search(header)
        answered = bool(status_match and status_match.group(1).strip().lower() == "answered")
        id_match = ID_RE.search(header)
        label = id_match.group(1) if id_match else path.stem
        title = _first_heading(path) or path.stem
        entry = f"{label} — {title}"
        target = answered_entries if answered else open_entries
        if len(target) < limit:
            target.append(entry)
    return open_entries, answered_entries


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def render_board(
    branch_label: str,
    commit: Optional[dict[str, str]],
    dirty: Optional[bool],
    ledger_entries: Optional[list[str]],
    inbox_counts: Optional[dict[str, int]],
    open_questions: Optional[list[str]],
    answered_questions: Optional[list[str]],
    task_titles: Optional[list[str]],
    backlog_titles: Optional[list[str]],
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

    if inbox_counts is not None or open_questions is not None:
        lines.append("## Waiting")
        if inbox_counts is not None:
            lines.append(f"- For me: {inbox_counts['mine']}")
            lines.append(f"- For everyone: {inbox_counts['all']}")
            lines.append(f"- For others: {inbox_counts['other']}")
        if open_questions is not None:
            lines.append(f"- Open questions: {len(open_questions)}")
            lines.extend(f"  - {entry}" for entry in open_questions)
        if answered_questions is not None:
            lines.append(f"- Answered — the assistant processes these: {len(answered_questions)}")
            lines.extend(f"  - {entry}" for entry in answered_questions)
        lines.append("")

    if task_titles is not None:
        lines.append("## Open tasks")
        if task_titles:
            lines.extend(f"- {title}" for title in task_titles)
        else:
            lines.append("- (none)")
        lines.append("")

    if backlog_titles is not None:
        lines.append("## Backlog")
        if backlog_titles:
            lines.extend(f"- {title}" for title in backlog_titles)
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

    parser = argparse.ArgumentParser(
        prog="board.py", description="Write the per-branch board to .act-local/board-<branch>.md.")
    parser.add_argument("--chat-language", metavar="CODE",
                        help="remember the chat language recognized for this person on this machine "
                             "(.act-local/identity.json) while language-chat is auto, then exit")
    args = parser.parse_args(argv)

    root = actlib.repo_root()

    if args.chat_language is not None:
        code = actlib.normalize_language(args.chat_language)
        if code is None:
            print(f"board: {args.chat_language!r} is no language code (e.g. de, en, pt-br)", file=sys.stderr)
            return 2
        actlib.write_identity({"chat_language": code})
        chat = actlib.language_settings(actlib.read_config())[0]
        suffix = "" if chat == "auto" else f" (inactive while config.md fixes language-chat {chat!r})"
        print(f"board: chat language {code!r} remembered for this checkout in .act-local/identity.json{suffix}")
        return 0

    branch = get_branch(root)
    commit = get_last_commit(root) if branch is not None else None
    dirty = has_changes(root) if branch is not None else None
    branch_label = branch if branch is not None else "(no git)"
    filename = f"board-{sanitize_branch(branch) if branch is not None else 'no-git'}.md"

    identity_data = actlib.read_identity()
    my_identity = identity_data.get("identity") if identity_data else None

    ledger_entries = read_ledger_entries(root)
    inbox_counts = read_inbox_counts(root, my_identity)
    open_questions, answered_questions = read_questions(root)
    task_titles = read_task_titles(root)
    backlog_titles = read_backlog_titles(root)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    content = render_board(
        branch_label, commit, dirty, ledger_entries, inbox_counts, open_questions,
        answered_questions, task_titles, backlog_titles, generated_at,
    )

    board_path = root / ".act-local" / filename
    board_path.parent.mkdir(parents=True, exist_ok=True)
    board_path.write_text(content, encoding="utf-8")

    ledger_count = len(ledger_entries) if ledger_entries is not None else 0
    waiting_total = sum(inbox_counts.values()) if inbox_counts is not None else 0
    questions_count = len(open_questions) if open_questions is not None else 0
    task_count = len(task_titles) if task_titles is not None else 0
    backlog_count = len(backlog_titles) if backlog_titles is not None else 0
    rel = board_path.relative_to(root).as_posix()
    print(
        f"board: wrote {rel} (branch={branch_label}, ledger={ledger_count}, "
        f"waiting={waiting_total}, questions={questions_count}, tasks={task_count}, "
        f"backlog={backlog_count})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
