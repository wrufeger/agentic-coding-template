#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Moves the entries under docs/ai/work/ from plain header lines to YAML frontmatter. A task,
#          backlog or journal entry (and every entry that was archived) used to start with "key:
#          value" lines (id, for, created, started ...) straight at the top of the file; from now on
#          the scripts write them between two "---" lines, so any Markdown or YAML-aware tool sees
#          them as metadata (the inbox moved earlier, see 003-inbox-frontmatter):
#              id: T<n>                  ---
#              created: ...              id: T<n>
#                                ->      created: ...
#              # Title                   ---
#
#                                        # Title
#          What this does (the same in "solo" and "team" mode):
#            - Candidates are the "*.md" files under docs/ai/work/tasks/, backlog/, ledger/ and
#              archive/ (the archive recursively, so archived inbox entries and proposals too),
#              except every README.md (any letter case) and everything under archive/legacy/. A file
#              is rewritten only when its first line (after an optional UTF-8 BOM) is a header
#              field, i.e. matches "<name>: ..." like the header readers expect.
#            - The leading run of header lines is kept unchanged, wrapped in a "---" line above and
#              below; a field without a value ("for:") ends the run, as it does for the readers.
#              Everything after the header stays byte for byte, so a "---" divider further down (a
#              reply block) is not touched. The line ending of the header lines (LF or CRLF) is used
#              for the two new "---" lines.
#            - A leading BOM is dropped (the opening "---" must be the very first thing in the file,
#              or the frontmatter would not be recognized), as migrations 002 and 003 do.
#            - The header is found the way actlib.split_header finds it: lines end at LF only (a lone
#              CR is no line break) and a field is matched with the readers' own pattern.
#            - Each file is replaced through a temporary file and os.replace, so an abort never leaves
#              a cut-off file; a symbolic link is left alone instead of being written through.
#            - Left byte-identical: a file that already starts with "---", a file without a header,
#              the READMEs, the legacy archive and every other folder (docs/ai/inbox/ was handled by
#              003). A file that is not valid UTF-8 is reported and left as it is.
#          Re-running apply() changes nothing (a converted file starts with "---"); plan() only
#          reads, never writes. update.py runs due migrations in sorted order, so 001 to 003 run
#          before this one when they are due in the same update.
#
# Contract (.act/scripts/update.py step 8): plan(root) -> str, apply(root) -> (str, list[str]) of
# project-relative paths (posix separators) touched. Stdlib only, no `actlib` import: a migration
# must not depend on the *project's* possibly-older copy of it — the small header scan this needs is
# reimplemented below.

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Optional

WORK_DIR = "docs/ai/work"
SCAN_DIRS = ("tasks", "backlog", "ledger", "archive")  # below WORK_DIR; the archive is walked recursively
LEGACY_DIR = "archive/legacy"  # below WORK_DIR; never rewritten
LIST_LIMIT = 10  # names listed in plan()/apply() descriptions before "... and N more"

_BOM = b"\xef\xbb\xbf"
_FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z-]*:\s")  # same pattern as the header readers' (str, so \s also matches NBSP)


def _is_readme(name: str) -> bool:
    return name.lower() == "readme.md"


def _is_field(line: str) -> bool:
    # as the header readers see it: lines split at "\n" only, a trailing "\r" is not content, and
    # "for:" with no value is not a field
    return bool(_FIELD_RE.match(line.rstrip("\r")))


def _is_legacy(relative: Path) -> bool:
    """True for archive/legacy and everything below it, whatever the letter case (a case-folding
    file system such as Windows' reports the folder under either spelling, others keep both)."""
    legacy_parts = [part.lower() for part in LEGACY_DIR.split("/")]
    return [part.lower() for part in relative.parts[:len(legacy_parts)]] == legacy_parts


def _has_link(path: Path, base: Path) -> bool:
    """True if `path` or a folder between `base` and it is a symbolic link."""
    return any(part.is_symlink() for part in (path, *path.parents) if part != base and base in part.parents)


def _convert(data: bytes) -> Optional[bytes]:
    """`data` in frontmatter form, or None when the file is not a candidate (already frontmatter,
    no header). Raises UnicodeDecodeError for content that is not valid UTF-8. The header is found
    the way actlib.split_header finds it: lines end at "\n" only (a lone "\r" is no line break),
    a blank or non-field line ends the run."""
    text = data.decode("utf-8")  # strict check
    if text.startswith("\ufeff"):
        text = text[1:]
    lines = text.split("\n")
    count = 0
    while count < len(lines) and lines[count].strip() and _is_field(lines[count]):
        count += 1
    if not count:
        return None
    head_length = sum(len(line) + 1 for line in lines[:count])
    head, rest = text[:head_length], text[head_length:]
    newline = "\r\n" if lines[0].endswith("\r") else "\n"
    if not head.endswith("\n"):  # header is the whole file and lacks a final newline
        head += newline
    return f"---{newline}{head}---{newline}{rest}".encode("utf-8")


def _write_atomic(path: Path, content: bytes) -> None:
    """Replace `path` by `content` through a temporary file in the same folder and os.replace, so
    an abort leaves either the old or the new file, never a cut-off one; the file mode is kept."""
    temp = path.with_name(f".{path.name}.migrating")
    try:
        temp.write_bytes(content)
        shutil.copymode(path, temp)
        os.replace(temp, path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def _candidates(root: Path) -> list[Path]:
    """Every *.md file the migration looks at, sorted by project-relative path."""
    work = root / WORK_DIR
    found: list[Path] = []
    for name in SCAN_DIRS:
        base = work / name
        if not base.is_dir():
            continue
        for path in base.rglob("*.md"):
            if not path.is_file() or _is_readme(path.name) or _is_legacy(path.relative_to(work)):
                continue
            if _has_link(path, base):  # a link (file, or folder on the way) is not rewritten through
                continue
            found.append(path)
    return sorted(found, key=lambda p: p.relative_to(root).as_posix())


def _scan(root: Path) -> tuple[list[tuple[Path, bytes]], list[str]]:
    """(file, new content) for every file to convert, and the paths of non-UTF-8 files left alone."""
    todo: list[tuple[Path, bytes]] = []
    skipped: list[str] = []
    for path in _candidates(root):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        try:
            new = _convert(data)
        except UnicodeDecodeError:
            skipped.append(path.relative_to(root).as_posix())
            continue
        if new is not None:
            todo.append((path, new))
    return todo, skipped


def _names(names: list[str]) -> str:
    shown = ", ".join(names[:LIST_LIMIT])
    return shown + (f", ... and {len(names) - LIST_LIMIT} more" if len(names) > LIST_LIMIT else "")


def plan(root: Path) -> str:
    """Describes what apply() would do, writes nothing."""
    todo, skipped = _scan(root)
    parts: list[str] = []
    if todo:
        parts.append(f"would convert {len(todo)} work entr(y/ies) to frontmatter: "
                     + _names([p.relative_to(root).as_posix() for p, _ in todo]))
    if skipped:
        parts.append("would skip (not valid UTF-8): " + _names(skipped))
    return "; ".join(parts) if parts else "no work entry in the old header form — nothing to do"


def apply(root: Path) -> tuple[str, list[str]]:
    """Converts the entries as described above. Returns (description, touched project-relative
    paths)."""
    todo, skipped = _scan(root)
    touched: list[Path] = []
    for path, new in todo:
        _write_atomic(path, new)
        touched.append(path)
    parts: list[str] = []
    rels = [p.relative_to(root).as_posix() for p in touched]
    if touched:
        parts.append(f"converted {len(touched)} work entr(y/ies) to frontmatter: " + _names(rels))
    if skipped:
        parts.append("left alone (not valid UTF-8): " + _names(skipped))
    description = "; ".join(parts) if parts else "no work entry in the old header form — nothing to do"
    return description, rels
