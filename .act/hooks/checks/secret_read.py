#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check — reading a secret file (`.env`, private keys, cloud and package-registry
#          credentials) into the assistant's context (PreToolUse): a guardrail next to
#          `R-safe-no-secret-log` and `R-safe-no-secret-diff`, which keep a secret out of a log and
#          out of a commit; this one keeps it out of the conversation in the first place, since
#          whatever enters the context is sent on with every later step. Applies to **everyone** —
#          orchestrator and worker alike. The matching rule text is `R-safe-no-secret-read`;
#          this module only enforces it.
#
#          Covered: the Read tool (`file_path`), the Grep tool (`path`, and `glob` when its own
#          name part targets a secret name), and Bash/PowerShell commands whose reading command
#          (`cat`, `head`, `grep`, `Get-Content`, ... — see `_READ_COMMANDS`) carries a secret path
#          as an argument, and every input redirection target of the raw command line
#          (`< .env`, `read x < .env`, `< .env cat`), whatever command stands before it. Git
#          `<rev>:<path>` operands of show/cat-file/diff/blame/grep and `dd if=`/`tar`/`perl`
#          file operands count as reads. The Glob tool lists names only and is left alone.
#
# Origin of the path list: rebuilt in Python from cc-safety-net, `src/core/rules/secret.ts`
#          (https://github.com/kenryu42/claude-code-safety-net, commit f9f2e5a, MIT licence).
#          Taken over: the exact basenames (plus `id_dsa`, which the source lists only as a variant
#          prefix), the `.env.*` variants, the home-relative credential
#          paths, the id_*/credentials variant names, the key-like basename pattern, and the
#          credential (not the config) paths of the coding CLIs. Not taken over, deliberately: the
#          coding CLIs' *config* files (the source ships them switched off, and a project's own
#          `.claude/settings.json` or `.mcp.json` is routine reading here), and the extensions
#          `asc`, `cscfg`, `gnucash`, `mdf`, `ovpn`, `pcap`, `rdp`, `sdf`, `tblk`, `tpm` (signatures,
#          captures and ordinary documents: too broad to block by name). The source's licence notice,
#          verbatim:
#
#            MIT License
#
#            Copyright (c) 2026 J Liew
#
#            Permission is hereby granted, free of charge, to any person obtaining a copy
#            of this software and associated documentation files (the "Software"), to deal
#            in the Software without restriction, including without limitation the rights
#            to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#            copies of the Software, and to permit persons to whom the Software is
#            furnished to do so, subject to the following conditions:
#
#            The above copyright notice and this permission notice shall be included in all
#            copies or substantial portions of the Software.
#
#            THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#            IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#            FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#            AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#            LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#            OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
#            SOFTWARE.
#
#          Exceptions: `.env.example`, `.env.sample`, `.env.template` (the same three
#          checks/secret_scan.py lets through), any name ending in `.example`, `.sample` or
#          `.template`, and public keys (`*.pub`). Every name is compared case-insensitively.
#
#          Paths: relative to the call's `cwd`, absolute, or with `~`, `$HOME`, `${HOME}`,
#          `%USERPROFILE%`, `%HOME%`, `$env:USERPROFILE`, `$env:HOME` in front. A home-relative rule
#          matches a path inside the home directory only; it is compared lexically (no symlink or
#          8.3 short-name resolution).
#
# Known limits:
#   - a program that reads the file itself stays invisible — `python script.py`, `node app.js`,
#     `docker run --env-file`; only string literals of an interpreter's inline code (`python -c`,
#     `node -e`, ...) are looked at. `xargs cat`, a path built from a variable (`cat "$F"`) or
#     from a glob (`cat .e*`) is not followed.
#   - an NTFS alternate data stream is cut off the last path segment (`.env::$DATA`, `.env:x`).
#   - a Grep `glob` has its non-nested `{a,b}` groups expanded before the match.
#   - a Grep over a directory (`path` = the project, `glob` = `*`) can still reach a `.env`
#     inside it when the search tool does not skip it; only a path or glob that names a secret
#     file or a secret home directory is refused. Likewise a command naming a *parent* of a
#     secret directory (`grep -r x ~`).
#   - the text of a here-string (`cat <<< .env`) is reported by the scanner as an operand and is
#     refused like a file name; over-refusing, accepted.
#   - a pattern word that merely looks like a secret name (`grep .env README`) is refused as well;
#     over-refusing there is the accepted price. A write redirection on a reading command
#     (`cat x > .env`) is refused for the same reason (the scanner reports both as plain words).
#   - shares command_words.py's and shell_targets.py's own limits for tokenizing (best-effort
#     PowerShell quoting, no expansion of variables or globs).

from __future__ import annotations

import fnmatch
import os
import re
import sys
from pathlib import Path
from typing import Optional

import actlib

from .brace_expand import expand_braces as _expand_braces
from .command_words import _stripped_word_lists
from .common import _check_mode, _shell_command
from .powershell_targets import _extract_ps_command_flag, _ps_tokens
from .shell_targets import _command_name, _to_native_path

__all__ = [
    "SECRET_EXCEPTIONS", "check_secret_read", "secret_label", "_READ_COMMANDS", "_home_roots",
]

SECRET_EXCEPTIONS = frozenset({".env.example", ".env.sample", ".env.template"})

_BASENAMES = frozenset({
    ".env", ".npmrc", ".pypirc", ".netrc", ".git-credentials",
    "id_rsa", "id_dsa", "id_ed25519", "id_ecdsa", "credentials",
})
# Prefixes whose `-x`/`_x` continuations (id_rsa-work, id_ed25519_old) are private keys too.
# `credentials` is left out here: `credentials_helper.py` is ordinary code.
_SEPARATOR_PREFIXES = ("id_rsa", "id_dsa", "id_ed25519", "id_ecdsa")
# Public keys and template copies carry no secret.
_FREE_SUFFIXES = (".pub", ".example", ".sample", ".template")
_VARIANT_PREFIXES = _SEPARATOR_PREFIXES + ("credentials",)
_VARIANT_SUFFIXES = (
    ".bak", ".backup", ".copy", ".disabled", ".key", ".old", ".orig", ".pem", ".save", ".tmp",
)
_SSH_KEY_RE = re.compile(r"^.*_(rsa|dsa|ed25519|ecdsa)$")
_EXTENSIONS = frozenset({
    "agilekeychain", "bek", "fve", "jks", "keychain", "kwallet", "p12", "pem", "pfx", "pkcs12",
    "psafe3", "key", "keypair", "keystore", "keyring", "kdb", "kdbx",
})

# Home-relative paths (a directory also covers everything below it); `*` matches one segment.
_HOME_PATHS = (
    ".ssh", ".aws", ".gcp", ".config/gcloud", ".config/gh/hosts.yml",
    ".kube/config", ".docker/config.json",
    *(f".kube/config{s}" for s in (".bak", ".backup", ".copy", ".disabled", ".old", ".orig", ".save", ".tmp")),
    *(f".docker/config.json{s}" for s in (".bak", ".backup", ".copy", ".disabled", ".old", ".orig", ".save", ".tmp")),
    # credentials of coding CLIs (their config files are deliberately not listed, see the header)
    ".claude/.credentials.json",
    ".codex/auth.json", ".codex/.credentials.json", ".codex/secrets", ".codex/.sandbox-secrets",
    ".gemini/oauth_creds.json", ".gemini/mcp-oauth-tokens.json", ".gemini/a2a-oauth-tokens.json",
    ".gemini/gemini-credentials.json",
    ".copilot/config.json", ".copilot/mcp-oauth-config", ".copilot/mcp-secrets",
    ".kimi-code/server.token", ".kimi-code/credentials", ".kimi/credentials", ".kimi/mcp-oauth",
    ".local/share/opencode/auth.json", ".local/share/opencode/mcp-auth.json",
    ".local/share/opencode/opencode.db",
    ".pi/agent/auth.json",
    ".local/share/amp/secrets.json", ".amp/oauth",
    ".cursor/auth.json", ".config/cursor/auth.json", ".cursor/projects/*/mcp-auth.json",
    ".grok/auth.json", ".grok/mcp_credentials.json",
    ".factory/auth.encrypted", ".factory/auth.v2.file", ".factory/auth.v2.key",
    ".factory/auth.v2.loginkeychain",
    ".local/share/devin/credentials.toml", ".local/share/devin/mcp/oauth",
)
_HOME_PATH_PARTS = tuple(tuple(p.split("/")) for p in _HOME_PATHS)

# Names a glob can stand for; a Grep `glob` is refused when it matches one of these by more than
# its wildcards.
_GLOB_SAMPLES = (
    ".env", ".env.local", ".env.production", "id_rsa", "id_ed25519", "id_rsa.pem", "credentials",
    ".npmrc", ".pypirc", ".netrc", ".git-credentials", "server.pem", "server.key", "store.p12",
    "store.pfx", "store.jks", "vault.kdbx", "x_rsa",
)

# Commands that put a file's content in front of the reader (or send it elsewhere): a secret
# path as an argument of one of these is a read. Lower-case, directory and `.exe` dropped.
_READ_COMMANDS = frozenset({
    "cat", "tac", "nl", "head", "tail", "less", "more", "most", "bat", "batcat", "type",
    "od", "xxd", "hexdump", "strings", "base64", "basenc", "cut", "sort", "uniq", "paste", "tr",
    "fold", "fmt", "rev", "column", "diff", "cmp", "comm", "grep", "egrep", "fgrep", "rg", "ag",
    "ack", "sed", "awk", "gawk", "mawk", "jq", "yq", "openssl", "cp", "scp", "rsync", "source",
    ".", "curl", "wget", "xargs", "zcat", "dd", "tar", "readarray", "mapfile", "read",
    # PowerShell
    "get-content", "gc", "select-string", "sls", "import-csv", "import-clixml",
    "convertfrom-json", "copy-item", "cpi", "copy", "start-process", "invoke-item",
})
# Of these, the last operand is the destination — written to, not read (`cp .env.example .env`).
_COPY_COMMANDS = frozenset({"cp", "scp", "rsync", "copy", "copy-item", "cpi"})
_INTERPRETERS = frozenset({
    "python", "python2", "python3", "py", "node", "nodejs", "deno", "bun", "ruby", "perl", "php",
    "pwsh", "powershell", "lua",
})
_DOTNET_READ_RE = re.compile(
    r"(?:ReadAll(?:Text|Lines|Bytes)|OpenRead|OpenText|StreamReader)\s*\(\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
_LITERAL_RE = re.compile(r"""['"]([^'"\s]+)['"]""")
_HOME_TOKEN_RE = re.compile(
    r"^(?:~|\$\{?HOME\}?|\$\{?USERPROFILE\}?|%USERPROFILE%|%HOME%|\$env:(?:USERPROFILE|HOME)|\$\{env:(?:USERPROFILE|HOME)\})(?=[/\\]|$)",
    re.IGNORECASE,
)
_WILDCARD_CHARS = "*?["
# `<` / `0<` input redirection (not `<<`, `<<<`, `<(`): the target word, quoted or bare.
_REDIRECT_IN_RE = re.compile(r"""(?<!<)<(?![<(])\s*("[^"]*"|'[^']*'|[^\s;&|()<>]+)""")
# `xargs -a FILE` / `--arg-file FILE` (command_words strips `xargs` as a wrapper, so it is read raw).
_XARGS_FILE_RE = re.compile(r"""\bxargs\b[^;&|\n]*?\s(?:-a\s*|--arg-file(?:=|\s+))("[^"]*"|'[^']*'|[^\s;&|()<>]+)""")
# Git subcommands that print file content; their `<rev>:<path>` operands and file operands are reads.
_GIT_READ_SUBCOMMANDS = frozenset({"show", "cat-file", "diff", "blame", "annotate", "grep", "log", "difftool"})
# Interpreters whose plain file operands are read too (`perl -pe1 .env`).
_INTERPRETER_FILE_ARGS = frozenset({"perl", "ruby"})
_PS_ASSIGN_RE = re.compile(r"^\$\w+$")


def _home_roots() -> list[str]:
    """The user's home directory in the lower-cased, forward-slash form `_normalize` produces,
    from the environment first (HOME, USERPROFILE) and `Path.home()` last; duplicates dropped."""
    candidates = [os.environ.get("HOME"), os.environ.get("USERPROFILE")]
    try:
        candidates.append(str(Path.home()))
    except (RuntimeError, OSError):
        pass
    roots: list[str] = []
    for candidate in candidates:
        if candidate:
            normalized = _normalize(_to_native_path(candidate), None)
            if normalized and normalized not in roots:
                roots.append(normalized)
    return roots


def _normalize(path: str, cwd: Optional[str]) -> Optional[str]:
    """`path` as an absolute, lexically normalized, forward-slash, case-folded string; None for a
    relative path with no `cwd` to join it onto."""
    text = path.replace("\\", "/")
    lowered_prefix = text[:8].lower()
    if lowered_prefix.startswith("//?/unc/"):
        text = "//" + text[8:]
    elif lowered_prefix.startswith(("//?/", "//./")):
        text = text[4:]
    if not (text.startswith("/") or re.match(r"^[A-Za-z]:/", text)):
        if cwd is None:
            return None
        text = f"{_to_native_path(cwd).replace(chr(92), '/')}/{text}"
    return os.path.normcase(os.path.normpath(text)).replace("\\", "/").lower()


def _expand_home(word: str) -> tuple[str, bool]:
    """(`word` with a leading home token replaced by the home directory, whether one was)."""
    match = _HOME_TOKEN_RE.match(word)
    if not match:
        return word, False
    roots = _home_roots()
    if not roots:
        return word, False
    return roots[0] + word[match.end():], True


def _basename_label(name: str) -> Optional[str]:
    """Why a file *named* `name` (any directory) counts as a secret, or None."""
    lowered = name.lower()
    if not lowered or lowered in SECRET_EXCEPTIONS or lowered.endswith(_FREE_SUFFIXES):
        return None
    if lowered in _BASENAMES:
        return f"{lowered} file"
    if lowered.startswith(".env."):
        return ".env variant"
    for prefix in _SEPARATOR_PREFIXES:
        if lowered.startswith(prefix) and lowered[len(prefix):len(prefix) + 1] in ("-", "_"):
            return f"{prefix} variant"
    for prefix in _VARIANT_PREFIXES:
        if lowered.startswith(prefix) and lowered[len(prefix):] in _VARIANT_SUFFIXES:
            return f"{prefix} variant"
    if _SSH_KEY_RE.match(lowered):
        return "SSH private key name"
    if "." in lowered:
        extension = lowered.rsplit(".", 1)[1]
        if extension in _EXTENSIONS:
            return f".{extension} key or keystore file"
    return None


def _home_label(normalized: str) -> Optional[str]:
    """Why an absolute, normalized path inside the home directory counts as a secret, or None."""
    for root in _home_roots():
        if not normalized.startswith(root + "/"):
            continue
        parts = normalized[len(root) + 1:].split("/")
        for pattern in _HOME_PATH_PARTS:
            if len(parts) >= len(pattern) and all(
                fnmatch.fnmatchcase(part, pat) for part, pat in zip(parts, pattern)
            ):
                return f"~/{'/'.join(pattern)}"
    return None


def secret_label(raw: str, cwd: Optional[str]) -> Optional[str]:
    """Why the path `raw` (as written in a tool call or command) counts as a secret file or
    directory, or None. Never raises."""
    word = raw.strip().strip("'\"")
    if not word or "\0" in word:
        return None
    try:
        expanded, _ = _expand_home(word)
        head, slash, last = expanded.replace("\\", "/").rpartition("/")
        if ":" in last and not (not head and re.match(r"^[A-Za-z]:", last)):
            expanded = head + slash + last.split(":", 1)[0]
        name = expanded.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        label = _basename_label(name)
        if label:
            return label
        normalized = _normalize(expanded, cwd)
        return _home_label(normalized) if normalized else None
    except (OSError, ValueError):
        return None


def _glob_label(pattern: str, cwd: Optional[str]) -> Optional[str]:
    """Judge a Grep `glob` after brace expansion, see `_glob_variant_label`."""
    for variant in _expand_braces(pattern):
        label = _glob_variant_label(variant, cwd)
        if label:
            return label
    return None


def _glob_variant_label(pattern: str, cwd: Optional[str]) -> Optional[str]:
    """Like `secret_label` for a Grep `glob`: a name part without wildcards is judged as a path;
    one with wildcards is refused when it matches a known secret name and has literal text of
    its own (`*` and `**/*` reach everything and are not refused)."""
    name = pattern.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    if not any(char in name for char in _WILDCARD_CHARS):
        return secret_label(pattern, cwd)
    if not name.strip(_WILDCARD_CHARS + "."):
        return None
    lowered = name.lower()
    for sample in _GLOB_SAMPLES:
        if fnmatch.fnmatchcase(sample, lowered) and _basename_label(sample):
            return f"glob matching {sample}"
    return None


def _candidate_words(word: str) -> list[str]:
    """The path-like strings inside one command word: the word itself, the value of
    `--opt=value` / `-Param:value`, and a curl-style `@file`."""
    candidates = [word]
    if re.match(r"^[A-Za-z_]\w*=", word):
        candidates.append(word.split("=", 1)[1])
    if word.startswith("-") and len(word) > 1:
        for separator in ("=", ":"):
            if separator in word:
                candidates.append(word.split(separator, 1)[1])
    more = [c[1:] for c in candidates if c.startswith("@") and len(c) > 1]
    more += [c.split("@", 1)[1] for c in candidates if c.startswith("-") and "=@" in c]
    return candidates + more


def _ps_word_lists(command: str, depth: int = 0) -> list[list[str]]:
    """The simple commands of a PowerShell command line as word lists, read with PowerShell's own
    tokenizer (a backslash is a path separator there, not an escape), including the text behind a
    nested `pwsh -Command`; empty when the line cannot be tokenized."""
    try:
        tokens = _ps_tokens(command)
    except Exception:  # noqa: BLE001 — falls back to the shell word scanner alone
        return []
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


# Options of the search tools that take a value, for finding the search pattern (the first operand
# that is not an option or an option's value). Short options by command family, then long ones. An
# option not listed counts as a switch: a misjudged value then ends up read as the pattern, and the
# real pattern is checked as a file name, which can only refuse more, never less.
_GREP_FAMILY = {"grep": "grep", "egrep": "grep", "fgrep": "grep", "rg": "rg"}
# (`-C` is no value option of grep for the same reason as `--context` below: in BSD grep its value is
# optional and glued on, so `grep -C foo .env` searches for `foo`.)
_GREP_VALUE_SHORT = {
    "grep": frozenset("ABmefdD"),
    "rg": frozenset("ABCmefgtTjMErd"),
    "git-grep": frozenset("ABCmef"),
}
# (`--context` is left out on purpose: BSD grep takes an optional value there, so a following word
# may be the pattern; read as a switch it can only refuse more.)
_GREP_VALUE_LONG = frozenset({
    "--after-context", "--before-context", "--max-count", "--regexp", "--file",
    "--directories", "--devices", "--include", "--exclude", "--exclude-dir", "--exclude-from",
    "--label", "--binary-files", "--glob", "--iglob", "--type", "--type-not", "--type-add",
    "--max-depth", "--max-columns", "--threads", "--replace", "--encoding", "--sort", "--sortr",
    "--colors", "--pre", "--pre-glob", "--ignore-file", "--path-separator", "--engine",
    "--max-filesize",
})
# `-e PATTERN` / `-f FILE` (and the long forms): the pattern then comes from the option, so every
# operand is a file. Long names are matched by prefix, since GNU tools accept an abbreviation.
_GREP_PATTERN_SHORT = frozenset("ef")
_GREP_PATTERN_LONG = ("--regexp", "--file")


def _grep_pattern_index(args: list[str], family: str) -> Optional[int]:
    """Index in `args` (the words after a grep-like command or after `git grep`) of the search
    pattern given as a plain operand, or None when there is none to skip: the pattern is supplied
    by `-e`/`--regexp`/`-f`/`--file` (every operand is a file then), or no operand exists."""
    short_value = _GREP_VALUE_SHORT[family]
    index = 0
    pattern: Optional[int] = None
    options_done = False
    while index < len(args):
        arg = args[index]
        if options_done or not arg.startswith("-") or arg == "-":
            if pattern is None:
                pattern = index
            index += 1
            continue
        if arg == "--":
            options_done = True
            index += 1
            continue
        if arg.startswith("--"):
            name, has_value, _ = arg.partition("=")
            if any(len(name) >= 3 and long_name.startswith(name) for long_name in _GREP_PATTERN_LONG):
                return None
            if not has_value and name in _GREP_VALUE_LONG:
                index += 1  # the option's value is the next word
            index += 1
            continue
        position = 1
        while position < len(arg):
            char = arg[position]
            if char in short_value:
                if char in _GREP_PATTERN_SHORT:
                    return None
                if position == len(arg) - 1:
                    index += 1  # the option's value is the next word
                break
            position += 1
        index += 1
    return pattern


def _git_literals(args: list[str]) -> list[str]:
    """The operands of a `git show|cat-file|diff|blame|grep|log ...` call that may name a file:
    every plain word and the `<path>` of every `<rev>:<path>`; empty for any other subcommand."""
    index = 0
    subcommand = None
    while index < len(args):
        arg = args[index]
        if arg in ("-C", "-c", "--git-dir", "--work-tree"):
            index += 2
            continue
        if not arg.startswith("-"):
            subcommand = arg.lower()
            break
        index += 1
    if subcommand not in _GIT_READ_SUBCOMMANDS:
        return []
    literals: list[str] = []
    rest = args[index + 1:]
    pattern_at = _grep_pattern_index(rest, "git-grep") if subcommand == "grep" else None
    for position, arg in enumerate(rest):
        if arg.startswith("-") or position == pattern_at:
            continue
        literals.append(arg)
        if ":" in arg:
            literals.append(arg.split(":", 1)[1])
    return literals


def _command_label(command: str, cwd: Optional[str], powershell: bool = False) -> Optional[tuple[str, str]]:
    """(path, label) of the first secret path a reading command in `command` names, else None."""
    for match in _DOTNET_READ_RE.finditer(command):
        label = secret_label(match.group(1), cwd)
        if label:
            return match.group(1), label
    for match in (*_REDIRECT_IN_RE.finditer(command), *_XARGS_FILE_RE.finditer(command)):
        label = secret_label(match.group(1), cwd)
        if label:
            return match.group(1), label
    try:
        word_lists = _stripped_word_lists(command)
    except Exception:  # noqa: BLE001 — a scanner bug must not turn into a silent allow
        word_lists = []
        for fragment in re.split(r"[;&|\n]+", command):
            words = fragment.split()
            if words:
                word_lists.append(words)
    if powershell:
        word_lists = _ps_word_lists(command) + word_lists
    for words in word_lists:
        # PowerShell `$x = Get-Content .env`: the assignment is not the command.
        while len(words) > 2 and _PS_ASSIGN_RE.match(words[0]) and words[1] == "=":
            words = words[2:]
        if not words:
            continue
        name = _command_name(words[0])
        if name == "git":
            literals = _git_literals([str(word) for word in words[1:]])
        elif name in _READ_COMMANDS:
            literals = [str(word) for word in words[1:]]
            if name in _GREP_FAMILY:
                # The first operand is the search pattern, not a file to read.
                pattern_at = _grep_pattern_index(literals, _GREP_FAMILY[name])
                if pattern_at is not None:
                    del literals[pattern_at]
            if name in _COPY_COMMANDS:
                positional = [i for i, lit in enumerate(literals) if not lit.startswith("-")]
                if len(positional) > 1:
                    del literals[positional[-1]]
        elif name in _INTERPRETERS:
            literals = [lit for word in words[1:] for lit in _LITERAL_RE.findall(str(word))]
            if name in _INTERPRETER_FILE_ARGS:
                literals += [str(word) for word in words[1:]]
        else:
            continue
        for literal in literals:
            for candidate in _candidate_words(literal):
                label = secret_label(candidate, cwd)
                if label:
                    return candidate, label
    return None


def _tool_hits(payload: dict, cwd: Optional[str]) -> Optional[tuple[str, str]]:
    """(path, label) a Read/Grep/Bash/PowerShell call would read, else None."""
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    if tool_name == "Read":
        path = tool_input.get("file_path")
        if isinstance(path, str):
            label = secret_label(path, cwd)
            return (path, label) if label else None
    elif tool_name == "Grep":
        path = tool_input.get("path")
        if isinstance(path, str):
            label = secret_label(path, cwd)
            if label:
                return path, label
        pattern = tool_input.get("glob")
        if isinstance(pattern, str):
            label = _glob_label(pattern, cwd)
            if label:
                return pattern, label
    else:
        shell = _shell_command(payload)
        if shell is not None:
            return _command_label(shell[1], cwd, powershell=shell[0] == "PowerShell")
    return None


# Environment variable that overrides `secret-read` for one run (block | warn | off).
_ENV_OVERRIDE = "ACT_SECRET_READ"


def check_secret_read(payload: dict) -> int:
    """Check: deny reading a secret file into the context (see this module's header). Runs for
    every caller; `warn` lets the call through and reports it on stdout."""
    config = actlib.read_config()
    mode = _check_mode(config, "secret-read", default="block")
    # One run may deviate from the project's value through the environment (docs/ai/config.md: the
    # environment overrides the file for that run); an unknown value there is ignored.
    override = os.environ.get(_ENV_OVERRIDE, "").strip().lower()
    if override in ("block", "warn", "off"):
        mode = override
    if mode == "off":
        return 0
    cwd_raw = payload.get("cwd")
    cwd = cwd_raw if isinstance(cwd_raw, str) and cwd_raw else None
    hit = _tool_hits(payload, cwd)
    if hit is None:
        return 0
    path, label = hit
    lead = "[act] warning --" if mode == "warn" else "[act] read refused --"
    message = (
        f"{lead} `{path}` looks like a secret file ({label}) (R-safe-no-secret-read): its "
        "content would enter the conversation. Ask the owner for the non-secret values you "
        "need, or read the matching `.env.example`; the owner can set `secret-read` to "
        f"`warn` or `off` in docs/ai/config.md § Checks, or for one run with {_ENV_OVERRIDE}"
    )
    if mode == "warn":
        print(message)
        return 0
    print(message, file=sys.stderr)
    return 2
