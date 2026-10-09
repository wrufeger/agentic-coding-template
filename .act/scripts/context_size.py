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
#   python .act/scripts/context_size.py --report [--json] # whole session: base load, cache hit rate, cache breaks
#   As a module: tokens_from_status(), last_context_tokens(), status_segment(), hint_threshold().
#
# Read-only; the status line reads only the tail of a transcript, --report streams the whole file line by
# line; a bad line never raises. Stdlib only. The report's method (hit rate, cache breaks, base load from
# the transcript's usage fields) is modelled on claude-context-optimizer (MIT).

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

DEFAULT_THRESHOLD = 180_000
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
    """`context-hint` from docs/ai/config.md: a token count, default 180000; `off` -> None; malformed -> default."""
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


def _usage_fields(usage: dict) -> dict:
    out = {}
    for key in _USAGE_KEYS + ("output_tokens",):
        value = usage.get(key, 0)
        out[key] = 0 if isinstance(value, bool) or not isinstance(value, (int, float)) else int(value)
    return out


def iter_calls(transcript: Path) -> Iterator[dict]:
    """Model calls of the main session, in order, one per `message.id`. The transcript writes one line per
    content block of a response, all with the same id; their `usage` is identical in practice, so the last
    line of an id wins (a streamed partial `output_tokens` could only be smaller in an earlier line).
    Sub-agent lines (`isSidechain`), non-assistant lines, lines without a usable `usage` and bad lines are
    skipped. The file is streamed; only the calls themselves are kept. Yields dicts with `id`, `time` (the
    first line's timestamp or None), the usage fields and `context` (input + cache creation + cache read)."""
    calls: dict = {}
    with Path(transcript).open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if '"usage"' not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict) or entry.get("type") != "assistant" or entry.get("isSidechain"):
                continue
            message = entry.get("message")
            if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
                continue
            if message.get("model") == "<synthetic>":
                continue  # a client-side API error line, not a model call
            call_id = message.get("id")
            if not isinstance(call_id, str) or not call_id:
                call_id = f"line-{len(calls)}"  # no id: the line counts as its own call
            fields = _usage_fields(message["usage"])
            fields["context"] = sum(fields[key] for key in _USAGE_KEYS)
            fields["id"] = call_id
            timestamp = entry.get("timestamp")
            fields["time"] = calls[call_id]["time"] if call_id in calls else (timestamp if isinstance(timestamp, str) else None)
            calls[call_id] = fields  # a dict keeps the first insertion position of an id
    yield from calls.values()


def _seconds_between(earlier: Optional[str], later: Optional[str]) -> Optional[int]:
    try:
        first = datetime.fromisoformat(str(earlier).replace("Z", "+00:00"))
        second = datetime.fromisoformat(str(later).replace("Z", "+00:00"))
        return int((second - first).total_seconds())
    except (ValueError, TypeError):  # TypeError: one timestamp with a zone, one without
        return None


def build_report(transcript: Path) -> dict:
    """Whole-session numbers. A cache break is a call whose `cache_read` fell below half of its
    predecessor's although the context did not shrink (pause past the cache lifetime, changed prefix)."""
    steps = base = total_in = cache_read = cache_creation = output = 0
    breaks: list = []
    prev: Optional[dict] = None
    for call in iter_calls(transcript):
        steps += 1
        if prev is None:
            base = call["context"]
        elif call["cache_read_input_tokens"] < prev["cache_read_input_tokens"] / 2 and call["context"] >= prev["context"]:
            breaks.append({"step": steps, "cache_read_before": prev["cache_read_input_tokens"],
                           "cache_read_after": call["cache_read_input_tokens"],
                           "seconds_since_previous": _seconds_between(prev["time"], call["time"])})
        total_in += call["context"]
        cache_read += call["cache_read_input_tokens"]
        cache_creation += call["cache_creation_input_tokens"]
        output += call["output_tokens"]
        prev = call
    return {"transcript": Path(transcript).name, "steps": steps, "base_load": base, "input_total": total_in,
            "cache_read": cache_read, "cache_hit_rate": round(cache_read / total_in, 4) if total_in else None,
            "cache_creation": cache_creation, "cache_breaks": len(breaks), "breaks": breaks, "output_total": output}


def format_report(report: dict) -> str:
    rate = report["cache_hit_rate"]
    rate_text = "n/a" if rate is None else f"{rate * 100:.1f}%"
    lines = [f"transcript: {report['transcript']}", f"steps: {report['steps']}",
             f"base load (first call): {report['base_load']} tokens",
             f"input total: {report['input_total']} tokens",
             f"cache hit rate: {rate_text} (cache_read {report['cache_read']})",
             f"cache creation: {report['cache_creation']} tokens", f"cache breaks: {report['cache_breaks']}"]
    for item in report["breaks"]:
        gap = item["seconds_since_previous"]
        gap_text = "gap unknown" if gap is None else f"{gap} s after the previous call"
        lines.append(f"  step {item['step']}: cache_read {item['cache_read_before']} -> {item['cache_read_after']}, {gap_text}")
    lines.append(f"output total: {report['output_total']} tokens")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Context size of the running session, from its transcript.")
    parser.add_argument("--transcript", type=Path, help="path of a transcript (.jsonl); default: the newest of this project")
    parser.add_argument("--report", action="store_true", help="whole-session report: base load, cache hit rate, cache breaks")
    parser.add_argument("--json", action="store_true", help="print the whole-session report as JSON (implies --report)")
    args = parser.parse_args(argv)
    if args.json:
        args.report = True

    transcript = args.transcript
    if transcript is None:
        folder = project_transcripts(Path.cwd())
        candidates = sorted(folder.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        if not candidates:
            print(f"no transcript under {folder}", file=sys.stderr)
            return 1
        transcript = candidates[-1]
    if args.report:
        try:
            report = build_report(transcript)
        except OSError as error:
            print(f"cannot read {transcript}: {error}", file=sys.stderr)
            return 1
        if report["steps"] == 0:
            print(f"no main-session model call with usage in {transcript}", file=sys.stderr)
            return 1
        print(json.dumps(report, indent=2) if args.json else format_report(report))
        return 0
    tokens = last_context_tokens(transcript)
    if tokens is None:
        print(f"no main-session model call with usage in {transcript}", file=sys.stderr)
        return 1
    print(f"context: {tokens} tokens · {status_segment({'context_window': {'current_usage': {'input_tokens': tokens}}})}"
          f" · {transcript.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
