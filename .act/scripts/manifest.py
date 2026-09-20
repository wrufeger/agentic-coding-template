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
# MANIFEST.json itself and this script are excluded from both the written manifest and the
# comparison, since neither is meaningful to hash against itself.

from __future__ import annotations

import json
import sys
from pathlib import Path

import actlib


def _act_dir() -> Path:
    return actlib.repo_root() / ".act"


def _manifest_path(act_dir: Path) -> Path:
    return act_dir / "MANIFEST.json"


def _self_path() -> Path:
    return Path(__file__).resolve()


def collect_files(act_dir: Path) -> dict[str, str]:
    """Return {relative_path: sha256} for every file under `act_dir`, excluding MANIFEST.json,
    this script itself, and Python bytecode caches (__pycache__/, *.pyc, *.pyo — generated locally,
    not part of the template's tracked content). Relative paths use forward slashes for a
    platform-independent manifest."""
    manifest_path = _manifest_path(act_dir).resolve()
    self_path = _self_path()
    files: dict[str, str] = {}
    for path in sorted(act_dir.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            continue
        resolved = path.resolve()
        if resolved == manifest_path or resolved == self_path:
            continue
        rel = path.relative_to(act_dir).as_posix()
        files[rel] = actlib.sha256_file(path)
    return files


def write_manifest(act_dir: Path) -> int:
    files = collect_files(act_dir)
    manifest_path = _manifest_path(act_dir)
    manifest_path.write_text(
        json.dumps(files, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"MANIFEST.json: wrote {len(files)} file(s)")
    return 0


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
        return write_manifest(act_dir)
    return check_manifest(act_dir)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
