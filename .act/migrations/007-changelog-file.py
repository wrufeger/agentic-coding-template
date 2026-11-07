#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Gives an existing project the CHANGELOG.md in its root that `init` now creates for a new one,
#          so `act-commit` and `act-release` have a place to write to. What this does:
#            - If CHANGELOG.md does not exist in the project root and the switch `changelog` in
#              docs/ai/config.md § Formats is `file` (or the row is missing: `file` is the default), the
#              file is created with LF line endings from the starter block of the project's changelog
#              format (docs/project/formats/changelog.md) or, without one, of the template's
#              (.act/formats/changelog.md), or from a built-in copy of the same text: a title, one
#              sentence on the format and an empty `## [Unreleased]`. The new file is written through a
#              temporary file created exclusively in the project root, which is gone on every path.
#            - A CHANGELOG.md that exists is never touched, whatever it contains, and neither is a
#              symbolic link or a Windows junction at that path (the migration says "skipped: ... is a
#              link or junction" and creates nothing). A project that keeps its changelog under another name or in
#              another letter case (`changelog.md`, `CHANGES.md`, `HISTORY.md`, `NEWS` ...) gets no
#              second file either: the migration says which file it found and creates nothing. With `changelog: release-notes-only` or `off` nothing is
#              created; the description says so.
#            - Nothing else is written. Old releases are not reconstructed from the git history: the
#              file starts empty and fills from the next commit with a visible effect (format permitting)
#              or from the next release.
#          Why a migration and not a step of update.py: it runs once per project and is recorded in the
#          lock, so a project that deletes the file or switches the changelog off afterwards is not offered
#          it again at every update; update.py lists the migration in its plan (`would run: 007-...`) and prints
#          its plan line before applying it, and the project answers by agreeing to the update, or by
#          adding the row `changelog` with the value `off` under § Formats in docs/ai/config.md first (an old
#          config has no such section, and `config.py` refuses to set a missing row: add it by hand). init
#          records every migration it ships as done for a new project, which already has the file from
#          `init` itself. plan() only reads, never writes.
#
# Contract (.act/scripts/update.py step 8): plan(root) -> str, apply(root) -> (str, list[str]) of
# project-relative paths (posix separators) touched. Stdlib only; the link test lives in the sibling file
# _links.py (loaded below, shipped together with this file).

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

TARGET = "CHANGELOG.md"
PROJECT_FORMAT = "docs/project/formats/changelog.md"
TEMPLATE_FORMAT = ".act/formats/changelog.md"
FALLBACK = (
    "# Changelog\n\n"
    "All notable changes to this project are documented in this file.\n"
    "The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).\n\n"
    "## [Unreleased]\n"
)
_ROW_RE = re.compile(r"^\|\s*`?changelog`?\s*\|\s*`?([^|`]*?)`?\s*\|", re.MULTILINE)
_LIKE_RE = re.compile(r"(?:changelog|changes|history|news)(?![A-Za-z])", re.IGNORECASE)
_STARTER_RE = re.compile(r"^## Starter file[^\n]*\n.*?^```[^\n]*\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)


def _exists(path: Path) -> bool:
    """True for a file or a folder at `path`."""
    return path.exists()


def _mode(root: Path) -> str:
    """The value of the `changelog` row of docs/ai/config.md; `file` when the row or the file is missing,
    empty or not one of the three known values."""
    try:
        text = (root / "docs" / "ai" / "config.md").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "file"
    match = _ROW_RE.search(text)
    value = match.group(1).strip().lower() if match else ""
    return value if value in ("file", "release-notes-only", "off") else "file"


def _starter(root: Path) -> str:
    for rel in (PROJECT_FORMAT, TEMPLATE_FORMAT):
        try:
            text = (root / rel).read_text(encoding="utf-8").replace("\r\n", "\n")
        except (OSError, UnicodeDecodeError):
            continue
        match = _STARTER_RE.search(text)
        if match and match.group(1).strip():
            return match.group(1)
    return FALLBACK


def _like(root: Path) -> str:
    """The first name in the project root that serves as a changelog under another name or letter case
    (`changelog`, `changes`, `history`, `news`, alone or with an extension, dash or digit; `newsletter.md`
    is none), a file or a link; "" when there is none."""
    try:
        listing = sorted(root.iterdir(), key=lambda p: p.name)
    except OSError:
        return ""
    for entry in listing:
        if entry.name != TARGET and _LIKE_RE.match(entry.name) and (entry.is_symlink() or entry.is_file()):
            return entry.name
    return ""


def _state(root: Path) -> str:
    """"linked", "exists", "other-name", "switched-off" or "create"."""
    if _LINKS.link_problem(root, root / TARGET):  # a link at the path (even a dangling one)
        return "linked"
    if _exists(root / TARGET):
        return "exists"
    if _like(root):
        return "other-name"
    if _mode(root) != "file":
        return "switched-off"
    return "create"


def plan(root: Path) -> str:
    """Describes what apply() would do, writes nothing."""
    state = _state(root)
    if state == "linked":
        return (f"skipped: {_LINKS.link_problem(root, root / TARGET)} — nothing is written through it, "
                f"{TARGET} is left as it is")
    if state == "create":
        return (f"would create {TARGET} with an empty `## [Unreleased]` section (to prevent it, add the row "
                "`changelog` with the value `off` under § Formats in docs/ai/config.md first)")
    if state == "other-name":
        return f"{_like(root)} is already the project's changelog — {TARGET} is not created"
    if state == "switched-off":
        return f"`changelog` is {_mode(root)} in docs/ai/config.md — {TARGET} is not created"
    return f"{TARGET} exists — nothing to do"


def apply(root: Path) -> tuple[str, list[str]]:
    """Creates the file as described above. Returns (description, touched project-relative paths)."""
    if _state(root) != "create":
        return plan(root), []
    target = root / TARGET
    _LINKS.write_new(target, _starter(root).encode("utf-8"))  # LF endings: the text is written as it is
    return f"created {TARGET} with an empty `## [Unreleased]` section", [TARGET]


if __name__ == "__main__":
    project = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    print(plan(project))
