"""Detached background processes of the session start (update lookup, dependency scan, act-local-tidy)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

__all__ = ["spawn_detached"]


def spawn_detached(root: Path, event: str, *extra: str) -> bool:
    """Fire-and-forget: launches dispatch.py with the internal `event` (one of the `_..-worker` events
    dispatch.main() knows, never a real harness hook event) and `root` as a fully detached process and
    returns at once. stdin/stdout/stderr all go to DEVNULL, never a pipe back to this process - a pipe
    would reintroduce exactly the blocking this exists to avoid, one level up. Returns whether the
    process was started at all; callers that need no answer ignore it.

    The launched script is dispatch.py, not a module of checks/: `Path(__file__).resolve().parent` is
    .act/hooks/checks/, so its own `.parent` reaches .act/hooks/, where dispatch.py lives."""
    script = Path(__file__).resolve().parent.parent / "dispatch.py"
    args = [sys.executable, str(script), event, str(root), *extra]
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
