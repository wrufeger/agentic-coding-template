#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Resolve a role's tier/reasoning -- never a real model name anywhere else under .act/ --
#          into a concrete model alias/effort pair for one tool. Reads
#          .act/tiers.json (the template's tier -> model table) and docs/ai/config.md's
#          "## Roles" table (a project's own override; a filled-in model there wins over the tier
#          lookup entirely). Used by init.py/update.py when materializing/refreshing
#          .claude/agents/<name>.md (and its "-high" variant) -- and, with the `copilot` tool,
#          .github/agents/<name>.agent.md with a model priority list -- and by
#          .act/hooks/dispatch.py's session-start-refresh, which re-derives only the
#          `model`/`effort` frontmatter fields (Copilot: `model`/`models`/`reasoning-effort`) of an
#          already-existing bridge -- everything else in that file, including a project's own text
#          below the frontmatter, is left untouched.
#
# Usage: not run directly -- imported (`import tiers`) the same way actlib.py is, from a script in
#        .act/scripts/ or .act/hooks/ (both add their own directory to sys.path automatically).
#
# Output format: this module has no CLI output of its own; each function's return value is
#        documented at the function.

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

import actlib
import frontmatter


# ---------------------------------------------------------------------------
# Frontmatter: split / render, built on frontmatter.parse_frontmatter() (this used to
# be its own, separately-permissive regex/field parser; a project's own already-materialized file
# may carry a comment, a folded scalar (`description: >` plus continuation lines), or a YAML list
# (`tools:\n  - Read`), and the shared parser now reads those instead of silently dropping them.
# Safe for two things: reading a single known field back out (e.g. "tier"/"variant-of" below), and
# building a *brand-new* .claude/agents/<name>.md from a .act/bridges/agents/<name>.md template,
# which this project authors and keeps single-line on purpose. A file whose frontmatter the parser
# cannot read with confidence (frontmatter.ParseResult.ok is False -- an opener that never closes,
# or a line that is neither "key: value", quoted, a block-scalar/continuation line, nor blank) is
# treated the same as "no frontmatter block at all": ({}, text, []) -- this module never aborts a
# session start over a malformed file, it just leaves that file's model/effort unresolved (see
# refresh_project_bridge_frontmatter() further down). Refreshing an already-materialized file's
# `model`/`effort` never goes through here at all -- see _apply_resolved_fields() further down,
# which rewrites those two lines in place instead, byte for byte, without a structured re-parse.
# ---------------------------------------------------------------------------


def split_frontmatter(text: str) -> tuple[dict[str, str], str, list[str]]:
    """Split a bridge/role file into (fields, body, field_order). `fields` maps each frontmatter
    key to its raw value; `field_order` is the keys in the order they appeared, so a rewrite can
    keep it. Returns ({}, text, []) if `text` has no "---\\n...\\n---\\n" block at all, or one the
    shared parser could not read with confidence -- callers treat both the same, as "nothing to
    resolve here", not an error (frontmatter.parse_frontmatter()'s docstring)."""
    result = frontmatter.parse_frontmatter(text)
    if not result.ok:
        return {}, text, []
    return result.fields, result.body, result.order


def render_frontmatter(fields: dict[str, str], order: list[str], body: str) -> str:
    """Inverse of split_frontmatter: `order` (a key may appear at most once) with each key's
    current value from `fields` (a key in `order` but missing from `fields` is dropped). A value
    that needs quoting to read back as the same value (frontmatter.quote_value() -- e.g. one
    containing ": ", since split_frontmatter() only ever hands back the quote-stripped value) is
    quoted again here; a plain value that never needed quoting is written exactly as before
    (a review found that writing every value back unquoted produced invalid YAML,
    e.g. description: "Use when: a thing" turning into an unquoted "description: Use when: a
    thing")."""
    lines = ["---"]
    for key in order:
        if key in fields:
            lines.append(f"{key}: {frontmatter.quote_value(fields[key])}")
    lines.append("---")
    return "\n".join(lines) + "\n" + body


def render_generated_bridge(bridge_text: str, model: str, effort: Optional[str]) -> str:
    """Build a .claude/agents/<name>.md's initial content from its .act/bridges/agents/<name>.md
    template: same frontmatter fields in the same order, except "tier" becomes "model" in place
    and "reasoning" becomes "effort" right after it (dropped entirely if `effort` is falsy) -- the
    body below the frontmatter (the "Apply the rules from ..." line plus any template text below
    it) is copied verbatim."""
    fields, body, order = split_frontmatter(bridge_text)
    new_fields = {k: v for k, v in fields.items() if k not in ("tier", "reasoning")}
    new_fields["model"] = model
    if effort:
        new_fields["effort"] = effort
    new_order: list[str] = []
    for key in order:
        if key == "tier":
            new_order.append("model")
        elif key == "reasoning":
            if effort:
                new_order.append("effort")
        else:
            new_order.append(key)
    if "model" not in new_order:
        new_order.append("model")
    return render_frontmatter(new_fields, new_order, body)


# Claude Code tool names of a role bridge -> the tool aliases a Copilot agent file takes (compared
# without regard to case); a name not listed here is written unchanged.
_COPILOT_TOOL_ALIASES: dict[str, str] = {
    "bash": "execute", "shell": "execute", "powershell": "execute",
    "read": "read", "notebookread": "read",
    "edit": "edit", "multiedit": "edit", "write": "edit", "notebookedit": "edit",
    "grep": "search", "glob": "search",
    "task": "agent",
    "websearch": "web", "webfetch": "web",
    "todowrite": "todo",
}

COPILOT_AGENT_SUFFIX = ".agent.md"


def copilot_tool_names(value: str) -> list[str]:
    """The `tools` value of a role bridge (a comma list, a `[a, b]` flow list or a `- a` block list
    folded to one line by the frontmatter parser) as Copilot tool aliases: each name mapped through
    the alias table, in the order of first appearance, without duplicates; an unknown name stays."""
    text = value.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    if re.match(r"^-\s", text) or re.search(r"\s-\s", text):
        parts = [piece for piece in re.split(r"(?:^|\s)-\s+", text) if piece.strip()]
    else:
        parts = text.split(",")
    names: list[str] = []
    for part in parts:
        name = part.strip().strip("'\"").strip()
        if not name:
            continue
        mapped = _COPILOT_TOOL_ALIASES.get(name.lower(), name)
        if mapped not in names:
            names.append(mapped)
    return names


def render_generated_copilot_bridge(
    bridge_text: str, models: list[str], effort: Optional[str], variant_of: Optional[str] = None,
) -> str:
    """Build a .github/agents/<name>.agent.md's initial content from a role bridge (a template one
    under .act/bridges/agents/ or a project's own role file): the bridge's frontmatter keys in their
    order, `tier` becoming `model` (the first of `models`), `models` and `model-policy: preferred`,
    `reasoning` becoming `reasoning-effort` (left out when `effort` is falsy), `tools` mapped to
    Copilot's aliases and followed by `strict-tools-list: true` (no `tools` in the bridge: neither),
    `include-custom-instructions: true` last; every other key of the bridge (`effort`, `omitClaudeMd`,
    `model`, ...) is dropped. With no `models` (a bridge without `tier` and no Copilot cell) the
    model keys and `reasoning-effort` are left out. `variant_of` (a role name) makes the file that
    role's "-high" variant: `name` becomes `<role>-high`, `variant-of: <role>` follows it and the
    description is reworded. The body below the frontmatter is copied verbatim."""
    fields, body, order = split_frontmatter(bridge_text)
    model_lines: list[str] = []
    if models:
        model_lines = [
            f"model: {frontmatter.quote_value(models[0])}",
            f"models: {json.dumps(models)}",
            "model-policy: preferred",
        ]
        if effort:
            model_lines.append(f"reasoning-effort: {effort}")
    # the model block sits where `tier` stood; a bridge without one gets it after its description
    anchor = "tier" if "tier" in order else next((k for k in ("description", "name") if k in order), "")
    lines = ["---"]
    emitted = False
    for key in order:
        if key not in fields:
            continue
        if key == "name":
            value = f"{variant_of}-high" if variant_of else fields[key]
            lines.append(f"name: {frontmatter.quote_value(value)}")
            if variant_of:
                lines.append(f"variant-of: {variant_of}")
        elif key == "description":
            value = (f"Same as {variant_of}, one reasoning step higher - use only when named explicitly."
                     if variant_of else fields[key])
            lines.append(f"description: {frontmatter.quote_value(value)}")
        elif key == "tools":
            lines.append(f"tools: {json.dumps(copilot_tool_names(fields[key]))}")
            lines.append("strict-tools-list: true")
        if key == anchor and not emitted:
            lines.extend(model_lines)
            emitted = True
    if not emitted:
        lines.extend(model_lines)
    lines.append("include-custom-instructions: true")
    lines.append("---")
    return "\n".join(lines) + "\n" + body


# ---------------------------------------------------------------------------
# .act/tiers.json
# ---------------------------------------------------------------------------

def load_tiers(root: Path) -> dict:
    """Read .act/tiers.json. Returns {} if it is missing or not valid JSON -- callers then treat
    every tier as unresolvable (§ 2: a tool with no researched mapping is left alone, never
    guessed)."""
    path = root / ".act" / "tiers.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


# A reasoning value that means "no effort line, the tool's own default". `default` is the current
# spelling; `none` is read the same way (an older project file may still carry it) and an empty
# value says nothing at all.
NO_EFFORT_VALUES = ("", "default", "none")


def no_effort(value: str) -> bool:
    """True when `value` asks for no effort line (`default`, the older `none`, or empty)."""
    return (value or "").strip() in NO_EFFORT_VALUES


def reasoning_default(tool_data: Optional[dict]) -> str:
    """The scale level a `default` reasoning counts as for a bump (`reasoning_default` in the
    tool's table of .act/tiers.json); empty when the table names none."""
    return str((tool_data or {}).get("reasoning_default") or "")


def bump(scale: list[str], value: str, steps: int = 1, start: str = "") -> str:
    """One step up `scale` from `value`, capped at the last entry. A `value` that asks for no effort
    line (`default`, `none`, empty) counts as `start` when that is on the scale. `value` not found
    in `scale` (or an empty scale) is returned unchanged."""
    if no_effort(value) and start in scale:
        value = start
    if not scale or value not in scale:
        return value
    index = min(scale.index(value) + steps, len(scale) - 1)
    return scale[index]


# A tool whose table moved to a new name: a lookup for the key finds the table under the old name
# when the new one is missing (a project's own .act/tiers.json from before the rename).
_TOOL_TABLE_FALLBACKS: dict[str, str] = {"copilot": "copilot-cli"}


def tool_table(tiers_data: dict, tool: str) -> Optional[dict]:
    """The table of `tool` in `tiers_data`, or None when there is none. For `copilot` an entry
    named `copilot-cli` answers when `copilot` is missing. Every reader of the table goes through
    here."""
    data = tiers_data.get(tool)
    if data is None and tool in _TOOL_TABLE_FALLBACKS:
        data = tiers_data.get(_TOOL_TABLE_FALLBACKS[tool])
    return data if isinstance(data, dict) else None


def tier_models(entry: dict) -> list[str]:
    """The model list of one tier entry: its `models` (a priority list, first available wins) or
    else its single `model`; empty when it has neither."""
    models = entry.get("models")
    if isinstance(models, list):
        listed = [str(m) for m in models if str(m).strip()]
        if listed:
            return listed
    model = entry.get("model")
    return [str(model)] if model else []


def resolve_tier_models(
    tiers_data: dict, tool: str, tier: str, reasoning: str
) -> tuple[list[str], Optional[str], Optional[str]]:
    """Like resolve_tier(), but with the tier's whole model list (`models`, else `[model]`):
    ([model, ...], effort_or_None, problem_or_None); the list is empty whenever `problem` is set
    and for the silent cases named at resolve_tier()."""
    tool_data = tool_table(tiers_data, tool)
    if tool_data is None:
        return [], None, ("tool" if tiers_data else None)
    tiers_table = tool_data.get("tiers") or {}
    entry = tiers_table.get(tier)
    if not entry:
        return [], None, ("tier" if tiers_table else None)
    models = tier_models(entry)
    scale = tool_data.get("reasoning_scale") or []
    if not no_effort(reasoning) and scale and reasoning not in scale:
        return [], None, "reasoning"
    value = reasoning if (reasoning in scale or not scale) else ""
    if entry.get("bump_reasoning"):
        value = bump(scale, value, 1, reasoning_default(tool_data))
    if no_effort(value):
        return models, None, None
    return models, value, None


def resolve_tier(
    tiers_data: dict, tool: str, tier: str, reasoning: str
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(model_alias, effort_or_None, problem_or_None) for one (tier, reasoning) pair under `tool`.
    `problem` distinguishes three *reportable* reasons the pair could not be resolved from the one
    *silent, documented* reason (see .act/tiers.json's own
    "_comment"): a tool present in tiers.json with an empty "tiers" table has deliberately no
    researched mapping yet, so (None, None, None) there is normal, not a bug -- callers leave the
    role's existing model/effort untouched without telling anyone.

    - "tool": `tool` has no entry in `tiers_data` at all (a tool tiers.json never heard of, unlike
      the researched-but-empty case above).
    - "tier": `tool` is configured, but `tier` is not one of its known tiers (e.g. a typo).
    - "reasoning": `tier` resolved fine, but `reasoning` is non-empty, not `default`/"none", and not one of
      the tool's `reasoning_scale` values -- previously this silently fell back to the scale's
      first entry instead of being reported, which is the bug this case exists to prevent."""
    models, effort, problem = resolve_tier_models(tiers_data, tool, tier, reasoning)
    return (models[0] if models else None), effort, problem


# ---------------------------------------------------------------------------
# docs/ai/config.md § Roles -- the project's own override
# ---------------------------------------------------------------------------

_MODEL_VALUE_RE = re.compile(r"^[A-Za-z0-9._:\[\]=-]+$")
# one entry of the Roles table's Copilot cell: the same shape plus "/" (a provider/id of a BYOK model)
_COPILOT_MODEL_RE = re.compile(r"^[A-Za-z0-9._:/\[\]=-]+$")
ROLES_MARK_RE = re.compile(r"^<!--\s*act:roles\s*-->$")


def read_role_overrides(root: Path, notes: Optional[list[str]] = None) -> dict[str, dict[str, Any]]:
    """Parse the "## Roles" table in docs/ai/config.md: role name (backticks stripped) ->
    {"tier": ..., "reasoning": ..., "model": ..., "copilot": [...]} for whichever of the cells is
    non-empty. The optional fifth cell (`Copilot`) is a comma-separated priority list of Copilot
    model IDs, result key `copilot` (a list of strings): each entry loses its backticks and
    whitespace, empty entries fall away, and every entry must match `[A-Za-z0-9._:/\\[\\]=-]+`
    (a provider/id of a BYOK model too) or the whole cell is rejected with a note, like `model`.
    A table with four columns stays valid.
    A role not mentioned there at all is simply absent from the result. Robust against a missing
    file or an empty/header-only table -- returns {} rather than raising.

    A fixed `model` cell is only accepted if it looks like a model alias/ID
    (`[A-Za-z0-9._:\\[\\]=-]+`, the same shape every entry in .act/tiers.json itself uses) --
    anything else (whitespace, punctuation, a stray shell/YAML metacharacter) is rejected and left
    out of the result instead of ever reaching a `model:` frontmatter line unescaped; a rejection
    is appended to `notes` when a list is given."""
    path = root / "docs" / "ai" / "config.md"
    if not path.is_file():
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return {}

    # The section is found by its `<!-- act:roles -->` mark, so a translated heading still works
    # (R-work-language); the English heading remains the fallback for a config.md without the mark.
    # The table's header row is skipped by shape (a separator row follows it), never by its words.
    in_roles = False
    result: dict[str, dict[str, Any]] = {}
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("## "):
            in_roles = stripped[3:].strip().lower() == "roles"
            continue
        if ROLES_MARK_RE.match(stripped):
            in_roles = True
            continue
        if not in_roles or not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [c.strip() for c in stripped[1:-1].split("|")]
        if len(cells) < 4:
            continue
        role = cells[0].strip("`").strip()
        if not role or set(role) <= {"-", ":"} or actlib._is_header_row(lines, index):
            continue
        entry: dict[str, Any] = {}
        if cells[1].strip("`").strip():
            entry["tier"] = cells[1].strip("`").strip()
        if cells[2].strip("`").strip():
            entry["reasoning"] = cells[2].strip("`").strip()
        raw_model = cells[3].strip("`").strip()
        if raw_model:
            if _MODEL_VALUE_RE.match(raw_model):
                entry["model"] = raw_model
            elif notes is not None:
                notes.append(
                    f"docs/ai/config.md § Roles: model value for '{role}' rejected "
                    f"(unexpected characters), not applied: {raw_model!r}"
                )
        if len(cells) > 4:
            listed = [part.strip().strip("`").strip() for part in cells[4].split(",")]
            listed = [part for part in listed if part]
            if listed:
                if all(_COPILOT_MODEL_RE.match(part) for part in listed):
                    entry["copilot"] = listed
                elif notes is not None:
                    notes.append(
                        f"docs/ai/config.md § Roles: Copilot models for '{role}' rejected "
                        f"(unexpected characters), not applied: {cells[4]!r}"
                    )
        if entry:
            result[role] = entry
    return result


# ---------------------------------------------------------------------------
# Resolving one role's effective model/effort for one tool
# ---------------------------------------------------------------------------

def effective_model_effort(
    root: Path, role: str, template_tier: str, template_reasoning: str,
    tiers_data: dict, overrides: dict[str, dict[str, Any]], tool: str = "claude-code",
    bump_variant: bool = False,
) -> tuple[Optional[str], Optional[str], Optional[str], str, str]:
    """Resolve one role's `model`/`effort`/`problem`, override-first (docs/ai/config.md § Roles): a
    fixed `model` in config.md's Roles table wins outright over the tier lookup (and so is always
    fully resolved -- `problem` is always None on that path), but its `reasoning` still falls back
    to the template's own value when the override leaves that cell empty -- "fix the model alone,
    leave the reasoning tier unchanged" is a valid override on its own. Otherwise
    `tier`/`reasoning` (the override's value if given, else the template's) go through
    resolve_tier() -- see there for what `problem` means. `bump_variant=True` additionally bumps
    the resolved reasoning one step further, for a role's "-high" variant file (`root` is accepted
    for symmetry with the read_* helpers above and future per-role extensions; unused today).

    The trailing `(effective_tier, effective_reasoning)` pair is what was actually attempted --
    the override's own value where one was given, the template's otherwise, after any
    `bump_variant` step -- so a caller building a `describe_unresolved_tier()` message reports the
    value that actually caused `problem`, not just the template's default (which may itself be
    perfectly valid, e.g. an override that only replaces `reasoning` with a typo).

    For `tool="copilot"` the `model` cell does not apply (it is Claude Code's); the result is the
    first of effective_copilot_models()'s list."""
    if tool == "copilot":
        models, effort, problem, tier, reasoning = effective_copilot_models(
            root, role, template_tier, template_reasoning, tiers_data, overrides, bump_variant)
        return (models[0] if models else None), effort, problem, tier, reasoning
    tool_data = tool_table(tiers_data, tool) or {}
    scale = tool_data.get("reasoning_scale") or []
    start = reasoning_default(tool_data)
    override = overrides.get(role, {})

    if "model" in override:
        reasoning = override.get("reasoning", template_reasoning)
        if bump_variant:
            reasoning = bump(scale, reasoning, 1, start)
        effort = None if no_effort(reasoning) else reasoning
        return override["model"], effort, None, "", reasoning

    tier = override.get("tier", template_tier)
    reasoning = override.get("reasoning", template_reasoning)
    if bump_variant:
        reasoning = bump(scale, reasoning, 1, start)
    model, effort, problem = resolve_tier(tiers_data, tool, tier, reasoning)
    return model, effort, problem, tier, reasoning


def effective_copilot_models(
    root: Path, role: str, template_tier: str, template_reasoning: str,
    tiers_data: dict, overrides: dict[str, dict[str, Any]], bump_variant: bool = False,
) -> tuple[list[str], Optional[str], Optional[str], str, str]:
    """Like effective_model_effort() for the `copilot` tool, with a model priority list instead of one
    model: (models, effort, problem, effective_tier, effective_reasoning). A filled `Copilot` cell
    of the role's row in docs/ai/config.md § Roles wins outright over the tier lookup (`problem` is
    then None); its `reasoning` still falls back to the template's value. Without it
    `tier`/`reasoning` go through resolve_tier_models(); a tier with only a single `model` gives
    `[model]`. The `model` cell is Claude Code's and is ignored here. `bump_variant` bumps the
    reasoning one step further, for the role's "-high" file."""
    del root
    tool_data = tool_table(tiers_data, "copilot") or {}
    scale = tool_data.get("reasoning_scale") or []
    start = reasoning_default(tool_data)
    override = overrides.get(role, {})
    tier = override.get("tier", template_tier)
    reasoning = override.get("reasoning", template_reasoning)
    if bump_variant:
        reasoning = bump(scale, reasoning, 1, start)
    listed = override.get("copilot")
    if listed:
        effort = None if no_effort(reasoning) else reasoning
        return list(listed), effort, None, tier, reasoning
    models, effort, problem = resolve_tier_models(tiers_data, "copilot", tier, reasoning)
    return models, effort, problem, tier, reasoning


# ---------------------------------------------------------------------------
# Refreshing an already-materialized project bridge's model/effort fields
# ---------------------------------------------------------------------------

def role_bridge_names(root: Path) -> list[str]:
    """Every role name with both a .act/agents/<name>.md role file and a
    .act/bridges/agents/<name>.md bridge -- the same pairing rule init.py's
    agent_bridge_targets() uses."""
    agents_dir = root / ".act" / "agents"
    bridges_dir = root / ".act" / "bridges" / "agents"
    names = []
    if not agents_dir.is_dir():
        return names
    for role_path in sorted(agents_dir.glob("*.md")):
        if role_path.name.lower() == "readme.md":
            continue
        if (bridges_dir / role_path.name).is_file():
            names.append(role_path.stem)
    return names


_MODEL_LINE_RE = re.compile(r"^model:\s*")
_EFFORT_LINE_RE = re.compile(r"^effort:\s*")


def apply_resolved_fields(text: str, model: str, effort: Optional[str]) -> Optional[str]:
    """Public name of `_apply_resolved_fields` for the callers outside this module (the package load applies the same
    refresh step to a role file it writes): rewrites only the `model:` and `effort:` lines, None when nothing changes."""
    return _apply_resolved_fields(text, model, effort)


def _apply_resolved_fields(text: str, model: str, effort: Optional[str]) -> Optional[str]:
    """Rewrite only the `model:`/`effort:` *lines* of an already-frontmattered file's text --
    every other line (a comment, a folded-scalar continuation like `description: >` plus its
    indented follow-on lines, a YAML list like `tools:\\n  - Read`, a key with digits in it,
    anything at all) is left exactly as it is, byte for byte, including its own line terminator.
    This works purely line by line (never a structured re-parse of the whole frontmatter block the
    way split_frontmatter()/render_frontmatter() do above -- those lose any line that is not a
    single `key: value` pair, which is exactly the bug this function exists to avoid) -- a missing
    `model:`/`effort:` line is inserted right before the closing `---`, and an `effort:` line that
    must go away (falsy `effort`, but one was present before) is dropped outright, not blanked.

    Returns None if `text` has no opening "---" frontmatter fence at all (nothing to resolve) or
    the result would be byte-identical to `text` (nothing actually changed -- callers use this to
    decide whether a write is needed at all). Caller is responsible for reading/writing `text` with
    `newline=""` so the line terminators carried inside it (and so also in the return value) are
    the file's own, never translated by Python's universal-newlines handling."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return None
    close_index: Optional[int] = None
    for i in range(1, len(lines)):
        if lines[i].rstrip("\r\n") == "---":
            close_index = i
            break
    if close_index is None:
        return None

    opening_stripped = lines[0].rstrip("\r\n")
    eol = lines[0][len(opening_stripped):] or "\n"

    new_block: list[str] = []
    have_model = False
    have_effort = False
    for line in lines[1:close_index]:
        stripped = line.rstrip("\r\n")
        line_eol = line[len(stripped):]
        if _MODEL_LINE_RE.match(stripped):
            have_model = True
            new_block.append(f"model: {model}{line_eol}")
        elif _EFFORT_LINE_RE.match(stripped):
            have_effort = True
            if effort:
                new_block.append(f"effort: {effort}{line_eol}")
            # else: this line is dropped -- effort no longer applies to this role
        else:
            new_block.append(line)
    if not have_model:
        new_block.append(f"model: {model}{eol}")
    if effort and not have_effort:
        new_block.append(f"effort: {effort}{eol}")

    new_text = "".join(lines[:1] + new_block + lines[close_index:])
    return new_text if new_text != text else None


_COPILOT_MODEL_LINE_RE = re.compile(r"^model:\s*")
_COPILOT_MODELS_LINE_RE = re.compile(r"^models:\s*")
_COPILOT_POLICY_LINE_RE = re.compile(r"^model-policy:")
_COPILOT_EFFORT_LINE_RE = re.compile(r"^reasoning-effort:\s*")


# The cells of a Roles row that apply to each tool's bridges: `tier` and `reasoning` to both, the fixed
# `model` to Claude Code only, the `Copilot` model list to Copilot only.
TOOL_ROLE_CELLS: dict[str, tuple[str, ...]] = {
    "claude-code": ("tier", "reasoning", "model"),
    "copilot": ("tier", "reasoning", "copilot"),
}


def _is_continuation(line: str) -> bool:
    """Whether a frontmatter line continues the key line before it: indented, or a `- ` list item."""
    return line.startswith((" ", "\t", "- ")) or line.rstrip("\r\n") == "-"


def _apply_resolved_copilot_fields(
    text: str, models: list[str], effort: Optional[str], insert_missing: bool = False,
) -> Optional[str]:
    """The Copilot counterpart of _apply_resolved_fields(): rewrite only the `model:`, `models:` and
    `reasoning-effort:` lines of an already-frontmattered .agent.md text (`model` = the first of
    `models`, `models` a JSON-style list), every other line byte for byte with its own line
    terminator. The continuation lines of a replaced key (indented or `- ` lines, e.g. the items of a
    block list) go with it. A missing line of the three is inserted before the closing `---` (in
    that order), a `reasoning-effort:` line goes away when `effort` is falsy. A file with neither a
    `model:` nor a `models:` line is the project's own choice of model and returns None, like a file
    with no frontmatter fence or a result byte-identical to `text` -- unless `insert_missing` is
    set: then `model:`, `models:`, `model-policy: preferred` and `reasoning-effort:` (when `effort`)
    are inserted before the closing `---`. On a refresh, `model-policy: preferred` goes right after the
    `models:` line when `models` has more than one entry and the block has no `model-policy:` line; an
    existing one keeps its value."""
    if not models:
        return None
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        return None
    close_index = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r\n") == "---"), None)
    if close_index is None:
        return None
    eol = lines[0][len(lines[0].rstrip("\r\n")):] or "\n"
    block = [line.rstrip("\r\n") for line in lines[1:close_index]]
    if not any(_COPILOT_MODEL_LINE_RE.match(b) or _COPILOT_MODELS_LINE_RE.match(b) for b in block):
        if not insert_missing:
            return None
        added = [f"model: {frontmatter.quote_value(models[0])}", f"models: {json.dumps(models)}",
                 "model-policy: preferred"]
        if effort:
            added.append(f"reasoning-effort: {effort}")
        inserted = "".join(lines[:close_index] + [f"{line}{eol}" for line in added] + lines[close_index:])
        return inserted if inserted != text else None
    wanted = {
        "model": f"model: {frontmatter.quote_value(models[0])}",
        "models": f"models: {json.dumps(models)}",
        "effort": f"reasoning-effort: {effort}" if effort else "",
    }
    seen: set[str] = set()
    new_block: list[str] = []
    replacing = False  # the previous line was one of the three keys: its continuation lines go too
    for line in lines[1:close_index]:
        stripped = line.rstrip("\r\n")
        line_eol = line[len(stripped):]
        if replacing and _is_continuation(line):
            continue
        replacing = False
        for kind, pattern in (("model", _COPILOT_MODEL_LINE_RE), ("models", _COPILOT_MODELS_LINE_RE),
                              ("effort", _COPILOT_EFFORT_LINE_RE)):
            if pattern.match(stripped):
                seen.add(kind)
                replacing = True
                if wanted[kind]:
                    new_block.append(f"{wanted[kind]}{line_eol}")
                break
        else:
            new_block.append(line)
    for kind in ("model", "models", "effort"):
        if kind not in seen and wanted[kind]:
            new_block.append(f"{wanted[kind]}{eol}")
    if len(models) > 1 and not any(_COPILOT_POLICY_LINE_RE.match(b.rstrip("\r\n")) for b in new_block):
        # several models without a policy line: add the soft preference right after `models:`
        at = next((i for i, b in enumerate(new_block) if _COPILOT_MODELS_LINE_RE.match(b.rstrip("\r\n"))), None)
        if at is not None:
            new_block.insert(at + 1, f"model-policy: preferred{eol}")
    new_text = "".join(lines[:1] + new_block + lines[close_index:])
    return new_text if new_text != text else None


def _has_model_line(text: str) -> bool:
    """Whether the frontmatter of `text` has a `model:` or a `models:` line."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    for line in lines[1:]:
        if line.strip() == "---":
            return False
        if _COPILOT_MODEL_LINE_RE.match(line) or _COPILOT_MODELS_LINE_RE.match(line):
            return True
    return False


def copilot_files_without_model(root: Path) -> list[str]:
    """The files under .github/agents/ that carry the name of a template role or of its "-high"
    variant (`<name>.agent.md` or `<name>.md`) and have neither a `model:` nor a `models:` line:
    paths relative to `root`, `/`-separated, sorted. They are the project's own files, never
    changed by a refresh; update.py turns them into a question with a proposal. A file that cannot
    be read is left out."""
    agents_dir = root / ".github" / "agents"
    if not agents_dir.is_dir():
        return []
    names = set(role_bridge_names(root))
    names |= {f"{name}-high" for name in names}
    found: list[str] = []
    for path in sorted(agents_dir.iterdir()):
        if not path.is_file():
            continue
        if path.name.endswith(COPILOT_AGENT_SUFFIX):
            stem = path.name[: -len(COPILOT_AGENT_SUFFIX)]
        elif path.name.endswith(".md"):
            stem = path.name[: -len(".md")]
        else:
            continue
        if stem not in names:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if not _has_model_line(text):
            found.append(path.relative_to(root).as_posix())
    return found


def describe_unresolved_tier(role: str, tool: str, tier: str, reasoning: str, problem: str) -> str:
    """Human-readable `[act] note:` text for one of resolve_tier()'s reportable `problem` values."""
    if problem == "tool":
        return f"'{tool}' has no entry in .act/tiers.json -- role '{role}' left as it is"
    if problem == "tier":
        return f"role '{role}': tier '{tier}' is not known to '{tool}' in .act/tiers.json -- left as it is"
    return f"role '{role}': reasoning '{reasoning}' is not on '{tool}'s reasoning_scale in .act/tiers.json -- left as it is"


def package_role_files(root: Path, names: "set[str] | list[str]") -> "tuple[dict[str, Path], set[str]]":
    """For the template roles in `names` that an active package replaces (`pre-template/agents/<name>.md` in its
    folder under .act-local/packages/): (the package's file by role, the roles that cannot be read). The file then
    stands where the template's bridge stands for the role's tier and reasoning, so a refresh keeps the package's
    choice for the role and for its "-high" variant. Only a plain file of a plain folder whose hash is the one the
    lock records counts; the role of a package that is broken or whose folder is missing is in the second set, and a
    refresh leaves it as it is (what the package gave stays until the package is whole again). A package with no
    lock entry changes nothing. With two packages the later entry of the lock wins, as it does where the role's copy
    is written."""
    found: dict[str, Path] = {}
    frozen: set[str] = set()
    try:
        packages = actlib.read_packages(root)
    except (OSError, ValueError):
        return found, frozen
    for package_id, entry in packages.items():
        files = entry.get("files")
        if not isinstance(files, dict):
            continue
        folder = root / ".act-local" / "packages" / package_id
        for rel, recorded in files.items():
            parts = rel.split("/") if isinstance(rel, str) else []
            if len(parts) != 3 or parts[:2] != ["pre-template", "agents"] or not parts[2].endswith(".md") \
                    or parts[2][: -len(".md")] not in names or not isinstance(recorded, str):
                continue
            path = folder / rel
            role = parts[2][: -len(".md")]
            try:
                if any(actlib.is_redirect(os.lstat(p)) for p in (folder, folder / parts[0], folder / parts[0] / parts[1], path)):
                    frozen.add(role)
                elif actlib.lock_hash(path.read_bytes()) == recorded:
                    found[role] = path
                else:
                    frozen.add(role)
            except OSError:
                frozen.add(role)
    return found, frozen


def refresh_project_bridge_frontmatter(
    root: Path, tool: str = "claude-code", apply: bool = True, notes: Optional[list[str]] = None
) -> list[str]:
    """Re-derive the `model`/`effort` frontmatter of every already-materialized
    .claude/agents/*.md file -- a template role's base bridge and its "-high" variant alike, and a
    project's own role as long as it is named in docs/ai/config.md's "## Roles" table and has its
    own bridge file, per docs/ai/config.md § Roles -- from the current .act/tiers.json and that Roles table.
    Nothing else in any file is touched: not the rest of the frontmatter, never the body (see
    _apply_resolved_fields() above). A file this function cannot resolve (no template role and no
    Roles-table entry for it, or a tool with a deliberately unpopulated tiers.json entry -- see
    .act/tiers.json's own "_comment") is left exactly as it is, silently, same as always. A
    *reportable* reason it could not be resolved (resolve_tier()'s "tool"/"tier"/"reasoning"
    problems, e.g. a typo'd tier or reasoning value) instead appends one message to `notes` when a
    list is given (deduplicated -- the same problem is reported once, not once per role that hits
    it) — the file is still left exactly as it is either way.

    With `tool="copilot"` the same applies to .github/agents/*.agent.md and the lines `model:`,
    `models:` and `reasoning-effort:` (see _apply_resolved_copilot_fields()): the models come from
    the role's `Copilot` cell in docs/ai/config.md § Roles, else from the tier's list; a file with
    neither a `model:` nor a `models:` line is the project's own and stays untouched
    (copilot_files_without_model() names such files).

    Only a "-high" file the template itself generated as a bump of `base_role` -- marked with a
    `variant-of: <base_role>` frontmatter field at generation time, see init.py's
    write_agent_bridge_file() -- is treated as a variant here; a project's own role that merely
    happens to be named "...-high" without that field is resolved as its own, unrelated role (or
    left alone if it is not a template role and not in the Roles table either).

    A single file that cannot even be read/written (OSError, e.g. permission denied, or
    UnicodeDecodeError, e.g. a non-UTF-8 file) is skipped with a note, never aborts the run --
    every other file is still processed.

    With `apply=False` (dry run, used by dispatch.py's session-start-refresh under `warn`), nothing
    is written -- the returned list is what *would* change. Returns the list of
    .claude/agents/<name>.md (Copilot: .github/agents/<name>.agent.md) destinations
    (repo-root-relative, forward slashes) actually changed (or that would be, under `apply=False`)."""
    if tool not in ("claude-code", "copilot"):
        return []
    copilot = tool == "copilot"
    suffix = COPILOT_AGENT_SUFFIX if copilot else ".md"
    agents_dest_dir = root / (".github" if copilot else ".claude") / "agents"
    if not agents_dest_dir.is_dir():
        return []
    bridges_dir = root / ".act" / "bridges" / "agents"
    tiers_data = load_tiers(root)
    overrides = read_role_overrides(root, notes=notes)
    template_roles = {name: bridges_dir / f"{name}.md" for name in role_bridge_names(root)}
    frozen_roles: set[str] = set()
    if not copilot:  # a role an active package replaces keeps the package's tier and reasoning (Claude Code files only)
        replaced, frozen_roles = package_role_files(root, set(template_roles))
        template_roles.update(replaced)
        frozen_roles -= set(replaced)

    seen_notes: set[str] = set()

    def _note(message: str) -> None:
        if notes is not None and message not in seen_notes:
            seen_notes.add(message)
            notes.append(message)

    changed: list[str] = []
    for dest in sorted(agents_dest_dir.glob(f"*{suffix}")):
        stem = dest.name[: -len(suffix)]
        if not stem or stem.lower() == "readme":
            continue
        rel = dest.relative_to(root).as_posix()

        try:
            with open(dest, encoding="utf-8", newline="") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as exc:
            _note(f"{rel}: skipped, could not read ({exc.__class__.__name__})")
            continue

        dest_fields, _, _ = split_frontmatter(text)
        is_variant = stem.endswith("-high") and dest_fields.get("variant-of") == stem[: -len("-high")]
        base_role = stem[: -len("-high")] if is_variant else stem

        if base_role in frozen_roles:
            continue  # the package that replaces this role is not whole: its file stays as it is
        if base_role in template_roles:
            try:
                tmpl_fields, _, _ = split_frontmatter(template_roles[base_role].read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError) as exc:
                _note(f"{template_roles[base_role].relative_to(root).as_posix()}: skipped, could not read "
                      f"({exc.__class__.__name__}); role '{base_role}' left as it is")
                continue
            if "tier" not in tmpl_fields and not (copilot and overrides.get(base_role, {}).get("copilot")):
                continue  # older (or hand-authored) bridge with a fixed model already
            template_tier = tmpl_fields.get("tier", "")
            template_reasoning = tmpl_fields.get("reasoning", "")
        elif any(c in overrides.get(base_role, {}) for c in TOOL_ROLE_CELLS[tool]):
            template_tier, template_reasoning = "", ""
        else:
            continue  # nothing to resolve this role's fields from

        if copilot:
            models, effort, problem, eff_tier, eff_reasoning = effective_copilot_models(
                root, base_role, template_tier, template_reasoning, tiers_data, overrides, is_variant,
            )
            if not models:
                if problem:
                    _note(describe_unresolved_tier(base_role, tool, eff_tier, eff_reasoning, problem))
                continue
            # an own role's file written without model lines (it had no tier) gets them once its row
            # carries a Copilot cell; a template role's file without them stays the project's choice
            own_role = base_role not in template_roles and bool(overrides.get(base_role, {}).get("copilot"))
            new_text = _apply_resolved_copilot_fields(text, models, effort, insert_missing=own_role)
        else:
            model, effort, problem, eff_tier, eff_reasoning = effective_model_effort(
                root, base_role, template_tier, template_reasoning, tiers_data, overrides,
                tool=tool, bump_variant=is_variant,
            )
            if model is None:
                if problem:
                    _note(describe_unresolved_tier(base_role, tool, eff_tier, eff_reasoning, problem))
                continue
            new_text = _apply_resolved_fields(text, model, effort)
        if new_text is None:
            continue
        if apply:
            try:
                with open(dest, "w", encoding="utf-8", newline="") as f:
                    f.write(new_text)
            except OSError as exc:
                _note(f"{rel}: skipped, could not write ({exc.__class__.__name__})")
                continue
        changed.append(rel)

    return changed


# ---------------------------------------------------------------------------
# A skill's own reasoning level -> the tool's reasoning field in the skill copy
# ---------------------------------------------------------------------------

_SKILL_REASONING_LINE_RE = re.compile(r"^reasoning:\s*(.*?)\s*$")


def skill_copy_text(
    text: str, skill: str, tool: str, tiers_data: dict, overrides: dict[str, dict[str, Any]],
) -> str:
    """The text of one skill's SKILL.md as it is written for `tool`: the source's `reasoning: <level>`
    frontmatter line (a value of the tool's `reasoning_scale`) is replaced by the tool's own field
    (`reasoning_field` in .act/tiers.json, Claude Code: `effort`). A row naming the skill in
    docs/ai/config.md § Roles (`overrides[skill]["reasoning"]`) wins over the source's own value. No
    level at all, a level that is `default`, "none" or not on the scale, or a tool with an empty
    `reasoning_field` (no researched mapping) leaves the text exactly as it is -- including the source
    `reasoning` line in the last two cases -- so the skill simply inherits the session's setting.
    Line terminators and every other line are kept byte for byte; an `effort:` line the source carries
    itself is replaced only when a level resolves."""
    tool_data = tool_table(tiers_data, tool) or {}
    field = tool_data.get("reasoning_field") or ""
    scale = tool_data.get("reasoning_scale") or []
    lines = text.splitlines(keepends=True)
    if not field or not scale or not lines or lines[0].rstrip("\r\n") != "---":
        return text
    close_index = next((i for i in range(1, len(lines)) if lines[i].rstrip("\r\n") == "---"), None)
    if close_index is None:
        return text

    source_level = ""
    for line in lines[1:close_index]:
        match = _SKILL_REASONING_LINE_RE.match(line.rstrip("\r\n"))
        if match:
            source_level = match.group(1).strip("'\"")
    level = (overrides.get(skill) or {}).get("reasoning") or source_level
    if no_effort(level) or level not in scale:
        return text

    eol = lines[0][len(lines[0].rstrip("\r\n")):] or "\n"
    field_re = re.compile(rf"^{re.escape(field)}:\s*")
    block: list[str] = []
    have_field = False
    for line in lines[1:close_index]:
        stripped = line.rstrip("\r\n")
        if _SKILL_REASONING_LINE_RE.match(stripped):
            continue
        if field_re.match(stripped):
            have_field = True
            block.append(f"{field}: {level}{line[len(stripped):]}")
        else:
            block.append(line)
    if not have_field:
        block.append(f"{field}: {level}{eol}")
    return "".join(lines[:1] + block + lines[close_index:])
