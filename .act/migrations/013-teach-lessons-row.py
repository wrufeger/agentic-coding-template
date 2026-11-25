#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Moves the config key `teach-lessons` out of the template into the package `teach`: the key is no longer a
#          row of docs/ai/config.md, the package asks for it. What this does to docs/ai/config.md (read and written
#          as bytes, so encoding, BOM and every line's own ending, LF or CRLF, stay as they were; only the parts
#          below are cut out):
#            - The table row `teach-lessons`, whatever its value (`local`, `docs`, empty, unknown); also when line 1
#              starts with a UTF-8 BOM (the BOM stays at the start of the file, also when the first section goes).
#            - The explanation paragraph of the old skeleton: a line starting with `` `teach-lessons`: `` (the key
#              is never translated, the prose may be in any language) outside a code fence, through the last
#              non-blank line before the next blank line, the next heading line (`#` to `######`) or the end of the
#              file, plus the one blank line after it.
#            - The section that held them (its `## ` heading, in any language, to the next one or the end of the
#              file), when nothing but the table head (header and separator line) and blank lines is left in it:
#              the whole section goes. With another row or any other text left in it, the section stays. When the
#              cut reaches the end of the file, the blank lines before it go too, so the file ends the way it ended
#              before: one final line ending (or none, when it had none), no extra blank line.
#            Lines inside a package settings block (`<!-- act:package-settings <id> -->` to
#            `<!-- /act:package-settings <id> -->`) are never touched: a row `teach-lessons` there belongs to the
#            package, which answers its own question in that block. Everything else (other rows, other text) stays
#            byte for byte; a second run finds nothing.
#          When the old row held a value other than `local`, the text names it together with the command
#          `python .act/scripts/packages.py settings teach teach-lessons=<value>` that gives the package the same
#          answer once it is installed (the package default is `local`, so a row `local` needs nothing). Offering the
#          package is the job of the migration `012-teach-package`, which writes nothing; both can run in one update.
#          Nothing found, or no docs/ai/config.md: nothing to do, and the text says so. No other file is touched. The
#          file is replaced through a temporary file created exclusively next to it (a name of its own, gone on every
#          path); when docs/ai/config.md, or a folder on its way, is a symbolic link or a Windows junction, nothing is
#          written: the text says "skipped: ... is a link or junction".
#          Why a migration and not a step of update.py: it edits a file the project owns, so update.py lists it in its
#          plan and prints its plan line, which tells the owner what changes and which value to carry over, before
#          applying it. A row left behind by a project that skips the migration is ignored, never an error. init
#          records every migration it ships as done for a new project, whose config has no such row. plan() only
#          reads, never writes; it says "would remove", apply() reports the same in the past tense.
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
# One table row whose first cell is the key (with or without backticks), without its line ending.
_ROW_RE = re.compile(rb"[ \t]*\|[ \t]*`?teach-lessons`?[ \t]*\|([^\r\n]*)")
_VALUE_RE = re.compile(rb"^\s*`?([^|`]*?)`?\s*(?:\|.*)?$")
_LINE_RE = re.compile(rb"[^\r\n]*(?:\r\n|\n|\r)|[^\r\n]+")
_FENCE_RE = re.compile(rb"[ \t]*(`{3,}|~{3,})")
_PARAGRAPH_START = b"`teach-lessons`:"
_HEADING_RE = re.compile(rb"##[ \t]+\S")
_ANY_HEADING_RE = re.compile(rb"#{1,6}[ \t]+\S")
_SEPARATOR_RE = re.compile(rb"\|?[ \t:|-]*-[ \t:|-]*")
# The block a package's settings rows sit in (the same lines `config.py` reads).
_SETTINGS_MARK_RE = re.compile(rb"^<!--\s*act:package-settings\s+([a-z][a-z0-9-]*)\s*-->$")
_SETTINGS_END_RE = re.compile(rb"^<!--\s*/act:package-settings\s+([a-z][a-z0-9-]*)\s*-->$")

NOTHING = f"no row `teach-lessons` and no explanation paragraph of it in {CONFIG} — nothing to remove"


def _read(root: Path) -> bytes | None:
    try:
        return (root / CONFIG).read_bytes()
    except OSError:
        return None


def _body(line: bytes) -> bytes:
    return line.rstrip(b"\r\n")


def _fence_after(line: bytes, fence: bytes | None) -> bytes | None:
    """The fence state after `line`: the opening marker while inside a fence, else None."""
    text = _body(line)
    found = _FENCE_RE.match(text)
    if fence is None:
        return found.group(1) if found else None
    if found and found.group(1)[:1] == fence[:1] and len(found.group(1)) >= len(fence) \
            and not text[found.end():].strip():
        return None
    return fence


def _emptied_sections(out: list[bytes], heads: list[int], marks: list[int]) -> list[tuple[int, int]]:
    """The (start, end) line ranges of the sections around the cuts that hold only the table head (header and
    separator line) and blank lines now, heading text not looked at. `heads` are the heading lines of `out` outside
    a code fence and a settings block, `marks` the places in `out` where something was cut."""
    ranges: set[tuple[int, int]] = set()
    for mark in marks:
        before = [n for n in heads if n < mark]
        if not before:
            continue
        start = before[-1]
        end = next((n for n in heads if n >= mark), len(out))
        table = [text for text in (_body(line).strip() for line in out[start + 1:end]) if text]
        if len(table) == 2 and table[0].startswith(b"|") and table[1].startswith(b"|") \
                and _SEPARATOR_RE.fullmatch(table[1]):
            ranges.add((start, end))
    return sorted(ranges)


def _strip_lines(data: bytes) -> tuple[bytes, list[str], list[bytes]]:
    """Cuts the row(s) and the explanation paragraph(s). Returns (new data, parts, row value cells)."""
    bom = data.startswith(BOM)
    lines = _LINE_RE.findall(data[len(BOM):] if bom else data)
    out: list[bytes] = []
    heads: list[int] = []
    marks: list[int] = []
    parts: list[str] = []
    cells: list[bytes] = []
    fence: bytes | None = None
    block: bytes | None = None
    tail_cut = False
    i = 0
    while i < len(lines):
        line = lines[i]
        text = _body(line)
        if fence is not None or _FENCE_RE.match(text):
            fence = _fence_after(line, fence)
            out.append(line)
            i += 1
            continue
        if block is not None:
            closed = _SETTINGS_END_RE.match(text.strip())
            if closed and closed.group(1) == block:
                block = None
            out.append(line)
            i += 1
            continue
        opened = _SETTINGS_MARK_RE.match(text.strip())
        if opened:
            block = opened.group(1)
            out.append(line)
            i += 1
            continue
        row = _ROW_RE.fullmatch(text)
        if row:
            parts.append("the `teach-lessons` row")
            cells.append(row.group(1))
            marks.append(len(out))
            i += 1
            tail_cut = i >= len(lines)
        elif text.startswith(_PARAGRAPH_START):
            end = i
            while end + 1 < len(lines) and _body(lines[end + 1]).strip() \
                    and not _ANY_HEADING_RE.match(_body(lines[end + 1])):
                end += 1
            parts.append("the explanation paragraph of the setting `teach-lessons`")
            marks.append(len(out))
            i = end + 1
            if i < len(lines) and not _body(lines[i]).strip():
                i += 1
            tail_cut = i >= len(lines)
        else:
            if _HEADING_RE.match(text):
                heads.append(len(out))
            out.append(line)
            i += 1
    emptied = _emptied_sections(out, heads, marks)
    if emptied:
        names = [f"`{_body(out[start]).decode('utf-8', 'replace').strip()}`" for start, _end in emptied]
        parts.append(f"the emptied section {', '.join(names)}")
        tail_cut = tail_cut or any(end == len(out) for _start, end in emptied)
    drop = {n for start, end in emptied for n in range(start, end)}
    kept = [line for n, line in enumerate(out) if n not in drop]
    if tail_cut and parts:
        while kept and not _body(kept[-1]).strip():
            kept.pop()
        if kept and not lines[-1].endswith((b"\n", b"\r")):
            kept[-1] = _body(kept[-1])
    return (BOM if bom else b"") + b"".join(kept), parts, cells


def _clean(data: bytes | None) -> tuple[bytes, list[str], str]:
    """The cleaned bytes, the parts removed and the old value ("" when there was no row; the last row wins)."""
    if data is None:
        return b"", [], ""
    new, parts, cells = _strip_lines(data)
    value = ""
    for cell in cells:
        match = _VALUE_RE.match(cell)
        value = match.group(1).decode("utf-8", "replace").strip().lower() if match else ""
    return new, parts, value


def _skipped(root: Path) -> str:
    """The description of a skipped file when `docs/ai/config.md` (or a folder on its way) is a link or junction,
    else "": nothing is written through a link."""
    problem = _LINKS.link_problem(root, root / CONFIG)
    if not problem:
        return ""
    return f"skipped: {problem} — nothing is written through it, {CONFIG} is left as it is"


def _describe(root: Path, data: bytes | None, applying: bool) -> str:
    """The text for the config as it is in `data` (read before any write)."""
    _new, parts, value = _clean(data)
    if not parts:
        return NOTHING
    skipped = _skipped(root)
    if skipped:
        return skipped
    text = f"{'removed' if applying else 'would remove'} {'; '.join(parts)} from {CONFIG}"
    if value:
        text += f" (the old value is `{value}`)"
    text += ": the setting moved into the package `teach`"
    if value == "local":
        text += ", whose default is `local` too"
    elif value:
        text += (f". To keep `{value}`, run `python .act/scripts/packages.py settings teach teach-lessons={value}` "
                 f"once the package is installed (`/act-packages add teach`)")
    return text


def plan(root: Path) -> str:
    """Describes what apply() would do, writes nothing."""
    return _describe(root, _read(root), False)


def apply(root: Path) -> tuple[str, list[str]]:
    """Removes the row and its paragraph. Returns (description, touched project-relative paths)."""
    data = _read(root)
    new, parts, _value = _clean(data)
    if data is None or not parts or new == data or _skipped(root):
        return _describe(root, data, True), []
    description = _describe(root, data, True)
    _LINKS.write_replace(root / CONFIG, new)
    return description, [CONFIG]


if __name__ == "__main__":
    project = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    print(plan(project))
