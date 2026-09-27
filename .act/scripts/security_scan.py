#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Security check Art B (concept docs/project/concepts/ai-dev-app/14-security-check.md,
#          `Q86a`-`Q86c` all decided "a"): a live library-vulnerability lookup against the lock
#          files an ecosystem actually has, run either as a manual command (`--deps`) or from
#          `checks/deps_scan.py` before a commit and `checks/session.py` once a day (both reuse
#          `run_scan`/`available_tools` from here rather than shelling out a second time). Art A
#          (dangerous patterns) is `checks/danger_scan.py`; Art C (Semgrep, `act-release`) is
#          `security_deep.py`, a separate script.
#
#          One tool for everything, chosen once per call to `run_scan` (never mixed within one
#          run): `osv-scanner` first -- one database (OSV/GHSA and friends) covering every
#          ecosystem this module detects a lock file for, so it is preferred whenever installed
#          even if an ecosystem-specific tool is *also* installed. Without it, one tool per
#          ecosystem instead, each independent (a missing/broken tool in one ecosystem never hides
#          a finding in another): `npm audit --json` (npm's own `package-lock.json`), `composer
#          audit --format=json` (`composer.lock`), `pip-audit --disable-pip --no-deps -r
#          <requirements.txt>` (a *pinned* requirements file only -- see "pip-audit mode" below).
#          `yarn.lock`/`pnpm-lock.yaml`/`go.mod`/`Cargo.lock` have no ecosystem-specific fallback
#          coded here at all; without `osv-scanner` they are named in `missing_tools` and simply
#          not scanned, same as `poetry.lock`/`Pipfile.lock` (pip-audit's own `--no-deps` mode only
#          takes a plain requirements file, not a lock format of its own).
#
#          osv-scanner CLI form (2026-09-27 review): osv-scanner not installed on this machine —
#          the two invocation shapes below are read off the tool's own documentation, not verified
#          against a real run, and are stated here as an assumption rather than a confirmed fact.
#          v1 takes `-L <lockfile>` directly after `--format json`; v2 moved every scan mode under
#          a `scan` subcommand (`osv-scanner scan source --lockfile=<path> ...`). `_run_osv_scanner`
#          tries the v1 shape first (the common case today) and falls back to the v2 shape only
#          when the first attempt's own stderr looks like a "no such flag"/usage complaint rather
#          than a real scan failure — see `_looks_like_cli_mismatch`.
#
#          pip-audit mode: `--disable-pip --no-deps -r <file>` reads the pinned versions straight
#          out of the file and looks each one up against its own vulnerability database -- it never
#          installs a package, builds one, or executes anything from the project (`--disable-pip`
#          drops pip-audit's own default "resolve missing pins by installing them" behaviour,
#          `--no-deps` keeps it from walking a package's own dependency tree either). A
#          requirements file with an unpinned line (`requests` with no `==`) is passed through
#          unchanged -- pip-audit itself decides what it can and cannot look up from that, this
#          module does not pre-filter it.
#
#          `available_tools()` is the one place that decides what is actually installed --
#          `checks/deps_scan.py`, `checks/session.py`'s daily note, and `.act/scripts/init.py`'s
#          setup-time offer (`security-check: deps` when a tool exists) all call this instead of
#          probing `shutil.which` themselves, so a fourth caller never drifts from what this module
#          already knows how to run.
#
#          Scan cache (`.act-local/security-scan-cache/`, section "Scan cache" below): the commit
#          check never runs a tool inside its own hook call; it asks checks/session.py's detached
#          "_security-scan-worker" to scan exactly the lock files the commit touches and reads the
#          answer back from `<state-hash>.json` here -- `state-hash` = `lock_set_digest()` over
#          those files' paths and contents, so a result only ever answers for the very content it
#          scanned (the worker digests before and after its run and writes nothing when the two
#          differ). `<state-hash>.running.json` marks a scan in flight, with a `stale_after`
#          derived from the tools' own timeouts (`scan_time_limit()`), never a fixed guess. Both
#          the check (`checks/deps_scan.py`) and the worker (`checks/session.py`) go through the
#          helpers here rather than spelling the file names out twice.
#
#          Accepted exceptions: `docs/ai/local/security-accepted.md`, one line per advisory id --
#          `- <advisory-id>: <reason>` (a Markdown list item, the same shape every other project
#          doc uses for a list; `#`-comments and blank lines ignored). `load_accepted()` never
#          raises on a missing or malformed file -- an empty result there just means nothing is
#          accepted yet, not an error.
#
# Known limits:
#   - severity is read as each tool already reports it (`database_specific.severity` for
#     osv-scanner, falling back to its own `groups[].max_severity` CVSS score when that is absent —
#     see `_osv_group_severity`/`_severity_from_cvss`: >=9 critical, >=7 high, >=4 moderate, else
#     low — and `severity` for npm/composer) and only normalized to
#     critical/high/moderate/low/unknown -- a raw CVSS *vector string* (osv-scanner's own
#     `severity[].score` field, as opposed to the numeric `groups[].max_severity`) is not parsed
#     into a numeric score here;
#   - pip-audit's default JSON output carries no severity field at all -- every pip-audit finding
#     is "unknown" severity, never "high"/"critical", until pip-audit itself starts reporting one.
#     This means a pip-audit finding can never hold a commit on its own (only `deps_scan.py`'s own
#     high/critical check does that, and "unknown" never qualifies) -- it only ever notes;
#   - `composer audit` names no fixed version in its own JSON output -- `fixed_version` is always
#     None for a composer finding;
#   - `detect_lock_files` walks the whole project tree (skipping `.git`, `.act`, `node_modules`,
#     `vendor`, `.venv`/`venv`, `__pycache__`, `dist`, `build`, and any dot-directory) -- a lock
#     file placed somewhere else this list does not skip is still found, one placed *inside* one of
#     these directories on purpose (an unusual layout) is not;
#   - every tool call is a real subprocess with argument lists, never a shell string -- a tool that
#     needs network access (osv-scanner's own database lookup, if not run with a local database)
#     reaches it itself; this module never opens a connection of its own.

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from typing import Iterable, Optional

import actlib

__all__ = [
    "LOCK_FILE_NAMES", "PIP_AUDIT_LOCK_NAMES", "TOOL_NAMES", "INSTALL_HINTS",
    "SEVERITY_LEVELS", "Finding", "ScanResult", "CACHE_DIRNAME",
    "normalize_severity", "detect_lock_files", "lock_files_from_paths", "available_tools",
    "lock_file_digest", "lock_set_digest", "scan_time_limit",
    "cache_dir", "result_cache_path", "running_marker_path", "is_state_hash",
    "write_running_marker", "read_running_marker", "clear_running_marker",
    "write_result_cache", "read_result_cache", "result_from_dict",
    "accepted_list_path", "load_accepted", "is_accepted",
    "run_scan", "main",
]

# ---------------------------------------------------------------------------
# Lock-file detection and tool table
# ---------------------------------------------------------------------------

LOCK_FILE_NAMES: dict[str, tuple[str, ...]] = {
    "npm": ("package-lock.json",),
    "yarn": ("yarn.lock",),
    "pnpm": ("pnpm-lock.yaml",),
    "composer": ("composer.lock",),
    "python": (
        "requirements.txt", "requirements-lock.txt", "requirements.lock",
        "poetry.lock", "Pipfile.lock",
    ),
    # osv-scanner reads the module graph from `go.mod`, not the checksum-only `go.sum` (2026-09-27
    # review, item 11) -- unverified: osv-scanner is not installed on this machine, this is read
    # off its own documented lockfile parsers, not confirmed by a real run.
    "go": ("go.mod",),
    "cargo": ("Cargo.lock",),
}
# The only python lock names pip-audit's own --disable-pip --no-deps -r mode can read at all
# (a plain, pinned requirements file) -- poetry.lock/Pipfile.lock are detected (for osv-scanner)
# but never handed to the pip-audit fallback, see the module docstring.
PIP_AUDIT_LOCK_NAMES = frozenset({"requirements.txt", "requirements-lock.txt", "requirements.lock"})

TOOL_NAMES = ("osv-scanner", "npm", "composer", "pip-audit")
INSTALL_HINTS: dict[str, str] = {
    "osv-scanner": "install osv-scanner (https://google.github.io/osv-scanner/installation/)",
    "npm": "install Node.js/npm (https://nodejs.org/)",
    "composer": "install Composer (https://getcomposer.org/download/)",
    "pip-audit": "pip install pip-audit",
}

_SKIP_DIR_NAMES = frozenset({
    ".git", ".act", "node_modules", "vendor", ".venv", "venv", "__pycache__", "dist", "build",
})


def detect_lock_files(root: Path) -> dict[str, list[Path]]:
    """Every lock file `root` actually holds, grouped by ecosystem -- absolute paths. A directory
    name in `_SKIP_DIR_NAMES`, or any dot-directory, is never walked into (see the module
    docstring's "Known limits")."""
    name_to_ecosystems: dict[str, list[str]] = {}
    for ecosystem, names in LOCK_FILE_NAMES.items():
        for name in names:
            name_to_ecosystems.setdefault(name, []).append(ecosystem)

    found: dict[str, list[Path]] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIR_NAMES and not d.startswith(".")]
        for filename in filenames:
            for ecosystem in name_to_ecosystems.get(filename, ()):
                found.setdefault(ecosystem, []).append(Path(dirpath) / filename)
    return found


def lock_files_from_paths(paths: "Iterable[Path]") -> dict[str, list[Path]]:
    """`paths` (explicit lock files, e.g. the ones one commit touches) grouped by ecosystem the same
    way `detect_lock_files` groups a walk -- by file name alone, no directory skip list: a file the
    caller names is scanned wherever it lies (`build/requirements.txt` included), which is what
    lets checks/deps_scan.py judge exactly the touched files instead of the whole project. A name
    no ecosystem claims is dropped; duplicates are folded."""
    name_to_ecosystems: dict[str, list[str]] = {}
    for ecosystem, names in LOCK_FILE_NAMES.items():
        for name in names:
            name_to_ecosystems.setdefault(name, []).append(ecosystem)
    grouped: dict[str, list[Path]] = {}
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        for ecosystem in name_to_ecosystems.get(path.name, ()):
            grouped.setdefault(ecosystem, []).append(path)
    return grouped


_DIGEST_MAX_BYTES = 5 * 1024 * 1024  # a lock file past this size only contributes its size to the
# digest, not its full content -- cheap enough for the huge, rare outlier, still distinguishes one
# lock-file state from another for the common case (shared by checks/deps_scan.py's own cache key
# and checks/session.py's daily background scan, 2026-09-27 review, item 2).


def lock_file_digest(path: Path) -> Optional[str]:
    """sha256 of `path`'s current on-disk content (or, past `_DIGEST_MAX_BYTES`, its size) -- None
    if the file cannot be read at all (never a reason to raise). The one place both
    checks/deps_scan.py (its per-commit cache key) and checks/session.py (its daily background
    scan's own "what did I actually scan" record) compute this, so the two can compare notes
    without duplicating the read logic."""
    try:
        size = path.stat().st_size
    except OSError:
        return None
    hasher = hashlib.sha256()
    try:
        if size > _DIGEST_MAX_BYTES:
            hasher.update(f"size:{size}".encode("ascii"))
        else:
            hasher.update(path.read_bytes())
    except OSError:
        return None
    return hasher.hexdigest()


def lock_set_digest(paths: "Iterable[Path]") -> Optional[str]:
    """One sha256 over every path in `paths` (its own string, so two same-named files in two
    directories never collide) plus its content digest (`lock_file_digest`), order-independent --
    the "state hash" both checks/deps_scan.py (cache key for one commit's touched lock files) and
    checks/session.py's worker (digest before *and* after its scan, result recorded only when both
    agree) compute, in this one place. None as soon as one file cannot be read: a hash that does not
    describe the real content is never handed out."""
    hasher = hashlib.sha256()
    for path in sorted({str(path) for path in paths}):
        digest = lock_file_digest(Path(path))
        if digest is None:
            return None
        hasher.update(path.encode("utf-8", "replace"))
        hasher.update(b"\0")
        hasher.update(digest.encode("ascii"))
        hasher.update(b"\n")
    return hasher.hexdigest()


# Per-call subprocess timeouts of the tool runners below -- `scan_time_limit` derives the "is this
# background scan dead or just slow" limit from these, so a longer-running multi-tool scan is never
# mistaken for a dead one by a fixed number chosen independently of them.
_OSV_TIMEOUT = 90.0   # one osv-scanner call over every lock file; tried at most twice (v1, v2 shape)
_TOOL_TIMEOUT = 60.0  # npm audit / composer audit / pip-audit, one call per lock file


def scan_time_limit(lock_files: dict[str, list[Path]]) -> float:
    """Upper bound (seconds) on the tool time one `run_scan(root, lock_files)` can spend before
    every subprocess in it has timed out on its own: the osv-scanner path (two invocation shapes)
    or the per-ecosystem path (one call per lock file), whichever is longer."""
    count = sum(len(paths) for paths in lock_files.values())
    return max(2 * _OSV_TIMEOUT, _TOOL_TIMEOUT * max(count, 1))


# ---------------------------------------------------------------------------
# Scan cache -- .act-local/security-scan-cache/<state-hash>.json (a finished scan of exactly the
# lock files whose `lock_set_digest` is <state-hash>) and <state-hash>.running.json (that scan
# still in flight). Written by checks/session.py's worker, read by checks/deps_scan.py; every
# helper here is best-effort and never raises on I/O (a failed write only costs a repeated scan).
# ---------------------------------------------------------------------------

CACHE_DIRNAME = "security-scan-cache"
_STATE_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def is_state_hash(value: object) -> bool:
    """True for a hex sha256 as `lock_set_digest` returns it -- the only shape ever used as a cache
    file name (a worker's own argv is checked against this before it touches the file system)."""
    return isinstance(value, str) and bool(_STATE_HASH_RE.match(value))


def cache_dir(root: Path) -> Path:
    return root / ".act-local" / CACHE_DIRNAME


def result_cache_path(root: Path, state_hash: str) -> Path:
    return cache_dir(root) / f"{state_hash}.json"


def running_marker_path(root: Path, state_hash: str) -> Path:
    return cache_dir(root) / f"{state_hash}.running.json"


def _write_json(path: Path, data: dict) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        return False
    return True


def _read_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_running_marker(root: Path, state_hash: str, stale_after: float) -> bool:
    """Marks a scan of <state_hash> as in flight; `stale_after` (epoch seconds) is when a reader
    may treat it as dead -- the writer derives it from `scan_time_limit`, the reader only compares.
    False when the marker could not be written (the caller then does not spawn: a worker nobody
    can see would only be waited for by no one)."""
    return _write_json(
        running_marker_path(root, state_hash), {"started": time.time(), "stale_after": stale_after},
    )


def read_running_marker(root: Path, state_hash: str) -> Optional[dict]:
    """{"started": float, "stale_after": float} for a scan of <state_hash> still marked as running,
    None when there is no (readable, well-formed) marker."""
    data = _read_json(running_marker_path(root, state_hash))
    if data is None:
        return None
    started = data.get("started")
    stale_after = data.get("stale_after")
    if not isinstance(started, (int, float)) or not isinstance(stale_after, (int, float)):
        return None
    return {"started": float(started), "stale_after": float(stale_after)}


def clear_running_marker(root: Path, state_hash: str) -> None:
    try:
        running_marker_path(root, state_hash).unlink()
    except OSError:
        pass


def write_result_cache(root: Path, state_hash: str, result: "ScanResult", files: "list[str]") -> bool:
    """Records `result` as the answer for the lock-file state <state_hash>: `day` (a cached answer
    never outlives the day -- the tools' databases move on), `written` (epoch seconds, so a reader
    can apply a short retry interval to a failed run), `cacheable` (`result.is_clean()`: no tool
    error, no missing tool -- a reader treats anything else as a miss once the retry interval is
    over), `files` (what was scanned, for a human reading the file)."""
    return _write_json(result_cache_path(root, state_hash), {
        "day": date.today().isoformat(),
        "written": time.time(),
        "cacheable": result.is_clean(),
        "files": list(files),
        "result": dataclasses.asdict(result),
    })


def read_result_cache(root: Path, state_hash: str) -> Optional[dict]:
    """The raw record `write_result_cache` stored for <state_hash>, shape-checked (`day` str,
    `written` number, `cacheable` bool, `result` dict), or None -- the caller decides whether it is
    still current (`result_from_dict` turns its `result` back into a `ScanResult`)."""
    data = _read_json(result_cache_path(root, state_hash))
    if data is None:
        return None
    if not isinstance(data.get("day"), str) or not isinstance(data.get("written"), (int, float)):
        return None
    if not isinstance(data.get("cacheable"), bool) or not isinstance(data.get("result"), dict):
        return None
    return data


def result_from_dict(data: dict) -> "ScanResult":
    """`ScanResult` back from `dataclasses.asdict(result)` -- a finding entry whose keys no longer
    match `Finding` raises TypeError, which the reading check treats as a cache miss."""
    findings = [Finding(**item) for item in data.get("findings", []) if isinstance(item, dict)]
    return ScanResult(
        findings=findings,
        tools_used=[str(item) for item in data.get("tools_used", [])],
        missing_tools=[str(item) for item in data.get("missing_tools", [])],
        errors=[str(item) for item in data.get("errors", [])],
        scanned_files=[str(item) for item in data.get("scanned_files", [])],
    )


def available_tools() -> dict[str, str]:
    """Installed path for every tool name in `TOOL_NAMES` actually found on `PATH` (`shutil.which`,
    which also finds a `.cmd`/`.exe`/`.bat` wrapper on Windows via `PATHEXT`) -- the one place
    every caller (this module's own `run_scan`, `checks/deps_scan.py`, `checks/session.py`,
    `init.py`'s setup-time offer) reads "what is installed" from, so a test's fake tool placed on
    `PATH` (no separate environment variable needed) is found the same way a real install would
    be."""
    return {name: path for name in TOOL_NAMES if (path := shutil.which(name))}


# ---------------------------------------------------------------------------
# Findings and severity
# ---------------------------------------------------------------------------

SEVERITY_LEVELS = ("critical", "high", "moderate", "low", "unknown")
_SEVERITY_ALIASES = {
    "critical": "critical",
    "high": "high",
    "moderate": "moderate", "medium": "moderate",
    "low": "low",
    "info": "low", "informational": "low", "informational only": "low",
}


def normalize_severity(raw: object) -> str:
    """`raw` (whatever string a tool's own JSON calls its severity) folded onto
    `SEVERITY_LEVELS` -- "unknown" for anything empty or not recognized, never an exception; see
    the module docstring's "Known limits" for pip-audit (no severity field at all) and a raw CVSS
    vector (not parsed)."""
    if not raw:
        return "unknown"
    return _SEVERITY_ALIASES.get(str(raw).strip().lower(), "unknown")


@dataclasses.dataclass(frozen=True)
class Finding:
    ecosystem: str
    package: str
    version: str
    advisory_id: str
    severity: str
    fixed_version: Optional[str]
    lock_file: str
    summary: str = ""


@dataclasses.dataclass
class ScanResult:
    findings: "list[Finding]" = dataclasses.field(default_factory=list)
    tools_used: "list[str]" = dataclasses.field(default_factory=list)
    missing_tools: "list[str]" = dataclasses.field(default_factory=list)
    errors: "list[str]" = dataclasses.field(default_factory=list)
    scanned_files: "list[str]" = dataclasses.field(default_factory=list)

    def is_clean(self) -> bool:
        """True when every lock file was actually looked at by a working tool -- no tool error, no
        missing tool. Only such a result may answer for its content for the rest of the day; a
        result that never really looked is reused for a short retry interval at most (see
        `write_result_cache`/checks/deps_scan.py), so a tool installed or fixed later gets a fresh
        scan on the next commit."""
        return not self.errors and not self.missing_tools


# ---------------------------------------------------------------------------
# Accepted exceptions -- docs/ai/local/security-accepted.md
# ---------------------------------------------------------------------------

_ACCEPTED_LINE_RE = re.compile(r"^-\s*([^\s:]+)\s*:\s*(.+)$")


def accepted_list_path(root: Path) -> Path:
    return root / "docs" / "ai" / "local" / "security-accepted.md"


def load_accepted(root: Path) -> dict[str, str]:
    """advisory id -> reason, from `accepted_list_path(root)` -- {} for a missing, unreadable, or
    entirely non-matching file, never an exception (same fail-open stance every other best-effort
    read in this template takes for a project file it did not itself write yet)."""
    path = accepted_list_path(root)
    accepted: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return accepted
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ACCEPTED_LINE_RE.match(stripped)
        if match:
            advisory_id = match.group(1).strip()
            if not advisory_id or advisory_id == "?":
                continue  # never a real advisory id (2026-09-27 review, item 7) -- accepting it
                # would silently accept every unresolved/parent-package finding at once
            accepted[advisory_id] = match.group(2).strip()
    return accepted


def is_accepted(advisory_id: str, accepted: dict[str, str]) -> bool:
    return advisory_id in accepted


# ---------------------------------------------------------------------------
# Subprocess helper -- argument lists only, never a shell string (R-safe-no-secret-cli's own
# reasoning applies here too: a shell string is one more place a path or argument could be
# misparsed).
# ---------------------------------------------------------------------------

def _run(
    args: "list[str]", cwd: Path, timeout: float = 60.0,
) -> "tuple[Optional[str], Optional[int], Optional[str], Optional[str]]":
    """(stdout, returncode, stderr, start_error). `start_error` is set only when the tool itself
    could not be run at all (timeout, executable missing/not executable) -- npm audit/composer
    audit/pip-audit all exit non-zero exactly when they *found* something, which is the normal,
    expected case here, not a failure by itself; the caller decides what a given `returncode`
    means for its own tool (2026-09-27 review, item 5: blank stdout plus an unexpected exit code
    used to come back as a silent "clean" result -- `returncode`/`stderr` are now handed back so
    each runner can tell that apart from a real "nothing found")."""
    try:
        result = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, None, None, f"timed out after {timeout:.0f}s"
    except OSError as exc:
        return None, None, None, f"failed to start ({args[0]}): {exc}"
    return result.stdout, result.returncode, result.stderr, None


def _relative(path_value: object, root: Path) -> str:
    if not path_value:
        return "?"
    try:
        return str(Path(str(path_value)).resolve().relative_to(root.resolve()))
    except (OSError, ValueError):
        return str(path_value)


# ---------------------------------------------------------------------------
# Tool runners -- each returns (findings, error); `error` never stops the other ecosystems' own
# runs in run_scan(), it is only carried into ScanResult.errors for the caller to report. An error
# text names what happened, never the tool -- run_scan() prefixes the tool (and lock file) exactly
# once when it records it (2026-09-27 review 2: the prefix used to appear twice).
# ---------------------------------------------------------------------------

def _severity_from_cvss(score: object) -> Optional[str]:
    """critical/high/moderate/low from a numeric CVSS score (osv-scanner's own `groups[].
    max_severity`, a plain number as a string) -- >=9 critical, >=7 high, >=4 moderate, else low
    (2026-09-27 review, item 8). None for anything that does not parse as a number at all, never
    an exception."""
    try:
        value = float(score)
    except (TypeError, ValueError):
        return None
    if value >= 9:
        return "critical"
    if value >= 7:
        return "high"
    if value >= 4:
        return "moderate"
    return "low"


def _osv_group_severity(vuln_id: str, groups: object) -> Optional[str]:
    """The CVSS-derived severity of `vuln_id` from `package_entry["groups"]` (each group names the
    aliased vulnerability ids it covers plus their shared `max_severity`) -- None if `groups` does
    not name this id at all, or names it with no usable score."""
    if not isinstance(groups, list):
        return None
    for group in groups:
        if not isinstance(group, dict):
            continue
        ids = group.get("ids")
        if isinstance(ids, list) and vuln_id in ids:
            severity = _severity_from_cvss(group.get("max_severity"))
            if severity:
                return severity
    return None


def _osv_severity(vuln: dict, groups: object) -> str:
    database_specific = vuln.get("database_specific")
    if isinstance(database_specific, dict) and database_specific.get("severity"):
        return normalize_severity(database_specific["severity"])
    # a raw CVSS *vector* string in vuln["severity"] is not parsed (see the module docstring) --
    # but package_entry["groups"][].max_severity is a plain numeric CVSS score, read here instead
    # (2026-09-27 review, item 8)
    group_severity = _osv_group_severity(str(vuln.get("id", "?")), groups)
    return group_severity or "unknown"


def _osv_fixed_version(vuln: dict) -> Optional[str]:
    for affected in vuln.get("affected", []) if isinstance(vuln.get("affected"), list) else ():
        if not isinstance(affected, dict):
            continue
        for value_range in affected.get("ranges", []) if isinstance(affected.get("ranges"), list) else ():
            if not isinstance(value_range, dict):
                continue
            for event in value_range.get("events", []) if isinstance(value_range.get("events"), list) else ():
                if isinstance(event, dict) and event.get("fixed"):
                    return str(event["fixed"])
    return None


def _looks_like_cli_mismatch(stderr: Optional[str]) -> bool:
    """True when `stderr` reads like "this flag/command does not exist" rather than a real scan
    failure -- the signal `_run_osv_scanner` uses to retry with the v2 (`scan source`) invocation
    shape after the v1 one fails (2026-09-27 review, item 11; see the module docstring for why this
    is an assumption, not a confirmed behaviour)."""
    if not stderr:
        return False
    lowered = stderr.lower()
    return any(
        phrase in lowered
        for phrase in ("unknown command", "unknown flag", "unrecognized", "flag needs an argument")
    )


def _unexpected_empty_output(returncode: Optional[int]) -> bool:
    """True when a tool printed nothing at all *and* exited with a code that is not the plain
    "ran cleanly" 0 -- the signal that this is a real failure (crashed, misconfigured, no network),
    not the ordinary "found nothing" case (2026-09-27 review, item 5): a real vulnerability report
    always carries JSON, so blank stdout together with a non-zero exit is never a clean run."""
    return returncode is not None and returncode != 0


def _run_osv_scanner(
    tool_path: str, root: Path, lock_paths: "list[Path]",
) -> "tuple[list[Finding], Optional[str]]":
    args_v1 = [tool_path, "--format", "json"]
    for path in lock_paths:
        args_v1 += ["-L", str(path)]
    stdout, returncode, stderr, start_error = _run(args_v1, root, timeout=_OSV_TIMEOUT)
    if start_error:
        return [], start_error
    if (not stdout or not stdout.strip()) and _looks_like_cli_mismatch(stderr):
        # v2 moved every scan mode under `scan` -- retry once with that shape (item 11, unverified)
        args_v2 = [tool_path, "scan", "source", "--format", "json"]
        args_v2 += [f"--lockfile={path}" for path in lock_paths]
        stdout, returncode, stderr, start_error = _run(args_v2, root, timeout=_OSV_TIMEOUT)
        if start_error:
            return [], start_error
    if not stdout or not stdout.strip():
        if _unexpected_empty_output(returncode):
            detail = (stderr or "").strip().splitlines()[:1]
            return [], f"exited {returncode} with no output" + (f" ({detail[0]})" if detail else "")
        return [], None
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return [], f"could not parse its own JSON output ({exc})"

    findings: list[Finding] = []
    for scan_result in data.get("results", []) if isinstance(data, dict) else ():
        if not isinstance(scan_result, dict):
            continue
        source = scan_result.get("source")
        lock_file = _relative((source or {}).get("path") if isinstance(source, dict) else None, root)
        for package_entry in scan_result.get("packages", []) if isinstance(scan_result.get("packages"), list) else ():
            if not isinstance(package_entry, dict):
                continue
            package_info = package_entry.get("package") or {}
            name = str(package_info.get("name", "?"))
            version = str(package_info.get("version", "?"))
            ecosystem = str(package_info.get("ecosystem", "?"))
            groups = package_entry.get("groups")
            for vuln in package_entry.get("vulnerabilities", []) if isinstance(package_entry.get("vulnerabilities"), list) else ():
                if not isinstance(vuln, dict):
                    continue
                findings.append(Finding(
                    ecosystem=ecosystem, package=name, version=version,
                    advisory_id=str(vuln.get("id", "?")),
                    severity=_osv_severity(vuln, groups),
                    fixed_version=_osv_fixed_version(vuln),
                    lock_file=lock_file,
                    summary=str(vuln.get("summary") or "")[:200],
                ))
    return findings, None


def _run_npm_audit(tool_path: str, root: Path, lock_path: Path) -> "tuple[list[Finding], Optional[str]]":
    stdout, returncode, stderr, start_error = _run([tool_path, "audit", "--json"], lock_path.parent, timeout=_TOOL_TIMEOUT)
    if start_error:
        return [], start_error
    if not stdout or not stdout.strip():
        if _unexpected_empty_output(returncode):
            detail = (stderr or "").strip().splitlines()[:1]
            return [], f"exited {returncode} with no output" + (f" ({detail[0]})" if detail else "")
        return [], None
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return [], f"could not parse its own JSON output ({exc})"
    if isinstance(data, dict) and isinstance(data.get("error"), dict):
        # npm's own top-level {"error": {...}} shape (bad lockfile, network, ...) -- not a
        # vulnerability report at all (2026-09-27 review, item 5)
        error_info = data["error"]
        message = error_info.get("summary") or error_info.get("code") or "unknown npm error"
        return [], str(message)

    findings: list[Finding] = []
    vulnerabilities = data.get("vulnerabilities") if isinstance(data, dict) else None
    if isinstance(vulnerabilities, dict):
        for name, entry in vulnerabilities.items():
            if not isinstance(entry, dict):
                continue
            severity = normalize_severity(entry.get("severity"))
            fix_available = entry.get("fixAvailable")
            fixed_version = fix_available.get("version") if isinstance(fix_available, dict) else None
            via = entry.get("via") if isinstance(entry.get("via"), list) else []
            # a `via` entry that is a plain string names a parent package, not an advisory of its
            # own -- and a dict entry with none of these three fields identifies no real advisory
            # either (2026-09-27 review, item 7); either way it is skipped rather than falling
            # back to a synthetic "?" id, which used to slip past load_accepted's own id check too
            advisory_ids = [
                str(item.get("source") or item.get("url") or item.get("title"))
                for item in via
                if isinstance(item, dict) and (item.get("source") or item.get("url") or item.get("title"))
            ]
            for advisory_id in advisory_ids:
                findings.append(Finding(
                    ecosystem="npm", package=str(name), version=str(entry.get("range", "?")),
                    advisory_id=advisory_id, severity=severity, fixed_version=fixed_version,
                    lock_file=_relative(lock_path, root),
                ))
    return findings, None


def _run_composer_audit(tool_path: str, root: Path, lock_path: Path) -> "tuple[list[Finding], Optional[str]]":
    # --no-plugins --no-scripts: a vendor/ composer plugin or script is dependency code, never run
    # just to audit the dependency it comes from (2026-09-27 review, item 6); --no-interaction:
    # never pause for a prompt in an unattended hook.
    args = [tool_path, "audit", "--format=json", "--no-plugins", "--no-scripts", "--no-interaction"]
    stdout, returncode, stderr, start_error = _run(args, lock_path.parent, timeout=_TOOL_TIMEOUT)
    if start_error:
        return [], start_error
    if not stdout or not stdout.strip():
        if _unexpected_empty_output(returncode):
            detail = (stderr or "").strip().splitlines()[:1]
            return [], f"exited {returncode} with no output" + (f" ({detail[0]})" if detail else "")
        return [], None
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return [], f"could not parse its own JSON output ({exc})"

    findings: list[Finding] = []
    advisories = data.get("advisories") if isinstance(data, dict) else None
    if isinstance(advisories, dict):
        for package_name, entries in advisories.items():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                findings.append(Finding(
                    ecosystem="composer", package=str(package_name),
                    version=str(entry.get("affectedVersions", "?")),
                    advisory_id=str(entry.get("advisoryId") or entry.get("cve") or "?"),
                    severity=normalize_severity(entry.get("severity")),
                    fixed_version=None,  # composer audit's own JSON never names one, see the docstring
                    lock_file=_relative(lock_path, root),
                    summary=str(entry.get("title") or "")[:200],
                ))
    return findings, None


def _run_pip_audit(tool_path: str, root: Path, lock_path: Path) -> "tuple[list[Finding], Optional[str]]":
    # --disable-pip --no-deps: read the pins straight from the file, never install or resolve
    # anything (see the module docstring's "pip-audit mode").
    args = [
        tool_path, "--format", "json", "--disable-pip", "--no-deps",
        "--progress-spinner", "off", "-r", str(lock_path),
    ]
    stdout, returncode, stderr, start_error = _run(args, root, timeout=_TOOL_TIMEOUT)
    if start_error:
        return [], start_error
    if not stdout or not stdout.strip():
        if _unexpected_empty_output(returncode):
            detail = (stderr or "").strip().splitlines()[:1]
            return [], f"exited {returncode} with no output" + (f" ({detail[0]})" if detail else "")
        return [], None
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        return [], f"could not parse its own JSON output ({exc})"

    dependencies = data.get("dependencies") if isinstance(data, dict) else (data if isinstance(data, list) else None)
    findings: list[Finding] = []
    if isinstance(dependencies, list):
        for dependency in dependencies:
            if not isinstance(dependency, dict):
                continue
            name = str(dependency.get("name", "?"))
            version = str(dependency.get("version", "?"))
            for vuln in dependency.get("vulns", []) if isinstance(dependency.get("vulns"), list) else ():
                if not isinstance(vuln, dict):
                    continue
                fix_versions = vuln.get("fix_versions")
                fixed = str(fix_versions[0]) if isinstance(fix_versions, list) and fix_versions else None
                findings.append(Finding(
                    ecosystem="python", package=name, version=version,
                    advisory_id=str(vuln.get("id", "?")),
                    severity="unknown",  # pip-audit's own JSON carries no severity field at all
                    fixed_version=fixed,
                    lock_file=_relative(lock_path, root),
                    summary=str(vuln.get("description") or "")[:200],
                ))
    return findings, None


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_scan(root: Path, lock_files: "Optional[dict[str, list[Path]]]" = None) -> ScanResult:
    """One scan of `root`'s lock files: `osv-scanner` if installed (every detected lock file, one
    call), else one ecosystem-specific fallback tool per ecosystem that has one and is installed
    (npm/composer/pip-audit); an ecosystem with a lock file but no available tool at all
    (`yarn`/`pnpm`/`go`/`cargo` without `osv-scanner`, or `python`'s own fallback missing pip-audit)
    is named in `.missing_tools` and simply not scanned -- never a reason to fail the whole run."""
    result = ScanResult()
    if lock_files is None:
        lock_files = detect_lock_files(root)
    if not lock_files:
        return result

    all_lock_paths = [path for paths in lock_files.values() for path in paths]
    result.scanned_files = [_relative(path, root) for path in all_lock_paths]
    tools = available_tools()

    if "osv-scanner" in tools:
        findings, error = _run_osv_scanner(tools["osv-scanner"], root, all_lock_paths)
        result.tools_used.append("osv-scanner")
        if error:
            result.errors.append(f"osv-scanner: {error}")
        result.findings.extend(findings)
        return result

    if "npm" in lock_files:
        if "npm" in tools:
            for lock_path in lock_files["npm"]:
                findings, error = _run_npm_audit(tools["npm"], root, lock_path)
                if "npm" not in result.tools_used:
                    result.tools_used.append("npm")
                if error:
                    result.errors.append(f"npm audit ({_relative(lock_path, root)}): {error}")
                result.findings.extend(findings)
        else:
            result.missing_tools.append(
                f"osv-scanner ({INSTALL_HINTS['osv-scanner']}) or npm ({INSTALL_HINTS['npm']}) -- "
                "package-lock.json not scanned"
            )

    if "composer" in lock_files:
        if "composer" in tools:
            for lock_path in lock_files["composer"]:
                findings, error = _run_composer_audit(tools["composer"], root, lock_path)
                if "composer" not in result.tools_used:
                    result.tools_used.append("composer")
                if error:
                    result.errors.append(f"composer audit ({_relative(lock_path, root)}): {error}")
                result.findings.extend(findings)
        else:
            result.missing_tools.append(
                f"osv-scanner ({INSTALL_HINTS['osv-scanner']}) or composer ({INSTALL_HINTS['composer']}) "
                "-- composer.lock not scanned"
            )

    python_locks = lock_files.get("python", [])
    pip_audit_locks = [path for path in python_locks if path.name in PIP_AUDIT_LOCK_NAMES]
    other_python_locks = [path for path in python_locks if path.name not in PIP_AUDIT_LOCK_NAMES]
    if pip_audit_locks:
        if "pip-audit" in tools:
            for lock_path in pip_audit_locks:
                findings, error = _run_pip_audit(tools["pip-audit"], root, lock_path)
                if "pip-audit" not in result.tools_used:
                    result.tools_used.append("pip-audit")
                if error:
                    result.errors.append(f"pip-audit ({_relative(lock_path, root)}): {error}")
                result.findings.extend(findings)
        else:
            result.missing_tools.append(
                f"osv-scanner ({INSTALL_HINTS['osv-scanner']}) or pip-audit ({INSTALL_HINTS['pip-audit']}) "
                "-- requirements not scanned"
            )
    if other_python_locks:
        # a missing tool, not a tool failure (2026-09-27 review, item 14) -- osv-scanner is simply
        # not installed here, nothing actually ran and failed
        result.missing_tools.append(
            "poetry.lock/Pipfile.lock only scanned via osv-scanner (not installed) -- pip-audit's "
            "own --disable-pip --no-deps mode needs a plain requirements.txt"
        )

    for ecosystem in ("yarn", "pnpm", "go", "cargo"):
        if ecosystem in lock_files:
            result.missing_tools.append(
                f"osv-scanner ({INSTALL_HINTS['osv-scanner']}) -- {ecosystem}'s lock file has no "
                "other supported tool here"
            )
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _format_finding_line(finding: Finding, accepted: "dict[str, str]") -> str:
    fixed = f" -> fix: {finding.fixed_version}" if finding.fixed_version else ""
    note = f" [accepted: {accepted[finding.advisory_id]}]" if finding.advisory_id in accepted else ""
    return (
        f"{finding.severity:<8} {finding.package} {finding.version} ({finding.advisory_id}) "
        f"in {finding.lock_file}{fixed}{note}"
    )


def main(argv: "Optional[list[str]]" = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Security check Art B -- dependency-vulnerability scan via osv-scanner or an "
            "ecosystem's own audit tool (npm audit / composer audit / pip-audit). Read-only "
            "except for the chosen tool's own network lookup; never installs or builds anything."
        ),
    )
    parser.add_argument("--deps", action="store_true", help="run the scan and print a summary")
    parser.add_argument("--json", action="store_true", help="with --deps: print the result as JSON instead of text")
    args = parser.parse_args(argv)

    if not args.deps:
        parser.print_help()
        return 0

    try:
        root = actlib.repo_root()
    except RuntimeError as exc:
        print(f"[security_scan] {exc}", file=sys.stderr)
        return 2

    result = run_scan(root)
    accepted = load_accepted(root)

    if args.json:
        print(json.dumps(dataclasses.asdict(result), ensure_ascii=False, indent=2))
    else:
        if not result.scanned_files:
            print("[security_scan] no lock file found -- nothing to scan")
        else:
            print(f"[security_scan] scanned: {', '.join(result.scanned_files)}")
            if result.tools_used:
                print(f"[security_scan] tool(s): {', '.join(result.tools_used)}")
            for missing in result.missing_tools:
                print(f"[security_scan] note: missing tool -- {missing}")
            for error in result.errors:
                print(f"[security_scan] note: {error}")
            if result.findings:
                for finding in result.findings:
                    print("  " + _format_finding_line(finding, accepted))
            else:
                print("[security_scan] no known vulnerability found")

    unaccepted_high = [
        finding for finding in result.findings
        if finding.severity in ("critical", "high") and not is_accepted(finding.advisory_id, accepted)
    ]
    return 1 if unaccepted_high else 0


if __name__ == "__main__":
    sys.exit(main())
