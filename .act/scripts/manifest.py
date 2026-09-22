#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Generate or verify .act/MANIFEST.json — a SHA-256 hash per file under .act/, used to
#          detect local edits to the template before an update overwrites them. Stdlib only.
#
# Usage:
#   python .act/scripts/manifest.py --write     # (re)generate .act/MANIFEST.json from disk
#   python .act/scripts/manifest.py --check     # compare disk against .act/MANIFEST.json
#
# Output format:
#   --write: prints "MANIFEST.json: wrote <n> file(s)" to stdout, exit 0.
#   --check: one line per difference, "<path>:<state>" (state is one of "modified", "missing",
#            "added"), relative to .act/ with forward slashes; prints "MANIFEST.json: no
#            differences" and exits 0 if there are none, exits 1 if there are any differences.
#
# MANIFEST.json itself is excluded from both the written manifest and the comparison, since it
# cannot hash itself. This script is included like any other file: excluding it by its own
# location made the result depend on which copy of .act/ ran it (init from the template checkout
# vs. the project's own copy).

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import actlib


def _act_dir() -> Path:
    return actlib.repo_root() / ".act"


def _manifest_path(act_dir: Path) -> Path:
    return act_dir / "MANIFEST.json"


def collect_files(act_dir: Path) -> dict[str, str]:
    """Return {relative_path: sha256} for every file under `act_dir`, excluding MANIFEST.json
    and Python bytecode caches (__pycache__/, *.pyc, *.pyo — generated locally,
    not part of the template's tracked content). Relative paths use forward slashes for a
    platform-independent manifest."""
    manifest_path = _manifest_path(act_dir).resolve()
    files: dict[str, str] = {}
    for path in sorted(act_dir.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            continue
        resolved = path.resolve()
        if resolved == manifest_path:
            continue
        rel = path.relative_to(act_dir).as_posix()
        files[rel] = content_hash(path)
    return files


def content_hash(path: Path) -> str:
    """SHA-256 of the file with CRLF folded to LF — unless it holds a NUL byte (binary). A checkout
    with core.autocrlf=true or a template committed with CRLF must not look like a hand edit."""
    data = path.read_bytes()
    if b"\x00" not in data:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def write_manifest(act_dir: Path) -> int:
    """Write .act/MANIFEST.json from disk and return the number of files it lists.

    `newline="\\n"` pins the file itself to LF regardless of platform: without it, `write_text`
    on Windows translates "\\n" to "\\r\\n" on write, so a manifest generated there would carry
    CRLF while `.gitattributes` (`eol=lf`) stores it as LF in git -- every checkout/clone would
    then see a raw byte difference and `manifest_fingerprint()` below exists to fold that away,
    but only if the file on disk was written the same way it is compared."""
    files = collect_files(act_dir)
    manifest_path = _manifest_path(act_dir)
    manifest_path.write_text(
        json.dumps(files, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return len(files)


def manifest_fingerprint(act_dir: Path) -> str:
    """SHA-256 fingerprint of `act_dir`/MANIFEST.json itself, CRLF-folded via `content_hash()` --
    the same folding every entry inside the manifest already gets. Used for
    .act-lock.json's `template.manifest_sha256` (init.py, update.py) and by dispatch.py to notice
    a project .act/ that came from somewhere other than update.py: without the folding, a manifest
    written on Windows (CRLF, see `write_manifest()`) compared against one recorded from a Linux
    write (LF) would look tampered with even though `--check` above finds no differences. Returns
    "" if the manifest does not exist (a fresh checkout with no lock yet)."""
    manifest_path = _manifest_path(act_dir)
    if not manifest_path.is_file():
        return ""
    return content_hash(manifest_path)


def check_manifest(act_dir: Path) -> int:
    manifest_path = _manifest_path(act_dir)
    if not manifest_path.is_file():
        print(f"MANIFEST.json: missing — run --write first ({manifest_path})", file=sys.stderr)
        return 1
    try:
        recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"MANIFEST.json: unreadable ({exc})", file=sys.stderr)
        return 1

    current = collect_files(act_dir)
    differences: list[str] = []

    for path, recorded_hash in sorted(recorded.items()):
        if path not in current:
            differences.append(f"{path}:missing")
        elif current[path] != recorded_hash:
            differences.append(f"{path}:modified")
    for path in sorted(current):
        if path not in recorded:
            differences.append(f"{path}:added")

    if not differences:
        print("MANIFEST.json: no differences")
        return 0

    for line in sorted(differences):
        print(line)
    return 1


def main(argv: list[str]) -> int:
    # Messages here can carry an em dash (e.g. the "missing" message below); on Windows,
    # stdout/stderr otherwise default to the console's legacy code page instead of UTF-8, which
    # would corrupt it. Same fix as .act/scripts/rules.py.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    if len(argv) != 1 or argv[0] not in ("--write", "--check"):
        print("usage: manifest.py --write | --check", file=sys.stderr)
        return 2

    act_dir = _act_dir()
    if argv[0] == "--write":
        print(f"MANIFEST.json: wrote {write_manifest(act_dir)} file(s)")
        return 0
    return check_manifest(act_dir)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
