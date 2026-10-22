#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check - a tool call that reaches outside the project (PreToolUse): the model reads or
#          writes a path that lies neither in the project, nor in a place the project has opened,
#          nor in one of the few places Claude Code itself works in. A guardrail next to
#          `R-safe-no-secret-read` (which keeps a secret out of the context): this one keeps the
#          assistant inside the folder the owner pointed it at, so another repository, a home
#          directory or a system folder is never read or changed by accident. Applies to
#          **everyone** - orchestrator and worker alike. The matching rule text is
#          `R-safe-outside-root`; this module only enforces it.
#
#          Covered: Read, Write, Edit, MultiEdit, NotebookEdit, NotebookRead (their path field),
#          Grep and Glob (`path`, and `glob`/`pattern` when they carry a path of their own), and
#          Bash/PowerShell commands: every path-like word of the command line counts as a read
#          (absolute, `~`, a drive letter, UNC, Git-Bash `/d/...`, a relative path with a `..`
#          segment, a `cd` or `git -C` target, the value of a `NAME=path` word, the text of an
#          `echo`/`printf` that is piped into `xargs`, the string after `cmd /c`), every write
#          target the shared write-target scanners find (`>`, `tee`, `mv`, `Set-Content`, ...) as a
#          write. A command that runs in a directory outside the allowed places (the session itself
#          started there) reads that directory. MCP tools are not looked at.
#
#          Two readings of a path word. The file tools expand nothing, so their path is taken
#          literally (`$x`, `{a,b}` and `%X%` are plain characters) and `x/..` is cut out as text, as
#          Windows and Node do; a Glob/Grep pattern is read per `{a,b}` alternative. In the shell a
#          word with a variable or substitution counts up to its literal directory prefix
#          (`D:/x/$v/y` -> `D:/x/`), a glob up to its literal directory.
#
#          Allowed without an entry: the project root; `permissions.additionalDirectories` of
#          `.claude/settings.json` and `.claude/settings.local.json`; the system temp directories
#          (the scratchpad and worker output files live there) and the payload's `scratchpad_dir`;
#          Claude Code's own folder for this project (`<claude dir>/projects/<project>`: memory,
#          transcripts, offloaded tool output); `<claude dir>/plans` (plan mode writes there);
#          read-only `<claude dir>/plugins` and `<claude dir>/skills`; the places listed in the
#          `outside-root-allow` row of docs/ai/config.md (a path relative to the project root or
#          starting with `~`, ` (read)` behind it = read-only; an entry with glob characters opens
#          only what its pattern hits, `../zone/o*` the folders of `zone` that start with `o`, never
#          `zone` itself); and, while a marker younger than 24 hours says so, the target folder of an
#          act-adopt run (`.act-local/outside-allow/adopt.json`, written by the adopt scripts from
#          inside Python). A marker target that would open far more than one project counts as
#          broken: a drive root, `/`, a UNC share root, the home directory or a directory above it,
#          the project root or a directory above it. The marker folder itself is write-locked for
#          the model: a write there is a finding like any other, and so is a copy, an unpacking or
#          a sync that can create it from a parent (see "writes that can create the marker folder").
#
#          Mode: `outside-root` in docs/ai/config.md § Checks (block | warn | off); a missing key
#          means `warn`, `ACT_OUTSIDE_ROOT` overrides it for one run. Under `warn` the message goes
#          to stdout and the call passes.
#
# Failure: this module is deliberately NOT in dispatch.py's `_FAIL_CLOSED` set. The default mode is
#          `warn`, and a crash of an accident guard must not refuse every Bash or Write call (the
#          owner could not even edit the config row that switches it off). A crash in the dispatcher
#          therefore skips the check with one line on stderr, like `secret_read`; inside this
#          module each scanner runs on its own, so a bug in one (say the PowerShell target
#          scanner) does not hide what the others found.
#
# Known limits:
#   - a program that touches the path itself stays invisible (`python script.py`, `node app.js`);
#     only string literals of an interpreter's inline code (`python -c`, ...) are looked at.
#   - a path built from a variable or a command substitution (`cat "$X/.."`, `$(pwd)/..`) is judged
#     only up to its literal prefix, so `cat /safe-place/$X/../..` passes when the prefix is allowed;
#     a brace list in a shell word is not expanded. A glob is judged by its literal directory prefix.
#   - paths are compared after resolving them (symlinks followed; a path of more than 40 segments is
#     cut lexically instead, which keeps a `cd a; cd a; ...` chain from costing quadratic time).
#     Nothing is looked up on the network: a UNC path to another host is compared as written. NTFS
#     data streams (`f:name`, `f::$DATA`) are cut off; Windows short names (`PROGRA~1`) and trailing
#     dots or spaces in a segment are compared as written.
#   - a command line with more than 150 `cd`-like statements is not given to the shared write-target
#     scanners (their cost grows with the cube of such a chain: 800 statements took 20 seconds);
#     the words are still read as reads, and a word naming the marker folder counts as a write.
#   - the `cd` tracking is lexical and best effort: a relative word counts only if it leaves the
#     allowed places from every directory the scanner thinks the shell may be in.
#   - heuristics against false alarms, all best effort: the program word, the text of `echo`/
#     `printf`, the value of `-m`/`--message`/`--body`/`--title`, URLs, the search pattern of
#     `grep`/`rg`, the script of `sed`/`awk`/`jq` and the value of `find -name` are not paths. A
#     path hidden behind one of those words goes unseen. A lone `/` is not a path, and on Windows
#     a one-segment word such as `/c` or `/s` is a switch.
#   - a tree with a hidden `.act-local/outside-allow/` staged inside the project and copied into the
#     project root as `dir/.` is not followed (only such a source from outside the project is, since a
#     copy inside the project is everyday work); nor are links (`ln -s`).
#   - the system temp directory is open as a whole: a project that itself lies in it sees its
#     neighbours as allowed (unlike the worker write scope, which carves that case out).
#   - shares command_words.py's, shell_targets.py's and powershell_targets.py's own limits for
#     tokenizing.

from __future__ import annotations

import fnmatch
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import actlib

from .brace_expand import expand_braces
from .command_words import _command_word_lists_new, _strip_command_prefix, _stripped_word_lists
from .common import _TOOL_PATH_FIELDS, _check_mode, _shell_command
from .powershell_targets import _powershell_write_targets, _ps_raw_redirect_targets
from .secret_read import (
    _GREP_FAMILY,
    _HOME_TOKEN_RE,
    _INTERPRETERS,
    _LITERAL_RE,
    _candidate_words,
    _grep_pattern_index,
    _ps_word_lists,
)
from .shell_targets import (
    _GIT_WRITES_WORKER_SCOPE,
    _bash_write_targets,
    _command_name,
    _heredoc_may_feed_shell,
    _resolve_path,
    _to_native_path,
)
from .write_scope import _external_directories, _read_json_object, _system_temp_roots

__all__ = ["check_outside_root"]

# Environment variable that overrides `outside-root` for one run (block | warn | off).
_ENV_OVERRIDE = "ACT_OUTSIDE_ROOT"
_ENTRY_TTL = timedelta(hours=24)
_MARKER_PARTS = (".act-local", "outside-allow")
_MARKER_FILE = "adopt.json"
_MAX_BASES = 8
_MAX_NAMED = 3
# More `cd`-like statements than this and the shared write-target scanners are not run (see _shell_findings).
_MAX_CD_FOR_TARGET_SCAN = 150
_CD_WORD_RE = re.compile(r"(?<![\w./-])(?:cd|chdir|pushd|set-location|sl|push-location)(?![\w./-])", re.IGNORECASE)
# Paths with more segments than this are cut lexically, not resolved (symlinks are not followed there).
_MAX_RESOLVE_SEGMENTS = 40
# A key that no real directory key can contain: a POSIX-rooted path on Windows has no drive, so it
# lies outside every place without being comparable to one.
_POSIX_PREFIX = "\0posix:"

_PS_ASSIGN_RE = re.compile(r"^\$\w+$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_UNC_RE = re.compile(r"^(?:\\\\|//)[^\\/\s]+[\\/]+[^\\/\s]")
_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]+://")
_FILE_URL_RE = re.compile(r"^file:/{2,3}(?=[A-Za-z]:|/|[^/])", re.IGNORECASE)
_DYNAMIC_RE = re.compile(r"[$`{]|%[A-Za-z_][A-Za-z0-9_]*%")
# (`//ve` is how Git Bash spells the Windows switch `/ve`, so that it is not turned into a path.)
_SWITCH_RE = re.compile(r"^/{1,2}[A-Za-z?][A-Za-z0-9:?=,+-]*$")
_GLOB_CHARS = "*?["
_SEGMENT_SPLIT_RE = re.compile(r"[\\/]")

# Commands whose arguments are text, not files.
_TEXT_COMMANDS = frozenset({
    "echo", "printf", "write-host", "write-output", "write-error", "write-warning", "write-verbose",
    "write-information",
})
# Options whose next word (or `=` value) is free text: a commit message, a PR title.
_MESSAGE_FLAGS = frozenset({
    "-m", "--message", "--body", "--title", "--subject", "--description", "--notes", "-message",
    "-body", "-title",
})
_GREP_LIKE = frozenset({"grep", "egrep", "fgrep", "rg", "ag", "ack"})
_EXPRESSION_COMMANDS = _GREP_LIKE | {"sed", "awk", "gawk", "mawk"}
_EXPRESSION_FLAGS = frozenset({"-e", "--regexp", "--expression"})
_SCRIPT_COMMANDS = frozenset({"sed", "awk", "gawk", "mawk", "jq", "yq"})
_SCRIPT_FLAGS = frozenset({"-e", "-f", "--expression", "--file"})
_FIND_VALUE_FLAGS = frozenset({
    "-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename", "-regex", "-iregex", "-lname",
    "-ilname",
})
_SELECT_STRING = frozenset({"select-string", "sls"})
_CD_NAMES = frozenset({"cd", "chdir", "pushd", "set-location", "sl", "push-location"})


@dataclass
class _Places:
    """The directories a call may reach, as comparison keys (see `_key`): `writable` ones for read
    and write, `readonly` ones for reading only."""

    writable: list[str] = field(default_factory=list)
    readonly: list[str] = field(default_factory=list)
    # Entries with glob characters (`outside-root-allow`): (compiled pattern, read-only).
    patterns: list[tuple[re.Pattern, bool]] = field(default_factory=list)

    def add(self, key: Optional[str], read_only: bool = False) -> None:
        if not key:
            return
        target = self.readonly if read_only else self.writable
        if key not in target:
            target.append(key)

    def add_pattern(self, pattern: re.Pattern, read_only: bool = False) -> None:
        self.patterns.append((pattern, read_only))

    def allows(self, key: str, write: bool) -> bool:
        if any(_under(key, base) for base in self.writable):
            return True
        if not write and any(_under(key, base) for base in self.readonly):
            return True
        return any(
            (not write or not read_only) and _pattern_hits(pattern, key) for pattern, read_only in self.patterns
        )


@dataclass
class _Finding:
    raw: str
    key: str
    write: bool
    shown: str
    lock: bool = False


def _key(path: object) -> str:
    """`path` as a comparison key: platform case rules applied, no trailing separator."""
    text = os.path.normcase(str(path))
    return text.rstrip("\\/") or text


def _under(key: str, base: str) -> bool:
    return key == base or key.startswith(base + os.sep) or key.startswith(base + "/")


def _forward(key: str) -> str:
    return key.replace("\\", "/")


def _pattern_hits(pattern: re.Pattern, key: str) -> bool:
    """True when the entry pattern matches `key` itself or one of its parent directories (a pattern
    names a place, and everything below the place is open)."""
    text = _forward(key)
    while True:
        if pattern.fullmatch(text):
            return True
        cut = text.rfind("/")
        if cut <= 0:
            return False
        text = text[:cut]


def _glob_regex(pattern: str) -> re.Pattern:
    """A forward-slash glob as a regular expression: `*` and `?` stay inside one path segment, `**`
    crosses segments, `[...]` is a character class."""
    out: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if pattern.startswith("**", index):
            out.append(".*")
            index += 2
            continue
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        elif char == "[" and "]" in pattern[index + 2:]:
            end = pattern.index("]", index + 2)
            body = pattern[index + 1:end]
            out.append("[" + ("^" + body[1:] if body.startswith("!") else body).replace("\\", "\\\\") + "]")
            index = end
        else:
            out.append(re.escape(char))
        index += 1
    return re.compile("".join(out), re.IGNORECASE if os.name == "nt" else 0)


def _home() -> Optional[str]:
    try:
        return str(Path.home())
    except (RuntimeError, OSError, KeyError):
        return None


def _cut_glob(text: str) -> str:
    """The literal directory prefix of a path with glob characters (`D:/x/*.py` -> `D:/x/`); the
    text itself without any; empty when the glob starts the path."""
    positions = [text.find(char) for char in _GLOB_CHARS if char in text]
    if not positions:
        return text
    prefix = text[: min(positions)]
    cut = max(prefix.rfind("/"), prefix.rfind("\\"))
    return prefix[: cut + 1] if cut >= 0 else ""


def _dynamic_prefix(text: str) -> str:
    """The literal directory prefix of a shell word before its first expansion (`D:/x/$v/y` ->
    `D:/x/`, `/usr/bin:$PATH` -> empty): what the shell leaves of the word is known only up to
    there. A POSIX-rooted word with a `:` in it is a search-path list (`PATH`), no single path."""
    if text[:1] == "/" and text[1:2] != "/" and ":" in text:
        return ""  # `/usr/bin:/bin`, `/usr/bin:$PATH`
    match = _DYNAMIC_RE.search(text)
    if not match:
        return text
    prefix = text[: match.start()]
    cut = max(prefix.rfind("/"), prefix.rfind("\\"))
    prefix = prefix[: cut + 1] if cut >= 0 else ""
    return "" if prefix.strip("/\\") == "" else prefix


def _collapse_dotdot(text: str) -> str:
    """`text` with its `.` and `..` segments cut out purely as text, the way Windows and Node do for a
    path they never expand (`D:/x/{y}/../a` -> `D:/x/a`); the drive or UNC prefix stays as it is."""
    match = re.match(r"^(?:[A-Za-z]:)?(?:[\\/]{1,2})?", text)
    prefix = match.group(0) if match else ""
    parts = _SEGMENT_SPLIT_RE.split(text[len(prefix):])
    rooted = prefix[-1:] in ("/", "\\")
    if len(prefix) == 2 and prefix[1] != ":" and len(parts) >= 2:
        prefix += parts[0] + "/" + parts[1] + "/"  # UNC: host and share stay put
        parts = parts[2:]
    stack: list[str] = []
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            if stack and stack[-1] != "..":
                stack.pop()
            elif not rooted:
                stack.append(part)
            continue
        stack.append(part)
    return prefix + "/".join(stack)


def _strip_stream(text: str) -> str:
    """On Windows a `:name` after the file name (`f.json:zone`, `f.json::$DATA`) is an NTFS data stream
    of the same file: cut it off, so the file is judged as itself. A drive letter's colon stays; a
    POSIX-rooted word is left alone."""
    if sys.platform != "win32" or (text[:1] in ("/", "\\") and not _UNC_RE.match(text)):
        return text
    drive = 2 if re.match(r"^[A-Za-z]:", text) else 0
    cut = text.find(":", drive)
    return text if cut < 0 else text[:cut]


def _resolve_text(raw: str, base: Optional[str], bash: bool, mode: str = "shell") -> Optional[str]:
    """`raw` as one absolute, resolved path text (a pseudo text for a POSIX-rooted path on Windows),
    or None where it cannot be known (a variable, a relative path with no base) or is no file (the
    null device, a switch). `mode` says who reads the word: "shell" expands it (a word with a variable
    or command substitution counts up to its literal prefix, a glob up to its literal directory),
    "file" is the path of a file tool, which expands nothing (taken literally, `..` collapsed as
    text), "glob" is the pattern of Glob or Grep (globs cut, nothing else expanded)."""
    text = raw.strip().strip("'\"")
    if not text or "\0" in text:
        return None
    if mode == "file":
        if text == "~" or text.startswith(("~/", "~\\")):
            home = _home()
            if home is None:
                return None
            text = home + text[1:]
    else:
        match = _HOME_TOKEN_RE.match(text)
        if match:
            home = _home()
            if home is None:
                return None
            text = home + text[match.end():]
        elif text.startswith("~"):
            return None  # `~user`: not knowable here
    text = _FILE_URL_RE.sub("", text, count=1)
    # The native drive form first (`/d/x`, the extended-length `\\?\D:\x`, the admin share
    # `\\localhost\C$\x`): the prefix holds a `?` that the glob cut below would take for a wildcard,
    # the share a `$` that the dynamic cut would.
    text = _to_native_path(text)
    if mode == "shell":
        text = _dynamic_prefix(text)
    if mode != "file":
        text = _cut_glob(text)
    elif ".." in _SEGMENT_SPLIT_RE.split(text):
        text = _collapse_dotdot(text)
    text = _strip_stream(text)
    if not text:
        return None
    if text == "/dev" or text.startswith("/dev/"):
        return None
    if sys.platform == "win32" and text[0] in "/\\" and not _UNC_RE.match(text):
        # No drive form: a path of the POSIX side.
        if bash and (text == "/tmp" or text.startswith("/tmp/")):
            roots = _system_temp_roots()
            if not roots:
                return None
            text = str(roots[0]) + text[4:]
        elif _SWITCH_RE.match(text):
            return None
        else:
            return _POSIX_PREFIX + text
    candidate = text if os.path.isabs(text) else (os.path.join(base, text) if base else None)
    if candidate and len(_SEGMENT_SPLIT_RE.split(candidate)) > _MAX_RESOLVE_SEGMENTS:
        # Resolving walks every segment of the path and costs O(depth) file system calls; a chain of
        # `cd sub &&` a thousand times makes that quadratic. Far past any real directory depth the
        # path is cut lexically instead.
        return os.path.normpath(candidate)
    resolved = _resolve_path(text, base)
    return str(resolved) if resolved is not None else None


def _resolve_key(raw: str, base: Optional[str], bash: bool, mode: str = "shell") -> Optional[str]:
    text = _resolve_text(raw, base, bash, mode)
    return _key(text) if text else None


def _looks_like_path(candidate: str, strict: bool = False) -> bool:
    """True when a command word names a place on its own: a home token, a drive letter, a UNC or
    rooted path, or (not `strict`) a relative path with a `..` segment. A URL is no path."""
    text = candidate.strip().strip("'\"")
    if text == "~":
        return True
    if len(text) < 2 or _URL_RE.match(text):
        return False
    if _HOME_TOKEN_RE.match(text) or _DRIVE_RE.match(text) or _UNC_RE.match(text):
        return True
    if text[0] == "/":
        return True
    if strict:
        return False
    return ".." in _SEGMENT_SPLIT_RE.split(text)


def _is_rooted(text: str) -> bool:
    stripped = text.strip().strip("'\"")
    return bool(
        _HOME_TOKEN_RE.match(stripped) or _DRIVE_RE.match(stripped) or _UNC_RE.match(stripped)
        or stripped[:1] in ("/", "\\")
    )


# --- allowed places ----------------------------------------------------------------------------

def _claude_dirs() -> list[Path]:
    dirs: list[Path] = []
    configured = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if configured:
        dirs.append(Path(configured))
    home = _home()
    if home:
        dirs.append(Path(home) / ".claude")
    return dirs


def _parse_created(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _marker_dir(root: Path) -> Path:
    return root.joinpath(*_MARKER_PARTS)


def _too_broad(target_text: str, root: Path) -> bool:
    """True for a marker target that would open far more than one project: a drive root, `/`, a UNC
    share root, the home directory or any directory above it, the project root or any directory above
    it. Such a marker counts as broken."""
    if target_text.startswith(_POSIX_PREFIX):
        return target_text[len(_POSIX_PREFIX):].strip("/\\") == ""
    key = _key(target_text)
    if Path(target_text).parent == Path(target_text):
        return True
    for guarded in (str(root), _home()):
        guarded_key = _resolve_key(guarded, None, False) if guarded else None
        if guarded_key and _under(guarded_key, key):
            return True
    return False


def _marker_target(root: Path) -> Optional[str]:
    """The folder the act-adopt marker opens, or None for a missing, malformed, expired or too broad
    marker."""
    data = _read_json_object(_marker_dir(root) / _MARKER_FILE)
    if data is None:
        return None
    target, created = data.get("target"), _parse_created(data.get("created"))
    if not isinstance(target, str) or not target.strip() or created is None:
        return None
    now = datetime.now(timezone.utc)
    if created > now + timedelta(minutes=5) or now - created >= _ENTRY_TTL:
        return None
    if not _is_rooted(target) or target.strip().startswith("~"):
        return None
    text = _resolve_text(target, None, False)
    if not text or _too_broad(text, root):
        return None
    return _key(text)


def _allow_entries(value: str, root: Path) -> list[tuple[str, bool, bool]]:
    """The (key or glob regex source, read-only, is a pattern) triples of the `outside-root-allow`
    value: `none` or empty = nothing. An entry with glob characters opens only what its pattern hits
    (`../zone/o*` the folders of `zone` that start with `o`, never `zone` itself)."""
    text = value.strip().strip("`").strip()
    if not text or text.lower() == "none":
        return []
    entries: list[tuple[str, bool, bool]] = []
    for part in text.split(","):
        part = part.strip().strip("`").strip()
        read_only = False
        match = re.search(r"\s*\(read\)\s*$", part, re.IGNORECASE)
        if match:
            read_only = True
            part = part[: match.start()].strip()
        part = part.strip("`'\" ")
        if not part:
            continue
        if any(char in part for char in _GLOB_CHARS):
            directory = _cut_glob(part)
            base = _resolve_key(directory or ".", str(root), False, "file")
            if base:
                entries.append((_forward(base).rstrip("/") + "/" + _forward(os.path.normcase(part[len(directory):])),
                                read_only, True))
            continue
        key = _resolve_key(part, str(root), False, "file")
        if key:
            entries.append((key, read_only, False))
    return entries


def _build_places(root: Path, payload: dict, config: dict) -> _Places:
    places = _Places()
    places.add(_resolve_key(str(root), None, False))
    try:
        for directory in _external_directories(root):
            places.add(_key(directory))
    except Exception:  # noqa: BLE001 - a broken settings file opens nothing, it breaks nothing
        pass
    for temp_root in _system_temp_roots():
        places.add(_key(temp_root))
    scratchpad = payload.get("scratchpad_dir")
    if isinstance(scratchpad, str) and scratchpad.strip():
        places.add(_resolve_key(scratchpad, None, False))
    for claude in _claude_dirs():
        for name in ("plugins", "skills"):
            places.add(_resolve_key(str(claude / name), None, False), read_only=True)
        # Plan mode writes its plan file here.
        places.add(_resolve_key(str(claude / "plans"), None, False))
    transcript = payload.get("transcript_path")
    if isinstance(transcript, str) and transcript.strip():
        resolved = _resolve_key(transcript, None, False)
        for claude in _claude_dirs():
            projects = _resolve_key(str(claude / "projects"), None, False)
            if resolved and projects and _under(resolved, projects) and resolved != projects:
                rest = resolved[len(projects):].lstrip("\\/")
                first, separator, _ = rest.partition(os.sep)
                if first and separator:  # a file inside the project folder, not the folder itself
                    places.add(projects + os.sep + first)
    places.add(_marker_target(root))
    for key, read_only, is_pattern in _allow_entries(str(config.get("outside-root-allow", "")), root):
        if is_pattern:
            places.add_pattern(_glob_regex(key), read_only)
        else:
            places.add(key, read_only=read_only)
    return places


# --- judging paths -----------------------------------------------------------------------------

class _Judge:
    """Collects the findings of one call."""

    def __init__(self, root: Path, places: _Places, bash: bool) -> None:
        self.places = places
        self.bash = bash
        self.lock_dir = str(_marker_dir(root))
        self.lock_key = _key(_marker_dir(root))
        self.lock_parent_key = _key(_marker_dir(root).parent)
        self.root_key = _resolve_key(str(root), None, False) or _key(root)
        self.found: list[_Finding] = []

    def judge(self, raw: str, write: bool, bases: list[Optional[str]], mode: str = "shell") -> None:
        keys: list[str] = []
        texts: list[str] = []
        for base in (bases or [None])[:_MAX_BASES]:
            text = _resolve_text(raw, base, self.bash, mode)
            if text:
                keys.append(_key(text))
                texts.append(text)
        if not keys:
            return
        locked = write and any(_under(key, self.lock_key) for key in keys)
        if not locked and any(self.places.allows(key, write) for key in keys):
            return
        self._add(raw, keys[0], texts[0], write, locked)

    def lock(self, raw: str, text: str) -> None:
        """A write that can create the marker folder (a copy, an unpacking or a sync into one of its
        parents): a finding whatever the place says."""
        self._add(raw, _key(text), text, True, True)

    def _add(self, raw: str, key: str, text: str, write: bool, locked: bool) -> None:
        for existing in self.found:
            if existing.key == key:
                existing.write = existing.write or write
                existing.lock = existing.lock or locked
                return
        shown = text.replace("\\", "/")
        if shown.startswith(_POSIX_PREFIX):
            shown = shown[len(_POSIX_PREFIX):]
        self.found.append(_Finding(str(raw).strip().strip("'\""), key, write, shown, locked))

    def is_parent_of_lock(self, key: str) -> bool:
        return key != self.lock_key and _under(self.lock_key, key)


def _tool_path(judge: _Judge, value: object, write: bool, bases: list[Optional[str]], mode: str = "file") -> None:
    if isinstance(value, str) and value.strip():
        judge.judge(value, write, bases, mode)


def _tool_pattern(judge: _Judge, value: object, bases: list[Optional[str]]) -> None:
    """The glob of Grep or the pattern of Glob: judged per brace alternative (`{D:/x,y}/*`), when the
    alternative names a place on its own."""
    if not isinstance(value, str):
        return
    for variant in expand_braces(value):
        if _looks_like_path(variant):
            judge.judge(variant, False, bases, "glob")


def _file_tool_findings(judge: _Judge, payload: dict, cwd: str) -> None:
    # The file tools expand nothing: `$x`, `{a,b}` and `%X%` in a path are plain characters (and
    # Windows and Node cut `x/..` out of `{y}/../a` as text), so the path is taken literally.
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return
    bases: list[Optional[str]] = [cwd]
    if tool == "Read":
        _tool_path(judge, tool_input.get("file_path"), False, bases)
    elif tool == "NotebookRead":
        _tool_path(judge, tool_input.get("notebook_path"), False, bases)
    elif tool in _TOOL_PATH_FIELDS:
        for name in _TOOL_PATH_FIELDS[tool]:
            _tool_path(judge, tool_input.get(name), True, bases)
    elif tool in ("Grep", "Glob"):
        _tool_path(judge, tool_input.get("path"), False, bases)
        _tool_pattern(judge, tool_input.get("glob" if tool == "Grep" else "pattern"), bases)


# --- shell commands ----------------------------------------------------------------------------

def _positional_after(args: list[str], start: int = 0) -> Optional[int]:
    for index in range(start, len(args)):
        if not args[index].startswith("-"):
            return index
    return None


def _non_path_positions(name: str, args: list[str]) -> set[int]:
    """Indexes of `args` that are text of the command and no file: a message, a search pattern, a
    script, a `find` name."""
    skip: set[int] = set()
    for index, arg in enumerate(args):
        lowered = arg.lower()
        if lowered in _MESSAGE_FLAGS:
            skip.add(index + 1)
        elif "=" in lowered and lowered.split("=", 1)[0] in _MESSAGE_FLAGS:
            skip.add(index)
    if name in _GREP_LIKE:
        family = _GREP_FAMILY.get(name, "grep" if name != "rg" else "rg")
        pattern_at = _grep_pattern_index([str(arg) for arg in args], family)
        if pattern_at is not None:
            skip.add(pattern_at)
    elif name == "git" and "grep" in args:
        at = args.index("grep")
        pattern_at = _grep_pattern_index([str(arg) for arg in args[at + 1:]], "git-grep")
        if pattern_at is not None:
            skip.add(at + 1 + pattern_at)
    elif name == "gh" and args[:1] == ["api"] and len(args) > 1:
        skip.add(1)
    elif name in _SELECT_STRING:
        lowered_args = [arg.lower() for arg in args]
        if "-pattern" in lowered_args:
            skip.add(lowered_args.index("-pattern") + 1)
        else:
            first = _positional_after(args)
            if first is not None:
                skip.add(first)
    elif name == "find":
        for index, arg in enumerate(args):
            if arg in _FIND_VALUE_FLAGS:
                skip.add(index + 1)
    if name in _EXPRESSION_COMMANDS:
        for index, arg in enumerate(args):
            if arg in _EXPRESSION_FLAGS:
                skip.add(index + 1)
    if name in _SCRIPT_COMMANDS and not any(arg in _SCRIPT_FLAGS for arg in args):
        first = _positional_after(args)
        if first is not None:
            skip.add(first)
    return skip


def _command_split(words: list[str]) -> Optional[tuple[str, list[str]]]:
    """(command name, its arguments) of one simple command's words, or None when there is none. A
    PowerShell assignment prefix (`$x = Get-Content ...`) and the call operator `&` are looked
    through; the program word itself is no path."""
    words = [str(word) for word in words]
    while len(words) > 2 and _PS_ASSIGN_RE.match(words[0]) and words[1] == "=":
        words = words[2:]
    if not words:
        return None
    if words[0] == "&" and len(words) > 1:
        return _command_name(words[1]), words[2:]
    return _command_name(words[0]), words[1:]


class _Words(list):
    """The words of one simple command. `feeds_xargs` marks one whose output goes into `xargs`: the
    words of an `echo` there are file names, not text."""

    feeds_xargs: bool = False


def _read_candidates(name: str, args: list[str], feeds_xargs: bool = False) -> list[tuple[str, bool]]:
    """(word, strict) pairs of a simple command that may name a place; `strict` marks a string
    literal of inline interpreter code, where a `..` is no path."""
    if name in _TEXT_COMMANDS and not feeds_xargs:
        return []
    skip = _non_path_positions(name, args)
    found: list[tuple[str, bool]] = []
    for index, word in enumerate(args):
        if index in skip:
            continue
        for candidate in _candidate_words(word):
            if _looks_like_path(candidate):
                found.append((candidate, False))
        if name in _INTERPRETERS and (" " in word or '"' in word or "'" in word):
            for literal in _LITERAL_RE.findall(word):
                if _looks_like_path(literal, strict=True):
                    found.append((literal, True))
    return found


# --- writes that can create the marker folder ---------------------------------------------------
#
# A write whose target is the marker folder or below it is found by the write-target scanners. What
# they do not see is a copy, an unpacking or a sync whose *destination* is a parent of the folder
# (`.act-local`, the project root) and whose source brings an `outside-allow/` along:
#   cp -r /tmp/x/outside-allow .act-local/     tar -xf a.tar -C .act-local     rsync -a /tmp/x/ .act-local/
# The rules, with the false alarms they accept or avoid:
#   - unpacking and syncing into a parent of the folder (`tar -x -C`, `unzip -d`, `Expand-Archive
#     -DestinationPath`, `7z x -o`, `rsync`, `robocopy`, `xcopy`) is always a finding: an archive or
#     a tree from elsewhere can hold the folder, and nobody has to unpack into `.act-local`. Without
#     an explicit destination only a shell that already stands in `.act-local` counts, since
#     `tar -xf release.tgz` in the project root is everyday work.
#   - `cp`/`mv`/`Copy-Item`/`Move-Item` count by what lands where: `<destination>/<name of the
#     source>` is the marker folder or below it, or (copying recursively or moving) the parent
#     `.act-local` itself. `cp -r src/ build/` creates `build/src` and stays free.
#   - a source whose name is not known (`.` / `dir/.`, a glob, a variable) counts when copying
#     recursively into `.act-local` itself; into the project root or above it only a source outside
#     the project that can bring a hidden folder along (`dir/.`, `.*`), since a plain `*` never
#     matches `.act-local`. `cp -r /tmp/scaffold/* .` stays free.
#   - not followed: a tree staged inside the project first and copied later, links (`ln -s`), and
#     programs that copy on their own. Another write inside the project (a plain `mkdir` and
#     `echo >`) into the folder is a write target and caught as such.

_COPY_COMMANDS = {
    "cp": False, "copy": False, "copy-item": False, "cpi": False,
    "mv": True, "move": True, "move-item": True, "mi": True,
}
_PS_STYLE = frozenset({"copy", "copy-item", "cpi", "move", "move-item", "mi", "expand-archive"})
_SYNC_DEST_INDEX = {"rsync": -1, "robocopy": 1, "xcopy": 1}
_EXTRACT_COMMANDS = frozenset({"tar", "bsdtar", "unzip", "expand-archive", "7z", "7za", "7zz"})
_PS_VALUE_PARAMS = ("path", "literalpath", "destination", "destinationpath")


def _last_segment(word: str) -> str:
    return _SEGMENT_SPLIT_RE.split(word.strip().strip("'\"").rstrip("\\/"))[-1]


def _operands(args: list[str], value_flags: frozenset) -> tuple[list[str], dict[str, str]]:
    """(operands, flag -> value) of a POSIX-style command line: `-t DIR`, `-tDIR`, `--flag=DIR`."""
    operands: list[str] = []
    values: dict[str, str] = {}
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            operands.extend(args[index + 1:])
            break
        if arg.startswith("--"):
            flag, _, value = arg.partition("=")
            if flag in value_flags:
                if value:
                    values[flag] = value
                elif index + 1 < len(args):
                    values[flag] = args[index + 1]
                    index += 1
        elif arg.startswith("-") and len(arg) > 1:
            if arg in value_flags and index + 1 < len(args):
                values[arg] = args[index + 1]
                index += 1
            else:
                for flag in value_flags:
                    if len(flag) == 2 and arg.startswith(flag) and len(arg) > 2:
                        values[flag] = arg[2:]
        else:
            operands.append(arg)
        index += 1
    return operands, values


def _ps_operands(args: list[str]) -> tuple[list[str], dict[str, str], set[str]]:
    """(operands, parameter -> value, switches) of a PowerShell command line; a parameter name may be
    shortened (`-Dest`), `-Name:value` is a value."""
    operands: list[str] = []
    named: dict[str, str] = {}
    switches: set[str] = set()
    index = 0
    while index < len(args):
        arg = args[index]
        if arg.startswith("-") and len(arg) > 1 and arg[1].isalpha():
            body, _, inline = arg[1:].partition(":")
            low = body.lower()
            full = next((name for name in _PS_VALUE_PARAMS if len(low) >= 3 and name.startswith(low)), None)
            if full is not None:
                if inline:
                    named[full] = inline
                elif index + 1 < len(args):
                    named[full] = args[index + 1]
                    index += 1
            else:
                switches.add(low)
        else:
            operands.append(arg)
        index += 1
    return operands, named, switches


def _is_recursive(args: list[str]) -> bool:
    return any(
        arg in ("--recursive", "--archive") or re.fullmatch(r"-[A-Za-z]*[rRa][A-Za-z]*", arg)
        for arg in args if arg.startswith("-")
    )


def _copy_plan(name: str, args: list[str]) -> Optional[tuple[list[str], str, bool]]:
    """(sources, destination, recursive) of a copy or move command line, or None."""
    if name in _PS_STYLE:
        operands, named, switches = _ps_operands(args)
        slots = {"path": named.get("path") or named.get("literalpath"), "destination": named.get("destination")}
        spare = iter(operands)
        for slot in ("path", "destination"):
            if slots[slot] is None:
                slots[slot] = next(spare, None)
        if not slots["path"] or not slots["destination"]:
            return None
        recursive = any(item and "recurse".startswith(item) for item in switches)
        return [part for part in slots["path"].split(",") if part], slots["destination"], recursive
    operands, values = _operands(args, frozenset({"-t", "--target-directory"}))
    target = values.get("-t") or values.get("--target-directory")
    if target:
        return (operands, target, _is_recursive(args)) if operands else None
    if len(operands) < 2:
        return None
    return operands[:-1], operands[-1], _is_recursive(args)


def _extract_destination(name: str, args: list[str]) -> Optional[tuple[Optional[str]]]:
    """(destination or None) wrapped in a tuple when the command unpacks an archive; None when it does
    not. A missing destination means the current directory."""
    if name in ("tar", "bsdtar"):
        extracts = any(
            arg in ("--extract", "--get")
            or (not arg.startswith("--") and arg.startswith("-") and "x" in arg[1:] and not arg.startswith("-C"))
            or (index == 0 and re.fullmatch(r"[A-Za-z]+", arg) is not None and "x" in arg)
            for index, arg in enumerate(args)
        )
        if not extracts:
            return None
        _, values = _operands(args, frozenset({"-C", "--directory"}))
        return (values.get("-C") or values.get("--directory"),)
    if name == "unzip":
        _, values = _operands(args, frozenset({"-d"}))
        return (values.get("-d"),)
    if name == "expand-archive":
        operands, named, _ = _ps_operands(args)
        spare = iter(operands)
        if not (named.get("path") or named.get("literalpath")):
            next(spare, None)
        return (named.get("destinationpath") or named.get("destination") or next(spare, None),)
    if name in ("7z", "7za", "7zz"):
        first = next((arg for arg in args if not arg.startswith("-")), "")
        if first not in ("x", "e"):
            return None
        out = next((arg[2:] for arg in args if arg.startswith("-o") and len(arg) > 2), None)
        return (out,)
    return None


def _lock_scan(judge: _Judge, name: str, args: list[str], bases: list[Optional[str]]) -> None:
    """Reports a copy, an unpacking or a sync that can create the marker folder (see above)."""
    if name in _COPY_COMMANDS:
        plan = _copy_plan(name, args)
        if plan is None:
            return
        sources, destination, recursive = plan
        recursive = recursive or _COPY_COMMANDS[name]
        for base in bases[:_MAX_BASES]:
            dest_text = _resolve_text(destination, base, judge.bash)
            if not dest_text or dest_text.startswith(_POSIX_PREFIX):
                continue
            dest_key = _key(dest_text)
            if _under(dest_key, judge.lock_key):
                judge.lock(destination, dest_text)
                return
            for source in sources:
                if _copy_creates_lock(judge, source, dest_text, dest_key, recursive, base):
                    judge.lock(destination, dest_text)
                    return
        return
    destinations: list[Optional[str]]
    if name in _SYNC_DEST_INDEX:
        operands = [arg for arg in args if not arg.startswith("-") and not _SWITCH_RE.match(arg)]
        index = _SYNC_DEST_INDEX[name]
        if len(operands) < 2 or index >= len(operands):
            return
        destinations = [operands[index]]
    elif name in _EXTRACT_COMMANDS:
        found = _extract_destination(name, args)
        if found is None:
            return
        destinations = [found[0]]
    else:
        return
    for destination in destinations:
        for base in bases[:_MAX_BASES]:
            if destination is None:
                # No explicit destination: the shell's own directory, but only `.act-local` itself.
                if base and _resolve_key(base, None, judge.bash) == judge.lock_parent_key:
                    judge.lock(".", base or "")
                    return
                continue
            dest_text = _resolve_text(destination, base, judge.bash)
            if not dest_text or dest_text.startswith(_POSIX_PREFIX):
                continue
            dest_key = _key(dest_text)
            if _under(dest_key, judge.lock_key) or judge.is_parent_of_lock(dest_key):
                judge.lock(destination, dest_text)
                return


def _copy_creates_lock(
    judge: _Judge, source: str, dest_text: str, dest_key: str, recursive: bool, base: Optional[str],
) -> bool:
    leaf = _last_segment(source)
    known = bool(leaf) and leaf not in (".", "..") and not any(char in leaf for char in _GLOB_CHARS) \
        and not _DYNAMIC_RE.search(leaf)
    if known:
        landed = _key(dest_text.rstrip("\\/") + "/" + leaf)
        return _under(landed, judge.lock_key) or (recursive and judge.is_parent_of_lock(landed))
    if not recursive:
        return False
    if dest_key == judge.lock_parent_key:
        # Into `.act-local` itself: anything that can be named `outside-allow` (or holds it).
        if not leaf or leaf in (".", "..") or _DYNAMIC_RE.search(leaf):
            return True
        return fnmatch.fnmatchcase(_MARKER_PARTS[1], leaf)
    if judge.is_parent_of_lock(dest_key):
        # Into the project root or above: only a source from outside the project, and one that
        # can bring a hidden folder along (`dir/.`, `.*`) - a plain `*` never matches `.act-local`.
        brings_hidden = leaf in ("", ".", "..") or (leaf.startswith(".") and fnmatch.fnmatchcase(_MARKER_PARTS[0], leaf))
        if not brings_hidden or _DYNAMIC_RE.search(leaf):
            return False
        source_key = _resolve_key(source, base, judge.bash)
        return bool(source_key) and not _under(source_key, judge.root_key)
    return False


def _scan_word_lists(judge: _Judge, word_lists: list[list[str]], cwd: str) -> None:
    _scan_from(judge, word_lists, [cwd], 0)


def _scan_from(judge: _Judge, word_lists: list[list[str]], bases: list[Optional[str]], depth: int) -> None:
    for words in word_lists:
        split = _command_split(words)
        if split is None:
            continue
        name, args = split
        feeds = bool(getattr(words, "feeds_xargs", False))
        for text, _strict in _read_candidates(name, args, feeds):
            judge.judge(text, False, bases)
        if len(words) > 2 and _PS_ASSIGN_RE.match(str(words[0])) and words[1] == "=":
            # `$t = "C:\\x"`: the value of an assignment is a word like any other.
            if _looks_like_path(str(words[2])):
                judge.judge(str(words[2]), False, bases)
        if name == "cmd" and depth < 2:
            # `cmd /c "type C:\\x"`: the string after /c is read by cmd, where a backslash is a
            # separator - not by the shell lexer, which would take it for an escape.
            flag = next((i for i, arg in enumerate(args) if arg.lower() in ("/c", "/k", "/r")), None)
            if flag is not None:
                try:
                    inner = _ps_word_lists(" ".join(args[flag + 1:]))
                except Exception:  # noqa: BLE001
                    inner = []
                if inner:
                    _scan_from(judge, inner, bases, depth + 1)
        try:
            _lock_scan(judge, name, args, bases)
        except Exception:  # noqa: BLE001 - the plain read scan keeps its findings
            pass
        if name not in _TEXT_COMMANDS and name not in _CD_NAMES and name != "export":
            # A command that runs in a directory outside the allowed places acts there, whatever its
            # words are (`cat a.txt` after the session started elsewhere).
            judge.judge(".", False, bases)
        if name in _CD_NAMES:
            index = _positional_after(args)
            if index is not None and args[index] not in ("-", "--"):
                moved = [
                    text for base in bases[:_MAX_BASES]
                    for text in [_resolve_text(args[index], base, judge.bash)]
                    if text and not text.startswith(_POSIX_PREFIX)
                ]
                if moved:
                    bases = list(dict.fromkeys(moved))[:_MAX_BASES]


_QUOTED_HEREDOC_RE = re.compile(r"""<<(-?)\s*(?:'([^'\s]+)'|"([^"\s]+)"|\\(\w+))""")


def _without_quoted_heredocs(command: str) -> str:
    """`command` without the body lines of every heredoc with a quoted delimiter (`<<'EOF'`,
    `<<"EOF"`, a backslash before the word), which the shell never runs; the opener and the
    terminator lines stay. Line based on purpose: it works when an earlier line holds a quote the
    lexers cannot close, the case where they would read the body as commands. Unquoted delimiters
    are left alone, since the shell expands (and runs) `$(...)` in their body."""
    kept: list[str] = []
    pending: list[tuple[str, bool]] = []
    for line in command.split("\n"):
        if pending:
            terminator, strip_tabs = pending[0]
            if (line.lstrip("\t") if strip_tabs else line).rstrip("\r") == terminator:
                pending.pop(0)
                kept.append(line)
            continue
        kept.append(line)
        for match in _QUOTED_HEREDOC_RE.finditer(line):
            pending.append((match.group(2) or match.group(3) or match.group(4), bool(match.group(1))))
    return "\n".join(kept)


def _coarse_word_lists(command: str) -> list[list[str]]:
    return [fragment.split() for fragment in re.split(r"[;&|\n]+", command) if fragment.split()]


_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_]\w*\+?=")


def _leading_assignments(words: list[str]) -> list[str]:
    """The `NAME=value` words in front of a command (`T=/x cmd`, `env T=/x cmd`, or a line of only
    assignments): `_strip_command_prefix` drops them, but the value is a path like any other."""
    found: list[str] = []
    for word in words:
        text = str(word)
        if _ASSIGNMENT_RE.match(text):
            found.append(text)
        elif _command_name(text) != "env":
            break
    return found


def _shell_word_lists(command: str) -> list[list[str]]:
    """The simple commands of `command` as word lists, read with the quote-aware word lexer alone.
    The union with the previous reading that the write-guards use (`_stripped_word_lists`) also
    takes a backtick span inside single quotes (`printf '... `GET /x` ...'`) for a command, which
    for a guard that judges every word is a steady source of false alarms; that union is the
    fallback only when the lexer fails. An assignment in front of a command is returned as the
    arguments of its own `export`; the command that feeds `xargs` is marked (`_Words`)."""
    try:
        raw = _command_word_lists_new(command)
        lists: list[list[str]] = []
        for index, (words, _separator) in enumerate(raw):
            assigned = _leading_assignments(words)
            if assigned:
                lists.append(_Words(["export", *assigned]))
            stripped = _strip_command_prefix(words)
            if not stripped:
                continue
            item = _Words(stripped)
            following = raw[index + 1] if index + 1 < len(raw) else None
            if following and following[1] in ("|", "|&") and following[0]:
                item.feeds_xargs = _command_name(following[0][0]) in ("xargs", "parallel")
            lists.append(item)
        return lists
    except Exception:  # noqa: BLE001 - a scanner bug must not turn into a silent allow
        try:
            return _stripped_word_lists(command)
        except Exception:  # noqa: BLE001
            return _coarse_word_lists(command)


def _shell_findings(judge: _Judge, tool: str, command: str, cwd: str) -> None:
    powershell = tool == "PowerShell"
    # The text of a quoted heredoc is never run; cut out first, so that a line of the command that
    # does not tokenize cannot push a scanner into reading the body as commands (`<id>` in a commit
    # message would be a redirection). A body a shell may run (`bash <<'EOF'`) stays.
    if not powershell:
        try:
            if not _heredoc_may_feed_shell(command):
                command = _without_quoted_heredocs(command)
        except Exception:  # noqa: BLE001 - the whole command is scanned then
            pass
    # Writes first: a word that is also a write target is reported as the write.
    try:
        if len(_CD_WORD_RE.findall(command)) > _MAX_CD_FOR_TARGET_SCAN:
            # The shared write-target scanners follow every directory change and their cost grows with
            # the cube of a `cd a; cd b; ...` chain (800 of them: 20 s, past any hook timeout). Beyond
            # a chain no real command line has they are skipped: the words are still read as reads,
            # and a word that names the marker folder counts as a write to it.
            if "outside-allow" in command.lower():
                judge.lock(".act-local/outside-allow", judge.lock_dir)
        elif powershell:
            targets = _powershell_write_targets(command, cwd, _GIT_WRITES_WORKER_SCOPE)
            if targets is None:
                targets = _ps_raw_redirect_targets(command)
            for target in sorted(targets):
                judge.judge(target, True, [cwd])
        else:
            for target, base in _bash_write_targets(command, cwd, _GIT_WRITES_WORKER_SCOPE):
                judge.judge(str(target), True, [base if base is not None else cwd])
    except Exception:  # noqa: BLE001 - the read scan below still runs
        pass
    groups: list[list[list[str]]] = []
    if powershell:
        try:
            groups.append(_ps_word_lists(command))
        except Exception:  # noqa: BLE001
            pass
    try:
        groups.append(_shell_word_lists(command))
    except Exception:  # noqa: BLE001
        pass
    for lists in groups:
        try:
            _scan_word_lists(judge, lists, cwd)
        except Exception:  # noqa: BLE001 - one group failing leaves the other
            continue


# --- the check ---------------------------------------------------------------------------------

def _project_root() -> Optional[Path]:
    starts: list[Optional[Path]] = []
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if project_dir:
        starts.append(Path(project_dir))
    starts.append(None)
    for start in starts:
        try:
            return actlib.repo_root(start)
        except (RuntimeError, OSError):
            continue
    return None


def _message(findings: list[_Finding], tool: str, mode: str) -> str:
    lead = "[act] warning --" if mode == "warn" else "[act] outside-root refused --"
    first = findings[0]
    shown = f"`{first.raw}`" if first.raw.replace("\\", "/") == first.shown else f"`{first.raw}` ({first.shown})"
    if first.lock:
        what = (
            f"{tool} writes {shown}: `.act-local/outside-allow/` is reserved for the act-adopt "
            "scripts (R-safe-outside-root)."
        )
        ways = (
            "The owner can set `outside-root` to `warn` or `off` in docs/ai/config.md § Checks, or "
            f"for one run with {_ENV_OVERRIDE}=warn"
        )
    else:
        action = "writes" if first.write else "reads"
        what = f"{tool} {action} {shown}, outside the project and its allowed places (R-safe-outside-root)."
        ways = (
            "Ways out: an entry in `outside-root-allow` (docs/ai/config.md § Checks; `<path>` or "
            "`<path> (read)`), the folder under `permissions.additionalDirectories`, or "
            f"{_ENV_OVERRIDE}=warn for one run"
        )
    more = ""
    if len(findings) > 1:
        named = ", ".join(
            f"`{item.raw}` ({'write' if item.write else 'read'})" for item in findings[1:_MAX_NAMED]
        )
        rest = len(findings) - _MAX_NAMED
        more = f" Also outside: {named}" + (f" and {rest} more." if rest > 0 else ".")
    return f"{lead} {what}{more} {ways}"


def check_outside_root(payload: dict) -> int:
    """Check: a tool call that reads or writes outside the project and its allowed places (see this
    module's header). Runs for every caller; `warn` lets the call through and reports it on stdout."""
    root = _project_root()
    if root is None:
        return 0  # not inside a template-managed project: nothing to enforce against
    config = actlib.read_config(root)
    mode = _check_mode(config, "outside-root", default="warn")
    override = os.environ.get(_ENV_OVERRIDE, "").strip().lower()
    if override in ("block", "warn", "off"):
        mode = override
    if mode == "off":
        return 0
    tool = payload.get("tool_name")
    if not isinstance(tool, str):
        return 0
    cwd_raw = payload.get("cwd")
    cwd = cwd_raw if isinstance(cwd_raw, str) and cwd_raw else str(root)
    shell = _shell_command(payload)
    if shell is None and not isinstance(payload.get("tool_input"), dict):
        return 0
    places = _build_places(root, payload, config)
    judge = _Judge(root, places, bash=tool != "PowerShell")
    if shell is not None:
        _shell_findings(judge, shell[0], shell[1], cwd)
    else:
        _file_tool_findings(judge, payload, cwd)
    if not judge.found:
        return 0
    message = _message(judge.found, tool, mode)
    if mode == "warn":
        print(message)
        return 0
    print(message, file=sys.stderr)
    return 2
