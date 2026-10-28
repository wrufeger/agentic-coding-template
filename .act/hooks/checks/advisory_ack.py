# -*- coding: utf-8 -*-
#
# Purpose: The chat sentence that acknowledges a template advisory ("Warnung quittiert", "warning
#          acknowledged", ...). dispatch.py's synchronous `UserPromptSubmit --act-check` entry calls
#          handle() for a prompt that starts like such a sentence; the whole prompt, trimmed, must be
#          one of the phrases below, optionally followed by advisory ids (`A1`, `A1 A3`, `A1, A3`) and a
#          closing `.` or `!`. When at least one named (or, without an id, any) advisory is active it is
#          acknowledged through advisory.py and the reason to show is returned -- dispatch.py then blocks
#          the prompt so it never reaches the model, as the quick capture does. Otherwise handle()
#          returns None and the prompt goes through unchanged. Files only: no git, no network.

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

from .common import _is_harness_message

__all__ = ["START_RE", "match_acknowledgement", "handle"]

# The cheap start test dispatch.py applies to the raw prompt before it imports this module (same pattern).
START_RE = re.compile(r"\s*(?:warnung|hinweis|warning|notice)\s", re.IGNORECASE)
_PHRASES = ("warnung akzeptiert", "warnung quittiert", "hinweis gelesen",
            "warning accepted", "warning acknowledged", "notice read")
_ID = r"A[1-9][0-9]{0,3}"
_SENTENCE_RE = re.compile(
    rf"(?P<phrase>{'|'.join(re.escape(phrase) for phrase in _PHRASES)})"
    rf"(?:[ \t]+(?P<ids>{_ID}(?:(?:[ \t]*,[ \t]*|[ \t]+){_ID})*))?[ \t]*[.!]?",
    re.IGNORECASE)
_ID_RE = re.compile(_ID, re.IGNORECASE)


def match_acknowledgement(prompt: object) -> Optional[list[str]]:
    """None when `prompt` is not an acknowledgement sentence; otherwise the ids it names (upper case, empty
    for "every active advisory")."""
    if not isinstance(prompt, str) or len(prompt) > 200:
        return None
    match = _SENTENCE_RE.fullmatch(prompt.strip())
    if match is None:
        return None
    return [item.upper() for item in _ID_RE.findall(match.group("ids") or "")]


def handle(root: Path, payload: dict) -> Optional[str]:
    """The reason text to show when `payload["prompt"]` acknowledged at least one active advisory, else None
    (a worker, a harness message, another sentence, nothing active, `advisory-check: off`, any error)."""
    prompt = payload.get("prompt")
    if payload.get("agent_id") or _is_harness_message(prompt):
        return None
    named = match_acknowledgement(prompt)
    if named is None:
        return None
    try:
        scripts = str(Path(__file__).resolve().parents[2] / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        import advisory

        active = [item.id for item in advisory.active_advisories(root)]
        wanted = [item for item in named if item in active] if named else active
        if not wanted:
            return None
        done, _unknown = advisory.acknowledge(root, wanted)
    except Exception as exc:  # noqa: BLE001 -- a failure here must never eat the user's message
        print(f"[act] advisory acknowledgement failed, message passed through ({exc!r})", file=sys.stderr)
        return None
    if not done:
        return None
    if len(done) == 1:
        return (f"act: advisory {done[0]} acknowledged — it no longer shows at session start, in the status "
                "line or on the board.")
    return (f"act: advisories {', '.join(done)} acknowledged — they no longer show at session start, in the "
            "status line or on the board.")
