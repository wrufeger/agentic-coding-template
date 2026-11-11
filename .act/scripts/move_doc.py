#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Moves a document (a file, or a folder with everything in it) below docs/ to a new place and
#          pulls the references along, so a reorganisation of the project docs is never a hand edit
#          (step "Structure" of the skill act-audit-docs, rule R-docs-order). What it does:
#            1. Plans first: lists the move, every file whose references it would rewrite and every
#               line it would move between index files. Writes nothing without --apply.
#            2. Moves the file or folder (os.replace; the destination must not exist, its folder is
#               created). Nothing under docs/ai/ is moved and nothing outside docs/.
#            3. Rewrites relative Markdown links and <img src> targets in every Markdown file under
#               docs/ (docs/ai/work/ledger/ and docs/ai/work/archive/ excepted: the journal keeps old
#               paths) and in the Markdown files at the project root, outside code blocks and code
#               spans. A moved file's own relative links are recomputed for its new folder.
#            4. Replaces the project-relative path of the old place (docs/project/old.md, also as a
#               prefix of a longer path) in the Markdown files under docs/, code spans included. The
#               Markdown files at the project root (CHANGELOG.md ...) keep their historic paths.
#            5. Moves the index line: the one line in the old folder's README.md that names the old
#               name goes to the README.md of the new folder (after its last index line), renamed and with
#               its links recomputed for the new folder; for a rename inside one folder it changes in
#               place. A line it cannot place is reported.
#            6. Prints what it could not know: other files that still contain the bare file name, and a
#               file that is not UTF-8 and names the file (it is never touched).
#          A byte order mark and the line endings of a file stay as they are. The tool stages nothing; stage
#          the old path and the new path and every file it prints, then run doctor.py. Stdlib only; reads
#          entries.py from beside it for the link rewriting.
#
# Usage:
#   python .act/scripts/move_doc.py <from> <to>            # plan, writes nothing
#   python .act/scripts/move_doc.py <from> <to> --apply    # do it
#   (paths relative to the project root, or to --root <dir>; `--root` defaults to the current folder)
#
# Exit code: 0 done or planned, 2 refused (source missing, destination exists, outside docs/, docs/ai/)
# - never a traceback.

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Optional

sys.dont_write_bytecode = True  # no cache folder beside the scripts
sys.path.insert(0, str(Path(__file__).resolve().parent))

import entries  # noqa: E402  (needs the path line above)

JOURNAL_DIRS = ("docs/ai/work/ledger", "docs/ai/work/archive")


class MoveError(Exception):
    """A refusal raised before anything is written."""


def _posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _resolve(root: Path, raw: str) -> Path:
    path = Path(raw.strip().replace("\\", "/"))
    path = path if path.is_absolute() else root / path
    return Path(os.path.normpath(path))


def _check_places(root: Path, source: Path, dest: Path) -> None:
    docs = root / "docs"
    for label, path in (("from", source), ("to", dest)):
        try:
            rel = path.relative_to(docs)
        except ValueError:
            raise MoveError(f"{label}: {path} is not below docs/") from None
        if not rel.parts or rel.parts[0] == "ai":
            raise MoveError(f"{label}: {_posix(path, root)} is {'docs/ itself' if not rel.parts else 'under docs/ai/'}"
                            " — documents there have their own tools (entries.py)")
    if not source.exists():
        raise MoveError(f"from: {_posix(source, root)} does not exist")
    if dest.exists():
        raise MoveError(f"to: {_posix(dest, root)} exists already — nothing is overwritten")
    if source.is_dir() and (dest == source or source in dest.parents):
        raise MoveError("to: a folder cannot move into itself")


def _markdown_files(root: Path) -> list[Path]:
    found = sorted(path for path in root.glob("*.md") if path.is_file())
    docs = root / "docs"
    journal = [root / rel for rel in JOURNAL_DIRS]
    for path in sorted(docs.rglob("*.md")):
        if path.is_file() and not any(folder in path.parents for folder in journal):
            found.append(path)
    return found


def _read(path: Path) -> Optional[str]:
    try:
        # no "utf-8-sig": a byte order mark stays in the text and is written back; line endings stay as they are
        with open(path, encoding="utf-8", newline="") as handle:
            return handle.read()
    except (OSError, UnicodeDecodeError):
        return None


def _mapping(source: Path, dest: Path) -> dict[Path, Path]:
    """Old file path -> new file path for everything the move carries."""
    if source.is_file():
        return {source: dest}
    return {path: dest / path.relative_to(source) for path in sorted(source.rglob("*")) if path.is_file()}


def _new_target(old_resolved: Path, moved: dict[Path, Path], source: Path, dest: Path) -> Optional[Path]:
    """Where a link target ends up: a moved file, a moved folder or a file below it; None if it stays."""
    if old_resolved in moved:
        return moved[old_resolved]
    if source.is_dir() and (old_resolved == source or source in old_resolved.parents):
        return dest / old_resolved.relative_to(source)
    return None


def _path_pattern(old_rel: str) -> "re.Pattern[str]":
    return re.compile(r"(?<![\w./\-])" + re.escape(old_rel) + r"(?![\w\-]|\.\w)")


def _rewrite_text(text: str, file_old: Path, file_new: Path, moved: dict[Path, Path], source: Path, dest: Path,
                  root: Path, old_rel: str, new_rel: str, paths: bool = True) -> str:
    """`text` of a file (that lived at file_old and lives at file_new) with links and paths followed;
    `paths` False leaves the written project-relative paths alone (a historic file)."""

    def mapper(_target: str, resolved: Path) -> Optional[str]:
        goal = _new_target(resolved, moved, source, dest)
        moved_self = file_new != file_old
        if goal is None and not moved_self:
            return None
        goal = goal if goal is not None else resolved
        rel = os.path.relpath(goal, file_new.parent).replace("\\", "/")
        return rel

    text = entries._rewrite_links(text, file_old.parent, mapper)
    if not paths:
        return text
    pattern = _path_pattern(old_rel)
    return pattern.sub(new_rel, text)


def _name_pattern(name: str, folder: bool = False) -> "re.Pattern[str]":
    """The name as an index line spells it. A folder only as `name/` or in backticks: the plain word
    ("data as of ...") is not the folder."""
    quoted = re.escape(name)
    if folder:
        return re.compile(r"(?<![\w.\-/])" + quoted + r"(?=/)|(?<=`)" + quoted + r"(?=`)")
    return re.compile(r"(?<![\w.\-/])" + quoted + r"(?![\w\-])")


def _eol_of(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def _is_index_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") or bool(re.match(r"[-*+]\s", stripped))


def _plan_index(root: Path, source: Path) -> tuple[list[str], list[tuple[Path, str]]]:
    """(notes, edits): `edits` are (README.md path, the one index line naming the moved name); the notes
    tell of a README.md whose lines cannot be told apart."""
    notes: list[str] = []
    edits: list[tuple[Path, str]] = []
    old_readme = source.parent / "README.md"
    text = _read(old_readme) if old_readme.is_file() else None
    if text is None:
        return notes, edits
    pattern = _name_pattern(source.name, source.is_dir())
    hits = [line for line in text.split("\n") if _is_index_line(line) and pattern.search(line)]
    if len(hits) != 1:
        if hits:
            notes.append(f"{_posix(old_readme, root)} has {len(hits)} lines naming {source.name} — move them by hand")
        return notes, edits
    edits.append((old_readme, hits[0]))
    return notes, edits


def _move_index_line(texts: dict[Path, str], root: Path, source: Path, dest: Path, line: str,
                     notes: list[str], moved: dict[Path, Path], old_rel: str, new_rel: str) -> None:
    """Take `line` out of the old folder's README.md text and put it, renamed and with its links
    recomputed for the new folder, into the new folder's."""
    old_readme = source.parent / "README.md"
    new_readme = dest.parent / "README.md"
    # links first (every one of them, for the folder the line lands in), then the name wherever it stands
    new_line = _rewrite_text(line, old_readme, new_readme, moved, source, dest, root, old_rel, new_rel)
    new_line = _name_pattern(source.name, source.is_dir()).sub(dest.name, new_line)
    if old_readme == new_readme:
        texts[old_readme] = texts[old_readme].replace(line, new_line, 1)
        return
    lines = texts[old_readme].split("\n")
    lines.remove(line)
    texts[old_readme] = "\n".join(lines)
    if new_readme not in texts:
        notes.append(f"{_posix(new_readme, root)} does not exist — the index line for {dest.name} is: {new_line.strip()}")
        return
    eol = _eol_of(texts[new_readme])  # the line takes the line ending of the file it lands in
    new_line = new_line.rstrip("\r") + ("\r" if eol == "\r\n" else "")
    new_lines = texts[new_readme].split("\n")
    last = max((i for i, item in enumerate(new_lines) if _is_index_line(item)), default=None)
    if last is None:
        new_lines.extend([eol[:-1] if eol == "\r\n" else "", new_line])
    else:
        new_lines.insert(last + 1, new_line)
    texts[new_readme] = "\n".join(new_lines)


def move(root: Path, raw_from: str, raw_to: str, apply: bool) -> int:
    source, dest = _resolve(root, raw_from), _resolve(root, raw_to)
    try:
        _check_places(root, source, dest)
    except MoveError as error:
        print(f"move_doc: refused — {error}", file=sys.stderr)
        return 2
    moved = _mapping(source, dest)
    old_rel, new_rel = _posix(source, root), _posix(dest, root)
    verb = "moved" if apply else "would move"
    print(f"move_doc: {verb} {old_rel}{'/' if source.is_dir() else ''} -> {new_rel}{'/' if source.is_dir() else ''}")

    originals: dict[Path, str] = {}
    unreadable: list[str] = []  # not UTF-8: left alone, named when they mention the file
    for path in _markdown_files(root):
        text = _read(path)
        if text is not None:
            originals[path] = text
            continue
        try:
            raw = path.read_bytes()
        except OSError:
            raw = b""
        if source.name.encode("utf-8") in raw or old_rel.encode("utf-8") in raw:
            unreadable.append(_posix(path, root))
    texts = dict(originals)
    notes, index_edits = _plan_index(root, source)
    for readme, line in index_edits:
        _move_index_line(texts, root, source, dest, line, notes, moved, old_rel, new_rel)
    notes += [f"{item} is not UTF-8 and names {source.name} — check it" for item in unreadable]
    changes: list[tuple[Path, Path, str]] = []  # (old path of the file, new path, new text)
    for path, text in texts.items():
        new_path = moved.get(path, path)
        historic = path.parent == root  # CHANGELOG.md and the like keep the paths they wrote down
        new_text = _rewrite_text(text, path, new_path, moved, source, dest, root, old_rel, new_rel, paths=not historic)
        if new_text != originals[path]:
            changes.append((path, new_path, new_text))

    for path, new_path, _text in changes:
        print(f"  references or index: {_posix(new_path if apply else path, root)}")
    for readme, line in index_edits:
        print(f"  index line: {_posix(readme, root)}: {line.strip()[:100]}")

    if apply:
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, dest)
        for _old, new_path, new_text in changes:
            with open(new_path, "w", encoding="utf-8", newline="") as handle:  # BOM and line endings as read
                handle.write(new_text)

    final = dict(originals)
    for old_path, _new_path, new_text in changes:
        final[old_path] = new_text
    bare: list[str] = []
    # the bare name: not part of a longer path, so a rewritten link or path no longer counts
    pattern = re.compile(r"(?<![\w.\-/])(?<!\]\()(?<!\]\(<)" + re.escape(source.name) + r"(?![\w\-])")
    for path, text in final.items():
        if path not in moved and pattern.search(text):
            bare.append(_posix(path, root))
    for note in notes:
        print(f"  by hand: {note}")
    for item in bare[:20]:
        print(f"  by hand: {item} still names {source.name} without a folder — check it")
    print("move_doc: stage the old and the new path and every file listed above, then run doctor.py"
          if apply else "move_doc: nothing written — add --apply to do it")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Move a document below docs/ and pull its references along.")
    parser.add_argument("source", help="file or folder to move (project-relative)")
    parser.add_argument("dest", help="new path (project-relative); must not exist")
    parser.add_argument("--apply", action="store_true", help="do it; without it only the plan is printed")
    parser.add_argument("--root", default=".", help="project root (default: current folder)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    return move(Path(args.root).resolve(), args.source, args.dest, args.apply)


if __name__ == "__main__":
    try:
        from usage import count_script_run
        count_script_run(__file__)
    except ImportError:
        pass
    sys.exit(main(sys.argv[1:]))
