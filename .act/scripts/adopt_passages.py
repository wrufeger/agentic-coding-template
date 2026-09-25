#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Mechanical insertion of an adopted project's own passages into
#          docs/project/coding_rules.md and docs/README.md (skill `act-adopt`, step 6, "Files
#          outside the entry system"). The model — or the worker preparing a batch for it — has
#          already cut the passage byte-identical from the old source and decided that it is the
#          project's own text, not the predecessor template's (step 2's diff); this script does not
#          re-decide any of that. It only does the two things a human hand-edit got wrong once
#          (B-follow-up to B129.2): shift every heading in the passage down by the same number of
#          levels (the old top level becomes "###" in coding_rules.md, "##" in docs/README.md,
#          exactly as the skill's table says) and insert the shifted text at the fixed place — the
#          end of the "Own rules" section (after its `<!-- act:own-rules -->` mark and comment
#          line) for coding_rules.md, the end of the file for docs/README.md — while preserving the
#          target file's own line endings (a `\r\n` file stays `\r\n`) and everything already there.
#          Re-running with the same passages file is a no-op: the exact shifted block, once found
#          already in place, is never inserted twice. Stdlib only.
#
# Usage:
#   python .act/scripts/adopt_passages.py --target <dir> --into coding --from <passages.md> --plan
#   python .act/scripts/adopt_passages.py --target <dir> --into coding --from <passages.md>
#   python .act/scripts/adopt_passages.py --target <dir> --into readme --from <passages.md> [--plan]
#
# `--into coding`  -> docs/project/coding_rules.md, inserted at the end of the "Own rules" section,
#                     old top heading level shifted to "###" (a passage with no heading of its own
#                     is inserted as is, unshifted).
# `--into readme`  -> docs/README.md, appended at the end of the file, old top heading level
#                     shifted to "##".
#
# `--from` names a UTF-8 file holding the passage(s) exactly as cut from the old source (several
# spans may already be concatenated there, in their original order) — never text retyped by a
# model. A leading BOM is stripped; the file's own line endings do not matter, the target file's do.
#
# Output format:
#   "already present, nothing to do" (exit 0) if the shifted block is already at its place; one
#   line naming the target, the insertion point and the number of lines, then "inserted" (write) or
#   "would insert" (--plan), exit 0. A schema problem in the target file (marker not found for
#   `--into coding`) or a missing/unreadable file: one line on stderr, exit 1; a bad command line:
#   exit 2.

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Optional

RE_HEADING = re.compile(r"^(?P<hashes>#{1,6})(?P<rest>\s+.*)?$")
RE_OWN_RULES_MARK = re.compile(r"^<!--\s*act:own-rules\s*-->\s*$")
RE_TOP_HEADING = re.compile(r"^##\s+.*$")
# A fenced code block (``` or ~~~, indented up to three spaces, closed by a fence of the same
# character and at least the same length) — a "heading" inside one is example text, never shifted
# or counted towards the passage's shallowest level.
RE_FENCE = re.compile(r"^\s{0,3}(?P<fence>`{3,}|~{3,})")

TARGETS = {
    "coding": {"path": "docs/project/coding_rules.md", "level": 3},
    "readme": {"path": "docs/README.md", "level": 2},
}


class Refused(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _strip_bom(text: str) -> str:
    return text[1:] if text.startswith("﻿") else text


def detect_newline(raw: bytes) -> str:
    """The target file's own line ending — "\\r\\n" if that is what most of its line breaks use,
    "\\n" otherwise (also the default for a file with no line break at all)."""
    crlf = raw.count(b"\r\n")
    lf_only = raw.count(b"\n") - crlf
    return "\r\n" if crlf > lf_only else "\n"


def _headings_outside_fences(lines: list[str]) -> list[tuple[int, "re.Match[str]"]]:
    """(index, match) for every Markdown heading line in `lines` that is not inside a fenced code
    block — a line such as "# install deps first" inside a ``` block is example text, not a
    heading to shift."""
    found: list[tuple[int, "re.Match[str]"]] = []
    fence: Optional[str] = None
    for i, line in enumerate(lines):
        fence_match = RE_FENCE.match(line)
        if fence is not None:
            if fence_match and fence_match.group("fence")[0] == fence[0] \
                    and len(fence_match.group("fence")) >= len(fence):
                fence = None
            continue
        if fence_match:
            fence = fence_match.group("fence")
            continue
        m = RE_HEADING.match(line)
        if m:
            found.append((i, m))
    return found


def shift_headings(text: str, target_level: int) -> str:
    """`text` (already "\\n"-normalized) with every Markdown heading's level shifted by the same
    amount, so the shallowest heading in it becomes exactly `target_level` (never below level 1).
    Text with no heading outside a fenced code block comes back unchanged; a fence's own content is
    never touched."""
    lines = text.split("\n")
    headings = _headings_outside_fences(lines)
    if not headings:
        return text
    shift = target_level - min(len(m.group("hashes")) for _, m in headings)
    if shift == 0:
        return text
    out = list(lines)
    for i, m in headings:
        new_level = max(1, len(m.group("hashes")) + shift)
        out[i] = "#" * new_level + (m.group("rest") or "")
    return "\n".join(out)


def _own_rules_section_bounds(lines: list[str]) -> tuple[int, int]:
    """(content_start, content_end): the "Own rules" section's content (into `lines`, split on
    "\\n") — everything between the `<!-- act:own-rules -->` mark itself and the next top-level
    ("## ") heading, or the end of the file if there is none. `content_start` is the mark's own
    line index plus one, so the existing comment line and every rule already there stay inside the
    span, in their original order. Raises Refused if the mark itself is not found."""
    mark_index: Optional[int] = None
    for i, line in enumerate(lines):
        if RE_OWN_RULES_MARK.match(line.strip()):
            mark_index = i
            break
    if mark_index is None:
        raise Refused("no '<!-- act:own-rules -->' mark found — is this a coding_rules.md the "
                       "template wrote?")
    end = len(lines)
    for i in range(mark_index + 1, len(lines)):
        if RE_TOP_HEADING.match(lines[i].strip()):
            end = i
            break
    return mark_index + 1, end


def _contains_block(existing: str, block: str) -> bool:
    """True if `block` sits anywhere in `existing` as its own paragraph — bounded by the start/end
    of `existing` or a blank line on each side, not merely as a substring of a larger paragraph."""
    return ("\n\n" + block + "\n\n") in ("\n\n" + existing + "\n\n")


def _append_block(existing: str, block: str) -> tuple[str, bool]:
    """(new_text, changed): `block` appended to `existing` (both already "\\n"-normalized and
    outer-blank-stripped), separated by one blank line — unless `block` is already present
    somewhere in `existing` as its own paragraph, in which case `existing` comes back unchanged.
    Checked anywhere in `existing`, not only as its trailing block (T76 follow-up): a rerun stays
    idempotent even after something else was appended after the block in the same section."""
    if existing and _contains_block(existing, block):
        return existing, False
    return (existing + "\n\n" + block if existing else block), True


def build_result(target_text: str, into: str, passage: str) -> tuple[str, bool]:
    """(new_text, changed). `new_text` is `target_text` unchanged if the block is already present,
    or with the block inserted."""
    block = shift_headings(passage.strip("\n"), TARGETS[into]["level"])
    if into == "coding":
        lines = target_text.split("\n")
        content_start, end = _own_rules_section_bounds(lines)
        head = lines[:content_start]
        tail = lines[end:]
        body = "\n".join(lines[content_start:end]).strip("\n")
        new_body, changed = _append_block(body, block)
        if not changed:
            return target_text, False
        new_lines = head + [""] + new_body.split("\n") + (([""] + tail) if tail else [])
        return "\n".join(new_lines), True
    # "readme": append at the very end of the file — the whole file is the "existing" span.
    new_text, changed = _append_block(target_text.rstrip("\n"), block)
    return (new_text + "\n") if changed else target_text, changed


def run(root: Path, into: str, passages_path: Path, plan: bool) -> int:
    target_rel = TARGETS[into]["path"]
    target_path = root / target_rel
    if not target_path.is_file():
        print(f"adopt_passages.py: {target_rel} not found under {root}", file=sys.stderr)
        return 1
    try:
        passage_raw = passages_path.read_bytes()
    except OSError as exc:
        print(f"adopt_passages.py: cannot read {passages_path}: {exc}", file=sys.stderr)
        return 1
    try:
        passage = _strip_bom(passage_raw.decode("utf-8")).replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError as exc:
        print(f"adopt_passages.py: {passages_path}: not valid UTF-8 ({exc})", file=sys.stderr)
        return 1
    if not passage.strip():
        print(f"adopt_passages.py: {passages_path} is empty — nothing to insert", file=sys.stderr)
        return 1

    target_raw = target_path.read_bytes()
    newline = detect_newline(target_raw)
    try:
        target_text = target_raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    except UnicodeDecodeError as exc:
        print(f"adopt_passages.py: {target_rel}: not valid UTF-8 ({exc})", file=sys.stderr)
        return 1

    try:
        new_text, changed = build_result(target_text, into, passage)
    except Refused as exc:
        print(f"adopt_passages.py: {target_rel}: {exc.message}", file=sys.stderr)
        return 1

    if not changed:
        print(f"[adopt-passages] {target_rel}: already present, nothing to do")
        return 0

    inserted_lines = new_text.count("\n") - target_text.count("\n")
    where = "end of the 'Own rules' section" if into == "coding" else "end of the file"
    verb = "would insert" if plan else "inserted"
    print(f"[adopt-passages] {target_rel}: {verb} {inserted_lines} line(s) at {where} "
          f"<- {passages_path}")
    if plan:
        return 0

    with open(target_path, "w", encoding="utf-8", newline=newline) as handle:
        handle.write(new_text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adopt_passages.py",
        description="Insert an adopted project's own passages into docs/project/coding_rules.md "
                    "or docs/README.md, heading levels shifted, target line endings preserved.",
    )
    parser.add_argument("--target", metavar="DIR", required=True, help="the project (already set up by adopt.py --apply)")
    parser.add_argument("--into", choices=sorted(TARGETS), required=True, help="which file to insert into")
    parser.add_argument("--from", dest="passages", metavar="FILE", required=True,
                        help="UTF-8 file holding the passage(s), cut byte-identical from the old source")
    parser.add_argument("--plan", action="store_true", help="check and show what would change, write nothing")
    return parser


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    root = Path(args.target).expanduser().resolve()
    passages_path = Path(args.passages).expanduser().resolve()
    if not (root / ".act").is_dir():
        print(f"adopt_passages.py: {root} has no .act/ — run adopt.py --apply (or init.py) first", file=sys.stderr)
        return 2
    if not passages_path.is_file():
        print(f"adopt_passages.py: passages file not found: {passages_path}", file=sys.stderr)
        return 2
    return run(root, args.into, passages_path, args.plan)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
