#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check 1d — parallel workers never share write scope (R-cost-delegate, PreToolUse
#          Agent/Task of the orchestrator) plus the observer that frees a finished worker's entry.
#
# The orchestrator starts a worker with a `Write scope:` line (see checks/write_scope.py, which
# parses it and records one file per start under .act-local/worker-scopes/<tool_use_id>.json).
# Two workers running at the same time must not write into the same files, so a start whose scope
# overlaps the scope of a worker that is still running is refused (or only reported, mode warn).
#
# A test or probe run reads a tree and must not run next to a worker that writes in it, so an assignment
# that runs tests also names the tree it reads as its own line `Tests: <glob>[, <glob> ...]` (same
# patterns and normalization as `Write scope:`, see write_scope._parse_tests_scope); it is recorded in the
# start's entry under "tests". A starting worker's `Tests:` patterns are compared with the `Write scope:` of
# every running worker, and its `Write scope:` with the `Tests:` of every running worker, with the same
# overlap test as below. Two `Tests:` lines never clash (two readers), and a worker's own `Tests:` against
# its own `Write scope:` is no conflict (a worker is only compared with the others).
#
# Rules: `Write scope: none` never overlaps anything (read-only), a `Tests:` line included. A start without
# the line counts as "everything" — it overlaps every scope except none; against a `Tests:` line it overlaps
# that line too (it may write anywhere), and a running worker without the line likewise overlaps a starting
# `Tests:` line. Two pattern lists overlap when one pair of
# patterns may match the same path. An exact path is compared with the other pattern by matching it
# (write_scope._matches_scope). Two glob patterns are compared as the matching reads them — `*` any run
# of characters, `/` included, `?` any one character, every other character (a `[` too) itself — and
# overlap when one string can match both: `src/lib/alpha/**` and `src/lib/beta*` do not (the literal
# `alpha` and `beta` part them), `src/lib/**` and `src/lib/beta*` do, and so do a pattern that starts
# with a wildcard and any other that it can reach (`*.md` and `docs/**`). `dir/**` also counts as the
# directory `dir`, which a worker with that scope may create. Patterns longer than _TABLE_LIMIT
# (as a product of their lengths) count as overlapping. Patterns are normalized by
# write_scope._parse_write_scope (a trailing "/" means "/**", absolute paths and `../sibling/...`
# resolve the same way).
#
# "Still running" = an entry exists, the observer has not marked it ended, and it is younger than
# _OVERLAP_ENTRY_TTL. The harness reports a stop only with an agent_id; the entry is found through
# <session>/subagents/agent-<id>.meta.json ("toolUseId"), as write_scope does. The harness also fires
# SubagentStop for its own helper agents, which never had an entry — those are passed over silently (see
# checks/event_log.py). Three events reach observe():
#   - SubagentStop, and PostToolUse of the orchestrator's TaskStop (its tool_input.task_id is the agent id;
#     a worker stopped that way is not seen ending through SubagentStop): the entry is marked ended, not
#     deleted. The worker no longer counts as running.
#   - SubagentStart: a worker the orchestrator continues with a message (SendMessage) starts again under
#     the same agent id, and no new Agent/Task call records anything. If its entry is marked ended, the mark
#     is cleared and the entry's time renewed: the worker runs again. write_scope finds its scope either
#     way (an ended entry still binds a call of that agent id to its scope).
# Why marked, not deleted: a deleted entry is gone for the resume, and the restricted scopes of workers
# started in the meantime then make write_scope's fail-closed fallback refuse the resumed worker's own writes.
# A worker that crashed without a stop leaves its entry until the TTL; the message names the way to free it
# at once (stop it with TaskStop).
#
# The orchestrator gets a note, never a refusal (check_main_session_overlap, same switch; `off` silences it, a
# `block` row counts as `warn` for it): a Write/Edit/MultiEdit/NotebookEdit path, or a write target of its
# Bash/PowerShell command (the scanners write_scope uses), that falls under the `Tests:` of a running worker, and
# a command that runs the project's test command (third entry of `commands`) in a tree a running worker writes in.
# A target that is dynamic (`$VAR`, `~`), or relative with no known directory, cannot be placed and passes; inline
# code the reader fails on is not looked at. The note is printed (it is a hint, not an entry of the incident log) and
# queued under .act-local/worker-scopes/hints/<tool_use_id>.json, because PreToolUse text never reaches the model:
# note_main_session_overlap delivers it with this call's PostToolUse (registered in dispatch.py's
# _POST_TOOL_USE_NOTES).
#
# This check records the start's own entry too (same file and content write_scope writes), so it
# works when `worker-write-scope` is off, and so a second start right behind the first already
# sees it. Two starts racing within the same instant can still both pass: each reads before the
# other has written.

from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import actlib

from . import inline_code as _inline_code
from .command_parse import Parse, parse_for
from .common import _TOOL_PATH_FIELDS, _WORKER_TOOL_NAMES, _check_mode, _pop_pending_notes, _queue_pending_note
from .shell_targets import (
    _GIT_WRITES_WORKER_SCOPE,
    _command_name,
    _is_absolute_target,
    _is_dynamic_target,
    _resolve_path,
)
from .write_scope import (
    _INLINE_DYNAMIC_RE,
    _SAFE_ID_RE,
    _assignment_scope,
    _entry_has_ended,
    _inline_literal_path,
    _matches_scope,
    _normalize_candidate_path,
    _read_json_object,
    _record_worker_scope,
    _split_glob_prefix,
    _store_worker_scope_entry,
    _target_forms,
    _worker_scope_file,
    _worker_scopes_dir,
)

__all__ = [
    "_OVERLAP_ENTRY_TTL", "_entry_time", "_patterns_overlap", "_scopes_overlap", "_tests_overlap", "_remove_worker_scope",
    "_mark_worker_scope", "check_worker_scope_overlap", "check_main_session_overlap", "note_main_session_overlap",
    "observe",
]

# Shorter than write_scope's 24 h: a crashed worker or a start refused by a later check leaves an
# entry that would otherwise lock its area for a day. Longer than a normal assignment.
_OVERLAP_ENTRY_TTL = timedelta(hours=3)
_FUTURE_SLACK = timedelta(minutes=5)  # a timestamp further ahead is invalid, not "running"
_TABLE_LIMIT = 250_000  # pattern length product up to which two globs are compared exactly


def _glob_forms(pattern: str) -> list[str]:
    """What a pattern matches as write_scope._matches_scope reads it: the pattern itself and, for
    `dir/**`, the directory `dir` as well (a worker with that scope may create it)."""
    root = pattern[:-3] if pattern.endswith("/**") and len(pattern) > 3 else None
    if root is not None and not any(char in root for char in "*?"):
        return [pattern, root]
    return [pattern]


def _globs_intersect(first: str, second: str) -> bool:
    """True if some path matches both patterns, read the way write_scope._matches_scope matches
    (fnmatch): `*` is any run of characters, `/` included, `?` is any one character, everything else —
    `[` too — stands for itself. Two such patterns are compared character by character, so a literal
    part that cannot match (`t194-*` against `t195-*`) keeps them apart wherever the glob sits. Patterns
    too long to tabulate count as meeting (the cautious answer)."""
    rows, cols = len(first), len(second)
    if rows * cols > _TABLE_LIMIT:
        return True
    # meet[i][j]: the tails first[i:] and second[j:] have a common match. A `*` matches nothing or
    # eats one character of the other pattern's tail (a `*` of its own included, which is the same as
    # skipping it); any other pair of characters must agree, `?` agreeing with every one.
    meet = [[False] * (cols + 1) for _ in range(rows + 1)]
    for i in range(rows, -1, -1):
        for j in range(cols, -1, -1):
            if i == rows and j == cols:
                meet[i][j] = True
            elif i < rows and first[i] == "*":
                meet[i][j] = meet[i + 1][j] or (j < cols and meet[i][j + 1])
            elif j < cols and second[j] == "*":
                meet[i][j] = meet[i][j + 1] or (i < rows and meet[i + 1][j])
            elif i < rows and j < cols:
                meet[i][j] = (first[i] == "?" or second[j] == "?" or first[i] == second[j]) and meet[i + 1][j + 1]
    return meet[0][0]


def _patterns_overlap(first: str, second: str) -> bool:
    """True if two normalized Write scope patterns may match the same path (cautious)."""
    first_abs, second_abs = _is_absolute_target(first), _is_absolute_target(second)
    if first_abs != second_abs:
        return False  # project-relative vs. sibling-checkout (absolute) patterns never meet
    if os.name == "nt" or first_abs:
        first, second = first.casefold(), second.casefold()  # Windows paths ignore case
    first_prefix, first_glob = _split_glob_prefix(first)
    second_prefix, second_glob = _split_glob_prefix(second)
    if not first_glob and not second_glob:
        return first == second
    if not first_glob:
        return _matches_scope(first, [second])
    if not second_glob:
        return _matches_scope(second, [first])
    return any(
        _globs_intersect(one, other)
        for one in _glob_forms(first)
        for other in _glob_forms(second)
    )


def _describe(scope: dict) -> str:
    if scope.get("mode") == "unrestricted":
        return "everything (no `Write scope:` line)"
    return ", ".join(scope.get("patterns") or [])


def _scopes_overlap(new: dict, other: dict) -> Optional[tuple[str, str]]:
    """None if the two scopes cannot collide, else a pair of readable descriptions (new, other)."""
    new_mode, other_mode = new.get("mode"), other.get("mode")
    if new_mode not in ("patterns", "unrestricted") or other_mode not in ("patterns", "unrestricted"):
        return None  # none (read-only) and error (writes nothing) never overlap
    if new_mode == "unrestricted" or other_mode == "unrestricted":
        return _describe(new), _describe(other)
    for pattern in new.get("patterns") or []:
        for existing in other.get("patterns") or []:
            if isinstance(pattern, str) and isinstance(existing, str) and _patterns_overlap(pattern, existing):
                return pattern, existing
    return None


def _write_line(scope: dict, shown: str) -> str:
    """How a message names the `Write scope:` of a scope: its line with the matching pattern, or the missing line."""
    if scope.get("mode") == "unrestricted":
        return "no `Write scope:` line (counts as everything)"
    return f"`Write scope: {shown}`"


def _tests_overlap(reader: dict, writer: dict) -> Optional[tuple[str, str]]:
    """None if the tree `reader` runs tests in (its `Tests:` patterns) cannot meet what `writer` writes (its
    scope), else a pair of readable descriptions (a Tests pattern, the writer's scope). A writer without a
    `Write scope:` line may write anywhere; `none` and an unusable scope write nothing."""
    tests = [pattern for pattern in reader.get("tests") or [] if isinstance(pattern, str)]
    if not tests or writer.get("mode") not in ("patterns", "unrestricted"):
        return None
    if writer.get("mode") == "unrestricted":
        return tests[0], _describe(writer)
    for pattern in tests:
        for existing in writer.get("patterns") or []:
            if isinstance(existing, str) and _patterns_overlap(pattern, existing):
                return pattern, existing
    return None


def _entry_time(entry: dict) -> Optional[datetime]:
    """The entry's timestamp as an aware datetime (a naive one is read as UTC), else None."""
    ts = entry.get("ts")
    try:
        when = datetime.fromisoformat(ts) if isinstance(ts, str) else None
        if when is not None and when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    return when


def _entry_is_running(entry: dict) -> bool:
    """Not marked ended, younger than the TTL and not more than 5 minutes in the future (then it is
    invalid)."""
    if _entry_has_ended(entry):
        return False
    when = _entry_time(entry)
    if when is None:
        return False
    now = datetime.now(timezone.utc)
    try:
        return now - _OVERLAP_ENTRY_TTL <= when <= now + _FUTURE_SLACK
    except TypeError:
        return False


def check_worker_scope_overlap(payload: dict) -> int:
    """Check 1d: refuse an Agent/Task start whose write scope overlaps a running worker's
    (R-cost-delegate). Only the orchestrator's own calls are looked at. Parallel starts of one
    message really run at the same time, so the start first writes its own entry and only then
    reads the others; of two overlapping starts the one with the later (ts, tool_use_id) yields —
    it removes its own entry and is refused, the earlier one stays. Never both pass, never both
    refused."""
    config = actlib.read_config()
    mode = _check_mode(config, "worker-scope-overlap", default="block")
    if mode == "off":
        return 0
    if payload.get("agent_id") or payload.get("tool_name") not in _WORKER_TOOL_NAMES:
        return 0
    tool_input = payload.get("tool_input")
    tool_use_id = payload.get("tool_use_id")
    prompt = tool_input.get("prompt") if isinstance(tool_input, dict) else None
    if not isinstance(prompt, str) or not isinstance(tool_use_id, str) or not tool_use_id:
        return 0
    try:
        root = actlib.repo_root()
    except RuntimeError:
        return 0

    new = _assignment_scope(prompt, root)
    _record_worker_scope(root, tool_use_id, new)  # claim first, then look at the others
    own_file = _worker_scope_file(root, tool_use_id)
    own_entry = _read_json_object(own_file) if own_file is not None else None
    own_when = _entry_time(own_entry) if own_entry else None
    own_key = (own_when or datetime.now(timezone.utc), tool_use_id)
    try:
        candidates = sorted(_worker_scopes_dir(root).glob("*.json"))
    except OSError:
        candidates = []
    for path in candidates:
        if path == own_file:
            continue
        entry = _read_json_object(path)
        if entry is None or not _entry_is_running(entry):
            continue
        other_when = _entry_time(entry)
        if other_when is None or (other_when, path.stem) > own_key:
            continue  # started after this one: that start yields, not this one
        free = (
            "If that worker is no longer wanted, stop it with TaskStop: that frees it at once. A worker that "
            f"crashed without any stop frees it after {_OVERLAP_ENTRY_TTL}."
        )
        clash = _scopes_overlap(new, entry)
        reads = _tests_overlap(new, entry)
        writes = None if reads else _tests_overlap(entry, new)
        if clash is not None:
            message = (
                f"[act] write scope overlaps a running worker's: {clash[0]} vs. {clash[1]} "
                f"(worker {path.stem}) — parallel workers need separate write scopes (R-cost-delegate): give "
                "each assignment its own line `Write scope: <glob>[, <glob> ...]`, e.g. `Write scope: "
                "src/api/**` (syntax: .act/rules/topics/checks.md); or merge both tasks into one assignment "
                "with one write scope; or start this one after the other has ended. If that worker is no longer "
                "wanted, stop it with TaskStop: that frees its scope at once. A worker that crashed without any "
                f"stop frees it after {_OVERLAP_ENTRY_TTL}."
            )
        elif reads is not None:
            message = (
                f"[act] the tree this assignment runs tests in is written by a running worker: `Tests: "
                f"{reads[0]}` vs. that worker's {_write_line(entry, reads[1])} (worker {path.stem}) — a test or "
                "probe run never runs against a tree a worker writes in at the same time (R-cost-delegate): "
                "start this one after that worker has ended, or test an isolated copy (a clone or worktree) and "
                "name the copy in `Tests:` (syntax: .act/rules/topics/checks.md). " + free
            )
        elif writes is not None:
            message = (
                f"[act] a running worker runs tests in the tree this assignment writes: "
                f"{_write_line(new, writes[1])} vs. that worker's `Tests: {writes[0]}` (worker {path.stem}) — a test or "
                "probe run never runs against a tree a worker writes in at the same time (R-cost-delegate): "
                "start this one after that test run has ended, or let that worker test an isolated copy (a "
                "clone or worktree) and name the copy in its `Tests:` line (syntax: .act/rules/topics/checks.md). "
                + free
            )
        else:
            continue
        if mode == "warn":
            print(message)
            return 0
        _remove_worker_scope(root, tool_use_id)
        print(message, file=sys.stderr)
        return 2
    return 0


_TMP_PREFIX = ".act-local/tmp/"  # a worker scope below it is an isolated copy (a clone, a throwaway project)
_HINTS_DIRNAME = "hints"  # below .act-local/worker-scopes/: notes owed to one tool call, by tool_use_id
_CD_NAMES = frozenset({"cd", "pushd", "chdir", "set-location", "sl"})
_MAX_TREE_WORDS = 60  # words of one test command line looked at as paths


def _running_entries(root: Path) -> list[tuple[str, dict]]:
    """(tool_use_id, entry) of every worker that is running now (_entry_is_running). An unreadable registry
    or entry counts as no worker, as in check_worker_scope_overlap."""
    try:
        candidates = sorted(_worker_scopes_dir(root).glob("*.json"))
    except OSError:
        return []
    found: list[tuple[str, dict]] = []
    for path in candidates:
        entry = _read_json_object(path)
        if entry is not None and _entry_is_running(entry):
            found.append((path.stem, entry))
    return found


def _tests_of(entry: dict) -> list[str]:
    tests = entry.get("tests")
    return [pattern for pattern in tests if isinstance(pattern, str)] if isinstance(tests, list) else []


def _first_tests_hit(target: str, running: list[tuple[str, dict]]) -> Optional[tuple[str, str]]:
    """(worker id, pattern) of the first running worker whose `Tests:` pattern may match `target`, a path in
    the form write_scope._normalize_candidate_path gives (project-relative, else absolute)."""
    for worker_id, entry in running:
        for pattern in _tests_of(entry):
            if _patterns_overlap(target, pattern):
                return worker_id, pattern
    return None


def _main_write_paths(
    payload: dict, root: Path
) -> tuple[list[tuple[str, Optional[str], bool]], list[tuple[str, Optional[str]]]]:
    """What a call of the main session writes, read with the scanners write_scope uses for a worker's call:
    ([(raw target, directory it resolves against or None, literal name of a brace list)], [(path literal of
    inline interpreter code, directory or None)]). Raises inline_code.ReaderFailure like write_scope does."""
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        return [], []
    pairs: list[tuple[str, Optional[str]]] = []
    inline: list[tuple[str, Optional[str], str]] = []
    if tool_name in _TOOL_PATH_FIELDS:
        for field in _TOOL_PATH_FIELDS[tool_name]:
            value = tool_input.get(field)
            if isinstance(value, str) and value:
                pairs.append((value, str(root)))
    elif tool_name in ("Bash", "PowerShell"):
        command = tool_input.get("command")
        if not isinstance(command, str):
            return [], []
        cwd_raw = payload.get("cwd")
        base_cwd = cwd_raw if isinstance(cwd_raw, str) and cwd_raw else str(root)
        parse = parse_for(payload, command)
        if tool_name == "Bash":
            pairs = list(parse.bash_write_targets(base_cwd, _GIT_WRITES_WORKER_SCOPE))
            inline = parse.inline_targets(base_cwd)
        else:
            ps_targets = parse.write_targets(base_cwd, _GIT_WRITES_WORKER_SCOPE)
            if ps_targets is None:
                ps_targets = parse.ps_raw_redirects()
            pairs = [(target, None) for target in ps_targets]
            inline = parse.inline_targets(base_cwd)
    forms: list[tuple[str, Optional[str], bool]] = []
    seen: set[tuple] = set()
    for raw, base in pairs:
        for path, literal_brace in _target_forms(tool_name, raw):
            key = (str(path), base, literal_brace)
            if key not in seen:
                seen.add(key)
                forms.append((path, base, literal_brace))
    return forms, [(raw, base) for raw, base, _language in inline]


def _placed(raw: str, base: Optional[str], root: Path, dynamic: bool) -> Optional[str]:
    """The target as a path to compare (project-relative, else absolute), or None where it cannot be placed:
    still expanded by the shell (`dynamic`), or relative with no known directory."""
    if dynamic or (base is None and not _is_absolute_target(raw)):
        return None
    return _normalize_candidate_path(raw, root, base if base is not None else str(root))


def _write_note(shown: str, pattern: str, worker_id: str) -> str:
    return (
        f"[act] note: a running worker runs tests in this tree: {shown} falls under that worker's `Tests: {pattern}` "
        f"(worker {worker_id}) — a write there can fail its run without saying anything about the code "
        "(R-cost-delegate). Not refused; the way out: wait until that worker has ended (or stop it with TaskStop), "
        "or work in an isolated copy (a clone or worktree)"
    )


def _split_commands_cell(value: str) -> list[str]:
    """The `commands` cell of docs/ai/config.md as its entries: split at a comma outside backticks."""
    parts: list[str] = []
    buffer: list[str] = []
    in_code = False
    for char in value:
        if char == "`":
            in_code = not in_code
        if char == "," and not in_code:
            parts.append("".join(buffer).strip())
            buffer = []
        else:
            buffer.append(char)
    parts.append("".join(buffer).strip())
    return parts


def _test_command_words(config: dict) -> list[str]:
    """The words of the configured test command (third entry of `commands`); [] when it is not set."""
    parts = _split_commands_cell(config.get("commands", ""))
    command = parts[2].strip("`").strip() if len(parts) >= 3 else ""
    return [] if command.lower() in ("", "(not set)", "none") else command.split()


def _normal_program(word: str) -> str:
    name = _command_name(word)
    return "python" if name in ("python3", "py") else name


# Interpreter options that do not change which script runs: `-u`, `-B`, `-I`, `-E`, `-O`, `-s`, `-S`, `-q`,
# `-v`, `-X <opt>` / `-Xopt`, `-W <arg>` / `-Warg`, and the launcher's version `-3`, `-3.12`, `-3-64`.
# Anything else (`-m`, `-c`, an unknown option) ends the list and counts as part of the command.
_PYTHON_OPTION_RE = re.compile(r"-(?:[BEIOsSuqv]+|[XW].+|\d(?:\.\d+)?(?:-\d+)?)")


def _without_python_options(words: list[str]) -> list[str]:
    """`words` of a Python call with the options of _PYTHON_OPTION_RE between the program and the script
    removed; any other command is returned as it is."""
    if not words or _normal_program(str(words[0])) != "python":
        return words
    index = 1
    while index < len(words):
        word = str(words[index])
        if word in ("-X", "-W") and index + 1 < len(words):
            index += 2
        elif _PYTHON_OPTION_RE.fullmatch(word):
            index += 1
        else:
            break
    return [words[0], *words[index:]]


def _runs_test_command(words: list[str], test: list[str]) -> bool:
    """True if the simple command `words` starts with the words of the test command. The program is compared
    by name (`python3` = `python`, directory and `.exe` dropped); a later word of the test command that is a
    path (`tests/run.py`) also matches the same path spelled with a longer directory in front
    (`D:/clone/tests/run.py`), since a run in a copy is the same run in another tree. Interpreter options in
    front of the script (`py -3 tests/run.py`, `python -X utf8 tests/run.py`) do not change the run."""
    words, test = _without_python_options(words), _without_python_options(test)
    if len(words) < len(test) or _normal_program(str(words[0])) != _normal_program(test[0]):
        return False
    for word, wanted in zip(words[1:], test[1:]):
        have = str(word).replace("\\", "/")
        want = wanted.replace("\\", "/").removeprefix("./")
        if have != want and not ("/" in want and have.endswith("/" + want)):
            return False
    return True


def _test_run_trees(
    command: str, cwd: str, root: Path, test: list[str], parse: Optional[Parse] = None,
) -> list[tuple[str, bool]]:
    """(path, is a directory) of the tree each run of the test command in `command` reads: the directory it
    runs in (the call's cwd, moved by a literal `cd` in front of it) and every word of the run that names an
    existing file or directory. Paths are in the form write_scope._normalize_candidate_path gives. `parse` is
    the dispatcher's reading of `command`; without it the command is read here."""
    if parse is None:
        parse = Parse("Bash", command)
    trees: list[tuple[str, bool]] = []
    current = cwd
    for words in parse.stripped():
        if not words:
            continue
        if _command_name(str(words[0])) in _CD_NAMES:
            operands = [str(word) for word in words[1:] if not str(word).startswith("-")]
            if operands and not _INLINE_DYNAMIC_RE.search(operands[0]):
                resolved = _resolve_path(operands[0], current)
                if resolved is not None:
                    current = str(resolved)
            continue
        if not _runs_test_command(words, test):
            continue
        places: list[tuple[str, bool]] = [(current, True)]
        for word in [str(one) for one in words[:_MAX_TREE_WORDS]]:
            if word.startswith("-") and "=" in word:
                word = word.split("=", 1)[1]
            if not word or word.startswith("-") or _INLINE_DYNAMIC_RE.search(word) or any(c in word for c in "*?"):
                continue
            resolved = _resolve_path(word, current)
            try:
                if resolved is not None and resolved.exists():
                    places.append((str(resolved), resolved.is_dir()))
            except OSError:
                continue
        for place, is_dir in places:
            rel = _normalize_candidate_path(place, root, current)
            if rel is not None and (rel, is_dir) not in trees:
                trees.append((rel, is_dir))
    return trees


def _tree_meets_scope(tree: str, is_dir: bool, scope: dict) -> Optional[str]:
    """The pattern of a worker's `Write scope:` (or a description of it) that meets the tree a test run reads,
    else None. A pattern below .act-local/tmp/ is an isolated copy: it counts only for a tree that is itself
    below .act-local/tmp/ (the copy, a part of it or a folder inside it), never for the project root or a
    folder that merely contains the area. A worker without a `Write scope:` line writes everywhere."""
    if scope.get("mode") == "unrestricted":
        return _describe(scope)
    if scope.get("mode") != "patterns":
        return None
    in_tmp = tree.startswith(_TMP_PREFIX)
    region = "**" if tree in (".", "") else (f"{tree}/**" if is_dir else tree)
    for pattern in scope.get("patterns") or []:
        if not isinstance(pattern, str) or (pattern.startswith(_TMP_PREFIX) and not in_tmp):
            continue
        if _patterns_overlap(pattern, region):
            return pattern
    return None


def _hint_file(root: Path, tool_use_id: str) -> Optional[Path]:
    if not isinstance(tool_use_id, str) or not _SAFE_ID_RE.match(tool_use_id):
        return None
    return _worker_scopes_dir(root) / _HINTS_DIRNAME / f"{tool_use_id}.json"


def _queue_hint(root: Path, tool_use_id: object, text: str, payload: "dict | None" = None) -> None:
    """Owe `text` to this call's PostToolUse (note_main_session_overlap); old leftovers (a call refused by a later
    check never gets one) are removed on the way. Without a usable tool_use_id nothing is queued."""
    path = _hint_file(root, tool_use_id) if isinstance(tool_use_id, str) else None
    if path is None:
        return
    _queue_pending_note(path, text, payload)
    try:
        limit = time.time() - _OVERLAP_ENTRY_TTL.total_seconds()
        for old in path.parent.glob("*.json"):
            if old != path and old.stat().st_mtime < limit:
                old.unlink()
    except OSError:
        pass


def _main_session_mode(config: dict) -> str:
    """`off` when the switch is off, else `warn`: the main session is never refused, so a `block` row counts as
    `warn` here. Its notes are hints to the main session, never an entry of the incident log."""
    if _check_mode(config, "worker-scope-overlap", default="block") == "off":
        return "off"
    return "warn"


def _say(root: Path, payload: dict, text: str) -> None:
    """The note: on stdout like any warn check (transcript) and queued for the model."""
    print(text)
    _queue_hint(root, payload.get("tool_use_id"), text, payload)


def check_main_session_overlap(payload: dict) -> int:
    """The orchestrator gets notes, never a refusal (R-cost-delegate), under the switch of
    check_worker_scope_overlap. (1) A path it writes, with a file tool or as a write target of a shell command, that
    falls under the `Tests:` of a running worker. (2) A shell command that runs the configured test command in a tree
    a running worker writes in. Always returns 0. A worker's own call is not looked at (write_scope does)."""
    config = actlib.read_config()
    if _main_session_mode(config) == "off" or payload.get("agent_id"):
        return 0
    tool_name = payload.get("tool_name")
    if tool_name not in _TOOL_PATH_FIELDS and tool_name not in ("Bash", "PowerShell"):
        return 0
    try:
        root = actlib.repo_root()
    except RuntimeError:
        return 0
    running = _running_entries(root)
    if not running:
        return 0

    testers = [(worker_id, entry) for worker_id, entry in running if _tests_of(entry)]
    if testers:
        try:
            targets, inline = _main_write_paths(payload, root)
        except _inline_code.ReaderFailure:
            targets, inline = [], []  # inline code the reader fails on is not looked at (named limit)
        candidates = [(raw, _placed(raw, base, root, _is_dynamic_target(raw) and not literal))
                      for raw, base, literal in targets]
        candidates += [
            (raw, _placed(_inline_literal_path(raw, base, root), base, root, _INLINE_DYNAMIC_RE.search(raw) is not None))
            for raw, base in inline
        ]
        for raw, placed in candidates:
            hit = _first_tests_hit(placed, testers) if placed is not None else None
            if hit is not None:
                _say(root, payload, _write_note(raw, hit[1], hit[0]))
                return 0

    shell = payload.get("tool_input") if tool_name in ("Bash", "PowerShell") else None
    command = shell.get("command") if isinstance(shell, dict) else None
    test = _test_command_words(config) if isinstance(command, str) else []
    if test:
        cwd_raw = payload.get("cwd")
        cwd = cwd_raw if isinstance(cwd_raw, str) and cwd_raw else str(root)
        for tree, is_dir in _test_run_trees(command, cwd, root, test, parse_for(payload, command)):
            for worker_id, entry in running:
                shown = _tree_meets_scope(tree, is_dir, entry)
                if shown is None:
                    continue
                writer = (
                    "a worker with no `Write scope:` line (it counts as writing everywhere)"
                    if entry.get("mode") == "unrestricted" else f"that worker's `Write scope: {shown}`"
                )
                _say(root, payload, (
                    f"[act] note: a running worker writes in the tree this test run reads: "
                    f"{'the project root' if tree in ('.', '') else tree} meets {writer} "
                    f"(worker {worker_id}) — a failure may come from a half-written file (R-cost-delegate). Not "
                    "refused; the way out: run it after that worker has ended, or against an isolated copy (a clone "
                    "or worktree)"
                ))
                return 0
    return 0


def note_main_session_overlap(payload: dict) -> Optional[str]:
    """PostToolUse counterpart: the hint check_main_session_overlap queued for this very call (matched by
    tool_use_id), once; None when there is none. Registered in dispatch.py's _POST_TOOL_USE_NOTES."""
    tool_use_id = payload.get("tool_use_id")
    if payload.get("agent_id") or not isinstance(tool_use_id, str):
        return None
    try:
        path = _hint_file(actlib.repo_root(), tool_use_id)
    except RuntimeError:
        return None
    if path is None or not path.is_file():
        return None
    # a row switched off after the hint was queued: nothing is said, the file still goes
    notes = [] if _main_session_mode(actlib.read_config()) == "off" else _pop_pending_notes(path, payload)
    try:
        path.unlink()
    except OSError:
        pass
    return "\n".join(notes) if notes else None


def _remove_worker_scope(root: Path, tool_use_id: str) -> None:
    path = _worker_scope_file(root, tool_use_id)
    if path is None:
        return
    for _attempt in range(20):
        try:
            path.unlink()
            return
        except FileNotFoundError:
            return
        except OSError:
            time.sleep(0.05)  # Windows: briefly held open by a concurrent reader; the TTL is the last resort


def _mark_worker_scope(root: Path, tool_use_id: str, ended: bool) -> None:
    """Mark the entry of one Agent/Task start as ended (the worker stopped), or clear that mark and renew
    the entry's time (the worker runs again). Nothing else of the entry changes; an entry that is missing,
    unreadable or already in that state is left alone, and none is created."""
    path = _worker_scope_file(root, tool_use_id)
    entry = _read_json_object(path) if path is not None else None
    if path is None or entry is None or _entry_has_ended(entry) == ended:
        return
    now = datetime.now(timezone.utc).isoformat()
    if ended:
        entry["ended"] = now
    else:
        entry.pop("ended", None)
        entry["ts"] = now
    _store_worker_scope_entry(path, entry)


def _mark_agent_scope(payload: dict, agent_id: object, ended: bool) -> None:
    """Find the entry of the worker `agent_id` through its meta.json ("toolUseId") in the session's
    subagents folder (payload transcript_path) or next to the worker's own transcript
    (agent_transcript_path) and mark it (_mark_worker_scope). An id that is not a safe filename, a meta.json
    that is missing or has no toolUseId: nothing happens."""
    if not isinstance(agent_id, str) or not _SAFE_ID_RE.match(agent_id):
        return
    metas: list[Path] = []
    transcript = payload.get("transcript_path")
    if isinstance(transcript, str) and transcript:
        metas.append(Path(transcript).with_suffix("") / "subagents" / f"agent-{agent_id}.meta.json")
    agent_transcript = payload.get("agent_transcript_path")
    if isinstance(agent_transcript, str) and agent_transcript:
        metas.append(Path(agent_transcript).with_suffix(".meta.json"))
    root = actlib.repo_root()
    for meta_path in metas:
        meta = _read_json_object(meta_path)
        tool_use_id = meta.get("toolUseId") if meta else None
        if isinstance(tool_use_id, str) and tool_use_id:
            _mark_worker_scope(root, tool_use_id, ended)
            return


def observe(event: str, payload: dict) -> None:
    """SubagentStop and the orchestrator's TaskStop (PostToolUse): mark the stopped worker's entry ended.
    SubagentStart: clear that mark when a stopped worker is continued. PostToolUseFailure of an Agent/Task
    call: drop the entry of a start that failed. (Not PostToolUse of Agent/Task: a background agent gets
    that right at its start.) Never raises; an agent without an entry (the harness's own helper agents) is
    passed over silently."""
    try:
        if event == "PostToolUseFailure":
            tool_use_id = payload.get("tool_use_id")
            if (
                payload.get("tool_name") in _WORKER_TOOL_NAMES
                and not payload.get("agent_id")
                and isinstance(tool_use_id, str)
                and tool_use_id
            ):
                _remove_worker_scope(actlib.repo_root(), tool_use_id)
            return
        if event == "PostToolUse":
            if payload.get("tool_name") == "TaskStop" and not payload.get("agent_id"):
                tool_input = payload.get("tool_input")
                _mark_agent_scope(payload, tool_input.get("task_id") if isinstance(tool_input, dict) else None, True)
            return
        if event in ("SubagentStop", "SubagentStart"):
            _mark_agent_scope(payload, payload.get("agent_id"), event == "SubagentStop")
    except Exception:  # noqa: BLE001 — an observer must never break the event
        return
