#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: The one place where the migrations (NNN-*.py in this folder) test whether a path may be written, and
#          write a file safely. A migration never writes through a symbolic link or a Windows junction, and
#          never to a place whose real path leaves the project: it skips that file or folder and says so in
#          its plan/apply line. This module is not a migration (update.py picks up NNN-*.py only); each
#          migration loads it by file name from its own folder (importlib, see the top of 008-done-entries-keep.py).
#          Why not `actlib`: a migration must not depend on the *project's* possibly-older copy of it, so
#          the same test as `actlib.link_problem` is kept here, stdlib only, in the same words.
#
# Usage: not run directly.
#   link_problem(root, path) -> str        "" when `path` may be written, else one short reason
#   LinkCheck(root).problem(path)          the same, remembering folders already examined (long scans)
#   list_links(root, paths) -> list[str]   the link components (project-relative) among `paths`, each once
#   write_replace(target, data, keep_mode) replace `target` by `data` through an exclusive temp file
#   write_new(target, data)                create `target` through an exclusive temp file
# Python 3.9 and later: a junction is recognized by the attributes of an os.lstat result, since
# os.path.islink and Path.is_symlink are False for a junction in every version (3.12 added is_junction).

from __future__ import annotations

import os
import secrets
import shutil
import stat
from pathlib import Path
from typing import Iterable

_REPARSE_POINT = 0x400        # FILE_ATTRIBUTE_REPARSE_POINT (st_file_attributes)
_NAME_SURROGATE = 0x20000000  # reparse tag bit: the point stands for another file system object


def _is_redirect(info: os.stat_result) -> bool:
    """True for a symbolic link, a junction or another reparse point that stands for another file system
    object; a reparse point of unknown tag counts as one."""
    if stat.S_ISLNK(info.st_mode):
        return True
    if not getattr(info, "st_file_attributes", 0) & _REPARSE_POINT:
        return False
    tag = getattr(info, "st_reparse_tag", 0)
    return not tag or bool(tag & _NAME_SURROGATE)


class LinkCheck:
    """The link test for one project `root`; folders already examined are remembered, so a scan of many
    files in few folders costs one `os.lstat` per file and one per folder."""

    def __init__(self, root: Path) -> None:
        self.root = os.path.abspath(root)
        self._folders: dict[str, str] = {}

    def _below(self, path: str) -> bool:
        try:
            return os.path.commonpath([os.path.normcase(self.root), os.path.normcase(path)]) == os.path.normcase(self.root)
        except ValueError:  # another drive
            return False

    def _shown(self, path: str) -> str:
        try:
            return Path(path).relative_to(self.root).as_posix() or "."
        except ValueError:
            return Path(path).name or "?"

    def _folder(self, folder: str) -> str:
        if os.path.normcase(folder) == os.path.normcase(self.root):
            return ""  # the root itself may be reached through a link, as the owner set it up
        known = self._folders.get(os.path.normcase(folder))
        if known is None:
            known = self._entry(folder)
            self._folders[os.path.normcase(folder)] = known
        return known

    def _entry(self, path: str) -> str:
        if not self._below(path):
            return f"{self._shown(path)} is not below the project"
        reason = self._folder(os.path.dirname(path))  # the way down from the root first: the top link is named
        if reason:
            return reason
        try:
            info = os.lstat(path)
        except (FileNotFoundError, NotADirectoryError):
            return ""  # nothing there yet: what is created there is a real file or folder
        except OSError:
            return f"{self._shown(path)} cannot be examined"
        if _is_redirect(info):
            return f"{self._shown(path)} is a link or junction"
        if stat.S_ISDIR(info.st_mode) and _outside(self.root, path):
            return f"{self._shown(path)} resolves outside the project"
        return ""

    def problem(self, path: Path) -> str:
        """"" when `path` may be written: no component from the root down to it (itself included) is a link
        or junction and, for a folder, its real path stays under the real path of the root. Else one short
        reason. The result holds for the moment of the call; a link planted later is not caught."""
        target = os.path.abspath(path)
        if os.path.normcase(target) == os.path.normcase(self.root):
            return ""
        return self._entry(target)


def _outside(root: str, path: str) -> bool:
    try:
        real_root = os.path.normcase(os.path.realpath(root))
        real = os.path.normcase(os.path.realpath(path))
        return os.path.commonpath([real_root, real]) != real_root
    except (OSError, ValueError):  # unresolvable is unsafe; ValueError: another drive
        return True


def link_problem(root: Path, path: Path) -> str:
    """LinkCheck(root).problem(path), for a single path."""
    return LinkCheck(root).problem(path)


def list_links(root: Path, paths: Iterable[Path]) -> list[str]:
    """The distinct reasons `problem` gives for those of `paths` that may not be written, in order of first
    appearance: a linked folder with many files below it is named once."""
    check = LinkCheck(root)
    found: list[str] = []
    for path in paths:
        problem = check.problem(path)
        if problem and problem not in found:
            found.append(problem)
    return found


def _open_temp(target: Path) -> tuple[int, Path]:
    """A new temporary file next to `target`, created exclusively (O_EXCL, O_NOFOLLOW where it exists): a
    file or link already standing at that name is never opened. Returns (descriptor, path). The name holds
    a random part, so two runs never share one."""
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    for _attempt in range(20):
        temp = target.with_name(f".{target.name}.{secrets.token_hex(4)}.migrating")
        try:
            return os.open(temp, flags, 0o666), temp
        except FileExistsError:
            continue
    raise FileExistsError(f"no free temporary name next to {target.name}")


def _write_through_temp(target: Path, data: bytes, keep_mode: bool) -> None:
    descriptor, temp = _open_temp(target)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        if keep_mode:
            shutil.copymode(target, temp)
        os.replace(temp, target)
    except BaseException:
        try:
            os.chmod(temp, stat.S_IWRITE)  # copymode may have made it read-only: it must still be removable
        except OSError:
            pass
        temp.unlink(missing_ok=True)
        raise


def write_replace(target: Path, data: bytes) -> None:
    """Replace the existing `target` by `data` through a temporary file in the same folder and os.replace, so
    an abort leaves the old or the new file, never a cut-off one; the file mode is kept. The temporary file
    is gone on every path out of here."""
    _write_through_temp(target, data, True)


def write_new(target: Path, data: bytes) -> None:
    """Create `target` with `data` through a temporary file in the same folder and os.replace; the temporary
    file is gone on every path out of here."""
    _write_through_temp(target, data, False)
