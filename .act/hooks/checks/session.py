#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: SessionStart handling — inbox/questions "answered, not yet processed" count, bridge/
#          role-frontmatter re-derivation, board refresh, template-awareness notes (check 2b), the
#          active-topics status line, and the orchestrator-only rules delivered as hook context
#          (all gated by their own docs/ai/config.md row, see _check_mode). refresh_session() is
#          the single SessionStart entry point dispatch.py calls; everything below feeds into it.
#          Unlike the PreToolUse checks, this is not a list of independent pass/fail gates — every
#          sub-step is its own best-effort note or side effect, and refresh_session() must never
#          fail the session over any of them.

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import actlib
import manifest
import tiers

from .common import _check_mode

__all__ = [
    "_current_branch", "_STATUS_RE", "_count_inbox_waiting", "_count_questions_answered",
    "_refresh_board", "_BRIDGE_MAP", "_TOPIC_SWITCHES", "_active_topics",
    "_refresh_bridges", "_manifest_fingerprint", "_pulled_without_update",
    "_update_check_state_path", "_already_checked_today", "_mark_checked_today",
    "_remote_update_available", "_update_check_result_path", "_consume_pending_update_note",
    "_run_update_check_worker", "_spawn_update_check_worker", "_check_update_awareness",
    "_CHECKBOX_RE", "_OVERRIDE_RE", "_SECTION_HEADING_RE", "_RULE_ID_IN_TEXT_RE",
    "_read_rule_states", "_filter_orchestrator_file", "_deliver_orchestrator_rules",
    "refresh_session",
]

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


def _count_questions_answered(root: Path) -> int:
    """
    Count question entries (docs/ai/questions/*.md, one file per question, T43) whose header says
    `status: answered` — a person replied but the answer has not been worked into its place yet,
    the same "waiting" meaning _count_inbox_waiting() counts for the inbox (R-human-inbox-first).
    Excludes README.md. Header shape and field are identical to the inbox's own (see
    _STATUS_RE) — the difference is only the directory and, for a question, an `id:`/`status:`
    pair right above `# <title>` instead of `for:`/`status:`.

    Robust against a file that is not valid UTF-8: skipped rather than raised, same contract as
    _count_inbox_waiting()'s own OSError guard, plus UnicodeDecodeError specifically here since a
    question file is more likely to have been hand-edited outside the assistant.
    """
    questions_dir = root / "docs" / "ai" / "questions"
    if not questions_dir.is_dir():
        return 0
    count = 0
    for entry in questions_dir.glob("*.md"):
        if entry.name.lower() == "readme.md":
            continue
        try:
            lines = entry.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line in lines[:20]:
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
    reported error (dispatch.py's docstring: a SessionStart check fails open). True/False otherwise.

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
    """Fire-and-forget: launches dispatch.py as a fully detached background process running
    _run_update_check_worker(root) (dispatched via dispatch.main()'s "_update-check-worker"
    internal event, never a real harness hook event) and returns immediately without waiting on
    it. Its stdin/stdout/stderr all go to DEVNULL, never a pipe back to this process -- a pipe
    here would reintroduce exactly the blocking this exists to avoid, just one level up.
    Best-effort: a failure to spawn is silent, same as every other note in this check.

    The launched script is dispatch.py itself, not this module: `Path(__file__).resolve().parent`
    is .act/hooks/checks/, so its own `.parent` reaches .act/hooks/, where dispatch.py — the only
    file main() (and thus this internal event) is wired to — actually lives."""
    script = Path(__file__).resolve().parent.parent / "dispatch.py"
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
    post_notes after it (dispatch.py's docstring / SessionStart output format): the pulled-
    without-update note is local, cheap and synchronous, so it stays a pre_note like before; the
    remote "update available" note is now always a *previous* run's finding (see
    _spawn_update_check_worker below), so it prints as a postscript after the status line rather
    than ahead of it.

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


# ---------------------------------------------------------------------------
# Active topics at session start — a topic with a switch (logging, feedback, ...) only ever
# matters once its own switch is on (docs/project/concepts/ai-dev-app/03-core-rules.md § "Thema
# mit Schalter" in the template-pflege repo); this names, in the table's own order, which ones are
# active this session and where their rule file lives, so the orchestrator (and a human reading
# the transcript) can tell without opening docs/ai/config.md first.
# ---------------------------------------------------------------------------

_TOPIC_SWITCHES: tuple[tuple[str, str, Callable[[str], bool]], ...] = (
    ("logging", "logging", lambda value: value.strip().lower() == "on"),
    ("feedback", "feedback", lambda value: value.strip().lower() not in ("", "off")),
)


def _active_topics(root: Path, config: dict[str, str]) -> list[tuple[str, str]]:
    """(topic name, path to show) for every topic in _TOPIC_SWITCHES whose switch is active, in
    the table's own order. The path follows actlib.resolve()'s own local-over-template
    precedence (docs/ai/local/rules/topics/<name>.md wins over .act/rules/topics/<name>.md — the
    same rule every other override in this template follows, e.g. rules.py/doctor.py/init.py),
    shown relative to the project root; "missing" if neither exists (a switch turned on before
    the topic file was ever added to this template version, or one a project deleted by hand
    without turning the switch off — reported rather than silently skipped either way)."""
    active: list[tuple[str, str]] = []
    for name, config_key, is_active in _TOPIC_SWITCHES:
        if not is_active(config.get(config_key, "")):
            continue
        resolved = actlib.resolve(f"rules/topics/{name}.md")
        if resolved is None:
            active.append((name, "missing"))
        else:
            path, _origin = resolved
            active.append((name, path.relative_to(root).as_posix()))
    return active


def refresh_session(payload: dict) -> int:
    """Check 2: runs only for SessionStart. Never fails the session — every sub-step is best
    effort and swallows its own errors; the fixed-format status line always comes right after
    every other note except two deliberate exceptions: the "topics active" line, printed first of
    all and even when `session-start-refresh` is "off" (see the comment above _active_topics()'s
    call below), and an "update available" note, which is always a previous run's background
    finding and prints after the status line (see _check_update_awareness's pre_notes/post_notes
    split)."""
    config = actlib.read_config()

    try:
        root = actlib.repo_root()
    except RuntimeError:
        return 0  # not inside a template-managed project — nothing to report

    # Printed ahead of the session-start-refresh on/off/warn gate below, and regardless of it: a
    # topic's own switch (docs/ai/config.md § Logging/Feedback), not this check, decides whether
    # it is active, and its rule file has to be named either way — "session-start-refresh: off"
    # only turns off the bridge/board/rules re-derivation this function does, not topic awareness.
    try:
        topics = _active_topics(root, config)
    except Exception:
        topics = []
    if topics:
        print("[act] topics active: " + ", ".join(f"{name} ({path})" for name, path in topics))

    mode = _check_mode(config, "session-start-refresh", default="block")
    if mode == "off":
        return 0

    branch = _current_branch(root)

    waiting = 0
    try:
        waiting += _count_inbox_waiting(root)
    except Exception:
        pass
    try:
        waiting += _count_questions_answered(root)
    except Exception:
        pass

    # T42: whether a feedback reminder to the template author is due right now
    # (.act/scripts/feedback.py --due's own logic) — folded into the status line like the inbox
    # count above, and counted as an "open point" that silences the tip/reminder line below (same
    # reasoning as inbox/questions: the thing that is waiting comes first, self-promotion later).
    # Imported lazily and wrapped in its own try/except, like every other sub-step in this
    # function — a broken tips.py must never take the session-start hook down with it.
    feedback_due = False
    try:
        from . import tips as _tips
        feedback_due = _tips.is_feedback_due(root)
    except Exception:
        feedback_due = False

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
    feedback_part = " · feedback due" if feedback_due else ""
    print(f"[act] branch={branch}{inbox_part}{feedback_part} · board updated{rules_part}{roles_part}")
    # Printed after the status line, not before: an "update available" note here is always a
    # previous SessionStart's background finding (_consume_pending_update_note), never something
    # this run just checked, so it reads as a postscript rather than part of this run's status.
    for note in post_update_notes:
        print(note)
    # T42: at most one line, last of all — either a due reminder from docs/ai/local/reminders.md
    # (user's own, always checked first) or a rotated .act/tips.md tip (config.md § Tips),
    # silenced by `output-depth: sparse` and by any open point above (inbox/questions/feedback
    # due) inside tips.session_line() itself. Same lazy-import-and-swallow pattern as every other
    # sub-step here.
    try:
        from . import tips as _tips
        tip_line = _tips.session_line(payload, root, config, waiting + (1 if feedback_due else 0))
    except Exception:
        tip_line = None
    if tip_line:
        print(tip_line)
    return 0
