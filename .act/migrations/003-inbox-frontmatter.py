#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Moves the entries in docs/ai/inbox/ from plain header lines to YAML frontmatter. An entry
#          used to start with "key: value" lines (id, kind, for, status, created ...) straight at the
#          top of the file; from now on the scripts write them between two "---" lines, so any
#          Markdown or YAML-aware tool sees them as metadata:
#              id: U<n>                  ---
#              kind: todo                id: U<n>
#              status: open      ->      kind: todo
#                                        status: open
#              # Title                   ---
#
#                                        # Title
#          What this does (the same in "solo" and "team" mode):
#            - Candidates are the "*.md" files directly in docs/ai/inbox/, except README.md (any
#              letter case). A file is rewritten only when its first line (after an optional UTF-8
#              BOM) is a header field, i.e. matches "<name>: ..." like the header readers expect.
#            - The leading run of header lines is kept unchanged, wrapped in a "---" line above and
#              below; everything after it stays byte for byte, so a "---" divider further down (a
#              reply block) is not touched. The line ending of the header lines (LF or CRLF) is
#              used for the two new "---" lines.
#            - A leading BOM is dropped (the opening "---" must be the very first thing in the file,
#              or the frontmatter would not be recognized), as the todo-id migration does.
#            - The header is found the way actlib.split_header finds it: lines end at LF only (a lone
#              CR is no line break) and a field is matched with the readers' own pattern.
#            - Each file is replaced through a temporary file and os.replace, so an abort never leaves
#              a cut-off file; a symbolic link is left alone instead of being written through.
#            - Left byte-identical: a file that already starts with "---", a file without a header,
#              the README, the archive (docs/ai/work/archive/ is never rewritten) and every other
#              folder. A file that is not valid UTF-8 is reported and left as it is.
#          Migrations 001 and 002 write and edit the old-form headers; update.py runs due migrations
#          in sorted order, so they run before this one when they are due in the same update.
#          Re-running apply() changes nothing (a converted file starts with "---"); plan() only
#          reads, never writes.
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

INBOX_DIR = "docs/ai/inbox"
LIST_LIMIT = 10  # names listed in plan()/apply() descriptions before "... and N more"

_BOM = b"\xef\xbb\xbf"
_FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z-]*:\s")  # same pattern as the header readers' (str, so \s also matches NBSP)


def _is_readme(name: str) -> bool:
    return name.lower() == "readme.md"


def _is_field(line: str) -> bool:
    # as the header readers see it: lines split at "\n" only, a trailing "\r" is not content, and
    # "for:" with no value is not a field
    return bool(_FIELD_RE.match(line.rstrip("\r")))


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


def _scan(root: Path) -> tuple[list[tuple[Path, bytes]], list[str]]:
    """(file, new content) for every file to convert, and the names of non-UTF-8 files left alone."""
    inbox = root / INBOX_DIR
    todo: list[tuple[Path, bytes]] = []
    skipped: list[str] = []
    if not inbox.is_dir():
        return todo, skipped
    for path in sorted(inbox.glob("*.md"), key=lambda p: p.name):
        if path.is_symlink() or not path.is_file() or _is_readme(path.name):  # a link is not rewritten through
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        try:
            new = _convert(data)
        except UnicodeDecodeError:
            skipped.append(path.name)
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
        parts.append(f"would convert {len(todo)} inbox entr(y/ies) to frontmatter: "
                     + _names([p.name for p, _ in todo]))
    if skipped:
        parts.append("would skip (not valid UTF-8): " + _names(skipped))
    return "; ".join(parts) if parts else "no inbox entry in the old header form — nothing to do"


def apply(root: Path) -> tuple[str, list[str]]:
    """Converts the inbox entries as described above. Returns (description, touched
    project-relative paths)."""
    todo, skipped = _scan(root)
    touched: list[Path] = []
    for path, new in todo:
        _write_atomic(path, new)
        touched.append(path)
    parts: list[str] = []
    if touched:
        parts.append(f"converted {len(touched)} inbox entr(y/ies) to frontmatter: "
                     + _names([p.name for p in touched]))
    if skipped:
        parts.append("left alone (not valid UTF-8): " + _names(skipped))
    description = "; ".join(parts) if parts else "no inbox entry in the old header form — nothing to do"
    return description, [p.relative_to(root).as_posix() for p in touched]
