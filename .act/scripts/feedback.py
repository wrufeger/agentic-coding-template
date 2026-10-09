#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Voluntary feedback from a derived project to the template author — so real work in
#          real projects turns into better default rules, scripts, skills and a clearer
#          human/AI hand-off in the template. What is reported is NEVER the project, only what
#          served the WORKING METHOD well or was missing. Full policy: .act/rules/topics/feedback.md.
#
#          Four things hold without exception:
#            1. No file ever leaves the project. The assistant reads `.act/`, the generated
#               bridges and `docs/ai/` — but sends only what is useful to a STRANGER: which rule
#               was added, which workflow proved itself, which script or skill was born here.
#               Never a project name, a path, a number from the project, or a quote.
#            2. Nothing is ever sent without consent (docs/ai/config.md § Feedback, key
#               `feedback`) — except a hand-written message via --direct, see there.
#            3. Every send is LOGGED, in two places: the full payload lands under
#               .act-local/feedback/sent/ (gitignored, never versioned) and, additionally,
#               a one-line journal entry (date, kind, entry count, schema version — never the
#               content) is written to docs/ai/work/ledger/ via entries.py.
#            4. At most as often as `feedback-cadence` allows; --force lifts that gate for a
#               manual send (the skill act-feedback does this after showing --plan).
#
#          Every string that could leave the project runs through feedback_privacy.py first
#          (secrets, paths, mail addresses, IPs, foreign URLs). A hit means: not sent, reported.
#
#          Deliberately different from the template's earlier (German) feedback.py:
#            - No legacy-format migration: this build has no prior projects to carry forward, so
#              the old script's dual old/new front-matter parsing is dropped outright.
#            - Pending entries and small bookkeeping (project id, cadence counters) live under
#              .act-local/feedback/ (gitignored, per checkout) instead of a versioned entry file
#              per finding — the finished protocol of an actual send lives there too now (no
#              versioned copy of a send's full payload at all; a one-line journal entry via
#              entries.py is the in-repo proof instead, see _write_journal_entry()).
#              A team therefore gets one project id per checkout, not one per project. The id is
#              created lazily wherever a payload is actually built (_build_payload for --plan and
#              --send, cmd_direct for --direct) and persisted right away — not only on --enable,
#              since `feedback` is normally switched on directly in docs/ai/config.md, never via
#              --enable at all.
#            - "mcp_server" is not collected: this template stage does not know which servers of
#              the MCP catalog (.act/mcp-catalog.md) a project uses. With scope "c" a send carries
#              `tools` (counts of agents/skills/scripts on disk) and `usage`: the invocation counts
#              from .act-local/usage.json since the previous send (the counts at that send are
#              kept in state.json, so every send reports only what is new), as
#              {"since": date, "skills": {name: n}, "scripts": {name: n}} - template skills and
#              scripts by name (the names listed in .act/MANIFEST.json), everything else (a skill
#              or script built in the project) only as ONE collective counter `own` in each of the
#              two maps, never by name.
#            - The adaptive cadence threshold drops the old "lower it after a template update"
#              factor (no reliable per-date update log to read yet); the ignored/postponed/
#              consecutive-sends factors are kept.
#            - This repo is not (yet) fully guarded against running on the template checkout
#              itself — the old template.json had an `is_template` marker for that; nothing
#              equivalent exists in .act-lock.json yet. --direct refuses outright when there is no
#              .act-lock.json at all (the template checkout's own state, see cmd_direct); the
#              other commands still lack that guard — open point, see hand-back report.
#            - Four old top-level fields are dropped outright, not just left empty:
#              `setup_path`/`entry_mode` (no --enable-driven interview flow exists to fill them
#              from), `tools_removed` (no "remove a KI tool" step exists in this build to report
#              on), `questionnaire` (the skeleton ships no feedback.md with human-written answers
#              to collect). `switches` and `rule_sets` ARE kept (see _switches()/_rule_sets()
#              below), reshaped for this build's actual config keys.
#
# Usage:
#   --target <dir>
#       Every command below acts on the project at <dir> instead of the checkout this script is
#       run from — its outbox, its state, its docs/ai/config.md, its .act-lock.json. Needed for
#       act-adopt, which runs from the template checkout against a project being adopted at
#       <dir>; without it, every command below acts on the checkout's own project as found by
#       actlib.repo_root() (walking upward from the current working directory).
#   python .act/scripts/feedback.py --status
#       Consent, target URL, how many entries are waiting, when last sent. Writes nothing.
#   python .act/scripts/feedback.py --enable [--mode confirm|automatic|manual] [--repo-url <url>]
#       Sets `feedback` in docs/ai/config.md (default: automatic). --repo-url is only sent if it
#       is public (https://); without it, a message carries no repo URL (the project id is separate).
#   python .act/scripts/feedback.py --disable
#       Sets `feedback` to `off`. Collecting stops; a hand-written --direct message still goes out.
#   python .act/scripts/feedback.py --add --kind <rule|script|skill|workflow|docs|bug|mcp|link>
#                                    --title "<one line>" --text "<2-6 sentences>" [--url <link>]
#       Stores a finding under .act-local/feedback/entries/. Sends nothing by itself — UNLESS
#       `feedback` is `automatic` and `feedback-cadence` is `immediate` (same send as --send), or
#       --kind is `bug` (a template bug bypasses the cadence gate entirely, never the consent
#       gate — see .act/rules/topics/feedback.md § "Immediate trigger"). Written for a stranger:
#       pattern, not project — no names, no paths, no code.
#   python .act/scripts/feedback.py --plan        (default)
#       Shows the full payload that would be sent. Writes and sends nothing.
#   python .act/scripts/feedback.py --send [--force] [--yes]
#       Sends if consent, the privacy check and the cadence gate all allow it. --force lifts the
#       cadence gate (not the consent gate — `feedback: off` still refuses). --yes confirms an
#       actual send when `feedback` is `confirm` (without it, that mode only shows the payload).
#   python .act/scripts/feedback.py --direct "<text>" [--contact <email>]
#       Sends a hand-written message AT ONCE — independent of consent and cadence. Whoever writes
#       the text and triggers the send has already done everything consent is otherwise for. With
#       `feedback: off`, only the text, the full template commit hash and the project id leave the
#       project — no further context. The project id goes with every direct message (never the
#       repo URL — a direct message stays minimal on purpose), so several messages from the same
#       project can be told apart; it is created when the message is built if it does not exist yet.
#       --contact <email> (only with --direct) adds a reply address as the field `contact`, for
#       this one message: never stored, never filled in by itself, shape-checked narrowly. A mail
#       address inside the text is still rejected. The privacy check still runs. Refuses outright with no
#       .act-lock.json on disk (the template checkout's own state, not a derived project's).
#   python .act/scripts/feedback.py --due
#       Reports whether a reminder is due under the current cadence (fixed interval, or the
#       learned threshold for `feedback-cadence: adaptive`) — for a dispatcher to call at session
#       start instead of embedding this logic in a hook. Never fails: always exit 0. When due
#       under `adaptive`, advances the same-day-only learning marker in .act-local/feedback/state.json.
#   python .act/scripts/feedback.py --postpone <days>
#       Pauses the due reminder for <days> days (writes `reminder_paused_until`) AND counts as a
#       postponement for the adaptive-cadence learning (`postponements`, resets `consecutive_sends`
#       to 0) — the same single action the earlier feedback.py's --postpone/--verschieben did.
#       Sends nothing, changes no config.
#   python .act/scripts/feedback.py --clear
#       Discards every waiting entry without sending. What was already sent stays in its protocol
#       — that is the proof and is never cleared.
#   python .act/scripts/feedback.py --target <dir> --discard-harvest
#       Removes <dir>/.act-local/adopt/harvest.md (act-adopt step 6's local list of candidates for
#       the template) without adding anything to the outbox — the path for
#       docs/ai/config.md's `feedback: off`. No-op (exit 0) if the file is not there.
#
# Output format: plain text; a payload is shown as an indented JSON block. Exit 0 = ok, 1 =
#   payload rejected (not sent), 2 = aborted (no consent, missing argument, transport error).

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Optional

import actlib
import feedback_privacy

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# Target of the report. A constant here on purpose: it must be reachable from every derived
# project, not only from the template's own development checkout. Overridable per run via
# ENDPOINT_ENV, so a test never has to touch this line.
FEEDBACK_ENDPOINT = "https://rufeger.de/agentic-coding-feedback"
ENDPOINT_ENV = "AGENTIC_FEEDBACK_URL"

# Wire schema numbers — kept identical to the template's earlier feedback.py so the existing
# server endpoint (feedback-endpoint.php et al.) keeps accepting both the batch and the direct
# payload without a server-side change.
SCHEMA_BATCH = 3
SCHEMA_DIRECT = 4

# Origin marker every message carries. DELIBERATELY PUBLIC and checked in — it is not a secret
# and must not look like one: it only tells the endpoint that a message comes from a project
# using this template, keeping accidental noise out. Not named "secret"/"token"/"key" on purpose:
# words like that are exactly what feedback_privacy.SECRET_WORDS filters out further down this
# same chain.
ORIGIN = "agentic-coding-template/1"

STATE_DIR_REL = ".act-local/feedback"
STATE_FILE_REL = ".act-local/feedback/state.json"
ENTRIES_DIR_REL = ".act-local/feedback/entries"
# The full payload of every send stays local (gitignored) — never versioned, no choice to
# make. The proof for a stranger reading the project's own history is the one-line journal entry
# _write_journal_entry() adds to docs/ai/work/ledger/, not this file.
PROTOCOL_DIR_REL = ".act-local/feedback/sent"

MODE_VALUES = ("off", "confirm", "automatic", "manual")
# Minimum gap per cadence, in hours (None: no fixed interval — needs --force). Same table as
# docs/ai/config.md § Feedback documents; "adaptive" has no fixed interval, its own threshold is
# computed in _adaptive_threshold().
CADENCE_HOURS = {"manual": None, "immediate": 0, "hourly": 1, "daily": 24, "weekly": 168}
CADENCE_VALUES = tuple(CADENCE_HOURS) + ("adaptive",)
KINDS = ("rule", "script", "skill", "workflow", "docs", "bug", "mcp", "link")

TITLE_MAX = 120
TEXT_MAX = 1200
DIRECT_MAX = 4000
TIMEOUT_S = 15

# Server-side hard limits (feedback-endpoint.php: EINTRAEGE_MAX, BODY_MAX) — a send is chunked
# into several POSTs, one protocol each, rather than risking a 413 or a silently truncated batch.
ENTRIES_PER_SEND_MAX = 20
BODY_BYTES_MAX = 32768

# Shape of the random id --enable/_build_payload create — must match feedback-endpoint.php's own
# validieren_gesammelt() (`^[0-9a-f]{32}$`), checked again here before anything is sent so a
# tampered state.json is caught before it leaves the project, not after a 400 from the server.
PROJECT_ID_RE = re.compile(r"^[0-9a-f]{32}$")
# Reply address of --direct --contact: plain ASCII local@host.tld. Deliberately a subset of what
# PHP's FILTER_VALIDATE_EMAIL accepts on the server: anything the server would reject makes it
# drop the field silently, while this client has already reported "sent". ASCII only, so no
# bidi/zero-width/control characters, URLs, paths or markup can pass as an "address".
CONTACT_RE = re.compile(
    r"[A-Za-z0-9_%+-]+(?:\.[A-Za-z0-9_%+-]+)*@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)*\.[A-Za-z]{2,63}", re.ASCII)
CONTACT_MAX = 254
CONTACT_LOCAL_MAX = 64


def _valid_contact(value: object) -> bool:
    """True for a plain ASCII e-mail address within the length limits."""
    return (isinstance(value, str) and len(value) <= CONTACT_MAX
            and CONTACT_RE.fullmatch(value) is not None
            and len(value.split("@", 1)[0]) <= CONTACT_LOCAL_MAX)

# Scope "a": closed vocabulary of docs/ai/config.md keys whose VALUE says only how the template
# was configured, never a project fact — same idea as the earlier feedback.py's SCHALTER
# whitelist, reshaped for this build's actual config keys (mode/output-depth/dependency-check/
# logging/log-level/tips instead of AI-CONFIG.md's Orchestrator-Modell/Commit-Verhalten/...).
# feedback-endpoint.php's own SCHALTER constant still lists the old key names and would currently
# drop these silently rather than reject them (empty groups are pruned server-side, see its own
# comment) — updating it is a separate, later server change, not part of this one.
SWITCHES_WHITELIST = ("mode", "output-depth", "dependency-check", "logging", "log-level", "tips")

# Adaptive-cadence learning (mirrors the template's earlier feedback-check.py, minus the
# template-update factor — see the header comment's "deliberately different" note).
ADAPTIVE_BASE_DAYS = 5
ADAPTIVE_MIN_DAYS = 2
ADAPTIVE_MAX_DAYS = 30
ADAPTIVE_NEGATIVE_FACTOR = 1.5   # per ignored reminder or postponement
ADAPTIVE_POSITIVE_FACTOR = 0.7  # per send in a row
MIN_REMINDER_INTERVAL_H = 48    # hard floor regardless of cadence or learned threshold


# ---------------------------------------------------------------------------
# Config (docs/ai/config.md) — reading via actlib, writing a single cell here
# ---------------------------------------------------------------------------

def _set_config_value(root: Path, key: str, value: str) -> bool:
    """Writes the "Value" column of exactly one row in docs/ai/config.md — same one-cell-only
    approach as init.py's own bulk write, just for a single key after the fact. False if the row
    is not found (config.md missing, or the key was renamed)."""
    path = root / "docs" / "ai" / "config.md"
    if not path.is_file():
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    pattern = re.compile(r"(?m)^(\|\s*`" + re.escape(key) + r"`\s*\|)([^|]*)(\|)")
    if not pattern.search(text):
        return False
    new_text = pattern.sub(lambda m: m.group(1) + " " + value + " " + m.group(3), text, count=1)
    try:
        path.write_text(new_text, encoding="utf-8")
    except OSError:
        return False
    return True


def _read_config_at(root: Path) -> dict[str, str]:
    """`actlib.read_config(root)` under this script's own name — kept as a thin alias (rather than
    rewriting every call site below to `actlib.read_config(root)` directly) since the adopt flow predates
    `read_config()` taking an explicit `root`; now that it does, this is the one place that would
    need to change if the two ever diverged again."""
    return actlib.read_config(root)


def _read_lock_at(root: Path) -> dict:
    """Same as actlib.read_lock(), for an explicit `root` (actlib.read_lock() takes none) — needed
    for --target the same way _read_config_at() used to be, before actlib.read_config() itself
    grew a `root` parameter."""
    data = actlib._read_json(root / ".act-lock.json")
    if data is None:
        return actlib._default_lock()
    result = actlib._default_lock()
    result.update(data)
    return result


def _mode(config: dict[str, str]) -> str:
    value = (config.get("feedback") or "off").strip().lower()
    return value if value in MODE_VALUES else "off"


def _cadence(config: dict[str, str]) -> str:
    value = (config.get("feedback-cadence") or "weekly").strip().lower()
    return value if value in CADENCE_VALUES else "weekly"


def _scope(config: dict[str, str]) -> set[str]:
    raw = config.get("feedback-scope") or "a,b,c"
    return {t.strip().lower() for t in raw.split(",") if t.strip().lower() in {"a", "b", "c"}}


def _protocol_dir(root: Path) -> Path:
    return root / PROTOCOL_DIR_REL


_GITHUB_SOURCE_RE = re.compile(
    r"(?i)^(?:https?://github\.com/|git@github\.com:)([\w.-]+/[\w.-]+?)(?:\.git)?/?$")


def _template_repo(lock: dict) -> Optional[str]:
    """The template's own "owner/repo" path if .act-lock.json § template.source is a github.com
    address, else None. Passed to feedback_privacy.check_text() so its github.com exception
    covers only the template's own repo, not "any github.com URL" (a link to some OTHER project's
    private github repo is exactly the kind of thing that must still be flagged)."""
    source = (lock.get("template") or {}).get("source") or ""
    match = _GITHUB_SOURCE_RE.match(source)
    return match.group(1) if match else None


def _endpoint() -> str:
    """Target address, ALWAYS with a trailing slash — without it the real endpoint answers a POST
    with a 301 to the slash variant, and urllib turns a redirected POST into a GET (the payload
    would vanish, the caller would only see an uninformative "405"; confirmed 2026-09-15 against the
    real endpoint in the template's earlier feedback.py)."""
    raw = (os.environ.get(ENDPOINT_ENV) or FEEDBACK_ENDPOINT).rstrip("/")
    return raw + "/"


# ---------------------------------------------------------------------------
# State (.act-local/feedback/state.json) — gitignored, per checkout
# ---------------------------------------------------------------------------

def _read_state(root: Path) -> dict:
    path = root / STATE_FILE_REL
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_state(root: Path, state: dict) -> None:
    """Atomic write (temp file + os.replace) in the same directory — no reader ever sees a
    half-written state.json, and a failure never leaves a stray temp file behind."""
    path = root / STATE_FILE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                          dir=str(path.parent), prefix=path.name + ".",
                                          suffix=".tmp", delete=False) as handle:
            tmp_path = handle.name
            json.dump(state, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        actlib.replace_file(tmp_path, path)
    except BaseException:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


# ---------------------------------------------------------------------------
# Outbox entries (.act-local/feedback/entries/*.json) — gitignored, per checkout
# ---------------------------------------------------------------------------

def _entry_slug(title: str) -> str:
    raw = (title or "entry").lower()
    raw = "".join(c if c.isalnum() else "-" for c in raw)
    raw = "-".join(part for part in raw.split("-") if part)[:50]
    return raw or "entry"


def _free_path(directory: Path, base: str, suffix: str) -> Path:
    """Next free directory/base+suffix path — on a collision, suffix -2, -3, ... Never overwrites
    an existing file, e.g. two immediate sends in the same second (cadence "immediate")."""
    path = directory / f"{base}{suffix}"
    n = 2
    while path.exists():
        path = directory / f"{base}-{n}{suffix}"
        n += 1
    return path


def _write_entry(root: Path, entry: dict) -> Path:
    directory = root / ENTRIES_DIR_REL
    directory.mkdir(parents=True, exist_ok=True)
    base = f"{entry['date']}-{_entry_slug(entry['title'])}"
    path = _free_path(directory, base, ".json")
    path.write_text(json.dumps(entry, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _read_entries(root: Path) -> list[dict]:
    """The waiting entries, already in wire form (kind/title/text/date/url) — a malformed or
    incomplete file is skipped rather than raised, since this is gitignored local bookkeeping,
    not a record anyone needs to recover byte for byte."""
    directory = root / ENTRIES_DIR_REL
    if not directory.is_dir():
        return []
    entries = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and data.get("kind") and data.get("title"):
            entries.append(data)
    return entries


def _clear_outbox(root: Path) -> None:
    """Removes every waiting entry — called only right after a successful send: the protocol
    written for that send already holds a full copy of each entry, so this is not a second, lossy
    place they live."""
    directory = root / ENTRIES_DIR_REL
    if not directory.is_dir():
        return
    for path in directory.glob("*.json"):
        try:
            path.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Metrics (scope "a"/"b"/"c") — numbers only, never names, paths or text
# ---------------------------------------------------------------------------

def _git(root: Path, *args: str) -> str:
    """A git call that never disturbs the caller: if it fails (no repo, no git, timeout), there
    are simply no numbers."""
    try:
        result = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                                 timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout if result.returncode == 0 else ""


_METRICS_SKIP_DIRS = {".git", "node_modules", ".venv", "dist", "build", ".output", ".nuxt",
                       "__pycache__"}


def _metrics(root: Path) -> dict:
    """Scope "a": numbers from `git log` and the filesystem only — nothing that could name or
    identify the project. What cannot be determined is left out, never guessed."""
    metrics: dict = {}
    # Pathspec "-- .": root can be a sub-project inside a larger git repository — without a
    # pathspec, `git log` would count every commit of the whole repo, not just this project.
    dates = _git(root, "log", "--format=%ad", "--date=short", "--", ".").split()
    if dates:
        metrics["commits"] = len(dates)
        metrics["days_active"] = len(set(dates))
        metrics["first_commit"] = dates[-1]
        metrics["last_commit"] = dates[0]
        since = time.strftime("%Y-%m-%d", time.localtime(time.time() - 30 * 86400))
        metrics["commits_30_days"] = sum(1 for d in dates if d >= since)
    docs_ai_hits = _git(root, "log", "--format=%h", "--", "docs/ai").split()
    if docs_ai_hits:
        metrics["commits_docs_ai"] = len(docs_ai_hits)
    file_count, total_bytes = 0, 0
    for path in root.rglob("*"):
        if any(part in _METRICS_SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file():
            file_count += 1
            try:
                total_bytes += path.stat().st_size
            except OSError:
                pass
    metrics["files"] = file_count
    metrics["size_mb"] = round(total_bytes / 1_048_576, 1)
    log_path = root / "ai.log"
    if log_path.exists():  # only if logging is actually on — off by default
        try:
            lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
            metrics["log_lines"] = len(lines)
            metrics["log_sessions"] = sum(1 for line in lines if "[session]" in line and " start" in line)
        except OSError:
            pass
    return metrics


_RULE_CHANGE_AREAS = {
    "rules": ".act/rules", "coding": ".act/coding",
    "coding_rules_md": "docs/project/coding_rules.md", "core_rules_md": "docs/ai/rules.md",
    "skills": ".act/skills", "scripts": ".act/scripts",
}


def _rule_changes(root: Path) -> dict:
    """Scope "b": how often the AI rules and the doc structure were worked on, as a COUNT per
    area, never as content. That a rule was added is useful to the template; WHAT it says is
    something the assistant describes in its own entry (--add) if it is useful to a stranger."""
    result = {}
    for name, path in _RULE_CHANGE_AREAS.items():
        hits = _git(root, "log", "--format=%h", "--", path).split()
        if hits:
            result[name] = len(hits)
    return result


def _tool_counts(root: Path) -> dict:
    """Scope "c": how many agents/skills/scripts the project has — counts only, no names (a
    self-built file's name often gives the project away)."""
    result = {}
    for name, folder, pattern in (("agents", ".act/agents", "*.md"),
                                   ("skills", ".act/skills", "*"),
                                   ("scripts", ".act/scripts", "*.py")):
        directory = root / folder
        if directory.is_dir():
            result[name] = len([p for p in directory.glob(pattern) if p.name != "README.md"])
    return result


def _template_names(root: Path) -> tuple[set[str], set[str]]:
    """Names of the skills and scripts the TEMPLATE ships, read from .act/MANIFEST.json (its keys
    are paths below .act/). Without a manifest nothing counts as a template name, so every use is
    reported only as `own` - never a name that might be the project's."""
    try:
        data = json.loads((root / ".act" / "MANIFEST.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set(), set()
    skills: set[str] = set()
    scripts: set[str] = set()
    for rel in data if isinstance(data, dict) else ():
        parts = str(rel).split("/")
        if len(parts) >= 3 and parts[0] == "skills":
            skills.add(parts[1])
        elif len(parts) == 2 and parts[0] == "scripts" and parts[1].endswith(".py"):
            scripts.add(parts[1][:-3])
    return skills, scripts


def _usage_counts(root: Path) -> dict[str, dict[str, int]]:
    """Raw invocation counts per category ("skills", "scripts") from .act-local/usage.json,
    read directly (never consolidated - building a payload must not write). Missing or unreadable
    file: empty counts."""
    try:
        data = json.loads((root / ".act-local" / "usage.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    result: dict[str, dict[str, int]] = {"skills": {}, "scripts": {}}
    for category in result:
        section = data.get(category) if isinstance(data, dict) else None
        for name, entry in (section.items() if isinstance(section, dict) else ()):
            count = entry.get("count") if isinstance(entry, dict) else None
            if isinstance(count, int) and count > 0:
                result[category][str(name)] = count
    return result


def _earliest_first_used(root: Path) -> str:
    """Earliest `first_used` day over the skills and scripts in .act-local/usage.json, or "" when
    there is none (missing file, no dates)."""
    try:
        data = json.loads((root / ".act-local" / "usage.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    days: list[str] = []
    for category in ("skills", "scripts"):
        section = data.get(category) if isinstance(data, dict) else None
        for entry in (section.values() if isinstance(section, dict) else ()):
            day = entry.get("first_used") if isinstance(entry, dict) else None
            if isinstance(day, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                days.append(day)
    return min(days) if days else ""


def _usage_since_last_send(root: Path, state: dict) -> dict:
    """Scope "c": invocation counts since the previous send - current counts minus the baseline
    stored in state.json at that send. Template names stay as they are, every other name is added
    up into the single counter `own`. Names a stranger could recognise never leave the project."""
    template_skills, template_scripts = _template_names(root)
    baseline = state.get("usage_baseline")
    baseline = baseline if isinstance(baseline, dict) else {}
    counts = _usage_counts(root)
    usage: dict = {}
    since = str(state.get("usage_baseline_at") or state.get("last_sent") or "")[:10]
    if not since:
        # First send, nothing reported before: everything counted so far, from the earliest day
        # usage.json knows - or no start date at all when it knows none.
        since = _earliest_first_used(root)
    if since:
        usage["since"] = since
    for category, known in (("skills", template_skills), ("scripts", template_scripts)):
        before = baseline.get(category)
        before = before if isinstance(before, dict) else {}
        merged: dict[str, int] = {}
        for name, count in counts[category].items():
            base = int(before.get(name) or 0)
            if base > count:
                base = 0  # usage.json was reset since the baseline was taken: count from zero
            delta = count - base
            if delta <= 0:
                continue
            key = name if name in known else "own"
            merged[key] = merged.get(key, 0) + delta
        usage[category] = merged
    return usage


def _switches(config: dict[str, str]) -> dict:
    """Scope "a": the value of each SWITCHES_WHITELIST key that is actually set — a closed-
    vocabulary settings snapshot, never a project fact. A key config.md does not have (or whose
    value is empty) is simply left out."""
    return {key: config[key] for key in SWITCHES_WHITELIST if config.get(key)}


def _rule_sets(root: Path) -> list:
    """Scope "b": which coding rule-set bundles are enabled, if this build tracks that anywhere
    that can be read without opening docs/project/coding_rules.md (out of scope for this check —
    see the review note this responds to). Neither docs/ai/config.md nor .act-lock.json carries
    that selection at this build stage — .act-lock.json's own top-level keys are `template`,
    `migrations_applied` and `removed_by_user` (see actlib._default_lock()), none of which name a
    rule set — so this returns [] until one of them does."""
    del root  # kept as a parameter so a future implementation does not need to change the call site
    return []


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------

def _ensure_project_id(root: Path, config: dict[str, str], state: dict) -> dict:
    """Creates and persists a project id the first time a payload is built — not only via
    --enable, which `feedback` is normally never switched through (it is edited directly in
    docs/ai/config.md). The id exists whatever `feedback` says: it only tells messages from the
    same checkout apart and carries no content. Mutates and returns `state`; a no-op once an id
    exists. `config` is kept for the callers' signature."""
    del config
    if not state.get("project_id"):
        state["project_id"] = uuid.uuid4().hex
        _write_state(root, state)
    return state


def _build_payload(root: Path, config: dict[str, str]) -> dict:
    scope = _scope(config)
    state = _ensure_project_id(root, config, _read_state(root))
    lock = _read_lock_at(root)
    template = lock.get("template") or {}
    payload: dict = {
        "schema": SCHEMA_BATCH,
        "origin": ORIGIN,
        "project_id": state.get("project_id"),
        "date": time.strftime("%Y-%m-%d"),
        # Full hash, not shortened: the receiving side has the full history and can derive
        # date/distance from it itself; a shortened hash would be ambiguous across many projects.
        "template_base": template.get("commit") or None,
        "scope": ",".join(sorted(scope)),
        "entries": _read_entries(root),
    }
    if "a" in scope:
        payload["metrics"] = _metrics(root)
        switches = _switches(config)
        if switches:
            payload["switches"] = switches
    if "b" in scope:
        payload["rule_changes"] = _rule_changes(root)
        rule_sets = _rule_sets(root)
        if rule_sets:
            payload["rule_sets"] = rule_sets
    if "c" in scope:
        payload["tools"] = _tool_counts(root)
        payload["usage"] = _usage_since_last_send(root, state)
    if state.get("repo_url"):
        payload["repo_url"] = state["repo_url"]
    return payload


def _check_payload(payload: dict, endpoint: str, *, template_repo: Optional[str] = None) -> list[str]:
    """Every string in the payload against feedback_privacy.check_text() (or, for a link's own
    URL, the stricter check_link()). Returns a list of findings — empty means: nothing
    objectionable. `project_id`/`repo_url`/`template_base` get their own narrow, shape-only check
    instead of a blanket exemption: each is given on purpose, but a tampered value (a path instead
    of an id, a private host as the repo URL) must not slip through unchecked."""
    findings: list[str] = []

    def walk(value, path, *, is_link_url=False):
        if isinstance(value, str):
            if is_link_url:
                for reason in feedback_privacy.check_link(value):
                    findings.append(f"{path}: {reason}")
            else:
                for reason in feedback_privacy.check_text(value, endpoint, template_repo=template_repo):
                    findings.append(f"{path}: {reason}")
        elif isinstance(value, dict):
            for key, sub in value.items():
                walk(sub, f"{path}.{key}", is_link_url=(key == "url" and value.get("kind") == "link"))
        elif isinstance(value, list):
            for index, sub in enumerate(value):
                walk(sub, f"{path}[{index}]")

    for key, value in payload.items():
        if key == "project_id":
            if value is not None and not (isinstance(value, str) and PROJECT_ID_RE.fullmatch(value)):
                findings.append(f"{key}: not a 32-character hex id")
            continue
        if key == "repo_url":
            if isinstance(value, str):
                for reason in feedback_privacy.check_link(value):
                    findings.append(f"{key}: {reason}")
            continue
        if key == "contact":
            # A reply address the human gave on purpose with --direct --contact: simple mail
            # shape only (the text check would flag any mail address): plain ASCII, local part
            # at most 64 and the whole address at most 254 characters.
            if not _valid_contact(value):
                findings.append(f"{key}: not a plain ASCII e-mail address (name@host.tld, local part at most "
                                f"{CONTACT_LOCAL_MAX}, at most {CONTACT_MAX} characters)")
            continue
        if key == "template_base":
            # Full commit hash (up to 40 hex chars) — LONG_HEX would otherwise flag it as a
            # secret. Checked narrowly instead of skipped: only hex, 7-40 chars; anything else is
            # not a hash and does not leave the project (a tampered .act-lock.json).
            if not (isinstance(value, str) and feedback_privacy.COMMIT_HASH.fullmatch(value)):
                findings.append(f"{key}: not a commit hash (expected 7-40 hex characters)")
            continue
        walk(value, key)
    return findings


def _show(payload: dict, endpoint: str) -> None:
    print(f"target:  {endpoint}")
    if payload.get("kind") == "direct":
        print("content: a hand-written message")
    else:
        print(f"entries: {len(payload.get('entries') or [])}")
    print("")
    print("full payload:")
    for line in json.dumps(payload, indent=2, ensure_ascii=False).split("\n"):
        print("  " + line)


# ---------------------------------------------------------------------------
# Sending and protocol
# ---------------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirects are NOT followed. Reason: urllib turns a redirected POST into a GET — the
    payload would be gone, and the receiver would answer with a misleading 405. A clear error
    naming the target address is cheaper than that search."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_SENDER = urllib.request.build_opener(_NoRedirect)


def _post(endpoint: str, payload: dict) -> tuple[Optional[int], Optional[str]]:
    """(code, error_text). Exactly one POST, no redirect, a readable diagnosis on failure."""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        endpoint, data=data, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8",
                 "User-Agent": "agentic-coding-template-feedback/1"})
    try:
        with _SENDER.open(request, timeout=TIMEOUT_S) as response:
            return response.status, None
    except urllib.error.HTTPError as exc:
        if exc.code in (301, 302, 303, 307, 308):
            target = exc.headers.get("Location", "(no target)")
            return None, (f"the receiver redirects to {target} — a redirect eats a POST's body. "
                           f"Enter exactly that address as the target.")
        return None, f"receiver answers with HTTP {exc.code}."
    except (urllib.error.URLError, OSError) as exc:
        return None, f"unreachable ({exc})."


def _write_protocol(root: Path, payload: dict, endpoint: str) -> Path:
    directory = _protocol_dir(root)
    directory.mkdir(parents=True, exist_ok=True)
    path = _free_path(directory, time.strftime("%Y-%m-%d_%H%M%S"), ".json")
    path.write_text(json.dumps(
        {"sent_to": endpoint, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "payload": payload},
        indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _write_journal_entry(root: Path, title_en: str, title_de: str) -> None:
    """One journal entry per successful send (docs/ai/work/ledger/, via entries.py's own `new`) —
    date, kind (batch/direct), entry count and schema version only, in the title; NEVER the sent
    content or an entry's own title (the local protocol under .act-local/feedback/sent/ is
    the full record; this is only the project's own note that a send happened). The title follows
    `language-docs` (R-work-language, actlib.localized()) — `title_en`/`title_de` are the two
    fixed variants a caller already built, not a template this function fills in itself, since it
    is a plain sentence rather than a `.format()`-shaped one. A failure here is reported on
    stderr but never turns an already-successful send into a failure."""
    try:
        import entries
        language = actlib.docs_language(root)
        entries.cmd_new(root, "ledger", [actlib.localized(language, title_en, title_de)])
    except Exception as exc:  # noqa: BLE001 - a journal-entry failure must never fail the send
        print(f"feedback: could not write journal entry ({exc})", file=sys.stderr)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_status(root: Path) -> int:
    config = _read_config_at(root)
    mode, cadence = _mode(config), _cadence(config)
    state = _read_state(root)
    print(f"feedback:   {mode}   (cadence: {cadence}, from docs/ai/config.md)")
    print(f"target:     {_endpoint()}")
    print(f"project id: {state.get('project_id') or '- (created with the first payload built)'}")
    print(f"waiting:    {len(_read_entries(root))} entries ({ENTRIES_DIR_REL}/)")
    protocol_dir = _protocol_dir(root)
    sent = list(protocol_dir.glob("*.json")) if protocol_dir.is_dir() else []
    print(f"protocol:   {len(sent)} send(s) ({protocol_dir.relative_to(root).as_posix()}/) - "
          f"local, kept out of git")
    print(f"last sent:  {state.get('last_sent') or 'never'}")
    if state.get("repo_url"):
        print(f"repo url:   {state['repo_url']}")
    if mode == "off":
        print("")
        print("Nothing is sent. Enable with: feedback.py --enable [--mode confirm|automatic|manual]")
    return 0


def cmd_enable(root: Path, repo_url: Optional[str], mode: Optional[str]) -> int:
    mode = (mode or "automatic").strip().lower()
    if mode not in MODE_VALUES:
        print(f"error: --mode must be one of {', '.join(MODE_VALUES)}.", file=sys.stderr)
        return 2
    if not _set_config_value(root, "feedback", mode):
        print("error: row 'feedback' not found in docs/ai/config.md — set it there by hand.",
              file=sys.stderr)
        return 2
    state = _read_state(root)
    if mode != "off" and not state.get("project_id"):
        # A random id generated here — no name, no path, no hash derived from project data. It
        # makes several messages from the same project traceable to each other without naming
        # the project. Deleting .act-local/feedback/state.json gets rid of it; the next --enable
        # creates a fresh one.
        state["project_id"] = uuid.uuid4().hex
    if repo_url:
        if not repo_url.startswith("https://"):
            print("error: --repo-url must start with https:// (publicly reachable).", file=sys.stderr)
            return 2
        problems = feedback_privacy.check_link(repo_url)
        if problems:
            print("error: --repo-url is unsuitable:", file=sys.stderr)
            for reason in problems:
                print(f"  - {reason}", file=sys.stderr)
            return 2
        state["repo_url"] = repo_url
    _write_state(root, state)
    print(f"docs/ai/config.md: feedback = {mode}   (cadence: {_cadence(_read_config_at(root))})")
    if mode != "off":
        print(f"target: {_endpoint()} - protocol of every send under "
              f"{_protocol_dir(root).relative_to(root).as_posix()}/ (local, kept out of git)")
    return 0


def cmd_disable(root: Path) -> int:
    if not _set_config_value(root, "feedback", "off"):
        print("error: row 'feedback' not found in docs/ai/config.md — set it there by hand.",
              file=sys.stderr)
        return 2
    print("docs/ai/config.md: feedback = off")
    return 0


def cmd_add(root: Path, kind: Optional[str], title: Optional[str], text: Optional[str],
            url: Optional[str], yes: bool = False) -> int:
    kind = (kind or "").strip().lower()
    if kind not in KINDS:
        print(f"error: --kind must be one of {', '.join(KINDS)}.", file=sys.stderr)
        return 2
    title, text = (title or "").strip(), (text or "").strip()
    if not title or not text:
        print("error: --title and --text are both required.", file=sys.stderr)
        return 2
    if len(title) > TITLE_MAX or len(text) > TEXT_MAX:
        print(f"error: title max. {TITLE_MAX}, text max. {TEXT_MAX} characters.", file=sys.stderr)
        return 2
    endpoint = _endpoint()
    if kind == "link":
        if not url:
            print("error: --kind link requires --url.", file=sys.stderr)
            return 2
        problems = feedback_privacy.check_link(url)
        if problems:
            print("not stored - the address is unsuitable:", file=sys.stderr)
            for reason in problems:
                print(f"  - {reason}", file=sys.stderr)
            return 1
    elif url:
        print("error: --url only applies with --kind link.", file=sys.stderr)
        return 2
    problems = feedback_privacy.check_text(title, endpoint) + feedback_privacy.check_text(text, endpoint)
    if problems:
        print("not stored - the text contains:", file=sys.stderr)
        for reason in sorted(set(problems)):
            print(f"  - {reason}", file=sys.stderr)
        print("Describe the pattern, not the project: no paths, no names, no code.", file=sys.stderr)
        return 1
    entry = {"kind": kind, "title": title, "text": text, "date": time.strftime("%Y-%m-%d")}
    if url:
        entry["url"] = url
    path = _write_entry(root, entry)
    waiting = len(_read_entries(root))
    print(f"stored: {path.relative_to(root).as_posix()}. {waiting} "
          f"entr{'y' if waiting == 1 else 'ies'} waiting. Preview: feedback.py --plan")
    if kind == "bug":
        # A template bug is reported at once, independent of the cadence — see
        # .act/rules/topics/feedback.md. The consent gate (mode)
        # still applies: cmd_send prints why nothing went out if mode is "off"; the entry stays
        # stored either way (an unsent bug report is not a failed --add).
        print("template bug — bypassing the cadence gate:")
        cmd_send(root, force=False, yes=yes, bypass_cadence=True)
        return 0
    config = _read_config_at(root)
    if _mode(config) == "automatic" and _cadence(config) == "immediate":
        print("cadence 'immediate': triggering a send now.")
        if cmd_send(root, force=False, yes=yes) != 0:
            print("entry stays stored - the send will be retried next time.", file=sys.stderr)
    return 0


def cmd_plan(root: Path) -> int:
    config = _read_config_at(root)
    payload = _build_payload(root, config)
    endpoint = _endpoint()
    _show(payload, endpoint)
    print("")
    template_repo = _template_repo(_read_lock_at(root))
    problems = _check_payload(payload, endpoint, template_repo=template_repo)
    if problems:
        print("rejected - this would NOT be sent:")
        for reason in problems:
            print(f"  - {reason}")
        return 1
    if _mode(config) == "off":
        print("feedback is off - nothing would be sent (enable with --enable).")
        return 0
    print("clean. Send with: feedback.py --send")
    return 0


def _hours_since(stamp: Optional[str]) -> float:
    """Hours since the timestamp 'YYYY-MM-DD HH:MM'. Very large if never sent or unreadable."""
    if not stamp:
        return 1e9
    try:
        sent = time.mktime(time.strptime(str(stamp)[:16], "%Y-%m-%d %H:%M"))
    except ValueError:
        return 1e9
    return (time.time() - sent) / 3600.0


def _payload_size(payload: dict) -> int:
    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _chunk_entries(entries: list, envelope: dict) -> list[list]:
    """Splits `entries` into chunks that each, wrapped in `envelope`, fit ENTRIES_PER_SEND_MAX and
    BODY_BYTES_MAX (mirrors feedback-endpoint.php's own EINTRAEGE_MAX/BODY_MAX) — one send, one
    protocol per chunk. A single oversized entry still gets its own chunk (nothing is dropped);
    the server's own per-field limits are what would reject it at that point, not this script."""
    chunks: list[list] = [entries[i:i + ENTRIES_PER_SEND_MAX]
                           for i in range(0, len(entries), ENTRIES_PER_SEND_MAX)] or [[]]
    result: list[list] = []
    for chunk in chunks:
        result.extend(_shrink_chunk(chunk, envelope))
    return result


def _shrink_chunk(chunk: list, envelope: dict) -> list[list]:
    payload = dict(envelope)
    payload["entries"] = chunk
    if len(chunk) <= 1 or _payload_size(payload) <= BODY_BYTES_MAX:
        return [chunk]
    mid = len(chunk) // 2
    return _shrink_chunk(chunk[:mid], envelope) + _shrink_chunk(chunk[mid:], envelope)


def cmd_send(root: Path, force: bool, yes: bool, bypass_cadence: bool = False) -> int:
    config = _read_config_at(root)
    mode, cadence = _mode(config), _cadence(config)
    if mode == "off":
        print("aborted: feedback is off (docs/ai/config.md).", file=sys.stderr)
        return 2
    if mode == "manual" and not force:
        print("nothing sent: feedback is set to 'manual' - send only via "
              "/act-feedback (--send --force --yes).")
        return 0
    state = _read_state(root)
    if not bypass_cadence:
        hours_min = CADENCE_HOURS.get(cadence)
        if hours_min is None and not force:
            print("nothing sent: cadence is 'manual' or 'adaptive' - send only via "
                  "/act-feedback (--send --force --yes).")
            return 0
        hours_since = _hours_since(state.get("last_sent"))
        if hours_min is not None and hours_since < hours_min and not force:
            print(f"nothing sent: last send {hours_since:.1f}h ago, cadence '{cadence}' allows "
                  f"earliest after {hours_min}h. The outbox is kept and goes out next time.")
            return 0
    payload = _build_payload(root, config)
    # _build_payload may have created and saved the project id (_ensure_project_id); read the state
    # again so the writes below keep it instead of putting back the copy read before.
    state = _read_state(root)
    endpoint = _endpoint()
    template_repo = _template_repo(_read_lock_at(root))
    problems = _check_payload(payload, endpoint, template_repo=template_repo)
    if problems:
        print("rejected - not sent:", file=sys.stderr)
        for reason in problems:
            print(f"  - {reason}", file=sys.stderr)
        return 1
    if mode == "confirm" and not yes:
        _show(payload, endpoint)
        print("")
        print("mode 'confirm': nothing sent. Repeat the same call with --yes to send.")
        return 0

    entries = payload.pop("entries")
    envelope = payload  # everything but "entries" - the shared part of every chunk
    entry_chunks = _chunk_entries(entries, envelope)
    protocol_paths: list[Path] = []
    for index, chunk in enumerate(entry_chunks):
        chunk_payload = dict(envelope)
        chunk_payload["entries"] = chunk
        if index > 0:
            # Scope-gated fields (metrics/switches/rule_changes/rule_sets/tools/usage) and repo_url go
            # with the first send only - repeating them per chunk would look like several
            # different sends' worth of numbers to whoever reads the protocol.
            for key in ("metrics", "switches", "rule_changes", "rule_sets", "tools", "usage", "repo_url"):
                chunk_payload.pop(key, None)
        code, error = _post(endpoint, chunk_payload)
        if error:
            sent_so_far = f" ({len(protocol_paths)} of {len(entry_chunks)} chunk(s) already sent)" if protocol_paths else ""
            print(f"aborted: {error}{sent_so_far} The remaining outbox is kept.", file=sys.stderr)
            return 2
        protocol_paths.append(_write_protocol(root, chunk_payload, endpoint))
        if index == 0 and "usage" in chunk_payload:
            # The chunk carrying the counts went out: they become the baseline right now, so a later
            # chunk failing does not make the next send report them a second time.
            state["usage_baseline"] = _usage_counts(root)
            state["usage_baseline_at"] = time.strftime("%Y-%m-%d")
            _write_state(root, state)

    state["last_sent"] = time.strftime("%Y-%m-%d %H:%M")
    state["reminders_without_reaction"] = 0
    state["postponements"] = 0
    state["consecutive_sends"] = int(state.get("consecutive_sends") or 0) + 1
    state.pop("last_reminder", None)
    _write_state(root, state)
    _clear_outbox(root)
    _write_journal_entry(
        root, f"Feedback sent: batch ({len(entries)} entries, schema {SCHEMA_BATCH})",
        f"Feedback gesendet: Sammelversand ({len(entries)} Einträge, Schema {SCHEMA_BATCH})",
    )
    protocol_list = ", ".join(p.relative_to(root).as_posix() for p in protocol_paths)
    print(f"feedback sent ({len(entry_chunks)} send(s), {len(entries)} entries). "
          f"Protocol: {protocol_list}.")
    return 0


def cmd_direct(root: Path, text: Optional[str], yes: bool, contact: Optional[str] = None) -> int:
    """Sends a hand-written message at once. See the header comment for why this is deliberately
    not gated by consent or cadence."""
    del yes  # accepted for CLI symmetry with --send; a hand-written message never needs 'confirm'
    text = (text or "").strip()
    if not text:
        print("aborted: no text given.", file=sys.stderr)
        return 2
    if len(text) > DIRECT_MAX:
        print(f"aborted: text longer than {DIRECT_MAX} characters - please shorten it.", file=sys.stderr)
        return 2

    if not (root / ".act-lock.json").is_file():
        # No .act-lock.json means this is the template checkout itself, not a derived project (see
        # actlib.read_lock(), which would otherwise happily hand back an empty-but-valid-looking
        # skeleton and let a message go out with no template_base at all). The template does not
        # report feedback about itself.
        print("aborted: no .act-lock.json here - this looks like the template checkout itself, "
              "not a derived project. --direct only sends from a derived project.", file=sys.stderr)
        return 2

    lock = _read_lock_at(root)
    endpoint = _endpoint()
    template_repo = _template_repo(lock)
    config = _read_config_at(root)
    mode = _mode(config)
    payload: dict = {"schema": SCHEMA_DIRECT, "origin": ORIGIN, "kind": "direct",
                      "date": time.strftime("%Y-%m-%d"), "text": text}
    template_commit = (lock.get("template") or {}).get("commit")
    if template_commit:
        payload["template_base"] = template_commit
    # The project id goes with every direct message, whatever `feedback` says.
    state = _ensure_project_id(root, config, _read_state(root))
    if state.get("project_id"):
        payload["project_id"] = state["project_id"]
    if contact is not None:
        # Only on the human's explicit wish; never stored in state.json, never added by itself.
        payload["contact"] = contact.strip()

    problems = _check_payload(payload, endpoint, template_repo=template_repo)
    if problems:
        print("not sent - the payload was rejected:", file=sys.stderr)
        for reason in problems:
            print(f"  - {reason}", file=sys.stderr)
        print("  Please rephrase the text without that part.", file=sys.stderr)
        return 1

    _show(payload, endpoint)
    print("")
    if mode == "off":
        print("feedback is set to 'off' - only this text, the template commit hash and the project id "
              "leave the project" + (", plus the reply address you gave." if contact else "."))

    code, error = _post(endpoint, payload)
    if error:
        print(f"aborted: {error}", file=sys.stderr)
        return 2

    protocol_path = _write_protocol(root, payload, endpoint)
    _write_journal_entry(
        root, f"Feedback sent: direct message (schema {SCHEMA_DIRECT})",
        f"Feedback gesendet: Direktnachricht (Schema {SCHEMA_DIRECT})",
    )
    print(f"message sent (HTTP {code}). Protocol: {protocol_path.relative_to(root).as_posix()}.")
    return 0


def _work_days_since(root: Path, last_sent: Optional[str]) -> int:
    """Days with at least one commit since `last_sent` ('YYYY-MM-DD HH:MM'). Without a timestamp:
    since ever."""
    since = (last_sent or "")[:10]
    args = ["log", "--format=%ad", "--date=short"]
    if since:
        args.append(f"--since={since}")
    # Pathspec "-- .": same reasoning as _metrics() - root can be a sub-project inside a larger
    # git repository, and without it this would count every commit of the whole repo.
    args += ["--", "."]
    dates = _git(root, *args).split()
    return len(set(dates))


def _adaptive_threshold(state: dict) -> tuple[int, str]:
    """The learned threshold (work days) for cadence "adaptive" — see the header comment for the
    derivation (and what was deliberately dropped versus the template's earlier version). Returns
    (threshold, why) — why is meant for --status-style output, so the math never stays a black box."""
    ignored = int(state.get("reminders_without_reaction") or 0)
    postponed = int(state.get("postponements") or 0)
    in_a_row = int(state.get("consecutive_sends") or 0)

    threshold = ADAPTIVE_BASE_DAYS * (ADAPTIVE_NEGATIVE_FACTOR ** (ignored + postponed))
    threshold = min(threshold, float(ADAPTIVE_MAX_DAYS))
    threshold = threshold * (ADAPTIVE_POSITIVE_FACTOR ** in_a_row)
    threshold = max(threshold, float(ADAPTIVE_MIN_DAYS))
    threshold = min(max(round(threshold), ADAPTIVE_MIN_DAYS), ADAPTIVE_MAX_DAYS)

    parts = [f"base {ADAPTIVE_BASE_DAYS}"]
    if ignored:
        parts.append(f"{ignored}x ignored")
    if postponed:
        parts.append(f"{postponed}x postponed")
    if in_a_row:
        parts.append(f"{in_a_row}x sent in a row")
    return threshold, ", ".join(parts)


def _advance_adaptive_marker(state: dict, work_days: int, threshold: int) -> bool:
    """Only called when a reminder is actually due under cadence "adaptive". Counts
    "reminders_without_reaction" up if a reminder already fired on an EARLIER calendar day without
    a send in between since (the very first reminder of a cycle does not count as "ignored" yet).
    At most one step per calendar day. Mutates `state` in place, returns True if it changed."""
    today = time.strftime("%Y-%m-%d")
    last_reminder = state.get("last_reminder") or ""
    if last_reminder == today:
        return False
    if last_reminder:
        state["reminders_without_reaction"] = int(state.get("reminders_without_reaction") or 0) + 1
        state["consecutive_sends"] = 0
    state["last_reminder"] = today
    return True


def cmd_postpone(root: Path, days: Optional[int]) -> int:
    """Pauses the due reminder for `days` days and counts it as a postponement for the adaptive-
    cadence learning — the same single action as the earlier feedback.py's --postpone/
    --verschieben. Sends nothing, changes no config."""
    if days is None or days <= 0:
        print("error: --postpone needs a positive number of days.", file=sys.stderr)
        return 2
    state = _read_state(root)
    until = time.strftime("%Y-%m-%d", time.localtime(time.time() + days * 86400))
    state["reminder_paused_until"] = until
    state["postponements"] = int(state.get("postponements") or 0) + 1
    state["consecutive_sends"] = 0
    state.pop("last_reminder", None)
    _write_state(root, state)
    print(f"reminder paused until {until} ({days} day(s)).")
    return 0


def cmd_clear(root: Path) -> int:
    """Discards every waiting entry, without sending. What is already in a protocol under
    .act-local/feedback/sent/ stays there — that is the proof and is never cleared here."""
    count = len(_read_entries(root))
    _clear_outbox(root)
    print(f"outbox cleared ({count} entr{'y' if count == 1 else 'ies'} discarded). "
          f"What was already sent stays in its protocol.")
    return 0


HARVEST_FILE_REL = ".act-local/adopt/harvest.md"


def cmd_discard_harvest(root: Path) -> int:
    """With docs/ai/config.md's `feedback: off`, act-adopt's harvest.md (step 6's
    local list of candidates for the template, written while reading the old project) is deleted
    rather than turned into outbox entries — nothing of it survives. A no-op, not an error, when
    there is nothing to discard (an adoption that found no candidates, or a rerun)."""
    path = root / HARVEST_FILE_REL
    if not path.is_file():
        print(f"nothing to discard: {HARVEST_FILE_REL} does not exist.")
        return 0
    try:
        path.unlink()
    except OSError as exc:
        print(f"error: could not remove {HARVEST_FILE_REL}: {exc}", file=sys.stderr)
        return 2
    print(f"discarded: {HARVEST_FILE_REL} (feedback is off — nothing of it is kept or sent).")
    return 0


def due_status(root: Path) -> "tuple[bool, str]":
    """(due, detail) -- the same due/no-due decision and detail text cmd_due() prints below,
    factored out (review 2026-09-23) so a caller that only wants the boolean (checks/tips.py's
    is_feedback_due(), folded into the SessionStart status line) does not have to capture and
    parse cmd_due()'s stdout. Never raises; side effect unchanged from before the split: an
    adaptive cadence's learning marker still advances exactly when due comes back True."""
    config = _read_config_at(root)
    mode, cadence = _mode(config), _cadence(config)
    state = _read_state(root)
    last_sent = state.get("last_sent") or ""
    today = time.strftime("%Y-%m-%d")
    paused_until = str(state.get("reminder_paused_until") or "").strip()
    paused = paused_until if paused_until and paused_until > today else ""
    hours_since = _hours_since(last_sent)
    waiting = len(_read_entries(root))

    due, reason = False, ""
    work_days, threshold = 0, ADAPTIVE_BASE_DAYS
    if mode in ("off", "manual"):
        reason = f"mode '{mode}' never reminds"
    elif paused:
        reason = f"paused until {paused}"
    elif cadence == "adaptive":
        work_days = _work_days_since(root, last_sent)
        threshold, why = _adaptive_threshold(state)
        due = work_days >= threshold and hours_since >= MIN_REMINDER_INTERVAL_H
        reason = f"{work_days} work day(s) since last send, threshold {threshold} ({why})"
    else:
        hours_min = CADENCE_HOURS.get(cadence)
        if hours_min is None:
            reason = f"cadence '{cadence}' has no fixed interval"
        else:
            due = hours_since >= max(hours_min, MIN_REMINDER_INTERVAL_H)
            reason = f"cadence '{cadence}', {hours_since / 24:.1f} day(s) since last send"

    if due and cadence == "adaptive":
        try:
            if _advance_adaptive_marker(state, work_days, threshold):
                _write_state(root, state)
        except OSError:
            pass  # a failed marker write must never turn a due reminder into a silent one

    detail = f"{reason}; {waiting} entr{'y' if waiting == 1 else 'ies'} waiting"
    return due, detail


def cmd_due(root: Path) -> int:
    """Reports whether a reminder is due, for a dispatcher to call at session start. Never raises
    and always exits 0 — a broken due-check must not stop a session, only stay silent about it."""
    due, detail = due_status(root)
    print(f"due: {'yes' if due else 'no'} ({detail})")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="feedback.py",
        description="Voluntary feedback to the template author - never without consent, never unseen.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--status", action="store_true", help="show the current state")
    group.add_argument("--enable", action="store_true", help="set consent")
    group.add_argument("--disable", action="store_true", help="revoke consent")
    group.add_argument("--add", action="store_true", help="store a finding in the outbox")
    group.add_argument("--plan", action="store_true", help="show the payload, send nothing (default)")
    group.add_argument("--send", action="store_true",
                        help="send if consent, the privacy check and the cadence gate all allow it")
    group.add_argument("--direct", metavar="TEXT", default=None,
                        help="send a hand-written message at once - works even with feedback off")
    group.add_argument("--due", action="store_true",
                        help="report whether a reminder is due under the current cadence")
    group.add_argument("--postpone", metavar="DAYS", type=int, default=None,
                        help="pause the due reminder for this many days and count it as a postponement")
    group.add_argument("--clear", action="store_true", help="discard every waiting entry, send nothing")
    group.add_argument("--discard-harvest", action="store_true",
                        help="remove --target's .act-local/adopt/harvest.md, add nothing to the outbox")
    parser.add_argument("--contact", metavar="EMAIL", default=None,
                         help="with --direct: a reply address for this one message (never stored)")
    parser.add_argument("--target", metavar="DIR", default=None,
                         help="act on the project at DIR instead of the current checkout (act-adopt)")
    parser.add_argument("--kind", choices=KINDS, default=None, help="with --add")
    parser.add_argument("--title", default=None, help="with --add: one line")
    parser.add_argument("--text", default=None, help="with --add: two to six sentences")
    parser.add_argument("--url", default=None, help="with --add --kind link: the public address")
    parser.add_argument("--repo-url", default=None, help="with --enable: public repo URL (optional)")
    parser.add_argument("--mode", choices=MODE_VALUES, default=None,
                         help="with --enable: off, confirm, automatic (default), manual")
    parser.add_argument("--force", action="store_true",
                         help="with --send: lift the cadence gate (not the consent gate)")
    parser.add_argument("--yes", action="store_true",
                         help="with --send and mode 'confirm': actually send after showing the payload")
    return parser


def main(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.target:
        root = Path(args.target).expanduser().resolve()
        if not root.is_dir():
            print(f"feedback.py: target is not a directory: {root}", file=sys.stderr)
            return 2
    else:
        root = actlib.repo_root()

    if args.contact is not None and args.direct is None:
        print("feedback.py: --contact only works together with --direct.", file=sys.stderr)
        return 2
    if args.contact is not None and not args.contact.strip():
        print("feedback.py: --contact needs an e-mail address; leave the option out for no reply address.",
              file=sys.stderr)
        return 2
    if args.discard_harvest:
        return cmd_discard_harvest(root)
    if args.status:
        return cmd_status(root)
    if args.enable:
        return cmd_enable(root, args.repo_url, args.mode)
    if args.disable:
        return cmd_disable(root)
    if args.add:
        return cmd_add(root, args.kind, args.title, args.text, args.url, args.yes)
    if args.send:
        return cmd_send(root, args.force, args.yes)
    if args.direct is not None:
        return cmd_direct(root, args.direct, args.yes, args.contact)
    if args.due:
        return cmd_due(root)
    if args.postpone is not None:
        return cmd_postpone(root, args.postpone)
    if args.clear:
        return cmd_clear(root)
    return cmd_plan(root)


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - must never surface a traceback
        print(f"feedback: error: {exc}", file=sys.stderr)
        sys.exit(2)
