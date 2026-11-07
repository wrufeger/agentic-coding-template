#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Gives an existing project the reading-list file docs/ai/local/resources.md. A new project
#          gets it from the scaffold when it is set up; a project from before the file existed does
#          not have it. What this does:
#            - If docs/ai/local/resources.md does not exist, it is created as a copy of the scaffold
#              file .act/skeleton/local/resources.md, with LF line endings (the same text a new
#              project starts with).
#            - A file that exists is never touched, whatever it contains. A symbolic link or a Windows
#              junction at that path, or on the way to it, is never written through: the migration says
#              so ("skipped: ... is a link or junction") and creates nothing. The new file is written
#              through a temporary file created exclusively in its folder, which is gone on every path.
#            - If the scaffold file is missing from .act/skeleton/, nothing is created and the
#              description says so.
#          Re-running apply() changes nothing (the file exists by then). A project that deletes the
#          file afterwards does not get it back: update.py runs a migration only once and records it
#          in the lock; init records every migration it ships as done for a new project, which
#          already has the file from the scaffold. plan() only reads, never writes.
#
# Contract (.act/scripts/update.py step 8): plan(root) -> str, apply(root) -> (str, list[str]) of
# project-relative paths (posix separators) touched. Stdlib only; the one use of `actlib` (the inbox
# entry for translating new scaffold, only with `language-docs` other than English) is guarded: a failure
# there never stops the migration.
# The link test lives in the sibling file _links.py (loaded below, shipped together with this file).

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_links():
    """The sibling _links.py (link test, exclusive temporary file), loaded by file name."""
    spec = importlib.util.spec_from_file_location("_act_migration_links", Path(__file__).with_name("_links.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_LINKS = _load_links()

TARGET = "docs/ai/local/resources.md"
SOURCE = ".act/skeleton/local/resources.md"


def _note_translation(root: Path, rel: str) -> tuple[str, list[str]]:
    """With `language-docs` other than English, enters the new scaffold file `rel` into the inbox
    entry for the scaffold translation (actlib.note_scaffold_for_translation). Returns (a phrase
    for the description or "", the entry's project-relative path as a list or empty). Never
    raises: the file is created either way, a missing entry only costs the hint."""
    scripts = str(root / ".act" / "scripts")
    inbox_problem = _LINKS.link_problem(root, root / "docs" / "ai" / "inbox")
    if inbox_problem:
        return f"; translation entry not written ({inbox_problem})", []
    try:
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        import actlib
        note = getattr(actlib, "note_scaffold_for_translation", None)
        entry = note(root, [rel]) if note is not None else None
    except Exception as exc:
        return f"; translation entry not written ({exc.__class__.__name__}: {exc})", []
    if entry is None:
        return "", []
    entry_rel = entry.relative_to(root).as_posix()
    return f"; named in {entry_rel} for translation", [entry_rel]


def _state(root: Path) -> str:
    """"linked", "exists", "no-source" or "create"."""
    if _LINKS.link_problem(root, root / TARGET):  # a link at the path or on the way, even a dangling one
        return "linked"
    if (root / TARGET).exists():
        return "exists"
    if not (root / SOURCE).is_file():
        return "no-source"
    return "create"


def plan(root: Path) -> str:
    """Describes what apply() would do, writes nothing."""
    state = _state(root)
    if state == "linked":
        return (f"skipped: {_LINKS.link_problem(root, root / TARGET)} — nothing is written through it, "
                f"{TARGET} is left as it is")
    if state == "create":
        return (f"would create {TARGET} from the scaffold; with `language-docs` other than English it would "
                "also create or extend the inbox entry *-translate-scaffold.md")
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
    _LINKS.write_new(target, text.encode("utf-8"))  # LF endings: the text is written as it is
    note, touched = _note_translation(root, TARGET)
    return f"created {TARGET} from the scaffold{note}", [TARGET, *touched]
