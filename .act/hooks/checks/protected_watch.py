#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Watcher for the files `R-safe-git-metadata` protects (PostToolUse and PostToolUseFailure,
#          orchestrator and workers). The static check git-metadata-guard reads the text of a call
#          BEFORE it runs; a script file, inline code or a program that writes the file itself is
#          invisible to it. This module looks at the files AFTER every call instead, whatever wrote
#          them, and compares them with a snapshot kept under `.act-local/protected-watch/`.
#
# Watched (the same places the guard protects):
#   - `.git/hooks/**`, `.git/config`, `.git/config.worktree` of the repository, of a `.git` file's git
#     directory (and its `commondir`), and of the git directories below `modules/` and `worktrees/`;
#   - `.claude/settings*.json`, `.claude/agents/**`, `.claude/skills/**`, `.claude/commands/**` of the
#     project;
#   - `.mcp.json`, `.envrc`, `.devcontainer.json`, `.devcontainer/**`, `.vscode/tasks.json` at the
#     project root.
#   `.git/config` is compared only on the keys that start code (git_metadata_guard._dangerous_reason, the
#   list is imported from there, not copied): git itself rewrites the file for `push -u`, `remote add`
#   and so on, and that is no change worth a report. Without a usable `git` the whole file is compared.
#   For a key whose danger depends on the value (`alias.*`, `remote.*.url`, `protocol.*.allow`) every value is
#   kept, harmless or not, so a harmless value that was changed to a dangerous one is put back too.
#
# Places: everything the watcher may delete, create, replace or write lies below one of the ANCHORS fixed when
# the snapshot was taken -- the project root and the git directories found then (each with its real path,
# both kept in state.json) -- or below `.act-local/protected-watch/`. Nothing read from the working tree at
# restore time can add a place: the `.git` file of a linked worktree or separate git directory and the git
# directory's `commondir` are watched as files of their own (kind `f`, "pointer to the git directory"), and a
# rewritten pointer is a change like any other -- put back for a worker, reported for the orchestrator -- while
# the scan keeps listing the snapshot's git directories, never the new target. A git directory that was first
# seen in a snapshot taken during a WORKER's call (the state was missing) is restorable only when it lies below
# the project root in fact: written below it, no link on the way from the root to it, and its REAL path below
# the root's real path (a pointer that names a path inside the root which reaches outside through a linked
# folder does not qualify). Any other is watched but not restored, until a session start takes a trusted
# snapshot.
#
# Links: the watcher never follows a link, a junction or another reparse point that stands for another place.
# A watched folder (or file) that is one is listed as ONE entry of its own (kind `l`, hashed by its target
# text) and never entered or read -- the `modules/` and `worktrees/` folders of a git directory and every
# entry below them included; a git directory that is one is not entered either. Before it removes or
# restores a file it checks that the anchor (a git directory) is not a link and still a directory, that its
# real path is the one the snapshot recorded (a junction planted above it changes that), that no component
# from the anchor down to the parent is a link, and that the real path of the deepest existing parent is the
# expected one. The same component check guards every write below `.act-local/protected-watch/`. A path that
# fails is reported as "not restored (path goes through a link)" and left alone; a link a worker put where a
# watched folder or file was is removed (the link itself, never its target). A write goes through a temp
# file created exclusively (O_EXCL, and O_NOFOLLOW where it exists): a hard link or symlink already standing
# at that name is never opened. A blob or a queued note that is a link is not read.
#
# Cheap first: every call lists the watched places once (os.scandir, stat only) and compares
# (mtime_ns, size) with the snapshot; only a file whose stat differs is read and hashed (sha256). Nothing
# else is imported on that path (no actlib, no checks.common), so the common case costs about a
# millisecond on top of the interpreter start. A project that has none of these files costs one directory
# listing of the project root.
#
# A change that is real (the hash differs; for `.git/config` a code-starting key differs):
#   - a WORKER's call (payload has `agent_id`), mode `block`: the file is put back at once from the
#     snapshot taken before the call (not from git: a versioned file can carry the orchestrator's wanted,
#     uncommitted edits; `.git/hooks` and `.git/config` are never versioned), a file that appeared is
#     removed, and the changed version is kept under `.act-local/protected-watch/kept/`. For `.git/config`
#     only the changed keys are reset (`git config --file`), the rest of the file stays as git left it.
#     The worker gets the message, the human gets a `systemMessage`, and a note is queued for the
#     orchestrator's next tool call (`take_orchestrator_notes`). The incident log gets one row `restored` (and
#     one `restore-failed` for what could not be put back) with the tool and the kinds of file, no path.
#     One exception, a single form: a change of the project's `.claude/settings.local.json` that only ADDS
#     entries to the list `permissions.allow` (strict JSON on both sides; every other key and every other
#     `permissions` key equal; every earlier entry still there, order free; all entries strings) is
#     reported, never put back -- it is Claude Code writing the owner's "always allow" answer. A removed or
#     altered entry, a hook, `env` or any other key, a file that does not parse or appeared new is put back
#     as above. That judgement reads two copies the watcher holds and writes nothing, so it adds no place.
#   - the ORCHESTRATOR's call, or mode `warn`: reported only, with the command that puts the file back; the
#     previous version is kept under `kept/` so the command stays valid; the new state becomes the
#     reference. The commands name the file (`git config --file <path>`), end git's options with `--` (a
#     value that begins with `-` is a value, not an option) and quote every argument so that no shell (bash,
#     PowerShell, cmd) expands anything in a key, a value or a path: an argument with a character outside a
#     small safe set is written as a Python string literal with `\xNN` escapes, one that begins with `@`
#     (PowerShell splatting) or `-` or holds a comma (PowerShell array) is put in double quotes.
#     One exception, the orchestrator's call only (`_own_skill_copies`): an added or modified file whose path is
#     exactly (case-sensitive) a destination the copy step itself lists (init.copy_targets for the project's
#     `tools`, plus own skills from the lock's `copies`), not in the lock's `removed_by_user`, and whose bytes
#     equal what the step writes from its source, is not reported; the new state becomes the reference. Anything
#     else is reported as before; a worker's call restores it like any other change.
#   - a restore that fails (read-only file, a path through a link, no copy): the old entry stays the reference,
#     so the change is reported again at the next call, and a temp file the write left behind is removed.
#   Mode `off` (or a missing snapshot) does nothing. SessionStart calls `snapshot()` after the session
#   handler has refreshed the bridges.
#
# Limits (stated in .act/rules/topics/checks.md):
#   - An entry a worker adds to permissions.allow in .claude/settings.local.json itself is only reported,
#     like the owner's "always allow" answer: the file does not tell the two apart.
#   - It reports AFTER the call; it prevents nothing. A hook runs at the next git command, which can be
#     the very next call of another worker.
#   - A change made between two calls by someone else (the human in an editor, Claude Code itself writing
#     `.claude/settings.local.json` when a permission is granted, another session in the same project) is
#     attributed to the next call. A worker call that ends while the orchestrator has just changed a
#     protected file is attributed to the worker, and the change is put back (the kept copy and the
#     command in the message undo that).
#   - stat first: a write that leaves size and modification time as they were is not seen (a file modified
#     within 2 s before the snapshot is hashed once more on the next call, so a write in the same clock
#     tick is not missed); a file over 2 MB is hashed but cannot be restored; the lists are cut at 4000
#     files; `*.sample` hooks are left out (git never runs them).
#   - A worker that deletes the snapshot itself makes the next call take a new one; its write scope
#     normally keeps it out of `.act-local/`. A git directory that such a snapshot finds and that does not lie
#     below the root in fact (see Places above) is not restored.
#   - A `.git` file above the project root (the project inside a worktree or separate git directory whose
#     pointer lies outside it) is outside the root and not watched: the git directories it named at snapshot
#     time stay watched, a rewrite of that pointer is not seen.
#   - Who is blamed: a worker's change that first shows up in the ORCHESTRATOR's call (calls running in
#     parallel, a background command that ends late, a worker call that finds the lock taken and returns)
#     is reported as the orchestrator's and becomes the reference; it is not put back. The report names the
#     call it was seen in, not who wrote.
#   - A watched folder that was a link when the snapshot was taken (a shared `.claude/skills` linked in on
#     purpose) is watched as that link only; what lies behind it is not. A `.act-local` that is a link makes
#     the watcher stop (one line on stderr): it writes nothing through a link.
#   - A link is checked at the moment of the write, not held: one planted between the check and the write
#     by a process running at that very instant is not caught.
#   - User-level files (`~/.claude`) are not watched: other projects share them and Claude Code writes
#     there itself; they stay with the static check. `*.code-workspace` files are not watched either.
#   - Two sessions in one project share one snapshot.
#   - Everything here is best effort: an error is one line on stderr, never a blocked call.

from __future__ import annotations

import json
import os
import stat
import sys
import time
from collections import namedtuple

__all__ = [
    "run", "watch", "snapshot", "queue_orchestrator_note", "take_orchestrator_notes", "watch_mode",
]

_DEFAULT_MODE = "block"
_MODES = ("block", "warn", "off")
_MAX_COPY = 2_000_000       # bytes: larger files are hashed but not copied
_MAX_FILES = 4000           # files listed at most
_MAX_LISTED = 12            # files named in one message
_MAX_NOTE = 65536           # bytes of one queued note that are read
_STATE_VERSION = 2          # state.json layout; an older one is taken afresh
_LOCK_WAIT = 1.0            # seconds to wait for the lock of another hook process
_LOCK_STALE = 15.0          # seconds after which a lock is orphaned
_NOTE_TTL = 86400.0         # seconds a queued orchestrator note stays valid
_KEPT_TTL = 30 * 86400.0    # seconds a kept copy stays
_GIT_TIMEOUT = 15
_WATCH_DIR = "protected-watch"

_KIND_FILE = "f"
_KIND_CONFIG = "c"
_KIND_LINK = "l"            # a symlink, junction or other name-surrogate reparse point: listed, never entered
_REPARSE_POINT = 0x400      # FILE_ATTRIBUTE_REPARSE_POINT (st_file_attributes)
_NAME_SURROGATE = 0x20000000  # reparse tag bit: the point stands for another file system object
_PLAIN_CHARS = "_./:@+=-"   # besides ASCII letters and digits: an argument of only these needs no quoting
_NOT_FIRST = "@-"           # ... unless it begins with one of these: `@x` is splatting in PowerShell, `-x` an option
_QUOTED_CHARS = " ,"        # allowed in an argument only inside double quotes: PowerShell reads a bare `a,b` as an array
_GIT_WORDS = frozenset({"git", "config", "--file", "--unset-all", "--add", "--"})  # the watcher's own tokens
_RACY_NS = 2_000_000_000    # an entry whose file was modified this close to the snapshot is hashed again next time
_ROOT_FILES = frozenset({".mcp.json", ".envrc", ".devcontainer.json"})

# A place a restore may write below, fixed when the snapshot was taken: its path, its real path then, whether
# it is a git directory (which itself must be no link and still a directory) and whether a restore may write
# below it at all (a git directory outside the root first seen during a worker's call may not).
_Anchor = namedtuple("_Anchor", "path real gitdir restorable")


# ---------------------------------------------------------------------------
# Mode and paths
# ---------------------------------------------------------------------------

def _norm(path: str) -> str:
    return os.path.abspath(path).replace("\\", "/")


def _project_root() -> str:
    # .act/hooks/checks/protected_watch.py -> the project is three levels above the checks folder
    return _norm(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))


def watch_mode(root: str) -> str:
    """`block` | `warn` | `off` for the key `protected-watch` in docs/ai/config.md (default block); the
    environment variable ACT_PROTECTED_WATCH overrides it for one run. The table is read by hand, without
    actlib, so the common call stays cheap."""
    env = os.environ.get("ACT_PROTECTED_WATCH", "").strip().lower()
    if env in _MODES:
        return env
    try:
        with open(os.path.join(root, "docs", "ai", "config.md"), encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return _DEFAULT_MODE
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or "protected-watch" not in stripped:
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) >= 2 and cells[0].strip("`").strip() == "protected-watch":
            value = cells[1].strip("`").strip().lower()
            return value if value in _MODES else _DEFAULT_MODE
    return _DEFAULT_MODE


def _base(root: str) -> str:
    return root.rstrip("/") + "/.act-local/" + _WATCH_DIR


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

def _is_link_info(info: os.stat_result) -> bool:
    """True for a symbolic link, a Windows junction or another reparse point that stands for another
    file system object (name surrogate). Works without os.path.isjunction / Path.is_junction (Python 3.12+):
    the attributes of an lstat result say it. A reparse point of unknown tag counts as a link."""
    if stat.S_ISLNK(info.st_mode):
        return True
    attributes = getattr(info, "st_file_attributes", 0)
    if not attributes & _REPARSE_POINT:
        return False
    tag = getattr(info, "st_reparse_tag", 0)
    return not tag or bool(tag & _NAME_SURROGATE)


def _lstat(path: str) -> os.stat_result | None:
    try:
        return os.lstat(path)
    except OSError:
        return None


def _parts_below(anchor: str, path: str) -> list[str] | None:
    """The names between `anchor` and `path` (the last one included), None when `path` is not below it."""
    anchor, path = anchor.replace("\\", "/").rstrip("/"), path.replace("\\", "/")
    norm_anchor, norm_path = os.path.normcase(anchor).replace("\\", "/"), os.path.normcase(path).replace("\\", "/")
    if norm_path != norm_anchor and not norm_path.startswith(norm_anchor + "/"):
        return None
    return [part for part in path[len(anchor):].split("/") if part]


def _link_in(anchor: str, path: str, include_last: bool = False, include_anchor: bool = False) -> str | None:
    """The first component below `anchor` on the way to `path` that is a link (None when the way is clear).
    The last component (the file itself) is looked at only with `include_last`: a write replaces a link
    that stands where the file was, it never goes through it. A component that does not exist is no link;
    what is created there is a real folder. With `include_anchor` the anchor itself must not be one."""
    anchor = anchor.replace("\\", "/").rstrip("/")
    if include_anchor:
        info = _lstat(anchor)
        if info is not None and _is_link_info(info):
            return anchor
    parts = _parts_below(anchor, path)
    if parts is None:
        return path  # not below the anchor at all: nothing here may be written
    if not include_last:
        parts = parts[:-1]
    current = anchor
    for part in parts:
        current = f"{current}/{part}"
        info = _lstat(current)
        if info is None:
            return None
        if _is_link_info(info):
            return current
    return None


def _real(path: str) -> str:
    return _norm(os.path.realpath(path))


def _same_place(path: str, real: str) -> bool:
    """True when `path` still resolves to the real path `real` recorded at snapshot time."""
    return os.path.normcase(os.path.normpath(_real(path))) == os.path.normcase(os.path.normpath(real))


def _really_inside(root: str, gitdir: str) -> bool:
    """True when `gitdir` lies below the project root in fact, not only in its spelling: the path is written
    below the root, no component from the root down to it (itself included) is a link, and its real path lies
    below the real path of the root. A pointer that names a path inside the root which reaches outside
    through a linked folder fails the second and third test."""
    if not _parts_below(root, gitdir):
        return False
    if _link_in(root, gitdir, include_last=True):  # the root itself may be reached through a link, as the owner set it up
        return False
    return bool(_parts_below(_real(root), _real(gitdir)))


def _unexpected_parent(anchor: _Anchor, path: str) -> bool:
    """True when the real path of the deepest existing parent of `path` is not where the anchor's real path
    (as recorded at snapshot time) and the names in between lead: a link or mount point the attribute test
    did not name, or a link planted above the anchor."""
    parts = (_parts_below(anchor.path, path) or [])[:-1]
    while parts and not os.path.isdir(f"{anchor.path}/{'/'.join(parts)}"):
        parts.pop()
    expected = os.path.join(anchor.real, *parts)
    actual = os.path.realpath(f"{anchor.path}/{'/'.join(parts)}" if parts else anchor.path)
    return os.path.normcase(os.path.normpath(expected)) != os.path.normcase(os.path.normpath(actual))


def _remove_link(path: str) -> None:
    """Remove the link itself (never what it points at): rmdir takes a junction or a directory symlink on
    Windows, unlink a symlink on POSIX and a file symlink."""
    try:
        os.rmdir(path)
    except OSError:
        os.unlink(path)


# ---------------------------------------------------------------------------
# Listing the watched places
# ---------------------------------------------------------------------------

def _find_gitdirs(root: str) -> list[str]:
    """The git directories that matter for the project: the `.git` directory found at the root or above
    it (at most 12 levels), or for a `.git` FILE its `gitdir:` target and that directory's `commondir`.
    A `.git` that is a link is not followed."""
    current = root
    for _ in range(12):
        dot_git = current + "/.git"
        try:
            info = _lstat(dot_git)
            if info is not None and _is_link_info(info):
                return []
            if os.path.isdir(dot_git):
                return [dot_git]
            if os.path.isfile(dot_git):
                with open(dot_git, encoding="utf-8", errors="replace") as handle:
                    text = handle.read().strip()
                found: list[str] = []
                if text.lower().startswith("gitdir:"):
                    target = text[len("gitdir:"):].strip()
                    gitdir = _norm(target if os.path.isabs(target) else os.path.join(current, target))
                    found.append(gitdir)
                    try:
                        with open(gitdir + "/commondir", encoding="utf-8", errors="replace") as handle:
                            common = handle.read().strip()
                        found.append(_norm(common if os.path.isabs(common) else os.path.join(gitdir, common)))
                    except OSError:
                        pass
                return found
        except OSError:
            return []
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return []


def _add(found: dict, path: str, kind: str, info: os.stat_result) -> bool:
    if len(found) >= _MAX_FILES:
        return False
    found[_norm(path)] = [info.st_mtime_ns, info.st_size, kind]
    return True


def _add_item(found: dict, path: str, plain_kind: str) -> None:
    """A watched file: a link standing there is listed as a link, never read through."""
    info = _lstat(path)
    if info is None:
        return
    if _is_link_info(info):
        _add(found, path, _KIND_LINK, info)
    elif not stat.S_ISDIR(info.st_mode):
        _add(found, path, plain_kind, info)


def _walk(directory: str, found: dict, skip_samples: bool = False) -> None:
    """Every file below `directory`; a link (symlink, junction) anywhere, the folder itself included, is
    listed as one entry and not entered. With `skip_samples` the `*.sample` files of a hooks folder are
    left out: git never runs them."""
    top = _lstat(directory)
    if top is None:
        return
    if _is_link_info(top):
        _add(found, directory, _KIND_LINK, top)
        return
    if not stat.S_ISDIR(top.st_mode):
        return
    pending = [directory]
    while pending:
        current = pending.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        info = entry.stat(follow_symlinks=False)
                        if _is_link_info(info):
                            if not _add(found, entry.path, _KIND_LINK, info):
                                return
                        elif stat.S_ISDIR(info.st_mode):
                            pending.append(entry.path)
                        elif skip_samples and entry.name.endswith(".sample"):
                            continue
                        elif not _add(found, entry.path, _KIND_FILE, info):
                            return
                    except OSError:
                        continue
        except OSError:
            continue


def _scan_gitdir(gitdir: str, found: dict, depth: int) -> None:
    """The watched items of one git directory: its hooks, its config files and its `commondir` pointer. A
    git directory that is a link, a file or gone is not entered (what the snapshot had there counts as
    removed; a restore below it is refused by the anchor checks)."""
    top = _lstat(gitdir)
    if top is None or _is_link_info(top) or not stat.S_ISDIR(top.st_mode):
        return
    _walk(gitdir + "/hooks", found, skip_samples=True)
    for name in ("config", "config.worktree"):
        _add_item(found, f"{gitdir}/{name}", _KIND_CONFIG)
    _add_item(found, f"{gitdir}/commondir", _KIND_FILE)
    if depth >= 3:
        return
    for sub in ("modules", "worktrees"):
        for inner in _inner_gitdirs(f"{gitdir}/{sub}", 0, found):
            _scan_gitdir(inner, found, depth + 1)


def _inner_gitdirs(base: str, level: int, found: dict) -> list[str]:
    """The git directories (folders holding a HEAD file) below `base`, a submodule name may contain `/`.
    `base` itself (`modules`, `worktrees`) and every entry below it that is a link is listed as one entry
    of its own in `found` and not entered, like any other link: nothing behind it is listed, hashed or run
    through `git config`."""
    top = _lstat(base)
    if top is None:
        return []
    if _is_link_info(top):
        _add(found, base, _KIND_LINK, top)
        return []
    if not stat.S_ISDIR(top.st_mode):
        return []
    out: list[str] = []
    try:
        with os.scandir(base) as entries:
            for entry in entries:
                try:
                    info = entry.stat(follow_symlinks=False)
                    if _is_link_info(info):
                        _add(found, entry.path, _KIND_LINK, info)
                        continue
                    if not stat.S_ISDIR(info.st_mode):
                        continue
                except OSError:
                    continue
                if os.path.exists(entry.path + "/HEAD"):
                    out.append(entry.path)
                elif level < 3:
                    out.extend(_inner_gitdirs(entry.path, level + 1, found))
    except OSError:
        pass
    return out


def _scan(root: str, gitdirs: list[str]) -> dict:
    """path -> [mtime_ns, size, kind] for everything watched, by one listing of the project root plus the
    watched folders. Stat only, nothing is read. `gitdirs` are the git directories to look at: the ones the
    snapshot recorded (watch time) or the ones found now (snapshot time), never read afresh at watch time."""
    found: dict = {}
    for gitdir in gitdirs:
        _scan_gitdir(gitdir, found, 0)
    try:
        with os.scandir(root) as entries:
            names = {entry.name.lower(): entry.path for entry in entries}
    except OSError:
        return found
    if ".git" in names:
        _add_item(found, names[".git"], _KIND_FILE)  # a .git FILE is the pointer to the git directory
    for name in _ROOT_FILES:
        if name in names:
            _add_item(found, names[name], _KIND_FILE)
    if ".devcontainer" in names:
        _walk(names[".devcontainer"], found)
    if ".vscode" in names:
        top = _lstat(names[".vscode"])
        if top is not None and _is_link_info(top):
            _add(found, names[".vscode"], _KIND_LINK, top)
        else:
            _add_item(found, names[".vscode"] + "/tasks.json", _KIND_FILE)
    if ".claude" in names:
        claude = names[".claude"]
        top = _lstat(claude)
        if top is not None and _is_link_info(top):
            _add(found, claude, _KIND_LINK, top)
            return found
        try:
            with os.scandir(claude) as entries:
                for entry in entries:
                    lowered = entry.name.lower()
                    try:
                        if lowered in ("agents", "skills", "commands"):
                            _walk(entry.path, found)
                        elif lowered.startswith("settings") and lowered.endswith(".json"):
                            _add_item(found, entry.path, _KIND_FILE)
                    except OSError:
                        continue
        except OSError:
            pass
    return found


# ---------------------------------------------------------------------------
# Files: hash, copy, write
# ---------------------------------------------------------------------------

def _read_hash(path: str) -> tuple[str, bytes | None]:
    """(sha256 hex, content or None when the file is larger than _MAX_COPY); ("?", None) when it cannot
    be read."""
    import hashlib

    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            data = handle.read(_MAX_COPY + 1)
            if len(data) <= _MAX_COPY:
                digest.update(data)
                return digest.hexdigest(), data
            digest.update(data)
            while True:
                chunk = handle.read(1 << 20)
                if not chunk:
                    break
                digest.update(chunk)
            return digest.hexdigest(), None
    except OSError:
        return "?", None


def _fingerprint(path: str, kind: str) -> tuple[str, bytes | None]:
    """(digest, content) of a watched item. A link is not opened: its digest is the hash of its target text
    (`?` when that cannot be read); there is no content."""
    if kind != _KIND_LINK:
        return _read_hash(path)
    import hashlib

    try:
        target = os.readlink(path)
    except OSError:
        return "?", None
    return hashlib.sha256(b"link:" + target.encode("utf-8", errors="replace")).hexdigest(), None


def _root_of(base: str) -> str:
    """The project root a state folder `<root>/.act-local/protected-watch` belongs to."""
    return os.path.dirname(os.path.dirname(base))


_EXCLUSIVE = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
              | getattr(os, "O_CLOEXEC", 0))


def _write_atomic(path: str, data: bytes, anchor: str) -> None:
    """Write `data` to `path` by a temp file next to it and a rename. Refuses (OSError) when a component
    between `anchor` and the file's folder is a link: nothing is created or replaced through a link. The temp
    file is created exclusively: a file, hard link or symlink already standing at its name is never opened
    (and not removed either, it is not ours). A temp file this write made and could not rename is removed."""
    linked = _link_in(anchor, path)
    if linked:
        raise OSError(f"path goes through a link ({linked})")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = f"{path}.pw-{os.getpid()}.tmp"
    descriptor = os.open(temp, _EXCLUSIVE, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        os.replace(temp, path)
    except OSError:
        try:
            os.remove(temp)
        except OSError:
            pass
        raise


def _blob(base: str, digest: str) -> str:
    return f"{base}/blobs/{digest}"


def _store_blob(base: str, digest: str, data: bytes | None) -> None:
    if data is None or digest == "?":
        return
    target = _blob(base, digest)
    if not os.path.exists(target):
        try:
            _write_atomic(target, data, _root_of(base))
        except OSError:
            pass


def _read_blob(base: str, digest: str) -> bytes | None:
    """The kept copy, or None when there is none or what stands at its name is not a plain file (a link is
    never read through)."""
    path = _blob(base, digest)
    info = _lstat(path)
    if info is None or _is_link_info(info) or not stat.S_ISREG(info.st_mode):
        return None
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return None


def _mode_bits(path: str) -> int:
    try:
        return os.lstat(path).st_mode & 0o777
    except OSError:
        return 0o644


def _is_racy(mtime_ns: int) -> bool:
    """True when a later write could still leave the same size and modification time (the clock has not
    moved on since): such an entry is hashed again on the next call, like git does with a racy index entry."""
    return time.time_ns() - mtime_ns < _RACY_NS


def _entry(path: str, info: list, digest: str, data: bytes | None, base: str, keys: dict | None) -> dict:
    _store_blob(base, digest, data)
    entry = {"m": info[0], "s": info[1], "h": digest, "k": info[2], "x": _mode_bits(path)}
    if _is_racy(info[0]):
        entry["r"] = True
    if info[2] == _KIND_CONFIG:
        entry["d"] = keys["d"] if keys else None
        if keys and keys["a"]:
            entry["a"] = keys["a"]
    return entry


# ---------------------------------------------------------------------------
# .git/config: the keys that start code
# ---------------------------------------------------------------------------

_GUARD = None


def _guard():
    """The module with the key list (git_metadata_guard), imported on first use: its import pulls in the
    shell scanners, which the common path must not pay for. None when it cannot be imported."""
    global _GUARD
    if _GUARD is None:
        scripts = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts")
        scripts = os.path.abspath(scripts)
        if scripts not in sys.path:
            sys.path.append(scripts)
        try:
            from checks import git_metadata_guard as guard  # noqa: WPS433 -- lazy on purpose
        except Exception:  # noqa: BLE001 -- no key list: the whole file is compared instead
            return None
        _GUARD = guard
    return _GUARD


def _config_keys(config_path: str) -> dict | None:
    """What the config file says about the keys that start code, or None when that cannot be told (no git,
    no key list): the caller then compares the whole file.
      "d": {key: [values]} of the keys whose value starts code, the dangerous values only (what is compared);
      "a": {key: [values]} of every key that can start code for SOME value (`alias.*`, `remote.*.url`,
           `protocol.*.allow`), all its values, harmless ones too (what a restore puts back)."""
    import subprocess

    guard = _guard()
    if guard is None:
        return None
    try:
        done = subprocess.run(
            ["git", "config", "--file", config_path, "--list", "-z"], capture_output=True, timeout=_GIT_TIMEOUT,
            cwd=os.path.dirname(config_path),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    danger: dict[str, list[str]] = {}
    every: dict[str, list[str]] = {}
    for raw in done.stdout.decode("utf-8", errors="replace").split("\0"):
        if not raw:
            continue
        key, sep, value = raw.partition("\n")
        try:
            reason = guard._dangerous_reason(key, value if sep else "")
        except Exception:  # noqa: BLE001 -- an unreadable key counts as dangerous
            reason = "unreadable"
        try:
            depends = guard._dangerous_reason(key, None)
        except Exception:  # noqa: BLE001
            depends = "unreadable"
        if reason:
            danger.setdefault(key, []).append(value)
        if depends:
            every.setdefault(key, []).append(value)
    return {"d": danger, "a": every}


def _git_config_run(config_path: str, args: list[str]) -> bool:
    import subprocess

    try:
        done = subprocess.run(
            ["git", "config", "--file", config_path, *args], capture_output=True, timeout=_GIT_TIMEOUT,
            cwd=os.path.dirname(config_path),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode in (0, 5)  # 5: the key to unset was not there


def _restore_config_keys(config_path: str, old: dict, now: dict) -> bool:
    """Reset the code-starting keys that differ to their snapshot values with `git config --file`. A key
    whose danger depends on the value gets ALL its snapshot values back, harmless ones included."""
    old_danger, now_danger, old_every = old["d"], now["d"], old.get("a") or {}
    for key in sorted(set(old_danger) | set(now_danger)):
        if old_danger.get(key) == now_danger.get(key):
            continue
        if not _git_config_run(config_path, ["--unset-all", "--", key]):
            return False
        for value in old_every.get(key, old_danger.get(key, [])):
            if not _git_config_run(config_path, ["--add", "--", key, value]):  # `--`: a value may begin with `-`
                return False
    again = _config_keys(config_path)
    return again is not None and again["d"] == old_danger


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def _load_state(base: str) -> dict | None:
    """The snapshot, or None when there is none or its layout is not the current one (an older one is taken
    afresh): `root`, `root_real`, `gitdirs` ([path, real path, restorable] each), `session`, `files`."""
    try:
        with open(base + "/state.json", encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, ValueError):
        return None
    if not (isinstance(state, dict) and state.get("version") == _STATE_VERSION and isinstance(state.get("files"), dict)
            and isinstance(state.get("root"), str) and isinstance(state.get("root_real"), str)
            and isinstance(state.get("gitdirs"), list)):
        return None
    return state


def _save_state(base: str, state: dict, files: dict) -> None:
    """Write the snapshot: the head fields of `state` (the root, its real path, the git directories, the
    session) with `files` as the entries."""
    saved = {key: state.get(key) for key in ("version", "root", "root_real", "gitdirs", "session")}
    saved.update(ts=time.time(), files=files)
    _write_atomic(base + "/state.json", json.dumps(saved, separators=(",", ":")).encode("utf-8"), state["root"])


def _gitdir_paths(state: dict) -> list[str]:
    """The git directories the snapshot recorded (their paths)."""
    return [item[0] for item in state["gitdirs"] if isinstance(item, list) and item and isinstance(item[0], str)]


def _assert_base_clear(root: str) -> None:
    """OSError when `.act-local` or `.act-local/protected-watch` is a link: the watcher writes nothing
    through one (state, copies, notes, lock all live below it)."""
    linked = _link_in(root, _base(root) + "/x")
    if linked:
        raise OSError(f"{_shown(root, _norm(linked))} is a link; the watcher writes nothing through a link")


def snapshot(root: str | None = None, session: object = None, trusted: bool = True) -> int:
    """Take the reference state now (SessionStart, and the first call without a snapshot). Returns the
    number of files watched; with mode `off` the old snapshot is dropped and 0 returned. The git directories
    found now become the anchors below which a later restore may write; with `trusted` False (a snapshot
    taken during a worker's call) one that does not lie below the project root in fact -- by its real path,
    with no link between the root and it (_really_inside) -- is watched but not restored below. Nothing
    is removed or written when `.act-local` or the state folder is a link (OSError; silently with mode off)."""
    root = root or _project_root()
    base = _base(root)
    if watch_mode(root) == "off":
        try:
            _assert_base_clear(root)
            os.remove(base + "/state.json")
        except OSError:
            pass
        return 0
    _assert_base_clear(root)
    gitdirs = _find_gitdirs(root)
    scan = _scan(root, gitdirs)
    files: dict = {}
    for path, info in scan.items():
        digest, data = _fingerprint(path, info[2])
        keys = _config_keys(path) if info[2] == _KIND_CONFIG else None
        files[path] = _entry(path, info, digest, data, base, keys)
    state = {"version": _STATE_VERSION, "root": root, "root_real": _real(root),
             "session": session if isinstance(session, str) else "",
             "gitdirs": [[gitdir, _real(gitdir), trusted or _really_inside(root, gitdir)] for gitdir in gitdirs]}
    _save_state(base, state, files)
    _collect_garbage(base, files)
    return len(files)


def _collect_garbage(base: str, files: dict) -> None:
    """Drop blobs no snapshot entry refers to, kept copies and notes past their age."""
    live = {entry["h"] for entry in files.values()}
    now = time.time()
    root = _root_of(base)
    if not _link_in(root, base + "/blobs/x"):
        try:
            with os.scandir(base + "/blobs") as entries:
                for entry in entries:
                    if entry.name not in live:
                        try:
                            os.remove(entry.path)
                        except OSError:
                            pass
        except OSError:
            pass
    for sub, ttl in (("kept", _KEPT_TTL), ("notes", _NOTE_TTL)):
        if _link_in(root, f"{base}/{sub}/x"):
            continue
        try:
            with os.scandir(f"{base}/{sub}") as entries:
                for entry in entries:
                    try:
                        if now - entry.stat().st_mtime > ttl:
                            os.remove(entry.path)
                    except OSError:
                        pass
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Lock (one hook process at a time may judge and restore)
# ---------------------------------------------------------------------------

class _Lock:
    def __init__(self, base: str) -> None:
        self.path = base + "/lock"
        self.held = False

    def __enter__(self) -> "_Lock":
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        deadline = time.monotonic() + _LOCK_WAIT
        while True:
            try:
                os.mkdir(self.path)
                self.held = True
                return self
            except FileExistsError:
                try:
                    if time.time() - os.stat(self.path).st_mtime > _LOCK_STALE:
                        os.rmdir(self.path)
                        continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    return self
                time.sleep(0.03)
            except OSError:
                return self

    def __exit__(self, *_exc: object) -> None:
        if self.held:
            try:
                os.rmdir(self.path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Judging a change
# ---------------------------------------------------------------------------

def _flat(path: str) -> str:
    text = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in path)
    return text[-90:]


def _examine(base: str, files: dict, scan: dict) -> tuple[dict, list[dict]]:
    """(new state entries, changes). Hashes only what differs by stat; a file whose hash or, for the git
    config, whose code-starting keys equal the snapshot only has its stat refreshed."""
    new_files = dict(files)
    changes: list[dict] = []
    for path in sorted(set(files) | set(scan)):
        old = files.get(path)
        info = scan.get(path)
        if info is None:
            changes.append({"path": path, "op": "removed", "old": old, "new": None, "kind": old["k"]})
            del new_files[path]
            continue
        if old is not None and old["m"] == info[0] and old["s"] == info[1] and not old.get("r"):
            continue
        digest, data = _fingerprint(path, info[2])
        if old is not None and old["h"] == digest and digest != "?":
            refreshed = {key: value for key, value in old.items() if key != "r"}
            refreshed.update(m=info[0], s=info[1])
            if _is_racy(info[0]):
                refreshed["r"] = True
            new_files[path] = refreshed
            continue
        keys = None
        if info[2] == _KIND_CONFIG:
            keys = _config_keys(path)
            old_danger = old.get("d") if old else None
            if keys is not None and (old_danger is not None or old is None) and keys["d"] == (old_danger or {}):
                new_files[path] = _entry(path, info, digest, data, base, keys)  # git rewrote harmless keys
                continue
        new_entry = _entry(path, info, digest, data, base, keys)
        new_files[path] = new_entry
        changes.append({"path": path, "op": "added" if old is None else "modified", "old": old, "new": new_entry,
                        "kind": info[2], "data": data})
    return new_files, changes


def _diff_keys(old: dict | None, new: dict | None) -> list[tuple[str, str, list, list]]:
    """(key, what, old values, new values) for each code-starting key that differs. The old values are all
    the values the snapshot had for the key (harmless ones included), the new ones the dangerous ones."""
    old_danger = (old or {}).get("d") or {}
    new_danger = (new or {}).get("d") or {}
    old_every = (old or {}).get("a") or {}
    out = []
    for key in sorted(set(old_danger) | set(new_danger)):
        if old_danger.get(key) == new_danger.get(key):
            continue
        had = key in old_danger or key in old_every
        what = "added" if not had else "removed" if key not in new_danger else "changed"
        out.append((key, what, old_every.get(key, old_danger.get(key, [])), new_danger.get(key, [])))
    return out


def _keep(base: str, stamp: str, label: str, path: str, data: bytes | None) -> str | None:
    """Keep `data` as a file under kept/ and return its path; None when there is no content to keep."""
    if data is None:
        return None
    target = f"{base}/kept/{stamp}-{label}-{_flat(path)}"
    try:
        _write_atomic(target, data, _root_of(base))
    except OSError:
        return None
    return target


def _strict_object(pairs: list) -> dict:
    """json object hook: a repeated key is an error (which of the two counts would depend on the reader)."""
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"repeated key {key!r}")
        out[key] = value
    return out


def _no_constant(name: str) -> None:
    raise ValueError(f"constant {name} is not valid JSON")


def _parse_settings(data: bytes | None) -> dict | None:
    """The JSON object a settings file holds, None when it is missing, not UTF-8, not strict JSON (repeated
    keys, NaN and Infinity count as errors) or not an object."""
    if data is None:
        return None
    try:
        doc = json.loads(data.decode("utf-8"), object_pairs_hook=_strict_object, parse_constant=_no_constant)
    except (ValueError, RecursionError):
        return None
    return doc if isinstance(doc, dict) else None


def _canon(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _local_settings_path(root: str) -> str:
    return os.path.normcase(root.rstrip("/") + "/.claude/settings.local.json")


def _allow_additions(old_doc: dict, new_doc: dict) -> list[str] | None:
    """The entries `new_doc` adds to `permissions.allow` when that is ALL it changes against `old_doc`;
    None for every other difference (also: nothing added). The one form that qualifies: every key outside
    `permissions` equal, every key of `permissions` except `allow` equal, `allow` a list of strings in
    which every earlier entry is still present (as often as before, order free) and at least one is new.
    A missing `permissions` or `allow` in the old file counts as empty, but only when the old file lacked
    the key: an existing key may not vanish, an empty `permissions` may not turn into none."""
    if {key: _canon(value) for key, value in old_doc.items() if key != "permissions"} != \
            {key: _canon(value) for key, value in new_doc.items() if key != "permissions"}:
        return None
    new_perm = new_doc.get("permissions")
    if not isinstance(new_perm, dict) or "permissions" not in new_doc:
        return None
    old_perm = old_doc.get("permissions", {}) if "permissions" in old_doc else {}
    if not isinstance(old_perm, dict):
        return None
    if {key: _canon(value) for key, value in old_perm.items() if key != "allow"} != \
            {key: _canon(value) for key, value in new_perm.items() if key != "allow"}:
        return None
    new_allow = new_perm.get("allow")
    old_allow = old_perm.get("allow", []) if "allow" in old_perm else []
    if not isinstance(new_allow, list) or not isinstance(old_allow, list):
        return None
    if not all(isinstance(item, str) for item in new_allow) or not all(isinstance(item, str) for item in old_allow):
        return None
    remaining = list(new_allow)
    for item in old_allow:
        if item not in remaining:
            return None
        remaining.remove(item)
    return remaining or None


def _reportable_addition(base: str, change: dict, root: str) -> list[str] | None:
    """For a change of the project's `.claude/settings.local.json` that only adds entries to
    `permissions.allow` (Claude Code writing the owner's "always allow" answer): the added entries; None
    for everything else, which is put back as before. The judgement reads two copies the watcher itself
    holds (the snapshot's blob and the content read from the changed file) and touches nothing: no place
    is resolved here and nothing is written below any."""
    if change["op"] != "modified" or change["kind"] != _KIND_FILE or change["old"] is None:
        return None
    if os.path.normcase(change["path"]) != _local_settings_path(root):
        return None
    old_doc = _parse_settings(_read_blob(base, change["old"]["h"]))
    new_doc = _parse_settings(change.get("data"))
    if old_doc is None or new_doc is None:
        return None
    return _allow_additions(old_doc, new_doc)


def _own_skill_copies(changes: list[dict], root: str) -> list[dict]:
    """The changes that are the template's own skill copies: an added or modified file whose destination
    (exact, case-sensitive string) is a key of the map the copy step itself builds (init.copy_targets for the
    project's `tools`, plus the project's own skills as update.py adds them from the lock's `copies`), is not
    in the lock's `removed_by_user`, and whose bytes equal init.skill_copy_bytes of the source the map names.
    An allowlist, used for the orchestrator's call only: a deleted file, any other path, a destination the copy
    step would not write, a source that is a link or outside the project, a file over 2 MB, anything not
    byte-equal, or any error leaves the change out and it is reported as before."""
    wanted: list[tuple[dict, str]] = []
    for change in changes:
        if change["op"] not in ("added", "modified") or change["kind"] != _KIND_FILE or change.get("data") is None:
            continue
        parts = _parts_below(root.rstrip("/") + "/.claude/skills", change["path"])
        if parts and len(parts) >= 2:
            wanted.append((change, ".claude/skills/" + "/".join(parts)))
    if not wanted:
        return []
    from pathlib import Path

    base, found, old_cwd = Path(root), [], os.getcwd()
    try:
        scripts = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
        if scripts not in sys.path:
            sys.path.append(scripts)
        import init  # noqa: WPS433 -- lazy on purpose: only a changed skill copy pays for it

        os.chdir(base)  # actlib.resolve() and the lock readers look at the working directory
        lock = init.actlib.read_lock_at(base)
        if lock is None:
            return []
        removed = set(lock.get("removed_by_user") or [])
        tools_cell = init.actlib.read_config(base).get("tools", "")
        tools = sorted({init.actlib.normalize_tool(t) for t in tools_cell.split(",") if t.strip()})
        real = base.resolve()
        expected: dict[str, Path] = {}
        for dest, src in init.copy_targets(base, tools).items():
            expected[dest] = src
        cut = init.act_profile.read_cut(base).skills
        prefix = "docs/ai/local/skills/"
        active = [d for d, gate in init.SKILL_TARGET_DIRS if init._skill_target_active(gate, tools)]
        for entry in (lock.get("copies") or {}).values():  # own skills, as update.py's step builds them
            source_rel = entry.get("source") if isinstance(entry, dict) else None
            if (not isinstance(source_rel, str) or not source_rel.startswith(prefix)
                    or os.path.normpath(source_rel).replace("\\", "/") != source_rel):
                continue
            rel = source_rel[len(prefix):]
            if rel.split("/")[0] in cut or init.actlib.is_bytecode_cache(Path(rel)) or not (base / source_rel).is_file():
                continue
            for dest_root in active:
                expected.setdefault(f"{dest_root}/{rel}", base / source_rel)
        for change, dest in wanted:
            src = expected.get(dest)
            if src is None or dest in removed:
                continue
            try:
                source_rel = os.path.relpath(src, real).replace("\\", "/")
                if source_rel.startswith("../") or _link_in(root, f"{root.rstrip('/')}/{source_rel}", include_last=True):
                    continue
                if init.skill_copy_bytes(base, dest, Path(src)) == change["data"]:
                    found.append(change)
            except (OSError, ValueError, KeyError, AttributeError, TypeError):  # no verdict: reported
                continue
    except Exception:  # noqa: BLE001 -- no verdict at all: every change is reported
        return []
    finally:
        os.chdir(old_cwd)
    return found


def _anchors(state: dict, root: str) -> list[_Anchor]:
    """The places a restore may write below, fixed when the snapshot was taken: the project root (itself
    reached however the owner set it up) and the git directories recorded then, each with its real path.
    Nothing is read from the working tree here: a `.git` file or `commondir` rewritten since is a change of
    its own, never a new anchor."""
    anchors = [_Anchor(root.rstrip("/"), state["root_real"], False, True)]
    for item in state["gitdirs"]:
        if isinstance(item, list) and len(item) == 3 and isinstance(item[0], str) and isinstance(item[1], str):
            anchors.append(_Anchor(item[0].rstrip("/"), item[1], True, bool(item[2])))
    return anchors


def _anchor_for(path: str, anchors: list[_Anchor]) -> _Anchor | None:
    """The deepest anchor `path` lies strictly below (a path that IS an anchor -- a `.git` pointer file where
    the snapshot's git directory was -- belongs to the anchor above it)."""
    best: _Anchor | None = None
    for anchor in anchors:
        if _parts_below(anchor.path, path) and (best is None or len(anchor.path) > len(best.path)):
            best = anchor
    return best


def _blocked(anchor: _Anchor, path: str, root: str) -> str | None:
    """Why nothing may be removed or written at `path` now (None when it may): the anchor is not restorable;
    a git directory anchor is a link or no longer a directory; the anchor or the deepest existing parent does
    not resolve to the real path the snapshot recorded (a link planted above or below); a component between
    the anchor and the parent is a link."""
    if not anchor.restorable:
        return ("not restored (this git directory was first seen during a worker's call and does not lie below the "
                "project root in fact; a session start takes a trusted snapshot)")
    linked = _link_in(anchor.path, path, include_anchor=anchor.gitdir)
    if linked is None and anchor.gitdir and not os.path.isdir(anchor.path):
        return f"not restored (the git directory {_shown(root, anchor.path)} is no longer a directory)"
    if linked is None and not _same_place(anchor.path, anchor.real):
        linked = anchor.path
    if linked is None and _unexpected_parent(anchor, path):
        linked = os.path.dirname(path)
    if linked:
        return f"not restored (path goes through a link: {_shown(root, _norm(linked))})"
    return None


def _keep_reference(new_files: dict, change: dict) -> None:
    """A restore that did not happen: the snapshot entry stays the reference (a file that appeared has none),
    so the next call reports the change again instead of taking the worker's version as the new normal."""
    if change["old"] is not None:
        new_files[change["path"]] = change["old"]
    else:
        new_files.pop(change["path"], None)


def _restore(base: str, change: dict, stamp: str, new_files: dict, root: str, anchors: list[_Anchor]) -> dict:
    """Put one changed file back to the snapshot version (worker call, mode block). Returns the report
    fields: {"restored": bool, "kept": str | None, "how": str}. Every path is checked against the anchors of
    the snapshot first (_blocked); a path that fails is left alone and the snapshot entry stays the reference."""
    path, op, old = change["path"], change["op"], change["old"]
    result = {"restored": False, "kept": None, "how": ""}
    anchor = _anchor_for(path, anchors)
    if anchor is None:
        result["how"] = "not restored (the path is outside the watched places)"
    else:
        result["how"] = _blocked(anchor, path, root) or ""
    if anchor is None or result["how"]:
        _keep_reference(new_files, change)
        return result
    if op in ("added", "modified") and change["kind"] != _KIND_LINK:
        data = change.get("data")
        if data is None:
            data = _read_whole(path)
        result["kept"] = _keep(base, stamp, "changed", path, data)
    try:
        if op == "added" and change["kind"] == _KIND_LINK:
            _remove_link(path)
            del new_files[path]
            result.update(restored=True, how="the link was removed (what it pointed at was not touched)")
        elif op == "added":
            os.remove(path)
            del new_files[path]
            result.update(restored=True, how="removed")
        elif (change["kind"] == _KIND_CONFIG and op == "modified" and old.get("d") is not None
              and change["new"].get("d") is not None):
            if _restore_config_keys(path, old, change["new"]):
                digest, data = _read_hash(path)
                info = _stat_info(path, _KIND_CONFIG)
                new_files[path] = _entry(path, info, digest, data, base, _config_keys(path))
                result.update(restored=True, how="the changed keys were reset with `git config`")
            else:
                result["restored"] = _restore_whole(base, change, new_files, result, anchor.path)
        else:
            result["restored"] = _restore_whole(base, change, new_files, result, anchor.path)
    except OSError as exc:
        result["how"] = f"not restored ({type(exc).__name__}: {exc})"
    if not result["restored"]:
        _keep_reference(new_files, change)
    return result


def _restore_whole(base: str, change: dict, new_files: dict, result: dict, anchor: str) -> bool:
    """Write the snapshot copy of the file back. False (and a reason in result) when there is no copy."""
    path, old = change["path"], change["old"]
    if old is not None and old["k"] == _KIND_LINK:
        result["how"] = "not restored (the snapshot had a link here; a link is not recreated)"
        return False
    data = _read_blob(base, old["h"]) if old else None
    if data is None:
        result["how"] = "no copy of the snapshot version (file over 2 MB or copy missing): not restored"
        return False
    _write_atomic(path, data, anchor)
    if sys.platform != "win32":
        try:
            os.chmod(path, old.get("x", 0o644))
        except OSError:
            pass
    info = _stat_info(path, old["k"])
    restored = {key: value for key, value in old.items() if key != "r"}
    restored.update(m=info[0], s=info[1], r=True)  # just written: hashed once more next time
    new_files[path] = restored
    result["how"] = "restored from the snapshot taken before the call"
    return True


def _stat_info(path: str, kind: str) -> list:
    info = os.stat(path)
    return [info.st_mtime_ns, info.st_size, kind]


def _read_whole(path: str) -> bytes | None:
    try:
        with open(path, "rb") as handle:
            return handle.read(_MAX_COPY + 1)[:_MAX_COPY]
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

def _shown(root: str, path: str) -> str:
    prefix = root.rstrip("/") + "/"
    return path[len(prefix):] if path.startswith(prefix) else path


def _what(root: str, path: str) -> str:
    shown = _shown(root, path).lower()
    if shown == ".git" or shown == "commondir" or shown.endswith("/commondir"):
        return "pointer to the git directory"
    if "/hooks/" in "/" + shown or shown.endswith("/hooks"):
        return "git hook"
    if shown.endswith("config") or shown.endswith("config.worktree"):
        return "git config"
    if "/.claude/" in "/" + shown:
        return "Claude settings/role/skill"
    return "file that starts code when the folder is opened"


def _py_literal(text: str) -> str:
    """`text` as a Python string literal that holds only letters, digits, space, comma and `_./:@+=-`,
    everything else as an escape: safe inside double quotes for bash, PowerShell and cmd (no `$`, backtick, `"`, `%`,
    `!`, `^`, `&`, quote or backslash of its own survives to be expanded)."""
    out = []
    for ch in text:
        code = ord(ch)
        if (ch.isascii() and ch.isalnum()) or ch in _PLAIN_CHARS or ch in _QUOTED_CHARS:
            out.append(ch)
        elif code < 0x100:
            out.append(f"\\x{code:02x}")
        elif code < 0x10000:
            out.append(f"\\u{code:04x}")
        else:
            out.append(f"\\U{code:08x}")
    return "'" + "".join(out) + "'"


def _shell_arg(text: str) -> str | None:
    """`text` as an argument that is the same in bash, PowerShell and cmd: bare when it holds only letters,
    digits and `_./:@+=-` and does not begin with `@` (splatting in PowerShell: a bare `@x` vanishes) or `-`
    (an option); in double quotes when it also holds spaces or commas (PowerShell reads a bare `a,b` as an
    array) or begins with one of those; None for anything else."""
    if not text:
        return None
    plain = all((ch.isascii() and ch.isalnum()) or ch in _PLAIN_CHARS for ch in text)
    if plain and text[0] not in _NOT_FIRST:
        return text
    if plain or all((ch.isascii() and ch.isalnum()) or ch in _PLAIN_CHARS or ch in _QUOTED_CHARS for ch in text):
        return f'"{text}"'
    return None


def _git_command(args: list[str]) -> str:
    """`git <args>` for a human to paste into any shell: plain when every argument is plain (the watcher's
    own words -- `config`, `--file`, `--add`, `--` ... -- stay bare), otherwise one Python call that runs git
    with the arguments as escaped literals (nothing is left to the shell)."""
    quoted = [arg if arg in _GIT_WORDS else _shell_arg(arg) for arg in ["git", *args]]
    if all(item is not None for item in quoted):
        return " ".join(item for item in quoted if item is not None)
    return ("python -c \"import subprocess; subprocess.run(["
            + ", ".join(_py_literal(arg) for arg in ["git", *args]) + "], check=True)\"")


def _python_command(statement: str) -> str:
    return f'python -c "{statement}"'


def _restore_commands(base: str, change: dict, kept_before: str | None) -> list[str]:
    """The commands (one per line) that put the file back to the version before the call (orchestrator
    case: a report)."""
    path, op = change["path"], change["op"]
    if op == "added" and change["kind"] == _KIND_LINK:
        literal = _py_literal(path)
        return [_python_command(f"import os; p={literal}; os.rmdir(p) if os.name == 'nt' and os.path.isdir(p) else os.unlink(p)")]
    if op == "added":
        return [_python_command(f"import os; os.remove({_py_literal(path)})")]
    if change["kind"] == _KIND_CONFIG and change.get("keys"):
        commands = []
        for key, _what_changed, old_values, _new in change["keys"]:
            commands.append(_git_command(["config", "--file", path, "--unset-all", "--", key]))
            commands.extend(_git_command(["config", "--file", path, "--add", "--", key, value]) for value in old_values)
        return commands
    if kept_before:
        return [_python_command(f"import shutil; shutil.copyfile({_py_literal(kept_before)}, {_py_literal(path)})")]
    return ["(no copy of the previous version was kept: restore it from your own source)"]


def _describe(root: str, change: dict) -> str:
    op = change["op"] + (" as a link" if change["kind"] == _KIND_LINK and change["op"] != "removed" else "")
    text = f"{_shown(root, change['path'])} ({op}; {_what(root, change['path'])})"
    keys = change.get("keys")
    if keys:
        text += ": " + ", ".join(f"{what} {key}" for key, what, _o, _n in keys[:4])
        if len(keys) > 4:
            text += f", +{len(keys) - 4} more"
    return text


def _who(payload: dict) -> str:
    agent_id = payload.get("agent_id")
    if not agent_id:
        return "the orchestrator"
    role = payload.get("agent_type")
    return f"worker `{role}` ({agent_id})" if isinstance(role, str) and role else f"worker {agent_id}"


# ---------------------------------------------------------------------------
# The watcher
# ---------------------------------------------------------------------------

def _timestamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def watch(event: str, payload: dict, root: str | None = None) -> dict | None:
    """Compare the protected files with the snapshot. None when nothing changed (the common case);
    otherwise {"context": text for the model, "message": text for the human}."""
    root = root or _project_root()
    mode = watch_mode(root)
    if mode == "off":
        return None
    base = _base(root)
    state = _load_state(base)
    if state is None or not _same_root(state.get("root"), root):
        snapshot(root, payload.get("session_id"), trusted=not payload.get("agent_id"))
        return None
    files = state["files"]
    scan = _scan(root, _gitdir_paths(state))
    if not _dirty(files, scan):
        return None
    _assert_base_clear(root)
    with _Lock(base) as lock:
        if not lock.held:
            return None  # another hook process is judging this very change
        state = _load_state(base)
        if state is None or not _same_root(state.get("root"), root):
            return None
        files = state["files"]
        scan = _scan(root, _gitdir_paths(state))
        if not _dirty(files, scan):
            return None
        new_files, changes = _examine(base, files, scan)
        for change in changes:
            if change["kind"] == _KIND_CONFIG and change["new"] is not None:
                change["keys"] = _diff_keys(change["old"], change["new"])
        worker = bool(payload.get("agent_id"))
        if not worker:  # the orchestrator's own skill copies (act-update, session start) are no news
            own = _own_skill_copies(changes, root)
            changes = [change for change in changes if not any(change is done for done in own)]
        if not changes:
            _save_state(base, state, new_files)
            return None
        stamp = _timestamp()
        restoring = worker and mode == "block"
        anchors = _anchors(state, root) if restoring else []
        results = []
        for change in changes:
            added = _reportable_addition(base, change, root) if restoring else None
            if added:
                # only entries added to permissions.allow: reported, never put back; the changed file is the
                # reference from now on (new_files already holds it), the previous version is kept
                before = _keep(base, stamp, "before", change["path"], _read_blob(base, change["old"]["h"]))
                results.append({"restored": False, "kept": before, "how": "", "added": added})
            elif restoring:
                results.append(_restore(base, change, stamp, new_files, root, anchors))
            else:
                before = None
                old = change["old"]
                if change["op"] != "added" and old is not None:
                    before = _keep(base, stamp, "before", change["path"], _read_blob(base, old["h"]))
                results.append({"restored": False, "kept": before, "how": ""})
        _save_state(base, state, new_files)
    _log_restores(root, payload, changes, results, restoring)
    return _report(event, payload, root, base, changes, results, restoring)


_KIND_WORDS = (("pointer to the git directory", "git-pointer"), ("git hook", "git-hook"), ("git config", "git-config"),
               ("Claude settings/role/skill", "claude-files"))


def _log_restores(root: str, payload: dict, changes: list, results: list, restoring: bool) -> None:
    """The incident log (.act/scripts/incidents.py): one row `restored` for the files of this call that were put
    back, one `restore-failed` for those that could not be. Identifiers only: the tool, the kinds of file
    (`git-hook`, `claude-files` ...) and their number, never a path. A change that is only reported (the
    orchestrator's, mode `warn`, an added `permissions.allow` entry) is no incident. Never raises."""
    if not restoring:
        return
    try:
        scripts = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "scripts"))
        if scripts not in sys.path:
            sys.path.append(scripts)
        import incidents  # noqa: WPS433 -- lazy on purpose: only a change that was really made gets here
        from pathlib import Path

        tool = payload.get("tool_name") if isinstance(payload.get("tool_name"), str) else "tool"
        for kind, done in (("restored", True), ("restore-failed", False)):
            picked = [change for change, result in zip(changes, results)
                      if not result.get("added") and bool(result.get("restored")) == done]
            if not picked:
                continue
            words = sorted({dict(_KIND_WORDS).get(_what(root, change["path"]), "startup-file") for change in picked})
            incidents.record(Path(root), kind, "protected_watch", f"{tool} {'+'.join(words)} x{len(picked)}", "worker")
    except Exception:  # noqa: BLE001 -- the log must never change what the watcher does
        pass


def _same_root(stored: object, root: str) -> bool:
    return isinstance(stored, str) and os.path.normcase(stored) == os.path.normcase(root)


def _dirty(files: dict, scan: dict) -> bool:
    if len(files) != len(scan):
        return True
    for path, info in scan.items():
        entry = files.get(path)
        if entry is None or entry["m"] != info[0] or entry["s"] != info[1] or entry.get("r"):
            return True
    return False


def _report(event: str, payload: dict, root: str, base: str, changes: list, results: list, restoring: bool) -> dict:
    who = _who(payload)
    tool = payload.get("tool_name") if isinstance(payload.get("tool_name"), str) else "a tool"
    listed = changes[:_MAX_LISTED]
    lines = []
    for change, result in zip(listed, results):
        line = f"- {_describe(root, change)}"
        if restoring and result.get("added"):
            shown = ", ".join(json.dumps(item[:200]) for item in result["added"][:_MAX_LISTED])  # JSON escapes control characters
            line += (f" -> only entries added to permissions.allow ({shown}"
                     + (f", +{len(result['added']) - _MAX_LISTED} more" if len(result["added"]) > _MAX_LISTED else "")
                     + "): reported, not put back")
            if result["kept"]:
                line += f"; previous version kept at {_shown(root, result['kept'])}"
        elif restoring:
            line += f" -> {result['how'] or 'not restored'}"
            if result["kept"]:
                line += f"; changed version kept at {_shown(root, result['kept'])}"
        lines.append(line)
    if len(changes) > len(listed):
        lines.append(f"- and {len(changes) - len(listed)} more")
    head = f"{who} changed protected files with {tool}{' (call failed)' if event == 'PostToolUseFailure' else ''}"
    if restoring and all(result.get("added") for result in results):
        context = (
            f"[act] protected-watch: {head}: only entries were added to the permissions.allow list of "
            ".claude/settings.local.json (Claude Code writes that when the owner answers \"always allow\").\n"
            + "\n".join(lines)
            + "\nReported, not put back; the file as it stands is the reference from now on. Do not edit Claude settings "
            "yourself (R-safe-git-metadata); if you did not expect this, say so in your result."
        )
        message = f"ℹ️ PERMISSIONS ADDED to .claude/settings.local.json during a call by {who} (reported, not put back):\n" + "\n".join(lines)
        note = (
            f"[act] protected-watch: {who} was running when entries were added to permissions.allow in "
            f".claude/settings.local.json (call to {tool}); reported, not put back. Tell the human if it was not an "
            "\"always allow\" answer.\n" + "\n".join(lines)
        )
        try:
            queue_orchestrator_note(root, note)
        except OSError:
            pass
        return {"context": context, "message": message}
    if restoring:
        all_back = all(result["restored"] for result in results if not result.get("added"))
        kept_addition = any(result.get("added") for result in results)
        except_addition = " except the reported permissions.allow addition" if kept_addition else ""
        context = (
            f"[act] protected-watch: {head} (R-safe-git-metadata: a worker never writes these).\n" + "\n".join(lines)
            + (f"\nThe files were put back{except_addition}. " if all_back else "\nSome files could NOT be put back. ")
            + "Do not try again; name the file and the change you need in your result and let the orchestrator decide."
        )
        message = (
            f"⚠️ PROTECTED FILES CHANGED by {who}"
            + (f" - put back{except_addition}" if all_back else " - NOT all put back")
            + ":\n" + "\n".join(lines)
        )
        note = (
            f"[act] protected-watch: {who} changed protected files during a call to {tool}; "
            + (f"put back{except_addition}" if all_back else "not all put back")
            + " (R-safe-git-metadata). Tell the human.\n" + "\n".join(lines)
        )
        try:
            queue_orchestrator_note(root, note)
        except OSError:
            pass
        return {"context": context, "message": message}
    commands = []
    for change, result in zip(changes[:_MAX_LISTED], results):
        commands.extend(f"  {line}" for line in _restore_commands(base, change, result["kept"]))
    context = (
        f"[act] protected-watch: {head} (R-safe-git-metadata).\n" + "\n".join(lines)
        + "\nReported only; the new state is the reference from now on. If this was not intended, tell the human now. "
        "To put back the previous version the human runs (the assistant's own writes to hooks and git config are refused):\n"
        + "\n".join(commands)
    )
    message = f"⚠️ PROTECTED FILES CHANGED by {who} (reported only):\n" + "\n".join(lines)
    return {"context": context, "message": message}


# ---------------------------------------------------------------------------
# Notes for the orchestrator (a worker's change, a worker's model switch)
# ---------------------------------------------------------------------------

def queue_orchestrator_note(root: str, text: str) -> None:
    """Leave a note that the orchestrator's next tool call (PostToolUse/PostToolUseFailure of the main
    session) delivers as additionalContext. OSError when `.act-local` is a link."""
    _assert_base_clear(root)
    folder = _base(root) + "/notes"
    os.makedirs(folder, exist_ok=True)
    _write_atomic(f"{folder}/{time.time_ns()}-{os.getpid()}.txt", text.encode("utf-8"), root)


def take_orchestrator_notes(root: str | None = None) -> list[str]:
    """The queued notes, oldest first, each delivered once; [] (one failed scandir) when there are none."""
    root = root or _project_root()
    folder = _base(root) + "/notes"
    try:
        names = sorted(name for name in os.listdir(folder) if name.endswith(".txt"))
    except OSError:
        return []
    if names and _link_in(root, folder + "/x"):
        return []  # nothing is read, renamed or removed through a link
    notes: list[str] = []
    for name in names:
        path = f"{folder}/{name}"
        info = _lstat(path)
        if info is None or _is_link_info(info) or not stat.S_ISREG(info.st_mode):
            continue  # a link or anything but a plain file is neither read nor removed
        claimed = f"{path}.taken-{os.getpid()}"
        try:
            os.replace(path, claimed)
            with open(claimed, encoding="utf-8", errors="replace") as handle:
                text = handle.read(_MAX_NOTE)
            os.remove(claimed)
        except OSError:
            continue
        if text.strip():
            notes.append(text.strip())
    return notes


# ---------------------------------------------------------------------------
# Entry point for dispatch.py
# ---------------------------------------------------------------------------

def run(event: str, payload: dict) -> dict | None:
    """What dispatch.py calls after every tool call (PostToolUse in its early block, PostToolUseFailure in
    main): the watcher, plus the queued notes for the orchestrator's own calls. Returns None when there is
    nothing to say, else {"context": str, "message": str} (message may be empty)."""
    root = _project_root()
    context: list[str] = []
    message: list[str] = []
    try:
        found = watch(event, payload, root)
    except Exception as exc:  # noqa: BLE001 -- a watcher bug must never block or corrupt the hook output
        print(f"[act] protected-watch skipped ({type(exc).__name__}: {exc})", file=sys.stderr)
        found = None
    if found:
        context.append(found["context"])
        message.append(found["message"])
    if not payload.get("agent_id"):
        try:
            context.extend(take_orchestrator_notes(root))
        except Exception as exc:  # noqa: BLE001
            print(f"[act] orchestrator notes skipped ({type(exc).__name__}: {exc})", file=sys.stderr)
    if not context and not message:
        return None
    return {"context": "\n".join(context), "message": "\n".join(message)}
