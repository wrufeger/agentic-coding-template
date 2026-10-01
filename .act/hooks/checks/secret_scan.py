#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check — secret scan before a commit (PreToolUse, `R-safe-no-secret-diff`). Triggers on
#          a Bash/PowerShell call that runs `git commit` (also inside a chain, with global options
#          like `git -C x commit`, a nested shell, or a simple git alias) — for orchestrator and
#          worker alike (Q75 a: the dispatcher is the only gate, no separate git hook). What gets
#          checked is exactly what the commit would take:
#            - `git diff --cached -U0` (always) -- every git call of the walk runs from the
#              repository's top level, not the commit's own directory: with `diff.relative=true` a
#              diff from a subdirectory silently drops everything outside it (2026-09-27 review 3,
#              m3; the pathspecs handed in are absolute or top-anchored, so nothing else changes);
#            - with `-a`/`--all`, or an earlier `git add -u|--update|-A|--all|--no-ignore-removal`
#              *without a pathspec* (or `git add` with no paths at all, or `git add :/`) in the
#              same chain, also `git diff -U0` (unstaged changes to every tracked file, not just the
#              ones named) -- with a pathspec (`git add -A src`) git stages only under it, so only
#              the per-path walk below runs for it (review 3, M1);
#            - after an earlier `git add -A|--all|--no-ignore-removal` without a pathspec (or
#              `--pathspec-from-file`, or `git add :/`) in the same chain, also every new, untracked
#              file in the whole working tree (git's own `:/` pathspec, _WHOLE_TREE_PATHSPEC -- from
#              a subdirectory too, where a bare `git ls-files` stops at the current directory;
#              2026-09-27 review 2, C2); new files are read via the repository's top level
#              (`--full-name`), so a name in a finding is root-relative whichever directory the
#              commit runs from. A short flag counts inside a cluster too (`-fA`, `-Av`; review 3,
#              m2), and `git stage` is read as `git add`;
#            - `git commit <pathspec>`'s own trailing pathspec operands (message/author/etc.
#              options and their values excluded — see _COMMIT_VALUE_FLAGS), and any `git add
#              <paths>` earlier in the same chain (not staged yet when this PreToolUse call
#              happens — nothing in the chain has run yet): for each, `git diff -U0 -- <path>`
#              plus the content of any new, untracked file under it (`git ls-files --others`,
#              *without* `--exclude-standard` when that `add` used `-f`/`--force` — a forced add
#              can stage a gitignored file, e.g. `.env`, that `--exclude-standard` would otherwise
#              hide from view here too); a top-anchored magic pathspec (`:/src`, `:(top)src`) is
#              handed to git as written, every other operand resolved to an absolute path first;
#            - `git merge|cherry-pick|revert|rebase|am --continue` — only the staged diff (these
#              commit whatever is already staged, no working-tree pass).
#          A `bash -c '...'`/`sh -c '...'`, `powershell`/`pwsh -Command '...'`, or `cmd /c ...`
#          nested inside the chain is unwrapped and scanned the same way, recursively, up to
#          _MAX_NESTED_DEPTH. A subcommand that is not literally one of the above is looked up as a
#          simple git alias (`git config --get alias.<name>`, cached per call) once time remains in
#          the shared budget.
#
#          Only added lines ('+') count — a removed secret does not hold up the commit. Matched
#          against: known key/token formats (AWS, GitHub, GitLab, Slack, Stripe, Google, OpenAI/
#          Anthropic, JWT, a private-key block), a newly added file named `.env`/`.env.*` (the
#          `.env.example`/`.env.sample`/`.env.template` trio excepted), and a `KEY = "value"`-style
#          assignment (JSON-style `"key": "value"` too — every such candidate on a line is tried,
#          not just the first) whose key looks credential-related (feedback_privacy.SECRET_WORDS,
#          reused rather than a second word list) and whose value is at least 20 characters with
#          Shannon entropy at or above 3.0 bit/char for a purely hex-digit value, 3.5 otherwise (the
#          key-name gate already keeps ordinary code/prose out, so the bar itself can sit lower). A
#          line containing the marker `act:allow-secret`, or a value that reads as a placeholder
#          (`<token>`, `${VAR}`, `xxx...`, `changeme`, `example`, ...), is never reported.
#          An *unquoted* value that is code rather than a literal is never measured, but only in a
#          source-code file (_SOURCE_EXTENSIONS: .py .js .ts .vue .php .java .go .cs ... ; the path
#          comes from the diff section / new-file name), never on a comment line (leading `#`,
#          `//`, `/*`, `*`, `--`, `<!--`) or after a comment marker earlier on the line, and never
#          for a value that looks generated (two or more separate digit runs, `Ab3dEf9Gh...`):
#          a call (identifier or member path directly followed by `(` -- a keyword argument whose
#          value is a function call), a member-access path (a field copied from a request body,
#          `req.body.<field>`) or a plain identifier. In every other file
#          (`.env*`, .ini, .cfg, .conf, .properties, .yaml/.yml, .toml, shell scripts, Dockerfile,
#          docs, no or unknown extension) a bare value is a literal and stays measured, whatever
#          its shape. A quoted value is always measured.
#          All findings are named in the hold message, up to _MAX_FINDINGS one by one, then "+N more"
#          with the total and the affected files, so one round of marking is enough;
#          the scan itself stops collecting at _MAX_COLLECTED.
#          Deliberately not flagged, by construction rather than as a special case: a lockfile's
#          `"integrity": "sha512-..."`/`"resolved": "..."` or a bare UUID never matches the
#          assignment rule, because their key names are not in the credential vocabulary.
#
#          Chain parsing reuses shell_targets' tokenizer (_line_mode_tokens/_shell_tokens — quoting
#          and heredocs handled the same way as check 1/1c) rather than a second shlex-based
#          scanner; on top of the token stream this module only needs "which simple commands appear
#          in this order" (_simple_commands) and "is this one a `git <sub>` call, and under which
#          `-C` directory" (_git_call) — much less than shell_targets' write-target machinery, so
#          it is its own small walker, not a copy of _scan_tokens. If the command cannot be
#          tokenized at all (an unclosed quote, `$'...'` ANSI-C quoting — shlex does not know it),
#          a coarse raw-text fallback treats a bare "git ... commit" mention as a `-a`-style commit
#          with no known add-paths — over-inclusive on purpose, the same stance shell_targets takes
#          for its own tokenizing fallback.
#
#          A file's own diff section over 2MB is skipped (named in the "not fully checked" note),
#          every other file in the same diff is still scanned — the 2MB line is per file, not per
#          diff. Diff/ls-files calls run with `-c core.quotePath=false` (readable non-ASCII names
#          instead of octal escapes) and, for diff, `--no-textconv` (do not run a configured
#          textconv filter — closer to what is actually being committed).
#
#          Timeout-aware: a fixed ~4.5s budget shared across every git subprocess call (including
#          alias lookups) and file read for this check, capped further by the hook-wide deadline
#          (_check_deadline: dispatch.py's own start, payload["_act_hook_started"], plus
#          _HOOK_BUDGET -- inside the harness's 10s hook timeout; the secret, danger and deps scans
#          run back to back in one hook call, so their budgets must not simply add up, 2026-09-27
#          review 2, m5). Running out
#          of it never blocks by itself — only a note ("not fully checked") — but real findings
#          from the part that *was* scanned still hold the commit. The note says which limit hit
#          (_incomplete_note): the time budget (or a failed git call), and/or the files skipped for
#          size, named.
#
#          PreToolUse's plain stdout (the `warn`-mode hold message, the "not fully checked" note)
#          is transcript-only and never reaches the model on an allowed (exit 0) call — confirmed
#          against the harness docs, see checks/encoding_hint.py's header for the research this
#          module leans on rather than repeating. note_secret_scan() is the PostToolUse companion:
#          it drains and returns whatever check_secret_scan queued for this session (reusing
#          encoding_hint's generic queue helpers, `.act-local/secret-scan-notes/<session>.
#          pending.json` of its own), once, via hookSpecificOutput.additionalContext — the field
#          actually documented to reach the model for that event. Registration is dispatch.py's own
#          (out of this module's write scope): add `("secret_scan", "note_secret_scan"),` to
#          `_POST_TOOL_USE_NOTES` (dispatch.py:193, right after the `("encoding_hint", ...)` line).
#
# Known limits:
#   - a target reached only through `python -c`, a script, `eval`, `$(...)`, or a shell function is
#     invisible, same as shell_targets' own write-target scan;
#   - `cd`/`-C` tracking is a single "current directory", not shell_targets' branch-aware set of
#     possible directories, and only a literal `cd <dir>`/`git -C <dir>` moves it — `pushd`/
#     PowerShell's `Set-Location` do not, so a chain using either can end up scanned against the
#     wrong directory (a wrong guess only weakens the scan, never blocks something real);
#   - a word right after a redirection operator (`git commit -m x > log.txt`) is not specially
#     dropped, so it can end up as an extra, harmless word in that command's argument list;
#   - the tokenizer is POSIX/Bash-shaped; a PowerShell/cmd-specific construct (backtick escaping, a
#     cmdlet, `$(...)`) is only approximated, not specially understood — nested-shell unwrapping
#     (`_nested_command`) covers the common `-c`/`-Command`/`/c` shape only;
#   - alias resolution follows exactly one level, ignores a shell alias (`alias.x = !...`), and
#     substitutes only the resolved subcommand name — an alias's own default arguments (e.g.
#     `alias.ci = commit -v`) are not merged in, only whatever the caller wrote after the alias;
#   - a value under 20 characters is never checked at all (the length floor that keeps the
#     entropy/keyword heuristic's false-positive rate down);
#   - a file under a `-diff` gitattribute is invisible to `git diff` regardless of `--no-textconv`
#     (an unrelated feature — `-diff` makes git treat the file as binary outright) — accepted gap,
#     not worked around here (2026-09-23 review);
#   - `--pathspec-from-file` (on `add` or `commit`) is treated as "scan everything", the same as
#     `-a`/`-A` — its file is not read to recover the actual path list;
#   - a pathspec whose magic is relative to the directory git runs in (`:(glob)*.txt`, `:!secrets`,
#     `:(icase)x`) is not understood: it is resolved like a plain file name and matches nothing, and
#     an exclude in it is not applied to the other operands (a file it excludes is still scanned --
#     over-inclusive, never a miss elsewhere); only a top-anchored one (`:/x`, `:(top)x`) is handed
#     to git as written (2026-09-27 review 3);
#   - a `git add -u|-A "$dir"` whose operand cannot be placed keeps the flag's widest reading (the
#     whole tree), over-inclusive on purpose -- a plain `git add "$dir"` stays invisible, as above.

from __future__ import annotations

import dataclasses
import math
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional

import actlib
import feedback_privacy

from .common import _check_mode, _shell_command
from .encoding_hint import _pop_pending_notes, _queue_pending_note
from .shell_targets import (
    _ASSIGNMENT_RE,
    _GIT_GLOBAL_VALUE_FLAGS,
    _RESERVED_PREFIXES,
    _SEPARATOR_OPS,
    _SHELL_NAMES,
    _SIMPLE_DIR_RE,
    _WRAPPER_ARG_RE,
    _WRAPPER_COMMANDS,
    _cd_bases,
    _command_name,
    _is_dynamic_target,
    _line_mode_tokens,
    _operands,
    _shell_tokens,
    _to_native_path,
)

__all__ = [
    "_ALLOW_MARK", "_ENV_ALLOWED", "_MAX_DIFF_BYTES", "_MAX_FINDINGS", "_MAX_COLLECTED", "_TIME_BUDGET",
    "_SOURCE_EXTENSIONS", "_MEMBER_ACCESS_RE", "_IDENTIFIER_RE", "_CALL_RE", "_is_source_file", "_incomplete_note",
    "_GIT_TIMEOUT", "_ALIAS_TIMEOUT", "_MAX_NESTED_DEPTH", "_NOTES_DIRNAME",
    "_SAFE_SESSION_ID_RE", "_KNOWN_PATTERNS", "_KEY_VALUE_RE", "_PLACEHOLDER_RE", "_HUNK_RE",
    "_DIFF_GIT_HEADER_RE", "_HEX_ONLY_RE", "_KNOWN_SUBCOMMANDS", "_CONTINUE_SUBCOMMANDS",
    "_COMMIT_VALUE_FLAGS", "_ADD_ALL_FLAGS", "_ADD_FORCE_FLAGS", "_GIT_COMMIT_FALLBACK_RE",
    "_entropy_threshold", "_shannon_entropy", "_looks_like_placeholder", "_normalized_key",
    "_match_secret", "_is_env_filename", "_mask", "_format_finding", "_build_message",
    "_strip_ab_prefix", "_diff_sections", "_section_file_name", "_diff_entries",
    "_scan_diff_text", "_scan_new_file", "_run_git", "_repo_toplevel", "_resolve_dir", "_resolve_alias",
    "_git_call", "_nested_command", "_simple_commands", "_tokenize_chain",
    "_git_commit_invocations", "_scan_commit", "_pending_file", "_queue_note",
    "_ADD_UNTRACKED_FLAGS", "_WHOLE_TREE_PATHSPEC", "_HOOK_BUDGET", "_hook_deadline", "_check_deadline",
    "_ADD_SUBCOMMANDS", "_ADD_VALUE_FLAGS", "_ADD_ALL_LETTERS", "_ADD_UNTRACKED_LETTERS",
    "_ADD_FORCE_LETTERS", "_SHORT_CLUSTER_RE", "_WHOLE_TREE_OPERANDS", "_SHORT_MAGIC_RE",
    "_LONG_MAGIC_RE", "_AddFlags", "_add_flags", "_is_top_anchored_pathspec", "_resolve_pathspec",
    "check_secret_scan", "note_secret_scan",
]

_ALLOW_MARK = "act:allow-secret"
_ENV_ALLOWED = {".env.example", ".env.sample", ".env.template"}
_MAX_DIFF_BYTES = 2 * 1024 * 1024
# Findings named one by one in the hold message; the rest is counted ("+N more", total, files).
_MAX_FINDINGS = 30
# The scan itself stops collecting here (a runaway diff), so the whole list is nearly always complete.
_MAX_COLLECTED = 500
# Kept well under the hook's own ~10s timeout, shared across every subprocess call (diff, ls-files,
# alias lookups) and file read this check makes for one PreToolUse invocation.
_TIME_BUDGET = 4.5
# Hook-wide cap, seconds after dispatch.py's own start (payload["_act_hook_started"]): the harness
# kills a PreToolUse hook at 10 s, and this check, danger_scan and deps_scan run back to back in
# that one process -- each caps its own deadline with _check_deadline() (2026-09-27 review 2, m5).
_HOOK_BUDGET = 8.0
_GIT_TIMEOUT = 3.0
_ALIAS_TIMEOUT = 1.5
_MAX_NESTED_DEPTH = 3
_NOTES_DIRNAME = "secret-scan-notes"
# A session_id becomes an entry's filename (see _pending_file) — validated first, same reasoning
# as checks/encoding_hint.py's own _SAFE_SESSION_ID_RE for the same kind of harness-supplied id.
_SAFE_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")

# Known key/token formats. Order matters where one is a prefix of another (Anthropic's "sk-ant-"
# before the generic OpenAI-style "sk-").
_KNOWN_PATTERNS: tuple[tuple[str, "re.Pattern[str]"], ...] = (
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,255}\b")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("GitLab token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("Stripe live key", re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{24,}\b")),
    ("Google API key", re.compile(r"\bAIza[A-Za-z0-9_-]{35}\b")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("OpenAI-style API key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.eyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b")),
    ("private key block", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
)

# "KEY = 'value'" / "KEY: value" / ".env"-style "KEY=value" / JSON-style '"key": "value"' — key
# and value read apart so the key can be checked against feedback_privacy.SECRET_WORDS and the
# value against entropy/placeholder. The key itself is optionally quoted (JSON), the value either
# quoted or bare. _match_secret tries every candidate on a line via finditer, not just the first.
_KEY_VALUE_RE = re.compile(
    r"""(?:"(?P<qkey>[A-Za-z][A-Za-z0-9_.\-]{0,60})"|(?P<key>[A-Za-z][A-Za-z0-9_.\-]{0,60}))
        \s*[:=]\s*
        (?:
            "(?P<dq>[^"]{20,})"
          | '(?P<sq>[^']{20,})'
          | (?P<bare>[^\s'"#,;]{20,})
        )""",
    re.VERBOSE,
)

_PLACEHOLDER_RE = re.compile(
    r"""(?ix)^(?:
        <[^<>]*>
      | \$\{[^{}]*\}
      | \$[A-Za-z_][A-Za-z0-9_]*
      | x{3,}[\w.-]*
      | changeme
      | change[_-]?me
      | example
      | sample
      | your[_-].*
      | replace[_-]?me
      | placeholder
      | todo
      | \.\.\.
      | n/?a
    )$""",
    re.VERBOSE,
)

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
_DIFF_GIT_HEADER_RE = re.compile(r"^diff --git a/(.*) b/(.*)$", re.M)
_HEX_ONLY_RE = re.compile(r"^[0-9a-fA-F]+$")

_ADD_SUBCOMMANDS = frozenset({"add", "stage"})  # `git stage` is git's own synonym for `git add`
_KNOWN_SUBCOMMANDS = {"add", "stage", "commit", "merge", "cherry-pick", "revert", "rebase", "am"}
_CONTINUE_SUBCOMMANDS = {"merge", "cherry-pick", "revert", "rebase", "am"}
# git-commit options that consume the next word as their own value — never a pathspec operand
# (2026-09-23 review, item 1).
_COMMIT_VALUE_FLAGS = frozenset({
    "-m", "-F", "-C", "-c", "-t",
    "--author", "--date", "--fixup", "--squash", "--cleanup", "--trailer", "--template",
})
# git-add options that consume the next word as their own value (`--chmod=+x` is the documented
# spelling, git's option parser takes `--chmod +x` as well) -- never a pathspec operand.
_ADD_VALUE_FLAGS = frozenset({"--pathspec-from-file", "--chmod"})
# `git add` flags that stage changes repo-wide, not just the named paths (item 2) -- when the add
# names no pathspec at all: git >= 2.0 reads `-A`/`-u` without a pathspec as the whole working tree
# (from a subdirectory too), with a pathspec they only widen what is staged *under* it, which the
# per-path walk in _scan_commit covers on its own (2026-09-27 review 3, M1). A short flag is also
# read from inside a cluster (`-fA`, `-Av`; _SHORT_CLUSTER_RE -- git add has no short option that
# takes a value, so every letter of a cluster is a flag; review 3, m2).
_ADD_ALL_FLAGS = frozenset({"-u", "--update", "-A", "--all", "--no-ignore-removal"})
_ADD_FORCE_FLAGS = frozenset({"-f", "--force"})
# The subset of _ADD_ALL_FLAGS that also stages *untracked* files (`-u`/`--update` never does): such
# an add contributes one whole-tree entry (_WHOLE_TREE_PATHSPEC, git's own "top of the working tree"
# pathspec magic) to the commit's add_paths, so _scan_commit's new-file walk covers the whole tree --
# from a subdirectory too (2026-09-27 review 2, C2).
_ADD_UNTRACKED_FLAGS = frozenset({"-A", "--all", "--no-ignore-removal"})
_ADD_ALL_LETTERS = frozenset("uA")
_ADD_UNTRACKED_LETTERS = frozenset("A")
_ADD_FORCE_LETTERS = frozenset("f")
_SHORT_CLUSTER_RE = re.compile(r"^-[A-Za-z]+$")
_WHOLE_TREE_PATHSPEC = ":/"
# A pathspec operand that is git's own "everything from the top of the working tree": as an operand
# it means the same as `-A` with no pathspec (unstaged pass plus the whole-tree entry).
_WHOLE_TREE_OPERANDS = frozenset({":/", ":(top)"})
# Pathspec magic (gitglossary "pathspec"): short form `:` plus signature characters from `/` (top)
# and `!`/`^` (exclude), optionally closed by another `:`; long form `:(word,word)pattern`. Only a
# *top-anchored* one reads the same from whichever directory git runs in, so only that kind is
# handed to git unchanged (_resolve_pathspec).
_SHORT_MAGIC_RE = re.compile(r"^:([/!^]*)")
_LONG_MAGIC_RE = re.compile(r"^:\(([^)]*)\)")

_GIT_COMMIT_FALLBACK_RE = re.compile(r"\bgit\b.{0,80}?\bcommit\b", re.S)


def _entropy_threshold(value: str) -> float:
    """3.0 bit/char for a purely hex-digit value (its own max is ~4.0, so a real hex secret still
    clears this easily), 3.5 otherwise — the key-name gate (feedback_privacy.SECRET_WORDS) already
    keeps ordinary code/prose from ever reaching this check, so the bar itself can sit lower than a
    flat 4.0 without reopening that door (2026-09-23 review, item 4)."""
    return 3.0 if _HEX_ONLY_RE.match(value) else 3.5


def _shannon_entropy(value: str) -> float:
    """Bits per character. 0.0 for an empty string (never reached here — the caller only ever
    passes a value already matched at >= 20 chars)."""
    if not value:
        return 0.0
    length = len(value)
    counts = Counter(value)
    return -sum((n / length) * math.log2(n / length) for n in counts.values())


def _looks_like_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER_RE.match(value.strip()))


_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_KEY_SEPARATOR_RE = re.compile(r"[_.]+")


def _normalized_key(key: str) -> str:
    """`key` with every camelCase transition and `_`/`.` run turned into `-` — the one separator
    feedback_privacy.SECRET_WORDS' `\\b`-anchored vocabulary reliably treats as a boundary. `_`
    is itself a word character in Python's regex engine, so `\\btoken\\b` never matches inside a
    raw "SECRET_TOKEN" — the underscore hides the boundary instead of making one. `-` does not
    have that problem (and is already one of the two separators `api[_-]?key`/`private[_-]?key`
    accept), so normalizing onto it fixes SCREAMING_SNAKE_CASE and camelCase keys alike without
    touching feedback_privacy.py itself."""
    return _KEY_SEPARATOR_RE.sub("-", _CAMEL_BOUNDARY_RE.sub("-", key))


_MEMBER_ACCESS_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*(?:\??\.[A-Za-z_$][A-Za-z0-9_$]*)+$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
# Source-code files, where an unquoted value after `key =`/`key:` is an expression (a variable, a
# member path, a call), not a literal. Everything else -- `.env*`, .ini/.cfg/.conf/.properties,
# .yaml/.yml/.toml, no extension, any unknown extension, shell scripts (`KEY=value` is a literal
# there) -- reads a bare value as a literal and keeps measuring it.
_SOURCE_EXTENSIONS = frozenset({
    ".py", ".js", ".mjs", ".cjs", ".ts", ".mts", ".cts", ".tsx", ".jsx", ".vue", ".svelte", ".php",
    ".java", ".kt", ".kts", ".go", ".cs", ".rb", ".rs", ".swift", ".scala", ".c", ".h", ".cpp", ".hpp",
    ".cc", ".dart", ".lua",
})


def _is_source_file(path: Optional[str]) -> bool:
    if not path:
        return False
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name.startswith(".env"):
        return False
    return os.path.splitext(name)[1] in _SOURCE_EXTENSIONS


_CALL_RE = re.compile(r"^[A-Za-z_$][\w$.?]*\(")
_COMMENT_PREFIXES = ("#", "//", "/*", "*", "--", "<!--")
# Markers that open a comment somewhere before the value on the same line (`x = f()  # key=...`).
# Found inside a string literal they cost an exemption, never a finding -- the safe direction.
_INLINE_COMMENT_MARKERS = ("#", "//", "/*", "<!--")
_DIGIT_RUN_RE = re.compile(r"[0-9]+")


def _looks_random(value: str) -> bool:
    """Two or more separate digit runs between letters (`Ab3dEf9Gh`) -- how generated keys look, and
    how hand-written names (`sha256Hash`, `oauth2Client`, `req.body.accessToken`) rarely do."""
    return len(_DIGIT_RUN_RE.findall(value)) >= 2


def _is_expression_value(value: str, path: Optional[str], line: str = "", start: int = 0) -> bool:
    """True for an unquoted value that is code, not a literal: a call (`name(` / `a.b(`), a member
    path (`req.body.accessToken`) or a plain identifier -- in a source-code file only, never on a
    comment line or after a comment marker earlier on the line (`start` is where the key=value
    candidate begins), and never for a value that looks generated (_looks_random) -- so a key left
    in a trailing comment, a docstring, a template literal or a JSX attribute is still measured."""
    if not _is_source_file(path) or line.lstrip().startswith(_COMMENT_PREFIXES):
        return False
    if any(marker in line[:start] for marker in _INLINE_COMMENT_MARKERS):
        return False
    if _looks_random(value):
        return False
    shapes = (_CALL_RE, _MEMBER_ACCESS_RE, _IDENTIFIER_RE)
    return any(shape.match(value) for shape in shapes)


def _match_secret(line: str, path: Optional[str] = None) -> Optional[tuple[str, str]]:
    """(kind, matched value) for the first thing in `line` that looks like a secret, or None. `path`
    (the file the line came from, when known) decides whether an unquoted identifier is code or a
    literal (_is_expression_value); a quoted value is always measured. The
    caller is responsible for the `act:allow-secret` exemption — checked once per line before this
    is even called, not repeated here. Every key=value-shaped candidate on the line is tried in
    turn (finditer, not just the first match) — a line can carry more than one such pair, and an
    earlier one not passing the key/entropy gate must not hide a later one that does."""
    for kind, pattern in _KNOWN_PATTERNS:
        match = pattern.search(line)
        if match and not _looks_like_placeholder(match.group(0)):
            return kind, match.group(0)
    for match in _KEY_VALUE_RE.finditer(line):
        key = match.group("qkey") or match.group("key")
        quoted = match.group("dq") or match.group("sq")
        value = quoted or match.group("bare")
        if (
            value
            and not (not quoted and _is_expression_value(value, path, line, match.start()))
            and not _looks_like_placeholder(value)
            and feedback_privacy.SECRET_WORDS.search(_normalized_key(key))
            and _shannon_entropy(value) >= _entropy_threshold(value)
        ):
            return "high-entropy assignment", value
    return None


def _is_env_filename(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    if name in _ENV_ALLOWED:
        return False
    return name == ".env" or name.startswith(".env.")


def _mask(value: str) -> str:
    return f"{value[:4]}…" if value else "…"


def _format_finding(finding: dict) -> str:
    location = f"{finding['file']}:{finding['line']}" if finding.get("line") else finding["file"]
    shown_value = f" {_mask(finding['value'])}" if finding.get("value") else ""
    return f"{location} ({finding['kind']}){shown_value}"


def _build_message(findings: list[dict]) -> str:
    shown = findings[:_MAX_FINDINGS]
    rest = findings[_MAX_FINDINGS:]
    more = ""
    if rest:
        files = sorted({f["file"] for f in rest})
        listed = ", ".join(files[:5]) + (f", +{len(files) - 5} more files" if len(files) > 5 else "")
        capped = f", scan stopped at {_MAX_COLLECTED}" if len(findings) >= _MAX_COLLECTED else ""
        more = f" (+{len(rest)} more, {len(findings)} findings in total{capped}; also in: {listed})"
    return (
        "[act] commit held: possible secret in " + "; ".join(_format_finding(f) for f in shown)
        + more + " — remove it or mark the line act:allow-secret"
    )


def _incomplete_note(timed_out: bool, oversized: list[str]) -> str:
    """The "not fully checked" note, saying which limit hit: the time budget (_TIME_BUDGET per
    check, _HOOK_BUDGET from the hook's own start; a git call that failed or timed out counts here
    too) and/or files skipped for size (_MAX_DIFF_BYTES, named)."""
    reasons: list[str] = []
    if timed_out:
        reasons.append(
            f"time budget used up ({_TIME_BUDGET:g}s for this check, {_HOOK_BUDGET:g}s for the whole "
            "hook) or a git call failed"
        )
    if oversized:
        shown = ", ".join(oversized[:5])
        more = f" (+{len(oversized) - 5} more)" if len(oversized) > 5 else ""
        reasons.append(f"skipped for size (over {_MAX_DIFF_BYTES // (1024 * 1024)} MB each): {shown}{more}")
    return (
        "[act] secret-scan: not fully checked — " + "; ".join(reasons)
        + " — review it yourself before committing"
    )


def _strip_ab_prefix(path: str) -> str:
    return path[2:] if path[:2] in ("a/", "b/") else path


_DIFF_SECTION_SPLIT_RE = re.compile(r"(?m)^(?=diff --git )")


def _diff_sections(diff_text: str) -> list[str]:
    """`diff_text` split into one chunk per `diff --git` file section — the unit the 2MB size
    guard now applies to (item 7: a file's own section, not the whole diff)."""
    return [section for section in _DIFF_SECTION_SPLIT_RE.split(diff_text) if section.strip()]


def _section_file_name(section: str) -> Optional[str]:
    """The `b/<path>` name from a section's own `diff --git` header, read from just its first
    ~2000 chars (the header is always right at the start) — used to name a file skipped for size
    without having to scan the rest of a possibly huge section."""
    match = _DIFF_GIT_HEADER_RE.search(section[:2000])
    if not match:
        return None
    return match.group(2) or match.group(1)


def _diff_entries(section: str) -> list[tuple[str, bool, list[tuple[int, str]]]]:
    """A single `diff --git` section (see _diff_sections) as (path, is_new_file, [(line_no,
    added_text), ...]). Only '+' lines are collected (a removed secret never holds up a commit).
    `---`/`+++`/`new file mode`/`index ` are read as file-header lines only *before* the section's
    first `@@` hunk marker — never after (2026-09-23 review, item 9). Before the fix, a file whose
    own first added line happened to read "++ <anything>" (e.g. "++ /dev/null") produced a diff
    line "+++ <anything>" that this parser misread as a *header*, silently dropping that file's
    tracking (`file = None`) and every following line in the section along with it — exactly the
    kind of line an adversarial commit would plant first. -U0 output has no hunk-internal context
    lines, so nothing legitimate is lost by treating everything after the first `@@` as pure +/-
    content."""
    entries: list[tuple[str, bool, list[tuple[int, str]]]] = []
    file: Optional[str] = None
    is_new = False
    line_no: Optional[int] = None
    lines: list[tuple[int, str]] = []
    seen_hunk = False

    def flush() -> None:
        if file is not None:
            entries.append((file, is_new, lines))

    for raw in section.splitlines():
        if raw.startswith("diff --git "):
            flush()
            file, is_new, line_no, lines, seen_hunk = None, False, None, [], False
            continue
        if not seen_hunk and raw.startswith("new file mode"):
            is_new = True
            continue
        if not seen_hunk and raw.startswith("+++ "):
            path = raw[4:].strip()
            file = None if path == "/dev/null" else _strip_ab_prefix(path)
            continue
        if not seen_hunk and (raw.startswith("--- ") or raw.startswith("index ")):
            continue
        if raw.startswith("@@"):
            seen_hunk = True
            match = _HUNK_RE.match(raw)
            line_no = int(match.group(1)) if match else None
            continue
        if file is None or line_no is None:
            continue
        if raw.startswith("+"):
            lines.append((line_no, raw[1:]))
            line_no += 1
        elif raw.startswith("-"):
            continue
        else:
            line_no += 1
    flush()
    return entries


def _scan_diff_text(diff_text: str, findings: list[dict], oversized: list[str]) -> None:
    """Append findings (up to _MAX_COLLECTED total) from `diff_text` in place, per file section —
    a section over _MAX_DIFF_BYTES is skipped and its name appended to `oversized` instead of
    scanned; every other section in the same diff is still scanned normally (item 7)."""
    for section in _diff_sections(diff_text):
        if len(findings) >= _MAX_COLLECTED:
            return
        if len(section.encode("utf-8", "replace")) > _MAX_DIFF_BYTES:
            oversized.append(_section_file_name(section) or "?")
            continue
        for file, is_new, lines in _diff_entries(section):
            if len(findings) >= _MAX_COLLECTED:
                return
            if is_new and _is_env_filename(file):
                findings.append({"file": file, "line": None, "kind": "new .env file", "value": None})
            for line_no, content in lines:
                if len(findings) >= _MAX_COLLECTED:
                    return
                if _ALLOW_MARK in content:
                    continue
                hit = _match_secret(content, file)
                if hit is not None:
                    kind, value = hit
                    findings.append({"file": file, "line": line_no, "kind": kind, "value": value})


def _scan_new_file(path: Path, rel: str, findings: list[dict], oversized: list[str]) -> None:
    """Same content checks as _scan_diff_text, for a brand-new untracked file's whole content
    (there is no diff for it — everything in it is new). A file over _MAX_DIFF_BYTES is skipped
    and named in `oversized`, same as an oversized diff section."""
    if _is_env_filename(rel):
        findings.append({"file": rel, "line": None, "kind": "new .env file", "value": None})
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size > _MAX_DIFF_BYTES:
        oversized.append(rel)
        return
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line_no, content in enumerate(text.splitlines(), start=1):
        if len(findings) >= _MAX_COLLECTED:
            return
        if _ALLOW_MARK in content:
            continue
        hit = _match_secret(content, rel)
        if hit is not None:
            kind, value = hit
            findings.append({"file": rel, "line": line_no, "kind": kind, "value": value})


def _run_git(args: list[str], cwd: str, timeout: float) -> Optional[str]:
    if timeout <= 0:
        return None
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotePath=false", *args], cwd=cwd, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None
    return result.stdout if result.returncode == 0 else None


def _repo_toplevel(cwd: str, timeout: float) -> Optional[str]:
    """`git rev-parse --show-toplevel` for `cwd`, or None -- the base every root-relative name git
    reports (`diff --name-only`, `ls-files --full-name`) is joined onto, never `cwd` itself, which
    may be a subdirectory of the repository (shared by this module, danger_scan and deps_scan)."""
    output = _run_git(["rev-parse", "--show-toplevel"], cwd, timeout)
    if not output:
        return None
    stripped = output.strip()
    return stripped or None


def _hook_deadline(payload: dict) -> Optional[float]:
    """The monotonic instant by which every check in this hook call must have answered --
    dispatch.py's own start (payload["_act_hook_started"], set in its _run_checks) plus
    _HOOK_BUDGET -- or None when the payload carries no start (a direct call from a probe, or a
    check reused outside dispatch.py's PreToolUse run)."""
    started = payload.get("_act_hook_started")
    if isinstance(started, bool) or not isinstance(started, (int, float)):
        return None
    return float(started) + _HOOK_BUDGET


def _check_deadline(payload: dict, budget: float) -> float:
    """now + `budget`, capped by `_hook_deadline(payload)` when there is one -- the deadline a
    check hands to its own git/file work. May already lie in the past when earlier checks used the
    hook's time up; every consumer treats "no time left" as "not fully checked", never as a reason
    to block or to run past the hook's own timeout."""
    deadline = time.monotonic() + budget
    hook_deadline = _hook_deadline(payload)
    if hook_deadline is not None:
        deadline = min(deadline, hook_deadline)
    return deadline


def _resolve_dir(raw: str, base: str) -> Optional[str]:
    """`raw` (a `-C`/`cd` argument or a `git add`/commit pathspec) resolved to an absolute native
    path against `base`, or None if it cannot be placed (still shell-expanded, or resolution
    failed)."""
    if _is_dynamic_target(raw):
        return None
    native = _to_native_path(raw)
    path = Path(native)
    if not path.is_absolute():
        path = Path(_to_native_path(base)) / native
    try:
        return str(path.resolve())
    except OSError:
        return None


@dataclasses.dataclass(frozen=True)
class _AddFlags:
    """What one `git add`'s own flags say about its reach: `all` (`-u`/`-A`: unstaged changes to
    tracked files beyond any named path), `untracked` (`-A`: new files too), `forced` (`-f`: ignored
    files too), `from_file` (`--pathspec-from-file`: the path list sits in a file this module does
    not read -- treated as the whole tree, see the module docstring's known limits)."""
    all: bool = False
    untracked: bool = False
    forced: bool = False
    from_file: bool = False


def _add_flags(args: list[str]) -> _AddFlags:
    """The _AddFlags of one `git add`'s arguments: a long form matched whole, a short flag also
    inside a cluster (`-fA`, `-Av` -- git add has no short option that takes a value, so every
    letter of a cluster is a flag; 2026-09-27 review 3, m2). Words after `--` are operands."""
    all_flag = untracked = forced = from_file = False
    for arg in args:
        if arg == "--":
            break
        if arg == "--pathspec-from-file" or arg.startswith("--pathspec-from-file="):
            from_file = True
        letters = frozenset(arg[1:]) if _SHORT_CLUSTER_RE.match(arg) else frozenset()
        all_flag = all_flag or arg in _ADD_ALL_FLAGS or bool(letters & _ADD_ALL_LETTERS)
        untracked = untracked or arg in _ADD_UNTRACKED_FLAGS or bool(letters & _ADD_UNTRACKED_LETTERS)
        forced = forced or arg in _ADD_FORCE_FLAGS or bool(letters & _ADD_FORCE_LETTERS)
    return _AddFlags(all=all_flag, untracked=untracked, forced=forced, from_file=from_file)


def _is_top_anchored_pathspec(raw: str) -> bool:
    """True for a pathspec carrying git's `top` magic (`:/x`, `:!/x`, `:(top)x`, `:(top,glob)x`):
    matched against the working tree from its top, so it reads the same from whichever directory
    a later git call runs in."""
    long_form = _LONG_MAGIC_RE.match(raw)
    if long_form:
        return "top" in long_form.group(1).split(",")
    short_form = _SHORT_MAGIC_RE.match(raw)
    return bool(short_form) and "/" in short_form.group(1)


def _resolve_pathspec(raw: str, base: str) -> Optional[str]:
    """A `git add`/`git commit` pathspec operand the way _scan_commit hands it back to git: a
    top-anchored magic pathspec unchanged (_is_top_anchored_pathspec), anything else resolved to an
    absolute path against `base` (_resolve_dir) -- None if it cannot be placed. Magic relative to
    the directory git runs in (`:(glob)x`, `:!x`, `:(icase)x`) is not carried along by this walk;
    such an operand goes through _resolve_dir like a plain name and matches nothing (a known limit,
    see the module docstring)."""
    if _is_top_anchored_pathspec(raw):
        return raw
    return _resolve_dir(raw, base)


def _resolve_alias(name: str, cwd: str, timeout: float, cache: dict) -> Optional[str]:
    """First word of `git config --get alias.<name>` in `cwd`, cached in `cache` for the lifetime
    of one check_secret_scan call (so the same unresolved/resolved name is never looked up twice
    in one chain). None if `name` names no alias, is a shell alias ("!..." — unsupported, out of
    scope), or the lookup fails/times out. Does not itself check whether the resolved name is one
    this module understands — the caller does that (2026-09-23 review, item 8)."""
    if name in cache:
        return cache[name]
    resolved: Optional[str] = None
    output = _run_git(["config", "--get", f"alias.{name}"], cwd, timeout)
    if output:
        stripped = output.strip()
        first = stripped.split(None, 1)[0] if stripped else ""
        if first and not first.startswith("!"):
            resolved = first
    cache[name] = resolved
    return resolved


def _git_call(
    words: list[str], cwd: str, deadline: Optional[float], alias_cache: dict,
) -> Optional[dict]:
    """{"kind": "add" | "commit" | "continue", "args": <sub's own args>, "directory": <-C dir or
    None>} for a `git [-C dir] [global opts] <sub> ...` call whose subcommand is `add`, `commit`,
    or one of merge/cherry-pick/revert/rebase/am run with `--continue` (item 8) — resolving a
    *simple* git alias to one of those first when the literal subcommand is none of them and
    `deadline` still has time left (_resolve_alias). Assignments and wrapper commands (sudo, env,
    ...) before `git` are skipped, same as shell_targets._simple_command_targets. None if `words`
    names no such subcommand at all (bare `git`, not `git` in the first place, or a subcommand this
    module has no interest in)."""
    index = 0
    while index < len(words):
        word = words[index]
        if _ASSIGNMENT_RE.match(word):
            index += 1
        elif word in _RESERVED_PREFIXES:
            index += 1
        elif _command_name(word) in _WRAPPER_COMMANDS:
            index += 1
            while index < len(words) and (
                _WRAPPER_ARG_RE.match(words[index]) or _ASSIGNMENT_RE.match(words[index])
            ):
                index += 1
        else:
            break
    if index >= len(words) or _command_name(words[index]) != "git":
        return None

    args = words[index + 1:]
    directory: Optional[str] = None
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "-C" and i + 1 < len(args):
            directory = args[i + 1]
            i += 2
        elif arg in _GIT_GLOBAL_VALUE_FLAGS:
            i += 2
        elif arg.startswith("-"):
            i += 1
        else:
            break
    if i >= len(args):
        return None

    subcommand = args[i]
    sub_args = args[i + 1:]
    if subcommand not in _KNOWN_SUBCOMMANDS and deadline is not None and deadline - time.monotonic() > 0:
        call_cwd = cwd
        if directory is not None:
            resolved_dir = _resolve_dir(directory, cwd)
            if resolved_dir is not None:
                call_cwd = resolved_dir
        resolved = _resolve_alias(
            subcommand, call_cwd, min(_ALIAS_TIMEOUT, deadline - time.monotonic()), alias_cache,
        )
        if resolved in _KNOWN_SUBCOMMANDS:
            subcommand = resolved

    if subcommand in _ADD_SUBCOMMANDS:
        return {"kind": "add", "args": sub_args, "directory": directory}
    if subcommand == "commit":
        return {"kind": "commit", "args": sub_args, "directory": directory}
    if subcommand in _CONTINUE_SUBCOMMANDS and "--continue" in sub_args:
        return {"kind": "continue", "args": sub_args, "directory": directory}
    return None


def _nested_command(words: list[str]) -> Optional[str]:
    """The command string `words` would hand to a nested shell, or None — `bash -c '...'`/
    `sh -c '...'` (any name in shell_targets._SHELL_NAMES, `-c` possibly combined like `-ec`),
    `powershell`/`pwsh -Command '...'`/`-c '...'`, or `cmd /c ...` (the remaining words joined back
    with spaces — cmd's own tokenizing differs enough from POSIX shlex that this is closer to
    correct than picking a single word). Item 6."""
    if not words:
        return None
    name = _command_name(words[0])
    args = words[1:]
    if name in _SHELL_NAMES:
        for idx, arg in enumerate(args):
            if arg.startswith("-") and not arg.startswith("--") and "c" in arg[1:] and idx + 1 < len(args):
                return args[idx + 1]
        return None
    if name in ("powershell", "pwsh"):
        for idx, arg in enumerate(args):
            if arg.lower() in ("-c", "-command") and idx + 1 < len(args):
                return args[idx + 1]
        return None
    if name == "cmd":
        for idx, arg in enumerate(args):
            if arg.lower() == "/c" and idx + 1 < len(args):
                return " ".join(args[idx + 1:])
        return None
    return None


def _simple_commands(tokens: list) -> list[list[str]]:
    """Split a shell_targets token stream into simple commands (word tokens only) in the order
    they appear — everything this module needs from the chain: "did a `git add`/`git commit`
    happen, and in what order", not shell_targets' branch-aware write-target bookkeeping. A word
    right after a redirection operator is not specially dropped (see the module docstring's
    "Known limits")."""
    commands: list[list[str]] = []
    words: list[str] = []
    for text, is_op in tokens:
        if is_op and text in _SEPARATOR_OPS:
            if words:
                commands.append(words)
            words = []
            continue
        if is_op:
            continue
        words.append(text)
    if words:
        commands.append(words)
    return commands


def _tokenize_chain(command: str) -> Optional[list]:
    """shell_targets' own tokenizer (line mode first, whole-command fallback), None if neither
    manages (an unclosed quote, or `$'...'` ANSI-C quoting, which shlex does not know)."""
    if "$'" in command:
        return None
    try:
        return _line_mode_tokens(command)
    except ValueError:
        pass
    try:
        return _shell_tokens(command, newline_is_operator=True)
    except ValueError:
        return None


def _git_commit_invocations(
    command: str,
    base_cwd: str,
    deadline: Optional[float] = None,
    alias_cache: Optional[dict] = None,
    depth: int = 0,
) -> list[dict]:
    """Every `git commit`/continued-operation call in `command`, in order, as {"cwd", "all",
    "add_paths"} — "cwd" is the commit's own directory (moved by a `cd <literal dir>` or
    `git -C dir` earlier in the same chain, a single best-effort current directory, not
    shell_targets' branch-aware set — see the module docstring), "all" is whether -a/--all (or a
    prior all-staging `git add`) applies, "add_paths" a list of {"path", "forced"} named by any
    `git add`/commit-pathspec earlier in the same chain ("forced" when added with `-f`/`--force` —
    see _scan_commit for what that changes). A `bash -c`/`powershell -Command`/`cmd /c` wrapping a
    nested command is unwrapped and scanned recursively (_nested_command, capped at
    _MAX_NESTED_DEPTH). `deadline`/`alias_cache` thread through to _git_call's alias resolution;
    both may be None/omitted for a pure, no-git-access parse (used by tests and the tokenizer
    fallback below).

    Falls back to a coarse raw-text search when the chain cannot be tokenized at all: a bare
    "git ... commit" mention is treated as a `-a`-style commit with no known add-paths —
    over-inclusive on purpose (shell_targets takes the same stance for its own fallback)."""
    if alias_cache is None:
        alias_cache = {}
    tokens = _tokenize_chain(command)
    if tokens is None:
        if _GIT_COMMIT_FALLBACK_RE.search(command):
            return [{"cwd": base_cwd, "all": True, "add_paths": []}]
        return []

    invocations: list[dict] = []
    pending_add_paths: list[dict] = []
    pending_all = False
    cwd = base_cwd
    for words in _simple_commands(tokens):
        if depth < _MAX_NESTED_DEPTH:
            nested = _nested_command(words)
            if nested is not None:
                invocations.extend(
                    _git_commit_invocations(nested, cwd, deadline, alias_cache, depth + 1)
                )
                continue

        call = _git_call(words, cwd, deadline, alias_cache)
        if call is None:
            if words and _command_name(words[0]) == "cd":
                operands, _values = _operands(words[1:])
                if len(operands) == 1 and _SIMPLE_DIR_RE.match(operands[0]) and not operands[0].startswith("-"):
                    new_bases = _cd_bases(frozenset({cwd}), operands[0])
                    if len(new_bases) == 1:
                        (only,) = new_bases
                        if only is not None:
                            cwd = only
            continue

        call_cwd = cwd
        if call["directory"] is not None:
            resolved = _resolve_dir(call["directory"], cwd)
            if resolved is not None:
                call_cwd = resolved

        if call["kind"] == "add":
            args = call["args"]
            flags = _add_flags(args)
            operands, _values = _operands(args, _ADD_VALUE_FLAGS)
            # `git add :/` is git's own "everything from the top" -- read like `-A` with no pathspec
            whole_tree = flags.from_file or any(op in _WHOLE_TREE_OPERANDS for op in operands)
            operands = [op for op in operands if op not in _WHOLE_TREE_OPERANDS]
            add_paths: list[dict] = []
            unplaced = False
            for raw_path in operands:
                resolved_path = _resolve_pathspec(raw_path, call_cwd)
                if resolved_path is None:
                    unplaced = True  # `git add -A "$dir"`: reach unknown, -A/-u keep their widest reading
                else:
                    add_paths.append({"path": resolved_path, "forced": flags.forced})
            # No pathspec at all: `-u`/`-A` stage the whole tree (git >= 2.0, from a subdirectory
            # too) and a bare `git add` is read the same way, over-inclusive on purpose. With a
            # pathspec, `-A`/`-u` only widen what is staged *under* it, which the per-path walk in
            # _scan_commit already covers exactly -- so `git add -A src` gets neither the unstaged
            # whole-tree pass nor the whole-tree entry (2026-09-27 review 3, M1); the whole-tree
            # entry is what lets the new-file walk see untracked files anywhere (review 2, C2).
            if whole_tree or not operands or (flags.all and unplaced):
                pending_all = True
            if whole_tree or (flags.untracked and (not operands or unplaced)):
                pending_add_paths.append({"path": _WHOLE_TREE_PATHSPEC, "forced": flags.forced})
            pending_add_paths.extend(add_paths)

        elif call["kind"] == "commit":
            args = call["args"]
            all_flag = pending_all or any(
                arg == "--all" or (arg.startswith("-") and not arg.startswith("--") and "a" in arg[1:])
                for arg in args
            )
            if any(
                arg == "--pathspec-from-file" or arg.startswith("--pathspec-from-file=")
                for arg in args
            ):
                all_flag = True
            operands, _values = _operands(args, _COMMIT_VALUE_FLAGS)
            extra_paths = list(pending_add_paths)
            for raw_path in operands:
                resolved_path = _resolve_pathspec(raw_path, call_cwd)
                if resolved_path is not None:
                    extra_paths.append({"path": resolved_path, "forced": False})
            invocations.append({"cwd": call_cwd, "all": all_flag, "add_paths": extra_paths})
            pending_add_paths = []
            pending_all = False

        elif call["kind"] == "continue":
            invocations.append({"cwd": call_cwd, "all": False, "add_paths": []})
    return invocations


def _scan_commit(invocation: dict, deadline: float) -> tuple[list[dict], bool, list[str], bool]:
    """Findings for one commit-like invocation, plus whether scanning was cut short (timeout or a
    diff section/file over 2MB — an incomplete scan is never grounds to block on its own, only to
    note), the names of any file skipped for size, and whether time (or a failed git call) was
    what cut it short -- the two reasons get distinct wording in check_secret_scan's note."""
    findings: list[dict] = []
    oversized: list[str] = []
    incomplete = timed_out = False
    cwd = invocation["cwd"]
    if not os.path.isdir(cwd):
        return findings, False, oversized, False

    def budget() -> float:
        return min(_GIT_TIMEOUT, deadline - time.monotonic())

    # Every git call of the walk runs from the repository's top level, never the commit's own
    # directory: with `diff.relative=true` a diff from a subdirectory names only the files under
    # it, relative to it -- a staged `.env` at the root would silently vanish from a `cd sub && git
    # commit`. From the top level the output is complete and root-relative whichever directory the
    # commit runs from, without `--no-relative` (git >= 2.28 only); the pathspecs handed in are
    # absolute or top-anchored, so the result is otherwise the same (2026-09-27 review 3, m3).
    toplevel = _repo_toplevel(cwd, budget())
    if toplevel is None:
        incomplete = timed_out = True  # not a repository (git commit itself would fail), or out of time
    git_cwd = toplevel or cwd
    staged = _run_git(
        ["diff", "--cached", "--no-color", "--no-ext-diff", "--no-textconv", "-U0"], git_cwd, budget(),
    )
    if staged is None:
        incomplete = timed_out = True
    else:
        _scan_diff_text(staged, findings, oversized)

    if invocation["all"] and len(findings) < _MAX_COLLECTED:
        unstaged = _run_git(
            ["diff", "--no-color", "--no-ext-diff", "--no-textconv", "-U0"], git_cwd, budget(),
        )
        if unstaged is None:
            incomplete = timed_out = True
        else:
            _scan_diff_text(unstaged, findings, oversized)

    for entry in invocation["add_paths"]:
        if len(findings) >= _MAX_COLLECTED:
            break
        if deadline - time.monotonic() <= 0:
            incomplete = timed_out = True
            break
        raw_path = entry["path"]
        if raw_path != _WHOLE_TREE_PATHSPEC:
            # the whole-tree entry's own unstaged diff is the `all` pass above (always set with it)
            path_diff = _run_git(
                ["diff", "--no-color", "--no-ext-diff", "--no-textconv", "-U0", "--", raw_path],
                git_cwd, budget(),
            )
            if path_diff is None:
                incomplete = timed_out = True
            else:
                _scan_diff_text(path_diff, findings, oversized)

        if len(findings) >= _MAX_COLLECTED or deadline - time.monotonic() <= 0:
            if deadline - time.monotonic() <= 0:
                incomplete = timed_out = True
            break
        if toplevel is None:
            break  # nowhere to join root-relative names onto (already noted as incomplete above)
        # --full-name: root-relative names whichever subdirectory the commit runs from, read via
        # the top level -- a bare `ls-files` from a subdirectory would also stop at that
        # subdirectory without an explicit pathspec (2026-09-27 review 2, C2)
        ls_args = ["ls-files", "--others", "--full-name", "-z", "--", raw_path]
        if not entry["forced"]:
            ls_args.insert(2, "--exclude-standard")
        untracked = _run_git(ls_args, toplevel, budget())
        if untracked is None:
            incomplete = timed_out = True
            continue
        for rel in filter(None, untracked.split("\0")):
            if len(findings) >= _MAX_COLLECTED:
                break
            if deadline - time.monotonic() <= 0:
                incomplete = timed_out = True
                break
            _scan_new_file(Path(toplevel) / rel, rel, findings, oversized)
    if oversized:
        incomplete = True
    return findings, incomplete, oversized, timed_out


def _pending_file(root: Path, session_id: str) -> Optional[Path]:
    """Queue of note texts owed to this session, drained by note_secret_scan() on the matching
    PostToolUse event (see this module's docstring). Own directory, own file — a separate queue
    from checks/encoding_hint.py's, whose generic read/write helpers (_pop_pending_notes,
    _queue_pending_note) are reused as-is."""
    if not _SAFE_SESSION_ID_RE.match(session_id):
        return None
    return root / ".act-local" / _NOTES_DIRNAME / f"{session_id}.pending.json"


def _queue_note(payload: dict, note: str) -> None:
    """Best-effort: a failed write here only means note_secret_scan() finds nothing later, never a
    reason to change what check_secret_scan itself does."""
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return
    try:
        root = actlib.repo_root()
    except RuntimeError:
        return
    pending_path = _pending_file(root, session_id)
    if pending_path is not None:
        _queue_pending_note(pending_path, note)


def check_secret_scan(payload: dict) -> int:
    """A `git commit`-like call in a Bash/PowerShell call is held while what it would commit still
    holds a likely secret — see the module docstring for exactly what is checked and how. Applies
    to the orchestrator and every worker alike (no `_is_worker` gate)."""
    config = actlib.read_config()
    mode = _check_mode(config, "secret-scan", default="block")
    if mode == "off":
        return 0

    shell = _shell_command(payload)
    if shell is None:
        return 0
    _tool_name, command = shell

    if "git" not in command:
        return 0  # cheapest possible reject before any tokenizing/subprocess work — a
        # merge/cherry-pick/revert/rebase/am --continue or an alias resolving to `commit` never
        # contains the literal substring "commit" itself, so the filter can only be this broad

    deadline = _check_deadline(payload, _TIME_BUDGET)
    invocations = _git_commit_invocations(command, _base_cwd(payload), deadline, {})
    if not invocations:
        return 0

    findings: list[dict] = []
    incomplete = False
    timed_out = False
    oversized: list[str] = []
    for invocation in invocations:
        if time.monotonic() >= deadline:
            incomplete = timed_out = True
            break
        more, inv_incomplete, inv_oversized, inv_timed_out = _scan_commit(invocation, deadline)
        findings.extend(more)
        incomplete = incomplete or inv_incomplete
        timed_out = timed_out or inv_timed_out
        oversized.extend(inv_oversized)
        if len(findings) >= _MAX_COLLECTED:
            break

    if findings:
        message = _build_message(findings)
        if mode == "warn":
            print(message)
            _queue_note(payload, message)
            return 0
        print(message, file=sys.stderr)
        return 2

    if incomplete:
        note = _incomplete_note(timed_out, oversized)
        print(note)
        _queue_note(payload, note)
    return 0


def note_secret_scan(payload: dict) -> Optional[str]:
    """PostToolUse companion for check_secret_scan's `warn`-mode/incomplete-scan notes — see this
    module's docstring for why a plain PreToolUse stdout line cannot reach the model on its own.
    Returns whatever this same session's PreToolUse call queued, once, then forgets it; None when
    nothing was queued (the common case: block mode with no findings, `off`, or a call this check
    never even looked at). Registered in dispatch.py's own _POST_TOOL_USE_NOTES — not done here
    (out of this module's write scope): add `("secret_scan", "note_secret_scan"),` there
    (dispatch.py:193, right after the `("encoding_hint", "note_encoding_hint")` line)."""
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return None
    try:
        root = actlib.repo_root()
    except RuntimeError:
        return None
    pending_path = _pending_file(root, session_id)
    if pending_path is None:
        return None
    notes = _pop_pending_notes(pending_path)
    if not notes:
        return None
    return "\n".join(notes)


def _base_cwd(payload: dict) -> str:
    cwd_raw = payload.get("cwd")
    return cwd_raw if isinstance(cwd_raw, str) and cwd_raw else os.getcwd()
