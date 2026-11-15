#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check — secret scan before a commit (PreToolUse, `R-safe-no-secret-diff`). Triggers on
#          a Bash/PowerShell call that runs `git commit` (also inside a chain, with global options
#          like `git -C x commit`, a nested shell, or a simple git alias) — for orchestrator and
#          worker alike (decided: the dispatcher is the only gate, no separate git hook). What gets
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
#          For a file that cannot carry a comment (JSON), the project lists accepted lines in
#          `docs/ai/local/secret-accepted.md`, one `- <path> <hash>: <reason>` per line (_ACCEPTED_REL;
#          _load_accepted, _line_hash): <path> is root-relative with `/`, <hash> the first 16 hex digits
#          of the SHA-256 of the finding's line as UTF-8 with surrounding whitespace removed and no line
#          ending, so any other change to the line (or the same line in another file) is held again.
#          The hold message prints the finished entry for each finding, never the value. Fail-closed: a
#          file that cannot be read or decoded accepts nothing, a line that does not match the format is
#          skipped, and an entry naming the list itself is ignored, so the list can never exempt its own
#          lines (a value written into a reason is scanned like any other text).
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
#          Two more shapes read apart from that rule: a credential-named parameter in a URL's query
#          string (`https://host/p?api_key=<value>`, `&token=<value>`; _URL_QUERY_RE) and the quoted
#          literal after an environment lookup (`os.environ.get("API_TOKEN") or "<value>"`,
#          `os.getenv('API_TOKEN') or '<value>'`, `process.env.API_TOKEN || "<value>"`, `?? "<value>"`,
#          PHP `getenv('API_TOKEN') ?: '<value>'`; _ENV_FALLBACK_RE, keyed by the variable's name, and
#          in a chain of lookups by every name in it; the default as the second argument
#          `os.environ.get("API_TOKEN", "<value>")`, _ENV_DEFAULT_RE) -- both under the same key-name,
#          length, placeholder and entropy gates; the lookups also cover `import.meta.env`, `Deno.env.get`, Ruby `ENV`,
#          Laravel `env('API_TOKEN', '<value>')`, keyword defaults and Python string prefixes; a single-quoted key (`{'token': '<value>'}`) counts
#          like a double-quoted one, and so does a PHP array entry (`'token' => '<value>'`, _ARROW_RE).
#          All findings are named in the hold message, up to _MAX_FINDINGS one by one, then "+N more"
#          with the total and the affected files, so one round of marking is enough;
#          the scan itself stops collecting at _MAX_COLLECTED.
#          One narrow exemption by shape: in the file `.act-lock.json` at the repository root (the
#          path exactly, not one in a subfolder), a line that consists of nothing but a rule ID as
#          key (`R-...` or `CR-...`) and a value of exactly 64 lowercase hex digits (the override
#          hashes `doctor --accept` writes; _LOCK_OVERRIDE_RE, applied in _match_secret after the
#          known token patterns, so the diff and the new-file path alike). Any other key, any other
#          value shape (63 or 65 digits, upper case, not hex), any other line in that file and the
#          same line in any other file is scanned as before.
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
#          tokenized at all (an unclosed quote, or a `$'` that the quote pass the shell checks share cannot
#          place; that tokenizer reads a live `$'...'` ANSI-C run itself, and a `$'` that is only text is told
#          apart by the same pass),
#          a coarse raw-text fallback treats a bare "git ... commit" mention as a `-a`-style commit
#          with no known add-paths — over-inclusive on purpose, the same stance shell_targets takes
#          for its own tokenizing fallback. The chain is read once, with the word lexer (backtick
#          spans included); a failure in that reading propagates (_git_commit_invocations).
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
#          review 2, m5). A git call that runs past its limit is repeated once, for its own limit
#          or what is left, when at least half a second is left before the deadline (_run_git); a repeat
#          that is not possible or fails again, a loop that stops at the deadline with work still open, and a git alias that cannot
#          be looked up for want of time refuse the commit unchecked (exit 2, "time budget used up":
#          the seconds, run again, how to switch the check off; `warn` mode prints the same text as
#          a note) -- a spent budget is never a pass. Real findings from the part that *was* scanned
#          still hold the commit first. Not a time-out, and so only a note ("not fully checked",
#          _incomplete_note): a git call that failed (not a repository, an error answer: the commit
#          is free) and the files skipped for size, named.
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
#   - `git add -u src` is read as also staging untracked files under `src` (it does not), and
#     `git add -n`/`--dry-run` counts as staging although it stages nothing -- both over-inclusive;
#   - `git commit -am x` reads `x` (the message, glued to the cluster) as a path operand: harmless,
#     a name that exists nowhere matches nothing -- the safe direction;
#   - a `git add -u|-A "$dir"` whose operand cannot be placed keeps the flag's widest reading (the
#     whole tree), over-inclusive on purpose -- a plain `git add "$dir"` stays invisible, as above.

from __future__ import annotations

import dataclasses
import hashlib
import math
import os
import re
import stat
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional

import actlib
import feedback_privacy

from .command_parse import Parse, parse_for
from .common import (
    _HOOK_BUDGET, MAX_NESTING, _check_mode, _hook_deadline, _shell_command, _time_limit_note, _time_limit_refusal,
)
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
    _operands,
    _to_native_path,
)

__all__ = [
    "_ALLOW_MARK", "_ACCEPTED_REL", "_ACCEPTED_HASH_RE", "_LazyAccepted", "_diff_prefix_args", "_line_hash", "_load_accepted", "_ENV_ALLOWED", "_MAX_DIFF_BYTES", "_MAX_FINDINGS", "_MAX_COLLECTED", "_TIME_BUDGET",
    "_SOURCE_EXTENSIONS", "_MEMBER_ACCESS_RE", "_IDENTIFIER_RE", "_CALL_RE", "_is_source_file", "_incomplete_note",
    "_GIT_TIMEOUT", "_ALIAS_TIMEOUT", "_MAX_NESTED_DEPTH", "_NOTES_DIRNAME",
    "_SAFE_SESSION_ID_RE", "_KNOWN_PATTERNS", "_KEY_VALUE_RE", "_PLACEHOLDER_RE", "_HUNK_RE",
    "_URL_QUERY_RE", "_ENV_FALLBACK_RE", "_ENV_BLOCK_RE", "_ENV_KEY_RE", "_ENV_DEFAULT_RE", "_ARROW_RE", "_RULE_LIST_RE", "_DIFF_GIT_HEADER_RE", "_HEX_ONLY_RE", "_KNOWN_SUBCOMMANDS", "_CONTINUE_SUBCOMMANDS",
    "_COMMIT_VALUE_FLAGS", "_ADD_ALL_FLAGS", "_ADD_FORCE_FLAGS", "_GIT_COMMIT_FALLBACK_RE",
    "_entropy_threshold", "_shannon_entropy", "_looks_like_placeholder", "_normalized_key",
    "_LOCK_FILE_REL", "_LOCK_OVERRIDE_RE", "_match_secret", "_is_env_filename", "_mask", "_format_finding", "_build_message",
    "_strip_ab_prefix", "_diff_sections", "_section_file_name", "_diff_entries", "_text_lines", "_match_secret_line",
    "_joined_line_hit",
    "_scan_diff_text", "_scan_new_file", "_run_git", "_GitTimedOut", "_repo_toplevel", "_resolve_dir", "_resolve_alias",
    "_git_call", "_nested_command", "_simple_commands", "_with_span_commands",
    "_git_commit_invocations", "_scan_commit", "_pending_file", "_queue_note",
    "_ADD_UNTRACKED_FLAGS", "_WHOLE_TREE_PATHSPEC", "_HOOK_BUDGET", "_hook_deadline", "_check_deadline",
    "_ADD_SUBCOMMANDS", "_ADD_VALUE_FLAGS", "_ADD_ALL_LETTERS", "_ADD_UNTRACKED_LETTERS",
    "_ADD_FORCE_LETTERS", "_SHORT_CLUSTER_RE", "_WHOLE_TREE_OPERANDS", "_SHORT_MAGIC_RE",
    "_LONG_MAGIC_RE", "_AddFlags", "_add_flags", "_is_top_anchored_pathspec", "_resolve_pathspec",
    "check_secret_scan", "note_secret_scan",
]

_ALLOW_MARK = "act:allow-secret"
# The project's list of accepted lines (see the module docstring), relative to the repository root.
_ACCEPTED_REL = "docs/ai/local/secret-accepted.md"
_ACCEPTED_HASH_RE = re.compile(r"^[0-9a-f]{16}$")
# The list is read only when a finding needs it, and only if it is a plain file of at most this size; a
# line over _ACCEPTED_MAX_LINE characters is skipped (a list entry is one short line).
_ACCEPTED_MAX_BYTES = 256 * 1024
_ACCEPTED_MAX_LINE = 2000
# One line of the lock file's override table: a rule ID and a SHA-256 hex digest, nothing else on the line.
_LOCK_FILE_REL = ".act-lock.json"
_LOCK_OVERRIDE_RE = re.compile(r'\s*"(?:R|CR)-[a-z0-9]+(?:-[a-z0-9]+)+"\s*:\s*"[0-9a-f]{64}"\s*,?\s*')
_ENV_ALLOWED = {".env.example", ".env.sample", ".env.template"}
_MAX_DIFF_BYTES = 2 * 1024 * 1024
# Findings named one by one in the hold message; the rest is counted ("+N more", total, files).
_MAX_FINDINGS = 30
# The scan itself stops collecting here (a runaway diff), so the whole list is nearly always complete.
_MAX_COLLECTED = 500
# Kept well under the hook's own ~10s timeout, shared across every subprocess call (diff, ls-files,
# alias lookups) and file read this check makes for one PreToolUse invocation.
_TIME_BUDGET = 4.5
# The hook-wide cap (_HOOK_BUDGET, common.py): the harness kills a PreToolUse hook at 10 s, and this
# check, danger_scan and deps_scan run back to back in that one process -- each caps its own
# deadline with _check_deadline() (2026-09-27 review 2, m5).
_GIT_TIMEOUT = 3.0
_ALIAS_TIMEOUT = 1.5
_MAX_NESTED_DEPTH = MAX_NESTING
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
    r"""(?:"(?P<qkey>[A-Za-z][A-Za-z0-9_.\-]{0,60})"|'(?P<sqkey>[A-Za-z][A-Za-z0-9_.\-]{0,60})'|(?P<key>[A-Za-z][A-Za-z0-9_.\-]{0,60}))
        \s*[:=]\s*
        (?:
            (?P<tpre>[rRbBfFuU]{0,2})(?:\"\"\"(?P<tdq>[^"]{20,})\"\"\"|'''(?P<tsq>[^']{20,})''')
          | (?P<dpre>[rRbBfFuU]{0,2})"(?P<dq>[^"]{20,})"
          | (?P<spre>[rRbBfFuU]{0,2})'(?P<sq>[^']{20,})'
          | (?P<bare>[^\s'"#,;]{20,})
        )""",
    re.VERBOSE,
)

# A credential-named parameter inside a URL's query string (`https://host/p?api_key=<value>`,
# `&access_token=<value>`): _KEY_VALUE_RE reads `https:` as the key and swallows the whole URL as its
# bare value, so the parameter never gets a turn of its own -- this reads it separately.
_URL_QUERY_RE = re.compile(
    r"""[?&](?P<key>[A-Za-z][A-Za-z0-9_.\-]{0,60})=(?P<value>[^\s&'"#,;]{20,})"""
)
# A literal fallback after an environment lookup (`os.environ.get("API_TOKEN") or "<value>"`,
# `os.getenv('API_TOKEN') or '<value>'`, `os.environ["API_TOKEN"] or "<value>"`): the key is the
# environment variable's name, the value the quoted literal after `or`/`||`/`??`.
#
# The lookup is Python's `environ`/`getenv`, JavaScript's `process.env.NAME` / `process.env?.NAME` /
# `process.env["NAME"]` / `import.meta.env.NAME` / Deno's `Deno.env.get("NAME")`, PHP's `$_ENV["NAME"]` /
# `env('NAME')`, Ruby's `ENV['NAME']`; the operator `or`, `||`, `??` or PHP's `?:` (blanks allowed
# inside). A lookup may be parenthesised, end in TypeScript's `!`, and an inline `/* ... */` comment may
# sit between the operands. A chain of lookups
# (`environ.get("API_TOKEN") or environ.get("X") or "<value>"`) is one match: every name in it is a
# candidate key, since any of them may carry the secret. The literal is double-quoted, single-quoted
# (Python string prefixes `r`/`b`/`f`/`u` and triple quotes included) or a backtick string without `${`.
# Every gap is bounded, so the scan stays linear on one long line.
_ENV_NAME = r"""["'][A-Za-z][A-Za-z0-9_.\-]{0,60}["']"""
_BARE_NAME = r"[A-Za-z_][A-Za-z0-9_]{0,60}"
_GAP = r"(?:\s|/\*[^*\n]{0,80}\*/){0,20}"
_CLOSE = r"!?(?:\s{0,20}\))?"
_ENV_LOOKUP = (
    r"(?:(?:\bos\s{0,20}\.\s{0,20})?(?:environ(?:\s{0,20}\.\s{0,20}(?:get|pop))?|getenv)\s{0,20}[(\[]\s{0,20}" + _ENV_NAME + r"[^)\]]{0,200}[)\]]"
    r"|(?:process\s{0,20}\.\s{0,20}env|import\s{0,20}\.\s{0,20}meta\s{0,20}\.\s{0,20}env)\s{0,20}"
    r"(?:\??\.\s{0,20}" + _BARE_NAME + r"|(?:\?\.\s{0,20})?\[\s{0,20}" + _ENV_NAME + r"\s{0,20}\])"
    r"|\bDeno\s{0,20}\.\s{0,20}env\s{0,20}\.\s{0,20}get\s{0,20}\(\s{0,20}" + _ENV_NAME + r"\s{0,20}\)"
    r"|\$_(?:ENV|SERVER)\s{0,20}\[\s{0,20}" + _ENV_NAME + r"\s{0,20}\]"
    r"|(?<![\w$])ENV\s{0,20}\[\s{0,20}" + _ENV_NAME + r"\s{0,20}\]"
    r"|(?<![\w.$>:])env\s{0,20}\(\s{0,20}" + _ENV_NAME + r"\s{0,20}\))"
)
_ENV_OPERATOR = r"(?:\bor\b|\|\||\?\?|\?\s{0,20}:)"
_STR_PREFIX = r"[rRbBfFuU]{1,2}"
_QUOTED_LITERAL = (
    r"""(?:""" + _STR_PREFIX + r""")?(?:\"\"\"(?P<tdq>[^"]{20,})\"\"\"|\'\'\'(?P<tsq>[^']{20,})\'\'\'"""
    r"""|"(?P<dq>[^"]{20,})"|'(?P<sq>[^']{20,})'|`(?P<bt>(?:[^`$]|\$(?!\{)){20,})`)"""
)
_ENV_FALLBACK_RE = re.compile(
    r"(?P<chain>" + _ENV_LOOKUP + r"(?:" + _CLOSE + _GAP + _ENV_OPERATOR + _GAP + r"(?:\(\s{0,20})?" + _ENV_LOOKUP + r"){0,24})"
    + _CLOSE + _GAP + _ENV_OPERATOR + _GAP + _QUOTED_LITERAL
)
# The variable names inside one matched chain (_ENV_FALLBACK_RE's "chain" group).
_ENV_KEY_RE = re.compile(
    r"""(?:environ(?:\s{0,20}\.\s{0,20}(?:get|pop))?|getenv)\s{0,20}[(\[]\s{0,20}["'](?P<k1>[A-Za-z][A-Za-z0-9_.\-]{0,60})["']
      | (?:process\s{0,20}\.\s{0,20}env|import\s{0,20}\.\s{0,20}meta\s{0,20}\.\s{0,20}env)\s{0,20}
          (?:\??\.\s{0,20}(?P<k2>[A-Za-z_][A-Za-z0-9_]{0,60})
          | (?:\?\.\s{0,20})?\[\s{0,20}["'](?P<k3>[A-Za-z][A-Za-z0-9_.\-]{0,60})["'])
      | \$_(?:ENV|SERVER)\s{0,20}\[\s{0,20}["'](?P<k4>[A-Za-z][A-Za-z0-9_.\-]{0,60})["']
      | Deno\s{0,20}\.\s{0,20}env\s{0,20}\.\s{0,20}get\s{0,20}\(\s{0,20}["'](?P<k5>[A-Za-z][A-Za-z0-9_.\-]{0,60})["']
      | (?<![\w$])ENV\s{0,20}\[\s{0,20}["'](?P<k6>[A-Za-z][A-Za-z0-9_.\-]{0,60})["']
      | (?<![\w.$>:])env\s{0,20}\(\s{0,20}["'](?P<k7>[A-Za-z][A-Za-z0-9_.\-]{0,60})["']""",
    re.VERBOSE,
)
# The default as the lookup's own second argument (`os.environ.get("API_TOKEN", "<value>")`,
# `os.getenv('API_TOKEN', '<value>')`, `os.environ.setdefault(...)`, `os.environ.pop("API_TOKEN", "<v>")`,
# a keyword `default="<v>"` / `key="API_TOKEN"`, Laravel `env('API_TOKEN', '<v>')`, Ruby
# `ENV.fetch('API_TOKEN', '<v>')`, and a nested default `environ.get("A", environ.get("API_TOKEN", "<v>"))`):
# the keys are the first arguments of the calls in "head".
_DEFAULT_FUNC = (
    r"(?:environ\s{0,20}\.\s{0,20}(?:get|setdefault|pop)|getenv|(?<![\w.$>:])env|\bENV\s{0,20}\.\s{0,20}fetch)"
)
_DEFAULT_HEAD = r"(?:os\s{0,20}\.\s{0,20})?" + _DEFAULT_FUNC + r"\s{0,20}\(\s{0,20}(?:key\s{0,20}=\s{0,20})?" + _ENV_NAME + r"\s{0,20},\s{0,20}"
_ENV_DEFAULT_RE = re.compile(
    r"(?P<head>(?:" + _DEFAULT_HEAD + r"){1,6})(?:default\s{0,20}=\s{0,20})?" + _QUOTED_LITERAL
)
# Ruby's default as a block: `ENV.fetch('API_TOKEN') { '<v>' }` / `ENV.fetch('API_TOKEN') do '<v>' end`.
_ENV_BLOCK_RE = re.compile(
    r"(?P<head>\bENV\s{0,20}\.\s{0,20}fetch\s{0,20}\(\s{0,20}" + _ENV_NAME + r"\s{0,20}\)\s{0,20}(?:\{|\bdo\b)\s{0,20})"
    + _QUOTED_LITERAL
)
_QUOTED_NAME_RE = re.compile(r"""["']([A-Za-z][A-Za-z0-9_.\-]{0,60})["']""")
# A PHP-style array entry (`'token' => '<value>'`), the key quoted or bare, the value quoted and
# without a blank (a sentence is not a secret). The bare key only starts where no name character
# precedes it -- otherwise a long run of letters is retried at every position.
_ARROW_RE = re.compile(
    r"""(?:"(?P<qkey>[A-Za-z][A-Za-z0-9_.\-]{0,60})"|'(?P<sqkey>[A-Za-z][A-Za-z0-9_.\-]{0,60})'"""
    r"""|(?<![A-Za-z0-9_.\-])(?P<key>[A-Za-z][A-Za-z0-9_.\-]{0,60}))\s{0,20}=>\s{0,20}"""
    r"""(?:"(?P<dq>[^"]{20,})"|'(?P<sq>[^']{20,})')"""
)
# A validation rule list as an array value (Laravel: `'password' => 'required|string|min:8'`).
_RULE_LIST_RE = re.compile(r"^[a-z_]+(?::[^|]*)?(?:\|[a-z_]+(?::[^|]*)?)+$")

_PERCENT_ESCAPE_RE = re.compile(r"%[0-9A-Fa-f]{2}")

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
# git's own commands. An alias never shadows one of them, so a call of one of these needs no alias lookup (the
# lookup is what a spent time budget cannot afford: _git_call).
_GIT_BUILTINS = frozenset({
    "status", "log", "diff", "show", "branch", "checkout", "switch", "restore", "reset", "clean", "stash", "tag",
    "fetch", "pull", "push", "remote", "clone", "init", "config", "describe", "grep", "blame", "bisect", "mv", "rm",
    "ls-files", "ls-tree", "ls-remote", "rev-parse", "rev-list", "cat-file", "diff-tree", "diff-index", "reflog",
    "worktree", "submodule", "notes", "shortlog", "show-ref", "for-each-ref", "symbolic-ref", "update-ref",
    "apply", "archive", "bundle", "gc", "fsck", "prune", "repack", "maintenance", "help", "version", "var",
    "format-patch", "send-email", "request-pull", "range-diff", "merge-base", "name-rev", "count-objects",
    "hash-object", "write-tree", "read-tree", "commit-tree", "mktree", "check-ignore", "check-attr", "sparse-checkout",
    "difftool", "mergetool", "gitk", "citool", "gui", "instaweb", "daemon", "credential", "filter-branch",
    "replace", "rerere", "verify-commit", "verify-tag", "whatchanged", "cherry", "patch-id", "interpret-trailers",
    "column", "fmt-merge-msg", "unpack-file", "pack-objects", "unpack-objects", "index-pack", "update-index",
    "stripspace", "mailinfo", "mailsplit", "get-tar-commit-id", "scalar", "backfill", "hook", "last-modified",
})
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


def _literal_of(match: "re.Match[str]") -> Optional[str]:
    """The quoted literal of an _ENV_FALLBACK_RE / _ENV_DEFAULT_RE match, whichever quoting it used."""
    for name in ("dq", "sq", "bt", "tdq", "tsq"):
        if match.group(name):
            return match.group(name)
    return None


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
    # after the known patterns, so a provider token shape in the key itself is still caught
    if path is not None and path == _LOCK_FILE_REL and _LOCK_OVERRIDE_RE.fullmatch(line):
        return None  # an override hash in the root lock file, see the module docstring
    def counts(key: str, value: Optional[str], quoted: bool, start: int) -> bool:
        return bool(
            value
            and not (not quoted and _is_expression_value(value, path, line, start))
            and not _looks_like_placeholder(value)
            and feedback_privacy.SECRET_WORDS.search(_normalized_key(key))
            and _shannon_entropy(value) >= _entropy_threshold(value)
        )

    def url_hit(pos: int, endpos: int) -> Optional[str]:
        for match in _URL_QUERY_RE.finditer(line, pos, endpos):
            value = match.group("value")
            # a template or interpolation (`%s`, `%(name)s`, `${x}`) is no literal; a percent-escape
            # (`%2B`) is the start of a URL-encoded one
            if value[0] in "{$<[(" or (value[0] == "%" and not _PERCENT_ESCAPE_RE.match(value)):
                continue
            if counts(match.group("key"), value, True, match.start()):
                return value
        return None

    def pair_hit(pos: int, endpos: int, inner: bool) -> Optional[str]:
        for match in _KEY_VALUE_RE.finditer(line, pos, endpos):
            key = match.group("qkey") or match.group("sqkey") or match.group("key")
            quoted = match.group("tdq") or match.group("tsq") or match.group("dq") or match.group("sq")
            prefix = (
                match.group("tpre") if match.group("tdq") or match.group("tsq")
                else match.group("dpre") if match.group("dq") else match.group("spre")
            )
            if quoted and prefix and "f" in prefix.lower() and "{" in quoted:
                continue  # an f-string with interpolation is an expression, not a literal
            value = quoted or match.group("bare")
            if counts(key, value, bool(quoted), match.start()):
                return value
            if quoted and not inner:
                # a credential pair inside the quoted text (`'cmd': 'run --opt token=<v> now'`):
                # one level only, over a range of its own, so the whole scan stays linear
                group = next(name for name in ("tdq", "tsq", "dq", "sq") if match.group(name))
                found = pair_hit(match.start(group), match.end(group), True) or url_hit(
                    match.start(group), match.end(group))
                if found:
                    return found
        return None

    found = pair_hit(0, len(line), False)
    if found:
        return "high-entropy assignment", found
    found = url_hit(0, len(line))
    if found:
        return "high-entropy assignment", found
    for match in _ENV_FALLBACK_RE.finditer(line):
        value = _literal_of(match)
        for key_match in _ENV_KEY_RE.finditer(match.group("chain")):
            key = next(name for name in key_match.groups() if name)
            if counts(key, value, True, match.start()):
                return "high-entropy assignment", value
    for match in (*_ENV_DEFAULT_RE.finditer(line), *_ENV_BLOCK_RE.finditer(line)):
        value = _literal_of(match)
        for key in _QUOTED_NAME_RE.findall(match.group("head")):
            if counts(key, value, True, match.start()):
                return "high-entropy assignment", value
    for match in _ARROW_RE.finditer(line):
        key = match.group("qkey") or match.group("sqkey") or match.group("key")
        value = match.group("dq") or match.group("sq")
        # a value with a blank is prose (a translation table: `'PASSWORD_EXPLAIN' => 'Enter your ...'`),
        # a `rule|rule:arg` list is a validation rule set, not a secret
        if " " not in value and not _RULE_LIST_RE.match(value) and counts(key, value, True, match.start()):
            return "high-entropy assignment", value
    return None


def _line_hash(content: str) -> str:
    """The first 16 hex digits of the SHA-256 of `content` as UTF-8, surrounding whitespace removed
    (the line ending is never part of it) -- the key of an entry in the accepted list."""
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()[:16]


def _normalized_rel(path: str) -> str:
    rel = path.strip().replace("\\", "/")
    while rel.startswith("./"):
        rel = rel[2:]
    return rel


def _parse_accepted_line(raw: str) -> Optional[tuple[str, str]]:
    """(root-relative path, hash) of one `- <path> <hash>: <reason>` line, or None. Linear in the
    line: split, never a backtracking pattern."""
    line = raw.strip()
    if len(line) > _ACCEPTED_MAX_LINE or not line.startswith("-"):
        return None
    head, colon, reason = line[1:].partition(":")
    if not colon or not reason.strip():
        return None
    words = head.split()
    if len(words) < 2 or not _ACCEPTED_HASH_RE.match(words[-1]):
        return None
    rel = _normalized_rel(" ".join(words[:-1]))
    return (rel, words[-1]) if rel else None


def _load_accepted(toplevel: Optional[str], deadline: Optional[float] = None) -> frozenset[tuple[str, str]]:
    """The (root-relative path, line hash) pairs accepted in the project's list. Fail-closed: no
    repository top level, anything but a plain file (a symlink, a pipe, a device, a directory), a file
    over _ACCEPTED_MAX_BYTES, a missing, unreadable or undecodable file, or a deadline already past
    gives an empty set; a line that does not match the format is skipped on its own. An entry for the
    list itself is ignored (compared case-insensitively)."""
    if not toplevel:
        return frozenset()
    path = Path(toplevel) / _ACCEPTED_REL
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_size > _ACCEPTED_MAX_BYTES:
            return frozenset()
        with open(path, "rb") as handle:
            text = handle.read(_ACCEPTED_MAX_BYTES + 1).decode("utf-8")
    except (OSError, ValueError):
        return frozenset()
    if len(text) > _ACCEPTED_MAX_BYTES or (deadline is not None and time.monotonic() >= deadline):
        return frozenset()
    own = _ACCEPTED_REL.casefold()
    accepted: set[tuple[str, str]] = set()
    for raw in text.splitlines():
        entry = _parse_accepted_line(raw)
        if entry is not None and entry[0].casefold() != own:
            accepted.add(entry)
    return frozenset(accepted)


class _LazyAccepted:
    """The accepted list, read on the first lookup -- a commit without a finding never touches it."""

    def __init__(self, toplevel: Optional[str], deadline: Optional[float]) -> None:
        self._toplevel = toplevel
        self._deadline = deadline
        self._entries: Optional[frozenset[tuple[str, str]]] = None

    def __contains__(self, item: object) -> bool:
        if self._entries is None:
            self._entries = _load_accepted(self._toplevel, self._deadline)
        return item in self._entries


def _diff_prefix_args() -> list[str]:
    """Fixed `a/` and `b/` prefixes for every diff call: `diff.noprefix` or `diff.mnemonicPrefix` in a
    configuration would otherwise change the file names the scan reads back."""
    return ["--src-prefix=a/", "--dst-prefix=b/"]


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


def _accept_hint(findings: list[dict]) -> str:
    """For a line that cannot carry a comment: the finished entries for the accepted list, one per
    finding with a line (path and hash, never the value), the reason left for the person to write."""
    entries = sorted({(f["file"], f["hash"]) for f in findings if f.get("hash")})
    if not entries:
        return ""
    lines = "; ".join(f"- {path} {digest}: <reason>" for path, digest in entries)
    return f" — or, for a false alarm in a file without comments, add to {_ACCEPTED_REL}: {lines}"


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
        + _accept_hint(shown)
    )


def _incomplete_note(git_failed: bool, oversized: list[str]) -> str:
    """The "not fully checked" note for what is no time-out: a git call that failed (not a repository, or
    git answered with an error) and/or files skipped for size (_MAX_DIFF_BYTES, named). A time-out is no
    note but a refusal (_time_limit_message)."""
    reasons: list[str] = []
    if git_failed:
        reasons.append("a git call failed (not a repository, or git answered with an error)")
    if oversized:
        shown = ", ".join(oversized[:5])
        more = f" (+{len(oversized) - 5} more)" if len(oversized) > 5 else ""
        reasons.append(f"skipped for size (over {_MAX_DIFF_BYTES // (1024 * 1024)} MB each): {shown}{more}")
    return (
        "[act] secret-scan: not fully checked — " + "; ".join(reasons)
        + " — review it yourself before committing"
    )


def _time_limit_message(seconds: float) -> str:
    """The text of a scan that ran out of time (_TIME_BUDGET for this check, _HOOK_BUDGET for the whole hook)
    while work was still open: the commit is refused unchecked, `block` mode only."""
    return _time_limit_refusal("secret-scan", seconds, "secret-scan")


def _strip_ab_prefix(path: str) -> str:
    return path[2:] if path[:2] in ("a/", "b/") else path


_C_ESCAPES = {
    "\\": b"\\", '"': b'"', "n": b"\n", "t": b"\t", "a": b"\a", "b": b"\b", "f": b"\f", "r": b"\r", "v": b"\v",
}


def _c_unquote(raw: str) -> str:
    """A file name as git prints it in a diff header: a name with a control character, a quote or a
    backslash (or, without core.quotePath=false, a non-ASCII character) comes wrapped in double quotes
    with C escapes (`\\t`, `\\"`, `\\\\`, octal bytes such as `\\303\\244`). Returns the real name; a name not
    wrapped in quotes, or one that does not decode, comes back as it is."""
    if len(raw) < 2 or raw[0] != '"' or raw[-1] != '"':
        return raw
    inner = raw[1:-1]
    out = bytearray()
    i = 0
    while i < len(inner):
        ch = inner[i]
        if ch != "\\" or i + 1 >= len(inner):
            out.extend(ch.encode("utf-8"))
            i += 1
            continue
        nxt = inner[i + 1]
        if nxt in "01234567":
            j = i + 1
            while j < len(inner) and j < i + 4 and inner[j] in "01234567":
                j += 1
            out.append(int(inner[i + 1:j], 8) & 0xFF)
            i = j
        elif nxt in _C_ESCAPES:
            out.extend(_C_ESCAPES[nxt])
            i += 2
        else:
            out.extend(ch.encode("utf-8"))
            i += 1
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError:
        return inner


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


# Characters `str.splitlines()` also breaks at, besides a line feed: a lone CR, vertical tab, form feed, the
# file separators, NEL, LS and PS. Git counts a line only by its line feed, so a diff or file is split there
# alone and one of these inside a line stays part of it (_match_secret_line then also looks at each piece).
_ODD_BREAK_RE = re.compile("[\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]")


def _text_lines(text: str) -> list[str]:
    """`text` split at the line feed only, one trailing CR of a CRLF line cut off -- the line view git
    itself has (so the numbers match), never `splitlines()`, which would turn the text behind a lone CR,
    form feed, NEL or U+2028 into a line of its own that a diff then reads as context (and skips)."""
    return [raw[:-1] if raw.endswith("\r") else raw for raw in text.split("\n")]


def _match_secret_line(line: str, path: Optional[str] = None) -> Optional[tuple[str, str]]:
    """_match_secret for the whole line, then -- when it holds one of the _ODD_BREAK_RE characters -- for
    each piece between them: an interpreter may read such a character as a line end (a lone CR is
    one for Python), so a secret behind it is as real as one on a line of its own."""
    hit = _match_secret(line, path)
    if hit is None and _ODD_BREAK_RE.search(line):
        for piece in line.splitlines():
            hit = _match_secret(piece, path)
            if hit is not None:
                break
    return hit


# The break between two lines of one expression: the first ends in an operator that joins an environment
# lookup to its literal fallback, or the second starts with one (`process.env.API_TOKEN ||` / `"<literal>"`).
_TRAILING_OPERATOR_RE = re.compile(r"(?:\|\||\?\?|\?\s{0,20}:|\bor)\s*$")
_LEADING_OPERATOR_RE = re.compile(r"^\s*(?:\|\||\?\?|\?\s{0,20}:|or\b)")


def _joined_line_hit(previous: str, line: str, path: Optional[str] = None) -> Optional[tuple[str, str]]:
    """A hit for two neighbouring added lines read as one, when an operator sits at the break between them
    (`const t = process.env.API_TOKEN ||` then `  "<literal>";`): the lookup and its literal fallback are
    one expression that the line-by-line scan cannot see. Only a match that reaches into the second line
    counts -- whatever lies in the first alone was scanned on its own."""
    if not (_TRAILING_OPERATOR_RE.search(previous) or _LEADING_OPERATOR_RE.match(line)):
        return None
    first = previous.rstrip()
    joined = first + " " + line.lstrip()
    for match in _ENV_FALLBACK_RE.finditer(joined):
        if match.end() > len(first):
            return _match_secret(joined, path)
    return None


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

    for raw in _text_lines(section):
        if raw.startswith("diff --git "):
            flush()
            file, is_new, line_no, lines, seen_hunk = None, False, None, [], False
            continue
        if not seen_hunk and raw.startswith("new file mode"):
            is_new = True
            continue
        if not seen_hunk and raw.startswith("+++ "):
            path = raw[4:]
            if path.endswith("\t"):
                path = path[:-1]  # git appends a tab to a name with a blank; the blank itself stays
            path = _c_unquote(path)
            file = None if path == "/dev/null" else _strip_ab_prefix(path)
            continue
        if not seen_hunk and (raw.startswith("rename to ") or raw.startswith("copy to ")):
            # A rename or copy names its new path here (no a/ b/ prefix); a pure one has no `+++` line at
            # all. The new name counts as a new file: `env.txt` -> `.env` brings in a .env file.
            file = _c_unquote(raw.split(" to ", 1)[1])
            is_new = True
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


def _scan_diff_text(
    diff_text: str, findings: list[dict], oversized: list[str],
    accepted: "frozenset[tuple[str, str]] | _LazyAccepted" = frozenset(),
) -> None:
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
            previous: Optional[tuple[int, str]] = None
            for line_no, content in lines:
                if len(findings) >= _MAX_COLLECTED:
                    return
                before, previous = previous, (line_no, content)
                if _ALLOW_MARK in content:
                    continue
                hit = _match_secret_line(content, file)
                if (
                    hit is None and before is not None and before[0] + 1 == line_no
                    and _ALLOW_MARK not in before[1]
                ):
                    hit = _joined_line_hit(before[1], content, file)
                if hit is not None:
                    digest = _line_hash(content)
                    if (_normalized_rel(file), digest) in accepted:
                        continue
                    kind, value = hit
                    findings.append({"file": file, "line": line_no, "kind": kind, "value": value, "hash": digest})


def _scan_new_file(
    path: Path, rel: str, findings: list[dict], oversized: list[str],
    accepted: "frozenset[tuple[str, str]] | _LazyAccepted" = frozenset(),
) -> None:
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
        text = path.read_bytes().decode("utf-8", "replace")  # a lone CR stays, as in the diff path
    except OSError:
        return
    previous_line = ""
    for line_no, content in enumerate(_text_lines(text), start=1):
        if len(findings) >= _MAX_COLLECTED:
            return
        before, previous_line = previous_line, content
        if _ALLOW_MARK in content:
            continue
        hit = _match_secret_line(content, rel)
        if hit is None and before and _ALLOW_MARK not in before:
            hit = _joined_line_hit(before, content, rel)
        if hit is not None:
            digest = _line_hash(content)
            if (_normalized_rel(rel), digest) in accepted:
                continue
            kind, value = hit
            findings.append({"file": rel, "line": line_no, "kind": kind, "value": value, "hash": digest})


_RETRY_MIN_SECONDS = 0.5  # the least a repeat of a timed-out git call is worth starting with


class _GitTimedOut(Exception):
    """A git call of a scan ran past its time limit and could not be repeated before the check's deadline."""


def _run_git(args: list[str], cwd: str, timeout: float, deadline: Optional[float] = None) -> Optional[str]:
    """Stdout of `git <args>` in `cwd`, or None when git fails (an error exit, no git, an unusable `cwd`). A
    call that runs past `timeout` is told apart only with a `deadline` (the check's own, a monotonic instant):
    it is repeated once, for the shorter of its own `timeout` and what is left before the deadline, when at least
    _RETRY_MIN_SECONDS are left, otherwise _GitTimedOut is raised, also for a `timeout` that is already used up.
    Without a deadline a time-out gives None, as a failure does (the callers that only note something)."""
    for attempt in (1, 2):
        if timeout <= 0:
            if deadline is None:
                return None
            raise _GitTimedOut("no time left for a git call")
        try:
            # bytes, decoded here: text mode would turn a lone CR in the output into a line feed and so
            # move the text behind it onto a line of its own (a diff reads that as context and skips it)
            result = subprocess.run(
                ["git", "-c", "core.quotePath=false", *args], cwd=cwd, capture_output=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            if deadline is None:
                return None
            left = deadline - time.monotonic()
            if attempt == 1 and left >= _RETRY_MIN_SECONDS:
                timeout = min(timeout, left)  # the repeat gets its own limit, or what is left of the deadline
                continue
            raise _GitTimedOut(f"a git call ran past {timeout:g} s") from None
        except (OSError, ValueError):
            return None
        return result.stdout.decode("utf-8", "replace") if result.returncode == 0 else None
    return None  # not reached: the second attempt returns or raises


def _repo_toplevel(cwd: str, timeout: float, deadline: Optional[float] = None) -> Optional[str]:
    """`git rev-parse --show-toplevel` for `cwd`, or None (not a repository, or git failed) -- the base every
    root-relative name git reports (`diff --name-only`, `ls-files --full-name`) is joined onto, never `cwd`
    itself, which may be a subdirectory of the repository (shared by this module, danger_scan and deps_scan).
    `deadline` as in _run_git: with one, a time-out raises _GitTimedOut instead of giving None."""
    output = _run_git(["rev-parse", "--show-toplevel"], cwd, timeout, deadline)
    if not output:
        return None
    stripped = output.strip()
    return stripped or None


def _check_deadline(payload: dict, budget: float) -> float:
    """now + `budget`, capped by `_hook_deadline(payload)` when there is one -- the deadline a
    check hands to its own git/file work. May already lie in the past when earlier checks used the
    hook's time up; every consumer treats "no time left" with work still open as a time-out (the scans
    refuse the call unchecked, the notes say they are incomplete), never as a pass, and never runs
    past the hook's own timeout."""
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


def _resolve_alias(name: str, cwd: str, timeout: float, cache: dict, deadline: Optional[float] = None) -> Optional[str]:
    """First word of `git config --get alias.<name>` in `cwd`, cached in `cache` for the lifetime
    of one check_secret_scan call (so the same unresolved/resolved name is never looked up twice
    in one chain). None if `name` names no alias, is a shell alias ("!..." — unsupported, out of
    scope), or the lookup fails. A lookup that runs past its limit raises _GitTimedOut when a `deadline`
    is given (_run_git). Does not itself check whether the resolved name is one this module understands --
    the caller does that (2026-09-23 review, item 8)."""
    if name in cache:
        return cache[name]
    resolved: Optional[str] = None
    output = _run_git(["config", "--get", f"alias.{name}"], cwd, timeout, deadline)
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
    `deadline` still has time left (_resolve_alias); with no time left a name that is no git builtin of its own
    (an alias cannot shadow one) raises _GitTimedOut. Assignments and wrapper commands (sudo, env,
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
    if subcommand not in _KNOWN_SUBCOMMANDS and deadline is not None and deadline - time.monotonic() <= 0:
        if subcommand not in _GIT_BUILTINS:
            # no time left to look the name up, and it may be an alias for a commit: not "not a commit"
            raise _GitTimedOut("no time left to resolve a git alias")
    elif subcommand not in _KNOWN_SUBCOMMANDS and deadline is not None:
        call_cwd = cwd
        if directory is not None:
            resolved_dir = _resolve_dir(directory, cwd)
            if resolved_dir is not None:
                call_cwd = resolved_dir
        resolved = _resolve_alias(
            subcommand, call_cwd, min(_ALIAS_TIMEOUT, deadline - time.monotonic()), alias_cache, deadline,
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


def _with_span_commands(commands: list[list[str]], depth: int = 0) -> list[list[str]]:
    """`commands` with the simple commands of every backtick span in them (each word's `subs`, quote
    context already applied by shell_targets' tokenizer) put in front of the command whose word holds
    the span — bash expands a span before it runs the command around it, so a `git add` there is
    ahead of a later `git commit`. Spans inside spans are followed up to _MAX_NESTED_DEPTH (counted
    from `depth`, the nesting the caller is already at). A span that does not tokenize but
    mentions a commit contributes a `-a`-style `git commit`, the coarse stance of the raw-text
    fallback in _git_commit_invocations."""
    expanded: list[list[str]] = []
    for words in commands:
        if depth < _MAX_NESTED_DEPTH:
            for word in words:
                for span in getattr(word, "subs", ()):
                    span_tokens = Parse("Bash", span).chain_tokens()
                    if span_tokens is not None:
                        expanded.extend(_with_span_commands(_simple_commands(span_tokens), depth + 1))
                    elif _GIT_COMMIT_FALLBACK_RE.search(span):
                        expanded.append(["git", "commit", "-a"])
        expanded.append(words)
    return expanded


_TOKENIZE_HERE: object = object()  # "no tokens handed in": None is a valid handed-in result


def _git_commit_invocations(
    command: str,
    base_cwd: str,
    deadline: Optional[float] = None,
    alias_cache: Optional[dict] = None,
    depth: int = 0,
    chain_tokens: object = _TOKENIZE_HERE,
) -> list[dict]:
    """Every `git commit`/continued-operation call in `command`, in order, read with the word lexer
    (backtick spans included; an exception in it propagates), as {"cwd", "all",
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
    over-inclusive on purpose (shell_targets takes the same stance for its own fallback).

    `chain_tokens` is the result of `Parse.chain_tokens` for the top-level call when the caller
    already has it (the dispatcher's shared parse hands it to the three commit-reading checks; None
    is a result too: the text does not tokenize). Left out, the chain is tokenized here, as are all
    nested texts. Only this pure reading is shared -- alias lookups and their cache stay per call."""
    if alias_cache is None:
        alias_cache = {}
    tokens = Parse("Bash", command).chain_tokens() if chain_tokens is _TOKENIZE_HERE else chain_tokens
    if tokens is None:
        if _GIT_COMMIT_FALLBACK_RE.search(command):
            return [{"cwd": base_cwd, "all": True, "add_paths": []}]
        return []

    invocations: list[dict] = []
    pending_add_paths: list[dict] = []
    pending_all = False
    cwd = base_cwd
    commands = _simple_commands(tokens)
    for words in _with_span_commands(commands, depth):
        if depth < _MAX_NESTED_DEPTH:
            nested = _nested_command(words)
            if nested is not None:
                invocations.extend(
                    _git_commit_invocations(nested, cwd, deadline, alias_cache, depth + 1)
                )
                continue

        call = _git_call(words, cwd, deadline, alias_cache)
        if call is None:
            # A backtick span glued to the name (`` `echo x`cd ``) makes bash run a different command
            # (`xcd`), not `cd`; _command_name reads the name with the span cut out and would see
            # `cd`. Only follow a `cd` whose name word carries no span — otherwise leave cwd where it
            # is (the over-inclusive side: a later commit is then scanned at the unchanged directory).
            if words and _command_name(words[0]) == "cd" and not getattr(words[0], "subs", ()):
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
    # A `$'` that was only text no longer sends the whole command to the raw fallback, so a commit the token
    # reading cannot see (inside `eval`, `bash <<<`, `| bash`, `source <(...)`) must not slip through: when the
    # raw text mentions more commits than were read as invocations, the over-inclusive fallback stays.
    if "$'" in command and len(_GIT_COMMIT_FALLBACK_RE.findall(command)) > len(invocations):
        invocations.append({"cwd": base_cwd, "all": True, "add_paths": []})
    return invocations


def _scan_commit(invocation: dict, deadline: float) -> tuple[list[dict], bool, list[str], bool]:
    """(findings, git_failed, oversized, timed_out) for one commit-like invocation: a git call that failed (not
    a repository, or an error answer) is only worth a note, like the names of the files skipped for size
    (over 2MB); `timed_out` says that time ran out while work was still open (a git call past its limit and
    not repeatable, the deadline reached before the walk was done), which check_secret_scan answers with a
    refusal, not a note. The findings made up to that point are kept."""
    findings: list[dict] = []
    oversized: list[str] = []
    try:
        git_failed, timed_out = _scan_commit_walk(invocation, deadline, findings, oversized)
    except _GitTimedOut:
        return findings, False, oversized, True
    return findings, git_failed, oversized, timed_out


def _scan_commit_walk(invocation: dict, deadline: float, findings: list[dict], oversized: list[str]) -> tuple[bool, bool]:
    """The walk of _scan_commit: fills `findings` and `oversized`, returns (git_failed, timed_out); a git call
    past its limit raises _GitTimedOut."""
    git_failed = timed_out = False
    cwd = invocation["cwd"]
    if not os.path.isdir(cwd):
        return False, False

    def budget() -> float:
        return min(_GIT_TIMEOUT, deadline - time.monotonic())

    # Every git call of the walk runs from the repository's top level, never the commit's own
    # directory: with `diff.relative=true` a diff from a subdirectory names only the files under
    # it, relative to it -- a staged `.env` at the root would silently vanish from a `cd sub && git
    # commit`. From the top level the output is complete and root-relative whichever directory the
    # commit runs from, without `--no-relative` (git >= 2.28 only); the pathspecs handed in are
    # absolute or top-anchored, so the result is otherwise the same (2026-09-27 review 3, m3).
    toplevel = _repo_toplevel(cwd, budget(), deadline)
    if toplevel is None:
        git_failed = True  # not a repository (git commit itself would fail): a note, no time-out
    git_cwd = toplevel or cwd
    accepted = _LazyAccepted(toplevel, deadline)
    staged = _run_git(
        ["diff", "--cached", *_diff_prefix_args(), "--no-color", "--no-ext-diff", "--no-textconv", "-U0"], git_cwd, budget(),
        deadline,
    )
    if staged is None:
        git_failed = True
    else:
        _scan_diff_text(staged, findings, oversized, accepted)

    if invocation["all"] and len(findings) < _MAX_COLLECTED:
        unstaged = _run_git(
            ["diff", *_diff_prefix_args(), "--no-color", "--no-ext-diff", "--no-textconv", "-U0"], git_cwd, budget(),
            deadline,
        )
        if unstaged is None:
            git_failed = True
        else:
            _scan_diff_text(unstaged, findings, oversized, accepted)

    for entry in invocation["add_paths"]:
        if len(findings) >= _MAX_COLLECTED:
            break
        if deadline - time.monotonic() <= 0:
            timed_out = True  # an add path is still unread
            break
        raw_path = entry["path"]
        if raw_path != _WHOLE_TREE_PATHSPEC:
            # the whole-tree entry's own unstaged diff is the `all` pass above (always set with it)
            path_diff = _run_git(
                ["diff", *_diff_prefix_args(), "--no-color", "--no-ext-diff", "--no-textconv", "-U0", "--", raw_path],
                git_cwd, budget(), deadline,
            )
            if path_diff is None:
                git_failed = True
            else:
                _scan_diff_text(path_diff, findings, oversized, accepted)

        if len(findings) >= _MAX_COLLECTED or deadline - time.monotonic() <= 0:
            if deadline - time.monotonic() <= 0 and len(findings) < _MAX_COLLECTED:
                timed_out = True  # the untracked files of this path are still unread
            break
        if toplevel is None:
            break  # nowhere to join root-relative names onto (already noted as failed above)
        # --full-name: root-relative names whichever subdirectory the commit runs from, read via
        # the top level -- a bare `ls-files` from a subdirectory would also stop at that
        # subdirectory without an explicit pathspec (2026-09-27 review 2, C2)
        ls_args = ["ls-files", "--others", "--full-name", "-z", "--", raw_path]
        if not entry["forced"]:
            ls_args.insert(2, "--exclude-standard")
        untracked = _run_git(ls_args, toplevel, budget(), deadline)
        if untracked is None:
            git_failed = True
            continue
        for rel in filter(None, untracked.split("\0")):
            if len(findings) >= _MAX_COLLECTED:
                break
            if deadline - time.monotonic() <= 0:
                timed_out = True  # an untracked file is still unread
                break
            _scan_new_file(Path(toplevel) / rel, rel, findings, oversized, accepted)
    return git_failed, timed_out


def _pending_file(root: Path, session_id: str) -> Optional[Path]:
    """Queue of note texts owed to this session, drained by note_secret_scan() on the matching
    PostToolUse event (see this module's docstring). Own directory, own file — a separate queue
    from checks/encoding_hint.py's, whose generic read/write helpers (_pop_pending_notes,
    _queue_pending_note) are reused as-is."""
    if not _SAFE_SESSION_ID_RE.match(session_id):
        return None
    path = root / ".act-local" / _NOTES_DIRNAME / f"{session_id}.pending.json"
    return path if actlib.local_write_ok(root, path) else None  # behind a link out of the project: nothing queued


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
        _queue_pending_note(pending_path, note, payload)


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

    started = time.monotonic()
    deadline = _check_deadline(payload, _TIME_BUDGET)
    findings: list[dict] = []
    git_failed = False
    timed_out = False
    oversized: list[str] = []
    try:
        invocations = _git_commit_invocations(
            command, _base_cwd(payload), deadline, {},
            chain_tokens=parse_for(payload, command).chain_tokens(),
        )
        for invocation in invocations:
            if time.monotonic() >= deadline:
                timed_out = True  # an invocation is still unscanned
                break
            more, inv_failed, inv_oversized, inv_timed_out = _scan_commit(invocation, deadline)
            findings.extend(more)
            git_failed = git_failed or inv_failed
            timed_out = timed_out or inv_timed_out
            oversized.extend(inv_oversized)
            if len(findings) >= _MAX_COLLECTED or inv_timed_out:
                break
    except _GitTimedOut:
        timed_out = True  # a git alias could not be looked up in time: the call may be a commit
        invocations = []
    if not invocations and not timed_out:
        return 0

    if findings:
        message = _build_message(findings)
        if mode == "warn":
            print(message)
            _queue_note(payload, message)
            return 0
        print(message, file=sys.stderr)
        return 2

    if timed_out:
        message = _time_limit_message(max(deadline - started, 0.0))
        if mode == "warn":
            print(message)  # `warn` never refuses: the same text as a note
            _queue_note(payload, message)
            return 0
        print(message, file=sys.stderr)
        return 2

    if git_failed or oversized:
        note = _incomplete_note(git_failed, oversized)
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
    notes = _pop_pending_notes(pending_path, payload)
    if not notes:
        return None
    return "\n".join(notes)


def _base_cwd(payload: dict) -> str:
    cwd_raw = payload.get("cwd")
    return cwd_raw if isinstance(cwd_raw, str) and cwd_raw else os.getcwd()
