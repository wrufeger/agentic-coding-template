#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Context size of the running Claude Code session, for the status line ("ctx 127k") and
#          for the one-time /clear hint (checks/context_hint.py). Every model call of the main
#          session is recorded in its transcript (~/.claude/projects/<project>/<session>.jsonl;
#          ~ is %USERPROFILE% on Windows) with `usage`: fresh input, cache creation and cache read
#          together are the context that call sent along. The last such call of the main session
#          (sub-agent entries are marked `isSidechain` and skipped) shows how large the context is
#          right now. The status line also gets the same numbers on stdin as
#          `context_window.current_usage`, which is the cheaper source and wins; the transcript is the
#          status line's source only for an older Claude Code without `context_window` on stdin.
#
# Usage:
#   python .act/scripts/context_size.py                  # newest transcript of the project at the cwd
#   python .act/scripts/context_size.py --transcript P   # a specific transcript
#   As a module: tokens_from_status(), last_context_tokens(), status_segment(), hint_threshold().
#
# Read-only; only the tail of a transcript is read, and a bad line never raises. Stdlib only.

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Optional

DEFAULT_THRESHOLD = 150_000
_TAIL_SIZES = (256_000, 1_000_000, 4_000_000)  # grow only when the smaller tail holds no main-session call
_USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def _sum_usage(usage: object) -> Optional[int]:
    """Context of one call: input + cache creation + cache read; None when `usage` is no usable dict."""
    if not isinstance(usage, dict):
        return None
    total = 0
    for key in _USAGE_KEYS:
        value = usage.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            value = 0
        total += int(value)
    return total


def tokens_from_status(payload: dict) -> Optional[int]:
    """Context tokens from the status line's stdin JSON (`context_window.current_usage`); None when absent."""
    try:
        window = payload.get("context_window")
        if not isinstance(window, dict):
            return None
        return _sum_usage(window.get("current_usage"))
    except Exception:  # noqa: BLE001 — a status segment must never raise
        return None


def _tail_text(transcript: Path, size: int) -> tuple[str, bool]:
    """(last `size` bytes decoded, whether that is the whole file)."""
    with transcript.open("rb") as handle:
        handle.seek(0, 2)
        length = handle.tell()
        handle.seek(max(0, length - size))
        data = handle.read()
    return data.decode("utf-8", "replace"), length <= size


def _last_in_text(text: str) -> Optional[int]:
    found: Optional[int] = None
    for line in text.splitlines():
        if '"usage"' not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue  # the first line of a tail is usually cut off; any bad line is skipped
        if not isinstance(entry, dict) or entry.get("type") != "assistant" or entry.get("isSidechain"):
            continue
        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        tokens = _sum_usage(message.get("usage"))
        if tokens is not None:
            found = tokens
    return found


def last_context_tokens(transcript: Path) -> Optional[int]:
    """Context of the main session's last model call, read from the transcript's tail; None if unknown."""
    try:
        for size in _TAIL_SIZES:
            text, whole = _tail_text(Path(transcript), size)
            found = _last_in_text(text)
            if found is not None:
                return found
            if whole:
                break
    except (OSError, ValueError):
        pass
    return None


def format_tokens(tokens: int) -> str:
    return f"{round(tokens / 1000)}k" if tokens >= 1000 else str(tokens)


def status_segment(payload: dict) -> Optional[str]:
    """`ctx 127k` for the status line from stdin; the transcript is read only when the stdin JSON has no
    `context_window` at all (older Claude Code). `context_window` with a null `current_usage` (session
    start, right after /compact) gives None: the transcript would show the size from before the compaction."""
    try:
        tokens = tokens_from_status(payload)
        if tokens is None and "context_window" not in payload:  # older Claude Code only
            path = payload.get("transcript_path")
            if isinstance(path, str) and path:
                tokens = last_context_tokens(Path(path))
        return None if tokens is None else f"ctx {format_tokens(tokens)}"
    except Exception:  # noqa: BLE001
        return None


def hint_threshold(root: Path) -> Optional[int]:
    """`context-hint` from docs/ai/config.md: a token count, default 150000; `off` -> None; malformed -> default."""
    try:
        import actlib
        value = str(actlib.read_config(Path(root)).get("context-hint", "")).strip().strip("`").lower()
    except Exception:  # noqa: BLE001
        return DEFAULT_THRESHOLD
    if value == "off":
        return None
    if value.isdigit() and int(value) > 0:
        return int(value)
    return DEFAULT_THRESHOLD


def project_transcripts(cwd: Path) -> Path:
    """Folder of a project's transcripts: Claude Code replaces every character but letters and digits with '-'."""
    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(cwd))


def main(argv: Optional[list[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Context size of the running session, from its transcript.")
    parser.add_argument("--transcript", type=Path, help="path of a transcript (.jsonl); default: the newest of this project")
    args = parser.parse_args(argv)

    transcript = args.transcript
    if transcript is None:
        folder = project_transcripts(Path.cwd())
        candidates = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        if not candidates:
            print(f"no transcript under {folder}", file=sys.stderr)
            return 1
        transcript = candidates[-1]
    tokens = last_context_tokens(transcript)
    if tokens is None:
        print(f"no main-session model call with usage in {transcript}", file=sys.stderr)
        return 1
    print(f"context: {tokens} tokens · {status_segment({'context_window': {'current_usage': {'input_tokens': tokens}}})}"
          f" · {transcript.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
