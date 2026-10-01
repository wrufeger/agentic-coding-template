#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Observer for the "logging" topic (docs/ai/config.md § Logging, .act/rules/topics/
#          logging.md) — turns every hook event dispatch.py sees into at most one line in ai.log,
#          via .act/scripts/log.py's write_line() and its per-session label numbering
#          (start_subagent_label/lookup_subagent_label). Registered in dispatch.py's _OBSERVERS
#          as ("event_log", "observe"); called for every event, before any PreToolUse check runs,
#          and must never raise (dispatch.py swallows the call in a try/except, but a bug here
#          should still fail silently and cheaply rather than rely on that net).
#
#          With `logging` set to "off" (the skeleton's default), observe() returns immediately —
#          no file is opened, no state is touched, see log.load_config()/write_line().
#
#          Sub-agent numbering ("builder#1", "builder#2", ...) comes from SubagentStart, recorded
#          under the payload's agent_id; SubagentStop looks that label back up. The harness also
#          fires SubagentStop for its own internal helper agents, which never got a SubagentStart
#          this template ever saw and carry an empty agent_type (2026-09-23 live probe,
#          a live probe capture's payloads.jsonl: 10 SubagentStop lines,
#          3 with a non-empty agent_type and a matching prior SubagentStart, 7 without) — both are
#          filtered out below rather than logged as a numberless "[end]" line.
#
#          A SubagentHandback tool call is a worker reporting back to its caller, not a nested
#          delegation; at DEBUG it is logged like any other tool call. Payload facts this reads
#          (2026-09-23 live probe; checks/write_scope.py's own module docstring records the same
#          facts for its own caller): PreToolUse for "Agent"/"Task" carries tool_use_id and
#          tool_input.prompt; every worker call carries agent_id/agent_type, the orchestrator's
#          own calls carry neither.
#
#          PreToolUse denial: dispatch.py now runs its PreToolUse observers
#          *after* the checks (see dispatch.py's own header and
#          dispatch._run_pre_tool_use_observers), so this module is the only observer still called
#          for a call one of the checks denied — with payload["_act_denied"] = True and, when
#          dispatch.py knows it, payload["_act_denied_by"] = "<check module name>" (e.g.
#          "encoding_hint") set on that call. This module logs that case as its own "denied" line,
#          naming the denying check (or "check" as a fallback when _act_denied_by is missing — a
#          call still denied should never be logged as if nothing happened just because the name
#          did not make it through), at WARN (review finding 5: a block is a rule actually stopping
#          the assistant, closer in severity to the ERROR "failed" line than to an ordinary INFO
#          status line) instead of the usual "delegate" line or the DEBUG-gated "tool" one — a plain
#          call gets its normal treatment, but a denial is never buried behind DEBUG the way an
#          ordinary tool call is (R-safe-block: every block is logged, even a harmless one); it
#          still respects the project's own `log-level` floor the same way every other line here
#          does (only ERROR now suppresses it, same as it would the "delegate" line).

from __future__ import annotations

import re
import time
from typing import Optional

import log

from .common import _is_harness_message

__all__ = [
    "_strip_plugin_prefix", "_clean_agent_type", "_first_str", "_short_arg_for_tool",
    "_resolve_label", "_TASK_NOTIFICATION_STATUS_RE", "_TASK_NOTIFICATION_SUMMARY_RE",
    "_harness_message_summary", "observe",
]

# <task-notification>'s own child elements (see checks.common._HARNESS_MESSAGE_PREFIXES's
# docstring for a real captured sample) — DOTALL because <summary> can in principle wrap, though
# every sample seen so far kept it on one line.
_TASK_NOTIFICATION_STATUS_RE = re.compile(r"<status>(.*?)</status>", re.DOTALL)
_TASK_NOTIFICATION_SUMMARY_RE = re.compile(r"<summary>(.*?)</summary>", re.DOTALL)
_OPENING_TAG_RE = re.compile(r"^<([a-zA-Z-]+)")


def _harness_message_summary(prompt: str) -> str:
    """The text logged for a harness-fed UserPromptSubmit (see checks.common._is_harness_message)
    instead of the raw prompt — write_line()/clean_text() still normalize whitespace and cut to
    the usual 200-char budget on top of this, so nothing here needs to enforce that itself.

    <task-notification>'s own body is a worker's entire final report, repeated in full nowhere
    here on purpose: that text already gets its own [end] line the moment the same worker's
    SubagentStop fires (this module's own SubagentStop branch) — logging it a second time, cut off
    mid-sentence at 200 characters, would just be noise. Only the two child elements that carry the
    outcome without the body — <status> and <summary> — are kept. Every other harness tag
    (agent-message, cross-session-message, system-reminder) keeps its full text, tagged with its
    own element name, same as any other logged text."""
    stripped = prompt.lstrip()
    if stripped.startswith("<task-notification"):
        status_match = _TASK_NOTIFICATION_STATUS_RE.search(stripped)
        summary_match = _TASK_NOTIFICATION_SUMMARY_RE.search(stripped)
        parts = [
            m.group(1).strip() for m in (status_match, summary_match) if m and m.group(1).strip()
        ]
        return "task-notification: " + " · ".join(parts) if parts else "task-notification"
    tag_match = _OPENING_TAG_RE.match(stripped)
    tag = tag_match.group(1) if tag_match else "harness-message"
    return f"{tag}: {stripped}"


def _strip_plugin_prefix(name) -> str:
    """"myplugin:builder" -> "builder" — a sub-agent type can carry a plugin prefix; the label
    numbering and the log line should read the bare role name either way."""
    name = str(name or "")
    return name.split(":", 1)[1] if ":" in name else name


def _clean_agent_type(payload: dict) -> str:
    return _strip_plugin_prefix(payload.get("agent_type") or "")


def _first_str(source: dict, keys) -> Optional[str]:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _short_arg_for_tool(tool_name: str, tool_input: dict) -> str:
    """A short "what did it touch" for a DEBUG [tool] line — the one field that best names the
    call's target, per tool; falls back to the first non-empty string argument for a tool this
    does not specifically know."""
    if tool_name == "Bash" or tool_name == "PowerShell":
        value = tool_input.get("command", "")
    elif tool_name in ("Read", "Edit", "MultiEdit", "Write"):
        value = tool_input.get("file_path", "")
    elif tool_name == "NotebookEdit":
        value = tool_input.get("notebook_path") or tool_input.get("file_path") or ""
    elif tool_name in ("Glob", "Grep"):
        pattern = tool_input.get("pattern", "")
        path = tool_input.get("path")
        value = f"{pattern} path={path}" if path else pattern
    elif tool_name == "Skill":
        value = tool_input.get("skill", "")
    elif tool_name == "WebFetch":
        value = tool_input.get("url", "")
    else:
        value = ""
        for candidate in tool_input.values():
            if isinstance(candidate, str) and candidate:
                value = candidate
                break
    return log.clean_text(value, limit=120)


def _resolve_label(cfg: dict, payload: dict, session_id, agent_id, now: float) -> str:
    """The label a log line should carry: "orchestrator" for a call with no agent_id, the
    numbered label a prior SubagentStart recorded for `agent_id` if one exists, else the bare
    (plugin-prefix-stripped) agent_type from this payload, else "subagent" as a last resort — a
    tool call from a worker whose own SubagentStart this session never logged (e.g. logging was
    just switched on) still gets *a* readable label instead of being dropped."""
    if not agent_id:
        return "orchestrator"
    label = log.lookup_subagent_label(cfg["root"], session_id, agent_id, now=now)
    if label:
        return label
    return _clean_agent_type(payload) or "subagent"


def observe(event: str, payload: dict) -> None:
    cfg = log.load_config()
    if not cfg["enabled"]:
        return

    root = cfg["root"]
    session_id = payload.get("session_id")
    agent_id = payload.get("agent_id")
    now = time.time()

    if event == "UserPromptSubmit":
        prompt = payload.get("prompt", "")
        if _is_harness_message(prompt):
            # A worker's report, a task-finished notice, or similar — fed in by the harness
            # itself, not typed by the user (checks.common._is_harness_message). Logged as a
            # system result, never as "[user] [prompt]" — see _harness_message_summary for what
            # each tag keeps.
            log.write_line(cfg, "INFO", "system", "result", _harness_message_summary(prompt))
            return
        log.write_line(cfg, "INFO", "user", "prompt", prompt)
        return

    if event == "PreToolUse":
        tool_name = payload.get("tool_name")
        tool_input = payload.get("tool_input")
        tool_input = tool_input if isinstance(tool_input, dict) else {}

        if payload.get("_act_denied") is True:
            # A check denied this call (dispatch.py's own PreToolUse observer ordering — see this
            # module's docstring) — logged as its own "denied" line at WARN (review finding 5),
            # well below the project's default INFO floor, so a reader who never raised log-level
            # still sees it (R-safe-block), even though it would otherwise have been an unremarkable
            # DEBUG "tool" line. Names the denying check (dispatch._run_checks' own module name,
            # passed through as _act_denied_by) so the line answers "denied by what", not only
            # "denied".
            label = _resolve_label(cfg, payload, session_id, agent_id, now)
            arg = _short_arg_for_tool(str(tool_name), tool_input)
            denied_by = payload.get("_act_denied_by") or "check"
            log.write_line(cfg, "WARN", label, "denied", f"{denied_by}: {tool_name} {arg}")
            return

        if tool_name in ("Agent", "Task") and not agent_id:
            # Only the orchestrator's own delegation calls — a worker attempting this is a
            # different rule's concern (checks/nesting_guard.py), not something this topic logs
            # under its own name.
            subagent_type = _strip_plugin_prefix(tool_input.get("subagent_type")) or "general-purpose"
            assignment = _first_str(tool_input, ("description", "prompt", "name")) or ""
            log.write_line(cfg, "INFO", "orchestrator", "delegate", f"{subagent_type} <- {assignment}")
            return

        if log._level_ok("DEBUG", cfg["level"]):
            label = _resolve_label(cfg, payload, session_id, agent_id, now)
            arg = _short_arg_for_tool(str(tool_name), tool_input)
            log.write_line(cfg, "DEBUG", label, "tool", f"{tool_name} {arg}")
        return

    if event == "SubagentStart":
        agent_type = _clean_agent_type(payload) or "subagent"
        label = log.start_subagent_label(root, session_id, agent_type, agent_id, now=now)
        log.write_line(cfg, "INFO", label, "start", "started")
        return

    if event == "SubagentStop":
        # Filter: only an agent this template itself started and numbered gets an [end] line —
        # see the module docstring for why the harness's own internal helper-agent stops (empty
        # agent_type, no matching SubagentStart) are silently dropped here.
        if not payload.get("agent_type") or not agent_id:
            return
        label = log.lookup_subagent_label(root, session_id, agent_id, now=now)
        if label is None:
            return
        last_message = payload.get("last_assistant_message")
        text = last_message if isinstance(last_message, str) and last_message else "ended"
        log.write_line(cfg, "INFO", label, "end", text)
        return

    if event in ("SessionStart", "SessionEnd"):
        detail_key = "source" if event == "SessionStart" else "reason"
        detail = payload.get(detail_key)
        text = ("start" if event == "SessionStart" else "ended") + (f" \u00b7 {detail_key}={detail}" if detail else "")
        log.write_line(cfg, "INFO", "orchestrator", "session", text)
        return

    if event == "PostToolUseFailure":
        label = _resolve_label(cfg, payload, session_id, agent_id, now)
        tool_name = payload.get("tool_name", "")
        error = _first_str(payload, ("error", "message"))
        if error is None:
            response = payload.get("tool_response")
            error = response if isinstance(response, str) else ""
        log.write_line(cfg, "ERROR", label, "error", f"{tool_name} failed \u00b7 {error}")
        return

    if event == "Notification":
        # No live payload sample for this event was available while this was built (see the
        # accompanying report) — field names are carried over from the template's predecessor
        # script (.claude/scripts/ai-log.py) rather than confirmed against a real capture.
        kind = _first_str(payload, ("notification_type", "type", "matcher")) or ""
        message = payload.get("message", "")
        if kind == "permission_prompt" or re.search(r"permission", kind, re.IGNORECASE):
            log.write_line(cfg, "INFO", "system", "session", f"waiting for approval \u00b7 {message}")
        elif log._level_ok("DEBUG", cfg["level"]):
            log.write_line(cfg, "DEBUG", "system", "session", f"{kind} \u00b7 {message}")
        return
