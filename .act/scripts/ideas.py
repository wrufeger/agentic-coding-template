#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: The per-person ideas file `docs/ai/concept/ideas-<identity>.md` — one versioned file for
#          every person on a project, written by that person as `## <title>` sections. This script
#          finds the entries that are new or changed since the assistant last processed the file
#          (a content hash per entry, kept in .act-local/ideas-seen.json, per checkout), records the
#          file as processed, and creates a missing file (and the folder's README.md) for the
#          session owner. The session start (hooks/checks/session.py) and init.py call the
#          functions below; every function takes the project root explicitly, so a run from another
#          working directory (init.py --target) never touches the wrong project. Stdlib plus actlib.
#
# Usage:
#   python .act/scripts/ideas.py            # same as --check
#   python .act/scripts/ideas.py --check    # list entries that are new or changed
#   python .act/scripts/ideas.py --seen     # record the current state of every entry as processed
#   python .act/scripts/ideas.py --ensure   # create the README.md and the own ideas file if missing
#
# Output format (every line goes to stdout unless noted; exit codes in brackets):
#   --check:  ideas: <rel path> — N new or changed: "A", "B"     (at most 5 titles, cut at 60 chars)  [0]
#             ideas: <rel path> — nothing new                                                           [0]
#   --seen:   ideas: <rel path> — N new or changed recorded as processed: "A", "B" (M entries in total) [0]
#             ideas: <rel path> — nothing new (M entries in total)                                      [0]
#             (N and the titles are what --check would have reported just before)
#   --ensure: ideas: created <rel path>   one line per file created                                     [0]
#             ideas: nothing to create                                                                  [0]
#             nothing is created unless docs/ai/config.md exists (a project, not the template itself).
#   No file yet (--check/--seen):
#             ideas: <rel path> — no such file (python .act/scripts/ideas.py --ensure creates it)
#             exit 0 for --check, exit 1 for --seen.
#   No identity (.act-local/identity.json missing or without "identity"): one line on stderr
#             "ideas: no identity in .act-local/identity.json — nothing to check";
#             exit 0 for --check, exit 1 for --seen and --ensure.
#   No project root: one line on stderr "ideas: <reason>", exit 1.
#   State: .act-local/ideas-seen.json as {"files": {"<rel path>": {"<entry key>": "<hash>"}}}, one
#   record per ideas file; the older one-file form {"file", "entries"} is still read.

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Optional

import actlib

IDEAS_DIR = "docs/ai/concept"
STATE_NAME = "ideas-seen.json"
README_NAME = "README.md"
START_MARK = "<!-- act:ideas-start -->"
DEFAULT_MARK = "<!-- act:default -->"
PREAMBLE_LABEL = "(text above the first entry)"
MAX_TITLES = 5
TITLE_WIDTH = 60

_HEADING_RE = re.compile(r"^## (\S.*?)\s*$")
_FALLBACK_TEXT = (
    "# Ideas — {identity}\n\n"
    "Your own ideas, wishes and concept notes for this project, one `## <title>` section each — only\n"
    "you write entries here. The next session start picks up what is new or changed.\n\n"
    "---\n"
)


# ---------------------------------------------------------------------------
# Locating the file
# ---------------------------------------------------------------------------

def identity(root: Path) -> Optional[str]:
    """The "identity" field of root/.act-local/identity.json, or None (missing, unreadable, empty)."""
    try:
        data = json.loads((root / ".act-local" / "identity.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = data.get("identity") if isinstance(data, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def own_file(root: Path, identity_name: Optional[str] = None) -> Optional[Path]:
    """root/docs/ai/concept/ideas-<identity_slug>.md for the given or the recorded identity."""
    name = identity_name if identity_name else identity(root)
    if not name:
        return None
    return root / IDEAS_DIR / f"ideas-{actlib.identity_slug(name)}.md"


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


# ---------------------------------------------------------------------------
# Entries and their hashes
# ---------------------------------------------------------------------------

def _normalize(lines: list[str]) -> str:
    """Lines rstripped, leading and trailing blank lines dropped, joined with LF."""
    cleaned = [line.rstrip() for line in lines]
    while cleaned and not cleaned[0]:
        cleaned.pop(0)
    while cleaned and not cleaned[-1]:
        cleaned.pop()
    return "\n".join(cleaned)


def _hash(lines: list[str]) -> str:
    return hashlib.sha256(_normalize(lines).encode("utf-8")).hexdigest()[:16]


_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def _split(lines: list[str], use_fences: bool) -> tuple[list[tuple[Optional[str], list[str]]], bool]:
    """(blocks as (title, lines) with title None for the preamble, whether a fence was still open
    at the end). A fence follows CommonMark: opened by 3+ backticks or tildes indented at most 3
    spaces, closed only by a bare fence of the same character at least as long."""
    blocks: list[tuple[Optional[str], list[str]]] = [(None, [])]
    fence_char = ""
    fence_len = 0
    for line in lines:
        if use_fences:
            if fence_char:
                closer = re.match(r"^ {0,3}(" + re.escape(fence_char) + r"{" + str(fence_len) + r",})\s*$", line)
                if closer:
                    fence_char, fence_len = "", 0
                blocks[-1][1].append(line)
                continue
            opener = _FENCE_OPEN_RE.match(line)
            if opener and not (opener.group(1)[0] == "`" and "`" in opener.group(2)):
                fence_char, fence_len = opener.group(1)[0], len(opener.group(1))
                blocks[-1][1].append(line)
                continue
        match = _HEADING_RE.match(line)
        if match:
            blocks.append((match.group(1), [line]))
        else:
            blocks[-1][1].append(line)
    return blocks, bool(fence_char)


def sections(text: str) -> list[tuple[str, str]]:
    """(key, hash) for the preamble (key "") and for every level-2 heading outside a code fence.
    A `###` heading belongs to its parent entry. A repeated title gets " #2", " #3" — skipping any
    number that is itself the literal title of another entry, so no two keys are ever equal. A
    fence still open at the end of the file is ignored (an unclosed fence hides nothing)."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff").split("\n")
    blocks, unclosed = _split(lines, True)
    if unclosed:
        blocks, _again = _split(lines, False)
    literal = {title for title, _body in blocks if title is not None}
    used: set[str] = set()
    result: list[tuple[str, str]] = []
    for title, body in blocks:
        if title is None:
            result.append(("", _hash(body)))
            continue
        key = title
        if key in used:
            number = 2
            key = f"{title} #{number}"
            while key in used or key in literal:
                number += 1
                key = f"{title} #{number}"
        used.add(key)
        result.append((key, _hash(body)))
    return result


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Processed state
# ---------------------------------------------------------------------------

def _state_path(root: Path) -> Path:
    return root / ".act-local" / STATE_NAME


def _load_all_state(root: Path) -> dict[str, dict[str, str]]:
    """Every recorded file: {rel path: {key: hash}}. Reads the current form {"files": {...}} and the
    older one-file form {"file": ..., "entries": ...}; anything unreadable counts as empty."""
    try:
        data = json.loads(_state_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    files: dict[str, dict[str, str]] = {}
    raw = data.get("files")
    if isinstance(raw, dict):
        for rel, entries in raw.items():
            if isinstance(entries, dict):
                files[str(rel)] = {str(key): str(value) for key, value in entries.items()}
    elif isinstance(data.get("file"), str) and isinstance(data.get("entries"), dict):
        files[data["file"]] = {str(key): str(value) for key, value in data["entries"].items()}
    return files


def _load_state(root: Path, rel: str) -> dict[str, str]:
    """The recorded hashes for `rel`; empty if nothing is recorded for that file."""
    return _load_all_state(root).get(rel, {})


def _new_or_changed(pairs: list[tuple[str, str]], recorded: dict[str, str]) -> list[str]:
    """Keys that are new or changed against `recorded`. The preamble counts only when it changed
    (never on the first record), shown as PREAMBLE_LABEL; an entry removed from the file never counts."""
    found: list[str] = []
    for key, digest in pairs:
        if key == "":
            if "" in recorded and recorded[""] != digest:
                found.append(PREAMBLE_LABEL)
        elif recorded.get(key) != digest:
            found.append(key)
    return found


def pending(root: Path) -> tuple[Optional[Path], list[str]]:
    """(own file, keys of the entries new or changed since the last --seen)."""
    path = own_file(root)
    if path is None or not path.is_file():
        return path, []
    text = _read(path)
    if text is None:
        return path, []
    return path, _new_or_changed(sections(text), _load_state(root, _rel(root, path)))


def mark_seen(root: Path) -> tuple[list[str], int]:
    """Record the current hash of every entry (and the preamble) of the own file as processed.
    Returns (keys that were new or changed — what pending() reported just before, total number of
    entries, the preamble not counted); ([], 0) when there is no file."""
    path = own_file(root)
    if path is None or not path.is_file():
        return [], 0
    text = _read(path)
    if text is None:
        return [], 0
    rel = _rel(root, path)
    pairs = sections(text)
    processed = _new_or_changed(pairs, _load_state(root, rel))
    files = _load_all_state(root)
    files[rel] = dict(pairs)
    target = _state_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"files": files}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return processed, sum(1 for key, _digest in pairs if key != "")


def titles_text(keys: list[str]) -> str:
    """`"A", "B"` — at most MAX_TITLES titles, each cut to TITLE_WIDTH characters, "…" for more."""
    shown = []
    for key in keys[:MAX_TITLES]:
        cut = key if len(key) <= TITLE_WIDTH else key[: TITLE_WIDTH - 1] + "…"
        shown.append(f'"{cut}"')
    text = ", ".join(shown)
    return text + ", …" if len(keys) > MAX_TITLES else text


# ---------------------------------------------------------------------------
# Creating what is missing
# ---------------------------------------------------------------------------

def _skeleton_readme(root: Path) -> Optional[Path]:
    """The template's folder README: a project override wins over the shipped skeleton."""
    for candidate in (root / "docs" / "ai" / "local" / "skeleton" / "concept" / README_NAME,
                      root / ".act" / "skeleton" / "concept" / README_NAME):
        if candidate.is_file():
            return candidate
    return None


def _starting_text(readme_text: str) -> Optional[str]:
    """The first fenced block after START_MARK, fence lines excluded; None if there is none."""
    lines = readme_text.replace("\r\n", "\n").split("\n")
    try:
        index = lines.index(START_MARK)
    except ValueError:
        return None
    fence: Optional[str] = None
    body: list[str] = []
    for line in lines[index + 1:]:
        stripped = line.strip()
        if fence is None:
            if stripped[:3] in ("```", "~~~"):
                fence = stripped[:3]
            continue
        if stripped.startswith(fence):
            return "\n".join(body).rstrip("\n") + "\n"
        body.append(line)
    return None


def ensure(root: Path, identity_name: Optional[str] = None, plan: bool = False,
           skip_config_gate: bool = False) -> list[tuple[Path, str]]:
    """Create the folder README.md and the own ideas file where missing — only in a project
    (docs/ai/config.md exists), never overwriting. Returns (path, kind) with kind "readme" or
    "ideas" for each file created, or that would be with `plan`. A new ideas file is recorded as
    processed at once so the session start does not report the starting text as new. When the
    folder README still carries the `act:default` mark and `language-docs` is not English, the
    new file carries it too, so the one-time scaffold translation lists it. `skip_config_gate`
    drops the docs/ai/config.md requirement — for init's plan run on a project not yet created;
    the session start never sets it."""
    if not skip_config_gate and not (root / "docs" / "ai" / "config.md").is_file():
        return []
    name = identity_name if identity_name else identity(root)
    if not name:
        return []
    created: list[tuple[Path, str]] = []
    readme = root / IDEAS_DIR / README_NAME
    source = _skeleton_readme(root)
    if not readme.exists() and (source is not None or plan):
        created.append((readme, "readme"))
        if not plan and source is not None:
            actlib.write_text_lf(readme, source.read_text(encoding="utf-8").replace("\r\n", "\n"))
    path = own_file(root, name)
    if path is not None and not path.exists():
        created.append((path, "ideas"))
        if not plan:
            template = None
            readme_source = readme if readme.is_file() else source
            default_mark = False
            if readme_source is not None:
                readme_text = readme_source.read_text(encoding="utf-8")
                template = _starting_text(readme_text)
                first_line = readme_text.replace("\r\n", "\n").split("\n", 1)[0]
                default_mark = actlib._DEFAULT_MARK_RE.match(first_line) is not None
            text = (template or _FALLBACK_TEXT).replace("{identity}", name)
            if template and default_mark:
                docs_language = actlib.language_settings(actlib.read_config(root))[1]
                if not actlib.is_english(docs_language):
                    text = DEFAULT_MARK + "\n" + text
            actlib.write_text_lf(path, text)
            mark_seen(root)
    return created


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _run_cli(root: Path, mode: str) -> int:
    if identity(root) is None:
        print("ideas: no identity in .act-local/identity.json — nothing to check", file=sys.stderr)
        return 0 if mode == "check" else 1
    if mode == "ensure":
        made = ensure(root)
        for path, _kind in made:
            print(f"ideas: created {_rel(root, path)}")
        if not made:
            print("ideas: nothing to create")
        return 0
    path = own_file(root)
    rel = _rel(root, path) if path else ""
    if path is None or not path.is_file():
        print(f"ideas: {rel} — no such file (python .act/scripts/ideas.py --ensure creates it)")
        return 0 if mode == "check" else 1
    if mode == "seen":
        processed, total = mark_seen(root)
        if processed:
            print(f"ideas: {rel} — {len(processed)} new or changed recorded as processed: "
                  f"{titles_text(processed)} ({total} entries in total)")
        else:
            print(f"ideas: {rel} — nothing new ({total} entries in total)")
        return 0
    _path, keys = pending(root)
    if keys:
        print(f"ideas: {rel} — {len(keys)} new or changed: {titles_text(keys)}")
    else:
        print(f"ideas: {rel} — nothing new")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Entries of the per-person ideas file that are new or changed since they were last processed.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="list new or changed entries (default)")
    group.add_argument("--seen", action="store_true", help="record every entry as processed")
    group.add_argument("--ensure", action="store_true", help="create the README.md and own file if missing")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    try:
        root = actlib.repo_root()
    except RuntimeError as exc:
        print(f"ideas: {exc}", file=sys.stderr)
        return 1
    mode = "seen" if args.seen else "ensure" if args.ensure else "check"
    return _run_cli(root, mode)


if __name__ == "__main__":
    sys.exit(main())
