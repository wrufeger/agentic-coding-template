#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: The first migration ever shipped (contract: .act/scripts/update.py step 8) — folds
#          docs/ai/questions/ into docs/ai/inbox/ (Q100 b, ADR-9,
#          docs/project/concepts/ai-dev-app/16-inbox-questions-tasks.md § "Entscheidung ... und
#          Bauvorgabe"):
#            1. Every docs/ai/questions/*.md file (not README.md) moves to docs/ai/inbox/, gets a
#               "kind: question" header line (right after "id:"/"formerly:", before "for:"), and is
#               renamed to "<ID>-<slug>.md" where ID is its own "id:" header value and slug is its
#               old filename with the leading "YYYY-MM-DD-" date stripped. A question without an
#               id yet (team mode, not assigned), or whose id is not a valid "Q<n>" (see below),
#               keeps its old filename, only moves and gains "kind: question".
#            2. docs/ai/questions/README.md is dropped if it is still the unedited template
#               scaffold (first line "<!-- act:default -->"); otherwise it is left in place and
#               named in the description for the human to remove by hand. The now-empty
#               docs/ai/questions/ directory is then removed.
#            3. Every file carrying an "id:" header under docs/ai/work/tasks/, .../backlog/,
#               .../archive/ (its "legacy/" and "proposals/" subtrees excluded — old material kept
#               byte for byte, and already-decided proposals, neither renamed here) and
#               docs/ai/inbox/ is renamed to "<ID>-<slug>.md" the same way, unless already named
#               that way. An inbox entry without an id (todo/report/note) keeps its name. An id
#               that isn't a valid identifier for its own location (wrong prefix, leading zeros,
#               anything not matching "^[TBQ]\d+[a-z]?$") is left unrenamed and reported instead.
#            4. docs/ai/inbox/README.md, docs/ai/work/tasks/README.md, .../backlog/README.md and
#               .../archive/README.md are replaced with the fetched template's own
#               .act/skeleton/<...>/README.md when they are still the unedited scaffold (same
#               "<!-- act:default -->" test) and its content actually differs; a project-edited
#               copy (no marker, or a different one) is left alone and named in the description.
#          A rename happens on the filesystem (Path.rename), never "git mv" — update.py's own
#          step_commit stages both the old (now-missing) and the new path from the touched-paths
#          list this module returns (git F11 handling already covers a tracked file that vanished).
#          Every rename target is checked for a pre-existing file right before the rename itself (a
#          collision is reported, never overwritten — Path.rename() raises on Windows but silently
#          replaces the target on POSIX, so the check must happen on our side either way).
#          Re-running apply() a second time changes nothing (every action here first checks whether
#          its target state already holds); plan() only reads, never writes. Anything this run
#          could not do on its own (a naming conflict, an invalid id, a project-edited README) is
#          also written to a single docs/ai/inbox/report-<timestamp>-migration-001-one-inbox.md
#          (kind: report) so it does not only flash by on stdout — a second run with the same
#          outstanding items finds that report still open and does not write a second one.
#
# Contract (.act/scripts/update.py step 8): plan(root) -> str, apply(root) -> (str, list[str]) of
# project-relative paths (posix separators) touched — old and new path for every rename, so
# step_commit's `git add`/`git commit` cover both sides. Stdlib only, no `actlib` import: a
# migration must not depend on the *project's* possibly-older copy of it (see the module docstring
# in update.py's step 8 section) — the small pieces of actlib.header_block/entries.py's slugging
# this needs are reimplemented below instead.

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import NamedTuple, Optional

QUESTIONS_DIR = "docs/ai/questions"
INBOX_DIR = "docs/ai/inbox"
TASKS_DIR = "docs/ai/work/tasks"
BACKLOG_DIR = "docs/ai/work/backlog"
ARCHIVE_DIR = "docs/ai/work/archive"
RENAME_DIRS = (TASKS_DIR, BACKLOG_DIR, ARCHIVE_DIR, INBOX_DIR)
# Subtrees under docs/ai/work/archive/ this migration never touches: old material kept byte for
# byte (legacy/) and already-decided proposals (proposals/), each with its own naming scheme.
ARCHIVE_EXCLUDE = (f"{ARCHIVE_DIR}/legacy", f"{ARCHIVE_DIR}/proposals")

# Which id prefix is valid in which location (16-inbox-questions-tasks.md § "Entscheidung"):
# questions/inbox only ever carry "Q", tasks only "T", backlog only "B", archive keeps all three
# since anything can end up there.
_ALLOWED_ID_PREFIXES = {
    QUESTIONS_DIR: "Q",
    INBOX_DIR: "Q",
    TASKS_DIR: "T",
    BACKLOG_DIR: "B",
    ARCHIVE_DIR: "TBQ",
}

README_REFRESH = (
    ("docs/ai/inbox/README.md", ".act/skeleton/inbox/README.md"),
    ("docs/ai/work/tasks/README.md", ".act/skeleton/work/tasks/README.md"),
    ("docs/ai/work/backlog/README.md", ".act/skeleton/work/backlog/README.md"),
    ("docs/ai/work/archive/README.md", ".act/skeleton/work/archive/README.md"),
)

_BOM = b"\xef\xbb\xbf"
_DEFAULT_MARK = b"<!-- act:default -->"
_ID_RE = re.compile(rb"(?im)^id:\s*(\S+)\s*$")
_ID_PARTS_RE = re.compile(r"^([TBQ])(\d+)([a-z]?)$")
_KEY_RE = re.compile(rb"^([A-Za-z][A-Za-z-]*):")
_DATE_PREFIX_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-")
_REPORT_NAME_RE = re.compile(r"^report-\d{8}-\d{4}(?:-\d+)?-migration-001-one-inbox\.md$")


def _is_readme(name: str) -> bool:
    return name.lower() == "readme.md"


def _split_bom(data: bytes) -> tuple[bytes, bytes]:
    """(bom, rest) — bom is b"" when data has none, so the header logic below never has to look
    at a leading BOM to find "id:"/"kind:" et al., and callers put it back verbatim afterwards."""
    if data.startswith(_BOM):
        return _BOM, data[len(_BOM):]
    return b"", data


def _line_ending(line: bytes) -> bytes:
    if line.endswith(b"\r\n"):
        return b"\r\n"
    if line.endswith(b"\n"):
        return b"\n"
    if line.endswith(b"\r"):
        return b"\r"
    return b"\n"


def _file_newline(lines: list[bytes]) -> bytes:
    """The line ending actually used elsewhere in the file, falling back to "\n" for a file with
    none (a single line with no trailing newline at all)."""
    for line in lines:
        if line.endswith((b"\r\n", b"\n", b"\r")):
            return _line_ending(line)
    return b"\n"


def _header_end(lines: list[bytes]) -> int:
    """Index one past the file's leading run of "key: value" header lines — mirrors
    actlib.header_block()/entries.py's _HEADER_FIELD_RE without importing either (see module
    docstring): stops at the first blank line or a line that isn't itself a header field."""
    end = 0
    for line in lines:
        if not line.strip() or not _KEY_RE.match(line):
            break
        end += 1
    return end


def _entry_id(data: bytes) -> Optional[str]:
    _, body = _split_bom(data)
    lines = body.splitlines(keepends=True)
    header = b"".join(lines[: _header_end(lines)])
    match = _ID_RE.search(header)
    return match.group(1).decode("ascii", "replace") if match else None


def _canonical_id(entry_id: str, location: str) -> Optional[str]:
    """The canonical form of entry_id (leading zeros in the numeric part dropped, e.g. "T012" ->
    "T12") if it is a syntactically valid id whose prefix is allowed at this location, None
    otherwise — an invalid id is left unrenamed by the caller and reported instead."""
    match = _ID_PARTS_RE.match(entry_id)
    if not match:
        return None
    prefix, digits, suffix = match.groups()
    if prefix not in _ALLOWED_ID_PREFIXES.get(location, ""):
        return None
    return f"{prefix}{int(digits)}{suffix}"


def _slug_from_filename(name: str) -> str:
    stem = name[:-3] if name.lower().endswith(".md") else name
    return _DATE_PREFIX_RE.sub("", stem)


def _with_kind_question(data: bytes) -> bytes:
    """`data` with a "kind: question" header line inserted right after any "id:"/"formerly:"
    lines and before the rest of the header (typically "for:") — everything else byte for byte
    unchanged, including a leading BOM and whichever line ending the file already used. A header
    whose last line is also the file's last line, with no trailing newline at all, gets the
    file's own line ending appended first so the new line does not run into it."""
    bom, body = _split_bom(data)
    lines = body.splitlines(keepends=True)
    end = _header_end(lines)
    insert_at = end
    for i in range(end):
        key = _KEY_RE.match(lines[i]).group(1).lower()
        if key not in (b"id", b"formerly"):
            insert_at = i
            break
    default_newline = _file_newline(lines)
    if insert_at > 0 and not lines[insert_at - 1].endswith((b"\r\n", b"\n", b"\r")):
        lines[insert_at - 1] = lines[insert_at - 1] + default_newline
    if insert_at < len(lines):
        newline = _line_ending(lines[insert_at])
    elif insert_at > 0:
        newline = _line_ending(lines[insert_at - 1])
    else:
        newline = default_newline
    new_line = b"kind: question" + newline
    body_out = b"".join(lines[:insert_at]) + new_line + b"".join(lines[insert_at:])
    return bom + body_out


class _Report(NamedTuple):
    questions_moved: int
    questions_conflicts: list[str]
    questions_invalid: list[str]
    renamed: int
    rename_conflicts: list[str]
    rename_invalid: list[str]
    readmes_refreshed: list[str]
    readmes_reported: list[str]
    questions_readme_dropped: bool
    questions_readme_reported: bool


def _archive_excluded(rel_posix: str) -> bool:
    return any(rel_posix == excl or rel_posix.startswith(excl + "/") for excl in ARCHIVE_EXCLUDE)


def _plan_moves(root: Path) -> tuple[list[tuple[Path, Path, bytes]], list[str], list[str]]:
    """Question files to move (src, dest, new_content), filenames that collide with an
    already-existing destination (reported, left in place), and ids that are syntactically
    invalid or carry the wrong prefix for docs/ai/questions/ (reported, kept under their old
    name)."""
    moves: list[tuple[Path, Path, bytes]] = []
    conflicts: list[str] = []
    invalid: list[str] = []
    questions_dir = root / QUESTIONS_DIR
    if not questions_dir.is_dir():
        return moves, conflicts, invalid
    inbox_dir = root / INBOX_DIR
    for src in sorted(questions_dir.glob("*.md")):
        if _is_readme(src.name):
            continue
        data = src.read_bytes()
        entry_id = _entry_id(data)
        dest_name = src.name
        if entry_id is not None:
            canonical = _canonical_id(entry_id, QUESTIONS_DIR)
            if canonical is None:
                invalid.append(
                    f"{QUESTIONS_DIR}/{src.name}: id {entry_id!r} is not a valid question id — "
                    f"moved to {INBOX_DIR}/ under its old name, not renamed"
                )
            else:
                dest_name = f"{canonical}-{_slug_from_filename(src.name)}.md"
        dest = inbox_dir / dest_name
        if dest.exists():
            conflicts.append(f"{QUESTIONS_DIR}/{src.name} -> {INBOX_DIR}/{dest_name} (target exists)")
            continue
        moves.append((src, dest, _with_kind_question(data)))
    return moves, conflicts, invalid


def _plan_renames(root: Path) -> tuple[list[tuple[Path, Path]], list[str], list[str]]:
    """Existing id-bearing files under RENAME_DIRS not yet named "<ID>-<slug>.md", plus name
    conflicts and ids invalid for their own location (see _canonical_id), both reported and left
    untouched."""
    renames: list[tuple[Path, Path]] = []
    conflicts: list[str] = []
    invalid: list[str] = []
    seen_dests: set[Path] = set()
    for rel in RENAME_DIRS:
        base = root / rel
        if not base.is_dir():
            continue
        for src in sorted(base.rglob("*.md")):
            if _is_readme(src.name):
                continue
            rel_posix = src.relative_to(root).as_posix()
            if _archive_excluded(rel_posix):
                continue
            data = src.read_bytes()
            entry_id = _entry_id(data)
            if entry_id is None:
                continue
            canonical = _canonical_id(entry_id, rel)
            if canonical is None:
                invalid.append(f"{rel_posix}: id {entry_id!r} is not valid here, not renamed")
                continue
            if src.name.startswith(f"{canonical}-") or src.name == f"{canonical}.md":
                continue  # already correctly named
            dest_name = f"{canonical}-{_slug_from_filename(src.name)}.md"
            dest = src.parent / dest_name
            if dest.exists() or dest in seen_dests:
                conflicts.append(f"{rel_posix} -> {dest.relative_to(root).as_posix()} (target exists)")
                continue
            seen_dests.add(dest)
            renames.append((src, dest))
    return renames, conflicts, invalid


def _plan_readmes(root: Path) -> tuple[list[tuple[Path, bytes]], list[str]]:
    """Unedited-scaffold README copies whose skeleton content changed, plus a note for every
    README this migration leaves untouched because it no longer looks like the scaffold."""
    refresh: list[tuple[Path, bytes]] = []
    reported: list[str] = []
    for rel_dest, rel_src in README_REFRESH:
        dest = root / rel_dest
        src = root / rel_src
        if not dest.is_file():
            continue
        current = dest.read_bytes()
        if not current.lstrip(b"\xef\xbb\xbf").startswith(_DEFAULT_MARK):
            reported.append(f"{rel_dest} (compare with {rel_src})")
            continue
        if not src.is_file():
            continue
        new_content = src.read_bytes()
        if new_content != current:
            refresh.append((dest, new_content))
    return refresh, reported


def _questions_readme(root: Path) -> tuple[bool, bool]:
    """(would_drop, would_report) for docs/ai/questions/README.md."""
    readme = root / QUESTIONS_DIR / "README.md"
    if not readme.is_file():
        return False, False
    data = readme.read_bytes()
    if data.lstrip(b"\xef\xbb\xbf").startswith(_DEFAULT_MARK):
        return True, False
    return False, True


def _build_report(root: Path) -> _Report:
    moves, move_conflicts, move_invalid = _plan_moves(root)
    renames, rename_conflicts, rename_invalid = _plan_renames(root)
    readmes, readme_reports = _plan_readmes(root)
    drop_readme, report_readme = _questions_readme(root)
    return _Report(
        questions_moved=len(moves),
        questions_conflicts=move_conflicts,
        questions_invalid=move_invalid,
        renamed=len(renames),
        rename_conflicts=rename_conflicts,
        rename_invalid=rename_invalid,
        readmes_refreshed=[str(p.relative_to(root)).replace("\\", "/") for p, _ in readmes],
        readmes_reported=readme_reports,
        questions_readme_dropped=drop_readme,
        questions_readme_reported=report_readme,
    )


def _describe(report: _Report) -> str:
    parts = [
        f"{report.questions_moved} question(s) -> {INBOX_DIR}/",
        f"{report.renamed} file(s) renamed to <ID>-<slug>.md",
    ]
    if report.questions_readme_dropped:
        parts.append(f"{QUESTIONS_DIR}/README.md dropped (unedited scaffold)")
    if report.questions_readme_reported:
        parts.append(f"{QUESTIONS_DIR}/README.md left in place (edited by the project — remove by hand)")
    if report.readmes_refreshed:
        parts.append(f"{len(report.readmes_refreshed)} README(s) refreshed: {', '.join(report.readmes_refreshed)}")
    if report.readmes_reported:
        parts.append("left in place (edited by the project): " + ", ".join(report.readmes_reported))
    conflicts = report.questions_conflicts + report.rename_conflicts
    if conflicts:
        parts.append(f"{len(conflicts)} conflict(s), not overwritten: " + "; ".join(conflicts))
    invalid = report.questions_invalid + report.rename_invalid
    if invalid:
        parts.append(f"{len(invalid)} invalid id(s), not renamed: " + "; ".join(invalid))
    return "; ".join(parts)


def _outstanding_notes(report: _Report) -> list[str]:
    """Everything this run could not resolve on its own — a human needs to look at each of
    these; used both for the description and for the persisted inbox report (see module
    docstring)."""
    notes: list[str] = []
    notes.extend(report.questions_conflicts)
    notes.extend(report.rename_conflicts)
    notes.extend(report.questions_invalid)
    notes.extend(report.rename_invalid)
    if report.questions_readme_reported:
        notes.append(f"{QUESTIONS_DIR}/README.md left in place (edited by the project) — remove by hand")
    for r in report.readmes_reported:
        notes.append(f"{r} left in place (edited by the project) — compare and update by hand")
    return notes


def _find_open_migration_report(root: Path) -> Optional[Path]:
    """An existing docs/ai/inbox/report-*-migration-001-one-inbox.md still status: open, so a
    repeated apply() with the same outstanding items does not write a second report."""
    inbox_dir = root / INBOX_DIR
    if not inbox_dir.is_dir():
        return None
    for candidate in sorted(inbox_dir.glob("report-*-migration-001-one-inbox.md")):
        if not _REPORT_NAME_RE.match(candidate.name):
            continue
        data = candidate.read_bytes()
        _, body = _split_bom(data)
        lines = body.splitlines(keepends=True)
        header = b"".join(lines[: _header_end(lines)])
        if re.search(rb"(?im)^status:\s*open\s*$", header):
            return candidate
    return None


def _write_migration_report(root: Path, notes: list[str]) -> Path:
    """Writes docs/ai/inbox/report-<YYYYMMDD-HHMM>-migration-001-one-inbox.md (kind: report, for
    the whole team) listing every outstanding item, so it survives past the run's stdout. Stdlib
    only (no actlib/entries.py, see module docstring): the header and filename scheme are built
    by hand instead of through the project's own entry helpers."""
    inbox_dir = root / INBOX_DIR
    inbox_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    stamp = now.strftime("%Y%m%d-%H%M")
    created = now.strftime("%Y-%m-%dT%H:%M:%S")
    dest = inbox_dir / f"report-{stamp}-migration-001-one-inbox.md"
    suffix = 2
    while dest.exists():
        dest = inbox_dir / f"report-{stamp}-{suffix}-migration-001-one-inbox.md"
        suffix += 1
    lines = [
        "kind: report\n",
        "for: all\n",
        "status: open\n",
        f"created: {created}\n",
        "\n",
        "# Migration 001 (one inbox) — left for a human\n",
        "\n",
        "Not resolved on its own, see .act/migrations/001-one-inbox.py:\n",
        "\n",
    ]
    for note in notes:
        lines.append(f"- {note}\n")
    with open(dest, "x", newline="\n", encoding="utf-8") as handle:
        handle.writelines(lines)
    return dest


def plan(root: Path) -> str:
    """Describes what apply() would do, writes nothing."""
    return _describe(_build_report(root))


def apply(root: Path) -> tuple[str, list[str]]:
    """Performs the moves/renames/README refreshes described above. Returns (description,
    touched_rel_paths) — every path this run actually created, rewrote, or made vanish, both sides
    of a rename included, so update.py's step_commit stages the whole change."""
    touched: list[Path] = []

    moves, move_conflicts, move_invalid = _plan_moves(root)
    inbox_dir = root / INBOX_DIR
    if moves:
        inbox_dir.mkdir(parents=True, exist_ok=True)
    for src, dest, new_content in moves:
        if dest.exists():
            continue  # planned a moment ago; re-check before ever touching the filesystem
        dest.write_bytes(new_content)
        src.unlink()
        touched.append(src)
        touched.append(dest)

    drop_readme, report_readme = _questions_readme(root)
    if drop_readme:
        readme = root / QUESTIONS_DIR / "README.md"
        readme.unlink()
        touched.append(readme)

    questions_dir = root / QUESTIONS_DIR
    if questions_dir.is_dir():
        try:
            next(questions_dir.iterdir())
        except StopIteration:
            questions_dir.rmdir()

    renames, rename_conflicts, rename_invalid = _plan_renames(root)
    for src, dest in renames:
        if dest.exists():
            continue  # planned a moment ago; re-check right before the rename itself
        src.rename(dest)
        touched.append(src)
        touched.append(dest)

    readmes, readme_reports = _plan_readmes(root)
    for dest, new_content in readmes:
        dest.write_bytes(new_content)
        touched.append(dest)

    report = _Report(
        questions_moved=len(moves),
        questions_conflicts=move_conflicts,
        questions_invalid=move_invalid,
        renamed=len(renames),
        rename_conflicts=rename_conflicts,
        rename_invalid=rename_invalid,
        readmes_refreshed=[str(p.relative_to(root)).replace("\\", "/") for p, _ in readmes],
        readmes_reported=readme_reports,
        questions_readme_dropped=drop_readme,
        questions_readme_reported=report_readme,
    )
    description = _describe(report)

    notes = _outstanding_notes(report)
    if notes:
        existing_report = _find_open_migration_report(root)
        if existing_report is None:
            report_path = _write_migration_report(root, notes)
            touched.append(report_path)
            description += f"; outstanding items written to {report_path.relative_to(root).as_posix()}"
        else:
            rel = existing_report.relative_to(root).as_posix()
            description += f"; outstanding items already reported in {rel}"

    touched_rel = [str(p.relative_to(root)).replace("\\", "/") for p in touched]
    return description, touched_rel
