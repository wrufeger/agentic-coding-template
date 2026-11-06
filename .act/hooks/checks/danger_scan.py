#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Check — dangerous-pattern scan before a commit (PreToolUse), the local part of the
#          security check (a decided concept): "Art A" of three. Only Art A is built here — Art B
#          (live library-vulnerability lookup via `pip-audit`/`npm audit`/`osv-scanner`, needs a
#          decision on network access) and Art C (Semgrep / a `reviewer` security pass) are not, per
#          the assignment; the `security-check` key already has four values so a project's config
#          does not have to change again once B/C land.
#
#          Triggers on the exact same `git commit`-like calls as checks/secret_scan.py, reusing its
#          own chain/alias/nested-shell walker (_git_commit_invocations) rather than a second one —
#          "which commit-like call, in which directory, against which diff/add-paths" is identical
#          for both checks; only what is looked for in the added lines differs. Only *added* ('+')
#          lines count, same reasoning as secret_scan.py (a removed dangerous call never holds up a
#          commit).
#
#          Patterns are grouped by the coding rule set they belong to (.act/coding/<name>.md, the
#          same paths docs/project/coding_rules.md's checkboxes name) and only run for a set the
#          project has actually switched on there — read with .act/scripts/rules.py's own parser
#          (rules.parse_project_file), never re-implemented here (R-work-override: the project's
#          checkboxes decide once, in one place). A pattern is matched against the whole added line
#          regardless of which file it is in (same stance secret_scan.py takes: cheap and language-
#          agnostic rather than tied to a file extension) — enabling a coding set is what turns a
#          pattern group on, not the file being edited. The one exception is a pattern that names
#          file extensions of its own (`extensions`, the PHP SQL patterns): it runs only on those
#          files, since its form means something else in other languages.
#
#          Verbatim from the concept's decided behaviour ("the same form as the encoding
#          hint"): a hit stops the first commit once, with the finding's location and reason: the
#          *second* attempt against the very same (reader, file, pattern) goes through — "eval is
#          sometimes the right call". This is exactly checks/encoding_hint.py's own block-mode
#          shape (dedup key -> stop once -> remembered -> quiet from then on), reused deliberately
#          rather than secret_scan.py's shape (which never remembers and always blocks again) —
#          a secret is never "sometimes right", a dangerous pattern can be. The dedup key is
#          (reader, file, pattern id) — not the line number, which shifts on every edit, and not
#          the matched text, which the same pattern can legitimately hit differently each time. A
#          line carrying the marker `act:allow-danger` is never even matched, the same as
#          `act:allow-secret` for the secret scan.
#
#          Adoption baseline: a project taken over has patterns that were there long before the first
#          commit. scripts/adopt_baseline.py books them and lists their exact `file|rule-id` keys in
#          .act-local/danger-scan-hints/baseline.json; a finding with such a key passes without the first
#          hold (an allow-list: exact keys only, no prefix, glob, case folding or path normalisation). The
#          list is separate from the per-reader hints - never merged into them, never written by this
#          check - and counts as empty when it is missing, malformed or reached through a symlink or
#          junction. Limit: the key has no line number, so a later new occurrence of a booked rule in the
#          same file passes too. Secrets (checks/secret_scan.py) are not covered and keep holding.
#
#          `security-check` in docs/ai/config.md (four values, not the usual block/warn/off):
#          `off` runs nothing here at all; `local`/`deps`/`full` all run exactly this module (Art
#          A) — `deps`/`full` do not yet run B/C, so for now they behave like `local`, honestly
#          documented as "not built yet" in the config skeleton rather than silently accepted. An
#          unrecognized or missing value falls back to `local` (the concept's own default:
#          "Standard local").
#
# Known limits:
#   - the SQL-string-concatenation patterns are a rough heuristic (an SQL keyword near a quote-and-
#     `+`, a PHP dot or `"... $var"` interpolation (PHP files only), Python `%` or `.format()`
#     after the literal, or an f-string/template-literal placeholder) - an operator or `+` continued
#     on the next line is not covered; the operator must sit within 200
#     characters of the statement with no `;` in between (INSERT INTO and DELETE FROM with `+`:
#     anywhere on the line), a LIKE operand is ignored by the `%` pattern, and a false positive on
#     ordinary string handling near the word
#     "select" is possible; documented as an open point for the concept rather than tuned further
#     here (2026-09-25, review). A query builder's tagged template literal (sql`...`) is the safe
#     form and is blanked out first (see _SQL_TAGGED_TEMPLATE); only its first line is recognized
#     as tagged, a later line of a multi-line literal is matched like any other line. Blanked out
#     too, unseen: a tag named `sql` that binds nothing (`const sql = String.raw`), a raw fragment
#     built on an earlier line and interpolated here, and a string concatenated onto the literal;
#   - `yaml.load(...)` without `SafeLoader` is detected by *absence* of the word "SafeLoader"
#     anywhere on the same added line — a `Loader=` argument written on a following line (a call
#     split across lines) is invisible, same class of limit secret_scan.py already accepts for its
#     own -U0, line-based diff view;
#   - if docs/project/coding_rules.md cannot be read or parsed at all (missing file, a rules.py
#     bug), this check fails open (no patterns are known to be enabled, so nothing is scanned) -
#     a broken rules.py must not lock out every commit, the same stance checks/session.py takes for
#     its own `import rules`;
#   - patterns run against the whole added line, not the language of the file it lives in - a
#     Python file happening to contain a Vue-shaped `v-html=` string could be flagged if the
#     project has the Vue coding set enabled too; accepted for the same reason secret_scan.py does
#     not check file extensions either (cheap and simple beats precise here).

from __future__ import annotations

import json
import os
import re
import stat
import sys
import time
from pathlib import Path
from typing import Callable, NamedTuple, Optional

import actlib

from .common import _shell_command
from .encoding_hint import _reader_key
from .secret_scan import (
    _check_deadline,
    _diff_entries,
    _diff_sections,
    _git_commit_invocations,
    _repo_toplevel,
    _run_git,
    _text_lines,
    _GIT_TIMEOUT,
    _MAX_DIFF_BYTES,
    _TIME_BUDGET,
    _WHOLE_TREE_PATHSPEC,
)

__all__ = [
    "_ALLOW_MARK", "_HINTS_DIRNAME", "_MAX_FINDINGS", "_SECURITY_CHECK_LEVELS", "_DOC_EXTENSIONS",
    "DangerPattern", "DANGER_PATTERNS", "_without_tagged_sql", "_security_check_level", "_enabled_coding_sets",
    "_is_scannable_path", "_active_patterns", "_match_line", "_scan_diff_text", "_scan_new_file", "_scan_commit",
    "_hints_file", "_load_noted", "_baseline_file", "_load_baseline", "_note_findings", "_format_finding", "_build_message",
    "check_danger_scan",
]

_ALLOW_MARK = "act:allow-danger"
_HINTS_DIRNAME = "danger-scan-hints"
_BASELINE_NAME = "baseline.json"
_MAX_BASELINE_BYTES = 4_000_000
_REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT: a Windows junction or symlink in st_file_attributes
_MAX_FINDINGS = 5
_SECURITY_CHECK_LEVELS = ("off", "local", "deps", "full")
# Prose, not code — a doc explaining `shell=True` or `eval()` is not a call to either, and holding
# it up on the same footing as source would only train everyone to reach for act:allow-danger
# without reading it. Extensions only (no content sniffing), same cheap-and-simple stance the
# module docstring already takes for not checking a file's language.
_DOC_EXTENSIONS = (".md", ".txt", ".rst")


def _is_scannable_path(rel: str) -> bool:
    """False for a doc file (see _DOC_EXTENSIONS) and for anything under `.act/` — the template's
    own files ship patterns like `shell=True` and `eval()` in comments and docstrings (this very
    module is a case in point), so scanning them would hold up the commit that *brings in* an
    `.act/` update for every Python project, regardless of what the project itself wrote."""
    posix_rel = rel.replace("\\", "/").lstrip("/")
    if posix_rel.startswith(".act/"):
        return False
    return Path(posix_rel).suffix.lower() not in _DOC_EXTENSIONS


class DangerPattern(NamedTuple):
    id: str
    label: str
    regex: "re.Pattern[str]"
    safe_regex: Optional["re.Pattern[str]"] = None  # a match on the same line exempts the hit
    prepare: Optional[Callable[[str], str]] = None  # the line as this pattern sees it
    extensions: Optional[tuple[str, ...]] = None  # only files with one of these suffixes (None: any file)


# SQL needs its structure, not just a keyword: "Update-Snapshot", a URL path ".../update-now" or the log
# text "Update {x} done" are not statements. A keyword counts only at a word start that is not glued to
# `-`, `/` or `.` (a leading optimizer hint comment is fine), and only together with its counterpart word:
# SELECT ... FROM, INSERT INTO / INSERT ... VALUES, UPDATE ... SET, DELETE [t] FROM. The text between the
# two words may hold an alias, a `{placeholder}` or, for concatenation, a closing quote, `+` and a variable
# (verbose mode: no literal spaces below).
_SQL_START = r"(?:(?<![\w/.\-])|(?<=\*/))"


# INSERT INTO and DELETE [t] FROM: no text between the two words that could hold a concatenation
_SQL_PAIR = r"(?:insert\s+into\b | delete\s+(?:[\w.`{}]+\s+)?from\b)"


def _sql_struct(mid: str, spanning: bool = False) -> str:
    # spanning: `mid` holds the concatenation itself, so _SQL_PAIR is left out; otherwise every
    # plain "DELETE FROM t" would count as concatenated
    pair = "" if spanning else r" | " + _SQL_PAIR
    return (
        r"(?:select\b" + mid + r"\bfrom\b | insert\b" + mid + r"\bvalues\b"
        r" | update\b" + mid + r"\bset\b" + pair + r")"
    )


_SQL_STRUCT = _sql_struct(r"[^\n;]{0,200}?")
# keyword and counterpart word in different literals of one concatenation
_SQL_SPAN = _sql_struct(r"""[^\n;]{0,200}?["']\s*\+[^\n;]{0,200}?""", spanning=True)
# _SQL_PAIR with a quote-and-`+` (or `+=`) anywhere on the line - no window and `;` allowed, the reach
# these two had while every one of them counted as concatenated
_SQL_PAIR_ON_LINE = r"""^(?=.*?(?:["']\s*\+|\+=?\s*["'])).*?""" + _SQL_START + _SQL_PAIR

# A tagged template literal of a query builder binds every `${...}` as a parameter - the safe form, not a
# string built from values: sql`...` (Kysely, Drizzle, postgres.js), <name>.sql`...`, Prisma.sql`...`,
# $queryRaw`...` and $executeRaw`...` (Prisma), also with a type argument (sql<number>`...`). The SQL
# patterns see the line with such literals blanked out; one not closed on its line runs to the line end
# (the first line of a multi-line literal). No space between tag and backtick, the way formatters write
# it; the type argument is capped at 200 characters, so a long line full of `sql<` stays linear. A raw
# helper anywhere on the line (sql.raw, sql.lit/sql.literal, sql.unsafe, Prisma.raw, $queryRawUnsafe, a
# bare raw(...) as in sql-template-tag, sql.__dangerous__rawValue) puts text into the statement unbound,
# so then nothing is blanked - stricter than "inside the literal", which a line regex cannot tell apart
# reliably once literals nest.
_SQL_TAGGED_TEMPLATE = re.compile(
    r"""(?<![\w$])(?:sql|\$queryRaw|\$executeRaw)(?:<[\w\s,.|&\[\]{}:;?'"<>]{0,200}?>)?`[^`\n]*`?"""
)
_SQL_RAW_HELPER = re.compile(
    r"\.(?:raw|lit|literal|unsafe)\b|RawUnsafe\b|(?<![\w$.])raw\s*\(|__dangerous__rawValue\b"
)


def _without_tagged_sql(line: str) -> str:
    if _SQL_RAW_HELPER.search(line):
        return line
    return _SQL_TAGGED_TEMPLATE.sub(" ", line)


# A LIKE operand (`LIKE '%foo%'`) holds a `%` right after a quote, which the `%`-formatting pattern would read
# as the operator of `"..." % value`; the operand is blanked for that pattern.
_SQL_LIKE_OPERAND = re.compile(r"""(?i)\b(?:i?like|similar\s+to)\s+(?:'[^'\n]*'|"[^"\n]*")""")


def _without_like_operands(line: str) -> str:
    return _SQL_LIKE_OPERAND.sub(" ", _without_tagged_sql(line))


# PHP files: the versioned endings (`.php5`, `.php7`, ...) and `.pht` are PHP for the web servers that map
# them, so they count like `.php`.
_PHP_EXTENSIONS = (
    ".php", ".php3", ".php4", ".php5", ".php7", ".php8", ".pht", ".phtml", ".inc", ".module",
)

# A line that only reports or logs (raise, print, a logger call; echo, error_log, throw new ...) and holds
# nothing but string literals and plain operands is text, not a statement sent to a database: "Cannot select
# a row from %s" is prose even though it holds `select ... from`. This is an allow-list for exactly that
# shape: the whole line must be one such call with literals and simple operands (no call, no `;` and no
# second statement), and no literal may open like a statement (`"SELECT ...`, `" select ...`, `"(SELECT ...`).
# Anything else is checked as before. A call spread over several lines is not recognised (each line is
# checked on its own, as before).
_SQL_OPENING_LITERAL = re.compile(
    r"""(?isx) ^ (?:[\s(]|\\[ntr])* (?:/\*.*?\*/ (?:[\s(]|\\[ntr])*)* (?:select|insert|update|delete|with)\b"""
)
_PY_OPERAND = r"""[\w.\[\]'"+\- ]+"""
_PY_ARGS = r"""[\w.\[\]'"+\-=, ]*"""
_PY_PROSE_CALL = re.compile(
    r"""(?x) ^\s*
    (?: raise\s+[\w.]+
      | print
      | (?:[\w.]*\.)?(?:logger|logging|log|_log|_logger|LOG|LOGGER)\.
        (?:debug|info|warning|warn|error|exception|critical|fatal|log)
      | warnings\.warn )
    \s*\(\s*
    [rRuU]?(?P<q>["']) (?:(?!(?P=q))[^\\\n]|\\.)* (?P=q)
    (?: \s*% \s*(?: """ + _PY_OPERAND + r""" | \( """ + _PY_ARGS + r""" \) )
      | \.format\( """ + _PY_ARGS + r""" \) )?
    """ + _PY_ARGS + r""" \) (?:\s+from\s+[\w.]+)? \s*$"""
)
_PHP_PROSE_CALL = re.compile(
    r"""(?x) ^\s*
    (?: echo\b | print\b | die\b | exit\b
      | (?:error_log|trigger_error|user_error)\s*\(
      | \$[\w>-]*(?:logger|log)->(?:debug|info|notice|warning|error|critical|alert|emergency|log)\s*\(
      | throw\s+new\s+[\\\w]+\s*\( )
    \s*\(?
    (?: \s*(?: "(?:[^"\\\n]|\\.)*" | '(?:[^'\\\n]|\\.)*' | \$[\w\[\]>'"-]{1,60} | \. | , | \d+ ) )+
    \s*\)*\s*;?\s*$"""
)
_LITERAL_RE = re.compile(r"""(?s)"((?:[^"\\\n]|\\.)*)"|'((?:[^'\\\n]|\\.)*)'""")


def _is_prose_line(line: str, call: "re.Pattern[str]") -> bool:
    if len(line) > 1000 or "{$" in line or "${" in line or not call.match(line):
        return False
    for match in _LITERAL_RE.finditer(line):
        body = match.group(1) if match.group(1) is not None else match.group(2)
        if _SQL_OPENING_LITERAL.match(body):
            return False
    return True


def _format_line(line: str) -> str:
    """The line as sql-format sees it: blank for a plain log/raise/print line (see _PY_PROSE_CALL)."""
    return " " if _is_prose_line(line, _PY_PROSE_CALL) else _without_like_operands(line)


def _php_concat_line(line: str) -> str:
    """The line as sql-php-concat sees it: blank for a plain echo/log/throw line (see _PHP_PROSE_CALL)."""
    return " " if _is_prose_line(line, _PHP_PROSE_CALL) else line

# PHP: a quote, the concatenation dot and a `$variable` (`"SELECT ... WHERE id = " . $id`), the variable
# first (`$cols . " FROM t"`), or the statement's two words in different literals of one dotted chain.
_SQL_PHP_CONCAT = (
    r"(?ix)" + _SQL_START + _SQL_STRUCT + r"""[^\n;]{0,200} ["']\s*\.\s*\$"""
    r"""| \$[\w\[\]>'"-]{1,60}\s*\.\s*["'] [^\n;]{0,200}""" + _SQL_START + _SQL_STRUCT
    + r"""| """ + _SQL_START + _sql_struct(r"""[^\n;]{0,200}?["']\s*\.[^\n;]{0,200}?""", spanning=True)
)
# PHP: a `$variable`, `${name}` or `{$expr}` inside a double-quoted string that holds the statement (single quotes do
# not interpolate in PHP, a `\$` is a literal dollar sign, `$1` is a positional parameter, not a variable).
_SQL_PHP_INTERPOLATION = (
    r"""(?ix) (?<![\w\\])"(?=[^"\n]{0,400}(?<!\\)(?:\$[A-Za-z_]|\$\{[A-Za-z_]|\{\$))[^"\n]{0,200}?"""
    + _SQL_START + _sql_struct(r"""[^"\n;]{0,200}?""")
)
# Python (and Ruby) formatting after the literal: `"... id = %s" % value`, `"... id = {}".format(value)`.
# The literal and the operator sit within 200 characters of the statement, no `;` in between. A `%` that
# opens a short literal of its own (`strftime('%Y', d)`, `DATE_FORMAT(d, '%Y-%m')`) is a date format, not
# the operator: no quote may close the run of non-blank characters right after it.
_SQL_FORMAT = (
    r"""(?ix)""" + _SQL_START + _SQL_STRUCT
    + r"""[^\n;]{0,200} ["']\s*(?:%(?![^'"\s]*['"])\s*[\w(\[{]|\.format\s*\()"""
)


# Grouped by the coding rule set (docs/project/coding_rules.md path) they belong to - see the
# module docstring. Only the sets the concept names an example for (Python, PHP, JS/Vue, SQL) get
# patterns; a set with none listed here (bash, csharp, go, java, tailwind) is simply never
# scanned, not a gap this module silently pretends to cover.
#   - a bare function-name pattern (eval, exec, system, ...) is written with a leading
#     `(?<![\w.])` rather than plain `\b`, so a *method* call of the same name on some unrelated
#     object (`model.eval()` in PyTorch, `session.exec(select(...))` in SQLModel, JS `re.exec(s)`,
#     `$obj->system(...)` in PHP) is not mistaken for the dangerous top-level builtin — `\b` alone
#     matches right after a `.`, which is exactly the boundary a method call sits on (2026-09-26,
#     review).
DANGER_PATTERNS: dict[str, tuple[DangerPattern, ...]] = {
    ".act/coding/python.md": (
        DangerPattern("python-eval-exec", "eval()/exec()", re.compile(r"(?<![\w.])(?:eval|exec)\s*\(")),
        DangerPattern("python-shell-true", "subprocess call with shell=True", re.compile(r"\bshell\s*=\s*True\b")),
        DangerPattern("python-pickle-loads", "pickle.load()/loads()", re.compile(r"\bpickle\.loads?\s*\(")),
        DangerPattern(
            "python-yaml-load", "yaml.load() without a SafeLoader",
            re.compile(r"\byaml\.load\s*\("), re.compile(r"SafeLoader"),
        ),
        DangerPattern("python-os-system", "os.system()", re.compile(r"\bos\.system\s*\(")),
    ),
    ".act/coding/php.md": (
        DangerPattern("php-eval", "eval()", re.compile(r"(?<![\w.])eval\s*\(")),
        DangerPattern("php-shell-exec", "shell_exec()", re.compile(r"(?<![\w.])shell_exec\s*\(")),
        DangerPattern("php-system", "system()", re.compile(r"(?<![\w.])system\s*\(")),
        DangerPattern("php-passthru", "passthru()", re.compile(r"(?<![\w.])passthru\s*\(")),
        DangerPattern("php-unserialize", "unserialize()", re.compile(r"(?<![\w.])unserialize\s*\(")),
    ),
    ".act/coding/vue.md": (
        DangerPattern("vue-v-html", "v-html binding", re.compile(r"\bv-html\s*=")),
        DangerPattern("vue-inner-html", "innerHTML assignment", re.compile(r"\.innerHTML\s*=")),
        DangerPattern("vue-new-function", "new Function()", re.compile(r"\bnew\s+Function\s*\(")),
    ),
    ".act/coding/typescript.md": (
        DangerPattern("ts-eval", "eval()", re.compile(r"(?<![\w.])eval\s*\(")),
        DangerPattern("ts-new-function", "new Function()", re.compile(r"\bnew\s+Function\s*\(")),
        DangerPattern("ts-inner-html", "innerHTML assignment", re.compile(r"\.innerHTML\s*=")),
        DangerPattern(
            "ts-dangerously-set-innerhtml", "dangerouslySetInnerHTML",
            re.compile(r"\bdangerouslySetInnerHTML\b"),
        ),
    ),
    ".act/coding/sql.md": (
        DangerPattern(
            "sql-concat", "SQL statement built by string concatenation",
            re.compile(
                r"(?ix)" + _SQL_START + _SQL_STRUCT + r"""[^\n;]{0,200} ["']\s*\+
                  | """ + _SQL_START + _SQL_SPAN + r"""
                  | \+\s*["'] [^\n;]{0,200}""" + _SQL_START + _SQL_STRUCT + r"""
                  | """ + _SQL_PAIR_ON_LINE,
            ),
            prepare=_without_tagged_sql,
        ),
        DangerPattern(
            "sql-fstring", "SQL statement built from an f-string/template literal",
            re.compile(
                r"""(?ix) (?<!\w)[rb]?f[rb]?["'] [^\n"']{0,200}""" + _SQL_START + _SQL_STRUCT
                + r"""| `[^`\n]{0,200} \$\{[^}]*\} [^`\n]{0,200}""" + _SQL_START + _SQL_STRUCT
                + r"""| `[^`\n]{0,200}""" + _SQL_START + _SQL_STRUCT + r"""[^`\n]{0,200} \$\{""",
            ),
            prepare=_without_tagged_sql,
        ),
        DangerPattern(
            "sql-php-concat", "SQL statement built by PHP string concatenation",
            re.compile(_SQL_PHP_CONCAT), prepare=_php_concat_line, extensions=_PHP_EXTENSIONS,
        ),
        DangerPattern(
            "sql-php-interpolation", "SQL statement with a PHP variable interpolated into the string",
            re.compile(_SQL_PHP_INTERPOLATION), extensions=_PHP_EXTENSIONS,
        ),
        DangerPattern(
            "sql-format", "SQL statement built with % or .format()",
            re.compile(_SQL_FORMAT), prepare=_format_line,
        ),
    ),
}
# Nuxt templates are Vue templates - reuse the Vue group rather than a near-duplicate list.
DANGER_PATTERNS[".act/coding/nuxt.md"] = DANGER_PATTERNS[".act/coding/vue.md"]


def _security_check_level(config: dict[str, str]) -> str:
    """`security-check` from docs/ai/config.md, normalized to one of _SECURITY_CHECK_LEVELS -
    falls back to "local" (the concept's own default) for a missing or unrecognized
    value, same fail-toward-the-default stance _check_mode takes for the block/warn/off checks."""
    value = config.get("security-check", "").strip().lower()
    return value if value in _SECURITY_CHECK_LEVELS else "local"


def _enabled_coding_sets(root: Path) -> set[str]:
    """The coding-rule-set paths (e.g. ".act/coding/python.md") the project has actually checked
    on in docs/project/coding_rules.md, read with .act/scripts/rules.py's own parser - never a
    second parser here (R-work-override). Empty (nothing scanned, never a reason to block) if the
    file is missing or rules.py cannot be imported/parsed - see the module docstring's "Known
    limits"."""
    try:
        import rules  # deferred: a broken rules.py must never lock out every commit
    except Exception:
        return set()
    path = root / "docs" / "project" / "coding_rules.md"
    if not path.is_file():
        return set()
    try:
        project_file = rules.parse_project_file(path, rules.AREAS["coding"])
    except Exception:
        return set()
    return {project_set.path for project_set in project_file.sets if project_set.enabled}


def _active_patterns(enabled_sets: set[str]) -> tuple[DangerPattern, ...]:
    active: list[DangerPattern] = []
    for set_path, patterns in DANGER_PATTERNS.items():
        if set_path in enabled_sets:
            active.extend(patterns)
    return tuple(active)


def _match_line(
    line: str, patterns: tuple[DangerPattern, ...], path: Optional[str] = None,
) -> Optional[DangerPattern]:
    """The first pattern in `patterns` that hits `line`, or None. The caller is responsible for the
    `act:allow-danger` exemption, checked once per line before this is even called (same split of
    responsibility as secret_scan._match_secret)."""
    suffix = Path(path.replace("\\", "/")).suffix.lower() if path else None
    for pattern in patterns:
        if pattern.extensions is not None and suffix not in pattern.extensions:
            continue
        text = pattern.prepare(line) if pattern.prepare else line
        if pattern.regex.search(text) and not (pattern.safe_regex and pattern.safe_regex.search(text)):
            return pattern
    return None


def _unbooked(file: str, patterns: tuple[DangerPattern, ...], booked: frozenset) -> tuple[DangerPattern, ...]:
    """`patterns` without those whose `file|rule-id` key is booked. Filtered before matching, because
    `_match_line` returns only the first hit: a booked pattern must not hide a later, unbooked one."""
    if not booked:
        return patterns
    return tuple(p for p in patterns if f"{file}|{p.id}" not in booked)


def _scan_diff_text(
    diff_text: str, patterns: tuple[DangerPattern, ...], findings: list[dict], booked: frozenset = frozenset(),
) -> None:
    for section in _diff_sections(diff_text):
        if len(findings) >= _MAX_FINDINGS:
            return
        if len(section.encode("utf-8", "replace")) > _MAX_DIFF_BYTES:
            continue  # an oversized section only weakens this scan, same as secret_scan - never
            # a reason to block on what could not be read
        for file, _is_new, lines in _diff_entries(section):
            if len(findings) >= _MAX_FINDINGS:
                return
            if not _is_scannable_path(file):
                continue
            file_patterns = _unbooked(file, patterns, booked)
            if not file_patterns:
                continue
            for line_no, content in lines:
                if len(findings) >= _MAX_FINDINGS:
                    return
                if _ALLOW_MARK in content:
                    continue
                hit = _match_line(content, file_patterns, file)  # booked rules are not in the list: no count
                if hit is not None:
                    findings.append({"file": file, "line": line_no, "pattern": hit})


def _scan_new_file(
    path: Path, rel: str, patterns: tuple[DangerPattern, ...], findings: list[dict],
    booked: frozenset = frozenset(), limit: Optional[int] = _MAX_FINDINGS,
) -> None:
    """`limit` None: no cap (the baseline run must see every finding it books)."""
    if not _is_scannable_path(rel):
        return
    try:
        if path.stat().st_size > _MAX_DIFF_BYTES:
            return
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    patterns = _unbooked(rel, patterns, booked)
    if not patterns:
        return
    for line_no, content in enumerate(_text_lines(text), start=1):
        if limit is not None and len(findings) >= limit:
            return
        if _ALLOW_MARK in content:
            continue
        hit = _match_line(content, patterns, rel)
        if hit is not None:
            findings.append({"file": rel, "line": line_no, "pattern": hit})


def _scan_commit(
    invocation: dict, patterns: tuple[DangerPattern, ...], deadline: float, booked: frozenset = frozenset(),
) -> list[dict]:
    """Findings for one commit-like invocation (see secret_scan._git_commit_invocations for its
    shape) - mirrors secret_scan._scan_commit's own staged/unstaged/add-paths walk, against the
    danger patterns instead of secret patterns. An incomplete scan (timeout, oversized section) is
    never grounds to block on its own here either - it only means fewer findings, same stance
    secret_scan.py takes."""
    findings: list[dict] = []
    cwd = invocation["cwd"]
    if not Path(cwd).is_dir():
        return findings

    def budget() -> float:
        return min(_GIT_TIMEOUT, deadline - time.monotonic())

    # every git call runs from the repository's top level, same as secret_scan._scan_commit: with
    # `diff.relative=true` a diff from a subdirectory silently drops everything outside it
    # (2026-09-27 review 3, m3); the pathspecs handed in are absolute or top-anchored
    toplevel = _repo_toplevel(cwd, budget())
    git_cwd = toplevel or cwd
    staged = _run_git(
        ["diff", "--cached", "--no-color", "--no-ext-diff", "--no-textconv", "-U0"], git_cwd, budget(),
    )
    if staged is not None:
        _scan_diff_text(staged, patterns, findings, booked)

    if invocation["all"] and len(findings) < _MAX_FINDINGS:
        unstaged = _run_git(
            ["diff", "--no-color", "--no-ext-diff", "--no-textconv", "-U0"], git_cwd, budget(),
        )
        if unstaged is not None:
            _scan_diff_text(unstaged, patterns, findings, booked)

    for entry in invocation["add_paths"]:
        if len(findings) >= _MAX_FINDINGS or deadline - time.monotonic() <= 0:
            break
        raw_path = entry["path"]
        if raw_path != _WHOLE_TREE_PATHSPEC:
            # the whole-tree entry's own unstaged diff is the `all` pass above (always set with it)
            path_diff = _run_git(
                ["diff", "--no-color", "--no-ext-diff", "--no-textconv", "-U0", "--", raw_path],
                git_cwd, budget(),
            )
            if path_diff is not None:
                _scan_diff_text(path_diff, patterns, findings, booked)
        if len(findings) >= _MAX_FINDINGS or deadline - time.monotonic() <= 0:
            break
        if toplevel is None:
            break  # nowhere to join root-relative names onto
        # --full-name + the top level, same as secret_scan._scan_commit (2026-09-27 review 2, C2):
        # root-relative names from a subdirectory too -- which is also what keeps
        # _is_scannable_path's `.act/` and doc-file exemptions meaningful there
        ls_args = ["ls-files", "--others", "--full-name", "-z", "--", raw_path]
        if not entry["forced"]:
            ls_args.insert(2, "--exclude-standard")
        untracked = _run_git(ls_args, toplevel, budget())
        if untracked is None:
            continue
        for rel in filter(None, untracked.split("\0")):
            if len(findings) >= _MAX_FINDINGS:
                break
            _scan_new_file(Path(toplevel) / rel, rel, patterns, findings, booked)
    return findings


def _hints_file(root: Path, reader_key: str) -> Path:
    return root / ".act-local" / _HINTS_DIRNAME / f"{reader_key}.json"


def _load_noted(path: Path) -> set:
    if not path.is_file():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return set(data) if isinstance(data, list) else set()


def _baseline_file(root: Path) -> Path:
    return root / ".act-local" / _HINTS_DIRNAME / _BASELINE_NAME


def _is_plain(path: Path, want_file: bool) -> bool:
    """True for a real directory (or, with want_file, a real file) that is not a symlink or junction."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & _REPARSE_POINT:
        return False
    return stat.S_ISREG(info.st_mode) if want_file else stat.S_ISDIR(info.st_mode)


def _load_baseline(root: Path) -> frozenset:
    """The `file|rule-id` keys the adoption baseline check booked (see scripts/adopt_baseline.py), read
    from .act-local/danger-scan-hints/baseline.json: an allow-list of exact keys, one list for the whole
    project, never merged into the per-reader hints and never written from here. A missing, oversized,
    unreadable or malformed file, a list holding anything but strings (one non-string item empties the
    whole list), and a file or folder on the way to
    it that is a symlink or junction all count as empty (nothing is let through)."""
    path = _baseline_file(root)
    for folder in (root / ".act-local", path.parent):
        if not _is_plain(folder, want_file=False):
            return frozenset()
    if not _is_plain(path, want_file=True):
        return frozenset()
    try:
        if path.stat().st_size > _MAX_BASELINE_BYTES:
            return frozenset()
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    if not isinstance(data, list):
        return frozenset()
    if not all(isinstance(item, str) for item in data):
        return frozenset()
    return frozenset(data)


def _note_findings(path: Path, noted: set, keys: "list[str]") -> None:
    """Best-effort, same reasoning as encoding_hint._note_path: a failed write here only means the
    same finding can be reported again later, never a reason to fail the tool call."""
    noted.update(keys)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sorted(noted), ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def _format_finding(finding: dict) -> str:
    pattern: DangerPattern = finding["pattern"]
    return f"{finding['file']}:{finding['line']} ({pattern.label})"


def _build_message(findings: list[dict]) -> str:
    shown = findings[:_MAX_FINDINGS]
    rest = len(findings) - len(shown)
    more = f" (+{rest} more)" if rest > 0 else ""
    return (
        "[act] commit held: dangerous pattern in " + "; ".join(_format_finding(f) for f in shown)
        + more + " — fix it, or mark the line act:allow-danger if it is intended; repeating the "
        "commit unchanged lets it through (security-check, local)"
    )


def check_danger_scan(payload: dict) -> int:
    """A `git commit`-like call in a Bash/PowerShell call is held once per (reader, file, pattern)
    while an added line matches a dangerous pattern from a coding rule set the project has
    switched on - see the module docstring for the full contract. Applies to the orchestrator and
    every worker alike (no _is_worker gate, same as secret_scan.py: a dangerous pattern is no less
    dangerous coming from a worker). A finding whose exact `file|rule-id` key is listed in
    .act-local/danger-scan-hints/baseline.json (booked by the adoption baseline check) is not held."""
    config = actlib.read_config()
    level = _security_check_level(config)
    if level == "off":
        return 0

    shell = _shell_command(payload)
    if shell is None:
        return 0
    _tool_name, command = shell
    if "git" not in command:
        return 0  # cheapest possible reject, same reasoning as secret_scan.py

    try:
        root = actlib.repo_root()
    except RuntimeError:
        return 0

    enabled_sets = _enabled_coding_sets(root)
    patterns = _active_patterns(enabled_sets)
    if not patterns:
        return 0

    cwd_raw = payload.get("cwd")
    base_cwd = cwd_raw if isinstance(cwd_raw, str) and cwd_raw else str(root)
    deadline = _check_deadline(payload, _TIME_BUDGET)
    invocations = _git_commit_invocations(command, base_cwd, deadline, {})
    if not invocations:
        return 0

    # booked keys are dropped while collecting, so they never count toward the cap and cannot hide a new hit
    booked = _load_baseline(root)
    all_findings: list[dict] = []
    for invocation in invocations:
        if time.monotonic() >= deadline:
            break
        all_findings.extend(_scan_commit(invocation, patterns, deadline, booked))
        if len(all_findings) >= _MAX_FINDINGS:
            break
    if not all_findings:
        return 0

    # a finding the adoption baseline booked (exact `file|rule-id` key) was dropped above; a new occurrence
    # of the same rule in the same file passes too, like the per-reader repeat

    reader_key = _reader_key(payload)
    if reader_key is None:
        # cannot deduplicate per reader (no dedup key -> no way for a legitimate repeat to ever
        # be recognized as "already noted") - report once, on stderr, but let this attempt through
        # rather than block forever on a call this check cannot ever remember having warned about
        print(_build_message(all_findings), file=sys.stderr)
        return 0

    hints_path = _hints_file(root, reader_key)
    noted = _load_noted(hints_path)
    new_findings = []
    new_keys = []
    for finding in all_findings:
        key = f"{finding['file']}|{finding['pattern'].id}"
        if key in noted:
            continue
        new_findings.append(finding)
        new_keys.append(key)

    if not new_findings:
        return 0  # every hit here was already noted once for this reader - the repeat goes through

    _note_findings(hints_path, noted, new_keys)
    print(_build_message(new_findings), file=sys.stderr)
    return 2
