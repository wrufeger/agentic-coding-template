"""State files below .act-local/ that the hook checks keep: one atomic JSON write and the once-a-day marker.

Shared by session.py (update check, dependency scan), tips.py, context_hint.py and worker_cap.py. Every
function is best-effort and never raises: a state file is bookkeeping, not a reason to fail a hook.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path

import actlib

__all__ = ["write_json_atomic", "checked_today", "mark_checked_today"]


def write_json_atomic(path: Path, data: dict, prefix: str = ".tmp-", sort_keys: bool = False) -> bool:
    """Write `data` as JSON via temp file + os.replace (atomic on POSIX and Windows alike). The temp
    file's suffix is ".tmp", not ".json": a ".json"-suffixed temp file is briefly visible to a
    concurrent writer that prunes stale `*.json` files in the same folder, which could delete it out
    from under us. False when the write failed; the caller decides whether that matters."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix=prefix, suffix=".tmp", dir=str(path.parent))
    except OSError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=sort_keys) + "\n")
        actlib.replace_file(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        return False
    return True


def checked_today(path: Path) -> bool:
    """True when the marker file at `path` says `last_checked` is today."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return isinstance(data, dict) and data.get("last_checked") == date.today().isoformat()


def mark_checked_today(root: Path, path: Path) -> None:
    """Write today's marker at `path` (below `root`'s .act-local/); nothing when .act-local is a link
    or leaves the project."""
    if not actlib.local_write_ok(root, path):
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"last_checked": date.today().isoformat()}) + "\n", encoding="utf-8")
    except OSError:
        pass
