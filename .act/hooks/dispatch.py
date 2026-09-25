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
#          PostToolUseFailure runs the very same _POST_TOOL_USE_NOTES list, the same way (2026-09-
#          23, T44 live probe): when every one of a worker's tool calls fails (e.g. every Read
#          errors because the file does not exist), the harness only ever fires PostToolUseFailure,
#          never PostToolUse — a worker that never gets a single successful call also never got its
#          cap-reached hint under the old PostToolUse-only wiring, silently. Confirmed against the
#          hook docs (code.claude.com/docs/en/hooks, fetched 2026-09-23): PostToolUseFailure's
#          hookSpecificOutput does support additionalContext, hookEventName "PostToolUseFailure".
#          Deliberately NOT given the same pre-import, pre-observer fast exit that PostToolUse's
#          early block above has (see that block's own comment): that exit runs before
#          _run_observers, which is safe for PostToolUse only because none of _OBSERVERS reacts to
#          a plain "PostToolUse" event — but checks.event_log.observe *does* have a dedicated
#          PostToolUseFailure branch (the "[error]" log line, every failure, any tool, worker or
#          not) that must keep firing regardless of which tool failed. Skipping straight past that
#          would silently drop failure logging for every tool outside _POST_TOOL_USE_TOOLS (Read,
#          Grep, Glob, WebFetch, ...) — the opposite of what this fix is for. PostToolUseFailure
#          therefore always goes through the normal event path (imports, observers, then notes);
#          only the notes themselves stay as cheap as PostToolUse's (each note_<name> already
#          returns None fast for a call it does not care about, see worker_cap.note_worker_cap et
#          al.). .act/bridges/settings.hooks.json's PostToolUseFailure entry was `async: true`
#          (needed only for the event-log write, which never needs to reach the model) — switched
#          to synchronous here so the JSON this now also prints is reliably delivered, one hook
#          entry doing both jobs rather than a second one added alongside it.
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
#   python .act/hooks/dispatch.py UserPromptSubmit --act-check
#   ... with the hook's JSON payload piped in on stdin (may be empty or malformed; handled).
#
#   <event> is the hook event name. "PreToolUse" runs the checks, "PostToolUse" and
#   "PostToolUseFailure" both run the notes, "SessionStart" the session handler; every event
#   (these four and e.g. SubagentStart, SubagentStop, UserPromptSubmit, Notification, SessionEnd)
#   first goes to the observers. Anything else exits 0 — an unknown event must never break the
#   caller's hook chain. "UserPromptSubmit --act-check" is a second, separate invocation of this
#   same event (its own synchronous entry in .act/bridges/settings.hooks.json, alongside the
#   plain "UserPromptSubmit" one, which stays async and unchanged) — see the fast-path block near
#   the top of this file, before the heavy imports, and "Output format" below.
#
# Output format:
#   PreToolUse:   exit 0 (allow) or exit 2 with a one-line reason on stderr (deny) — the
#                 harness convention for "block this tool call and show the assistant why".
#   PostToolUse / PostToolUseFailure: exit 0 always (notes never block); if at least one note
#                 module returned text, one line on stdout: {"hookSpecificOutput": {"hookEventName":
#                 "PostToolUse"|"PostToolUseFailure", "additionalContext": "<note>\n<note>..."}} —
#                 multiple notes joined with "\n", hookEventName matching whichever of the two
#                 events this run is for.
#                 Nothing printed at all when no note module had anything to say.
#   SessionStart: one JSON object on stdout (T64): `hookSpecificOutput.additionalContext` holds
#                 the lines below, kept under the 10,000-character cap (above it Claude Code
#                 moves a hook output into a file and shows the model a 2,000-character
#                 preview), and a top-level `systemMessage` holds one line for the human (rule
#                 files loaded per `rules.py --imports`, chat language, inbox entries to
#                 process). The lines: an optional
#                 block of orchestrator-only rules, one line per rule plus where the full text
#                 lives (main session only, never seen by a sub-agent), zero or more "[act] note: ..."
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
#   "UserPromptSubmit --act-check" (T67): the prompt is not "/act"/"/act <name>", or it is a
#                 worker's own payload — exit 0, nothing on stdout (the common case, checked
#                 before any of manifest.py/tiers.py/checks.session is imported). On a match:
#                 one line on stdout, {"decision": "block", "reason": "<skill list or one skill's
#                 SKILL.md in full>"} — the format Claude Code is confirmed to read for
#                 UserPromptSubmit as "show `reason` to the user, never send this prompt to the
#                 model" (same mechanism the predecessor template used before T60's `.act/`
#                 restructure). Always exit 0 either way; a bug in .act/scripts/skills.py falls
#                 back to "say nothing, let the prompt through" rather than eating it.
#
# Exit-code contract for PreToolUse specifically: a mechanism error while checking a candidate
# write is NOT swallowed the way a SessionStart error is. Every other check in this template
# fails open (never blocks the session on its own bug); the write-guard is the one exception —
# "when in doubt, deny" — because a false allow here means the template
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
        # Read raw bytes and decode as UTF-8 explicitly — sys.stdin.read() picks the console's
        # legacy code page on Windows (e.g. cp1252), which silently mangles non-ASCII bytes in
        # the payload (a prompt or path with an umlaut) before json.loads ever sees them (live
        # probe T44, 2026-09-23: "wörtlich" arrived as "wÃ¶rtlich"). errors="replace" keeps a
        # genuinely undecodable byte from crashing the hook — same "never grounds to crash"
        # stance as the except clause below.
        _raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        _early_payload = json.loads(_raw) if _raw.strip() else {}
    except (OSError, ValueError, AttributeError):
        _early_payload = {}
    if not isinstance(_early_payload, dict):
        _early_payload = {}
    if not _early_payload.get("agent_id") and _early_payload.get("tool_name") not in _POST_TOOL_USE_TOOLS:
        sys.exit(0)

# UserPromptSubmit "/act" fast intercept (T67) — a second, synchronous hook entry dedicated to
# this one check (.act/bridges/settings.hooks.json's "--act-check" entry), kept apart from the
# plain "UserPromptSubmit" entry below (still async, feeds only the observers — see
# checks/tips.py's own header for why that one stays async: it never needs to block anything). A
# normal prompt must never pay for manifest.py/tiers.py/checks.session just to rule itself out
# here — checked before any of that is imported, same early-exit shape as the PostToolUse block
# above. Only on an actual "/act"/"/act <name>" match is .act/scripts/skills.py imported and run;
# on a match, prints {"decision": "block", "reason": <skill list or one skill in full>} — Claude
# Code shows the reason to the user and never sends the prompt to the model (confirmed against
# the predecessor template's identical mechanism, live before T60's structure change).
if len(sys.argv) == 3 and sys.argv[1] == "UserPromptSubmit" and sys.argv[2] == "--act-check":
    import re as _re
    try:
        _raw2 = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        _payload2 = json.loads(_raw2) if _raw2.strip() else {}
    except (OSError, ValueError, AttributeError):
        _payload2 = {}
    if not isinstance(_payload2, dict):
        _payload2 = {}
    _prompt2 = _payload2.get("prompt")
    _match2 = _re.fullmatch(r"\s*/act(?:\s+(\S+))?\s*", _prompt2) if isinstance(_prompt2, str) else None
    if _match2 is None or _payload2.get("agent_id"):
        sys.exit(0)  # not "/act"/"/act <name>", or a worker's own payload — nothing to do here
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    try:
        import actlib as _actlib2  # noqa: E402
        import skills as _skills2  # noqa: E402
        _reason2 = _skills2.render(_actlib2.repo_root(), _match2.group(1) or "")
    except Exception:  # noqa: BLE001 — a bug in the listing must never eat the user's prompt
        sys.exit(0)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    print(json.dumps({"decision": "block", "reason": _reason2}, ensure_ascii=False))
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
    ("git_reset_hard", "check_git_reset_hard"),           # git reset --hard on a dirty tree (R-safe-git-reset)
    ("recursive_delete", "check_recursive_delete"),       # rm -r and friends (R-safe-no-shell-delete)
    ("secret_scan", "check_secret_scan"),                 # secrets in the diff before commit (R-safe-no-secret-diff)
    ("worker_cap", "check_worker_cap"),                   # tool calls beyond the worker's cap (R-cost-delegate)
    ("status_poll", "check_status_poll"),                 # repeated status queries (R-cost-wait)
    ("encoding_hint", "check_encoding_hint"),             # non-UTF-8 target, note only (R-code-encoding)
)

# PostToolUse / PostToolUseFailure notes, all of them run every time for either event (no "first
# wins" — unlike _PRE_TOOL_USE_CHECKS, these never block, so there is nothing to short-circuit).
# Each entry is (module under checks/, function name); signature note_<name>(payload: dict) -> str
# | None. Same skip-if-missing rule as _PRE_TOOL_USE_CHECKS. See the header comment above for the
# full contract, and for why PostToolUseFailure shares this exact list instead of its own.
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


def _emit_post_tool_use_notes(event: str, payload: dict) -> None:
    """Shared by the "PostToolUse" and "PostToolUseFailure" branches of main(): run
    _POST_TOOL_USE_NOTES and, only if at least one note came back, print the single
    hookSpecificOutput JSON object both events use, with hookEventName set to whichever of the two
    this call is for (see this module's header, "Output format")."""
    notes = _run_post_tool_use_notes(payload)
    if notes:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": "\n".join(notes),
            }
        }))


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
    if event in ("PostToolUse", "PostToolUseFailure"):
        _emit_post_tool_use_notes(event, payload)
        return 0  # notes never block
    if event == "SessionStart":
        return refresh_session(payload)
    return 0  # any other event (SubagentStart, UserPromptSubmit, ...) only feeds the observers


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
