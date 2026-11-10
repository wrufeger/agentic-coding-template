#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Retires the config key `done-entries`. Finished tasks, backlog items and inbox entries are now always
#          moved to docs/ai/work/archive/ by `entries.py archive` and folded into monthly files by `act-compact`,
#          which is what `done-entries: keep` did; the value `delete` no longer exists. What this does to
#          docs/ai/config.md (read and written as bytes, so encoding, BOM and every line's own ending, LF or CRLF,
#          stay as they were; only the parts below are cut out):
#            - The table row `done-entries`, whatever its value (`delete`, `keep`, empty, unknown); also when
#              line 1 starts with a UTF-8 BOM (the BOM stays).
#            - The explanation paragraph of the old skeleton: a line starting with `` `done-entries`: `` (the key is
#              never translated, the prose may be in any language) outside a code fence, through the last non-blank
#              line before the next blank line or the end of the file, plus the one blank line after it. That prose
#              told the assistant that the default deletes entries and to run `entries.py purge --all`.
#            - The sentence "With `done-entries: delete` only the journal folder counts and is merged
#              (`archive/ledger-<YYYY-MM>.md`)." of the archive paragraph, also when a line break stands at any of
#              its spaces: the sentence and the space before it go, a line left empty by that goes too, the rest
#              of the paragraph stays. A match inside a code fence is left alone.
#            Everything else (other rows, other text) stays byte for byte; a second run finds nothing.
#          A project that had `delete` (the default under Git) archives finished entries from now on instead
#          of deleting them, and `act-compact` folds the archive's files. Entries it deleted earlier stay in
#          Git history; nothing is reconstructed. A leftover `purge: after-commit` field in an archived file
#          stays as it is, `entries.py purge` is retired and does nothing.
#          Nothing found, or no docs/ai/config.md: nothing to do, and the description says so. No other file is
#          touched. The file is replaced through a temporary file created exclusively next to it (a name of its
#          own, gone on every path); when docs/ai/config.md, or a folder on its way, is a symbolic link or a
#          Windows junction, nothing is written: the description says "skipped: ... is a link or junction".
#          Why a migration and not a step of update.py: it edits a file the project owns, so update.py lists it in
#          its plan (a `008-...` line under `[8/10]`) and prints its plan line, which tells a `delete` project what changes,
#          before applying it. A row left behind by a project that skips the migration is ignored, never an
#          error. init records every migration it ships as done for a new project, whose config has no such row.
#          plan() only reads, never writes; it names each part it would remove, apply() reports the same.
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
_ROW_RE = re.compile(rb"[ \t]*\|[ \t]*`?done-entries`?[ \t]*\|([^\r\n]*)")
_VALUE_RE = re.compile(rb"^\s*`?([^|`]*?)`?\s*(?:\|.*)?$")
_LINE_RE = re.compile(rb"[^\r\n]*(?:\r\n|\n|\r)|[^\r\n]+")
_FENCE_RE = re.compile(rb"[ \t]*(`{3,}|~{3,})")
_PARAGRAPH_START = b"`done-entries`:"
SENTENCE = "With `done-entries: delete` only the journal folder counts and is merged (`archive/ledger-<YYYY-MM>.md`)."
# The sentence with an optional space before it; each of its spaces may also be one line ending.
_SENTENCE_RE = re.compile(
    rb"( )?(?<![A-Za-z0-9])" + rb"(?: |\r\n|\n|\r)".join(re.escape(w.encode()) for w in SENTENCE.split(" ")))


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


def _strip_lines(data: bytes) -> tuple[bytes, list[str], list[bytes]]:
    """Cuts the row(s) and the explanation paragraph(s). Returns (new data, parts, row value cells)."""
    lines = _LINE_RE.findall(data)
    out: list[bytes] = []
    parts: list[str] = []
    cells: list[bytes] = []
    fence: bytes | None = None
    i = 0
    while i < len(lines):
        line = lines[i]
        lead = BOM if i == 0 and line.startswith(BOM) else b""
        text = _body(line)[len(lead):]
        if fence is not None or _FENCE_RE.match(text):
            fence = _fence_after(line[len(lead):], fence)
            out.append(line)
            i += 1
            continue
        row = _ROW_RE.fullmatch(text)
        if row:
            parts.append("the `done-entries` row")
            cells.append(row.group(1))
            out.append(lead)
            i += 1
        elif text.startswith(_PARAGRAPH_START):
            end = i
            while end + 1 < len(lines) and _body(lines[end + 1]).strip():
                end += 1
            first = " ".join(text.decode("utf-8", "replace").split()[:6])
            parts.append(f"the explanation paragraph starting `{first} ...`")
            out.append(lead)
            i = end + 1
            if i < len(lines) and not _body(lines[i]).strip():
                i += 1
        else:
            out.append(line)
            i += 1
    return b"".join(out), parts, cells


def _strip_sentence(data: bytes) -> tuple[bytes, int]:
    """Cuts the retired sentence outside code fences. Returns (new data, number of cuts)."""
    fenced: list[tuple[int, int]] = []
    fence: bytes | None = None
    offset = 0
    opened = 0
    for line in _LINE_RE.findall(data):
        before = fence
        fence = _fence_after(line, fence)
        if before is None and fence is not None:
            opened = offset
        if before is not None and fence is None:
            fenced.append((opened, offset + len(line)))
        offset += len(line)
    if fence is not None:
        fenced.append((opened, len(data)))
    matches = [m for m in _SENTENCE_RE.finditer(data) if not any(a <= m.start() < b for a, b in fenced)]
    buf = data
    for m in reversed(matches):
        start, end = m.span()
        if m.group(1) is None and (start == 0 or buf[start - 1:start] in (b"\r", b"\n")) and buf[end:end + 1] == b" ":
            end += 1
        buf = buf[:start] + buf[end:]
        line_start = max(buf.rfind(b"\n", 0, start), buf.rfind(b"\r", 0, start)) + 1
        line = _LINE_RE.match(buf, line_start)
        if line and not _body(line.group(0)).strip(b" \t"):
            buf = buf[:line_start] + buf[line.end():]
    return buf, len(matches)


def _clean(data: bytes) -> tuple[bytes, list[str], list[str]]:
    """The cleaned bytes, the parts removed (for the description) and the lower-cased row values."""
    stripped, parts, cells = _strip_lines(data)
    new, sentences = _strip_sentence(stripped)
    if sentences:
        parts.append("the sentence about `done-entries: delete` in the archive paragraph")
    values = []
    for cell in cells:
        match = _VALUE_RE.match(cell)
        values.append(match.group(1).decode("utf-8", "replace").strip().lower() if match else "")
    return new, parts, values


def _describe(data: bytes | None) -> str:
    nothing = f"no `done-entries` row or prose in {CONFIG} — nothing to do"
    if data is None:
        return nothing
    _new, parts, values = _clean(data)
    if not parts:
        return nothing
    if not values:
        return (f"would remove stale `done-entries` text from {CONFIG}: {'; '.join(parts)}; finished entries are "
                "always archived and folded by `act-compact`")
    if "delete" in values:
        text = (f"would remove the `done-entries` row from {CONFIG} (it is `delete`): finished entries are archived "
                "from now on instead of deleted and `act-compact` folds the archive's files; entries deleted "
                "earlier stay in Git history, nothing is reconstructed")
    else:
        text = (f"would remove the `done-entries` row from {CONFIG} (it is `{values[0] or 'empty'}`): the key is "
                "retired, finished entries are always archived and folded by `act-compact`")
    others = [p for p in parts if not p.startswith("the `done-entries` row")]
    return text + (f"; and would remove {'; '.join(others)}" if others else "")


def _skipped(root: Path) -> str:
    """The description of a skipped file when `docs/ai/config.md` (or a folder on its way) is a link or junction,
    whether or not there is something to remove (as migrations 005 to 007 do), else "": nothing is written
    through a link."""
    problem = _LINKS.link_problem(root, root / CONFIG)
    if not problem:
        return ""
    return f"skipped: {problem} — nothing is written through it, {CONFIG} is left as it is"


def plan(root: Path) -> str:
    """Describes what apply() would do, writes nothing."""
    return _skipped(root) or _describe(_read(root))


def apply(root: Path) -> tuple[str, list[str]]:
    """Removes the parts described above. Returns (description, touched project-relative paths)."""
    skipped = _skipped(root)
    if skipped:
        return skipped, []
    data = _read(root)
    if data is None:
        return _describe(None), []
    new, parts, _values = _clean(data)
    if not parts or new == data:
        return _describe(data), []
    skipped = _skipped(root)  # once more right before the write
    if skipped:
        return skipped, []
    description = _describe(data).replace("would remove", "removed")
    _LINKS.write_replace(root / CONFIG, new)
    return description, [CONFIG]


if __name__ == "__main__":
    project = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    print(plan(project))
