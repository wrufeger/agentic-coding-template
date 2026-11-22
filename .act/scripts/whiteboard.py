#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: The per-person whiteboard `docs/ai/whiteboard-<identity>.md` — one versioned file for every
#          person on a project, written by that person as `## <kind>: <title>` sections (kinds: idea,
#          bug, note, reminder on a date, reminder on an event; no kind means idea). This script finds
#          what the assistant has to look at: the entries that are new or changed since it last
#          processed the file (a content hash per entry, kept in .act-local/whiteboard-seen.json, per
#          checkout), the date reminders that are due, and the event reminders to check. It records the
#          file as processed, and creates a missing file (and the README.md beside it) for the session
#          owner. A note is never reported. The session start (hooks/checks/session.py) and init.py call
#          the functions below; every function takes the project root explicitly, so a run from another
#          working directory (init.py --target) never touches the wrong project. Stdlib plus actlib.
#
# Usage:
#   python .act/scripts/whiteboard.py            # same as --check
#   python .act/scripts/whiteboard.py --check    # list what is new or changed, due, or to check
#   python .act/scripts/whiteboard.py --seen     # record the current state of every entry as processed
#   python .act/scripts/whiteboard.py --ensure   # create docs/ai/README.md and the own whiteboard if missing
#
# Kinds, from the heading `## <Kind>[ <qualifier>]: <title>` (letter case does not matter, English or German;
# the colon belongs to it):
#   Idea / Idee, Bug     reported when new or changed, processed by the assistant
#   Note / Notiz         never reported, never processed
#   Reminder <YYYY-MM-DD>: / Erinnerung <YYYY-MM-DD>:
#                        not reported before that day (local date); from then on reported until --seen ran on or
#                        after that day (the day of the last --seen is kept per file); reported again when changed
#   Reminder after <event>: / Erinnerung nach <Ereignis>:
#                        reported for checking at every start until the entry leaves the file. A reminder whose
#                        qualifier is not a valid ISO date (`2026-13-01`, `01.12.2026`, none) counts as this kind.
#   anything else, no kind included = idea (a `Draft`/`Entwurf` marker in the heading is the assistant's business).
#   For idea, bug and note the kind word must stand alone before the colon (`Note to self: …` is an idea).
#
# Output format (every line goes to stdout unless noted; exit codes in brackets):
#   --check:  whiteboard: <rel path> — N new or changed: "A", "B"       (at most 5 titles, cut at 60 chars) [0]
#             whiteboard: <rel path> — N due: "Reminder 2026-12-01: x"                                      [0]
#             whiteboard: <rel path> — N to check: "Reminder after release: y"                              [0]
#             (each line only when it applies; none of them: the next line)
#             whiteboard: <rel path> — nothing new                                                          [0]
#   --seen:   whiteboard: <rel path> — N new, changed or due recorded as processed: "A", "B" (M entries in total) [0]
#             whiteboard: <rel path> — nothing new (M entries in total)                                     [0]
#             (N and the titles are what --check would have reported just before, without the to-check line)
#   --ensure: whiteboard: created <rel path>   one line per file created                                    [0]
#             whiteboard: nothing to create                                                                 [0]
#             nothing is created unless docs/ai/config.md exists (a project, not the template itself).
#   No file yet (--check/--seen):
#             whiteboard: <rel path> — no such file (python .act/scripts/whiteboard.py --ensure creates it)
#             exit 0 for --check, exit 1 for --seen.
#   No identity (.act-local/identity.json missing or without "identity"): one line on stderr
#             "whiteboard: no identity in .act-local/identity.json — nothing to check";
#             exit 0 for --check, exit 1 for --seen and --ensure.
#   No project root: one line on stderr "whiteboard: <reason>", exit 1.
#   State: .act-local/whiteboard-seen.json as {"files": {"<rel path>": {"<entry key>": "<hash>"}},
#   "seen": {"<rel path>": "<YYYY-MM-DD>"}}. Where it holds nothing for a file, the record of the former
#   ideas file (.act-local/ideas-seen.json, docs/ai/concept/ideas-<identity>.md) counts, so a moved file does not
#   show up as new.

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import NamedTuple, Optional

import actlib

WHITEBOARD_DIR = "docs/ai"
STATE_NAME = "whiteboard-seen.json"
LEGACY_STATE_NAME = "ideas-seen.json"
LEGACY_DIR = "docs/ai/concept"
README_NAME = "README.md"
START_MARK = "<!-- act:whiteboard-start -->"
DEFAULT_MARK = "<!-- act:default -->"
PREAMBLE_LABEL = "(text above the first entry)"
MAX_TITLES = 5
TITLE_WIDTH = 60

_HEADING_RE = re.compile(r"^## (\S.*?)\s*$")
_FALLBACK_TEXT = (
    "# Whiteboard — {identity}\n\n"
    "Your own ideas, bugs, notes and reminders for this project, one `## <kind>: <title>` section each —\n"
    "only you write entries here. The next session start picks up what is new, changed or due.\n\n"
    "---\n"
)
_KIND_RE = re.compile(r"^(idea|idee|bug|note|notiz|reminder|erinnerung)((?:\s[^:]*)?):", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_FILE_RE = re.compile(r"^docs/ai/whiteboard-(.+)\.md$")


class Pending(NamedTuple):
    """What the session start has to look at in the own whiteboard (keys are the heading texts)."""

    new: list[str]    # ideas, bugs and the like that are new or changed
    due: list[str]    # reminders on a date that are due and not handled yet
    check: list[str]  # reminders on an event, to check at every start

    def __bool__(self) -> bool:
        return bool(self.new or self.due or self.check)


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
    """root/docs/ai/whiteboard-<identity_slug>.md for the given or the recorded identity."""
    name = identity_name if identity_name else identity(root)
    if not name:
        return None
    return root / WHITEBOARD_DIR / f"whiteboard-{actlib.identity_slug(name)}.md"


def _legacy_rel(rel: str) -> Optional[str]:
    """The project-relative path the former ideas file of the whiteboard `rel` had."""
    match = _FILE_RE.match(rel)
    return f"{LEGACY_DIR}/ideas-{match.group(1)}.md" if match else None


# ---------------------------------------------------------------------------
# Entries, their kinds and their hashes
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


def classify(key: str) -> tuple[str, Optional[datetime.date]]:
    """(kind, date) of an entry from its heading text (a key of sections()): kind is "idea", "bug", "note",
    "reminder" (a date reminder, with its date) or "event" (a reminder on an event). The preamble is "idea"."""
    match = _KIND_RE.match(key.strip())
    if not match:
        return "idea", None
    word = match.group(1).lower()
    qualifier = match.group(2).strip()
    if word in ("reminder", "erinnerung"):
        if _ISO_DATE_RE.match(qualifier):
            try:
                return "reminder", datetime.date.fromisoformat(qualifier)
            except ValueError:
                pass
        return "event", None
    if qualifier:
        return "idea", None  # `Note to self: …` — a kind word with more words is not the kind
    return {"idea": "idea", "idee": "idea", "bug": "bug", "note": "note", "notiz": "note"}[word], None


def _read(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Processed state
# ---------------------------------------------------------------------------

def _state_path(root: Path, name: str = STATE_NAME) -> Path:
    return root / ".act-local" / name


def _load_state_file(path: Path) -> tuple[dict[str, dict[str, str]], dict[str, str]]:
    """({rel path: {key: hash}}, {rel path: seen date}) of one state file. Reads the form {"files": {...},
    "seen": {...}} and the older one-file form {"file": ..., "entries": ...}; anything unreadable counts
    as empty."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    if not isinstance(data, dict):
        return {}, {}
    files: dict[str, dict[str, str]] = {}
    raw = data.get("files")
    if isinstance(raw, dict):
        for rel, entries in raw.items():
            if isinstance(entries, dict):
                files[str(rel)] = {str(key): str(value) for key, value in entries.items()}
    elif isinstance(data.get("file"), str) and isinstance(data.get("entries"), dict):
        files[data["file"]] = {str(key): str(value) for key, value in data["entries"].items()}
    seen: dict[str, str] = {}
    raw_seen = data.get("seen")
    if isinstance(raw_seen, dict):
        seen = {str(rel): str(value) for rel, value in raw_seen.items() if _ISO_DATE_RE.match(str(value))}
    return files, seen


def _load_record(root: Path, rel: str) -> tuple[dict[str, str], Optional[datetime.date]]:
    """(recorded hashes, day of the last --seen) for `rel`. Where the state file holds nothing for it,
    the record of the former ideas file counts (hashes only: the old state knew no day)."""
    files, seen = _load_state_file(_state_path(root))
    if rel in files:
        day = None
        if rel in seen:
            try:
                day = datetime.date.fromisoformat(seen[rel])
            except ValueError:
                day = None
        return files[rel], day
    legacy = _legacy_rel(rel)
    if legacy is not None:
        old_files, _old_seen = _load_state_file(_state_path(root, LEGACY_STATE_NAME))
        if legacy in old_files:
            return old_files[legacy], None
    return {}, None


def _evaluate(pairs: list[tuple[str, str]], recorded: dict[str, str], seen_day: Optional[datetime.date],
              today: datetime.date) -> Pending:
    """What is new or changed against `recorded`, which date reminders are due, which event reminders
    stand. The preamble counts only when it changed (never on the first record), shown as PREAMBLE_LABEL;
    an entry removed from the file never counts; a note never counts."""
    new: list[str] = []
    due: list[str] = []
    check: list[str] = []
    for key, digest in pairs:
        if key == "":
            if "" in recorded and recorded[""] != digest:
                new.append(PREAMBLE_LABEL)
            continue
        kind, day = classify(key)
        if kind == "note":
            continue
        if kind == "event":
            check.append(key)
            continue
        if kind == "reminder":
            if day is not None and day <= today and (recorded.get(key) != digest or seen_day is None or seen_day < day):
                due.append(key)
            continue
        if recorded.get(key) != digest:
            new.append(key)
    return Pending(new, due, check)


def pending(root: Path, today: Optional[datetime.date] = None) -> tuple[Optional[Path], Pending]:
    """(own file, what is new or changed, due and to check since the last --seen)."""
    path = own_file(root)
    if path is None or not path.is_file():
        return path, Pending([], [], [])
    text = _read(path)
    if text is None:
        return path, Pending([], [], [])
    recorded, seen_day = _load_record(root, actlib.rel_posix(path, root))
    return path, _evaluate(sections(text), recorded, seen_day, today or datetime.date.today())


def mark_seen(root: Path, today: Optional[datetime.date] = None) -> tuple[list[str], int]:
    """Record the current hash of every entry (and the preamble) of the own file as processed, and the
    day. Returns (keys that were new, changed or due — what pending() reported just before without the
    event reminders, total number of entries, the preamble not counted); ([], 0) when there is no file."""
    path = own_file(root)
    if path is None or not path.is_file():
        return [], 0
    text = _read(path)
    if text is None:
        return [], 0
    day = today or datetime.date.today()
    rel = actlib.rel_posix(path, root)
    pairs = sections(text)
    recorded, seen_day = _load_record(root, rel)
    found = _evaluate(pairs, recorded, seen_day, day)
    files, seen = _load_state_file(_state_path(root))
    files[rel] = dict(pairs)
    seen[rel] = day.isoformat()
    target = _state_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    actlib.write_text_lf(target, json.dumps({"files": files, "seen": seen}, ensure_ascii=False, indent=2) + "\n")
    return found.new + found.due, sum(1 for key, _digest in pairs if key != "")


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
    """The template's README for docs/ai/: a project override wins over the shipped skeleton."""
    for candidate in (root / "docs" / "ai" / "local" / "skeleton" / README_NAME,
                      root / ".act" / "skeleton" / README_NAME):
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
    """Create docs/ai/README.md and the own whiteboard where missing — only in a project
    (docs/ai/config.md exists), never overwriting. Returns (path, kind) with kind "readme" or
    "whiteboard" for each file created, or that would be with `plan`. A new whiteboard is recorded as
    processed at once so the session start does not report the starting text as new. When the
    README still carries the `act:default` mark and `language-docs` is not English, the
    new file carries it too, so the one-time scaffold translation lists it. `skip_config_gate`
    drops the docs/ai/config.md requirement — for init's plan run on a project not yet created;
    the session start never sets it."""
    if not skip_config_gate and not (root / "docs" / "ai" / "config.md").is_file():
        return []
    name = identity_name if identity_name else identity(root)
    if not name:
        return []
    created: list[tuple[Path, str]] = []
    readme = root / WHITEBOARD_DIR / README_NAME
    source = _skeleton_readme(root)
    if not readme.exists() and (source is not None or plan):
        created.append((readme, "readme"))
        if not plan and source is not None:
            actlib.write_text_lf(readme, source.read_text(encoding="utf-8").replace("\r\n", "\n"))
    path = own_file(root, name)
    if path is not None and not path.exists():
        created.append((path, "whiteboard"))
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


def append_section(root: Path, title: str, text: str) -> Path:
    """Append `## <title>` plus `text` (verbatim) as a new section at the end of the session
    owner's whiteboard and return that file. The file is read again right before writing, and
    created first (ensure()) when missing. The section stays unseen, so the next session start
    reports it like any entry the owner typed. Raises ValueError without an identity; OSError
    from the file system passes through."""
    name = identity(root)
    if not name:
        raise ValueError("no identity in .act-local/identity.json")
    path = own_file(root, name)
    if path is None:
        raise ValueError("no whiteboard path")
    if not path.exists():
        ensure(root)
    if path.exists():
        current = path.read_text(encoding="utf-8")
    else:  # no docs/ai/config.md yet (ensure() only works in a project): start the file by hand
        current = _FALLBACK_TEXT.replace("{identity}", name)
    current = current.rstrip("\n")
    body = text.strip("\n")
    actlib.write_text_lf(path, f"{current}\n\n## {title.strip()}\n" + (f"\n{body}\n" if body else ""))
    return path


def rename_whiteboard(root: Path, previous: str, new: str) -> Optional[tuple[str, str, bool]]:
    """After an identity change: move the whiteboard of the former identity to the new name, together with
    its record of what was processed. Returns None when the former identity has no whiteboard, else
    (old rel path, new rel path, moved) — moved False when the new name is taken or a link stands in the
    way: nothing is touched then, and the caller says so."""
    old_path = own_file(root, previous)
    new_path = own_file(root, new)
    if old_path is None or new_path is None or not old_path.is_file():
        return None
    old_rel, new_rel = actlib.rel_posix(old_path, root), actlib.rel_posix(new_path, root)
    if old_rel == new_rel:
        return None
    if new_path.exists() or actlib.link_problem(root, old_path) or actlib.link_problem(root, new_path):
        return old_rel, new_rel, False
    old_path.replace(new_path)
    files, seen = _load_state_file(_state_path(root))
    if old_rel in files:
        files[new_rel] = files.pop(old_rel)
        if old_rel in seen:
            seen[new_rel] = seen.pop(old_rel)
        actlib.write_text_lf(_state_path(root),
                             json.dumps({"files": files, "seen": seen}, ensure_ascii=False, indent=2) + "\n")
    return old_rel, new_rel, True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _run_cli(root: Path, mode: str) -> int:
    if identity(root) is None:
        print("whiteboard: no identity in .act-local/identity.json — nothing to check", file=sys.stderr)
        return 0 if mode == "check" else 1
    if mode == "ensure":
        made = ensure(root)
        for path, _kind in made:
            print(f"whiteboard: created {actlib.rel_posix(path, root)}")
        if not made:
            print("whiteboard: nothing to create")
        return 0
    path = own_file(root)
    rel = actlib.rel_posix(path, root) if path else ""
    if path is None or not path.is_file():
        print(f"whiteboard: {rel} — no such file (python .act/scripts/whiteboard.py --ensure creates it)")
        return 0 if mode == "check" else 1
    if mode == "seen":
        processed, total = mark_seen(root)
        if processed:
            print(f"whiteboard: {rel} — {len(processed)} new, changed or due recorded as processed: "
                  f"{titles_text(processed)} ({total} entries in total)")
        else:
            print(f"whiteboard: {rel} — nothing new ({total} entries in total)")
        return 0
    _path, found = pending(root)
    if found.new:
        print(f"whiteboard: {rel} — {len(found.new)} new or changed: {titles_text(found.new)}")
    if found.due:
        print(f"whiteboard: {rel} — {len(found.due)} due: {titles_text(found.due)}")
    if found.check:
        print(f"whiteboard: {rel} — {len(found.check)} to check: {titles_text(found.check)}")
    if not found:
        print(f"whiteboard: {rel} — nothing new")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Entries of the per-person whiteboard that are new or changed, due or to check since "
                    "they were last processed.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="list new, changed, due and to-check entries (default)")
    group.add_argument("--seen", action="store_true", help="record every entry as processed")
    group.add_argument("--ensure", action="store_true", help="create docs/ai/README.md and the own whiteboard if missing")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    try:
        root = actlib.repo_root()
    except RuntimeError as exc:
        print(f"whiteboard: {exc}", file=sys.stderr)
        return 1
    mode = "seen" if args.seen else "ensure" if args.ensure else "check"
    return _run_cli(root, mode)


if __name__ == "__main__":
    try:
        from usage import count_script_run
        count_script_run(__file__)
    except ImportError:
        pass
    sys.exit(main())
