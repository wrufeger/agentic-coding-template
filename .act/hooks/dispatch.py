#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Single entry point for every hook event this template wires into the assistant's
#          harness (currently PreToolUse, PostToolUse and SessionStart). One script per event would
#          scatter the same "read stdin, load actlib, check config" boilerplate across files;
#          dispatch.py does that once and hands off to one handler per event. The checks/notes
#          themselves live one module per check under .act/hooks/checks/ (see checks/__init__.py);
#          dispatch.py stays the thin entry point that reads the payload and runs them in a fixed
#          order.
#
#          PreToolUse runs the checks in _PRE_TOOL_USE_CHECKS, in that order, first denial wins:
#          the template write-guard (checks.write_guard.check_write_guard), the no-sub-sub-agents
#          guard (checks.nesting_guard.check_worker_nesting_guard, R-role-worker), and the
#          per-worker write-scope guard (checks.write_scope.check_worker_write_scope,
#          R-cost-delegate) — a worker may only write where its assignment's `Write scope:` line
#          allows.
#
#          To add a new PreToolUse check: write checks/<name>.py exporting a function
#          check_<name>(payload: dict) -> int (0 = allow, 2 = deny — print the reason to stderr
#          before returning 2, same as every existing check) and add ("<name>", "check_<name>")
#          to _PRE_TOOL_USE_CHECKS at the position it should run in. A listed module that does
#          not exist yet is skipped. Observers (event log, usage counter) work the same way via
#          _OBSERVERS, with observe(event, payload) -> None; they see every event and never block.
#
#          PostToolUse runs every entry in _POST_TOOL_USE_NOTES — signature
#          note_<name>(payload: dict) -> str | None — collecting whatever text each one returns
#          (None means "nothing to say", the common case) and, only if at least one note came back,
#          printing a single hookSpecificOutput JSON object on stdout (see "Output format" below).
#          Unlike PreToolUse's checks, notes never block: a missing module is skipped silently (not
#          built yet, same convention as _PRE_TOOL_USE_CHECKS), and an exception while loading or
#          calling one is caught, logged as one line on stderr, and skipped — the remaining notes
#          still run, and the JSON on stdout, if any, stays well-formed either way. This is the
#          channel a check reaches for when it needs the assistant to actually see a hint: unlike a
#          PreToolUse check's plain-text stdout (transcript-only, never fed back to the model — see
#          checks/encoding_hint.py's and checks/worker_cap.py's own header comments for the
#          research behind that), PostToolUse's hookSpecificOutput.additionalContext is documented
#          to reach the model. A check that also needs to *deny* a call still does that from
#          PreToolUse (exit 2 + stderr, the only channel confirmed to reach the model for that
#          event) — PostToolUse's notes are for the non-blocking half of the same checks only.
#
#          The PreToolUse hook fires for every tool (settings.hooks.json: the Edit/Write/Bash
#          entry, the Agent|Task entry and a third entry for all other tool names, e.g.
#          PowerShell, Read, MCP tools) — each check filters the tool names it cares about.
#          PostToolUse fires for every tool too, via a single unrestricted matcher (no need to
#          split it the way PreToolUse's matcher is split — that split exists so future PreToolUse
#          checks *could* be wired per tool-name group; every PostToolUse note today applies
#          uniformly regardless of tool, so one entry suffices without risking a double call).
#
#          SessionStart is a single combined handler (checks.session.refresh_session) rather than
#          a list — its sub-steps (inbox count, bridge refresh, template-awareness notes,
#          orchestrator-rules delivery, ...) are each their own best-effort note or side effect
#          gated by their own docs/ai/config.md row, not independent pass/fail gates, so a list
#          with "first denial wins" semantics does not fit it the way it fits PreToolUse.
#
# Usage:
#   python .act/hooks/dispatch.py <event>
#   ... with the hook's JSON payload piped in on stdin (may be empty or malformed; handled).
#
#   <event> is the hook event name. "PreToolUse" runs the checks, "PostToolUse" runs the notes,
#   "SessionStart" the session handler; every event (these three and e.g. SubagentStart,
#   SubagentStop, UserPromptSubmit, PostToolUseFailure, Notification, SessionEnd) first goes to
#   the observers. Anything else exits 0 — an unknown event must never break the caller's hook
#   chain.
#
# Output format:
#   PreToolUse:   exit 0 (allow) or exit 2 with a one-line reason on stderr (deny) — the
#                 harness convention for "block this tool call and show the assistant why".
#   PostToolUse:  exit 0 always (notes never block); if at least one note module returned text,
#                 one line on stdout: {"hookSpecificOutput": {"hookEventName": "PostToolUse",
#                 "additionalContext": "<note>\n<note>..."}} — multiple notes joined with "\n".
#                 Nothing printed at all when no note module had anything to say.
#   SessionStart: one or more lines on stdout — an optional block of orchestrator-only rules
#                 (main session only, never seen by a sub-agent), zero or more "[act] note: ..."
#                 lines (a changed/unrefreshable bridge, an unresolvable tier/reasoning value, a
#                 project .act/ pulled in without update.py — each best-effort and independently
#                 gated, see checks.session.refresh_session()), then the fixed-format status line
#                 "[act] branch=<name> [· inbox: <n> waiting] · board updated [· rules: <n>]
#                 [· role-bridges refreshed: <n>]", and finally, as a deliberate postscript after
#                 that status line, an optional "a template update is available" note — always a
#                 *previous* SessionStart's finding, consumed from .act-local/update-check-
#                 result.json, never something looked up during this run (see
#                 checks.session._spawn_update_check_worker: the actual `git ls-remote` runs
#                 detached, in the background, so it can never delay this session — a SessionStart
#                 hook has a fixed timeout, and an unreachable template source measured at 21s
#                 against a 5s subprocess timeout before this fix, see that function's docstring).
#                 Also re-derives the model/effort frontmatter of every existing
#                 .claude/agents/*.md role bridge (tiers.py), leaving the rest of each file
#                 untouched; exit 0 always — a session start must never fail the session over a
#                 mechanism error.
#
#   "_update-check-worker" <root>: internal only, never a real harness hook event — this is what
#                 checks.session._spawn_update_check_worker() launches as a detached background
#                 process (see main() below). Not documented to the harness, not something a hook
#                 config ever names.
#
# Exit-code contract for PreToolUse specifically: a mechanism error while checking a candidate
# write is NOT swallowed the way a SessionStart error is. Every other check in this template
# fails open (never blocks the session on its own bug); the write-guard is the one exception —
# "im Zweifel ablehnen" (when in doubt, deny) — because a false allow here means the template
# silently loses its own files to an edit the next update overwrites anyway.
#
# Backward compatibility: every name that used to live directly in this module (before the
# checks/ split, 2026-09-23) is still reachable as dispatch.<name> — each checks/ submodule
# declares its public surface in its own __all__, and this file re-imports all of it with a
# wildcard import per submodule below. A probe that does `import dispatch; dispatch._foo(...)`
# keeps working unchanged; so does one that monkeypatches a name a check reads through another
# module's own attribute lookup at call time (e.g. checks.session._manifest_fingerprint reads
# manifest.manifest_fingerprint via getattr() on the shared `manifest` module on every call, not
# a copied reference — patching `manifest.manifest_fingerprint` from outside still takes effect
# no matter which file defines the function that reads it).

from __future__ import annotations

import importlib
import json
import sys

from pathlib import Path  # noqa: E402

# Must run before importing anything under .act/ (actlib/manifest/tiers, the checks package):
# compiled caches go to the system temp directory instead of __pycache__/ folders under the
# template tree. Keeping them (rather than sys.dont_write_bytecode) saves ~35 ms per hook call,
# which runs twice for every tool call. Not under .act-local/: pycache_prefix mirrors the full
# source path below the prefix, which inside the project doubles the path length and breaks
# Windows' 260-character limit (and `git clean`) in deep checkouts. Writing a cache is best
# effort in Python — a failure there never fails the hook.
import tempfile  # noqa: E402
sys.pycache_prefix = str(Path(tempfile.gettempdir()) / "act-pycache")

# PostToolUse fires after every tool call, but only a worker's calls (cap note) and the writing
# tools (encoding note, secret-scan note after a commit) can produce a note. Everything else
# returns here, before the imports below — the common case costs one small JSON parse.
_POST_TOOL_USE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "PowerShell"}
_early_payload = None
if len(sys.argv) == 2 and sys.argv[1] == "PostToolUse":
    try:
        _raw = sys.stdin.read()
        _early_payload = json.loads(_raw) if _raw.strip() else {}
    except (OSError, ValueError):
        _early_payload = {}
    if not isinstance(_early_payload, dict):
        _early_payload = {}
    if not _early_payload.get("agent_id") and _early_payload.get("tool_name") not in _POST_TOOL_USE_TOOLS:
        sys.exit(0)

# Force UTF-8 on stdout/stderr: on Windows, Python otherwise picks the console's legacy code
# page (e.g. cp1252), which silently mangles the em dash in checks.write_guard's message into a
# different byte than the UTF-8 the harness expects. reconfigure() is Python 3.7+; the
# try/except keeps this a no-op on a stream that does not support it instead of crashing.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
# Keep .act/hooks/ ahead of .act/scripts/ so a future scripts/checks.py can never shadow the
# checks package.
_HOOKS_DIR = str(Path(__file__).resolve().parent)
if _HOOKS_DIR in sys.path:
    sys.path.remove(_HOOKS_DIR)
sys.path.insert(0, _HOOKS_DIR)
import actlib  # noqa: E402 (sys.path setup above must run first)
import manifest  # noqa: E402
import tiers  # noqa: E402

# checks/ lives next to this file (.act/hooks/checks/); Python already put this file's own
# directory (.act/hooks/) on sys.path[0] when it started, so the package is importable as-is.
# common and session are needed by main() itself; a failure there is a template bug that must
# surface, not be hidden. The other re-imports only keep `dispatch.<name>` reachable for probes —
# a broken check module must not crash the dispatcher here; the registry below decides what a
# broken check means (see _FAIL_CLOSED).
from checks.common import *  # noqa: E402,F401,F403
from checks.session import *  # noqa: E402,F401,F403
for _compat_module in ("nesting_guard", "shell_targets", "write_guard", "write_scope"):
    try:
        _mod = importlib.import_module(f"checks.{_compat_module}")
    except Exception:  # noqa: BLE001 — handled again, with a verdict, in _resolve()
        continue
    globals().update({name: getattr(_mod, name) for name in getattr(_mod, "__all__", ())})
del _compat_module


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

# PreToolUse checks, in the order they run — first non-zero return wins and is this call's own
# exit code. See the header comment above for how to add one. Each entry is (module under checks/,
# function name); a module that does not exist yet is skipped, so a check can be registered here
# before it is built (stage 5 builds several in parallel, one module each).
_PRE_TOOL_USE_CHECKS = (
    ("write_guard", "check_write_guard"),                 # check 1  — .act/ template write-guard
    ("nesting_guard", "check_worker_nesting_guard"),      # check 1b — no sub-sub-agents (R-role-worker)
    ("write_scope", "check_worker_write_scope"),          # check 1c — per-worker write scope (R-cost-delegate)
    ("worker_docs_ai", "check_worker_docs_ai"),           # worker writes under docs/ai/ (R-role-worker)
    ("worker_git_write", "check_worker_git_write"),       # worker runs a mutating git command (R-role-worker)
    ("commit_pathspec", "check_commit_pathspec"),         # git add -A / . / commit -a (R-code-commit)
    ("recursive_delete", "check_recursive_delete"),       # rm -r and friends (R-safe-no-shell-delete)
    ("secret_scan", "check_secret_scan"),                 # secrets in the diff before commit (R-safe-no-secret-diff)
    ("worker_cap", "check_worker_cap"),                   # tool calls beyond the worker's cap (R-cost-delegate)
    ("status_poll", "check_status_poll"),                 # repeated status queries (R-cost-wait)
    ("encoding_hint", "check_encoding_hint"),             # non-UTF-8 target, note only (R-code-encoding)
)

# PostToolUse notes, all of them run every time (no "first wins" — unlike _PRE_TOOL_USE_CHECKS,
# these never block, so there is nothing to short-circuit). Each entry is (module under checks/,
# function name); signature note_<name>(payload: dict) -> str | None. Same skip-if-missing rule as
# _PRE_TOOL_USE_CHECKS. See the header comment above for the full contract.
_POST_TOOL_USE_NOTES = (
    ("worker_cap", "note_worker_cap"),        # cap-reached / cap-exceeded hints (R-cost-delegate)
    ("encoding_hint", "note_encoding_hint"),  # `warn` mode's one-time non-UTF-8 note (R-code-encoding)
    ("secret_scan", "note_secret_scan"),      # `warn` mode / incomplete scan after a commit (R-safe-no-secret-diff)
)

# Observers see every hook event before any check runs and never block: signature
# observe(event: str, payload: dict) -> None; an exception inside one is swallowed. Used for
# the event log (topic "logging") and the usage counter. Same skip-if-missing rule as above.
_OBSERVERS = (
    ("event_log", "observe"),
    ("usage", "observe"),
    ("status_poll", "observe"),  # resets the poll streak on UserPromptSubmit (R-cost-wait)
    ("tips", "observe"),         # minute/hour reminders on UserPromptSubmit — the one observer
                                 # that prints, and only for that event: UserPromptSubmit runs
                                 # async (.act/bridges/settings.hooks.json), so plain stdout is
                                 # lost — only a hookSpecificOutput.additionalContext JSON object
                                 # on stdout reaches the model (checks/tips.py's observe() prints
                                 # exactly that, never bare text)
)


# Checks whose failure (import error, missing function, exception while running) refuses the
# call instead of letting it through: exit code 1 would count as "not blocking" for the harness,
# so a broken guard would silently open the door it is meant to keep shut. Every other check
# fails open with one line on stderr — a broken convenience check must not stop all work.
_FAIL_CLOSED = {"write_guard", "nesting_guard", "write_scope"}
# Only tools that can write or start a worker are refused by a broken guard — reading stays
# possible, so the assistant can still look into what broke.
_FAIL_CLOSED_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "PowerShell", "Agent", "Task"}


def _load(module_name: str, func_name: str):
    """(func, None) when the check is available, (None, None) when its module does not exist yet,
    (None, reason) when it exists but cannot be used."""
    try:
        module = importlib.import_module(f"checks.{module_name}")
    except ModuleNotFoundError as exc:
        if exc.name == f"checks.{module_name}":
            return None, None  # not built yet
        return None, f"import failed: {exc}"
    except Exception as exc:  # noqa: BLE001
        return None, f"import failed: {type(exc).__name__}: {exc}"
    func = getattr(module, func_name, None)
    if not callable(func):
        return None, f"function {func_name} missing"
    return func, None


def _check_failed(module_name: str, reason: str, payload: dict) -> int:
    if module_name in _FAIL_CLOSED and payload.get("tool_name") in _FAIL_CLOSED_TOOLS:
        print(f"[act] check {module_name} failed ({reason}) — refusing to be safe; "
              "run .act/scripts/doctor.py", file=sys.stderr)
        return 2
    print(f"[act] check {module_name} skipped ({reason})", file=sys.stderr)
    return 0


def _run_checks(payload: dict) -> int:
    for module_name, func_name in _PRE_TOOL_USE_CHECKS:
        func, reason = _load(module_name, func_name)
        if func is None:
            if reason is None:
                continue
            result = _check_failed(module_name, reason, payload)
        else:
            try:
                result = func(payload)
            except Exception as exc:  # noqa: BLE001
                result = _check_failed(module_name, f"{type(exc).__name__}: {exc}", payload)
        if result != 0:
            return result
    return 0


def _run_observers(event: str, payload: dict) -> None:
    for module_name, func_name in _OBSERVERS:
        func, _reason = _load(module_name, func_name)
        if func is None:
            continue
        try:
            func(event, payload)
        except Exception:  # noqa: BLE001 — an observer must never break the hook chain
            pass


def _run_post_tool_use_notes(payload: dict) -> list[str]:
    """Every note module's text, in _POST_TOOL_USE_NOTES order, skipping None. A module that does
    not exist yet is skipped silently (same as a not-yet-built PreToolUse check); one that exists
    but fails to load, or raises while called, is skipped too but logged as one stderr line — never
    blocks, never corrupts the stdout JSON main() builds from the list this returns."""
    notes: list[str] = []
    for module_name, func_name in _POST_TOOL_USE_NOTES:
        func, reason = _load(module_name, func_name)
        if func is None:
            if reason is not None:
                print(f"[act] note {module_name} skipped ({reason})", file=sys.stderr)
            continue
        try:
            note = func(payload)
        except Exception as exc:  # noqa: BLE001 — a broken note must never block or corrupt the JSON
            print(f"[act] note {module_name} skipped ({type(exc).__name__}: {exc})", file=sys.stderr)
            continue
        if isinstance(note, str) and note:
            notes.append(note)
    return notes


def main(argv: list[str]) -> int:
    # "_update-check-worker" is the one exception to the "exactly one arg" harness contract
    # below: it is never a harness hook event, only what checks.session._spawn_update_check_
    # worker() launches (argv[1] is the project root as a string). Checked first so a stray
    # extra argv entry here can never fall through to "no event named".
    if len(argv) == 2 and argv[0] == "_update-check-worker":
        return _run_update_check_worker(Path(argv[1]))

    if len(argv) != 1:
        return 0  # no event named — nothing to dispatch, never an error for the caller

    event = argv[0]
    payload = _early_payload if _early_payload is not None else _read_payload()
    _run_observers(event, payload)

    if event == "PreToolUse":
        return _run_checks(payload)
    if event == "PostToolUse":
        notes = _run_post_tool_use_notes(payload)
        if notes:
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": "\n".join(notes),
                }
            }))
        return 0  # notes never block
    if event == "SessionStart":
        return refresh_session(payload)
    return 0  # any other event (SubagentStart, UserPromptSubmit, ...) only feeds the observers


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
