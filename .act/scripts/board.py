#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Generate the board — a fully derived snapshot (current branch, last commit, dirty
#          state, recent journal entries, one "Waiting for you" list drawn from the single inbox
#          at docs/ai/inbox/ (16-inbox-questions-tasks.md), open tasks, open decisions
#          in the backlog, backlog items). Nothing here is hand-maintained; every run overwrites
#          the file from scratch. Where it goes is the `board` key in docs/ai/config.md:
#          `docs` (default) docs/ai/board.md, gitignored, heading names the branch;
#          `local` .act-local/board-<branch>.md; `shared` keeps the same local view in
#          docs/ai/board.md and never rewrites a versioned file on a plain run — only
#          `--shared` (called by act-commit) also writes docs/ai/board-<identity>.md, versioned,
#          without volatile lines (no last commit, no working tree, no timestamp: two runs
#          without content change are byte-identical).
#          Tasks carry `for: <identity>`: "Open tasks" lists this identity's, `all` and
#          unassigned ones; with `board-others` on (default with `mode: team`) a section
#          "Others" lists the tasks for other people and, in the `shared` local view, the open
#          tasks from every other docs/ai/board-*.md. Stdlib only.
#
#          Alongside the board, every run also (re)writes .act-local/inbox-<identity>.md: a
#          generated, read-only view collecting the full text of every open or answered inbox
#          entry addressed to this identity or to "all", so reading one file is enough — replying
#          still happens in the entry file itself (16-inbox-questions-tasks.md § "Board und
#          Leseansicht").
#
#          `--chat-language` instead remembers the chat language recognized for this person on
#          this machine while `language-chat` is `auto` (R-human-language) — per checkout in
#          .act-local/identity.json, never versioned; the session start names it again.
#
# Usage:
#   python .act/scripts/board.py
#   python .act/scripts/board.py --shared             # `board: shared`: also the versioned board
#   python .act/scripts/board.py --chat-language de   # remember the owner's chat language here
#
# Output format:
#   Writes the view chosen by `board` (docs/ai/board.md, or .act-local/board-<branch>.md for
#   `local`) and .act-local/inbox-<identity>.md (gitignored), then prints one summary line to
#   stdout, e.g. "board: wrote docs/ai/board.md (mode=docs, branch=next, ledger=3, waiting=2,
#   tasks=5, backlog=1)". `--shared` adds docs/ai/board-<identity>.md (a second summary line);
#   without an identity it writes none and says so on stderr. An unknown `board` value behaves
#   as `docs` and prints one note to stderr. All files are written with LF line endings.
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
# the other branch's board: each branch gets its own file, keyed by this encoding. The identity
# used for the inbox view filename gets the same treatment (see sanitize_identity()) — a raw
# identity string is free-form and may itself contain characters not safe in a filename.
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
TASKS_DIR = Path("docs/ai/work/tasks")
BACKLOG_DIR = Path("docs/ai/work/backlog")
BOARD_MODES = ("docs", "shared", "local")
DECISION_RE = re.compile(r"(?im)^decision:\s*(\S+)\s*$")
OTHERS_LIMIT = 10     # per list in the "Others" section
# Q65a: a task's working state ("Stand ...") lives here (entries.py state), gitignored, never in
# the versioned task file itself — read_task_titles() shows the last non-blank line next to the
# task's title.
STATE_DIR = Path(".act-local/state")
FOR_RE = re.compile(r"(?im)^for:\s*(.+?)\s*$")
STATUS_RE = re.compile(r"(?im)^status:\s*(\S+)\s*$")
ID_RE = re.compile(r"(?im)^id:\s*(\S+)\s*$")
CREATED_RE = re.compile(r"(?im)^created:\s*(\S+)\s*$")
_CREATED_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# A team-mode filename carries its timestamp as "-YYYYMMDD-HHMM-" (actlib.entry_stamp(), between
# the identity slug and the title slug); an older or hand-adopted entry instead carries a leading
# "YYYY-MM-DD-" date. Both are read-only fallbacks for _timeline_key() below, used when "created:"
# is missing or unparseable.
_FILENAME_TEAM_STAMP_RE = re.compile(r"-(\d{8})-(\d{4})-")
_FILENAME_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-")

LEDGER_LIMIT = 10
TASKS_LIMIT = 5
BACKLOG_LIMIT = 5
OPEN_LIMIT = 10       # per recipient group ("mine", "all") in the "Waiting for you" list
ANSWERED_LIMIT = 10


# ---------------------------------------------------------------------------
# Filename encoding
# ---------------------------------------------------------------------------

def sanitize_branch(branch: str) -> str:
    """Percent-encode a branch name into a single, filesystem-safe path segment. See the header
    comment for the exact rule and why it is reversible."""
    return branch.replace("%", "%25").replace("/", "%2F")


def sanitize_identity(identity: Optional[str]) -> str:
    """Turn an identity string into a filesystem-safe name for .act-local/inbox-<identity>.md:
    keep letters, digits, dot, dash and underscore, fold every other run of characters into a
    single "_". Returns "unknown" for a missing/empty identity (no .act-local/identity.json yet,
    or an identity that folds to nothing) — the view is still written in that case, just under a
    fixed name, so a fresh checkout gets *a* file to read rather than none."""
    if not identity or not identity.strip():
        return "unknown"
    safe = re.sub(r"[^A-Za-z0-9.-]+", "_", identity.strip())
    return safe.strip("_") or "unknown"


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


def _read_created(path: Path) -> Optional[str]:
    """The "created:" header value of `path`, or None if it is missing or the file cannot be read
    — the same field read_inbox_entries() already reads, reused here so tasks/backlog sort the
    same way the inbox does (_timeline_key())."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    match = CREATED_RE.search(actlib.header_block(text))
    return match.group(1).strip() if match else None


def _last_state_line(root: Path, task_filename: str) -> Optional[str]:
    """The last non-blank line of .act-local/state/<task_filename> (entries.py state, Q65a), or
    None if that file does not exist, is empty, or cannot be read as UTF-8 — the same, ungenerated
    working-state note a fresh session would otherwise have to reconstruct from the task file
    alone."""
    try:
        text = (root / STATE_DIR / task_filename).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return None


def read_task_titles(root: Path, limit: int = TASKS_LIMIT) -> Optional[list[str]]:
    """Return up to `limit` "<title>" or "<title> — <last state line>" strings from
    docs/ai/work/tasks/, oldest first by "created:" (_timeline_key(), same normalization the inbox
    uses), or None if the directory does not exist. Filename order alone no longer sorts
    chronologically once an id is embedded in the name (ADR-9, T75: "T1-..." .. "T5-..." then
    "T10-..-T13-.." would otherwise sort ahead of "T2-..", and a team-mode name awaiting an id
    sorts by its identity prefix, not by when it was written). Title is the file's first Markdown
    heading, or the filename stem if there is none; a task with a working state recorded via
    `entries.py state` (Q65a) gets that state's last line appended."""
    tasks = read_tasks(root)
    if tasks is None:
        return None
    return [_task_text(task) for task in tasks[:limit]]


def _task_text(task: dict) -> str:
    return f"{task['title']} — {task['state']}" if task["state"] else task["title"]


def read_tasks(root: Path) -> Optional[list[dict]]:
    """Every task under docs/ai/work/tasks/ as {"title", "for", "state"}, oldest first (same order
    as read_task_titles()), or None if the directory does not exist. "for" is the header's `for:`
    value or None; "state" the last working-state line or None."""
    tasks_dir = root / TASKS_DIR
    if not tasks_dir.is_dir():
        return None
    files = sorted(
        (p for p in tasks_dir.glob("*.md") if p.name.lower() != "readme.md"),
        key=lambda p: _timeline_key(_read_created(p), p.name, newest_first=False),
    )
    tasks: list[dict] = []
    for path in files:
        try:
            header = actlib.header_block(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            header = ""
        for_match = FOR_RE.search(header)
        tasks.append({
            "title": _first_heading(path) or path.stem,
            "for": for_match.group(1).strip() if for_match else None,
            "state": _last_state_line(root, path.name),
        })
    return tasks


def _is_own_task(task: dict, identity: Optional[str]) -> bool:
    """A task is this person's (or shared) if it names this identity or `all`, carries no `for:`,
    or if this checkout has no identity at all (nothing to tell it apart from). Short-form
    comparison like _group_by_recipient()."""
    target = (task["for"] or "").strip().lower()
    if not target or target == "all" or not identity:
        return True
    return actlib.recipient_slug(target) == actlib.recipient_slug(identity)


def read_open_decisions(root: Path) -> list[str]:
    """"<id> — <title>" for every backlog entry whose header says `decision: open` 
    (used with `inbox-decisions: at-start`), sorted by file name; an empty list if there is none
    (the board then leaves the section out)."""
    backlog_dir = root / BACKLOG_DIR
    if not backlog_dir.is_dir():
        return []
    found: list[str] = []
    for path in sorted(backlog_dir.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        try:
            header = actlib.header_block(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        match = DECISION_RE.search(header)
        if not match or match.group(1).strip().lower() != "open":
            continue
        id_match = ID_RE.search(header)
        title = _first_heading(path) or path.stem
        found.append(f"{id_match.group(1)} — {title}" if id_match else title)
    return found


def read_other_boards(root: Path, own_name: str) -> list[tuple[str, list[str]]]:
    """For `shared` mode: (person, open tasks) from every other docs/ai/board-*.md — the lines of
    its "## Open tasks" section, "(none)" dropped. `own_name` is this board's own file, skipped.
    Sorted by file name; a file that cannot be read is skipped."""
    found: list[tuple[str, list[str]]] = []
    for path in sorted((root / "docs" / "ai").glob("board-*.md")):
        if path.name == own_name:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        tasks: list[str] = []
        inside = False
        for line in lines:
            if line.startswith("## "):
                inside = line.strip() == "## Open tasks"
                continue
            if inside and line.startswith("- ") and line.strip() != "- (none)":
                tasks.append(line[2:].strip())
        found.append((path.stem[len("board-"):], tasks))
    return found


def read_backlog_titles(root: Path, limit: int = BACKLOG_LIMIT) -> Optional[list[str]]:
    """Same idea as read_task_titles(), for docs/ai/work/backlog/."""
    backlog_dir = root / BACKLOG_DIR
    if not backlog_dir.is_dir():
        return None
    files = sorted(
        (p for p in backlog_dir.glob("*.md") if p.name.lower() != "readme.md"),
        key=lambda p: _timeline_key(_read_created(p), p.name, newest_first=False),
    )
    return [(_first_heading(path) or path.stem) for path in files[:limit]]


# ---------------------------------------------------------------------------
# The one inbox (docs/ai/inbox/) — 16-inbox-questions-tasks.md, Q100 b
# ---------------------------------------------------------------------------

def read_inbox_entries(root: Path) -> Optional[list[dict]]:
    """
    Return every open or answered entry in actlib.INBOX_DIR as a dict, or None if that directory
    does not exist. A "done" entry is never returned (B85: done never appears as waiting).

    Each dict carries:
      - "path": the Path to the file
      - "kind": actlib.inbox_kind(text) — "question"/"todo"/"report"/"note"
      - "label": the "id:" value for a question (e.g. "Q101"), else the kind word
      - "for": the "for:" header value, lowercased comparisons are the caller's job, or None
      - "status": "open" (default when the field is missing or unrecognized) or "answered"
      - "created": the "created:" header value, or None if missing (sort fallback: the caller
        uses the filename instead — entries are named so that sorts chronologically too)
      - "title": the file's first Markdown heading, or its filename stem
      - "body": the file's text with the leading header block (and the blank line separating it
        from the rest) stripped, kept verbatim otherwise — used only by the generated inbox view
    """
    inbox_dir = root / actlib.INBOX_DIR
    if not inbox_dir.is_dir():
        return None

    entries: list[dict] = []
    for path in inbox_dir.glob("*.md"):
        if path.name.lower() == "readme.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        header = actlib.header_block(text)
        status_match = STATUS_RE.search(header)
        status = status_match.group(1).strip().lower() if status_match else "open"
        if status not in ("open", "answered"):
            continue  # "done" (or anything unrecognized) never shows up as waiting (B85)

        kind = actlib.inbox_kind(text)
        for_match = FOR_RE.search(header)
        recipient = for_match.group(1).strip() if for_match else None
        id_match = ID_RE.search(header)
        label = id_match.group(1) if id_match else kind
        created_match = CREATED_RE.search(header)
        created = created_match.group(1).strip() if created_match else None
        title = _first_heading(path) or path.stem

        header_line_count = len(header.splitlines()) if header else 0
        rest_lines = text.splitlines()[header_line_count:]
        while rest_lines and not rest_lines[0].strip():
            rest_lines.pop(0)
        body = "\n".join(rest_lines).rstrip("\n")

        entries.append({
            "path": path, "kind": kind, "label": label, "for": recipient,
            "status": status, "created": created, "title": title, "body": body,
        })
    return entries


def _parse_created(value: Optional[str]) -> Optional[datetime]:
    """`value` (a "created:" header field) as a datetime, tolerant of a date-only value ("some
    older or hand-written entries have no time component) by treating it as midnight. None if
    `value` is missing or not parseable as an ISO date/datetime at all."""
    if not value:
        return None
    text = value.strip()
    if _CREATED_DATE_ONLY_RE.match(text):
        text += "T00:00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _filename_timestamp(name: str) -> Optional[datetime]:
    """A timestamp read straight from `name`, for an entry whose "created:" field is missing or
    unparseable: a team-mode stamp ("-YYYYMMDD-HHMM-") if present, else a leading date prefix
    ("YYYY-MM-DD-"). None if neither pattern matches."""
    match = _FILENAME_TEAM_STAMP_RE.search(name)
    if match:
        try:
            return datetime.strptime(f"{match.group(1)}{match.group(2)}", "%Y%m%d%H%M")
        except ValueError:
            pass
    match = _FILENAME_DATE_RE.match(name)
    if match:
        try:
            return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            pass
    return None


def _timeline_key(created: Optional[str], name: str, *, newest_first: bool) -> tuple:
    """A comparable, ascending-sort key built from `created` (a "created:" header value) or,
    failing that, a timestamp read from the filename itself (_filename_timestamp()) — an entry
    with neither sorts after every timed one, in either direction, so it never jumps to the front
    just because `newest_first` flips the rest of the order. Entries tied on time (including two
    untimed ones) fall back to the filename, for a still-deterministic order."""
    when = _parse_created(created) or _filename_timestamp(name)
    if when is None:
        return (1, name)
    ordinal = when.timestamp()
    return (0, -ordinal if newest_first else ordinal, name)


def _sort_key(entry: dict) -> tuple:
    """Newest first: _timeline_key() on "created:"/the filename (16-inbox-questions-tasks.md §
    "Board und Leseansicht") — an entry with neither always sorts last, never first just because
    this list itself reads newest-first."""
    return _timeline_key(entry["created"], entry["path"].name, newest_first=True)


def _group_by_recipient(entries: list[dict], identity: Optional[str]) -> tuple[list[dict], list[dict], list[dict]]:
    """Split `entries` (already sorted newest-first) into (mine, all, other) — an entry with no
    "for:" field at all falls into "other" (Q63b), same as a value that names neither this
    identity nor "all"."""
    mine: list[dict] = []
    all_entries: list[dict] = []
    other: list[dict] = []
    for entry in entries:
        target = (entry["for"] or "").strip().lower()
        # B147: compare in the short form on both sides, so a hand-written `for: Wolfgang Rufeger`
        # finds the identity `wolfgang-rufeger`. "all" and an empty value keep their meaning.
        if target and target != "all":
            target = actlib.recipient_slug(target)
        if identity and target and target == actlib.recipient_slug(identity):
            mine.append(entry)
        elif target == "all":
            all_entries.append(entry)
        else:
            other.append(entry)
    return mine, all_entries, other


def _format_entry(entry: dict) -> str:
    return f"{entry['label']} — {entry['title']}"


# ---------------------------------------------------------------------------
# Rendering — board
# ---------------------------------------------------------------------------

def render_board(
    branch_label: str,
    commit: Optional[dict[str, str]],
    dirty: Optional[bool],
    ledger_entries: Optional[list[str]],
    waiting_mine: Optional[list[str]],
    waiting_all: Optional[list[str]],
    waiting_other_count: int,
    answered_entries: Optional[list[str]],
    task_titles: Optional[list[str]],
    backlog_titles: Optional[list[str]],
    generated_at: Optional[str],
    *,
    heading: Optional[str] = None,
    decisions: Optional[list[str]] = None,
    others: Optional[list[str]] = None,
) -> str:
    """`generated_at` None (mode `shared`) leaves the timestamp out; with `commit` and `dirty` None
    as well the output holds nothing volatile. `heading` replaces the branch in the title;
    `decisions` (open decisions in the backlog) and `others` (section "Others", None = off) are
    left out when empty/None respectively."""
    lines: list[str] = [f"# Board — {heading or branch_label}", ""]

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

    if waiting_mine is not None or answered_entries is not None:
        lines.append("## Waiting for you")
        combined = list(waiting_mine or []) + list(waiting_all or [])
        if combined:
            lines.extend(f"- {entry}" for entry in combined)
        if waiting_other_count:
            lines.append(f"- For others: {waiting_other_count} waiting")
        if not combined and not waiting_other_count:
            lines.append("- (none)")
        lines.append("")
        lines.append("### Answered — the assistant processes these")
        if answered_entries:
            lines.extend(f"- {entry}" for entry in answered_entries)
        else:
            lines.append("- (none)")
        lines.append("")

    if task_titles is not None:
        lines.append("## Open tasks")
        if task_titles:
            lines.extend(f"- {title}" for title in task_titles)
        else:
            lines.append("- (none)")
        lines.append("")

    if others is not None:
        lines.append("## Others")
        if others:
            lines.extend(f"- {entry}" for entry in others)
        else:
            lines.append("- (none)")
        lines.append("")

    if decisions:
        lines.append("## Open decisions in backlog")
        lines.extend(f"- {entry}" for entry in decisions)
        lines.append("")

    if backlog_titles is not None:
        lines.append("## Backlog")
        if backlog_titles:
            lines.extend(f"- {title}" for title in backlog_titles)
        else:
            lines.append("- (none)")
        lines.append("")

    lines.append("---")
    stamp = f"Generated {generated_at}." if generated_at else "Generated."
    lines.append(f"{stamp} This file is generated — edits here are lost on the next run.")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Rendering — the generated inbox read view (.act-local/inbox-<identity>.md)
# ---------------------------------------------------------------------------

def render_inbox_view(entries: list[dict], root: Path) -> str:
    """
    The full text of every open or answered entry addressed to this identity or "all", newest
    first, one section per entry — a single file to read; replying still happens in the entry
    file itself (16-inbox-questions-tasks.md § "Board und Leseansicht"). `entries` is expected
    already filtered (mine + all, open + answered) and sorted newest-first by the caller.
    """
    lines: list[str] = [
        "Generated, read-only -- answer in the entry file itself.",
        "",
    ]
    if not entries:
        lines.append("Nothing waiting.")
        lines.append("")
        return "\n".join(lines)

    for entry in entries:
        lines.append(f"## {_format_entry(entry)}")
        lines.append("")
        lines.append(f"`{entry['path'].relative_to(root).as_posix()}`")
        lines.append("")
        if entry["body"]:
            lines.append(entry["body"])
            lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"


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
        prog="board.py",
        description="Write the board view chosen by `board` in docs/ai/config.md: docs/ai/board.md (docs, "
                    "shared) or .act-local/board-<branch>.md (local).")
    parser.add_argument("--chat-language", metavar="CODE",
                        help="remember the chat language recognized for this person on this machine "
                             "(.act-local/identity.json) while language-chat is auto, then exit")
    parser.add_argument("--shared", action="store_true",
                        help="with `board: shared`: also write the versioned docs/ai/board-<identity>.md "
                             "(act-commit calls it; a plain run never touches that file)")
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

    config = actlib.read_config(root)
    board_mode = config.get("board", "").strip().lower() or "docs"
    if board_mode not in BOARD_MODES:
        print(f"board: unknown board value {config.get('board', '').strip()!r} in docs/ai/config.md "
              f"(docs | shared | local) — using docs", file=sys.stderr)
        board_mode = "docs"
    others_value = config.get("board-others", "").strip().lower()
    if others_value not in ("on", "off"):
        others_value = "on" if config.get("mode", "").strip().lower() == "team" else "off"

    identity_data = actlib.read_identity()
    my_identity = identity_data.get("identity") if identity_data else None

    ledger_entries = read_ledger_entries(root)
    inbox_entries = read_inbox_entries(root)
    all_tasks = read_tasks(root)
    task_titles: Optional[list[str]] = None
    others: Optional[list[str]] = None
    if all_tasks is not None:
        own_tasks = [t for t in all_tasks if _is_own_task(t, my_identity)]
        task_titles = [_task_text(t) for t in own_tasks[:TASKS_LIMIT]]
    known_titles = [t["title"] for t in (all_tasks or [])]
    other_tasks = [t for t in (all_tasks or []) if not _is_own_task(t, my_identity)]
    others_own_files: list[str] = []
    if others_value == "on":
        others_own_files = [f"{t['title']} — for {t['for']}" for t in other_tasks[:OTHERS_LIMIT]]

    def others_with_boards(skip_name: str) -> list[str]:
        merged = list(others_own_files)
        for person, person_tasks in read_other_boards(root, skip_name):
            for text in person_tasks[:OTHERS_LIMIT]:
                if any(text == title or text.startswith(f"{title} — ") for title in known_titles):
                    continue  # already known from a task file (own, shared or someone else's)
                merged.append(f"{text} — {person}")
        return merged

    backlog_titles = read_backlog_titles(root)
    decisions = read_open_decisions(root)

    slug = actlib.recipient_slug(my_identity) if my_identity else ""
    own_board_name = f"board-{slug}.md" if slug and slug != "unknown" else ""
    versioned_name: Optional[str] = None
    if board_mode == "shared" and args.shared:
        if own_board_name:
            versioned_name = own_board_name
        else:
            print("board: no usable identity in .act-local/identity.json — the versioned "
                  "docs/ai/board-<identity>.md is not written, only the local view", file=sys.stderr)
    if board_mode == "local":
        board_rel = Path(".act-local") / f"board-{sanitize_branch(branch) if branch is not None else 'no-git'}.md"
    else:
        board_rel = Path("docs") / "ai" / "board.md"
    if others_value == "on":
        # the local view of `shared` mode also lists what the others committed; the versioned file
        # (written below) stays free of it, so it depends on this person's own files only
        others = others_with_boards(own_board_name) if board_mode == "shared" else others_own_files
    else:
        others = None

    if inbox_entries is not None:
        open_entries = sorted((e for e in inbox_entries if e["status"] == "open"), key=_sort_key)
        answered_all = sorted((e for e in inbox_entries if e["status"] == "answered"), key=_sort_key)

        mine_open, all_open, other_open = _group_by_recipient(open_entries, my_identity)
        mine_answered, all_answered, _other_answered = _group_by_recipient(answered_all, my_identity)

        waiting_mine = [_format_entry(e) for e in mine_open[:OPEN_LIMIT]]
        waiting_all = [_format_entry(e) for e in all_open[:OPEN_LIMIT]]
        # The summary's own count below is the full "open" total (mine + all + other), not the
        # length of these two lists — they are capped at OPEN_LIMIT for the rendered board, and a
        # cap must never shrink what the summary line reports.
        waiting_mine_total = len(mine_open)
        waiting_all_total = len(all_open)
        waiting_other_count = len(other_open)
        answered_entries = [_format_entry(e) for e in answered_all[:ANSWERED_LIMIT]]

        view_entries = sorted(mine_open + all_open + mine_answered + all_answered, key=_sort_key)
    else:
        waiting_mine = waiting_all = answered_entries = None
        waiting_mine_total = waiting_all_total = 0
        waiting_other_count = 0
        view_entries = []

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    content = render_board(
        branch_label, commit, dirty, ledger_entries, waiting_mine, waiting_all,
        waiting_other_count, answered_entries, task_titles, backlog_titles, generated_at,
        heading=None, decisions=decisions, others=others,
    )

    board_path = root / board_rel
    actlib.write_text_lf(board_path, content)

    if versioned_name is not None:
        versioned_content = render_board(
            branch_label, None, None, ledger_entries, waiting_mine, waiting_all,
            waiting_other_count, answered_entries, task_titles, backlog_titles, None,
            heading=my_identity, decisions=decisions,
            others=others_own_files if others_value == "on" else None,
        )
        actlib.write_text_lf(root / "docs" / "ai" / versioned_name, versioned_content)

    # Written on every run, even when the inbox directory does not exist yet (view_entries is
    # then simply empty) — a fresh checkout still gets a file to read, "Nothing waiting.".
    view_filename = f"inbox-{sanitize_identity(my_identity)}.md"
    view_path = root / ".act-local" / view_filename
    actlib.write_text_lf(view_path, render_inbox_view(view_entries, root))

    ledger_count = len(ledger_entries) if ledger_entries is not None else 0
    waiting_total = (
        waiting_mine_total + waiting_all_total + waiting_other_count if waiting_mine is not None else 0
    )
    task_count = len(task_titles) if task_titles is not None else 0
    backlog_count = len(backlog_titles) if backlog_titles is not None else 0
    rel = board_path.relative_to(root).as_posix()
    print(
        f"board: wrote {rel} (mode={board_mode}, branch={branch_label}, ledger={ledger_count}, "
        f"waiting={waiting_total}, tasks={task_count}, backlog={backlog_count})"
    )
    if versioned_name is not None:
        print(f"board: wrote docs/ai/{versioned_name} (versioned, mode=shared)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
