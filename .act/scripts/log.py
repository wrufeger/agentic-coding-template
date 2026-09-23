#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Write one line to ai.log at the project root (AGENTS.md § "Logging (optional)",
#          .act/rules/topics/logging.md) and the small tools to read it back — follow it live
#          (--tail), inspect the effective switch (--status), or start a fresh file (--reset). Two
#          callers share this module: a human/assistant typing a line by hand (CLI mode below),
#          and .act/hooks/checks/event_log.py, the SessionStart/SubagentStart/.../PreToolUse
#          observer that turns hook payloads into lines automatically — it imports write_line()
#          and the label-numbering helpers from here instead of duplicating them, per this
#          module's own "Numbering" section below. Stdlib only.
#
# Usage:
#   python .act/scripts/log.py LEVEL agent topic Text...   # write one line (LEVEL: DEBUG|INFO|WARN|ERROR)
#   python .act/scripts/log.py --tail [--grep PATTERN] [--lines N] [--no-color]
#   python .act/scripts/log.py --status
#   python .act/scripts/log.py --reset
#   python .act/scripts/log.py --help
#
# Output format:
#   A written line: "[YYYY-MM-DD HH:MM:SS] [LEVEL] [agent] [topic] Text" — see write_line().
#   --tail: the same lines, colored by level unless --no-color or the NO_COLOR env var is set, or
#     stdout is not a terminal.
#   --status: effective config (root, log file, on/off, level) plus, if any sub-agent has been
#     numbered via the hooks, a short per-session summary.
#   --reset: renames ai.log to ai.log.<timestamp>.bak; "nothing to do" if it does not exist.
#   Errors: a one-line message on stderr, exit 2 for a bad command line, 1 for a failed --reset;
#   every other path exits 0 — a caller (a hook, an assistant mid-task) must never see a traceback
#   from a logging call that went wrong.

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

import actlib
import feedback_privacy

LEVELS = ["DEBUG", "INFO", "WARN", "ERROR"]
_LEVEL_RANK = {level: i for i, level in enumerate(LEVELS)}


# ---------------------------------------------------------------------------
# Config — docs/ai/config.md § Logging (`logging`: on|off, `log-level`: DEBUG|INFO|WARN|ERROR)
# ---------------------------------------------------------------------------

def _default_root() -> Path:
    """actlib.repo_root(), falling back to this script's own location (.act/scripts/log.py's
    grandparent) when the current directory is not inside a template-managed project — the same
    fallback shape actlib.repo_root() itself documents as its failure mode, so a stray call from
    outside the project still finds *a* root instead of raising."""
    try:
        return actlib.repo_root()
    except RuntimeError:
        return Path(__file__).resolve().parents[2]


def load_config() -> dict:
    """Effective logging config: {"root", "log_file", "enabled", "level"}. `enabled` is the
    `logging` key (only "on" counts; a missing/other value is off, the skeleton's own default).
    `level` is `log-level`, defaulting to "INFO" for a missing or unrecognized value."""
    root = _default_root()
    try:
        config = actlib.read_config()
    except (RuntimeError, OSError, UnicodeDecodeError):
        # RuntimeError: not inside a template-managed project (e.g. --status run from outside
        # one, see _default_root() above). OSError/UnicodeDecodeError: docs/ai/config.md exists
        # but cannot be read as UTF-8 -- actlib.read_config() only guards the OSError case itself,
        # not a bad encoding, and log.py must never crash on either.
        config = {}
    enabled = config.get("logging", "").strip().lower() == "on"
    level = config.get("log-level", "").strip().upper()
    if level not in LEVELS:
        level = "INFO"
    return {"root": root, "log_file": root / "ai.log", "enabled": enabled, "level": level}


# ---------------------------------------------------------------------------
# Secret masking — ported from the template's own predecessor script (.claude/scripts/ai-log.py,
# template-agentic-coding-project), not the same job as feedback_privacy.py: that module *rejects*
# a string carrying a finding (nothing is sent), this one *redacts* the secret-shaped part in
# place so the rest of the line still logs. Kept here rather than in feedback_privacy.py since
# masking has no reuse target there.
# ---------------------------------------------------------------------------

# key=value / key: value / a JSON field's "key": "value" / a shell assignment in quotes
# (export API_TOKEN="...", $env:GITHUB_TOKEN = '...') — an optional quote is tolerated both right
# after the key (a JSON key's closing quote) and right after the "="/":" (the value's opening
# quote; its closing quote is never consumed, so it survives untouched after the "***"). An
# optional leading scheme word is folded into the masked part too, so "Authorization: Bearer xyz"
# masks the whole "Bearer xyz", not just "xyz". Deliberately no `\b`: a `\b` between "_" and a
# letter does not exist, so `\bTOKEN\b` never matches inside "API_TOKEN" — see the same fix in
# feedback_privacy.py's own SECRET_WORDS for the reasoning; "tokens: 5 used" still passes through,
# since the "s" right after "token" breaks the required "[\"']?\s*[=:]" that must follow.
_SECRET_KV_RE = re.compile(
    r"(?i)((?:password|passwd|pwd|secret|token|api[_-]?key|authorization|bearer)[\"']?\s*[=:]\s*[\"']?"
    r"(?:(?:bearer|basic|token|jwt)\s+)?)([^\s\"']+)"
)
# Space-separated CLI flags: --password x, --secret-access-key x, -token x.
_SECRET_FLAG_RE = re.compile(
    r"(?i)(--?[a-z0-9-]*(?:password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|credential)"
    r"[a-z0-9-]*)[ \t]+([^\s\"']+)"
)
# Basic-auth username:password on a "-u" flag (curl -u admin:hunter2) — the value has no leading
# space to anchor a key=value match on, so this is its own pattern rather than a _SECRET_KV_RE case.
_SECRET_DASH_U_RE = re.compile(r"(?i)(\s-u\s*[^\s:]+:)\S+")
# mysql's own inline-password convention: "-p<password>", no space, not to be confused with a
# bare "-p" flag (which this excludes by requiring a non-space, non-"-" character right after it,
# i.e. an actual attached value, not the next flag).
_SECRET_DASH_P_RE = re.compile(r"(\s-p)([^\s-][^\s]*)")
# Credentials embedded in a URL: postgres://user:pass@host, https://user:token@github.com/...
_SECRET_URL_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^\s/:@]+):([^\s/@]+)@")


def _kv_replace(match: "re.Match") -> str:
    prefix = match.group(0)[: len(match.group(0)) - len(match.group(2))]
    return prefix + "***"


def mask_secrets(text: str) -> str:
    """Replace anything that looks like a secret in `text` with "***". Deliberately broad — a
    false positive costs a masked word in a log line, a missed one leaks a credential. Real token
    prefixes (GitHub/GitLab/Slack/AWS/Anthropic-shaped) are recognized via
    feedback_privacy.TOKEN_PREFIX — the same, more complete pattern the secret-scan check uses,
    rather than a second hand-kept list here."""
    if not text:
        return text
    text = _SECRET_URL_RE.sub(r"\1:***@", text)
    text = _SECRET_KV_RE.sub(_kv_replace, text)
    text = _SECRET_FLAG_RE.sub(r"\1 ***", text)
    text = _SECRET_DASH_U_RE.sub(r"\1***", text)
    text = _SECRET_DASH_P_RE.sub(r"\1***", text)
    text = feedback_privacy.TOKEN_PREFIX.sub("***", text)
    return text


def clean_text(text, limit: int = 200) -> str:
    """Normalize whitespace, mask secrets, and cut to `limit` characters ("…" suffix) — the
    AGENTS.md § Logging format's own line budget. `text` may be any value (a hook payload field is
    not always a string); non-strings are stringified first."""
    if text is None:
        text = ""
    text = str(text)
    if len(text) > 8000:  # cap before the regexes run, not just before the final truncation
        text = text[:8000]
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = mask_secrets(text)
    if len(text) > limit:
        text = text[: max(0, limit - 1)] + "…"
    return text


def _level_ok(line_level: str, configured_level: str) -> bool:
    return _LEVEL_RANK.get(line_level, 1) >= _LEVEL_RANK.get(configured_level, 1)


_LABEL_CLEAN_RE = re.compile(r"[\s()\[\]]+")


def write_line(cfg: dict, level: str, agent: str, topic: str, text) -> None:
    """Append one line to ai.log, if logging is on and `level` meets the configured floor.
    No-op otherwise (including "off": never even opens the file). `agent`/`topic` have brackets
    and whitespace stripped (the format's own "[agent]" delimiters must not appear inside a
    field, or --tail's line parser misreads it) and are lowercased for a consistent grep target."""
    level = str(level).upper()
    if level not in LEVELS:
        level = "INFO"
    if not cfg["enabled"] or not _level_ok(level, cfg["level"]):
        return

    agent = _LABEL_CLEAN_RE.sub("", str(agent).lower()) or "system"
    topic = _LABEL_CLEAN_RE.sub("", str(topic).lower()) or "session"
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] [{level}] [{agent}] [{topic}] {clean_text(text)}\n"
    try:
        with open(cfg["log_file"], "a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
    except OSError:
        pass  # a write failure (locked file, full disk) must never break the caller


# ---------------------------------------------------------------------------
# Numbering — .act-local/log-state.json (gitignored): per session, the next free "#n" for each
# agent_type and the agent_id -> "type#n" label already handed out, so a worker's later hook calls
# (and its SubagentStop) use the same label its SubagentStart was given. Guarded by a best-effort
# file lock (.act-local/log-state.lock) so two hook processes racing (SubagentStart/PreToolUse can
# both fire close together, and PostToolUseFailure/Notification run async — see settings.hooks.json)
# do not both grab the same number; a write is always atomic (temp file + os.replace) so a reader
# never sees a half-written file even if the lock itself was not obtained.
# ---------------------------------------------------------------------------

_SESSION_MAX_AGE = 24 * 3600  # a session's numbering is forgotten a day after its last activity
_LOCK_TIMEOUT = 1.0
_LOCK_STALE_AFTER = 5.0
_LOCK_SPIN_SLEEP = 0.02


def _state_path(root: Path) -> Path:
    return root / ".act-local" / "log-state.json"


def _lock_path(root: Path) -> Path:
    return root / ".act-local" / "log-state.lock"


class _StateLock:
    """Best-effort lock via os.open(O_CREAT|O_EXCL): never blocks a hook indefinitely. After
    _LOCK_TIMEOUT the caller proceeds without the lock (a missed number is far cheaper than a
    stuck hook); a lock older than _LOCK_STALE_AFTER is treated as abandoned and taken over."""

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self.held = False

    def __enter__(self) -> "_StateLock":
        deadline = time.time() + _LOCK_TIMEOUT
        while True:
            try:
                self.lock_path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                self.held = True
                return self
            except FileExistsError:
                try:
                    age = time.time() - self.lock_path.stat().st_mtime
                except OSError:
                    age = 0.0
                if age > _LOCK_STALE_AFTER:
                    try:
                        self.lock_path.unlink()
                    except OSError:
                        pass
                    continue
                if time.time() >= deadline:
                    self.held = False
                    return self
                time.sleep(_LOCK_SPIN_SLEEP)
            except OSError:
                self.held = False
                return self

    def __exit__(self, *exc_info) -> bool:
        if self.held:
            try:
                self.lock_path.unlink()
            except OSError:
                pass
        return False


def _load_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"sessions": {}}
    if not isinstance(data, dict) or not isinstance(data.get("sessions"), dict):
        return {"sessions": {}}
    return data


# A minimum of 50 tries, 5ms apart (250ms) per the reviewer's own fix recipe; measured live
# against this machine under load (2026-09-23, reviewer probe race2.py plus a from-scratch
# reproduction: a bare reader thread cycling open/read/close every ~2ms) that floor alone still
# lost over half of 200 concurrent writes — a successful call already needed up to 49 of the 50
# tries, right at the edge, so the fix is the same retry, given a longer leash: a wall-clock
# deadline rather than a fixed count, since Windows' own timer granularity can make a nominal 5ms
# sleep considerably longer than requested, so counting *tries* under-provisions time far more
# than counting *seconds* does. 2 seconds is generous but bounded, and stays well inside the 10s
# hook timeout in .act/bridges/settings.hooks.json even stacked with everything else a call does.
_REPLACE_RETRY_SLEEP = 0.005
_REPLACE_DEADLINE_SECONDS = 2.0


def _save_state(path: Path, state: dict, now: float) -> None:
    """Prune sessions inactive for over _SESSION_MAX_AGE, then write atomically (temp file in the
    same directory + os.replace, matching checks/write_scope.py's own convention).

    The final os.replace() is retried on PermissionError specifically: on Windows, a concurrent
    reader with the destination file open (checks/event_log.py's own lookup_subagent_label(), or
    --tail/--status, or an external reader entirely — a hook this module has no control over) can
    make MoveFileEx (what os.replace() uses there) fail with PermissionError even though the same
    call is atomic and always succeeds on POSIX. See _REPLACE_DEADLINE_SECONDS above for the
    retry's own shape and why it is time-bounded rather than try-count-bounded. Called with the
    state lock already held (see start_subagent_label()), so a retry here never races a second
    writer — only a reader, which the retry simply outwaits."""
    cutoff = now - _SESSION_MAX_AGE
    sessions = state.get("sessions")
    sessions = sessions if isinstance(sessions, dict) else {}
    state["sessions"] = {
        sid: sess for sid, sess in sessions.items()
        if isinstance(sess, dict) and isinstance(sess.get("last"), (int, float)) and sess["last"] >= cutoff
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".tmp-", suffix=".tmp", dir=str(path.parent))
    except OSError:
        return
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False)
        deadline = time.time() + _REPLACE_DEADLINE_SECONDS
        while True:
            try:
                os.replace(tmp_name, path)
                break
            except PermissionError:
                if time.time() >= deadline:
                    raise
                time.sleep(_REPLACE_RETRY_SLEEP)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass


def _session_entry(state: dict, session_id: Optional[str]) -> dict:
    key = session_id or "-"
    sessions = state.setdefault("sessions", {})
    session = sessions.get(key)
    if not isinstance(session, dict):
        session = {}
        sessions[key] = session
    session.setdefault("counters", {})
    session.setdefault("labels", {})
    return session


def start_subagent_label(
    root: Path, session_id: Optional[str], agent_type: str, agent_id: Optional[str], now: Optional[float] = None
) -> str:
    """Assign the next "#n" for `agent_type` in this session, record it under `agent_id` (if
    given — a SubagentStart without one is never seen live, but this must not crash on it), and
    return the label. Always called with the lock held, since two SubagentStart hooks for
    parallel workers of the same type can fire close together."""
    now = now if now is not None else time.time()
    state_path, lock_path = _state_path(root), _lock_path(root)
    with _StateLock(lock_path):
        state = _load_state(state_path)
        session = _session_entry(state, session_id)
        n = int(session["counters"].get(agent_type, 0)) + 1
        session["counters"][agent_type] = n
        label = f"{agent_type}#{n}"
        if agent_id:
            session["labels"][str(agent_id)] = label
        session["last"] = now
        _save_state(state_path, state, now)
    return label


def lookup_subagent_label(
    root: Path, session_id: Optional[str], agent_id: Optional[str], now: Optional[float] = None
) -> Optional[str]:
    """The label a prior start_subagent_label() call recorded for `agent_id` in this session, or
    None if none was ever recorded — the caller decides what that means (event_log.py treats it
    as "no matching SubagentStart", see that module's SubagentStop handling)."""
    if not agent_id:
        return None
    state = _load_state(_state_path(root))
    session = state.get("sessions", {}).get(session_id or "-")
    if not isinstance(session, dict):
        return None
    label = session.get("labels", {}).get(str(agent_id))
    return label if isinstance(label, str) and label else None


def _session_summary_lines(root: Path) -> list[str]:
    """For --status: up to 3 most recently active sessions, one line each, counters per type."""
    state = _load_state(_state_path(root))
    sessions = state.get("sessions", {})
    if not isinstance(sessions, dict) or not sessions:
        return []
    items = sorted(
        sessions.items(), key=lambda kv: kv[1].get("last", 0) if isinstance(kv[1], dict) else 0, reverse=True,
    )
    lines = []
    for session_id, session in items[:3]:
        counters = session.get("counters") if isinstance(session, dict) else None
        if not isinstance(counters, dict) or not counters:
            continue
        parts = [f"{agent_type}: {n} started, next #{int(n) + 1}" for agent_type, n in counters.items()]
        lines.append(f"  session {session_id}: " + "; ".join(parts))
    return lines


# ---------------------------------------------------------------------------
# --tail
# ---------------------------------------------------------------------------

_LEVEL_COLOR = {"DEBUG": "\x1b[90m", "WARN": "\x1b[33m", "ERROR": "\x1b[1;31m"}
_DIM = "\x1b[2m"
_CYAN = "\x1b[36m"
_RESET = "\x1b[0m"
_LINE_RE = re.compile(
    r"^\[(?P<ts>[^\]]+)\] \[(?P<level>[^\]]+)\] \[(?P<agent>[^\]]+)\] \[(?P<topic>[^\]]+)\] (?P<text>.*)$"
)


def _colorize(line: str) -> str:
    match = _LINE_RE.match(line.rstrip("\n"))
    if not match:
        return line.rstrip("\n")
    ts, level, agent, topic, text = (
        match.group("ts"), match.group("level"), match.group("agent"), match.group("topic"), match.group("text"),
    )
    if level == "INFO":
        return f"{_DIM}[{ts}]{_RESET} [{level}] {_CYAN}[{agent}]{_RESET} [{topic}] {text}"
    color = _LEVEL_COLOR.get(level, "")
    if color:
        return f"{_DIM}[{ts}]{_RESET} {color}[{level}] [{agent}] [{topic}] {text}{_RESET}"
    return f"{_DIM}[{ts}]{_RESET} [{level}] [{agent}] [{topic}] {text}"


def cmd_tail(cfg: dict, grep: Optional[str], lines: int, no_color: bool) -> int:
    """Print the last `lines` lines, then follow the file (poll every 0.3s) — reads/decodes as
    bytes so seek/tell positions stay correct regardless of text-mode newline translation."""
    log_file = cfg["log_file"]
    use_color = not no_color and not os.environ.get("NO_COLOR") and sys.stdout.isatty()
    if os.name == "nt":
        os.system("")  # enable ANSI escapes on a legacy Windows console

    pattern = None
    if grep:
        try:
            pattern = re.compile(grep, re.IGNORECASE)
        except re.error as exc:
            print(f"log: invalid --grep pattern: {exc}", file=sys.stderr)
            return 1

    def emit(raw_line: str) -> None:
        if pattern and not pattern.search(raw_line):
            return
        print(_colorize(raw_line) if use_color else raw_line.rstrip("\n"), flush=True)

    while not log_file.exists():
        print(f"log: waiting for {log_file} ...", file=sys.stderr)
        try:
            time.sleep(1.0)
        except KeyboardInterrupt:
            return 0

    try:
        with open(log_file, "rb") as handle:
            data = handle.read()
        pos = len(data)
        text = data.decode("utf-8", errors="replace")
        all_lines = text.splitlines(True)
        if all_lines and not all_lines[-1].endswith("\n"):
            rest = all_lines.pop()
            pos -= len(rest.encode("utf-8", errors="replace"))
        for one_line in (all_lines[-lines:] if lines > 0 else []):
            emit(one_line)

        while True:
            try:
                size = log_file.stat().st_size
            except OSError:
                size = 0
            if size < pos:
                pos = 0  # file was truncated/rotated underneath us — read from the start again
            try:
                with open(log_file, "rb") as handle:
                    handle.seek(pos)
                    new_bytes = handle.read()
                new_pos = pos + len(new_bytes)
                new_text = new_bytes.decode("utf-8", errors="replace")
                for one_line in new_text.splitlines(True):
                    if one_line.endswith("\n"):
                        emit(one_line)
                    else:
                        new_pos -= len(one_line.encode("utf-8", errors="replace"))
                pos = new_pos
            except OSError:
                pass
            time.sleep(0.3)
    except KeyboardInterrupt:
        return 0
    return 0


# ---------------------------------------------------------------------------
# --reset / --status
# ---------------------------------------------------------------------------

def cmd_reset(cfg: dict) -> int:
    log_file = cfg["log_file"]
    if not log_file.exists():
        print("log: nothing to do (ai.log does not exist)")
        return 0
    backup = log_file.with_name(f"ai.log.{time.strftime('%Y%m%d-%H%M%S')}.bak")
    try:
        log_file.rename(backup)
    except OSError as exc:
        print(
            f"log: could not rename {log_file} ({exc.strerror or exc}).\n"
            "log: the file is likely open elsewhere (editor, tail -f, viewer) — close it and retry.",
            file=sys.stderr,
        )
        return 1
    print(f"log: {log_file.name} -> {backup.name}")
    return 0


def cmd_status(cfg: dict) -> int:
    print(f"root:      {cfg['root']}")
    print(f"log file:  {cfg['log_file']}")
    print(f"logging:   {'on' if cfg['enabled'] else 'off'} (docs/ai/config.md § Logging)")
    print(f"level:     {cfg['level']}")
    summary = _session_summary_lines(cfg["root"])
    if summary:
        print("sessions (most recent first, max. 3):")
        for line in summary:
            print(line)
    else:
        print("sessions:  none yet (no sub-agent numbered via the hooks)")
    return 0


# ---------------------------------------------------------------------------
# main / argument parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="log.py",
        description=(
            "Write one line to ai.log (LEVEL agent topic text...), or --tail/--status/--reset it. "
            "See .act/rules/topics/logging.md for when this runs and what a line looks like."
        ),
    )
    parser.add_argument("level", nargs="?", metavar="LEVEL", help="DEBUG|INFO|WARN|ERROR")
    parser.add_argument("agent", nargs="?", metavar="AGENT", help="who acted, e.g. orchestrator, builder#2")
    parser.add_argument("topic", nargs="?", metavar="TOPIC", help="one word, e.g. decision, commit, result")
    parser.add_argument(
        "text", nargs=argparse.REMAINDER, metavar="TEXT",
        help="the line's message, joined with spaces (may itself start with '-')",
    )
    parser.add_argument("--tail", action="store_true", help="print the last lines of ai.log, then follow it")
    parser.add_argument("--grep", metavar="PATTERN", help="with --tail: only lines matching this pattern")
    parser.add_argument("--lines", type=int, default=20, metavar="N",
                         help="with --tail: how many existing lines to print first (default: 20)")
    parser.add_argument("--no-color", action="store_true", help="with --tail: plain text, no ANSI colors")
    parser.add_argument("--status", action="store_true", help="show the effective config and label counters")
    parser.add_argument("--reset", action="store_true", help="rename ai.log to ai.log.<timestamp>.bak")
    return parser


def main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = load_config()

    if args.tail:
        return cmd_tail(cfg, args.grep, args.lines, args.no_color)
    if args.status:
        return cmd_status(cfg)
    if args.reset:
        return cmd_reset(cfg)

    if not (args.level and args.agent and args.topic and args.text):
        parser.error("LEVEL, agent, topic and a text are all required to write a line")
    if args.level.upper() not in LEVELS:
        parser.error(f"LEVEL must be one of {', '.join(LEVELS)}")
    write_line(cfg, args.level.upper(), args.agent, args.topic, " ".join(args.text))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
