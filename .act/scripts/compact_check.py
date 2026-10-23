#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check the shortened sections of the archive collection files (`entries.py compact`) against
#          their full text, and the monthly topic overview against the ids of its month. A shortened
#          section may leave out the assistant's prose, never an id, hash, version, date, path or number
#          of the original, nor a line of the human's own words. Only text that is recognisably the
#          assistant's may be shortened (a paragraph opening with a bold label such as "**Context**"
#          and the option list directly below it); every other non-empty line of the original, marked
#          or not, counts as the human's and must stand verbatim. A note, and a todo captured from a
#          chat prefix, are the human's in full (a note up to the assistant's first reply block). The
#          original is read with `git show <hash>:<folder>/<file>` from the commit the collection's
#          head names. Stdlib only.
# Usage:
#   python .act/scripts/compact_check.py [--root DIR] [--month YYYY-MM] [--restore] [--no-overview]
#     Reads docs/ai/work/archive/*-YYYY-MM.md collection files (not legacy/). For every section: compares
#     the tokens of the original with the section; a section that lost one is reported with the missing
#     tokens ("compact_check: <id> in Q-2026-09.md lacks: ..."), a section whose original cannot be read
#     from Git is reported too, and so is a single file the named commit holds that is gone from the
#     working tree without a section in any collection. Then, for every month with a Q-, T-, B- or U- collection, the overview
#     archive/YYYY-MM.md must exist and name every id of that month's collections.
#     --restore writes the full body of each section that lost something back (heading and header line stay)
#     and then reports only what is still wrong. --month limits the check to one month, --no-overview skips
#     the overview. Exit 0: nothing wrong (after a restore: nothing left wrong), 1: a problem, 2: usage error.
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import actlib  # noqa: E402

ARCHIVE_DIR = Path("docs/ai/work/archive")
_COLLECTION_NAME_RE = re.compile(r"^(Q|T|B|U|other|ledger)-(\d{4}-\d{2})\.md$")
_ANCHOR_RE = re.compile(r'^<a id="([^"\n]+)"></a>\s*$')
_FULL_TEXT_RE = re.compile(r"git show ([0-9a-f]{7,40}):(\S+?)/<file>")
_FILE_FIELD_RE = re.compile(r"(?:^|\s·\s)file: (.+?)(?:\s·\s|$)")

_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_ID_RE = re.compile(r"\b(?:ADR-\d+|[QTBU]\d+[a-z]?)\b")
_HASH_RE = re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b")
_VERSION_RE = re.compile(r"\bv?\d+\.\d+\.\d+(?:[-+][\w.]+)?\b")
_PATH_RE = re.compile(r"(?:\.{0,2}/)?(?:[\w.~\-]+/)+[\w\-]+\.\w{1,5}\b|(?:[\w.~\-]+/){2,}")
_FILENAME_RE = re.compile(r"\b[\w\-]+\.(?:py|md|json|toml|ya?ml|sh|txt|js|ts|vue|php|cs|go|java|html|css|tsv)\b")
_NUMBER_RE = re.compile(r"(?<![\w.])\d+(?:[.,]\d+)?(?![\w])")
_LIST_MARKER_RE = re.compile(r"(?m)^\s*\d+[.)]\s")
_HUMAN_LINE_RE = re.compile(r"^\s*(?:>|\**\s*(?:Antwort|Answer|Reply)\b)", re.IGNORECASE)
_LABEL_RE = re.compile(r"^\s*\*\*[^*\n]+\*\*")
_HUMAN_LABEL_RE = re.compile(r"^\s*\*\*\s*(?:Antwort|Answer|Reply)\b", re.IGNORECASE)
_LIST_LINE_RE = re.compile(r"^(?:\s*(?:[-*+]|\d+[.)])\s|\s{2,}\S)")
_REPLY_BLOCK_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}\b")
_REFLOW_MIN = 30  # a human line at least this long may be found inside a reflowed paragraph
_KIND_RE =re.compile(r"(?im)^kind:\s*(\S+)")
_TRIAGE_RE = re.compile(r"(?im)^triage:")


@dataclass
class Section:
    """One entry section of a collection file."""

    anchor: str
    start: int  # index of the anchor line
    end: int  # index after the last line of the section
    lines: list[str]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def file_name(self) -> Optional[str]:
        if len(self.lines) < 3:
            return None
        field = self.lines[2].strip().strip("`").strip()
        match = _FILE_FIELD_RE.search(field)
        return match.group(1).strip() if match else None


def split_sections(lines: list[str]) -> list[Section]:
    """The sections of a collection: an anchor line directly followed by a `## ` heading starts one. A pair
    inside a fenced code block is an example, and a section boundary resets the fence state, as
    `actlib.collection_sections` does; that function lists only sections whose anchor is an id, while a
    journal or free-name section has none, so the scan is repeated here for every anchor."""
    starts: list[int] = []
    fence: actlib.FenceState = None
    for i, line in enumerate(lines):
        if i + 1 < len(lines) and _ANCHOR_RE.match(line.rstrip("\r")) and lines[i + 1].startswith("## "):
            starts.append(i)
            fence = None
            continue
        fence = actlib.fence_step(fence, line)
    sections: list[Section] = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        match = _ANCHOR_RE.match(lines[start].rstrip("\r"))
        sections.append(Section(match.group(1) if match else "", start, end, lines[start:end]))
    return sections


def tokens(text: str) -> set[str]:
    """Ids, hashes, versions, dates, paths and numbers of `text`; a number inside one of the others is not counted
    again."""
    found: set[str] = set()
    work = _LIST_MARKER_RE.sub(" ", text)
    for regex, fold in ((_DATE_RE, False), (_ID_RE, False), (_HASH_RE, True), (_VERSION_RE, False),
                        (_PATH_RE, False), (_FILENAME_RE, False)):
        for match in regex.finditer(work):
            value = match.group(0).rstrip(".")
            found.add(value.lower() if fold else value)
        work = regex.sub(" ", work)
    found.update(match.group(0) for match in _NUMBER_RE.finditer(work))
    return found


def _paragraphs(lines: list[str]) -> list[tuple[int, int]]:
    """(first, after-last) line index of every blank-line separated paragraph; a blank line inside a
    fenced code block does not end one."""
    found: list[tuple[int, int]] = []
    start: Optional[int] = None
    fence: actlib.FenceState = None
    for index, line in enumerate(lines):
        if not line.strip() and fence is None:
            if start is not None:
                found.append((start, index))
                start = None
            continue
        if start is None:
            start = index
        fence = actlib.fence_step(fence, line)
    if start is not None:
        found.append((start, len(lines)))
    return found


def human_lines(text: str, header: str = "") -> list[str]:
    """The lines of an entry body that must stay verbatim, whitespace folded: everything except text that is
    recognisably the assistant's. That is a paragraph opening with a bold label (other than Answer/Antwort/
    Reply) and the option list directly below it; after an empty label (`**Label:**` alone on its line) the
    lines up to the next blank line are the human's. Block quotes and Answer/Antwort/Reply lines are the
    human's everywhere. With `triage:` in the header (captured from a chat prefix) the whole text is the
    human's, in a `kind: note` everything before the assistant's first reply block."""
    lines = text.split("\n")
    kind = _KIND_RE.search(header)
    limit = 0
    if _TRIAGE_RE.search(header):
        limit = len(lines)
    elif kind and kind.group(1).lower() == "note":
        limit = next((i for i in range(len(lines) - 1)
                      if lines[i].strip() == "---" and _REPLY_BLOCK_RE.match(lines[i + 1])), len(lines))
    human = [index < limit or bool(_HUMAN_LINE_RE.match(line)) for index, line in enumerate(lines)]
    after_label = False  # the previous paragraph was assistant text that opened with a label
    for first, after in _paragraphs(lines):
        if first < limit:
            after_label = False
            continue
        label = _LABEL_RE.match(lines[first])
        if label and _HUMAN_LABEL_RE.match(lines[first]):
            human[first:after] = [True] * (after - first)
            after_label = False
        elif label:
            if not lines[first][label.end():].strip():
                human[first + 1:after] = [True] * (after - first - 1)
            after_label = True
        elif after_label and all(_LIST_LINE_RE.match(line) for line in lines[first:after]):
            after_label = False
        else:
            human[first:after] = [True] * (after - first)
            after_label = False
    return [" ".join(line.split()) for line, keep in zip(lines, human) if keep and line.strip()]


def git_show(root: Path, commit: str, path: str) -> Optional[str]:
    try:
        result = subprocess.run(["git", "-c", "core.quotePath=false", "show", f"{commit}:{path}"], cwd=root,
                                capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    try:
        return result.stdout.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError:
        return None


def head_sources(lines: list[str]) -> list[tuple[str, str]]:
    """(commit, folder) pairs named in the head of a collection, newest line first."""
    head_end = next((i for i in range(len(lines) - 1) if _ANCHOR_RE.match(lines[i]) and lines[i + 1].startswith("## ")),
                    len(lines))
    pairs = [(m.group(1), m.group(2)) for line in lines[:head_end] for m in [_FULL_TEXT_RE.search(line)] if m]
    return list(reversed(pairs))


def original_text(root: Path, sources: list[tuple[str, str]], file_name: str) -> Optional[str]:
    for commit, folder in sources:
        text = git_show(root, commit, f"{folder}/{file_name}")
        if text is not None:
            return text
    return None


def split_original(text: str) -> tuple[str, str]:
    """(title, body) of an original single file: heading line taken out of the body, header fields dropped."""
    body = actlib.split_header(text)[1]
    lines = body.split("\n")
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if re.match(r"^#{1,6}\s", line):
            return line.lstrip("#").strip(), "\n".join(lines[:index] + lines[index + 1:]).strip("\n")
        break
    return "", body.strip("\n")


def missing_in(original: str, section: Section) -> list[str]:
    """What the original body has and the section lacks: tokens first, then the human's lines."""
    _title, body = split_original(original)
    short = section.text
    lacking = sorted(tokens(body) - tokens(short), key=lambda t: (len(t), t))
    folded = " ".join(short.split())
    present = {" ".join(line.split()) for line in short.split("\n")}
    # a short line ("a", "1a 2a") counts only as a whole line, or it would be found inside any other text; a
    # long one may also stand inside a reflowed paragraph
    lacking += [f"line \"{line[:60]}\"" for line in human_lines(body, actlib.header_block(original))
                if line not in present and (len(line) < _REFLOW_MIN or line not in folded)]
    return lacking


def restored_section(section: Section, original: str) -> list[str]:
    """Anchor, heading and header line of `section` followed by the full body of `original`."""
    _title, body = split_original(original)
    lines = section.lines[:3]
    if body:
        lines += ["", *body.split("\n")]
        fence: actlib.FenceState = None
        for line in body.split("\n"):
            fence = actlib.fence_step(fence, line)
        if fence is not None:
            lines.append(actlib.fence_closer(fence))
    lines.append("")
    return lines


def check_collection(root: Path, path: Path, restore: bool) -> tuple[int, list[str], list[str]]:
    """(sections checked, problems still standing, restored anchors) for one collection file."""
    name = path.name
    raw = path.read_bytes().decode("utf-8")
    newline = "\r\n" if "\r\n" in raw else "\n"
    lines = raw.replace("\r\n", "\n").split("\n")
    sources = head_sources(lines)
    problems: list[str] = []
    restored: list[str] = []
    replacements: list[tuple[Section, list[str]]] = []
    sections = split_sections(lines)
    for section in sections:
        file_name = section.file_name
        if not file_name:
            problems.append(f"{section.anchor} in {name}: no `file:` field in the header line")
            continue
        original = original_text(root, sources, file_name)
        if original is None:
            problems.append(f"{section.anchor} in {name}: original {file_name} not found in Git "
                            f"(commits named in the head: {', '.join(c for c, _f in sources) or 'none'})")
            continue
        lacking = missing_in(original, section)
        if not lacking:
            continue
        if restore:
            replacements.append((section, restored_section(section, original)))
            restored.append(f"{section.anchor} in {name}")
        else:
            shown = ", ".join(lacking[:12]) + (f" (+{len(lacking) - 12} more)" if len(lacking) > 12 else "")
            problems.append(f"{section.anchor} in {name} lacks: {shown}")
    if replacements:
        for section, new_lines in reversed(replacements):
            lines[section.start:section.end] = new_lines
        actlib.overwrite_text(path, "\n".join(lines), newline=newline)
    return len(sections), problems, restored


def lost_files(root: Path, collections: list[Path]) -> list[str]:
    """Every single entry file the commits named in the collections' heads hold that is gone from the working
    tree and has no section (a matching `file:` field) in any collection: a section deleted by hand."""
    covered: set[tuple[str, str]] = set()
    pairs: set[tuple[str, str]] = set()
    for path in collections:
        try:
            lines = path.read_bytes().decode("utf-8").replace("\r\n", "\n").split("\n")
        except UnicodeDecodeError:
            continue  # reported by check_collection
        sources = head_sources(lines)
        pairs.update(sources)
        for section in split_sections(lines):
            if section.file_name:
                covered.update((folder, section.file_name) for _commit, folder in sources)
    problems: list[str] = []
    for commit, folder in sorted(pairs):
        try:
            result = subprocess.run(["git", "-c", "core.quotePath=false", "ls-tree", "-z", commit, f"{folder}/"],
                                    cwd=root, capture_output=True, check=True)
        except (OSError, subprocess.CalledProcessError):
            continue  # an unreadable commit is reported per section
        for record in result.stdout.decode("utf-8", errors="replace").split("\0"):
            meta, _tab, full = record.partition("\t")
            name = full.rpartition("/")[2]
            if (not full or meta.split()[1:2] != ["blob"] or not name.endswith(".md")
                    or name.lower() == "readme.md" or _COLLECTION_NAME_RE.match(name)
                    or re.fullmatch(r"\d{4}-\d{2}\.md", name)):
                continue
            if not (root / folder / name).exists() and (folder, name) not in covered:
                problems.append(f"{name} (held by {commit[:10]}:{folder}) is gone from the working tree "
                                "and no collection has a section for it")
    return problems


def overview_problems(archive: Path, month: str, collections: list[Path]) -> list[str]:
    """The overview `archive/<month>.md` must exist and name every id of the month's collections."""
    ids: list[str] = []
    for path in collections:
        text = path.read_bytes().decode("utf-8")
        ids += [entry_id for entry_id in actlib.entry_ids(text)]
    if not ids:
        return []
    overview = archive / f"{month}.md"
    if not overview.is_file():
        return [f"overview {overview.name} is missing: {len(ids)} id(s) in {month}"]
    text = overview.read_bytes().decode("utf-8")
    named = {actlib.canonical_id(match.group(0)) for match in re.finditer(r"\b[QTBU]\d+[a-z]?\b", text)}
    absent = [entry_id for entry_id in ids if entry_id not in named]
    if not absent:
        return []
    shown = ", ".join(absent[:20]) + (f" (+{len(absent) - 20} more)" if len(absent) > 20 else "")
    return [f"overview {overview.name} lacks {len(absent)} id(s): {shown}"]


def main(argv: Optional[list[str]] = None) -> int:
    # Findings quote section titles and bodies with umlauts or an em dash; on Windows, stdout/stderr otherwise
    # default to the console's legacy code page. Same fix as .act/scripts/rules.py.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="Check shortened archive sections and the monthly overview "
                                                 "against the full text in Git.")
    parser.add_argument("--root", default=".", help="project root (default: the current folder)")
    parser.add_argument("--month", metavar="YYYY-MM", help="check only the collections of this month")
    parser.add_argument("--restore", action="store_true",
                        help="write the full body back into every section that lost something")
    parser.add_argument("--no-overview", action="store_true", help="skip the check of the monthly overview")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    archive = root / ARCHIVE_DIR
    if not archive.is_dir():
        print(f"compact_check: no archive folder at {archive}", file=sys.stderr)
        return 2
    if args.month and not re.fullmatch(r"\d{4}-\d{2}", args.month):
        print(f"compact_check: --month wants YYYY-MM, got {args.month!r}", file=sys.stderr)
        return 2
    by_month: dict[str, list[Path]] = {}
    every_collection: list[Path] = []
    for path in sorted(archive.glob("*.md")):
        match = _COLLECTION_NAME_RE.match(path.name)
        if match:
            every_collection.append(path)
        if match and (not args.month or match.group(2) == args.month):
            by_month.setdefault(match.group(2), []).append(path)
    checked = 0
    problems: list[str] = []
    restored: list[str] = []
    for month, paths in sorted(by_month.items()):
        for path in paths:
            try:
                count, found, done = check_collection(root, path, args.restore)
            except UnicodeDecodeError as error:
                problems.append(f"{path.name} is not valid UTF-8: {error}")
                continue
            checked += count
            problems += found
            restored += done
        if not args.no_overview:
            problems += overview_problems(archive, month, [p for p in paths if p.name[0] in "QTBU"
                                                           and not p.name.startswith(("other", "ledger"))])
    problems += lost_files(root, every_collection)
    for line in restored:
        print(f"compact_check: restored {line} in full length")
    for line in problems:
        print(f"compact_check: {line}")
    if problems:
        print(f"compact_check: {len(problems)} problem(s) in {checked} section(s)")
        return 1
    print(f"compact_check: {checked} section(s) in {sum(len(p) for p in by_month.values())} collection(s) ok"
          + (f", {len(restored)} restored" if restored else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
