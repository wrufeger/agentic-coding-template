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
#          `--check` lints the descriptions (and a few body properties) of those same skills
#          against the description pattern in .act/skills/README.md § "Writing a skill
#          description" — the doctor reuses lint() for a project's own skills.
#
# Usage:
#   python .act/scripts/skills.py            # table: name + description, sorted by name
#   python .act/scripts/skills.py <name>     # that skill's SKILL.md, in full and unchanged
#   python .act/scripts/skills.py --check    # lint every skill; exit 1 on an error, else 0
#
# Output format:
#   Plain text, no Markdown fence — callers (this script's own CLI, the `act` skill's fallback,
#   the UserPromptSubmit fast path) put it in a code block themselves where one is wanted, so the
#   text here can be reused unchanged in all three places (R-cost-script single source of truth).
#   Table: header line, blank line, then per skill a "  /<name>" line (two-space indent, plus
#   " (own)"/" (overridden)" for a project skill under docs/ai/local/skills/ — see Skill.marker)
#   and, below it, the description without its trigger sentence (the first one starting
#   "Use ..."): for a trigger-first description the outcome sentence(s) after it, for an older
#   one the text before it; the full description when nothing else remains. Wrapped to 96 columns
#   with a six-space indent on every line (live probe: long descriptions used to wrap
#   flush-left, unreadable against the name column).
#   Unknown name: "Unknown skill '<name>'." on its own line, then a blank line, then the table —
#   never an error exit, since the caller (the hook included) always wants something shown.
#   Exit 0 always; exit 1 only if no skills directory exists at all (template checkout broken).
#   --check: one line per finding, "ERROR|WARN  <name>: <message>", then a "TOTAL" line (skills,
#   description words, estimated tokens — ceil(characters / 4) over the descriptions, a rough
#   figure for English prose) and a "RESULT" line. Exit 0 with no error (warnings allowed), 1 with
#   at least one error.

from __future__ import annotations

import argparse
import math
import re
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

# Description lint limits (words) — .act/skills/README.md § "Writing a skill description".
MIN_WORDS = 15
WARN_WORDS = 55
MAX_WORDS = 65
BODY_WARN_LINES = 300

# Third-person verbs that typically open a step in a step-summary description ("reads X, checks Y,
# writes Z"); three or more comma-joined segments starting with one read as a list of steps.
_STEP_VERBS = frozenset(
    "reads writes checks creates runs collects lists updates asks opens shows builds copies moves "
    "adds removes sets reviews books files archives compares scans derives picks proposes generates "
    "prints extracts drafts fetches verifies searches records reports renames translates "
    "inspects validates tests commits stages loads saves sorts counts finds names "
    "researches cuts measures reproduces offers drafts proposes".split()
)
# Sentence boundary: end punctuation, whitespace, then a capital or an opening quote. A bare ". "
# would cut "richte ... ein" in the middle of a trigger phrase.
_SENTENCE_SPLIT = re.compile(r'(?<=[.!?])\s+(?=[A-Z"\u201e])')
_WHEN_TO_USE_HEADING = re.compile(r"(?im)^#{1,6}\s*when to use\b")


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
    # Same override rule as actlib.resolve(), but against `root` (not the working directory), so
    # the doctor can lint another project via --target.
    local_path = root / "docs" / "ai" / "local" / "skills" / dir_name / "SKILL.md"
    template_path = root / ".act" / "skills" / dir_name / "SKILL.md"
    if local_path.is_file():
        path, origin = local_path, "local"
    elif template_path.is_file():
        path, origin = template_path, "template"
    else:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # listed with an empty description so lint_skill() reports the unreadable file
        return Skill(name=dir_name, description="", origin=origin, path=path,
                     marker=_marker(root, dir_name, origin))
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
    ...", "Use to check for drift, ..."). Sentence boundary is _SENTENCE_SPLIT. A trigger-first description
    (the pattern in .act/skills/README.md) keeps the sentences after the trigger — the outcome
    and any "Not for ..." hint; an older one keeps the text before it and drops the rest. Falls
    back to the full description when no trigger sentence exists, or when dropping it would leave
    nothing (the whole description is the trigger sentence)."""
    sentences = _SENTENCE_SPLIT.split(description)
    for i, sentence in enumerate(sentences):
        if sentence.startswith(_TRIGGER_PREFIX):
            if i == 0:
                short = " ".join(sentences[1:]).strip()
            else:
                short = " ".join(sentences[:i]).strip()
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

# ---------------------------------------------------------------------------
# Lint (--check)
# ---------------------------------------------------------------------------

class LintFinding(NamedTuple):
    level: str    # "ERROR" or "WARN"
    skill: str    # skill name
    message: str


def _step_summary(description: str) -> bool:
    """Heuristic: the description summarizes steps instead of (or before) naming a trigger —
    a "then" between steps, an arrow, or a sentence other than the trigger sentence with three or
    more comma/"and"-joined segments that open with a step verb ("reads X, checks Y and writes Z")."""
    for sentence in _SENTENCE_SPLIT.split(description):
        if sentence.startswith(_TRIGGER_PREFIX):
            continue
        if re.search(r"\bthen\b|->|\u2192", sentence):
            return True
        segments = re.split(r",\s*(?:and\s+)?|\s+and\s+", sentence)
        starts = sum(1 for seg in segments if seg.split(" ", 1)[0].lower() in _STEP_VERBS)
        if starts >= 3:
            return True
    return False


def lint_skill(skill: Skill, language_neutral: bool = False) -> list[LintFinding]:
    """Every finding for one skill: description length, trigger-first, step summary, and two body
    properties (a "When to use" heading, a long body without a references/ folder).

    `language_neutral` keeps only what holds in any language and for any size of skill — a missing
    or overlong description, an unreadable file, a long body without references/. A project's own
    skill may be written in the project's language and may be tiny, so the English trigger-first,
    step-verb and minimum-length checks would only produce noise there."""
    findings: list[LintFinding] = []
    name = skill.name
    description = skill.description
    words = len(description.split())
    if words == 0 or (words < MIN_WORDS and not language_neutral):
        findings.append(LintFinding("ERROR", name, f"description has {words} words (minimum {MIN_WORDS})"))
    elif words > MAX_WORDS:
        findings.append(LintFinding("ERROR", name, f"description has {words} words (maximum {MAX_WORDS})"))
    elif words > WARN_WORDS:
        findings.append(LintFinding("WARN", name, f"description has {words} words (aim for at most {WARN_WORDS})"))
    if not language_neutral and not description.startswith(_TRIGGER_PREFIX):
        findings.append(LintFinding(
            "ERROR", name, 'description does not start with a trigger sentence ("Use when ...")'))
    if not language_neutral and _step_summary(description):
        findings.append(LintFinding(
            "ERROR", name, "description looks like a summary of steps; name the trigger and the outcome instead "
            "(an agent that reads the steps acts on them without loading the skill)"))
    try:
        body = skill.path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        findings.append(LintFinding("ERROR", name, f"cannot read {skill.path}: {exc}"))
        return findings
    if not language_neutral and _WHEN_TO_USE_HEADING.search(body):
        findings.append(LintFinding(
            "WARN", name, 'body has a "When to use" heading; the trigger belongs in the description '
            "(the body is only read after the skill has loaded)"))
    lines = len(body.splitlines())
    if lines > BODY_WARN_LINES and not (skill.path.parent / "references").is_dir():
        findings.append(LintFinding(
            "WARN", name, f"SKILL.md has {lines} lines and no references/ folder (limit ~{BODY_WARN_LINES}); "
            "move detail to references/<topic>.md with a pointer saying when to read it"))
    return findings


def description_totals(skills: list[Skill]) -> tuple[int, int, int]:
    """(skills, words, estimated tokens) over all descriptions. Tokens = ceil(characters / 4),
    the usual rough figure for English prose; a real tokenizer differs by some percent."""
    words = sum(len(s.description.split()) for s in skills)
    chars = sum(len(s.description) for s in skills)
    return len(skills), words, math.ceil(chars / 4)


def lint(root: Path, language_neutral: bool = False) -> list[tuple[Skill, LintFinding]]:
    """Every finding under `root`, each with the skill it belongs to, in skill-name order
    (`language_neutral`: see lint_skill)."""
    return [(skill, finding) for skill in list_skills(root)
            for finding in lint_skill(skill, language_neutral=language_neutral)]


def render_check(root: Path) -> tuple[str, int]:
    """(report text, exit code) for --check."""
    skills = list_skills(root)
    findings = [finding for skill in skills for finding in lint_skill(skill)]
    lines = [f"{f.level:<5} {f.skill}: {f.message}" for f in findings]
    count, words, tokens = description_totals(skills)
    errors = sum(1 for f in findings if f.level == "ERROR")
    warnings = len(findings) - errors
    lines.append(f"TOTAL  {count} skills, {words} description words, ~{tokens} tokens "
                 "(estimate: ceil(characters / 4) over all descriptions)")
    lines.append(f"RESULT {errors} errors, {warnings} warnings")
    return "\n".join(lines), (1 if errors else 0)


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
    except (OSError, UnicodeDecodeError) as exc:
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
    parser.add_argument("--check", action="store_true",
                        help="lint every skill's description and body; exit 1 if there is an error")
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

    if args.check:
        text, code = render_check(root)
        print(text)
        return code

    print(render(root, args.name))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
