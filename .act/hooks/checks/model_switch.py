#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Say it loudly when a worker or the session itself continues on another model (Stop and
#          SubagentStop). When the safety filter of the chosen model refuses a request, Claude Code may
#          carry on with a fallback model, and in a sub-agent nothing in the chat says so. The only trace
#          is in the transcript: an assistant record with `message.stop_reason == "refusal"`, and from then
#          on a different `message.model` (the record of the switch itself is no event of the hook API for a
#          sub-agent). This check reads the transcript and reports.
#
# What is read: at SubagentStop the worker's own transcript (`agent_transcript_path`, else
# `<session>/subagents/agent-<id>.jsonl` next to the session transcript), at Stop the session's
# (`transcript_path`) -- only the part not read before. The offset and the last model seen are kept in one
# small file per transcript under `.act-local/model-switch/`, so two workers ending together never write
# the same file. A first read, or one after the file was rewritten, takes at most the last 4 MB; a later read
# goes on from the saved offset in blocks of at most 4 MB, up to 16 blocks per call (what is left is read at
# the next Stop), so a refusal in the middle of a large addition is not skipped. The state folder is written
# and pruned only when neither `.act-local` nor `model-switch` is a link (the watcher's link test decides,
# checks/protected_watch.py), through a temp file created exclusively and removed when the write fails.
#
# What counts: any assistant record with `stop_reason: refusal` (its `stop_details.category`, if given,
# is named, never its explanation; only letters, digits, `_` and `-`, at most 40 characters of it), and a
# `message.model` that differs from the previous one of the same transcript, `<synthetic>` ignored (it is no
# model). A model name is text from the transcript: only letters, digits and `._:@/-` of it are kept, at most
# 64 characters, in the state file and in every message. No role alias (the short names in `tiers.json`) is mapped to a
# model id. A switch the human made with `/model` shows up the same way and is named as a switch; the
# message says so.
#
# What it says: one note for the orchestrator, delivered with the additionalContext of its next tool call
# (checks/protected_watch.py queues and delivers the notes); the orchestrator tells the human in chat. The
# hook prints nothing for the human: a live probe (Claude Code 2.1.319) showed that a `systemMessage` of
# Stop/SubagentStop is recorded in the transcript but never displayed. The note is NOT put into
# `additionalContext` of the Stop/SubagentStop output: the hook documentation says that field keeps the
# stopping agent running (for SubagentStop the SUBAGENT, not its caller), and recommends a PostToolUse hook
# for the parent. Nothing here blocks or keeps an agent running. `run` returns None in every case; a note
# that cannot be queued raises before the offset is saved (the next Stop reads it again), and dispatch.py
# reports that failure on stderr (the note is the only path).
#
# Switch: `model-switch` in docs/ai/config.md § Checks, `warn` (default) or `off` (`block` counts as `warn`).
#
# Limits:
#   - The human learns of a switch only when the orchestrator says so in chat; the hook shows nothing itself.
#   - It reports after the agent has stopped; a worker that never stops (killed, crashed) is not read.
#   - Claude Code does not promise the final message to be in the transcript at Stop; a record that is
#     not there yet is read at the next Stop.
#   - A switch inside one turn that leaves no assistant record on the other model is not seen.
#   - A single record larger than 4 MB (an inline image, say) is skipped whole.
#   - A worker id that holds anything but letters, digits, `_` and `-` finds no transcript and is not named.
#   - The harness has its own events for a model change of the SESSION (PreModelSwitch, PostModelSwitch,
#     the latter also for an automatic fallback); none is documented for a sub-agent, so this check reads
#     the transcript for both.

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Optional

import actlib

from . import protected_watch
from .common import _check_mode

__all__ = ["run", "scan_transcript"]

_MAX_CHUNK = 4_000_000          # bytes read at most per block
_MAX_BLOCKS = 16                # blocks read at most per call; the rest is read at the next Stop
_MAX_CATEGORY = 40              # characters of a refusal category that reach a message
_MAX_MODEL = 64                 # characters of a model name that reach the state file and a message
_MODEL_CHARS = "._:@/-"         # besides letters and digits: what a model id may hold (vendor ids carry : @ /)
_EXCLUSIVE = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
              | getattr(os, "O_CLOEXEC", 0))
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")  # an agent id used as a file name part
_STATE_TTL = 7 * 86400.0        # seconds a per-transcript state file is kept after its last use
_SYNTHETIC = "<synthetic>"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _state_dir(root: Path) -> Path:
    return root / ".act-local" / "model-switch"


def _state_file(root: Path, transcript: Path) -> Path:
    key = hashlib.sha1(os.path.normcase(str(transcript)).encode("utf-8", errors="replace")).hexdigest()[:20]
    return _state_dir(root) / f"{key}.json"


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _linked(root: Path) -> bool:
    """True when `.act-local` or `.act-local/model-switch` is a link (symlink, junction, reparse point):
    nothing is written or removed through one. The watcher's component test, not a copy of it."""
    folder = str(_state_dir(root)).replace("\\", "/")
    return protected_watch._link_in(str(root).replace("\\", "/"), folder + "/x") is not None


def _save(root: Path, path: Path, state: dict) -> None:
    """Write the state file through a temp file created exclusively (a link already standing at its name is
    never opened) and a rename; a temp file this write made and could not rename is removed. Nothing is
    written when the state folder lies behind a link."""
    if _linked(root):
        return
    temp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(str(temp), _EXCLUSIVE, 0o644)
    except OSError:
        return
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(json.dumps(state).encode("utf-8"))
        os.replace(temp, path)
    except OSError:
        try:
            os.remove(temp)
        except OSError:
            pass


def _prune(root: Path) -> None:
    """Drop state files not used for _STATE_TTL; nothing is removed through a link."""
    if _linked(root):
        return
    now = time.time()
    try:
        for entry in os.scandir(_state_dir(root)):
            try:
                if now - entry.stat(follow_symlinks=False).st_mtime > _STATE_TTL:
                    os.remove(entry.path)
            except OSError:
                continue
    except OSError:
        pass


def _new_lines(path: Path, offset: int) -> tuple[list[str], int, bool]:
    """(complete lines after `offset`, the offset behind the last one, whether more follows in the file).
    A first read (no usable offset) takes at most the last 4 MB; a later one takes the next block of at most
    4 MB, and the caller asks again while more follows. A tail without a newline that is a whole JSON record
    counts as a line too (the last record of a stopped agent); any other partial tail is left for the next
    read. A block without any newline (one record over 4 MB) is skipped whole."""
    size = path.stat().st_size
    warm = 0 < offset <= size
    start = offset if warm else 0
    skip_first = False
    if not warm and size > _MAX_CHUNK:
        start, skip_first = size - _MAX_CHUNK, True
    end = min(size, start + _MAX_CHUNK)
    more = end < size
    with open(path, "rb") as handle:
        handle.seek(start)
        data = handle.read(end - start)
    consumed = len(data)
    cut = data.rfind(b"\n")
    tail = data[cut + 1:] if cut >= 0 else data
    body = data[:cut + 1] if cut >= 0 else b""
    if more:
        if cut >= 0:
            consumed = len(body)  # the partial line at the end of the block belongs to the next one
    elif tail.strip():
        try:
            json.loads(tail.decode("utf-8", errors="replace"))
            body += tail + b"\n"
        except ValueError:
            consumed = len(body)
    text = body.decode("utf-8", errors="replace")
    lines = text.split("\n")
    if skip_first and lines:
        lines = lines[1:]
    return [line for line in lines if line.strip()], start + consumed, more


def _clean_category(value: object) -> str:
    """The refusal category as it may appear in a message: letters, digits, `_` and `-` only, at most
    _MAX_CATEGORY characters. The text comes from the transcript and is no instruction."""
    if not isinstance(value, str):
        return ""
    return "".join(ch for ch in value if ch.isascii() and (ch.isalnum() or ch in "_-"))[:_MAX_CATEGORY]


def _clean_model(value: object) -> str:
    """A model name as it may appear in the state file and a message: letters, digits and `._:@/-` only, at
    most _MAX_MODEL characters; "" for anything else. Text from the transcript, no instruction."""
    if not isinstance(value, str):
        return ""
    return "".join(ch for ch in value if ch.isascii() and (ch.isalnum() or ch in _MODEL_CHARS))[:_MAX_MODEL]


def scan_transcript(lines: list[str], last_model: Optional[str]) -> dict:
    """What the lines say: {"refusals": [category or ""], "switches": [(from, to)], "last_model": str|None,
    "model": the model of the last real record}. Pure, for the probes."""
    refusals: list[str] = []
    switches: list[tuple[str, str]] = []
    last = last_model
    for line in lines:
        if '"assistant"' not in line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        message = record.get("message") if isinstance(record, dict) else None
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        if message.get("stop_reason") == "refusal":
            details = message.get("stop_details")
            category = details.get("category") if isinstance(details, dict) else ""
            refusals.append(_clean_category(category))
        raw = message.get("model")
        model = _clean_model(raw) if isinstance(raw, str) and raw != _SYNTHETIC else ""
        if model:
            if last is not None and model != last:
                switches.append((last, model))
            last = model
    return {"refusals": refusals, "switches": switches, "last_model": last}


def _transcript_for(event: str, payload: dict) -> Optional[Path]:
    """The transcript to read: the session's at Stop, the worker's own at SubagentStop (given path only
    below the session transcript's folder, as usage.py does; else the standard place next to it)."""
    session = payload.get("transcript_path")
    if event == "Stop":
        return Path(session) if isinstance(session, str) and session and Path(session).is_file() else None
    if not (isinstance(session, str) and session):
        return None
    agent_id = payload.get("agent_id")
    given = payload.get("agent_transcript_path")
    folder = Path(session).resolve().parent
    if isinstance(given, str) and given:
        path = Path(given).resolve()
        if folder in path.parents and path.is_file():
            return path
    if isinstance(agent_id, str) and _SAFE_ID_RE.match(agent_id):
        candidate = Path(session).with_suffix("") / "subagents" / f"agent-{agent_id}.jsonl"
        if candidate.is_file():
            return candidate
    return None


def _messages(event: str, payload: dict, scanned: dict) -> Optional[str]:
    """The note for the orchestrator, or None when the lines held nothing."""
    refusals, switches = scanned["refusals"], scanned["switches"]
    if not refusals and not switches:
        return None
    category = next((item for item in refusals if item), "")
    refused = (
        f" after a safety-filter refusal{f' ({category})' if category else ''}" if refusals else ""
    )
    steps = "; ".join(f"`{old}` -> `{new}`" for old, new in switches[:3])
    now_on = scanned["last_model"]
    if event == "SubagentStop":
        role = payload.get("agent_type") if isinstance(payload.get("agent_type"), str) and payload.get("agent_type") else "worker"
        agent_id = payload.get("agent_id") if isinstance(payload.get("agent_id"), str) else ""
        agent_id = agent_id if _SAFE_ID_RE.match(agent_id) else ""
        who = f"worker `{role}`" + (f" ({agent_id})" if agent_id else "")
        if switches:
            core = f"{who} continued on another model{refused}: {steps}."
        else:
            core = f"{who} was refused by the safety filter (no change of model seen yet; it now runs on `{now_on}`)."
        return (
            f"[act] model switch: {core} Claude Code does not show this in the chat. Tell the human at the start "
            "of your next reply, name the role and the model, and treat its result as unchecked until you have "
            "read it. (A model chosen for the role is no switch; one changed with /model shows up here too.)"
        )
    if switches:
        core = f"this session now runs on `{now_on}`{refused}: {steps}."
    else:
        core = f"the safety filter refused a request of this session (it runs on `{now_on}`)."
    return (
        f"[act] model switch: {core} Tell the human at the start of your next reply that this session runs on "
        "that model until it is restarted. (If the human changed the model with /model, say so and drop it.)"
    )


def run(event: str, payload: dict) -> None:
    """Stop / SubagentStop: read what the transcript gained since the last read and, if it shows a refusal
    or a changed model, queue the note for the orchestrator. Always returns None (nothing is printed for the
    human). A note that cannot be queued raises OSError for dispatch.py, which reports it."""
    if event not in ("Stop", "SubagentStop"):
        return None
    config = actlib.read_config()
    if _check_mode(config, "model-switch", default="warn") == "off":
        return None
    transcript = _transcript_for(event, payload)
    if transcript is None:
        return None
    root = _project_root()
    state_path = _state_file(root, transcript)
    state = _load(state_path)
    offset = state.get("offset") if isinstance(state.get("offset"), int) else 0
    last_model = _clean_model(state.get("model")) or None
    scanned: dict = {"refusals": [], "switches": [], "last_model": last_model}
    new_offset = offset
    try:
        for _ in range(_MAX_BLOCKS):
            lines, new_offset, more = _new_lines(transcript, new_offset)
            part = scan_transcript(lines, scanned["last_model"])
            scanned["refusals"] += part["refusals"]
            scanned["switches"] += part["switches"]
            scanned["last_model"] = part["last_model"]
            if not more:
                break
    except OSError:
        return None
    note = _messages(event, payload, scanned)
    if scanned["refusals"] and scanned["switches"]:
        # a refusal that made the model change is a severe event: one row in the incident log (model name only)
        try:
            import incidents  # noqa: E402 -- .act/scripts/ is on sys.path, as for actlib
            incidents.record(root, "model-switch", "model_switch", scanned["switches"][-1][1],
                             "worker" if event == "SubagentStop" else "main")
        except Exception:  # noqa: BLE001 -- the log must never break the check
            pass
    if note is not None:
        # queued before the offset is saved: when queuing raises, the offset stays and the next Stop reports it
        protected_watch.queue_orchestrator_note(str(root).replace("\\", "/"), note)
    _save(root, state_path, {"offset": new_offset, "model": scanned["last_model"], "path": str(transcript)})
    _prune(root)
    return None
