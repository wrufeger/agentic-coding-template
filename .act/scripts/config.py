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
#   "own key, not checked"); the Roles rows follow as `<role> = tier · reasoning · model` and are
#   only shown; the last line says how to look at and set a key. One key: its value and source, the
#   allowed values or format, the default, when a change takes effect, then the notes - the
#   paragraphs under the table that name the key, in the project's own config.md (for a check the
#   Guards column instead). A new value is validated without regard to case against the schema and
#   written in its canonical spelling; free text and keys the schema does not know take any one-line
#   value, a `|` in it is written `\|`. The write replaces only the value cell of that one row; every
#   other byte of the file (BOM, line endings, other cells, the Guards column, the rest) stays.
#   Nothing is committed.
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
    for index, line in enumerate(lines):
        stripped = line.strip()
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
        rows.append(Row(index, section, in_roles, key, cells, pipes))
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
    if not row.in_roles and row.key not in actlib.CONFIG_SCHEMA:
        notes.append("own key, not checked")
    return ", ".join(notes)


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
            tier, reasoning, model = (row.cells + ["", "", ""])[1:4]
            out.append(f"  {row.key} = {tier} · {reasoning} · {model}")
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
            tier, reasoning, model = (row.cells + ["", "", ""])[1:4]
            return 0, (f"{row.key} = {tier} · {reasoning} · {model}  (Roles table: edit by hand)")
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
            if len(row.cells) > 2 and row.cells[2]:
                out.append("Guards: " + row.cells[2])
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
    check = _check_effect(key, new_value, row.cells[2] if len(row.cells) > 2 else "")
    if check:
        out.append(check)
    return 0, "\n".join(out)


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
