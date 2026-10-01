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
#          pattern group on, not the file being edited.
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
#          `security-check` in docs/ai/config.md (four values, not the usual block/warn/off):
#          `off` runs nothing here at all; `local`/`deps`/`full` all run exactly this module (Art
#          A) — `deps`/`full` do not yet run B/C, so for now they behave like `local`, honestly
#          documented as "not built yet" in the config skeleton rather than silently accepted. An
#          unrecognized or missing value falls back to `local` (the concept's own default:
#          "Standard local").
#
# Known limits:
#   - the SQL-string-concatenation patterns are a rough heuristic (an SQL keyword near a quote-and-
#     `+` or an f-string/template-literal placeholder) - a real query builder's `.format()`/`%`-
#     style call is not covered, and a false positive on ordinary string handling near the word
#     "select" is possible; documented as an open point for the concept rather than tuned further
#     here (2026-09-25, review);
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
import re
import sys
import time
from pathlib import Path
from typing import NamedTuple, Optional

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
    _GIT_TIMEOUT,
    _MAX_DIFF_BYTES,
    _TIME_BUDGET,
    _WHOLE_TREE_PATHSPEC,
)

__all__ = [
    "_ALLOW_MARK", "_HINTS_DIRNAME", "_MAX_FINDINGS", "_SECURITY_CHECK_LEVELS", "_DOC_EXTENSIONS",
    "DangerPattern", "DANGER_PATTERNS", "_security_check_level", "_enabled_coding_sets",
    "_is_scannable_path", "_active_patterns", "_match_line", "_scan_diff_text", "_scan_new_file", "_scan_commit",
    "_hints_file", "_load_noted", "_note_findings", "_format_finding", "_build_message",
    "check_danger_scan",
]

_ALLOW_MARK = "act:allow-danger"
_HINTS_DIRNAME = "danger-scan-hints"
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
                r"""(?ix) \b(?:select|insert|update|delete)\b [^\n;]{0,200} ["']\s*\+
                  | \+\s*["'] [^\n;]{0,200} \b(?:select|insert|update|delete)\b""",
            ),
        ),
        DangerPattern(
            "sql-fstring", "SQL statement built from an f-string/template literal",
            re.compile(
                r"""(?ix) f["'] [^\n"']{0,200} \b(?:select|insert|update|delete)\b
                  | `[^`\n]{0,200} \$\{[^}]*\} [^`\n]{0,200} \b(?:select|insert|update|delete)\b""",
            ),
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


def _match_line(line: str, patterns: tuple[DangerPattern, ...]) -> Optional[DangerPattern]:
    """The first pattern in `patterns` that hits `line`, or None. The caller is responsible for the
    `act:allow-danger` exemption, checked once per line before this is even called (same split of
    responsibility as secret_scan._match_secret)."""
    for pattern in patterns:
        if pattern.regex.search(line) and not (pattern.safe_regex and pattern.safe_regex.search(line)):
            return pattern
    return None


def _scan_diff_text(
    diff_text: str, patterns: tuple[DangerPattern, ...], findings: list[dict],
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
            for line_no, content in lines:
                if len(findings) >= _MAX_FINDINGS:
                    return
                if _ALLOW_MARK in content:
                    continue
                hit = _match_line(content, patterns)
                if hit is not None:
                    findings.append({"file": file, "line": line_no, "pattern": hit})


def _scan_new_file(path: Path, rel: str, patterns: tuple[DangerPattern, ...], findings: list[dict]) -> None:
    if not _is_scannable_path(rel):
        return
    try:
        if path.stat().st_size > _MAX_DIFF_BYTES:
            return
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    for line_no, content in enumerate(text.splitlines(), start=1):
        if len(findings) >= _MAX_FINDINGS:
            return
        if _ALLOW_MARK in content:
            continue
        hit = _match_line(content, patterns)
        if hit is not None:
            findings.append({"file": rel, "line": line_no, "pattern": hit})


def _scan_commit(invocation: dict, patterns: tuple[DangerPattern, ...], deadline: float) -> list[dict]:
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
        _scan_diff_text(staged, patterns, findings)

    if invocation["all"] and len(findings) < _MAX_FINDINGS:
        unstaged = _run_git(
            ["diff", "--no-color", "--no-ext-diff", "--no-textconv", "-U0"], git_cwd, budget(),
        )
        if unstaged is not None:
            _scan_diff_text(unstaged, patterns, findings)

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
                _scan_diff_text(path_diff, patterns, findings)
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
            _scan_new_file(Path(toplevel) / rel, rel, patterns, findings)
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
    dangerous coming from a worker)."""
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

    all_findings: list[dict] = []
    for invocation in invocations:
        if time.monotonic() >= deadline:
            break
        all_findings.extend(_scan_commit(invocation, patterns, deadline))
        if len(all_findings) >= _MAX_FINDINGS:
            break
    if not all_findings:
        return 0

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
