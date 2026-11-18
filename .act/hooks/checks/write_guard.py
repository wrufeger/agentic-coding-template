#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check 1 — template write-guard (PreToolUse), checked before every other check. Denies
#          an AI write under .act/**, pointing at docs/ai/local/<path> instead. It protects the project's
#          .act-local/packages/ the same way (the packages the lock records change through packages.py only), and
#          .act-local itself: moving, renaming or removing the folder that holds them is refused too.
#
# Exit-code contract specific to this check: a mechanism error while checking a candidate write is
# NOT swallowed the way most other checks fail open. Every other check in this template fails open
# (never blocks the session on its own bug); this one is the exception — "when in doubt, deny"
# — because a false allow here means the template silently loses its own
# files to an edit the next update overwrites anyway.

from __future__ import annotations

import os
import re
import shlex
import sys
from pathlib import Path
from typing import Callable, Optional

import actlib

from .command_parse import Parse, parse_for
from .inline_code import WHOLE_FOLDER, mentions_interpreter
from .common import _TOOL_PATH_FIELDS, _check_mode, _note_refusal_class
from .common import _is_unplaced_target, _unplaced_reason
from .list_feeds import FIND_HIT, Binding, ShellFacts, find_hits, lists_files, ps_fed_writes, shell_facts
from .shell_targets import _GIT_WRITES_TEMPLATE_GUARD, _XARGS_INPUT, _is_absolute_target, _is_dynamic_target
from .shell_targets import _ASSIGNMENT_RE, _RESERVED_PREFIXES, _VALUE_FLAGS, _WINDOWS_SWITCH_RE
from .shell_targets import _command_name, _raw_redirect_targets, _simple_command_targets
from .shell_targets import _resolve_path

__all__ = [
    "_PROTECTED_PATH_RE", "_names_protected_path", "_WRITE_GUARD_MESSAGE", "_UNKNOWN_FOLDER_MESSAGE",
    "_PACKAGES_MESSAGE", "_UNKNOWN_PACKAGES_MESSAGE", "_LOCAL_MESSAGE", "_is_under_packages", "_is_local_itself",
    "_bash_targets_protected_path", "_powershell_targets_protected_path", "_unplaced_message",
    "_targets_protected_path", "_is_under_project_act",
    "_resolve_against", "_guard_root", "check_write_guard",
]

# ".act" as a whole path segment, in any spelling of case (".ACT/x" is the same file as ".act/x" on Windows
# and on macOS, whose file systems do not tell the two apart): ".act/" or ".act\" anywhere in the string, or
# ".act" at the very end — never as a prefix of another name. Deliberately no required prefix character
# before ".act" (a shell command has it after a space, quote, "=", redirect symbol, "(", and
# so on — enumerating all of those is more fragile than just not requiring one). The suffix
# check is what excludes ".act-lock.json" and ".act-local/", both project-level state next to
# the template tree rather than inside it, from this guard.
_ACT_PATH_RE = re.compile(r"\.act(?:[\\/]|$)", re.IGNORECASE)
# The packages folder of a project, `.act-local/packages` as a whole path segment pair (`.act-local/packages-old/` is
# another folder and stays free): the second tree this check protects. A throwaway project below `.act-local/tmp/`
# has one of its own, which is free like its `.act/`.
_PACKAGES_PATH_RE = re.compile(r"\.act-local[\\/]packages(?:[\\/]|$)", re.IGNORECASE)
# `.act-local` itself as the last part of a target (the folder that holds `packages/`): moving, renaming or
# removing it takes the packages with it. Names below it (`.act-local/tmp/x`) are no match.
_LOCAL_ITSELF_RE = re.compile(r"(?:^|[\\/])\.act-local[\\/]*$", re.IGNORECASE)
# Any of the three, for a text that cannot be resolved.
_PROTECTED_PATH_RE = re.compile(
    _ACT_PATH_RE.pattern + "|" + _PACKAGES_PATH_RE.pattern + "|" + _LOCAL_ITSELF_RE.pattern, re.IGNORECASE)
# A throwaway tree: `.act-local/tmp/` as whole segments. A throwaway project below it carries a `.act/` of
# its own, which is no part of the project's template tree.
_THROWAWAY_RE = re.compile(r"(?:^|[\\/])\.act-local[\\/]tmp[\\/]")
# A path segment that is known as it stands: no variable (`$NAME`, cmd's `%NAME%`), command substitution, glob,
# brace, `~`, parenthesis, quote or white space, and not `..`. What may follow `.act-local/tmp/` in an exempt
# text, and what may stand before it, segment by segment (an empty segment is a doubled or trailing separator).
_PLAIN_SEGMENT_RE = re.compile(r"^(?!\.\.$)[^\\/$%`*?\[\]{}~()'\"\s]*$")
# The one place a variable may stand before `.act-local/tmp/`: the whole first segment of the text, `$NAME`,
# `${NAME}` or PowerShell's `$env:NAME`.
_LEADING_VARIABLE_RE = re.compile(r"^\$(?:\w+|\{\w+\}|env:\w+)$")


def _names_protected_path(text: str, root: Optional[Path]) -> bool:
    """True when the text of a target that cannot be resolved (a variable in it, an unknown directory)
    names `.act/` (_PROTECTED_PATH_RE) - unless it is a path inside a throwaway tree, which carries a
    `.act/` of its own. Allow-list, one pattern: the project `root` is known and does not itself lie below
    `.act-local/tmp/`, the text holds `.act-local/tmp/` as whole segments with no `.act` segment before it,
    and both parts around it are known as they stand: every segment behind it, and every segment before it
    except a first one that is a lone `$NAME`, `${NAME}` or `$env:NAME` (_LEADING_VARIABLE_RE), must match
    _PLAIN_SEGMENT_RE (no `..`, no variable, command substitution, glob, brace, `~`, parenthesis, quote or
    white space; the text before may also be empty). Allow-list: anything else that names `.act/` stays
    protected. `$ROOT/.act-local/tmp/job/proj/.act/x` is free; `$ROOT/.act/x`, `.act-local/tmp/$job/.act/x`,
    `$ROOT/.act-local/tmp/../../.act/x`, `$(x)/.act-local/tmp/job/.act/x` (a substitution that begins before
    the marker and ends after it) and `$A$B/.act-local/tmp/job/.act/x` are not. With `root` None, or a root
    below `.act-local/tmp/` in any spelling of case (a throwaway project itself, where its own `.act/` can be
    spelled through `.act-local/tmp/` behind a variable, an administrative share or any other prefix; the
    root is compared lower-cased, the marker in the text only as typed in lower case), there is no exemption
    at all. `%NAME%` (cmd's variable) is no known segment either, like `$NAME`. Limit: a leading variable is
    trusted to stand for a place outside `.act/`; one that holds `.act` itself reaches only new files below
    `.act/.act-local/tmp/`, no file of the template."""
    if not _PROTECTED_PATH_RE.search(text):
        return False
    if root is None or _THROWAWAY_RE.search(root.as_posix().lower() + "/"):
        return True
    marker = _THROWAWAY_RE.search(text)
    if marker is None:
        return True
    before, after = text[:marker.start()], text[marker.end():]
    if _PROTECTED_PATH_RE.search(before):
        return True
    if before:
        first, *rest = re.split(r"[\\/]", before)
        if not (_LEADING_VARIABLE_RE.match(first) or _PLAIN_SEGMENT_RE.match(first)):
            return True
        if not all(_PLAIN_SEGMENT_RE.match(segment) for segment in rest):
            return True
    return not all(_PLAIN_SEGMENT_RE.match(segment) for segment in re.split(r"[\\/]", after))


def _is_under_packages(resolved: Path, root: Path) -> bool:
    """True if `resolved` (absolute and already resolved, as for _is_under_project_act) is `root`'s own
    `.act-local/packages/` or lies below it: the packages the lock records and the folders resting there change
    through `packages.py` only. Only at the project root: a throwaway project below `.act-local/tmp/` has a
    `.act-local/packages/` of its own, and `.act-local/packages-old/` is another folder."""
    packages_root = _resolve_path(str(root / ".act-local" / "packages"))
    if packages_root is None:
        packages_root = (root / ".act-local" / "packages").resolve()
    resolved, packages_root = _folded(resolved), _folded(packages_root)
    return resolved == packages_root or packages_root in resolved.parents


def _is_local_itself(resolved: Path, root: Path) -> bool:
    """True if `resolved` (absolute and already resolved) is `root`'s own `.act-local` folder as a whole, a parent
    of `.act-local/packages/` within the project: a move, a rename or a removal of it takes the packages with it.
    Only the project's own: a throwaway project below `.act-local/tmp/` has a `.act-local` of its own, which is free."""
    local = _resolve_path(str(root / ".act-local"))
    if local is None:
        local = (root / ".act-local").resolve()
    return _folded(resolved) == _folded(local)


def _is_under_project_act(resolved: Path, root: Path) -> bool:
    """True if `resolved` (an absolute, already-resolved path — from _resolve_path, so already in
    the plain native drive form) lies inside `root`'s own .act/ — the only tree this check protects
    (2026-09-25): a target outside `root` entirely, even one whose own path happens to
    contain a `.act/` segment (a sibling checkout's template tree, edited on purpose from a
    template-maintenance project), is not this check's business. `root` itself goes through the
    same _resolve_path, so both sides of the comparison are spelled the same way (a
    `CLAUDE_PROJECT_DIR` handed over in the `\\\\?\\` form would otherwise never match its own
    targets)."""
    act_root = _resolve_path(str(root / ".act"))
    if act_root is None:
        act_root = (root / ".act").resolve()
    resolved, act_root = _folded(resolved), _folded(act_root)
    return resolved == act_root or act_root in resolved.parents


def _removes_root(resolved: Path, root: Path) -> bool:
    """True if `resolved` is the folder a recursive delete (inline code, `shutil.rmtree`) removes as a whole, named
    as `<folder>/(whole folder)` (inline_code.WHOLE_FOLDER), and that folder is `root` or one of its parents: it holds
    `root`'s own .act/, which the path does not show."""
    if resolved.name != WHOLE_FOLDER:
        return False
    top = _folded(_resolve_path(str(root)) or root)
    folder = _folded(resolved.parent)
    return folder == top or folder in top.parents


def _folded(path: Path) -> Path:
    """`path` lower-cased on macOS, whose default file system does not tell `.ACT` from `.act` while Path
    compares them as different names (on Windows, Path already compares without regard to case; on Linux a
    differently spelled name is a different file)."""
    return Path(str(path).lower()) if sys.platform == "darwin" else path


def _resolve_against(base_cwd: str, raw: str) -> Optional[Path]:
    """`raw` resolved to an absolute path: as-is if already absolute, else joined onto
    `base_cwd` first (shell_targets._resolve_path — the shared normalization, so a `\\\\?\\`- or
    admin-share-spelled target compares like any other). None on any error resolving it (never
    raises) — the caller then falls back to the raw-text check."""
    return _resolve_path(raw, base_cwd)


# A write whose files come from a list the scan cannot read (an `xargs` input, a `$(...)` or backtick span, a
# loop or `read` variable, the hits of `find -exec`, a PowerShell pipeline) is let through only when the command
# that makes the list is shown and names folders that are not the project root, a parent of it or `.act`: an
# allow-list of list commands, each with the operands it may take.
_LIST_MESSAGE = (
    "[act] write-guard refused -- this write takes its files from a list (an xargs input, $(...) or backticks, a "
    "loop, read or mapfile variable, the hits of find -exec or find -delete, a PowerShell pipeline) whose source "
    "does not name the folders it reads, so .act/ (the template's own files, replaced on update) may be among them. "
    "Name the folders in the list command (`grep -rl x docs src | xargs sed -i ...`, `for f in $(find docs -name "
    "'*.md'); do ...`, `find docs -exec ...`, `find docs -delete`, `Get-ChildItem docs -Recurse | Remove-Item`): a "
    "list over the project root, `.`, "
    "`..`, `git ls-files` or a list file cannot be vouched for, and a list cannot leave .act/ out. A change to a "
    "file of .act/ goes to docs/ai/local/<same path>."
)
# A change of directory in the command: where a `find` or a PowerShell lister reads from is then not known.
_CD_WORD_RE = re.compile(r"(?<![\w./\\-])(?:cd|chdir|pushd|popd|sl|set-location|push-location|pop-location)(?![\w-])",
                         re.IGNORECASE)
_BOUND_VARIABLE_RE = re.compile(r"\$(?:\{(\w+)|(\w+))")
# The one directory change that keeps the base known: a single leading `cd <literal path>` (also `Set-Location`,
# `-Path`/`-LiteralPath`) followed by `&&`, `;` or a line break.
_LEADING_CD_RE = re.compile(
    r"""^\s*(?:cd|chdir|sl|set-location)\s+(?:-(?:literal)?path\s+)?(?:"([^"$`]+)"|'([^']+)'|([^\s;&|<>"'$`*?\[\]{}()~-][^\s;&|<>"'$`*?\[\]{}()~]*))\s*(?:&&|;|\n)""",
    re.IGNORECASE)


def _command_base(command: str, base_cwd: str) -> Optional[str]:
    """The directory a list command of `command` reads from: `base_cwd`, or the literal target of a single leading
    `cd`/`Set-Location` (resolved against `base_cwd`); None when the command changes directory any other way (a
    second `cd`, `pushd`, a variable, a subshell), so a relative folder is not known."""
    words = _CD_WORD_RE.findall(command)
    if not words:
        return base_cwd
    match = _LEADING_CD_RE.match(command)
    if len(words) != 1 or match is None:
        return None
    resolved = _resolve_path(next(group for group in match.groups() if group), base_cwd)
    return str(resolved) if resolved is not None else None
_SINGLE_PATH_COMMANDS = frozenset({"mktemp", "pwd", "dirname", "basename", "date", "whoami", "hostname", "id", "uname"})
_FILTER_COMMANDS = frozenset({"head", "tail", "sort", "uniq"})
_GREP_LONG = frozenset({
    "--regexp", "--file", "--max-count", "--include", "--exclude", "--exclude-dir", "--exclude-from", "--context",
    "--after-context", "--before-context", "--label", "--binary-files", "--directories", "--devices", "--max-depth",
})
_RG_LONG = frozenset({
    "--regexp", "--file", "--glob", "--iglob", "--type", "--type-not", "--type-add", "--max-count", "--max-depth",
    "--after-context", "--before-context", "--context", "--threads", "--ignore-file", "--encoding", "--replace",
    "--sort", "--sortr", "--pre", "--max-filesize", "--path-separator",
})
# `grep`/`rg` list file names only with these; otherwise they print lines of the files named (a list file's content).
_NAME_ONLY_FLAGS = frozenset({"l", "L", "--files", "--files-with-matches", "--files-without-match"})
_FIND_ACTIONS = frozenset({"-exec", "-execdir", "-ok", "-okdir", "-printf", "-delete"})
_LS_FILES_LONG = frozenset({"--exclude", "--exclude-from", "--exclude-per-directory", "--format", "--with-tree", "--abbrev"})


def _split_flags(words: list[str], letters: str, longs: frozenset) -> tuple[list[str], list[str], set[str]]:
    """The operands before `--`, those after it, and the option names seen (letters and long names) of a
    command's words; an option in `letters`/`longs` takes a value (the rest of the word, else the next word)."""
    plain: list[str] = []
    after: list[str] = []
    flags: set[str] = set()
    index = 0
    while index < len(words):
        word = words[index]
        index += 1
        if "--" in flags and word != "--":
            after.append(word)
        elif word == "--":
            flags.add("--")
        elif word.startswith("--"):
            flags.add(word.partition("=")[0])
            if word in longs:
                index += 1
        elif word.startswith("-") and len(word) > 1:
            for position, letter in enumerate(word[1:], 1):
                flags.add(letter)
                if letter in letters:
                    index += position == len(word) - 1
                    break
        else:
            plain.append(word)
    return plain, after, flags


def _listing_operands(words: list[str], first: bool) -> Optional[list[str]]:
    """The folders the list command `words` reads (the first stage of a source, else a later stage), or None
    when it is not a command of the allow-list or reads a place it does not name: `grep`/`rg` (a recursive one
    or the first stage needs a path), `find`, `ls`, `git ls-files`, `git grep -- <paths>`; `head`/`tail`/`sort`/
    `uniq` as later stages; `echo`/`printf`, `seq` with numbers only and the commands that print one path
    (_SINGLE_PATH_COMMANDS) read nothing."""
    name = os.path.basename(words[0]).lower().removesuffix(".exe")
    rest = words[1:]
    if first and name in ("echo", "printf"):
        # Literal words only: no glob, brace, variable, substitution, escape, joining format or `.act` text.
        fmt = rest[0] if rest else ""
        if name == "printf":  # one `%s` prints each word; a format without `%` is itself the text
            texts = rest[1:] if re.fullmatch(r"%s(?:\\n)?", fmt) else ([fmt] if "%" not in fmt else None)
        else:
            texts = [word for word in rest if word != "-n"]
        escape = r"\\(?![n0](?!\d))" if name == "printf" else r"\\"
        if texts is None or any(re.search(rf"[*?\[{{$`]|{escape}", word) or _PROTECTED_PATH_RE.search(word)
                                or (name == "echo" and word.startswith("-")) for word in texts):
            return None
        return []
    if first and (name in _SINGLE_PATH_COMMANDS or (name == "git" and rest[:1] == ["rev-parse"])):
        return []
    if first and name == "seq":  # numbers only: no option (`-f` takes a format), no name
        return [] if all(re.fullmatch(r"\d+(?:\.\d+)?", word) for word in rest) else None
    if name in _FILTER_COMMANDS:
        return [] if not first and all(re.fullmatch(r"-[\w-]*|\d+", word) for word in rest) else None
    if name in ("grep", "egrep", "fgrep", "rg"):
        rg = name == "rg"
        plain, after, flags = _split_flags(rest, "efgtTmABCjdEMr" if rg else "efmABCdD", _RG_LONG if rg else _GREP_LONG)
        if "--files" not in flags and not flags & {"e", "f", "--regexp", "--file"}:
            plain = plain[1:]  # the pattern
        operands = plain + after
        if operands and not flags & _NAME_ONLY_FLAGS:
            return None  # content mode: the lines of a file named here are the list
        need = first or (not rg and bool(flags & {"r", "R", "--recursive", "--dereference-recursive"}))
        return operands if operands or not need else None
    if not first:
        return None
    if name == "find":
        if any(word in _FIND_ACTIONS or word.startswith(("-fprint", "-fls")) for word in rest):
            return None  # prints or runs something of its own
        operands: list[str] = []
        for word in rest:
            if word.startswith(("-", "!", "(")) and not (word in ("-H", "-L", "-P") and not operands):
                break
            operands += [] if word in ("-H", "-L", "-P") else [word]
        return operands or None
    if name == "ls":
        if any(word.startswith("--") or (word.startswith("-") and re.search("[IwT]", word)) for word in rest):
            return None
        return [word for word in rest if not word.startswith("-")] or None
    if name == "git" and rest[:1] == ["ls-files"]:
        plain, after, _ = _split_flags(rest[1:], "xX", _LS_FILES_LONG)
        return plain + after or None
    if name == "git" and rest[:1] == ["grep"]:
        _, after, flags = _split_flags(rest[1:], "efmABC", _GREP_LONG)
        return after if flags & (_NAME_ONLY_FLAGS | {"--name-only"}) and after else None
    if name == "git" and rest[:1] == ["diff"]:
        _, after, flags = _split_flags(rest[1:], "", frozenset())
        named = "--name-only" in flags and not any(flag.startswith("--output") for flag in flags)
        return after if named and after else None
    return None


def _fixed_folder(word: str, base: Optional[str], root: Optional[Path]) -> bool:
    """True when the operand `word` of a list command names a folder as it stands (no variable, substitution,
    brace or `~`; a glob only below a plain folder) that is neither the project `root`, a parent of it nor
    inside `.act/`."""
    if re.search(r"[$`{}~()]", word) or word.startswith(":"):  # `:/` is git's pathspec for the repository top
        return False
    glob = re.search(r"[*?\[]", word)
    prefix = re.sub(r"[^\\/]*$", "", word[:glob.start()]) if glob else word
    if not prefix.strip().rstrip("\\/"):
        return False
    if root is None:
        return True
    if base is None and not _is_absolute_target(prefix):
        return False
    resolved = _resolve_path(prefix, base)
    if resolved is None:
        return False
    top = _folded(_resolve_path(str(root)) or root)
    local = _folded(_resolve_path(str(root / ".act-local")) or root / ".act-local")  # holds `packages/`
    return not (_is_under_project_act(resolved, root) or _is_under_packages(resolved, root)
                or _folded(resolved) in (top, local) or _folded(resolved) in top.parents)


def _source_is_shown(source: str, base: Optional[str], root: Optional[Path]) -> bool:
    """True when the command text `source`, a pipeline of list commands, is of the allow-list
    (_listing_operands) and every folder it names is fixed (_fixed_folder). Any other operator (`;`, `&&`, a
    redirection but one of stderr to `/dev/null` or stdout, a subshell) or an unreadable quote is not shown;
    nor is a source that names `.act` as text."""
    if _PROTECTED_PATH_RE.search(source):
        return False
    tokens = Parse("Bash", source).chain_tokens()
    if tokens is None:
        return False
    while tokens and tokens[-1] == ("\n", True):
        tokens.pop()
    stages: list[list[str]] = []
    stage: list[str] = []
    index = 0
    while index <= len(tokens):
        text, is_operator = tokens[index] if index < len(tokens) else ("|", True)
        following = tokens[index + 1][0] if index + 1 < len(tokens) else ""
        index += 1
        if not is_operator:
            stage.append(text)
        elif text in (">", ">&") and stage and stage[-1] in ("1", "2") and following in ("/dev/null", "1", "2"):
            stage.pop()
            index += 1  # `2>/dev/null`, `2>&1`
        elif text != "|" or not stage:
            return False
        else:
            stages.append(stage)
            stage = []
    for number, words in enumerate(stages):
        operands = _listing_operands(words, number == 0)
        if operands is None or not all(_fixed_folder(operand, base, root) for operand in operands):
            return False
    return True


def _quoted_word(text: str, pos: int) -> tuple[str, int]:
    """The word `shlex.quote` wrote at `text[pos]` and the index behind it (ValueError when it does not end)."""
    start, out = pos, []
    while True:
        if text.startswith("'", pos):
            end = text.index("'", pos + 1)
            out.append(text[pos + 1:end])
            pos = end + 1
        elif text.startswith("\"'\"", pos):
            out.append("'")
            pos += 3
        else:
            break
    if pos == start:
        bare = re.compile(r"[\w@%+=:,./-]*").match(text, pos)
        return bare.group(), bare.end()
    return "".join(out), pos


def _read_placeholder(text: str, pos: int) -> Optional[tuple[str, int]]:
    """The source text and the end of the `xargs` placeholder (shell_targets._xargs_placeholder) whose
    `$(xargs input` ends at `text[pos]`; None when it does not read as that."""
    source = ""
    try:
        if text.startswith(" of ", pos):
            source, pos = _quoted_word(text, pos + 4)
        if text.startswith(" in ", pos):
            pos += 3
            while text.startswith(" ", pos):
                pos = _quoted_word(text, pos + 1)[1]
    except ValueError:
        return None
    return (source, pos + 1) if text.startswith(")", pos) else None


def _substitution_texts(command: str) -> Optional[list[str]]:
    """The text inside every `$(...)` and backtick span of `command` (a `$((` arithmetic is none); None when
    one does not end. Deliberately over-inclusive: a quote that hides one from the shell is not told apart."""
    found: list[str] = []
    index = 0
    while index < len(command):
        char = command[index]
        if char == "\\":
            index += 2
        elif char == "`":
            end = index + 1
            while end < len(command) and command[end] != "`":
                end += 2 if command[end] == "\\" else 1
            if end >= len(command):
                return None
            found.append(command[index + 1:end])
            index = end + 1
        elif command.startswith("$(", index) and not command.startswith("$((", index):
            depth, end, quote = 1, index + 2, ""
            while end < len(command) and depth:
                char = command[end]
                end += 2 if char == "\\" else 1
                if quote:
                    quote = "" if char == quote else quote
                elif char in "'\"":
                    quote = char
                else:
                    depth += (char == "(") - (char == ")")
            if depth:
                return None
            found.append(command[index + 2:end - 1])
            index = end
        else:
            index += 1
    return found


def _list_is_shown(raw: str, command: str, base: Optional[str], root: Optional[Path]) -> bool:
    """False when the dynamic write target `raw` is made of a list the scan cannot read - an `xargs` input
    placeholder, or a `$(...)`/backtick span of `command` (the scanner keeps a bare `$` of it) - whose source
    is not shown (_source_is_shown). A target made of a variable only is no list and passes here."""
    sources: list[str] = []
    rest = raw
    while (at := rest.find(_XARGS_INPUT)) >= 0:
        placeholder = _read_placeholder(rest, at + len(_XARGS_INPUT))
        if placeholder is None or not placeholder[0]:
            return False  # no source text: a list file, `-a file`
        sources.append(placeholder[0])
        rest = rest[:at] + rest[placeholder[1]:]
    if re.search(r"`|\$\((?!\()", rest) or rest == "$":  # `$((` is arithmetic, no list
        found = _substitution_texts(command)
        if found is None:
            return False  # a span that does not end
        sources += found  # none found: the `$` was an arithmetic expansion or a variable, no list
        # The scanner keeps only a bare `$` of an unquoted `$(...)`, so a suffix glued to it (`$(pwd)/.act/y`) is
        # lost: where the source prints a folder and the command names `.act`, the target may lie in it.
        if rest == "$" and _PROTECTED_PATH_RE.search(command) and any(
                re.match(r"\s*(?:pwd|dirname|git\s+rev-parse)\b", source) for source in found):
            return False
    return all(_source_is_shown(source, base, root) for source in sources)


def _bash_targets_protected_path(
    command: str, base_cwd: str, root: Optional[Path], parse: Optional[Parse] = None,
) -> Optional[str]:
    """The refusal message if a Bash command writes to a path under `root`'s own .act/ — judged from the write
    targets the shared scanner finds (Parse.write_targets), not from a mere mention: `cat .act/x >
    /tmp/y`, `python .act/scripts/doctor.py 2>&1 | tail` and `grep -rn x .act/ 2>/dev/null` are
    reads and pass. Of the git subcommands only `git mv`/`git rm` count here
    (_GIT_WRITES_TEMPLATE_GUARD): `git checkout`/`git restore` stay allowed, since the orchestrator
    uses them to switch branches, unstage, and fetch the template's own version of a .act/ file
    back. A target whose directory is unknown (after `pushd`, a `cd $VAR`, inside a subshell, ...),
    that contains a variable, or whose own project `root` could not be determined is denied only
    if its own text names .act/, with _UNKNOWN_FOLDER_MESSAGE (also where the scanner yields a target that
    resolves into .act/ with a known folder and the same target with none: the message changes, the verdict
    does not; a variable the command assigns exactly once, as a
    literal, before its first use is read as that value alone, in both directions: refused when the value is,
    passed when the value is, _judge_target) — everything else about it cannot be decided here (a
    *determinable* target is resolved and checked against `root`'s own .act/ only, never against
    the raw text — a sibling checkout's .act/ is not this project's to protect). A dynamic target that is a
    list the scan cannot read (an `xargs` input, a `$(...)` or backtick span) passes only when its source
    names fixed folders (_list_is_shown, an allow-list), else it is refused with _LIST_MESSAGE; so does a
    target made of a loop or `read` variable fed by such a list (_bound_refusal; a literal loop word that names
    `.act` or may match it is refused as a write to `.act`), and a command `find` runs on every hit
    (-exec, -execdir, -ok, -okdir; _find_run_refusal) when its folders are not fixed, and the command a `mapfile`/
    `readarray -C <callback>` runs per quantum on a line of its feed (_callback_refusal). A write the scan could
    not place (a PowerShell command it could not follow to the end, _is_unplaced_target) is refused as such; inline code whose write path the text does not show is no target and passes.
    `parse` is the dispatcher's reading of `command`; without it the command is read here."""
    if parse is None:
        parse = Parse("Bash", command)
    read: list[ShellFacts] = []

    def facts() -> ShellFacts:
        if not read:
            tokens = parse.chain_tokens()
            read.append(shell_facts(tokens) if tokens is not None else ShellFacts())
        return read[0]

    targets = list(parse.bash_write_targets(base_cwd, _GIT_WRITES_TEMPLATE_GUARD))
    for raw, base in targets:
        message = _judge_target(raw, base, root, command, facts)
        if message is not None and message.startswith(_LOCAL_MESSAGE) and _local_destination_only(
                raw, base, command, parse):
            continue  # a copy INTO `.act-local` is no write to `.act-local` as a whole
        if message is not None:
            if base is not None and (raw, None) in targets:
                # the scanner also yields this target with no known folder (after `cd $VAR`, `pushd`, in a
                # subshell): the folder is not known, so say that; the verdict stays
                for known, unknown in ((_WRITE_GUARD_MESSAGE, _UNKNOWN_FOLDER_MESSAGE),
                                       (_PACKAGES_MESSAGE, _UNKNOWN_PACKAGES_MESSAGE)):
                    if message.startswith(known):
                        message = unknown + message[len(known):]
                        break
            return message
    if re.search(r"mapfile|readarray", command, re.IGNORECASE):
        for callback, binding in facts().callbacks:
            message = _callback_refusal(callback, binding, command, base_cwd, root)
            if message is not None:
                return message
    if "find" in command.lower():
        for words in facts().finds:
            source, runs = find_hits(words)
            for run in runs:
                message = _find_run_refusal(run, source, command, base_cwd, root)
                if message is not None:
                    return message
            if _find_deletes(words) and not (
                source and _source_is_shown(source, _command_base(command, base_cwd), root)
            ):
                return _LIST_MESSAGE  # `find . -delete` removes whatever it visits, and its folders are not fixed
    return None


# The find primaries whose next word is a pattern or a name, not an action (`-name -delete`).
_FIND_VALUE_PRIMARIES = frozenset({
    "-name", "-iname", "-path", "-ipath", "-wholename", "-iwholename", "-regex", "-iregex", "-lname", "-ilname",
    "-newer", "-user", "-group", "-type", "-xtype", "-perm", "-size", "-links", "-inum", "-samefile",
})


def _find_deletes(words: list[str]) -> bool:
    """True when the words of a `find` stage hold the `-delete` action."""
    return any(word == "-delete" and words[index - 1] not in _FIND_VALUE_PRIMARIES for index, word in enumerate(words) if index)


# The literal values a command binds shell names to, read for a target made of a variable. A value is one
# unquoted word, a single-quoted text or a double-quoted text with no expansion in it; a binding is an
# assignment-only command (`f=a g=b/c; ...`, optionally behind `export`, `local`, `declare`, `typeset` or
# `readonly` with plain flags `-r -x -g`). A prefix assignment of a command (`g=x cmd $g`) binds nothing the
# command sees (bash expands `$g` first). A name assigned more than once, or any other way, stays unknown.
# This is a copy of the reader in write_scope.py; each check keeps its own.
# Limit: the assignment is read wherever it stands in the text, so one that bash does not run before the write
# (inside `( ... )`, in a later pipeline stage, in a branch that does not run, after `unset`, in a heredoc body
# or a quoted string, `local` outside a function, a name only a child `bash -c` sees, a quoted `'$f'` or `\$f`
# target, a non-ASCII name) can be taken as the value: a possible false block on a constructed command. The
# write-guard also lets a target pass on that reading (_judge_target), only for an assignment that stands before
# the first use of its name, and only for a value bash leaves alone (no white space, no `*`, `?`, `[`; never the
# names PWD and OLDPWD, which `cd` resets). Further classes of that limit, all constructed commands and not
# accidental ones: an assignment bash does not run before the write, an `unset` between the assignment and the
# write, an assignment in a heredoc body or a quoted string, a function body that is never called, a name that is
# not exported and is used inside the text of a child shell (`bash -c`, a quoted heredoc fed to a shell), and a
# rebinding the count does not see (`printf -v`, `eval "..."`, `source`).
_LITERAL_VALUE = r"""(?:"[^"$`\\\n]*"|'[^'\n]*'|[\w./:+@%-]+)"""
_ASSIGN_WORD = rf"[A-Za-z_]\w*={_LITERAL_VALUE}"
_ASSIGNMENT_COMMAND_RE = re.compile(
    rf"""(?:^|[;&|\n])[ \t]*((?:(?:export|local|declare|typeset|readonly)[ \t]+(?:-[rxg]+[ \t]+)*)?{_ASSIGN_WORD}(?:[ \t]+{_ASSIGN_WORD})*)(?=[ \t]*(?:&&|\|\||;|\n|$))"""
)
_ASSIGN_PART_RE = re.compile(rf"(?:^|[ \t])([A-Za-z_]\w*)=({_LITERAL_VALUE})(?=[ \t]|$)")
_NAME_ASSIGNED_RE = re.compile(r"(?:^|[;&|(\n\s])(?:export[ \t]+)?([A-Za-z_]\w*)\+?=")
_NAME_LOOP_RE = re.compile(r"\b(?:for|select)[ \t]+([A-Za-z_]\w*)")
_NAME_READ_RE = re.compile(r"\b(?:read|getopts|mapfile|readarray)\b([^;&|\n]*)")
_NAME_DECLARED_RE = re.compile(r"\b(?:local|declare|typeset|readonly)\b([^;&|\n]*)")
_PLAIN_FLAG_RE = re.compile(r"-[rxg]+")
_VARIABLE_USE_RE = re.compile(r"\$(?:([A-Za-z_]\w*)|\{([A-Za-z_]\w*)\})")


def _assigned_literals(command: str) -> dict[str, str]:
    """Every shell name `command` assigns exactly once, as a literal binding, mapped to its value. A name
    assigned more than once, also with literals only, or any other way (from a substitution, with `+=`, as a
    prefix of a command, by `read` or `mapfile`, as a loop variable, declared with another flag or without a
    value) is not in the result: it is not known what it holds. The assignment is read wherever it stands in the
    text (see the limit above): one bash does not run before the write can be taken as the value."""
    counts: dict[str, int] = {}
    for match in _NAME_ASSIGNED_RE.finditer(command):
        counts[match.group(1)] = counts.get(match.group(1), 0) + 1
    for match in _NAME_LOOP_RE.finditer(command):
        counts[match.group(1)] = counts.get(match.group(1), 0) + 2
    for match in _NAME_READ_RE.finditer(command):
        for name in re.findall(r"[A-Za-z_]\w*", match.group(1)):
            counts[name] = counts.get(name, 0) + 2
    for match in _NAME_DECLARED_RE.finditer(command):
        words = match.group(1).split()
        plain_flags = all(_PLAIN_FLAG_RE.fullmatch(word) for word in words if word.startswith("-"))
        for word in (word for word in words if not word.startswith("-")):
            parsed = re.match(r"([A-Za-z_]\w*)=(.*)$", word)
            if plain_flags and parsed is not None and re.fullmatch(_LITERAL_VALUE, parsed.group(2)):
                continue  # a literal binding, counted by _NAME_ASSIGNED_RE
            for name in re.findall(r"[A-Za-z_]\w*", word):
                counts[name] = counts.get(name, 0) + 2
    values: dict[str, str] = {}
    for command_match in _ASSIGNMENT_COMMAND_RE.finditer(command):
        for part in _ASSIGN_PART_RE.finditer(command_match.group(1)):
            if counts.get(part.group(1)) == 1:
                value = part.group(2)
                values[part.group(1)] = value[1:-1] if value[:1] in ("'", '"') else value
    return values


def _assigned_text(raw: str, command: str) -> Optional[str]:
    """The text of the target `raw` with each variable that `command` assigns exactly once, as a simple literal,
    replaced by its value. None where nothing is replaced: no variable, or none of them a literal binding."""
    if "$" not in raw or not command:
        return None
    values = _assigned_literals(command)

    def value_of(match: "re.Match[str]") -> str:
        return values.get(match.group(1) or match.group(2), match.group(0))

    text = _VARIABLE_USE_RE.sub(value_of, str(raw))
    return text if text != raw else None


def _assigned_value_refusal(
    raw: str, base: Optional[str], root: Optional[Path], command: str,
) -> Optional[str]:
    """The refusal message when a variable of the target `raw` is assigned once, as a literal, in `command` and
    the resulting target is a write to `.act/` (`f=.act/x && echo y > $f`): it is judged as a target written
    out. This is the refusal-only reading, used where the assignment does not stand before the first use of the
    name (`cp a $f/.act/x; f=...`, _assigned_before_use): a value that gives no such verdict, and a variable
    the command does not bind to one literal, change nothing - the target is judged as it stands."""
    text = _assigned_text(raw, command)
    if text is None:
        return None
    message = _judge_text(text, base, root, command, None)
    if message in (*_PATH_MESSAGES, _ROOT_REMOVAL_MESSAGE):
        return _read_as(message, raw, text)
    return None


def _assigned_before_use(raw: str, command: str) -> bool:
    """True when each literal binding that the target `raw` names stands in `command` before the first use of its
    name (`$NAME` or `${NAME}`): bash then runs the assignment first, so the value is what the write sees. A
    value with white space or one of `*`, `?`, `[` (bash splits or expands it) and the names `PWD` and `OLDPWD`
    (bash resets them on `cd`) never count."""
    values = _assigned_literals(command)
    names = {m.group(1) or m.group(2) for m in _VARIABLE_USE_RE.finditer(str(raw))} & set(values)
    for name in names:
        if name in ("PWD", "OLDPWD") or re.search(r"[\s*?\[]", values[name]):
            return False
        assigned = next((m.end() for m in _NAME_ASSIGNED_RE.finditer(command) if m.group(1) == name), None)
        used = next((m.start() for m in _VARIABLE_USE_RE.finditer(command) if (m.group(1) or m.group(2)) == name), None)
        if assigned is None or used is None or assigned > used:
            return False
    return True


def _read_as(message: str, raw: str, text: str) -> str:
    """`message` with the note that the target `raw` was read as `text`, for a refusal that comes from the value
    of a variable; any other message stays as it is."""
    if message in (*_PATH_MESSAGES, _ROOT_REMOVAL_MESSAGE):
        return f"{message} (the target `{raw}` was read as `{text}`: the command assigns that value to the name)"
    return message


def _judge_target(
    raw: str, base: Optional[str], root: Optional[Path], command: str, facts: Optional[Callable[[], ShellFacts]],
) -> Optional[str]:
    """The refusal message for one write target of `command` (raw text, the directory it is relative to), or
    None. `facts` reads the loop and `read` variables of the command (list_feeds.shell_facts) when asked for.
    A variable the command assigns exactly once, as a literal, before its first use counts as written out: the
    target is judged only as the text with the values in place (_assigned_text), with the same `base`, `root`
    and `facts`, and that verdict stands, refusing (with the note of what it was read as) or passing
    (`T=<throwaway copy>; cp a $T/.act/x`). Where an assignment does not stand before the first use, the value
    only refuses (_assigned_value_refusal) and the raw target is judged as it stands. Limit for the pass
    direction, all constructed commands and not accidental ones: an assignment that bash does not run before the
    write (inside `( ... )`, a later pipeline stage, a branch that does not run), an `unset` between the
    assignment and the write, an assignment in a heredoc body or a quoted string, a function body that is never
    called, a name that is not exported and is used inside the text of a child shell (`bash -c`, a quoted
    heredoc fed to a shell), a rebinding the count does not see (`printf -v`, `eval "..."`, `source`). A value
    with white space or a glob character, and the names PWD and OLDPWD, never count (_assigned_before_use)."""
    if _is_unplaced_target(raw):
        return _unplaced_message(raw)
    text = _assigned_text(raw, command)
    if text is not None and _assigned_before_use(raw, command):
        message = _judge_text(text, base, root, command, facts)
        return _read_as(message, raw, text) if message is not None else None
    message = _assigned_value_refusal(raw, base, root, command)
    if message is not None:
        return message
    return _judge_text(raw, base, root, command, facts)


def _judge_text(
    raw: str, base: Optional[str], root: Optional[Path], command: str, facts: Optional[Callable[[], ShellFacts]],
) -> Optional[str]:
    """The verdict on the target text `raw` as it stands (no variable of the command is replaced here):
    _UNKNOWN_FOLDER_MESSAGE when it names .act/ but its folder is not known (base unknown, a dynamic target, no
    project root), _WRITE_GUARD_MESSAGE when it resolves into the project's own .act/, _LIST_MESSAGE for a list
    that is not shown, None when it passes."""
    if base is None or _is_dynamic_target(raw) or root is None:
        if _names_protected_path(raw, root):
            return _unknown_message(raw)
        if not _list_is_shown(raw, command, base, root):
            return _LIST_MESSAGE
        return _bound_refusal(raw, facts().bindings, base, root) if facts and _BOUND_VARIABLE_RE.search(raw) else None
    resolved = _resolve_path(raw, base)
    if resolved is None:
        return _WRITE_GUARD_MESSAGE  # cannot place it — fail closed, see the module docstring
    if _removes_root(resolved, root):
        return _ROOT_REMOVAL_MESSAGE
    return _resolved_message(resolved, root)


def _bound_refusal(
    raw: str, bindings: dict[str, list[Binding]], base: Optional[str], root: Optional[Path],
) -> Optional[str]:
    """The refusal message when the dynamic target `raw` names a loop or `read` variable fed by a list that
    names `.act` or whose source is not shown (_source_is_shown); a variable nothing in the command fills is
    unknown and passes as before."""
    for match in _BOUND_VARIABLE_RE.finditer(raw):
        for binding in bindings.get(match.group(1) or match.group(2), ()):
            message = _binding_refusal(binding, base, root)
            if message is not None:
                return message
    return None


def _binding_refusal(binding: Binding, base: Optional[str], root: Optional[Path]) -> Optional[str]:
    """The refusal message for one list (list_feeds.Binding): it names `.act` or may match it, or something in it
    cannot be shown (_source_is_shown); None when it is shown. A scalar variable (`LIST=$(...)`) is a list only
    through the sources that list files (list_feeds.lists_files) and is judged by those alone: with none of them it is
    no list and passes, whatever its text names - the test comes before `names_act` and `unshown` are read."""
    sources = [source for source in binding.sources if lists_files(source)] if binding.scalar else binding.sources
    if binding.scalar and not sources:
        return None
    if binding.names_act:
        return _WRITE_GUARD_MESSAGE
    if binding.unshown or not all(_source_is_shown(source, base, root) for source in sources):
        return _LIST_MESSAGE
    return None


# A `-C` callback that is nothing but a variable or a substitution (`"$cb"`, `$(cmd)`): the command is unknown.
_BARE_CALLBACK_RE = re.compile(r"\$\{?\w+\}?|\$\(.*\)|`[^`]*`", re.DOTALL)


def _callback_refusal(
    callback: str, binding: Binding, command: str, base_cwd: str, root: Optional[Path],
) -> Optional[str]:
    """The refusal message for the `-C` callback of a `mapfile`/`readarray` (list_feeds.ShellFacts.callbacks): bash runs
    it per quantum with the array index and the line appended, so it is read like a `find -exec` command on a hit
    (_find_run_refusal), the line being the hit and the list `binding` that feeds the mapfile standing for the
    source; a callback that is a shell (`sh -c '... "$2"' _`) is read like `find -exec sh -c '...' _ {}`, a `$`
    or backtick inside it is part of its text. A value that is only a variable or a substitution is an unknown
    command, as `find -exec` treats one; so is an empty one."""
    if not callback.strip() or _BARE_CALLBACK_RE.fullmatch(callback.strip()):
        return None
    text = f"{callback} 0 {FIND_HIT}"
    words = callback.split()
    is_shell = os.path.basename(words[0]).lower() in ("sh", "bash", "zsh", "dash", "ksh")
    base = _command_base(command, base_cwd)
    for raw, where in Parse("Bash", text).bash_write_targets(base, _GIT_WRITES_TEMPLATE_GUARD):
        message = _judge_target(raw, where, root, text, None)
        if message is not None:
            return message
        if FIND_HIT in raw or (is_shell and _is_dynamic_target(raw)):
            message = _binding_refusal(binding, where, root)
            if message is not None:
                return message
    return None


def _find_run_refusal(
    run: list[str], source: Optional[str], command: str, base_cwd: str, root: Optional[Path],
) -> Optional[str]:
    """The refusal message for a command line `find` runs on every hit (`run`, the hit written FIND_HIT; list_feeds.
    find_hits) when a write target of it is under .act, or is made of the hit while `source` (`find <folders>`)
    is not shown. A target of a shell the hit is handed to (`sh -c '... "$1"' _ {}`) counts as made of the hit."""
    text = " ".join(shlex.quote(word) for word in run)
    is_shell = os.path.basename(run[0]).lower() in ("sh", "bash", "zsh", "dash", "ksh")
    base = _command_base(command, base_cwd)  # a `cd` moves where `find` reads from
    for raw, where in Parse("Bash", text).bash_write_targets(base, _GIT_WRITES_TEMPLATE_GUARD):
        message = _judge_target(raw, where, root, text, None)
        if message is not None:
            return message
        listed = FIND_HIT in raw or (is_shell and _is_dynamic_target(raw))
        if listed and not (source and _source_is_shown(source, where, root)):
            return _LIST_MESSAGE
    return None


_WRITE_GUARD_MESSAGE = (
    "[act] .act/ belongs to the template and is replaced on update. Put your version in "
    "docs/ai/local/<same path> — it wins over the template."
)
_UNKNOWN_FOLDER_MESSAGE = (
    "[act] write-guard refused -- the target names .act/ but its folder is not known (a variable, a substitution, "
    "or a relative path after cd to a variable), so it may be this project's own .act/ (the template's files, "
    "replaced on update). A throwaway copy under .act-local/tmp/ passes when the command shows the place: write "
    "the path out (cp a .act-local/tmp/<task>/tpl/.act/x), or set the variable once to a literal before its first "
    "use (T=.act-local/tmp/<task>/tpl; cp a $T/.act/x), and cd only to a folder written out. A change to this "
    "project's own .act/ goes to docs/ai/local/<same path>. Never route the write through a script file or an "
    "interpreter instead."
)
_ROOT_REMOVAL_MESSAGE = (
    "[act] this removes the project root or a folder that holds it, the template's .act/ included. "
    "Remove only the folder below the project you mean."
)
_PACKAGES_MESSAGE = (
    "[act] .act-local/packages/ holds the packages of this project, and the lock records them: a file written there "
    "by hand is not what the lock names. Change it through `python .act/scripts/packages.py` (fetch, add, remove); "
    "that run is no write this check sees. A throwaway copy under .act-local/tmp/ is free."
)
_UNKNOWN_PACKAGES_MESSAGE = (
    "[act] write-guard refused -- the target names .act-local/packages/ but its folder is not known (a variable, a "
    "substitution, or a relative path after cd to a variable), so it may be this project's own packages folder. A "
    "throwaway copy under .act-local/tmp/ passes when the command shows the place: write the path out, or set the "
    "variable once to a literal before its first use, and cd only to a folder written out. Change the packages of "
    "this project through `python .act/scripts/packages.py` (fetch, add, remove)."
)
_LOCAL_MESSAGE = (
    "[act] .act-local is the folder that holds this project's packages (.act-local/packages/) and its local state: "
    "moving, renaming or removing it as a whole is refused, like the same for .act/. Work inside it (move or remove a "
    "folder below it, such as .act-local/tmp/<task>/); the packages change through "
    "`python .act/scripts/packages.py` (fetch, add, remove)."
)
# What a refusal of this check can be: the `message in (...)` and `startswith` tests read this one list.
_PATH_MESSAGES = (
    _WRITE_GUARD_MESSAGE, _UNKNOWN_FOLDER_MESSAGE, _PACKAGES_MESSAGE, _UNKNOWN_PACKAGES_MESSAGE, _LOCAL_MESSAGE)


def _packages_only(text: str) -> bool:
    """True when the target text names `.act-local/packages/` and no `.act/`: the message then speaks of packages."""
    return bool(_PACKAGES_PATH_RE.search(text)) and not _ACT_PATH_RE.search(text)


def _local_only(text: str) -> bool:
    """True when the target text ends in `.act-local` itself and names no `.act/` and no packages folder."""
    return bool(_LOCAL_ITSELF_RE.search(text)) and not _ACT_PATH_RE.search(text) and not _PACKAGES_PATH_RE.search(text)


def _text_message(text: str) -> str:
    """The refusal for a target `text` that names a protected path (_names_protected_path) and cannot be placed."""
    if _local_only(text):
        return _LOCAL_MESSAGE
    return _PACKAGES_MESSAGE if _packages_only(text) else _WRITE_GUARD_MESSAGE


def _unknown_message(text: str) -> str:
    """The refusal for a target `text` that names a protected path whose folder is not known."""
    if _local_only(text):
        return _LOCAL_MESSAGE
    return _UNKNOWN_PACKAGES_MESSAGE if _packages_only(text) else _UNKNOWN_FOLDER_MESSAGE


def _resolved_message(resolved: Path, root: Path) -> Optional[str]:
    """The refusal for a target that resolves to `resolved` in the project `root`: into `.act/`, into
    `.act-local/packages/`, onto `.act-local` itself, or None."""
    if _is_under_project_act(resolved, root):
        return _WRITE_GUARD_MESSAGE
    if _is_under_packages(resolved, root):
        return _PACKAGES_MESSAGE
    return _LOCAL_MESSAGE if _is_local_itself(resolved, root) else None


# --- a copy INTO `.act-local` is no write to `.act-local` as a whole ---------------------------------------------
# The scanners list every operand a command writes to, the folder a copy fills as well as the folder a `mv` or an
# `rm` takes away, and do not say which is which. A target that is `.act-local` itself passes only when each
# command that yields it places files INTO it: `cp`, `mv`, `install` (last operand or `-t`), `rsync`, `robocopy`
# (destination) and PowerShell's `Copy-Item`, `Move-Item`, `Expand-Archive` (-Destination/-DestinationPath or the
# second operand). Anything else stays refused: the folder as the thing moved, renamed, removed, made (`mkdir`),
# written by a redirect or inline code, a copy with `-T`, a sync that deletes (`rsync --delete*`, `robocopy /MIR`,
# `/PURGE`), a command behind a wrapper (`sudo`, `xargs`, `bash -c`), and every form the reading below cannot place.
_DESTINATION_WRITERS = frozenset({"cp", "mv", "install", "rsync", "robocopy"})
_RSYNC_DELETES_RE = re.compile(r"--del(?!a)")  # --delete, --delete-after, --del ...; not --delay-updates
_ROBOCOPY_DELETES = ("/MIR", "/PURGE")
_DESTINATION_PLACEHOLDER = "z2c-destination-placeholder"


def _indexed_operands(args: list[str], value_flags: frozenset) -> tuple[list[int], dict[str, list[tuple[int, str]]]]:
    """shell_targets._operands with positions: (the indexes of the operands, flag -> [(index of the word that
    holds the value, the text in front of the value inside that word)]), for `-t DIR`, `--target-directory=DIR`
    and `-tDIR`."""
    operands: list[int] = []
    values: dict[str, list[tuple[int, str]]] = {}
    index = 0
    options_done = False
    while index < len(args):
        arg = args[index]
        here = index
        index += 1
        if options_done or arg == "-" or not arg.startswith("-"):
            operands.append(here)
        elif arg == "--":
            options_done = True
        elif arg.startswith("--") and "=" in arg:
            name = arg.split("=", 1)[0]
            if name in value_flags:
                values.setdefault(name, []).append((here, name + "="))
        elif arg in value_flags:
            if index < len(args):
                values.setdefault(arg, []).append((index, ""))
                index += 1
        elif not arg.startswith("--") and len(arg) > 2 and arg[:2] in value_flags:
            values.setdefault(arg[:2], []).append((here, arg[:2]))
    return operands, values


def _destination_slots(name: str, args: list[str]) -> Optional[list[tuple[int, str]]]:
    """Where the command `name` with the arguments `args` takes the folder it places files into, as (index in
    `args`, text in front of the folder inside that word); None when the command is no plain copy into a folder
    (`-T`, `install -d`, a sync that deletes there, no destination to be read)."""
    if name in ("cp", "mv", "install"):
        for arg in args:
            if arg == "--":
                break
            cluster = arg.startswith("-") and not arg.startswith("--")
            if arg == "--no-target-directory" or (cluster and "T" in arg[1:]):
                return None
            if name == "install" and (arg == "--directory" or (cluster and "d" in arg[1:])):
                return None
        operands, values = _indexed_operands(args, _VALUE_FLAGS[name])
        explicit = values.get("-t", []) + values.get("--target-directory", [])
        if explicit:
            return explicit
        return [(operands[-1], "")] if len(operands) >= 2 else None
    if name == "rsync":
        if any(_RSYNC_DELETES_RE.match(arg) for arg in args):
            return None
        operands, _ = _indexed_operands(args, _VALUE_FLAGS["rsync"])
        return [(operands[-1], "")] if len(operands) >= 2 else None
    if name == "robocopy":
        if any(arg.upper().startswith(_ROBOCOPY_DELETES) for arg in args):
            return None
        positional = [index for index, arg in enumerate(args) if not _WINDOWS_SWITCH_RE.match(arg)]
        return [(positional[1], "")] if len(positional) >= 2 else None
    return None


def _yields_target(words: list, bases: frozenset, raw: str) -> bool:
    """True when the simple command `words` yields `raw` as a write target (the scanner's own reading of it)."""
    found, _ = _simple_command_targets(words, bases, _GIT_WRITES_TEMPLATE_GUARD, 0)
    return any(str(target) == raw for target, _base in found)


def _local_destination_only(raw: str, base: Optional[str], command: str, parse: Parse) -> bool:
    """True when the write target `raw` (resolved against `base`), which names `.act-local` itself, is only the
    folder that copies of the Bash `command` place files into (see the section comment). Each simple command
    that yields `raw` must be such a copy with `raw` as its destination, and the same command with the
    destination word replaced must not yield `raw` any more (a source, a log file or a second operand would).
    A redirect or inline code that names `raw`, or no command that yields it at all, is no copy: False. Any
    error of the reading is False, the refusing side."""
    try:
        if mentions_interpreter(command) or raw in _raw_redirect_targets(command):
            return False
        bases = frozenset({base})
        explained = False
        for words, _separator in parse.words():
            words = list(words)
            if not _yields_target(words, bases, raw):
                continue
            start = 0
            while start < len(words) and (_ASSIGNMENT_RE.match(words[start]) or words[start] in _RESERVED_PREFIXES):
                start += 1
            if start >= len(words) or getattr(words[start], "subs", ()):
                return False
            name = _command_name(words[start])
            args = [str(word) for word in words[start + 1:]]
            slots = _destination_slots(name, args) if name in _DESTINATION_WRITERS else None
            if not slots or not any(args[index][len(prefix):] == raw for index, prefix in slots):
                return False
            replaced = list(words)
            for index, prefix in slots:
                replaced[start + 1 + index] = prefix + _DESTINATION_PLACEHOLDER
            if _yields_target(replaced, bases, raw):
                return False
            explained = True
        return explained
    except Exception:  # noqa: BLE001 - what cannot be read is refused, like a target that cannot be placed
        return False


# PowerShell: the cmdlets that copy, move or unpack into a folder, the parameters they read, and what is only read.
_PS_COPY_NAMES = frozenset({
    "copy-item", "cpi", "copy", "cp", "move-item", "mi", "move", "mv", "expand-archive"})
_PS_VALUE_PARAMS = ("path", "literalpath", "destination", "destinationpath")
_PS_SWITCH_PARAMS = ("recurse", "force", "passthru", "container", "whatif", "confirm", "usetransaction")
_PS_LOCATION_NAMES = frozenset({
    "set-location", "sl", "cd", "chdir", "push-location", "pushd", "pop-location", "popd"})
_PS_READ_NAMES = frozenset({
    "get-childitem", "gci", "ls", "dir", "get-content", "gc", "cat", "type", "get-item", "gi", "test-path",
    "select-string", "sls", "write-output", "echo", "write-host", "get-location", "pwd", "measure-object"})


def _ps_copy_words(args: list[str]) -> Optional[tuple[list[str], list[str]]]:
    """(the words that are sources, the words that are the destination) of the arguments of a PowerShell copy,
    move or unpack: `-Path`/`-LiteralPath`/`-Destination`/`-DestinationPath` by their name (a shortened name is
    read when it stands for one of them only, `-Name:value` too), else the first operand is the source and the
    second the destination. None for a parameter that is none of these and no known switch."""
    operands: list[str] = []
    named: dict[str, str] = {}
    index = 0
    while index < len(args):
        arg = args[index]
        index += 1
        if arg.startswith("-") and len(arg) > 1 and arg[1].isalpha():
            body, colon, inline = arg[1:].partition(":")
            low = body.lower()
            values = {"destination" if item.startswith("destination") else item
                      for item in _PS_VALUE_PARAMS if item.startswith(low)}
            switches = [item for item in _PS_SWITCH_PARAMS if item.startswith(low)]
            if switches and not values:
                continue
            if len(values) != 1 or switches:
                return None
            slot = next(iter(values))
            if colon:
                named[slot] = inline
            elif index < len(args):
                named[slot] = args[index]
                index += 1
        else:
            operands.append(arg)
    spare = iter(operands)
    source = named.get("path") or named.get("literalpath")
    destination = named.get("destination")
    if source is None:
        source = next(spare, None)
    if destination is None:
        destination = next(spare, None)
    if source is None or destination is None:
        return None
    return [source, *spare], [destination]


_PS_PARAM_PREFIX_RE = re.compile(r"^-[A-Za-z]+:")


def _ps_names_local(word: str, base_cwd: str, root: Path) -> bool:
    """True when the PowerShell word (a list `a,b` word by word, a `-Name:value` by its value) resolves to the
    `.act-local` folder itself, or cannot be placed (a variable, a wildcard) and ends in `.act-local`."""
    for part in _PS_PARAM_PREFIX_RE.sub("", word.strip().strip("'\"")).split(","):
        part = part.strip().strip("'\"")
        if not part or part.startswith("-"):
            continue
        if _is_dynamic_target(part):
            if _LOCAL_ITSELF_RE.search(part):
                return True
            continue
        resolved = _resolve_path(part, base_cwd)
        if resolved is None or _is_local_itself(resolved, root):
            return True
    return False


def _ps_local_destination_only(parse: Parse, base_cwd: str, root: Path) -> bool:
    """True when no PowerShell command of the call names `.act-local` itself other than as the folder a
    `Copy-Item`, `Move-Item` or `Expand-Archive` places files into (see the section comment), and at least one
    does. A location change, a redirect that names it, a source that names it and any other command that has a
    word naming it (`Remove-Item`, `Rename-Item`, `New-Item`, `Set-Content` ...) make it False; a command that
    only reads (`Get-ChildItem`) does not. Any error of the reading is False, the refusing side."""
    try:
        if any(_ps_names_local(text, base_cwd, root) for text in parse.ps_raw_redirects()):
            return False
        explained = False
        for item in parse.ps_words():
            name, args = str(item[0]), [str(word) for word in item[1:]]
            low = name.lower()
            if low in _PS_LOCATION_NAMES:
                return False
            if low in _PS_READ_NAMES:
                continue
            if low in _PS_COPY_NAMES:
                split = _ps_copy_words(args)
                if split is None:
                    return False
                sources, destinations = split
                if any(_ps_names_local(word, base_cwd, root) for word in sources):
                    return False
                explained = explained or any(_ps_names_local(word, base_cwd, root) for word in destinations)
                continue
            if any(_ps_names_local(word, base_cwd, root) for word in (name, *args)):
                return False
        return explained
    except Exception:  # noqa: BLE001 - what cannot be read is refused, like a target that cannot be placed
        return False


def _unplaced_message(target: str) -> str:
    """The refusal of a command whose write the scanner could not place (common._unplaced_target): the
    reason the target carries, and the way out."""
    return (
        "[act] write-guard refused -- the command could not be checked to the end: "
        f"{_unplaced_reason(target)}, so where it writes is unknown and .act/ (the template's own files) "
        "may be among it. Split it into shorter commands, or write the path out in the code as a literal."
    )


def _powershell_targets_protected_path(
    command: str, base_cwd: str, root: Optional[Path], parse: Optional[Parse] = None,
) -> Optional[str]:
    """The message to refuse a PowerShell command with, or None when it passes. _WRITE_GUARD_MESSAGE when
    it writes to a path under `root`'s own .act/ — same judgment as _bash_targets_protected_path, via
    Parse.write_targets with `broad=True` (only git mv/rm count,
    _GIT_WRITES_TEMPLATE_GUARD, same split as the Bash side; `broad` is check 1's own deliberately
    over-inclusive extra pass, see that module's docstring). None back from that scanner
    (Invoke-Expression/iex, an unterminated quote/here-string) denies outright if .act/ is mentioned
    anywhere in the raw command text — "when in doubt, deny" (2026-09-23 review, BLOCK): unlike check 1c's
    own None fallback (_ps_raw_redirect_targets, the same operator-based approximation Bash's own scanner
    falls back to), check 1 cannot afford to miss a write it could not parse, since a false allow here
    survives until the next template update silently overwrites it. The one target that scanner hands
    back for a write it could not place (powershell_targets._is_unplaced_target: a relative write behind
    more directory changes than it tracks, a command larger than its budget) refuses with _unplaced_message
    — where that write lands is unknown, so it is never resolved against `base_cwd` like a plain relative
    name. A *determinable* target (already resolved to an absolute path by the scanner) is checked against
    `root`'s own .act/ only, same as the Bash side. `parse` is the dispatcher's reading of `command`; without
    it the command is read here."""
    if parse is None:
        parse = Parse("PowerShell", command)
    targets = parse.write_targets(base_cwd, _GIT_WRITES_TEMPLATE_GUARD, broad=True)
    if targets is None:
        return _text_message(command) if _PROTECTED_PATH_RE.search(command) else None
    for target in targets:
        if _is_unplaced_target(target):
            return _unplaced_message(target)
    for target in targets:
        if _is_dynamic_target(target) or root is None:
            if _names_protected_path(target, root):
                return _text_message(target)
            continue
        resolved = _resolve_path(target, base_cwd)
        if resolved is None:
            return _WRITE_GUARD_MESSAGE  # cannot place it — fail closed, see the module docstring
        if _removes_root(resolved, root):
            return _ROOT_REMOVAL_MESSAGE
        message = _resolved_message(resolved, root)
        if message == _LOCAL_MESSAGE and _ps_local_destination_only(parse, base_cwd, root):
            continue  # a copy INTO `.act-local` is no write to `.act-local` as a whole
        if message is not None:
            return message
    return _ps_list_refusal(command, base_cwd, root)


def _inside_project(base: Optional[str], root: Optional[Path]) -> bool:
    """True when the directory `base` is known, lies in the project `root` (the root itself or below) and is not
    inside `.act`: a name-only wildcard listed there names no file of `.act` (a parent of the root would list the
    project folder itself)."""
    if base is None or root is None:
        return False
    resolved = _resolve_path(base)
    if resolved is None:
        return False
    top = _folded(_resolve_path(str(root)) or root)
    inside = _folded(resolved) == top or top in _folded(resolved).parents
    return inside and not _is_under_project_act(resolved, root) and not _is_under_packages(resolved, root)


def _item_target_refusal(target: str, base: Optional[str], root: Optional[Path], removed: bool = True) -> Optional[str]:
    """The refusal message for the file or folder `target` an item object made in place names (`[IO.FileInfo]::new(x)`
    followed by a method that writes), or - with `removed` False - a place a method of an item writes to (the
    argument of `MoveTo`, `CopyTo`, `Replace`, which removes nothing at it; the project root and its parents are no
    refusal there, `.Replace('..', '/')` may be a string): judged like a write target of the literal reader - a
    literal against `.act` (and the project root), a text that holds a variable by its own text only; None when it
    passes."""
    if _is_unplaced_target(target):
        return _unplaced_message(target)
    if base is None and not _is_absolute_target(target) or _is_dynamic_target(target) or root is None:
        return _text_message(target) if _names_protected_path(target, root) else None
    resolved = _resolve_path(target, base)
    if resolved is None:
        return _WRITE_GUARD_MESSAGE if removed else None
    if removed and _removes_root(resolved, root):
        return _ROOT_REMOVAL_MESSAGE
    return _resolved_message(resolved, root)


def _ps_list_refusal(command: str, base_cwd: str, root: Optional[Path]) -> Optional[str]:
    """_LIST_MESSAGE when a write or delete cmdlet of the PowerShell `command` takes its item from a list
    (list_feeds.ps_fed_writes: the pipeline, `$_`, a variable a loop or an assignment filled, a sub-expression) that
    a list command of the allow-list does not show: `Get-ChildItem`/`gci`/`ls`/`dir`, `Resolve-Path`, `git ls-files`
    ... must name fixed folders, not the project root, `.act` or no folder at all (_fixed_folder). A single name-only
    wildcard that cannot match `.act` (`Get-Item *.log`) reads the current folder only and passes when that lies
    inside the project and not in `.act` (_inside_project) - list_feeds.ps_fed_writes leaves it out only for a
    command without a location change or a command it does not show, and a write that works on the item itself
    (a link or junction that a wildcard matches by its name and that leads to `.act` is a known limit). The file an
    item object made in place names (`[IO.FileInfo]::new(x).Delete()`) is judged as a write target, and the argument
    of `MoveTo`, `CopyTo` and `Replace` of an item as a place written to (_item_target_refusal). A source that is
    none of those (`Get-Content list.txt`, a literal list) is not judged, as before."""
    fed = ps_fed_writes(command, lambda name, args: _listing_operands([name, *args], True))
    base = _command_base(command, base_cwd)  # a `Set-Location` moves where a lister reads from
    for item in fed or ():
        for operands in item.listers:
            # No folder named: the lister reads the current one (a leading `Set-Location` moved it, _command_base).
            if operands is None or not all(_fixed_folder(operand, base, root) for operand in operands or ["."]):
                return _LIST_MESSAGE
        if item.current_folder and not _inside_project(base, root):
            return _LIST_MESSAGE
        for target in item.item_targets:
            message = _item_target_refusal(target, base, root)
            if message is not None:
                return message
        for target in item.destinations:
            message = _item_target_refusal(target, base, root, removed=False)
            if message is not None:
                return message
    return None


def _targets_protected_path(
    tool_name: str, tool_input: dict, base_cwd: str, root: Optional[Path], payload: Optional[dict] = None,
) -> Optional[str]:
    """The message this tool call is refused with, or None when it passes: _WRITE_GUARD_MESSAGE when it
    writes somewhere under `root`'s own .act/, based on the write-target field(s) that specific tool uses;
    _unplaced_message for a PowerShell write the scanner could not place. Unknown tools never match — this
    guard only needs to understand the tools named in the PreToolUse matcher in settings.hooks.json.
    `base_cwd` is the directory a relative Bash/PowerShell/file-tool target is resolved against
    (the tool's own cwd); `root` is the project whose .act/ this check protects (None when it
    could not be determined, e.g. `base_cwd` sits outside any template-managed project) — see
    _is_under_project_act. `payload` is the hook payload carrying the dispatcher's parse of a shell command;
    without it the command is read here."""
    shared = payload or {"tool_name": tool_name}
    if tool_name == "Bash":
        command = tool_input.get("command")
        if not isinstance(command, str):
            return None
        return _bash_targets_protected_path(command, base_cwd, root, parse_for(shared, command))
    if tool_name == "PowerShell":
        command = tool_input.get("command")
        if not isinstance(command, str):
            return None
        return _powershell_targets_protected_path(command, base_cwd, root, parse_for(shared, command))
    for field in _TOOL_PATH_FIELDS.get(tool_name, ()):
        value = tool_input.get(field)
        if not isinstance(value, str):
            continue
        if root is None:
            if _names_protected_path(value, root):
                return _text_message(value)
            continue
        resolved = _resolve_against(base_cwd, value)
        if resolved is None:
            if _names_protected_path(value, root):
                return _text_message(value)
            continue
        message = _resolved_message(resolved, root)
        if message is not None:
            return message
    return None


def _guard_root() -> Optional[Path]:
    """The project root this check protects — never derived from the tool call's own `cwd`
    (a worker or the running Claude Code session can sit in a sibling project's directory
    while still writing an absolute path into *this* project's `.act/`, and the guard must catch
    that write regardless of where the process happens to be sitting). Preferred order: the
    `CLAUDE_PROJECT_DIR` environment variable Claude Code sets for every hook invocation, when it
    points at a real template-managed project; else the location dispatch.py itself was loaded
    from (`.act/hooks/dispatch.py`'s own directory tells us unambiguously which project's `.act/`
    is running this hook, independent of `cwd`); `cwd` is only the last resort, for a manual
    invocation with neither of those available."""
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_dir:
        candidate = Path(env_dir)
        if (candidate / ".act").is_dir():
            return candidate.resolve()
    dispatch_root = Path(__file__).resolve().parents[3]
    if (dispatch_root / ".act").is_dir():
        return dispatch_root
    return None


def check_write_guard(payload: dict) -> int:
    """Check 1: deny an AI write under <project root>/.act/**, pointing at
    docs/ai/local/<path> instead, and one under <project root>/.act-local/packages/**, pointing at packages.py — never a write outside that root, even one whose path
    happens to contain a `.act/` segment (a sibling checkout's template tree, deliberately
    edited from a template-maintenance project, is not this check's business). See this module's
    docstring for why this check's error handling — fail closed, not open — differs from the rest
    of the checks."""
    config = actlib.read_config()
    mode = _check_mode(config, "template-write-guard", default="block")
    if mode == "off":
        return 0

    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        return 0  # nothing to check a write target against

    cwd_raw = payload.get("cwd")
    base_cwd = cwd_raw if isinstance(cwd_raw, str) and cwd_raw else os.getcwd()
    root = _guard_root()
    if root is None:
        try:
            root = actlib.repo_root(Path(base_cwd))
        except RuntimeError:
            root = None  # base_cwd is not inside any template-managed project either
    message = _targets_protected_path(tool_name, tool_input, base_cwd, root, payload)
    if message is None:
        return 0

    if mode == "warn":
        print(message)
        return 0

    _note_refusal_class("protected-path")
    print(message, file=sys.stderr)
    return 2
