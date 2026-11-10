#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: PowerShell write-target scanner — the PowerShell counterpart of shell_targets.py, for
#          the same two callers (checks/write_guard.py check 1, checks/write_scope.py check 1c).
#          Claude Code on Windows offers a `PowerShell` tool next to `Bash` (tool_input.command,
#          seen in a live probe); both checks used to look at Bash only. This module
#          answers the same question shell_targets.py answers for Bash — which paths does a
#          command
#          write to — but for PowerShell syntax, and with a deliberately different return shape:
#
#          _powershell_write_targets(command, base_cwd, git_writes, broad=False, depth=0)
#              -> set[str] | None
#
#          Bash's _bash_write_targets returns (raw, base) pairs because a Bash command can leave
#          several *possible* current directories active at the same point (an `||` list, a `cd`
#          inside a subshell) — resolution is deferred to the caller. A PowerShell script runs one
#          statement after another, but a directory change may fail and the script goes on, so this
#          module tracks the small set of directories the shell may be in itself (Set-Location/cd/
#          Push-Location/pushd/chdir, Pop-Location/popd; see _follow_cd and _TrackedDirs) and resolves
#          every target it can, against each of them, to an
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
#   - Out-File, Tee-Object and its alias `tee` (-FilePath/-Path/-LiteralPath or 1st positional; the value
#     of `-Variable` is no file);
#   - New-Item/ni/mkdir/md (-Path and/or -Name, joined; 1st positional is -Path);
#   - Copy-Item/cp/copy/cpi, Move-Item/mv/move/mi (-Destination, or the 2nd positional — the 1st is
#     the source, never itself a target, unless -Path named the source explicitly, in which case
#     the sole remaining positional is the destination). Move-Item also counts its source (-Path/
#     -LiteralPath, else the first positional; every positional when -Destination is named): the move
#     removes it, as Bash `mv` counts its sources;
#   - Remove-Item/rm/del/ri/rd/rmdir/erase (every -Path/-LiteralPath value plus every positional);
#   - Expand-Archive (-DestinationPath); Invoke-WebRequest/iwr (-OutFile);
#   - [System.IO.File]/[IO.File]/[global::System.IO.File]::WriteAllText/WriteAllLines/
#     AppendAllText/AppendAllLines/WriteAllBytes/CreateText/AppendText/OpenWrite/Create/Delete(...) (1st argument),
#     File::Copy/Move and Directory::Move (2nd argument), Directory::Delete/CreateDirectory (1st argument), and
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
#   - `wsl`/`wsl.exe [options] [--] <command line>`, scanned with shell_targets._wsl_targets: the line
#     runs inside WSL, where `/mnt/<x>/...` is drive <X>: (nowhere else in the command);
#   - Set-Location/cd/sl/chdir/Push-Location/pushd update the tracked current directories for what follows
#     (_follow_cd): a move to a literal directory that exists moves each tracked directory; a move to one
#     that does not exist (yet — an earlier statement may create it) or to a dynamic target keeps the old
#     directory next to the new one (or next to "unknown"), since a failed move only reports an error and
#     the script goes on; Pop-Location/popd and `Set-Location -`/`+` make every directory seen so far
#     possible again. A directory at or below a target collected earlier in the same command (removed,
#     moved, copied over) counts as missing too: the move may fail. A directory made earlier in the command by
#     a literal `New-Item -ItemType Directory`/`mkdir`/`md` that certainly runs (first in the command or behind
#     `;`/a line break, outside any script block or condition) counts as existing (_ps_directory_creation,
#     _TrackedDirs.note_created) and is no written place; a removal or move after it still wins. The set stays small
#     (_MAX_TRACKED_DIRECTORIES): past the cap the followed directory, "unknown", the directories confirmed
#     to exist and the shortest paths are kept, and from then on every relative target also comes back as
#     the one target no check may place (_unplaced_target, refused by every check that reads this module).
#     Next to the set, the one directory this module followed before it tracked a set (cd/sl/Set-Location/
#     Push-Location, moved whether the target exists or not) is still followed and is never dropped, so no
#     target found that way is lost (_TrackedDirs). A nested PowerShell scan (`pwsh -c`, a script piped in)
#     runs once, from the tracked set; the work of one command, nested scans included, is bounded
#     (_RESOLUTION_BUDGET) — past the bound the whole command is that one unplaceable target.
#   - native programs of the Bash table (`touch`, `sed -i`, `tar -x`, `find -delete`, `chmod`, `curl.exe -o`,
#     `git clone` ...), read by their arguments with shell_targets._simple_command_targets; a name that is also
#     a cmdlet alias keeps its cmdlet reading, and `curl`/`wget` without `.exe` (Invoke-WebRequest aliases in
#     Windows PowerShell 5.1) add the file of `-OutFile` as well;
#   - inline interpreter code (`python -c`, a literal piped into `python -`): its write calls are read once and
#     resolved against every directory the call may run in; a crash of that reader comes back as one dynamic
#     target holding the command text, never as an empty answer.
#   - check 1 only (`broad=True`, see _broad_guard_candidates): additionally, every word of a
#     Start-Process/Invoke-Command/python(3)/py invocation (their own write behaviour is opaque —
#     this is a literal-text net, not a resolved target), every word after `& $sb`/`& { ... }`
#     appearing anywhere in a statement, and every word to the right of `$var =`.
#
# Statement separators: `;`, `|`, a bare newline, `&&`/`||` (PS 7) — see _ps_tokens.
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

import functools
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

from . import inline_code as _inline_code
from .common import MAX_NESTING, _is_unplaced_target, _unplaced_reason, _unplaced_target  # noqa: F401 - re-exported
from . import shell_targets as _shell_targets  # the module itself, for the rsync flag it holds while scanning
from .shell_targets import (
    _GIT_WRITES_WORKER_SCOPE,
    _bash_write_targets,
    _creation_keys,
    _place_at_or_below,
    _expand_directory_wildcard,
    _git_targets,
    _attribute_targets,
    _is_absolute_target,
    _ALL_OPERAND_WRITERS,
    _LAST_OPERAND_WRITERS,
    _is_dynamic_target,
    _is_remote_unc,
    _perl_inplace_targets,
    _ps_reads_stdin,
    _reads_script_from_stdin,
    _resolve_path,
    _robocopy_targets,
    _simple_command_targets,
    _to_native_path,
    _wsl_targets,
)

__all__ = [
    "_PS_OPERATORS_LEN3", "_PS_OPERATORS_LEN2", "_PS_OPERATORS_LEN2_GATED", "_PS_OPERATORS_LEN1",
    "_PS_REDIRECT_OPS", "_PS_VALUE_FLAGS", "_ALIASES", "_CD_ALIASES",
    "_FLAG_ONLY_KEYS", "_PS_INTERP_NAMES", "_CMD_NAMES", "_GUARD_OPAQUE_ALL_ARGS",
    "_GUARD_OPAQUE_DASH_C", "_BROAD_EXCLUDE_VALUE_FLAGS", "_BROAD_SKIP_KINDS", "_IEX_WORDS",
    "_IO_FILE_WRITE_RE", "_IO_FILE_COPY_MOVE_RE",
    "_IO_STREAMWRITER_RE", "_PS_IGNORABLE_RE", "_PS_RAW_REDIRECT_RE", "_PS_MAX_SCAN_DEPTH", "_Token",
    "_match_ps_operator", "_consume_here_string", "_ps_tokens", "_uses_invoke_expression",
    "_ps_command_name", "_ps_split_args", "_target_from_flags", "_target_destination",
    "_target_new_item", "_targets_remove", "_cmdlet_targets", "_extract_dash_c",
    "_extract_ps_command_flag", "_ps_word_lists", "_extract_cmd_c", "_ps_is_ignorable", "_is_here_string_word",
    "_broad_guard_candidates", "_resolve_ps_target", "_resolve_ps_targets", "_resolve_cd_target",
    "_join_directory", "_directory_exists", "_place_key", "_TrackedDirs", "_follow_cd", "_flush_ps_statement",
    "_scan_ps_tokens", "_ps_raw_redirect_targets", "_powershell_write_targets",
    "_PsInlineTarget", "_powershell_inline_code_targets", "_MAX_TRACKED_DIRECTORIES", "_RESOLUTION_BUDGET",
    "_unplaced_target", "_is_unplaced_target", "_unplaced_reason", "_ScanLimit", "_ScanBudget", "_InlineSink",
    "_collect_ps_inline", "_inline_sink_targets", "_scan_ps_inline",
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

# Flags whose next word (space or ":" form) is a value, never a switch — see _ps_split_args.
# 2026-09-23 review (BLOCK): a flag missing here shifts every later positional by one, which can
# both miss a real target and (for check 1c) misjudge an unrelated word as the target instead —
# widened past what this module's own extraction functions read, to whatever a write cmdlet in
# _ALIASES/_FLAG_ONLY_KEYS plausibly takes, so the shift itself cannot happen.
_PS_VALUE_FLAGS = frozenset({
    "path", "literalpath", "destination", "filepath", "name", "newname", "value", "itemtype",
    "encoding", "delimiter", "width", "filter", "include", "exclude", "stream", "credential",
    "destinationpath", "outfile", "argumentlist", "scriptblock", "type", "variable",
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
    "tee-object": "outfile", "tee": "outfile",
    "new-item": "newitem", "ni": "newitem", "mkdir": "newitem", "md": "newitem",
    "copy-item": "destination2nd", "cp": "destination2nd", "copy": "destination2nd", "cpi": "destination2nd",
    "move-item": "move", "mv": "move", "move": "move", "mi": "move",
    "robocopy": "robocopy", "perl": "perl_inplace", "ruby": "perl_inplace",
    "chmod": "attribute", "chown": "attribute", "chgrp": "attribute",
    "remove-item": "all_operands", "rm": "all_operands", "del": "all_operands", "ri": "all_operands",
    "rd": "all_operands", "rmdir": "all_operands", "erase": "all_operands",
    "expand-archive": "flag_only",
    "invoke-webrequest": "flag_only", "iwr": "flag_only",
}
# `pushd` and `chdir` are PowerShell aliases of Push-Location and Set-Location. The scan tracks the directories the
# shell may be in (_follow_cd, _TrackedDirs): a move to a literal directory that exists moves them; a move to a
# missing or dynamic one keeps the old directory next to the new one, since the move may fail (a missing directory
# is a non-terminating error and the script goes on); Pop-Location/`popd`/`Set-Location -`/`+` add every
# directory seen so far back.
# Native programs (Git for Windows ships them, `curl.exe` and `tar.exe` come with Windows) that write files and
# that the Bash scanner reads by their arguments: the same table serves here, so `touch f`, `sed -i s/a/b/ f`,
# `curl.exe -o f url`, `tar -xf a.tar -C d` give the same targets under PowerShell as under Bash. A name that is
# also a cmdlet alias (`cp`, `mv`, `rm`, `mkdir`, `rmdir`) keeps its cmdlet reading (_ALIASES).
_NATIVE_WRITERS = (
    (_ALL_OPERAND_WRITERS | _LAST_OPERAND_WRITERS | frozenset({"sed", "dd", "tar", "unzip", "find", "curl", "wget"}))
    - frozenset(_ALIASES)
)
_CD_ALIASES = frozenset({"cd", "chdir", "set-location", "sl", "push-location", "pushd"})
# The names this module followed as one current directory before it tracked a set (`pushd` and `chdir` were not
# among them, and a move counted whether the target existed or not). That one directory is still followed the same
# way next to the set (_TrackedDirs.followed), so nothing found before is lost.
_CD_ALIASES_FOLLOWED = frozenset({"cd", "set-location", "sl", "push-location"})
# Windows PowerShell 5.1 aliases of Invoke-WebRequest (`curl.exe` and `wget.exe` are the programs).
_WEB_ALIASES = frozenset({"curl", "wget"})
_POP_ALIASES = frozenset({"pop-location", "popd"})
# The most directories tracked at once (_follow_cd). Every target of a statement is resolved against each of
# them, so the cap bounds the cost of a long chain of directory changes; past it the followed directory,
# "unknown" (None), the directories confirmed to exist and the shortest paths stay, the rest is dropped — and
# from then on every relative target also comes back as the one target no check may place (_unplaced_target),
# since the directory it is relative to may be a dropped one (_TrackedDirs.capped).
_MAX_TRACKED_DIRECTORIES = 24
# How much work one scan of a command may do — statements, resolutions of a target against a directory,
# directory changes followed, nested scans — counted by _ScanBudget in units and shared with every nested scan:
# a step that only looks something up costs one unit, a file-system round trip (_TrackedDirs.resolve,
# _TrackedDirs.followed_after) _RESOLUTION_COST. Past the budget the command comes back as the one target no
# check may place, the way a scanner crash is refused: a command no one writes by hand is refused rather than
# checked only in part.
_RESOLUTION_BUDGET = 100_000
_RESOLUTION_COST = 5
_TOO_DEEP = f"command text nested deeper than {MAX_NESTING} levels"
_LOST_DIRECTORY = "a directory the shell may be in was dropped past the cap of tracked directories"
_BUDGET_USED_UP = "the command is larger than the scan follows (its resolution budget is used up)"
_IEX_WORDS = frozenset({"invoke-expression", "iex"})

# (path literal, the directory it resolves against or None when unknown, interpreter language)
_PsInlineTarget = tuple[str, Optional[str], str]


class _ScanLimit(RuntimeError):
    """One scan used up its budget (_RESOLUTION_BUDGET): _powershell_write_targets turns it into the target
    no check may place (_unplaced_target); a nested scan lets it through to the top-level one."""


@dataclass
class _ScanBudget:
    """The work one scan of a command may still do (_RESOLUTION_BUDGET), shared by every state the scan
    goes through, nested scans included."""

    left: int = _RESOLUTION_BUDGET

    def charge(self, cost: int = 1) -> None:
        self.left -= cost
        if self.left < 0:
            raise _ScanLimit(_BUDGET_USED_UP)


@dataclass
class _InlineSink:
    """Where the walk of the statements puts the path literals of inline interpreter code (_collect_ps_inline).
    `swallow` says what a failure of the reader does: noted in `failed` and the walk goes on (the targets scan,
    which then reports one dynamic target for the command), or it propagates (the worker write scope's own
    reading, which reports it)."""

    swallow: bool = False
    failed: bool = False
    found: list[_PsInlineTarget] = field(default_factory=list)

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
_BROAD_SKIP_KINDS = frozenset({"destination2nd", "robocopy", "perl_inplace"})

_IO_FILE_WRITE_RE = re.compile(
    r"\[(?:global::)?(?:System\.)?IO\.File\]::"
    r"(?:WriteAllText|WriteAllLines|AppendAllText|AppendAllLines|WriteAllBytes|CreateText|AppendText|OpenWrite|Create|Delete)"
    r"\(\s*([^,)]+)",
    re.IGNORECASE,
)
# Directory.Delete(path[, recursive])/Directory.CreateDirectory(path): the 1st argument.
_IO_DIRECTORY_WRITE_RE = re.compile(
    r"\[(?:global::)?(?:System\.)?IO\.Directory\]::(?:Delete|CreateDirectory)\(\s*([^,)]+)",
    re.IGNORECASE,
)
# File.Copy(sourceFileName, destFileName)/File.Move(...) and Directory.Move: the *2nd* argument is the target, unlike
# every other File method above (1st argument) — a separate pattern, not a shared capture group.
# File.Move and Directory.Move also take the 1st argument away (the source), like Move-Item.
_IO_MOVE_SOURCE_RE = re.compile(
    r"\[(?:global::)?(?:System\.)?IO\.(?:File|Directory)\]::Move\(\s*([^,)]+)",
    re.IGNORECASE,
)
_IO_FILE_COPY_MOVE_RE = re.compile(
    r"\[(?:global::)?(?:System\.)?IO\.(?:File\]::(?:Copy|Move)|Directory\]::Move)\(\s*[^,]+,\s*([^,)]+)",
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
_PS_MAX_SCAN_DEPTH = MAX_NESTING

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


def _expand_outfile_flag(args: list[str]) -> list[str]:
    """`args` with every abbreviation of `-OutFile` (`-o`, `-Out`, `-OutF:x`) written out in full, as PowerShell
    reads a unique prefix of a parameter name; over-inclusive for `-o` (ambiguous in PowerShell itself)."""
    expanded: list[str] = []
    for arg in args:
        if arg.startswith("-") and len(arg) > 1:
            key, separator, value = arg[1:].partition(":")
            if key and "outfile".startswith(key.lower()):
                arg = f"-outfile{separator}{value}"
        expanded.append(arg)
    return expanded


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


def _targets_move(positionals: list[str], values: dict[str, list[str]]) -> list[str]:
    """Move-Item: the destination (as Copy-Item reads it) and the source, which the move changes too -
    Bash `mv` counts its sources the same way. The source is -Path/-LiteralPath, else the first positional
    (every positional when -Destination names the destination)."""
    destination = _target_destination(positionals, values)
    named = list(values.get("path", [])) + list(values.get("literalpath", []))
    if values.get("destination"):
        sources = positionals
    elif named:
        sources = positionals[1:]
    else:
        sources = positionals[:1]
    return ([destination] if destination else []) + named + list(sources)


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


# A directory made by a `New-Item -ItemType Directory`/`mkdir`/`md` statement earlier in the same command counts as
# existing for a later `cd` to the same place (_TrackedDirs.note_created): the scan runs before the command does,
# so the folder is not on disk yet. An allowlist: exactly these creation commands with a literal path.
_PS_CREATED_DIR_RE = re.compile(r"^(?:[A-Za-z]:)?[\w./\\ +@-]+$")
_PS_CREATION_UNSAFE_WORDS = frozenset({
    "if", "elseif", "else", "foreach", "for", "while", "until", "do", "switch", "try", "catch", "finally",
    "function", "filter", "trap",
})
# `-WhatIf` and `-Confirm` (and every abbreviation PowerShell accepts) make the cmdlet create nothing, or ask first.
_PS_NO_EFFECT_FLAGS = ("whatif", "confirm")


def _ps_directory_creation(name: str, args: list[str]) -> Optional[tuple[list[str], bool]]:
    """(the literal paths, whether the missing parents are made too) of a statement that creates directories:
    `New-Item`/`ni` with `-ItemType`/`-Type` `Directory` (or `dir`), `mkdir`/`md`; None for anything else, a path
    that is not a plain literal (a variable, a wildcard, a list `a,b`, a provider path `env:X`) and a call
    with `-WhatIf`/`-Confirm`."""
    if _ALIASES.get(name) != "newitem":
        return None
    for arg in args:
        if arg.startswith("-") and len(arg) > 1:
            flag = arg[1:].partition(":")[0].lower()
            if flag and (any(word.startswith(flag) for word in _PS_NO_EFFECT_FLAGS) or flag in ("cf", "wi")):
                return None
    positionals, values = _ps_split_args(args)
    kinds = [str(kind).lower() for kind in values.get("itemtype", []) + values.get("type", [])]
    if name in ("mkdir", "md"):
        if kinds:
            return None
        parents = sys.platform == "win32"  # the function makes the parents too; a native `mkdir` elsewhere does not
    else:
        if len(kinds) != 1 or kinds[0] not in ("directory", "dir"):
            return None
        parents = True
    raws = _target_new_item(positionals, values)
    if not raws or any(_is_dynamic_target(raw) or not _PS_CREATED_DIR_RE.match(raw) for raw in raws):
        return None
    return raws, parents


def _cmdlet_targets(name: str, args: list[str]) -> list[str]:
    kind = _ALIASES.get(name)
    if kind is None:
        return []
    positionals, values = _ps_split_args(args)
    if kind == "path_target":
        target = _target_from_flags(positionals, values, ("path", "literalpath"))
        return [target] if target else []
    if kind == "outfile":
        target = _target_from_flags(positionals, values, ("filepath", "path", "literalpath"))
        return [target] if target else []
    if kind == "newitem":
        return _target_new_item(positionals, values)
    if kind == "destination2nd":
        target = _target_destination(positionals, values)
        return [target] if target else []
    if kind == "move":
        return _targets_move(positionals, values)
    if kind == "robocopy":
        return _robocopy_targets(args)
    if kind == "perl_inplace":
        return _perl_inplace_targets(args, name)
    if kind == "attribute":
        return _attribute_targets(name, args)
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


def _ps_word_lists(command: str, depth: int = 0) -> list[list[str]]:
    """The simple commands of a PowerShell command line as word lists, read with PowerShell's own
    tokenizer (a backslash is a path separator there, not an escape), including the text behind a
    nested `pwsh -Command`; empty when the line cannot be tokenized (an unterminated quote). A crash of
    the tokenizer is not caught here: check_secret_read refuses the call for it."""
    tokens = _ps_tokens(command)
    if tokens is None:
        return []
    lists: list[list[str]] = []
    words: list[str] = []
    for text, is_operator in [*tokens, ("", True)]:
        if not is_operator:
            words.append(text)
            continue
        if words:
            lists.append(words)
            if depth < 2:
                inner = _extract_ps_command_flag(words[1:])
                if inner:
                    lists.extend(_ps_word_lists(inner, depth + 1))
        words = []
    return lists


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


def _strip_literal_call(words: list[str]) -> list[str]:
    """`& <literal program> args...` read as the direct call `<program> args...`: the call operator at
    the start of a statement followed by a plain word (a program name or a path, quotes already
    removed by the tokenizer). A dynamic program (`& $var`, `& (expr)`, `& { ... }`, `& @splat`, any
    word containing `$`) is left alone, so the caller still treats it
    as an opaque call; the statement's arguments are then checked like those of a direct call."""
    if len(words) < 2 or words[0] != "&":
        return words
    program = words[1]
    if not program or program[0] in "({@$&-" or "$" in program or "(" in program or program in ("{", "}"):
        return words
    return words[1:]


# `$name = <program> args...` with one of these programs is read as the call `<program> args...` alone by the
# statement handlers (_strip_program_assignment). For check 1 (broad), the words right of the `=` stay
# candidates as before, minus the few words that name what the program only reads (_assigned_read_words).
_PS_ASSIGNED_PROGRAMS = frozenset({"py", "python", "python3", "git"})
_PS_PYTHON_PROGRAMS = frozenset({"py", "python", "python3"})
_PS_ASSIGN_VAR_RE = re.compile(r"^\$(?:\w+:)?\w+$")
_PS_PROGRAM_WORD_RE = re.compile(r"^[\w.:/\ -]+$")
# An argument that cannot start another command or build a list of words: no sub-expression, script block,
# array comma, escape or statement separator. One that can keeps the whole assignment under the
# over-inclusive reading.
_PS_PLAIN_ARG_RE = re.compile(r"^[^(){}`;,]*$")
# Interpreter options that take no value and cannot run other code (`-3`, `-3.12`, `-u`, `-B` ...): the first
# word after them is the script. `-m`, `-c` and options with a value (`-X`, `-W`) are not among them.
_PS_PYTHON_PLAIN_OPTION_RE = re.compile(r"^-(?:\d(?:\.\d+)?(?:-\d+)?|[uBOEsSIqdvb]+)$")
# git subcommands that only read the repository; their path and revision words are no write target.
_PS_GIT_READ_SUBCOMMANDS = frozenset({"log", "diff", "show", "status", "blame", "ls-files", "rev-parse", "grep"})


def _strip_program_assignment(words: list[str]) -> tuple[list[str], list[str]]:
    """`$name = <program> args...` split into (the call `<program> args...` alone, the words right of the `=`
    that stay over-inclusive candidates for check 1). The call alone is what the statement handlers read
    (its redirections, `git mv`, ...), for a program of _PS_ASSIGNED_PROGRAMS with plain arguments
    (_PS_PLAIN_ARG_RE). The candidates are every word right of the `=` except those _assigned_read_words
    names - the script of a python call, the path and revision words of a read-only git call. Anything
    else - a cmdlet, a string, an expression, a call operator, a sub-expression or array among the
    arguments - is returned as it is, with no extra candidates (the whole statement is read as before)."""
    if len(words) < 3 or words[1] != "=" or not _PS_ASSIGN_VAR_RE.match(words[0]):
        return words, []
    program = words[2]
    if not _PS_PROGRAM_WORD_RE.match(program) or _ps_command_name(program) not in _PS_ASSIGNED_PROGRAMS:
        return words, []
    if not all(_PS_PLAIN_ARG_RE.match(word) for word in words[3:]):
        return words, []
    dropped = _assigned_read_words(words[2:])
    return words[2:], [word for index, word in enumerate(words[2:]) if index not in dropped]


def _assigned_read_words(call: list[str]) -> frozenset[int]:
    """Indexes in `call` (program word first) of the words that are no write target: the script word of
    `py|python|python3 [plain interpreter options] <script> ...` (never with `-m`, `-c` or an option with a
    value), and the non-option words (paths, revisions) of `git <log|diff|show|status|blame|ls-files|
    rev-parse|grep> ...` without `-o` or `--output*`. Empty for every other call."""
    name = _ps_command_name(call[0])
    if name in _PS_PYTHON_PROGRAMS:
        for index in range(1, len(call)):
            word = call[index]
            if _PS_PYTHON_PLAIN_OPTION_RE.match(word):
                continue
            return frozenset() if word.startswith("-") else frozenset({index})
        return frozenset()
    if name == "git" and len(call) > 1 and call[1] in _PS_GIT_READ_SUBCOMMANDS:
        options = call[2:]
        if any(
            word.startswith("--output") or word == "-o" or (word.startswith("-") and not word.startswith("--") and "o" in word[1:])
            for word in options
        ):
            return frozenset()
        return frozenset(index for index in range(2, len(call)) if not call[index].startswith("-"))
    return frozenset()


def _block_script_words(words: list[str]) -> frozenset[int]:
    """Indexes in `words` of the script word of a plain `py|python|python3 [plain options] <script> args...`
    call that starts the statement or follows a `{` (the body of a loop or script block, which the scanner
    reads as one statement with the `{`/`}` words in it): the script is only run, as it is without the loop
    (_assigned_read_words). Allow-list: the call ends at the next word holding a brace, and every word of it
    must be a plain argument (_PS_PLAIN_ARG_RE); any other call keeps every word a candidate."""
    skipped: set[int] = set()
    for index, word in enumerate(words):
        if index and words[index - 1] != "{":
            continue
        if not _PS_PROGRAM_WORD_RE.match(word) or _ps_command_name(word) not in _PS_PYTHON_PROGRAMS:
            continue
        end = next((i for i in range(index + 1, len(words)) if "{" in words[i] or "}" in words[i]), len(words))
        call = words[index:end]
        if all(_PS_PLAIN_ARG_RE.match(arg) for arg in call[1:]):
            skipped.update(index + offset for offset in _assigned_read_words(call))
    return frozenset(skipped)


def _assigned_git_invocations(word_lists: list[list[str]]) -> list[tuple[list[str], list[str]]]:
    """The git calls of PowerShell statements (`word_lists`, as _ps_word_lists reads them) that sit behind a
    variable assignment (`$null = git config core.hooksPath x`, `$r = git commit -m x`), as (prefix, argv)
    pairs the way the Bash word reader hands out its git calls (Parse.git_invocations_with_prefix): that
    reader takes `$r` for the command there and never sees the git call. The assignment is cut off by
    _strip_program_assignment, the helper the write scan uses, so both read the same forms."""
    found: list[tuple[list[str], list[str]]] = []
    for words in word_lists:
        call = _strip_literal_call(words)
        stripped, _ = _strip_program_assignment(call)
        if stripped is not call and stripped and _ps_command_name(stripped[0]) == "git":
            found.append(([], stripped[1:]))
    return found


def _broad_guard_candidates(words: list[str]) -> list[str]:
    """Extra, deliberately over-inclusive raw-text candidates for check 1 (write_guard) only — see
    the module docstring's `broad` paragraph and the _GUARD_OPAQUE_CMDLETS/_BROAD_EXCLUDE_VALUE_
    FLAGS/_BROAD_SKIP_KINDS comments for the exceptions. Never includes a here-string word (its
    content is not command text, see _is_here_string_word) or an ignorable target (_ps_is_ignorable
    — filtered by the caller, _flush_ps_statement, the same way a precise target is)."""
    if not words:
        return []
    candidates: list[str] = []
    words = _strip_literal_call(words)
    effective = words
    if len(words) >= 2 and words[0].startswith("$") and words[1] == "=":
        effective = _strip_literal_call(words[2:])
        words = words[:2] + effective
        candidates.extend(effective)
    if any(w in ("&", "{", "}") for w in words):
        skipped = _block_script_words(words)
        candidates.extend(word for index, word in enumerate(words) if index not in skipped)
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
    stream duplication/the null device rather than a file (_ps_is_ignorable). A file-system round trip
    (_resolve_path): the scan asks it once per (target, directory) through _TrackedDirs.resolve."""
    if not raw or _ps_is_ignorable(raw):
        return None
    if _is_dynamic_target(raw):
        return raw
    if not _is_absolute_target(raw) and cwd is None:
        return raw
    resolved = _resolve_path(raw, cwd)
    return resolved.as_posix() if resolved is not None else raw


def _resolve_ps_targets(raw: Optional[str], tracked: "_TrackedDirs", note: bool = True) -> set[str]:
    """_resolve_ps_target for every directory the shell may be in (`tracked.possible`): a dynamic or
    absolute `raw` is resolved once (no directory takes part), a relative one against each of them
    (itself, unresolved, for the unknown directory None) — and, once a tracked directory was dropped at
    the cap (`tracked.capped`), also as the target no check may place (_unplaced_target), since the
    directory it is relative to may be a dropped one. Empty for a falsy or ignorable `raw`. Every answer
    is noted as a written place (_TrackedDirs.note_written) unless `note` is False (a directory a statement only
    creates takes nothing away)."""
    if not raw or _ps_is_ignorable(raw):
        return set()
    raw = str(raw)
    found: set[str] = set()
    if _is_dynamic_target(raw) or _is_absolute_target(raw):
        resolved = tracked.resolve(raw, None)
        if resolved:
            found.add(str(resolved))
    else:
        for cwd in tracked.possible:
            resolved = tracked.resolve(raw, cwd)
            if resolved:
                found.add(str(resolved))
        if tracked.capped:
            found.add(_unplaced_target(_LOST_DIRECTORY))
    if note:
        tracked.note_written(found)
    return found


def _add_resolved_pairs(
    pairs: Iterable[tuple[str, Optional[str]]], result: set[str], tracked: "_TrackedDirs"
) -> None:
    """Add the (raw target, base directory) pairs a shell_targets helper returns to `result`, each resolved
    against its base — the raw text itself for a dynamic target or an unknown base; a relative target also
    as the target no check may place once a tracked directory was dropped at the cap (_resolve_ps_targets)."""
    found: set[str] = set()
    for raw, base in pairs:
        text = str(raw)
        if base is None or _is_dynamic_target(text):
            tracked.budget.charge()
            resolved: Optional[str] = text
        else:
            resolved = tracked.resolve(text, base)
        if resolved:
            found.add(str(resolved))
        if tracked.capped and not _is_dynamic_target(text) and not _is_absolute_target(text):
            found.add(_unplaced_target(_LOST_DIRECTORY))
    tracked.note_written(found)
    tracked.note_filed(found)
    result.update(found)


def _effective_bases(cwds: frozenset, base_cwd: str) -> list[str]:
    """The distinct directories a nested Bash scan (`bash -c`, a script piped into `bash`) runs in: each tracked
    directory, `base_cwd` standing in for the unknown one (None), sorted so the scan order is stable. A nested
    PowerShell scan does not take this road: it starts from the tracked set itself (_powershell_write_targets
    with `start`)."""
    return sorted({cwd if cwd is not None else base_cwd for cwd in cwds})


def _resolve_cd_target(target: Optional[str], cwd: Optional[str]) -> Optional[str]:
    """The new tracked current directory after Set-Location/cd/Push-Location to `target` — an
    absolute native path string, or None if it cannot be pinned down (no/dynamic target, or a
    relative one while `cwd` is already unknown) — the reading of the one followed directory, see
    _follow_cd."""
    if not target or _is_dynamic_target(target):
        return None
    if not _is_absolute_target(target) and cwd is None:
        return None
    resolved = _resolve_path(target, cwd)
    return str(resolved) if resolved is not None else None


# A directory operand PowerShell reads as a wildcard pattern: `-Path` (and a bare operand) does, `-LiteralPath` does not.
_PS_WILDCARD_RE = re.compile(r"[*?\[]")


def _wildcard_directories(target: str, cwd: Optional[str], budget: _ScanBudget) -> Optional[list[str]]:
    """The directories (absolute native paths, sorted) a wildcard `target` names when `cwd` is the current
    directory (shell_targets._expand_directory_wildcard); empty when none matches, None when it cannot be told
    (a relative target while `cwd` is unknown, a share on another host, too many candidates)."""
    joined = _join_directory(target, cwd)
    if joined is None:
        return None
    budget.charge(_RESOLUTION_COST)
    return _expand_directory_wildcard(joined)


@functools.lru_cache(maxsize=8192)
def _join_directory(target: Optional[str], cwd: Optional[str]) -> Optional[str]:
    """`target` joined onto `cwd` as one absolute native path, lexically (`.`/`..` collapsed, no file-system
    round trip — the write targets read against it are resolved for real later, see _resolve_ps_target),
    or None when it cannot be placed (no or dynamic target, a relative one while `cwd` is unknown). The
    cheap reading _follow_cd uses for the set of possible directories, where every statement may add
    many of them; a pure function of its arguments, so its answers are kept."""
    if not target or _is_dynamic_target(target):
        return None
    try:
        candidate = Path(_to_native_path(target))
        if not candidate.is_absolute():
            if cwd is None:
                return None
            candidate = Path(_to_native_path(cwd)) / candidate
        return os.path.normpath(str(candidate))
    except (OSError, ValueError):
        return None


def _directory_exists(path: str, known: dict[str, bool]) -> bool:
    """True when `path` is a directory on this machine now; `known` keeps the answers of one scan (nothing
    runs between them: a command is scanned before it runs), and a path below a directory known to be
    missing is missing too, without asking. A UNC path to another host is never asked (a network round
    trip from a hook, see shell_targets._is_remote_unc) and counts as not known to exist. Whether an
    earlier statement of the same command took the directory away is a separate question
    (_TrackedDirs.is_written)."""
    answer = known.get(path)
    if answer is not None:
        return answer
    parent = os.path.dirname(path)
    if parent and parent != path and known.get(parent) is False:
        answer = False
    else:
        try:
            answer = not _is_remote_unc(Path(path)) and os.path.isdir(path)
        except (OSError, ValueError):
            answer = False
    known[path] = answer
    return answer


def _place_key(target: str) -> Optional[str]:
    """`target` (an absolute path in any spelling) as the key a written place is kept under: native, `.`/`..`
    collapsed, case folded as this file system folds it; None for a relative or dynamic target, which names no
    place of its own."""
    if not target or _is_dynamic_target(target) or not _is_absolute_target(target):
        return None
    try:
        return os.path.normcase(os.path.normpath(_to_native_path(target)))
    except (OSError, ValueError):
        return None


@dataclass(frozen=True)
class _TrackedDirs:
    """The directories a PowerShell script may be in at one point of the scan. `possible` is the set every
    target is resolved against (None = unknown); `followed` is the one directory this module followed before
    it tracked a set (cd/sl/Set-Location/Push-Location, moved whether the target exists or not, None once a
    move could not be placed) and is always in `possible`, so no target found that way is lost; `seen` is
    every directory that was possible so far, what Pop-Location and `Set-Location -` go back to; `confirmed`
    is every directory a move found existing (and not written earlier in the command) — what the cap keeps
    first; `capped` says that a directory was dropped at the cap, from then on every relative target also
    comes back as the one no check may place (_unplaced_target). `known` (the existence answers,
    _directory_exists), `moves` (where the followed directory went from where), `written` (the places the
    targets collected so far name, see is_written), `resolved` (the answers of _resolve_ps_target, see
    resolve) and `budget` (the work left to this scan, _ScanBudget) are shared by every state the scan goes
    through, nested scans included: the file system does not change in between."""

    followed: Optional[str]
    possible: frozenset
    seen: frozenset
    confirmed: frozenset = frozenset()
    capped: bool = False
    known: dict[str, bool] = field(default_factory=dict, compare=False, repr=False)
    moves: dict[tuple[Optional[str], Optional[str]], Optional[str]] = field(
        default_factory=dict, compare=False, repr=False
    )
    written: set[str] = field(default_factory=set, compare=False, repr=False)
    resolved: dict[tuple[str, Optional[str]], Optional[str]] = field(default_factory=dict, compare=False, repr=False)
    budget: _ScanBudget = field(default_factory=_ScanBudget, compare=False, repr=False)
    created: set[str] = field(default_factory=set, compare=False, repr=False)
    recreated: set[str] = field(default_factory=set, compare=False, repr=False)  # created again after a target
    filed: set[str] = field(default_factory=set, compare=False, repr=False)  # places a command may have made a file at

    @classmethod
    def start(cls, base_cwd: str) -> "_TrackedDirs":
        return cls(base_cwd, frozenset({base_cwd}), frozenset({base_cwd}), frozenset({base_cwd}))

    def followed_after(self, target: Optional[str]) -> Optional[str]:
        """Where the followed directory is after a move to `target` (_resolve_cd_target, a file-system
        round trip per path segment on Windows), asked once per (target, directory) in this scan."""
        key = (target, self.followed)
        if key not in self.moves:
            self.budget.charge(_RESOLUTION_COST)
            self.moves[key] = _resolve_cd_target(target, self.followed)
        return self.moves[key]

    def resolve(self, raw: str, cwd: Optional[str]) -> Optional[str]:
        """_resolve_ps_target, asked once per (target, directory) in this scan: the same target is resolved
        against the same directory many times while the shell may be in several directories, and the file
        system does not change while a command is scanned. A round trip costs the budget _RESOLUTION_COST,
        a kept answer one unit."""
        key = (raw, cwd)
        if key in self.resolved:
            self.budget.charge()
            return self.resolved[key]
        self.budget.charge(_RESOLUTION_COST)
        answer = _resolve_ps_target(raw, cwd)
        self.resolved[key] = answer
        return answer

    def moved_to(
        self, followed: Optional[str], possible: Iterable[Optional[str]], confirmed: Iterable[str] = ()
    ) -> "_TrackedDirs":
        """The state after a move: `possible` plus `followed`, capped at _MAX_TRACKED_DIRECTORIES — past the
        cap the followed directory and the unknown one (None, when it is there) stay in any case, then the
        directories confirmed to exist, shortest first, then the shortest of the rest; dropping any marks
        the state `capped` for good. `seen` grows by everything that was possible, `confirmed` by what
        this move confirmed."""
        merged = frozenset(possible) | {followed}
        confirmed_dirs = self.confirmed | frozenset(confirmed)
        capped = self.capped
        if len(merged) > _MAX_TRACKED_DIRECTORIES:
            pinned = frozenset({followed}) | (merged & frozenset({None}))
            rest = sorted(
                (p for p in merged if p not in pinned), key=lambda p: (p not in confirmed_dirs, len(p), p)
            )
            merged = pinned | frozenset(rest[:_MAX_TRACKED_DIRECTORIES - len(pinned)])
            capped = True
        return _TrackedDirs(
            followed, merged, self.seen | merged, confirmed_dirs, capped,
            self.known, self.moves, self.written, self.resolved, self.budget, self.created, self.recreated,
            self.filed,
        )

    def note_written(self, targets: Iterable[str]) -> None:
        """Remember the places the absolute targets among `targets` name (is_written)."""
        for target in targets:
            key = _place_key(target)
            if key is not None:
                self.written.add(key)
                if self.recreated:  # a removal after the creation wins again
                    self.recreated.difference_update([place for place in self.recreated if _place_at_or_below(place, key)])

    def note_created(self, raws: Iterable[str], parents: bool) -> None:
        """Remember the places a statement that certainly runs and creates the directories `raws` makes in each
        directory the shell may be in (is_created): those among them _directory_creatable accepts. One a target
        named before (a removal, a move) is made again then: it exists (is_written leaves it out)."""
        made = _creation_keys(list(raws), parents, self.possible, self.is_created, _to_native_path)
        self.created.update(made)
        # A place a command made a file at (a move or copy to it, a redirection, `Set-Content`) is not made again:
        # the creation fails there and a move after it stays where it was.
        self.recreated.update(key for key in made if key in self.written and key not in self.filed)

    def note_filed(self, targets: Iterable[str], removal: bool = False) -> None:
        """The absolute `targets` of one statement: places it may have made a file at, or (`removal`) took away, so
        that an earlier file there no longer stands in the way of a creation."""
        for target in targets:
            key = _place_key(target)
            if key is not None:
                self.filed.discard(key) if removal else self.filed.add(key)

    def is_created(self, directory: str) -> bool:
        """True when `directory` (an absolute native path) is a place a creation noted (note_created) makes, or a
        parent of one: it counts as existing for a move there, unless is_written says it is taken away again."""
        if not self.created:
            return False
        key = os.path.normcase(os.path.normpath(directory))
        prefix = key.rstrip("\\/") + os.sep
        return any(made == key or made.startswith(prefix) for made in self.created)

    def is_written(self, directory: str) -> bool:
        """True when `directory` (an absolute native path) is at or below a place a target collected so far
        names: a removal, a move or a copy earlier in the same command may have taken it away or changed it,
        so a move there may fail and the shell stay where it was — the directory counts as missing then
        (_follow_cd keeps the old directory next to the new one). Not so for a place a certain creation made again
        after that (note_created): it exists, what lies below it does not."""
        key = os.path.normcase(os.path.normpath(directory))
        made_again = key in self.recreated
        while True:
            if key in self.written and not made_again:
                return True
            made_again = False
            parent = os.path.dirname(key)
            if not parent or parent == key:
                return False
            key = parent


def _follow_cd(statement: list[str], tracked: _TrackedDirs) -> Optional[_TrackedDirs]:
    """What a statement does to the directories the shell may be in: the state after it, or None when it moves
    nothing. A move (`cd`, `Set-Location`, `Push-Location`, `pushd`, `chdir`) to a literal directory that exists
    or that a directory-creating statement earlier in the command certainly makes (_TrackedDirs.is_created) — and
    that no target collected earlier in the command names or contains (_TrackedDirs.is_written: a
    removal before the move) — moves each possible directory there; to one that does not exist (an earlier
    statement may create it) or to a dynamic target it keeps the old directory next to the new one (or next
    to unknown), since a failed move is a non-terminating error and the script goes on. `Pop-Location`,
    `popd` and `Set-Location -`/`+` go back to a directory of an earlier statement (or nowhere): every
    directory seen so far is possible again. The followed directory (_TrackedDirs) moves as it always did:
    on cd/sl/Set-Location/Push-Location, whether the target exists or not, `-` and `+` read as names."""
    if not statement:
        return None
    name = _ps_command_name(statement[0])
    if name in _POP_ALIASES:
        return tracked.moved_to(tracked.followed, tracked.possible | tracked.seen)
    if name not in _CD_ALIASES:
        return None
    positionals, values = _ps_split_args(statement[1:])
    target = _target_from_flags(positionals, values, ("path", "literalpath"))
    tracked.budget.charge()
    wildcard = target is not None and not values.get("literalpath") and bool(_PS_WILDCARD_RE.search(target))
    if wildcard:
        # PowerShell resolves the pattern itself: the shell may be in any directory it names now, or still in the
        # old one (a move that fails, or one that matches several, goes on); a pattern that names none (or too many
        # to follow) leaves the directory unknown next to the old one.
        found = _wildcard_directories(target, tracked.followed, tracked.budget)
        followed = (found[0] if found else None) if name in _CD_ALIASES_FOLLOWED else tracked.followed
        possible_wild: set[Optional[str]] = set()
        for cwd in tracked.possible:
            tracked.budget.charge()
            matches = _wildcard_directories(target, cwd, tracked.budget)
            possible_wild.add(cwd)
            possible_wild.update(matches if matches else (None,))
        return tracked.moved_to(followed, possible_wild)
    followed = tracked.followed_after(target) if name in _CD_ALIASES_FOLLOWED else tracked.followed
    if target in ("-", "+"):
        return tracked.moved_to(followed, tracked.possible | tracked.seen)
    possible: set[Optional[str]] = set()
    confirmed: set[str] = set()
    for cwd in tracked.possible:
        tracked.budget.charge()
        joined = _join_directory(target, cwd)
        if joined is None:
            possible.update((cwd, None))
        elif (
            (_directory_exists(joined, tracked.known) or tracked.is_created(joined)) and not tracked.is_written(joined)
        ):
            possible.add(joined)
            confirmed.add(joined)
        else:
            possible.update((cwd, joined))
    return tracked.moved_to(followed, possible, confirmed)


def _flush_ps_statement(
    words: list[str], redirect_targets: list[str], tracked: _TrackedDirs, base_cwd: str,
    git_writes: frozenset, result: set[str], broad: bool, depth: int, creation_certain: bool = False,
) -> None:
    """Handle one statement (its words and any redirection targets collected for it) and add every write
    target it names to `result`. The statement is read once; each relative target is resolved against every
    directory the shell may be in (`tracked.possible`, None = unknown, see _TrackedDirs). A nested PowerShell
    scan (`pwsh -c`, `cmd /c`) runs once, from the tracked set itself; a nested Bash scan (`bash -c`) once per
    distinct directory (the Bash scanner takes one). A directory change is followed by the caller (_follow_cd).
    `creation_certain` says that the statement runs for sure (the caller's reading), so a directory it creates
    is noted for a later move there (_TrackedDirs.note_created).
    See the module docstring for which cmdlets/constructs are recognized, and for what `broad`/`depth` do."""
    cwds = tracked.possible
    for raw in redirect_targets:
        resolved_targets = _resolve_ps_targets(raw, tracked)
        result.update(resolved_targets)
        tracked.note_filed(resolved_targets)
    words, assigned_candidates = _strip_program_assignment(_strip_literal_call(words))
    if words:
        name = _ps_command_name(words[0])
        args = words[1:]
        if name in _CD_ALIASES or name in _POP_ALIASES:
            pass  # moves the tracked directories: _scan_ps_tokens does that for every statement (_follow_cd)
        elif name == "git":
            _add_resolved_pairs(_git_targets(args, cwds, git_writes), result, tracked)
        elif name in ("bash", "sh"):
            inner = _extract_dash_c(args)
            if inner is not None:
                for where in _effective_bases(cwds, base_cwd):
                    tracked.budget.charge()
                    _add_resolved_pairs(_bash_write_targets(inner, where, git_writes), result, tracked)
        elif name in _CMD_NAMES or name in _PS_INTERP_NAMES:
            # cmd.exe's own quoting/variable syntax is not identical to PowerShell's, but its
            # redirect operators and backslash-as-separator convention are — much closer to this
            # module's own tokenizer than to Bash's (which reads "\x" as an escaped "x", silently
            # corrupting a Windows path; 2026-09-23 review fix). Recursed with this same scanner
            # for both, not shell_targets' Bash one — once, from the whole tracked set.
            inner = _extract_cmd_c(args) if name in _CMD_NAMES else _extract_ps_command_flag(args)
            if inner is not None and depth >= _PS_MAX_SCAN_DEPTH:
                result.add(_unplaced_target(_TOO_DEEP))
            elif inner is not None:
                inner_targets = _powershell_write_targets(inner, base_cwd, git_writes, broad, depth + 1, tracked)
                if inner_targets is None:
                    # Not evaluable (Invoke-Expression, an open quote): where it writes is unknown. It stays one
                    # dynamic target holding the inner text, which the checks refuse by that text (the guard of
                    # the template's own files) or by definition (the worker write scope), never a silent pass.
                    result.add(f"$(nested command: {inner})")
                else:
                    result.update(inner_targets)
        elif name == "wsl":
            # `wsl [options] [--] <command line>`: the line runs inside WSL and is read by the Bash
            # scanner (shell_targets._wsl_targets), where `/mnt/<x>/...` is drive <X>:; the words are
            # PowerShell's, their quoting already applied.
            _add_resolved_pairs(_wsl_targets([str(arg) for arg in args], cwds, git_writes, depth), result, tracked)
        elif name in _NATIVE_WRITERS:
            _add_resolved_pairs(
                _simple_command_targets([name] + [str(arg) for arg in args], cwds, git_writes, depth)[0],
                result, tracked,
            )
            if name in _WEB_ALIASES and not words[0].lower().endswith(".exe"):
                # Windows PowerShell 5.1: `curl` and `wget` are aliases of Invoke-WebRequest, whose `-OutFile`
                # (also abbreviated: `-Out`) names the file. The reading of the program above stays as well.
                for raw in _cmdlet_targets("invoke-webrequest", _expand_outfile_flag(args)):
                    result.update(_resolve_ps_targets(raw, tracked))
        else:
            creation = _ps_directory_creation(name, args)
            kind = _ALIASES.get(name)
            destination = _target_destination(*_ps_split_args(args)) if kind == "move" else None
            for raw in _cmdlet_targets(name, args):
                if creation is not None and raw in creation[0]:
                    result.update(_resolve_ps_targets(raw, tracked, note=False))  # making a directory takes nothing away
                else:
                    resolved_targets = _resolve_ps_targets(raw, tracked)
                    result.update(resolved_targets)
                    # What the statement may have made a file at, and what it took away (a move takes its sources).
                    tracked.note_filed(resolved_targets, removal=kind == "all_operands" or (kind == "move" and raw != destination))
            if creation is not None and creation_certain:
                tracked.note_created(creation[0], creation[1])
        if broad:
            for raw in _broad_guard_candidates(words) + assigned_candidates:
                candidate = raw.strip()
                if candidate and not _ps_is_ignorable(candidate):
                    result.add(candidate)
    joined = " ".join(words + redirect_targets)
    for pattern in (_IO_FILE_WRITE_RE, _IO_DIRECTORY_WRITE_RE, _IO_FILE_COPY_MOVE_RE, _IO_MOVE_SOURCE_RE,
                    _IO_STREAMWRITER_RE):
        for match in pattern.finditer(joined):
            result.update(_resolve_ps_targets(match.group(1).strip(), tracked))


def _scan_ps_tokens(
    tokens: list[_Token], base_cwd: str, git_writes: frozenset, broad: bool, depth: int,
    start: Optional[_TrackedDirs] = None, inline: Optional[_InlineSink] = None,
) -> set[str]:
    """The write targets of a tokenized command, every statement read once against the directories the shell
    may be in (_follow_cd, from `start` or `base_cwd` alone) — see _flush_ps_statement. With `inline`, the
    same walk also collects the path literals of inline interpreter code (_collect_ps_inline), so both
    readings follow the directory changes the same way. Raises _ScanLimit once the scan's budget is used up."""
    result: set[str] = set()
    tracked = start if start is not None else _TrackedDirs.start(base_cwd)
    words: list[str] = []
    redirect_targets: list[str] = []
    piped: Optional[str] = None  # the literal text the previous stage of a pipeline sends down
    # A directory-creating statement is certain to run (and so to have made its directory) when it starts the
    # command or follows `;` or a line break, at the top level, in a command without a script block or a
    # construct whose body may not run.
    creation_stream_ok = depth == 0 and not any(
        "{" in text or "}" in text or (not is_op and text.lower() in _PS_CREATION_UNSAFE_WORDS) for text, is_op in tokens
    )
    previous_op: Optional[str] = None
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
        produced: Optional[str] = None
        if words or redirect_targets:
            tracked.budget.charge()
            statement = _strip_literal_call(words)
            if piped is not None:
                result.update(_piped_script_targets(piped, statement, tracked, base_cwd, git_writes, broad, depth))
            _flush_ps_statement(
                words, redirect_targets, tracked, base_cwd, git_writes, result, broad, depth,
                creation_stream_ok and previous_op in (None, ";", "\n"),
            )
            if inline is not None and statement:
                _collect_ps_inline(statement, piped, tracked, inline)
            moved = _follow_cd(_strip_program_assignment(statement)[0], tracked)
            if moved is not None:
                tracked = moved
            produced = _ps_literal_output(statement)
            words = []
            redirect_targets = []
        if at_end:
            return result
        piped = produced if text == "|" else None
        previous_op = text
        index += 1


def _piped_script_targets(
    piped: str, statement: list[str], tracked: _TrackedDirs, base_cwd: str, git_writes: frozenset, broad: bool,
    depth: int,
) -> set[str]:
    """The write targets of a text a pipeline sends into a shell that runs it as its script: `powershell`
    or `pwsh` reading standard input (`'cmd' | powershell -`, a here-string piped in), `bash` or `sh` doing
    so (`'cmd' | bash`). The text is read like the one behind `-Command` — a PowerShell script once, from the
    tracked set, a Bash script once per directory; a text that cannot be evaluated that way (Invoke-Expression
    in it, an unterminated quote) counts with its raw redirections. Empty for any other receiver."""
    if not statement:
        return set()
    name = _ps_command_name(statement[0])
    if name in _PS_INTERP_NAMES and _ps_reads_stdin(statement[1:]):
        if depth >= _PS_MAX_SCAN_DEPTH:
            return {*_ps_raw_redirect_targets(piped), _unplaced_target(_TOO_DEEP)}
        found = _powershell_write_targets(piped, base_cwd, git_writes, broad, depth + 1, tracked)
        return set(_ps_raw_redirect_targets(piped)) if found is None else found
    if name in ("bash", "sh") and _reads_script_from_stdin(statement):
        result: set[str] = set()
        for where in _effective_bases(tracked.possible, base_cwd):
            tracked.budget.charge()
            _add_resolved_pairs(_bash_write_targets(piped, where, git_writes), result, tracked)
        return result
    return set()


def _ps_raw_redirect_targets(command: str) -> set[str]:
    """Coarse last resort for a command _powershell_write_targets returned None for (an
    unterminated quote/here-string, Invoke-Expression/iex): every word right after a redirect-style
    operator anywhere in the raw text, quotes stripped off its ends — the PowerShell twin of
    shell_targets._raw_redirect_targets, over-inclusive by design. Used by checks/write_scope.py's
    own None fallback (check 1c stays "the same way as the Bash fallback" — checks/write_guard.py's check 1
    instead searches the whole raw command text directly, see this module's docstring)."""
    return {match.group(1).strip("'\"") for match in _PS_RAW_REDIRECT_RE.finditer(command)}


def _collect_ps_inline(
    statement: list[str], piped: Optional[str], tracked: _TrackedDirs, sink: _InlineSink
) -> None:
    """The path literals of one statement's inline interpreter code (`python -c '<code>'`, `node -e "..."`, a
    literal piped into `python -` / `python` / `node`), each once per directory the statement may run in
    (`tracked.possible`), appended to `sink.found`; a relative one also as the target no check may place once
    a tracked directory was dropped at the cap. A failure of the reader is noted in `sink.failed` when the
    sink swallows (the walk goes on, the caller reports one dynamic target), else it propagates. A call can
    start more than once in a statement: the scanner reads a `{ }` body as part of one statement, so the calls
    in a loop or script block are found too (_inline_call_starts)."""
    for start, program in _inline_call_starts(statement):
        language = _inline_code.interpreter_language(_ps_command_name(program))
        if language is None:
            continue
        kind, code = _inline_code.code_source(language, statement[start + 1:])
        if kind == _inline_code.SOURCE_STDIN:
            code = piped if start == 0 else None
        elif kind == _inline_code.SOURCE_CODE and code is not None:
            code = _unwrap_here_string(code)
        if kind == _inline_code.SOURCE_NONE or code is None:
            continue
        reader = _inline_code.write_targets
        try:
            if kind == _inline_code.SOURCE_CODE and (start > 0 or program != statement[0]):
                paths = _read_with_glued_closers(reader, language, code)
            else:
                paths = list(reader(language, code))
        except Exception:  # noqa: BLE001 - the fail-closed path: a crash of the reader ends as one dynamic target, never as an allow
            if not sink.swallow:
                raise
            sink.failed = True
            return
        cwds = sorted(tracked.possible, key=lambda cwd: (cwd is None, cwd or ""))
        for path in paths:
            tracked.budget.charge()
            sink.found.extend((path, cwd, language) for cwd in cwds)
            if tracked.capped and not _is_dynamic_target(path) and not _is_absolute_target(path):
                sink.found.append((_unplaced_target(_LOST_DIRECTORY), None, language))


def _read_with_glued_closers(reader: Callable[[str, str], Iterable[str]], language: str, code: str) -> list[str]:
    """The paths the inline code of a call inside `{ }` or `( )` writes. The tokenizer glues the closing `}` or `)`
    to a quoted code word (`{python -c "..."}` is one word `...}`), and the text cannot tell that closer from one
    the code itself ends with, so the code is read as it stands and with up to three trailing closers cut; the
    paths of all readings are joined. A reading that could not place a write (an unplaced target) only counts when
    no other reading found a path, and a crash only when no reading succeeded: a cut that does not belong to the
    code breaks it, the one that does makes it readable."""
    variants = [code]
    for _ in range(3):
        if not variants[-1].endswith((")", "}")):
            break
        variants.append(variants[-1][:-1])
    found: list[str] = []
    unplaced: list[str] = []
    failure: Optional[Exception] = None
    read_any = False
    for variant in variants:
        try:
            paths = list(reader(language, variant))
        except Exception as error:  # noqa: BLE001 - a cut that breaks the code; judged after all readings
            failure = error
            continue
        read_any = True
        found.extend(path for path in paths if not _is_unplaced_target(path))
        unplaced.extend(path for path in paths if _is_unplaced_target(path))
    if not read_any and failure is not None:
        raise failure
    return list(dict.fromkeys(found or unplaced))


# What may stand in front of a program word that starts a call inside a statement: `{`, `(`, `$(`, `@(`.
_PS_CALL_OPENER_RE = re.compile(r"^(?:\$\(|@\(|[{(])+")


def _inline_call_starts(statement: list[str]) -> list[tuple[int, str]]:
    """(index, program word) of every place a call can start in a statement: its first word and, in a body the
    scanner reads as part of the statement, the word after `{`, `(`, `$(`, `&`, `.` or the `=` of an
    assignment, or a word that carries such an opener itself (`{python`, `$(python`) — the opener cut off."""
    starts: list[tuple[int, str]] = []
    for index, word in enumerate(statement):
        bare = _PS_CALL_OPENER_RE.sub("", word)
        if index == 0 or bare != word or statement[index - 1].endswith(("{", "(")) or statement[index - 1] in ("&", ".", "="):
            starts.append((index, bare))
    return starts


def _inline_sink_targets(sink: _InlineSink, base_cwd: str, command: str, tracked: _TrackedDirs) -> set[str]:
    """The files the inline interpreter code of a scanned command writes, from what the walk put into `sink`,
    resolved like any other target; a rooted path without a drive takes the drive of the directory the program
    runs in on Windows, as the interpreter reads it. A failure of the reader is no silent allow: the command text
    comes back as one dynamic target (`$(inline code: ...)`), which the worker write scope refuses and which the
    guard of the template's own files reads by its text."""
    if sink.failed:
        return {f"$(inline code: {command})"}
    found: set[str] = set()
    for path, cwd, _language in sink.found:
        if sys.platform == "win32" and path.startswith(("/", "\\")) and path[1:2] not in ("/", "\\"):
            drive = Path(cwd if cwd is not None else base_cwd).drive
            path = f"{drive}{path}" if drive else path
        resolved = tracked.resolve(path, cwd)
        if resolved:
            found.add(str(resolved))
    tracked.note_written(found)
    return found


def _powershell_write_targets(
    command: str, base_cwd: str, git_writes: frozenset = _GIT_WRITES_WORKER_SCOPE,
    broad: bool = False, depth: int = 0, start: Optional[_TrackedDirs] = None,
) -> Optional[set[str]]:
    """The paths a PowerShell command writes to, each already resolved to an absolute forward-slash
    path where possible (see the module docstring for what an unresolved entry looks like instead),
    or None when the command is not safely evaluable this way at all (Invoke-Expression/iex, an
    unterminated quote or here-string) — see the module docstring for what each caller does then.
    `git_writes` is the same choice of git subcommands shell_targets._bash_write_targets takes
    (_GIT_WRITES_TEMPLATE_GUARD for check 1, _GIT_WRITES_WORKER_SCOPE for check 1c); `broad` and
    `depth` are documented in the module docstring's `broad` paragraph. `start` is given by a nested
    scan only (`pwsh -c`, a script piped into `pwsh`): the command then starts from the directories the
    outer one may be in and shares its budget, and a crash or the end of the budget goes up to the top-level
    scan, which answers for the whole command: None for a crash (the caller's own fallback), the one target
    no check may place (_unplaced_target) once the budget is used up — a command no one writes by hand is
    refused rather than checked only in part. A `bash -c` text inside the
    command is scanned by shell_targets._bash_write_targets, which drops an rsync destination on another
    machine only while the PowerShell line as a whole is nothing but one rsync call with plain words
    (`$env:RSYNC_RSH = ...; bash -c 'rsync ...'` keeps the destination a local path): the flag
    shell_targets._RSYNC_ENV_NAMED is set here for the whole scan, a True from an outer scan kept."""
    nested = start is not None
    previous_named = _shell_targets._RSYNC_ENV_NAMED
    _shell_targets._RSYNC_ENV_NAMED = bool(previous_named) or _shell_targets._names_rsync_variable(command)
    try:
        tokens = _ps_tokens(command)
        if tokens is None or _uses_invoke_expression(tokens):
            return None
        tracked = start if start is not None else _TrackedDirs.start(base_cwd)
        sink = _InlineSink(swallow=True) if _inline_code.mentions_interpreter(command) else None
        result = _scan_ps_tokens(tokens, base_cwd, git_writes, broad, depth, tracked, sink)
        if sink is not None:
            result |= _inline_sink_targets(sink, base_cwd, command, tracked)
        return result
    except _ScanLimit as limit:
        if nested:
            raise
        return {_unplaced_target(str(limit))}
    except Exception:
        # A bug in this scanner must never turn into a silent allow (dispatch.py's docstring,
        # "when in doubt, deny"): None makes the caller fall back to its own raw-text search.
        if nested:
            raise
        return None
    finally:
        _shell_targets._RSYNC_ENV_NAMED = previous_named


def _unwrap_here_string(word: str) -> str:
    """The text of a here-string word (`@'`, a line break, the body, a line break, `'@`) without its
    markers; any other word comes back as it is."""
    if not _is_here_string_word(word) or len(word) < 4:
        return word
    inner = word[2:-2].replace("\r\n", "\n")
    newline = inner.find("\n")
    body = inner[newline + 1:] if newline >= 0 else inner
    return body.rstrip(" \t").removesuffix("\n")


def _ps_literal_output(words: list[str]) -> Optional[str]:
    """The text a PowerShell statement sends down the pipeline when it is literally known: a lone string
    or here-string, or `echo`/`Write-Output` with literal arguments. Quoting is gone from the words, so a
    lone word that is really a command name counts as text too, which holds no write call anyway."""
    if not words:
        return None
    if len(words) == 1:
        return _unwrap_here_string(words[0])
    if _ps_command_name(words[0]) in ("echo", "write-output"):
        return " ".join(_unwrap_here_string(word) for word in words[1:])
    return None


def _scan_ps_inline(
    tokens: list[_Token], base_cwd: str, start: Optional[_TrackedDirs] = None
) -> list[_PsInlineTarget]:
    """The path literals of inline interpreter code in a tokenized command, collected by the one walk of the
    statements (_scan_ps_tokens with an _InlineSink, from `start` or `base_cwd` alone): `python -c '<code>'`,
    `node -e "..."`, and a literal piped into `python -` / `python` / `node`. A literal comes once per directory
    it may run in. A failure of the reader propagates (the worker write scope reports it)."""
    sink = _InlineSink()
    tracked = start if start is not None else _TrackedDirs.start(base_cwd)
    _scan_ps_tokens(tokens, base_cwd, _GIT_WRITES_WORKER_SCOPE, False, 0, tracked, sink)
    return sink.found


def _powershell_inline_code_targets(command: str, base_cwd: str) -> list[_PsInlineTarget]:
    """The PowerShell counterpart of shell_targets._bash_inline_code_targets, for the worker write scope
    only: the path literals that inline interpreter code names next to a write call, each with the
    directory a relative one resolves against (None when a Set-Location target could not be followed)
    and the language. Empty when the command is not safely evaluable (an unterminated quote or
    here-string, Invoke-Expression), is larger than the scan follows (the targets scan refuses it then,
    see _powershell_write_targets) or does not mention an interpreter."""
    if not _inline_code.mentions_interpreter(command):
        return []
    try:
        tokens = _ps_tokens(command)
        if tokens is None or _uses_invoke_expression(tokens):
            return []
        return list(dict.fromkeys(_scan_ps_inline(tokens, base_cwd)))
    except (ValueError, RecursionError, _ScanLimit) as error:
        # What the PowerShell tokenizer and the scan raise on text they cannot read, and the end of the scan's
        # budget: the inline part ends here. Another kind of error is a bug and propagates to the dispatcher.
        _inline_code.report_skipped("PowerShell scan", error)
        return []
