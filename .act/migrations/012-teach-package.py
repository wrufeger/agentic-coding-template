#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Offers the package `teach` to a project that used the skills `act-teach` or `act-slides`, which the
#          template no longer ships; writes nothing, only says what it found and the command to run. What this does
#          (plan() and apply() both only return text; the project is read, never written):
#            - a folder `.act-local/learn/` (the learning records of `act-teach`),
#            - a folder `docs/learn/` (versioned lessons, `teach-lessons: docs`),
#            - a file `docs/presentation/*.md` (a deck of `act-slides`),
#            - the setting `teach-lessons: docs` in docs/ai/config.md (a table row; the file is read as bytes and
#              decoded as UTF-8 with replacement, a BOM is ignored).
#          With one or more of them the text names each one found and the command `/act-packages add teach`, and
#          says that an unedited copy of the two skills goes with this update while an edited one stays. Without any,
#          or with the package `teach` already recorded in .act-lock.json, it is one line: nothing to offer.
#          The text is right whether the skill copies are still there (the --plan preview) or already gone (the
#          update removes them in an earlier step than the migrations), because it speaks of the update as a whole.
#          Why a migration: only a project that used the skills needs to hear that they moved, and only once.
#          plan() only reads, never writes; apply() returns the same text and an empty list of touched files.
#
# Contract (.act/scripts/update.py step 8): plan(root) -> str, apply(root) -> (str, list[str]) of
# project-relative paths (posix separators) touched. Stdlib only.

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

CONFIG = "docs/ai/config.md"
LOCK = ".act-lock.json"
PACKAGE = "teach"
_UNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")

NOTHING = ("no use of the teaching skills found (`.act-local/learn/`, `docs/learn/`, `docs/presentation/*.md`, "
           "`teach-lessons: docs`) — nothing to offer")
INSTALLED = f"package `{PACKAGE}` is already installed — nothing to offer"


def _installed(root: Path) -> bool:
    """True when .act-lock.json records the package; an unreadable lock counts as not installed."""
    try:
        lock = json.loads((root / LOCK).read_bytes().decode("utf-8-sig", "replace"))
    except (OSError, ValueError):
        return False
    packages = lock.get("packages") if isinstance(lock, dict) else None
    return isinstance(packages, dict) and PACKAGE in packages


def _teach_lessons(root: Path) -> str:
    """The value of the `teach-lessons` row of docs/ai/config.md (the last row wins), "" when there is none."""
    try:
        text = (root / CONFIG).read_bytes().decode("utf-8", "replace").lstrip("\ufeff")
    except OSError:
        return ""
    value = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        cells = _UNESCAPED_PIPE_RE.split(stripped[1:-1])
        if len(cells) >= 2 and cells[0].strip().strip("`").strip() == "teach-lessons":
            value = cells[1].strip().strip("`").strip().lower()
    return value


def _signals(root: Path) -> list[str]:
    """One phrase per sign of use found, in a fixed order."""
    found: list[str] = []
    if (root / ".act-local" / "learn").is_dir():
        found.append("the folder `.act-local/learn/` (learning records)")
    if (root / "docs" / "learn").is_dir():
        found.append("the folder `docs/learn/` (lessons)")
    deck = root / "docs" / "presentation"
    try:
        decks = sorted(p.name for p in deck.iterdir() if p.suffix.lower() == ".md" and p.is_file()) \
            if deck.is_dir() else []
    except OSError:
        decks = []
    if decks:
        found.append(f"{len(decks)} file(s) `docs/presentation/*.md` (slide decks)")
    if _teach_lessons(root) == "docs":
        found.append("the setting `teach-lessons: docs` in docs/ai/config.md")
    return found


def _describe(root: Path) -> str:
    if _installed(root):
        return INSTALLED
    found = _signals(root)
    if not found:
        return NOTHING
    return ("offer: this project looks like it uses the teaching skills `act-teach` and `act-slides` (found: "
            + "; ".join(found) + "). The template no longer ships them; they now come as the package `teach`. "
            "An unedited copy of the two skills goes with this update, an edited one stays. To keep using them run "
            "`/act-packages add teach` (the plan and a diff come first, nothing is installed without your yes). "
            "This migration writes nothing")


def plan(root: Path) -> str:
    """Describes what apply() would say, writes nothing."""
    return _describe(root)


def apply(root: Path) -> tuple[str, list[str]]:
    """Returns the offer (or the one line that there is none) and an empty list: no file is written."""
    return _describe(root), []


if __name__ == "__main__":
    project = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    print(plan(project))
