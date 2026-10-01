#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: List the project's skills like a man page (name + one-line description from each
#          `SKILL.md`'s frontmatter), or print one skill's `SKILL.md` in full — the mechanical
#          half of skill `act`. Built so the `/act` UserPromptSubmit fast path
#          (.act/hooks/dispatch.py) never has to walk `.act/skills/`/`docs/ai/local/skills/` by
#          hand: it imports this module and calls render() once a prompt actually matches
#          "/act"/"/act <name>" (the skill used to make the model read every SKILL.md by
#          hand, seven tool calls, ~74s for one `/act`).
#
#          Skill discovery follows the same override rule as everywhere else in this template
#          (actlib.resolve(), see .act/skills/README.md): a project's own skill under
#          docs/ai/local/skills/<name>/SKILL.md wins over a template one of the same name, and a
#          project-only skill (no template counterpart) is listed too — the two source
#          directories are only used to find *names*, actlib.resolve() decides which file wins
#          for each one.
#
# Usage:
#   python .act/scripts/skills.py            # table: name + description, sorted by name
#   python .act/scripts/skills.py <name>     # that skill's SKILL.md, in full and unchanged
#
# Output format:
#   Plain text, no Markdown fence — callers (this script's own CLI, the `act` skill's fallback,
#   the UserPromptSubmit fast path) put it in a code block themselves where one is wanted, so the
#   text here can be reused unchanged in all three places (R-cost-script single source of truth).
#   Table: header line, blank line, then per skill a "  /<name>" line (two-space indent, plus
#   " (own)"/" (overridden)" for a project skill under docs/ai/local/skills/ — see Skill.marker)
#   and, below it, the description with its trigger sentence (the first one starting "Use ...")
#   cut off, wrapped to 96 columns with a six-space indent on every line (live probe: long
#   descriptions used to wrap flush-left, unreadable against the name column).
#   Unknown name: "Unknown skill '<name>'." on its own line, then a blank line, then the table —
#   never an error exit, since the caller (the hook included) always wants something shown.
#   Exit 0 always; exit 1 only if no skills directory exists at all (template checkout broken).

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path
from typing import NamedTuple, Optional

import actlib
import tiers

WIDTH = 96          # wrap width for the table's description lines
INDENT = "      "   # six spaces — description lines, under the two-space-indented "/<name>" line

# Sentence-lead marker for the trigger half of a description (see _short_description()) — every
# convention seen across this template's SKILL.md files reads "Use when ...", "Use after ...",
# "Use to ...", "Use right after ...", so the generic prefix is what's checked, not a fixed list.
_TRIGGER_PREFIX = "Use "


class Skill(NamedTuple):
    name: str          # frontmatter `name`, falling back to the directory name
    description: str   # frontmatter `description`, "" if missing
    origin: str         # "local" or "template" — actlib.resolve()'s own vocabulary
    path: Path
    marker: str = ""    # "own" (local, no template counterpart), "overridden" (local + template), or ""


def _skill_dir_names(root: Path) -> set[str]:
    """Every directory name under `.act/skills/` or `docs/ai/local/skills/` that holds a
    `SKILL.md` — a name here only says "worth resolving", actlib.resolve() below still decides
    which file (template or project override) is read for it."""
    names: set[str] = set()
    for base in (root / ".act" / "skills", root / "docs" / "ai" / "local" / "skills"):
        if not base.is_dir():
            continue
        for entry in base.iterdir():
            if entry.is_dir() and (entry / "SKILL.md").is_file():
                names.add(entry.name)
    return names


def _marker(root: Path, dir_name: str, origin: str) -> str:
    """"own" for a project skill with no template counterpart, "overridden" for a project skill
    that replaces a template one of the same name, "" for a plain template skill."""
    if origin != "local":
        return ""
    template_path = root / ".act" / "skills" / dir_name / "SKILL.md"
    return "overridden" if template_path.is_file() else "own"


def load_skill(root: Path, dir_name: str) -> Optional[Skill]:
    """The effective `Skill` for the skill directory named `dir_name`, or None if neither source
    has it (a caller passed a name that does not exist at all)."""
    resolved = actlib.resolve(f"skills/{dir_name}/SKILL.md")
    if resolved is None:
        return None
    path, origin = resolved
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    fields, _body, _order = tiers.split_frontmatter(text)
    name = fields.get("name", "").strip() or dir_name
    description = fields.get("description", "").strip()
    marker = _marker(root, dir_name, origin)
    return Skill(name=name, description=description, origin=origin, path=path, marker=marker)


def list_skills(root: Path) -> list[Skill]:
    """Every skill, sorted by its frontmatter `name` — the template's own plus any project-only
    one under docs/ai/local/skills/, one entry per name (a project override never doubles up with
    the template skill it replaces, since both share the same directory name)."""
    skills = []
    for dir_name in _skill_dir_names(root):
        skill = load_skill(root, dir_name)
        if skill is not None:
            skills.append(skill)
    return sorted(skills, key=lambda skill: skill.name)


def _short_description(description: str) -> str:
    """`description` with its trigger sentence dropped — the first sentence that starts with
    `_TRIGGER_PREFIX` ("Use when a bug is reported, ...", "Use right after a task is accepted,
    ...", "Use to check for drift, ..."), plus everything after it. Sentence boundary is ". ", so
    the description is split on it and the first matching sentence onward is cut. Falls back to
    the full description when no such sentence exists, or when cutting it would leave nothing
    (the whole description is one trigger sentence)."""
    sentences = description.split(". ")
    for i, sentence in enumerate(sentences):
        if sentence.startswith(_TRIGGER_PREFIX):
            short = ". ".join(sentences[:i]).strip()
            return short or description
    return description


def render_table(skills: list[Skill]) -> str:
    if not skills:
        return "No skills found under .act/skills/ — is this a template checkout?"
    lines = ["PROJECT SKILLS — /act <name> shows one in full", ""]
    for skill in skills:
        suffix = f" ({skill.marker})" if skill.marker else ""
        lines.append(f"  /{skill.name}{suffix}")
        short = _short_description(skill.description)
        if short:
            lines.append(textwrap.fill(short, WIDTH, initial_indent=INDENT, subsequent_indent=INDENT))
    return "\n".join(lines)


def render(root: Path, name: str = "") -> str:
    """The full text for `name` (its SKILL.md, unchanged) or, with no name, the table from
    render_table() — what every caller (this script's CLI, the `act` skill's fallback, the
    UserPromptSubmit fast path) shows. Never raises: a read error falls back to the table with a
    note, same as an unknown name."""
    name = name.strip()
    skills = list_skills(root)
    if not name:
        return render_table(skills)
    match = next((skill for skill in skills if skill.name == name), None)
    if match is None:
        return f"Unknown skill '{name}'.\n\n{render_table(skills)}"
    try:
        return match.path.read_text(encoding="utf-8").rstrip("\n")
    except OSError as exc:
        return f"Could not read {match.path}: {exc}\n\n{render_table(skills)}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skills.py",
        description="List the project's skills (name + description), or print one in full.",
    )
    parser.add_argument("name", nargs="?", default="", help="print exactly this skill's SKILL.md in full")
    return parser


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    try:
        root = actlib.repo_root()
    except RuntimeError as exc:
        print(f"skills.py: {exc}", file=sys.stderr)
        return 1

    if not (root / ".act" / "skills").is_dir():
        print(f"skills.py: no .act/skills/ under {root} — is this a template checkout?", file=sys.stderr)
        return 1

    print(render(root, args.name))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
