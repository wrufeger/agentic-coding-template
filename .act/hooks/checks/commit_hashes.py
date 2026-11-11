#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check — a note, never a refusal, when a `git commit` names a commit hash that no repository knows
#          (R-work-evidence: a commit hash counts as evidence, so it must exist). PreToolUse, Bash and
#          PowerShell, main session. It reads the text the commit brings: the lines added to the staged
#          journal files (`docs/ai/work/ledger/`) and the commit message as the command text shows it (`-m`,
#          a heredoc behind `-F -`, the file a literal `-F <file>` names). A hash is a word in backticks of
#          7 to 40 hex characters with at least one digit and one letter (`` `3e2901a` ``); a bare number or a
#          hex word without backticks is never looked at.
#
# Each hash is looked up with `git cat-file -e <hash>^{commit}` in this repository and in the repositories
# the row `commit-hashes-repos` lists (paths relative to the project root, `none` for no further one): a
# journal can name commits of another repository. A hash none of them knows is named in one note, unless it
# is the start (case-insensitive) of a template commit recorded in `.act-lock.json` of the project root, in
# the working tree, staged or in its history: an update journals the change of the template commit, and a
# project has no clone of the template. Limit: a template commit never recorded in the lock, such as an
# intermediate one, is still noted.
#
# Switch `commit-hashes` in docs/ai/config.md § Checks: `warn` (default, also for a missing row) notes, `off`
# says nothing; `block` counts as `warn` because the call is never refused. The note reaches the model as
# PostToolUse context (a PreToolUse line on stdout is only shown to the person), queued under
# `.act-local/commit-hash-hints/<tool_use_id>.json`. Fails open: an exception, a missing git or a lookup
# past the time budget lets the call pass without a note.
#
# Limits: a hash in a message file written in the same call, or in a program's own text, is not seen; an
# abbreviation that is ambiguous in a repository counts as unknown there.

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Optional

import actlib

from .command_parse import parse_for
from .common import (
    _SHELL_TOOL_NAMES, _check_mode, _is_worker, _note_only, _pop_pending_notes, _queue_pending_note,
    _shell_command,
)
from .worker_git_write import _parse_git_invocation
from .write_scope import _SAFE_ID_RE

__all__ = ["check_commit_hashes", "note_commit_hashes"]

_HINTS_DIRNAME = "commit-hash-hints"
_LEDGER = "docs/ai/work/ledger/"
_HASH_RE = re.compile(r"\\?`([0-9A-Fa-f]{7,40})\\?`")
_LOCK = ".act-lock.json"
_LOCK_COMMIT_RE = re.compile(r'"commit"\s*:\s*"([0-9A-Fa-f]{7,40})"')
_MAX_HASHES = 20
_MAX_FILE_BYTES = 200_000
_BUDGET_SECONDS = 4.0

_NOTE = (
    "[act] note: {hashes} named in this commit {verb} no commit in this repository{others} — a mistyped or "
    "invented hash is no evidence (R-work-evidence); fix it, or ignore the note when the commit lives in "
    "another repository (list it in `commit-hashes-repos` in docs/ai/config.md § Checks). Not refused"
)


def _mode(config: dict) -> str:
    """`off` or `warn`: the call is never refused, so a `block` row counts as `warn`."""
    return "off" if _check_mode(config, "commit-hashes", default="warn") == "off" else "warn"


def _hex_hashes(text: str) -> list[str]:
    """The backticked hex words in `text` with a digit and a letter, in order, without repeats."""
    found: list[str] = []
    for match in _HASH_RE.finditer(text):
        word = match.group(1)
        if any(c.isdigit() for c in word) and any(c.isalpha() for c in word) and word.lower() not in found:
            found.append(word.lower())
    return found


def _git(root: Path, args: list[str], timeout: float) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=max(timeout, 0.5), check=False)
    except (OSError, subprocess.SubprocessError):
        return None


def _staged_ledger_text(root: Path) -> str:
    """The lines added to the staged journal files."""
    done = _git(root, ["diff", "--cached", "-U0", "--no-color", "--", _LEDGER], _BUDGET_SECONDS)
    if done is None or done.returncode != 0:
        return ""
    return "\n".join(line[1:] for line in done.stdout.splitlines() if line.startswith("+") and not line.startswith("+++"))


def _message_files(commit_args: list[str], cwd: Path) -> str:
    """The text of the files a literal `-F <file>` / `--file=<file>` names (not `-`, which is the heredoc)."""
    names: list[str] = []
    for index, arg in enumerate(commit_args):
        if arg in ("-F", "--file") and index + 1 < len(commit_args):
            names.append(commit_args[index + 1])
        elif arg.startswith("--file="):
            names.append(arg[len("--file="):])
        elif arg.startswith("-F") and len(arg) > 2 and not arg.startswith("--"):
            names.append(arg[2:])
    text = []
    for name in names:
        if name == "-" or any(char in name for char in "$`"):
            continue
        path = Path(name) if Path(name).is_absolute() else cwd / name
        try:
            if path.is_file() and path.stat().st_size <= _MAX_FILE_BYTES:
                text.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return "\n".join(text)


def _is_repo(path: Path) -> bool:
    done = _git(path, ["rev-parse", "--git-dir"], 2.0) if path.is_dir() else None
    return done is not None and done.returncode == 0


def _repos(root: Path, config: dict) -> list[Path]:
    """This repository first, then the folders of `commit-hashes-repos` that are repositories; empty when this
    one is none (the lookups would say nothing)."""
    if not _is_repo(root):
        return []
    repos = [root]
    for entry in config.get("commit-hashes-repos", "none").split(","):
        entry = entry.strip().strip("`")
        if not entry or entry.lower() == "none":
            continue
        path = Path(entry) if Path(entry).is_absolute() else root / entry
        if _is_repo(path):
            repos.append(path)
    return repos


def _lock_commits(root: Path, deadline: float) -> Optional[list[str]]:
    """Every template commit `.act-lock.json` names, in the working tree (an update committed in the call that
    stages it), staged or in its history (added and removed lines); None when out of time or git fails."""
    found: list[str] = []
    try:
        lock = root / _LOCK
        if lock.is_file() and lock.stat().st_size <= _MAX_FILE_BYTES:
            found.extend(match.lower() for match in _LOCK_COMMIT_RE.findall(
                lock.read_text(encoding="utf-8", errors="replace")))
    except OSError:
        pass
    for args in (["diff", "--cached", "-U0", "--no-color", "--", _LOCK],
                 ["log", "--format=", "-p", "-U0", "--no-color", "--", _LOCK]):
        left = deadline - time.monotonic()
        if left <= 0:
            return None
        done = _git(root, args, left)
        if done is None:
            return None
        if done.returncode == 0:
            found.extend(match.lower() for match in _LOCK_COMMIT_RE.findall(done.stdout))
    return found


def _unknown(hashes: list[str], repos: list[Path]) -> list[str]:
    deadline = time.monotonic() + _BUDGET_SECONDS
    missing: list[str] = []
    for word in hashes:
        known = False
        for repo in repos:
            left = deadline - time.monotonic()
            if left <= 0:
                return []  # out of time: no note rather than a false one
            done = _git(repo, ["cat-file", "-e", f"{word}^{{commit}}"], left)
            if done is None:
                return []
            if done.returncode == 0:
                known = True
                break
        if not known:
            missing.append(word)
    if missing:
        recorded = _lock_commits(repos[0], deadline)
        if recorded is None:
            return []
        missing = [word for word in missing if not any(commit.startswith(word) for commit in recorded)]
    return missing


def _hint_file(root: Path, tool_use_id: object) -> Optional[Path]:
    if not isinstance(tool_use_id, str) or not _SAFE_ID_RE.match(tool_use_id):
        return None
    path = root / ".act-local" / _HINTS_DIRNAME / f"{tool_use_id}.json"
    return path if actlib.local_write_ok(root, path) else None


def check_commit_hashes(payload: dict) -> int:
    """Notes the commit hashes of this `git commit` that no repository knows (stdout, and queued for PostToolUse)."""
    try:
        shell = _shell_command(payload)
        if shell is None or _is_worker(payload) or "commit" not in shell[1]:
            return 0
        config = actlib.read_config()
        if _mode(config) == "off":
            return 0
        command = shell[1]
        commits = [
            sub_args for args in parse_for(payload, command).git_invocations()
            for subcommand, sub_args, _dirs, _override, _alias in [_parse_git_invocation(args)]
            if subcommand == "commit"
        ]
        if not commits:
            return 0
        root = actlib.repo_root()
        cwd = Path(payload["cwd"]) if isinstance(payload.get("cwd"), str) and payload.get("cwd") else root
        text = "\n".join([command, _staged_ledger_text(root), *(_message_files(args, cwd) for args in commits)])
        hashes = _hex_hashes(text)[:_MAX_HASHES]
        if not hashes:
            return 0
        repos = _repos(root, config)
        missing = _unknown(hashes, repos) if repos else []
        if not missing:
            return 0
        shown = ", ".join(f"`{word}`" for word in missing)
        note = _NOTE.format(
            hashes=shown, verb="is" if len(missing) == 1 else "are",
            others=" or the repositories of `commit-hashes-repos`" if len(repos) > 1 else "")
        print(note)
        _note_only("commit-hashes")
        path = _hint_file(root, payload.get("tool_use_id"))
        if path is not None:
            _queue_pending_note(path, note, payload)
    except Exception:  # noqa: BLE001 -- a note is never worth a refused or broken call
        return 0
    return 0


def note_commit_hashes(payload: dict) -> Optional[str]:
    """PostToolUse counterpart: the note queued for this very call (by tool_use_id), once; None when there is none.
    Registered in dispatch.py's _POST_TOOL_USE_NOTES."""
    if _is_worker(payload) or payload.get("tool_name") not in _SHELL_TOOL_NAMES:
        return None
    try:
        path = _hint_file(actlib.repo_root(), payload.get("tool_use_id"))
        if path is None or not path.is_file():
            return None
        notes = [] if _mode(actlib.read_config()) == "off" else _pop_pending_notes(path, payload)
        try:
            path.unlink()
        except OSError:
            pass
        return "\n".join(notes) if notes else None
    except Exception:  # noqa: BLE001
        return None
