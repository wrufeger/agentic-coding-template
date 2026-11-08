"""Session start, orchestrator-only rules: the short form handed over while docs/ai/rules.md does not
import them.

Split out of session.py, which keeps the entry point and the order of the sub-steps."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .common import _check_mode

# ---------------------------------------------------------------------------
# Orchestrator-only rules (.act/rules/orchestrator/) — imported by docs/ai/rules.md
# like the shared ones (marked "main session only, workers skip this section"). The hook hands
# over a short form only as a fallback, while a locally changed docs/ai/rules.md does not import
# them yet. See the "Overrides" note on _read_rule_states for the docs/ai/rules.md syntax this
# reads.
# ---------------------------------------------------------------------------

_CHECKBOX_RE = re.compile(r"^\s*-\s*\[([ xX])\]\s*`(R-[\w-]+)`")
_OVERRIDE_RE = re.compile(r"^-?\s*replaces\s+`(R-[\w-]+)`\s*:\s*(.+)$", re.IGNORECASE)
_SECTION_HEADING_RE = re.compile(r"^##\s+(.*)$")
_RULE_ID_IN_TEXT_RE = re.compile(r"`(R-[\w-]+)`")


def _read_rule_states(root: Path) -> tuple[dict[str, bool], dict[str, str]]:
    """
    Parse docs/ai/rules.md (the project's own copy, generated from .act/bridges/rules.md and free
    to be hand-edited afterwards) for two things:

      - enabled: rule id -> False for every "- [ ] `R-id`" checkbox found anywhere in the file.
        A rule id never mentioned there at all is on by default, so a template update that adds a
        new rule takes effect without the project having to touch this file.
      - overrides: rule id -> replacement text, read from a line of the form
        "replaces `R-id`: <text>" (the skeleton ships this as an HTML-commented example under
        "## Overrides"; a real override is an uncommented line in that same shape, so any line
        starting with "<!--" is skipped here rather than matched).

    Returns ({}, {}) if the file is missing or unreadable — nothing found means nothing to filter
    on, not an error.
    """
    path = root / "docs" / "ai" / "rules.md"
    enabled: dict[str, bool] = {}
    overrides: dict[str, str] = {}
    if not path.is_file():
        return enabled, overrides
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return enabled, overrides

    for line in lines:
        checkbox_match = _CHECKBOX_RE.match(line)
        if checkbox_match:
            mark, rule_id = checkbox_match.groups()
            enabled[rule_id] = mark.strip().lower() == "x"
            continue
        stripped = line.strip()
        if stripped.startswith("<!--"):
            continue  # the skeleton's own placeholder example, never a real override
        override_match = _OVERRIDE_RE.match(stripped)
        if override_match:
            rule_id, text = override_match.groups()
            overrides[rule_id] = text.strip()
    return enabled, overrides


def _filter_orchestrator_file(
    text: str, enabled: dict[str, str], overrides: dict[str, str]
) -> tuple[str, int]:
    """
    Split one .act/rules/orchestrator/*.md file into its "## " sections. A section whose heading
    carries a `R-...` id (every actual rule) is dropped when that id is off in `enabled` and has
    no entry in `overrides`; if it has one, the override text replaces the section body. A
    section without an id in its heading (the file's title/intro, a plain reference passage such as
    "Role assignment" in 00-role.md) is never gated and always kept.

    Returns (filtered_text, rule_count): the filtered file, and how many gated sections survived
    (original or overridden) — the caller sums this across files for the status line.
    """
    lines = text.splitlines()
    kept: list[str] = []
    rule_count = 0

    section_lines: Optional[list[str]] = None
    section_rule_id: Optional[str] = None

    def _flush() -> None:
        nonlocal section_lines, section_rule_id, rule_count
        if section_lines is None:
            return
        if section_rule_id is None:
            kept.extend(section_lines)
        elif section_rule_id in overrides:  # a replacement wins, checked or not
            heading = section_lines[0] if section_lines else f"## `{section_rule_id}`"
            kept.append(f"{heading} (project override)")
            kept.append("")
            kept.append(overrides[section_rule_id])
            rule_count += 1
        elif enabled.get(section_rule_id, True):
            kept.extend(section_lines)
            rule_count += 1
        # else: off, no override on file -> section dropped entirely
        section_lines = None
        section_rule_id = None

    preamble: list[str] = []
    in_section = False
    for line in lines:
        heading_match = _SECTION_HEADING_RE.match(line)
        if heading_match:
            _flush()
            in_section = True
            section_lines = [line]
            id_match = _RULE_ID_IN_TEXT_RE.search(heading_match.group(1))
            section_rule_id = id_match.group(1) if id_match else None
            continue
        if in_section:
            section_lines.append(line)
        else:
            preamble.append(line)
    _flush()

    return "\n".join(preamble + kept).rstrip("\n") + "\n", rule_count


def _orchestrator_short_lines(
    text: str, enabled: dict[str, bool], overrides: dict[str, str], compact: bool = False
) -> tuple[list[str], int]:
    """One line per rule of one .act/rules/orchestrator/*.md file — its id and heading
    title (or the project's override text, shortened) — instead of the full text, which would
    swell the session-start output with rules that belong in an import (and past 10,000
    characters, Claude Code moves it into a file and shows only a 2,000-character preview). Same
    gating as _filter_orchestrator_file(). With
    `compact`, only the ids, comma-separated on one line. Returns (lines, rule_count)."""
    lines: list[str] = []
    ids: list[str] = []
    for heading in (m.group(1) for m in map(_SECTION_HEADING_RE.match, text.splitlines()) if m):
        id_match = _RULE_ID_IN_TEXT_RE.search(heading)
        if not id_match:
            continue
        rule_id = id_match.group(1)
        if rule_id in overrides:  # a replacement wins, checked or not
            override = overrides[rule_id]
            title = "(project override) " + (override if len(override) <= 90 else override[:89] + "…")
        elif enabled.get(rule_id, True):
            title = heading.split("—", 1)[1].strip() if "—" in heading else ""
        else:
            continue
        ids.append(rule_id)
        lines.append(f"- {rule_id}: {title}" if title else f"- {rule_id}")
    if compact and ids:
        lines = ["  " + ", ".join(ids)]
    return lines, len(ids)


def _orchestrator_rules_imported(reached: list[str]) -> bool:
    """True when docs/ai/rules.md already imports the orchestrator files — then
    Claude Code loads them in full and the hook adds nothing."""
    return any(path.startswith(".act/rules/orchestrator/") or path.startswith("docs/ai/local/rules/orchestrator/")
               for path in reached)


def _deliver_orchestrator_rules(root: Path, config: dict[str, str], compact: bool = False,
                                reached: Optional[list[str]] = None) -> Optional[int]:
    """
    Fallback only: normally docs/ai/rules.md imports the orchestrator rules and this prints
    nothing. While a locally changed docs/ai/rules.md does not import them, print a short form of
    .act/rules/orchestrator/*.md (ascending filename order, filtered through _read_rule_states,
    one line per rule, see _orchestrator_short_lines) plus where the full text lives — never the
    full text: that alone was 12 KB, past the 10,000 characters above which Claude Code moves a
    hook output into a file and shows the model only a 2,000-character preview.

    Returns None (and prints nothing) if the check is off or the directory does not exist yet.
    Prints nothing either, but returns the count, when `reached` (rules.resolve_imports) shows
    that docs/ai/rules.md imports the files itself. Otherwise the number of rules delivered (0 if
    every one was checked off), for the caller's status line. "block" and "warn" behave the same.
    """
    mode = _check_mode(config, "orchestrator-rules", default="block")
    if mode == "off":
        return None

    rules_dir = root / ".act" / "rules" / "orchestrator"
    if not rules_dir.is_dir():
        return None

    enabled, overrides = _read_rule_states(root)
    try:
        import act_profile  # deferred, see _active_topics
        cut_files = act_profile.read_cut(root).rules
    except Exception:  # noqa: BLE001
        cut_files = frozenset()
    total = 0
    blocks: list[str] = []
    for path in sorted(rules_dir.glob("*.md")):
        if f".act/rules/orchestrator/{path.name}" in cut_files:
            continue  # excluded by the scope (docs/ai/config.md § Scope)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        lines, count = _orchestrator_short_lines(text, enabled, overrides, compact=compact)
        total += count
        if count:
            blocks.append(f"{path.name}:")
            blocks.extend(lines)

    if blocks and not (reached and _orchestrator_rules_imported(reached)):
        form = "their ids only" if compact else "one line each"
        print(f"[act] orchestrator rules, main session only — docs/ai/rules.md does not import them "
              f"yet, so {form}; the binding text is in .act/rules/orchestrator/<file>, read it "
              "before acting on a rule:")
        print("\n".join(blocks))
    return total
