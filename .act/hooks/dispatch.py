#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Single entry point for every hook event this template wires into the assistant's
#          harness (currently PreToolUse and SessionStart). One script per event would scatter
#          the same "read stdin, load actlib, check config" boilerplate across files; dispatch.py
#          does that once and hands off to one handler per event. PreToolUse runs two checks: the
#          template write-guard (check_write_guard) and the no-sub-sub-agents guard
#          (check_worker_nesting_guard, R-role-worker) — the first block wins.
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
#   SessionStart: one or more lines on stdout — an optional block of orchestrator-only rules
#                 (main session only, never seen by a sub-agent), zero or more "[act] note: ..."
#                 lines (a changed/unrefreshable bridge, an unresolvable tier/reasoning value, a
#                 project .act/ pulled in without update.py — each best-effort and independently
#                 gated, see refresh_session()), then the fixed-format status line "[act]
#                 branch=<name> [· inbox: <n> waiting] · board updated [· rules: <n>]
#                 [· role-bridges refreshed: <n>]", and finally, as a deliberate postscript after
#                 that status line, an optional "a template update is available" note — always a
#                 *previous* SessionStart's finding, consumed from .act-local/update-check-
#                 result.json, never something looked up during this run (see
#                 _spawn_update_check_worker: the actual `git ls-remote` runs detached, in the
#                 background, so it can never delay this session — a SessionStart hook has a
#                 fixed timeout, and an unreachable template source measured at 21s against a
#                 5s subprocess timeout before this fix, see that function's docstring). Also
#                 re-derives the model/effort frontmatter of every existing .claude/agents/*.md
#                 role bridge (tiers.py), leaving the rest of each file untouched;
#                 exit 0 always — a session start must never fail the session over a mechanism
#                 error.
#
#   "_update-check-worker" <root>: internal only, never a real harness hook event — this is what
#                 _spawn_update_check_worker() launches as a detached background process (see
#                 main() below). Not documented to the harness, not something a hook config ever
#                 names.
#
# Exit-code contract for PreToolUse specifically: a mechanism error while checking a candidate
# write is NOT swallowed the way a SessionStart error is. Every other check in this template
# fails open (never blocks the session on its own bug); the write-guard is the one exception —
# "im Zweifel ablehnen" (when in doubt, deny) — because a false allow here means the template
# silently loses its own files to an edit the next update overwrites anyway.

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import actlib  # noqa: E402 (sys.path setup above must run first)
import manifest  # noqa: E402
import tiers  # noqa: E402

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
    Falls back to `default` for a missing key or an unrecognized value: default deny means
    an unrecognized value is treated the same as an absent row."""
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
# Check 1b — no sub-sub-agents (R-role-worker, PreToolUse)
# ---------------------------------------------------------------------------

# A role's own `tools` frontmatter never lists "Agent"/"Task" (docs/project/concepts/ai-dev-app/
# 02-directory-plan.md § "Brücken" in the template-pflege repo, .act/agents/README.md) — this is
# the mechanical backstop for that rule: a PreToolUse call to either tool whose payload carries an
# "agent_id" did not come from the orchestrator (the harness stamps every sub-agent's own tool
# calls with its agent_id; the main session's calls carry none — confirmed against
# D:/dev/rufeger/template-agentic-coding-project/.claude/scripts/ai-log.py, which reads
# payload["agent_id"] on every hook event including PreToolUse). Denied regardless of what a
# role's own tools list says, since a hand-edited role bridge could otherwise re-add the tool.
#
# The same guard also catches the CLI-level escape hatch: a sub-agent that cannot call
# Agent/Task directly can still reach for `claude -p "..."` (or `--print`) via Bash to spawn an
# unsupervised second harness instance. Same test (agent_id present -> not the orchestrator),
# same verdict. Known gap, not fixable from this payload alone: a skill invoked with
# `context: fork` runs as its own harness call, indistinguishable here from an ordinary
# sub-agent Bash call — this guard cannot see the difference and does not try to.
_WORKER_TOOL_NAMES = {"Agent", "Task"}
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
    `claude -p` CLI escape hatch (Bash). See the module docstring for why PreToolUse checks fail
    closed rather than open."""
    config = actlib.read_config()
    mode = _check_mode(config, "worker-nesting-guard", default="block")
    if mode == "off":
        return 0

    if not payload.get("agent_id"):
        return 0  # the orchestrator's own call — never stamped with an agent_id

    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    message: Optional[str] = None
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


# ---------------------------------------------------------------------------
# Check 2 — session start: inbox count, bridge re-derivation, board refresh,
#           orchestrator-only rules delivered as hook context
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


_STATUS_RE = re.compile(r"^status:\s*(\S+)", re.IGNORECASE)


def _count_inbox_waiting(root: Path) -> int:
    """
    Count inbox entries that are "answered, not yet processed": a file in docs/ai/inbox/ (one
    per entry, "YYYY-MM-DD-<slug>.md") whose header says `status: answered`.

    The header carries three fields: `for:` (who it is addressed to), `status:` and the date in
    the file name. `status` runs `open` -> `answered` -> `done`: the human (or the assistant, when
    the answer came up in chat) sets `answered`, and whoever works the entry into its place sets
    `done`. Only `answered` is counted — `open` is still waiting on a person, `done` is finished.
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
            match = _STATUS_RE.match(line.strip())
            if match:
                if match.group(1).strip().lower() == "answered":
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


# ---------------------------------------------------------------------------
# Check 2b — template awareness at session start: a project .act/ that was brought to a clean
# template state by something other than update.py (e.g. a plain `git pull` of the shared history
# some projects still keep from before Q73a), and, at most once a day, whether the template's own
# remote has moved past what .act-lock.json last recorded. Both read-only, both best-effort — see
# refresh_session()'s try/except around each call; neither ever raises out of this function.
# ---------------------------------------------------------------------------

def _manifest_fingerprint(act_dir: Path) -> str:
    """CRLF-folded fingerprint of act_dir/MANIFEST.json, matching what .act-lock.json's
    template.manifest_sha256 is meant to record (Q73a) -- unlike a raw `actlib.sha256_file()` of
    the file, this is unaffected by the checkout's line endings (core.autocrlf), so a MANIFEST.json
    checked out with CRLF on Windows still fingerprints the same as the LF copy that produced the
    recorded hash. Prefers manifest.py's own `manifest_fingerprint()` (added alongside this fix);
    falls back to manifest.py's existing `content_hash()` — which already does the same CRLF
    folding for every other file under .act/ — applied to MANIFEST.json directly, in case that
    function has not landed yet. Returns "" if MANIFEST.json cannot be read at all."""
    fingerprint_fn = getattr(manifest, "manifest_fingerprint", None)
    if callable(fingerprint_fn):
        try:
            return fingerprint_fn(act_dir)
        except Exception:
            pass  # fall through to the content_hash() fallback below
    try:
        return manifest.content_hash(act_dir / "MANIFEST.json")
    except OSError:
        return ""


def _pulled_without_update(root: Path) -> bool:
    """True when .act/ matches its own MANIFEST.json exactly (so not a hand-edit — that is a
    different, already-covered concern, see doctor.py's manifest-drift check) but the fingerprint
    of that MANIFEST.json does not match the one .act-lock.json recorded at the last
    update.py/init.py run (`template.manifest_sha256`, Q73a) -- the fingerprint that tells a
    project's own regular state apart from one a plain `git pull` (or any other means outside
    update.py) just landed."""
    manifest_path = root / ".act" / "MANIFEST.json"
    if not manifest_path.is_file():
        return False
    try:
        recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(recorded, dict) or manifest.collect_files(root / ".act") != recorded:
        return False  # hand-edited (or unreadable) -- not what this check is looking for
    lock = actlib.read_lock()
    expected = (lock.get("template") or {}).get("manifest_sha256") or ""
    return _manifest_fingerprint(root / ".act") != expected


def _update_check_state_path(root: Path) -> Path:
    return root / ".act-local" / "update-check.json"


def _already_checked_today(root: Path) -> bool:
    try:
        data = json.loads(_update_check_state_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and data.get("last_checked") == date.today().isoformat()


def _mark_checked_today(root: Path) -> None:
    path = _update_check_state_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"last_checked": date.today().isoformat()}) + "\n", encoding="utf-8")
    except OSError:
        pass


def _remote_update_available(root: Path) -> Optional[bool]:
    """None if the check could not be made at all (no source/commit recorded, no network, the
    source is not a git remote/repo, or it took too long) -- always silent in that case, never a
    reported error (module docstring: a SessionStart check fails open). True/False otherwise.

    Only ever called from _run_update_check_worker(), i.e. inside the detached background
    process _spawn_update_check_worker() starts -- never directly from the SessionStart hook, so
    however long `git ls-remote` actually takes here never delays a session (see the header
    comment above _pulled_without_update).

    stdout/stderr go to a real temp file, not a pipe: `subprocess.run(capture_output=True, ...)`
    was measured at 21s against an unreachable address on Windows even with `timeout=5`, because
    a grandchild process git spawns (e.g. for the ssh transport) can keep the write end of the
    pipe open past the point `timeout` kills the immediate `git` process, and `communicate()`
    then blocks reading from that still-open pipe until the grandchild itself gives up. Waiting
    on a real file's process exit status has no such pipe to drain, so the timeout is enforced
    as written. GIT_TERMINAL_PROMPT/GCM_INTERACTIVE/GIT_SSH_COMMAND keep git from ever pausing
    for a credential prompt or a slow ssh handshake in an unattended background process."""
    lock = actlib.read_lock()
    template = lock.get("template") or {}
    source = template.get("source") or ""
    commit = template.get("commit") or ""
    if not source or not commit:
        return None
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes -o ConnectTimeout=3")
    try:
        with tempfile.TemporaryDirectory(prefix="act-update-check-") as tmp_dir:
            out_path = Path(tmp_dir) / "ls-remote.out"
            with open(out_path, "wb") as out_file:
                result = subprocess.run(
                    ["git", "ls-remote", "--", source, "HEAD"],
                    cwd=root, stdout=out_file, stderr=subprocess.DEVNULL,
                    timeout=5, env=env,
                    # no console window for git.exe on Windows, where the worker has none
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            if result.returncode != 0:
                return None
            output = out_path.read_text(encoding="utf-8", errors="replace").strip()
    except (OSError, subprocess.TimeoutExpired):
        return None
    if not output:
        return None
    remote_commit = output.split()[0].strip()
    return bool(remote_commit) and remote_commit != commit


def _update_check_result_path(root: Path) -> Path:
    return root / ".act-local" / "update-check-result.json"


def _consume_pending_update_note(root: Path) -> Optional[str]:
    """Reads and deletes .act-local/update-check-result.json, written by a previous
    _run_update_check_worker() run (see _spawn_update_check_worker) -- consuming it means the
    note surfaces exactly once, on the first SessionStart after the background check finished,
    same as the old synchronous check only ever reported it once (the run that found it). Silent
    on any I/O problem; a missing file (nothing pending) is the common case, not an error."""
    path = _update_check_result_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        path.unlink()
    except OSError:
        pass
    if isinstance(data, dict) and data.get("available"):
        return "[act] note: a template update is available -- run `python .act/scripts/update.py`"
    return None


def _run_update_check_worker(root: Path) -> int:
    """Body of the detached background process _spawn_update_check_worker() launches: the actual
    network lookup, isolated from the SessionStart hook so its result can only ever help the
    *next* session, never delay this one. Writes update-check-result.json on a conclusive
    True/False; leaves any existing file alone on None (inconclusive), so a stale-but-valid
    earlier result is not clobbered by a run that itself couldn't tell. Always exits 0 -- nothing
    reads this process's own exit code, and every exception here must stay inside this process."""
    try:
        available = _remote_update_available(root)
    except Exception:
        return 0
    if available is None:
        return 0
    try:
        path = _update_check_result_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"available": bool(available)}) + "\n", encoding="utf-8")
    except OSError:
        pass
    return 0


def _spawn_update_check_worker(root: Path) -> None:
    """Fire-and-forget: launches this same script as a fully detached background process running
    _run_update_check_worker(root) (dispatched via main()'s "_update-check-worker" internal
    event, never a real harness hook event) and returns immediately without waiting on it. Its
    stdin/stdout/stderr all go to DEVNULL, never a pipe back to this process -- a pipe here would
    reintroduce exactly the blocking this exists to avoid, just one level up. Best-effort: a
    failure to spawn is silent, same as every other note in this check."""
    script = Path(__file__).resolve()
    args = [sys.executable, str(script), "_update-check-worker", str(root)]
    try:
        if sys.platform == "win32":
            subprocess.Popen(
                args, cwd=root,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP,
                close_fds=True,
            )
        else:
            subprocess.Popen(
                args, cwd=root,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True, close_fds=True,
            )
    except OSError:
        pass


def _check_update_awareness(root: Path, config: dict[str, str]) -> tuple[list[str], list[str]]:
    """Check 2b's two notes, gated by the single `update-check` row (docs/ai/config.md § Checks,
    default "block" == on; "off" skips both notes and never spawns the background worker below).

    Returns (pre_notes, post_notes) -- pre_notes belong before the fixed-format status line,
    post_notes after it (module docstring / SessionStart output format): the pulled-without-
    update note is local, cheap and synchronous, so it stays a pre_note like before; the remote
    "update available" note is now always a *previous* run's finding (see _spawn_update_check_
    worker below), so it prints as a postscript after the status line rather than ahead of it.

    The remote lookup itself is throttled to once a day via .act-local/update-check.json
    (gitignored, per-checkout): when not yet checked today, this kicks off a detached background
    process (_spawn_update_check_worker) and marks today as checked immediately, without waiting
    for that process -- its result, if any, is picked up by _consume_pending_update_note() on a
    later SessionStart. Never raises."""
    mode = _check_mode(config, "update-check", default="block")
    if mode == "off":
        return [], []
    pre_notes: list[str] = []
    post_notes: list[str] = []
    if _pulled_without_update(root):
        pre_notes.append("[act] note: .act/ was pulled in without update.py -- run `python .act/scripts/update.py` (or --catch-up) to finish it")
    pending = _consume_pending_update_note(root)
    if pending:
        post_notes.append(pending)
    if not _already_checked_today(root):
        _mark_checked_today(root)
        _spawn_update_check_worker(root)
    return pre_notes, post_notes


# ---------------------------------------------------------------------------
# Orchestrator-only rules (.act/rules/orchestrator/) — delivered as SessionStart hook context,
# never @-imported into docs/ai/rules.md, so a sub-agent (which only ever loads that file) never
# sees them. See the "Overrides" note on _read_rule_states for the docs/ai/rules.md syntax this
# reads.
# ---------------------------------------------------------------------------

_CHECKBOX_RE = re.compile(r"^\s*-\s*\[([ xX])\]\s*`(R-[\w-]+)`")
_OVERRIDE_RE = re.compile(r"^-?\s*replaces\s+`(R-[\w-]+)`\s*:\s*(.+)$", re.IGNORECASE)
_SECTION_HEADING_RE = re.compile(r"^##\s+(.*)$")
_RULE_ID_IN_TEXT_RE = re.compile(r"`(R-[\w-]+)`")


def _read_rule_states(root: Path) -> tuple[dict[str, bool], dict[str, str]]:
    """
    Parse docs/ai/rules.md (the project's own copy, generated from .act/bridges/rules.md and free
    to be hand-edited afterwards) for two things:

      - enabled: rule id -> False for every "- [ ] `R-id`" checkbox found anywhere in the file.
        A rule id never mentioned there at all is on by default, so a template update that adds a
        new rule takes effect without the project having to touch this file.
      - overrides: rule id -> replacement text, read from a line of the form
        "replaces `R-id`: <text>" (the skeleton ships this as an HTML-commented example under
        "## Overrides"; a real override is an uncommented line in that same shape, so any line
        starting with "<!--" is skipped here rather than matched).

    Returns ({}, {}) if the file is missing or unreadable — nothing found means nothing to filter
    on, not an error.
    """
    path = root / "docs" / "ai" / "rules.md"
    enabled: dict[str, bool] = {}
    overrides: dict[str, str] = {}
    if not path.is_file():
        return enabled, overrides
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return enabled, overrides

    for line in lines:
        checkbox_match = _CHECKBOX_RE.match(line)
        if checkbox_match:
            mark, rule_id = checkbox_match.groups()
            enabled[rule_id] = mark.strip().lower() == "x"
            continue
        stripped = line.strip()
        if stripped.startswith("<!--"):
            continue  # the skeleton's own placeholder example, never a real override
        override_match = _OVERRIDE_RE.match(stripped)
        if override_match:
            rule_id, text = override_match.groups()
            overrides[rule_id] = text.strip()
    return enabled, overrides


def _filter_orchestrator_file(
    text: str, enabled: dict[str, str], overrides: dict[str, str]
) -> tuple[str, int]:
    """
    Split one .act/rules/orchestrator/*.md file into its "## " sections. A section whose heading
    carries a `R-...` id (every actual rule) is dropped when that id is off in `enabled` and has
    no entry in `overrides`; if it has one, the override text replaces the section body. A
    section without an id in its heading (the file's title/intro, a plain reference table such as
    "Role assignment" in 00-role.md) is never gated and always kept.

    Returns (filtered_text, rule_count): the filtered file, and how many gated sections survived
    (original or overridden) — the caller sums this across files for the status line.
    """
    lines = text.splitlines()
    kept: list[str] = []
    rule_count = 0

    section_lines: Optional[list[str]] = None
    section_rule_id: Optional[str] = None

    def _flush() -> None:
        nonlocal section_lines, section_rule_id, rule_count
        if section_lines is None:
            return
        if section_rule_id is None:
            kept.extend(section_lines)
        elif enabled.get(section_rule_id, True):
            kept.extend(section_lines)
            rule_count += 1
        elif section_rule_id in overrides:
            heading = section_lines[0] if section_lines else f"## `{section_rule_id}`"
            kept.append(f"{heading} (project override)")
            kept.append("")
            kept.append(overrides[section_rule_id])
            rule_count += 1
        # else: off, no override on file -> section dropped entirely
        section_lines = None
        section_rule_id = None

    preamble: list[str] = []
    in_section = False
    for line in lines:
        heading_match = _SECTION_HEADING_RE.match(line)
        if heading_match:
            _flush()
            in_section = True
            section_lines = [line]
            id_match = _RULE_ID_IN_TEXT_RE.search(heading_match.group(1))
            section_rule_id = id_match.group(1) if id_match else None
            continue
        if in_section:
            section_lines.append(line)
        else:
            preamble.append(line)
    _flush()

    return "\n".join(preamble + kept).rstrip("\n") + "\n", rule_count


def _deliver_orchestrator_rules(root: Path, config: dict[str, str]) -> Optional[int]:
    """
    Read every .act/rules/orchestrator/*.md file, in ascending filename order, filter it through
    _read_rule_states/_filter_orchestrator_file, and print what survives as SessionStart hook
    context — the one channel this template has that reaches only the main session (a sub-agent
    only ever sees docs/ai/rules.md, and these files are deliberately not @-imported there; see
    .act/bridges/rules.md).

    Returns None (and prints nothing) if the check is off or the directory does not exist yet —
    an older checkout, or a build stage before this directory was added, does nothing here rather
    than erroring. Otherwise returns the number of rules delivered (0 if every one was checked
    off), for the caller's status line.

    "block" and "warn" behave the same here: unlike the other two checks, this one has no side
    effect to withhold under "warn" — it only ever prints hook context, never writes a file — so
    both non-off values simply deliver the filtered rules.
    """
    mode = _check_mode(config, "orchestrator-rules", default="block")
    if mode == "off":
        return None

    rules_dir = root / ".act" / "rules" / "orchestrator"
    if not rules_dir.is_dir():
        return None

    enabled, overrides = _read_rule_states(root)
    total = 0
    blocks: list[str] = []
    for path in sorted(rules_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        filtered, count = _filter_orchestrator_file(text, enabled, overrides)
        total += count
        if count:
            blocks.append(filtered.rstrip("\n"))

    if blocks:
        print("[act] orchestrator rules (main session only, not seen by sub-agents):")
        print()
        print("\n\n".join(blocks))
        print()
    return total


def refresh_session(payload: dict) -> int:
    """Check 2: runs only for SessionStart. Never fails the session — every sub-step is best
    effort and swallows its own errors; the fixed-format status line always comes right after
    every other note except one deliberate postscript: an "update available" note, which is
    always a previous run's background finding and prints after the status line (see
    _check_update_awareness's pre_notes/post_notes split)."""
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

    # Role bridges (.claude/agents/*.md): only the `model`/`effort` frontmatter pair is refreshed
    # here, never the rest of the file — see tiers.py's refresh_project_bridge_frontmatter() and
    # 13-model-tiers.md § "Pflege der Zuordnungstabelle" for why this differs from _refresh_bridges
    # above, which replaces a whole file or leaves it alone.
    role_frontmatter_changed: list[str] = []
    tier_notes: list[str] = []
    try:
        role_frontmatter_changed = tiers.refresh_project_bridge_frontmatter(root, apply=(mode == "block"), notes=tier_notes)
    except Exception:
        pass
    if mode == "warn":
        for dest_rel in role_frontmatter_changed:
            print(f"[act] note: {dest_rel} model/effort would be refreshed from tiers.json/config.md (warn mode, not applied)")
    # An unknown tier/reasoning value (config.md § Roles or tiers.json) is reported once here as a
    # single line, whatever the role count — previously this only ever surfaced in init.py/
    # update.py's own notes, never at session start (Q29).
    if tier_notes:
        print("[act] note: " + "; ".join(tier_notes))

    post_update_notes: list[str] = []
    try:
        pre_update_notes, post_update_notes = _check_update_awareness(root, config)
        for note in pre_update_notes:
            print(note)
    except Exception:
        pass  # template-awareness is informational only, must never block the session

    rules_delivered: Optional[int] = None
    try:
        rules_delivered = _deliver_orchestrator_rules(root, config)
    except Exception:
        pass  # a broken rules delivery must not block the session

    inbox_part = f" · inbox: {waiting} waiting" if waiting else ""
    rules_part = f" · rules: {rules_delivered}" if rules_delivered is not None else ""
    roles_part = f" · role-bridges refreshed: {len(role_frontmatter_changed)}" if mode == "block" and role_frontmatter_changed else ""
    print(f"[act] branch={branch}{inbox_part} · board updated{rules_part}{roles_part}")
    # Printed after the status line, not before: an "update available" note here is always a
    # previous SessionStart's background finding (_consume_pending_update_note), never something
    # this run just checked, so it reads as a postscript rather than part of this run's status.
    for note in post_update_notes:
        print(note)
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    # "_update-check-worker" is the one exception to the "exactly one arg" harness contract
    # below: it is never a harness hook event, only what _spawn_update_check_worker() launches
    # (argv[1] is the project root as a string). Checked first so a stray extra argv entry here
    # can never fall through to "no event named".
    if len(argv) == 2 and argv[0] == "_update-check-worker":
        return _run_update_check_worker(Path(argv[1]))

    if len(argv) != 1:
        return 0  # no event named — nothing to dispatch, never an error for the caller

    event = argv[0]
    payload = _read_payload()

    if event == "PreToolUse":
        write_result = check_write_guard(payload)
        if write_result != 0:
            return write_result
        return check_worker_nesting_guard(payload)
    if event == "SessionStart":
        return refresh_session(payload)
    return 0  # unknown event — do nothing, exit 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
