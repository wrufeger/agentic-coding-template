#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Single entry point for every hook event this template wires into the assistant's
#          harness (currently PreToolUse and SessionStart). One script per event would scatter
#          the same "read stdin, load actlib, check config" boilerplate across files; dispatch.py
#          does that once and hands off to one handler per event.
#
# Usage:
#   python .act/hooks/dispatch.py <event>
#   ... with the hook's JSON payload piped in on stdin (may be empty or malformed; handled).
#
#   Recognized <event> values: "PreToolUse", "SessionStart". Any other value (or none) does
#   nothing and exits 0 — an unknown event must never break the caller's hook chain.
#
# Output format:
#   PreToolUse:   exit 0 (allow) or exit 2 with a one-line reason on stderr (deny) — the
#                 harness convention for "block this tool call and show the assistant why".
#   SessionStart: one or more lines on stdout, ending in the fixed-format status line
#                 "[act] branch=<name> [· inbox: <n> waiting] · board updated"; exit 0 always —
#                 a session start must never fail the session over a mechanism error.
#
# Exit-code contract for PreToolUse specifically: a mechanism error while checking a candidate
# write is NOT swallowed the way a SessionStart error is. Every other check in this template
# fails open (never blocks the session on its own bug); the write-guard is the one exception —
# "im Zweifel ablehnen" (when in doubt, deny) — because a false allow here means the template
# silently loses its own files to an edit the next update overwrites anyway.

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import actlib  # noqa: E402 (sys.path setup above must run first)

# Force UTF-8 on stdout/stderr: on Windows, Python otherwise picks the console's legacy code
# page (e.g. cp1252), which silently mangles the em dash in _WRITE_GUARD_MESSAGE below into a
# different byte than the UTF-8 the harness expects. reconfigure() is Python 3.7+; the
# try/except keeps this a no-op on a stream that does not support it instead of crashing.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _read_payload() -> dict:
    """Read the hook's JSON payload from stdin. Returns {} for empty/malformed input — a
    payload we cannot parse is never grounds to crash, only to fall back to defaults."""
    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return {}
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _check_mode(config: dict[str, str], key: str, default: str) -> str:
    """Look up one row of the Checks table in docs/ai/config.md ("block" | "warn" | "off").
    Falls back to `default` for a missing key or an unrecognized value — "Vorgabe ist Ablehnen"
    (default deny) means an unrecognized value is treated the same as an absent row."""
    value = config.get(key, "").strip().lower()
    return value if value in ("block", "warn", "off") else default


# ---------------------------------------------------------------------------
# Check 1 — template write-guard (PreToolUse), checked before anything else
# ---------------------------------------------------------------------------

# ".act" as a whole path segment: ".act/" or ".act\" anywhere in the string, or ".act" at the
# very end — never as a prefix of another name. Deliberately no required prefix character
# before ".act" (a shell command has it after a space, quote, "=", redirect symbol, "(", and
# so on — enumerating all of those is more fragile than just not requiring one). The suffix
# check is what excludes ".act-lock.json" and ".act-local/", both project-level state next to
# the template tree rather than inside it, from this guard.
_PROTECTED_PATH_RE = re.compile(r"\.act(?:[\\/]|$)")

# Shell constructs that mark a Bash command as *writing* somewhere, as opposed to merely
# mentioning a path (reading, grepping, listing it). Deliberately broad — "im Zweifel
# ablehnen" — a command matched here plus a protected-path mention anywhere in it denies the
# whole command, even if the path is actually only the read side (e.g. `cat .act/x > /tmp/y`).
_REDIRECT_RE = re.compile(r"(\d*>>?|&>>?|>\|)")
_WRITE_WORD_RE = re.compile(r"(?:^|[;&|]\s*)\s*(cp|mv|mkdir|rm|rmdir|touch|tee|install|rsync|dd|ln)\b")
_SED_INPLACE_RE = re.compile(r"\bsed\b[^;&|]*-i\b")
_FETCH_TO_FILE_RE = re.compile(r"\b(curl\b[^;&|]*-o\b|wget\b[^;&|]*-O\b)")
_GIT_WRITE_RE = re.compile(r"\bgit\s+(mv|rm)\b")


def _bash_targets_protected_path(command: str) -> bool:
    """True if a Bash command both mentions a path under .act/ and contains a write construct
    (redirection, cp/mv/mkdir/rm/..., in-place sed, curl -o/wget -O, git mv/rm). A
    protected-path mention with no write construct at all (cat, ls, grep, git diff, ...) is a
    read and is allowed."""
    if not _PROTECTED_PATH_RE.search(command):
        return False
    return bool(
        _REDIRECT_RE.search(command)
        or _WRITE_WORD_RE.search(command)
        or _SED_INPLACE_RE.search(command)
        or _FETCH_TO_FILE_RE.search(command)
        or _GIT_WRITE_RE.search(command)
    )


# Which tool_input field holds the write target, per tool. Bash has no single target field and
# is handled separately by _bash_targets_protected_path.
_TOOL_PATH_FIELDS = {
    "Write": ("file_path",),
    "Edit": ("file_path",),
    "MultiEdit": ("file_path",),
    "NotebookEdit": ("notebook_path", "file_path"),
}

_WRITE_GUARD_MESSAGE = (
    "[act] .act/ belongs to the template and is replaced on update. Put your version in "
    "docs/ai/local/<same path> — it wins over the template (ADR-5)."
)


def _targets_protected_path(tool_name: str, tool_input: dict) -> bool:
    """True if this tool call writes somewhere under .act/, based on the write-target field(s)
    that specific tool uses. Unknown tools never match — this guard only needs to understand
    the tools named in the PreToolUse matcher in settings.hooks.json."""
    if tool_name == "Bash":
        command = tool_input.get("command")
        return isinstance(command, str) and _bash_targets_protected_path(command)
    for field in _TOOL_PATH_FIELDS.get(tool_name, ()):
        value = tool_input.get(field)
        if isinstance(value, str) and _PROTECTED_PATH_RE.search(value):
            return True
    return False


def check_write_guard(payload: dict) -> int:
    """Check 1: deny an AI write under .act/**, pointing at docs/ai/local/<path> instead
    (ADR-5). See the module docstring for why this check's error handling — fail closed, not
    open — differs from the rest of the script."""
    config = actlib.read_config()
    mode = _check_mode(config, "template-write-guard", default="block")
    if mode == "off":
        return 0

    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        return 0  # nothing to check a write target against

    if not _targets_protected_path(tool_name, tool_input):
        return 0

    if mode == "warn":
        print(_WRITE_GUARD_MESSAGE)
        return 0

    print(_WRITE_GUARD_MESSAGE, file=sys.stderr)
    return 2


# ---------------------------------------------------------------------------
# Check 2 — session start: inbox count, bridge re-derivation, board refresh
# ---------------------------------------------------------------------------

def _current_branch(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    name = result.stdout.strip()
    return name if result.returncode == 0 and name else "unknown"


_ANSWERED_RE = re.compile(r"^answered:\s*(\S.*)$", re.IGNORECASE)


def _count_inbox_waiting(root: Path) -> int:
    """
    Count inbox entries that are "answered, not yet processed": a file in docs/ai/inbox/ (one
    per entry, "YYYY-MM-DD-<slug>.md" per its README) whose header carries an `answered:` field
    with a value other than empty/"no"/"false". Stage 1 has no archive step yet — an answered
    entry simply stays in inbox/ until a later stage adds one — so presence there is enough.

    Assumption: the inbox entry format beyond `for: <identity>` is not written up yet (skeleton
    README is one line); this `answered:` field is this script's own placeholder convention
    until the real format is documented.
    """
    inbox_dir = root / "docs" / "ai" / "inbox"
    if not inbox_dir.is_dir():
        return 0
    count = 0
    for entry in inbox_dir.glob("*.md"):
        if entry.name.lower() == "readme.md":
            continue
        try:
            lines = entry.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines[:20]:  # header fields live at the top of the file
            match = _ANSWERED_RE.match(line.strip())
            if match and match.group(1).strip().lower() not in ("no", "false"):
                count += 1
                break
    return count


def _refresh_board(root: Path) -> None:
    """Run .act/scripts/board.py if it exists yet (a parallel task builds it); do nothing,
    silently, otherwise — per the build order for this script (T15 depends only on T14)."""
    board_script = root / ".act" / "scripts" / "board.py"
    if not board_script.is_file():
        return
    try:
        subprocess.run([sys.executable, str(board_script)], cwd=root, timeout=15, capture_output=True)
    except (OSError, subprocess.TimeoutExpired):
        pass  # a broken board refresh must not block the session


# Destination (repo-root-relative) -> source filename under .act/bridges/, for exactly the
# bridges .act/bridges/gitattributes marks `merge=ours`. Only these are re-derived here; keep
# this map and that file's merge=ours lines in sync if a later stage adds more bridges.
_BRIDGE_MAP = {
    "CLAUDE.md": "CLAUDE.md",
    "AGENTS.md": "AGENTS.md",
    "docs/ai/rules.md": "rules.md",
}


def _refresh_bridges(root: Path, write: bool) -> tuple[list[str], list[str]]:
    """
    Re-derive every generated bridge that is still exactly as it was last generated (current
    hash matches .act-local/cache.json) from its .act/bridges/ source — this stands in for a
    registered `merge=ours` driver (see .act/bridges/gitattributes), which needs a per-machine
    `git config` no checkout is guaranteed to have. A bridge whose hash no longer matches was
    edited locally and is left untouched either way.

    With `write=False` (check-mode-`warn`), nothing is written — the "refreshed" list reports
    what would have changed instead.

    Returns (changed, refreshed): `changed` are destinations left alone because they were
    edited locally; `refreshed` are destinations re-derived from the template (or that would
    have been, under write=False).
    """
    cache = actlib.read_cache()
    generated = cache["generated"]
    changed: list[str] = []
    refreshed: list[str] = []

    for dest_rel, source_name in _BRIDGE_MAP.items():
        dest_path = root / dest_rel
        source_path = root / ".act" / "bridges" / source_name
        if not dest_path.is_file() or not source_path.is_file():
            continue  # not generated yet, or template source missing — nothing to do here

        recorded_hash = generated.get(dest_rel)
        if recorded_hash is None:
            continue  # never tracked as generated — not ours to touch

        current_hash = actlib.sha256_file(dest_path)
        if current_hash != recorded_hash:
            changed.append(dest_rel)
            continue

        refreshed.append(dest_rel)
        if write:
            content = source_path.read_text(encoding="utf-8")
            dest_path.write_text(content, encoding="utf-8")
            generated[dest_rel] = actlib.sha256_file(dest_path)

    if write and refreshed:
        actlib.write_cache({"generated": generated})
    return changed, refreshed


def refresh_session(payload: dict) -> int:
    """Check 2: runs only for SessionStart. Never fails the session — every sub-step is best
    effort and swallows its own errors; the fixed-format status line is always printed last."""
    config = actlib.read_config()
    mode = _check_mode(config, "session-start-refresh", default="block")
    if mode == "off":
        return 0

    try:
        root = actlib.repo_root()
    except RuntimeError:
        return 0  # not inside a template-managed project — nothing to report

    branch = _current_branch(root)

    try:
        waiting = _count_inbox_waiting(root)
    except Exception:
        waiting = 0

    changed_bridges: list[str] = []
    refreshed_bridges: list[str] = []
    try:
        changed_bridges, refreshed_bridges = _refresh_bridges(root, write=(mode == "block"))
    except Exception:
        pass

    try:
        _refresh_board(root)
    except Exception:
        pass

    for dest_rel in changed_bridges:
        print(f"[act] note: {dest_rel} was changed locally, template version not applied")
    if mode == "warn":
        for dest_rel in refreshed_bridges:
            print(f"[act] note: {dest_rel} would be refreshed from .act/bridges/ (warn mode, not applied)")

    inbox_part = f" · inbox: {waiting} waiting" if waiting else ""
    print(f"[act] branch={branch}{inbox_part} · board updated")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    if len(argv) != 1:
        return 0  # no event named — nothing to dispatch, never an error for the caller

    event = argv[0]
    payload = _read_payload()

    if event == "PreToolUse":
        return check_write_guard(payload)
    if event == "SessionStart":
        return refresh_session(payload)
    return 0  # unknown event — do nothing, exit 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
