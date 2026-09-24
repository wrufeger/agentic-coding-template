#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: List the project's skills like a man page (name + one-line description from each
#          `SKILL.md`'s frontmatter), or print one skill's `SKILL.md` in full — the mechanical
#          half of skill `act`. Built so the `/act` UserPromptSubmit fast path
#          (.act/hooks/dispatch.py) never has to walk `.act/skills/`/`docs/ai/local/skills/` by
#          hand: it imports this module and calls render() once a prompt actually matches
#          "/act"/"/act <name>" (T67 — the skill used to make the model read every SKILL.md by
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
#   Unknown name: "Unknown skill '<name>'." on its own line, then a blank line, then the table —
#   never an error exit, since the caller (the hook included) always wants something shown.
#   Exit 0 always; exit 1 only if no skills directory exists at all (template checkout broken).

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NamedTuple, Optional

import actlib
import tiers


class Skill(NamedTuple):
    name: str          # frontmatter `name`, falling back to the directory name
    description: str   # frontmatter `description`, "" if missing
    origin: str         # "local" or "template" — actlib.resolve()'s own vocabulary
    path: Path


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
    return Skill(name=name, description=description, origin=origin, path=path)


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


def render_table(skills: list[Skill]) -> str:
    if not skills:
        return "No skills found under .act/skills/ — is this a template checkout?"
    width = max(len(skill.name) for skill in skills)
    lines = ["Skills in this project — /act <name> shows one in full", ""]
    lines.extend(f"  {skill.name.ljust(width)}  {skill.description}".rstrip() for skill in skills)
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
