#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Quick capture for the synchronous "UserPromptSubmit --act-check" hook (dispatch.py): a chat
#          message that starts with `todo:`, `note:` or `idea:` is filed without a model turn.
#            todo: -> inbox entry (kind: todo, for: <own identity>, status: open, triage: open)
#            note: -> inbox entry (kind: note, for: <own identity>, status: open, triage: open)
#            idea: -> new `## <title>` section at the end of docs/ai/concept/ideas-<identity>.md
#          Every further line that starts with a prefix opens another entry; lines in between belong
#          to the entry above. Text before the first prefix means: no capture, the message goes on
#          to the model unchanged. dispatch.py checks the cheap prefix pattern (PREFIX_START_RE) on
#          the raw prompt before it imports this module, so a normal prompt never pays for it.
#
#          capture() returns the text for the hook's {"decision": "block", "reason": ...} answer, or
#          None for "let the prompt through": a worker's payload, a harness message, `quick-capture:
#          off` in docs/ai/config.md (a missing key means on), no identity, no entry with text, or
#          every entry failing to file. Nothing here raises. When some entries were filed and others
#          failed, the reason lists the filed ones, then each failure with its text verbatim, so
#          the message is never lost and nothing is filed twice.

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

from .common import _is_harness_message

__all__ = ["PREFIX_START_RE", "parse_entries", "short_title", "capture"]

# Cheap test dispatch.py applies to the raw prompt: the first non-blank line starts with a prefix.
PREFIX_START_RE = re.compile(r"\s*(?:todo|note|idea):", re.IGNORECASE)
_LINE_PREFIX_RE = re.compile(r"[ \t]*(todo|note|idea):[ \t]*", re.IGNORECASE)
_TITLE_WIDTH = 60
# Seconds to wait for entries.lock per entry: the hook's own limit is 10 s for the whole message.
_LOCK_WAIT = 1.5
_HELP_LINE = ("undo: delete the file (or section) and resend without the prefix; "
              "switch off: quick-capture: off in docs/ai/config.md")


def parse_entries(prompt: str) -> list[tuple[str, str]]:
    """(kind, text) per entry, kind in todo|note|idea. A line with a prefix opens an entry; the
    other lines belong to the entry above, verbatim. [] when text stands before the first prefix.
    Entries without any text are dropped."""
    entries: list[tuple[str, list[str]]] = []
    for line in prompt.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        match = _LINE_PREFIX_RE.match(line)
        if match:
            entries.append((match.group(1).lower(), [line[match.end():]]))
        elif entries:
            entries[-1][1].append(line)
        elif line.strip():
            return []  # text before the first prefix: not a capture
    result: list[tuple[str, str]] = []
    for kind, lines in entries:
        text = "\n".join(lines).strip("\n").rstrip()
        if text.strip():
            result.append((kind, text))
    return result


def short_title(text: str) -> str:
    """First non-empty line of `text`, cut at a word boundary to about 60 characters."""
    first = next((line.strip() for line in text.split("\n") if line.strip()), "")
    if len(first) <= _TITLE_WIDTH:
        return first
    cut = first[:_TITLE_WIDTH + 1]
    space = cut.rfind(" ")
    return (cut[:space] if space > _TITLE_WIDTH // 2 else first[:_TITLE_WIDTH]).rstrip(" ,;:-")


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def capture(root: Path, payload: dict) -> Optional[str]:
    """File every prefixed entry of payload["prompt"]; the reason text to show, or None."""
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or payload.get("agent_id") or _is_harness_message(prompt):
        return None
    try:
        import actlib
        import entries
        import ideas

        if actlib.read_config(root).get("quick-capture", "on").strip().strip("`").lower() == "off":
            return None
        parsed = parse_entries(prompt)
        identity = ideas.identity(root)
        if not parsed or not identity:
            return None
        lines: list[str] = []
        failed: list[str] = []
        for kind, text in parsed:
            try:
                title = short_title(text)
                # A one-line entry is its own title; repeating it as the body adds nothing.
                body = "" if text.strip() == title else text
                if kind == "idea":
                    path = ideas.append_section(root, title, body)
                    lines.append(f"[act] captured idea -> {_rel(root, path)}")
                    continue
                path, entry_id = entries.create_entry(
                    root, kind, title, recipient=identity, body=f"{body}\n" if body else "",
                    extra_header=[("triage", "open")], lock_timeout=_LOCK_WAIT)
                label = f"{kind} {entry_id}" if entry_id else kind
                lines.append(f"[act] captured {label} -> {_rel(root, path)} (triage pending)")
            except Exception as exc:  # one failed entry must not hide the ones already filed
                print(f"[act] quick-capture: filing {kind} failed ({exc!r})", file=sys.stderr)
                failed.append(f"[act] filing failed for {kind}: {exc}\n{text}")
        if not lines:
            return None  # nothing filed: the message goes through to the model unchanged
        lines.extend(failed)
        lines.append(_HELP_LINE)
        return "\n".join(lines)
    except Exception as exc:  # a failure to file must never eat the user's message
        print(f"[act] quick-capture: filing failed, message passed through ({exc!r})", file=sys.stderr)
        return None
