#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check — dependency-vulnerability scan before a commit (PreToolUse), the "deps"/"full"
#          part of the security check (a decided concept): "Art B" of three. Runs only with
#          `security-check: deps` or `full` in docs/ai/config.md (`danger_scan.py`'s own
#          `_security_check_level`, reused rather than a second parser here — R-work-override: one
#          place decides the level), and only when this commit's own diff actually touches a lock
#          file (`.act/scripts/security_scan.py`'s `LOCK_FILE_NAMES`) — a commit that never
#          touches
#          one costs nothing beyond the same `git commit`-detection walk
#          `danger_scan.py`/`secret_scan.py` already do (reused here too,
#          `secret_scan._git_commit_invocations`, rather than a third copy of "which commit-like
#          call, in which directory").
#
#          What is judged: exactly the lock files this commit touches — staged; unstaged with `-a`
#          or a prior all-staging `git add`; modified or brand-new under a `git add <path>` earlier
#          in the same chain; brand-new anywhere in the tree after a `git add -A` (the whole-tree
#          entry `secret_scan._WHOLE_TREE_PATHSPEC` carries) — and nothing else: a finding in a lock
#          file the commit leaves alone never holds it (2026-09-27 review 2, m7); the daily
#          session-start scan (`checks/session.py`) keeps covering every lock file the project has.
#          Every name git reports is root-relative and joined onto the repository's top level
#          (`secret_scan._repo_toplevel`), never onto the commit's own directory. A touched name
#          that no longer exists on disk (`git rm go.mod`) is dropped, one that exists but cannot
#          be read is dropped with a note — neither ever leaves the check waiting on a digest that
#          can never come (review 2, M3).
#
#          The scan never runs inside this hook's own short timeout (a PreToolUse hook is killed at
#          ~10 s, a real network lookup takes 60-90 s). On a cache miss the check writes a running
#          marker (`security_scan.write_running_marker`) and spawns `checks/session.py`'s detached
#          "_security-scan-worker" with exactly the touched files and their state hash
#          (`security_scan.lock_set_digest`: paths plus content digests), waits up to `_WAIT_BUDGET`
#          — capped by the hook-wide deadline, `secret_scan._check_deadline`, so the secret, danger
#          and deps scans together stay inside the hook's timeout (review 2, m5) — for
#          `<state-hash>.json` to land in `.act-local/security-scan-cache/`, and if it has not,
#          denies once with "dependency scan running — commit again in a moment" (exit 2). The
#          retry reads the finished result — recorded by the worker only if the files had not
#          changed while the tool ran (digest before and after, review 2 C1). A marker past its
#          own `stale_after` (the tools' own timeouts, `security_scan.scan_time_limit`, plus
#          `_WORKER_MARGIN_SECONDS` — never a fixed guess a multi-tool scan could outrun, review 2
#          m6) is a dead worker: the marker is cleared and the commit let through with a "not
#          checked" note, nothing cached. A spawn that fails clears its marker at once and notes,
#          rather than leaving every later commit waiting on a worker that never existed (m6). With
#          no scan tool installed at all the engine cannot start a subprocess anyway, so its
#          missing-tool answer is taken directly, without a worker.
#
#          Cache: `<state-hash>.json` answers for the rest of the day when it is clean (no tool
#          error, no missing tool — `ScanResult.is_clean`); a result that never really looked is
#          reused for `_ERROR_RETRY_SECONDS` at most (an immediate retry of the same commit re-reads
#          the note rather than re-running a failing tool) and is a miss after that, so a tool
#          installed or fixed later gets a fresh scan (review 2, M4). A result from an earlier day
#          is always a miss — the tools' databases move on.
#
#          Verdict: an unaccepted finding at severity high/critical holds the commit
#          (package, version, advisory id, severity, fixed version, how to accept it — the same
#          shape secret_scan.py/danger_scan.py already use for their own block message); a lower or
#          "unknown" severity, or one already accepted (`docs/ai/local/security-accepted.md`, see
#          `security_scan.load_accepted`), only notes, via the same PostToolUse-note queue
#          secret_scan.py established (`_pending_file`/`_queue_note`/`note_deps_scan`, own
#          directory under `.act-local/`) — a plain PreToolUse stdout line on an allowed call is
#          transcript-only, never reaching the model (see secret_scan.py's own header for the
#          research behind that). A missing tool notes once per machine (remembered in
#          `.act-local/cache.json`, same file `checks/session.py` already keeps its own once-only
#          notes in) with the install command; a tool/network failure notes every time, never
#          blocks (fail-open, same stance `security_scan.py`'s own docstring documents for its
#          runners). Every note is queued for PostToolUse too.
#
#          Registration (dispatch.py): `("deps_scan", "check_deps_scan")` in `_PRE_TOOL_USE_CHECKS`
#          right after danger_scan, `("deps_scan", "note_deps_scan")` in `_POST_TOOL_USE_NOTES`;
#          `check_deps_scan` in `checks/mcp_ide.py`'s `_SHELL_REUSE_CHECKS` — an IDE terminal's own
#          `git commit` gets the same check. Any exception in `check_deps_scan`'s own body is caught
#          here and turned into a fail-open note naming it, never propagated: reached via mcp_ide's
#          shell-reuse path, an uncaught exception would surface as `check_mcp_ide` itself failing,
#          which *is* fail-closed (dispatch.py's `_FAIL_CLOSED`).
#
#          After `git merge`, `git pull` and `git cherry-pick` (also `pull --rebase`, `merge
#          --no-commit`, a merge that stops on conflicts) the lock files the command brought in are
#          checked too, but only afterwards (`note_deps_merge_scan`, a PostToolUse note, also run for
#          PostToolUseFailure, which is how a merge that stops on conflicts arrives): before the
#          call the tree has not changed yet. Nothing is held; a finding goes into the inbox as one
#          `report` entry (`entries.create_entry`), once per lock-file state and day. A clean result,
#          a missing scan tool or a tool error writes nothing. The command is recognised through
#          `command_words` (`git -C dir pull` and `cd x && git merge y` included); the changed lock
#          files come from git: ORIG_HEAD..HEAD for merge and pull, the picked commits for
#          cherry-pick (only when HEAD moved in the last minutes), plus everything the tree differs
#          from HEAD in while an operation is open (MERGE_HEAD, CHERRY_PICK_HEAD, REBASE_HEAD,
#          `--no-commit`). Unmerged lock files are left out (conflict markers; the commit that ends
#          the merge is checked by the commit check). The scan itself reuses the cache and the
#          detached worker, which files the report when it is done, so the hook stays fast.
#
#          The worker gets its lock-file list through a file under `.act-local/security-scan-lists/`
#          (unique per run, removed afterwards), never through argv: a few hundred absolute paths
#          overrun the Windows command-line limit (WinError 206).
#
# Known limits:
#   - the state hash covers each touched lock file's *current on-disk content*, not the exact
#     staged blob a partially staged commit would record — a lock file staged and then edited
#     further, unstaged, is hashed by its edited state; accepted as rare (a lock file is staged
#     whole, not partially);
#   - same tokenizer/alias/nested-shell limits as `danger_scan.py`/`secret_scan.py`, since this
#     reuses their own commit-detection walk verbatim;
#   - two commits racing on the very same lock-file state can each spawn a worker (the marker check
#     is best-effort, not a lock) — wasteful, never wrong: both compute the same answer;
#   - the wait budget is shared with the other commit checks through the hook-wide deadline: when
#     they have used the hook's time up, this check notes "not checked" instead of looking at all.

from __future__ import annotations

import dataclasses
import json
import os
import re
import sys
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Optional

import actlib
import security_scan

from . import session
from .board_refresh import _base_cwd, _targets_own_project
from .command_words import _command_word_lists, _strip_command_prefix
from .common import _is_worker, _pop_pending_notes, _queue_pending_note, _shell_command
from .danger_scan import _security_check_level
from .secret_scan import (
    _check_deadline,
    _git_commit_invocations,
    _repo_toplevel,
    _run_git,
    _GIT_TIMEOUT,
    _SAFE_SESSION_ID_RE,
    _TIME_BUDGET,
    _WHOLE_TREE_PATHSPEC,
    _resolve_dir,
)
from .shell_targets import _command_name
from .worker_git_write import _first_operand, _parse_git_invocation, _resolve_dash_c_chain

__all__ = [
    "_NOTES_DIRNAME", "_ALL_LOCK_BASENAMES", "_WAIT_BUDGET", "_POLL_INTERVAL",
    "_ERROR_RETRY_SECONDS", "_WORKER_MARGIN_SECONDS", "_MIN_DETECTION_SECONDS",
    "_Outcome", "_touched_lock_files", "_readable_lock_files", "_current_cache", "_resolve_scan",
    "_note", "_note_once", "_pending_file", "_queue_note",
    "_format_finding", "_build_block_message", "_build_note_message", "_judge",
    "check_deps_scan", "note_deps_scan",
    "_LISTS_DIRNAME", "_write_list_file", "_read_list_file", "_remove_list_file", "_spawn_scan_worker",
    "run_list_worker", "_IntegrationCall", "_integration_calls", "_integration_lock_files", "_report_result",
    "note_deps_merge_scan",
]

_NOTES_DIRNAME = "deps-scan-notes"

_ALL_LOCK_BASENAMES = frozenset(
    name for names in security_scan.LOCK_FILE_NAMES.values() for name in names
)

# Time (seconds) to wait for a freshly spawned background scan's result once lock-file detection
# is done -- always capped by the hook-wide deadline (secret_scan._check_deadline), never added on
# top of what the earlier commit checks already spent (2026-09-27 review 2, m5).
_WAIT_BUDGET = 4.0
_POLL_INTERVAL = 0.15
# Below this much detection time left, the check does not even start looking (a git call that is
# cut off halfway only means fewer touched names -- better to say "not checked" plainly).
_MIN_DETECTION_SECONDS = 0.5
# A result that never really looked (tool error, missing tool) answers an immediate retry of the
# same commit for this long, then counts as a cache miss again (review 2, M4).
_ERROR_RETRY_SECONDS = 60.0
# Added to the tools' own summed timeouts (security_scan.scan_time_limit) for the running marker's
# `stale_after`: interpreter start-up, digesting and the JSON write of the worker itself.
_WORKER_MARGIN_SECONDS = 60.0


@dataclasses.dataclass
class _Outcome:
    """What `_resolve_scan` found out for one commit's touched lock files: `status` is "result"
    (with `result` set), "running" (a scan is in flight, deny once), "dead" (a marker outlived its
    own stale limit -- cleared, fail open), "spawn_failed" (no worker could be started, fail open)
    or "unhashable" (a file changed between being listed and being digested, fail open)."""
    status: str
    result: Optional[security_scan.ScanResult] = None


def _touched_lock_files(invocation: dict, deadline: float) -> "list[str]":
    """Every **absolute, resolved path** this one commit-like invocation would actually commit
    whose basename is a known lock file (`_ALL_LOCK_BASENAMES`): staged names always; unstaged
    tracked ones too when the invocation is `-a`-shaped or follows an all-staging `git add`; for
    every `git add <path>` earlier in the same chain both a tracked file modified under that path
    and an untracked new file under it; for a `git add -A` (the whole-tree entry) every untracked
    new file in the tree. Every name git reports (`--name-only`, `ls-files --full-name`) is
    repo-root-relative and joined onto the repository's own top level, never onto the commit's
    directory, which may be a subdirectory. A commit's own `-a` never takes an untracked file, so
    none is listed for it. Best-effort, same "an incomplete read only means fewer touched names,
    never a reason to block" stance `danger_scan.py`/`secret_scan.py` take for their git calls."""
    cwd = invocation["cwd"]
    if not Path(cwd).is_dir():
        return []

    def budget() -> float:
        return min(_GIT_TIMEOUT, deadline - time.monotonic())

    toplevel = _repo_toplevel(cwd, budget())
    if toplevel is None:
        return []  # not a repository (git commit itself would fail), or out of time
    base = Path(toplevel)

    # every git call runs from the top level, never from `cwd`: with `diff.relative=true` a diff
    # from a subdirectory names only the files under it -- a staged root `go.mod` would silently
    # vanish from a `cd sub && git commit` (2026-09-27 review 3, m3); the pathspecs handed in are
    # absolute or top-anchored, so the result is otherwise the same
    candidates: list[str] = []
    staged = _run_git(["diff", "--cached", "--name-only"], toplevel, budget())
    if staged:
        candidates.extend(str(base / name) for name in staged.splitlines())

    if invocation["all"]:
        unstaged = _run_git(["diff", "--name-only"], toplevel, budget())
        if unstaged:
            candidates.extend(str(base / name) for name in unstaged.splitlines())

    for entry in invocation["add_paths"]:
        path = entry["path"]  # absolute (secret_scan._resolve_pathspec), or a `:`-magic pathspec
        if path != _WHOLE_TREE_PATHSPEC:
            if not path.startswith(":"):
                candidates.append(path)  # a magic pathspec (`:/src`) is not a file name of its own
            path_diff = _run_git(["diff", "--name-only", "--", path], toplevel, budget())
            if path_diff:
                candidates.extend(str(base / name) for name in path_diff.splitlines())
        # --full-name plus the top level: the whole tree from a subdirectory too (2026-09-27
        # review 2, C2 -- a bare `ls-files` from a subdirectory stops at that subdirectory)
        ls_args = ["ls-files", "--others", "--full-name", "-z", "--", path]
        if not entry["forced"]:
            ls_args.insert(2, "--exclude-standard")
        untracked = _run_git(ls_args, toplevel, budget())
        if untracked:
            candidates.extend(str(base / rel) for rel in filter(None, untracked.split("\0")))

    touched: list[str] = []
    for name in candidates:
        if Path(name).name not in _ALL_LOCK_BASENAMES:
            continue
        try:
            touched.append(str(Path(name).resolve()))  # one spelling per file, whichever git call named it
        except OSError:
            touched.append(name)
    return touched


def _readable_lock_files(
    root: Path, names: "list[str]", deadline: Optional[float] = None,
) -> "tuple[list[Path], list[str]]":
    """(`paths` to scan, root-relative names that exist but cannot be read). A name that no longer
    exists on disk -- a deleted or renamed-away lock file -- is dropped silently: there is nothing
    to scan, and waiting for a digest of it would never end (2026-09-27 review 2, M3). Past
    `deadline` (a monotonic instant, when given) nothing is returned at all: a partial list would
    be scanned and cached as if it were the whole set."""
    paths: list[Path] = []
    unreadable: list[str] = []
    for name in names:
        if deadline is not None and time.monotonic() >= deadline:
            return [], []
        path = Path(name)
        if not path.is_file():
            continue
        if security_scan.lock_file_digest(path) is None:
            unreadable.append(_display(path, root))
            continue
        paths.append(path)
    return paths, unreadable


def _display(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def _current_cache(root: Path, state_hash: str, today: str) -> Optional[security_scan.ScanResult]:
    """The cached answer for `state_hash` if it may still be used: from today, and either clean or
    younger than `_ERROR_RETRY_SECONDS` (review 2, M4). None for a miss -- including a record whose
    finding entries no longer match `security_scan.Finding` (an older template's cache file)."""
    data = security_scan.read_result_cache(root, state_hash)
    if data is None or data["day"] != today:
        return None
    if not data["cacheable"] and time.time() - float(data["written"]) > _ERROR_RETRY_SECONDS:
        return None
    try:
        return security_scan.result_from_dict(data["result"])
    except TypeError:
        return None


def _resolve_scan(root: Path, paths: "list[Path]", payload: dict) -> _Outcome:
    """This commit's own dependency-vulnerability answer for exactly `paths` -- see `_Outcome` for
    the possible statuses and the module docstring for the design. Never runs a scan tool in this
    process: a cache hit answers at once; otherwise the detached worker is spawned (or an already
    running one waited for) up to `_WAIT_BUDGET`, capped by the hook-wide deadline."""
    state_hash = security_scan.lock_set_digest(paths)
    if state_hash is None:
        return _Outcome("unhashable")
    today = date.today().isoformat()

    cached = _current_cache(root, state_hash, today)
    if cached is not None:
        return _Outcome("result", cached)

    lock_files = security_scan.lock_files_from_paths(paths)
    if not security_scan.available_tools():
        # nothing installed: run_scan cannot start a subprocess, it only names what is missing --
        # answered here directly, no worker (never cached either: is_clean() is False)
        return _Outcome("result", security_scan.run_scan(root, lock_files))

    now = time.time()
    marker = security_scan.read_running_marker(root, state_hash)
    if marker is not None:
        if now > marker["stale_after"]:
            security_scan.clear_running_marker(root, state_hash)
            return _Outcome("dead")  # the marker is gone, so a later commit spawns afresh
    else:
        stale_after = now + security_scan.scan_time_limit(lock_files) + _WORKER_MARGIN_SECONDS
        if not security_scan.write_running_marker(root, state_hash, stale_after):
            return _Outcome("spawn_failed")  # a worker nobody can see would be waited for by no one
        if not _spawn_scan_worker(root, state_hash, paths, report=False):
            security_scan.clear_running_marker(root, state_hash)
            return _Outcome("spawn_failed")

    wait_until = _check_deadline(payload, _WAIT_BUDGET)
    while time.monotonic() < wait_until:
        time.sleep(min(_POLL_INTERVAL, max(0.0, wait_until - time.monotonic())))
        cached = _current_cache(root, state_hash, today)
        if cached is not None:
            return _Outcome("result", cached)
    return _Outcome("running")


# ---------------------------------------------------------------------------
# The worker gets its lock-file list through a file, never through argv: on Windows a command line
# is capped at 32,767 characters (WinError 206), and a few hundred absolute lock-file paths pass
# that. The file lives under .act-local/security-scan-lists/, is named after the state hash plus a
# random suffix (unique per run), is read by dispatch.py's "_security-scan-worker" event and
# removed when the run is over; a leftover from a killed worker is pruned the next time one is
# written.
# ---------------------------------------------------------------------------

_LISTS_DIRNAME = "security-scan-lists"
_LIST_FILE_RE = re.compile(r"^[0-9a-f]{64}-[0-9a-f]{32}\.json$")
_LIST_MAX_AGE_SECONDS = 86400.0


def _lists_dir(root: Path) -> Path:
    return root / ".act-local" / _LISTS_DIRNAME


def _prune_list_files(directory: Path) -> None:
    cutoff = time.time() - _LIST_MAX_AGE_SECONDS
    try:
        entries = list(directory.iterdir())
    except OSError:
        return
    for path in entries:
        try:
            if _LIST_FILE_RE.match(path.name) and path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


def _write_list_file(root: Path, state_hash: str, paths: "list[Path]", report: bool) -> Optional[Path]:
    """Writes the worker's input (`paths`, and whether the run reports its findings to the inbox)
    and returns the file, or None when it cannot be written."""
    directory = _lists_dir(root)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        _prune_list_files(directory)
        path = directory / f"{state_hash}-{uuid.uuid4().hex}.json"
        path.write_text(
            json.dumps({"paths": [str(item) for item in paths], "report": report}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError:
        return None
    return path


def _own_list_file(root: Path, state_hash: str, list_file: Path) -> bool:
    """True only for a file this module wrote for `state_hash` -- a worker never reads or removes
    anything else, whatever its argv names."""
    try:
        same_dir = list_file.resolve().parent == _lists_dir(root).resolve()
    except OSError:
        return False
    return same_dir and bool(_LIST_FILE_RE.match(list_file.name)) and list_file.name.startswith(state_hash)


def _read_list_file(root: Path, state_hash: str, list_file: Path) -> "Optional[tuple[list[Path], bool]]":
    if not _own_list_file(root, state_hash, list_file):
        return None
    try:
        data = json.loads(list_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("paths"), list):
        return None
    return [Path(str(item)) for item in data["paths"]], bool(data.get("report"))


def _remove_list_file(root: Path, state_hash: str, list_file: Path) -> None:
    if _own_list_file(root, state_hash, list_file):
        try:
            list_file.unlink()
        except OSError:
            pass


def _spawn_scan_worker(root: Path, state_hash: str, paths: "list[Path]", report: bool) -> bool:
    """Starts the detached scan worker for `paths` with the list in a file. The launcher
    (`session._spawn_security_scan_worker`) appends its lock-path arguments to the command line as
    they are, so one argument `@<list file>` stands in for the whole list; dispatch.py reads that
    form. False (and no file left behind) when nothing could be started."""
    list_file = _write_list_file(root, state_hash, paths, report)
    if list_file is None:
        return False
    if session._spawn_security_scan_worker(root, state_hash, [Path("@" + str(list_file))]):
        return True
    _remove_list_file(root, state_hash, list_file)
    return False


def run_list_worker(root: Path, state_hash: str, list_file: Path) -> int:
    """Body of the worker started with `@<list file>` (dispatch.py): reads the list, runs the same
    scan as the argv form (`session._run_security_scan_worker`), reports to the inbox when the list
    says so, and always removes the list file and the running marker afterwards. Always exits 0
    -- nothing observes this process's own exit code."""
    if not security_scan.is_state_hash(state_hash):
        return 0
    try:
        loaded = _read_list_file(root, state_hash, list_file)
        if loaded is not None:
            paths, report = loaded
            if not (report and _current_cache(root, state_hash, date.today().isoformat()) is not None):
                session._run_security_scan_worker(root, state_hash, paths)  # no answer cached yet
            if report:
                result = _current_cache(root, state_hash, date.today().isoformat())
                if result is not None:
                    _report_result(root, state_hash, result, paths)
    except Exception:  # noqa: BLE001 -- nothing else can observe a detached worker's failure
        pass
    finally:
        _remove_list_file(root, state_hash, list_file)
        security_scan.clear_running_marker(root, state_hash)
    return 0


def _note(payload: dict, message: str) -> None:
    """A note on an allowed call: printed (transcript) and queued for PostToolUse (the model)."""
    print(message)
    _queue_note(payload, message)


def _note_once(payload: dict, key: str, message: str) -> None:
    """`_note`, but only the first time this exact `key` is seen on this machine -- remembered in
    `.act-local/cache.json` (same file `checks/session.py` already keeps its own once-only notes
    in), same as e.g. `_docs_audit_note`'s "no full docs audit on record yet" note."""
    cache = actlib.read_cache()
    noted = set(cache.get("deps_scan_noted", []))
    if key in noted:
        return
    noted.add(key)
    actlib.write_cache({"deps_scan_noted": sorted(noted)})
    _note(payload, message)


def _pending_file(root: Path, session_id: str) -> Optional[Path]:
    if not _SAFE_SESSION_ID_RE.match(session_id):
        return None
    return root / ".act-local" / _NOTES_DIRNAME / f"{session_id}.pending.json"


def _queue_note(payload: dict, note: str) -> None:
    """Best-effort, same reasoning as secret_scan.py's own `_queue_note`: a failed write here only
    means note_deps_scan() finds nothing later, never a reason to change what check_deps_scan
    itself decided."""
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return
    try:
        root = actlib.repo_root()
    except RuntimeError:
        return
    pending_path = _pending_file(root, session_id)
    if pending_path is not None:
        _queue_pending_note(pending_path, note)


def _format_finding(finding: security_scan.Finding, accepted: "dict[str, str]") -> str:
    fixed = f" -> fix: {finding.fixed_version}" if finding.fixed_version else ""
    accepted_note = f" [accepted: {accepted[finding.advisory_id]}]" if finding.advisory_id in accepted else ""
    return (
        f"{finding.package} {finding.version} ({finding.advisory_id}, {finding.severity}){fixed}"
        f"{accepted_note}"
    )


def _build_block_message(findings: "list[security_scan.Finding]") -> str:
    shown = findings[:5]
    rest = len(findings) - len(shown)
    more = f" (+{rest} more)" if rest > 0 else ""
    return (
        "[act] commit held: unaccepted dependency vulnerability in "
        + "; ".join(_format_finding(f, {}) for f in shown) + more
        + " -- update the package, or accept it with a reason in "
        "docs/ai/local/security-accepted.md (a line `- <advisory-id>: <reason>`); repeating the "
        "commit unchanged does not let it through (security-check, deps)"
    )


def _build_note_message(findings: "list[security_scan.Finding]", accepted: "dict[str, str]") -> str:
    shown = findings[:5]
    rest = len(findings) - len(shown)
    more = f" (+{rest} more)" if rest > 0 else ""
    return "[act] security-check (deps): " + "; ".join(_format_finding(f, accepted) for f in shown) + more


def _judge(payload: dict, root: Path, result: security_scan.ScanResult) -> int:
    """The verdict for a finished scan: missing tools note once per machine, tool errors
    note every time, an unaccepted high/critical finding holds (exit 2), everything else notes."""
    accepted = security_scan.load_accepted(root)
    for missing in result.missing_tools:
        _note_once(payload, f"missing_tool:{missing}", f"[act] security-check (deps): {missing}")
    for error in result.errors:
        _note(payload, f"[act] security-check (deps): {error}")

    unaccepted_high = [
        finding for finding in result.findings
        if finding.severity in ("critical", "high") and not security_scan.is_accepted(finding.advisory_id, accepted)
    ]
    if unaccepted_high:
        print(_build_block_message(unaccepted_high), file=sys.stderr)
        return 2

    other = [finding for finding in result.findings if finding not in unaccepted_high]
    if other:
        _note(payload, _build_note_message(other, accepted))
    return 0


def _check(payload: dict, root: Path, command: str) -> int:
    cwd_raw = payload.get("cwd")
    base_cwd = cwd_raw if isinstance(cwd_raw, str) and cwd_raw else str(root)
    deadline = _check_deadline(payload, _TIME_BUDGET)
    if deadline - time.monotonic() < _MIN_DETECTION_SECONDS:
        _note(payload, "[act] security-check (deps): no time left in this hook call -- not checked this time")
        return 0
    invocations = _git_commit_invocations(command, base_cwd, deadline, {})
    if not invocations:
        return 0

    touched: set[str] = set()
    for invocation in invocations:
        if time.monotonic() >= deadline:
            break
        touched.update(_touched_lock_files(invocation, deadline))
    if not touched:
        return 0  # this commit does not touch a lock file -- nothing for Art B to look at

    paths, unreadable = _readable_lock_files(root, sorted(touched))
    if unreadable:
        _note(payload, f"[act] security-check (deps): could not read {', '.join(unreadable)} -- not checked")
    if not paths:
        return 0

    outcome = _resolve_scan(root, paths, payload)
    if outcome.status == "running":
        names = ", ".join(_display(path, root) for path in paths)
        print(
            f"[act] security-check (deps): dependency scan running for {names} -- commit again in a moment",
            file=sys.stderr,
        )
        return 2
    if outcome.status == "dead":
        _note(payload, "[act] security-check (deps): a previous scan attempt never finished -- not checked this time")
        return 0
    if outcome.status == "spawn_failed":
        _note(payload, "[act] security-check (deps): the dependency scan could not be started -- not checked this time")
        return 0
    if outcome.result is None:
        _note(payload, "[act] security-check (deps): a touched lock file changed while being read -- not checked this time")
        return 0
    return _judge(payload, root, outcome.result)


def check_deps_scan(payload: dict) -> int:
    """A `git commit`-like call is held once an unaccepted high/critical dependency vulnerability
    sits in a lock file this commit touches -- see the module docstring for the full contract.
    Applies to the orchestrator and every worker alike (no `_is_worker` gate, same as
    danger_scan.py/secret_scan.py: a vulnerable dependency is no less real coming from a worker).
    Every exception raised anywhere below is caught here and turned into a fail-open note naming
    it -- see the module docstring for why (reached through checks/mcp_ide.py's own shell-reuse
    path, an uncaught exception here would make an unrelated call fail *closed* instead)."""
    config = actlib.read_config()
    level = _security_check_level(config)
    if level not in ("deps", "full"):
        return 0

    shell = _shell_command(payload)
    if shell is None:
        return 0
    _tool_name, command = shell
    if "git" not in command:
        return 0

    try:
        root = actlib.repo_root()
    except RuntimeError:
        return 0

    try:
        _record_integration_heads(payload, root, command)
    except Exception:  # noqa: BLE001 -- best effort: without a record the post-call scan falls back to the reflog
        pass

    try:
        return _check(payload, root, command)
    except Exception as exc:  # noqa: BLE001 -- logged in the note below; see the module docstring
        note = f"[act] security-check (deps): internal error ({type(exc).__name__}: {exc}) -- not checked this time"
        _note(payload, note)
        return 0


def note_deps_scan(payload: dict) -> Optional[str]:
    """PostToolUse companion for check_deps_scan's own notes -- see secret_scan.py's
    note_secret_scan for why a plain PreToolUse stdout line cannot reach the model on its own.
    Registered in dispatch.py's own _POST_TOOL_USE_NOTES."""
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return None
    try:
        root = actlib.repo_root()
    except RuntimeError:
        return None
    pending_path = _pending_file(root, session_id)
    if pending_path is None:
        return None
    notes = _pop_pending_notes(pending_path)
    if not notes:
        return None
    return "\n".join(notes)


# ---------------------------------------------------------------------------
# After `git merge`, `git pull` and `git cherry-pick` (PostToolUse): the lock files the command
# brought in are scanned like a commit's, but nothing is held -- the tree has already changed. A
# finding goes into the inbox as one report entry; a clean result, a missing tool or a tool error
# writes nothing (the commit check and the daily scan keep reporting those). PostToolUseFailure
# runs the same note, which covers a merge that stops on conflicts.
# ---------------------------------------------------------------------------

_INTEGRATION_SUBCOMMANDS = frozenset({"merge", "pull", "cherry-pick"})
# flags that end or inspect an operation instead of bringing anything in
_INTEGRATION_SKIP_FLAGS = frozenset({"--abort", "--quit", "--skip", "--help", "-h"})
# `-n` is `--no-stat` for merge and pull, `--no-commit` only for cherry-pick
_INTEGRATION_NO_COMMIT_FLAGS = {
    "merge": frozenset({"--no-commit"}),
    "pull": frozenset({"--no-commit"}),
    "cherry-pick": frozenset({"-n", "--no-commit"}),
}
# Without a HEAD recorded before the call, only a reflog entry this young belongs to the command
# that just ran (HEAD did not move for an "Already up to date" or a merge that stopped on
# conflicts). Only the fallback: a call with a record does not depend on it.
_FRESH_SECONDS = 660.0
_REFLOG_LIMIT = 50
# HEAD recorded before a call (PreToolUse), read and removed after it, keyed by the tool call's id
_HEADS_DIRNAME = "merge-heads"
_HEADS_MAX_AGE_SECONDS = 86400.0
_RECORD_TIME_BUDGET = 2.0
_STATE_HEADS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REBASE_HEAD")
_MERGE_SUBJECT_PREFIXES = ("merge", "pull", "rebase", "commit (merge)")
_NOTE_TIME_BUDGET = 4.0
_CD_NAMES = frozenset({"cd", "pushd", "chdir"})
_SEVERITY_ORDER = {name: index for index, name in enumerate(security_scan.SEVERITY_LEVELS)}


@dataclasses.dataclass
class _IntegrationCall:
    """One `git merge|pull|cherry-pick` of a command: `target` is the directory git works in -- the
    call's directory moved by every earlier `cd` of the chain, then by the call's own `-C`
    options -- or None when it cannot be told (a dynamic directory)."""
    subcommand: str
    args: "list[str]"
    target: Optional[Path]


def _integration_calls(command: str, base_cwd: str) -> "list[_IntegrationCall]":
    """Every `git merge|pull|cherry-pick` in `command`. Found through the shared command-word
    tokenizer, never by a regex over the raw string."""
    calls: "list[_IntegrationCall]" = []
    cwd: Optional[str] = base_cwd
    for words, _separator in _command_word_lists(command):
        stripped = _strip_command_prefix(words)
        if not stripped:
            continue
        name = _command_name(stripped[0])
        if name in _CD_NAMES:
            operand = _first_operand(stripped[1:])
            cwd = _resolve_dir(operand, cwd) if operand is not None and cwd is not None else None
            continue
        if name != "git":
            continue
        subcommand, sub_args, dash_c_dirs, _override, _alias = _parse_git_invocation(stripped[1:])
        if subcommand not in _INTEGRATION_SUBCOMMANDS or _INTEGRATION_SKIP_FLAGS & set(sub_args):
            continue
        if cwd is None:
            target = None
        elif dash_c_dirs:
            target = _resolve_dash_c_chain(dash_c_dirs, cwd)
        else:
            target = Path(cwd)
        calls.append(_IntegrationCall(subcommand, list(sub_args), target))
    return calls


def _git_names(args: "list[str]", toplevel: str, budget: float) -> "list[str]":
    output = _run_git([*args, "-z"], toplevel, budget)
    return [name for name in output.split("\0") if name] if output else []


def _fresh_reflog(toplevel: str, budget: float) -> "list[tuple[str, str, bool]]":
    """HEAD's newest reflog entries as (commit, subject, fresh), newest first."""
    output = _run_git(
        ["reflog", "-n", str(_REFLOG_LIMIT), "--date=unix", "--format=%H%x09%gd%x09%gs", "HEAD"],
        toplevel, budget,
    )
    entries: "list[tuple[str, str, bool]]" = []
    now = time.time()
    for line in (output or "").splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        stamp = re.search(r"\{(\d+)\}", parts[1])
        age = now - float(stamp.group(1)) if stamp else float("inf")
        entries.append((parts[0], parts[2], age <= _FRESH_SECONDS))
    return entries


def _heads_file(root: Path, tool_use_id: object) -> Optional[Path]:
    if not isinstance(tool_use_id, str) or not _SAFE_SESSION_ID_RE.match(tool_use_id):
        return None
    return root / ".act-local" / _HEADS_DIRNAME / f"{tool_use_id}.json"


def _prune_heads(directory: Path) -> None:
    cutoff = time.time() - _HEADS_MAX_AGE_SECONDS
    try:
        entries = list(directory.iterdir())
    except OSError:
        return
    for entry in entries:
        try:
            if entry.stat().st_mtime < cutoff:
                entry.unlink()
        except OSError:
            continue


def _record_integration_heads(payload: dict, root: Path, command: str) -> None:
    """PreToolUse side of the post-call scan: HEAD of every repository an integration call of
    `command` works in, written under the tool call's id (the harness hands the same id to the
    PostToolUse hook). With it the scan diffs against the real starting point, however long the
    command ran or whether it was started in the background -- the reflog window is only the
    fallback for a call without a record."""
    if _is_worker(payload) or not any(word in command for word in _INTEGRATION_SUBCOMMANDS):
        return
    path = _heads_file(root, payload.get("tool_use_id"))
    if path is None:
        return
    calls = _integration_calls(command, _base_cwd(payload))
    if not calls:
        return
    deadline = time.monotonic() + _RECORD_TIME_BUDGET
    heads: "dict[str, str]" = {}
    for call in calls:
        if call.target is None or not _targets_own_project(call.target, root):
            continue
        toplevel = _repo_toplevel(str(call.target), min(_GIT_TIMEOUT, deadline - time.monotonic()))
        if toplevel is None or toplevel in heads:
            continue  # a chain's first call in a repository holds the starting point for all of them
        head = _run_git(["rev-parse", "-q", "--verify", "HEAD"], toplevel, min(_GIT_TIMEOUT, deadline - time.monotonic()))
        if head and head.strip():
            heads[toplevel] = head.strip()
    if heads:
        _prune_heads(path.parent)
        security_scan._write_json(path, {"heads": heads, "written": time.time()})


def _take_recorded_heads(root: Path, tool_use_id: object) -> "dict[str, str]":
    """The record `_record_integration_heads` wrote for this tool call (removed on reading), or {}."""
    path = _heads_file(root, tool_use_id)
    if path is None:
        return {}
    data = security_scan._read_json(path)
    try:
        path.unlink()
    except OSError:
        pass
    heads = data.get("heads") if data else None
    if not isinstance(heads, dict):
        return {}
    return {str(key): str(value) for key, value in heads.items() if isinstance(value, str)}


def _git_dir_has_state_head(toplevel: str, budget: float) -> bool:
    """True while a merge, cherry-pick or rebase is open in `toplevel` (one git call, then plain
    file checks in the repository's own git directory -- worktrees included)."""
    output = _run_git(["rev-parse", "--git-dir"], toplevel, budget)
    if not output or not output.strip():
        return False
    git_dir = Path(toplevel) / output.strip()  # an absolute answer replaces the top level
    return any((git_dir / head).exists() for head in _STATE_HEADS)


def _integration_lock_files(
    call: _IntegrationCall, toplevel: str, deadline: float, recorded_head: Optional[str] = None,
) -> "list[str]":
    """Absolute paths of the lock files one merge/pull/cherry-pick brought into the tree at
    `toplevel`: the committed change plus, while an operation is still open (MERGE_HEAD,
    CHERRY_PICK_HEAD, REBASE_HEAD, or `--no-commit`), everything the tree differs from HEAD in. The
    committed change is HEAD against the HEAD recorded before the call when there is one;
    otherwise it comes from the reflog and only when HEAD moved within `_FRESH_SECONDS`
    (ORIG_HEAD..HEAD for merge and pull, the picked commits for cherry-pick). A lock file that is
    unmerged is left out: it holds conflict markers, no tool can read it, and the commit that
    concludes the merge is checked by the commit check."""
    def budget() -> float:
        return min(_GIT_TIMEOUT, deadline - time.monotonic())

    names: "set[str]" = set()
    base: Optional[str] = None
    if recorded_head:
        base = recorded_head
    else:
        entries = _fresh_reflog(toplevel, budget())
        if entries and entries[0][2]:
            subject = entries[0][1]
            if call.subcommand == "cherry-pick":
                picked = 0
                while picked < len(entries) and entries[picked][2] and entries[picked][1].startswith("cherry-pick"):
                    picked += 1
                if picked and picked < len(entries):
                    base = entries[picked][0]
                elif picked:  # every fetched entry is a pick: the entry before the first one
                    before = _run_git(["rev-parse", "-q", "--verify", f"HEAD@{{{picked}}}"], toplevel, budget())
                    base = before.strip() if before and before.strip() else None
            elif subject.startswith(_MERGE_SUBJECT_PREFIXES):
                origin = _run_git(["rev-parse", "-q", "--verify", "ORIG_HEAD"], toplevel, budget())
                base = origin.strip() if origin and origin.strip() else (entries[1][0] if len(entries) > 1 else None)
    if base is not None:
        names.update(_git_names(["diff", "--name-only", base, "HEAD"], toplevel, budget()))

    state_open = _git_dir_has_state_head(toplevel, budget())
    in_progress = state_open or bool(_INTEGRATION_NO_COMMIT_FLAGS[call.subcommand] & set(call.args))
    unmerged: "set[str]" = set()
    if in_progress:
        names.update(_git_names(["diff", "--name-only", "HEAD"], toplevel, budget()))
    if state_open:
        unmerged = set(_git_names(["diff", "--name-only", "--diff-filter=U"], toplevel, budget()))

    base_path = Path(toplevel)
    found: "list[str]" = []
    for name in sorted(names - unmerged):
        if Path(name).name not in _ALL_LOCK_BASENAMES:
            continue
        path = base_path / name
        try:
            found.append(str(path.resolve()))
        except OSError:
            found.append(str(path))
    return found


def _reported_marker(root: Path, state_hash: str) -> Path:
    return security_scan.cache_dir(root) / f"{state_hash}.reported.json"


def _unaccepted_findings(root: Path, result: security_scan.ScanResult) -> "list[security_scan.Finding]":
    """The findings of `result` no accepted advisory covers, most severe first."""
    accepted = security_scan.load_accepted(root)
    return sorted(
        (f for f in result.findings if not security_scan.is_accepted(f.advisory_id, accepted)),
        key=lambda f: _SEVERITY_ORDER.get(f.severity, len(_SEVERITY_ORDER)),
    )


def _claim_reported_marker(marker: Path) -> bool:
    """Creates the marker atomically (O_EXCL): True for the one caller that made it, False when it
    exists already or cannot be created -- two hooks on the same state never both report."""
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:  # FileExistsError included
        return False
    try:
        os.write(fd, (json.dumps({"written": time.time()}) + "\n").encode("ascii"))
    except OSError:
        pass  # an empty marker still claims the state
    finally:
        os.close(fd)
    return True


def _report_result(root: Path, state_hash: str, result: security_scan.ScanResult, paths: "list[Path]") -> bool:
    """One inbox report entry for the unaccepted findings in `result`; False (nothing written) for
    a clean result, only accepted findings, a state already reported (the marker never expires: the
    same lock-file state is reported once), or a failed write -- which releases the marker again."""
    findings = _unaccepted_findings(root, result)
    if not findings:
        return False
    marker = _reported_marker(root, state_hash)
    if marker.exists() or not _claim_reported_marker(marker):
        return False
    try:
        import entries  # deferred: only a run that has something to report needs it
        names = [_display(path, root) for path in paths]
        shown_files = ", ".join(names[:10]) + (f" (+{len(names) - 10} more)" if len(names) > 10 else "")
        lines = "\n".join(f"- {_format_finding(finding, {})}" for finding in findings[:20])
        more = f"\n- (+{len(findings) - 20} more)" if len(findings) > 20 else ""
        body = (
            "The lock files that `git merge`, `git pull` or `git cherry-pick` just brought in were scanned "
            "for known vulnerabilities (`security-check: deps`). Nothing was blocked.\n\n"
            f"Lock files checked: {shown_files}\n\n"
            f"Unaccepted findings:\n{lines}{more}\n\n"
            "Update the package, or accept an advisory with a reason in "
            "`docs/ai/local/security-accepted.md` (a line `- <advisory-id>: <reason>`). "
            "The commit check holds an unaccepted high or critical finding in a lock file a commit touches. "
            "Rescan with `python .act/scripts/security_scan.py --deps`.\n"
        )
        count = len(findings)
        entries.create_entry(
            root, "report",
            f"Dependency scan after merge: {count} unaccepted finding{'s' if count != 1 else ''}",
            body=body, slug="dependency-scan-after-merge",
        )
    except Exception:  # noqa: BLE001 -- best effort: a failed report must never disturb the hook chain
        try:
            marker.unlink()
        except OSError:
            pass
        return False
    return True


def _scan_after_integration(payload: dict) -> None:
    if _is_worker(payload):
        return  # a worker's git access is read-only; it never brings anything in
    shell = _shell_command(payload)
    if shell is None:
        return
    command = shell[1]
    if "git" not in command or not any(word in command for word in _INTEGRATION_SUBCOMMANDS):
        return
    if _security_check_level(actlib.read_config()) not in ("deps", "full"):
        return
    try:
        root = actlib.repo_root().resolve()
    except (RuntimeError, OSError):
        return
    recorded = _take_recorded_heads(root, payload.get("tool_use_id"))
    calls = _integration_calls(command, _base_cwd(payload))
    if not calls or not security_scan.available_tools():
        return

    deadline = time.monotonic() + _NOTE_TIME_BUDGET
    touched: "set[str]" = set()
    for call in calls:
        if call.target is None or not _targets_own_project(call.target, root):
            continue
        toplevel = _repo_toplevel(str(call.target), min(_GIT_TIMEOUT, deadline - time.monotonic()))
        if toplevel is None:
            continue
        touched.update(_integration_lock_files(call, toplevel, deadline, recorded.get(toplevel)))
    paths, _unreadable = _readable_lock_files(root, sorted(touched), deadline)
    if not paths or time.monotonic() >= deadline:
        return
    state_hash = security_scan.lock_set_digest(paths)
    if state_hash is None or _reported_marker(root, state_hash).exists():
        return

    cached = _current_cache(root, state_hash, date.today().isoformat())
    if cached is not None:
        if _unaccepted_findings(root, cached):
            # the inbox write can wait on the entries lock: the detached worker does it, not this hook
            _spawn_scan_worker(root, state_hash, paths, report=True)
        return
    now = time.time()
    marker = security_scan.read_running_marker(root, state_hash)
    if marker is not None:
        if now > marker["stale_after"]:
            security_scan.clear_running_marker(root, state_hash)
        return  # a scan of exactly this state is in flight (or was dead -- the next call spawns afresh)
    lock_files = security_scan.lock_files_from_paths(paths)
    stale_after = now + security_scan.scan_time_limit(lock_files) + _WORKER_MARGIN_SECONDS
    if not security_scan.write_running_marker(root, state_hash, stale_after):
        return
    if not _spawn_scan_worker(root, state_hash, paths, report=True):
        security_scan.clear_running_marker(root, state_hash)


def note_deps_merge_scan(payload: dict) -> Optional[str]:
    """PostToolUse (and PostToolUseFailure) companion for a `git merge|pull|cherry-pick`: scans the
    lock files it brought in, in the background, and files a finding as an inbox report. Never
    returns a note -- the inbox is the channel -- and never blocks. Registered in dispatch.py's own
    _POST_TOOL_USE_NOTES; an exception here is logged and skipped by the caller."""
    _scan_after_integration(payload)
    return None
