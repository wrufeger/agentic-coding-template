#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Observer for the template's local usage counter (T41). This module only turns hook
#          events into tiny, one-shot event files — the schema, the consolidation step that folds
#          them into .act-local/usage.json, and the CLI (--show/--outcome/--unused/--reset) all
#          live in .act/scripts/usage.py; read that file's header first. Registered in
#          dispatch.py's _OBSERVERS as ("usage", "observe"): observe() runs for every hook event,
#          before any PreToolUse check, and must never raise or block (dispatch.py's
#          _run_observers already swallows an observer's exception, but this stays fast on its
#          own — writing one small file is O(1), no read-modify-write of shared state happens
#          here at all, see the concurrency note below).
#
# What is counted here, and from which event (dispatch.py's own docstring lists the wired events):
#   - a worker start, by role/tier/model: PreToolUse, tool_name "Agent"/"Task"
#     (checks.common._WORKER_TOOL_NAMES), *no* agent_id in the payload (the orchestrator's own
#     call, not a nested one — checks.common._is_worker), tool_input.subagent_type present.
#     Deliberately NOT keyed off SubagentStart's own agent_type instead: the brief line
#     "subagent_type from the orchestrator's Agent call, or agent_type at SubagentStart" offers
#     either signal for the same start, and only the PreToolUse call also carries the tier
#     ("Tier: ..." in tool_input.prompt) and the model (tool_input.model) that SubagentStart's own
#     payload does not — so using it alone avoids correlating two separate events (no queue, no
#     race between an Agent/Task call and its own SubagentStart, unlike checks/write_scope.py's
#     tool_use_id -> meta.json binding, which exists only because a *worker's own later* call has
#     no other way back to its assignment). This also gives "helper agents without agent_type
#     don't count" for free: an internal helper agent of the harness (empty agent_type, SubagentStop only, no
#     prior SubagentStart or Agent/Task call — confirmed in both 2026-09-23 live-probe captures,
#     see the brief) never reaches this branch at all, since it was never started through the
#     Agent/Task tool in the first place.
#   - a skill call: PreToolUse, tool_name "Skill", tool_input.skill.
#   - a slash command: UserPromptSubmit, payload.prompt starting with "/<name>" (the same field
#     .claude/scripts/ai-log.py's --hook mode reads for its own "[user] [prompt]" line).
#   - a script call: PreToolUse, tool_name "Bash"/"PowerShell" (checks.common._SHELL_TOOL_NAMES),
#     command containing ".act/scripts/<name>.py".
#   - a checklist read: PreToolUse, tool_name "Read", file_path under ".act/checklists/" or
#     "docs/ai/local/checklists/".
#   Cap hits and denials inside a PreToolUse *check* (worker-cap, status-poll, ...) cannot be seen
#   here — this observer runs before the checks (dispatch.py's fixed order). A check that wants
#   one counted calls usage.record(kind, key) itself instead — see that function's docstring in
#   .act/scripts/usage.py for the one line a check needs.
#   - SessionStart: no recording of its own — triggers usage.consolidate_at_session_start(), the
#     one place .act-local/usage/events/ actually shrinks again (2026-09-23 review, point 1: it
#     only ever grew otherwise). Budgeted, see that function's own docstring.
#
# Known limit (2026-09-23 review, point 4): this observer sees a PreToolUse *before* any check
# runs (dispatch.py's own fixed order), so a role start, skill call, script call or checklist read
# is counted here even when a later check in the chain denies it (worker-cap, write-scope,
# nesting-guard, ...) — a denied attempt looks the same as a successful one in usage.json. Not
# fixed: dispatch.py would have to run the observers *after* the checks to tell them apart, which
# would also delay every check by the observer's own (small but nonzero) cost, and a check that
# specifically wants its own denials counted already has usage.record() for that (see above) — it
# is the "checks" category, not "roles"/"skills"/..., that is meant to hold rejection counts.
#
# Concurrency: many dispatch.py processes can run at once — parallel worker tool calls fire their
# own PreToolUse hooks concurrently (CLAUDE.md § Logging: only the Agent-call/SubagentStart/-Stop
# hooks are synchronous, all other events async). A shared counter in memory is not an
# option (separate processes), and a single shared JSON file updated read-modify-write per event
# would lose updates under that concurrency — the same failure mode checks/write_scope.py's own
# docstring documents for a single shared scope file (t26_race.py, 2026-09-23 review: 8 parallel
# writers, up to 6 of 8 lost under a naive single-file scheme). This module therefore never opens
# .act-local/usage.json itself — every call below goes through usage.record_event(), which gives
# each occurrence its own uniquely named file (mkstemp + os.replace, the same atomic-rename
# pattern write_scope.py uses for its per-worker scope files), so N parallel occurrences produce N
# files with no shared state to race over. Folding those files into the single usage.json is left
# to usage.py's own consolidation step, run by its CLI (--show/--outcome/--unused) — see that
# file's header for why concurrency is low there (normally only the orchestrator calls it).

from __future__ import annotations

import re

import actlib
import usage

from .common import _SHELL_TOOL_NAMES, _WORKER_TOOL_NAMES, _is_harness_message

__all__ = [
    "_TIER_RE", "_SCRIPT_CALL_RE", "_CHECKLIST_PATH_RE", "_SLASH_COMMAND_TOKEN_RE",
    "_COMMAND_NAME_RE", "_FORK_SUBAGENT_TYPE", "_tier_from_prompt", "_slash_command", "observe",
]

# "Tier: <value>" — first match, stopping at whitespace or a separator/punctuation character so
# "Tier: light." and "Tier: standard · Estimate: ..." both yield a bare value ("light",
# "standard"). Lower-cased on capture (see _tier_from_prompt) so "Tier: Standard" and
# "Tier: standard" land in the same usage.json bucket instead of splitting the count.
_TIER_RE = re.compile(r"Tier:\s*([^\s.,;·]+)", re.IGNORECASE)

# ".act/scripts/<name>.py" run *through an interpreter* — either a literal "python"/"python3"/"py"
# (optionally ".exe") or a shell variable holding a resolved interpreter path, the pattern
# .act/bridges/settings.hooks.json's own wiring uses for dispatch.py (`"$P" .act/hooks/dispatch.py
# ...`; 2026-09-23 review point 2's own ask: check that a script invoked this way from a skill/hook
# still counts). Interpreter flags ("-u", ...) between the interpreter and the path are tolerated.
# Without the interpreter requirement, merely *reading* the script (`sed -n 1,40p
# .act/scripts/feedback.py`, `grep -n x .act/scripts/log.py`) used to count as a call too (review
# point 2) — it no longer does, since neither "sed"/"grep" nor the line/pattern arguments in front
# of the path match either interpreter alternative. Known looseness, accepted: the variable branch
# matches *any* "$NAME"/"${NAME}" right before a script path, not only one that actually holds an
# interpreter (e.g. `echo $P .act/scripts/x.py` still counts) — narrower than that would miss the
# legitimate "$P .act/scripts/x.py" forms the review explicitly asked to catch, and a stray `echo`
# of a script path is a rare, harmless over-count for a nudge counter.
_SCRIPT_CALL_RE = re.compile(
    r'(?:(?:python3?|py)(?:\.exe)?|"?\$\{?[A-Za-z_][A-Za-z0-9_]*\}?"?)'
    r'\s+(?:-\S+\s+)*["\']?[^\s"\']*\.act[/\\]scripts[/\\](\w[\w-]*)\.py'
)

# A Read target under .act/checklists/ or docs/ai/local/checklists/ (see actlib.resolve — a
# checklist may live in either place, project override first). Either path separator, anchored at
# the end so only the checklist's own file counts, not something merely nested under that
# directory.
_CHECKLIST_PATH_RE = re.compile(
    r"(?:^|[/\\])(?:\.act[/\\]checklists|docs[/\\]ai[/\\]local[/\\]checklists)"
    r"[/\\]([A-Za-z0-9_-]+)\.md$"
)

# A prompt that starts with "/<name>" — a slash command, built-in or one of this template's own
# (.claude/skills/act-*, plus the unprefixed short forms /commit, /idea, /prepare,
# /update-template). No allow-list here: whatever word follows the slash is the key recorded, as
# long as that *entire* first token matches lower-case letters/digits plus ":_-" (every real
# command name here is lower-case; ":" for a plugin-qualified name like "anthropic-skills:docx") —
# this keeps a prompt that merely opens with a filesystem path ("/Users/alex/secret-project/
# notes.md please read", "/tmp/x.log ...") from being misread as a command (2026-09-23 review,
# point 4). Matched in two steps rather than one pattern with a `(?!/)` lookahead right after the
# char class: a lookahead there only rejects a match that runs all the way to the "/" — regex
# backtracking then just retries with a *shorter* prefix that avoids the "/" instead of failing
# outright (a first, broken attempt at this fix let "/tmp/x.log ..." through as command "tm",
# backtracked off the trailing "p" precisely to dodge the "/" in "tmp/x.log"). Validating the
# *whole* first whitespace-delimited token against the charset, after extracting it greedily with
# `\S+`, has no such backtracking path to a wrong-but-technically-matching answer.
_SLASH_COMMAND_TOKEN_RE = re.compile(r"^\s*/(\S+)")
_COMMAND_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9:_-]*$")


def _slash_command(prompt: str) -> "str | None":
    match = _SLASH_COMMAND_TOKEN_RE.match(prompt)
    if not match:
        return None
    token = match.group(1)
    return token if _COMMAND_NAME_RE.match(token) else None


# subagent_type "fork" (context: fork) is deliberately not counted as a role start at all — not
# given its own key either (2026-09-23 review, point 3: "own key or leave it out —
# justify it"). Reasoning: the roles.<name>.tiers/models/outcomes breakdown feeds the per-role/tier
# proposal (a local inbox entry; only the pattern, never these numbers, goes out via Feedback) — a "role" there is a
# choice from .act/agents/*.md's tier table (builder, reviewer, explorer, ...), each with its own
# tier/model. A fork always inherits the parent's own model verbatim (Agent tool docs: "the fork
# runs on your model — a model override is ignored") and is not a role selection at all, so
# recording it under "roles" would mix a concept with no tier of its own into a table meant to
# compare tiers *between* roles, and a dedicated "fork" key would still need its own tier/model
# semantics invented for a case where neither ever varies — not useful enough to carry.
_FORK_SUBAGENT_TYPE = "fork"


def _tier_from_prompt(prompt: str) -> str:
    match = _TIER_RE.search(prompt)
    return match.group(1).lower() if match else ""


def observe(event: str, payload: dict) -> None:
    """Called by dispatch.py for every hook event, before any check runs. See this module's
    docstring for what is recorded from which event; anything else is a silent no-op."""
    try:
        root = actlib.repo_root()
    except RuntimeError:
        return  # not inside a template-managed project — nothing to count

    if event == "PreToolUse":
        _observe_pre_tool_use(root, payload)
    elif event == "UserPromptSubmit":
        _observe_user_prompt(root, payload)
    elif event == "SessionStart":
        usage.consolidate_at_session_start(root)


def _observe_pre_tool_use(root, payload: dict) -> None:
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        return

    if tool_name in _WORKER_TOOL_NAMES:
        if payload.get("agent_id"):
            return  # a worker starting a further sub-agent — nesting_guard's concern, not ours
        subagent_type = tool_input.get("subagent_type")
        if not isinstance(subagent_type, str) or not subagent_type:
            # Agent tool docs: omitting subagent_type starts a fresh general-purpose agent — that
            # is still a real worker start, just an unnamed one (2026-09-23 review, point 3).
            subagent_type = "general-purpose"
        if subagent_type == _FORK_SUBAGENT_TYPE:
            # a fork is the caller's own session continuing, not a role choice — see
            # _FORK_SUBAGENT_TYPE's own comment above for why it is omitted, not given a key
            return
        prompt = tool_input.get("prompt")
        tier = _tier_from_prompt(prompt) if isinstance(prompt, str) else ""
        model = tool_input.get("model")
        model = model if isinstance(model, str) and model else ""
        usage.record_event(root, "roles", subagent_type, tier=tier, model=model)
        return

    if tool_name == "Skill":
        skill = tool_input.get("skill")
        if isinstance(skill, str) and skill:
            usage.record_event(root, "skills", skill)
        return

    if tool_name in _SHELL_TOOL_NAMES:
        command = tool_input.get("command")
        if isinstance(command, str):
            for name in _SCRIPT_CALL_RE.findall(command):
                usage.record_event(root, "scripts", name)
        return

    if tool_name == "Read":
        file_path = tool_input.get("file_path")
        if isinstance(file_path, str):
            match = _CHECKLIST_PATH_RE.search(file_path)
            if match:
                usage.record_event(root, "checklists", match.group(1))


def _observe_user_prompt(root, payload: dict) -> None:
    prompt = payload.get("prompt")
    if not isinstance(prompt, str):
        return
    if _is_harness_message(prompt):
        # A worker's report or a task-finished notice never starts with "/" anyway (it opens with
        # "<...", T44 live probe), so _slash_command already falls through to None below without
        # this — kept explicit rather than relying on that shape, the same defense-in-depth
        # checks.event_log/checks.tips apply for the same payload field (2026-09-23).
        return
    command = _slash_command(prompt)
    if command:
        usage.record_event(root, "commands", command)
