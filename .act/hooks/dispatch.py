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
#          to _PRE_TOOL_USE_CHECKS at the position it should run in. A listed module whose file is
#          missing counts as a failed check (see "Exit-code contract" below), not as one that is not
#          built yet. Observers (event log, usage counter) work the same way via
#          _OBSERVERS, with observe(event, payload) -> None (checks/board_refresh.py, for instance,
#          regenerates the board after a PostToolUse of a git merge/pull/rebase/switch/...); for
#          every event but PreToolUse they see it before any check runs and never block — for
#          PreToolUse specifically they run *after* the checks instead (see the "PreToolUse" paragraph under Usage below).
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
#          to reach the model, and reaches a worker for its own calls (live probe, see
#          checks/worker_cap.py). A check that also needs to *deny* a call still does that from
#          PreToolUse (exit 2 + stderr, the only channel confirmed to reach the model for that
#          event) — PostToolUse's notes are for the non-blocking half of the same checks only.
#
#          PostToolUseFailure runs the very same _POST_TOOL_USE_NOTES list, the same way (a live
#          probe): when every one of a worker's tool calls fails (e.g. every Read
#          errors because the file does not exist), the harness only ever fires PostToolUseFailure,
#          never PostToolUse — a worker that never gets a single successful call also never got its
#          cap-reached hint under the old PostToolUse-only wiring, silently. Confirmed against the
#          hook docs (code.claude.com/docs/en/hooks, fetched 2026-09-23): PostToolUseFailure's
#          hookSpecificOutput does support additionalContext, hookEventName "PostToolUseFailure".
#          Deliberately NOT given the same pre-import, pre-observer fast exit that PostToolUse's
#          early block above has (see that block's own comment): that exit runs before
#          _run_observers, which is safe for PostToolUse only because the observers that react to
#          a plain "PostToolUse" event (board_refresh) only care about tools in
#          _POST_TOOL_USE_TOOLS (Bash, PowerShell), which the early block lets through — but checks.event_log.observe *does* have a dedicated
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
#          Before either of those, PostToolUse and PostToolUseFailure run the protected-files watcher
#          (checks.protected_watch.run, R-safe-git-metadata: after every call it compares the files that
#          rule protects with a snapshot, puts back what a worker changed and reports what the orchestrator
#          changed) and deliver the notes queued for the orchestrator. It needs only the standard library,
#          so PostToolUse runs it in the early block below, before the heavy imports, and the early exit
#          still applies to every call that can produce no note -- except a TaskStop call of the
#          orchestrator, which an observer (worker_scope_overlap) reacts to. Its report joins the notes in
#          the one JSON object, plus a top-level systemMessage for the human.
#
#          Stop and SubagentStop run checks.model_switch.run after the observers: it reads the transcript
#          (the worker's own at SubagentStop, the session's at Stop) and, if a refusal or another model
#          shows up, queues a note for the orchestrator, delivered with its next PostToolUse
#          (additionalContext of a stop event would keep the agent running). Nothing is printed for the
#          human: Claude Code records a Stop/SubagentStop systemMessage in the transcript but never
#          displays it. SessionStart takes the watcher's snapshot after the session handler has run.
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
#   python .act/hooks/dispatch.py SubagentStart --worker-rules <part>   # worker rules, see checks/worker_rules.py
#   ... with the hook's JSON payload piped in on stdin (may be empty or malformed; handled).
#
#   <event> is the hook event name. "PreToolUse" runs the checks, "PostToolUse" and
#   "PostToolUseFailure" both run the notes, "SessionStart" the session handler; every event but
#   "PreToolUse" (these three and e.g. SubagentStart, SubagentStop, UserPromptSubmit, Notification,
#   SessionEnd) goes to the observers first, unconditionally. "PreToolUse" is the one exception
#   exception: its observers run *after* its checks, and only for a call the checks
#   allow — see _run_pre_tool_use_observers' own docstring for why a call the checks deny must
#   never reach usage.py's role/skill/script/checklist counters (it never happened, from the
#   counters' point of view), while checks.event_log.observe still runs for it, marked as a denial
#   (R-safe-block: every block is logged). Anything else exits 0 — an unknown event must never
#   break the caller's hook chain. "UserPromptSubmit --act-check" is a second, separate invocation
#   of this same event (its own synchronous entry in .act/bridges/settings.hooks.json, alongside
#   the plain "UserPromptSubmit" one, which stays async and unchanged) — see the fast-path block
#   near the top of this file, before the heavy imports, and "Output format" below.
#
# Output format:
#   PreToolUse:   exit 0 (allow) or exit 2 with a one-line reason on stderr (deny) — the
#                 harness convention for "block this tool call and show the assistant why". A call
#                 that goes ahead although a check failed (see "Exit-code contract" below) prints one
#                 line on stdout, {"systemMessage": "<failure texts>"}, for the human, and leaves the
#                 same texts for this call's PostToolUse (.act-local/check-failures/<tool_use_id>.txt),
#                 whose additionalContext hands them to the model. Whatever else the checks print on
#                 stdout is held back meanwhile and joins that message, so stdout stays one JSON
#                 object; without a failure it is written unchanged.
#   PostToolUse / PostToolUseFailure: exit 0 always (notes never block); if at least one note
#                 module returned text, one line on stdout: {"hookSpecificOutput": {"hookEventName":
#                 "PostToolUse"|"PostToolUseFailure", "additionalContext": "<note>\n<note>..."}} —
#                 multiple notes joined with "\n", hookEventName matching whichever of the two
#                 events this run is for; the protected-files watcher's report comes first and adds a
#                 top-level "systemMessage" (shown to the human).
#                 Nothing printed at all when no note module had anything to say. A note that fails,
#                 and the texts queued by this call's PreToolUse (above), come after the watcher's
#                 report in the same additionalContext and systemMessage.
#   Stop / SubagentStop: exit 0 always, nothing on stdout (a systemMessage of these events is never shown).
#                 checks.model_switch queues its note for the orchestrator; when that module fails, or its
#                 note cannot be queued, one "[act] model-switch failed ..." line goes to stderr and the
#                 same text is queued as a note; stderr alone is the last resort when that queue itself
#                 fails (see _model_switch_failed).
#   SessionStart: one JSON object on stdout: `hookSpecificOutput.additionalContext` holds
#                 the lines below, kept under the 10,000-character cap (above it Claude Code
#                 moves a hook output into a file and shows the model a 2,000-character
#                 preview), and a top-level `systemMessage` holds one line for the human (rule
#                 files loaded per `rules.py --imports`, chat language, inbox entries to
#                 process). `hookSpecificOutput.sessionTitle` names the session after the project
#                 (config key `session-name`) on source startup, resume or fork, unless the
#                 input already carries a `session_title`. The lines: an optional
#                 block of orchestrator-only rules, one line per rule plus where the full text
#                 lives (main session only, never seen by a sub-agent), zero or more "[act] note: ..."
#                 lines (a changed/unrefreshable bridge, an unresolvable tier/reasoning value, a
#                 project .act/ pulled in without update.py — each best-effort and independently
#                 gated, see checks.session.refresh_session()), then the fixed-format status line
#                 "[act] branch=<name>[ · inbox: <n> waiting][ · ideas: <n> new][ · feedback due] ·
#                 board updated[ · rules: <n>][ · role-bridges refreshed: <n>]", then, unless
#                 `board-at-start` is off, an optional board excerpt ("[act] board excerpt ..." plus the
#                 board's "Waiting for you" and "Open tasks" sections, about 2,000 characters, a cut
#                 marked) that is shortened or dropped before anything else when the 10,000-character
#                 cap gets near, and finally, as a deliberate postscript after
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
#   "_act-local-tidy-worker" <root>: the same kind of internal-only event, launched by
#                 checks.session._spawn_act_local_tidy_worker() once a day: scripts/act_local_tidy.py
#                 keeps .act-local/ small; the next session start reports what it found.
#
#   "_security-scan-worker" <root> [<state-hash> <lock-file>...]: the same kind of internal-only
#                 event, launched by checks.session._spawn_security_scan_worker() — with the root
#                 alone for the daily dependency-vulnerability scan at session start (security-
#                 check: deps/full), with a state hash and the lock files one commit
#                 touches for checks/deps_scan.py's commit check — its own background process so
#                 `security_scan.run_scan()`'s tool call never delays a session start or a commit's
#                 own PreToolUse hook, mirroring "_update-check-worker". deps_scan.py hands the
#                 lock files over as one `@<list file>` argument (a JSON file under
#                 .act-local/security-scan-lists/, removed by the worker afterwards): on Windows a
#                 few hundred paths overrun the command-line limit (WinError 206). The same file
#                 says whether the run also files its findings as an inbox report -- the scan after
#                 a merge, pull or cherry-pick (deps_scan.note_deps_merge_scan, a PostToolUse note
#                 that never blocks).
#
#   "UserPromptSubmit --act-check": the prompt is not "/act"/"/act <name>", or it is a
#                 worker's own payload — exit 0, nothing on stdout (the common case, checked
#                 before any of manifest.py/tiers.py/checks.session is imported). On a match:
#                 one line on stdout, {"decision": "block", "reason": "<skill list or one skill's
#                 SKILL.md in full>"} — the format Claude Code is confirmed to read for
#                 UserPromptSubmit as "show `reason` to the user, never send this prompt to the
#                 model" (same mechanism the predecessor template used before the current `.act/`
#                 layout). Always exit 0 either way; a bug in .act/scripts/skills.py falls
#                 back to "say nothing, let the prompt through" rather than eating it.
#                 Quick capture rides on the same entry: when the first non-blank line starts with
#                 todo:/note:/idea: (case-insensitive; one regex on the raw prompt, still before any
#                 import), checks/quick_capture.py files the entries (inbox todo/note with `triage:
#                 open`, or a section in the own ideas file) and the same {"decision": "block"} line
#                 reports where; off with `quick-capture: off` in docs/ai/config.md, no identity or
#                 any error means the prompt goes through untouched.
#
# Exit-code contract for PreToolUse specifically: a mechanism error while checking a candidate
# call is NOT swallowed the way a SessionStart error is. The guards in _FAIL_CLOSED — the write-guard
# and the other write guards, and secret_read and outside_root for Bash and PowerShell — "when in doubt,
# deny": a false allow there means the template silently loses its own files to an edit the next update
# overwrites, or a secret or a foreign folder reaches the context. Every other check fails open (never
# blocks the session on its own bug), but not silently: see "Output format" for how the failure is
# reported to the model and the human.
#
# The same holds one level up: if the dispatcher cannot import a module it needs itself (actlib, manifest,
# tiers, checks.common, checks.session, or what they import), it ends with one line on stderr naming the module and
# exit 2 for a PreToolUse event (refused: no guard can run), exit 0 for every other event - never a traceback
# with exit 1, which Claude Code counts as not blocking.
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
import os
import re
import stat
import sys
import time

from pathlib import Path  # noqa: E402

# When this hook process began its own work -- every PreToolUse check receives it as
# payload["_act_hook_started"] (see _run_checks) and caps its own time budget against it
# (checks/secret_scan._check_deadline): the harness kills a PreToolUse hook at 10 s
# (.act/bridges/settings.hooks.json), and the secret, danger and deps scans run back to back in
# this one process, so their individual budgets must not simply add up (2026-09-27 review 2, m5).
_HOOK_STARTED = time.monotonic()

# Must run before importing anything under .act/ (actlib/manifest/tiers, the checks package):
# compiled caches go to <project>/.act-local/pyc instead of __pycache__/ folders under the
# template tree. Keeping them (rather than sys.dont_write_bytecode) saves ~35 ms per hook call,
# which runs twice for every tool call. The project, not the system temp directory: a cache there
# grows with every project path and is never cleaned up; here it is gitignored with the rest of
# .act-local/ and goes away with the project. The limit: pycache_prefix mirrors the full source path
# (without the drive letter) below the prefix, so inside the project the cache path is about twice as
# long as the source path, and Windows fails at 260 characters (deleting the folder, `git clean`).
# A `.act-local` or `.act-local/pyc` that is a link or junction, or whose real path leaves the project,
# gets no cache either (nothing is compiled into a place outside the project).
# If the longest cache path of this tree or of the standard library (cached below the prefix too)
# could pass _PYC_PATH_BUDGET, no cache is written at all — sys.dont_write_bytecode, so there is no
# __pycache__/ under .act/ either. Writing a cache is best effort in Python — a failure there never
# fails the hook.
_PYC_PATH_BUDGET = 240  # characters; Windows' limit is 260 including the drive and the file name
_PYC_LONGEST_TAIL = 70  # below .act/: "/hooks/checks/<longest module>.cpython-3NN.pyc" is about 50 today


def _pyc_way_is_clear(project_root: Path) -> bool:
    """False when `.act-local` or `.act-local/pyc` is a symbolic link, a Windows junction or another
    name-surrogate reparse point, or when the real path of the cache folder lies outside the project: Python
    would write the compiled caches through it. Standard library only (this runs before anything of
    .act/ is imported); the same test as actlib.link_problem."""
    folder = project_root
    for part in (".act-local", "pyc"):
        folder = folder / part
        try:
            info = os.lstat(folder)
        except OSError:
            return True  # not there yet: Python creates a real folder
        attributes = getattr(info, "st_file_attributes", 0)
        tag = getattr(info, "st_reparse_tag", 0)
        if stat.S_ISLNK(info.st_mode) or (attributes & 0x400 and (not tag or tag & 0x20000000)):
            return False
    try:
        real_root = os.path.normcase(os.path.realpath(project_root))
        real = os.path.normcase(os.path.realpath(folder))
        return os.path.commonpath([real_root, real]) == real_root
    except (OSError, ValueError):  # a path that cannot be resolved is not safe; ValueError: another drive
        return False


try:
    _project_root = Path(__file__).resolve().parents[2]
    _pyc_prefix = _project_root / ".act-local" / "pyc"
    # The mirrored path drops only a drive letter ("D:"); a UNC share stays in it.
    _sources = (str(_project_root / ".act"), os.path.dirname(os.__file__))
    _longest_source = max(len(s) - 2 if s[1:2] == ":" else len(s) for s in _sources)
    if len(str(_pyc_prefix)) + _longest_source + _PYC_LONGEST_TAIL > _PYC_PATH_BUDGET or not _pyc_way_is_clear(_project_root):
        sys.dont_write_bytecode = True
    else:
        sys.pycache_prefix = str(_pyc_prefix)
except (IndexError, OSError, ValueError, RuntimeError):  # no usable project path: no cache either
    sys.dont_write_bytecode = True

# PostToolUse fires after every tool call, but only a worker's calls (cap note), the writing tools
# (encoding note, secret-scan note after a commit) and a few observed tools can produce a note. The
# protected-files watcher (checks/protected_watch.py, R-safe-git-metadata) and the orchestrator's queued
# notes run first, for every call: they need nothing but the standard library, so the common case still
# costs one small JSON parse, one directory listing and a few stat calls. Everything else returns
# here, before the imports below.
_POST_TOOL_USE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "PowerShell"}
# Tools of the orchestrator that an observer reacts to at PostToolUse, so the early exit must let them
# through: TaskStop (checks/worker_scope_overlap.observe frees the scope of the worker it stopped).
_POST_TOOL_USE_OBSERVED_TOOLS = {"TaskStop"}
_early_payload = None
_early_watch = None
_early_failures: "list[str]" = []

# Check failures (a check that cannot be imported or raises, a note that fails) are not only a stderr line:
# stderr reaches the model only when the call is refused (exit 2). A call that goes ahead gets the failure
# as a systemMessage for the human (PreToolUse and PostToolUse output) and, for the model, as
# additionalContext of the same call's PostToolUse, which the dispatcher already uses for its notes
# (reaches the model and a worker: live probe, Claude Code 2.1.319). The text waits in
# .act-local/check-failures/<tool_use_id>.txt between the two hook runs, the way checks/encoding_hint.py
# queues its note; without a tool_use_id the reader (session and agent) is the key.
_CHECK_FAILURES: "list[str]" = []   # this process's failures of PreToolUse checks, in the order they happened
_NOTE_FAILURES: "list[str]" = []    # ... of PostToolUse notes
_FAILURE_PARTS = (".act-local", "check-failures")
_FAILURE_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_FAILURE_TTL = 86400.0  # seconds a queued failure text stays valid (the call may never reach PostToolUse)
_MAX_FAILURE_REASON = 300  # characters of a check's own error text that go into a report


def _failure_key(payload: dict) -> "str | None":
    tool_use_id = payload.get("tool_use_id")
    if isinstance(tool_use_id, str) and _FAILURE_ID_RE.match(tool_use_id):
        return tool_use_id
    session = payload.get("session_id")
    if isinstance(session, str) and _FAILURE_ID_RE.match(session):
        agent = payload.get("agent_id")
        return f"{session}__{agent if isinstance(agent, str) and _FAILURE_ID_RE.match(agent) else 'main'}"
    return None


def _is_link(path: "str | os.PathLike[str]") -> bool:
    """True for a symbolic link and, on Windows, any reparse point (a junction too). A missing path is no link."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & 0x400)


# The project this dispatcher runs in, as it was started: <project>/.act/hooks/dispatch.py, two levels up, with
# no link resolved. A `.act` that is a link must not move the queue (and the prune of old texts in it) to the
# place the link points at, which can lie outside the project.
_QUEUE_ROOT = Path(os.path.abspath(__file__)).parents[2]


def _failure_folder() -> Path:
    return _QUEUE_ROOT.joinpath(*_FAILURE_PARTS)


def _failure_folder_clear(folder: Path) -> bool:
    """Neither `.act-local` nor the queue folder is a link: nothing is written or read through one."""
    return not (_is_link(folder.parent) or _is_link(folder))


def _queue_failure_notes(payload: dict, texts: "list[str]") -> None:
    """Leave `texts` for this call's PostToolUse (see above). Best effort: a queue that cannot be written
    is one line on stderr, never a reason to fail the call."""
    key = _failure_key(payload)
    if key is None or not texts:
        return
    folder = _failure_folder()
    try:
        if not _failure_folder_clear(folder):
            return
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{key}.txt"
        if not _failure_folder_clear(folder) or _is_link(path):
            return
        _prune_failure_notes(folder)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(texts) + "\n")
    except OSError as exc:
        print(f"[act] check failure not queued for the model ({type(exc).__name__}: {exc})", file=sys.stderr)


def _prune_failure_notes(folder: Path) -> None:
    """Remove the texts of calls that never reached PostToolUse. Best effort, entry by entry: one that cannot be
    read or removed is left, and never costs the text that is about to be queued."""
    try:
        names = os.listdir(folder)
    except OSError:
        return
    now = time.time()
    for name in names:
        old = folder / name
        try:
            if name.endswith(".txt") and not _is_link(old) and now - os.lstat(old).st_mtime > _FAILURE_TTL:
                os.remove(old)
        except OSError:
            continue


def _take_failure_notes(payload: dict) -> "list[str]":
    """The texts `_queue_failure_notes` left for this call, each delivered once; [] when there are none
    (the common case: one failed lstat)."""
    key = _failure_key(payload)
    if key is None:
        return []
    folder = _failure_folder()
    path = folder / f"{key}.txt"
    try:
        os.lstat(path)
    except OSError:
        return []
    try:
        if not _failure_folder_clear(folder) or _is_link(path):
            return []
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read(65536)
        os.remove(path)
    except OSError:
        return []
    return [line for line in text.splitlines() if line.strip()]


def _watch_protected_files(event: str, payload: dict):
    """What checks.protected_watch has to say after this call -- {"context": str, "message": str} or None.
    Imported on the spot (the module needs only the standard library) and never raises: a bug there is one
    line on stderr, the call is not touched."""
    try:
        from checks import protected_watch  # noqa: E402 -- before the heavy imports on purpose
        return protected_watch.run(event, payload)
    except Exception as exc:  # noqa: BLE001
        print(f"[act] protected-watch skipped ({type(exc).__name__}: {exc})", file=sys.stderr)
        return None


def _post_tool_use_json(event: str, contexts: list, message: str = "") -> str:
    """The one JSON object a PostToolUse/PostToolUseFailure hook prints: additionalContext for the model
    and, when there is one, the systemMessage for the human."""
    out = {"hookSpecificOutput": {"hookEventName": event, "additionalContext": "\n".join(contexts)}}
    if message:
        out["systemMessage"] = message
    return json.dumps(out)


if len(sys.argv) == 2 and sys.argv[1] == "PostToolUse":
    try:
        # Read raw bytes and decode as UTF-8 explicitly — sys.stdin.read() picks the console's
        # legacy code page on Windows (e.g. cp1252), which silently mangles non-ASCII bytes in
        # the payload (a prompt or path with an umlaut) before json.loads ever sees them (live
        # probe: "wörtlich" arrived as "wÃ¶rtlich"). errors="replace" keeps a
        # genuinely undecodable byte from crashing the hook — same "never grounds to crash"
        # stance as the except clause below.
        _raw = sys.stdin.buffer.read().decode("utf-8", errors="replace")
        _early_payload = json.loads(_raw) if _raw.strip() else {}
    except (OSError, ValueError, AttributeError):
        _early_payload = {}
    if not isinstance(_early_payload, dict):
        _early_payload = {}
    _early_watch = _watch_protected_files("PostToolUse", _early_payload)
    _early_failures = _take_failure_notes(_early_payload)
    if (not _early_payload.get("agent_id")
            and _early_payload.get("tool_name") not in _POST_TOOL_USE_TOOLS | _POST_TOOL_USE_OBSERVED_TOOLS):
        if _early_watch or _early_failures:
            print(_post_tool_use_json(
                "PostToolUse", ([_early_watch["context"]] if _early_watch else []) + _early_failures,
                "\n".join(([_early_watch["message"]] if _early_watch else []) + _early_failures)))
        sys.exit(0)

# UserPromptSubmit "/act" fast intercept — a second, synchronous hook entry dedicated to
# this one check (.act/bridges/settings.hooks.json's "--act-check" entry), kept apart from the
# plain "UserPromptSubmit" entry below (still async, feeds only the observers — see
# checks/tips.py's own header for why that one stays async: it never needs to block anything). A
# normal prompt must never pay for manifest.py/tiers.py/checks.session just to rule itself out
# here — checked before any of that is imported, same early-exit shape as the PostToolUse block
# above. Only on an actual "/act"/"/act <name>" match is .act/scripts/skills.py imported and run;
# on a match, prints {"decision": "block", "reason": <skill list or one skill in full>} — Claude
# Code shows the reason to the user and never sends the prompt to the model (confirmed against
# the predecessor template's identical mechanism, live before the `.act/` layout).
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
    if _payload2.get("agent_id"):
        sys.exit(0)  # a worker's own payload — nothing to do here
    # `/act-config ...`: answered by .act/scripts/config.py without a model turn. The cheap start
    # test decides before config is imported; `/act-configure` and every other prompt do not match.
    # `/act-info [--limit N]` and `/act-version [--all]` are shortcuts the same way: the script's own output
    # (`/act-version` the three-line form, `--all` the full list), run as a child process (a timeout or failure passes the prompt on, like a failure of config).
    _config_match = (_re.match(r"\s*/act-(config|info|version)(?=\s|$)", _prompt2) if isinstance(_prompt2, str) else None)
    if _config_match is not None:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        try:
            _root5 = Path(__file__).resolve().parents[2]
            _rest5 = _prompt2[_config_match.end():]
            if _config_match.group(1) == "config":
                import config as _config  # noqa: E402
                _config_code, _config_out = _config.handle(_root5, _rest5)
            else:
                import shlex as _shlex
                import subprocess as _subprocess
                _script5, _lead5 = (("info.py", []) if _config_match.group(1) == "info"
                                    else ("update.py", ["--versions", "--short"]))
                # Windows paths keep their backslashes (non-POSIX split); the git lookup gets a shorter limit than the hook's 8 s.
                _run5 = _subprocess.run(
                    [sys.executable, str(_root5 / ".act" / "scripts" / _script5), *_lead5,
                     *[_t[1:-1] if os.name == "nt" and len(_t) > 1 and _t[0] == _t[-1] and _t[0] in "\"'" else _t
                       for _t in _shlex.split(_rest5, posix=(os.name != "nt"))]],
                    cwd=str(_root5), capture_output=True, timeout=8, stdin=_subprocess.DEVNULL,
                    env={**os.environ, "ACT_LS_REMOTE_TIMEOUT": "5"})
                _config_out = _run5.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n").rstrip("\n")
                if not _config_out:
                    _err5 = _run5.stderr.decode("utf-8", errors="replace").strip()
                    if _run5.returncode == 2 and _err5.startswith("usage:"):
                        sys.exit(0)  # argparse usage error (e.g. an unknown option): the prompt goes on
                    _config_out = _err5 or f"{_script5} printed nothing"
        except Exception as _exc5:  # noqa: BLE001 -- a bug here must never eat the user's prompt
            print(f"[act] act-{_config_match.group(1)}: failed, message passed through ({_exc5!r})", file=sys.stderr)
            sys.exit(0)
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
        print(json.dumps({"decision": "block", "reason": _config_out,
                          "hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                 "suppressOriginalPrompt": True}}, ensure_ascii=False))
        sys.exit(0)
    if _match2 is None:
        # Advisory acknowledgement: the whole prompt is a sentence like "Warnung quittiert" (optionally
        # with advisory ids). The cheap start test decides before checks.advisory_ack is imported; the
        # module answers only when at least one advisory is active (files only), else the prompt goes on
        # unchanged. A block answers like the quick capture below: the prompt never reaches the model.
        if isinstance(_prompt2, str) and _re.match(r"\s*(?:warnung|hinweis|warning|notice)\s", _prompt2, _re.IGNORECASE):
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            try:
                from checks import advisory_ack as _advisory_ack  # noqa: E402
                _reason4 = _advisory_ack.handle(Path(__file__).resolve().parents[2], _payload2)
            except Exception as _exc4:  # noqa: BLE001 -- a bug here must never eat the user's prompt
                print(f"[act] advisory acknowledgement: failed, message passed through ({_exc4!r})", file=sys.stderr)
                _reason4 = None
            if _reason4:
                try:
                    sys.stdout.reconfigure(encoding="utf-8")
                except (AttributeError, ValueError):
                    pass
                print(json.dumps({"decision": "block", "reason": _reason4,
                                  "hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                         "suppressOriginalPrompt": True}}, ensure_ascii=False))
                sys.exit(0)
        # Quick capture: the first non-blank line starts with todo:/note:/idea: (case-insensitive).
        # One regex on the raw prompt decides, before checks.quick_capture is imported; every other
        # prompt ends here. capture() files the entries and returns the text to show, or None
        # (quick-capture off, no identity, a worker, any error) — then the prompt goes through.
        if not isinstance(_prompt2, str) or _re.match(r"\s*(?:todo|note|idea):", _prompt2, _re.IGNORECASE) is None:
            sys.exit(0)
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        try:
            from checks import quick_capture as _quick_capture  # noqa: E402
            # The project is this file's own, never the process cwd (a `cd` may have moved it).
            _reason3 = _quick_capture.capture(Path(__file__).resolve().parents[2], _payload2)
        except Exception as _exc3:  # noqa: BLE001 — a bug in the capture must never eat the user's prompt
            print(f"[act] quick-capture: failed, message passed through ({_exc3!r})", file=sys.stderr)
            sys.exit(0)
        if not _reason3:
            sys.exit(0)
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
        # suppressOriginalPrompt: the block notice leaves out its "Original prompt: ..." tail; the
        # reason already names where the text went.
        print(json.dumps({"decision": "block", "reason": _reason3,
                          "hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                                 "suppressOriginalPrompt": True}}, ensure_ascii=False))
        sys.exit(0)
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    try:
        import skills as _skills2  # noqa: E402
        _reason2 = _skills2.render(Path(__file__).resolve().parents[2], _match2.group(1) or "")
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
def _import_failed(module: str, exc: BaseException) -> None:
    """The modules the dispatcher itself needs (below) cannot be imported: end with one line on stderr
    naming the module, never with a traceback and exit 1 (which Claude Code reads as "not blocking", so every
    call would go through unchecked). A PreToolUse event exits 2 and is refused: no guard can be run. Every
    other event exits 0, the way the hook commands' `; true` would end it anyway."""
    event = sys.argv[1] if len(sys.argv) > 1 else ""
    detail = " ".join(f"{type(exc).__name__}: {exc}".split())[:_MAX_FAILURE_REASON]
    refuse = event == "PreToolUse"
    try:
        print(f"[act] dispatcher cannot import {module} ({detail})"
              + (" -- refusing to be safe; ask the owner to run .act/scripts/doctor.py (with the `!` prefix)"
                 if refuse else " -- event skipped; run .act/scripts/doctor.py"), file=sys.stderr)
    except (OSError, ValueError):
        pass
    sys.exit(2 if refuse else 0)


_importing = "actlib"
try:
    import actlib  # noqa: E402 (sys.path setup above must run first)
    _importing = "manifest"
    import manifest  # noqa: E402
    _importing = "tiers"
    import tiers  # noqa: E402

    # checks/ lives next to this file (.act/hooks/checks/); Python already put this file's own
    # directory (.act/hooks/) on sys.path[0] when it started, so the package is importable as-is.
    # common and session are needed by main() itself; a failure there is a template bug that must
    # surface (_import_failed), not be hidden. The other re-imports only keep `dispatch.<name>`
    # reachable for probes — a broken check module must not crash the dispatcher here; the registry
    # below decides what a broken check means (see _FAIL_CLOSED).
    _importing = "checks.common"
    from checks.common import *  # noqa: E402,F401,F403
    _importing = "checks.session"
    from checks.session import *  # noqa: E402,F401,F403
except Exception as _import_exc:  # noqa: BLE001 -- ImportError, SyntaxError and whatever a module does at import time
    _import_failed(_importing, _import_exc)
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
# function name); a module whose file is missing is a failed check like one that cannot be imported
# (_load, _check_failed): refused for a guard in _FAIL_CLOSED, reported for every other check.
#
# Order note: worker_cap and status_poll are deliberately
# the LAST two entries — both can deny based on their own running counter/streak (worker's tool-call
# count, orchestrator's consecutive-poll streak), and that counter/streak must never be bumped for a
# call another, earlier check goes on to deny anyway (e.g. encoding_hint refusing a worker's Write to
# a non-UTF-8 file must not also count that call against the worker's cap). Every check ahead of them
# here — including deps_scan, which can also deny — runs first for the same reason; a future check
# that can deny stays ahead of these two unless it specifically needs to see their denial first.
_PRE_TOOL_USE_CHECKS = (
    ("write_guard", "check_write_guard"),                 # check 1  — .act/ template write-guard
    ("git_metadata_guard", "check_git_metadata_guard"),   # .git/hooks, .git/config, git config keys that run code; worker: .claude/ settings
    ("nesting_guard", "check_worker_nesting_guard"),      # check 1b — no sub-sub-agents (R-role-worker)
    ("write_scope", "check_worker_write_scope"),          # check 1c — per-worker write scope (R-cost-delegate)
    ("worker_docs_ai", "check_worker_docs_ai"),           # worker writes under docs/ai/ (R-role-worker)
    ("worker_git_write", "check_worker_git_write"),       # worker runs a mutating git command (R-role-worker)
    ("cd_git", "check_cd_git"),                           # cd/pushd and git in one Bash call, Claude Code only (Claude Code asks the owner each time)
    ("mcp_ide", "check_mcp_ide"),                          # IDE MCP tool calls, classified and reused
    ("commit_pathspec", "check_commit_pathspec"),         # git add -A / . / commit -a (R-code-commit)
    ("git_discard", "check_git_discard"),                 # git that discards work: reset --hard, clean -f, folder checkout/restore, stash drop, force push to the default branch, branch -D (R-safe-git-reset, R-safe-git-discard)
    ("recursive_delete", "check_recursive_delete"),       # rm -r and friends (R-safe-no-shell-delete)
    ("secret_read", "check_secret_read"),                 # reading a secret file (.env, keys, cloud credentials) into the context
    ("outside_root", "check_outside_root"),               # reading or writing outside the project and its allowed places (R-safe-outside-root)
    ("secret_scan", "check_secret_scan"),                 # secrets in the diff before commit (R-safe-no-secret-diff)
    ("danger_scan", "check_danger_scan"),                 # dangerous patterns in the diff before commit (security-check)
    ("deps_scan", "check_deps_scan"),                     # dependency vulnerabilities in a touched lock file (security-check)
    ("encoding_hint", "check_encoding_hint"),             # non-UTF-8 target, note only (R-code-encoding)
    ("throwaway_place", "check_throwaway_place"),         # main session: temp directory or a file directly under .act-local/ as a target, note only (R-work-throwaway)
    ("commit_hashes", "check_commit_hashes"),             # git commit naming a commit hash no repository knows, note only (R-work-evidence)
    ("worker_scope_overlap", "check_worker_scope_overlap"),  # a worker start whose Write scope overlaps a running worker's (R-cost-delegate) —
                                                          # after every check that could still refuse the start: it records the start's
                                                          # scope, and a later refusal would leave that entry standing (worker_cap and
                                                          # status_poll never refuse the orchestrator's own Agent/Task call)
    ("worker_scope_overlap", "check_main_session_overlap"),  # notes, never a refusal: the orchestrator's write under a running worker's Tests:, its test run in a tree a worker writes in
    ("worker_cap", "check_worker_cap"),                   # tool calls beyond the worker's cap (R-cost-delegate) — last on purpose, see above
    ("status_poll", "check_status_poll"),                 # repeated status queries (R-cost-wait) — last on purpose, see above
)

# PostToolUse / PostToolUseFailure notes, all of them run every time for either event (no "first
# wins" — unlike _PRE_TOOL_USE_CHECKS, these never block, so there is nothing to short-circuit).
# Each entry is (module under checks/, function name); signature note_<name>(payload: dict) -> str
# | None. A missing module is reported as for _PRE_TOOL_USE_CHECKS. See the header comment above for the
# full contract, and for why PostToolUseFailure shares this exact list instead of its own.
_POST_TOOL_USE_NOTES = (
    ("worker_cap", "note_worker_cap"),        # cap-reached / cap-exceeded hints (R-cost-delegate)
    ("encoding_hint", "note_encoding_hint"),  # `warn` mode's one-time non-UTF-8 note (R-code-encoding)
    ("throwaway_place", "note_throwaway_place"),  # the note about a misplaced throwaway target (R-work-throwaway)
    ("commit_hashes", "note_commit_hashes"),  # the note about an unknown commit hash (R-work-evidence)
    ("secret_scan", "note_secret_scan"),      # `warn` mode / incomplete scan after a commit (R-safe-no-secret-diff)
    ("deps_scan", "note_deps_scan"),          # lower-severity/accepted findings after a commit (security-check)
    ("deps_scan", "note_deps_merge_scan"),    # lock files a merge/pull/cherry-pick brought in -> inbox report (security-check)
    ("worker_scope_overlap", "note_main_session_overlap"),  # the orchestrator's test run beside a worker writing in the tree (R-cost-delegate)
)

# Observers see every hook event and never block: signature observe(event: str, payload: dict) ->
# None; an exception inside one is swallowed. For every event but PreToolUse they run before any
# check does; for PreToolUse itself they run *after* the checks instead (_run_pre_tool_use_observers
# below). Used for the event log (topic "logging") and the usage counter. Same
# missing-module rule as above, except that an observer is skipped without a report.
_OBSERVERS = (
    ("event_log", "observe"),
    ("usage", "observe"),
    ("status_poll", "observe"),  # resets the poll streak on UserPromptSubmit (R-cost-wait)
    ("board_refresh", "observe"),  # regenerates the board after PostToolUse of git merge/pull/...
    ("tips", "observe"),         # minute/hour reminders on UserPromptSubmit — prints, like
                                 # context_hint below, only for that event: UserPromptSubmit runs
                                 # async (.act/bridges/settings.hooks.json), so plain stdout is
                                 # lost — only a hookSpecificOutput.additionalContext JSON object
                                 # on stdout reaches the model (checks/tips.py's observe() prints
                                 # exactly that, never bare text)
    ("worker_scope_overlap", "observe"),  # SubagentStop drops the finished worker's write-scope entry
    ("context_hint", "observe"),  # one-time /clear hint per context-size step on UserPromptSubmit;
                                  # prints the same kind of object as tips — main() merges both
)


# Checks whose failure (import error, missing function, exception while running) refuses the
# call instead of letting it through: exit code 1 would count as "not blocking" for the harness,
# so a broken guard would silently open the door it is meant to keep shut. Every other check
# fails open — a broken convenience check must not stop all work — but its failure is reported
# to the model and the human (see _report_check_failures), not left to one stderr line.
_FAIL_CLOSED = {"write_guard", "git_metadata_guard", "nesting_guard", "write_scope", "mcp_ide",
                "secret_read", "outside_root"}
# Only tools that can write or start a worker are refused by a broken guard — reading stays
# possible, so the assistant can still look into what broke.
_FAIL_CLOSED_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit", "Bash", "PowerShell", "Agent", "Task"}
# The two read guards are refused for the shell only: a broken secret_read must not let `cat .env` through,
# and a broken outside_root not a command that reaches out of the project; Read, Write, Edit and the rest
# stay possible, so the cause can be looked into and the config fixed.
_FAIL_CLOSED_SHELL_ONLY = {"secret_read", "outside_root"}
_SHELL_TOOLS = {"Bash", "PowerShell"}

def _mcp_call_needs_mcp_ide(tool_name: str, payload: dict) -> bool:
    """True when a *working* checks.mcp_ide.check_mcp_ide could have denied this call -- i.e.
    whether _check_failed's fallback below (mcp_ide broken) must deny it too, rather than letting
    it through the way mcp_ide.py's own final `return 0` would for anything it does not classify
    (review finding 4b: a broken mcp_ide used to deny *every* `mcp__` call, even a plainly
    read-only one on an unrelated server, which is a strictly worse outcome than the bug this check
    exists to guard against). A server with no IDE evidence at all (Gmail, Docs, ...) must stay
    untouched here exactly as it would with a working mcp_ide.

    Judged from checks.mcp_ide_tables -- the class tables mcp_ide.py itself reads, kept in a module
    of their own with nothing in it that can fail -- so a runtime error inside check_mcp_ide() and
    an import error of mcp_ide.py come out the same (the two used
    to differ, exit 2 vs. 0 for the orchestrator's own `create_new_file`): a shell- or
    write-classified tool denies for everyone (a working check can deny the orchestrator there,
    via the .act/ write-guard); an exec-classified one for a worker only (a working check never
    denies the orchestrator there, it only prints a note); a read tool never; an unlisted tool on an
    IDE-named server (checks.session._is_ide_server_name, already loaded by this module's own
    wildcard import above -- the one part of the definition that never depends on mcp_ide.py) for
    a worker only, as the working check would. Only if even the tables module cannot be used is
    every call on an IDE-named server refused, worker or not, reads included: with no table left to
    tell `read_file` from `create_new_file`, "cannot evaluate" denies, and the message names
    doctor.py."""
    if not tool_name.startswith("mcp__"):
        return False
    rest = tool_name[len("mcp__"):]
    server, sep, suffix = rest.partition("__")
    if not sep or not server or not suffix:
        return False  # not even shaped like an MCP tool call
    ide_named = _is_ide_server_name(server)
    try:
        tables = importlib.import_module("checks.mcp_ide_tables")
        tool_class = tables._tool_class(suffix)
    except Exception:  # noqa: BLE001 — not even the tables are usable: nothing left to classify with
        return ide_named
    if tool_class in ("shell", "write"):
        return True
    if tool_class == "exec":
        return _is_worker(payload)
    if tool_class == "read":
        return False
    return ide_named and _is_worker(payload)


def _load(module_name: str, func_name: str):
    """(func, None) when the check is available, (None, reason) when it cannot be used: its module file is
    missing, it fails to import, or the function is not there. A missing file is a failure like the others
    -- a guard whose file was deleted must not be taken for one that is not built yet."""
    try:
        module = importlib.import_module(f"checks.{module_name}")
    except ModuleNotFoundError as exc:
        if exc.name == f"checks.{module_name}":
            return None, f"module file checks/{module_name}.py missing"
        return None, f"import failed: {exc}"
    except Exception as exc:  # noqa: BLE001
        return None, f"import failed: {type(exc).__name__}: {exc}"
    func = getattr(module, func_name, None)
    if not callable(func):
        return None, f"function {func_name} missing"
    return func, None


def _note_incident(kind: str, source: str, payload: dict, detail: str = "") -> None:
    """Append one event to the incident log (.act/scripts/incidents.py), delivered to the inbox at the next
    session start. Identifiers only: the tool name, a shell command's first word when it is a plain word.
    Never raises."""
    try:
        import incidents  # noqa: E402 -- .act/scripts/ is on sys.path
        tool = payload.get("tool_name")
        parts = [detail, tool if isinstance(tool, str) else ""]
        if tool in _SHELL_TOOLS:
            tool_input = payload.get("tool_input")
            parts.append(incidents.command_word(tool_input.get("command") if isinstance(tool_input, dict) else None))
        role = "worker" if payload.get("agent_id") else "main"
        incidents.record(actlib.repo_root(), kind, source, " ".join(part for part in parts if part), role)
    except Exception:  # noqa: BLE001 -- the log must never change a verdict
        pass


_SLOW_NOTED = False


def _modes_seen() -> "dict[str, str]":
    """checks.common.MODES_SEEN, or an empty dict while that module is not loaded or lacks it (a new
    dispatch.py next to an old common.py in the middle of an update). Never raises."""
    modes = getattr(sys.modules.get("checks.common"), "MODES_SEEN", None)
    return modes if isinstance(modes, dict) else {}


def _hits_seen() -> "dict[str, dict]":
    """checks.common.HITS (what a check in `warn` mode reported about a hit), or an empty dict while that module
    is not loaded or lacks it. Never raises."""
    hits = getattr(sys.modules.get("checks.common"), "HITS", None)
    return hits if isinstance(hits, dict) else {}


# The checks whose `warn` hit means the call went through AND wrote, deleted or committed something: the incident
# log keeps those. A check that reports its hit itself (checks.common._note_hit) decides for its own call; a hint
# to the main session, a worker-count note or a read-only notice is no entry.
_ACTING_CHECKS = frozenset({
    "write_guard", "git_metadata_guard", "write_scope", "worker_docs_ai", "worker_git_write",
    "commit_pathspec", "git_discard", "recursive_delete", "secret_read", "secret_scan",
})


def _payload_target(payload: dict) -> str:
    """The masked class of the file a file tool names (`project/d2`), else "-". Never a name."""
    try:
        tool_input = payload.get("tool_input")
        raw = next((tool_input[key] for key in ("file_path", "notebook_path") if isinstance(tool_input, dict)
                    and isinstance(tool_input.get(key), str)), "")
        common = importlib.import_module("checks.common")
        return common._target_class(raw, actlib.repo_root()) if raw else "-"
    except Exception:  # noqa: BLE001 -- the log must never change a verdict
        return "-"


def _note_check_outcome(module_name: str, payload: dict, result: int, printed: str, modes: "dict[str, str]",
                        hits: "dict[str, dict] | None" = None) -> None:
    """Incident log entries for one finished check: a `warn` hit that let the call through and wrote, deleted or
    read a secret file (the check's own report, else a plain-text note from a check whose row was `warn` and that
    is in _ACTING_CHECKS), a check that ended past 8 s of the harness' 10 s hook limit. A refusal is not an
    incident: the caller sees it at once, and it is only counted (_count_refusal)."""
    if result != 0:
        return
    text = printed.strip()
    hits = hits or {}
    if hits or (text and not text.startswith("{") and "warn" in modes.values()):
        acting = [info for info in hits.values() if isinstance(info, dict) and info.get("acts")]
        if acting:
            _note_incident("warn", module_name, payload, f"{acting[0].get('reason', 'warned')} {acting[0].get('target', '-')}")
        elif not hits and module_name in _ACTING_CHECKS:
            _note_incident("warn", module_name, payload, f"warned {_payload_target(payload)}")
    global _SLOW_NOTED
    if not _SLOW_NOTED and time.monotonic() - _HOOK_STARTED > 8.0:
        _SLOW_NOTED = True  # one row per hook call: the first check that ends past 8 s is the one named
        _note_incident("check-slow", module_name, payload)


def _count_refusal(module_name: str, payload: dict) -> None:
    """Count one refusal of a check, silently, per check, role and day in usage.json (identifiers only: the
    check's module name and the worker's role name or `main`; no command, no path). A refusal is no incident, but a check that
    keeps refusing workers is what `doctor.py --inbox` asks about. Never raises and never changes the verdict."""
    try:
        import incidents
        if incidents.is_off():
            return  # the switch of the test suites: the project's own counters stay clean
        import usage
        role = "main"
        if payload.get("agent_id"):
            agent_type = payload.get("agent_type")
            role = agent_type if isinstance(agent_type, str) and agent_type else "worker"
        usage.record_refusal(actlib.repo_root(), module_name, role)
    except Exception:  # noqa: BLE001 -- counting must never change a verdict
        pass


def _is_reader_failure(exc: BaseException) -> bool:
    """True for the failure of the reader of inline interpreter code (checks.inline_code.ReaderFailure): a command
    it could not read to the end is refused by every check that reads write targets, fail-closed guard or not."""
    reader_failure = getattr(sys.modules.get("checks.inline_code"), "ReaderFailure", None)
    return isinstance(reader_failure, type) and isinstance(exc, reader_failure)


def _check_failed(module_name: str, reason: str, payload: dict, reader_failure: bool = False) -> int:
    tool_name = payload.get("tool_name")
    if module_name == "mcp_ide":
        # mcp_ide is only ever this check's business for an actual `mcp__...` call (see
        # mcp_ide.check_mcp_ide's own early `return 0` for anything else) — an unrelated Bash/
        # Write/Agent call must never be denied just because this one, unrelated check is broken
        # (review finding 4a). Within an MCP call, fail closed only where a working check would
        # actually have looked at all (_mcp_call_needs_mcp_ide, review finding 4b) — a plainly
        # read-only or unrecognized MCP tool passes through the same as mcp_ide.py's own final
        # `return 0` would for it, broken check or not.
        applies = isinstance(tool_name, str) and _mcp_call_needs_mcp_ide(tool_name, payload)
    elif module_name in _FAIL_CLOSED_SHELL_ONLY:
        applies = tool_name in _SHELL_TOOLS
    else:
        applies = tool_name in _FAIL_CLOSED_TOOLS
    reason = " ".join(str(reason).split())[:_MAX_FAILURE_REASON]
    _note_incident("check-error", module_name, payload, reason.split(":")[0])  # the exception class only, never its text
    if (module_name in _FAIL_CLOSED or reader_failure) and applies:
        print(f"[act] check {module_name} failed ({reason}) — refusing to be safe; "
              f"{tool_name} stays refused until the check works again, ask the owner to run "
              ".act/scripts/doctor.py (with the `!` prefix)", file=sys.stderr)
        return 2
    text = (f"[act] check {module_name} skipped ({reason}) — it did not look at this "
            f"{tool_name if isinstance(tool_name, str) else 'tool'} call; run .act/scripts/doctor.py")
    print(text, file=sys.stderr)
    _CHECK_FAILURES.append(text)
    return 0


def _build_parse(payload: dict) -> "object | None":
    """The checks.command_parse.Parse of a Bash or PowerShell call, else None. A module that cannot be
    imported or a construction that raises gives None: the checks then read the command themselves."""
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if tool_name not in ("Bash", "PowerShell") or not isinstance(command, str):
        return None
    try:
        module = importlib.import_module("checks.command_parse")
        return module.Parse(tool_name, command)
    except Exception:  # noqa: BLE001 - never fails the dispatcher
        return None


def _run_checks(payload: dict) -> "tuple[int, str | None]":
    """(exit code, denying module's name) — the name is None on allow (exit code 0), and passed on
    to _run_pre_tool_use_observers so checks.event_log.observe can name the check that denied
    instead of only recording that *some* check did."""
    # a copy, never the caller's own dict (same stance as _run_pre_tool_use_observers): the checks
    # see the hook's own start for their shared time budget, the observers and the log do not
    checked_payload = dict(payload, _act_hook_started=_HOOK_STARTED)
    parse = _build_parse(payload)
    if parse is not None:
        checked_payload["_act_parse"] = parse  # one reading of the command for all checks of this call
    for module_name, func_name in _PRE_TOOL_USE_CHECKS:
        func, reason = _load(module_name, func_name)
        failed = False
        if func is None:
            failed = True
            result = _check_failed(module_name, reason or "check not available", payload)
        else:
            import io
            _modes_seen().clear()
            _hits_seen().clear()
            real_stdout, printed = sys.stdout, io.StringIO()
            sys.stdout = printed  # what the check prints is passed on below, and looked at for a `warn` hit
            try:
                result = func(checked_payload)
            except Exception as exc:  # noqa: BLE001
                failed = True  # _check_failed has logged check-error; a refusal row on top would double it
                result = _check_failed(module_name, f"{type(exc).__name__}: {exc}", payload, _is_reader_failure(exc))
            finally:
                sys.stdout = real_stdout
            sys.stdout.write(printed.getvalue())
            if not failed:
                _note_check_outcome(module_name, payload, result, printed.getvalue(), dict(_modes_seen()),
                                    dict(_hits_seen()))
        if result != 0:
            if not failed:
                _count_refusal(module_name, payload)
            return result, module_name
    return 0, None


def _run_observers(event: str, payload: dict) -> None:
    for module_name, func_name in _OBSERVERS:
        func, _reason = _load(module_name, func_name)
        if func is None:
            continue
        try:
            func(event, payload)
        except Exception:  # noqa: BLE001 — an observer must never break the hook chain
            pass


def _run_observers_merged(event: str, payload: dict) -> None:
    """UserPromptSubmit: more than one observer may print a hookSpecificOutput JSON object (tips,
    context_hint); two objects back to back would not be valid output. Capture what the observers
    print, merge every additionalContext text into one object, print that. Anything that is not such
    an object (plain text, JSON of another shape) is printed after it unchanged. Whatever goes wrong
    while merging, the captured output is printed as it was; this never raises."""
    import io
    real = sys.stdout
    buffer = io.StringIO()
    sys.stdout = buffer
    try:
        _run_observers(event, payload)
    finally:
        sys.stdout = real
    captured = buffer.getvalue()
    if not captured.strip():
        return
    try:
        texts: list[str] = []
        other: list[str] = []
        decoder = json.JSONDecoder()
        position = 0
        while position < len(captured):
            if captured[position].isspace():
                position += 1
                continue
            try:
                obj, end = decoder.raw_decode(captured, position)
            except ValueError:
                other.append(captured[position:])
                break
            specific = obj.get("hookSpecificOutput") if isinstance(obj, dict) else None
            context = specific.get("additionalContext") if isinstance(specific, dict) else None
            if isinstance(context, str) and context:
                texts.append(context)
            else:
                other.append(captured[position:end])
            position = end
        merged = ""
        if texts:
            merged = json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": "\n".join(texts)}}) + "\n"
        merged += "".join(chunk.rstrip("\n") + "\n" for chunk in other)
    except Exception:  # noqa: BLE001 — a hook never ends in a traceback; pass the output through
        merged = captured
    try:
        sys.stdout.write(merged)
    except Exception:  # noqa: BLE001
        pass


def _run_pre_tool_use_observers(payload: dict, denied: bool, denied_by: "str | None" = None) -> None:
    """PreToolUse's own observer run: a call one of _PRE_TOOL_USE_CHECKS
    denies must never be counted by usage.py's role/skill/script/checklist counters, nor logged as
    an unqualified success — the fix is to run the observers *after* _run_checks, for this one
    event only, and skip every counting observer outright when the call was denied.

    Allowed call (denied=False): unchanged behavior, every observer in _OBSERVERS runs exactly as
    it always has (_run_observers(event, payload)).

    Denied call (denied=True): only checks.event_log.observe still runs (R-safe-block: every
    block is logged, even a harmless one) — with payload["_act_denied"] = True and, when known,
    payload["_act_denied_by"] = denied_by (the module name from _run_checks, e.g. "encoding_hint")
    set on a *copy* of payload (never mutate the caller's own dict) so it can log the line as a
    denial naming which check denied it, rather than as a "delegate"/DEBUG "tool" line or an
    unqualified "denied". usage.observe, status_poll.observe and tips.observe are skipped
    entirely: none of them has any business seeing a call that never actually happened. (status_
    poll.observe/tips.observe only react to UserPromptSubmit anyway, so skipping them here changes
    nothing for PreToolUse — spelled out because _OBSERVERS is a shared list, not to imply either
    one used to fire here.)

    Considered and rejected: passing `denied` as a third argument to every observer's own
    observe(event, payload) — this module's own header documents that signature as
    "observe(event: str, payload: dict) -> None" for every registered observer, a contract other
    checks/notes also rely on (see the header's "Backward compatibility" paragraph); widening it
    everywhere for the sake of the one observer that needs the flag would be a bigger, riskier
    change than reusing the payload dict already every observer's only channel."""
    if not denied:
        _run_observers("PreToolUse", payload)
        return
    func, _reason = _load("event_log", "observe")
    if func is None:
        return
    extra = {"_act_denied": True}
    if denied_by:
        extra["_act_denied_by"] = denied_by
    try:
        func("PreToolUse", dict(payload, **extra))
    except Exception:  # noqa: BLE001 — an observer must never break the hook chain
        pass


def _note_failed(module_name: str, reason: str) -> None:
    reason = " ".join(str(reason).split())[:_MAX_FAILURE_REASON]
    text = f"[act] note {module_name} skipped ({reason}) — its hint for this call is missing; run .act/scripts/doctor.py"
    print(text, file=sys.stderr)
    _NOTE_FAILURES.append(text)


def _run_post_tool_use_notes(payload: dict) -> list[str]:
    """Every note module's text, in _POST_TOOL_USE_NOTES order, skipping None. A module that does
    not exist is reported like one that fails to load or raises while called: skipped, logged as one
    stderr line and kept in _NOTE_FAILURES for the report to the model and the human — never blocks,
    never corrupts the stdout JSON main() builds from the list this returns."""
    notes: list[str] = []
    timed = dict(payload, _act_hook_started=_HOOK_STARTED)  # the notes' waits stay inside the hook's own time
    for module_name, func_name in _POST_TOOL_USE_NOTES:
        func, reason = _load(module_name, func_name)
        if func is None:
            if reason is not None:
                _note_failed(module_name, reason)
            continue
        try:
            note = func(timed)
        except Exception as exc:  # noqa: BLE001 — a broken note must never block or corrupt the JSON
            _note_failed(module_name, f"{type(exc).__name__}: {exc}")
            continue
        if isinstance(note, str) and note:
            notes.append(note)
    return notes


def _emit_post_tool_use_notes(event: str, payload: dict, watch: "dict | None" = None,
                              queued: "list[str] | None" = None) -> None:
    """Shared by the "PostToolUse" and "PostToolUseFailure" branches of main(): run
    _POST_TOOL_USE_NOTES and, only if at least one note (or a watcher report, see
    _watch_protected_files) came back, print the single hookSpecificOutput JSON object both events use,
    with hookEventName set to whichever of the two this call is for (see this module's header, "Output
    format"). The watcher's report comes first; its message for the human rides along as the top-level
    systemMessage. After it come the check failures of this call's PreToolUse (`queued`, see
    _queue_failure_notes) and of the notes just run, for the model as context and for the human as the
    systemMessage; then the notes themselves."""
    notes = _run_post_tool_use_notes(payload)
    failures = list(queued or []) + _NOTE_FAILURES
    notes = failures + notes
    messages = ([watch["message"]] if watch and watch["message"] else []) + failures
    if watch:
        notes.insert(0, watch["context"])
    if notes:
        print(_post_tool_use_json(event, notes, "\n".join(messages)))


def _model_switch_failed(event: str, reason: str) -> None:
    """The model-switch report could not be made (module missing, raising, or its note not queued): one stderr
    line and the same text as a note for the orchestrator. A stop event has no channel to the human (Claude Code
    records a systemMessage of Stop/SubagentStop in the transcript without showing it) nor to the model that
    would not keep the agent running, so the text goes where the orchestrator's next tool call delivers it: the
    note queue of checks/protected_watch.py. The check-failure queue is not used: its key for a stop event is
    never read by a real PostToolUse. When the note queue itself fails, stderr is the last resort."""
    reason = " ".join(str(reason).split())[:_MAX_FAILURE_REASON]
    text = (f"[act] model-switch failed ({reason}) — a model change in this {event} may not have been reported; "
            "run .act/scripts/doctor.py")
    print(text, file=sys.stderr)
    try:
        from checks import protected_watch
        protected_watch.queue_orchestrator_note(str(_QUEUE_ROOT).replace("\\", "/"), text)
    except Exception:  # noqa: BLE001 -- a hook never ends in a traceback; stderr above is all that is left
        pass


def _model_switch_output(event: str, payload: dict) -> None:
    """Stop / SubagentStop: checks.model_switch reads the part of the transcript not read before and, on a
    refusal or a changed model, queues the note for the orchestrator (see that module). Prints nothing on
    stdout. A module that cannot be loaded, raises or cannot queue its note is reported by
    _model_switch_failed. Never raises, never blocks."""
    func, reason = _load("model_switch", "run")
    if func is None:
        if reason is not None:
            _model_switch_failed(event, reason)
        return
    try:
        func(event, payload)
    except Exception as exc:  # noqa: BLE001 -- a hook never ends in a traceback
        _model_switch_failed(event, f"{type(exc).__name__}: {exc}")


def _snapshot_protected_files(payload: dict) -> None:
    """SessionStart: the reference state for checks.protected_watch, taken after the session handler has
    refreshed the bridges (so its own writes are not reported as a change)."""
    try:
        from checks import protected_watch
        protected_watch.snapshot(session=payload.get("session_id"))
    except Exception as exc:  # noqa: BLE001
        print(f"[act] protected-watch snapshot skipped ({type(exc).__name__}: {exc})", file=sys.stderr)


def _run_worker_rules(part_arg: str) -> int:
    """`dispatch.py SubagentStart --worker-rules <i>`: one of the fixed SubagentStart hook entries
    (.act/bridges/settings.hooks.json) that hand a worker whose role says `omitClaudeMd: true`
    part <i> of the rules CLAUDE.md would have loaded (checks/worker_rules.py). Always returns 0 —
    SubagentStart blocks nothing, and a failure prints a fixed sentence instead (first entry only)."""
    try:
        part = int(part_arg)
    except ValueError:
        return 0
    try:
        payload = _read_payload()
        from checks import worker_rules
        worker_rules.emit(part, payload if isinstance(payload, dict) else {})
    except Exception:  # noqa: BLE001 — a missing or broken module must not break the worker start
        if part == 1:
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": (
                "Worker rules could not be assembled: read CLAUDE.md, docs/ai/rules.md and the files it "
                "imports from .act/rules/shared/ before your first step; skip .act/rules/orchestrator/.")}}))
    return 0


def _report_check_failures(payload: dict, held: str) -> None:
    """A PreToolUse call goes ahead although a check failed (it was skipped, see _check_failed): tell the
    human with a systemMessage now and leave the same text for this call's PostToolUse, which hands it to
    the model as additionalContext (_queue_failure_notes). `held` is what the checks printed meanwhile;
    it joins the message instead of standing in front of the JSON object. Nothing here can raise."""
    try:
        parts = ([held.strip()] if held.strip() else []) + list(_CHECK_FAILURES)
        print(json.dumps({"systemMessage": "\n".join(parts)}))
    except Exception as exc:  # noqa: BLE001 -- a hook never ends in a traceback
        print(f"[act] check failure not reported ({type(exc).__name__}: {exc})", file=sys.stderr)
        sys.stdout.write(held)
    _queue_failure_notes(payload, list(_CHECK_FAILURES))


def main(argv: list[str]) -> int:
    # "_update-check-worker" is the one exception to the "exactly one arg" harness contract
    # below: it is never a harness hook event, only what checks.session._spawn_update_check_
    # worker() launches (argv[1] is the project root as a string). Checked first so a stray
    # extra argv entry here can never fall through to "no event named".
    if len(argv) == 2 and argv[0] == "_update-check-worker":
        return _run_update_check_worker(Path(argv[1]))
    if len(argv) == 2 and argv[0] == "_act-local-tidy-worker":
        return _run_act_local_tidy_worker(Path(argv[1]))  # internal event, as above: the daily .act-local/ tidy
    if len(argv) >= 2 and argv[0] == "_security-scan-worker":
        # argv[1] the project root; optionally argv[2] a state hash and argv[3:] the lock files a
        # commit touches, for checks/deps_scan.py (see checks.session._run_security_scan_worker).
        # checks/deps_scan.py passes the list as one `@<list file>` argument instead, because a
        # long list overruns the Windows command-line limit.
        state_hash = argv[2] if len(argv) >= 3 else None
        if state_hash is not None and len(argv) == 4 and argv[3].startswith("@"):
            from checks import deps_scan as _deps_scan  # noqa: E402 -- only this worker needs it
            return _deps_scan.run_list_worker(Path(argv[1]), state_hash, Path(argv[3][1:]))
        return _run_security_scan_worker(Path(argv[1]), state_hash, [Path(arg) for arg in argv[3:]])

    if len(argv) == 3 and argv[0] == "SubagentStart" and argv[1] == "--worker-rules":
        return _run_worker_rules(argv[2])

    if len(argv) != 1:
        return 0  # no event named — nothing to dispatch, never an error for the caller

    event = argv[0]
    payload = _early_payload if _early_payload is not None else _read_payload()

    if event == "PreToolUse":
        # Checks run first, observers second — the reverse of every other event, and
        # the reverse of this module's own order before this fix. See _run_pre_tool_use_observers'
        # own docstring for why a denied call must never reach a counting observer at all.
        # What the checks and observers print on stdout is held back: a call that goes ahead with a failed check
        # prints one JSON object (the failure report), and plain text in front of it would make it unreadable.
        import io
        real_stdout = sys.stdout
        held = io.StringIO()
        sys.stdout = held
        try:
            result, denied_by = _run_checks(payload)
            _run_pre_tool_use_observers(payload, denied=(result != 0), denied_by=denied_by)
        finally:
            sys.stdout = real_stdout
        if result == 0 and _CHECK_FAILURES:
            _report_check_failures(payload, held.getvalue())
        elif held.getvalue():
            sys.stdout.write(held.getvalue())
        return result

    if event == "UserPromptSubmit":
        _run_observers_merged(event, payload)
    else:
        _run_observers(event, payload)
    if event in ("PostToolUse", "PostToolUseFailure"):
        # PostToolUse was watched in the early block above (when it came through there), the failure event is not
        watch = _early_watch if _early_payload is not None else _watch_protected_files(event, payload)
        queued = _early_failures if _early_payload is not None else _take_failure_notes(payload)
        _emit_post_tool_use_notes(event, payload, watch, queued)
        return 0  # notes never block
    if event == "SessionStart":
        code = refresh_session(payload)
        _snapshot_protected_files(payload)
        return code
    if event in ("SubagentStop", "Stop"):
        _model_switch_output(event, payload)
        return 0
    return 0  # any other event (SubagentStart, UserPromptSubmit, ...) only feeds the observers


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
