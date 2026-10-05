#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Generate .act/scripts/README.md — a reference for every script under .act/scripts/,
#          built from each script's own `--help` output plus a small hand-kept table that says
#          whether a script is meant to be run directly or through a skill (a judgement call is
#          involved), and, for a library module with no CLI, just the one-line purpose from its
#          own header comment. Single source of truth: nothing here restates a script's options
#          by hand, so the reference cannot drift from the script's actual argparse definition —
#          only from this generator itself, which `--check` catches. Stdlib only.
#
# Usage:
#   python .act/scripts/script_docs.py            # (re)write .act/scripts/README.md
#   python .act/scripts/script_docs.py --check     # compare disk against the generated text,
#                                                   # write nothing, exit 1 on any difference
#
# Output format:
#   (no flag): prints "script_docs: wrote .act/scripts/README.md (<n> scripts)" to stdout, exit 0.
#   --check:   "script_docs: README.md matches" to stdout and exit 0 if up to date; otherwise one
#              problem per line to stderr (README.md missing/stale, a script with no entry in
#              SCRIPT_INFO below, an entry naming a skill that doesn't exist under .act/skills/,
#              or a stale entry for a script no longer on disk) and exit 1.
#
# Determinism: `--help` output can vary with terminal width and argparse's own program-name
# guess; both are pinned here (COLUMNS=100, argparse's default prog is already the bare filename,
# since it comes from os.path.basename(sys.argv[0])) so two runs produce identical output
# regardless of machine or invocation path. Subprocess output is newline-normalized
# ("\r\n"/"\r" -> "\n") so a Windows run compares equal to a Linux one, and the file itself is
# written with explicit "\n" endings (see _write_lf), same convention as init.py's
# _write_new_file.

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

import actlib

README_NAME = "README.md"
HELP_COLUMNS = "100"

# kind:
#   "library" — no CLI (no `if __name__ == "__main__":`), imported only.
#   "direct"  — run as-is, no judgement call needed.
#   "skill"   — better run through the named skill: a judgement call is involved (requires
#               "skill", checked against the directory names under .act/skills/; several skills
#               that use the same script are given comma-separated: "act-pr, act-issue").
# "note" (optional): one short qualifier shown in parentheses next to the call, for a script that
# is partly the other kind (e.g. a --plan/read-only mode that is direct even though the full run
# needs a skill).
SCRIPT_INFO: dict[str, dict[str, str]] = {
    "actlib.py": {"kind": "library"},
    "board.py": {"kind": "direct"},
    "adopt.py": {"kind": "direct", "note": "used by skill `act-adopt` (stage 6)"},
    "adopt_config.py": {"kind": "direct", "note": "used by skill `act-adopt` (stage 6)"},
    "adopt_entries.py": {"kind": "direct", "note": "used by skill `act-adopt` (stage 6)"},
    "adopt_passages.py": {"kind": "direct", "note": "used by skill `act-adopt` (stage 6)"},
    "adopt_scan.py": {"kind": "direct", "note": "used by skill `act-adopt` (stage 6)"},
    "doctor.py": {"kind": "direct", "note": "judging the findings: skill `act-doctor`"},
    "entries.py": {"kind": "direct"},
    "feedback.py": {"kind": "skill", "skill": "act-feedback", "note": "`--status`/`--due` alone are direct"},
    "feedback_privacy.py": {"kind": "library"},
    "forge.py": {"kind": "skill", "skill": "act-pr, act-issue, act-integrations", "note": "reads are direct; every write shows a preview and needs `--apply` after the human's \"yes\" (`topics/live-systems.md`)"},
    "frontmatter.py": {"kind": "library"},
    "i18n_check.py": {"kind": "skill", "skill": "act-check-translations"},
    "ideas.py": {"kind": "direct", "note": "session start and init call it; run by hand to record entries as processed"},
    "init.py": {"kind": "direct"},
    "integrations.py": {"kind": "skill", "skill": "act-integrations", "note": "`status` alone is direct"},
    "log.py": {"kind": "direct"},
    "manifest.py": {"kind": "direct"},
    "rules.py": {"kind": "direct"},
    "script_docs.py": {"kind": "direct"},
    "security_deep.py": {"kind": "direct", "note": "used by skill `act-release` with `security-check: full`"},
    "security_scan.py": {"kind": "direct", "note": "also run before a commit that touches a lock file and daily at session start, with `security-check: deps`/`full`"},
    "seo_check.py": {"kind": "skill", "skill": "act-seo"},
    "settings_export.py": {"kind": "skill", "skill": "act-export-settings"},
    "settings_format.py": {"kind": "library"},
    "settings_load.py": {"kind": "skill", "skill": "act-load-settings"},
    "skills.py": {"kind": "direct", "note": "used by skill `act` and by dispatch.py's `/act` fast path"},
    "tiers.py": {"kind": "library"},
    "update.py": {"kind": "skill", "skill": "act-update", "note": "`--plan` alone is direct"},
    "unit_copies.py": {"kind": "direct", "note": "session start and update.py call it; run by hand to create the copies at once"},
    "usage.py": {"kind": "direct"},
}


class ScriptDocsError(Exception):
    """A script on disk has no SCRIPT_INFO entry, an entry names a skill that does not exist
    under .act/skills/, an entry is marked "library" but has a __main__ entry point (or the
    reverse), or SCRIPT_INFO has an entry for a script no longer on disk — each would make the
    generated reference silently wrong instead of catching the gap."""


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def _scripts_dir(root: Path) -> Path:
    return root / ".act" / "scripts"


def _discover_scripts(scripts_dir: Path) -> list[Path]:
    return sorted(p for p in scripts_dir.glob("*.py") if p.is_file())


def _has_cli(path: Path) -> bool:
    return "\nif __name__ ==" in path.read_text(encoding="utf-8")


def _truncate(text: str, limit: int = 140) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:—-") + "…"


def _purpose_line(path: Path) -> str:
    """The "# Purpose:" header field, header continuation lines joined with a space and cut to
    one line (word boundary, "…" suffix) — not a "first sentence" cut, since these header
    paragraphs wrap without regard for sentence-ending periods (and use "vs." mid-sentence)."""
    parts: list[str] = []
    collecting = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("#"):
            if collecting:
                break
            continue
        stripped = line[1:].strip()
        if not collecting:
            if stripped.startswith("Purpose:"):
                collecting = True
                parts.append(stripped[len("Purpose:"):].strip())
            continue
        if stripped == "" or re.match(r"^(Usage|Output format)\s*:", stripped):
            break
        parts.append(stripped)
    return _truncate(" ".join(p for p in parts if p))


# ---------------------------------------------------------------------------
# --help capture
# ---------------------------------------------------------------------------

def _run_help(script_path: Path, subcommand: Optional[str] = None) -> str:
    env = dict(os.environ)
    env["COLUMNS"] = HELP_COLUMNS
    env["LINES"] = "24"
    env["PYTHONIOENCODING"] = "utf-8"
    # Pin argparse's help to plain text regardless of the caller's own environment: Python 3.13+
    # colors --help output by default when it thinks the terminal supports it, and that decision
    # can survive into a captured subprocess too. NO_COLOR=1 is argparse's own opt-out; FORCE_COLOR
    # and PYTHON_COLORS (both an explicit opt-*in*, PYTHON_COLORS besides also being read by 3.14)
    # are removed rather than merely left alone, so a run with either set in the calling shell
    # cannot make README.md carry ANSI escapes and then fail its own `--check` against a run
    # without them.
    env["NO_COLOR"] = "1"
    env.pop("FORCE_COLOR", None)
    env.pop("PYTHON_COLORS", None)
    argv = [sys.executable, str(script_path)]
    if subcommand:
        argv.append(subcommand)
    argv.append("--help")
    result = subprocess.run(
        argv, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
    )
    text = result.stdout if result.stdout.strip() else result.stderr
    return text.replace("\r\n", "\n").replace("\r", "\n").strip("\n")


_SUBCOMMANDS_RE = re.compile(r"\{([A-Za-z0-9_,-]+)\}\s+\.\.\.")


def _subcommands_from_help(help_text: str) -> list[str]:
    first_line = help_text.splitlines()[0] if help_text else ""
    match = _SUBCOMMANDS_RE.search(first_line)
    return match.group(1).split(",") if match else []


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------

def generate(root: Path) -> str:
    scripts_dir = _scripts_dir(root)
    paths = _discover_scripts(scripts_dir)
    disk_names = {p.name for p in paths}
    stale = sorted(set(SCRIPT_INFO) - disk_names)
    if stale:
        raise ScriptDocsError(
            f"SCRIPT_INFO has entries for scripts no longer on disk: {', '.join(stale)}"
        )

    skills_dir = root / ".act" / "skills"
    known_skills = {p.name for p in skills_dir.iterdir() if p.is_dir()} if skills_dir.is_dir() else set()

    entries = []
    for path in paths:
        name = path.name
        info = SCRIPT_INFO.get(name)
        if info is None:
            raise ScriptDocsError(f"{name}: no entry in SCRIPT_INFO — add one before regenerating")
        kind = info["kind"]
        skill = info.get("skill")
        for skill_name in _skill_names(skill):
            if skill_name not in known_skills:
                raise ScriptDocsError(f"{name}: SCRIPT_INFO names skill '{skill_name}', not found under .act/skills/")
        has_cli = _has_cli(path)
        if kind == "library" and has_cli:
            raise ScriptDocsError(f"{name}: marked \"library\" in SCRIPT_INFO but has a __main__ entry point")
        if kind != "library" and not has_cli:
            raise ScriptDocsError(f"{name}: marked \"{kind}\" in SCRIPT_INFO but has no __main__ entry point")

        entry = {"name": name, "kind": kind, "skill": skill, "note": info.get("note"),
                  "purpose": _purpose_line(path)}
        if kind != "library":
            help_text = _run_help(path)
            subcommands = _subcommands_from_help(help_text)
            entry["help"] = help_text
            entry["subcommands"] = [(sub, _run_help(path, sub)) for sub in subcommands]
        entries.append(entry)
    return _render(entries)


def _skill_names(skill: Optional[str]) -> list[str]:
    """The skill names of a SCRIPT_INFO "skill" value: one name, or several separated by commas."""
    return [part.strip() for part in (skill or "").split(",") if part.strip()]


def _call_cell(entry: dict) -> str:
    if entry["kind"] == "library":
        return "library"
    skills = _skill_names(entry.get("skill"))
    if entry["kind"] == "direct":
        cell = "direct"
    else:
        cell = f"skill{'s' if len(skills) > 1 else ''} " + ", ".join(f"`{s}`" for s in skills)
    if entry.get("note"):
        cell += f" ({entry['note']})"
    return cell


def _render(entries: list[dict]) -> str:
    lines: list[str] = [
        "<!-- generated by script_docs.py — do not edit by hand -->",
        "",
        "# Scripts",
        "",
        "One row per script under `.act/scripts/`; the per-script sections below are each "
        "script's own `--help` output, not retyped by hand. Regenerate with "
        "`python .act/scripts/script_docs.py` after changing a script's arguments — "
        "`--check` catches drift, and `doctor.py` reports it as a finding.",
        "",
        "| Script | Purpose | Call |",
        "| :--- | :--- | :--- |",
    ]
    for entry in entries:
        lines.append(f"| `{entry['name']}` | {entry['purpose']} | {_call_cell(entry)} |")
    lines.append("")

    libraries = [e for e in entries if e["kind"] == "library"]
    if libraries:
        lines.append("## Libraries (no CLI, imported only)")
        lines.append("")
        for entry in libraries:
            lines.append(f"- `{entry['name']}` — {entry['purpose']}")
        lines.append("")

    for entry in entries:
        if entry["kind"] == "library":
            continue
        lines.append(f"## `{entry['name']}`")
        lines.append("")
        lines.append(f"Call: {_call_cell(entry)}")
        lines.append("")
        lines.append("```text")
        lines.append(entry["help"])
        lines.append("```")
        lines.append("")
        for sub, sub_help in entry["subcommands"]:
            lines.append(f"### `{entry['name']} {sub}`")
            lines.append("")
            lines.append("```text")
            lines.append(sub_help)
            lines.append("```")
            lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


# ---------------------------------------------------------------------------
# Check
# ---------------------------------------------------------------------------

def check(root: Path) -> list[str]:
    try:
        generated = generate(root)
    except ScriptDocsError as exc:
        return [str(exc)]
    readme_path = _scripts_dir(root) / README_NAME
    if not readme_path.is_file():
        return ["missing — run `python .act/scripts/script_docs.py`"]
    if readme_path.read_text(encoding="utf-8") != generated:
        return ["out of date — run `python .act/scripts/script_docs.py`"]
    return []


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _write_lf(dest: Path, text: str) -> None:
    """Write with "\\n" line endings regardless of platform default — same convention as
    init.py's own _write_new_file — so README.md stays byte-identical across OSes."""
    with open(dest, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="script_docs.py",
        description="Generate .act/scripts/README.md from every script's own --help output.",
    )
    parser.add_argument("--check", action="store_true",
                         help="compare disk against the generated text, write nothing, exit 1 on any difference")
    return parser


def main(argv: list[str]) -> int:
    # Output can carry an em dash; on Windows, stdout/stderr otherwise default to the console's
    # legacy code page instead of UTF-8, which would corrupt it. Same fix as .act/scripts/rules.py.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    args = build_parser().parse_args(argv)
    root = actlib.repo_root()

    if args.check:
        problems = check(root)
        if problems:
            for problem in problems:
                print(f"{README_NAME}: {problem}", file=sys.stderr)
            return 1
        print(f"script_docs: {README_NAME} matches")
        return 0

    try:
        text = generate(root)
    except ScriptDocsError as exc:
        print(f"script_docs: {exc}", file=sys.stderr)
        return 1
    dest = _scripts_dir(root) / README_NAME
    _write_lf(dest, text)
    count = len(_discover_scripts(_scripts_dir(root)))
    print(f"script_docs: wrote {dest.relative_to(root).as_posix()} ({count} scripts)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
