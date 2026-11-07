#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Gives an existing project the index file docs/project/README.md. A new project gets it from
#          the bridge .act/bridges/docs-project-readme.md when it is set up; a project from before the
#          rule on the order of the project docs does not have it. What this does:
#            - If docs/project/ exists and docs/project/README.md does not, the file is created from the
#              bridge, with LF line endings, minus the table rows of coding_rules.md and glossary.md
#              when the project has no such file (an index line without its file is a finding).
#            - A file that exists is never touched, whatever it contains. A symbolic link or a Windows
#              junction at that path, or on the way to it, is never written through: the migration says
#              so ("skipped: ... is a link or junction") and creates nothing. The new file is written
#              through a temporary file created exclusively in its folder, which is gone on every path.
#            - Without docs/project/ or without the bridge, nothing is created and the description says
#              so. Nothing else is written: the README.md of the project's other folders, and the lines
#              for the files already in docs/project/, are the project's to write (act-doctor names
#              what is missing, the step "Structure" of act-audit-docs moves documents).
#          Re-running apply() changes nothing (the file exists by then). A project that deletes the file
#          afterwards does not get it back: update.py runs a migration only once and records it in the
#          lock; init records every migration it ships as done for a new project, which already has the
#          file from the bridge. plan() only reads, never writes.
#
# Contract (.act/scripts/update.py step 8): plan(root) -> str, apply(root) -> (str, list[str]) of
# project-relative paths (posix separators) touched. Stdlib only; the one use of `actlib` (the inbox
# entry for translating new scaffold, only with `language-docs` other than English) is guarded: a failure
# there never stops the migration.
# The link test lives in the sibling file _links.py (loaded below, shipped together with this file).

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path


def _load_links():
    """The sibling _links.py (link test, exclusive temporary file), loaded by file name."""
    spec = importlib.util.spec_from_file_location("_act_migration_links", Path(__file__).with_name("_links.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_LINKS = _load_links()

TARGET = "docs/project/README.md"
SOURCE = ".act/bridges/docs-project-readme.md"
_ROW_FILE_RE = re.compile(r"^\|\s*`([\w.\-]+\.md)`")


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
    """"linked", "exists", "no-folder", "no-source" or "create"."""
    if _LINKS.link_problem(root, root / TARGET):  # a link at the path or on the way, even a dangling one
        return "linked"
    if (root / TARGET).exists():
        return "exists"
    if not (root / "docs" / "project").is_dir():
        return "no-folder"
    if not (root / SOURCE).is_file():
        return "no-source"
    return "create"


def _text(root: Path) -> str:
    """The bridge text without the table rows whose file the project does not have."""
    source = (root / SOURCE).read_text(encoding="utf-8").replace("\r\n", "\n")
    kept = []
    for line in source.split("\n"):
        match = _ROW_FILE_RE.match(line)
        if match and not (root / "docs" / "project" / match.group(1)).is_file():
            continue
        kept.append(line)
    return "\n".join(kept)


def plan(root: Path) -> str:
    """Describes what apply() would do, writes nothing."""
    state = _state(root)
    if state == "linked":
        return (f"skipped: {_LINKS.link_problem(root, root / TARGET)} — nothing is written through it, "
                f"{TARGET} is left as it is")
    if state == "create":
        return (f"would create {TARGET} from {SOURCE}; with `language-docs` other than English it would "
                "also create or extend the inbox entry *-translate-scaffold.md")
    if state == "no-folder":
        return "docs/project/ does not exist — nothing to do"
    if state == "no-source":
        return f"{SOURCE} is missing — nothing to do"
    return f"{TARGET} exists — nothing to do"


def apply(root: Path) -> tuple[str, list[str]]:
    """Creates the file as described above. Returns (description, touched project-relative paths)."""
    if _state(root) != "create":
        return plan(root), []
    target = root / TARGET
    _LINKS.write_new(target, _text(root).encode("utf-8"))  # LF endings: the text is written as it is
    note, touched = _note_translation(root, TARGET)
    return f"created {TARGET} from {SOURCE}{note}", [TARGET, *touched]
