#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check `worker-run-watch` (PreToolUse snapshot, PostToolUse note, reporting only, R-role-worker): a
#          worker's Bash or PowerShell call that runs code the other checks cannot see through (a script file, an
#          interpreter given a file or a module, a script path run directly, inline code that starts a process)
#          can commit, move a ref or write files outside the worker's Write scope. This check takes a snapshot of
#          the repositories before such a call and compares it after the call; it never refuses and never resets.
#
# Selected calls (_selected; the caller is a worker, the tool Bash or PowerShell):
#   - an interpreter started with a script file or a module: `python`, `python3`, `py` (also `py -3 x.py`),
#     `python -m <module>`, `node x.js`, `node --test`, `node -r <file>` (also `--require`, `--import`, `--loader`),
#     `bash`/`sh`/`zsh`/`dash`/`ksh` with a file argument (not `-n`, a syntax check), `pwsh`/`powershell` with
#     `-File` or a `.ps1`; `source x.sh`;
#   - the wrappers `uv run`, `poetry run`, `pipenv run`, `pdm run`, `hatch run`, `conda run`, judged by the command
#     they wrap (`uv run python x.py`);
#   - a script path run directly: any first word with a `/` or a `\` in it, whatever its extension (`./x.sh`,
#     `./gradlew`, `.\x.ps1`, `& .\x.ps1`, `& 'C:\...\x.ps1'`); a bare name needs a `.ps1`, `.bat` or `.cmd`;
#   - not selected: `py -0`, `py -0p`, `py --list`, `py --list-paths`, and the activation of a virtual environment
#     (`source .venv/bin/activate`, `& .\.venv\Scripts\Activate.ps1`, `activate.bat`);
#   - inline code whose program starts a process: Python with a call of kind CALL_RUN (inline_code.py), JavaScript
#     with a `child_process` call (`exec`, `execSync`, `spawn`, `spawnSync`, `execFile`, `execFileSync`, `fork`) in
#     its text; a program read from standard input that this reading cannot get (`python < x.py`) counts.
#   Everything else (`python --version`, `python -c "print(1)"`, `git status`, `ls`) is not selected and costs
#   nothing: no git call, no file written.
#
# Repositories compared (decided at PreToolUse, never from a path in the command): the git top-level of the project
# root plus the top-levels of the literal base folders of the calling worker's `Write scope:` patterns that lie
# outside the project (an absolute pattern, or a relative one that leaves the project, _external_form: resolved from
# the project root; a scope recorded as an error has its patterns read again from the assignment, else the one its
# message names, _own_scope);
# deduplicated, at most _MAX_REPOS; a folder without a repository is skipped.
#
# Snapshot per repository (git with fixed arguments in the top-level, `--no-optional-locks`,
# `-c core.fsmonitor=false`, no GIT_DIR / GIT_WORK_TREE / GIT_INDEX_FILE in the environment): HEAD (or the symbolic
# target when unborn), every ref with its id, and `git status --porcelain=v1 -z -uall` with the size and
# modification time of every listed path, so a file that was already modified and is written again counts as
# changed. More than _MAX_STATUS entries: the file part reports "too many changes to compare", the ref part still
# runs. Kept in .act-local/worker-run-watch/<key>.json (the dispatcher's failure key: the tool use id), written
# atomically, removed at PostToolUse; entries older than 24 h are removed at PreToolUse. Every delete goes through
# _remove: one file in that folder, fixed from the project root when the check starts, behind the guard of every
# write under .act-local/ (actlib.local_write_ok). More than _MAX_REFS_STORED refs or _MAX_STATUS paths: the note and
# the incident row come once per session and repository (too-many-<session>.seen), not on every call.
#
# Budget: the git calls of one event, and the loops that look at the file system (size and time of the listed paths,
# resolving them), share _GIT_BUDGET seconds, and never more than what is left of the
# dispatcher's hook budget (PostToolUse: what the protected-files watcher left of it). A time-out, a git error or a
# selected call whose PostToolUse finds no snapshot is reported as "comparison not possible" with the reason; the
# check never passes silently. It is registered last in dispatch.py, so a call another check refused takes no
# snapshot; it is no fail-closed guard and judges no refusal: a crash is let through with the dispatcher's report.
#
# Comparison (PostToolUse and PostToolUseFailure: a failed script is compared too):
#   - refs: "new commit" only when HEAD's target (the branch it names) is unchanged and the new id descends from the
#     old one (`git merge-base --is-ancestor`); a change of HEAD's target (branch switch, detach) is its own
#     "ref changed" line `HEAD (<old target> -> <new target>)`; a ref added, changed or removed, also a branch HEAD
#     moved to or a branch moved anywhere but forward, is "ref changed" (at most _MAX_REFS). The way back
#     `git reset --soft <old id>` is offered for "new commit" only;
#   - files: a path new in the status list, gone from it, or with another status code, size or modification time is
#     a candidate. Dropped: paths under `.act-local/`, and paths that match the `Write scope:` of any running worker
#     including the caller (worker_scope_overlap._running_entries, write_scope._matches_scope; `unrestricted`
#     matches everything inside the project). The rest is reported as "outside every running worker's Write scope"
#     (at most _MAX_FILES paths);
#   - "author uncertain": another worker runs besides the caller, or a main-session call of a writing tool ended
#     during the window (the note function touches .act-local/worker-run-watch/main-activity for such a call while a
#     snapshot is pending; the comparison reads its modification time against the snapshot time).
#
# Reports (identifiers and paths, never file contents): the worker gets one block starting `worker-run-watch:` in
# the additionalContext of the call's PostToolUse; the orchestrator gets a note (protected_watch.queue_orchestrator_note)
# with the worker's agent id and, for a new commit in the project repository, the way back; the incident log gets
# one row (kind `worker-run-watch`, identifiers only), as protected_watch does for a restore.
#
# Switch: `worker-run-watch` in docs/ai/config.md § Checks, `warn` (default) or `off`; `block` counts as `warn`.
#
# Limits: paths under `.act-local/` and ignored files are not seen; a background process that writes after the
# call has ended is not seen; a program outside the selection (an unknown binary, `npm run`, `make`) is not
# selected; another writer in the same window makes the note say "author uncertain"; a project nested in another
# repository is compared as that repository; at most _MAX_STATUS changed paths are compared.

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

import actlib

from . import inline_code as _inline_code
from .command_parse import parse_for
from .common import _check_mode, _hook_deadline, _is_worker, _shell_command
from .shell_targets import _is_absolute_target, _to_native_path
from .worker_scope_overlap import _running_entries
from .write_scope import (
    _SAFE_ID_RE,
    _SCOPE_LINE_RE,
    _agent_assignment_text,
    _matches_scope,
    _normalize_candidate_path,
    _parse_pattern_list,
    _read_json_object,
    _resolve_worker_scope,
    _split_glob_prefix,
)

__all__ = ["check_worker_run_watch", "note_worker_run_watch"]

_DIRNAME = "worker-run-watch"
_MAIN_ACTIVITY = "main-activity"
_KEY_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")  # the dispatcher's failure-key shape (dispatch._FAILURE_ID_RE)
_GIT_BUDGET = 3.0        # seconds for all git calls of one event together
_MAX_REPOS = 3
_MAX_STATUS = 2000       # changed paths compared per repository
_MAX_REFS_STORED = 5000  # refs compared per repository
_MAX_REFS = 10           # refs named in one report
_MAX_FILES = 10          # paths named in one report
_ID_RE = re.compile(r"^[0-9a-f]{40,64}$")
_SNAPSHOT_TTL = 86400.0  # seconds a snapshot file waits for its PostToolUse
_WRITING_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "PowerShell"})
_ENV_DROP = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR", "GIT_OBJECT_DIRECTORY",
             "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE", "GIT_PREFIX")

_BARE_SCRIPT_EXTS = frozenset({".ps1", ".bat", ".cmd"})  # run by name without a path in front
_ACTIVATE_SCRIPTS = frozenset({"activate.ps1", "activate.bat"})  # a virtual environment's activation, run by path
_RUN_WRAPPERS = frozenset({"uv", "poetry", "pipenv", "pdm", "hatch", "conda"})  # `<wrapper> run <command>`
_RUN_VALUE_OPTIONS = frozenset({"-p", "--python", "--with", "--with-requirements", "--with-editable", "--with-package",
                                "--project", "--directory", "--env-file", "--group", "--only-group", "--no-group",
                                "--extra", "--package", "--index", "--cwd", "-n", "--name", "--prefix", "-C", "-e",
                                "--env"})  # options of those wrappers that take the next word as their value
_PY_LIST_RE = re.compile(r"^(?:-0\w*|--list(?:-paths)?)$")  # `py -0`, `py -0p`, `py --list`, `py --list-paths`
_SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
_PWSH = frozenset({"pwsh", "powershell"})
_PY_LAUNCHER_RE = re.compile(r"^-(?:\d[\w.-]*|V:\S*)$")  # `py -3`, `py -3.12`, `py -V:3.12`
_NODE_VALUE_OPTIONS = frozenset({"-r", "--require", "--import", "--loader", "--experimental-loader", "-C",
                                 "--conditions", "--input-type"})
_NODE_PRELOAD_OPTIONS = frozenset({"-r", "--require", "--import", "--loader", "--experimental-loader"})
_NODE_EVAL_OPTIONS =frozenset({"-e", "--eval", "-p", "--print", "-pe", "-ep"})
_NODE_NO_CODE_OPTIONS = frozenset({"-v", "--version", "-h", "--help", "-c", "--check"})
_CHILD_CALL_RE = re.compile(r"\b(?:exec|execSync|spawn|spawnSync|execFile|execFileSync|fork)\s*\(")

_REASONS = {
    "time": "the time left for git ran out",
    "git-error": "git failed",
    "no-git": "git was not found",
    "no-snapshot": "no snapshot of the state before the call was found",
    "unreadable": "the snapshot of the state before the call could not be read",
}


class _GitProblem(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# Which calls are watched
# ---------------------------------------------------------------------------

def _base_name(word: str) -> str:
    base = word.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return base[:-4] if base.endswith(".exe") else base


def _is_script_path(word: str) -> bool:
    """A first word that is a path (`./gradlew`, `.\\x.ps1`: with a `/` or a `\\`, whatever its extension), or a bare
    name with one of _BARE_SCRIPT_EXTS."""
    if "/" in word or "\\" in word:
        return True
    return os.path.splitext(word.lower())[1] in _BARE_SCRIPT_EXTS


def _python_runs_file(args: list[str]) -> bool:
    """A Python call that code_source reads as `none` (no inline code): True for a script file or a module, False
    for a query that runs nothing (`--version`, `-V`, `-h`) or a `-c` without code."""
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            index += 1
            break
        if arg == "-":
            return False
        if not arg.startswith("-"):
            return True
        if arg.startswith("--"):
            if arg in ("--version", "--help"):
                return False
            index += 2 if arg == "--check-hash-based-pycs" else 1
            continue
        if _PY_LAUNCHER_RE.match(arg):
            index += 1
            continue
        takes_next = False
        for position in range(1, len(arg)):
            char = arg[position]
            if char == "c":
                return False
            if char == "m":
                return True
            if char in "Vh?":
                return False
            if char in "WXQ":
                takes_next = position + 1 == len(arg)
                break
        index += 2 if takes_next else 1
    return index < len(args) and args[index] != "-"


def _node_runs_more(args: list[str]) -> bool:
    """`node --test` (runs the test files) and `node` with a file preloaded by `-r`/`--require`/`--import`/`--loader`:
    that file runs, also next to `-e`."""
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if arg == "--" or not arg.startswith("-"):
            return False
        if arg == "--test":
            return True
        if arg in _NODE_PRELOAD_OPTIONS:
            return index < len(args)
        if arg.partition("=")[0] in _NODE_PRELOAD_OPTIONS and "=" in arg:
            return True
        if arg in _NODE_EVAL_OPTIONS or arg in _NODE_VALUE_OPTIONS:
            index += 1
    return False


def _node_runs_file(args: list[str]) -> bool:
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            index += 1
            break
        if arg == "-":
            return False
        if not arg.startswith("-"):
            return True
        if arg.startswith(("--eval=", "--print=")) or arg in _NODE_EVAL_OPTIONS or arg in _NODE_NO_CODE_OPTIONS:
            return False
        index += 2 if arg in _NODE_VALUE_OPTIONS else 1
    return index < len(args) and args[index] != "-"


def _shell_runs_file(args: list[str]) -> bool:
    """`bash x.sh`: the first word that is no option is a file; `-c` hands over a command text, which the command
    reading follows as commands of their own; `-n` only checks the syntax and runs nothing."""
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            return index + 1 < len(args)
        if not arg or arg[0] not in "-+":
            return True
        if arg in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file"):
            index += 2
            continue
        if arg[0] == "-" and not arg.startswith("--") and ("c" in arg[1:] or "n" in arg[1:]):
            return False
        index += 1
    return False


def _pwsh_runs_file(args: list[str]) -> bool:
    for arg in args:
        lowered = arg.lower()
        if lowered in ("-file", "-f") or lowered.startswith("-file:"):
            return True
        if lowered in ("-command", "-c") or lowered.startswith("-command:"):
            return False
    return any(not arg.startswith("-") and arg.lower().endswith(".ps1") for arg in args)


def _starts_process(language: str, code: str) -> bool:
    """Inline code that starts a process: Python with a call of kind CALL_RUN, JavaScript with a call of
    `child_process` (the module named and one of its starting functions called)."""
    if language == _inline_code.PYTHON:
        program = _inline_code.read_python_program(code)
        return program is not None and any(call.kind == _inline_code.CALL_RUN for call in program.calls)
    if language == _inline_code.NODE:
        return "child_process" in code and bool(_CHILD_CALL_RE.search(code))
    return False


def _py_lists(args: list[str]) -> bool:
    """`py -0`, `py -0p`, `py --list`, `py --list-paths`: the launcher lists interpreters and runs no code (only
    the options in front of a first word that is no option are looked at)."""
    for arg in args:
        if not arg.startswith("-"):
            return False
        if _PY_LIST_RE.match(arg):
            return True
    return False


def _wrapped_kind(args: list[str], depth: int) -> Optional[str]:
    """`uv run`, `poetry run`, `pipenv run`, `pdm run`, `hatch run`, `conda run`: judged by the command they wrap.
    Any other subcommand of those tools (`uv pip install`, `poetry add`) runs no code of the worker's."""
    index = 0
    while index < len(args) and args[index].startswith("-"):
        index += 2 if args[index] in _RUN_VALUE_OPTIONS else 1
    if index >= len(args) or args[index] != "run" or depth >= 3:
        return None
    index += 1
    while index < len(args) and args[index].startswith("-") and args[index] != "-":
        if args[index] == "--":
            index += 1
            break
        index += 2 if args[index] in _RUN_VALUE_OPTIONS else 1
    if index >= len(args):
        return None
    if args[index].lower().endswith((".py", ".pyw")):
        return "script"  # `uv run x.py` runs the file with the project's Python
    return _call_kind(args[index:], depth + 1)


def _call_kind(words: list[str], depth: int = 0) -> Optional[str]:
    """How one simple command runs code: "script" (a file, a module or a script path), "inline" (inline code that
    starts a process), "stdin" (a program read from standard input, judged by the caller), else None."""
    if not words:
        return None
    if len(words) >= 3 and words[0].startswith("$") and words[1] == "=":
        words = words[2:]  # PowerShell: `$out = python x.py`
    if words[0] == "&" and len(words) > 1:
        words = words[1:]
    name = words[0]
    base = _base_name(name)
    args = words[1:]
    if base in _RUN_WRAPPERS:
        return _wrapped_kind(args, depth)
    language = _inline_code.interpreter_language(name)
    if language is not None:
        if language == _inline_code.PYTHON and base in ("py", "pyw") and _py_lists(args):
            return None  # the launcher's list of installed interpreters
        if language == _inline_code.NODE and _node_runs_more(args):
            return "script"
        kind, code = _inline_code.code_source(language, args)
        if kind == _inline_code.SOURCE_STDIN:
            return "stdin"
        if kind == _inline_code.SOURCE_CODE:
            return "inline" if _starts_process(language, code or "") else None
        runs = _python_runs_file(args) if language == _inline_code.PYTHON else _node_runs_file(args)
        return "script" if runs else None
    if base in _SHELLS:
        return "script" if _shell_runs_file(args) else None
    if base in _PWSH:
        return "script" if _pwsh_runs_file(args) else None
    if base in ("source", ".") and args:
        return None if _base_name(args[0]) == "activate" else "script"  # a virtual environment's activation
    if base in _ACTIVATE_SCRIPTS:
        return None
    return "script" if _is_script_path(name) else None


def _selected(payload: dict, tool_name: str, command: str) -> Optional[str]:
    """"script", "inline" or "stdin" for a call this check watches, else None."""
    parse = parse_for(payload, command)
    powershell = tool_name == "PowerShell"
    lists = (parse.ps_words() or parse.stripped()) if powershell else parse.stripped()
    stdin_calls = 0
    for words in lists:
        kind = _call_kind(list(words))
        if kind == "stdin":
            stdin_calls += 1
        elif kind is not None:
            return kind
    if not stdin_calls:
        return None
    if powershell:
        return "stdin"
    cwd = payload.get("cwd")
    try:
        programs, _text = parse.inline_code(cwd if isinstance(cwd, str) and cwd else None)
    except _inline_code.ReaderFailure:
        return None  # every check that reads the program refuses such a call before this one runs
    stdin_programs = [item for item in programs if item[3] == _inline_code.SOURCE_STDIN]
    if not stdin_programs:
        return "stdin"
    return "inline" if any(_starts_process(item[0], item[1]) for item in stdin_programs) else None


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------

class _Budget:
    """The git time of one event: _GIT_BUDGET seconds, at most what is left of the hook's own budget."""

    def __init__(self, payload: dict) -> None:
        self.deadline = time.monotonic() + _GIT_BUDGET
        hook = _hook_deadline(payload)
        if hook is not None:
            self.deadline = min(self.deadline, hook)

    def left(self) -> float:
        return self.deadline - time.monotonic()

    def ensure(self) -> None:
        """Raises _GitProblem("time") when the time is used up: called in the loops that touch the file system, so
        they count against the same budget as the git calls."""
        if self.left() <= 0.05:
            raise _GitProblem("time")


def _git(args: list[str], cwd: str, budget: _Budget) -> "subprocess.CompletedProcess[bytes]":
    budget.ensure()
    left = budget.left()
    env ={key: value for key, value in os.environ.items() if key not in _ENV_DROP}
    env.update({"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "LANGUAGE": "C"})
    try:
        return subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", *args], cwd=cwd, env=env,
            capture_output=True, timeout=left, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise _GitProblem("time") from None
    except FileNotFoundError:
        raise _GitProblem("no-git") from None
    except (OSError, subprocess.SubprocessError):
        raise _GitProblem("git-error") from None


def _text(done: "subprocess.CompletedProcess[bytes]") -> str:
    return done.stdout.decode("utf-8", errors="replace").strip()


def _toplevel(folder: str, budget: _Budget) -> Optional[str]:
    """The git top-level of `folder`, None for a folder that is no repository."""
    done = _git(["rev-parse", "--show-toplevel"], folder, budget)
    if done.returncode != 0:
        if b"not a git repository" in done.stderr.lower():
            return None
        raise _GitProblem("git-error")
    return _text(done) or None


def _state(top: str, budget: _Budget) -> dict:
    """The state compared: head, the branch HEAD names, refs (None when there are too many) and the status list
    with size and modification time per path (None when there are too many)."""
    symbolic = _git(["symbolic-ref", "-q", "HEAD"], top, budget)
    head_ref = _text(symbolic) if symbolic.returncode == 0 else ""
    revision = _git(["rev-parse", "-q", "--verify", "HEAD"], top, budget)
    if revision.returncode not in (0, 1):
        raise _GitProblem("git-error")
    head = _text(revision) if revision.returncode == 0 else ""
    listed = _git(["for-each-ref", "--format=%(refname) %(objectname)"], top, budget)
    if listed.returncode != 0:
        raise _GitProblem("git-error")
    refs: Optional[dict] = {}
    lines = [line for line in listed.stdout.decode("utf-8", errors="replace").splitlines() if line.strip()]
    if len(lines) > _MAX_REFS_STORED:
        refs = None
    else:
        for line in lines:
            name, _space, identifier = line.rpartition(" ")
            refs[name] = identifier
    status = _git(["status", "--porcelain=v1", "-z", "-uall", "--no-renames"], top, budget)
    if status.returncode != 0:
        raise _GitProblem("git-error")
    entries = [item for item in status.stdout.split(b"\0") if item]
    files: Optional[dict] = {}
    if len(entries) > _MAX_STATUS:
        files = None
    else:
        for item in entries:
            budget.ensure()
            text = item.decode("utf-8", errors="replace")
            code, relative = text[:2], text[3:]
            try:
                info = os.lstat(os.path.join(top, relative))
                size, modified = info.st_size, info.st_mtime_ns
            except OSError:
                size, modified = None, None  # a deleted path
            files[relative] = [code, size, modified]
    return {"head": head, "head_ref": head_ref, "refs": refs, "files": files}


def _existing_dir(prefix: str) -> Optional[str]:
    """The nearest existing folder at or above the literal part of an outside pattern (at most 4 steps up)."""
    if not prefix:
        return None
    try:
        path = Path(_to_native_path(prefix))
        for _step in range(5):
            if path.is_dir():
                return str(path)
            if path.parent == path:
                return None
            path = path.parent
    except (OSError, ValueError):
        return None
    return None


def _external_form(root: Path, pattern: str) -> str:
    """A relative pattern that leaves the project (`../other/src/**`) as the absolute POSIX path it stands for
    (resolved from the project root, the glob remainder kept), the form write_scope keeps for a pattern inside an
    additional directory and _matches_scope compares an outside path with. Any other pattern comes back unchanged."""
    if not pattern.startswith("..") or (len(pattern) > 2 and pattern[2] not in "/\\"):
        return pattern
    prefix, remainder = _split_glob_prefix(pattern.replace("\\", "/"))
    if not prefix:
        return pattern
    try:
        resolved = str((root / prefix).resolve()).replace("\\", "/")
    except (OSError, ValueError):
        return pattern
    return f"{resolved}/{remainder}" if remainder else resolved


def _own_scope(root: Path, payload: dict) -> Optional[dict]:
    """The calling worker's recorded scope. A scope write_scope recorded as an error (a pattern that leaves the
    project and lies in no additional directory: every write of that worker is refused, but its scripts run) has
    lost its patterns, so they are read again from the worker's own assignment text."""
    try:
        scope = _resolve_worker_scope(root, payload)
    except Exception:  # noqa: BLE001 -- an unreadable scope leaves the project repository alone
        return None
    if not scope or scope.get("mode") != "error":
        return scope
    try:
        text = _agent_assignment_text(payload.get("transcript_path"), str(payload.get("agent_id")))
        match = _SCOPE_LINE_RE.search(text) if text else None
        raw = _parse_pattern_list(match.group(1), None) if match else None
    except Exception:  # noqa: BLE001
        raw = None
    return raw or scope  # no assignment text: the project repository only, every changed path counts as outside


def _scope_patterns(root: Path, scope: Optional[dict]) -> list[str]:
    """The patterns of a recorded scope in the form _matches_scope compares (_external_form)."""
    if not scope or scope.get("mode") != "patterns":
        return []
    return [_external_form(root, item) for item in scope.get("patterns") or [] if isinstance(item, str)]


def _repo_folders(root: Path, payload: dict) -> list[str]:
    """The project root, then the literal base folder of every `Write scope:` pattern of the calling worker that
    lies outside the project (an absolute pattern, or a relative one that leaves the project, _external_form)."""
    folders = [str(root)]
    for pattern in _scope_patterns(root, _own_scope(root, payload)):
        if _is_absolute_target(pattern):
            folder = _existing_dir(_split_glob_prefix(pattern)[0])
            if folder and folder not in folders:
                folders.append(folder)
    return folders


def _snapshot(root: Path, payload: dict, budget: _Budget) -> list[dict]:
    repos: list[dict] = []
    seen: set[str] = set()
    for index, folder in enumerate(_repo_folders(root, payload)):
        if len(repos) >= _MAX_REPOS:
            break
        try:
            top = _toplevel(folder, budget)
            if top is None:
                continue
            marker = os.path.normcase(os.path.realpath(top))
            if marker in seen:
                continue
            seen.add(marker)
            repos.append(dict(_state(top, budget), top=top, project=index == 0))
        except _GitProblem as problem:
            repos.append({"top": folder, "project": index == 0, "problem": problem.reason})
    return repos


# ---------------------------------------------------------------------------
# Snapshot files
# ---------------------------------------------------------------------------

def _folder(root: Path) -> Path:
    return root / ".act-local" / _DIRNAME


def _key(payload: dict) -> Optional[str]:
    """The dispatcher's failure key (dispatch._failure_key): the tool use id, else `<session>__<agent>`."""
    tool_use_id = payload.get("tool_use_id")
    if isinstance(tool_use_id, str) and _KEY_RE.match(tool_use_id):
        return tool_use_id
    session = payload.get("session_id")
    if isinstance(session, str) and _KEY_RE.match(session):
        agent = payload.get("agent_id")
        return f"{session}__{agent if isinstance(agent, str) and _KEY_RE.match(agent) else 'main'}"
    return None


def _remove(root: Path, folder: Path, name: str) -> None:
    """Deletes one file of the snapshot folder, and only that: `folder` is the one fixed from the project root when the
    check started, `name` a plain file name in it, and the path must pass the guard every write under `.act-local/`
    passes (`actlib.local_write_ok`: no link or junction on the way, nothing that resolves out of the project), as in
    worker_scope_overlap._remove_worker_scope. Anything else is left where it is; the 24 h pruning is the last resort."""
    if not name or name in (".", "..") or "/" in name or "\\" in name or os.sep in name:
        return
    path = folder / name
    if path.parent != folder or not actlib.local_write_ok(root, path):
        return
    try:
        path.unlink()
    except OSError:
        pass


def _prune(root: Path, folder: Path) -> None:
    if not actlib.local_write_ok(root, folder):
        return
    try:
        names = os.listdir(folder)
    except OSError:
        return
    limit = time.time() - _SNAPSHOT_TTL
    for name in names:
        if name == _MAIN_ACTIVITY or not name.endswith((".json", ".tmp", ".seen")):
            continue
        try:
            if os.lstat(folder / name).st_mtime < limit:
                _remove(root, folder, name)
        except OSError:
            pass


def _write_atomic(root: Path, path: Path, text: str) -> bool:
    """Writes `text` to `path` in the snapshot folder through a temporary file; False when nothing could be written
    (a link on the way, a full disk)."""
    if not actlib.local_write_ok(root, path):
        return False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix=".tmp-", suffix=".tmp", dir=str(path.parent))
    except OSError:
        return False
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        actlib.replace_file(temporary, path)
    except OSError:
        _remove(root, path.parent, os.path.basename(temporary))
        return False
    return True


def _store(root: Path, key: str, data: dict) -> bool:
    return _write_atomic(root, _folder(root) / f"{key}.json", json.dumps(data))


def _first_time(root: Path, payload: dict, top: str, part: str) -> bool:
    """True the first time a repository's `part` ("refs" or "files") was too big to compare in this session, False
    after that: the note and the incident row come once per session and repository, not on every call. A call with
    no usable session id always says it."""
    session = payload.get("session_id")
    if not isinstance(session, str) or not _KEY_RE.match(session):
        return True
    path = _folder(root) / f"too-many-{session}.seen"
    entry = f"{hashlib.sha1(os.path.normcase(os.path.realpath(top)).encode('utf-8', 'replace')).hexdigest()[:16]} {part}"
    try:
        known = path.read_text(encoding="utf-8").split("\n") if path.is_file() else []
    except OSError:
        known = []
    if entry in known:
        return False
    _write_atomic(root, path, "\n".join([*known[-50:], entry]))
    return True


def _pending(folder: Path) -> bool:
    try:
        return any(name.endswith(".json") for name in os.listdir(folder))
    except OSError:
        return False


# ---------------------------------------------------------------------------
# PreToolUse
# ---------------------------------------------------------------------------

def check_worker_run_watch(payload: dict) -> int:
    """PreToolUse: for a worker's call that runs code the other checks cannot see through, take the snapshot the
    PostToolUse note compares. Always allows (returns 0)."""
    if not _is_worker(payload):
        return 0
    shell = _shell_command(payload)
    if shell is None:
        return 0
    tool_name, command = shell
    if _check_mode(actlib.read_config(), "worker-run-watch", default="warn") == "off":
        return 0
    via = _selected(payload, tool_name, command)
    key = _key(payload)
    if via is None or key is None:
        return 0
    root = actlib.repo_root()
    _prune(root, _folder(root))
    budget = _Budget(payload)
    snapshot = {"v": 1, "t_ns": time.time_ns(), "via": via, "repos": _snapshot(root, payload, budget),
                "others": _other_workers(root, payload) > 0}
    _store(root, key, snapshot)  # a snapshot that cannot be written is reported by the PostToolUse note
    return 0


# ---------------------------------------------------------------------------
# PostToolUse
# ---------------------------------------------------------------------------

def _caller_tool_use_id(payload: dict) -> Optional[str]:
    transcript, agent = payload.get("transcript_path"), payload.get("agent_id")
    if not isinstance(transcript, str) or not transcript or not isinstance(agent, str) or not _SAFE_ID_RE.match(agent):
        return None
    meta = _read_json_object(Path(transcript).with_suffix("") / "subagents" / f"agent-{agent}.meta.json")
    value = meta.get("toolUseId") if meta else None
    return value if isinstance(value, str) and value else None


def _other_workers(root: Path, payload: dict) -> int:
    """How many workers run besides the caller (the registry of worker_scope_overlap)."""
    running = _running_entries(root)
    caller = _caller_tool_use_id(payload)
    if caller is not None:
        return len([item for item in running if item[0] != caller])
    return max(len(running) - 1, 0)


def _scope_cover(root: Path, payload: dict):
    """A function that says whether a normalized path lies inside the Write scope of a running worker, the caller
    included."""
    scopes = [entry for _tool_use_id, entry in _running_entries(root)]
    own = _own_scope(root, payload)
    if own:
        scopes.append(own)
    patterns: list[str] = []
    unrestricted = False
    for scope in scopes:
        if scope.get("mode") == "unrestricted":
            unrestricted = True
        elif scope.get("mode") == "patterns":
            patterns.extend(_scope_patterns(root, scope))

    def covered(normalized: str) -> bool:
        if _is_absolute_target(normalized):
            return _matches_scope(normalized, patterns)
        return unrestricted or _matches_scope(normalized, patterns)

    return covered


def _short(identifier: str) -> str:
    return identifier[:7] if identifier else "none"


def _clean(text: str) -> str:
    return "".join(char if char.isprintable() else "?" for char in text)[:200]


def _target(ref: str, head: str) -> str:
    """What HEAD stands for: the branch it names, else "detached" (an id), else "none" (nothing yet)."""
    return _clean(ref) if ref else ("detached" if head else "none")


def _descends(top: str, old: str, new: str, budget: _Budget) -> bool:
    """True when `new` is a commit on top of `old` (`git merge-base --is-ancestor`, fixed arguments, ids checked): a
    first commit (nothing before) counts. False for anything else, a deleted branch and a history rewritten."""
    if not old:
        return bool(new)
    if not (_ID_RE.match(old) and _ID_RE.match(new)):
        return False
    return _git(["merge-base", "--is-ancestor", old, new], top, budget).returncode == 0


def _compare(root: Path, payload: dict, snapshot: dict, budget: _Budget) -> dict:
    """What changed since the snapshot: {"commits": [...], "refs": [...], "files": [...], "problems": [...]}."""
    found: dict = {"commits": [], "refs": [], "files": [], "problems": [], "skipped": []}
    covered = None
    for repo in snapshot.get("repos") or []:
        label = "the project repository" if repo.get("project") else _clean(str(repo.get("top", "?")))
        if repo.get("problem"):
            found["problems"].append((label, str(repo["problem"])))
            continue
        try:
            after = _state(repo["top"], budget)
        except _GitProblem as problem:
            found["problems"].append((label, problem.reason))
            continue
        old_head, new_head = repo["head"], after["head"]
        old_ref, new_ref = repo["head_ref"], after["head_ref"]
        new_commit = False
        if old_ref != new_ref:
            # HEAD points elsewhere (branch switch, detach): its own line; a branch it moved to is listed below
            found["refs"].append((label, "HEAD", _target(old_ref, old_head), _target(new_ref, new_head),
                                  f", commit {_short(old_head)} -> {_short(new_head)}"))
        elif old_head != new_head:
            try:
                new_commit = _descends(repo["top"], old_head, new_head, budget)
            except _GitProblem as problem:
                found["problems"].append((label, problem.reason))
            if new_commit:
                found["commits"].append((label, old_head, new_head, new_ref, bool(repo.get("project"))))
            elif not new_ref:
                found["refs"].append((label, "HEAD (detached)", _short(old_head), _short(new_head), ""))
        if repo["refs"] is None or after["refs"] is None:
            if _first_time(root, payload, repo["top"], "refs"):
                found["skipped"].append((label, "refs"))
        else:
            for name in sorted(set(repo["refs"]) | set(after["refs"])):
                old, new = repo["refs"].get(name, ""), after["refs"].get(name, "")
                if old == new or (new_commit and name == new_ref and new == new_head):
                    continue
                found["refs"].append((label, _clean(name), _short(old), _short(new), ""))
        if repo["files"] is None or after["files"] is None:
            if _first_time(root, payload, repo["top"], "files"):
                found["skipped"].append((label, "files"))
            continue
        changed = [name for name in sorted(set(repo["files"]) | set(after["files"]))
                   if repo["files"].get(name) != after["files"].get(name)]
        if changed and covered is None:
            covered = _scope_cover(root, payload)
        for name in changed:
            try:
                budget.ensure()  # resolving the paths counts against the same time as the git calls
            except _GitProblem as problem:
                found["problems"].append((label, problem.reason))
                break
            normalized = _normalize_candidate_path(os.path.join(repo["top"], name).replace("\\", "/"), root, str(root))
            if normalized is None or normalized == ".act-local" or normalized.startswith(".act-local/"):
                continue
            if not covered(normalized):
                found["files"].append(_clean(normalized))
    return found


def _uncertain(root: Path, payload: dict, snapshot: dict) -> bool:
    if snapshot.get("others") or _other_workers(root, payload) > 0:
        return True
    try:
        touched = (_folder(root) / _MAIN_ACTIVITY).stat().st_mtime_ns
    except OSError:
        return False
    return touched >= int(snapshot.get("t_ns") or 0)


def _lines(found: dict) -> list[str]:
    lines: list[str] = []
    for label, old, new, branch, _project in found["commits"]:
        lines.append(f"- new commit in {label}: {_short(old)} -> {_short(new)}" + (f" ({_clean(branch)})" if branch else ""))
    for label, name, old, new, extra in found["refs"][:_MAX_REFS]:
        lines.append(f"- ref changed in {label}: {_clean(name)} ({old} -> {new}){extra}")
    if len(found["refs"]) > _MAX_REFS:
        lines.append(f"- and {len(found['refs']) - _MAX_REFS} more refs")
    files = found["files"]
    if files:
        lines.append(f"- outside every running worker's Write scope ({len(files)}): " + ", ".join(files[:_MAX_FILES])
                     + (f" and {len(files) - _MAX_FILES} more" if len(files) > _MAX_FILES else ""))
    for label, part in found["skipped"]:
        lines.append(f"- too many changes to compare in {label}: the {part} were not compared")
    for label, reason in found["problems"]:
        lines.append(f"- comparison not possible for {label}: {_REASONS.get(reason, reason)}")
    return lines


def _incident_rows(found: dict, uncertain: bool) -> list[str]:
    parts = []
    if found["commits"]:
        parts.append(f"commit x{len(found['commits'])}")
    if found["refs"]:
        parts.append(f"ref x{len(found['refs'])}")
    if found["files"]:
        parts.append(f"outside-scope x{len(found['files'])}")
    rows = [" ".join(parts + (["uncertain"] if uncertain else []))] if parts else []
    reasons = sorted({reason for _label, reason in found["problems"]} | ({"too-many-changes"} if found["skipped"] else set()))
    rows += [f"unchecked {reason}" for reason in reasons]
    return rows


def _report(root: Path, payload: dict, found: dict, uncertain: bool) -> Optional[str]:
    lines = _lines(found)
    if not lines:
        return None
    changed = bool(found["commits"] or found["refs"] or found["files"])
    tail = ["- author uncertain: another worker ran, or the main session wrote, while this call ran; the changes above may "
            "not be yours"] if uncertain and changed else []
    agent = payload.get("agent_id") if isinstance(payload.get("agent_id"), str) else "?"
    tool = payload.get("tool_name") if isinstance(payload.get("tool_name"), str) else "a tool"
    way_back = [f"The way back for the commit in the project repository: check what it holds (`git show {_short(new)}`), "
                f"then `git reset --soft {_short(old)}`." for _label, old, new, _branch, project in found["commits"]
                if project and old and new]
    if found["refs"]:
        way_back.append("No command to go back is offered for a ref change: the lines above name the old targets and ids; "
                        "look at them and at `git reflog` before moving anything.")
    note = ("[act] worker-run-watch: worker " + _clean(agent) + f" ran code with {tool} and the state changed meanwhile:\n"
            + "\n".join(lines + tail + way_back))
    queued = True
    try:
        from . import protected_watch
        protected_watch.queue_orchestrator_note(str(root).replace("\\", "/"), note)
    except Exception:  # noqa: BLE001 -- the report to the worker still goes out
        queued = False
    try:
        import incidents
        for row in _incident_rows(found, uncertain):
            incidents.record(root, "worker-run-watch", "worker_run_watch", row, "worker")
    except Exception:  # noqa: BLE001 -- the log never changes what the check says
        pass
    advice = ["Do not undo a commit or ref change yourself (R-role-worker): name it, and the files, in your result; the "
              "orchestrator decides. Files outside your Write scope are named there too."] if changed else []
    if not queued:
        advice.append("The orchestrator could not be notified from here: say so in your result.")
    return "[act] worker-run-watch: after your call that ran code the checks cannot read, compared with before it:\n" \
        + "\n".join(lines + tail + advice)


def _touch_main_activity(payload: dict) -> None:
    if payload.get("tool_name") not in _WRITING_TOOLS:
        return
    try:
        root = actlib.repo_root()
    except RuntimeError:
        return
    folder = _folder(root)
    if not _pending(folder):
        return
    path = folder / _MAIN_ACTIVITY
    if not actlib.local_write_ok(root, path):
        return
    try:
        os.utime(path, None)
    except FileNotFoundError:
        try:
            path.write_bytes(b"")
        except OSError:
            pass
    except OSError:
        pass


def note_worker_run_watch(payload: dict) -> Optional[str]:
    """PostToolUse and PostToolUseFailure: for a main-session call of a writing tool, mark the time (while a
    snapshot is pending); for a worker's shell call, compare the snapshot with the state now and report."""
    if not _is_worker(payload):
        _touch_main_activity(payload)
        return None
    shell = _shell_command(payload)
    if shell is None:
        return None
    tool_name, command = shell
    try:
        root = actlib.repo_root()
    except RuntimeError:
        return None
    key = _key(payload)
    folder = _folder(root)  # fixed here: the only place this call deletes in
    path = folder / f"{key}.json" if key else None
    snapshot: Optional[dict] = None
    unreadable = False
    if path is not None and path.is_file():
        snapshot = _read_json_object(path)
        unreadable = snapshot is None
        _remove(root, folder, path.name)
    if _check_mode(actlib.read_config(), "worker-run-watch", default="warn") == "off":
        return None
    found: dict
    uncertain = False
    if snapshot is None:
        if not unreadable and _selected(payload, tool_name, command) is None:
            return None  # an ordinary call: nothing was to be snapshotted
        reason = "unreadable" if unreadable else "no-snapshot"
        found = {"commits": [], "refs": [], "files": [], "problems": [("this call", reason)], "skipped": []}
    else:
        found = _compare(root, payload, snapshot, _Budget(payload))
        uncertain = _uncertain(root, payload, snapshot)
    return _report(root, payload, found, uncertain)
