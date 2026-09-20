#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Shared library for every script under .act/scripts/ and .act/hooks/ — the single place that
#          knows how to resolve template vs. project files, and how to read/write the small state files
#          the template keeps outside of .act/ (lock file, per-checkout identity, generated-file cache,
#          project config). Stdlib only, no third-party dependencies.
#
# Usage: not run directly — imported, e.g. `import actlib` from a script in the same directory
#        (.act/scripts/ or .act/hooks/, both add their own directory to sys.path automatically).
#
# Output format: this module has no CLI output of its own; each function's return value is documented
#        at the function.
#
# Conventions used throughout:
#   - All paths are pathlib.Path, resolved relative to repo_root() unless documented otherwise.
#   - All file I/O is UTF-8, explicit.
#   - JSON files are written with indent=2, sorted only where noted, and a trailing newline.
#   - "Unknown fields" in a JSON state file (keys not part of the documented schema) are preserved on
#     write: a write merges onto the file's current content instead of replacing it outright.

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Root and path resolution
# ---------------------------------------------------------------------------

def repo_root(start: Optional[Path] = None) -> Path:
    """
    Find the project root by walking upward from `start` (default: the current working
    directory) until a directory containing a `.act` subdirectory is found.

    Works regardless of the working directory the caller was invoked from, as long as it is
    somewhere inside the project tree.

    Raises RuntimeError if no `.act` directory is found up to the filesystem root.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".act").is_dir():
            return candidate
    raise RuntimeError(
        "repo_root: no '.act' directory found in any parent of "
        f"'{current}' — is this run inside a template-managed project?"
    )


def resolve(path: str) -> Optional[tuple[Path, str]]:
    """
    Resolve a template-relative path (e.g. "rules/shared/00-core.md") against the single
    override rule used everywhere in this template — checklists, topic rules, scripts alike:

      1. docs/ai/local/<path>  — project override, wins if present
      2. .act/<path>           — template default

    Returns a (resolved_path, origin) tuple, where origin is "local" or "template", or None if
    neither location has the file.
    """
    root = repo_root()
    local_path = root / "docs" / "ai" / "local" / path
    if local_path.is_file():
        return local_path, "local"
    template_path = root / ".act" / path
    if template_path.is_file():
        return template_path, "template"
    return None


# ---------------------------------------------------------------------------
# JSON state files — shared read/write helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> Optional[dict]:
    """Read a JSON object from `path`. Returns None if the file is missing, unreadable, or not a
    JSON object (never raises for those cases — callers fall back to a default)."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_json_merged(path: Path, data: dict) -> dict:
    """Write `data` to `path` as JSON, merging onto whatever is already there so unknown top-level
    keys already present on disk survive the write. Creates the parent directory if needed.
    Returns the merged dict actually written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = _read_json(path) or {}
    merged.update(data)
    path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return merged


# ---------------------------------------------------------------------------
# .act-lock.json — versioned, tracks the applied template state
# ---------------------------------------------------------------------------

def _default_lock() -> dict:
    return {
        "template": {"version": "", "commit": "", "source": ""},
        "migrations_applied": [],
        "removed_by_user": [],
    }


def read_lock() -> dict:
    """Read .act-lock.json at the repo root. Returns a fresh, valid skeleton (see _default_lock)
    if the file does not exist yet; missing required keys in an existing file are filled in with
    defaults without touching any other key present."""
    path = repo_root() / ".act-lock.json"
    data = _read_json(path)
    if data is None:
        return _default_lock()
    result = _default_lock()
    result.update(data)
    return result


def write_lock(data: dict) -> dict:
    """Merge `data` onto .act-lock.json at the repo root and write it back. Any field already in
    the file that is not part of `data` (including fields unknown to this template version) is
    kept. Returns the merged dict actually written."""
    path = repo_root() / ".act-lock.json"
    return _write_json_merged(path, data)


# ---------------------------------------------------------------------------
# .act-local/identity.json — per-checkout identity, gitignored
# ---------------------------------------------------------------------------

def _identity_path() -> Path:
    return repo_root() / ".act-local" / "identity.json"


def read_identity() -> Optional[dict]:
    """Read .act-local/identity.json. Returns None if it does not exist (or is unreadable) —
    callers treat that as "not initialized yet", never as an error."""
    return _read_json(_identity_path())


def write_identity(data: dict) -> dict:
    """Merge `data` (expected keys: identity, workspace, created) onto .act-local/identity.json,
    creating the .act-local/ directory if needed. Returns the merged dict actually written."""
    return _write_json_merged(_identity_path(), data)


# ---------------------------------------------------------------------------
# .act-local/cache.json — generated-file cache, gitignored
# ---------------------------------------------------------------------------

def _cache_path() -> Path:
    return repo_root() / ".act-local" / "cache.json"


def read_cache() -> dict:
    """Read .act-local/cache.json. Returns {"generated": {}} if the file is missing or unreadable,
    and fills in a missing "generated" key so callers can always index into it directly."""
    data = _read_json(_cache_path()) or {}
    data.setdefault("generated", {})
    return data


def write_cache(data: dict) -> dict:
    """Merge `data` (expected key: "generated", a dict mapping path -> sha256) onto
    .act-local/cache.json, creating the .act-local/ directory if needed. Returns the merged dict
    actually written."""
    merged = _write_json_merged(_cache_path(), data)
    merged.setdefault("generated", {})
    return merged


# ---------------------------------------------------------------------------
# docs/ai/config.md — project configuration as a Markdown key/value table
# ---------------------------------------------------------------------------

def read_config() -> dict[str, str]:
    """
    Read docs/ai/config.md as a simple key/value table: any Markdown table row with exactly two
    cells is taken as (key, value); the header row and the "---" separator row are skipped.
    Robust against a missing file and against lines that are not a two-cell table row — those are
    silently ignored rather than raising.
    """
    path = repo_root() / "docs" / "ai" / "config.md"
    config: dict[str, str] = {}
    if not path.is_file():
        return config
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return config

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        inner = stripped[1:-1]
        cells = [cell.strip() for cell in inner.split("|")]
        if len(cells) != 2:
            continue
        key, value = cells
        if not key:
            continue
        if _is_separator_cell(key) and _is_separator_cell(value):
            continue
        if _is_header_row(lines, index):
            continue
        config[key] = value
    return config


def _is_header_row(lines: list[str], index: int) -> bool:
    """True if the table row at `index` is a header row: the next non-empty line is a
    separator row. Word-free on purpose — the header may be written in any language."""
    for following in lines[index + 1:]:
        stripped = following.strip()
        if not stripped:
            continue
        if not (stripped.startswith("|") and stripped.endswith("|")):
            return False
        cells = [cell.strip() for cell in stripped[1:-1].split("|")]
        return bool(cells) and all(_is_separator_cell(cell) for cell in cells)
    return False


def _is_separator_cell(cell: str) -> bool:
    """True for a Markdown table separator cell such as ":---", "---", "---:", ":---:"."""
    body = cell.strip(":")
    return bool(body) and set(body) == {"-"}


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of the file at `path`, read in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_interactive() -> bool:
    """True if this run should be treated as interactive: stdin is a real terminal and the caller
    did not pass --non-interactive."""
    if "--non-interactive" in sys.argv:
        return False
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False
