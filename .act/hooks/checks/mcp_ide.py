#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check — MCP tool calls from a connected IDE server (JetBrains `idea`
#          today, PreToolUse). The checks under this package hang on the tool names the
#          standard harness uses (`Bash`, `PowerShell`, `Write`, `Edit`, ...) — an MCP server
#          brings its own tool names for the same actions (`execute_terminal_command`,
#          `apply_patch`, `execute_sql_query`, ...) and runs straight past every one of them
#          unless something translates the call first. This module does that translation and then
#          **reuses the existing checks**, exactly as they are, rather than re-implementing their
#          judgment for a second tool surface.
#
#          Four classes, by the MCP tool's own name (`mcp__<server>__<tool>` — the tool name alone
#          decides the class, never the server; the tables themselves live in
#          checks/mcp_ide_tables.py, shared with dispatch.py's fail-closed fallback so both always
#          judge a name the same way):
#            - shell:  a tool whose one string argument is a command line, same as Bash/PowerShell
#                       (`execute_terminal_command`). Translated into a synthetic payload with
#                       `tool_input.command` set to that argument and run **twice** through the
#                       same checks a real shell call would face — once with `tool_name` "Bash",
#                       once with "PowerShell" — since a Windows IDE's terminal tool can be either
#                       (review finding 1: a `Set-Content`/`New-Item`/... PowerShell write cmdlet is
#                       invisible to the Bash-shaped write-scope/write-guard scanner, which only
#                       recognizes Bash's own write syntax) and this module has no way to know which
#                       shell the call actually ran in. The reused checks: the template write-guard,
#                       the docs/ai/ guard, the worker write-scope guard, the worker git-write
#                       guard, `git reset --hard`, a recursive delete, and the secret/danger/deps
#                       scan (all `PreToolUse` checks that already understand a Bash or PowerShell
#                       command via `checks.common._shell_command`). Each translation runs once per
#                       base directory too (`_shell_cwd_variants`): with the call's own
#                       `projectPath` as the shell's `cwd` when given — an IDE terminal runs in the
#                       project the call names (review finding M-d: `echo x > src/a.py` with
#                       `projectPath=E:/other` used to be judged against the session's own
#                       directory only) — and then with the payload's own `cwd` as before. First
#                       denial across all translations and bases wins.
#            - write:  a tool naming one or more files it changes (`apply_patch`, `create_new_file`,
#                       `create_notebook`, `reformat_file`, `rename_refactoring`, `apply_quick_fix`,
#                       `edit_notebook`, `replace_text_in_file`) -- see `_WRITE_TOOL_FIELDS` for
#                       each one's actual schema.
#                       Every target is translated in turn into a synthetic payload with `tool_name`
#                       "Write" and `tool_input.file_path` set to that target's own **absolute**
#                       path (see `_absolute_write_targets` — built here rather than left to the
#                       reused checks' own relative/`cwd` resolution, since `write_scope.py`'s own
#                       resolution for a Write-shaped tool ignores `cwd`/`projectPath` entirely and
#                       always resolves a relative target against the project root regardless —
#                       review finding 5; a relative target is resolved against **both** the call's
#                       own `projectPath` and the project root when the two differ, review finding
#                       M-d), then run through the write-guard, the docs/ai/ guard and the worker
#                       write-scope guard (the three checks keyed on `Write`'s own path field); the
#                       first denial across all targets and bases wins.
#            - exec:   a tool with no argument any existing check could evaluate as a path or a
#                       command line (`execute_run_configuration`, `execute_code_on_kernel`,
#                       `run_notebook_cell`, `execute_tool`, `invoke_ide_action`, `build_project`,
#                       `execute_sql_query`, `create_database_connection`,
#                       `edit_database_connection`, `configure_python_interpreter`,
#                       `cancel_sql_query`, `interrupt_notebook`, `kill_notebook`,
#                       `test_database_connection`, `xdebug_set_variable`,
#                       `xdebug_control_session`, `xdebug_evaluate_expression`,
#                       `xdebug_remove_breakpoint`, `xdebug_run_to_line`, `xdebug_set_breakpoint`,
#                       `xdebug_start_debugger_session`, and Claude Code's own `mcp__ide__
#                       executeCode`, review finding M-a). A worker is denied outright — there
#                       is nothing here to check its write scope or the docs/ai/ guard against, so
#                       the safe answer is "use a standard tool instead"; the orchestrator is let
#                       through with a one-line note, never blocked (the human is already present
#                       when the orchestrator acts). `cancel_sql_query`, `interrupt_notebook`,
#                       `kill_notebook`, `test_database_connection`, `xdebug_set_breakpoint` and
#                       `xdebug_remove_breakpoint` are deliberate choices, not an oversight (review
#                       finding 3): none of them names a file or a command line this module could
#                       check, and each can disrupt a running process, session or external
#                       connection (or, for `test_database_connection`, reach out to a host/
#                       credential this module has no way to judge) — the same "nothing to bind a
#                       write scope to" reasoning the rest of this class already rests on, not a
#                       claim that any one of them writes a file.
#            - read:   a plainly read-only tool, by **exact** name (`_READ_TOOLS`: every read tool
#                       of the JetBrains server, plus `getDiagnostics` of Claude Code's own `ide`
#                       server), untouched by this check whatever server it came from. Exact, not a
#                       name prefix (review finding M-b): `find_and_replace` starts with `find_`
#                       and `replace_text_in_file` fits no prefix at all, so the earlier prefix rule
#                       let a worker run the first unchecked and left the second to the "unlisted"
#                       rule below instead of the write class it belongs to.
#
#          Review finding 3's own base rule, for everything left over (a tool name this module does
#          not otherwise recognize at all): a worker is denied outright for any *unrecognized* tool
#          on a server this module judges "IDE-shaped" (see `_is_ide_server` — the server's own name
#          passes `checks.session._is_ide_server_name`, i.e. contains one of
#          `_IDE_SERVER_NAME_HINTS` or *is* one of `_IDE_SERVER_EXACT_NAMES` — Claude Code's own
#          `ide` server, review finding M-a: `idea` is no substring of `ide`, so
#          `mcp__ide__executeCode` used to pass as a server this module had no evidence about — or
#          this very call's own suffix is already one of the ones the tables know), since an unknown
#          IDE action could be anything from a read to an arbitrary write; the orchestrator gets a
#          one-line note instead, never a block. A tool on a server this module has no reason to
#          think is IDE-shaped at all (Gmail, Docs, ...) is untouched, exactly as before — this rule
#          only ever narrows what "untouched" means for a server this module already has some
#          evidence about, never widens it to every MCP server there is.
#
#          A tool's argument the mapping expects but does not find as a non-empty string/list
#          (missing, wrong type, or a patch with no path the parser recognizes) is never silently
#          let through — "cannot evaluate this call's target" denies the same as a real hit would,
#          per the concept's own rule for this (§ "Andere Wege zu denselben
#          Aktionen"): "kann eine Prüfung die Argumente eines Werkzeugs
#          nicht auswerten, lehnt sie ab, statt es durchzulassen". `_WRITE_TOOL_FIELDS` reflects the
#          real JetBrains `idea` MCP server's own schemas, loaded from a live session on 2026-09-26
#          (orchestrator): `apply_patch` takes `input` (alias `patch`) holding the
#          patch text itself, in either the Codex format (`*** Add File: <p>` / `*** Update File:
#          <p>` / `*** Delete File: <p>` / `*** Move to: <p>`) or a unified diff — either a bare
#          `--- a/<p>` / `+++ b/<p>` pair, or a full git-extended header (`diff --git a/<p> b/<p>`,
#          optionally followed by `rename from/to <p>` / `copy from/to <p>`; `/dev/null` ignored on
#          either side); a path on any of these lines may be C-quoted the way git itself quotes one
#          that needs it (`"a/x\"y"`, octal byte escapes) — see `_c_unquote` and review finding 2.
#          `create_new_file` and `create_notebook` take `pathInProject`; `reformat_file` takes
#          `files`, a list of project-relative paths, all of them checked; `rename_refactoring`
#          takes `pathInProject`, `symbolName`, `newName` but changes every reference across the
#          whole project, so its real targets are not bounded by `pathInProject` at all (see the
#          `project_wide` handling below); `apply_quick_fix` takes `filePath`; `edit_notebook` takes
#          `file_path`. Several of these tools can name more than one target in a single call
#          (`reformat_file`'s `files`, a multi-file patch) — every target is checked, in order, and
#          the first denial wins, same as the shell class already does across its several reused
#          checks.
#          A tool's own `projectPath`, when given as a non-empty string, is one base a relative
#          target resolves against, **next to** the project root — the absolute file_paths are
#          built here (`_absolute_write_targets`), not merely forwarded as `cwd` for the reused
#          checks to maybe use (review finding 5: `write_guard.py` does honor a translated call's
#          `cwd`, but `write_scope.py`'s own Write-shaped resolution never did, always resolving
#          against the project root regardless — the two reused checks would then judge the very
#          same relative target against two different base directories). Both bases, not just
#          `projectPath` (review finding M-d): the IDE may read `projectPath` only as the project to
#          act in and still land a relative `pathInProject` under that project's own root — with
#          `projectPath=<root>/src` and `pathInProject=.act/x.md` the earlier single-base resolution
#          checked `<root>/src/.act/x.md`, outside `.act/` proper, and let the call through; now
#          `<root>/src/.act/x.md` and `<root>/.act/x.md` are both checked, and one denial suffices.
#          A target that resolves outside the project root this way is judged exactly as any other
#          out-of-root target already is by the reused checks (write-guard: not under this project's
#          `.act/`, nothing to deny; write-scope: denied unless it matches a pattern resolved under
#          `permissions.additionalDirectories`), never specially handled here.
#
# Known limits:
#   - the class tables are keyed on the tool's own name only (`_mcp_tool_suffix` strips
#     `mcp__<server>__` off the front) — a server that reuses one of these exact tool names for a
#     genuinely different, unrelated action would be misclassified; no such collision is known.
#   - `rename_refactoring`'s real targets (every file holding a reference to the renamed symbol)
#     are not enumerable from the call's own arguments at all. For the orchestrator, or a worker
#     whose assignment named no restriction, `pathInProject` is checked as a stand-in target (the
#     .act/ and docs/ai/ guards still apply to it). For a worker bound to a restricted `Write
#     scope` (`mode` "patterns" or "none"), the call is denied outright — a scope naming a handful
#     of globs cannot vouch for a project-wide rename's real, unbounded reach.
#   - `check_mcp_ide` fails closed for a call it cannot classify away as read-only cleanly (see
#     dispatch.py's `_FAIL_CLOSED`/`_check_failed`): a bug in this module's own translation must
#     not quietly open the door the checks it delegates to would otherwise keep shut. Since review
#     finding 4, `_check_failed` narrows this itself when `mcp_ide` is the check that broke: an
#     unrelated Bash/Write call is never denied just because this module failed on some other,
#     unrelated call, and within an MCP call the fallback only denies where a working check would
#     actually have looked at all (a shell/write/exec-classified suffix, or an unlisted tool on an
#     IDE server for a worker) — see dispatch.py's own comment on `_check_failed`.
#   - `_c_unquote` handles git's own C-style quoting (`\\`, `\"`, octal byte escapes) but not every
#     escape C itself defines (`\t`/`\n` are handled since git can emit them for a path with control
#     characters, but e.g. `\a`/`\v` are not known to occur in a git-produced path and are left as
#     literal text if ever seen).
#   - an absolute target is compared only after the shared normalization in
#     `checks.shell_targets._resolve_path` (`\\?\`, `\\.\` and this machine's own administrative
#     shares mapped to the plain drive form — review finding M-c, fixed at that root so a plain
#     `Write`/`Edit`/shell target benefits the same way); a UNC path to any *other* host is left as
#     it is and judged as out of root (see that module's comment on why no check probes the
#     network), so an alias of this very machine under a name it does not know itself by is a
#     residual gap for the orchestrator's own `.act/` guard only — a worker's write there is out of
#     its root-relative scope regardless.

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Optional

import actlib

from .common import _check_mode, _is_worker
from .danger_scan import check_danger_scan
from .deps_scan import check_deps_scan
from .git_reset_hard import check_git_reset_hard
from .mcp_ide_tables import _EXEC_TOOLS, _READ_TOOLS, _SHELL_TOOL_ARGS, _WRITE_TOOL_FIELDS, _tool_class
from .recursive_delete import check_recursive_delete
from .secret_scan import check_secret_scan
from .session import _is_ide_server_name
from .shell_targets import _is_absolute_target, _resolve_path
from .worker_docs_ai import check_worker_docs_ai
from .worker_git_write import check_worker_git_write
from .write_guard import _guard_root, check_write_guard
from .write_scope import _resolve_worker_scope, check_worker_write_scope

__all__ = [
    "_SHELL_TOOL_ARGS", "_WRITE_TOOL_FIELDS", "_EXEC_TOOLS", "_READ_TOOLS",
    "_SHELL_REUSE_CHECKS", "_WRITE_REUSE_CHECKS", "_PATCH_PATH_PREFIXES",
    "_mcp_tool_suffix", "_mcp_tool_server", "_is_read_only_suffix", "_is_ide_server",
    "_extract_str_arg", "_c_unquote", "_patch_paths", "_write_tool_targets", "_write_target_base",
    "_project_root", "_absolute_write_targets", "_shell_cwd_variants", "_rename_worker_scope",
    "_deny_or_warn", "_run_reused_checks", "check_mcp_ide",
]

# The class tables (_SHELL_TOOL_ARGS, _WRITE_TOOL_FIELDS, _EXEC_TOOLS, _READ_TOOLS) are imported
# from checks/mcp_ide_tables.py above -- see that module's header for why they live apart from
# this one, and its comments for what each table holds.

# apply_patch's Codex-format path lines -- the text after the prefix, stripped, is the path.
_PATCH_PATH_PREFIXES = (
    "*** Add File:", "*** Update File:", "*** Delete File:", "*** Move to:",
)

# A unified diff's git-extended header lines this module also reads targets from (review finding
# 2) -- "diff --git a/<p> b/<p>" (both sides, quoted or not; a side of "/dev/null" is not a
# target), and "rename|copy from|to <p>" (the real source/destination of a rename or copy, which
# a plain "--- a/<p>" / "+++ b/<p>" pair alone does not always carry -- e.g. a deleted-file hunk
# with no "---"/"+++" lines at all still has its own "diff --git" line).
_DIFF_GIT_RE = re.compile(
    r'^diff --git (?P<a>"(?:[^"\\]|\\.)*"|\S+) (?P<b>"(?:[^"\\]|\\.)*"|\S+)$'
)
_RENAME_COPY_RE = re.compile(
    r'^(?:rename|copy) (?:from|to) (?P<path>"(?:[^"\\]|\\.)*"|.+)$'
)

# Reused, in this order, for a translated "shell" call (first denial wins) -- mirrors the order
# these same checks run in dispatch.py's own _PRE_TOOL_USE_CHECKS.
_SHELL_REUSE_CHECKS = (
    check_write_guard,
    check_worker_docs_ai,
    check_worker_write_scope,
    check_worker_git_write,
    check_git_reset_hard,
    check_recursive_delete,
    check_secret_scan,
    check_danger_scan,
    check_deps_scan,
)

# Reused, in this order, for a translated "write" call.
_WRITE_REUSE_CHECKS = (
    check_write_guard,
    check_worker_docs_ai,
    check_worker_write_scope,
)

# A shell-class MCP call is run through _SHELL_REUSE_CHECKS once per one of these tool_name
# translations -- a Windows IDE's terminal tool can run either shell, and this module has no way
# to tell which from the call's own arguments (review finding 1); first denial across both wins.
_SHELL_TOOL_NAME_TRANSLATIONS = ("Bash", "PowerShell")


def _mcp_tool_suffix(tool_name: str) -> Optional[str]:
    """The tool part of an MCP tool name (`mcp__<server>__<tool>` -> `<tool>`), independent of
    which server it came from -- the class tables above never key on the server name. None for
    anything not shaped like an MCP tool name at all."""
    if not tool_name.startswith("mcp__"):
        return None
    rest = tool_name[len("mcp__"):]
    server, sep, tool = rest.partition("__")
    if not sep or not server or not tool:
        return None
    return tool


def _mcp_tool_server(tool_name: str) -> Optional[str]:
    """The server part of an MCP tool name (`mcp__<server>__<tool>` -> `<server>`). None for
    anything not shaped like an MCP tool name at all -- same contract as _mcp_tool_suffix, the two
    are always computed from the same string."""
    if not tool_name.startswith("mcp__"):
        return None
    rest = tool_name[len("mcp__"):]
    server, sep, tool = rest.partition("__")
    if not sep or not server or not tool:
        return None
    return server


def _is_read_only_suffix(suffix: str) -> bool:
    """True for a suffix this module knows is read-only, whatever the server -- an exact match in
    mcp_ide_tables._READ_TOOLS, never a name prefix (review finding M-b)."""
    return suffix in _READ_TOOLS


def _is_ide_server(tool_name: str, suffix: str) -> bool:
    """True when this call's own server counts as "IDE-shaped" for review finding 3's base rule
    (an unrecognized tool on such a server denies for a worker, notes only for the orchestrator):
    either the server name itself passes checks.session._is_ide_server_name (a substring of
    _IDE_SERVER_NAME_HINTS, or exactly one of _IDE_SERVER_EXACT_NAMES -- Claude Code's own `ide`
    server, review finding M-a; the same definition session.py's own "ide" topic detection uses),
    or this call's own suffix is already one the tables classify (shell/write/exec/read) -- the
    latter mostly matters for a server whose name does not match but whose tools this module still
    classifies by name alone; in practice a suffix that matches a table is handled by its own
    branch in check_mcp_ide() well before this function is ever consulted, so this mainly
    documents the full definition rather than changing behaviour for that case."""
    server = _mcp_tool_server(tool_name)
    if server is not None and _is_ide_server_name(server):
        return True
    return _tool_class(suffix) is not None


def _extract_str_arg(tool_input: dict, field_names: tuple) -> Optional[str]:
    for field in field_names:
        value = tool_input.get(field)
        if isinstance(value, str) and value:
            return value
    return None


def _c_unquote(raw: str) -> str:
    """Undo git's own C-style quoting of a path (core.quotepath, on by default): a value wrapped
    in double quotes, with backslash escapes (`\\\\`, `\\"`, `\\n`, `\\t`) and octal byte escapes
    (`\\NNN`, each naming one raw byte -- the whole sequence of bytes is UTF-8-decoded together at
    the end, so a multi-byte character split across several octal escapes still comes back
    correctly), becomes the actual path text (review finding 2). A value not wrapped in double
    quotes at all is returned unchanged -- git only quotes a path that actually needs it. A
    decoding failure (a genuinely malformed escape sequence) falls back to the inner text as-is
    rather than raising -- never a reason to crash a PreToolUse check."""
    if len(raw) < 2 or raw[0] != '"' or raw[-1] != '"':
        return raw
    inner = raw[1:-1]
    result = bytearray()
    i = 0
    simple = {"\\": "\\", '"': '"', "n": "\n", "t": "\t"}
    while i < len(inner):
        ch = inner[i]
        if ch == "\\" and i + 1 < len(inner):
            nxt = inner[i + 1]
            if nxt in "01234567":
                j = i + 1
                digits = ""
                while j < len(inner) and len(digits) < 3 and inner[j] in "01234567":
                    digits += inner[j]
                    j += 1
                result.append(int(digits, 8) & 0xFF)
                i = j
                continue
            if nxt in simple:
                result.extend(simple[nxt].encode("utf-8"))
                i += 2
                continue
            result.extend(ch.encode("utf-8"))
            i += 1
            continue
        result.extend(ch.encode("utf-8"))
        i += 1
    try:
        return result.decode("utf-8")
    except UnicodeDecodeError:
        return inner


def _strip_ab_prefix(path: str) -> str:
    """Drop a leading "a/" or "b/" from a unified-diff path (`--- a/<p>`, `diff --git a/<p>
    b/<p>`) -- left unchanged if it has neither, same as the paths a real diff can already carry
    without one (e.g. a Codex-format path)."""
    if path.startswith("a/") or path.startswith("b/"):
        return path[2:]
    return path


def _patch_paths(text: str) -> list:
    """Every path named inside an `apply_patch` call's own patch text -- Codex format
    (`_PATCH_PATH_PREFIXES`) or a unified diff's own header lines: `--- a/<p>` / `+++ b/<p>`
    (`/dev/null`, meaning "no file on this side", is not a target), the git-extended `diff --git
    a/<p> b/<p>` line, and `rename|copy from|to <p>` (review finding 2). Any of these paths may be
    C-quoted (`_c_unquote`) the way git itself quotes one that needs it. Order preserved,
    duplicates kept (the caller checks each one regardless).

    A `diff --git ...` line this module cannot parse into at least one real target at all (neither
    side present, both `/dev/null`, or the line does not even match the expected two-path shape --
    e.g. an unquoted path containing a space) empties the whole result: per this module's own
    header comment ("cannot evaluate this call's target ... denies"), a patch with one hunk this
    parser cannot classify must not be let through just because its other hunks parsed cleanly --
    an empty result here makes `_write_tool_targets` deny the whole call (review finding 2's own
    "ein diff --git-Block ohne erkennbares Ziel -> ablehnen")."""
    paths: list = []
    unresolved = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()

        prefix = next((p for p in _PATCH_PATH_PREFIXES if stripped.startswith(p)), None)
        if prefix is not None:
            candidate = stripped[len(prefix):].strip()
            if candidate:
                paths.append(_c_unquote(candidate))
            continue

        if stripped.startswith("diff --git "):
            diff_match = _DIFF_GIT_RE.match(stripped)
            if diff_match is None:
                unresolved = True
                continue
            found_target = False
            for key in ("a", "b"):
                candidate = _strip_ab_prefix(_c_unquote(diff_match.group(key)))
                if candidate and candidate != "/dev/null":
                    paths.append(candidate)
                    found_target = True
            if not found_target:
                unresolved = True
            continue

        rename_copy_match = _RENAME_COPY_RE.match(stripped)
        if rename_copy_match:
            candidate = _c_unquote(rename_copy_match.group("path").strip())
            if candidate:
                paths.append(candidate)
            continue

        if stripped.startswith("--- ") or stripped.startswith("+++ "):
            candidate = stripped[4:].strip()
            if not candidate or candidate == "/dev/null":
                continue
            candidate = _strip_ab_prefix(_c_unquote(candidate))
            if candidate:
                paths.append(candidate)
            continue

    if unresolved:
        return []
    return paths


def _write_tool_targets(info: dict, tool_input: dict) -> Optional[list]:
    """This write-class call's own target path(s), per `info` (one entry of
    `_WRITE_TOOL_FIELDS`). None if none could be read at all -- the caller denies rather than
    letting the call through unchecked."""
    kind = info["kind"]
    fields = info["fields"]
    if kind == "single":
        value = _extract_str_arg(tool_input, fields)
        return [value] if value else None
    if kind == "list":
        value = tool_input.get(fields[0])
        if not isinstance(value, list):
            return None
        targets = [v for v in value if isinstance(v, str) and v]
        return targets or None
    if kind == "patch":
        text = _extract_str_arg(tool_input, fields)
        if text is None:
            return None
        targets = _patch_paths(text)
        return targets or None
    return None  # pragma: no cover -- every _WRITE_TOOL_FIELDS entry uses a kind handled above


def _write_target_base(tool_input: dict) -> Optional[str]:
    """The call's own `projectPath`, when given as a non-empty string -- one base a relative
    target is resolved against, next to the project root (see _absolute_write_targets), and the
    `cwd` a shell-class call is also checked under (_shell_cwd_variants). None means "no
    projectPath given", which leaves the project root as the only base there, never the call's own
    `cwd` (review finding 5: `write_scope.py`'s own Write-shaped resolution ignores `cwd` entirely
    and always resolves against the project root regardless of what this module hands it, so a
    `cwd`-based fallback here would be honored by one reused check and silently ignored by the
    other)."""
    value = tool_input.get("projectPath")
    return value if isinstance(value, str) and value else None


def _project_root() -> Optional[Path]:
    """The project this hook run belongs to, or None if it cannot be determined (not inside a
    template-managed project at all): found the way write_guard.py's check 1 finds it
    (_guard_root -- `CLAUDE_PROJECT_DIR`, else dispatch.py's own location), with
    actlib.repo_root() from the current directory as the last resort -- best-effort, same fallback
    shape as _rename_worker_scope's own try/except."""
    root = _guard_root()
    if root is not None:
        return root
    try:
        return actlib.repo_root()
    except RuntimeError:
        return None


def _absolute_write_targets(target: str, base: Optional[str], root: Optional[Path]) -> list:
    """Every absolute path this write-class call's own target may land at, made absolute *here*
    rather than left for the reused write_guard/write_scope checks to resolve against a base of
    their own choosing (review finding 5): `write_guard.py` does honor a translated call's `cwd`,
    but `write_scope.py`'s own resolution for a Write-shaped tool never did -- it always resolves a
    relative target against the project root, regardless of `cwd` -- so the two reused checks
    would judge the very same relative target against two different base directories, and a
    `projectPath` this module could only ever hand over via `cwd` would silently be ignored by one
    of them. Building the absolute paths once, here, means both reused checks see the same
    already-absolute path and never fall back to a base of their own at all
    (`_normalize_candidate_path`/`_resolve_against` both use a target's own base only when the
    target is *not* already absolute).

    `target` already absolute is returned as the one candidate, unchanged (the reused checks
    normalize its spelling themselves, shell_targets._resolve_path -- review finding M-c).
    Otherwise it is resolved against `base` (this call's own `projectPath`, see
    `_write_target_base`) when given **and** against `root` (the project root) when known -- both,
    since the IDE may read `projectPath` only as the project to act in and still land the relative
    path under that project's root (review finding M-d: `projectPath=<root>/src` plus
    `pathInProject=".act/x.md"` used to be checked as `<root>/src/.act/x.md` only, outside `.act/`
    proper); the caller checks every candidate and one denial suffices. Never against the call's
    own `cwd`, so a session merely sitting in a subdirectory when the call was made cannot make a
    `.act/`-relative target look like it resolves somewhere else entirely (review finding 5:
    `cwd=src` plus `pathInProject=".act/x.md"` used to resolve to `src/.act/x.md`). A candidate
    that resolves outside the project root is not special-cased here at all -- it is judged exactly
    as any other out-of-root target already is by the reused checks. A base the target cannot be
    resolved against (an OSError/ValueError inside Path.resolve) contributes the raw target instead,
    judged as relative text by the reused checks' own fallback path; with neither `base` nor `root`
    available (an environment this hook cannot place inside any project), that raw target is the
    only candidate, same as before this fix."""
    if _is_absolute_target(target):
        return [target]
    candidates: list = []
    for directory in (base, str(root) if root is not None else None):
        if directory is None:
            continue
        resolved = _resolve_path(target, directory)
        candidate = str(resolved) if resolved is not None else target
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates or [target]


def _shell_cwd_variants(tool_input: dict) -> list:
    """The `cwd` values a shell-class call's translations are checked under, in order: the call's
    own `projectPath` when given (an IDE terminal runs in the project the call names -- review
    finding M-d: `echo x > src/a.py` with `projectPath=E:/other` used to be judged against the
    session's own directory only, so a scoped worker got through), then None, meaning "leave the
    payload's own `cwd` as the harness reported it" (the reused checks fall back from there to
    the project root themselves, exactly as before). The caller runs every shell translation once
    per entry; one denial suffices."""
    variants: list = []
    project_path = _write_target_base(tool_input)
    if project_path is not None:
        variants.append(project_path)
    variants.append(None)
    return variants


def _rename_worker_scope(payload: dict) -> Optional[dict]:
    """The write scope bound to this call's worker, if any, for `rename_refactoring`'s own
    project-wide special case -- None if this is not a worker call, the project root cannot be
    determined, or the binding does not resolve (see write_scope._resolve_worker_scope; any of
    these leaves the call to be checked the same way an orchestrator's `pathInProject` is)."""
    if not _is_worker(payload):
        return None
    root = _project_root()
    if root is None:
        return None
    try:
        return _resolve_worker_scope(root, payload)
    except Exception:
        return None


def _deny_or_warn(mode: str, message: str) -> int:
    if mode == "warn":
        print(message)
        return 0
    print(message, file=sys.stderr)
    return 2


def _run_reused_checks(checks: tuple, sub_payload: dict) -> int:
    """First non-zero result from `checks`, each run against `sub_payload` -- every reused check
    reads its own `docs/ai/config.md` mode (template-write-guard, worker-write-scope, ...)
    independently; this only decides which checks see the translated call, not how each one
    itself is gated."""
    for func in checks:
        result = func(sub_payload)
        if result != 0:
            return result
    return 0


def check_mcp_ide(payload: dict) -> int:
    """Check: classify an MCP tool call from a connected IDE server (shell / write / exec-without-
    target / unlisted-on-an-IDE-server) and either translate it into an existing check's own tool
    shape and reuse that check, deny a worker outright (a tool with no evaluable target, or an
    unrecognized tool on an IDE-shaped server), or let it through untouched (a plainly read-only or
    genuinely unrecognized tool). See this module's docstring for the full contract."""
    config = actlib.read_config()
    mode = _check_mode(config, "ide-mcp", default="block")
    if mode == "off":
        return 0

    tool_name = payload.get("tool_name")
    if not isinstance(tool_name, str):
        return 0
    suffix = _mcp_tool_suffix(tool_name)
    if suffix is None:
        return 0  # not an MCP tool call

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}

    if suffix in _SHELL_TOOL_ARGS:
        command = _extract_str_arg(tool_input, _SHELL_TOOL_ARGS[suffix])
        if command is None:
            return _deny_or_warn(
                mode,
                f"[act] {tool_name}: could not read its command argument -- refusing rather than "
                "letting it through unchecked (ide-mcp)",
            )
        for shell_tool_name in _SHELL_TOOL_NAME_TRANSLATIONS:
            for cwd in _shell_cwd_variants(tool_input):
                sub_payload = dict(payload)
                sub_payload["tool_name"] = shell_tool_name
                sub_payload["tool_input"] = {"command": command}
                if cwd is not None:
                    sub_payload["cwd"] = cwd
                result = _run_reused_checks(_SHELL_REUSE_CHECKS, sub_payload)
                if result != 0:
                    return result
        return 0

    if suffix in _WRITE_TOOL_FIELDS:
        info = _WRITE_TOOL_FIELDS[suffix]
        if info.get("project_wide"):
            scope = _rename_worker_scope(payload)
            if scope is not None and scope.get("mode") in ("none", "patterns"):
                return _deny_or_warn(
                    mode,
                    f"[act] {tool_name}: renames every reference across the whole project -- its "
                    "real targets cannot be bounded by a Write scope; not usable by a scoped "
                    "worker (R-cost-delegate)",
                )
        targets = _write_tool_targets(info, tool_input)
        if not targets:
            return _deny_or_warn(
                mode,
                f"[act] {tool_name}: could not read a target path from its arguments -- refusing "
                "rather than letting it through unchecked (ide-mcp)",
            )
        base = _write_target_base(tool_input)
        root = _project_root()
        for target in targets:
            for candidate in _absolute_write_targets(target, base, root):
                sub_payload = dict(payload)
                sub_payload["tool_name"] = "Write"
                sub_payload["tool_input"] = {"file_path": candidate}
                result = _run_reused_checks(_WRITE_REUSE_CHECKS, sub_payload)
                if result != 0:
                    return result
        return 0

    if suffix in _EXEC_TOOLS:
        if _is_worker(payload):
            return _deny_or_warn(
                mode,
                f"[act] {tool_name} has no target this guard can check -- not usable by a worker; "
                "use a standard tool, or ask the orchestrator to run it (R-cost-delegate)",
            )
        print(f"[act] {tool_name} ran via the IDE MCP server, outside the usual write/shell checks")
        return 0

    if _is_read_only_suffix(suffix):
        return 0  # a plainly read-only MCP tool -- never this check's business

    if _is_ide_server(tool_name, suffix):
        if _is_worker(payload):
            return _deny_or_warn(
                mode,
                f"[act] {tool_name}: an unrecognized tool on an IDE MCP server -- not usable by a "
                "worker; use a standard tool, or ask the orchestrator to run it (R-cost-delegate)",
            )
        print(f"[act] {tool_name} ran via the IDE MCP server, outside the usual write/shell/exec checks")
        return 0

    return 0  # a genuinely unrecognized MCP tool, on a server with no IDE evidence at all
