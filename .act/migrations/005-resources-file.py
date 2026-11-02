#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Gives an existing project the reading-list file docs/ai/local/resources.md. A new project
#          gets it from the scaffold when it is set up; a project from before the file existed does
#          not have it. What this does:
#            - If docs/ai/local/resources.md does not exist, it is created as a copy of the scaffold
#              file .act/skeleton/local/resources.md, with LF line endings (the same text a new
#              project starts with).
#            - A file that exists is never touched, whatever it contains. A symbolic link at that
#              path (or on the way) counts as existing and is left alone.
#            - If the scaffold file is missing from .act/skeleton/, nothing is created and the
#              description says so.
#          Re-running apply() changes nothing (the file exists by then). A project that deletes the
#          file afterwards does not get it back: update.py runs a migration only once and records it
#          in the lock; init records every migration it ships as done for a new project, which
#          already has the file from the scaffold. plan() only reads, never writes.
#
# Contract (.act/scripts/update.py step 8): plan(root) -> str, apply(root) -> (str, list[str]) of
# project-relative paths (posix separators) touched. Stdlib only, no `actlib` import: a migration
# must not depend on the *project's* possibly-older copy of it.

from __future__ import annotations

import os
from pathlib import Path

TARGET = "docs/ai/local/resources.md"
SOURCE = ".act/skeleton/local/resources.md"


def _exists(path: Path) -> bool:
    """True for a file, a folder or a (possibly dangling) symbolic link at `path`, or on the way."""
    return path.exists() or any(part.is_symlink() for part in (path, *path.parents) if part.name)


def _state(root: Path) -> str:
    """"exists", "no-source" or "create"."""
    if _exists(root / TARGET):
        return "exists"
    if not (root / SOURCE).is_file():
        return "no-source"
    return "create"


def plan(root: Path) -> str:
    """Describes what apply() would do, writes nothing."""
    state = _state(root)
    if state == "create":
        return f"would create {TARGET} from the scaffold"
    if state == "no-source":
        return f"{SOURCE} is missing — nothing to do"
    return f"{TARGET} exists — nothing to do"


def apply(root: Path) -> tuple[str, list[str]]:
    """Creates the file as described above. Returns (description, touched project-relative paths)."""
    state = _state(root)
    if state != "create":
        return plan(root), []
    text = (root / SOURCE).read_text(encoding="utf-8")
    target = root / TARGET
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.migrating")
    try:
        with open(temp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(temp, target)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise
    return f"created {TARGET} from the scaffold", [TARGET]
