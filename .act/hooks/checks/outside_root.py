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
#          started there) reads that directory. The command line of `wsl`/`wsl.exe` is read as the
#          commands it runs inside WSL, where `/mnt/<x>/...` is the Windows drive <X>: (_scan_wsl,
#          the same mapping the shared write-target scanners apply there, and only there: a file
#          tool's `/mnt/d/x` is no drive on Windows). MCP tools are not looked at here, except
#          the read tools of the IDE server's known list, whose path arguments `ide-mcp` hands to
#          this check as a Read.
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
#          `zone` itself; an absolute path - a drive path in either slash style, or a POSIX-rooted
#          one - outside the project and outside the home directory is entered as read-only whether
#          or not ` (read)` stands behind it: it is the entry for a program folder, meant for reading
#          and starting a program, not for writing. Only the writes the scanners below recognize are
#          refused there, exactly as below a ` (read)` entry; a write they do not see passes. An
#          entry with a glob character keeps the glob rule above (writable unless ` (read)`), and one that is a drive root, `/`
#          or a folder above the project or the home directory opens reading everything below it);
#          and, while a marker younger than 24 hours says so, the target folder of an
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
# Failure: this module is one of dispatch.py's fail-closed guards for Bash and PowerShell, like
#          `secret_read`: if it cannot be imported or raises while it looks at such a call, the
#          dispatcher refuses that call and reports the failure to the model and the human. Read,
#          Write, Edit and the other tools stay possible, so the owner (or the assistant) can still
#          look into the cause and edit the config row that switches the check off. Inside this
#          module each scanner runs on its own, so a bug in one (say the PowerShell target
#          scanner) does not hide what the others found - but a scanner that raises on a Bash or
#          PowerShell command still refuses that call, naming the exception class (whatever the
#          mode says, short of `off`): what the scanner would have found is unknown.
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
#   - a command line with more than 150 `cd`-like statements is refused, whatever the mode says short
#     of `off`: the shared write-target scanners are not run on it (their cost grows with the cube of
#     such a chain: 800 statements took 20 seconds), so a write behind it would go unseen. The
#     message asks for shorter commands.
#   - the `cd` tracking is lexical and best effort: a relative word counts only if it leaves the
#     allowed places from every directory the scanner thinks the shell may be in.
#   - a string literal that is the direct argument of a URL or path normalisation in the inline code of
#     a JavaScript runtime (`node`, `nodejs`, `deno`, `bun`; `new URL(`, `URL(`, `url.resolve(`,
#     `path.normalize(`, `path.posix.normalize(`, also behind `require('path')`) is no read
#     (_url_argument_literals). Only that exact position: a
#     literal in a call nested inside it, any other call, and a `file:` URL stay candidates. The whole
#     exception is off as soon as the command line names a file API (_FILE_API_RE: `fs`, `open(`,
#     `readFile`, `Path(`, `child_process`, `fetch`, `import.meta`, `Bun.`, a `file:` anywhere ...), since
#     the normalised string could be read right after (`const p = path.normalize('/etc/passwd');
#     fs.readFileSync(p)`). A file API the list does not know, or one reached through `eval` or an
#     obfuscated name, makes the literal look harmless. Comments and regular-expression literals are read
#     as code, so a call name inside one (`f(/* URL( */ '/x')`) can place a literal wrongly, and a call
#     name more than _CALL_WINDOW characters before its `(` is not recognised (stricter, never looser).
#   - a URL route is no read where a script is called: a word with a leading `/` behind the script file of
#     `python` (also `py`, `pythonw`, versioned), `node`, `deno run`, `bun [run]`, `tsx`, `ts-node`, `ruby`,
#     `php`, `perl`, `lua`, `bash`/`sh`/`zsh`/`dash`/`ksh`, behind the package of `npx`, `bunx`, `npm exec`/`x`,
#     `pnpm exec`/`dlx` or `yarn exec`/`dlx`, or behind a relative program (`./run.sh`, `./.venv/bin/python`) is
#     left out when its first segment names nothing (_script_arg_start). Not the script itself, not inline code
#     (`-c`, `-e`; behind a package any such option takes the exception away), not a word with `..`, `~`, a
#     variable, `%`, an expanding brace group (`{a,b}`, `{1..3}`; `{id}` is text), a drive, `file:` or a UNC
#     form, not the value of a file option (`-o`, `-vo`, `--output`, `--file`, `--config`, `--save-to` ... in
#     _FILE_OPTIONS and _FILE_OPTION_RE), and not a word whose first segment exists (`/etc`, `/usr`, `/home`).
#     On Windows one existing reading of the first segment is enough: the drive form (`/q/x` as `Q:`), a folder
#     of the drive of the base folder or of the process (a native program opens `/q/x` as `<drive>:/q/x`), a name
#     every POSIX root has, a folder of a Git for Windows root taken from its usual install places (no PATH
#     search). Inside `wsl` no route is left out: the check cannot see the distribution's `/`. A script that
#     reads or writes such a path itself stays invisible: `python x.py /api/users` may open `/api/users` if it
#     exists later, and a script call this list does not know, or one behind `sudo`/`env` that the shared command
#     reading does not look through, is read as before. `python -m pkg` is no script call here.
#   - heuristics against false alarms, all best effort: the program word, the text of `echo`/
#     `printf`, the value of `-m`/`--message`/`--body`/`--title`, URLs, the search pattern of
#     `grep`/`rg`, the script of `sed`/`awk`/`jq` and the value of `find -name` are not paths. A
#     path hidden behind one of those words goes unseen. A lone `/` is the root, except as the
#     operator of `expr`/`let`, inside `$((...))`/`((...))`, in a PowerShell expression, and as the
#     value of a delimiter option (`cut -d /`); on Windows a one-segment word such as `/c` or `/s`
#     is a switch. A `file:` URL is not a URL here but the path it names (`file:///home/u/x` is
#     `/home/u/x`, `file://host/share/x` is `//host/share/x`, percent-decoded). The words of a
#     `for` loop are no paths when every use of the variable in the loop is the tail of a
#     `<scheme>://<host>` URL inside its literal body (`for p in /a /b; do curl "https://host$p"; done`).
#   - a tree with a hidden `.act-local/outside-allow/` staged inside the project and copied into the
#     project root as `dir/.` is not followed (only such a source from outside the project is, since a
#     copy inside the project is everyday work); nor are links (`ln -s`).
#   - the system temp directory is open as a whole: a project that itself lies in it sees its
#     neighbours as allowed (unlike the worker write scope, which carves that case out).
#   - shares command_words.py's, shell_targets.py's and powershell_targets.py's own limits for
#     tokenizing.

from __future__ import annotations

import fnmatch
import functools
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import unquote

import actlib

from .brace_expand import expand_braces
from .command_parse import Parse, parse_for
from .command_words import _strip_command_prefix
from .inline_code import mentions_interpreter
from .common import _TOOL_PATH_FIELDS, _check_mode, _note_hit, _shell_command, _target_class
from .powershell_targets import (
    _extract_ps_command_flag, _is_unplaced_target,
    _unplaced_reason,
)
from .secret_read import (
    _GREP_FAMILY,
    _HOME_TOKEN_RE,
    _INTERPRETERS,
    _LITERAL_RE,
    _candidate_words,
    _grep_pattern_index,
)
from .shell_targets import (
    _GIT_WRITES_WORKER_SCOPE,
    _command_name,
    _heredoc_may_feed_shell,
    _operands,
    _resolve_path,
    _to_native_path,
    _wsl_command_line,
    _wsl_native_word,
)
from .write_scope import _external_directories, _read_json_object, _system_temp_roots

__all__ = ["check_outside_root"]

# Environment variable that overrides `outside-root` for one run (block | warn | off).
_ENV_OVERRIDE = "ACT_OUTSIDE_ROOT"
_ENTRY_TTL = timedelta(hours=24)
_MARKER_PARTS = (".act-local", "outside-allow")
_MARKER_FILE = "adopt.json"
_MAX_BASES = 8  # directories one command may run in; more is unknown and refused (_Judge.capped)
# More `cd`-like statements than this and the shared write-target scanners are not run (see _shell_findings).
_MAX_CD_FOR_TARGET_SCAN = 150
_CD_WORD_RE = re.compile(r"(?<![\w./-])(?:cd|chdir|pushd|set-location|sl|push-location)(?![\w./-])", re.IGNORECASE)
# A path with more segments than this is not resolved (the walk costs a file system call per segment) and the call
# is refused as unknown (_UnknownPath).
_MAX_RESOLVE_SEGMENTS = 200  # above the most a chain of _MAX_CD_FOR_TARGET_SCAN directory changes reaches


class _UnknownPath(ValueError):
    """A path the check does not follow to the end (_MAX_RESOLVE_SEGMENTS)."""
# A key that no real directory key can contain: a POSIX-rooted path on Windows has no drive, so it
# lies outside every place without being comparable to one.
_POSIX_PREFIX = "\0posix:"

_PS_ASSIGN_RE = re.compile(r"^\$\w+$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:[\\/]")
_UNC_RE = re.compile(r"^(?:\\\\|//)[^\\/\s]+[\\/]+[^\\/\s]")
_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]+://")
# Two or more forward slashes and nothing else (`//`, `///`). As a word of its own that is the file
# system root, as on a POSIX system (`ls //`), and is read like `/`; as a fragment of text (a string
# literal of inline code, a floor division, a separator in a pattern) it is never a place. Only
# `//host/share` with a segment is a UNC path (`_UNC_RE`).
_ONLY_SLASHES_RE = re.compile(r"^/{2,}$")
# One or more forward slashes and nothing else: the same word with a single `/` included. A division
# or a separator in the `-c` text of a language interpreter (`python -c "print(7 / 2)"`) is such a word.
_BARE_SLASHES_RE = re.compile(r"^/+$")
# A `file:` URL names a local path: `file:///home/u/x`, `file:///C:/x`, `file://C:/x`, `file://host/share/x`
# (see `_file_url_path`); one slash (`file:/x`) too.
_FILE_URL_RE = re.compile(r"^file:/", re.IGNORECASE)
_DRIVE_ONLY_RE = re.compile(r"^[A-Za-z]:$")
_URL_DRIVE_PATH_RE = re.compile(r"^/[A-Za-z]:(?:[\\/]|$)")
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


def _file_url_path(text: str) -> str:
    """A `file:` URL as the path it names, percent-decoded: `file:///home/u/x` -> `/home/u/x`,
    `file:///C:/x` and `file://C:/x` -> `C:/x`, `file://host/share/x` -> `//host/share/x` (a UNC path;
    an empty host and `localhost` are this machine). Any other text is returned as it is."""
    if not _FILE_URL_RE.match(text):
        return text
    rest = text[len("file:"):]
    for mark in ("?", "#"):  # a query and a fragment are no part of the path
        rest = rest.split(mark, 1)[0]
    if rest.startswith("//"):
        rest = rest[2:]
        cut = rest.find("/")
        host, rest = (rest, "") if cut < 0 else (rest[:cut], rest[cut:])
        if _DRIVE_ONLY_RE.match(host):
            rest = host + rest  # `file://C:/x`
        elif host and host.lower() != "localhost":
            rest = "//" + host + rest
    if _URL_DRIVE_PATH_RE.match(rest):
        rest = rest[1:]  # `/C:/x`
    return unquote(rest, errors="replace").split("\x00", 1)[0] or text  # a NUL ends the name


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
    if _ONLY_SLASHES_RE.match(text):
        text = "/"  # a word of its own, not a fragment of text: the root, as `/` is
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
    text = _file_url_path(text)
    if chr(0) in text:
        return None  # a decoded %00
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
        # path is unknown, and so is what the command touches.
        raise _UnknownPath(f"a path with more than {_MAX_RESOLVE_SEGMENTS} segments")
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
    if text == "/" and not strict:
        return True  # a shell word of its own (`ls /`) is the root, as `//` is; in a text literal it is not
    if _FILE_URL_RE.match(text):
        return True  # a `file:` URL is a local path (curl, git and others read it)
    if len(text) < 2 or _URL_RE.match(text) or (strict and _ONLY_SLASHES_RE.match(text)):
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


def _is_absolute_form(part: str) -> bool:
    """True for an entry written as an absolute path: a drive path in either slash style (`D:\\x`,
    `D:/x`) or a POSIX-rooted one (`/opt/x`; on Windows the Git-Bash `/d/x` too). A UNC share
    (`//host/share`), `~`, a drive-relative `D:x` and a relative path are not."""
    return bool(_DRIVE_RE.match(part)) or (part[:1] == "/" and part[1:2] != "/")


# Program-folder entry, what the check does with it: the path is judged as resolved (`..` cut out), so a sibling
# folder that shares the name prefix (`Browser-old` next to `Browser`), the parent folder and a path that leaves the
# folder through `..` stay refused. An entry written as a `file:` URL or as `//localhost/C$/` is not recognised as
# absolute and is ignored. "Starting" is what the check sees of a program: the program word of a command is no path
# (`"D:/Program Files/Browser/browser.exe" --headless` needs no entry), but a `cd` into the folder, a path argument
# or a wrapper (`xvfb-run`, `Start-Process`, `bash -c`) does; what the started program writes itself is invisible.
# A relative path, `~`, a glob entry, a UNC share and an absolute path inside the project or the home directory keep
# their own behaviour (the last two are writable).
def _program_folder_entry(part: str, key: str, root: Path) -> bool:
    """True when the entry (no glob characters, already resolved to `key`) is exactly the program-folder
    form: written as an absolute path, and lying neither in the project nor in the home directory
    (those have their own forms). Such an entry is read-only, like one with ` (read)` behind it: meant
    for reading and starting a program. Judged on the resolved key, so `D:/prog/../other` counts as
    `D:/other`."""
    if not _is_absolute_form(part):
        return False
    root_key = _resolve_key(str(root), None, False)
    if root_key and _under(key, root_key):
        return False
    home = _home()
    home_key = _resolve_key(home, None, False) if home else None
    return not (home_key and _under(key, home_key))


def _allow_entries(value: str, root: Path) -> list[tuple[str, bool, bool]]:
    """The (key or glob regex source, read-only, is a pattern) triples of the `outside-root-allow`
    value: `none` or empty = nothing. An entry with glob characters opens only what its pattern hits
    (`../zone/o*` the folders of `zone` that start with `o`, never `zone` itself). An entry that is an
    absolute path outside the project and the home directory is read-only whatever follows it (see
    `_program_folder_entry`)."""
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
        if not part or _FILE_URL_RE.match(part):
            continue  # a `file:` URL is no entry (it names no place relative to the project)
        if any(char in part for char in _GLOB_CHARS):
            directory = _cut_glob(part)
            base = _resolve_key(directory or ".", str(root), False, "file")
            if base:
                entries.append((_forward(base).rstrip("/") + "/" + _forward(os.path.normcase(part[len(directory):])),
                                read_only, True))
            continue
        key = _resolve_key(part, str(root), False, "file")
        if key:
            entries.append((key, read_only or _program_folder_entry(part, key, root), False))
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

def _reads_nothing(raw: str, text: str, base: Optional[str], bash: bool, mode: str) -> bool:
    """True for a read that the command text does not show to reach anything: a shell word with a variable or
    substitution (its place is unknown), or a path that does not exist on the disk (`/contacts.json`,
    `D:/dev/x/tests/typo.ts`, `C:/nothing/x`: a URL route or a mistyped file, there is nothing to read, even when a
    parent folder exists; on Windows a POSIX-rooted word counts as existing when one reading of its first segment
    does, _root_entry_exists, deeper than that nothing is looked up). A write is never judged this way: it can
    create the place."""
    if _UNC_RE.match(raw.strip().strip("'\"")):
        return False  # a UNC path (`//localhost/C$/x` is the admin share, no variable) is never looked up
    if mode == "shell" and _DYNAMIC_RE.search(raw):
        return True
    if text.startswith(_POSIX_PREFIX):
        return not _root_entry_exists(text[len(_POSIX_PREFIX):].lstrip("/").split("/", 1)[0], base, bash)
    if text.startswith(("\\\\", "//")):
        return False  # a UNC path is never looked up (the host may hang): judged as written
    return not os.path.lexists(text)


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
        # Reasons why a shell command was not looked at in full (a scanner raised, the command is longer than the
        # scanners follow): the call is refused for them, see check_outside_root.
        self.unchecked: list[str] = []

    def capped(self, bases: list) -> list:
        """The directories a command may run in, at most _MAX_BASES; more is unknown and refuses the call."""
        if len(bases) > _MAX_BASES:
            reason = f"it may run in more than {_MAX_BASES} different directories"
            if reason not in self.unchecked:
                self.unchecked.append(reason)
        return bases[:_MAX_BASES]

    def judge(self, raw: str, write: bool, bases: list[Optional[str]], mode: str = "shell") -> None:
        keys: list[str] = []
        texts: list[str] = []
        try:
            for base in self.capped(bases or [None]):
                text = _resolve_text(raw, base, self.bash, mode)
                if text and not (not write and _reads_nothing(raw, text, base, self.bash, mode)):
                    keys.append(_key(text))
                    texts.append(text)
        except _UnknownPath as unknown:
            self.unchecked.append(f"it holds {unknown}, more than the check follows")
            return
        if not keys:
            return
        locked = write and any(_under(key, self.lock_key) for key in keys)
        if not locked and any(self.places.allows(key, write) for key in keys):
            return
        self._add(raw, keys[0], texts[0], write, locked)

    def scanner_failed(self, exc: Exception) -> None:
        """A scanner raised on this command: what it would have found is unknown, so the call counts as not checked."""
        reason = (
            f"it holds {exc}, more than the check follows" if isinstance(exc, _UnknownPath)
            else f"a scanner of the check failed on it ({type(exc).__name__})"
        )
        if reason not in self.unchecked:
            self.unchecked.append(reason)

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


def _program_word(words: list[str]) -> str:
    """The program word of one simple command as written (`./run.sh`), where _command_split gives its name."""
    words = [str(word) for word in words]
    while len(words) > 2 and _PS_ASSIGN_RE.match(words[0]) and words[1] == "=":
        words = words[2:]
    if words and words[0] == "&" and len(words) > 1:
        return words[1]
    return words[0] if words else ""


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


_OPERAND_START_RE = re.compile(r"^[(\[]*[\d$]")
# Programs whose arguments are an arithmetic expression: a lone `/` between two operands is the operator there.
_DIVISION_COMMANDS = frozenset({"expr", "let"})


# What may stand inside an arithmetic expression of the shell, `$(( ... ))` or `(( ... ))`, that is taken out of the
# command before its words are read: no command substitution, quote, backtick, `;`, backslash or line break. Bash
# evaluates names there as variables and never reads a file, so `$(( a / b ))` and `$(( /etc/passwd ))` name no place.
_ARITHMETIC_BAD_RE = re.compile("[`'\";\\\\\\n]|\\$\\(")
_ARITHMETIC_START_RE = re.compile(r"\$\(\(|(?:^|[;&|{(\n]|\b(?:then|do|else|elif|if|while|until))[ \t]*\(\(")


def _without_arithmetic(command: str) -> str:
    """`command` with every shell arithmetic expression `$(( ... ))` and `(( ... ))` (at a command start) that
    holds nothing but operands and operators replaced by `$((0))` / `((0))`: the shell word lexer reads the inside
    of `$(( ... ))` as a command, where the `/` of `6 / 2` would be taken for the root. An expression with a
    command substitution, quote or backtick inside, or one that is not closed, stays as it is."""
    out: list[str] = []
    position = 0
    for match in _ARITHMETIC_START_RE.finditer(command):
        start = match.start()
        if start < position:
            continue
        opener = match.end() - 2
        # Inside the body the parentheses must balance; the first `)` that would take the depth below 0 has to be
        # followed by the second `)` of the closer. Any other character there means the shell reads subshells or a
        # command substitution (`((cat /etc/passwd) && (ls))`), not arithmetic.
        depth = 0
        end = None
        for index in range(opener + 2, len(command)):
            char = command[index]
            if char == "(":
                depth += 1
            elif char == ")":
                if depth:
                    depth -= 1
                elif command[index + 1:index + 2] == ")":
                    end = index + 1
                    break
                else:
                    break
        if end is None or end - 1 <= opener + 2:
            continue
        body = command[opener + 2:end - 1]
        if _ARITHMETIC_BAD_RE.search(body):
            continue
        out.append(command[position:opener])
        out.append("((0))")
        position = end + 1
    out.append(command[position:])
    return "".join(out)


# The word before a lone `/` in a PowerShell statement that makes it a division: a number (`1MB`), a variable or a
# property of one (`$x`, `$x.Length`), a closed parenthesis or index, with or without properties behind it
# (`(Get-Item a).Length`, `$a[0]`, `(Get-ChildItem | Measure-Object Length -Sum).Sum`).
_PS_OPERAND_END_RE = re.compile(r"^(?:[+-]?\d[\d_.]*(?:kb|mb|gb|tb|pb)?|\$[\w:.{}]+|.*[)\]](?:\.\w+)*)$", re.IGNORECASE)


def _paren_open(words: list[str]) -> bool:
    """True when `words` leave a parenthesis unclosed (`((Get-Item`, `$(`)."""
    text = " ".join(words)
    return text.count("(") > text.count(")")


def _is_division(name: str, args: list[str], index: int, powershell: bool = False) -> bool:
    """True when the lone `/` at `args[index]` is the operator of an expression, not the root. Allow-list,
    with a number, variable or parenthesis after the `/` in every form: `expr` and `let` (`expr 6 / 2`, an
    argument before it); in the shell an arithmetic expression `$(( ... ))` or `(( ... ))`, which is cut out of the
    command first (_without_arithmetic, so no `/` of it gets here); in PowerShell a
    statement that is an expression itself (its first word starts like a number, a variable, a parenthesis,
    a type or a property: `$x / 1MB`, `(Get-Item a).Length / 1MB`), an open parenthesis before the `/`
    (`Write-Output ((Get-Item a).Length / 1MB)`) or a number, variable or closed parenthesis right before it
    (`x = 7 / 2`; limit: `Get-ChildItem $dir / 2` passes). Anything else, `ls -la / 2`, `du -sh / $X`, `ls /`, is the
    root: a number or a variable behind it does not make it a division."""
    following = args[index + 1] if index + 1 < len(args) else ""
    if not _OPERAND_START_RE.match(following):
        return False
    before = [name, *args[:index]]
    if name in _DIVISION_COMMANDS:
        return index > 0
    if not powershell:
        return False
    left = args[index - 1] if index > 0 else name
    return (name[:1] in ("(", "$", "[", ".") or name[:1].isdigit() or _paren_open(before)
            or bool(_PS_OPERAND_END_RE.match(left)))


# Options whose next word is a separator or delimiter, per program (`cut -d / -f1`, `sort -t /`, `awk -F /`):
# a lone `/` right behind one is that text, not the root. Allow-list; any other program or option still
# reads a lone `/` as the root.
_SEPARATOR_VALUE_OPTIONS = {
    "cut": frozenset({"-d", "--delimiter"}),
    "paste": frozenset({"-d", "--delimiters"}),
    "sort": frozenset({"-t", "--field-separator"}),
    "join": frozenset({"-t"}),
    "awk": frozenset({"-F", "--field-separator"}),
    "gawk": frozenset({"-F", "--field-separator"}),
    "mawk": frozenset({"-F"}),
    "column": frozenset({"-s", "--separator"}),
}


def _is_separator_value(name: str, args: list[str], index: int) -> bool:
    """True when the lone `/` at `args[index]` is the value of a delimiter option of `name`
    (_SEPARATOR_VALUE_OPTIONS), e.g. the `/` of `cut -d / -f1 file`."""
    return index > 0 and args[index - 1] in _SEPARATOR_VALUE_OPTIONS.get(name, frozenset())


# A call whose argument list holds a string that is only normalised or resolved as text. The code before
# the opening parenthesis must end in one of these, within _CALL_WINDOW characters. The calls are those of
# JavaScript runtimes, so only their inline code gets the exception.
_JS_INTERPRETERS = frozenset({"node", "nodejs", "deno", "bun"})
_CALL_WINDOW = 120
_NORMALISING_CALL_RE = re.compile(
    r"""(?:
        \bnew\s+URL
      | (?<![\w$.])URL
      | (?<![\w$.])url\.resolve
      | \brequire\(\s*(?P<q1>['"])(?:node:)?url(?P=q1)\s*\)\s*\.resolve
      | (?<![\w$.])path(?:\.posix)?\.normalize
      | \brequire\(\s*(?P<q2>['"])(?:node:)?path(?P=q2)\s*\)(?:\s*\.posix)?\s*\.normalize
    )\s*$""",
    re.VERBOSE,
)

# Names of file APIs: when the inline code mentions one, no literal is exempt (see _read_candidates).
_FILE_API_RE = re.compile(
    r"""\bfs\b|\bfsp\b|\bopen\s*\(|\bopenSync\b|read[Ff]ile|write[Ff]ile|\bPath\s*\(|\bpathlib\b
      |\bchild_process\b|\bos\.|\bshutil\b|\bio\.|\bDeno\.|\bBun\.|\bsubprocess\b
      |\bfetch\b|\bimport\.meta\b|(?i:\bfile:)
      |\bcreate(?:Read|Write)Stream\b|\breaddir|\bglob\b|\bimport\s*\(|\brequire\s*\(\s*[^'"\s)]
      |\beval\s*\(|\bnew\s+Function\b|\bexec(?:Sync|File)?\s*\(|\bspawn""",
    re.VERBOSE,
)

_OPENERS = {"(": ")", "[": "]", "{": "}"}


def _url_argument_literals(code: str, starts: list[int]) -> set[int]:
    """The members of `starts` (offsets of a quote that opens a string literal of `code`) whose literal is
    a direct argument of a URL or path normalisation (_NORMALISING_CALL_RE): the innermost bracket open at
    that point is the `(` of such a call. A literal inside a nested call, a bracket or a block, and one the
    scan cannot place (it lies inside another string, or the brackets do not match) are left out. One pass
    over `code`; the call name is matched once per `(`, within the _CALL_WINDOW characters before it, so
    cost is linear. Whether the code names a file API (_FILE_API_RE) is for the caller."""
    wanted = set(starts)
    exempt: set[int] = set()
    stack: list[tuple[str, bool]] = []  # (opening bracket, it opens a normalising call)
    quote = ""
    index = 0
    while index < len(code):
        char = code[index]
        if quote:
            if char == "\\":
                index += 1
            elif char == quote:
                quote = ""
        else:
            if index in wanted and stack and stack[-1][1] and char in "'\"":
                exempt.add(index)
            if char in "'\"`":
                quote = char
            elif char in _OPENERS:
                normalising = char == "(" and bool(
                    _NORMALISING_CALL_RE.search(code, max(0, index - _CALL_WINDOW), index))
                stack.append((char, normalising))
            elif char in ")]}":
                if not stack or _OPENERS[stack[-1][0]] != char:
                    return exempt  # unbalanced: nothing after this point is placed
                stack.pop()
        index += 1
    return exempt


# --- a URL route as an argument of a script call ------------------------------------------------
#
# `python scripts/replace.py "/api/users" "/api/v2/users"`, `node scripts/rename-route.js /api/users`: the
# program is a script of the project and the word is a URL route it works on, not a place it reads. Allow-list:
# a word is left out of the read scan only when EVERY condition holds, anything else is read as before:
#   - the command is a script call (_SCRIPT_CALLS, or a program word that is a relative path such as
#     `./run.sh`), the word stands after the script (never the script itself) and the call runs no inline code
#     (`-c`, `-e`, `--eval`, a `-` for standard input);
#   - the word starts with one `/` and holds no `..`, `~`, backslash, quote, space or shell operator, and its
#     first segment is plain text (_ROUTE_SEGMENT_RE: no drive, no variable, no glob, no `:`);
#   - the word is not the value of an option that names a file (_FILE_OPTIONS, _FILE_OPTION_RE);
#   - the first segment names nothing, looked up the way the check resolves any path (_root_entry_exists).
# A known file command (`cat`, `cp`, `ls` ...) is no script call: `cat "/api/users"` is judged as ever.


@dataclass(frozen=True)
class _ScriptCall:
    """How the words of one kind of script call are laid out, up to the first word after the script."""

    extensions: tuple[str, ...] = ()  # the script file; empty: the word is a package (`npx tsx`)
    subcommands: frozenset = frozenset()  # words between the program and the script (`deno run`)
    subcommand_optional: bool = False
    inline_letters: str = ""  # short options that make the next word code, also inside a group (`-uc`)
    value_options: frozenset = frozenset()  # options whose next word is their value, not the script
    script_options: frozenset = frozenset()  # options whose next word is the script (`php -f`)


_JS_EXTENSIONS = (".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".jsx", ".tsx")
_TS_RUNNER = _ScriptCall(
    _JS_EXTENSIONS, subcommands=frozenset({"watch"}), subcommand_optional=True, inline_letters="ep",
    value_options=frozenset({"--tsconfig", "-P", "--project", "-r", "--require", "--import", "--env-file"}),
)
_SHELL_SCRIPT = _ScriptCall(
    (".sh", ".bash", ".zsh"), inline_letters="c", value_options=frozenset({"-o", "-O", "--rcfile", "--init-file"}),
)
_PACKAGE_OPTIONS = frozenset({"-p", "--package", "--registry", "--userconfig", "--cache", "-C", "--dir", "--cwd",
                              "--filter", "-F", "-w", "--workspace", "--prefix"})
_SCRIPT_CALLS: dict[str, _ScriptCall] = {
    "node": _ScriptCall(
        _JS_EXTENSIONS, inline_letters="epci",
        value_options=frozenset({"-r", "--require", "--import", "--loader", "--experimental-loader", "--env-file",
                                 "--conditions", "-C", "--input-type", "--title"}),
    ),
    "deno": _ScriptCall(
        _JS_EXTENSIONS, subcommands=frozenset({"run"}),
        value_options=frozenset({"-c", "--config", "--import-map", "--lock", "--cert", "--env-file", "--location",
                                 "--v8-flags", "--seed"}),
    ),
    "bun": _ScriptCall(
        _JS_EXTENSIONS, subcommands=frozenset({"run"}), subcommand_optional=True, inline_letters="ep",
        value_options=frozenset({"--cwd", "-c", "--config", "--env-file", "--port", "--tsconfig-override"}),
    ),
    "tsx": _TS_RUNNER,
    "ts-node": _TS_RUNNER,
    "ts-node-esm": _TS_RUNNER,
    "ts-node-script": _TS_RUNNER,
    "ruby": _ScriptCall((".rb",), inline_letters="e", value_options=frozenset({"-r", "-I", "-C"})),
    "php": _ScriptCall(
        (".php",), inline_letters="rR", script_options=frozenset({"-f"}), value_options=frozenset({"-d", "-c", "-z"}),
    ),
    "perl": _ScriptCall((".pl", ".t"), inline_letters="eE", value_options=frozenset({"-I"})),
    "lua": _ScriptCall((".lua",), inline_letters="e", value_options=frozenset({"-l"})),
    "bash": _SHELL_SCRIPT,
    "sh": _SHELL_SCRIPT,
    "zsh": _SHELL_SCRIPT,
    "dash": _SHELL_SCRIPT,
    "ksh": _SHELL_SCRIPT,
    "npx": _ScriptCall(inline_letters="c", value_options=_PACKAGE_OPTIONS),
    "bunx": _ScriptCall(inline_letters="c", value_options=_PACKAGE_OPTIONS),
    "pnpm": _ScriptCall(subcommands=frozenset({"exec", "dlx"}), inline_letters="c", value_options=_PACKAGE_OPTIONS),
    "yarn": _ScriptCall(subcommands=frozenset({"exec", "dlx"}), inline_letters="c", value_options=_PACKAGE_OPTIONS),
    "npm": _ScriptCall(subcommands=frozenset({"exec", "x"}), inline_letters="c", value_options=_PACKAGE_OPTIONS),
}
_PYTHON_CALL = _ScriptCall(
    (".py", ".pyw"), inline_letters="cm", value_options=frozenset({"-W", "-X", "-Q", "--check-hash-based-pycs"}),
)
_PYTHON_NAME_RE = re.compile(r"^(?:python|py|pythonw)\d*(?:\.\d+)*$")
# Long options that run inline code, and the same words after a package (`npx tsx -e ...`), where the program
# behind the package is not known.
_INLINE_LONG = frozenset({"--eval", "--print", "--command", "--call"})
_INLINE_AFTER_PACKAGE = _INLINE_LONG | {"-e", "-c", "-p"}
_RELATIVE_PROGRAM_RE = re.compile(r"^(?:\.[/\\]|[A-Za-z0-9_][A-Za-z0-9_.-]*[/\\])")
_ROUTE_SEGMENT_RE = re.compile(r"^[A-Za-z0-9_.@+-]+$")
_ROUTE_BAD_CHARS_RE = re.compile(r"""[\s\\~'"`;&|<>()$%\x00]""")
# A brace group the shell expands (`{a,b}`, `{1..3}`); `{id}` stays text.
_ROUTE_BRACE_RE = re.compile(r"\{[^{}]*(?:,|\.\.)[^{}]*\}")
# Options that name a file or a folder: what stands behind one is never read as a route. Matched on the option
# name without its dashes, lower case; a name that ends in one of _FILE_OPTION_RE's words counts as well.
_FILE_OPTIONS = frozenset({
    "o", "f", "i", "c", "d", "e", "l", "r", "output", "out", "outdir", "outfile", "file", "files", "input", "in",
    "infile", "config", "conf", "cfg", "cwd", "dir", "directory", "path", "paths", "root", "log", "cache", "dest",
    "destination", "target", "source", "src", "template", "schema", "tsconfig", "project", "key", "cert", "ca", "pem",
    "workdir", "base", "folder", "prefix", "data", "store", "db", "database", "to", "save", "save-to",
})
_FILE_OPTION_RE = re.compile(r"(?:file|dir|path|folder|directory|out|root|config|dest|target|save)s?$|(?:^|[-_])to$")
# Names a POSIX root has, for a path of the POSIX side on Windows (`/etc` is no folder of any drive there, but the
# shell the call runs in has it).
_POSIX_ROOT_NAMES = frozenset({
    "bin", "boot", "dev", "etc", "home", "lib", "lib32", "lib64", "mnt", "opt", "proc", "root", "run", "sbin", "srv",
    "sys", "tmp", "usr", "var", "media", "mingw32", "mingw64", "ucrt64", "clang64", "clangarm64", "cygdrive",
    "system", "users", "library", "applications", "volumes", "private",
})


def _bare(word: object) -> str:
    return str(word).strip().strip("'\"")


def _script_call_for(name: str) -> Optional[_ScriptCall]:
    if _PYTHON_NAME_RE.match(name):
        return _PYTHON_CALL
    return _SCRIPT_CALLS.get("node" if name == "nodejs" else name)


def _is_relative_program(program: str) -> bool:
    text = _bare(program)
    return bool(
        text and _RELATIVE_PROGRAM_RE.match(text) and ".." not in _SEGMENT_SPLIT_RE.split(text)
        and not _URL_RE.match(text)
    )


def _script_arg_start(name: str, program: str, args: list[str]) -> Optional[int]:
    """Index in `args` of the first word after the script of a script call, or None when the command is none
    (a known file command, an unknown program), runs inline code, or its script cannot be told."""
    call = _script_call_for(name)
    if call is None:
        return 0 if _is_relative_program(program) else None  # `./run.sh /api/x`: the program is the script
    index = 0
    subcommand_done = not call.subcommands
    after_dashes = False
    while index < len(args):
        word = _bare(args[index])
        if not after_dashes and word == "--":
            after_dashes = True
            index += 1
            continue
        if not after_dashes and word.startswith("-") and len(word) > 1:
            flag, equals, _value = word.partition("=")
            if flag in _INLINE_LONG:
                return None
            if flag in call.script_options and not equals:
                found = index + 1 < len(args) and _bare(args[index + 1]).lower().endswith(call.extensions)
                return index + 2 if found else None
            if not word.startswith("--") and not equals and any(letter in call.inline_letters for letter in word[1:]):
                if not any(flag.startswith(option) and len(flag) > len(option) for option in call.value_options):
                    return None  # `-c`, `-e`, `-uc`: the next word is code
            index += 1 if equals or flag not in call.value_options else 2
            continue
        # A word that is no option.
        if not subcommand_done:
            if word in call.subcommands:
                subcommand_done = True
                index += 1
                continue
            if not call.subcommand_optional:
                return None
            subcommand_done = True
        if not call.extensions:
            # A package (`npx tsx`, `pnpm dlx tool`): what runs behind it is unknown, so code options after it
            # take the exception away.
            rest = [_bare(arg) for arg in args[index + 1:]]
            if any(arg.split("=", 1)[0] in _INLINE_AFTER_PACKAGE for arg in rest):
                return None
            return index + 1
        return index + 1 if word.lower().endswith(call.extensions) else None
    return None


def _names_a_file_option(word: str) -> bool:
    """True when `word` is an option (without a value in the same word) that takes a file or a folder."""
    text = _bare(word)
    if not text.startswith("-") or len(text) < 2 or "=" in text:
        return False
    name = text.lstrip("-").lower()
    if name in _FILE_OPTIONS or _FILE_OPTION_RE.search(name):
        return True
    # A bundle of short options ends in the one that takes the value (`-vo /backup/x`).
    return not text.startswith("--") and len(name) > 1 and name.isalpha() and name[-1] in _FILE_OPTIONS


def _route_first_segment(word: str) -> Optional[str]:
    """The first segment of `word` when it has the shape of a URL route (one leading `/`, plain first segment, no
    `..`, `~`, backslash, quote, space, shell operator, variable, `%` or expanding brace group anywhere), else
    None."""
    text = _bare(word)
    if (
        not text.startswith("/") or text.startswith("//") or _ROUTE_BAD_CHARS_RE.search(text)
        or _ROUTE_BRACE_RE.search(text)
    ):
        return None
    segments = text[1:].split("/")
    if ".." in segments or not _ROUTE_SEGMENT_RE.match(segments[0]) or segments[0] == ".":
        return None
    return segments[0]


def _is_route_argument(args: list[str], index: int, start: int) -> bool:
    """True when `args[index]` (at or after `start`, the first word behind the script) has the shape of a route
    and no file option stands in front of it."""
    if _route_first_segment(args[index]) is None:
        return False
    return not (index > start and _names_a_file_option(args[index - 1]))


_LOCAL_DRIVE_RE = re.compile(r"^[A-Za-z]:")


@functools.lru_cache(maxsize=1)
def _git_bash_roots() -> tuple[str, ...]:
    """The root folders of a Git for Windows shell (the `/` of its `/etc`), taken from the places the installer
    uses and nothing else: no PATH search (an entry that points at an unreachable share can hang the hook). Only a
    local drive form is looked at, and only a folder that holds `usr` and `etc` counts. Empty off Windows."""
    if sys.platform != "win32":
        return ()
    candidates: list[str] = []
    for variable, tail in (
        ("GIT_INSTALL_ROOT", ""), ("ProgramFiles", "Git"), ("ProgramW6432", "Git"), ("ProgramFiles(x86)", "Git"),
        ("LOCALAPPDATA", os.path.join("Programs", "Git")), ("USERPROFILE", os.path.join("scoop", "apps", "git", "current")),
    ):
        value = os.environ.get(variable)
        if value:
            candidates.append(os.path.join(value, tail) if tail else value)
    candidates.append("C:/Program Files/Git")
    roots: list[str] = []
    for candidate in candidates:
        if (
            _LOCAL_DRIVE_RE.match(candidate) and candidate not in roots
            and os.path.isdir(os.path.join(candidate, "usr")) and os.path.isdir(os.path.join(candidate, "etc"))
        ):
            roots.append(candidate)
    return tuple(roots)


def _root_entry_exists(first: str, base: Optional[str], bash: bool) -> bool:
    """True when `/<first>` names something, or cannot be told: resolved the way the check resolves any path
    (_resolve_text). On Windows a POSIX-rooted word has several readings and one existing reading is enough: the
    drive form (`/q/x` is `Q:/x` in a Git shell), a folder of the drive the program runs on (a native program
    opens `/q/x` as `<drive>:/q/x`; the drive of the base folder and of the process), a name every POSIX root has
    (_POSIX_ROOT_NAMES), a folder of a Git shell's root (_git_bash_roots)."""
    # Asked with one more segment: a one-segment word (`/api`) is a switch on Windows and resolves to nothing.
    text = _resolve_text("/" + first + "/_", base, bash)
    if text is None:
        return True
    if sys.platform != "win32":
        return os.path.lexists(os.path.dirname(text))
    if not text.startswith(_POSIX_PREFIX) and os.path.lexists(os.path.dirname(text)):
        return True
    if first.lower() in _POSIX_ROOT_NAMES:
        return True
    roots = list(_git_bash_roots())
    try:
        working = os.getcwd()
    except OSError:
        working = ""
    for origin in (base or "", working):
        drive = _LOCAL_DRIVE_RE.match(origin)
        if drive and drive.group(0) + "\\" not in roots:
            roots.append(drive.group(0) + "\\")
    return any(os.path.lexists(os.path.join(root, first)) for root in roots)


def _read_candidates(
    name: str, args: list[str], feeds_xargs: bool = False, powershell: bool = False,
    program: str = "", route_absent: Optional[Callable[[str], bool]] = None,
) -> list[tuple[str, bool]]:
    """(word, strict) pairs of a simple command that may name a place; `strict` marks a string
    literal of inline interpreter code, where a `..` is no path. With `route_absent` (does the first
    segment of this word name nothing?) a URL route behind the script of a script call is left out
    (_script_arg_start); `program` is the program word as written."""
    if name in _TEXT_COMMANDS and not feeds_xargs:
        return []
    skip = _non_path_positions(name, args)
    found: list[tuple[str, bool]] = []
    route_from = _script_arg_start(name, program, args) if route_absent is not None else None
    for index, word in enumerate(args):
        if index in skip:
            continue
        if (
            route_from is not None and index >= route_from and _is_route_argument(args, index, route_from)
            and route_absent is not None and route_absent(word)
        ):
            continue  # a URL route for a script: text it works on, no place it reads
        for position, candidate in enumerate(_candidate_words(word)):
            if candidate.strip().strip("'\"") == "/" and (
                position or _is_division(name, args, index, powershell) or _is_separator_value(name, args, index)
            ):
                # `--grep=/` (the value of an option), `6 / 2` (a division) and `cut -d /` (a delimiter)
                # name no place
                continue
            if _looks_like_path(candidate):
                found.append((candidate, False))
        if name in _INTERPRETERS and (" " in word or '"' in word or "'" in word):
            matches = list(_LITERAL_RE.finditer(word))
            plain: set[int] = set()
            if matches and name in _JS_INTERPRETERS and not _FILE_API_RE.search(" ".join(args)):
                plain = _url_argument_literals(word, [match.start() for match in matches])
            for match in matches:
                literal = match.group(1)
                if not _looks_like_path(literal, strict=True):
                    continue
                if match.start() in plain and not _FILE_URL_RE.match(literal.strip()):
                    continue  # the argument of a URL or path normalisation: text, no read
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


def _last_value(values: dict[str, list[str]], *flags: str) -> Optional[str]:
    """The value of the first of `flags` that was given with a non-empty value; of a repeated flag the
    last one, since for `cp -t`, `tar -C` and `unzip -d` the later option overrides the earlier."""
    return next((values[flag][-1] for flag in flags if values.get(flag) and values[flag][-1]), None)


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
    target = _last_value(values, "-t", "--target-directory")
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
        return (_last_value(values, "-C", "--directory"),)
    if name == "unzip":
        _, values = _operands(args, frozenset({"-d"}))
        return (values.get("-d", [None])[-1],)
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
        for base in judge.capped(bases):
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
        for base in judge.capped(bases):
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


def _scan_wsl(judge: _Judge, args: list[str], bases: list[Optional[str]], depth: int) -> bool:
    """The command line of a `wsl`/`wsl.exe` call read as the commands it runs inside WSL: its words with
    `/mnt/<x>/...` as drive <X>: (shell_targets._wsl_native_word, the mapping the write-target scanners
    apply to the same line), split by the shell lexer where wsl hands the text to the distribution's
    shell, taken as they stand under `--exec`. A `--cd` directory in Windows or `/mnt` form is a read and
    the base of what follows; a Linux one (`~`, `/home/...`) leaves the base unknown. False when the call
    runs no command line (`wsl --list`, `--export`, ...): the caller then reads the words as before."""
    parsed = _wsl_command_line(args)
    if parsed is None:
        return False
    rest, cd_dir, exec_mode = parsed
    if cd_dir is not None:
        moved = str(_wsl_native_word(cd_dir))
        if _DRIVE_RE.match(moved) or _UNC_RE.match(moved):
            judge.judge(moved, False, bases)
            texts = [
                text for base in judge.capped(bases)
                for text in [_resolve_text(moved, base, judge.bash)]
                if text and not text.startswith(_POSIX_PREFIX)
            ]
            bases = list(dict.fromkeys(texts)) if texts else [None]
        else:
            bases = [None]
    lists: list[list[str]] = []
    if exec_mode:
        lists.append(_Words(str(_wsl_native_word(word)) for word in rest))
    else:
        nested = Parse("Bash", " ".join(str(word) for word in rest))  # the nested text: its own reading
        for words in _shell_word_lists(nested):
            item = _Words(str(_wsl_native_word(word)) for word in words)
            item.feeds_xargs = bool(getattr(words, "feeds_xargs", False))
            lists.append(item)
    _scan_from(judge, lists, bases, depth + 1, in_wsl=True)
    return True


def _scan_from(
    judge: _Judge, word_lists: list[list[str]], bases: list[Optional[str]], depth: int, in_wsl: bool = False,
) -> None:
    """Read the commands of `word_lists`. `in_wsl`: they run inside a WSL distribution, whose `/` is not any
    folder the check can look at, so no URL route is left out there (_script_arg_start)."""
    for words in word_lists:
        split = _command_split(words)
        if split is None:
            continue
        name, args = split
        if name == "wsl" and depth < 2 and _scan_wsl(judge, args, bases, depth):
            continue  # the words of the wsl call itself are its options and the line read above
        feeds = bool(getattr(words, "feeds_xargs", False))
        def route_absent(word: str, bases: list[Optional[str]] = bases) -> bool:
            first = _route_first_segment(word)
            return first is not None and not any(
                _root_entry_exists(first, base, judge.bash) for base in judge.capped(bases or [None])
            )

        for text, _strict in _read_candidates(
            name, args, feeds, not judge.bash, _program_word(words), None if in_wsl else route_absent,
        ):
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
                    inner = Parse("PowerShell", " ".join(args[flag + 1:])).ps_words()  # the nested text: its own reading
                except Exception as exc:  # noqa: BLE001 - the command counts as not checked
                    judge.scanner_failed(exc)
                    inner = []
                if inner:
                    _scan_from(judge, inner, bases, depth + 1, in_wsl)
        try:
            _lock_scan(judge, name, args, bases)
        except Exception as exc:  # noqa: BLE001 - the plain read scan keeps its findings, the call is refused
            judge.scanner_failed(exc)
        if name not in _TEXT_COMMANDS and name not in _CD_NAMES and name != "export":
            # A command that runs in a directory outside the allowed places acts there, whatever its
            # words are (`cat a.txt` after the session started elsewhere).
            judge.judge(".", False, bases)
        if name in _CD_NAMES:
            index = _positional_after(args)
            if index is not None and args[index] not in ("-", "--"):
                moved = [
                    text for base in judge.capped(bases)
                    for text in [_resolve_text(args[index], base, judge.bash)]
                    if text and not text.startswith(_POSIX_PREFIX)
                ]
                if moved:
                    bases = list(dict.fromkeys(moved))


_QUOTED_HEREDOC_RE = re.compile(r"""<<(-?)\s*(?:'([^'\s]+)'|"([^"\s]+)"|\\(\w+))""")


def _arithmetic_open_before(command: str) -> list[bool]:
    """For every index of `command`: True when an arithmetic expression (`$(( ... ))`, `(( ... ))` at a command
    start, `$[ ... ]`) is still open there, counted across lines. Quotes are not followed, on purpose: a quote
    that hides an opener only makes more of the command count as arithmetic, where a `<<` is a shift and no heredoc
    (so less is stripped, never more)."""
    openers = {match.end() - 2 for match in _ARITHMETIC_START_RE.finditer(command)}
    flags = [False] * (len(command) + 1)
    stack: list[str] = []
    index = 0
    while index < len(command):
        flags[index] = "A" in stack or "B" in stack
        char = command[index]
        if index in openers or (char == "$" and command.startswith("$((", index)):
            if char == "$":
                flags[index + 1] = flags[index + 2] = True
                index += 1
            stack.append("A")
            flags[index + 1] = True
            index += 2
            continue
        if char == "$" and command.startswith("$[", index):
            stack.append("B")
        elif char == "(" and stack:
            stack.append("p")
        elif char == ")" and stack:
            if stack[-1] == "A":
                stack.pop()
                if command.startswith(")", index + 1):
                    flags[index + 1] = True
                    index += 1
            elif stack[-1] == "p":
                stack.pop()
        elif char == "]" and stack and stack[-1] == "B":
            stack.pop()
        index += 1
    return flags


def _without_arithmetic_shifts(command: str) -> str:
    """`command` with every `<<` inside an arithmetic expression blanked out (same length): the word lexers
    take `<<'EOF'` there for a heredoc and skip the lines up to `EOF`, which in bash are commands (`(( 1
    <<'EOF' ))` followed by `touch /x`). Nothing in an arithmetic expression is a path, so nothing is lost."""
    if "<<" not in command:
        return command
    inside = _arithmetic_open_before(command)
    chars = list(command)
    for index in range(len(chars) - 1):
        if chars[index] == "<" and chars[index + 1] == "<" and inside[index]:
            chars[index] = chars[index + 1] = " "
    return "".join(chars)


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


def _shell_word_lists(parse: Parse) -> list[list[str]]:
    """The simple commands of `parse.command` as word lists, read the way every other check reads them
    (`Parse.words`); a coarse split only when the lexer fails. An assignment in front of a
    command is returned as the arguments of its own `export`; the command that feeds `xargs` is
    marked (`_Words`)."""
    try:
        raw = parse.words()
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
        return _coarse_word_lists(parse.command)


# Programs whose `-c` text is code of a language, not a command line.
_CODE_INTERPRETERS = _INTERPRETERS - {"pwsh", "powershell"}


def _ps_lists(parse: Parse, depth: int = 0) -> list[list[str]]:
    """`Parse.ps_words(2)` with one change: in the `-c` text of a language interpreter (`python -c "print(7
    // 2)"`) a word of only slashes is an operator or a comment of that language, not a path, so it is
    left out. The text of a nested shell or PowerShell (`pwsh -c "ls //"`) is a command line and keeps
    every word."""
    lists: list[list[str]] = []
    for words in parse.ps_words(2):  # 2: the nested text is read here, not there
        lists.append(words)
        inner = _extract_ps_command_flag(words[1:]) if depth < 2 else None
        if not inner:
            continue
        nested = _ps_lists(Parse(parse.tool_name, inner), depth + 1)  # the nested text: its own reading
        if _command_name(words[0]) in _CODE_INTERPRETERS:
            trimmed = ([word for word in item if not _BARE_SLASHES_RE.match(word)] for item in nested)
            nested = [item for item in trimmed if item]
        lists.extend(nested)
    return lists


# --- loop words that are only the tail of a URL ---------------------------------------------------
#
# `for p in /a /b; do curl "https://host$p"; done`: the words after `in` are no files, they only ever
# stand directly behind `<scheme>://<host>` in a URL. Allow-list: the words are left out of the read scan
# only when the loop is literal and EVERY use of the variable in the command is such a URL tail inside
# its body; anything else (a use outside the body, a plain `$p`, `${p:-x}`, `${!p}`, a `file:` URL, a
# body with a command substitution, a nested loop, `eval` ...) reads the words as before.

_LOOP_WORD = r"[^\s;&|<>$`'\"\\(){}*?\[\]~#!=]+"
_LOOP_HEAD_RE = re.compile(
    r"(?:^|(?<=[;&|\n]))[ \t]*for[ \t]+(?P<var>[A-Za-z_]\w*)[ \t]+in[ \t]+"
    r"(?P<words>" + _LOOP_WORD + r"(?:[ \t]+" + _LOOP_WORD + r")*)[ \t]*(?:;|\n)[ \t\n]*do(?=[\s;])"
)
_LOOP_DONE_RE = re.compile(r"(?:^|(?<=[\s;]))done(?=[\s;&|)]|$)")
_LOOP_BODY_BAD_RE = re.compile(
    r"`|\$\(|<<|\$\{!|(?:^|(?<=[;&|(\n]))[ \t]*\.(?=\s|$)"
    r"|\b(?:for|while|until|do|case|select|function|coproc|eval|declare|typeset|source"
    r"|export|local|readonly|set|IFS)\b"
)
_URL_TAIL_SCHEMES = "https?|ftps?|wss?"


def _in_quotes_at(command: str, position: int) -> bool:
    """True when `position` lies inside a quoted string of the shell command (a plain left-to-right
    reading, good enough to keep a loop that is only text out of the allow-list)."""
    state = ""
    index = 0
    while index < position:
        char = command[index]
        if state == "'":
            if char == "'":
                state = ""
        elif char == "\\":
            index += 1
        elif state == '"':
            if char == '"':
                state = ""
        elif char in ("'", '"'):
            state = char
        index += 1
    return state != ""


def _url_loop_words(command: str) -> list[tuple[int, int]]:
    """The (start, end) spans of the word lists after `in` of the `for` loops whose variable is used
    only as the tail of a `<scheme>://<host>` URL inside the loop's body (see above)."""
    if "<<" in command:
        return []
    spans: list[tuple[int, int]] = []
    for head in _LOOP_HEAD_RE.finditer(command):
        var = head.group("var")
        if _in_quotes_at(command, head.start("var")):
            continue
        done = next(
            (m for m in _LOOP_DONE_RE.finditer(command, head.end()) if not _in_quotes_at(command, m.start())),
            None,
        )
        if done is None:
            continue
        body_start, body_end = head.end(), done.start()
        if _LOOP_BODY_BAD_RE.search(command[body_start:body_end]):
            continue
        name = re.escape(var)
        uses = {
            match.start()
            for match in re.finditer(rf"\$(?:{name}(?!\w)|\{{[^}}]*(?<!\w){name}(?!\w)[^}}]*\}})", command)
        }
        tails = {
            match.start("ref")
            for match in re.finditer(
                rf"(?<![^\s'\"=])(?:{_URL_TAIL_SCHEMES})://[^\s/$`'\"\\;&|<>(){{}}]+(?P<ref>\${name}(?!\w)|\$\{{{name}\}})",
                command[:body_end], re.IGNORECASE,
            )
            if match.start("ref") >= body_start
        }
        # The bare name may occur only in the head and in the tails: `x=p; cat "${!x}"` and `printenv p`
        # use the variable by name alone.
        names = len(re.findall(rf"(?<!\w){name}(?!\w)", command))
        if uses and uses == tails and names == 1 + len(tails):
            spans.append((head.start("words"), head.end("words")))
    return spans


def _without_url_loop_words(command: str) -> str:
    """`command` with the words of every loop of `_url_loop_words` replaced by a plain word, for the read
    scan only (the write-target scanners get the command as it is)."""
    try:
        spans = _url_loop_words(command)
    except Exception:  # noqa: BLE001 - no allow-list then, the words are read as before
        return command
    for start, end in reversed(spans):
        command = command[:start] + "_" + command[end:]
    return command


def _shell_findings(judge: _Judge, tool: str, command: str, cwd: str, parse: Parse) -> None:
    powershell = tool == "PowerShell"
    whole = command  # the write scan below reads the program a quoted heredoc feeds to an interpreter, like `-c`/`-e`
    # The text of a quoted heredoc is never run; cut out first, so that a line of the command that
    # does not tokenize cannot push a scanner into reading the body as commands (`<id>` in a commit
    # message would be a redirection). A body a shell may run (`bash <<'EOF'`) stays.
    if not powershell:
        try:
            command = _without_arithmetic_shifts(command)
            if not _heredoc_may_feed_shell(command):
                command = _without_quoted_heredocs(command)
        except Exception:  # noqa: BLE001 - the whole command is scanned then
            pass
    # Writes first: a word that is also a write target is reported as the write.
    try:
        if len(_CD_WORD_RE.findall(command)) > _MAX_CD_FOR_TARGET_SCAN:
            # The shared write-target scanners follow every directory change and their cost grows with
            # the cube of a `cd a; cd b; ...` chain (800 of them: 20 s, past any hook timeout). They are
            # not run beyond a chain no real command line has, and the call is refused rather than let
            # through unchecked: a write behind such a chain would not be seen. A word that names the
            # marker folder is still reported as a write to it.
            judge.unchecked.append(
                f"it holds more than {_MAX_CD_FOR_TARGET_SCAN} directory changes (cd, pushd, Set-Location ...), "
                "more than the write-target scanners can follow"
            )
            if "outside-allow" in command.lower():
                judge.lock(".act-local/outside-allow", judge.lock_dir)
        elif powershell:
            reading = parse.for_text(command)
            targets = reading.write_targets(cwd, _GIT_WRITES_WORKER_SCOPE)
            if targets is None:
                targets = reading.ps_raw_redirects()
            for target in sorted(targets):
                if _is_unplaced_target(target):
                    # The scanner could not place this write (a relative one behind more directory changes than
                    # it tracks, a command larger than its budget): not checked in full, refused like a scanner
                    # failure — never resolved against the directory the command started in.
                    reason = f"it holds a write the scanner could not place ({_unplaced_reason(target)})"
                    if reason not in judge.unchecked:
                        judge.unchecked.append(reason)
                    continue
                judge.judge(target, True, [cwd])
        else:
            scanned = parse.for_text(whole if mentions_interpreter(whole) else command)
            for target, base in scanned.bash_write_targets(cwd, _GIT_WRITES_WORKER_SCOPE):
                if _is_unplaced_target(target):
                    judge.unchecked.append(f"it holds a write the scanner could not place ({_unplaced_reason(target)})")
                    continue
                judge.judge(str(target), True, [base if base is not None else cwd])
    except Exception as exc:  # noqa: BLE001 - the read scan below still runs, the call is refused
        judge.scanner_failed(exc)
    groups: list[list[list[str]]] = []
    if powershell:
        try:
            groups.append(_ps_lists(parse.for_text(command)))
        except Exception as exc:  # noqa: BLE001
            judge.scanner_failed(exc)
    try:
        # The inside of a shell arithmetic expression is no command line (PowerShell has none of that syntax).
        groups.append(_shell_word_lists(parse.for_text(
            command if powershell else _without_url_loop_words(_without_arithmetic(command)))))
    except Exception as exc:  # noqa: BLE001
        judge.scanner_failed(exc)
    for lists in groups:
        try:
            _scan_word_lists(judge, lists, cwd)
        except Exception as exc:  # noqa: BLE001 - one group failing leaves the other, the call is refused
            judge.scanner_failed(exc)


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
            "Ways out, only on the owner's word for this case (never add one yourself): an entry in "
            "`outside-root-allow` (docs/ai/config.md § Checks; `<path>` or `<path> (read)`; for a program "
            "folder outside the project and the home directory, such as a browser, the absolute path "
            "`D:/Program Files/Browser` or `/opt/browser`, which is read-only: for reading and starting a "
            "program, not for writing), the folder under `permissions.additionalDirectories`, or "
            f"{_ENV_OVERRIDE}=warn for one run"
        )
    more = ""
    if len(findings) > 1:
        more = f" {len(findings) - 1} more path(s) outside, the same way."
    return f"{lead} {what}{more} {ways}"


def _unchecked_message(reasons: list[str], tool: str, found: list[_Finding]) -> str:
    if not found:
        named = ""
    elif found[0].lock:
        named = f" It also writes where the `.act-local/outside-allow` folder could be created (`{found[0].raw}`)."
    else:
        named = f" It also reads or writes `{found[0].raw}`, outside the project and its allowed places."
    bug = " A scanner failure is a bug of the template: report it." if any("failed" in item for item in reasons) else ""
    return (
        f"[act] outside-root refused -- {tool} command not checked in full: {'; '.join(reasons)}, so what it "
        f"touches is unknown (R-safe-outside-root).{named} Split it into shorter commands.{bug} The owner can set "
        f"`outside-root` to `off` in docs/ai/config.md § Checks, or for one run with {_ENV_OVERRIDE}=off"
    )


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
        _shell_findings(judge, shell[0], shell[1], cwd, parse_for(payload, shell[1]))
    else:
        _file_tool_findings(judge, payload, cwd)
    if shell is not None and judge.unchecked:
        # Fail closed, like a failing check module (dispatch.py): a command the scanners did not see in full
        # may hold what they would have refused. Whatever mode says, short of `off`.
        print(_unchecked_message(judge.unchecked, tool, judge.found), file=sys.stderr)
        return 2
    if not judge.found:
        return 0
    message = _message(judge.found, tool, mode)
    if mode == "warn":
        # the incident log counts a hit only when the call wrote (a read outside is a hint nobody needs to act on);
        # reported here, not left to the printed text, so that an override from the environment counts as well
        writes = [item for item in judge.found if item.write]
        shown = (writes or judge.found)[0]
        _note_hit("outside-root", ("reserved-folder" if shown.lock else "outside-write") if writes else "outside-read",
                  _target_class(shown.shown, root), acts=bool(writes))
        print(message)
        return 0
    print(message, file=sys.stderr)
    return 2
