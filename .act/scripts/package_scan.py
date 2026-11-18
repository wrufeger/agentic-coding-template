#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: The static scan of a package folder: what in it can act on the project beyond text. It only reads the
#          folder - it never imports, runs or evaluates anything from it - and lists one finding per line, each
#          starting with `RED `. `packages.py` shows these before it asks about a package that carries no valid
#          signature of the template author (`packages-unverified: scan`); a clean scan is no endorsement, it
#          only says that none of the places below holds anything.
#
# Usage:
#   python .act/scripts/package_scan.py <package folder>
#
# What it reports (one line each):
#   - every line of `## disables` in package.md (a template rule the package switches off)
#   - every line of `## checks` that sets a check weaker than the template's default (`off` < `warn` < `block`; a
#     check the template does not know counts as `block`)
#   - every file under `scripts/` and `hooks/checks/` (code that runs in the project), and any `install.py`
#   - an `install.md` (an AI-guided setup that will be followed after the install)
#   - every MCP server: a `.mcp.json` or `mcp.json` anywhere, `mcpServers` in any file, `mcp add` in `install.md`,
#     `install.py` or a script
#   - a symbolic link or junction, and a file too large to read (neither can be judged)
#
# Output format:
#   One finding per line, `RED <kind>: <detail>`, in a fixed order; the lines are plain text. When stdout is a
#   terminal the command prints them in ANSI red as well. Exit 0 = nothing found, 1 = findings, 2 = usage (no
#   folder given, or not a folder).
#
# Library use: `scan(folder)` (all of the above), `scan_text(package.md bytes)` (the `disables` and `checks` lines
#   only, no disk access) and `relaxation_counts(findings)` for the one-line summary of a session start.
#
# Limits:
#   Static and by name and text: a program that builds a path or a command at run time, or a file kind not named
#   above, is not seen. The scan says what is there, never whether it is harmless.

from __future__ import annotations

import os
import re
import stat
import sys
from pathlib import Path
from typing import Optional

import actlib

PREFIX = "RED "
RANK = {"off": 0, "warn": 1, "block": 2}
MAX_FILE = 4 * 1024 * 1024  # bytes read of one file for the text searches
SIDES = ("pre-template", "post-template")
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")
LIST_RE = re.compile(r"^[-*]\s+(.*\S)\s*$")
MCP_ADD_RE = re.compile(r"""\bmcp\b[\s'",\[\]]{1,6}add\b""", re.IGNORECASE)  # `mcp add`, also as an argument list
MCP_FILES = (".mcp.json", "mcp.json")
RED, RESET = "\x1b[31m", "\x1b[0m"


def _walk(folder: Path) -> "tuple[list[str], list[str]]":
    """(files, problems) below `folder`: the regular files as sorted posix paths relative to it, and a line for each
    symbolic link or junction (never followed) and each entry or folder that cannot be read."""
    files: list[str] = []
    links: list[str] = []
    stack: list[tuple[Path, str]] = [(folder, "")]
    while stack:
        current, prefix = stack.pop()
        try:
            entries = sorted(os.scandir(current), key=lambda entry: entry.name)
        except OSError as error:
            links.append(f"{prefix or '.'} (cannot be listed: {type(error).__name__})")
            continue
        for entry in entries:
            rel = prefix + entry.name
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                links.append(f"{rel} (cannot be read)")
                continue
            if actlib.is_redirect(info):
                links.append(f"{rel} (symbolic link or junction)")
            elif stat.S_ISDIR(info.st_mode):
                stack.append((Path(entry.path), rel + "/"))
            elif stat.S_ISREG(info.st_mode):
                files.append(rel)
    return sorted(files), sorted(links)


def manifest_sections(text: str) -> "dict[str, list[str]]":
    """The non-blank lines of each `## <name>` section of package.md, by lower-cased name; the header between the
    two leading `---` lines is skipped."""
    lines = text.replace("\r\n", "\n").split("\n")
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                lines = lines[index + 1:]
                break
    out: dict[str, list[str]] = {}
    current: Optional[str] = None
    for line in lines:
        match = SECTION_RE.match(line)
        if match:
            current = match.group(1).strip().lower()
            out.setdefault(current, [])
        elif current is not None and line.strip():
            out[current].append(line.strip())
    return out


def _default_mode(check: str) -> str:
    """The template's default for a block/warn/off check; `block` (the strongest) for one it does not know, so
    that anything but `block` is reported."""
    entry = actlib.CONFIG_SCHEMA.get(check)
    default = entry.default if entry is not None else ""
    return default if default in RANK else "block"


def _read_bytes(folder: Path, rel: str) -> "Optional[bytes]":
    """The bytes of a file, None when it is larger than MAX_FILE or cannot be read."""
    path = folder / rel
    try:
        if path.stat().st_size > MAX_FILE:
            return None
        return path.read_bytes()
    except OSError:
        return None


def _read(folder: Path, rel: str) -> "Optional[str]":
    """The text of a file, None when it is larger than MAX_FILE or cannot be read."""
    data = _read_bytes(folder, rel)
    return None if data is None else data.decode("utf-8", errors="replace")


def scan_text(manifest: "Optional[bytes]") -> "list[str]":
    """The findings of the `package.md` bytes alone, in the form of `scan`: one `RED disables:` finding per line of its
    `## disables` section and one `RED checks:` finding per line of `## checks` that is no list line or sets a check
    weaker than the template's default. None, or bytes larger than MAX_FILE, give the single finding that it was not
    read. Pure: nothing is read from disk."""
    if manifest is None or len(manifest) > MAX_FILE:
        return [f"{PREFIX}package.md: too large or unreadable, `disables` and `checks` were not read"]
    sections = manifest_sections(manifest.decode("utf-8", errors="replace"))
    findings: list[str] = []
    for line in sections.get("disables", []):
        match = LIST_RE.match(line)
        findings.append(f"{PREFIX}disables: {match.group(1) if match else line}")
    for line in sections.get("checks", []):
        match = LIST_RE.match(line)
        text = match.group(1) if match else line
        name, _, value = text.partition(":")
        name, value = name.strip().strip("`"), value.strip().strip("`").lower()
        default = _default_mode(name)
        if not match:
            findings.append(f"{PREFIX}checks: a line that is no list line, so it cannot be compared: {text}")
        elif RANK.get(value, -1) < RANK[default]:
            findings.append(f"{PREFIX}checks: weaker than the template's `{default}`: {text}")
    return findings


def relaxation_counts(findings: "list[str]") -> "tuple[int, int]":
    """(disabled rules, weaker checks) in findings of `scan_text` or `scan`: the `disables:` lines and the `checks:
    weaker than` lines. Counted the way the scan lists them, so a summary and the scan never disagree."""
    disabled = sum(1 for line in findings if line.startswith(f"{PREFIX}disables:"))
    weaker = sum(1 for line in findings if line.startswith(f"{PREFIX}checks: weaker than"))
    return disabled, weaker


def _is_code_path(rel: str) -> bool:
    parts = rel.split("/")
    if "scripts" in parts[:-1]:
        return True
    return any(parts[i] == "hooks" and parts[i + 1] == "checks" for i in range(len(parts) - 2))


def scan(folder: Path) -> "list[str]":
    """The findings for the package folder `folder`, one per line, each starting with `RED `; empty when none.
    Reads only: nothing of the folder is imported, run or evaluated. A folder that cannot be listed is a finding."""
    folder = Path(folder)
    if not folder.is_dir():
        return [f"{PREFIX}folder: `{folder}` is not a folder, nothing could be scanned"]
    files, problems = _walk(folder)
    findings: list[str] = []

    if "package.md" in files:
        findings += scan_text(_read_bytes(folder, "package.md"))

    for rel in files:
        base = rel.rsplit("/", 1)[-1]
        if rel == "install.md":
            findings.append(f"{PREFIX}install.md: an AI-guided setup that will be followed after the install")
        if base == "install.py":
            findings.append(f"{PREFIX}install.py: code that runs once at install ({rel})")
        elif _is_code_path(rel):
            findings.append(f"{PREFIX}code: {rel} (runs in the project)")
        if base.lower() in MCP_FILES:
            findings.append(f"{PREFIX}mcp server: {rel} (an MCP configuration file)")

    for rel in files:
        text = _read(folder, rel)
        if text is None:
            findings.append(f"{PREFIX}unreadable: {rel} (too large or cannot be read, it was not searched)")
            continue
        if "mcpServers" in text:
            findings.append(f"{PREFIX}mcp server: `mcpServers` in {rel}")
        runs_code = rel in ("install.md", "install.py") or _is_code_path(rel) or rel.rsplit("/", 1)[-1] == "install.py"
        if runs_code and MCP_ADD_RE.search(text):
            findings.append(f"{PREFIX}mcp server: `mcp add` in {rel}")

    for problem in problems:
        findings.append(f"{PREFIX}link or unreadable: {problem}")
    return findings


def colorize(line: str, stream=None) -> str:
    """`line` in ANSI red when `stream` (default stdout) is a terminal, else unchanged."""
    stream = stream if stream is not None else sys.stdout
    try:
        tty = stream.isatty()
    except (AttributeError, ValueError):
        tty = False
    return f"{RED}{line}{RESET}" if tty else line


def main(argv: "list[str]") -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    if len(argv) != 1 or argv[0] in ("-h", "--help"):
        print("usage: package_scan.py <package folder>", file=sys.stderr)
        return 2
    folder = Path(argv[0])
    if not folder.is_dir():
        print(f"package_scan: `{folder}` is not a folder", file=sys.stderr)
        return 2
    findings = scan(folder)
    for line in findings:
        print(colorize(line))
    return 1 if findings else 0


if __name__ == "__main__":
    try:
        from usage import count_script_run
        count_script_run(__file__)
    except ImportError:
        pass
    sys.exit(main(sys.argv[1:]))
