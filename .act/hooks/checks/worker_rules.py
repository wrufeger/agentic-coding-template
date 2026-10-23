"""SubagentStart: hand a worker the rules that apply to it, in place of CLAUDE.md.

The template's roles carry `omitClaudeMd: true` in their frontmatter, so Claude Code does not load
CLAUDE.md for them — which spares every worker start the orchestrator rules (.act/rules/orchestrator/).
This module gives such a worker what CLAUDE.md would have loaded, minus those orchestrator imports
(scripts/rules.py, worker_rule_parts()). dispatch.py calls it once per fixed hook entry
(`dispatch.py SubagentStart --worker-rules <i>`), each entry printing part <i> as one
hookSpecificOutput.additionalContext string: Claude Code moves a single string over 10,000 characters
into a file and shows a short preview only, so the text is cut into parts of at most 9,500
characters (rules.WORKER_PART_LIMIT); the last entry carries any remainder.

Delivered only when the role file of the started `agent_type` (.claude/agents/<type>.md in the project,
else ~/.claude/agents/<type>.md) says `omitClaudeMd: true`. A role without the field loads CLAUDE.md
itself and must not get the rules twice. Any failure prints one fixed sentence (first entry only)
telling the worker to read the shared rules itself, and never makes the hook fail: SubagentStart
blocks nothing.
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

__all__ = ["emit", "role_omits_claude_md"]

_ROLE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
# Read as YAML does: the key is case-sensitive, a ` #` comment after the value is dropped.
_OMIT_LINE = re.compile(r"^omitClaudeMd\s*:\s*(?P<value>[^\s#]+)\s*(?:#.*)?$")
_NAME_LINE = re.compile(r"^name\s*:\s*(?P<value>[^#]+?)\s*(?:#.*)?$")


def _project_root(payload: dict) -> Path:
    import actlib
    for candidate in (os.environ.get("CLAUDE_PROJECT_DIR"), payload.get("cwd")):
        if candidate:
            try:
                return actlib.repo_root(Path(candidate))
            except RuntimeError:
                continue
    return actlib.repo_root()


def _frontmatter_lines(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").lstrip("﻿").splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    out: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        out.append(line)
    return out


def _frontmatter_says_omit(path: Path) -> bool:
    for line in _frontmatter_lines(path):
        match = _OMIT_LINE.match(line)
        if match:
            return match.group("value").strip("\"'").lower() == "true"
    return False


def _role_file(base: Path, agent_type: str) -> Optional[Path]:
    """`<type>.md` in `base`, else the file whose frontmatter `name:` is the type — Claude Code
    goes by the name field, not the file name."""
    path = base / f"{agent_type}.md"
    if path.is_file():
        return path
    if not base.is_dir():
        return None
    for candidate in sorted(base.glob("*.md")):
        for line in _frontmatter_lines(candidate):
            match = _NAME_LINE.match(line)
            if match:
                if match.group("value").strip("\"'") == agent_type:
                    return candidate
                break
    return None


def role_omits_claude_md(agent_type: str, root: Path, home: Path) -> bool:
    """Whether the role file of `agent_type` carries `omitClaudeMd: true`: the project's
    .claude/agents/<type>.md, else the user's. A type that is not a plain file name (a plugin
    prefix, a path) has no role file of ours."""
    if not _ROLE_NAME.match(agent_type):
        return False
    for base in (root / ".claude" / "agents", home / ".claude" / "agents"):
        path = _role_file(base, agent_type)
        if path is not None:
            return _frontmatter_says_omit(path)
    return False


def _print_context(text: str) -> None:
    sys.stdout.write(json.dumps(
        {"hookSpecificOutput": {"hookEventName": "SubagentStart", "additionalContext": text}},
        ensure_ascii=False) + "\n")


def emit(part: int, payload: dict) -> None:
    """Print part number `part` (1-based) for the started worker, or nothing. Never raises."""
    try:
        import rules
        agent_type = str(payload.get("agent_type") or "")
        if not agent_type:
            return
        root = _project_root(payload)
        home = Path.home()
        if not role_omits_claude_md(agent_type, root, home):
            return
        parts = rules.worker_rule_parts(root, home)
        if part >= rules.WORKER_PARTS:   # the last entry takes whatever is left
            text = "\n".join(item.text for item in parts[part - 1:])
        else:
            text = parts[part - 1].text if part - 1 < len(parts) else ""
        if text:
            _print_context(text)
    except Exception:  # noqa: BLE001 — a hook never ends in a traceback; SubagentStart blocks nothing
        _fallback(part)


def _fallback(part: int) -> None:
    if part != 1:
        return
    try:
        sentence: Optional[str] = None
        try:
            import rules
            sentence = rules.WORKER_RULES_FALLBACK
        except Exception:  # noqa: BLE001
            pass
        _print_context(sentence or (
            "Worker rules could not be assembled: read CLAUDE.md, docs/ai/rules.md and the files it "
            "imports from .act/rules/shared/ before your first step; skip .act/rules/orchestrator/."))
    except Exception:  # noqa: BLE001
        pass
