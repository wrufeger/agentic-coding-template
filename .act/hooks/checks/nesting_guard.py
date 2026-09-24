#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check 1b — no sub-sub-agents (R-role-worker, PreToolUse).
#
# A role's own `tools` frontmatter never lists "Agent"/"Task" (.act/agents/README.md) — this is
# the mechanical backstop for that rule: a PreToolUse call to either tool whose payload carries an
# "agent_id" did not come from the orchestrator (the harness stamps every sub-agent's own tool
# calls with its agent_id; the main session's calls carry none — confirmed 2026-09-23 against a
# real Claude Code run's payload capture, a live probe capture's
# payloads.jsonl: every PreToolUse fired from inside a spawned sub-agent carries "agent_id", the
# orchestrator's own PreToolUse for "Agent" does not). Denied regardless of what a role's own
# tools list says, since a hand-edited role bridge could otherwise re-add the tool.
#
# The same probe also shows the guard's live blind spot: the sub-agent it spawned (role
# quick-check, tools Read/Grep/Glob/Bash/SubagentHandback) never got the "Agent"/"Task" tool at
# all, so no PreToolUse for either ever fired to test the guard against — the *payload field* this
# guard relies on is confirmed, the guard's own denial path was not exercised live. The nesting
# guard's Bash-level escape-hatch check (`claude -p`/`--print`) is unaffected by that, since Bash
# was in the sub-agent's tool list.
#
# The same guard also catches the CLI-level escape hatch: a sub-agent that cannot call
# Agent/Task directly can still reach for `claude -p "..."` (or `--print`) via Bash to spawn an
# unsupervised second harness instance. Same test (agent_id present -> not the orchestrator),
# same verdict. Known gap, not fixable from this payload alone: a skill invoked with
# `context: fork` runs as its own harness call, indistinguishable here from an ordinary
# sub-agent Bash call — this guard cannot see the difference and does not try to.

from __future__ import annotations

import re
import sys

import actlib

from .common import _WORKER_TOOL_NAMES, _check_mode

__all__ = [
    "_WORKER_NESTING_MESSAGE", "_CLAUDE_PRINT_MESSAGE", "_bash_starts_claude_print",
    "_SHELL_SEP_RE", "_CLAUDE_COMMAND_WORD_RE", "_PRINT_FLAG_RE",
    "check_worker_nesting_guard",
]

_WORKER_NESTING_MESSAGE = (
    "[act] only the orchestrator starts workers — return a split proposal instead"
)
_CLAUDE_PRINT_MESSAGE = (
    "[act] only the orchestrator starts workers — no `claude -p`/--print from inside a sub-agent"
)

# Segment a shell command on the operators that start a new command (&&, ||, ;, |, &, newline),
# so a `claude -p` buried after an unrelated first command (e.g. `cd x && claude -p "y"`) is
# still caught, without needing a real shell parser.
_SHELL_SEP_RE = re.compile(r"&&|\|\||[;&|\n]")
# "claude" as the *command* of a segment, not merely a word appearing in it (so `echo claude -p`
# stays allowed): after leading whitespace, an optional path prefix (`/usr/local/bin/claude`,
# `./claude`) and/or a leading `npx`/its flags (`npx claude -p`, `npx -y claude -p`), "claude"
# (optionally .exe/.cmd on Windows) must be the next token, followed by whitespace or the end of
# the segment — that trailing boundary is what excludes "claude-code"/"claude.md" as a
# substring match.
_CLAUDE_COMMAND_WORD_RE = re.compile(
    r"^\s*(?:(?:npx|-{1,2}\S+)\s+)*(?:[\w./\\~-]*[/\\])?claude(?:\.exe|\.cmd)?(?=\s|$)"
)
_PRINT_FLAG_RE = re.compile(r"(?:^|\s)(?:-p|--print)(?:[\s=]|$)")


def _bash_starts_claude_print(command: str) -> bool:
    """True if some segment of `command` runs the `claude` CLI with -p/--print — the print-mode
    invocation that runs one prompt to completion and exits, usable to spawn an unsupervised
    second harness instance from inside a sub-agent. See the comment above _WORKER_TOOL_NAMES
    for the known gap (a `context: fork` skill is not detectable this way)."""
    for segment in _SHELL_SEP_RE.split(command):
        if _CLAUDE_COMMAND_WORD_RE.search(segment) and _PRINT_FLAG_RE.search(segment):
            return True
    return False


def check_worker_nesting_guard(payload: dict) -> int:
    """Check 1b: deny a sub-agent starting a further sub-agent, directly (Agent/Task) or via the
    `claude -p` CLI escape hatch (Bash). See dispatch.py's docstring for why PreToolUse checks
    fail closed rather than open where a mechanism error occurs."""
    config = actlib.read_config()
    mode = _check_mode(config, "worker-nesting-guard", default="block")
    if mode == "off":
        return 0

    if not payload.get("agent_id"):
        return 0  # the orchestrator's own call — never stamped with an agent_id

    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    message: str | None = None
    if tool_name in _WORKER_TOOL_NAMES:
        message = _WORKER_NESTING_MESSAGE
    elif tool_name == "Bash" and isinstance(tool_input, dict):
        command = tool_input.get("command")
        if isinstance(command, str) and _bash_starts_claude_print(command):
            message = _CLAUDE_PRINT_MESSAGE

    if message is None:
        return 0

    if mode == "warn":
        print(message)
        return 0

    print(message, file=sys.stderr)
    return 2
