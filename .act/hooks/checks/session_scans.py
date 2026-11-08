"""Session start, background scans: the daily dependency-vulnerability scan and `act-local-tidy`, each
a detached worker whose finding the next start reports.

Split out of session.py, which keeps the entry point and the order of the sub-steps."""
from __future__ import annotations

import dataclasses
import json
import time
from datetime import date
from pathlib import Path
from typing import Optional

import actlib

from .background import spawn_detached
from .common import _check_mode
from .state_files import checked_today, mark_checked_today

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
        `security-scan-result.json` (every unaccepted high/critical finding, and every tool that
        signalled findings with an unreadable report) for the SessionStart
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
        scanned_at = time.time()
        lock_files = security_scan.detect_lock_files(root)
        result = security_scan.run_scan(root, lock_files)
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
        if not actlib.local_write_ok(root, path):
            return 0  # .act-local is a link or leaves the project: nothing is written through it
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "scanned_at": scanned_at,
                    "lock_files": sorted(str(p) for paths in lock_files.values() for p in paths),
                    "findings": [dataclasses.asdict(f) for f in unaccepted_high],
                    "unreadable_reports": list(result.unreadable_reports),
                },
                ensure_ascii=False,
            ) + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass
    return 0


def _spawn_security_scan_worker(
    root: Path, state_hash: Optional[str] = None, lock_paths: "Optional[list[Path]]" = None,
) -> bool:
    """Fire-and-forget: starts the "_security-scan-worker" event of dispatch.py as a detached background
    process (background.spawn_detached), like `_spawn_update_check_worker`. With `state_hash`/`lock_paths`
    the worker runs in request mode (see `_run_security_scan_worker`). Returns whether the process was
    started at all -- the caller that wrote a running marker for it clears that marker on False (a
    swallowed spawn failure used to leave every later commit waiting on a worker that never existed)."""
    extra: list[str] = []
    if state_hash is not None:
        extra = [state_hash, *(str(path) for path in (lock_paths or []))]
    if not actlib.local_write_ok(root, root / ".act-local" / "security-scan-result.json"):
        return False  # the worker leaves its result below .act-local: not through a link
    return spawn_detached(root, "_security-scan-worker", *extra)


def _consume_pending_security_scan_note(root: Path) -> Optional[str]:
    """Reads and deletes `security-scan-result.json`, written by a previous
    `_run_security_scan_worker()` run -- consuming it means the note surfaces exactly once, on the
    first SessionStart after the background scan finished (unlike the update note, which stays
    until the update is installed). Silent on any I/O problem; a missing file (nothing pending, or
    the last scan found nothing to report) is the common case, not an error."""
    path = _security_scan_result_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        if actlib.local_write_ok(root, path):
            path.unlink()
    except OSError:
        pass
    if not isinstance(data, dict):
        return None
    findings = data.get("findings")
    findings = findings if isinstance(findings, list) else []
    unreadable = data.get("unreadable_reports")
    unreadable = [str(item) for item in unreadable] if isinstance(unreadable, list) else []
    if not findings and not unreadable:
        return None
    scanned_at = data.get("scanned_at")
    lock_files = data.get("lock_files")
    if isinstance(scanned_at, (int, float)) and isinstance(lock_files, list):
        for name in lock_files:
            try:
                changed = Path(str(name)).stat().st_mtime > scanned_at
            except OSError:
                changed = True  # the lock file is gone: the result no longer describes the project
            if changed:
                return None  # a lock file changed after the scan: the findings may no longer hold
    return _format_security_scan_note(
        root, [item for item in findings if isinstance(item, dict)], scanned_at, unreadable,
    )


def _format_age(seconds: float) -> str:
    minutes = int(max(seconds, 0) // 60)
    if minutes < 60:
        return f"{minutes} min"
    hours = minutes // 60
    return f"{hours} h" if hours < 48 else f"{hours // 24} d"


def _format_security_scan_note(
    root: Path, findings: "list[dict]", scanned_at: object, unreadable: "Optional[list[str]]" = None,
) -> Optional[str]:
    """One line for the unaccepted findings of the daily scan, grouped by lock file (path relative to
    `root`) so a new finding in the project's own lock file does not drown in a long list, and with
    the age of the scan when it is known. A tool that signalled findings with an unreadable report
    (`unreadable`) is named as its own part: it is never a clean scan."""
    groups: dict[str, list[dict]] = {}
    for item in findings:
        groups.setdefault(str(item.get("lock_file") or "?"), []).append(item)
    parts: list[str] = []
    for lock_file, items in groups.items():
        try:
            shown_name = Path(lock_file).resolve().relative_to(root.resolve()).as_posix()
        except (OSError, ValueError):
            shown_name = lock_file
        shown = items[:3]
        rest = len(items) - len(shown)
        more = f" (+{rest} more)" if rest > 0 else ""
        entries = ", ".join(
            f"{item.get('package', '?')} {item.get('version', '?')} "
            f"({item.get('advisory_id', '?')}, {item.get('severity', '?')})"
            for item in shown
        )
        parts.append(f"{shown_name} [{len(items)}]: {entries}{more}")
    for report in (unreadable or [])[:3]:
        parts.append(f"unread findings: {report}")
    if not parts:
        return None
    age = ""
    if isinstance(scanned_at, (int, float)):
        age = f" (scan {_format_age(time.time() - scanned_at)} old)"
    return (f"[act] security-check (deps){age}: unaccepted dependency vulnerability: "
            + "; ".join(parts) + " -- see `python .act/scripts/security_scan.py --deps`")


def _check_security_scan_awareness(root: Path, config: dict[str, str]) -> "list[str]":
    """Check the session-start half of the dependency scan (docs/ai/config.md § Checks, `security-check:
    deps`/`full` only -- `off`/`local` never scan here): once a day, kick off a detached background
    scan (`_spawn_security_scan_worker`) and report a *previous* run's finding, if any
    (`_consume_pending_security_scan_note`) -- same split `_check_update_awareness` already takes
    for its own remote lookup, never a synchronous scan inside the hook itself. Returns the
    post-status-line notes (empty list for `off`/`local`, or while nothing is pending yet). Never
    raises -- the caller already wraps this in its own try/except, same as every other best-effort
    sub-step here."""
    if (root / ".act-local" / "security-scan-cache").is_dir():  # nothing cached, nothing to prune
        try:
            import security_scan  # deferred, like in the worker
            security_scan.prune_cache(root)  # entries from before today never answer anything again
        except ImportError:
            pass
    level = actlib.security_check_level(config)
    if level not in ("deps", "full"):
        return []
    post_notes: list[str] = []
    pending = _consume_pending_security_scan_note(root)
    if pending:
        post_notes.append(pending)
    if not checked_today(_security_scan_state_path(root)):
        mark_checked_today(root, _security_scan_state_path(root))
        _spawn_security_scan_worker(root)
    return post_notes


# ---------------------------------------------------------------------------
# `act-local-tidy` at session start (docs/ai/config.md § Checks): keeps .act-local/ small. Same shape as
# the update check above -- once a day a detached worker (`_act-local-tidy-worker` in dispatch.py) runs
# scripts/act_local_tidy.py's run_daily(); the finding goes to a result file that the *next* session
# start reports, so this start never waits for a directory walk.
# ---------------------------------------------------------------------------

def _tidy_module():
    import act_local_tidy  # deferred: a session start pays for it only here
    return act_local_tidy


def _consume_pending_tidy_note(root: Path) -> Optional[str]:
    """Reads and deletes .act-local/act-local-tidy-result.json (written by `_run_act_local_tidy_worker`)
    and returns the one-line report, None when there is none."""
    tidy = _tidy_module()
    path = tidy.result_path(root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        if actlib.local_write_ok(root, path):
            path.unlink()
    except OSError:
        pass
    line = (tidy.format_result(data) if isinstance(data, dict) else "") or None
    if line and isinstance(data, dict) and data.get("mode") == "would":
        tidy.record_reported(root)  # a report-only result was shown today: removal may start on a later day
    return line


def _run_act_local_tidy_worker(root: Path) -> int:
    """Body of the detached process: one daily tidy run. Always exits 0; every error stays in here."""
    try:
        _tidy_module().run_daily(root)
    except Exception:  # noqa: BLE001 -- nothing can observe a failure of this process
        pass
    return 0


def _spawn_act_local_tidy_worker(root: Path) -> None:
    """Fire-and-forget, as `_spawn_update_check_worker`: the `_act-local-tidy-worker` event of dispatch.py."""
    spawn_detached(root, "_act-local-tidy-worker")


def _check_act_local_tidy(root: Path, config: dict[str, str], state: dict) -> "list[str]":
    """Reports a previous run's finding (post-status-line note, plus `state["tidy"]` for the human line)
    and, at most once a calendar day, starts the detached worker. `act-local-tidy: off` does neither.
    The marker `spawned` in .act-local/act-local-tidy.json keeps parallel session starts from each
    spawning one. Never raises past the caller's own try/except."""
    if _check_mode(config, "act-local-tidy", default="block") == "off" or not (root / ".act-local").is_dir():
        return []
    tidy = _tidy_module()
    notes: list[str] = []
    if tidy.base_is_link(root):  # nothing is read, written or spawned through a linked .act-local
        return [f"[act] note: act-local-tidy: {tidy.LINK_NOTE}"]
    pending = _consume_pending_tidy_note(root)
    if pending:
        notes.append(f"[act] note: {pending}")
        state["tidy"] = pending
    today = date.today().isoformat()
    if tidy.read_state(root).get("spawned") != today:
        tidy.write_state(root, spawned=today)
        _spawn_act_local_tidy_worker(root)
    return notes
