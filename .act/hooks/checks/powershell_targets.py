#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: PowerShell write-target scanner — the PowerShell counterpart of shell_targets.py, for
#          the same two callers (checks/write_guard.py check 1, checks/write_scope.py check 1c).
#          Claude Code on Windows offers a `PowerShell` tool next to `Bash` (tool_input.command,
#          live probe T34); both checks used to look at Bash only. This module answers the same
#          question shell_targets.py answers for Bash — which paths does a command write to — but
#          for PowerShell syntax, and with a deliberately different return shape:
#
#          _powershell_write_targets(command, base_cwd, git_writes, broad=False, depth=0)
#              -> set[str] | None
#
#          Bash's _bash_write_targets returns (raw, base) pairs because a Bash command can leave
#          several *possible* current directories active at the same point (an `||` list, a `cd`
#          inside a subshell) — resolution is deferred to the caller. A PowerShell script runs one
#          statement after another with exactly one current directory at any point, so this module
#          tracks it itself (Set-Location/cd/Push-Location) and resolves every target it can to an
#          absolute, forward-slash path before returning it; a target it cannot resolve (still
#          carries a variable/sub-expression, or its base directory turned unknown after an
#          unresolvable Set-Location) is returned as its own literal text instead — a caller can
#          tell the two apart with shell_targets._is_absolute_target/_is_dynamic_target exactly the
#          way it already does for a Bash target whose base came back None. Returns None instead of
#          a (possibly empty) set when the command as a whole is not safely evaluable this way
#          (Invoke-Expression/iex, an unterminated quote or here-string) — checks/write_guard.py
#          (check 1, "when in doubt, deny") then denies if _PROTECTED_PATH_RE matches anywhere in
#          the raw command text; checks/write_scope.py (check 1c) falls back to
#          _ps_raw_redirect_targets, the same operator-based fallback Bash's own scanner uses.
#
#          `broad` (2026-09-23 review, BLOCK) is check 1's own extra, deliberately over-inclusive
#          pass (see _broad_guard_candidates): every positional and every flag value — recognized
#          or not — of a call to a recognized write cmdlet, every word of a `$var = ...`
#          assignment's right-hand side, and every word of a statement using the call operator `&`
#          or a script block `{ ... }`, added as raw (unresolved) text candidates alongside the
#          precise ones. check 1c passes broad=False (the default) and stays exact — a worker's
#          write scope is enforced against the one real target, not against everything a command
#          merely mentions. `depth` caps pwsh/powershell -c/-Command recursion (see
#          _PS_INTERP_NAMES) the same way shell_targets._MAX_SCAN_DEPTH caps Bash's own recursion.
#
# Recognized as a write (see _ALIASES/_CD_ALIASES/_FLAG_ONLY_KEYS and _flush_ps_statement for the
# exact mapping):
#   - redirections `>`, `>>`, `*>`, `2>` (also `*>>`/`2>>`/`3>`.../a glued fd digit, harmless
#     extras) — but not a target that is itself just a stream duplication/null device, see
#     _ps_is_ignorable (`2>&1`, `2>$null`, `*> $null`, `> NUL`, `> nul:`);
#   - Set-Content/sc, Add-Content/ac, Clear-Content/clc, Set-Item/si, Rename-Item/ren/rni,
#     Export-Csv, Export-Clixml (-Path/-LiteralPath or 1st positional);
#   - Out-File, Tee-Object (-FilePath/-Path or 1st positional);
#   - New-Item/ni/mkdir/md (-Path and/or -Name, joined; 1st positional is -Path);
#   - Copy-Item/cp/copy/cpi, Move-Item/mv/move/mi (-Destination, or the 2nd positional — the 1st is
#     the source, never itself a target, unless -Path named the source explicitly, in which case
#     the sole remaining positional is the destination);
#   - Remove-Item/rm/del/ri/rd/rmdir/erase (every -Path/-LiteralPath value plus every positional);
#   - Expand-Archive (-DestinationPath); Invoke-WebRequest/iwr (-OutFile);
#   - [System.IO.File]/[IO.File]/[global::System.IO.File]::WriteAllText/WriteAllLines/
#     AppendAllText/AppendAllLines/WriteAllBytes/Copy/Move/Create(...) (1st argument), and
#     [...IO.StreamWriter]::new(...) (1st argument) — matched against the statement's words
#     rejoined with a single space each, so whitespace right after the opening "(" does not split
#     the match across two words;
#   - `git mv|rm|checkout|restore` (git_writes chooses which, same split as shell_targets.py: check
#     1 only mv/rm, check 1c also checkout/restore), via shell_targets._git_targets, reused as-is;
#   - `bash -c "..."` / `sh -c "..."`, scanned with shell_targets._bash_write_targets (the Bash
#     scanner); `cmd`/`cmd.exe /c "..."`, scanned the same way (an approximation — cmd.exe's own
#     redirect syntax is close enough to Bash's for `>`/`>>`/`2>`, not identical);
#   - `pwsh`/`powershell`(.exe) `-c`/`-Command "..."`, scanned recursively with *this* module
#     (still PowerShell syntax), up to _PS_MAX_SCAN_DEPTH deep;
#   - Set-Location/cd/sl/Push-Location updates the tracked current directory for what follows;
#     an unresolvable target (a variable, or nothing findable) makes it unknown from there on.
#   - check 1 only (`broad=True`, see _broad_guard_candidates): additionally, every word of a
#     Start-Process/Invoke-Command/python(3)/py invocation (their own write behaviour is opaque —
#     this is a literal-text net, not a resolved target), every word after `& $sb`/`& { ... }`
#     appearing anywhere in a statement, and every word to the right of `$var =`.
#
# Statement separators: `;`, `|`, a bare newline, `&&`/`||` (PS 7) — see _PS_SEPARATOR_OPS.
# Quoting: '...' verbatim except '' -> a literal '; "..." with a backtick as the escape character
# and "" -> a literal " (both PowerShell rules); a backtick followed by a newline is a line
# continuation (dropped, not a separator); an unquoted "#" starts a comment to the end of the
# line (PowerShell has no Bash-style "start of word" restriction on it); @'...'@ / @"..."@
# here-strings become a single opaque word each — their content is never scanned as commands or
# redirections and never enters a `broad` candidate either (see _is_here_string_word), which is
# also why `> .act/x` written *inside* a here-string body is not read as a redirection or a write.
#
# Known limits (a target missed here is simply not checked — see the two _ALIASES gaps noted
# above for Copy-Item/Move-Item in mixed positional/named form, beyond the one `-Path`-as-source
# shape this module does understand):
#   - Invoke-Expression/iex anywhere in the command makes the whole command bail to None — what it
#     runs is opaque to a syntactic scan, but check 1 still denies if the raw command text mentions
#     .act/ anywhere (see this module's docstring and checks/write_guard.py);
#   - a target built from a variable ($var, $env:X) or a sub-expression ($(...)) is never resolved
#     — kept as its own literal text, denied only if that text itself names .act/ (check 1) or is
#     out of scope by definition (check 1c, same as an unresolved Bash target); a Join-Path/other
#     expression call is not evaluated either, only caught (check 1 only) via `broad`'s literal-text
#     net over the call's own positionals/flag values, or its assignment's right-hand side;
#   - a comma-separated array argument (`-Path a,b`) is read as one glued word, not two targets;
#   - an abbreviated/partial parameter name (`-Fi` for `-FilePath`) is not matched to its flag —
#     it is dropped as an unrecognized switch, which usually still leaves its value as a stray
#     positional (recovered by the cmdlet's own positional fallback) rather than lost outright;
#   - only the literal fd number "2" is gated like Bash's fd-glue special case (`file2>x` stays one
#     word) for the length-3/gated length-2 operators; another digit glued the same way (`file3>x`)
#     is read as a generic `>` at that position — `3>` on its own (nothing accumulated yet) is still
#     recognized as a redirection, just via the ungated ">" match, same end result.

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .shell_targets import (
    _GIT_WRITES_WORKER_SCOPE,
    _bash_write_targets,
    _git_targets,
    _is_dynamic_target,
    _to_native_path,
)

__all__ = [
    "_PS_OPERATORS_LEN3", "_PS_OPERATORS_LEN2", "_PS_OPERATORS_LEN2_GATED", "_PS_OPERATORS_LEN1",
    "_PS_REDIRECT_OPS", "_PS_SEPARATOR_OPS", "_PS_VALUE_FLAGS", "_ALIASES", "_CD_ALIASES",
    "_FLAG_ONLY_KEYS", "_PS_INTERP_NAMES", "_CMD_NAMES", "_GUARD_OPAQUE_ALL_ARGS",
    "_GUARD_OPAQUE_DASH_C", "_BROAD_EXCLUDE_VALUE_FLAGS", "_BROAD_SKIP_KINDS", "_IEX_WORDS",
    "_IO_FILE_WRITE_RE", "_IO_FILE_COPY_MOVE_RE",
    "_IO_STREAMWRITER_RE", "_PS_IGNORABLE_RE", "_PS_RAW_REDIRECT_RE", "_PS_MAX_SCAN_DEPTH", "_Token",
    "_match_ps_operator", "_consume_here_string", "_ps_tokens", "_uses_invoke_expression",
    "_ps_command_name", "_ps_split_args", "_target_from_flags", "_target_destination",
    "_target_new_item", "_targets_remove", "_cmdlet_targets", "_extract_dash_c",
    "_extract_ps_command_flag", "_extract_cmd_c", "_ps_is_ignorable", "_is_here_string_word",
    "_broad_guard_candidates", "_resolve_ps_target", "_resolve_cd_target", "_flush_ps_statement",
    "_scan_ps_tokens", "_ps_raw_redirect_targets", "_powershell_write_targets",
]

_Token = tuple[str, bool]  # (text, is_operator) — same shape as shell_targets._Token

# Redirect-style operators, grouped by how they are matched (see _match_ps_operator): the length-3
# and length-2-gated ones only count as an operator right at the start of a fresh word (`word`
# empty) — otherwise "file2>x"/"abc*>x" would lose their leading digit/"*" into the operator, the
# same fd-glue problem shell_targets.py solves differently (post-hoc, via a token stream) because
# this scanner works character by character instead.
_PS_OPERATORS_LEN3 = ("*>>", "2>>")          # gated
_PS_OPERATORS_LEN2 = (">>", "&&", "||")      # ungated
_PS_OPERATORS_LEN2_GATED = ("*>", "2>")      # gated
_PS_OPERATORS_LEN1 = (">", "|", ";")         # ungated
_PS_REDIRECT_OPS = frozenset({">", ">>", "*>", "*>>", "2>", "2>>"})
_PS_SEPARATOR_OPS = frozenset({";", "|", "&&", "||", "\n"})

# Flags whose next word (space or ":" form) is a value, never a switch — see _ps_split_args.
# 2026-09-23 review (BLOCK): a flag missing here shifts every later positional by one, which can
# both miss a real target and (for check 1c) misjudge an unrelated word as the target instead —
# widened past what this module's own extraction functions read, to whatever a write cmdlet in
# _ALIASES/_FLAG_ONLY_KEYS plausibly takes, so the shift itself cannot happen.
_PS_VALUE_FLAGS = frozenset({
    "path", "literalpath", "destination", "filepath", "name", "newname", "value", "itemtype",
    "encoding", "delimiter", "width", "filter", "include", "exclude", "stream", "credential",
    "destinationpath", "outfile", "argumentlist", "scriptblock", "type",
})

# lower-cased cmdlet/alias name -> extraction kind, dispatched in _cmdlet_targets.
_ALIASES = {
    "set-content": "path_target", "sc": "path_target",
    "add-content": "path_target", "ac": "path_target",
    "clear-content": "path_target", "clc": "path_target",
    "set-item": "path_target", "si": "path_target",
    "rename-item": "path_target", "ren": "path_target", "rni": "path_target",
    "export-csv": "path_target", "export-clixml": "path_target",
    "out-file": "outfile",
    "tee-object": "outfile",
    "new-item": "newitem", "ni": "newitem", "mkdir": "newitem", "md": "newitem",
    "copy-item": "destination2nd", "cp": "destination2nd", "copy": "destination2nd", "cpi": "destination2nd",
    "move-item": "destination2nd", "mv": "destination2nd", "move": "destination2nd", "mi": "destination2nd",
    "remove-item": "all_operands", "rm": "all_operands", "del": "all_operands", "ri": "all_operands",
    "rd": "all_operands", "rmdir": "all_operands", "erase": "all_operands",
    "expand-archive": "flag_only",
    "invoke-webrequest": "flag_only", "iwr": "flag_only",
}
_CD_ALIASES = frozenset({"cd", "set-location", "sl", "push-location"})
_IEX_WORDS = frozenset({"invoke-expression", "iex"})

# kind == "flag_only": the target is exactly this flag's value, no positional fallback at all (an
# Expand-Archive/Invoke-WebRequest call with none named simply writes nowhere this module can name).
_FLAG_ONLY_KEYS = {
    "expand-archive": ("destinationpath",),
    "invoke-webrequest": ("outfile",),
    "iwr": ("outfile",),
}

# check 1 only (`broad`): a call to one of these is opaque — its own write behaviour cannot be
# read from its arguments — so every argument word is added as a raw literal-text candidate
# instead of a resolved target (2026-09-23 review: Start-Process/Invoke-Command each carry a
# string/script-block argument that is itself effectively a second command line).
_GUARD_OPAQUE_ALL_ARGS = frozenset({"start-process", "invoke-command"})
# check 1 only (`broad`): narrower than the above — only the value of an actual `-c` flag is
# opaque-scanned, not every argument, so `python some_script.py` (the script's own writes are
# invisible here regardless, same as any external program — see the module docstring's known
# limits) does not get every one of its arguments treated as a literal .act/ candidate merely for
# being python's own arguments.
_GUARD_OPAQUE_DASH_C = frozenset({"python", "python3", "py"})
# check 1 only (`broad`): a flag value that names something other than a write target and must
# not become a candidate merely by co-occurring with a recognized write cmdlet — Rename-Item's
# -NewName is a bare leaf name, not the item being changed (that is -Path/the positional, already
# a candidate); a -NewName value that happened to read ".act" would otherwise falsely deny.
_BROAD_EXCLUDE_VALUE_FLAGS = {"rename-item": {"newname"}, "ren": {"newname"}, "rni": {"newname"}}
# check 1 only (`broad`): kinds whose *precise* extraction already picks the one real target out
# of two "positional-shaped" candidates (Copy-Item/Move-Item: source then destination) — widening
# to "every positional" here would turn the source (being read, not written) into a false positive.
_BROAD_SKIP_KINDS = frozenset({"destination2nd"})

_IO_FILE_WRITE_RE = re.compile(
    r"\[(?:global::)?(?:System\.)?IO\.File\]::"
    r"(?:WriteAllText|WriteAllLines|AppendAllText|AppendAllLines|WriteAllBytes|Create)"
    r"\(\s*([^,)]+)",
    re.IGNORECASE,
)
# File.Copy(sourceFileName, destFileName)/File.Move(...): the *2nd* argument is the target, unlike
# every other File method above (1st argument) — a separate pattern, not a shared capture group.
_IO_FILE_COPY_MOVE_RE = re.compile(
    r"\[(?:global::)?(?:System\.)?IO\.File\]::(?:Copy|Move)\(\s*[^,]+,\s*([^,)]+)",
    re.IGNORECASE,
)
_IO_STREAMWRITER_RE = re.compile(
    r"\[(?:global::)?(?:System\.)?IO\.StreamWriter\]::new\(\s*([^,)]+)",
    re.IGNORECASE,
)

# A redirect target that names a stream duplication or the null device, never a file — the
# PowerShell analogue of shell_targets._IGNORABLE_TARGETS (`2>&1`, `2>$null`, `> NUL`, `> nul:`).
# "&1"/"&2"/... reaches here as its own word: "2>&1" tokenizes to the operator "2>" (see
# _match_ps_operator) followed by the plain word "&1" ("&" alone is not itself an operator in this
# module's operator set, see _PS_OPERATORS_LEN2/_PS_OPERATORS_LEN1, so it is read as an ordinary
# character and stays glued to the following digit).
_PS_IGNORABLE_RE = re.compile(r"^(?:\$null|nul:?|&\d+)$", re.IGNORECASE)

# check 1 only (`broad`): a here-string word (see _is_here_string_word) is exactly the delimiters
# plus its raw, never-executed body — added as its own word only so ordinary scanning can skip
# past it as one unit; broad candidates must never repeat that body's contents as if they were
# real command text (that is the whole point of a here-string, see the module docstring's FP case).
_HERE_STRING_PREFIXES = ("@'", '@"')

# pwsh/powershell(.exe) -c/-Command "..." recurse into *this* scanner (still PowerShell syntax);
# cmd/cmd.exe /c "..." recurse into shell_targets' Bash scanner as a close-enough approximation.
_PS_INTERP_NAMES = frozenset({"pwsh", "powershell"})
_CMD_NAMES = frozenset({"cmd"})
_PS_MAX_SCAN_DEPTH = 4

# Last-resort raw-text scan (see _ps_raw_redirect_targets), the PowerShell twin of
# shell_targets._RAW_REDIRECT_RE: every word right after a redirect-style operator anywhere in the
# raw text, fd/`*` gating not attempted (raw text has no word boundaries to check against).
_PS_RAW_REDIRECT_RE = re.compile(r"(?:2>>|2>|\*>>|\*>|>>|>)\s*([^\s;|&]+)")


def _match_ps_operator(command: str, index: int, word_is_empty: bool) -> Optional[str]:
    """The operator token starting at `command[index]`, longest match first, or None. The
    length-3/length-2-gated groups (leading digit or "*") only match when `word_is_empty` — see
    the comment above _PS_OPERATORS_LEN3 for why."""
    if word_is_empty:
        for op in _PS_OPERATORS_LEN3:
            if command.startswith(op, index):
                return op
    for op in _PS_OPERATORS_LEN2:
        if command.startswith(op, index):
            return op
    if word_is_empty:
        for op in _PS_OPERATORS_LEN2_GATED:
            if command.startswith(op, index):
                return op
    for op in _PS_OPERATORS_LEN1:
        if command.startswith(op, index):
            return op
    return None


def _consume_here_string(command: str, index: int) -> Optional[tuple[str, int]]:
    """`command[index]` is the "@" of an @'...'@ / @"..."@ here-string opener. Returns (word_text,
    index_after) with the *whole* here-string (open marker, content, close marker) folded into one
    opaque word — its content is never re-scanned as commands (see the module docstring) — or None
    if it is not actually followed by a newline (not a valid here-string opener; the "@" is then
    just an ordinary character to the caller) or no terminator line is ever found (bails the whole
    command, the same "cannot place it safely" response as an unterminated ordinary quote)."""
    quote = command[index + 1]
    newline = command.find("\n", index)
    if newline == -1 or command[index + 2:newline].strip(" \t\r"):
        return None  # not a real here-string opener: needs nothing but whitespace before the newline
    terminator = quote + "@"
    content_start = newline + 1
    pos = content_start
    while True:
        line_end = command.find("\n", pos)
        line = command[pos:line_end if line_end != -1 else len(command)]
        if line.lstrip(" \t").startswith(terminator):
            term_offset = pos + (len(line) - len(line.lstrip(" \t")))
            return command[index:term_offset + len(terminator)], term_offset + len(terminator)
        if line_end == -1:
            return None  # no terminator line anywhere -> unsafe, caller bails the whole command
        pos = line_end + 1


def _ps_tokens(command: str) -> Optional[list[_Token]]:
    """Tokenize a PowerShell command into (text, is_operator) pairs. None if a quote or a
    here-string is never closed — the command is then not safely evaluable (see the module
    docstring's None contract)."""
    tokens: list[_Token] = []
    word: list[str] = []
    i = 0
    n = len(command)

    def flush() -> None:
        if word:
            tokens.append(("".join(word), False))
            word.clear()

    while i < n:
        ch = command[i]
        if ch == "`" and i + 1 < n and command[i + 1] in "\r\n":
            i += 2
            if command[i - 1] == "\r" and i < n and command[i] == "\n":
                i += 1
            continue
        if ch == "`" and i + 1 < n:
            word.append(command[i + 1])
            i += 2
            continue
        if ch == "'":
            j = i + 1
            buf: list[str] = []
            closed = False
            while j < n:
                if command[j] == "'":
                    if j + 1 < n and command[j + 1] == "'":
                        buf.append("'")
                        j += 2
                        continue
                    j += 1
                    closed = True
                    break
                buf.append(command[j])
                j += 1
            if not closed:
                return None
            word.append("".join(buf))
            i = j
            continue
        if ch == '"':
            j = i + 1
            buf = []
            closed = False
            while j < n:
                c = command[j]
                if c == "`" and j + 1 < n:
                    buf.append(command[j + 1])
                    j += 2
                    continue
                if c == '"':
                    if j + 1 < n and command[j + 1] == '"':
                        buf.append('"')
                        j += 2
                        continue
                    j += 1
                    closed = True
                    break
                buf.append(c)
                j += 1
            if not closed:
                return None
            word.append("".join(buf))
            i = j
            continue
        if ch == "@" and i + 1 < n and command[i + 1] in "'\"":
            here = _consume_here_string(command, i)
            if here is not None:
                text, end = here
                word.append(text)
                i = end
                continue
            if command.find("\n", i) != -1:
                # looked like an opener but never closed -> unsafe, see _consume_here_string
                return None
            # else: no newline anywhere left -> not actually an opener, ordinary "@" character
        if ch == "#":
            flush()
            newline = command.find("\n", i)
            i = newline if newline != -1 else n
            continue
        if ch in " \t":
            flush()
            i += 1
            continue
        if ch == "\r":
            i += 1
            continue
        if ch == "\n":
            flush()
            tokens.append(("\n", True))
            i += 1
            continue
        op = _match_ps_operator(command, i, not word)
        if op is not None:
            flush()
            tokens.append((op, True))
            i += len(op)
            continue
        word.append(ch)
        i += 1
    flush()
    return tokens


def _uses_invoke_expression(tokens: list[_Token]) -> bool:
    """True if any word (in any position, not just a statement's first) is exactly
    Invoke-Expression/iex — see the module docstring's None contract."""
    return any(not is_op and text.lower() in _IEX_WORDS for text, is_op in tokens)


def _ps_command_name(word: str) -> str:
    name = word.replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name[:-4] if name.endswith(".exe") else name


def _ps_split_args(args: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    """Split a cmdlet's arguments into positionals and the values of _PS_VALUE_FLAGS ("-Path X",
    "-Path:X"). Any other "-Flag" is treated as a switch — dropped, not added to positionals, its
    value (if any) not consumed, so an abbreviated/unrecognized flag's value usually still survives
    as a stray positional rather than being lost outright (see the module docstring's known limits)."""
    positionals: list[str] = []
    values: dict[str, list[str]] = {}
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith("-") and len(arg) > 1:
            body = arg[1:]
            if ":" in body:
                key, _, val = body.partition(":")
                if key.lower() in _PS_VALUE_FLAGS:
                    values.setdefault(key.lower(), []).append(val)
                i += 1
                continue
            key = body.lower()
            if key in _PS_VALUE_FLAGS:
                if i + 1 < len(args):
                    values.setdefault(key, []).append(args[i + 1])
                    i += 2
                else:
                    i += 1
                continue
            i += 1  # unrecognized flag: a switch, simply dropped
            continue
        positionals.append(arg)
        i += 1
    return positionals, values


def _target_from_flags(
    positionals: list[str], values: dict[str, list[str]], flag_keys: tuple[str, ...],
    allow_positional_fallback: bool = True,
) -> Optional[str]:
    for key in flag_keys:
        vals = values.get(key)
        if vals:
            return vals[0]
    return positionals[0] if allow_positional_fallback and positionals else None


def _target_destination(positionals: list[str], values: dict[str, list[str]]) -> Optional[str]:
    """Copy-Item/Move-Item: -Destination, else the 2nd positional (the 1st is the source and not
    itself a target — see the module docstring). If the source was instead named via -Path/
    -LiteralPath, the sole remaining positional is the destination (2026-09-23 review: `Copy-Item
    -Path a .act/x` was missed entirely before this)."""
    vals = values.get("destination")
    if vals:
        return vals[0]
    if values.get("path") or values.get("literalpath"):
        return positionals[0] if positionals else None
    return positionals[1] if len(positionals) >= 2 else None


def _target_new_item(positionals: list[str], values: dict[str, list[str]]) -> list[str]:
    path = (values.get("path") or [None])[0] or (positionals[0] if positionals else None)
    name = (values.get("name") or [None])[0]
    if path and name:
        return [path.replace("\\", "/").rstrip("/") + "/" + name]
    if path:
        return [path]
    if name:
        return [name]
    return []


def _targets_remove(positionals: list[str], values: dict[str, list[str]]) -> list[str]:
    return list(values.get("path") or []) + list(values.get("literalpath") or []) + list(positionals)


def _cmdlet_targets(name: str, args: list[str]) -> list[str]:
    kind = _ALIASES.get(name)
    if kind is None:
        return []
    positionals, values = _ps_split_args(args)
    if kind == "path_target":
        target = _target_from_flags(positionals, values, ("path", "literalpath"))
        return [target] if target else []
    if kind == "outfile":
        target = _target_from_flags(positionals, values, ("filepath", "path"))
        return [target] if target else []
    if kind == "newitem":
        return _target_new_item(positionals, values)
    if kind == "destination2nd":
        target = _target_destination(positionals, values)
        return [target] if target else []
    if kind == "all_operands":
        return _targets_remove(positionals, values)
    if kind == "flag_only":
        target = _target_from_flags(positionals, values, _FLAG_ONLY_KEYS[name], allow_positional_fallback=False)
        return [target] if target else []
    return []  # pragma: no cover — every _ALIASES value has a branch above


def _extract_dash_c(args: list[str]) -> Optional[str]:
    for index, arg in enumerate(args):
        if arg == "-c" and index + 1 < len(args):
            return args[index + 1]
    return None


def _extract_ps_command_flag(args: list[str]) -> Optional[str]:
    """pwsh/powershell(.exe) `-c`/`-Command <script>` — the script string, or None."""
    for index, arg in enumerate(args):
        if arg.lower() in ("-c", "-command") and index + 1 < len(args):
            return args[index + 1]
    return None


def _extract_cmd_c(args: list[str]) -> Optional[str]:
    """cmd/cmd.exe `/c <command>` (also accepts "-c", cmd.exe understands both) — the command
    string, or None."""
    for index, arg in enumerate(args):
        if arg.lower() in ("/c", "-c") and index + 1 < len(args):
            return args[index + 1]
    return None


def _ps_is_ignorable(raw: str) -> bool:
    return bool(_PS_IGNORABLE_RE.match(raw.strip()))


def _is_here_string_word(word: str) -> bool:
    return word.startswith(_HERE_STRING_PREFIXES)


def _broad_guard_candidates(words: list[str]) -> list[str]:
    """Extra, deliberately over-inclusive raw-text candidates for check 1 (write_guard) only — see
    the module docstring's `broad` paragraph and the _GUARD_OPAQUE_CMDLETS/_BROAD_EXCLUDE_VALUE_
    FLAGS/_BROAD_SKIP_KINDS comments for the exceptions. Never includes a here-string word (its
    content is not command text, see _is_here_string_word) or an ignorable target (_ps_is_ignorable
    — filtered by the caller, _flush_ps_statement, the same way a precise target is)."""
    if not words:
        return []
    candidates: list[str] = []
    effective = words
    if len(words) >= 2 and words[0].startswith("$") and words[1] == "=":
        candidates.extend(words[2:])
        effective = words[2:]
    if any(w in ("&", "{", "}") for w in words):
        candidates.extend(words)
    if effective:
        name = _ps_command_name(effective[0])
        kind = _ALIASES.get(name)
        if name in _GUARD_OPAQUE_ALL_ARGS:
            candidates.extend(effective[1:])
        elif name in _GUARD_OPAQUE_DASH_C:
            value = _extract_dash_c(effective[1:])
            if value is not None:
                candidates.append(value)
        elif kind is not None and kind not in _BROAD_SKIP_KINDS:
            positionals, values = _ps_split_args(effective[1:])
            excluded = _BROAD_EXCLUDE_VALUE_FLAGS.get(name, frozenset())
            candidates.extend(positionals)
            for key, vals in values.items():
                if key not in excluded:
                    candidates.extend(vals)
    return [c for c in candidates if c and not _is_here_string_word(c)]


def _resolve_ps_target(raw: Optional[str], cwd: Optional[str]) -> Optional[str]:
    """`raw` resolved to an absolute, forward-slash path against `cwd` — or `raw` itself,
    unresolved, when it is dynamic, `cwd` is unknown, or resolution fails outright (see the module
    docstring for how a caller tells the two apart). None for a falsy `raw`, or one that names a
    stream duplication/the null device rather than a file (_ps_is_ignorable)."""
    if not raw or _ps_is_ignorable(raw):
        return None
    if _is_dynamic_target(raw):
        return raw
    native = _to_native_path(raw)
    try:
        path = Path(native)
        if not path.is_absolute():
            if cwd is None:
                return raw
            path = Path(_to_native_path(cwd)) / native
        return path.resolve().as_posix()
    except (OSError, ValueError):
        return raw


def _resolve_cd_target(target: Optional[str], cwd: Optional[str]) -> Optional[str]:
    """The new tracked current directory after Set-Location/cd/Push-Location to `target` — an
    absolute native path string, or None if it cannot be pinned down (no/dynamic target, or a
    relative one while `cwd` is already unknown) — see _flush_ps_statement."""
    if not target or _is_dynamic_target(target):
        return None
    native = _to_native_path(target)
    try:
        path = Path(native)
        if not path.is_absolute():
            if cwd is None:
                return None
            path = Path(_to_native_path(cwd)) / native
        return str(path.resolve())
    except (OSError, ValueError):
        return None


def _flush_ps_statement(
    words: list[str], redirect_targets: list[str], cwd: Optional[str], base_cwd: str,
    git_writes: frozenset, result: set[str], broad: bool, depth: int,
) -> Optional[str]:
    """Handle one statement (its words and any redirection targets collected for it), add every
    write target it names to `result`, and return the (possibly changed) current directory for the
    statement after it. See the module docstring for which cmdlets/constructs are recognized, and
    for what `broad`/`depth` do."""
    for raw in redirect_targets:
        resolved = _resolve_ps_target(raw, cwd)
        if resolved:
            result.add(resolved)
    if words:
        name = _ps_command_name(words[0])
        args = words[1:]
        if name in _CD_ALIASES:
            positionals, values = _ps_split_args(args)
            target = _target_from_flags(positionals, values, ("path", "literalpath"))
            cwd = _resolve_cd_target(target, cwd)
        elif name == "git":
            for raw, base in _git_targets(args, frozenset({cwd}), git_writes):
                resolved = raw if (base is None or _is_dynamic_target(raw)) else _resolve_ps_target(raw, base)
                if resolved:
                    result.add(resolved)
        elif name in ("bash", "sh"):
            inner = _extract_dash_c(args)
            if inner is not None:
                for raw, base in _bash_write_targets(inner, cwd if cwd is not None else base_cwd, git_writes):
                    resolved = raw if (base is None or _is_dynamic_target(raw)) else _resolve_ps_target(raw, base)
                    if resolved:
                        result.add(resolved)
        elif name in _CMD_NAMES or name in _PS_INTERP_NAMES:
            # cmd.exe's own quoting/variable syntax is not identical to PowerShell's, but its
            # redirect operators and backslash-as-separator convention are — much closer to this
            # module's own tokenizer than to Bash's (which reads "\x" as an escaped "x", silently
            # corrupting a Windows path; 2026-09-23 review fix). Recursed with this same scanner
            # for both, not shell_targets' Bash one.
            inner = _extract_cmd_c(args) if name in _CMD_NAMES else _extract_ps_command_flag(args)
            if inner is not None and depth < _PS_MAX_SCAN_DEPTH:
                inner_targets = _powershell_write_targets(
                    inner, cwd if cwd is not None else base_cwd, git_writes, broad, depth + 1
                )
                if inner_targets:
                    result.update(inner_targets)
        else:
            for raw in _cmdlet_targets(name, args):
                resolved = _resolve_ps_target(raw, cwd)
                if resolved:
                    result.add(resolved)
        if broad:
            for raw in _broad_guard_candidates(words):
                candidate = raw.strip()
                if candidate and not _ps_is_ignorable(candidate):
                    result.add(candidate)
    joined = " ".join(words + redirect_targets)
    for pattern in (_IO_FILE_WRITE_RE, _IO_FILE_COPY_MOVE_RE, _IO_STREAMWRITER_RE):
        for match in pattern.finditer(joined):
            resolved = _resolve_ps_target(match.group(1).strip(), cwd)
            if resolved:
                result.add(resolved)
    return cwd


def _scan_ps_tokens(
    tokens: list[_Token], base_cwd: str, git_writes: frozenset, broad: bool, depth: int
) -> set[str]:
    result: set[str] = set()
    cwd: Optional[str] = base_cwd
    words: list[str] = []
    redirect_targets: list[str] = []
    index = 0
    n = len(tokens)
    while True:
        at_end = index >= n
        text, is_op = tokens[index] if not at_end else ("", True)
        if not at_end and not is_op:
            words.append(text)
            index += 1
            continue
        if not at_end and text in _PS_REDIRECT_OPS:
            if index + 1 < n and not tokens[index + 1][1]:
                redirect_targets.append(tokens[index + 1][0])
                index += 2
            else:
                index += 1
            continue
        if words or redirect_targets:
            cwd = _flush_ps_statement(words, redirect_targets, cwd, base_cwd, git_writes, result, broad, depth)
            words = []
            redirect_targets = []
        if at_end:
            return result
        index += 1


def _ps_raw_redirect_targets(command: str) -> set[str]:
    """Coarse last resort for a command _powershell_write_targets returned None for (an
    unterminated quote/here-string, Invoke-Expression/iex): every word right after a redirect-style
    operator anywhere in the raw text, quotes stripped off its ends — the PowerShell twin of
    shell_targets._raw_redirect_targets, over-inclusive by design. Used by checks/write_scope.py's
    own None fallback (check 1c stays "the same way as the Bash fallback" — checks/write_guard.py's check 1
    instead searches the whole raw command text directly, see this module's docstring)."""
    return {match.group(1).strip("'\"") for match in _PS_RAW_REDIRECT_RE.finditer(command)}


def _powershell_write_targets(
    command: str, base_cwd: str, git_writes: frozenset = _GIT_WRITES_WORKER_SCOPE,
    broad: bool = False, depth: int = 0,
) -> Optional[set[str]]:
    """The paths a PowerShell command writes to, each already resolved to an absolute forward-slash
    path where possible (see the module docstring for what an unresolved entry looks like instead),
    or None when the command is not safely evaluable this way at all (Invoke-Expression/iex, an
    unterminated quote or here-string) — see the module docstring for what each caller does then.
    `git_writes` is the same choice of git subcommands shell_targets._bash_write_targets takes
    (_GIT_WRITES_TEMPLATE_GUARD for check 1, _GIT_WRITES_WORKER_SCOPE for check 1c); `broad` and
    `depth` are documented in the module docstring's `broad` paragraph."""
    try:
        tokens = _ps_tokens(command)
        if tokens is None or _uses_invoke_expression(tokens):
            return None
        return _scan_ps_tokens(tokens, base_cwd, git_writes, broad, depth)
    except Exception:
        # A bug in this scanner must never turn into a silent allow (dispatch.py's docstring,
        # "when in doubt, deny"): None makes the caller fall back to its own raw-text search.
        return None
