#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Security check "Art C": a deep, cross-language scan with Semgrep over the files
#          changed since a ref (default: the latest tag) or the whole tree (`--all`). Runs only on
#          request and before a release (`security-check: full`, invoked from the `act-release`
#          skill) - never on every commit, unlike Art A (checks/danger_scan.py). Art B (library-
#          vulnerability lookup, `security_scan.py`/`deps_scan.py`) is a separate, foreign build in
#          progress and is neither imported nor touched here.
#
#          Semgrep config chosen: `p/default` (the registry's broad, language-agnostic default
#          ruleset - "open rule set" per the concept, no project-specific tuning shipped by the
#          template itself, same stance the concept takes for Art B: no home-grown vulnerability
#          lists to maintain). NOT `--config auto`: `auto` picks rules based on the project and
#          *requires* Semgrep's metrics endpoint to do so (`--metrics=off` together with `auto`
#          either fails outright or silently falls back to a much smaller rule set, depending on
#          the installed Semgrep version) - `p/default` runs the same way with `--metrics=off`
#          regardless of version, so metrics are actually off, not just requested.
#
#          Only *changed* files are targeted by default (git diff --diff-filter=ACMR against the
#          ref, plus untracked files) - scanning the whole tree on every call would make this check
#          too slow to run "on request", the same reasoning the concept gives for Art A only
#          looking at added lines. `--all` opts into a whole-tree scan (e.g. for the first run on a
#          project, or a periodic full audit).
#
# Usage:
#   python .act/scripts/security_deep.py [--since <ref> | --all] [--json] [--force]
#       Runs Semgrep over the targeted files and prints the findings. Without `--since`/`--all`,
#       the ref is the latest tag (`git describe --tags --abbrev=0`); with no tag in the repo, this
#       falls back to `--all` (nothing to compare against yet).
#       `--json`: prints the parsed findings as a JSON array (one object per finding: `rule_id`,
#       `path`, `line`, `severity`, `message`) instead of the human-readable listing.
#       `--force`: run even when `security-check` (docs/ai/config.md) is not `full` - see below.
#
# `security-check` gate: with a level other than `full` (off/local/deps), this prints one line
# saying so and exits 0 without invoking Semgrep at all, unless `--force` is given - Art C is
# "on request and before a release", never implied by a lower level (concept, "Steuerung" table).
#
# Exit codes:
#   0 - security-check is not `full` and --force was not given (skipped); or Semgrep ran and found
#       nothing to report for the targeted files (including: no files were targeted at all).
#   1 - Semgrep ran and reported at least one finding (see the printed output for severities - the
#       caller, e.g. act-release, decides what a given severity means for the release).
#   3 - `semgrep` is not installed (or not on PATH) - printed as one line with the install command,
#       no traceback; distinct from exit 1 so a caller never mistakes "tool missing" for "clean".
#   4 - Semgrep could not be run to completion: a timeout, output that was not the JSON this
#       script expects, an invalid `--since` ref, a Semgrep exit code >= 2, or an error-level entry
#       in Semgrep's own `errors` array (rules not downloadable, bad config, ...) - a real failure,
#       distinct from both "clean" and "findings"; a fatal run with an empty `results` array must
#       never be read as "no findings".
#
# Testability: `ACT_SEMGREP_CMD`, if set, is split with `shlex.split()` and used as the base
# command instead of resolving `semgrep` via `shutil.which()` - lets a test point this script at a
# canned stand-in (e.g. "python /path/to/fake_semgrep.py") without touching PATH or installing
# anything, and without the platform quirks of putting a `.cmd`/shell-script shim on PATH on
# Windows vs. POSIX. Never set in normal use.

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple, Optional

import actlib

_SEMGREP_CMD_ENV = "ACT_SEMGREP_CMD"
_SEMGREP_CONFIG = "p/default"
_GIT_TIMEOUT = 10.0
_SEMGREP_TIMEOUT = 300.0
# Windows' CreateProcess command-line limit is ~32768 chars; stay well under it (the base command
# and per-target quoting/escaping add overhead this budget does not account for exactly).
_TARGETS_CHUNK_CHARS = 8000
_INSTALL_HINT = (
    "[act] semgrep not found - install with `pipx install semgrep` (or `pip install --user "
    "semgrep`); Docker alternative: `docker run --rm -v <project>:/src returntocorp/semgrep "
    "semgrep --config p/default /src`"
)

EXIT_CLEAN = 0
EXIT_FINDINGS = 1
EXIT_MISSING_TOOL = 3
EXIT_RUN_FAILED = 4


class Finding(NamedTuple):
    rule_id: str
    path: str
    line: int
    severity: str
    message: str


def _security_check_level(config: dict[str, str]) -> str:
    """Same normalization as checks/danger_scan.py._security_check_level (not imported from
    there - that module lives under .act/hooks/checks/, a separate package this standalone script
    has no reason to depend on): falls back to "local" for a missing/unrecognized value."""
    value = config.get("security-check", "").strip().lower()
    return value if value in ("off", "local", "deps", "full") else "local"


def _run_git(args: list[str], cwd: Path) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=_GIT_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _latest_tag(root: Path) -> Optional[str]:
    output = _run_git(["describe", "--tags", "--abbrev=0"], root)
    if output is None:
        return None
    tag = output.strip()
    return tag or None


def _resolve_ref(root: Path, ref: str) -> Optional[str]:
    """Resolves `ref` (as given on the command line via `--since`) to a commit hash before it is
    ever passed to another git command as a diff endpoint. `ref` is untrusted input and could look
    like an option itself (e.g. "--output=x") - `--end-of-options` keeps `git rev-parse` from
    reading it as one, and this doubles as validation that `ref` actually names a commit; `None`
    means it does not."""
    output = _run_git(["rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"], root)
    if output is None:
        return None
    resolved = output.strip()
    return resolved or None


def _changed_files(root: Path, ref: str) -> list[str]:
    """Files changed since `ref` (tracked, added/copied/modified/renamed - a deleted file cannot
    be scanned) plus untracked files not covered by .gitignore, relative to `root`."""
    files: set[str] = set()
    diff_output = _run_git(["diff", "--name-only", "--diff-filter=ACMR", ref], root)
    if diff_output:
        files.update(line.strip() for line in diff_output.splitlines() if line.strip())
    untracked_output = _run_git(["ls-files", "--others", "--exclude-standard"], root)
    if untracked_output:
        files.update(line.strip() for line in untracked_output.splitlines() if line.strip())
    return sorted(rel for rel in files if (root / rel).is_file())


def _strip_quotes(token: str) -> str:
    """shlex.split(..., posix=False) keeps a token's surrounding quote characters instead of
    consuming them (needed so a quoted Windows path with a space stays one token) - strip them
    back off per part so a caller quoting one path (`"C:\\Program Files\\semgrep\\semgrep.exe"
    --foo`) gets a usable path, not one wrapped in literal quote characters."""
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ('"', "'"):
        return token[1:-1]
    return token


def _resolve_semgrep_cmd() -> Optional[list[str]]:
    import os

    override = os.environ.get(_SEMGREP_CMD_ENV, "").strip()
    if override:
        # posix=False on every platform: posix-mode shlex.split() treats a backslash as an escape
        # character, which mangles a plain Windows path (e.g. "C:\Users\...\python.exe") - the
        # override is only ever a simple space-separated command, optionally with one part quoted
        # to keep a space inside it together.
        return [_strip_quotes(part) for part in shlex.split(override, posix=False)]
    found = shutil.which("semgrep")
    return [found] if found else None


def _parse_semgrep_json(raw: str) -> tuple[list[Finding], list[dict]]:
    data = json.loads(raw)
    findings: list[Finding] = []
    for entry in data.get("results", []):
        extra = entry.get("extra", {})
        start = entry.get("start", {})
        findings.append(
            Finding(
                rule_id=str(entry.get("check_id", "?")),
                path=str(entry.get("path", "?")),
                line=int(start.get("line", 0) or 0),
                severity=str(extra.get("severity", "?")),
                message=str(extra.get("message", "")).strip(),
            )
        )
    errors = data.get("errors", [])
    return findings, (errors if isinstance(errors, list) else [])


def _format_finding(finding: Finding) -> str:
    return f"{finding.path}:{finding.line} [{finding.severity}] {finding.rule_id}: {finding.message}"


def _chunk_targets(targets: list[str], limit: int = _TARGETS_CHUNK_CHARS) -> list[list[str]]:
    """Groups `targets` into chunks whose combined length (plus one separator per target) stays
    under `limit`, so a long file list cannot exceed the Windows command-line limit in a single
    Semgrep invocation. A single target longer than `limit` still gets its own, oversized chunk
    (there is no shorter way to name it) rather than being silently dropped."""
    chunks: list[list[str]] = []
    current: list[str] = []
    current_len = 0
    for target in targets:
        added_len = len(target) + 1
        if current and current_len + added_len > limit:
            chunks.append(current)
            current = []
            current_len = 0
        current.append(target)
        current_len += added_len
    if current:
        chunks.append(current)
    return chunks or [[]]


def _run_semgrep_once(
    base_cmd: list[str], targets: list[str], cwd: Path,
) -> tuple[Optional[list[Finding]], str]:
    """Runs one Semgrep invocation over `targets` (already within the command-line length budget).
    Returns (findings, error) - exactly one of the two is set; a non-empty `error` is a
    human-readable reason `security_deep.py` should exit EXIT_RUN_FAILED for."""
    command = [*base_cmd, "--config", _SEMGREP_CONFIG, "--metrics=off", "--json", *targets]
    try:
        result = subprocess.run(
            command, cwd=str(cwd), capture_output=True, text=True, timeout=_SEMGREP_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return None, f"semgrep timed out after {_SEMGREP_TIMEOUT:.0f}s"
    except OSError as exc:
        return None, f"could not run semgrep ({exc})"
    # Semgrep itself exits 1 when it reports findings - that alone is not a run failure. But a
    # fatal run (rules not downloadable, bad config, ...) can still print JSON with an empty
    # `results` array - that must never be read as "no findings", so both the exit code and the
    # `errors` array are checked, not just whether the output parsed as JSON at all.
    try:
        findings, errors = _parse_semgrep_json(result.stdout)
    except (json.JSONDecodeError, TypeError, ValueError):
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        return None, f"semgrep produced no usable JSON output ({detail[:200]})"
    fatal_error = next(
        (e for e in errors if isinstance(e, dict) and str(e.get("level", "")).lower() == "error"),
        None,
    )
    if result.returncode >= 2 or fatal_error is not None:
        detail = str(fatal_error.get("message", "")).strip() if fatal_error else ""
        if not detail:
            detail = result.stderr.strip() or f"semgrep exited {result.returncode}"
        return None, f"semgrep run failed ({detail[:200]})"
    return findings, ""


def run_semgrep(base_cmd: list[str], targets: list[str], cwd: Path) -> tuple[Optional[list[Finding]], str]:
    """Runs Semgrep against `targets` (paths relative to `cwd`, or `cwd` itself for a whole-tree
    scan), chunking a long target list across several invocations so no single command line
    exceeds `_TARGETS_CHUNK_CHARS`. Returns (findings, error) like `_run_semgrep_once` - the first
    chunk to fail stops the scan and reports that chunk's error."""
    all_findings: list[Finding] = []
    for chunk in _chunk_targets(targets):
        findings, error = _run_semgrep_once(base_cmd, chunk, cwd)
        if error:
            return None, error
        assert findings is not None  # error is empty, so _run_semgrep_once took the success path
        all_findings.extend(findings)
    return all_findings, ""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deep security scan (Art C) over the files changed since a ref, via Semgrep.",
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--since", metavar="REF", help="scan files changed since REF instead of the latest tag")
    scope.add_argument("--all", action="store_true", help="scan the whole tree instead of only changed files")
    parser.add_argument("--json", action="store_true", help="print findings as a JSON array instead of text")
    parser.add_argument(
        "--force", action="store_true",
        help="run even when docs/ai/config.md's security-check is not 'full'",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    # Findings can carry non-ASCII characters; a Windows console or a redirect otherwise uses a legacy
    # code page instead of UTF-8, which would corrupt or crash on them. Same fix as
    # .act/scripts/rules.py.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    args = build_parser().parse_args(argv)

    try:
        root = actlib.repo_root()
    except RuntimeError as exc:
        print(f"[act] security_deep: {exc}", file=sys.stderr)
        return EXIT_RUN_FAILED

    config = actlib.read_config(root)
    level = _security_check_level(config)
    if level != "full" and not args.force:
        print(
            f"[act] security_deep: security-check is '{level}', not 'full' - skipping "
            "(pass --force to run anyway)"
        )
        return EXIT_CLEAN

    if args.all:
        targets = ["."]
    else:
        if args.since:
            ref = _resolve_ref(root, args.since)
            if ref is None:
                print(
                    f"[act] security_deep: '{args.since}' is not a valid ref (git rev-parse "
                    "could not verify it)", file=sys.stderr,
                )
                return EXIT_RUN_FAILED
        else:
            ref = _latest_tag(root)
        if ref is None:
            print("[act] security_deep: no tag found - scanning the whole tree (like --all)")
            targets = ["."]
        else:
            changed = _changed_files(root, ref)
            if not changed:
                print(f"[act] security_deep: no changed files since '{ref}' - nothing to scan")
                return EXIT_CLEAN
            targets = changed

    base_cmd = _resolve_semgrep_cmd()
    if base_cmd is None:
        print(_INSTALL_HINT, file=sys.stderr)
        return EXIT_MISSING_TOOL

    findings, error = run_semgrep(base_cmd, targets, root)
    if error:
        print(f"[act] security_deep: {error}", file=sys.stderr)
        return EXIT_RUN_FAILED

    assert findings is not None  # error is empty, so run_semgrep took the success path
    if args.json:
        print(json.dumps([f._asdict() for f in findings], ensure_ascii=False, indent=2))
    elif not findings:
        print("[act] security_deep: no findings")
    else:
        for finding in findings:
            print(_format_finding(finding))

    return EXIT_FINDINGS if findings else EXIT_CLEAN


if __name__ == "__main__":
    sys.exit(main())
