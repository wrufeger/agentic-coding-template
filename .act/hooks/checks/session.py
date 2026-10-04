#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: SessionStart handling — inbox "answered, not yet processed" count (the single inbox at
#          docs/ai/inbox/, all kinds — question/todo/report/note),
#          bridge/role-frontmatter re-derivation, board refresh, sync of the files that
#          hang on a
#          docs/ai/config.md value — skill copies, CLAUDE.md and hook entries on `tools`, a role's
#          bridges on its "## Roles" row (tier/reasoning/model) — when one moved since the last
#          snapshot (see update.sync_dependent_files(), imported lazily at that one
#          call site so a session start
#          never pays for/depends on `update`'s own imports — entries, rules, ... — just for this
#          best-effort sub-step), template-awareness notes (check 2b), the active-topics
#          status line, the import check and, only as a fallback, a short form of the
#          orchestrator-only rules when docs/ai/rules.md does not import them (all gated by
#          their own docs/ai/config.md row, see _check_mode). refresh_session() is
#          the single SessionStart entry point dispatch.py calls; everything below feeds into it.
#          Unlike the PreToolUse checks, this is not a list of independent pass/fail gates — every
#          sub-step is its own best-effort note or side effect, and refresh_session() must never
#          fail the session over any of them.

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import actlib
import manifest
import tiers

from .common import _check_mode
from .danger_scan import _security_check_level

__all__ = [
    "_current_branch", "_STATUS_RE", "_count_inbox_waiting",
    "_DOCS_AUDIT_TITLE_PREFIX", "_LEDGER_HEADING_RE", "_LEDGER_CREATED_RE",
    "_LEDGER_DATE_IN_NAME_RE", "_parse_docs_audit_due", "_ledger_entry_date",
    "_last_ledger_entry_with_prefix", "_last_docs_audit_entry", "_commits_since", "_docs_audit_note",
    "_DEPENDENCY_CHECK_TITLE_PREFIX", "_DEPENDENCY_CHECK_DUE_DAYS", "_dependency_check_note",
    "_refresh_board", "_BRIDGE_MAP", "_TOPIC_SWITCHES", "_IDE_SERVER_NAME_HINTS",
    "_IDE_SERVER_EXACT_NAMES", "_is_ide_server_name", "_servers_match_ide_hint", "_user_mcp_servers",
    "_same_project_path", "_ide_mcp_connected", "_active_topics",
    "_bootstrap_marker", "_first_line", "_is_bootstrap_copy",
    "_refresh_bridges", "_manifest_fingerprint", "_pulled_without_update",
    "_update_check_state_path", "_already_checked_today", "_mark_checked_today",
    "_remote_update_available", "_update_check_result_path", "_consume_pending_update_note",
    "_run_update_check_worker", "_spawn_update_check_worker", "_check_update_awareness",
    "_security_scan_state_path", "_security_scan_already_checked_today",
    "_mark_security_scan_checked_today", "_security_scan_result_path", "_run_security_scan_worker",
    "_spawn_security_scan_worker", "_consume_pending_security_scan_note",
    "_check_security_scan_awareness",
    "_CHECKBOX_RE", "_OVERRIDE_RE", "_SECTION_HEADING_RE", "_RULE_ID_IN_TEXT_RE",
    "_read_rule_states", "_filter_orchestrator_file", "_deliver_orchestrator_rules",
    "_chat_language_line", "_orchestrator_short_lines", "_orchestrator_rules_imported",
    "CONTEXT_LIMIT", "_fit_context", "_human_line", "_old_imports_note", "_changed_bridge_note",
    "_ideas_pending", "_ideas_note", "_ideas_ensure_notes",
    "refresh_session",
]

# ---------------------------------------------------------------------------
# Check 2 — session start: inbox count, bridge re-derivation, board refresh,
#           orchestrator-only rules as a fallback short form
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
    Count inbox entries that are "answered, not yet processed": a file in actlib.INBOX_DIR (the
    single inbox, one file per entry, every kind — question/todo/report/note)
    whose header says `status: answered`.

    The header carries `for:` (who it is addressed to, absent for a question), `kind:`, and for a
    question an `id:` too — none of which matter here, only `status:` does. `status` runs `open`
    -> `answered` -> `done` (a question keeps that same lifecycle; it used to live
    under docs/ai/questions/, which no longer exists): the human
    (or the assistant, when the answer came up in chat) sets `answered`, and whoever works the
    entry into its place sets `done`. Only `answered` is counted — `open` is still waiting on a
    person, `done` is finished and never appears here. This one count now covers what used
    to be two separate counts (inbox entries and questions) before the two lived in one place.
    """
    inbox_dir = root / actlib.INBOX_DIR
    if not inbox_dir.is_dir():
        return 0
    count = 0
    for entry in inbox_dir.glob("*.md"):
        if entry.name.lower() == "readme.md":
            continue
        try:
            lines = entry.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line in lines[:20]:  # header fields live at the top of the file
            match = _STATUS_RE.match(line.strip())
            if match:
                if match.group(1).strip().lower() == "answered":
                    count += 1
                break
    return count


# ---------------------------------------------------------------------------
# Docs-audit freshness at session start: a hint, never a blocker, on how long ago the
# last full `act-audit-docs` sweep ran (skills/act-audit-docs/SKILL.md: a full pass logs a journal
# entry whose title starts with "act-audit-docs", a spot check of one area does not). "Full" is
# decided purely by that title prefix, never by which files a partial pass touched.
# ---------------------------------------------------------------------------

_DOCS_AUDIT_TITLE_PREFIX = "act-audit-docs"
_LEDGER_HEADING_RE = re.compile(r"^#\s+(.*)$")
_LEDGER_CREATED_RE = re.compile(r"^created:\s*(.+)$", re.IGNORECASE)
_LEDGER_DATE_IN_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")


def _parse_docs_audit_due(raw: str) -> "tuple[int, int]":
    """Parse the `docs-audit-due` value (docs/ai/config.md § Docs audit), e.g. "30d/100c" -> (30,
    100). Falls back to the template default (30, 100) for a missing or malformed value -- same
    "an unrecognized value is treated as absent" rule _check_mode follows for the block/warn/off
    checks, just for a value shape of its own."""
    match = re.match(r"^\s*(\d+)\s*d\s*/\s*(\d+)\s*c\s*$", raw, re.IGNORECASE)
    if not match:
        return 30, 100
    return int(match.group(1)), int(match.group(2))


def _ledger_entry_date(lines: list[str], filename: str) -> Optional[date]:
    """The date a journal entry counts as made on: the `created:` header field
    (entries.py writes an ISO timestamp there) if present and parseable, else the
    `YYYY-MM-DD-` date prefix every ledger filename carries (entries.py new ledger <title>).
    None if neither yields a usable date."""
    for line in lines[:5]:  # created: is always the first line
        created_match = _LEDGER_CREATED_RE.match(line.strip())
        if created_match:
            try:
                return datetime.fromisoformat(created_match.group(1).strip()).date()
            except ValueError:
                break
    name_match = _LEDGER_DATE_IN_NAME_RE.match(filename)
    if name_match:
        try:
            return date.fromisoformat(name_match.group(1))
        except ValueError:
            return None
    return None


def _last_ledger_entry_with_prefix(root: Path, title_prefix: str) -> "tuple[Optional[date], bool]":
    """(most recent date of a journal entry whose `# ` heading starts with `title_prefix`, whether
    the ledger directory exists at all). None as the date means either the directory does not
    exist, or it exists but holds no matching entry -- the caller tells the two apart via the
    second element. Shared by `_docs_audit_note` (prefix `act-audit-docs`) and the
    `dependency-check: regularly` staleness note (prefix `act-deps`) rather than each
    keeping its own copy of the same ledger scan.

    Filters by filename first (the ledger filename carries the same slug the heading does,
    `entries.py new ledger <title>`) before reading a file in full: with a project of any size,
    reading every ledger entry just to check its heading is wasteful when the filename already
    rules almost all of them out."""
    ledger_dir = root / "docs" / "ai" / "work" / "ledger"
    if not ledger_dir.is_dir():
        return None, False
    slug_start = title_prefix.lower().replace(" ", "-")
    best: Optional[date] = None
    for path in ledger_dir.glob("*.md"):
        if path.name.lower() == "readme.md":
            continue
        name_lower = path.name.lower()
        # entries.py new ledger <title> names the file "<YYYY-MM-DD>-<slug>.md" -- the slug (the
        # title, lowercased/hyphenated) follows the date prefix, so a filename that does not
        # contain the wanted slug at all cannot hold a matching heading either.
        if slug_start not in name_lower:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        title: Optional[str] = None
        for line in lines:
            heading_match = _LEDGER_HEADING_RE.match(line)
            if heading_match:
                title = heading_match.group(1).strip()
                break
        if title is None or not title.startswith(title_prefix):
            continue
        when = _ledger_entry_date(lines, path.name)
        if when is not None and (best is None or when > best):
            best = when
    return best, True


def _last_docs_audit_entry(root: Path) -> "tuple[Optional[date], bool]":
    """(most recent date of a full act-audit-docs sweep, whether the ledger directory exists at
    all) -- see `_last_ledger_entry_with_prefix`."""
    return _last_ledger_entry_with_prefix(root, _DOCS_AUDIT_TITLE_PREFIX)


def _commits_since(root: Path, when: date) -> int:
    """Number of commits on HEAD authored since `when` (inclusive of that day) -- 0 on any error
    (no git, not a repository, timeout): silence over a wrong number, same as every other
    best-effort sub-step in this module."""
    try:
        # A bare "--since=YYYY-MM-DD" is parsed against the current time of day (review finding
        # c) -- a commit made earlier *today*, before this hook's own clock time, would otherwise
        # be silently excluded from "since `when`". Pinning the time to midnight makes the whole
        # of `when`'s day count, matching what a human reading "since 2026-08-01" expects.
        result = subprocess.run(
            ["git", "rev-list", "--count", f"--since={when.isoformat()}T00:00:00", "HEAD"],
            cwd=root, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    if result.returncode != 0:
        return 0
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def _docs_audit_note(root: Path, config: dict[str, str]) -> Optional[str]:
    """One-time-per-state hint (never a blocker): how long ago the last full
    `act-audit-docs` sweep ran, in days and commits, once either exceeds the `docs-audit-due`
    threshold; or, once only, that there is no such entry on record yet at all. Only while
    `docs/project/` exists -- nothing to audit otherwise, so neither note fires without it (review
    finding b: the docstring already said this, the "overdue" branch did not actually check it).
    `off` skips the whole check.

    The overdue note is throttled to once a day (review finding a: config.md calls it a "one-time
    note", but a session start recurs many times a day -- including a resume/compact, which is not
    a fresh session in any way that matters here) via `.act-local/cache.json`'s
    `docs_audit_overdue_last_noted`, the same per-day-state pattern `_check_update_awareness`'s
    `_already_checked_today` uses for its own once-a-day network check."""
    if not (root / "docs" / "project").is_dir():
        return None
    raw = config.get("docs-audit-due", "").strip()
    if raw.lower() == "off":
        return None
    days_due, commits_due = _parse_docs_audit_due(raw)

    when, _ledger_exists = _last_docs_audit_entry(root)
    if when is None:
        cache = actlib.read_cache()
        if cache.get("docs_audit_never_noted"):
            return None
        actlib.write_cache({"docs_audit_never_noted": True})
        return "[act] note: no full docs audit on record yet -- act-audit-docs when convenient"

    age_days = (date.today() - when).days
    commits_since = _commits_since(root, when)
    if age_days <= days_due and commits_since <= commits_due:
        return None
    cache = actlib.read_cache()
    today = date.today().isoformat()
    if cache.get("docs_audit_overdue_last_noted") == today:
        return None
    actlib.write_cache({"docs_audit_overdue_last_noted": today})
    return (f"[act] note: docs last fully audited {age_days} days / {commits_since} commits ago "
            "-- act-audit-docs when convenient")


# ---------------------------------------------------------------------------
# `dependency-check: regularly` staleness note at session start: same shape as
# `_docs_audit_note` above (fixed 30-day threshold, no commit count -- `act-deps` has no config.md
# knob for that), reusing `_last_ledger_entry_with_prefix` instead of its own ledger scan.
# ---------------------------------------------------------------------------

_DEPENDENCY_CHECK_TITLE_PREFIX = "act-deps"
_DEPENDENCY_CHECK_DUE_DAYS = 30


def _dependency_check_note(root: Path, config: dict[str, str]) -> Optional[str]:
    """With `dependency-check: regularly`, a note (at most once a day, per state, same pattern as
    `_docs_audit_note`'s own overdue note) once the last `act-deps` run (a journal entry titled
    `act-deps: ...`) is older than 30 days, or once only when none is on record yet. `never` and
    `once` (the skeleton default) print nothing here: `once` is entirely init.py's one-time inbox
    entry (`actlib.write_dependency_check_note`), not a recurring session-start note."""
    mode = config.get("dependency-check", "once").strip().lower()
    if mode != "regularly":
        return None
    when, _ledger_exists = _last_ledger_entry_with_prefix(root, _DEPENDENCY_CHECK_TITLE_PREFIX)
    cache = actlib.read_cache()
    if when is None:
        if cache.get("dependency_check_never_noted"):
            return None
        actlib.write_cache({"dependency_check_never_noted": True})
        return ("[act] note: no `act-deps` run on record yet -- act-deps when convenient "
                "(dependency-check: regularly)")
    age_days = (date.today() - when).days
    if age_days <= _DEPENDENCY_CHECK_DUE_DAYS:
        return None
    today = date.today().isoformat()
    if cache.get("dependency_check_overdue_last_noted") == today:
        return None
    actlib.write_cache({"dependency_check_overdue_last_noted": today})
    return (f"[act] note: last act-deps run {age_days} days ago -- act-deps when convenient "
            "(dependency-check: regularly)")


def _refresh_board(root: Path) -> None:
    """Run .act/scripts/board.py if it exists yet (a parallel task builds it); do nothing,
    silently, otherwise — per the build order for this script."""
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


def _bootstrap_marker() -> Optional[str]:
    """init.py's TEMPLATE_BOOTSTRAP_MARKER (the first line "<!-- act:bootstrap -->" a bare
    template clone's own root CLAUDE.md/AGENTS.md carry before `init` ever runs),
    imported lazily like `update`/`rules` elsewhere in this module so a session start never pays
    for init.py's own (much larger) import cost unless this one constant is actually needed.
    None if init.py cannot be imported at all -- the caller then treats every bootstrap check as
    "not a bootstrap file", the same fail-open stance every other best-effort note here takes."""
    try:
        from init import TEMPLATE_BOOTSTRAP_MARKER  # deferred: see the header comment
    except Exception:
        return None
    return TEMPLATE_BOOTSTRAP_MARKER


def _first_line(path: Path) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.readline().strip()
    except OSError:
        return ""


def _is_bootstrap_copy(dest_path: Path, lock_present: bool, marker: Optional[str]) -> bool:
    """True when `dest_path` is not the project's own CLAUDE.md/AGENTS.md but a copy of the
    template's own bootstrap file (first line `marker`) that landed on top of it -- a raw `git
    pull` of the template's shared history bringing in its root entry files verbatim rather than
    going through `update.py`. Only meaningful once the project is actually set up
    (`.act-lock.json` present, `lock_present`): a bare clone not yet run through `init` legitimately
    still carries the marker on its own root files, and those are `init`'s job to replace, not
    this one's (see `_bootstrap_entry_files` in init.py)."""
    if not lock_present or marker is None:
        return False
    return _first_line(dest_path) == marker


def _refresh_bridges(root: Path, write: bool) -> tuple[list[str], list[str], list[str]]:
    """
    Re-derive every generated bridge that is still exactly as it was last generated (current
    hash matches .act-local/cache.json) from its .act/bridges/ source — this stands in for a
    registered `merge=ours` driver (see .act/bridges/gitattributes), which needs a per-machine
    `git config` no checkout is guaranteed to have. A bridge whose hash no longer matches was
    edited locally and is left untouched either way.

    One exception: a root CLAUDE.md/AGENTS.md that is not locally edited at all but a raw
    copy of the *template's own* bootstrap file (see `_is_bootstrap_copy`) never counts as "edited
    locally" — it never was the project's file to begin with, whatever its recorded hash says — so
    it is rewritten from the template source the same as an unchanged bridge, just reported
    separately (`bootstrapped`) rather than folded into `refreshed`.

    With `write=False` (check-mode-`warn`), nothing is written — the "refreshed"/"bootstrapped"
    lists report what would have changed instead.

    Returns (changed, refreshed, bootstrapped): `changed` are destinations left alone because
    they were edited locally; `refreshed` are destinations re-derived from the template (or that
    would have been, under write=False) because they still matched their last-generated hash;
    `bootstrapped` are destinations re-derived because they turned out to be the template's own
    bootstrap file instead (or that would have been, under write=False).

    Each file is written and cached individually rather than batching the cache write
    until after the whole loop — a read/write failure partway through the map (a locked file, a
    permission error) used to leave every file processed *before* the failure both unrecorded in
    the cache and outside the caller's `touched` list (built from `refreshed`, since that append
    happened before the write was even attempted), so a bridge the update genuinely rewrote never
    made it into the commit and then looked "edited locally" at every later run because its
    recorded hash never caught up with what was actually on disk. Now a failure on one file only
    ever costs that one file (left for the next run to retry, its old recorded hash still
    matching its unwritten content) — every file already written stays written, cached, and
    reported.
    """
    cache = actlib.read_cache()
    generated = cache["generated"]
    changed: list[str] = []
    refreshed: list[str] = []
    bootstrapped: list[str] = []
    lock_present = (root / ".act-lock.json").is_file()
    marker = _bootstrap_marker()

    for dest_rel, source_name in _BRIDGE_MAP.items():
        dest_path = root / dest_rel
        source_path = root / ".act" / "bridges" / source_name
        if not dest_path.is_file() or not source_path.is_file():
            continue  # not generated yet, or template source missing — nothing to do here

        recorded_hash = generated.get(dest_rel)
        if recorded_hash is None:
            continue  # never tracked as generated — not ours to touch

        is_bootstrap = _is_bootstrap_copy(dest_path, lock_present, marker)

        # Compared with line endings normalized (and still accepts an older, raw-byte
        # recorded hash) so a checkout's own line endings never make an untouched bridge look
        # "changed locally" on their own. Skipped for a bootstrap copy: its hash never
        # matches the recorded one either, but that mismatch is not a local edit to preserve.
        if not is_bootstrap and not actlib.generated_unchanged(dest_path, recorded_hash):
            changed.append(dest_rel)
            continue

        target_list = bootstrapped if is_bootstrap else refreshed

        if not write:
            target_list.append(dest_rel)
            continue

        try:
            content = source_path.read_text(encoding="utf-8")
            actlib.write_text_lf(dest_path, content)
            generated[dest_rel] = actlib.generated_hash(dest_path)
        except (OSError, UnicodeDecodeError):
            continue  # left for the next run; every file already handled above stays reported
        target_list.append(dest_rel)
        actlib.write_cache({"generated": generated})

    return changed, refreshed, bootstrapped


# ---------------------------------------------------------------------------
# Check 2b — template awareness at session start: a project .act/ that was brought to a clean
# template state by something other than update.py (e.g. a plain `git pull` of the shared history
# some projects still keep from before the lock file recorded a manifest fingerprint), and, at most once a day, whether the template's own
# remote has moved past what .act-lock.json last recorded. Both read-only, both best-effort — see
# refresh_session()'s try/except around each call; neither ever raises out of this function.
# ---------------------------------------------------------------------------

def _manifest_fingerprint(act_dir: Path) -> str:
    """CRLF-folded fingerprint of act_dir/MANIFEST.json, matching what .act-lock.json's
    template.manifest_sha256 is meant to record -- unlike a raw `actlib.sha256_file()` of
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
    update.py/init.py run (`template.manifest_sha256`) -- the fingerprint that tells a
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


def _remote_update_available(root: Path) -> Optional[str]:
    """None if the check could not be made at all (no source/commit recorded, no network, the
    source is not a git remote/repo, or it took too long) -- always silent in that case, never a
    reported error (dispatch.py's docstring: a SessionStart check fails open). Otherwise the
    remote's current commit hash (which may equal the lock's own commit -- the caller decides
    what that means; see _run_update_check_worker).

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
    return remote_commit or None


def _update_check_result_path(root: Path) -> Path:
    return root / ".act-local" / "update-check-result.json"


def _consume_pending_update_note(root: Path) -> Optional[str]:
    """Reads and deletes .act-local/update-check-result.json, written by a previous
    _run_update_check_worker() run (see _spawn_update_check_worker) -- consuming it means the
    note surfaces exactly once, on the first SessionStart after the background check finished,
    same as the old synchronous check only ever reported it once (the run that found it). Silent
    on any I/O problem; a missing file (nothing pending) is the common case, not an error.

    The file only ever records `remote_commit` -- never a stale "available" flag by
    itself, so a project that ran `update.py` between the background check and this session
    doesn't get told about an update it already has: the note fires only if `remote_commit` still
    differs from the *current* lock's `template.commit`, re-read here rather than trusted from
    whatever the worker saw at the time."""
    path = _update_check_result_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        path.unlink()
    except OSError:
        pass
    if not isinstance(data, dict):
        return None
    remote_commit = data.get("remote_commit")
    if not remote_commit:
        return None
    lock = actlib.read_lock()
    current_commit = (lock.get("template") or {}).get("commit") or ""
    if remote_commit == current_commit:
        return None
    return "[act] note: a template update is available -- run `python .act/scripts/update.py`"


def _run_update_check_worker(root: Path) -> int:
    """Body of the detached background process _spawn_update_check_worker() launches: the actual
    network lookup, isolated from the SessionStart hook so its result can only ever help the
    *next* session, never delay this one. Writes update-check-result.json with the remote commit
    found; leaves any existing file alone when the lookup was inconclusive (None), so a
    stale-but-valid earlier result is not clobbered by a run that itself couldn't tell. Whether
    that remote commit still means "update available" is decided later, by
    _consume_pending_update_note() against the lock as it stands then -- not here, since this
    process's result may sit unread across more than one later `update.py` run. Always exits 0 --
    nothing reads this process's own exit code, and every exception here must stay inside this
    process."""
    try:
        remote_commit = _remote_update_available(root)
    except Exception:
        return 0
    if remote_commit is None:
        return 0
    try:
        path = _update_check_result_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"remote_commit": remote_commit}) + "\n", encoding="utf-8")
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
# Daily dependency-vulnerability scan at session start (`security-check: deps`/`full`,
# docs/ai/config.md § Checks): the same background-worker shape `_check_update_awareness` already
# established for the update check, reused here rather than a second polling mechanism —
# `security_scan.run_scan()` can itself take tens of seconds (a real network lookup through
# osv-scanner/npm/composer/pip-audit), which must never delay a session start any more than `git
# ls-remote` is allowed to (see `_remote_update_available`'s own docstring for the measured cost of
# getting this wrong).
# ---------------------------------------------------------------------------

def _security_scan_state_path(root: Path) -> Path:
    return root / ".act-local" / "security-scan-check.json"


def _security_scan_already_checked_today(root: Path) -> bool:
    try:
        data = json.loads(_security_scan_state_path(root).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and data.get("last_checked") == date.today().isoformat()


def _mark_security_scan_checked_today(root: Path) -> None:
    path = _security_scan_state_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"last_checked": date.today().isoformat()}) + "\n", encoding="utf-8")
    except OSError:
        pass


def _security_scan_result_path(root: Path) -> Path:
    return root / ".act-local" / "security-scan-result.json"


def _run_security_scan_worker(
    root: Path, state_hash: Optional[str] = None, lock_paths: "Optional[list[Path]]" = None,
) -> int:
    """Body of the detached background process `_spawn_security_scan_worker()` launches: the
    actual dependency-vulnerability scan, isolated from the SessionStart hook and from
    checks/deps_scan.py's own PreToolUse hook alike, so its result can only ever help a *later*
    check, never delay the one that triggered it (same reasoning as `_run_update_check_worker`'s
    own docstring). Two modes:
      - daily (root only): every lock file `security_scan.detect_lock_files` finds; writes
        `security-scan-result.json` (every unaccepted high/critical finding) for the SessionStart
        note — unchanged contract, severity/acceptance already filtered here;
      - request (`state_hash` plus `lock_paths`, spawned by checks/deps_scan.py for one commit):
        exactly those lock files and nothing else (2026-09-27 review 2, m7). The state hash is
        computed *before* the scan and again *after* it (`security_scan.lock_set_digest`); the
        result is recorded (`security_scan.write_result_cache`, under the before-hash) only when
        both agree — a lock file that changed while the tool ran gets no cached answer at all
        rather than the old content's answer filed under the new digest (review 2, C1). The
        running marker for `state_hash` is cleared on every exit path, so a later commit never
        waits on a run that is over.
    Always exits 0 — nothing reads this process's own exit code, and every exception here must
    stay inside this process (`Exception` is caught deliberately broad here, unlike a normal check:
    this is the one place nothing else can ever observe or log a failure, so silently doing nothing
    is the only available fallback — narrower, specific exceptions are used everywhere a caller
    could still see and act on one, per CR-python-basics)."""
    try:
        import security_scan  # deferred: a session start never pays for this unless actually used
    except ImportError:
        return 0
    if state_hash is not None:
        if not security_scan.is_state_hash(state_hash):
            return 0  # never our own spawn's argv -- and never a file name to touch
        try:
            paths = [Path(path) for path in (lock_paths or [])]
            before = security_scan.lock_set_digest(paths) if paths else None
            if before is not None:
                result = security_scan.run_scan(root, security_scan.lock_files_from_paths(paths))
                if security_scan.lock_set_digest(paths) == before:
                    security_scan.write_result_cache(root, before, result, [str(path) for path in paths])
        except Exception:  # noqa: BLE001 — see the docstring: nothing else can observe this failure
            pass
        finally:
            security_scan.clear_running_marker(root, state_hash)
        return 0
    try:
        result = security_scan.run_scan(root, security_scan.detect_lock_files(root))
        accepted = security_scan.load_accepted(root)
        unaccepted_high = [
            finding for finding in result.findings
            if finding.severity in ("critical", "high")
            and not security_scan.is_accepted(finding.advisory_id, accepted)
        ]
    except Exception:  # noqa: BLE001 — see the docstring: nothing else can observe this failure
        return 0
    try:
        path = _security_scan_result_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"findings": [dataclasses.asdict(f) for f in unaccepted_high]}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass
    return 0


def _spawn_security_scan_worker(
    root: Path, state_hash: Optional[str] = None, lock_paths: "Optional[list[Path]]" = None,
) -> bool:
    """Fire-and-forget: launches dispatch.py's own "_security-scan-worker" internal event as a
    fully detached background process, mirroring `_spawn_update_check_worker` exactly (see that
    function's own docstring for the platform-specific detach details -- stdin/stdout/stderr all go
    to DEVNULL, never a pipe back to this process). With `state_hash`/`lock_paths` the worker runs
    in request mode (see `_run_security_scan_worker`). Returns whether the process was started at
    all -- the caller that wrote a running marker for it clears that marker on False (2026-09-27
    review 2, m6: a swallowed spawn failure used to leave every later commit waiting on a worker
    that never existed)."""
    script = Path(__file__).resolve().parent.parent / "dispatch.py"
    args = [sys.executable, str(script), "_security-scan-worker", str(root)]
    if state_hash is not None:
        args.append(state_hash)
        args.extend(str(path) for path in (lock_paths or []))
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
        return False
    return True


def _consume_pending_security_scan_note(root: Path) -> Optional[str]:
    """Reads and deletes `security-scan-result.json`, written by a previous
    `_run_security_scan_worker()` run -- consuming it means the note surfaces exactly once, on the
    first SessionStart after the background scan finished (same contract as
    `_consume_pending_update_note`). Silent on any I/O problem; a missing file (nothing pending, or
    the last scan found nothing to report) is the common case, not an error."""
    path = _security_scan_result_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        path.unlink()
    except OSError:
        pass
    if not isinstance(data, dict):
        return None
    findings = data.get("findings")
    if not isinstance(findings, list) or not findings:
        return None
    shown = findings[:5]
    rest = len(findings) - len(shown)
    more = f" (+{rest} more)" if rest > 0 else ""
    parts = [
        f"{item.get('package', '?')} {item.get('version', '?')} "
        f"({item.get('advisory_id', '?')}, {item.get('severity', '?')})"
        for item in shown if isinstance(item, dict)
    ]
    if not parts:
        return None
    return ("[act] security-check (deps): unaccepted dependency vulnerability: "
            + "; ".join(parts) + more + " -- see `python .act/scripts/security_scan.py --deps`")


def _check_security_scan_awareness(root: Path, config: dict[str, str]) -> "list[str]":
    """Check the session-start half of the dependency scan (docs/ai/config.md § Checks, `security-check:
    deps`/`full` only -- `off`/`local` never scan here): once a day, kick off a detached background
    scan (`_spawn_security_scan_worker`) and report a *previous* run's finding, if any
    (`_consume_pending_security_scan_note`) -- same split `_check_update_awareness` already takes
    for its own remote lookup, never a synchronous scan inside the hook itself. Returns the
    post-status-line notes (empty list for `off`/`local`, or while nothing is pending yet). Never
    raises -- the caller already wraps this in its own try/except, same as every other best-effort
    sub-step here."""
    level = _security_check_level(config)
    if level not in ("deps", "full"):
        return []
    post_notes: list[str] = []
    pending = _consume_pending_security_scan_note(root)
    if pending:
        post_notes.append(pending)
    if not _security_scan_already_checked_today(root):
        _mark_security_scan_checked_today(root)
        _spawn_security_scan_worker(root)
    return post_notes


# ---------------------------------------------------------------------------
# Orchestrator-only rules (.act/rules/orchestrator/) — imported by docs/ai/rules.md
# like the shared ones (marked "main session only, workers skip this section"). The hook hands
# over a short form only as a fallback, while a locally changed docs/ai/rules.md does not import
# them yet. See the "Overrides" note on _read_rule_states for the docs/ai/rules.md syntax this
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
        elif section_rule_id in overrides:  # a replacement wins, checked or not
            heading = section_lines[0] if section_lines else f"## `{section_rule_id}`"
            kept.append(f"{heading} (project override)")
            kept.append("")
            kept.append(overrides[section_rule_id])
            rule_count += 1
        elif enabled.get(section_rule_id, True):
            kept.extend(section_lines)
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


def _orchestrator_short_lines(
    text: str, enabled: dict[str, bool], overrides: dict[str, str], compact: bool = False
) -> tuple[list[str], int]:
    """One line per rule of one .act/rules/orchestrator/*.md file — its id and heading
    title (or the project's override text, shortened) — instead of the full text, which would
    swell the session-start output with rules that belong in an import (and past 10,000
    characters, Claude Code moves it into a file and shows only a 2,000-character preview). Same
    gating as _filter_orchestrator_file(). With
    `compact`, only the ids, comma-separated on one line. Returns (lines, rule_count)."""
    lines: list[str] = []
    ids: list[str] = []
    for heading in (m.group(1) for m in map(_SECTION_HEADING_RE.match, text.splitlines()) if m):
        id_match = _RULE_ID_IN_TEXT_RE.search(heading)
        if not id_match:
            continue
        rule_id = id_match.group(1)
        if rule_id in overrides:  # a replacement wins, checked or not
            override = overrides[rule_id]
            title = "(project override) " + (override if len(override) <= 90 else override[:89] + "…")
        elif enabled.get(rule_id, True):
            title = heading.split("—", 1)[1].strip() if "—" in heading else ""
        else:
            continue
        ids.append(rule_id)
        lines.append(f"- {rule_id}: {title}" if title else f"- {rule_id}")
    if compact and ids:
        lines = ["  " + ", ".join(ids)]
    return lines, len(ids)


def _orchestrator_rules_imported(reached: list[str]) -> bool:
    """True when docs/ai/rules.md already imports the orchestrator files — then
    Claude Code loads them in full and the hook adds nothing."""
    return any(path.startswith(".act/rules/orchestrator/") or path.startswith("docs/ai/local/rules/orchestrator/")
               for path in reached)


def _deliver_orchestrator_rules(root: Path, config: dict[str, str], compact: bool = False,
                                reached: Optional[list[str]] = None) -> Optional[int]:
    """
    Fallback only: normally docs/ai/rules.md imports the orchestrator rules and this prints
    nothing. While a locally changed docs/ai/rules.md does not import them, print a short form of
    .act/rules/orchestrator/*.md (ascending filename order, filtered through _read_rule_states,
    one line per rule, see _orchestrator_short_lines) plus where the full text lives — never the
    full text: that alone was 12 KB, past the 10,000 characters above which Claude Code moves a
    hook output into a file and shows the model only a 2,000-character preview.

    Returns None (and prints nothing) if the check is off or the directory does not exist yet.
    Prints nothing either, but returns the count, when `reached` (rules.resolve_imports) shows
    that docs/ai/rules.md imports the files itself. Otherwise the number of rules delivered (0 if
    every one was checked off), for the caller's status line. "block" and "warn" behave the same.
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
        lines, count = _orchestrator_short_lines(text, enabled, overrides, compact=compact)
        total += count
        if count:
            blocks.append(f"{path.name}:")
            blocks.extend(lines)

    if blocks and not (reached and _orchestrator_rules_imported(reached)):
        form = "their ids only" if compact else "one line each"
        print(f"[act] orchestrator rules, main session only — docs/ai/rules.md does not import them "
              f"yet, so {form}; the binding text is in .act/rules/orchestrator/<file>, read it "
              "before acting on a rule:")
        print("\n".join(blocks))
    return total


# ---------------------------------------------------------------------------
# Chat language at session start (R-human-language) — only while `language-chat` is `auto`:
# the language remembered for this person on this machine (`board.py --chat-language`,
# .act-local/identity.json), so the assistant does not have to guess it again, or the hint how to
# remember it once recognized. A fixed `language-chat` needs no line; config.md already says it.
# ---------------------------------------------------------------------------

def _chat_language_line(config: dict[str, str]) -> Optional[str]:
    chat, docs = actlib.language_settings(config)
    if chat != "auto":
        return None
    remembered = actlib.remembered_chat_language()
    if remembered:
        return f"[act] chat language: {remembered} (remembered on this machine; docs stay {docs})"
    return (f"[act] chat language: auto, none remembered yet — recognize it from the owner's messages, "
            f"then `python .act/scripts/board.py --chat-language <code>` (until then: {docs})")


# ---------------------------------------------------------------------------
# Active topics at session start — a topic with a switch (logging, feedback, ...) only ever
# matters once its own switch is on; this names, in the table's own order, which ones are
# active this session and where their rule file lives, so the orchestrator (and a human reading
# the transcript) can tell without opening docs/ai/config.md first.
# ---------------------------------------------------------------------------

_TOPIC_SWITCHES: tuple[tuple[str, str, Callable[[str], bool]], ...] = (
    ("logging", "logging", lambda value: value.strip().lower() == "on"),
    ("feedback", "feedback", lambda value: value.strip().lower() not in ("", "off")),
)

# "ide" (topics/ide.md) is not gated by a docs/ai/config.md switch like the two above -- it is
# detected instead, from whether an IDE-shaped MCP server is actually configured for this project
# -- reading it never runs anything, only .mcp.json and Claude's own settings
# files, the same sources Claude Code itself reads its MCP server list from. A name or command
# containing one of these (case-insensitive) counts as "IDE-shaped" -- best-effort, JetBrains'
# `idea` MCP plugin is the only one confirmed as of this writing; a project using a different IDE
# MCP server under an unrecognized name sees "ide" inactive until this list is extended (project
# override: docs/ai/local/.act/hooks/checks/session.py per R-work-override).
_IDE_SERVER_NAME_HINTS = ("idea", "jetbrains", "intellij", "pycharm", "webstorm", "rider", "clion")
# Server names that count as an IDE server only when they match *exactly* (case-insensitive), never
# as a substring: Claude Code's own IDE integration (the VS Code and JetBrains extensions) registers
# its server as plain `ide` -- its tools reach the hooks as `mcp__ide__executeCode` and
# `mcp__ide__getDiagnostics` -- and "ide" as a
# substring would match "provider", "video", "guide" and the like in any server name or command.
# It is never configured in .mcp.json or ~/.claude.json (the extension injects it), so this mainly
# serves checks/mcp_ide.py's own "is this an IDE server" judgment; _servers_match_ide_hint honours
# it too, for a project that happens to name a configured server exactly that.
_IDE_SERVER_EXACT_NAMES = frozenset({"ide"})


def _is_ide_server_name(server: str) -> bool:
    """True if `server` (an MCP server's own name, as in `mcp__<server>__<tool>` or a config
    file's `mcpServers` key) counts as an IDE server: exactly one of _IDE_SERVER_EXACT_NAMES, or
    containing one of _IDE_SERVER_NAME_HINTS -- case-insensitive either way. The one definition
    checks/mcp_ide.py and dispatch.py's fail-closed fallback share with the topic detection here."""
    lowered = server.lower()
    return lowered in _IDE_SERVER_EXACT_NAMES or any(hint in lowered for hint in _IDE_SERVER_NAME_HINTS)


def _servers_match_ide_hint(servers: dict) -> bool:
    """True if some entry of `servers` (an `mcpServers` object: name -> {"command": ...,
    "args": [...], "url": ...}) has a name that is an IDE server's (_is_ide_server_name) or a
    command/args/url that looks like a JetBrains-family IDE server (see _IDE_SERVER_NAME_HINTS).
    Shared by every source _ide_mcp_connected reads from -- project-local config files and the
    owner's user-wide one alike."""
    for name, entry in servers.items():
        if _is_ide_server_name(str(name)):
            return True
        haystack = str(name)
        if isinstance(entry, dict):
            for field in ("command", "url"):
                value = entry.get(field)
                if isinstance(value, str):
                    haystack += " " + value
            args = entry.get("args")
            if isinstance(args, list):
                haystack += " " + " ".join(a for a in args if isinstance(a, str))
        haystack = haystack.lower()
        if any(hint in haystack for hint in _IDE_SERVER_NAME_HINTS):
            return True
    return False


def _user_mcp_servers(root: Path) -> list:
    """Every `mcpServers` object the owner's user-wide `~/.claude.json` carries that could apply to
    this project (review finding 6): a JetBrains IDE's own MCP server is often registered there,
    user-wide, rather than in a project-local `.mcp.json` -- `_ide_mcp_connected` reading only
    project-local files never sees it. Two places in that file define one: the top-level
    `mcpServers` object (Claude Code's own user-wide default, applied to every project) and
    `projects[<root>].mcpServers` (a project-specific addition/override Claude Code also reads
    from there, keyed by this project's own absolute path). Read-only, and only ever these two
    objects' own keys (server name, `command`/`args`/`url`) are ever looked at or returned -- never
    any other content the file might carry (session history, OAuth tokens, other projects'
    entries). Best-effort: a missing, unreadable, or malformed file contributes nothing; read once,
    as a whole, rather than incrementally -- this file can be large (home-directory session
    state), but a second, independent parse pass over it would cost more than one plain
    `json.loads` already does."""
    path = Path.home() / ".claude.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    found: list = []
    top_servers = data.get("mcpServers")
    if isinstance(top_servers, dict):
        found.append(top_servers)
    projects = data.get("projects")
    if isinstance(projects, dict):
        for key, project_entry in projects.items():
            if not isinstance(key, str) or not _same_project_path(key, root):
                continue
            if isinstance(project_entry, dict):
                project_servers = project_entry.get("mcpServers")
                if isinstance(project_servers, dict):
                    found.append(project_servers)
    return found


def _same_project_path(key: str, root: Path) -> bool:
    """True if `key` (a `projects` key of `~/.claude.json`) names `root`. Claude Code writes those
    keys in POSIX form even on Windows (`D:/dev/x`, confirmed against a real file on 2026-09-26),
    while `str(root)` is `D:\\dev\\x` -- a plain dict lookup never matched there. Compared after os.path.normcase/normpath on both sides, so neither slash
    direction nor drive-letter case matters; no filesystem access."""
    return os.path.normcase(os.path.normpath(key)) == os.path.normcase(os.path.normpath(str(root)))


def _ide_mcp_connected(root: Path) -> bool:
    """True if some configured MCP server's name or command looks like a JetBrains-family IDE
    server (see _IDE_SERVER_NAME_HINTS) -- read from .mcp.json and .claude/settings*.json under
    `root` (the "mcpServers" object each of those files can carry), and from the owner's user-wide
    `~/.claude.json` (review finding 6: `_user_mcp_servers`, since a JetBrains plugin's own server
    is often registered there instead of in a project-local file). Best-effort and read-only: a
    missing/unreadable/malformed file simply contributes nothing, never an error."""
    candidates = [root / ".mcp.json", root / ".claude" / "settings.json", root / ".claude" / "settings.local.json"]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        servers = data.get("mcpServers") if isinstance(data, dict) else None
        if isinstance(servers, dict) and _servers_match_ide_hint(servers):
            return True
    for servers in _user_mcp_servers(root):
        if _servers_match_ide_hint(servers):
            return True
    return False


def _ideas_pending(root: Path) -> "tuple[str, list[str]]":
    """(root-relative path of the session owner's ideas file, its new or changed entries) — see
    ideas.py; ("", []) when there is no identity, no file, or ideas.py cannot be imported. Imported
    lazily like `update`/`rules`: a session start never pays for it unless it is reached, and a
    broken ideas.py must not end the session."""
    try:
        import ideas  # deferred: see the docstring
        path, keys = ideas.pending(root)
        if path is None or not keys:
            return "", []
        return path.relative_to(root).as_posix(), keys
    except Exception:
        return "", []


def _ideas_note(rel: str, keys: list[str]) -> str:
    """The `[act] ideas:` session note: how many entries are new or changed, the first few titles
    (ideas.titles_text), and what to do about them."""
    import ideas  # deferred, as in _ideas_pending
    return (f"[act] ideas: {len(keys)} new or changed in {rel} — {ideas.titles_text(keys)} — "
            "process them per the ideas topic, then `python .act/scripts/ideas.py --seen`")


def _ideas_ensure_notes(root: Path, config: dict[str, str], write: bool) -> list[str]:
    """One note per file ideas.ensure() created for the session owner (or, with write=False, would
    create): the folder README.md of the ideas files and the owner's own file. Best effort."""
    import ideas  # deferred, as in _ideas_pending
    notes: list[str] = []
    english = actlib.is_english(actlib.language_settings(config)[1])
    for path, kind in ideas.ensure(root, plan=not write):
        rel = path.relative_to(root).as_posix()
        if not write:
            notes.append(f"[act] note: {rel} would be created (warn mode, not applied)")
        elif kind == "readme":
            extra = "" if english else " — scaffold in English, translate it once (R-work-language)"
            notes.append(f"[act] note: created {rel} — how the ideas files work{extra}")
        else:
            notes.append(f"[act] note: created {rel} — your own ideas file, one `## <title>` section per idea")
    return notes


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
    # "ide" is not one of _TOPIC_SWITCHES' config-driven entries -- it is detected instead, see
    # _ide_mcp_connected's own docstring.
    if _ide_mcp_connected(root):
        resolved = actlib.resolve("rules/topics/ide.md")
        if resolved is None:
            active.append(("ide", "missing"))
        else:
            path, _origin = resolved
            active.append(("ide", path.relative_to(root).as_posix()))
    # "ideas" is data-driven too: active while the owner's own ideas file has entries not yet
    # processed (ideas.py).
    if _ideas_pending(root)[1]:
        resolved = actlib.resolve("rules/topics/ideas.md")
        if resolved is None:
            active.append(("ideas", "missing"))
        else:
            path, _origin = resolved
            active.append(("ideas", path.relative_to(root).as_posix()))
    return active


# ---------------------------------------------------------------------------
# Session-start output — one JSON object: `additionalContext` for the model, kept under the
# 10,000-character cap above which Claude Code moves a hook's output into a file and shows only a
# preview (hooks.md: "capped at 10,000 characters ... a preview of up to the first 2,000
# characters"), and one
# top-level `systemMessage` line for the human ("Warning message shown to the user"). Plain text
# and JSON never mixed: everything the sub-steps print is captured and goes into the context.
# ---------------------------------------------------------------------------

CONTEXT_LIMIT = 9000  # characters; the harness cap is 10,000 per field, this leaves a margin
_RULES_MARK = "\x00act-orchestrator-rules\x00"
# Older forms Claude Code never loads: "@.act/..." (resolved from docs/ai/) and the orchestrator
# files listed in backticks instead of imported.
_OLD_IMPORT_RE = re.compile(r"^(?:@\.act/|`\.act/rules/orchestrator/)", re.MULTILINE)


def _old_rules_imports(root: Path) -> tuple[int, str]:
    """(count, sha256) of older "@.act/..." import lines left in docs/ai/rules.md — Claude Code
    resolves them from docs/ai/ and never finds them. (0, "") when there are none."""
    path = root / "docs" / "ai" / "rules.md"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0, ""
    count = len(_OLD_IMPORT_RE.findall(text))
    return (count, actlib.sha256_file(path)) if count else (0, "")


def _old_imports_note(root: Path) -> Optional[str]:
    """One note per state of a docs/ai/rules.md that still carries the old import form — one
    changed locally or never recorded as generated; an unchanged one was just re-derived by
    _refresh_bridges. Shown once, again only after the file changed and is still wrong.
    Remembered in .act-local/cache.json."""
    count, digest = _old_rules_imports(root)
    if not count:
        return None
    cache = actlib.read_cache()
    if cache.get("rules_import_hint") == digest:
        return None
    actlib.write_cache({"rules_import_hint": digest})
    return (f"[act] note: docs/ai/rules.md names {count} rule file(s) in a form "
            "Claude Code never loads (\"@.act/...\" or `.act/rules/orchestrator/...`) — write each "
            "as \"@../../.act/...\" (check: python .act/scripts/rules.py --imports)")


def _changed_bridge_note(root: Path, dest_rel: str) -> Optional[str]:
    """One note per changed state of a generated bridge that was edited locally: remembered
    by the pair (edited file's own content hash, template source's content hash) in
    .act-local/cache.json ("bridge_change_notes"), same pattern as _old_imports_note()'s
    "rules_import_hint" -- so it is not repeated at every session start while the edit stands, and
    noted again once the file changes further. The template source's own hash is part of the key
    too: a template update to the bridge source (e.g. .act/bridges/rules.md) while the project's
    copy stays locally edited must note again once -- the project's edit is now against a template
    version it has never been compared to, even though the local file itself did not change. This
    matters most for docs/ai/rules.md, which projects are invited to edit (own rules, § "Own
    rules")."""
    dest_path = root / dest_rel
    try:
        digest = actlib.normalized_sha256(dest_path)
    except OSError:
        return None
    source_name = _BRIDGE_MAP.get(dest_rel)
    source_path = root / ".act" / "bridges" / source_name if source_name else None
    try:
        source_digest = actlib.normalized_sha256(source_path) if source_path else ""
    except OSError:
        source_digest = ""
    key = f"{digest}:{source_digest}"
    cache = actlib.read_cache()
    notes = dict(cache.get("bridge_change_notes", {}))
    if notes.get(dest_rel) == key:
        return None
    notes[dest_rel] = key
    actlib.write_cache({"bridge_change_notes": notes})
    return f"[act] note: {dest_rel} was changed locally, template version not applied"


def _chat_language_short(config: dict[str, str]) -> str:
    chat, docs = actlib.language_settings(config)
    if chat != "auto":
        return chat
    return actlib.remembered_chat_language() or f"auto (until known: {docs})"


def _human_line(state: dict) -> Optional[str]:
    """The one `systemMessage` line: rule files loaded, chat language, and the inbox entries
    answered but not yet processed (the status line's own count)."""
    if not state:
        return None
    parts: list[str] = []
    if "files" in state:
        unresolved = state.get("unresolved", 0)
        parts.append(f"rules loaded: {state['files']} files"
                     + (f", {unresolved} import(s) not found" if unresolved else ""))
    if "chat" in state:
        parts.append(f"chat: {state['chat']}")
    if "inbox" in state:
        parts.append(f"inbox: {state['inbox']} to process")
    if state.get("ideas"):
        parts.append(f"ideas: {state['ideas']} new")
    if state.get("old_imports"):
        parts.append("docs/ai/rules.md uses the old import form, see note")
    return "act · " + " · ".join(parts) if parts else None


def _fit_context(text: str, rules_full: str, rules_compact: str) -> str:
    """Put the fallback orchestrator-rules block (usually empty) in place of its mark, and keep
    the whole under CONTEXT_LIMIT: first the tip/reminder line gives way, then the rules shrink
    to their ids; should even that not fit, the text is cut at a line boundary with a pointer to
    .act-local/session-start.txt, where the whole output is kept."""
    def without_tip(value: str) -> str:
        return "".join(line for line in value.splitlines(keepends=True)
                       if not line.startswith(("[act] tip", "[act] reminder")))

    full = text.replace(_RULES_MARK + "\n", rules_full)
    fitted = full
    for candidate in (full, without_tip(full), without_tip(text.replace(_RULES_MARK + "\n", rules_compact))):
        fitted = candidate
        if len(fitted) <= CONTEXT_LIMIT:
            return fitted.rstrip("\n")
    try:
        path = actlib.repo_root() / ".act-local" / "session-start.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(full, encoding="utf-8")
    except (OSError, RuntimeError):
        pass
    tail = "[act] note: session notes cut here — all of them in .act-local/session-start.txt"
    kept = fitted[:CONTEXT_LIMIT - len(tail) - 1].rsplit("\n", 1)[0]
    return kept + "\n" + tail


def refresh_session(payload: dict) -> int:
    """Check 2: runs only for SessionStart. Never fails the session. Prints exactly one JSON
    object: the notes and the status line as `hookSpecificOutput.additionalContext`, one
    human-readable line as `systemMessage`; nothing at all outside a template-managed project."""
    state: dict = {}
    rules_text = {"full": "", "compact": ""}
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        try:
            in_project = _collect_session(payload, state, rules_text)
        except Exception as exc:  # never fail the session over a note
            print(f"[act] note: session start stopped early ({exc.__class__.__name__})")
            in_project = True
    if not in_project:
        return 0
    context = _fit_context(buffer.getvalue(), rules_text["full"], rules_text["compact"])
    output: dict = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}
    message = _human_line(state)
    if message:
        output["systemMessage"] = message
    sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
    return 0


def _collect_session(payload: dict, state: dict, rules_text: dict) -> bool:
    """Everything refresh_session() reports, printed line by line (refresh_session captures it).
    Every sub-step is best effort and swallows its own errors; the fixed-format status line comes
    right after every other note except two deliberate exceptions: the "topics active" line,
    printed first of all and even when `session-start-refresh` is "off", and an "update available"
    note, which is always a previous run's background finding and prints after the status line
    (see _check_update_awareness's pre_notes/post_notes split). Fills `state` for the human line
    and `rules_text` with the orchestrator-rules block (full and compact), whose place in the
    output is marked by _RULES_MARK. Returns False outside a template-managed project."""
    config = actlib.read_config()

    try:
        root = actlib.repo_root()
    except RuntimeError:
        return False  # not inside a template-managed project — nothing to report

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
    try:
        language_line = _chat_language_line(config)
        state["chat"] = _chat_language_short(config)
    except Exception:
        language_line = None
    if language_line:
        print(language_line)

    try:
        audit_note = _docs_audit_note(root, config)
    except Exception:
        audit_note = None  # informational only, must never block the session
    if audit_note:
        print(audit_note)

    ideas_rel, ideas_keys = _ideas_pending(root)
    state["ideas"] = len(ideas_keys)
    if ideas_keys:
        try:
            print(_ideas_note(ideas_rel, ideas_keys))
        except Exception:
            pass  # informational only, must never block the session

    try:
        dependency_note = _dependency_check_note(root, config)
    except Exception:
        dependency_note = None  # informational only, must never block the session
    if dependency_note:
        print(dependency_note)

    mode = _check_mode(config, "session-start-refresh", default="block")
    if mode == "off":
        return True

    branch = _current_branch(root)

    waiting = 0
    try:
        waiting = _count_inbox_waiting(root)
    except Exception:
        pass
    state["inbox"] = waiting

    # The session owner's own ideas file (and the folder README) created on first use — in a
    # project that predates the ideas files, or for a second person who just joined.
    try:
        for note in _ideas_ensure_notes(root, config, write=(mode == "block")):
            print(note)
    except Exception:
        pass  # best effort, must never block the session

    # Whether a feedback reminder to the template author is due right now
    # (.act/scripts/feedback.py --due's own logic) — folded into the status line like the inbox
    # count above, and counted as an "open point" that silences the tip/reminder line below (same
    # reasoning as the inbox count: the thing that is waiting comes first, self-promotion later).
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
    bootstrap_bridges: list[str] = []
    try:
        changed_bridges, refreshed_bridges, bootstrap_bridges = _refresh_bridges(root, write=(mode == "block"))
    except Exception:
        pass

    try:
        _refresh_board(root)
    except Exception:
        pass

    # Files that hang on a docs/ai/config.md value — skill copies, CLAUDE.md and the
    # hook entries on `tools`, a role's bridges on its "## Roles" row (tier/reasoning/model) — are
    # synced here when that value moved since the .act-local/last-applied.json snapshot, not only
    # on the next `update.py` run. A plain comparison, no scan unless something moved (see
    # update.sync_dependent_files()). "block" syncs; "warn" only names what is pending.
    if mode in ("block", "warn"):
        try:
            import update  # deferred: see the header comment above 
            if mode == "block":
                sync_summary, _sync_copies, _sync_touched = update.sync_dependent_files(root, always_run=False)
                if sync_summary:
                    print(f"[act] note: docs/ai/config.md changed -- dependent files synced: {sync_summary}")
            else:
                pending = update.pending_dependent_changes(root)
                if pending:
                    print(f"[act] note: docs/ai/config.md changed ({pending}) -- dependent files would be synced (warn mode, not applied)")
        except Exception as exc:
            # Never silent — a sync that stopped midway is finished by the next session start
            # (it keeps its snapshot unwritten) or by update.py --catch-up.
            print(f"[act] note: syncing files that depend on docs/ai/config.md failed ({exc.__class__.__name__}) -- "
                  "retried next session, or run `python .act/scripts/update.py --catch-up`")

    for dest_rel in changed_bridges:
        if dest_rel == "docs/ai/rules.md" and _old_rules_imports(root)[0]:
            continue  # the more specific import note below replaces this one
        note = _changed_bridge_note(root, dest_rel)
        if note:
            print(note)
    if mode == "warn":
        for dest_rel in refreshed_bridges:
            print(f"[act] note: {dest_rel} would be refreshed from .act/bridges/ (warn mode, not applied)")
    # A raw `git pull` can land the template's own bootstrap CLAUDE.md/AGENTS.md (marker
    # "<!-- act:bootstrap -->") on top of the project's real bridge in an already set-up project.
    # _refresh_bridges tells that apart from an actual local edit and rewrites it here — self-
    # resolving, so no once-per-state cache entry like _changed_bridge_note's is needed: once
    # rewritten, the marker is gone and this cannot fire again for the same file.
    for dest_rel in bootstrap_bridges:
        verb = "replaced by" if mode == "block" else "would be replaced by (warn mode, not applied)"
        print(f"[act] note: {dest_rel}: template bootstrap file {verb} the project bridge "
              "(a raw git pull brought it in)")

    # What Claude Code actually loads. A checked coding set becomes an "@" import (and an
    # unchecked one loses it) so the checkboxes in docs/project/coding_rules.md decide; a locally
    # changed docs/ai/rules.md still importing "@.act/..." gets one note; then the imports are
    # followed from CLAUDE.md exactly the way Claude Code does (rules.resolve_imports).
    reached: list[str] = []
    try:
        import rules  # deferred like update above: a broken rules.py must not end the session
        coding_fixed = rules.sync_coding_imports(root, write=(mode == "block"))
        if coding_fixed:
            verb = "set to" if mode == "block" else "would be set to (warn mode)"
            print(f"[act] note: docs/project/coding_rules.md: {coding_fixed} set line(s) {verb} "
                  "their checkbox (checked = @-import)")
        old_note = _old_imports_note(root)
        if old_note:
            state["old_imports"] = True
            print(old_note)
        if (root / "CLAUDE.md").is_file():
            reached, unresolved = rules.resolve_imports(root, "CLAUDE.md")
            state["files"] = len(reached)
            state["unresolved"] = len(unresolved)
            if unresolved:
                print(f"[act] note: {len(unresolved)} @-import(s) Claude Code cannot follow — "
                      "python .act/scripts/rules.py --imports")
    except Exception as exc:
        print(f"[act] note: import check failed ({exc.__class__.__name__})")

    # Role bridges (.claude/agents/*.md): only the `model`/`effort` frontmatter pair is refreshed
    # here, never the rest of the file — see tiers.py's refresh_project_bridge_frontmatter() for
    # why this differs from _refresh_bridges above, which replaces a whole file or leaves it alone.
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
    # update.py's own notes, never at session start.
    if tier_notes:
        print("[act] note: " + "; ".join(tier_notes))

    post_update_notes: list[str] = []
    try:
        pre_update_notes, post_update_notes = _check_update_awareness(root, config)
        for note in pre_update_notes:
            print(note)
    except Exception:
        pass  # template-awareness is informational only, must never block the session

    try:
        post_update_notes.extend(_check_security_scan_awareness(root, config))
    except Exception:
        pass  # security-check's own daily scan is informational only, must never block the session

    rules_delivered: Optional[int] = None
    for key, compact in (("full", False), ("compact", True)):
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured):
                count = _deliver_orchestrator_rules(root, config, compact=compact, reached=reached)
            rules_delivered = count if key == "full" else rules_delivered
        except Exception:
            pass  # a broken rules delivery must not block the session
        rules_text[key] = captured.getvalue()
    print(_RULES_MARK)

    inbox_part = f" · inbox: {waiting} waiting" if waiting else ""
    rules_via = " (via import)" if _orchestrator_rules_imported(reached) else ""
    rules_part = f" · rules: {rules_delivered}{rules_via}" if rules_delivered is not None else ""
    roles_part = f" · role-bridges refreshed: {len(role_frontmatter_changed)}" if mode == "block" and role_frontmatter_changed else ""
    feedback_part = " · feedback due" if feedback_due else ""
    ideas_part = f" · ideas: {len(ideas_keys)} new" if ideas_keys else ""
    print(f"[act] branch={branch}{inbox_part}{ideas_part}{feedback_part} · board updated{rules_part}{roles_part}")
    # Printed after the status line, not before: an "update available" note here is always a
    # previous SessionStart's background finding (_consume_pending_update_note), never something
    # this run just checked, so it reads as a postscript rather than part of this run's status.
    for note in post_update_notes:
        print(note)
    # At most one line, last of all — either a due reminder from docs/ai/local/reminders.md
    # (user's own, always checked first) or a rotated .act/tips.md tip (config.md § Tips),
    # silenced by `output-depth: sparse` and by any open point above (inbox/feedback
    # due) inside tips.session_line() itself. Same lazy-import-and-swallow pattern as every other
    # sub-step here.
    try:
        from . import tips as _tips
        tip_line = _tips.session_line(payload, root, config,
                                       waiting + (1 if feedback_due else 0) + len(ideas_keys))
    except Exception:
        tip_line = None
    if tip_line:
        print(tip_line)
    return True
