#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Resolve a role's tier/reasoning -- never a real model name anywhere else under .act/ --
#          into a concrete model alias/effort pair for one tool. Reads
#          .act/tiers.json (the template's tier -> model table) and docs/ai/config.md's
#          "## Roles" table (a project's own override; a filled-in model there wins over the tier
#          lookup entirely). Used by init.py/update.py when materializing/refreshing
#          .claude/agents/<name>.md (and its "-high" variant) and by .act/hooks/dispatch.py's session-start-refresh, which re-derives only the
#          `model`/`effort` frontmatter fields of an already-existing bridge -- everything else in
#          that file, including a project's own text below the frontmatter, is left untouched.
#
# Usage: not run directly -- imported (`import tiers`) the same way actlib.py is, from a script in
#        .act/scripts/ or .act/hooks/ (both add their own directory to sys.path automatically).
#
# Output format: this module has no CLI output of its own; each function's return value is
#        documented at the function.

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

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


def bump(scale: list[str], value: str, steps: int = 1) -> str:
    """One step up `scale` from `value`, capped at the last entry. `value` not found in `scale`
    (or an empty scale) is returned unchanged."""
    if not scale or value not in scale:
        return value
    index = min(scale.index(value) + steps, len(scale) - 1)
    return scale[index]


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
    - "reasoning": `tier` resolved fine, but `reasoning` is non-empty, not "none", and not one of
      the tool's `reasoning_scale` values -- previously this silently fell back to the scale's
      first entry instead of being reported, which is the bug this case exists to prevent."""
    tool_data = tiers_data.get(tool)
    if tool_data is None:
        return None, None, ("tool" if tiers_data else None)
    tiers_table = tool_data.get("tiers") or {}
    entry = tiers_table.get(tier)
    if not entry:
        return None, None, ("tier" if tiers_table else None)
    model = entry.get("model")
    scale = tool_data.get("reasoning_scale") or []
    if reasoning and reasoning != "none" and scale and reasoning not in scale:
        return None, None, "reasoning"
    value = reasoning if reasoning in scale else (scale[0] if scale else reasoning)
    if entry.get("bump_reasoning"):
        value = bump(scale, value, 1)
    if not value or value == "none":
        return model, None, None
    return model, value, None


# ---------------------------------------------------------------------------
# docs/ai/config.md § Roles -- the project's own override
# ---------------------------------------------------------------------------

_MODEL_VALUE_RE = re.compile(r"^[A-Za-z0-9._:\[\]=-]+$")
ROLES_MARK_RE = re.compile(r"^<!--\s*act:roles\s*-->$")


def read_role_overrides(root: Path, notes: Optional[list[str]] = None) -> dict[str, dict[str, str]]:
    """Parse the "## Roles" table in docs/ai/config.md: role name (backticks stripped) ->
    {"tier": ..., "reasoning": ..., "model": ...} for whichever of the three cells is non-empty.
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
    result: dict[str, dict[str, str]] = {}
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
        entry: dict[str, str] = {}
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
        if entry:
            result[role] = entry
    return result


# ---------------------------------------------------------------------------
# Resolving one role's effective model/effort for one tool
# ---------------------------------------------------------------------------

def effective_model_effort(
    root: Path, role: str, template_tier: str, template_reasoning: str,
    tiers_data: dict, overrides: dict[str, dict[str, str]], tool: str = "claude-code",
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
    perfectly valid, e.g. an override that only replaces `reasoning` with a typo)."""
    del root
    scale = (tiers_data.get(tool) or {}).get("reasoning_scale") or []
    override = overrides.get(role, {})

    if "model" in override:
        reasoning = override.get("reasoning", template_reasoning)
        if bump_variant:
            reasoning = bump(scale, reasoning, 1)
        effort = reasoning if reasoning and reasoning != "none" else None
        return override["model"], effort, None, "", reasoning

    tier = override.get("tier", template_tier)
    reasoning = override.get("reasoning", template_reasoning)
    if bump_variant:
        reasoning = bump(scale, reasoning, 1)
    model, effort, problem = resolve_tier(tiers_data, tool, tier, reasoning)
    return model, effort, problem, tier, reasoning


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


def describe_unresolved_tier(role: str, tool: str, tier: str, reasoning: str, problem: str) -> str:
    """Human-readable `[act] note:` text for one of resolve_tier()'s reportable `problem` values."""
    if problem == "tool":
        return f"'{tool}' has no entry in .act/tiers.json -- role '{role}' left as it is"
    if problem == "tier":
        return f"role '{role}': tier '{tier}' is not known to '{tool}' in .act/tiers.json -- left as it is"
    return f"role '{role}': reasoning '{reasoning}' is not on '{tool}'s reasoning_scale in .act/tiers.json -- left as it is"


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
    .claude/agents/<name>.md destinations (repo-root-relative, forward slashes) actually changed
    (or that would be, under `apply=False`)."""
    if tool != "claude-code":
        return []
    agents_dest_dir = root / ".claude" / "agents"
    if not agents_dest_dir.is_dir():
        return []
    bridges_dir = root / ".act" / "bridges" / "agents"
    tiers_data = load_tiers(root)
    overrides = read_role_overrides(root, notes=notes)
    template_roles = {name: bridges_dir / f"{name}.md" for name in role_bridge_names(root)}

    seen_notes: set[str] = set()

    def _note(message: str) -> None:
        if notes is not None and message not in seen_notes:
            seen_notes.add(message)
            notes.append(message)

    changed: list[str] = []
    for dest in sorted(agents_dest_dir.glob("*.md")):
        if dest.stem.lower() == "readme":
            continue
        stem = dest.stem
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

        if base_role in template_roles:
            try:
                tmpl_fields, _, _ = split_frontmatter(template_roles[base_role].read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError) as exc:
                _note(f"{template_roles[base_role].relative_to(root).as_posix()}: skipped, could not read "
                      f"({exc.__class__.__name__}); role '{base_role}' left as it is")
                continue
            if "tier" not in tmpl_fields:
                continue  # older (or hand-authored) bridge with a fixed model already
            template_tier = tmpl_fields.get("tier", "")
            template_reasoning = tmpl_fields.get("reasoning", "")
        elif base_role in overrides:
            template_tier, template_reasoning = "", ""
        else:
            continue  # nothing to resolve this role's fields from

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
    text: str, skill: str, tool: str, tiers_data: dict, overrides: dict[str, dict[str, str]],
) -> str:
    """The text of one skill's SKILL.md as it is written for `tool`: the source's `reasoning: <level>`
    frontmatter line (a value of the tool's `reasoning_scale`) is replaced by the tool's own field
    (`reasoning_field` in .act/tiers.json, Claude Code: `effort`). A row naming the skill in
    docs/ai/config.md § Roles (`overrides[skill]["reasoning"]`) wins over the source's own value. No
    level at all, a level that is "none" or not on the scale, or a tool with an empty
    `reasoning_field` (no researched mapping) leaves the text exactly as it is -- including the source
    `reasoning` line in the last two cases -- so the skill simply inherits the session's setting.
    Line terminators and every other line are kept byte for byte; an `effort:` line the source carries
    itself is replaced only when a level resolves."""
    tool_data = tiers_data.get(tool) or {}
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
    if not level or level == "none" or level not in scale:
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
