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
#            - Each file is replaced through a temporary file (created exclusively, with a name of its own, in
#              the file's folder) and os.replace, so an abort never leaves a cut-off file and the temporary
#              file is gone on every path. Nothing is written through a symbolic link or a Windows junction:
#              a linked entry, or a linked folder anywhere from docs/ai/work down to it, is left alone and
#              named in the description ("skipped: ... is a link or junction", each link once).
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
# reimplemented below, and the link test lives in the sibling file _links.py (loaded below, shipped
# together with this file).

from __future__ import annotations

import fnmatch
import importlib.util
import os
import re
from pathlib import Path
from typing import Optional


def _load_links():
    """The sibling _links.py (link test, exclusive temporary file), loaded by file name."""
    spec = importlib.util.spec_from_file_location("_act_migration_links", Path(__file__).with_name("_links.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_LINKS = _load_links()

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
    """Replace `path` by `content` through a temporary file in the same folder (exclusively created, a
    name of its own) and os.replace, so an abort leaves either the old or the new file, never a
    cut-off one; the file mode is kept. The temporary file is gone on every path."""
    _LINKS.write_replace(path, content)


def _walk(root: Path) -> tuple[list[Path], list[str]]:
    """(every *.md file the migration looks at, sorted by project-relative path; why linked ones are left
    alone, each link once). A file counts as linked when the file or any folder from docs/ai/work down to it
    is a link or junction, or its real path leaves the project."""
    work = root / WORK_DIR
    found: list[Path] = []
    linked: list[str] = []
    check = _LINKS.LinkCheck(root)  # remembers the folders: the archive holds thousands of files in few folders
    for name in SCAN_DIRS:
        base = work / name
        problem = check.problem(base)
        if problem:
            if problem not in linked:
                linked.append(problem)
            continue
        if not base.is_dir():
            continue
        # os.walk, not rglob: rglob does not descend into a symlinked folder on POSIX (and so never names it),
        # while os.walk lists a linked folder (a junction too) among the subfolders, where it is tested and
        # pruned: its content is neither looked at nor written.
        for dirpath, dirnames, filenames in os.walk(base):
            here = Path(dirpath)
            kept: list[str] = []
            for sub in sorted(dirnames):
                if _is_legacy((here / sub).relative_to(work)):
                    continue  # old material: not descended into, as its files are not candidates
                problem = check.problem(here / sub)
                if problem:
                    if problem not in linked:
                        linked.append(problem)
                    continue
                kept.append(sub)
            dirnames[:] = kept
            for filename in filenames:
                path = here / filename
                if not fnmatch.fnmatch(filename, "*.md") or _is_readme(filename) \
                        or _is_legacy(path.relative_to(work)):
                    continue
                if not path.is_file() and not path.is_symlink():
                    continue
                problem = check.problem(path)
                if problem:  # a linked file is not rewritten through
                    if problem not in linked:
                        linked.append(problem)
                    continue
                found.append(path)
    return sorted(found, key=lambda p: p.relative_to(root).as_posix()), linked


def _candidates(root: Path) -> list[Path]:
    """Every *.md file the migration looks at, sorted by project-relative path."""
    return _walk(root)[0]


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
    if _walk(root)[1]:
        parts.append("skipped: " + _names(_walk(root)[1]))
    return "; ".join(parts) if parts else "no work entry in the old header form — nothing to do"


def apply(root: Path) -> tuple[str, list[str]]:
    """Converts the entries as described above. Returns (description, touched project-relative
    paths)."""
    todo, skipped = _scan(root)
    touched: list[Path] = []
    linked = _walk(root)[1]
    for path, new in todo:
        problem = _LINKS.link_problem(root, path)  # checked again right before the write
        if problem:
            if problem not in linked:
                linked.append(problem)
            continue
        _write_atomic(path, new)
        touched.append(path)
    parts: list[str] = []
    rels = [p.relative_to(root).as_posix() for p in touched]
    if touched:
        parts.append(f"converted {len(touched)} work entr(y/ies) to frontmatter: " + _names(rels))
    if skipped:
        parts.append("left alone (not valid UTF-8): " + _names(skipped))
    if linked:
        parts.append("skipped: " + _names(linked))
    description = "; ".join(parts) if parts else "no work entry in the old header form — nothing to do"
    return description, rels
