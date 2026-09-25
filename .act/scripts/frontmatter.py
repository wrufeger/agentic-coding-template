#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: One shared frontmatter parser for every "---\n...\n---\n" block under .act/ and
#          docs/ai/local/ -- used to be two: tiers.py's split_frontmatter() (single-line fields
#          only, built for the template's own generated bridge files) and settings_load.py's
#          _strict_frontmatter() (a hand-rolled parser gating an import's risky-key/name checks).
#          Two parsers meant two places that could each be wrong about the same shape (`B111.1`,
#          review of `T24`) -- this module reads a BOM, CRLF, single/double-quoted values, and a
#          multi-line value (a ">"/"|" block scalar or a plain indented continuation), which is the
#          shape Claude Code frontmatter actually uses (see .act/agents/*.md, .act/skills/*/SKILL.md
#          and the generated .act/bridges/agents/*.md -- none of the template's own files need the
#          multi-line/quoted forms today, but a project's own hand-authored role or skill can).
#
# Usage: not run directly -- imported (`import frontmatter`) from a script in .act/scripts/ or
#        .act/hooks/ (both add their own directory to sys.path automatically).
#
# Output format: no CLI output of its own; parse_frontmatter()'s return value is documented below.
#        A caller that must stay lenient on a malformed block (tiers.py: never abort a session
#        start over a bad file) uses ok=False as "nothing to resolve here", exactly like the
#        no-frontmatter-at-all case -- the parser itself never raises. A caller that must reject a
#        malformed block (settings_load.py: refuse importing a unit it cannot read with confidence)
#        uses ok=False as its refusal signal, with `error` (line number + offending text) folded
#        into the message it reports.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

_BLOCK_INDICATORS = (">", ">-", ">+", "|", "|-", "|+")


@dataclass
class ParseResult:
    """fields: key -> its (quote-stripped, multi-line-joined) value. order: keys in the order they
    first appeared (a key may repeat in `order` if the file itself repeats it -- last value wins in
    `fields`, same as a plain dict update; a caller that renders `order` back out skips a key no
    longer in `fields`, see tiers.render_frontmatter()). body: everything after the closing '---'
    line, verbatim (own line endings kept, never re-wrapped) -- unchanged from `text` itself when
    there is no frontmatter block at all (ok=True, fields={}, order=[]) or it could not be parsed
    (ok=False). error: "line <n>: <what> (<offending text>)" when ok=False, i.e. a '---' block was
    opened but a line inside it was neither 'key: value', a quoted key/value, a block-scalar
    ('>'/'|') opener plus its indented lines, a plain indented continuation, nor blank -- or the
    opener never found a closing '---' at all. None whenever ok=True."""
    fields: dict[str, str]
    order: list[str] = field(default_factory=list)
    body: str = ""
    ok: bool = True
    error: Optional[str] = None


def _strip_quotes(raw: str) -> str:
    """Trim whitespace and, if the whole (trimmed) string is wrapped in one matching pair of
    quotes, remove them -- used for a frontmatter key and a value alike, so a quoted key
    ('"hooks":') or a quoted value (name: "builder") is read the same as its unquoted form."""
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1].strip()
    return value


_QUOTE_TRIGGER_CHARS = "[]{}&*!|>%@`\"'?"


def quote_value(value: str) -> str:
    """Render `value` (already quote-stripped, e.g. from ParseResult.fields) back into the
    right-hand side of a "key: <value>" frontmatter line, adding double quotes -- and escaping any
    backslash/double-quote already inside it -- when writing it back unquoted would change its
    meaning or produce invalid YAML: an embedded ": " or " #" (either reads as a new key or a
    comment starting mid-value), a leading/trailing space, an empty value, or a value that starts
    with a character YAML gives special meaning at the start of a scalar (`_QUOTE_TRIGGER_CHARS`,
    which includes the two quote characters themselves -- an unquoted value starting with one would
    misread as an opening quote) or with "- " (a YAML sequence entry). A caller that built `value`
    itself (never round-tripped through parse_frontmatter()) gets the same treatment, so a value
    like "Use when: a thing" set directly by a caller is quoted correctly too."""
    if value == "" or value != value.strip() or ": " in value or " #" in value:
        needs_quote = True
    elif value[0] in _QUOTE_TRIGGER_CHARS or value.startswith("- "):
        needs_quote = True
    else:
        needs_quote = False
    if not needs_quote:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _indent_of(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def parse_frontmatter(text: str) -> ParseResult:
    """Parse the leading "---\\n...\\n---\\n" block of `text`, if any. A BOM before the opening
    fence and CRLF line endings are always tolerated; leading blank lines before the opening fence
    are tolerated too (a project's own hand-authored file is not always byte-perfect); a missing
    trailing newline right after the closing fence (file ends exactly at "---") is tolerated as
    well. A "#"-led comment line, at any indentation, is skipped outside a block scalar (the old
    pre-`B111.1` parser did too -- a project's own hand-authored file may carry one). Returns
    (fields={}, order=[], body=text, ok=True) -- not an error -- when the first non-blank line is
    not exactly "---": callers treat that as "nothing to resolve here"."""
    working = text.lstrip("﻿")
    lines = working.splitlines()

    start = 0
    while start < len(lines) and lines[start].strip() == "":
        start += 1
    if start >= len(lines) or lines[start].strip() != "---":
        return ParseResult(fields={}, order=[], body=text, ok=True)

    close: Optional[int] = None
    for i in range(start + 1, len(lines)):
        if lines[i].strip() == "---":
            close = i
            break
    if close is None:
        return ParseResult(
            fields={}, order=[], body=text, ok=False,
            error=f"line {start + 1}: opening '---' never closes",
        )

    fields: dict[str, str] = {}
    order: list[str] = []
    current_key: Optional[str] = None
    block_mode: Optional[str] = None  # ">" or "|", once a block-scalar opener was seen
    block_lines: list[str] = []
    plain_cont: list[str] = []

    def _finish_block() -> None:
        nonlocal current_key, block_mode, block_lines
        if current_key is not None and block_mode is not None:
            content_lines = [l for l in block_lines if l.strip() != ""]
            indent = min((_indent_of(l) for l in content_lines), default=0)
            dedented = [l[indent:] if len(l) >= indent else l.strip() for l in block_lines]
            if block_mode == ">":
                fields[current_key] = " ".join(s.strip() for s in dedented if s.strip() != "")
            else:
                fields[current_key] = "\n".join(dedented)
        block_mode = None
        block_lines = []

    def _finish_plain() -> None:
        nonlocal current_key, plain_cont
        if current_key is not None and plain_cont:
            base = fields.get(current_key, "")
            fields[current_key] = " ".join([base] + plain_cont) if base else " ".join(plain_cont)
        plain_cont = []

    i = start + 1
    while i < close:
        raw_line = lines[i]
        if raw_line.strip() == "":
            if block_mode is not None:
                block_lines.append(raw_line)
            i += 1
            continue
        if block_mode is None and raw_line.lstrip(" \t").startswith("#"):
            # A YAML comment line, at any indentation -- the old (pre-`B111.1`) tiers.py parser
            # skipped these too; only outside a block scalar, where a "#"-led line is data, not a
            # comment (a block scalar's own dedent step (_finish_block()) already handles a
            # comment-shaped line inside one no differently from any other content line).
            i += 1
            continue
        if raw_line[:1] in (" ", "\t"):
            if current_key is None:
                return ParseResult(
                    fields={}, order=[], body=text, ok=False,
                    error=f"line {i + 1}: indented line with no preceding key ({raw_line.strip()!r})",
                )
            if block_mode is not None:
                block_lines.append(raw_line)
            else:
                plain_cont.append(raw_line.strip())
            i += 1
            continue

        _finish_block()
        _finish_plain()
        if ":" not in raw_line:
            return ParseResult(
                fields={}, order=[], body=text, ok=False,
                error=f"line {i + 1}: no ':' found ({raw_line!r})",
            )
        raw_key, _, raw_value = raw_line.partition(":")
        key = _strip_quotes(raw_key)
        if not key:
            return ParseResult(
                fields={}, order=[], body=text, ok=False,
                error=f"line {i + 1}: empty key ({raw_line!r})",
            )
        value = raw_value.strip()
        current_key = key
        if key not in fields:
            order.append(key)
        if value in _BLOCK_INDICATORS:
            block_mode = value[0]
            block_lines = []
            fields[key] = ""
        else:
            block_mode = None
            fields[key] = _strip_quotes(value)
        i += 1

    _finish_block()
    _finish_plain()

    body_lines = working.splitlines(keepends=True)
    body = "".join(body_lines[close + 1:])
    return ParseResult(fields=fields, order=order, body=body, ok=True)
