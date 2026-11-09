#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check 1 — template write-guard (PreToolUse), checked before every other check. Denies
#          an AI write under .act/**, pointing at docs/ai/local/<path> instead.
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
from .common import _TOOL_PATH_FIELDS, _check_mode
from .common import _is_unplaced_target, _unplaced_reason
from .list_feeds import FIND_HIT, Binding, ShellFacts, find_hits, ps_fed_writes, shell_facts
from .shell_targets import _GIT_WRITES_TEMPLATE_GUARD, _XARGS_INPUT, _is_absolute_target, _is_dynamic_target
from .shell_targets import _resolve_path

__all__ = [
    "_PROTECTED_PATH_RE", "_names_protected_path", "_WRITE_GUARD_MESSAGE", "_bash_targets_protected_path",
    "_powershell_targets_protected_path", "_unplaced_message", "_targets_protected_path", "_is_under_project_act",
    "_resolve_against", "_guard_root", "check_write_guard",
]

# ".act" as a whole path segment, in any spelling of case (".ACT/x" is the same file as ".act/x" on Windows
# and on macOS, whose file systems do not tell the two apart): ".act/" or ".act\" anywhere in the string, or
# ".act" at the very end — never as a prefix of another name. Deliberately no required prefix character
# before ".act" (a shell command has it after a space, quote, "=", redirect symbol, "(", and
# so on — enumerating all of those is more fragile than just not requiring one). The suffix
# check is what excludes ".act-lock.json" and ".act-local/", both project-level state next to
# the template tree rather than inside it, from this guard.
_PROTECTED_PATH_RE = re.compile(r"\.act(?:[\\/]|$)", re.IGNORECASE)
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
    return not (_is_under_project_act(resolved, root) or _folded(resolved) == top
                or _folded(resolved) in top.parents)


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
    if its own text names .act/ — everything else about it cannot be decided here (a
    *determinable* target is resolved and checked against `root`'s own .act/ only, never against
    the raw text — a sibling checkout's .act/ is not this project's to protect). A dynamic target that is a
    list the scan cannot read (an `xargs` input, a `$(...)` or backtick span) passes only when its source
    names fixed folders (_list_is_shown, an allow-list), else it is refused with _LIST_MESSAGE; so does a
    target made of a loop or `read` variable fed by such a list (_bound_refusal; a literal loop word that names
    `.act` or may match it is refused as a write to `.act`), and a command `find` runs on every hit
    (-exec, -execdir, -ok, -okdir; _find_run_refusal) when its folders are not fixed. A write the scan could
    not place (inline code whose path the text does not show, _is_unplaced_target) is refused as such.
    `parse` is the dispatcher's reading of `command`; without it the command is read here."""
    if parse is None:
        parse = Parse("Bash", command)
    read: list[ShellFacts] = []

    def facts() -> ShellFacts:
        if not read:
            tokens = parse.chain_tokens()
            read.append(shell_facts(tokens) if tokens is not None else ShellFacts())
        return read[0]

    for raw, base in parse.bash_write_targets(base_cwd, _GIT_WRITES_TEMPLATE_GUARD):
        message = _judge_target(raw, base, root, command, facts)
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


def _judge_target(
    raw: str, base: Optional[str], root: Optional[Path], command: str, facts: Optional[Callable[[], ShellFacts]],
) -> Optional[str]:
    """The refusal message for one write target of `command` (raw text, the directory it is relative to), or
    None. `facts` reads the loop and `read` variables of the command (list_feeds.shell_facts) when asked for."""
    if _is_unplaced_target(raw):
        return _unplaced_message(raw)
    if base is None or _is_dynamic_target(raw) or root is None:
        if _names_protected_path(raw, root):
            return _WRITE_GUARD_MESSAGE
        if not _list_is_shown(raw, command, base, root):
            return _LIST_MESSAGE
        return _bound_refusal(raw, facts().bindings, base, root) if facts and _BOUND_VARIABLE_RE.search(raw) else None
    resolved = _resolve_path(raw, base)
    if resolved is None:
        return _WRITE_GUARD_MESSAGE  # cannot place it — fail closed, see the module docstring
    return _WRITE_GUARD_MESSAGE if _is_under_project_act(resolved, root) else None


def _bound_refusal(
    raw: str, bindings: dict[str, list[Binding]], base: Optional[str], root: Optional[Path],
) -> Optional[str]:
    """The refusal message when the dynamic target `raw` names a loop or `read` variable fed by a list that
    names `.act` or whose source is not shown (_source_is_shown); a variable nothing in the command fills is
    unknown and passes as before."""
    for match in _BOUND_VARIABLE_RE.finditer(raw):
        for binding in bindings.get(match.group(1) or match.group(2), ()):
            if binding.names_act:
                return _WRITE_GUARD_MESSAGE
            if binding.unshown or not all(_source_is_shown(source, base, root) for source in binding.sources):
                return _LIST_MESSAGE
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
        return _WRITE_GUARD_MESSAGE if _PROTECTED_PATH_RE.search(command) else None
    for target in targets:
        if _is_unplaced_target(target):
            return _unplaced_message(target)
    for target in targets:
        if _is_dynamic_target(target) or root is None:
            if _names_protected_path(target, root):
                return _WRITE_GUARD_MESSAGE
            continue
        resolved = _resolve_path(target, base_cwd)
        if resolved is None:
            return _WRITE_GUARD_MESSAGE  # cannot place it — fail closed, see the module docstring
        if _is_under_project_act(resolved, root):
            return _WRITE_GUARD_MESSAGE
    return _ps_list_refusal(command, base_cwd, root)


def _ps_list_refusal(command: str, base_cwd: str, root: Optional[Path]) -> Optional[str]:
    """_LIST_MESSAGE when a write or delete cmdlet of the PowerShell `command` takes its item from a list
    (list_feeds.ps_fed_writes: the pipeline, `$_`, a variable a loop or an assignment filled, a sub-expression) that
    a list command of the allow-list does not show: `Get-ChildItem`/`gci`/`ls`/`dir`, `Resolve-Path`, `git ls-files`
    ... must name fixed folders, not the project root, `.act` or no folder at all (_fixed_folder). A source that is
    none of those (`Get-Content list.txt`, a literal list) is not judged, as before."""
    fed = ps_fed_writes(command, lambda name, args: _listing_operands([name, *args], True))
    base = _command_base(command, base_cwd)  # a `Set-Location` moves where a lister reads from
    for item in fed or ():
        for operands in item.listers:
            # No folder named: the lister reads the current one (a leading `Set-Location` moved it, _command_base).
            if operands is None or not all(_fixed_folder(operand, base, root) for operand in operands or ["."]):
                return _LIST_MESSAGE
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
                return _WRITE_GUARD_MESSAGE
            continue
        resolved = _resolve_against(base_cwd, value)
        if resolved is None:
            if _names_protected_path(value, root):
                return _WRITE_GUARD_MESSAGE
            continue
        if _is_under_project_act(resolved, root):
            return _WRITE_GUARD_MESSAGE
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
    docs/ai/local/<path> instead — never a write outside that root, even one whose path
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

    print(message, file=sys.stderr)
    return 2
