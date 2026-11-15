#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Readers for write-guard (check 1): where the files a write works on come from when a shell loop or a
#          `find -exec` supplies them. They only read a command and name the sources; write_guard.py decides
#          whether a source is shown (names fixed folders) and refuses otherwise.
#
#          Bash: a loop variable (`for f in <words>`), a `read` variable or a `mapfile`/`readarray` array fed by a
#          pipe (also one at the end of a line), a process substitution, a here-string or a file is bound to the
#          list that feeds it, and a loop over such a variable takes its list (shell_facts); the words of a
#          `find` stage give the source (the folders it names) and the commands its `-exec`/`-execdir`/`-ok`/
#          `-okdir` run on every hit (find_hits). A list kept in a variable counts as the list that filled it: an
#          array assignment (`a=(<words>)`, `a+=(...)`, `b=("${a[@]}")`, also behind `local`/`declare`/`typeset`;
#          only as a command of its own, never inside `[[ ... ]]` or as an argument)
#          or a scalar one of a substitution that lists files, whose words are read like the words
#          of a `for` list. A substitution lists files only when its pipeline starts with a lister in name mode - the
#          command word matched whole (`./find-version.sh` is no `find`): `find`, `ls`, `fd`, `locate`, `git ls-files`
#          without `-s`/`--stage`, `grep`/`rg`/`git grep` with `-l`, `-L` (also in a cluster such as `-rl`),
#          `--files-with-matches`, `--files-without-match`, `--files` or `--name-only`, `git diff --name-only` or
#          `--name-status` - and goes on only with `head`, `tail`, `sort`, `uniq` or `grep` (`LIST=$(grep -rl x .)`,
#          `LIST="$(git ls-files | grep x)"`, `a=($(find . -name '*.md'))`); anything else prints text or a single
#          name (`v=$(grep -m1 ^version f | cut ...)`, `n=$(ls | wc -l)`, `n=$(basename "$f")`) and binds nothing, in a
#          scalar and in an array assignment alike (the literal words of the array stay as they are); an `ls` whose path
#          operands are all name-only globs that cannot match `.act` (`f=$(ls -t *.log | head -1)`: no `/` or `\`, nothing
#          that matches `.act` case-insensitively, a `[!...]` counts as matching) lists names of the current folder and
#          binds nothing either, while a loop over such a substitution (`for f in $(ls *.log)`) keeps its list.
#          A `read` or `mapfile` fed by a here-string of such a variable (`<<< "$LIST"`) takes it
#          too. The command a `mapfile`/`readarray -C <callback>` runs per quantum with the array index and the line
#          appended (ShellFacts.callbacks) is read like a `find -exec` command on a hit, a shell callback (`sh -c '...'
#          _`) like `find -exec sh -c '...' _ {}`; a callback that is only a variable stays an unknown command.
#          PowerShell: a write or delete cmdlet that takes its item from the pipeline, from `$_`, from a
#          variable a loop or an assignment filled, or from a sub-expression, together with the list commands
#          (`Get-ChildItem`, `Get-Item`, `Resolve-Path`, `git ls-files` ...) that can feed it; a `[IO.File]`/`[IO.Directory]`
#          call and a method of an item (`$_.Delete()`, also `.Delete.Invoke()`) count as such writers
#          (ps_fed_writes), as does an item object made in place (`[IO.FileInfo]::new(x)`, `New-Object IO.FileInfo x`,
#          `DirectoryInfo` too, directly or kept in a variable) with the file or folder it names, a variable that
#          holds `$_` inside a script block (`$f = $_`), and an assignment to `Attributes`, `IsReadOnly`, `CreationTime`,
#          `LastAccessTime`, `LastWriteTime` (also `...Utc`) or `UnixFileMode` of such an item. The literal first
#          argument of `MoveTo`/`CopyTo` of such an item and the destination and backup of its `Replace` are places
#          written to (PsFed.destinations). A `Get-Item`/`Get-ChildItem` of a single name-only wildcard that cannot
#          match `.act` (`*.log`) lists nothing of `.act`, but only for a command that holds no location change
#          (`location` in any name, `cd`, `sl`, `chdir`, `pushd`, `popd`), no `Invoke-Expression`/`iex`, no call operator
#          `&` or `.` (a literal name too), no word that ends in `.ps1`, no `[scriptblock]`, no `Invoke-Command`/`icm`
#          and no `.Invoke(`, and for a write that works on the item itself (the
#          pipeline input, `$_`, a variable that holds it, a method of it) and is no `MoveTo`, `CopyTo` or `Replace`.
#
# Known limits: a function or script body (also a function named as the `-C` callback of `mapfile`), `sudo -u user
#          find`, a list kept in a variable by any other form (`read -a`, `+=` on a scalar, an element assigned
#          `a[0]=...`, a plain literal scalar, a substitution with an unbalanced parenthesis in a quoted string, a lister
#          behind another first stage such as `cat x | grep -rl y .`) and a
#          PowerShell list from a file (`Get-Content list.txt`) are not
#          followed: such a write is judged as before. A property write on an item other than the ones named above
#          (`$_.Name = ...`), one with a compound operator other than `=`/`+=` (`-=`, `*=`), `CreateSymbolicLink`,
#          `CreateAsSymbolicLink`, `OpenHandle`, an item object made
#          by `New-Object ... -ArgumentList (,'x')`, by a cast (`[IO.FileInfo]'x'`) or kept in a typed variable
#          (`[IO.FileInfo]$f = 'x'`) are no write here. A `[IO.File]::Copy`/`Move` written `.Invoke(` is missed by the
#          literal reader, not by the list reader. A name wildcard matches the name of a link or junction that
#          leads to `.act` like any other: such a link is not seen. A `-C` callback value that is only a variable or
#          a substitution is read as an unknown command. Variables are bound by
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
from .powershell_targets import _ALIASES, _cmdlet_targets, _ps_command_name, _ps_io_write_name, _ps_open_is_read_only
from .powershell_targets import _ps_split_args, _ps_split_arguments, _ps_tokens, _ps_unquote
from .shell_targets import _SEPARATOR_OPS

__all__ = ["Binding", "ShellFacts", "shell_facts", "find_hits", "FIND_HIT", "PsFed", "ps_fed_writes", "lists_files"]

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
_MAPFILE_VALUE_OPTIONS = "dnOsuCc"
_VARIABLE_RE = re.compile(r"\$(?:\{(\w+)|(\w+))")


@dataclass
class Binding:
    """What feeds a variable: the command texts of its lists (to be shown), whether a literal word names `.act`
    or may match it, and whether the list is something that cannot be shown (a file)."""

    sources: list[str] = field(default_factory=list)
    names_act: bool = False
    unshown: bool = False
    refs: list[str] = field(default_factory=list)  # variables a loop word names (`for f in "${a[@]}"`): their lists too
    # A scalar variable of a substitution (`LIST=$(...)`), bound only when one of its own substitution texts lists files
    # (_scalar_binding): `sources` then holds those texts alone, and a substitution that only prints text makes no
    # binding at all. Used as a write target it is judged by the sources that list files (write_guard._binding_refusal).
    scalar: bool = False


@dataclass
class ShellFacts:
    """What one command text holds: the bindings of its loop and `read` variables, and the word lists of its
    `find` stages (find_hits reads them)."""

    bindings: dict[str, list[Binding]] = field(default_factory=dict)
    finds: list[list[str]] = field(default_factory=list)
    # The `-C` callbacks of `mapfile`/`readarray`: the callback text and the list that feeds the mapfile.
    callbacks: list[tuple[str, Binding]] = field(default_factory=list)


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


def _loop_binding(items: list[str], array: bool = False) -> Binding:
    """The Binding of the words of a `for` list or of an array assignment (`array`): there a substitution counts only
    when it is a list of files (lists_files) - one that prints text or a single name adds no source."""
    binding = Binding()
    for item in items:
        binding.refs += [one or two for one, two in _VARIABLE_RE.findall(item)]
        if _ACT_RE.search(item):
            binding.names_act = True
        found = _substitution_texts(item)
        if found and array:
            found = [text for text in found if lists_files(text)]
            if not found:
                continue  # `a=($(date +%s))`: text, no list; the literal part of the word was read above
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


def _mapfile_options(args: list[str]) -> tuple[list[str], Optional[str]]:
    """The array `mapfile`/`readarray <args>` fills (`MAPFILE` without a name) and the text of its `-C` callback
    (the last one given; None without one)."""
    index = 0
    callback: Optional[str] = None
    names: Optional[list[str]] = None
    while index < len(args):
        word = args[index]
        index += 1
        if word.startswith("-") and len(word) > 1:
            for position, letter in enumerate(word[1:], 1):
                if letter in _MAPFILE_VALUE_OPTIONS:
                    value = word[position + 1:]  # the value is the rest of the word, else the next word
                    if not value and index < len(args):
                        value, index = args[index], index + 1
                    if letter == "C":
                        callback = value
                    break
        else:
            names = [word]  # the options end at the first operand
            break
    return names or ["MAPFILE"], callback


def _mapfile_names(args: list[str]) -> list[str]:
    """The array `mapfile`/`readarray <args>` fills (`MAPFILE` without a name)."""
    return _mapfile_options(args)[0]


_DECLARERS = frozenset({"local", "declare", "typeset", "readonly", "export"})
_SCALAR_ASSIGNMENT_RE = re.compile(r"(\w+)=(.*)", re.DOTALL)
_ARRAY_ASSIGNMENT_RE = re.compile(r"(\w+)(\+?)=")


def _scalar_assignments(words: list[str]) -> list[tuple[str, str]]:
    """The (name, value) of the scalar assignments at the start of a stage (`LIST=$(...) cmd`, `local LIST=$(...)`,
    `declare -r LIST=...`): the words before the command, after a declaring word its options are skipped."""
    found: list[tuple[str, str]] = []
    declaring = False
    for word in words:
        match = _SCALAR_ASSIGNMENT_RE.fullmatch(word)
        if match:
            found.append((match.group(1), match.group(2)))
        elif word in _DECLARERS:
            declaring = True
        elif not (declaring and word.startswith("-")):
            break
    return found


# A substitution that lists files, read by its command words (lists_files): its pipeline starts with a lister in name
# mode - `find`, `ls`, `fd`, `locate`, `git ls-files` without `-s`/`--stage`, `grep`/`rg`/`git grep` with an option that
# prints file names only (`-l`, `-L`, also inside a cluster such as `-rl`, `--files-with-matches`,
# `--files-without-match`, `--files`, `--name-only`), `git diff --name-only`/`--name-status` - the command word matched
# whole (`./find-version.sh` is no `find`), and every later stage is one of `head`, `tail`, `sort`, `uniq`, `grep`.
# `n=$(grep -c x f)`, `v=$(grep -m1 ^version f | cut ...)`, `n=$(ls | wc -l)`, `sha=$(git diff | sha256sum)`,
# `n=$(basename "$f")` and `id=$(python .act/scripts/x.py)` print text or a single name: no list.
_NAME_LISTERS = frozenset({"find", "ls", "fd", "locate"})
_GREP_COMMANDS = frozenset({"grep", "rg"})
_NAME_ONLY_LONG = frozenset({"--files-with-matches", "--files-without-match", "--files-without-matches", "--files",
                             "--name-only"})
_NAME_ONLY_CLUSTER_RE = re.compile(r"-[A-Za-z]*[lL][A-Za-z]*")
_STAGE_CLUSTER_RE = re.compile(r"-[A-Za-z]*s[A-Za-z]*")
_LATER_STAGES = frozenset({"head", "tail", "sort", "uniq", "grep"})
_GIT_VALUE_OPTIONS = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"})


def _command_word(word: str) -> str:
    """The lower-case file name of a command word, without a `.exe`."""
    name = os.path.basename(word.replace("\\", "/")).lower()
    return name[:-4] if name.endswith(".exe") else name


def _prints_names_only(args: list[str]) -> bool:
    """True when one of the options of a grep-like command `args` makes it print file names only."""
    for arg in args:
        if arg == "--":
            break
        if arg in _NAME_ONLY_LONG or (arg.startswith("-") and not arg.startswith("--")
                                      and _NAME_ONLY_CLUSTER_RE.fullmatch(arg)):
            return True
    return False


_LS_VALUE_CLUSTER_RE = re.compile(r"-[A-Za-z]*[IwT][A-Za-z]*")
_LS_VALUE_OPTIONS = frozenset({"--ignore", "--width", "--tabsize", "--block-size", "--color", "--time-style", "--format",
                               "--sort", "--time", "--indicator-style", "--quoting-style", "--hide"})


def _ls_names_only_glob(args: list[str]) -> bool:
    """True when the `ls` arguments `args` have at least one path operand and every operand is a name-only glob that
    cannot match `.act`: a glob character, no `/`, backslash, `$`, backtick, `~`, brace or parenthesis in it, and
    _ps_glob_may_match_act false (case-insensitive; `[!...]`, `[^...]` and what is not understood may match). An
    option that takes a value word (`-I`, `-w`, `-T`, a long one without `=`) is not read: the answer is False."""
    operands: list[str] = []
    ended = False
    for arg in args:
        if ended or not arg.startswith("-") or arg == "-":
            operands.append(arg)
        elif arg == "--":
            ended = True
        elif arg in _LS_VALUE_OPTIONS or (not arg.startswith("--") and _LS_VALUE_CLUSTER_RE.fullmatch(arg)):
            return False
    return bool(operands) and all(
        re.search(r"[*?\[]", operand) and not re.search(r"[\/$`~{}()]", operand) and not _ps_glob_may_match_act(operand)
        for operand in operands)


def _is_name_lister(words: list[str]) -> bool:
    """True when the first stage `words` of a pipeline is a lister in name mode (see _NAME_LISTERS); an `ls` of name-only
    globs that cannot match `.act` (_ls_names_only_glob) is none."""
    words = _strip_prefix(words)
    if not words:
        return False
    name = _command_word(words[0])
    if name == "ls" and _ls_names_only_glob(words[1:]):
        return False
    if name in _NAME_LISTERS:
        return True
    if name in _GREP_COMMANDS:
        return _prints_names_only(words[1:])
    if name != "git":
        return False
    index = 1
    while index < len(words) and words[index].startswith("-"):  # global options, some take the next word
        index += 2 if words[index] in _GIT_VALUE_OPTIONS else 1
    if index >= len(words):
        return False
    sub, args = words[index], words[index + 1:]
    if sub == "ls-files":
        return not any(arg == "--stage" or (not arg.startswith("--") and _STAGE_CLUSTER_RE.fullmatch(arg)) for arg in args)
    if sub == "grep":
        return _prints_names_only(args)
    return sub == "diff" and any(arg in ("--name-only", "--name-status") for arg in args)


def _pipelines(source: str) -> Optional[list[list[list[str]]]]:
    """The pipelines of the command text `source`, each as its stages' words (redirections left out); None when it
    does not tokenize."""
    tokens = Parse("Bash", source).chain_tokens()
    if tokens is None:
        return None
    pipelines: list[list[list[str]]] = [[[]]]
    index = 0
    while index < len(tokens):
        text, is_op = tokens[index]
        index += 1
        if not is_op:
            pipelines[-1][-1].append(str(text))
        elif text == "(" and pipelines[-1][-1] and str(pipelines[-1][-1][-1]).endswith("$"):  # `$(...)` inside a word
            end = _matching_paren(tokens, index - 1)
            pipelines[-1][-1][-1] += "(" + _tokens_text(tokens[index:end]) + ")"
            index = end + 1
        elif text in ("|", "|&"):
            pipelines[-1].append([])
        elif text in _SEPARATOR_OPS or text == "\n":
            pipelines.append([[]])
        else:  # a redirection: its target is no word of the command
            if text.startswith((">", "&>")) and pipelines[-1][-1] and pipelines[-1][-1][-1].isdigit():
                pipelines[-1][-1].pop()
            if index < len(tokens) and not tokens[index][1]:
                index += 1
    return pipelines


def lists_files(source: str) -> bool:
    """True when the command text `source` is a list of files: one of its pipelines starts with a lister in name mode
    and goes on only with head, tail, sort, uniq or grep (_NAME_LISTERS); text that does not tokenize counts as one."""
    pipelines = _pipelines(source)
    if pipelines is None:
        return True
    for stages in pipelines:
        if stages[0] and _is_name_lister(stages[0]) and all(
                stage and _command_word(stage[0]) in _LATER_STAGES for stage in stages[1:]):
            return True
    return False


def _scalar_binding(value: str) -> Optional[Binding]:
    """The list a scalar assignment `NAME=<value>` makes: a Binding of the substitution texts of `value` that list
    files (lists_files), its refs the variables those texts name; None when none does - a substitution that only
    prints text, one that does not end (an unbalanced `(` inside a quoted string counts), a value without one - so
    the variable is no list, names no `.act` path through its text and inherits nothing from the variables it uses."""
    listing = [text for text in _substitution_texts(value) or () if lists_files(text)]
    if not listing:
        return None
    binding = Binding(sources=listing, scalar=True)
    for text in listing:
        binding.refs += [one or two for one, two in _VARIABLE_RE.findall(text)]
    return binding


def _in_command_position(before: list[str]) -> bool:
    """True when the words `before` in front of an array assignment leave it in the place of a command word: nothing,
    keywords, other assignments, a declaring word with its options (`local -a`). In `[[ $x =~ key=(.*) ]]` or as the
    argument of a command `key=(` is no assignment."""
    declaring = False
    for word in before:
        if word in _PREFIXES or word in _OPENERS or _SCALAR_ASSIGNMENT_RE.fullmatch(word) or _ARRAY_ASSIGNMENT_RE.fullmatch(word):
            continue
        if word in _DECLARERS:
            declaring = True
        elif not (declaring and word.startswith("-")):
            return False
    return True


def _array_items(body: list) -> list[str]:
    """The words between the parentheses of an array assignment (the tokens `body`); a `$(...)` span is one word."""
    items: list[str] = []
    index = 0
    while index < len(body):
        text, is_op = body[index]
        index += 1
        if is_op:
            if text == "(":
                index = _matching_paren(body, index - 1) + 1  # a group that is no word
            continue
        if str(text).endswith("$") and index < len(body) and body[index] == ("(", True):
            end = _matching_paren(body, index)
            text = str(text) + "(" + _tokens_text(body[index + 1:end]) + ")"
            index = end + 1
        items.append(str(text))
    return items


def shell_facts(tokens: list, _depth: int = 0) -> ShellFacts:
    """The loop and `read` bindings and the `find` stages of the token stream of a Bash command
    (Parse.chain_tokens), a text handed to `sh -c` included."""
    facts = ShellFacts()
    # per `read`/`mapfile`: its variables, the frames around it, its input redirections, the `-C` callback of a
    # mapfile and the stages of the pipe in front of it
    reads: list[tuple[list[str], list[_Frame], list[tuple[str, str]], Optional[str], list[str]]] = []
    stage: list[str] = []
    feeds: list[tuple[str, str]] = []  # input redirections of the stage
    pipe: list[str] = []  # the stages of the pipeline so far
    frames: list[_Frame] = []
    closed: Optional[_Frame] = None  # a compound the last `)` closed, for the redirections behind it
    groups: dict[str, list[str]] = {}  # a closed subshell as a pipe stage: its name and the pipelines it ran
    last_group = ""  # the subshell the last `)` closed, for the `|` right behind it
    after_pipe = False  # the last token was a `|`: a line break behind it does not end the pipe

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
        for variable, value in _scalar_assignments(words):  # `LIST=$(grep -rl x .)`: the list the substitution makes
            scalar = _scalar_binding(value)
            if scalar is not None:
                facts.bindings.setdefault(variable, []).append(scalar)
        words = _strip_prefix(words)
        if words:
            name = os.path.basename(words[0]).lower()
            if name == "read":
                reads.append((_read_names(words[1:]), list(frames), list(feeds), None, []))
            elif name in ("mapfile", "readarray"):
                names, callback = _mapfile_options(words[1:])
                reads.append((names, list(frames), list(feeds), callback, list(pipe)))
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
                            facts.callbacks += nested.callbacks
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
            after_pipe = False
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
        if text == "(" and stage and _ARRAY_ASSIGNMENT_RE.fullmatch(stage[-1]) and _in_command_position(stage[:-1]):
            end = _matching_paren(tokens, index - 1)  # `a=(...)`, `a+=(...)` as a command of its own
            facts.bindings.setdefault(_ARRAY_ASSIGNMENT_RE.fullmatch(stage.pop()).group(1), []).append(
                _loop_binding(_array_items(tokens[index:end]), array=True))
            index = end + 1
            closed = None
            after_pipe = False
            continue
        if text == "(" and stage and stage[-1].endswith("$"):  # a command substitution folded into its word
            end = _matching_paren(tokens, index - 1)
            stage[-1] += "(" + _tokens_text(tokens[index:end]) + ")"
            index = end + 1
            continue
        if text == "\n" and after_pipe and not stage:
            continue  # a pipe at the end of a line goes on in the next one: the pipe so far stays
        after_pipe = text in ("|", "|&")
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
    for names, owners, own_feeds, callback, own_pipe in reads:
        sources = own_feeds
        if not sources and callback is not None and own_pipe:  # `grep -rl x . | mapfile -C cmd`: the pipe feeds it
            sources = [("cmd", text) for text in _expand_groups(own_pipe, groups)]
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
                binding.refs += [one or two for one, two in _VARIABLE_RE.findall(value)]  # `<<< "$LIST"`
        for name in names:
            facts.bindings.setdefault(name, []).append(binding)
        if callback is not None:  # a callback nothing feeds reads the terminal: no list that can be shown
            binding.unshown = binding.unshown or not sources
            facts.callbacks.append((callback, binding))
    if _depth == 0:
        _follow_refs(facts.bindings)
    return facts


def _follow_refs(bindings: dict[str, list[Binding]]) -> None:
    """A loop whose words name variables (`for f in "${a[@]}"`) takes over the lists of the bindings of those
    variables (a `read`, `mapfile` or another loop), to a depth of a few steps."""
    for _ in range(_MAX_DEPTH + 1):
        for listed in bindings.values():
            for binding in listed:
                for ref in binding.refs:
                    for other in bindings.get(ref, ()):
                        if other is not binding:
                            binding.sources += [text for text in other.sources if text not in binding.sources]
                            binding.names_act = binding.names_act or other.names_act
                            binding.unshown = binding.unshown or other.unshown


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

_PS_LISTERS = frozenset({"get-childitem", "gci", "ls", "dir", "get-item", "gi", "resolve-path", "rvpa"})
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
    # Files or folders to be judged as write targets (write_guard._item_target_refusal): the argument of an item object
    # made in place (`[IO.FileInfo]::new(x)`, `New-Object IO.FileInfo x`), as its text.
    item_targets: list[str] = field(default_factory=list)
    # The places a method of an item writes to - the arguments of `MoveTo(x)`, `CopyTo(x)`, `Replace(destination,
    # backup)`, quotes removed, a `$null` left out -, to be judged against `.act` only.
    destinations: list[str] = field(default_factory=list)
    # A `Get-Item`/`Get-ChildItem` of one name-only wildcard that cannot match `.act` (`*.log`) feeds it and was left
    # out of `listers` (ps_fed_writes): it reads the current folder only, so that folder must lie inside the project and
    # not in `.act`.
    current_folder: bool = False


class _Pieces(list):
    """The pieces of a PowerShell command (kind, text); `glued` holds the indices of those that follow the one before
    without a space (`(Get-ChildItem).FullName`, a name followed by a sub-expression); `raw` the text of a word piece as
    it was written, quotes kept (the tokenizer drops them), where it could be told."""

    glued: set[int]
    raw: dict[int, str]


def _ps_pieces(command: str) -> Optional[_Pieces]:
    """The PowerShell tokens of `command` cut at parentheses and braces: ("word"|"op"|"open"|"close", text)."""
    tokens = _ps_tokens(command)
    if tokens is None:
        return None
    pieces = _Pieces()
    pieces.glued = set()
    pieces.raw = {}
    for text, is_op in tokens:
        if is_op:
            pieces.append(("op", text))
            continue
        parts = [part for part in _PS_PIECE_RE.split(text) if part]
        written = getattr(text, "raw", None)
        raw_parts = [part for part in _PS_PIECE_RE.split(written) if part] if written is not None else []
        for position, part in enumerate(parts):
            if position:
                pieces.glued.add(len(pieces))
            if len(raw_parts) == len(parts):  # the same cut: the written pieces are the pieces
                pieces.raw[len(pieces)] = raw_parts[position]
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


_PS_NAME_LISTERS = frozenset({"get-childitem", "gci", "ls", "dir", "get-item", "gi"})
# Short (8.3) names a file system may give `.act`; a pattern that matches one of them is treated like one that matches `.act`.
_ACT_NAMES = (".act", "ACT~1", "ACT~2", "ACT~3")


def _ps_glob_may_match_act(pattern: str) -> bool:
    """True when the PowerShell wildcard `pattern` (`*`, `?`, `[...]`; case-insensitive) can match the name `.act`.
    What is not understood (a negated or empty bracket expression, a range that does not compile) may match."""
    regex = ""
    index = 0
    while index < len(pattern):
        char = pattern[index]
        index += 1
        if char == "*":
            regex += ".*"
        elif char == "?":
            regex += "."
        elif char == "[":
            end = pattern.find("]", index + 1)
            body = pattern[index:end] if end > 0 else ""
            if not body or body[0] in "^!":
                regex += "."
            else:
                regex += "[" + "".join("\\" + char if char in "\\]^[" else char for char in body) + "]"
            index = end + 1 if end > 0 else len(pattern)
        else:
            regex += re.escape(char)
    try:
        return any(re.fullmatch(regex, name, re.IGNORECASE | re.DOTALL) for name in _ACT_NAMES)
    except re.error:
        return True


def _ps_name_glob(name: str, args: list[str]) -> bool:
    """True when the lister `name` with `args` is a `Get-Item`/`Get-ChildItem` (`gi`, `gci`, `ls`, `dir`) whose only
    path operand is a name-only wildcard - one of `*`, `?`, `[` in it, no separator, variable, `~`, drive or
    grouping character - that cannot match `.act` (_ps_glob_may_match_act), without an option that starts with `r`
    or `d` (`-Recurse`, `-Depth`, `-Directory`, ...): it lists names of the current folder and nothing below."""
    if name not in _PS_NAME_LISTERS:
        return False
    operands = _ps_lister_operands(args)
    if operands is None or len(operands) != 1:
        return False
    if any(word.startswith("-") and len(word) > 1 and word[1:].partition(":")[0].lower()[:1] in ("r", "d") for word in args):
        return False
    operand = operands[0]
    if not re.search(r"[*?\[]", operand) or re.search(r"[\\/$`~:{}()@;,|]", operand):
        return False
    return not _ps_glob_may_match_act(operand)


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


# .NET calls and methods of an item that change or remove a file or folder: `[IO.File]::WriteAllText($_.FullName, 'x')`,
# `[IO.Directory]::Delete($f, $true)`, `$_.Delete()`, `(Get-ChildItem x).MoveTo('y')`. A call of `[IO.File]`/`[IO.Directory]`
# takes its item in its arguments (the names are those of powershell_targets._ps_io_write_name, the set the literal
# reader uses; `[IO.StreamWriter]::new` too); a method takes the object in front of the dot (`Replace` is no fed write:
# it is a string method as often as a file one; of an item itself - `$_`, a variable, a sub-expression - only its
# destination and backup arguments are judged, like those of `MoveTo` and `CopyTo`, _PS_ARGUMENT_TARGETS).
# `.Invoke(` behind the method name is the same call.
_PS_STATIC_RE = re.compile(r"\[(?:global::)?(?:System\.)?IO\.(File|Directory|StreamWriter)\]::(\w+)", re.IGNORECASE)
_PS_ITEM_NEW_RE = re.compile(r"\[(?:global::)?(?:System\.)?IO\.(?:FileInfo|DirectoryInfo)\]::new", re.IGNORECASE)
_PS_ITEM_TYPE_RE = re.compile(
    r"\[?((?:global::)?(?:System\.)?IO\.(?:FileInfo|DirectoryInfo))\]?(?:\((.*)\))?", re.IGNORECASE | re.DOTALL)
# Properties of an item whose assignment changes the file or folder.
_PS_PROPERTY_RE = re.compile(
    r"(.*)\.(attributes|isreadonly|creationtime(?:utc)?|lastaccesstime(?:utc)?|lastwritetime(?:utc)?|unixfilemode)"
    r"(\+?=.*)?", re.IGNORECASE | re.DOTALL)
_PS_METHOD_WRITES = frozenset({
    "delete", "moveto", "copyto", "create", "createtext", "appendtext", "openwrite", "open", "encrypt", "decrypt",
    "createsubdirectory",
})
# Methods of an item whose first arguments name a file or folder that is written: how many of them (`MoveTo(destination)`,
# `CopyTo(destination[, overwrite])`, `Replace(destination, backup[, ignoreErrors])`).
_PS_ARGUMENT_TARGETS = {"moveto": 1, "copyto": 1, "replace": 2}

# What leaves the name-only wildcard relief (_ps_relief) out: a change of the location in the command text - `location`
# in any name (`Set-Location`, `Push-Location`, `Pop-Location`, a module-qualified one, `.SetLocation(`), the words
# `cd`, `sl`, `chdir`, `pushd`, `popd` - the commands `Invoke-Expression`/`iex`, any call operator `&`/`.` in the place
# of a command (a literal name too: the script it runs may change the location), a word that ends in `.ps1`, a
# `[scriptblock]`, `Invoke-Command`/`icm` and an `.Invoke(` call. Over-inclusive on purpose: it only keeps the list
# refusal. The relief is for a write on the item itself; a write target unrelated to the item (`Move-Item $_ $d`) is
# judged as anywhere else.
_PS_RELIEF_BLOCK_RE = re.compile(
    r"location|(?<![\w$-])(?:cd|sl|chdir|pushd|popd)(?![\w-])|(?<![\w$.-])(?:invoke-expression|iex)(?![\w-])"
    r"|(?<![\w.\\/$&-])[&.](?![&.\w\\/])\s*(?:[$({@]|[\"'][^\"']*\$)"
    r"|(?:^|[;|({=\n]|&&|\|\|)\s*[&.](?![&.\w\\/-])|\.ps1(?!\w)|\[scriptblock\]"
    r"|(?<![\w$.-])(?:invoke-command|icm)(?![\w-])|\.invoke\(", re.IGNORECASE)
_PS_ITEM_VARIABLES = frozenset({"$_", "$psitem"})


def _group_start(pieces: _Pieces, end: int) -> int:
    """The index of the opener of the closer at pieces[end]; 0 when it does not open."""
    depth = 0
    for index in range(end, -1, -1):
        depth += (pieces[index][0] == "close") - (pieces[index][0] == "open")
        if depth == 0:
            return index
    return 0


def _ps_item_object(pieces: _Pieces, index: int) -> Optional[tuple[str, int]]:
    """For the word at pieces[index], when it makes a `FileInfo` or `DirectoryInfo` in place (`[IO.FileInfo]::new(x)`,
    `New-Object IO.FileInfo x`, `New-Object -TypeName System.IO.FileInfo -ArgumentList x`, `New-Object
    IO.FileInfo(x)`): (the text of its argument, the index behind the construction); None otherwise."""
    kind, text = pieces[index]
    if kind != "word":
        return None
    if _PS_ITEM_NEW_RE.fullmatch(text):
        after = index + 1
        if after < len(pieces) and pieces[after] == ("open", "(") and after in pieces.glued:
            end = _group_end(pieces, after)
            return " ".join(piece[1] for piece in pieces[after + 1:end]), end + 1
        return None
    if _ps_command_name(text) != "new-object":
        return None
    args, stop = _ps_args(pieces, index + 1)
    positional: list[str] = []
    type_name = ""
    argument_list = ""
    position = 0
    while position < len(args):
        word = args[position]
        position += 1
        if word.startswith("-") and len(word) > 1:
            flag, colon, value = word[1:].partition(":")
            flag = flag.lower()
            takes_value = flag and any(full.startswith(flag) for full in ("typename", "argumentlist", "property", "comobject"))
            if takes_value and not colon and position < len(args):
                value, position = args[position], position + 1
            if flag and "typename".startswith(flag):
                type_name = value
            elif flag and "argumentlist".startswith(flag):
                argument_list = value
        else:
            positional.append(word)
    if not type_name and positional:
        type_name = positional.pop(0)
    if not argument_list and positional:
        argument_list = positional[0]
    match = _PS_ITEM_TYPE_RE.fullmatch(type_name)
    if match is None:
        return None
    argument = match.group(2) if match.group(2) is not None else argument_list
    wrapped = re.fullmatch(r"@?\((.*)\)", argument, re.DOTALL)
    argument = (wrapped.group(1) if wrapped else argument).strip()
    return (argument, stop) if argument else None


def _ps_object_of(pieces: _Pieces, index: int, owner: str) -> Optional[tuple[str, list[str]]]:
    """For a member word at pieces[index] (a method or property of an item): the text of the item it belongs to and
    the arguments of the item objects made in place in front of it. `owner` is the text before the dot (`$_`, `$f`);
    empty when the member follows a closing parenthesis (`(Get-ChildItem x).Delete()`, `[IO.FileInfo]::new(x).Delete()`,
    `(New-Object IO.FileInfo x).Delete()`)."""
    if owner:
        return owner, []
    if not (index > 0 and index in pieces.glued and pieces[index - 1] == ("close", ")")):
        return None
    start = _group_start(pieces, index - 1)
    made: Optional[tuple[str, int]] = None
    if start > 0 and start in pieces.glued:
        made = _ps_item_object(pieces, start - 1)  # `[IO.FileInfo]::new(x).Delete()`
    if made is None and start + 1 < index:
        made = _ps_item_object(pieces, start + 1)  # `(New-Object IO.FileInfo x).Delete()`
    return pieces[start][1] + " ".join(piece[1] for piece in pieces[start + 1:index]), [made[0]] if made else []


@dataclass
class _PsCall:
    """A .NET write call or a write method of an item found by _ps_call_writer."""

    name: str
    stop: int  # the index behind the call
    text: str  # what it works on: the arguments of a .NET call, the object in front of the dot of a method
    made: list[str]  # the arguments of the item objects made in place in front of the method
    arguments: str  # the arguments between its parentheses as written, quotes kept


def _ps_call_writer(pieces: _Pieces, index: int) -> Optional[_PsCall]:
    """For the word at pieces[index], when it is a .NET write call or a write method followed by its arguments in
    parentheses: the call (_PsCall); None otherwise. An `Open` that opens an existing file for reading only is no
    write (powershell_targets._ps_open_is_read_only, decided on the arguments as written). `Replace` of an item
    itself (`$_`, a variable, a sub-expression: not a property path, which is a string) with a lister or an item object
    behind it is a call too: its destination and backup arguments are write targets."""
    after = index + 1
    if after >= len(pieces) or pieces[after] != ("open", "(") or after not in pieces.glued:
        return None
    stop = _group_end(pieces, after) + 1
    arguments = " ".join(piece[1] for piece in pieces[after + 1:stop - 1])
    written = " ".join(pieces.raw.get(at, pieces[at][1]) for at in range(after + 1, stop - 1))
    text = re.sub(r"\.invoke$", "", pieces[index][1], flags=re.IGNORECASE)  # `$_.Delete.Invoke()` is `$_.Delete()`
    static = _PS_STATIC_RE.fullmatch(text)
    if static:
        name = static.group(2)
        if static.group(1).lower() == "streamwriter":
            writes = name.lower() == "new"
        else:
            writes = _ps_io_write_name(name) and not (name.lower() == "open" and _ps_open_is_read_only(written, True))
        return _PsCall(f"[IO]::{name}", stop, arguments, [], written) if writes else None
    method = re.fullmatch(r"(.*)\.(\w+)", text, re.DOTALL)
    if method is None or method.group(2).lower() not in _PS_METHOD_WRITES | {"replace"}:
        return None
    if method.group(2).lower() == "open" and _ps_open_is_read_only(written, False):
        return None
    owner = _ps_object_of(pieces, index, method.group(1))
    return _PsCall(method.group(2), stop, owner[0], owner[1], written) if owner else None


def _ps_property_writer(pieces: _Pieces, index: int) -> Optional[tuple[str, str, list[str]]]:
    """For the word at pieces[index], when it is an assignment to a property that changes the file or folder of an
    item (`$_.Attributes = ...`, `(Get-Item x).IsReadOnly = ...`; _PS_PROPERTY_RE): (the property, the text of the
    item, the arguments of the item objects made in place in front of it); None otherwise."""
    match = _PS_PROPERTY_RE.fullmatch(pieces[index][1])
    if match is None:
        return None
    following = pieces[index + 1] if index + 1 < len(pieces) else ("", "")
    if not match.group(3) and not (following[0] == "word" and re.match(r"\+?=(?!=)", following[1])):
        return None
    owner = _ps_object_of(pieces, index, match.group(1))
    return (match.group(2), owner[0], owner[1]) if owner else None


def ps_fed_writes(
    command: str, native_operands: Callable[[str, list[str]], Optional[list[str]]],
) -> Optional[list[PsFed]]:
    """The write or delete cmdlets of a PowerShell `command` that take their item from a list, each with the
    list commands that may feed it: those of the cmdlet's own statement before it or inside its own arguments
    (for `$_` also those in front of the script blocks around it), and those a variable it names was filled with
    (`foreach ($f in <list>)`, `$f = <list>`). A cmdlet is fed when it takes its item from the pipeline (no path
    of its own), names `$_`/`$PSItem`, holds a sub-expression, or names such a variable. `native_operands(name,
    args)` reads a `git`/`rg`/`grep` list command like Bash does (None: not a list, or one that is not
    understood). A `Get-Item`/`Get-ChildItem` of one name-only wildcard that cannot match `.act` is left out of the
    listers (and marked in `current_folder`) only when the command text changes no location and runs no command it
    does not show, and the write works on the item itself - the pipeline input, `$_`, a variable that holds it, a
    method of it, never an expression made of it (`$_.Directory`, `"$_.bak"`, `Join-Path`) - and is no `MoveTo`,
    `CopyTo` or `Replace`. None when the command does not tokenize."""
    pieces = _ps_pieces(command)
    if pieces is None:
        return None
    listers_at: list[tuple[int, Optional[list[str]], bool]] = []  # position, folders, a name-only wildcard (_ps_name_glob)
    for index, (kind, text) in enumerate(pieces):
        if kind != "word" or not _starts_command(pieces, index):
            continue
        name = _ps_command_name(text)
        args, _ = _ps_args(pieces, index + 1)
        if name in _PS_LISTERS:
            listers_at.append((index, _ps_lister_operands(args), _ps_name_glob(name, args)))
        elif name in ("rg", "grep") or (name == "git" and args[:1] in (["ls-files"], ["grep"], ["diff"])):
            listers_at.append((index, native_operands(name, args), False))
    assigned: dict[str, list[tuple[Optional[list[str]], bool]]] = {}
    objects: dict[str, list[str]] = {}  # `$o = [IO.FileInfo]::new(x)`: the argument of the item object a variable holds
    aliases: set[str] = set()  # `$f = $_` inside a script block: `$f` is the item of the pipeline like `$_`
    loop_variables: set[str] = set()  # `foreach ($f in <list>)`: `$f` is the item of the list
    for begin, (kind, text) in enumerate(pieces):  # `$files = <list>`, at the start of a statement
        match = re.fullmatch(r"\$(\w+)(\+?=?)", text) if kind == "word" and _starts_command(pieces, begin) else None
        if match and (match.group(2) in ("=", "+=") or (begin + 1 < len(pieces) and pieces[begin + 1][1] in ("=", "+="))):
            end = _local_end(pieces, begin)
            variable = match.group(1).lower()
            assigned.setdefault(variable, []).extend(
                (operands, glob) for at, operands, glob in listers_at if begin <= at < end)
            value = begin + 1 if match.group(2) else begin + 2  # the first piece of what is assigned
            if value < len(pieces) and pieces[value] == ("open", "("):
                value += 1  # `$o = (New-Object IO.FileInfo x)`
            if value < len(pieces):
                if pieces[value][1].lower() in ("$_", "$psitem") and _enclosing_blocks(pieces, begin):
                    aliases.add(variable)
                made = _ps_item_object(pieces, value)
                if made is not None:
                    objects.setdefault(variable, []).append(made[0])
    for index in range(len(pieces) - 3):  # `foreach ($f in <list>)`
        if (pieces[index][0] == "word" and pieces[index][1].lower() == "foreach" and pieces[index + 1] == ("open", "(")
                and pieces[index + 2][1].startswith("$") and pieces[index + 3] == ("word", "in")):
            close = _group_end(pieces, index + 1)
            loop_variables.add(pieces[index + 2][1][1:].lower())
            assigned.setdefault(pieces[index + 2][1][1:].lower(), []).extend(
                (operands, glob) for at, operands, glob in listers_at if index < at < close)
    found: list[PsFed] = []
    relief_possible = _PS_RELIEF_BLOCK_RE.search(command) is None
    held = {"$" + variable for variable in aliases | loop_variables}  # variables that are the item itself
    item_names = {"_", "psitem"} | set(assigned) | set(objects) | aliases  # variables an item flows through

    def variables_of(text: str) -> set[str]:
        return {variable.lower() for variable in re.findall(r"\$\{?(\w+)", text)}

    def is_item(text: str, narrow: bool) -> bool:
        """True when `text` is the item itself: `$_`, `$PSItem`, an alias of it or a `foreach` variable, a sub-expression
        that is nothing but a command, naming no item variable (`(Get-ChildItem *.log)`); `narrow` False also a
        variable a list or an item object filled. A property path, a concatenation, a call on it is an expression made of it."""
        low = text.strip().lower()
        if low in _PS_ITEM_VARIABLES or low in held:
            return True
        if re.fullmatch(r"[$@]?\([^|{};]*\)", low) and not variables_of(low) & item_names:
            return True
        return not narrow and low.startswith("$") and low[1:] in set(assigned) | set(objects)

    def judge(index: int, stop: int, name: str, targets: list[str], from_pipe: bool, made: list[str],
              call: Optional[_PsCall] = None) -> None:
        """Add the write at pieces[index] (its item texts `targets`, the statement it holds ending at `stop`, the
        arguments of the item objects `made` in place in front of it, the method call it is) when something feeds it:
        the pipeline in front of it, `$_` or a variable that holds it, a variable a list filled or an item object, a
        sub-expression, or an item object made in place."""
        variables = {variable.lower() for target in targets for variable in re.findall(r"\$\{?(\w+)", target)}
        filled = [variable for variable in variables if variable in assigned]
        sub = any(re.search(r"\$\(|@\(|^\(", target) for target in targets)
        current = any(re.search(r"\$_|\$PSItem", target, re.IGNORECASE) for target in targets) or bool(variables & aliases)
        items = made + [argument for variable in sorted(variables) for argument in objects.get(variable, [])]
        if not (from_pipe or sub or current or filled or items):
            return
        begin = _local_start(pieces, index)
        regions = [(begin, stop)]
        if current:  # `$_` is an item of the pipeline in front of each script block around the cmdlet
            regions += [(_local_start(pieces, block), block) for block in _enclosing_blocks(pieces, index)]
        entries = [(operands, glob) for first, last in regions for at, operands, glob in listers_at if first <= at < last]
        before = {variable.lower() for kind, text in pieces[begin:index] if kind == "word"
                  for variable in re.findall(r"\$\{?(\w+)", text)}  # `$files | ForEach-Object { ... }`
        for variable in filled + sorted(before & set(assigned) - set(filled)):
            entries += assigned[variable]
        low = name.lower()
        destinations: list[str] = []
        if call is not None and low in _PS_ARGUMENT_TARGETS:  # `MoveTo('x')`, `Replace('x', 'backup')`: written places
            parts = [_ps_unquote(part) for part in _ps_split_arguments(call.arguments)[:_PS_ARGUMENT_TARGETS[low]]]
            destinations = [part for part in parts if part and part.lower() != "$null"]
        if low == "replace":  # a string method as often as a file one: only a lister or an item object behind an item itself
            if is_item(targets[0], False) and (entries or items):
                found.append(PsFed(name, [], items, destinations=destinations))
            return
        relief = (relief_possible and low not in _PS_ARGUMENT_TARGETS
                  and all(is_item(target, True) or not (variables_of(target) & item_names or "(" in target)
                          for target in targets))
        found.append(PsFed(name, [operands for operands, glob in entries if relief is False or not glob],
                           items, destinations, relief and any(glob for operands, glob in entries)))

    for index, (kind, text) in enumerate(pieces):
        if kind != "word":
            continue
        call = _ps_call_writer(pieces, index)
        if call is not None:  # a .NET call or a method on an item (`[IO.File]::Delete($_.FullName)`, `$_.Delete()`)
            judge(index, call.stop, call.name, [call.text], False, call.made, call)
            continue
        prop = _ps_property_writer(pieces, index)
        if prop is not None:  # an assignment to a property of an item (`$_.Attributes = ...`)
            judge(index, index + 1, prop[0], [prop[1]], False, prop[2])
            continue
        name = _ps_command_name(text)
        writer = _ALIASES.get(name)
        if writer not in _PS_ITEM_WRITERS or not _starts_command(pieces, index):
            continue
        args, stop = _ps_args(pieces, index + 1)
        positionals, values = _ps_split_args(args)
        from_pipe = (writer in _PS_PIPE_FED and index > 0 and pieces[index - 1] == ("op", "|")
                     and not (positionals or values.get("path") or values.get("literalpath")))
        judge(index, stop, name, _cmdlet_targets(name, args), from_pipe, [])
    return found

