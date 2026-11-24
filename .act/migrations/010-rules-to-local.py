#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Moves the project's rule file docs/ai/rules.md to docs/ai/local/rules.md, next to the project's other own
#          files, and points CLAUDE.md, AGENTS.md and .gitattributes at the new place.
#          What this does (read and written as bytes, so encoding, BOM and every line ending stay):
#            1. docs/ai/rules.md exists and docs/ai/local/rules.md does not: the file moves. Each import line (the
#               lines rules.py reads as imports) with a relative path is read from docs/ai/ and rewritten for
#               docs/ai/local/, only when its target exists (also for a path that leaves the project); one whose
#               target does not exist stays as it is and is named ("import line <n> not rewritten: <path>"), an
#               absolute or ~ path stays silently.
#               A BOM before an import on line 1 stays and does not hide it. The sentence of the template's rule file
#               that says how imports resolve is brought to the new place when it stands there word for word. Every other line stays
#               byte for byte: own rules, checkboxes, `replaces` lines, the blocks of installed packages apart from their import lines. The
#               new file is written, read back, and only then is the old one deleted.
#            2. Both files exist: nothing is moved or edited anywhere; the description says to merge them by hand
#               and delete docs/ai/rules.md. Neither exists: nothing to move.
#            3. Moved, or neither file present: every docs/ai/rules.md in CLAUDE.md and AGENTS.md becomes
#               docs/ai/local/rules.md (an edited CLAUDE.md that kept the old import would load no rules at all),
#               and a line of .gitattributes for the old path is written for the new one. Other tracked text files
#               that still name docs/ai/rules.md are not edited; up to ten of them are named.
#            4. .act-local/cache.json § generated: the record of docs/ai/rules.md moves to the new key. A file that
#               still matched its record before the move gets the hash of what it is now, so it stays "generated"
#               and the session start re-derives it from the template; an edited one keeps a record that no
#               longer matches. CLAUDE.md and AGENTS.md likewise. .act-lock.json § bridges_applied: the
#               .gitattributes line for the old path is entered for the new one.
#          The way back is the update's own commit: `git revert <that commit>` brings back the old file and the
#          old CLAUDE.md, AGENTS.md and .gitattributes. A rule file with changes that were not committed is moved
#          all the same; the update then leaves it and its old place out of its commit (see update.py).
#          A file or folder on the way that is a symbolic link or a Windows junction is never touched: the
#          description names it. plan() only reads; apply() reports what it did. A second run finds nothing.
#
# Contract (.act/scripts/update.py step 8): plan(root) -> str, apply(root) -> (str, list[str]) of project-relative
# paths (posix separators) touched, deleted and created ones alike (the update commits by those paths). `EARLY =
# True` makes the update run this migration before any step that reads or writes the project's rule files. Stdlib
# only, except that the import lines are found with rules.py of the project's own .act/ (loaded below, shipped
# together with this file) and the link test lives in the sibling file _links.py.

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

EARLY = True

OLD = "docs/ai/rules.md"
NEW = "docs/ai/local/rules.md"
CLAUDE = "CLAUDE.md"
AGENTS = "AGENTS.md"
ATTRIBUTES = ".gitattributes"
CACHE = ".act-local/cache.json"
LOCK = ".act-lock.json"
# the first comment line of the template's .gitattributes block names the file; its old and its new wording
COMMENT_OLD = "# Generated bridges: CLAUDE.md, AGENTS.md, and docs/ai/rules.md are"
COMMENT_NEW = "# Generated bridges: CLAUDE.md, AGENTS.md, and docs/ai/local/rules.md are"
# how the template's rule file says imports resolve: the old sentence and the one that replaces it
SENTENCE_OLD = "Imports resolve relative to this file (`docs/ai/`), hence the `../../`."
SENTENCE_NEW = "Imports resolve relative to this file (`docs/ai/local/`), hence the `../../../`."
BOTH_EXIST = f"both {OLD} and {NEW} exist; merge them by hand and delete {OLD}"
SHOWN_MAX = 10
SCAN_MAX_BYTES = 1_000_000
# what is not scanned for the old name: the template's own files and their copies, and the history
SCAN_SKIP = (".act/", ".claude/", ".agents/", ".github/agents/", ".github/skills/", "docs/ai/work/archive/",
             "docs/ai/work/ledger")


def _load_links():
    """The sibling _links.py (link test and safe writes), loaded by file name."""
    spec = importlib.util.spec_from_file_location("_act_migration_links", Path(__file__).with_name("_links.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_LINKS = _load_links()


def _load_rules(root: Path):
    """rules.py of the project's own .act/ (the new one: update.py has replaced .act/ before it runs a migration),
    under a name of its own so it never replaces a module a running script holds."""
    scripts = root / ".act" / "scripts"
    path = scripts / "rules.py"
    spec = importlib.util.spec_from_file_location("_act_migration_rules", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"010-rules-to-local: cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    added = str(scripts) not in sys.path
    if added:
        sys.path.insert(0, str(scripts))
    sys.modules[spec.name] = module  # its dataclasses look their own module up while it is being executed
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - named, and the update stops here: it can be run again
        raise RuntimeError(f"010-rules-to-local: {path} cannot be loaded ({exc.__class__.__name__}: {exc})") from exc
    finally:
        sys.modules.pop(spec.name, None)
        if added:
            sys.path.remove(str(scripts))
    return module


def _read(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except OSError:
        return None


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _folded(data: bytes) -> bytes:
    """`data` with CRLF folded to LF, unless it holds a NUL byte (what actlib.normalized_sha256 hashes)."""
    return data if b"\x00" in data else data.replace(b"\r\n", b"\n")


def _matches_record(data: bytes, recorded: str) -> bool:
    """Whether `data` is what .act-local/cache.json § generated recorded: its normalized hash, or the raw one or
    the CRLF form of the folded bytes (older records), as actlib.generated_unchanged accepts."""
    if not recorded:
        return False
    folded = _folded(data)
    return recorded in (_sha(folded), _sha(data), _sha(folded.replace(b"\n", b"\r\n")))


def _shown(names: list[str]) -> str:
    return ", ".join(names[:SHOWN_MAX]) + (f" and {len(names) - SHOWN_MAX} more" if len(names) > SHOWN_MAX else "")


def _rewrite_target(root: Path, target: str) -> str | None:
    """The import target as it reads from docs/ai/local/; the same text for what needs no change (an absolute or ~
    path, one that leaves the project); None for a relative one whose target does not exist from docs/ai/."""
    if target.startswith(("/", "~")) or re.match(r"^[A-Za-z]:[\\/]", target):
        return target
    base = Path(OLD).parent
    resolved = os.path.normpath((root / base / target).as_posix())
    try:
        rel = Path(resolved).relative_to(os.path.normpath(root.as_posix())).as_posix()
    except ValueError:
        # leaves the project: rewritten like any other when its target exists, else reported
        if not os.path.exists(resolved):
            return None
        try:
            return os.path.relpath(resolved, root / Path(NEW).parent).replace(os.sep, "/")
        except ValueError:  # another drive: no relative path
            return None
    if not (root / rel).exists():
        return None
    if target.startswith("../../") and target[6:] == rel:
        return "../" + target  # the form the template writes: one more level up
    return os.path.relpath(root / rel, root / Path(NEW).parent).replace(os.sep, "/")


def _moved_text(root: Path, data: bytes) -> tuple[bytes, list[str], str]:
    """(bytes of the file for its new place, one "import line <n> not rewritten: <path>" per import left as it
    was, a note). A file that is not UTF-8 moves unchanged."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data, [], f"{OLD} is not UTF-8, moved unchanged: its import lines were not rewritten"
    rules = _load_rules(root)
    bom = "﻿" if text.startswith("﻿") else ""  # an import on line 1 is matched without it
    text, declined = rules.rewrite_import_targets(text[len(bom):], lambda target: _rewrite_target(root, target))
    text = bom + text
    if SENTENCE_OLD in text:
        text = text.replace(SENTENCE_OLD, SENTENCE_NEW, 1)
    return text.encode("utf-8"), [f"import line {number} not rewritten: {target}" for number, target in declined], ""


def _replace_bytes(data: bytes) -> bytes:
    return data.replace(OLD.encode("utf-8"), NEW.encode("utf-8"))


def _attributes_text(data: bytes) -> bytes:
    """.gitattributes with the line for the old path written for the new one, the attributes after it as they
    were (and the comment line of the template's block that names the file); the line itself is left alone when
    the new path has one already."""
    pattern = "/" + OLD
    new_pattern = "/" + NEW
    data = re.sub(rb"(?m)^" + re.escape(COMMENT_OLD.encode("utf-8")) + rb"(?=\r?$)", COMMENT_NEW.encode("utf-8"), data)
    if re.search(rb"(?m)^" + re.escape(new_pattern.encode("utf-8")) + rb"(?=[ \t]|\r?$)", data):
        return data
    return re.sub(rb"(?m)^" + re.escape(pattern.encode("utf-8")) + rb"(?=[ \t]|\r?$)", new_pattern.encode("utf-8"), data)


def _tracked_files_naming_old(root: Path) -> list[str]:
    """The tracked text files (not the ones SCAN_SKIP names) that still hold the old path, sorted."""
    try:
        done = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return []
    if done.returncode != 0:
        return []
    needle = OLD.encode("utf-8")
    found: list[str] = []
    for raw in done.stdout.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8", errors="replace")
        if rel in (OLD, NEW, CLAUDE, AGENTS) or rel.startswith(SCAN_SKIP):
            continue
        path = root / rel
        try:
            if not path.is_file() or path.is_symlink() or path.stat().st_size > SCAN_MAX_BYTES:
                continue
            data = path.read_bytes()
        except OSError:
            continue
        if needle in data and b"\x00" not in data:
            found.append(rel)
    return sorted(found)


def _state(root: Path) -> str:
    old, new = (root / OLD).is_file(), (root / NEW).is_file()
    if old and new:
        return "both"
    return "old" if old else ("new" if new else "none")


def plan(root: Path) -> str:
    state = _state(root)
    if state == "both":
        return BOTH_EXIST
    if state == "old":
        data = _read(root / OLD)
        moved, left, note = _moved_text(root, data) if data is not None else (b"", [], "")
        return (f"move {OLD} to {NEW}" + (f"; {len(left)} import line(s) cannot be rewritten" if left else "")
                + (f"; {note}" if note else "") + f"; point {CLAUDE}, {AGENTS} and {ATTRIBUTES} at the new place")
    if state == "none":
        return f"nothing to move: neither {OLD} nor {NEW} exists; point {CLAUDE}, {AGENTS} and {ATTRIBUTES} at the new place"
    return f"nothing to move: {NEW} is the rule file already"


def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_bytes().decode("utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(root: Path, rel: str, data: dict) -> bool:
    """The same bytes actlib writes (indent 2, LF); False when the file may not be written."""
    path = root / rel
    if _LINKS.link_problem(root, path):
        return False
    _LINKS.write_replace(path, (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    return True


def apply(root: Path) -> tuple[str, list[str]]:
    state = _state(root)
    if state == "both":
        return BOTH_EXIST, []
    if state == "new":
        return f"nothing to do: {NEW} is the rule file already", []

    check = _LINKS.LinkCheck(root)
    done: list[str] = []
    notes: list[str] = []
    touched: list[str] = []
    cache_before = _read_json(root / CACHE)
    generated = dict((cache_before or {}).get("generated") or {})
    new_records: dict[str, str] = {}  # cache keys written below, as they must stand
    drop_records: list[str] = []

    def blocked(*paths: Path) -> str:
        for path in paths:
            reason = check.problem(path)
            if reason:
                return reason
        return ""

    # 1. the move
    if state == "old":
        old_path, new_path = root / OLD, root / NEW
        reason = blocked(old_path, new_path)
        data = _read(old_path)
        if reason or data is None:
            return (f"{OLD} not moved ({reason or 'it cannot be read'}); move it to {NEW} by hand and point "
                    f"{CLAUDE} at it"), []
        moved, left, note = _moved_text(root, data)
        new_path.parent.mkdir(parents=True, exist_ok=True)
        _LINKS.write_new(new_path, moved)
        if _read(new_path) != moved:
            new_path.unlink(missing_ok=True)
            return f"{OLD} not moved: the new file did not read back as written; nothing changed", []
        old_path.unlink()
        touched += [OLD, NEW]
        recorded = generated.pop(OLD, None)
        if recorded is not None:
            new_records[NEW] = _sha(_folded(moved)) if _matches_record(data, recorded) else recorded
        done.append(f"moved {OLD} to {NEW}")
        notes += left
        if note:
            notes.append(note)
        if left:
            notes.append("rewrite those lines by hand: Claude Code reads them from docs/ai/local/")

    # 2. CLAUDE.md and AGENTS.md: the import and the pointer follow the file
    for name in (CLAUDE, AGENTS):
        path = root / name
        data = _read(path)
        if data is None or OLD.encode("utf-8") not in data:
            continue
        reason = blocked(path)
        if reason:
            notes.append(f"{name} not changed ({reason})")
            continue
        changed = _replace_bytes(data)
        _LINKS.write_replace(path, changed)
        touched.append(name)
        done.append(f"{name} names {NEW}")
        recorded = generated.get(name)
        if recorded and _matches_record(data, recorded):
            new_records[name] = _sha(_folded(changed))  # still the generated copy: the record follows its bytes

    # 3. .gitattributes
    path = root / ATTRIBUTES
    data = _read(path)
    if data is not None:
        changed = _attributes_text(data)
        if changed != data and not blocked(path):
            _LINKS.write_replace(path, changed)
            touched.append(ATTRIBUTES)
            done.append(f"{ATTRIBUTES}: /{NEW}")

    # 4. the records: cache (generated hashes) and lock (the lines the template wrote into .gitattributes)
    if cache_before is not None and (new_records or OLD in (cache_before.get("generated") or {})):
        generated.update(new_records)
        if _write_json(root, CACHE, {**cache_before, "generated": generated}):
            done.append("cache records follow")
        else:
            notes.append(f"{CACHE} not changed (a link on its way); the files count as edited until it is repaired")
    lock = _read_json(root / LOCK)
    applied = (lock or {}).get("bridges_applied")
    lines = applied.get(ATTRIBUTES) if isinstance(applied, dict) else None
    if isinstance(lines, list):
        pattern = "/" + OLD
        renamed = [COMMENT_NEW if line == COMMENT_OLD else
                   ("/" + NEW + line[len(pattern):]) if isinstance(line, str)
                   and (line == pattern or line.startswith(pattern + " ") or line.startswith(pattern + "\t")) else line
                   for line in lines]
        if renamed != lines:  # the lock is part of the update's commit anyway
            _write_json(root, LOCK, {**lock, "bridges_applied": {**applied, ATTRIBUTES: renamed}})

    # 5. what else still names the old path
    naming = _tracked_files_naming_old(root)
    if naming:
        notes.append(f"still name {OLD}: {_shown(naming)}")

    text = "; ".join(done) if done else f"nothing to move: neither {OLD} nor {NEW} exists"
    return "; ".join([text, *notes]), touched


if __name__ == "__main__":
    project = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    print(plan(project))
