#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Show and set the settings in docs/ai/config.md without a model: the overview of every
#          setting, one setting with its allowed values, default, effect and the explanation from
#          the project's own config.md, or a new value written into exactly one table cell. The
#          mechanical half of `/act-config`: in Claude Code the synchronous UserPromptSubmit hook
#          (.act/hooks/dispatch.py, `--act-check`) answers a prompt that starts with `/act-config`
#          by calling handle() and never sends the prompt to the model; everywhere else the human
#          runs this script. What a key accepts is declared once, in actlib.CONFIG_SCHEMA.
#
# Usage:
#   python .act/scripts/config.py                        # overview of every setting
#   python .act/scripts/config.py feedback               # one setting: value, allowed values, default, effect, notes
#   python .act/scripts/config.py feedback automatic     # set it (every key of config.md, also the Checks)
#   python .act/scripts/config.py --root <path> ...      # another project (default: the one this file belongs to)
#   Words after the key are joined with one space, so `config.py session-name My project` sets
#   "My project"; put `--` before a value that starts with a dash.
#
# Output format:
#   Plain text. Overview: the headings of the project's config.md, under each an indented
#   `key = value` line per row (a long value is cut at 60 characters with `…`), with the source in
#   parentheses where it is not config.md alone (this machine's remembered chat language, the name -
#   never the value - of an environment variable that overrides the key, "row missing, default: ...",
#   "own key, not checked"); the Roles rows follow as `<role> = tier · reasoning · model` (` · <copilot models>`
#   appended when the row's fifth cell, `Copilot`, is filled) and are only shown; the last line says how to look at and set a key. One key: its value and source, the
#   allowed values or format, the default, when a change takes effect, then the notes - the
#   paragraphs under the table that name the key, in the project's own config.md (for a check the
#   Guards column instead). A new value is validated without regard to case against the schema and
#   written in its canonical spelling; free text and keys the schema does not know take any one-line
#   value, a `|` in it is written `\|`. The write replaces only the value cell of that one row; every
#   other byte of the file (BOM, line endings, other cells, the Guards column, the rest) stays.
#   Nothing is committed.
#   Rows of a package's settings (a block between `<!-- act:package-settings <id> -->` marks below the table of
#   § Packages, written by `packages.py settings`) are shown as `setting of package <id>` and never checked against
#   the schema; `set_package_settings`, `drop_package_settings` and `prune_package_settings` change that block (text in,
#   text out).
#   Exit 0 = shown, written, or unchanged; exit 1 = refused (nothing written): unknown key, value not
#   allowed, a value with a line break, the row missing or present more than once, a Roles row, a
#   missing or unreadable config.md.
#
# Limits:
#   An empty value cannot be set by command; set the default by writing its value. The Roles table is
#   shown but changed by hand.

from __future__ import annotations

import argparse
import difflib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import actlib

CONFIG_REL = Path("docs") / "ai" / "config.md"
VALUE_CUT = 60
# Environment variables that replace a key's value for one run (names only are ever shown).
ENV_OVERRIDES = {
    "secret-read": "ACT_SECRET_READ",
    "outside-root": "ACT_OUTSIDE_ROOT",
    "forge": "ACT_FORGE_KIND",
    "forge-host": "ACT_FORGE_API_URL",
}
EFFECT_TEXT = {
    "now": "with the next hook or script call",
    "next-session": "from the next session start (the value is read only then, or from the loaded rules)",
}
_ROLES_MARK_RE = re.compile(r"^\s*<!--\s*act:roles\s*-->\s*$")
# The block a package's settings rows sit in, below the table of § Packages (see "settings of a package" below).
_SETTINGS_MARK_RE = re.compile(r"^<!--\s*act:package-settings\s+([a-z][a-z0-9-]*)\s*-->$")
_SETTINGS_END_RE = re.compile(r"^<!--\s*/act:package-settings\s+([a-z][a-z0-9-]*)\s*-->$")
_UNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")
_USAGE_LINE = ("Show a setting: /act-config <key>  -  set it: /act-config <key> <value>  "
               "(or: python .act/scripts/config.py <key> [<value>])")


@dataclass
class Row:
    """One table row of config.md: where it is, which section it sits in, its cells and the
    character offsets of the unescaped pipes (to replace the value cell and nothing else)."""
    index: int
    section: str
    in_roles: bool
    key: str
    cells: list[str]
    pipes: list[int]
    package: str = ""  # the id of the package whose settings block (act:package-settings) holds the row

    @property
    def value(self) -> str:
        return self.cells[1]


@dataclass
class Doc:
    """config.md split into lines (line break characters stay on the lines) and its table rows."""
    lines: list[str]
    rows: list[Row]


def _parse(text: str) -> Doc:
    """Split `text` at "\\n" only (a "\\r" stays on its line) and collect the table rows with their
    section, skipping header and separator rows by shape, never by wording."""
    lines = text.split("\n")
    rows: list[Row] = []
    section = ""
    in_roles = False
    package = ""
    for index, line in enumerate(lines):
        stripped = line.strip()
        opening = _SETTINGS_MARK_RE.match(stripped)
        if opening:
            package = opening.group(1)
            continue
        if _SETTINGS_END_RE.match(stripped):
            package = ""
            continue
        if stripped.startswith("#"):
            section = stripped.lstrip("#").strip()
            in_roles = section.lower() == "roles"
            continue
        if _ROLES_MARK_RE.match(stripped):
            in_roles = True
            continue
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        pipes = [match.start() for match in _UNESCAPED_PIPE_RE.finditer(line)]
        if len(pipes) < 3 or pipes[-1] != len(line.rstrip()) - 1:
            continue
        cells = [line[pipes[i] + 1:pipes[i + 1]].replace("\\|", "|").strip() for i in range(len(pipes) - 1)]
        key = cells[0].strip("`").strip()
        if not key or (actlib._is_separator_cell(key) and actlib._is_separator_cell(cells[1])):
            continue
        if actlib._is_header_row(lines, index):
            continue
        rows.append(Row(index, section, in_roles, key, cells, pipes, package))
    return Doc(lines, rows)


def _cut(value: str) -> str:
    return value if len(value) <= VALUE_CUT else value[:VALUE_CUT - 1].rstrip() + "…"


def _env_note(key: str) -> str:
    """The environment variable that overrides `key` for a run, if it is set - name only."""
    name = ENV_OVERRIDES.get(key)
    return f"overridden for this run by ${name}" if name and os.environ.get(name) else ""


def _source_notes(row: Row) -> str:
    notes: list[str] = []
    if row.key == "language-chat" and row.value.strip().strip("`").lower() == "auto":
        remembered = actlib.remembered_chat_language()
        if remembered:
            notes.append(f"this machine: {remembered}")
    env = _env_note(row.key)
    if env:
        notes.append(env)
    if row.package:
        notes.append(f"setting of package {row.package}")
    elif not row.in_roles and row.key not in actlib.CONFIG_SCHEMA:
        notes.append("own key, not checked")
    return ", ".join(notes)


def _roles_line(row: Row) -> str:
    """One Roles row as `<role> = tier · reasoning · model`, plus ` · <copilot models>` when the
    fifth cell (`Copilot`) is not empty."""
    tier, reasoning, model = (row.cells + ["", "", ""])[1:4]
    copilot = row.cells[4].strip() if len(row.cells) > 4 else ""
    return f"{row.key} = {tier} · {reasoning} · {model}" + (f" · {copilot}" if copilot else "")


def _overview(doc: Doc) -> str:
    out: list[str] = []
    seen: set[str] = set()
    last_section: Optional[str] = None
    roles_started = False
    for row in doc.rows:
        if row.section != last_section:
            out.append("")
            out.append(row.section or "(no heading)")
            last_section = row.section
        if row.in_roles:
            if not roles_started:
                out.append("  (edit these rows by hand; changed here only for display)")
                roles_started = True
            out.append(f"  {_roles_line(row)}")
            continue
        seen.add(row.key)
        notes = _source_notes(row)
        out.append(f"  {row.key} = {_cut(row.value) or '(empty)'}" + (f"  ({notes})" if notes else ""))
    missing = [entry for key, entry in actlib.CONFIG_SCHEMA.items() if key not in seen]
    if missing:
        out.append("")
        out.append("Rows missing from the file")
        for entry in missing:
            out.append(f"  {entry.key} = (row missing, default: {entry.default or 'none'})")
    out.append("")
    out.append(_USAGE_LINE)
    return "\n".join(out).lstrip("\n")


def _table_end(doc: Doc, row: Row) -> int:
    """Index of the first line after the table that holds `row`."""
    end = row.index + 1
    while end < len(doc.lines):
        stripped = doc.lines[end].strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            break
        end += 1
    return end


def _notes(doc: Doc, row: Row) -> list[str]:
    """The paragraphs under the table of `row`, up to the next heading, that name the key in
    backticks; if none does, those that name no key of that table."""
    end = _table_end(doc, row)
    table_keys = {other.key for other in doc.rows if other.section == row.section and not other.in_roles}
    paragraphs: list[str] = []
    current: list[str] = []
    for line in doc.lines[end:]:
        text = line.rstrip("\r")
        if text.strip().startswith("#"):
            break
        if not text.strip():
            if current:
                paragraphs.append(" ".join(part.strip() for part in current))
                current = []
            continue
        if text.strip().startswith("<!--"):
            continue
        current.append(text)
    if current:
        paragraphs.append(" ".join(part.strip() for part in current))
    named = [p for p in paragraphs if f"`{row.key}`" in p]
    if named:
        return named
    return [p for p in paragraphs if not any(f"`{key}`" in p for key in table_keys)]


# The format behind a key's `pattern`, in words; a key missing here shows its pattern itself.
_FORMAT_TEXT = {
    "language-chat": "a language code such as `de` or `pt-BR`, a language name such as `Deutsch`, or `auto`",
    "language-docs": "a language code such as `de` or `pt-BR`, or a language name such as `Deutsch`",
    "context-hint": "a token count such as `180000`",
    "own-rules-budget": "a character count such as `6000`",
    "task-wait-hours": "a number of hours such as `12` or `0.5`",
    "docs-audit-due": "`<days>d/<commits>c` such as `30d/100c`",
    "feedback-scope": "a comma list of `a`, `b`, `c` such as `a,b,c`",
    "archive-compact": "`<days>d <files>` such as `30d 300`",
    "forge": "`(not set)`",
    "methods": "`none`, or a comma list of method names such as `test-first, spec-first` (list: `.act/methods/README.md`)",
    "exclude": "`none`, or a comma list of template skill, role, rule file and topic names such as "
               "`act-seo, orchestrator/30-cost.md`",
}


def _allowed_text(key: str) -> str:
    entry = actlib.CONFIG_SCHEMA.get(key)
    if entry is None or (entry.values is None and entry.pattern is None):
        return "free text (any one-line value)"
    parts: list[str] = []
    if entry.values:
        parts.append(" | ".join(entry.values))
    if entry.pattern:
        parts.append(_FORMAT_TEXT.get(key, f"format {entry.pattern}"))
    return " or ".join(parts)


def _key_form(doc: Doc, key: str, rows: list[Row]) -> tuple[int, str]:
    entry = actlib.CONFIG_SCHEMA.get(key)
    out: list[str] = []
    row = rows[0] if rows else None
    if row is None:
        assert entry is not None
        out.append(f"{key} = (row missing, default: {entry.default or 'none'})")
        out.append(f"The row is missing from docs/ai/config.md; add it under § {entry.section} "
                   f"(`.act/skeleton/config.md`) before it can be set.")
    else:
        if row.in_roles:
            return 0, f"{_roles_line(row)}  (Roles table: edit by hand)"
        notes = _source_notes(row)
        out.append(f"{key} = {row.value or '(empty)'}" + (f"  ({notes})" if notes else "  (docs/ai/config.md)"))
        if len(rows) > 1:
            out.append("Warning: the row appears more than once, on lines "
                       + ", ".join(str(r.index + 1) for r in rows))
    out.append(f"Allowed: {_allowed_text(key)}")
    if entry is not None:
        out.append(f"Default: {entry.default or 'none stated'}")
        out.append(f"Takes effect: {EFFECT_TEXT[entry.effect]}")
    if row is not None:
        if row.section.lower() == "checks" or (entry is not None and entry.section == "Checks"):
            if len(row.cells) > 2 and _without_mark(row.cells[2]):
                out.append("Guards: " + _without_mark(row.cells[2]))
        elif row.package:
            out.append("")
            out.append(f"A setting of package `{row.package}`, never checked against the template's settings. Set it "
                       f"with: python .act/scripts/packages.py settings {row.package} {key}=<value> (that checks the "
                       "key against the package and refuses a value with `|`).")
        else:
            for paragraph in _notes(doc, row):
                out.append("")
                out.append(paragraph)
    return 0, "\n".join(out)


def _canonical(entry: Optional[actlib.ConfigKey], value: str) -> Optional[str]:
    """The spelling to write for `value`, or None if the schema does not allow it."""
    if entry is None or (entry.values is None and entry.pattern is None):
        return value
    if not actlib.config_value_ok(entry, value):
        return None
    for allowed in entry.values or ():
        if allowed.lower() == value.lower():
            return allowed
    return value


# Checks that only ever note ("never refuses" in the scaffold's Checks table): `block` counts as `warn`.
_NOTE_ONLY_CHECKS = ("update-branch-hint", "update-check", "docs-order", "model-switch", "changelog-length",
                     "commit-hashes")


def _check_effect(key: str, value: str, guards: str) -> str:
    entry = actlib.CONFIG_SCHEMA.get(key)
    if entry is None or entry.section != "Checks" or entry.values is None:
        return ""
    if key == "security-check":
        state = f"is now at level {value}"
    elif key in _NOTE_ONLY_CHECKS and value != "off":
        state = "now notes (it never refuses, so `block` counts as `warn`)"
    else:
        state = {"block": "now blocks", "warn": "now only warns", "off": "is now off"}.get(value, "")
    excerpt = guards if len(guards) <= 110 else guards[:109].rstrip() + "…"
    return f"Check `{key}` {state}." + (f" It guards: {excerpt}" if excerpt else "")


def _set_form(path: Path, doc: Doc, key: str, value: str,
              rows: list[Row]) -> tuple[int, str]:
    entry = actlib.CONFIG_SCHEMA.get(key)
    if re.search(r"[\r\n]", value):
        return 1, "A value must be on one line; nothing was written."
    if not rows:
        if entry is not None:
            return 1, (f"No row `{key}` in docs/ai/config.md; add it under § {entry.section} "
                       "(see `.act/skeleton/config.md`) first. Nothing was written.")
        return 1, f"Unknown setting `{key}`; no such row in docs/ai/config.md. Nothing was written."
    if len(rows) > 1:
        return 1, (f"Row `{key}` appears {len(rows)} times in docs/ai/config.md (lines "
                   + ", ".join(str(r.index + 1) for r in rows) + "); remove the extra ones first. "
                   "Nothing was written.")
    row = rows[0]
    if row.in_roles:
        return 1, f"`{key}` is in the Roles table; edit it by hand. Nothing was written."
    new_value = _canonical(entry, value)
    if new_value is None:
        return 1, (f"`{value}` is not allowed for `{key}`. Allowed: {_allowed_text(key)}. "
                   "Nothing was written.")
    old_value = row.value
    if new_value == old_value:
        return 0, f"`{key}` is already {old_value!r} (unchanged)."
    line = doc.lines[row.index]
    start, end = row.pipes[1] + 1, row.pipes[2]
    cell = line[start:end]
    body = cell.strip()
    lead = cell[:len(cell) - len(cell.lstrip())] if body else cell
    trail = cell[len(cell.rstrip()):] if body else ""
    new_cell = (lead or " ") + new_value.replace("|", "\\|") + (trail or " ")
    doc.lines[row.index] = line[:start] + new_cell + line[end:]
    text = "\n".join(doc.lines)
    try:
        actlib.write_text_atomic(path, text)  # writes "\n" as is, so CRLF lines and a BOM stay byte for byte
    except OSError as error:
        return 1, f"Could not write docs/ai/config.md ({error}). Nothing was written."
    out = [f"`{key}`: {old_value or '(empty)'} -> {new_value}",
           "Written to docs/ai/config.md, so it applies to everyone in the project once it is committed. "
           "Nothing was committed."]
    if entry is not None:
        out.append(f"Takes effect {EFFECT_TEXT[entry.effect]}.")
    env = _env_note(key)
    if env:
        out.append(f"Note: {env}.")
    check = _check_effect(key, new_value, _without_mark(row.cells[2]) if len(row.cells) > 2 else "")
    if check:
        out.append(check)
    return 0, "\n".join(out)


# --- check rows a package sets ------------------------------------------------------------------
#
# A package's `## checks` section sets rows of the Checks table. The row is marked in its third cell (the
# Guards column; the key and value cells stay as every reader expects them) with
#   <!-- act:package <id> was=<value before> now=<value the package set> -->
# `now=` lets the revert tell the package's value from one the owner wrote after it. One package marks a row
# at a time; the owner's own later change of the value is never undone.
_PACKAGE_MARK_RE = re.compile(r"[ \t]*<!--\s*act:package\s+([a-z][a-z0-9-]*)\s+was=(.*?)(?:\s+now=(\S*))?\s*-->")
_PACKAGE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
_PACKAGE_CHECK_VALUES = ("block", "warn", "off")
_NOT_BY_PACKAGE = ("secret-read-allow",)  # rows only the owner writes


class PackageCheckConflict(ValueError):
    """A package's check line cannot be applied: the row is unknown, is not a block/warn/off check, is one only the
    owner writes, or another package already marks it. The message names the row (and that package)."""


def _without_mark(cell: str) -> str:
    return _PACKAGE_MARK_RE.sub("", cell).strip()


def _cell_span(row: Row, index: int) -> tuple[int, int]:
    """Character offsets (start, end) of the raw text of cell `index` in the row's line, between its pipes."""
    return row.pipes[index] + 1, row.pipes[index + 1]


def _set_cell(line: str, row: Row, index: int, content: str) -> str:
    """`line` with the text of cell `index` replaced by `content` (already escaped), the cell's own leading and
    trailing blanks kept, as `_set_form` does for the value cell."""
    start, end = _cell_span(row, index)
    cell = line[start:end]
    body = cell.strip()
    lead = cell[:len(cell) - len(cell.lstrip())] if body else cell
    trail = cell[len(cell.rstrip()):] if body else ""
    return line[:start] + (lead or " ") + content + (trail or " ") + line[end:]


def _row_mark(row: Row) -> Optional[re.Match]:
    return _PACKAGE_MARK_RE.search(row.cells[2]) if len(row.cells) > 2 else None


def apply_package_checks(text: str, package_id: str, checks: "list[tuple[str, str]]") -> str:
    """The text of docs/ai/config.md with each named check row's value set and the row marked for the package
    (`<!-- act:package <id> was=<old> now=<new> -->` at the end of its third cell). Pure: text in, text out; the
    lines keep their line endings and a BOM stays. A row that this package already marks keeps the `was=` it has
    (a second install does not record the package's own value as the owner's), unless the owner changed the row
    since (its value differs from the mark's `now=`): the owner's value then stays and the mark records it, so
    a later revert keeps it. Raises PackageCheckConflict, with
    nothing changed, for an unknown row, a row that is no block/warn/off check, `secret-read-allow` (only the
    owner writes it), a value the row does not take, a row another package marks, a row that is not one row."""
    if not _PACKAGE_ID_RE.match(package_id):
        raise PackageCheckConflict(f"`{package_id}` is not a package id")
    doc = _parse(text)
    wanted: dict[str, str] = {}
    for name, value in checks:
        wanted[name] = value
    edits: list[tuple[Row, str, str]] = []
    for name, value in wanted.items():
        if name in _NOT_BY_PACKAGE:
            raise PackageCheckConflict(f"`{name}` is written by the owner only; a package cannot set it")
        rows = [row for row in doc.rows if row.key == name and not row.in_roles]
        if not rows:
            raise PackageCheckConflict(f"unknown check `{name}`: no such row in docs/ai/config.md")
        if len(rows) > 1:
            raise PackageCheckConflict(f"check `{name}` appears {len(rows)} times in docs/ai/config.md")
        row = rows[0]
        entry = actlib.CONFIG_SCHEMA.get(name)
        if entry is not None:
            takes = tuple(entry.values) if entry.values and set(_PACKAGE_CHECK_VALUES) <= set(entry.values) else ()
            in_checks = entry.section == "Checks"
        else:
            takes = _PACKAGE_CHECK_VALUES if row.value in _PACKAGE_CHECK_VALUES else ()
            in_checks = row.section.lower() == "checks"
        if not takes or not in_checks:
            raise PackageCheckConflict(f"`{name}` is not a block/warn/off check row of docs/ai/config.md")
        if value not in takes:
            raise PackageCheckConflict(f"`{name}` takes {' | '.join(takes)} as a package check, not `{value}`")
        mark = _row_mark(row)
        if mark is not None and mark.group(1) != package_id:
            raise PackageCheckConflict(f"check `{name}` is already set by package `{mark.group(1)}`")
        was = mark.group(2) if mark is not None else row.value
        if mark is not None and mark.group(3) is not None and row.value != mark.group(3):
            # the owner changed the row after this package set it: the owner's value stays, and the mark now records
            # it as both the old and the current value, so that `revert_package_checks` keeps it as well
            was = value = row.value
        if re.search(r"-->|\s+now=|[\r\n]", was):
            raise PackageCheckConflict(f"the value of `{name}` cannot be recorded in a mark")
        edits.append((row, value, was))
    lines = list(doc.lines)
    for row, value, was in edits:
        line = lines[row.index]
        mark_text = f"<!-- act:package {package_id} was={was} now={value} -->".replace("|", "\\|")
        if len(row.cells) < 3:  # a row without a Guards cell gets one
            tail = line[len(line.rstrip()):]
            line = line.rstrip() + f" {mark_text} |" + tail
        else:
            start, end = _cell_span(row, 2)
            cell = _PACKAGE_MARK_RE.sub("", line[start:end])
            body = cell.rstrip()
            line = line[:start] + body + (" " if body.strip() else "") + mark_text + cell[len(body):] + line[end:]
        lines[row.index] = _set_cell(line, _parse(line).rows[0], 1, value.replace("|", "\\|"))
    return "\n".join(lines)


def revert_package_checks(text: str, package_id: str) -> str:
    """The text with every row this package marks given its old value back, when the row still holds the value the
    package set (`now=`); a row the owner changed since keeps the owner's value. The mark goes either way. A mark
    without `now=` keeps the value. Pure: text in, text out; other rows and other packages' marks stay."""
    doc = _parse(text)
    lines = list(doc.lines)
    for row in doc.rows:
        mark = _row_mark(row)
        if mark is None or mark.group(1) != package_id:
            continue
        line = lines[row.index]
        start, end = _cell_span(row, 2)
        cell = _PACKAGE_MARK_RE.sub("", line[start:end], count=1)
        line = line[:start] + cell + line[end:]
        fresh = _parse(line).rows[0]
        now = mark.group(3)
        if now is not None and fresh.value == now:
            line = _set_cell(line, fresh, 1, mark.group(2).replace("|", "\\|"))
        lines[row.index] = line
    return "\n".join(lines)


# --- settings of a package ----------------------------------------------------------------------
#
# A package's `## settings` keys (`<id>-<key>`) are answered by the owner and kept in docs/ai/config.md, § Packages,
# in one block per package below the section's table, a table of its own between two marks:
#   <!-- act:package-settings <id> -->
#   | Key | Value |
#   | :--- | :--- |
#   | `<id>-<key>` | value |
#   <!-- /act:package-settings <id> -->
# The rows are read like every other row (actlib.read_config), shown here as settings of the package and never
# checked against actlib.CONFIG_SCHEMA. A block is inserted with one blank line in front of it and dropped with that
# blank line, so a package that is added and taken out again leaves the file as it was.
PACKAGES_SECTION_RE = re.compile(r"^##\s+Packages\s*$")


class PackageSettingError(ValueError):
    """A package setting cannot be written: a bad value, or § Packages is missing from docs/ai/config.md."""


def _settings_blocks(lines: list[str], package_id: str) -> list[tuple[int, int]]:
    """(index of the opening mark, index of the closing mark) of each complete settings block of the package."""
    found: list[tuple[int, int]] = []
    start: Optional[int] = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        opening = _SETTINGS_MARK_RE.match(stripped)
        if opening:
            start = index if opening.group(1) == package_id else None
            continue
        closing = _SETTINGS_END_RE.match(stripped)
        if closing and start is not None and closing.group(1) == package_id:
            found.append((start, index))
            start = None
    return found


def _block_rows(lines: list[str], start: int, end: int) -> list[tuple[int, str, str]]:
    """(line index, key, value) of the data rows of the block between the marks at `start` and `end`: the table
    lines after its header and separator row."""
    rows: list[tuple[int, str, str]] = []
    seen = 0
    for index in range(start + 1, end):
        stripped = lines[index].strip()
        if not (stripped.startswith("|") and stripped.endswith("|")):
            continue
        seen += 1
        if seen <= 2:
            continue
        cells = actlib.split_table_row(stripped[1:-1])
        if len(cells) >= 2:
            rows.append((index, cells[0].strip("`").strip(), cells[1]))
    return rows


def package_settings(text: str, package_id: str) -> dict[str, str]:
    """The settings rows (key -> value) in the package's block of `text`; empty when there is no block."""
    lines = text.split("\n")
    out: dict[str, str] = {}
    for start, end in _settings_blocks(lines, package_id)[:1]:
        for _, key, value in _block_rows(lines, start, end):
            out[key] = value
    return out


def _insert_after(lines: list[str]) -> int:
    """The index after which a new settings block goes: the last line of the last block in § Packages, else of the
    section's first table. Raises PackageSettingError when there is no such section or no table in it."""
    heading = next((i for i, line in enumerate(lines) if PACKAGES_SECTION_RE.match(line.strip())), None)
    if heading is None:
        raise PackageSettingError("docs/ai/config.md has no section `## Packages` (see `.act/skeleton/config.md`)")
    end = next((i for i in range(heading + 1, len(lines)) if lines[i].strip().startswith("#")), len(lines))
    inside: set[int] = set()
    last_block = None
    for index in range(heading + 1, end):
        closing = _SETTINGS_END_RE.match(lines[index].strip())
        if closing:
            for start, stop in _settings_blocks(lines, closing.group(1)):
                if stop == index:
                    inside.update(range(start, stop + 1))
                    last_block = stop
    if last_block is not None:
        return last_block
    first = next((i for i in range(heading + 1, end)
                  if i not in inside and lines[i].strip().startswith("|") and lines[i].strip().endswith("|")), None)
    if first is None:
        raise PackageSettingError("section `## Packages` of docs/ai/config.md has no table")
    last = first
    while last + 1 < end and lines[last + 1].strip().startswith("|") and lines[last + 1].strip().endswith("|"):
        last += 1
    return last


def _setting_value(key: str, value: str) -> str:
    text = value.strip()
    if "|" in text or re.search(r"[\r\n]", value):
        raise PackageSettingError(f"the value of `{key}` must be one line without `|`")
    return text


def set_package_settings(text: str, package_id: str, values: "dict[str, str]", order: "tuple[str, ...]" = ()) -> str:
    """The text of docs/ai/config.md with the rows `values` (key -> value) written in the package's block: a row that
    is there gets its value cell replaced, a new row goes to the end of the block (new rows in the order of `order`,
    the keys the package declares), a block that is not there is made below the table of § Packages. Values are
    stripped; one with `|` or a line break raises PackageSettingError, as does a text without § Packages. Pure: text
    in, text out; line endings and a BOM stay."""
    if not _PACKAGE_ID_RE.match(package_id):
        raise PackageSettingError(f"`{package_id}` is not a package id")
    clean = {key: _setting_value(key, value) for key, value in values.items()}
    lines = text.split("\n")
    cr = "\r" if lines and lines[0].endswith("\r") else ""
    blocks = _settings_blocks(lines, package_id)
    if len(blocks) > 1:
        raise PackageSettingError(f"docs/ai/config.md holds {len(blocks)} settings blocks of package `{package_id}`; remove the extra ones")
    rank = {key: index for index, key in enumerate(order)}
    if blocks:
        start, end = blocks[0]
        have = {key: index for index, key, _ in _block_rows(lines, start, end)}
        fresh = []
        for key, value in clean.items():
            if key in have:
                line = lines[have[key]]
                pipes = [match.start() for match in _UNESCAPED_PIPE_RE.finditer(line)]
                if len(pipes) >= 3:
                    lines[have[key]] = line[:pipes[1] + 1] + " " + value + " " + line[pipes[2]:]
                    continue
            fresh.append(key)
        for key in sorted(fresh, key=lambda k: rank.get(k, len(rank))):
            lines.insert(end, f"| `{key}` | {clean[key]} |{cr}")
            end += 1
        return "\n".join(lines)
    anchor = _insert_after(lines)
    made = ["", f"<!-- act:package-settings {package_id} -->", "| Key | Value |", "| :--- | :--- |"]
    made += [f"| `{key}` | {clean[key]} |" for key in sorted(clean, key=lambda k: rank.get(k, len(rank)))]
    made.append(f"<!-- /act:package-settings {package_id} -->")
    lines[anchor + 1:anchor + 1] = [line + cr for line in made]
    return "\n".join(lines)


def drop_package_settings(text: str, package_id: str) -> str:
    """The text without the package's settings block and the blank line in front of it (the one
    `set_package_settings` made). Pure; text without a block comes back unchanged."""
    lines = text.split("\n")
    for start, end in reversed(_settings_blocks(lines, package_id)):
        first = start - 1 if start > 0 and not lines[start - 1].strip() else start
        del lines[first:end + 1]
    return "\n".join(lines)


def prune_package_settings(text: str, package_id: str, keep: "tuple[str, ...] | list[str]") -> str:
    """The text with the rows of the package's block whose key is not in `keep` removed (an update whose new version
    no longer declares a key); the whole block goes when no row is left. Pure."""
    lines = text.split("\n")
    for start, end in reversed(_settings_blocks(lines, package_id)):
        rows = _block_rows(lines, start, end)
        stale = [index for index, key, _ in rows if key not in keep]
        if not stale:
            continue
        if len(stale) == len(rows):
            first = start - 1 if start > 0 and not lines[start - 1].strip() else start
            del lines[first:end + 1]
        else:
            for index in reversed(stale):
                del lines[index]
    return "\n".join(lines)


def handle(root: Path, text: str) -> tuple[int, str]:
    """Answer `/act-config <text>` for the project at `root`: the overview (empty text), one key
    (`<key>`) or a write (`<key> <value>`). Returns (exit code, output); exit 1 means refused and
    nothing written."""
    path = root / CONFIG_REL
    if not path.is_file():
        return 1, "docs/ai/config.md not found; nothing to show or set."
    try:
        raw = path.read_bytes()
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        return 1, "docs/ai/config.md is not valid UTF-8; nothing was changed."
    except OSError as error:
        return 1, f"Could not read docs/ai/config.md ({error})."
    doc = _parse(content)
    spec = text.strip()
    if not spec:
        return 0, _overview(doc)
    match = re.match(r"(\S+)\s*(.*)", spec, re.DOTALL)
    assert match is not None
    word, value = match.group(1).strip("`"), match.group(2).strip()
    in_file = {row.key for row in doc.rows}
    key = word if word in actlib.CONFIG_SCHEMA or word in in_file else word.lower()
    rows = [row for row in doc.rows if row.key == key]
    if key not in actlib.CONFIG_SCHEMA and not rows:
        close = difflib.get_close_matches(key, list(actlib.CONFIG_SCHEMA) + sorted(in_file), n=4, cutoff=0.5)
        hint = f" Did you mean: {', '.join(f'`{name}`' for name in close)}?" if close else ""
        return 1, f"Unknown setting `{word}`.{hint} /act-config alone lists them all."
    if not value:
        return _key_form(doc, key, rows)
    return _set_form(path, doc, key, value, rows)


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(
        prog="config.py",
        description="Show or set the settings in docs/ai/config.md. No arguments: every setting. "
                    "One key: its value, allowed values, default, effect and notes. A key and a value: "
                    "write the value into that row (nothing is committed).")
    parser.add_argument("--root", metavar="PATH", help="project root (default: the project this script belongs to)")
    parser.add_argument("words", nargs="*", metavar="KEY [VALUE ...]",
                        help="the key, then the value (words are joined with one space)")
    args = parser.parse_args(argv)
    try:
        root = Path(args.root).resolve() if args.root else actlib.repo_root(Path(__file__).resolve().parent)
    except RuntimeError as error:
        print(f"config: {error}", file=sys.stderr)
        return 1
    code, output = handle(root, " ".join(args.words))
    print(output)
    return code


if __name__ == "__main__":
    try:
        from usage import count_script_run
        count_script_run(__file__)
    except ImportError:
        pass
    sys.exit(main(sys.argv[1:]))
