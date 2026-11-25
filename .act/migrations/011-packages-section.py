#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Adds the section `## Packages` to docs/ai/config.md of a project made before packages existed. Without
#          it `packages.py settings <id> <key>=<value>` refuses with "no section `## Packages`", because the answers
#          of a package live in a block of that section. What this does (docs/ai/config.md is read and written as
#          bytes, so encoding, BOM and the file's line ending, LF or CRLF, stay as they were):
#            - A heading that `config.py` takes for the section (`## Packages`, spaces around allowed) is there, or
#              the file does not exist: nothing to do, and the description says so. The file is not touched.
#            - Else the section of the skeleton (heading, table with `packages-unverified`, `packages-sources` and
#              `packages-update` and their defaults, the three paragraphs that explain them) is inserted, a literal
#              copy below, directly before the heading `## Archive` when the file has one outside a code fence (that
#              is its place in the skeleton), else at the end of the file after one blank line. Its lines end like the
#              file's own (the first line ending found; LF in a file without any).
#          Everything else stays byte for byte; a second run finds the section and does nothing. No other file is
#          touched. The file is replaced through a temporary file created exclusively next to it (a name of its own,
#          gone on every path); when docs/ai/config.md, or a folder on its way, is a symbolic link or a Windows
#          junction, nothing is written: the description says "skipped: ... is a link or junction".
#          Why a migration and not a step of update.py: it edits a file the project owns, so update.py lists it in
#          its plan and prints its plan line before applying it. `packages.py settings` keeps refusing a config.md
#          without the section; it is the migration that adds it. init records every migration it ships as done for
#          a new project, whose config already has the section. plan() only reads, never writes.
#
# Contract (.act/scripts/update.py step 8): plan(root) -> str, apply(root) -> (str, list[str]) of
# project-relative paths (posix separators) touched. Stdlib only; the link test lives in the sibling file _links.py
# (loaded below, shipped together with this file).

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

CONFIG = "docs/ai/config.md"
BOM = b"\xef\xbb\xbf"
# The same test as config.py PACKAGES_SECTION_RE, applied to a stripped line.
_PACKAGES_RE = re.compile(r"^##\s+Packages\s*$")
_ARCHIVE_RE = re.compile(r"^##\s+Archive\s*$")
_LINE_RE = re.compile(rb"[^\r\n]*(?:\r\n|\n|\r)|[^\r\n]+")
_FENCE_RE = re.compile(rb"[ \t]*(`{3,}|~{3,})")

# The skeleton's section, with LF; a blank line follows it so that the next heading stands apart.
SECTION = r"""## Packages

| Key | Value |
| :--- | :--- |
| `packages-unverified` | block |
| `packages-sources` | https://github.com/wrufeger/act-packages/releases/latest/download/ |
| `packages-update` | ask |

`packages-unverified`: `block` \| `scan` \| `allow`. What `python .act/scripts/packages.py` does with a package that
carries no valid signature of the template author (a folder, a zip without its `.sig` file, or no signing key under
`.act/`): `block` (the default) refuses it, `scan` shows the findings of the static scan in red before it asks, `allow`
asks with a warning only. A package with a valid signature goes in every mode, a signature that does not match is
refused in every mode; the plan, the diff and your yes apply in every mode. Details: `.act/formats/package.md`.

`packages-sources`: a comma-separated list of places `packages.py fetch <id>` looks in, in this order: an `https://`
address or a local folder, each holding an `index.json`; a pipe character inside the value gets a backslash in front
of it.

`packages-update`: `ask` \| `off`. `ask` (the default): after a template update `act-update` shows the diff of every
installed package whose source has a newer version and asks; `off` leaves packages alone.
"""

NOTHING = f"{CONFIG} has a section `## Packages` or does not exist — nothing to do"


def _read(root: Path) -> bytes | None:
    try:
        return (root / CONFIG).read_bytes()
    except OSError:
        return None


def _body(line: bytes) -> bytes:
    return line.rstrip(b"\r\n")


def _headings(data: bytes) -> tuple[bool, int | None, int]:
    """(has the Packages heading, byte offset of the Archive heading line outside a code fence or None, the
    file's line ending as bytes)."""
    has = False
    archive: int | None = None
    eol = b""
    fence: bytes | None = None
    offset = 0
    for index, line in enumerate(_LINE_RE.findall(data)):
        text = _body(line)[len(BOM):] if index == 0 and line.startswith(BOM) else _body(line)
        start = offset + (len(BOM) if index == 0 and line.startswith(BOM) else 0)
        offset += len(line)
        if not eol and line != text and line[len(_body(line)):]:
            eol = line[len(_body(line)):]
        marker = _FENCE_RE.match(text)
        if fence is not None:
            if marker and marker.group(1)[:1] == fence[:1] and len(marker.group(1)) >= len(fence) \
                    and not text[marker.end():].strip():
                fence = None
            continue
        if marker:
            fence = marker.group(1)
            continue
        words = text.decode("utf-8", "replace").strip()
        if _PACKAGES_RE.match(words):
            has = True
        elif archive is None and _ARCHIVE_RE.match(words):
            archive = start
    return has, archive, eol or b"\n"


def _insert(data: bytes) -> bytes | None:
    """The data with the section added, or None when there is nothing to add."""
    has, archive, eol = _headings(data)
    if has:
        return None
    block = SECTION.encode("utf-8").replace(b"\n", eol)
    if archive is not None:
        return data[:archive] + block + eol + data[archive:]
    lines = _LINE_RE.findall(data)
    head = data
    if data and not data.endswith((b"\n", b"\r")):
        head += eol
    if lines and _body(lines[-1]).strip():
        head += eol
    return head + block


def _describe(data: bytes | None) -> str:
    if data is None or _insert(data) is None:
        return NOTHING
    _has, archive, _eol = _headings(data)
    where = "before `## Archive`" if archive is not None else "at the end"
    return (f"would add the section `## Packages` to {CONFIG} ({where}): its table with `packages-unverified`, "
            "`packages-sources` and `packages-update` at their defaults, so `packages.py settings` can keep a package's "
            "answers there")


def _skipped(root: Path) -> str:
    """The description of a skipped file when `docs/ai/config.md` (or a folder on its way) is a link or junction,
    else "": nothing is written through a link."""
    problem = _LINKS.link_problem(root, root / CONFIG)
    if not problem:
        return ""
    return f"skipped: {problem} — nothing is written through it, {CONFIG} is left as it is"


def plan(root: Path) -> str:
    """Describes what apply() would do, writes nothing."""
    return _skipped(root) or _describe(_read(root))


def apply(root: Path) -> tuple[str, list[str]]:
    """Adds the section described above. Returns (description, touched project-relative paths)."""
    skipped = _skipped(root)
    if skipped:
        return skipped, []
    data = _read(root)
    if data is None:
        return _describe(None), []
    new = _insert(data)
    if new is None:
        return _describe(data), []
    skipped = _skipped(root)  # once more right before the write
    if skipped:
        return skipped, []
    description = _describe(data).replace("would add", "added")
    _LINKS.write_replace(root / CONFIG, new)
    return description, [CONFIG]


if __name__ == "__main__":
    project = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    print(plan(project))
