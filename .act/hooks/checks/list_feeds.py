#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Readers for write-guard (check 1): where the files a write works on come from when a shell loop or a
#          `find -exec` supplies them. They only read a command and name the sources; write_guard.py decides
#          whether a source is shown (names fixed folders) and refuses otherwise.
#
#          Bash: a loop variable (`for f in <words>`) or a `read` variable fed by a pipe, a process
#          substitution, a here-string or a file is bound to the list that feeds it (shell_facts); the words of a
#          `find` stage give the source (the folders it names) and the commands its `-exec`/`-execdir`/`-ok`/
#          `-okdir` run on every hit (find_hits).
#          PowerShell: a write or delete cmdlet that takes its item from the pipeline, from `$_`, from a
#          variable a loop or an assignment filled, or from a sub-expression, together with the list commands
#          (`Get-ChildItem`, `Resolve-Path`, `git ls-files` ...) that can feed it (ps_fed_writes).
#
# Known limits: a list kept in a variable of a Bash assignment (`files=$(grep -rl x .)`), a function or script
#          body, `sudo -u user find`, a loop over a variable (`for f in $LIST`) and a PowerShell list from a file
#          (`Get-Content list.txt`) are not followed: such a write is judged as before. Variables are bound by
#          name for the whole command, not per loop: a name used by two loops (or a loop and a later assignment)
#          carries the lists of both.

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, field
from typing import Callable, Optional

from .brace_expand import expand_braces
from .command_parse import Parse
from .powershell_targets import _ALIASES, _cmdlet_targets, _ps_command_name, _ps_split_args, _ps_tokens
from .shell_targets import _SEPARATOR_OPS

__all__ = ["Binding", "ShellFacts", "shell_facts", "find_hits", "FIND_HIT", "PsFed", "ps_fed_writes"]

# The word that stands for a `{}` of `find -exec` when the command it runs is read for its write targets.
FIND_HIT = "act-find-hit"
_MAX_DEPTH = 3
_OPENERS = frozenset({"while", "until", "if", "for", "select", "case", "{"})
_CLOSERS = frozenset({"done", "fi", "esac", "}"})
_PREFIXES = frozenset({"do", "then", "else", "elif", "!", "time", "coproc"})
_WRAPPERS = frozenset({"sudo", "env", "nice", "nohup", "command", "builtin", "exec", "time", "stdbuf", "timeout"})
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
_ASSIGNMENT_RE = re.compile(r"\w+=")
# A glob that may match a dot folder (`.a*`, `.[a]ct`, `.ac?`): a segment that starts with a dot and has a glob character.
_DOT_GLOB_RE = re.compile(r"(?:^|[\\/])\.[^\\/]*[*?\[]")
_ACT_RE = re.compile(r"\.act(?:[\\/]|$)", re.IGNORECASE)
_READ_VALUE_OPTIONS = "pdnNtu"


@dataclass
class Binding:
    """What feeds a variable: the command texts of its lists (to be shown), whether a literal word names `.act`
    or may match it, and whether the list is something that cannot be shown (a file)."""

    sources: list[str] = field(default_factory=list)
    names_act: bool = False
    unshown: bool = False


@dataclass
class ShellFacts:
    """What one command text holds: the bindings of its loop and `read` variables, and the word lists of its
    `find` stages (find_hits reads them)."""

    bindings: dict[str, list[Binding]] = field(default_factory=dict)
    finds: list[list[str]] = field(default_factory=list)


@dataclass
class _Frame:
    """An open compound command (`while`, `{`, `(` ...): the stages of the pipe in front of it, and what the
    redirections behind it feed."""

    outer: list[str]  # the stages of the pipe in front of it
    paren: bool = False
    feeds: list[tuple[str, str]] = field(default_factory=list)
    inner: list[str] = field(default_factory=list)  # a subshell: the pipeline texts that ended inside it


def _quote(words: list[str]) -> str:
    return " ".join(shlex.quote(str(word)) for word in words)


def _matching_paren(tokens: list, start: int) -> int:
    """The index of the `)` that closes the `(` at tokens[start]; the last index when it does not close."""
    depth = 0
    for index in range(start, len(tokens)):
        if tokens[index][1] and tokens[index][0] in ("(", ")"):
            depth += 1 if tokens[index][0] == "(" else -1
            if depth == 0:
                return index
    return len(tokens) - 1


def _tokens_text(tokens: list) -> str:
    return " ".join(str(text) if is_op else shlex.quote(str(text)) for text, is_op in tokens)


def _expand_groups(stages: list[str], groups: dict[str, list[str]]) -> list[str]:
    """The pipeline texts a pipe of `stages` stands for: a closed subshell in it (`(a; b) | ...`) is each of the
    pipelines that ran inside it in turn."""
    for position, stage in enumerate(stages):
        if stage in groups:
            return [text for inner in groups[stage]
                    for text in _expand_groups(stages[:position] + [inner] + stages[position + 1:], groups)]
    return [" | ".join(stages)]


def _strip_prefix(words: list[str]) -> list[str]:
    """`words` without leading keywords, variable assignments and wrapper words (`sudo -n`, `time`, `env A=b`)."""
    index = 0
    wrapped = False
    while index < len(words):
        word = words[index]
        if word in _PREFIXES or _ASSIGNMENT_RE.match(word):
            index += 1
        elif os.path.basename(word).lower() in _WRAPPERS:
            wrapped = True
            index += 1
        elif wrapped and (word.startswith("-") or re.fullmatch(r"\d+[smhd]?", word)):
            index += 1
        else:
            break
    return words[index:]


def _loop_binding(items: list[str]) -> Binding:
    binding = Binding()
    for item in items:
        if _ACT_RE.search(item):
            binding.names_act = True
        found = _substitution_texts(item)
        if found is None:
            binding.unshown = True
        elif found:
            binding.sources += found
        elif any(_ACT_RE.search(variant) or _DOT_GLOB_RE.search(variant) for variant in expand_braces(item)):
            binding.names_act = True
    return binding


def _substitution_texts(text: str) -> Optional[list[str]]:
    """The command texts of the `$(...)` and backtick spans of one word; None when one does not end."""
    found: list[str] = []
    index = 0
    while index < len(text):
        if text[index] == "`":
            end = text.find("`", index + 1)
            if end < 0:
                return None
            found.append(text[index + 1:end])
            index = end + 1
        elif text.startswith("$(", index) and not text.startswith("$((", index):
            depth, end = 1, index + 2
            while end < len(text) and depth:
                depth += (text[end] == "(") - (text[end] == ")")
                end += 1
            if depth:
                return None
            found.append(text[index + 2:end - 1])
            index = end
        else:
            index += 1
    return found


def _read_names(args: list[str]) -> list[str]:
    """The variables `read <args>` fills (`REPLY` without a name)."""
    names: list[str] = []
    index = 0
    while index < len(args):
        word = args[index]
        index += 1
        if word.startswith("-") and len(word) > 1:
            for position, letter in enumerate(word[1:], 1):
                if letter in _READ_VALUE_OPTIONS or letter == "a":
                    value = word[position + 1:]
                    if not value and index < len(args):
                        value, index = args[index], index + 1
                    if letter == "a" and value:
                        names.append(value)
                    break
        else:
            names.append(word)
    return names or ["REPLY"]


def shell_facts(tokens: list, _depth: int = 0) -> ShellFacts:
    """The loop and `read` bindings and the `find` stages of the token stream of a Bash command
    (Parse.chain_tokens), a text handed to `sh -c` included."""
    facts = ShellFacts()
    reads: list[tuple[list[str], list[_Frame], list[tuple[str, str]]]] = []
    stage: list[str] = []
    feeds: list[tuple[str, str]] = []  # input redirections of the stage
    pipe: list[str] = []  # the stages of the pipeline so far
    frames: list[_Frame] = []
    closed: Optional[_Frame] = None  # a compound the last `)` closed, for the redirections behind it
    groups: dict[str, list[str]] = {}  # a closed subshell as a pipe stage: its name and the pipelines it ran
    last_group = ""  # the subshell the last `)` closed, for the `|` right behind it

    def finish() -> str:
        """Read the stage that ended; its text for the pipe."""
        nonlocal stage, feeds, pipe
        words = list(stage)
        text = ""
        compound = False
        while words:
            word = words[0]
            if word in _OPENERS:
                frames.append(_Frame(list(pipe)))
                pipe = []
                words = words[1:]
                if word in ("for", "select"):
                    if len(words) >= 3 and words[1] == "in":
                        facts.bindings.setdefault(words[0], []).append(_loop_binding(words[2:]))
                    words = []
                elif word == "case":
                    words = []
            elif word in _CLOSERS:
                if frames:
                    frame = frames.pop()
                    frame.feeds += feeds
                    pipe = frame.outer
                feeds = []
                compound = True
                words = words[1:]
            elif word in _PREFIXES:
                words = words[1:]
            else:
                break
        words = _strip_prefix(words)
        if words:
            name = os.path.basename(words[0]).lower()
            if name == "read":
                reads.append((_read_names(words[1:]), list(frames), list(feeds)))
            elif name == "find":
                facts.finds.append(words)
            elif name in _SHELLS and _depth < _MAX_DEPTH:
                for position, word in enumerate(words[1:], 1):
                    if word.startswith("-") and not word.startswith("--") and "c" in word[1:] and position + 1 < len(words):
                        inner = Parse("Bash", words[position + 1]).chain_tokens()
                        if inner is not None:
                            nested = shell_facts(inner, _depth + 1)
                            for key, values in nested.bindings.items():
                                facts.bindings.setdefault(key, []).extend(values)
                            facts.finds += nested.finds
                        break
            text = _quote(words)
        stage, feeds = [], []
        return "(compound)" if compound else text

    index = 0
    while index <= len(tokens):
        text, is_op = tokens[index] if index < len(tokens) else ("\n", True)
        index += 1
        if not is_op:
            stage.append(str(text))
            closed = None
            continue
        if text not in _SEPARATOR_OPS:  # a redirection
            following = tokens[index] if index < len(tokens) else None
            if text.startswith((">", "&>")) and stage and stage[-1].isdigit():
                stage.pop()  # a glued file descriptor
            if text in ("<", ">") and following == ("(", True):  # `<(cmd)` as an argument
                index = _matching_paren(tokens, index) + 1
                continue
            if text in ("<", "<<<", "<<", "<&", "<>"):
                if text == "<" and following == ("<", True) and index + 1 < len(tokens) and tokens[index + 1] == ("(", True):
                    end = _matching_paren(tokens, index + 1)
                    feed = ("cmd", _tokens_text(tokens[index + 2:end]))
                    index = end + 1
                elif following is not None and not following[1]:
                    feed = ("here" if text == "<<<" else "file", str(following[0]))
                    index += 1
                else:
                    feed = ("file", "")
                if not stage and closed is not None:
                    closed.feeds.append(feed)
                else:
                    feeds.append(feed)
            elif following is not None and not following[1]:
                index += 1  # an output redirection: the scanner reads its target
            continue
        if text == "(" and stage and stage[-1].endswith("$"):  # a command substitution folded into its word
            end = _matching_paren(tokens, index - 1)
            stage[-1] += "(" + _tokens_text(tokens[index:end]) + ")"
            index = end + 1
            continue
        closed = None
        group, last_group = last_group, ""
        stage_text = finish()
        ended = " | ".join(pipe + [stage_text]) if stage_text else " | ".join(pipe)
        if frames and frames[-1].paren and ended and text not in ("|", "|&", "("):
            frames[-1].inner.append(ended)  # a pipeline of a subshell ended
        if text in ("|", "|&"):
            pipe.append(stage_text or group)
        elif text == "(":
            frames.append(_Frame(list(pipe), paren=True))
            pipe = []
        elif text == ")":
            if frames and frames[-1].paren:
                closed = frames.pop()
                pipe = closed.outer
                last_group = f"(group {len(groups)})"
                groups[last_group] = closed.inner or ["(compound)"]
        else:
            pipe = []
    for names, owners, own_feeds in reads:
        sources = own_feeds
        if not sources:
            for frame in reversed(owners):
                if frame.feeds:
                    sources = frame.feeds
                    break
                if frame.outer:
                    sources = [("cmd", text) for text in _expand_groups(frame.outer, groups)]
                    break
        binding = Binding()
        for kind, value in sources:
            if kind == "cmd":
                binding.sources.append(value)
            elif kind == "file":
                binding.unshown = True
            else:
                found = _substitution_texts(value)
                binding.sources += found or []
                binding.unshown = binding.unshown or found is None
                binding.names_act = binding.names_act or bool(_ACT_RE.search(value))
        for name in names:
            facts.bindings.setdefault(name, []).append(binding)
    return facts


def find_hits(words: list[str]) -> tuple[Optional[str], list[list[str]]]:
    """For the words of one `find` stage: the command text that lists what it visits (`find <folders>`, None
    when it names none) and the command lines it runs on every hit, `{}` replaced by FIND_HIT.
    A command line without `{}` is no list and is left out."""
    rest = words[1:]
    operands: list[str] = []
    for word in rest:
        if word.startswith(("-", "!", "(")) and not (word in ("-H", "-L", "-P") and not operands):
            break
        if word not in ("-H", "-L", "-P"):
            operands.append(word)
    source = _quote(["find", *operands]) if operands else None
    runs: list[list[str]] = []
    index = 0
    while index < len(rest):
        word = rest[index]
        index += 1
        if word in ("-exec", "-execdir", "-ok", "-okdir"):
            run: list[str] = []
            while index < len(rest) and rest[index] not in (";", "+"):
                run.append(rest[index])
                index += 1
            index += 1
            if any("{}" in part for part in run):
                runs.append([part.replace("{}", FIND_HIT) for part in run])
    return source, runs


# --- PowerShell -------------------------------------------------------------------------------------------------

_PS_LISTERS = frozenset({"get-childitem", "gci", "ls", "dir", "resolve-path", "rvpa"})
# Switches of the listers, and the options that take a value (their value is no folder).
_PS_LIST_SWITCHES = frozenset({
    "recurse", "r", "force", "file", "directory", "name", "hidden", "readonly", "system", "followsymlink",
    "ad", "af", "ah", "ar", "as", "relative", "usetransaction", "verbose", "erroraction", "ea",
})
_PS_LIST_VALUES = frozenset({"filter", "include", "exclude", "depth", "attributes", "stream", "erroraction", "ea"})
_PS_LIST_PATHS = frozenset({"path", "literalpath", "lp", "pspath"})
# Kinds of write cmdlets (powershell_targets._ALIASES) that act on an item: those whose item can come from the
# pipeline, and those that take a file name only.
_PS_PIPE_FED = frozenset({"path_target", "move", "destination2nd", "all_operands"})
_PS_ITEM_WRITERS = _PS_PIPE_FED | {"outfile", "newitem"}
_PS_PIECE_RE = re.compile(r"(\$\(|@\(|[(){}])")
_PS_BOUNDARIES = frozenset({";", "\n", "&&", "||"})


@dataclass
class PsFed:
    """A write or delete cmdlet of a PowerShell command whose item comes from a list: the lister commands that
    may feed it, each as its operands (the folders it names; None when an option or a form is not understood)."""

    cmdlet: str
    listers: list[Optional[list[str]]]


class _Pieces(list):
    """The pieces of a PowerShell command (kind, text); `glued` holds the indices of those that follow the one before
    without a space (`(Get-ChildItem).FullName`, a name followed by a sub-expression)."""

    glued: set[int]


def _ps_pieces(command: str) -> Optional[_Pieces]:
    """The PowerShell tokens of `command` cut at parentheses and braces: ("word"|"op"|"open"|"close", text)."""
    tokens = _ps_tokens(command)
    if tokens is None:
        return None
    pieces = _Pieces()
    pieces.glued = set()
    for text, is_op in tokens:
        if is_op:
            pieces.append(("op", text))
            continue
        first = True
        for part in _PS_PIECE_RE.split(text):
            if not part:
                continue
            if not first:
                pieces.glued.add(len(pieces))
            first = False
            if part in ("$(", "@(", "(", "{"):
                pieces.append(("open", part))
            elif part in (")", "}"):
                pieces.append(("close", part))
            else:
                pieces.append(("word", part))
    return pieces


def _ps_args(pieces: _Pieces, start: int) -> tuple[list[str], int]:
    """The arguments of the command at pieces[start-1]: words up to an operator or an unmatched closer, a group in
    parentheses or braces joined into one word, pieces glued to each other one word. The index it stops at is the
    second value."""
    args: list[str] = []
    index = start
    while index < len(pieces):
        kind, text = pieces[index]
        if kind == "op" or kind == "close":
            break
        glued = index in pieces.glued and bool(args)
        if kind == "open":
            depth, end, inner = 1, index + 1, []
            while end < len(pieces) and depth:
                inner.append(pieces[end][1])
                depth += (pieces[end][0] == "open") - (pieces[end][0] == "close")
                end += 1
            text += " ".join(inner)
            index = end
        else:
            index += 1
        if glued:
            args[-1] += text
        else:
            args.append(text)
    return args, index


def _ps_lister_operands(args: list[str]) -> Optional[list[str]]:
    """The folders a PowerShell lister reads; [] without one (the current folder); None for an option or form
    that is not understood."""
    operands: list[str] = []
    index = 0
    while index < len(args):
        word = args[index]
        index += 1
        if word.startswith("-") and len(word) > 1:
            flag, _, value = word[1:].partition(":")
            flag = flag.lower()
            if flag in _PS_LIST_PATHS or flag in _PS_LIST_VALUES:
                if not value and index < len(args):
                    value, index = args[index], index + 1
                if flag in _PS_LIST_PATHS:
                    operands.append(value)
            elif flag not in _PS_LIST_SWITCHES:
                return None
        else:
            operands.append(word)
    return [part.strip() for word in operands for part in word.split(",") if part.strip()]


def _starts_command(pieces: _Pieces, index: int) -> bool:
    """True when the word at pieces[index] stands where a command name does: first, behind an operator, an
    opening parenthesis or brace, `&`, `.`, or where a statement takes a value (`in`, `=`)."""
    if index == 0:
        return True
    kind, text = pieces[index - 1]
    return kind in ("op", "open") or text in ("&", ".", "in", "=", "+=")


def _group_end(pieces: _Pieces, start: int) -> int:
    """The index of the closer of the opener at pieces[start]; the last index when it does not close."""
    depth = 0
    for index in range(start, len(pieces)):
        depth += (pieces[index][0] == "open") - (pieces[index][0] == "close")
        if depth == 0:
            return index
    return len(pieces) - 1


def _local_start(pieces: _Pieces, index: int) -> int:
    """Where the statement that holds pieces[index] begins: behind the last `;`, line break, `&&` or `||` on the
    same level before it. A group (`{ }`, `( )`) the scan leaves is not a limit: the statement goes on outside."""
    depth = 0
    for at in range(index - 1, -1, -1):
        kind, text = pieces[at]
        if kind == "close":
            depth += 1
        elif kind == "open" and depth:
            depth -= 1
        elif kind == "op" and text in _PS_BOUNDARIES and depth == 0:
            return at + 1
    return 0


def _local_end(pieces: _Pieces, index: int) -> int:
    """Where the statement that holds pieces[index] ends: at the next boundary or unmatched closer on its level."""
    depth = 0
    for at in range(index, len(pieces)):
        kind, text = pieces[at]
        if kind == "open":
            depth += 1
        elif kind == "close":
            if depth == 0:
                return at
            depth -= 1
        elif kind == "op" and text in _PS_BOUNDARIES and depth == 0:
            return at
    return len(pieces)


def _enclosing_blocks(pieces: _Pieces, index: int) -> list[int]:
    """The indices of the `{` of the script blocks that hold pieces[index], innermost first: `$_` in them is an
    item of the pipeline in front of the block."""
    found: list[int] = []
    depth = 0
    for at in range(index - 1, -1, -1):
        kind, text = pieces[at]
        if kind == "close":
            depth += 1
        elif kind == "open":
            if depth:
                depth -= 1
            elif text == "{":
                found.append(at)
    return found


def ps_fed_writes(
    command: str, native_operands: Callable[[str, list[str]], Optional[list[str]]],
) -> Optional[list[PsFed]]:
    """The write or delete cmdlets of a PowerShell `command` that take their item from a list, each with the
    list commands that may feed it: those of the cmdlet's own statement before it or inside its own arguments
    (for `$_` also those in front of the script blocks around it), and those a variable it names was filled with
    (`foreach ($f in <list>)`, `$f = <list>`). A cmdlet is fed when it takes its item from the pipeline (no path
    of its own), names `$_`/`$PSItem`, holds a sub-expression, or names such a variable. `native_operands(name,
    args)` reads a `git`/`rg`/`grep` list command like Bash does (None: not a list, or one that is not
    understood). None when the command does not tokenize."""
    pieces = _ps_pieces(command)
    if pieces is None:
        return None
    listers_at: list[tuple[int, Optional[list[str]]]] = []
    for index, (kind, text) in enumerate(pieces):
        if kind != "word" or not _starts_command(pieces, index):
            continue
        name = _ps_command_name(text)
        args, _ = _ps_args(pieces, index + 1)
        if name in _PS_LISTERS:
            listers_at.append((index, _ps_lister_operands(args)))
        elif name in ("rg", "grep") or (name == "git" and args[:1] in (["ls-files"], ["grep"], ["diff"])):
            listers_at.append((index, native_operands(name, args)))
    assigned: dict[str, list[Optional[list[str]]]] = {}
    for begin, (kind, text) in enumerate(pieces):  # `$files = <list>`, at the start of a statement
        match = re.fullmatch(r"\$(\w+)(\+?=?)", text) if kind == "word" and _starts_command(pieces, begin) else None
        if match and (match.group(2) in ("=", "+=") or (begin + 1 < len(pieces) and pieces[begin + 1][1] in ("=", "+="))):
            end = _local_end(pieces, begin)
            assigned.setdefault(match.group(1).lower(), []).extend(
                operands for at, operands in listers_at if begin <= at < end)
    for index in range(len(pieces) - 3):  # `foreach ($f in <list>)`
        if (pieces[index][0] == "word" and pieces[index][1].lower() == "foreach" and pieces[index + 1] == ("open", "(")
                and pieces[index + 2][1].startswith("$") and pieces[index + 3] == ("word", "in")):
            close = _group_end(pieces, index + 1)
            assigned.setdefault(pieces[index + 2][1][1:].lower(), []).extend(
                operands for at, operands in listers_at if index < at < close)
    found: list[PsFed] = []
    for index, (kind, text) in enumerate(pieces):
        name = _ps_command_name(text)
        writer = _ALIASES.get(name)
        if kind != "word" or writer not in _PS_ITEM_WRITERS or not _starts_command(pieces, index):
            continue
        args, stop = _ps_args(pieces, index + 1)
        positionals, values = _ps_split_args(args)
        targets = _cmdlet_targets(name, args)
        from_pipe = (writer in _PS_PIPE_FED and index > 0 and pieces[index - 1] == ("op", "|")
                     and not (positionals or values.get("path") or values.get("literalpath")))
        variables = {variable.lower() for target in targets for variable in re.findall(r"\$\{?(\w+)", target)}
        filled = [variable for variable in variables if variable in assigned]
        sub = any(re.search(r"\$\(|@\(|^\(", target) for target in targets)
        current = any(re.search(r"\$_|\$PSItem", target, re.IGNORECASE) for target in targets)
        if not (from_pipe or sub or current or filled):
            continue
        begin = _local_start(pieces, index)
        regions = [(begin, stop)]
        if current:  # `$_` is an item of the pipeline in front of each script block around the cmdlet
            regions += [(_local_start(pieces, block), block) for block in _enclosing_blocks(pieces, index)]
        listers = [operands for first, last in regions for at, operands in listers_at if first <= at < last]
        before = {variable.lower() for kind, text in pieces[begin:index] if kind == "word"
                  for variable in re.findall(r"\$\{?(\w+)", text)}  # `$files | ForEach-Object { ... }`
        for variable in filled + sorted(before & set(assigned) - set(filled)):
            listers += assigned[variable]
        found.append(PsFed(name, listers))
    return found


