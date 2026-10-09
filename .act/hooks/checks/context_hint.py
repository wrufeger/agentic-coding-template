"""Observer: a one-time note per threshold step to suggest /clear at the next task boundary.

Registered in dispatch.py's _OBSERVERS as ("context_hint", "observe"). On UserPromptSubmit only, it
reads the context size of the session's last model call from the transcript (hook payloads carry no
token counts, but every one carries `transcript_path`), compares step = tokens // threshold with the step
already noted for this session and, when higher, prints one hookSpecificOutput.additionalContext JSON
object (dispatch.py merges it with other observers' output for the same event). The noted step per
session lives in .act-local/context-hint.json. Threshold: `context-hint` in docs/ai/config.md (`off`
disables). Silent on any error, never blocks.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import actlib

from .common import _is_harness_message

__all__ = ["observe"]

_MAX_SESSIONS = 50
_MAX_AGE_SECONDS = 14 * 24 * 3600


def _state_path(root: Path) -> Path:
    return root / ".act-local" / "context-hint.json"


def _read_state(root: Path) -> dict:
    try:
        data = json.loads(_state_path(root).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"version": 1, "sessions": {}}
    sessions = data.get("sessions") if isinstance(data, dict) else None
    return {"version": 1, "sessions": sessions if isinstance(sessions, dict) else {}}


def _prune(sessions: dict) -> dict:
    now = time.time()
    kept = {key: value for key, value in sessions.items()
            if isinstance(value, dict) and isinstance(value.get("step"), int)
            and now - float(value.get("at", now)) < _MAX_AGE_SECONDS}
    newest = sorted(kept.items(), key=lambda item: float(item[1].get("at", 0)), reverse=True)[:_MAX_SESSIONS]
    return dict(newest)


def _write_state(root: Path, state: dict) -> None:
    path = _state_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=".context-hint-", suffix=".tmp", dir=str(path.parent))
    except OSError:
        return
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + "\n")
        actlib.replace_file(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass


def observe(event: str, payload: dict) -> None:
    if event != "UserPromptSubmit" or payload.get("agent_id"):
        return
    try:
        if _is_harness_message(payload.get("prompt")):
            return
        session_id = payload.get("session_id")
        transcript = payload.get("transcript_path")
        if not isinstance(session_id, str) or not session_id or not isinstance(transcript, str) or not transcript:
            return
        import context_size
        root = actlib.repo_root()
        threshold = context_size.hint_threshold(root)
        if threshold is None:
            return
        tokens = context_size.last_context_tokens(Path(transcript))
        if tokens is None:
            return
        step = tokens // threshold
        state = _read_state(root)
        entry = state["sessions"].get(session_id)
        noted = entry.get("step", 0) if isinstance(entry, dict) else 0  # a malformed entry counts as empty
        if step < 1 or not isinstance(noted, int) or step <= noted:
            return
        state["sessions"][session_id] = {"step": step, "at": time.time()}
        state["sessions"] = _prune(state["sessions"])
        _write_state(root, state)
        line = (f"[act] context ~{round(tokens / 1000)}k tokens (context-hint {threshold}): at the next task "
                "boundary — task done and committed, no worker running, nothing left only in chat — suggest "
                "/clear or a new session in the closing line (R-work-handover).")
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": line}}))
    except Exception:  # noqa: BLE001 — an observer never blocks
        return
