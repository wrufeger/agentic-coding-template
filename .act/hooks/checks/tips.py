#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: T42 — the SessionStart "tip of the day" line and the user's own reminders
#          (docs/project/concepts/ai-dev-app/03-core-rules.md § "Tipps im Chat", B104). Two
#          sources feed the same one-line slot, checked in this order:
#            1. docs/ai/local/reminders.md — the user's own "remind me to ..." lines, one per
#               line, each with a cadence prefix (session/daily/weekly/once/every <n>[mhdw]) or
#               none (falls back to whatever docs/ai/config.md's `tips` key says). A "session" or
#               calendar cadence (daily/weekly/every <n>d/w/once) is decided here, at
#               SessionStart, by session_line(); a minute/hour cadence (every <n>m/h) fires
#               *inside* a running session instead, from observe() on UserPromptSubmit —
#               .act/bridges/settings.hooks.json runs that hook `async: true`, so plain stdout is
#               lost there (unlike SessionStart's synchronous hook, whose plain stdout does reach
#               the model): observe() prints a hookSpecificOutput.additionalContext JSON object
#               instead (see its own docstring and dispatch.py's _OBSERVERS entry). Reminders
#               always go first — `tips: never` only silences the vendor tips below, never the
#               user's own list (an un-cadenced reminder falls back to daily cadence even then,
#               see _due_reminder).
#            2. .act/tips.md (docs/ai/local/tips.md wins if a project ever overrides it, same
#               actlib.resolve() precedence as everything else) — fixed, English tip texts, never
#               written by the model itself (see that file's own header for why). Selected by
#               rotation (the eligible tip not shown longest, never picked at random) among the
#               tips whose `when:` condition currently holds.
#
#          Both are silenced together by `output-depth: sparse` and by any open point at session
#          start — inbox/questions waiting (session.py's own `waiting`) or a feedback reminder
#          due (is_feedback_due() below, called by session.py separately so it can also fold into
#          its own status line) — and never shown twice in the same session (session_id, or twice
#          in the same calendar day for `tips: occasionally`).
#
# Usage: not run directly — session.py calls session_line() from refresh_session() (SessionStart)
#        and is_feedback_due() to decide the feedback_due status-line flag; dispatch.py's
#        _OBSERVERS calls observe() on every hook event (registered as ("tips", "observe")).
#        Both entry points are best-effort: an exception anywhere in here is the caller's to
#        swallow, never something that blocks a session or a tool call.
#
# State: .act-local/tips.json (gitignored, machine-local on purpose — a colleague on the same
#        project should see the same tips again, not "already seen" just because someone else's
#        workstation saw them first). Schema:
#   {"version": 1,
#    "last_shown_date": "YYYY-MM-DD",             # last calendar day ANY vendor tip was shown
#    "sessions": {"<session_id>": {"date": "YYYY-MM-DD", "started_at": "<iso>",
#                                   "tip_shown": true, "reminder_prompt_count": 0}},
#    "history": {"TIP-<slug>": "<iso>", "reminder:<12-hex>": "<iso>"}}
#   `sessions` entries older than yesterday are dropped on write (_prune_sessions) — a session's
#   own bookkeeping is only ever needed for its own lifetime plus a day of slack.
#
# `when:` condition grammar (.act/tips.md, see _eval_when):
#   always                    always eligible
#   config:<key>=<value>      docs/ai/config.md's <key> row equals <value> (case-insensitive)
#   exists:<path>             <path> (repo-root-relative) exists
#   missing:<path>            <path> does not exist
#   unused:<key>               usage.is_unused(root, key) — see .act/scripts/usage.py's header for
#                              the bare-vs-"category:name" key scheme
#   older:<path>><n>m         <path>'s last commit (`git log -1 --format=%ct`) is older than <n>
#                              months, falling back to mtime only when there is no commit history
#                              (untracked file, fresh checkout with no git repo) — mtime alone is
#                              not enough: a checkout gives every file "now" as its mtime
#                              regardless of its real age. `<path>` may list several with `|`
#                              (`older:package.json|composer.json>6m`): fires once at least one
#                              exists and every existing one is old — a fresh package.json next to
#                              a stale composer.json must not fire.
#
# docs/ai/local/reminders.md line grammar (see _read_reminders; documented for humans in
# .act/skeleton/local/README.md):
#   - <text>                       no cadence — daily cadence normally, session cadence under
#                                   `tips: regularly`; `tips: never` does NOT silence it (only the
#                                   vendor tips), so it still falls back to daily in that case
#   - session: <text>               once per session (like `tips: regularly`)
#   - daily: <text>                 at most once per calendar day
#   - weekly: <text>                at most once every 7 days
#   - once: <text>                  shown exactly once, ever, then silent until the line changes
#   - every <n>m: <text>            inside a running session, at least <n> minutes since last
#   - every <n>h: <text>            shown, evaluated on UserPromptSubmit, capped at 3 times/session
#   - every <n>d: <text>            at least <n> days since last shown, evaluated at session start
#   - every <n>w: <text>            at least <n> weeks since last shown, evaluated at session start
#   A line that matches none of the above (e.g. a stray "-" or a colon-free sentence) is kept
#   verbatim as an un-cadenced reminder rather than dropped — better to show something on the
#   default cadence than to silently lose a line the user wrote by hand.
#
# Output format: session_line() returns "[act] reminder: <text>" / "[act] tip: <text>" or None —
#   session.py prints it verbatim, one line, nothing else (SessionStart's hook is synchronous,
#   plain stdout reaches the model). observe() instead prints one JSON object on stdout for
#   UserPromptSubmit only (never for any other event, never for a worker's own payload — see
#   observe()'s docstring), because that hook runs async: {"hookSpecificOutput": {"hookEventName":
#   "UserPromptSubmit", "additionalContext": "[act] reminder: <text>"}} — the one field an async
#   hook's JSON reply is documented to still deliver. Otherwise observe() prints nothing, matching
#   every other observer's observe(event, payload) -> None contract (and staying silent leaves no
#   output for dispatch.py's other UserPromptSubmit observers to collide with on the same stdout).

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import actlib

from .common import _is_harness_message

__all__ = [
    "session_line", "observe", "is_feedback_due",
    "_eval_when", "_is_older_than", "_load_tips", "_read_reminders",
    "_read_state", "_write_state", "_due_tip", "_due_reminder", "_prompt_reminder_line",
]

_TIP_HEADING_RE = re.compile(r"^###\s+(TIP-[A-Za-z0-9-]+)\s*$")
_WHEN_LINE_RE = re.compile(r"^when:\s*(.+)$", re.IGNORECASE)
_OLDER_RE = re.compile(r"^older:(.+)>(\d+)m$", re.IGNORECASE)
_REMINDER_LINE_RE = re.compile(r"^-\s+(.+)$")  # requires a space after "-": a "---" rule is not a reminder
_EVERY_RE = re.compile(r"^every\s+(\d+)\s*([mhdw])$", re.IGNORECASE)
_MAX_PROMPT_REMINDERS_PER_SESSION = 3


# ---------------------------------------------------------------------------
# State file
# ---------------------------------------------------------------------------

def _state_path(root: Path) -> Path:
    return root / ".act-local" / "tips.json"


def _empty_state() -> dict:
    return {"version": 1, "last_shown_date": "", "sessions": {}, "history": {}}


def _read_state(root: Path) -> dict:
    path = _state_path(root)
    if not path.is_file():
        return _empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return _empty_state()
    if not isinstance(data, dict):
        return _empty_state()
    state = _empty_state()
    state.update({k: v for k, v in data.items() if k in state})
    if not isinstance(state.get("sessions"), dict):
        state["sessions"] = {}
    if not isinstance(state.get("history"), dict):
        state["history"] = {}
    return state


def _write_state(root: Path, state: dict) -> None:
    path = _state_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".tips-", suffix=".tmp", dir=str(path.parent))
    except OSError:
        return
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        os.replace(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass


def _prune_sessions(state: dict, today: str) -> None:
    """Drop any session bookkeeping older than yesterday — see this module's header."""
    sessions = state.get("sessions")
    if not isinstance(sessions, dict):
        return
    keep_from = _add_days(today, -1)
    for sid in list(sessions):
        entry = sessions.get(sid)
        day = entry.get("date") if isinstance(entry, dict) else None
        if not isinstance(day, str) or day < keep_from:
            del sessions[sid]


def _add_days(iso_date: str, delta_days: int) -> str:
    try:
        return (date.fromisoformat(iso_date) + timedelta(days=delta_days)).isoformat()
    except Exception:
        return iso_date


def _today() -> str:
    return date.today().isoformat()


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _days_since(iso_ts: str) -> float:
    try:
        return (datetime.now() - datetime.fromisoformat(iso_ts)).total_seconds() / 86400.0
    except Exception:
        return 1e9  # unparseable -> treat as "ages ago", never blocks a due reminder


# ---------------------------------------------------------------------------
# .act/tips.md
# ---------------------------------------------------------------------------

def _load_tips(root: Path) -> list:
    """[{"id": "TIP-...", "when": "...", "text": "..."}], in file order. A tip block without a
    `when:` line or without body text is dropped — a malformed entry must never crash the
    dispatcher, only be skipped (doctor.py is the place that should flag it as a finding)."""
    resolved = actlib.resolve("tips.md")
    if resolved is None:
        return []
    path, _origin = resolved
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    tips: list = []
    current: Optional[dict] = None
    body_lines: list = []

    def _flush() -> None:
        if current and current.get("when"):
            body = " ".join(line.strip() for line in body_lines if line.strip())
            if body:
                tips.append({"id": current["id"], "when": current["when"], "text": body})

    for raw_line in text.splitlines():
        heading = _TIP_HEADING_RE.match(raw_line)
        if heading:
            _flush()
            current = {"id": heading.group(1), "when": None}
            body_lines = []
            continue
        if current is None:
            continue
        stripped = raw_line.strip()
        if current.get("when") is None:
            when_match = _WHEN_LINE_RE.match(stripped)
            if when_match:
                current["when"] = when_match.group(1).strip()
                continue
        body_lines.append(raw_line)
    _flush()
    return tips


def _last_commit_time(root: Path, path_str: str) -> Optional[float]:
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%ct", "--", path_str],
            cwd=str(root), capture_output=True, text=True, timeout=3,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    if not output:
        return None
    try:
        return float(output)
    except ValueError:
        return None


def _path_older_verdict(root: Path, path_str: str, months: int) -> Optional[bool]:
    """None if `path_str` does not exist (caller decides what that means — a single-path
    `older:` condition treats it as "not old", a multi-path one drops it from the vote), else
    whether it is older than `months`. The last commit decides when there is one (review 2026-
    09-23: a fresh checkout gives every file "now" as its mtime regardless of its real age, which
    made mtime-first silently defeat this condition on a freshly cloned project) — mtime is only
    the fallback for an untracked file or a repo with no git history for this path."""
    path = root / path_str
    try:
        if not path.is_file():
            return None
        mtime = path.stat().st_mtime
    except OSError:
        return None
    commit_time = _last_commit_time(root, path_str)
    last_touched = commit_time if commit_time is not None else mtime
    age_days = (time.time() - last_touched) / 86400.0
    return age_days > months * 30  # stdlib-only approximation, documented in this module's header


def _is_older_than(root: Path, path_str: str, months: int) -> bool:
    return bool(_path_older_verdict(root, path_str, months))


def _eval_when(root: Path, config: dict, condition: str) -> bool:
    condition = (condition or "").strip()
    if condition == "always":
        return True
    if condition.startswith("config:"):
        key, sep, value = condition[len("config:"):].partition("=")
        if not sep:
            return False
        return config.get(key.strip(), "").strip().lower() == value.strip().lower()
    if condition.startswith("exists:"):
        rel = condition[len("exists:"):].strip()
        return bool(rel) and (root / rel).exists()
    if condition.startswith("missing:"):
        rel = condition[len("missing:"):].strip()
        return bool(rel) and not (root / rel).exists()
    if condition.startswith("unused:"):
        key = condition[len("unused:"):].strip()
        if not key:
            return False
        try:
            import usage
            return usage.is_unused(root, key)
        except Exception:
            return False
    older = _OLDER_RE.match(condition)
    if older:
        months = int(older.group(2))
        paths = [p.strip() for p in older.group(1).split("|") if p.strip()]
        verdicts = []
        for path_str in paths:
            try:
                verdict = _path_older_verdict(root, path_str, months)
            except Exception:
                verdict = None
            if verdict is not None:
                verdicts.append(verdict)
        # No listed path exists -> nothing to call old; at least one exists -> every *existing*
        # one must be old (package.json|composer.json>6m: a fresh package.json alongside a stale
        # composer.json must not fire).
        return bool(verdicts) and all(verdicts)
    return False  # unrecognized condition kind -> never fires, never crashes


def _tips_mode(config: dict) -> str:
    value = config.get("tips", "occasionally").strip().lower()
    return value if value in ("never", "occasionally", "regularly") else "occasionally"


def _due_tip(root: Path, config: dict, state: dict) -> Optional[dict]:
    mode = _tips_mode(config)
    if mode == "never":
        return None
    if mode == "occasionally" and state.get("last_shown_date") == _today():
        return None
    history = state.get("history", {})
    eligible = []
    for tip in _load_tips(root):
        try:
            ok = _eval_when(root, config, tip["when"])
        except Exception:
            ok = False
        if ok:
            eligible.append((history.get(tip["id"], ""), tip))
    if not eligible:
        return None
    eligible.sort(key=lambda pair: pair[0])
    return eligible[0][1]


# ---------------------------------------------------------------------------
# docs/ai/local/reminders.md
# ---------------------------------------------------------------------------

def _reminders_path(root: Path) -> Path:
    return root / "docs" / "ai" / "local" / "reminders.md"


def _read_reminders(root: Path) -> list:
    """[{"raw", "text", "cadence_kind", "n", "key"}] — see this module's header for the line
    grammar. `cadence_kind` is one of "session", "daily", "days", "weeks", "once", "minutes",
    "hours", "default" (no cadence prefix — inherits the `tips` config key)."""
    path = _reminders_path(root)
    if not path.is_file():
        return []
    try:
        # errors="replace": a hand-edited reminders.md in another encoding must not take the
        # whole tip/reminder mechanism down — a mangled character in one line beats losing every
        # reminder on the page (review 2026-09-23).
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    reminders: list = []
    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            continue
        match = _REMINDER_LINE_RE.match(stripped)
        if not match:
            continue
        body = match.group(1)
        kind, n, text = "default", None, body
        prefix, sep, rest = body.partition(":")
        if sep:
            token = prefix.strip().lower()
            if token == "session":
                kind, text = "session", rest.strip()
            elif token == "daily":
                kind, text = "daily", rest.strip()
            elif token == "weekly":
                kind, n, text = "days", 7, rest.strip()
            elif token == "once":
                kind, text = "once", rest.strip()
            else:
                every = _EVERY_RE.match(token)
                if every:
                    count, unit = int(every.group(1)), every.group(2).lower()
                    text = rest.strip()
                    kind, n = {
                        "m": ("minutes", count), "h": ("hours", count),
                        "d": ("days", count), "w": ("weeks", count),
                    }[unit]
                # else: unrecognized prefix -> kind stays "default", text stays the full body
        text = text.strip()
        if not text:
            continue
        key = hashlib.sha1(stripped.encode("utf-8")).hexdigest()[:12]
        reminders.append({"raw": stripped, "text": text, "cadence_kind": kind, "n": n, "key": key})
    return reminders


def _due_reminder(root: Path, config: dict, state: dict) -> Optional[dict]:
    """Session/daily/weekly/once-cadence reminders only — minute/hour ones are
    _prompt_reminder_line()'s job (UserPromptSubmit, within a running session)."""
    reminders = [r for r in _read_reminders(root) if r["cadence_kind"] not in ("minutes", "hours")]
    if not reminders:
        return None
    tips_mode = _tips_mode(config)
    today = _today()
    history = state.get("history", {})
    eligible = []
    for reminder in reminders:
        kind, n = reminder["cadence_kind"], reminder["n"]
        if kind == "default":
            # `tips: never` only turns the vendor tips off, never the user's own reminders
            # (review 2026-09-23) — an un-cadenced reminder falls back to daily cadence in that
            # case too, same as under `occasionally`; only `regularly` maps it to session cadence.
            kind = "session" if tips_mode == "regularly" else "daily"
        last = history.get(f"reminder:{reminder['key']}")
        if kind == "session":
            due = True  # the single-line-per-session guard in session_line() makes this safe
        elif kind == "daily":
            due = last is None or last[:10] != today
        elif kind == "days":
            due = last is None or _days_since(last) >= (n or 1)
        elif kind == "weeks":
            due = last is None or _days_since(last) >= (n or 1) * 7
        elif kind == "once":
            due = last is None
        else:
            due = False
        if due:
            eligible.append((last or "", reminder))
    if not eligible:
        return None
    eligible.sort(key=lambda pair: pair[0])
    return eligible[0][1]


# ---------------------------------------------------------------------------
# SessionStart entry point
# ---------------------------------------------------------------------------

def session_line(payload: dict, root: Path, config: dict, waiting: int) -> Optional[str]:
    """The one line session.py's refresh_session() prints under the status line, or None. Never
    raises — every failure mode falls back to None; session.py also wraps this in its own
    try/except as a second line of defense (that call is at module scope through a lazy import,
    see session.py's own comment for why)."""
    try:
        state = _read_state(root)
    except Exception:
        state = _empty_state()

    today = _today()
    session_id = payload.get("session_id")
    session_id = session_id if isinstance(session_id, str) and session_id else None

    try:
        _prune_sessions(state, today)
    except Exception:
        pass

    sessions = state.setdefault("sessions", {})
    sess = sessions.setdefault(session_id, {}) if session_id else {}
    sess.setdefault("started_at", _now_iso())
    sess["date"] = today
    already_shown = bool(sess.get("tip_shown"))

    depth = str(config.get("output-depth", "normal")).strip().lower()
    silence = depth == "sparse" or waiting > 0

    line: Optional[str] = None
    changed = bool(session_id)  # sess["date"]/"started_at" above already touched the state
    if not silence and not already_shown:
        try:
            reminder = _due_reminder(root, config, state)
        except Exception:
            reminder = None
        if reminder is not None:
            state.setdefault("history", {})[f"reminder:{reminder['key']}"] = _now_iso()
            line = f"[act] reminder: {reminder['text']}"
        else:
            try:
                tip = _due_tip(root, config, state)
            except Exception:
                tip = None
            if tip is not None:
                state.setdefault("history", {})[tip["id"]] = _now_iso()
                state["last_shown_date"] = today
                line = f"[act] tip: {tip['text']}"
        if line is not None:
            sess["tip_shown"] = True
            changed = True

    if changed:
        try:
            _write_state(root, state)
        except Exception:
            pass
    return line


# ---------------------------------------------------------------------------
# UserPromptSubmit — minute/hour-cadence reminders within a running session
# ---------------------------------------------------------------------------

def _prompt_reminder_line(root: Path, config: dict, payload: dict) -> Optional[str]:
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return None
    depth = str(config.get("output-depth", "normal")).strip().lower()
    if depth == "sparse":
        return None
    reminders = [r for r in _read_reminders(root) if r["cadence_kind"] in ("minutes", "hours")]
    if not reminders:
        return None

    try:
        state = _read_state(root)
    except Exception:
        state = _empty_state()
    today = _today()
    try:
        _prune_sessions(state, today)
    except Exception:
        pass
    sessions = state.setdefault("sessions", {})
    sess = sessions.setdefault(session_id, {})
    sess.setdefault("started_at", _now_iso())
    sess["date"] = today
    count = int(sess.get("reminder_prompt_count") or 0)
    if count >= _MAX_PROMPT_REMINDERS_PER_SESSION:
        return None

    history = state.setdefault("history", {})
    now = datetime.now()
    eligible = []
    for reminder in reminders:
        interval_minutes = reminder["n"] if reminder["cadence_kind"] == "minutes" else (reminder["n"] or 1) * 60
        last = history.get(f"reminder:{reminder['key']}") or sess.get("started_at")
        try:
            elapsed = (now - datetime.fromisoformat(last)).total_seconds() / 60.0 if last else interval_minutes
        except Exception:
            elapsed = interval_minutes
        if elapsed >= interval_minutes:
            eligible.append((last or "", reminder))
    if not eligible:
        return None
    eligible.sort(key=lambda pair: pair[0])
    _, chosen = eligible[0]
    history[f"reminder:{chosen['key']}"] = now.isoformat(timespec="seconds")
    sess["reminder_prompt_count"] = count + 1
    try:
        _write_state(root, state)
    except Exception:
        pass
    return f"[act] reminder: {chosen['text']}"


def observe(event: str, payload: dict) -> None:
    """Registered in dispatch.py's _OBSERVERS as ("tips", "observe"). Prints directly to stdout,
    unlike every other observer here — but only for UserPromptSubmit, and only for the main
    session's own prompt (never a worker's — see checks.common._is_worker), so nothing prints
    during PreToolUse/PostToolUse/SubagentStart/etc. despite observe() running for every one of
    them. UserPromptSubmit runs `async: true` (.act/bridges/settings.hooks.json), and an async
    hook's plain stdout never reaches the model — only hookSpecificOutput.additionalContext from
    a JSON object on stdout is documented to (review 2026-09-23; SessionStart, by contrast, is
    synchronous, so session_line()'s plain-text return is fine as-is). Every other
    UserPromptSubmit observer (event_log, usage, status_poll) prints nothing, so this stays the
    only stdout output for that event — the JSON below is not competing with anything else."""
    if event != "UserPromptSubmit" or payload.get("agent_id"):
        return
    if _is_harness_message(payload.get("prompt")):
        # A worker's report or a task-finished notice, not a real user turn (T44 live probe,
        # 2026-09-23, checks.common._is_harness_message) — a minute/hour reminder nudging Wolfgang
        # about something makes no sense attached to text he never typed.
        return
    try:
        root = actlib.repo_root()
        config = actlib.read_config()
        line = _prompt_reminder_line(root, config, payload)
    except Exception:
        return
    if line:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": line,
            }
        }))


def is_feedback_due(root: Path) -> bool:
    """Wraps .act/scripts/feedback.py's due_status(root) -> (due, detail) (review 2026-09-23: a
    dedicated boolean-returning function, factored out of cmd_due() itself, rather than capturing
    and parsing that command's stdout). Never raises: any failure (feedback.py missing, an
    exception inside due_status) reads as "not due"."""
    try:
        import feedback
        due, _detail = feedback.due_status(root)
    except Exception:
        return False
    return bool(due)
