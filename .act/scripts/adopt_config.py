#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Carry the settings of an older German AI-CONFIG.md (the predecessor template's control
#          file) over into the project's docs/ai/config.md during an adoption (skill act-adopt,
#          docs/project/concepts/ai-dev-app/11-build-decisions.md § "Stufe 6" in the template-pflege
#          repo). Only keys with a real counterpart are written, and only where config.md still
#          holds what init wrote without being told (the skeleton default, see DEFAULTS) — a value
#          the project already set is never overwritten, only reported next to the old one. German
#          values are translated (aus -> off, wöchentlich -> weekly, ...). Every other key, every
#          value without a counterpart and every free-text passage is listed in a report — nothing
#          is dropped silently. An old .claude/template.json "values" block fills in a mapped key
#          the AI-CONFIG.md lacks (or stands in for a missing AI-CONFIG.md). Stdlib only.
#
# Usage:
#   python .act/scripts/adopt_config.py --target <project> [--plan] [--source <AI-CONFIG.md>]
#       Sources, if --source is not given: <target>/AI-CONFIG.md, else its legacy copy under
#       docs/ai/work/archive/legacy/; fallback <target>/.claude/template.json (or its legacy copy).
#
# Output format:
#   The report as Markdown on stdout — "Mapped" (old key, old value, key, result: set / same /
#   kept: project value / not set: reason), "No counterpart" (old key, value, section, note), and
#   "Free text" (each passage verbatim with its section and lines) — also written to
#   <target>/.act-local/adopt/config-report.md; then one "[adopt-config] ..." summary line.
#   --plan: the same report ("would set"), nothing written. Exit 0 on success and on --plan;
#   2 if the target has no docs/ai/config.md or no source was found.

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

LEGACY_ROOT = Path("docs/ai/work/archive/legacy")
CONFIG = Path("docs/ai/config.md")
REPORT = Path(".act-local/adopt/config-report.md")

# Old key (German, case-insensitive; the new English key itself is accepted too) -> new key.
# The three command keys fill one position each of `commands` ("<lint>, <typecheck>, <test>").
KEY_MAP: dict[str, str] = {
    "projektname": "name", "auftraggeber": "owner", "stack": "stack",
    "lint-befehl": "commands:0", "typecheck-befehl": "commands:1", "test-befehl": "commands:2",
    "ki-werkzeuge": "tools", "feedback": "feedback", "feedback-takt": "feedback-cadence",
    "feedback-umfang": "feedback-scope", "logging": "logging", "logging-tiefe": "log-level",
}
KEY_MAP.update({new: new for new in ("name", "owner", "stack", "tools", "feedback-cadence",
                                     "feedback-scope", "log-level")})
TEMPLATE_JSON_KEYS = {"PROJEKTNAME": "projektname", "AUFTRAGGEBER": "auftraggeber", "STACK": "stack",
                      "LINT_BEFEHL": "lint-befehl", "TYPECHECK_BEFEHL": "typecheck-befehl",
                      "TEST_BEFEHL": "test-befehl"}
NOTES = {"coding-guidelines": "see the rule-set checkboxes in docs/project/coding_rules.md"}

VALUE_MAP: dict[str, dict[str, str]] = {
    "feedback": {"aus": "off", "bestätigen": "confirm", "automatisch": "automatic", "manuell": "manual",
                 "off": "off", "confirm": "confirm", "automatic": "automatic", "manual": "manual"},
    "feedback-cadence": {"manuell": "manual", "sofort": "immediate", "stündlich": "hourly", "täglich": "daily",
                         "wöchentlich": "weekly", "adaptiv": "adaptive", "manual": "manual",
                         "immediate": "immediate", "hourly": "hourly", "daily": "daily", "weekly": "weekly",
                         "adaptive": "adaptive"},
    "logging": {"aus": "off", "ein": "on", "off": "off", "on": "on"},
    "log-level": {v.lower(): v for v in ("DEBUG", "INFO", "WARN", "ERROR")},
}
# The old tool names (AI-CONFIG.md § Assistenten, "KI-Werkzeuge") -> the ids `tools` takes.
TOOL_MAP = {"claude code": "claude-code", "claude-code": "claude-code", "copilot": "copilot",
            "github copilot": "copilot", "cursor": "cursor", "aider": "aider", "gemini cli": "gemini",
            "gemini": "gemini", "chatgpt/codex": "codex", "codex": "codex", "ollama": "ollama", "cline": "cline"}

# What init writes when nobody told it otherwise (init.py step_config, .act/skeleton/config.md) —
# a config.md value in this set may be replaced; anything else is the project's own and stays.
DEFAULTS: dict[str, set] = {
    "name": {"", "<name>"}, "owner": {"", "<owner>", "unknown"}, "stack": {"", "<stack>", "unspecified"},
    "tools": {"", "<tool-list>", "(none)", "claude-code"}, "feedback": {"", "<feedback-mode>", "off"},
    "feedback-cadence": {"", "weekly"}, "feedback-scope": {"", "a,b,c"}, "logging": {"", "off"},
    "log-level": {"", "INFO"},
}
NOT_SET = "(not set)"
EMPTY_VALUES = {"", "—", "–", "-"}


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _cells(line: str) -> Optional[list[str]]:
    """The cells of a Markdown table row (an escaped "\\|" stays inside its cell), or None."""
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")) or len(stripped) < 2:
        return None
    return [c.strip() for c in re.split(r"(?<!\\)\|", stripped[1:-1])]


def _is_separator(cells: list[str]) -> bool:
    return all(c.strip(":") and set(c.strip(":")) == {"-"} for c in cells)


def parse_old_config(text: str) -> tuple[list[dict], list[dict]]:
    """(rows, free text). rows: {"key", "value", "section", "line"} for every key/value table row
    (header and separator rows skipped). free text: {"section", "first", "last", "text"} for each
    run of non-table, non-heading lines, verbatim."""
    lines = text.splitlines()
    rows: list[dict] = []
    passages: list[dict] = []
    section = "(before the first heading)"
    current: list[tuple[int, str]] = []

    def flush() -> None:
        while current and not current[-1][1].strip():
            current.pop()
        if current:
            passages.append({"section": section, "first": current[0][0], "last": current[-1][0],
                             "text": "\n".join(l for _n, l in current)})
        current.clear()

    for number, line in enumerate(lines, 1):
        cells = _cells(line)
        if cells is not None:
            flush()
            following = _cells(lines[number]) if number < len(lines) else None
            if _is_separator(cells) or (following is not None and _is_separator(following)):
                continue
            if len(cells) >= 2 and cells[0]:
                rows.append({"key": cells[0].strip("`").strip(), "value": cells[1], "section": section,
                             "line": number})
            continue
        if line.startswith("#"):
            flush()
            section = line.lstrip("#").strip()
            continue
        if current or line.strip():
            current.append((number, line))
    flush()
    return rows, passages


def read_template_values(path: Optional[Path]) -> dict[str, str]:
    if path is None:
        return {}
    try:
        data = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    values = data.get("values") if isinstance(data, dict) else None
    return {k: v for k, v in values.items() if isinstance(v, str)} if isinstance(values, dict) else {}


def _first_existing(root: Path, rel: str) -> Optional[Path]:
    for candidate in (root / rel, root / LEGACY_ROOT / rel):
        if candidate.is_file():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------

def _split_commands(value: str) -> list[str]:
    """`commands` cell -> its parts, split at ", " outside backticks."""
    parts, buf, in_code = [], "", False
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "`":
            in_code = not in_code
        if ch == "," and not in_code:
            parts.append(buf.strip())
            buf = ""
        else:
            buf += ch
        i += 1
    parts.append(buf.strip())
    return parts


def translate(new_key: str, old_value: str) -> tuple[Optional[str], str]:
    """(new value or None, note). None: nothing to write (empty, or no counterpart for the value)."""
    value = old_value.strip()
    if value.strip("`").strip() in EMPTY_VALUES:
        return None, "empty in the old file"
    if new_key in VALUE_MAP:
        mapped = VALUE_MAP[new_key].get(value.strip("`").strip().lower())
        return (mapped, "") if mapped else (None, f"value {value!r} has no counterpart")
    if new_key == "feedback-scope":
        letters = [p.strip().lower() for p in value.strip("`").split(",") if p.strip()]
        if letters and all(p in ("a", "b", "c") for p in letters):
            return ",".join(sorted(set(letters))), ""
        return None, f"value {value!r} has no counterpart (a, b, c)"
    if new_key == "tools":
        names = [p.strip() for p in value.split(",") if p.strip()]
        known = sorted({TOOL_MAP[n.lower()] for n in names if n.lower() in TOOL_MAP})
        unknown = [n for n in names if n.lower() not in TOOL_MAP]
        note = f"no tool id for: {', '.join(unknown)}" if unknown else ""
        return (", ".join(known) if known else None), note
    return value, ""


class ConfigFile:
    """docs/ai/config.md as lines, with the value cell of a `key` row replaceable in place."""

    def __init__(self, path: Path):
        self.path = path
        self.raw = path.read_bytes().decode("utf-8")
        self.newline = "\r\n" if "\r\n" in self.raw else "\n"
        self.lines = self.raw.splitlines()

    def _find(self, key: str) -> Optional[int]:
        pattern = re.compile(r"^\s*\|\s*`?" + re.escape(key) + r"`?\s*\|")
        return next((i for i, line in enumerate(self.lines) if pattern.match(line)), None)

    def get(self, key: str) -> Optional[str]:
        index = self._find(key)
        cells = _cells(self.lines[index]) if index is not None else None
        return cells[1] if cells and len(cells) > 1 else None

    def set(self, key: str, value: str) -> None:
        index = self._find(key)
        line = self.lines[index]
        match = re.match(r"^(\s*\|[^|]*\|)((?:\\\||[^|])*)(\|.*)$", line)
        self.lines[index] = f"{match.group(1)} {value} {match.group(3)}"

    def save(self) -> None:
        text = self.newline.join(self.lines) + (self.newline if self.raw.endswith(("\n", "\r\n")) else "")
        self.path.write_bytes(text.encode("utf-8"))


def _git_user(root: Path) -> str:
    result = subprocess.run(["git", "-C", str(root), "config", "user.name"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace")
    return result.stdout.strip() if result.returncode == 0 else ""


def build(root: Path, source: Optional[Path], template_json: Optional[Path], cfg: ConfigFile, plan: bool) -> dict:
    text = source.read_bytes().decode("utf-8", errors="replace") if source else ""
    rows, passages = parse_old_config(text)
    fallback = read_template_values(template_json)
    defaults = {k: set(v) for k, v in DEFAULTS.items()}
    defaults["name"].add(root.name)
    user = _git_user(root)
    if user:
        defaults["owner"].add(user)

    by_old: dict[str, dict] = {}
    unmapped: list[dict] = []
    for row in rows:
        key = row["key"].lower()
        if key in KEY_MAP and key not in by_old:
            by_old[key] = dict(row, origin=source.name if source else "")
        else:
            unmapped.append(dict(row, note=NOTES.get(key, "no counterpart")))
    for tj_key, value in fallback.items():
        old = TEMPLATE_JSON_KEYS.get(tj_key)
        have = by_old.get(old) if old else None
        tj_empty = value.strip("`").strip() in EMPTY_VALUES
        if old and (have is None or (have["value"].strip("`").strip() in EMPTY_VALUES and not tj_empty)):
            if have is not None:  # the old file's own (empty) row stays visible in the report
                unmapped.append(dict(have, note=f"empty; value taken from .claude/template.json {tj_key}"))
            by_old[old] = {"key": tj_key, "value": value, "section": ".claude/template.json values",
                           "line": None, "origin": ".claude/template.json"}
        elif not old:
            unmapped.append({"key": tj_key, "value": value, "section": ".claude/template.json values",
                             "line": None, "note": "no counterpart"})
        elif have["value"].strip() != value.strip():
            unmapped.append({"key": tj_key, "value": value, "section": ".claude/template.json values",
                             "line": None, "note": f"not used: {source.name if source else 'the old file'} says {have['value']!r}"})

    verb = "would set" if plan else "set"
    mapped: list[dict] = []
    command_parts: dict[int, tuple[str, dict]] = {}
    for old_key, row in by_old.items():
        new_key = KEY_MAP[old_key]
        if new_key.startswith("commands:"):
            value, note = translate("commands", row["value"])
            if value is None:
                mapped.append(dict(row, new="commands", result=f"not set: {note}"))
            else:
                command_parts[int(new_key.split(":")[1])] = (value, row)
            continue
        value, note = translate(new_key, row["value"])
        current = cfg.get(new_key)
        if value is None:
            result = f"not set: {note}"
        elif current is None:
            result = f"not set: config.md has no `{new_key}` row"
        elif current.strip() == value:
            result = "same"
        elif current.strip() in defaults.get(new_key, {""}):
            cfg.set(new_key, value)
            result = f"{verb}: {value}" + (f" ({note})" if note else "")
        else:
            result = f"kept: project value {current.strip()!r}" + (f" ({note})" if note else "")
        mapped.append(dict(row, new=new_key, result=result))

    if command_parts:
        current = cfg.get("commands")
        parts = _split_commands(current) if current is not None else []
        if current is None:
            outcome = {i: "not set: config.md has no `commands` row" for i in command_parts}
        elif len(parts) != 3:
            outcome = {i: f"kept: project value {current!r} (not three parts)" for i in command_parts}
        else:
            outcome = {}
            for i, (value, _row) in command_parts.items():
                if parts[i] == value:
                    outcome[i] = "same"
                elif parts[i] in (NOT_SET, "", f"<{('lint', 'typecheck', 'test')[i]}-command>"):
                    parts[i] = value
                    outcome[i] = f"{verb}: {value}"
                else:
                    outcome[i] = f"kept: project value {parts[i]!r}"
            if any(r.startswith(verb) for r in outcome.values()):
                cfg.set("commands", ", ".join(parts))
        for i, (value, row) in sorted(command_parts.items()):
            label = ("lint", "typecheck", "test")[i]
            mapped.append(dict(row, new=f"commands ({label})", result=outcome[i]))

    return {"source": source, "template_json": template_json, "mapped": mapped, "unmapped": unmapped,
            "passages": passages}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ") if value is not None else ""


def _fence(text: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def render(root: Path, data: dict, plan: bool) -> str:
    def rel(path: Optional[Path]) -> str:
        return path.relative_to(root).as_posix() if path else "none"

    out = ["# Config adoption report (`adopt_config.py`)", "",
           f"Source: `{rel(data['source'])}` · fallback: `{rel(data['template_json'])}` · target: `{CONFIG.as_posix()}`"
           + (" · plan only, nothing written" if plan else ""), "",
           "## Mapped", "", "| Old key | Old value | Key | Result |", "| :--- | :--- | :--- | :--- |"]
    out += [f"| {_cell(r['key'])} | {_cell(r['value'])} | `{r['new']}` | {_cell(r['result'])} |" for r in data["mapped"]] \
        or ["| — | — | — | nothing to map |"]
    out += ["", "## No counterpart", "", "| Old key | Old value | Section | Note |", "| :--- | :--- | :--- | :--- |"]
    out += [f"| {_cell(r['key'])} | {_cell(r['value'])} | {_cell(r['section'])} | {_cell(r['note'])} |"
            for r in data["unmapped"]] or ["| — | — | — | none |"]
    out += ["", "## Free text (no counterpart — the owner decides where it goes)", ""]
    if not data["passages"]:
        out.append("- none")
    for p in data["passages"]:
        fence = _fence(p["text"])
        out += [f"### {p['section']} (lines {p['first']}–{p['last']})", "", f"{fence}text", p["text"], fence, ""]
    return "\n".join(out).rstrip("\n") + "\n"


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(
        prog="adopt_config.py",
        description="Carry an old AI-CONFIG.md's settings into docs/ai/config.md; report everything else.",
    )
    parser.add_argument("--target", metavar="DIR", required=True, help="the project (already set up by adopt.py --apply)")
    parser.add_argument("--source", metavar="FILE", help="the old AI-CONFIG.md (default: see Usage)")
    parser.add_argument("--plan", action="store_true", help="show the report, write nothing")
    args = parser.parse_args(argv)

    root = Path(args.target).expanduser().resolve()
    config_path = root / CONFIG
    if not config_path.is_file():
        print(f"adopt_config.py: {CONFIG.as_posix()} missing in {root} — run adopt.py --apply (or init.py) first",
              file=sys.stderr)
        return 2
    source = Path(args.source).expanduser().resolve() if args.source else _first_existing(root, "AI-CONFIG.md")
    if source is not None and not source.is_file():
        print(f"adopt_config.py: source not found: {source}", file=sys.stderr)
        return 2
    template_json = _first_existing(root, ".claude/template.json")
    if source is None and not read_template_values(template_json):
        print("adopt_config.py: neither an AI-CONFIG.md nor a .claude/template.json with values found", file=sys.stderr)
        return 2

    cfg = ConfigFile(config_path)
    data = build(root, source, template_json, cfg, args.plan)
    report = render(root, data, args.plan)
    print(report, end="")
    changed = sum(1 for r in data["mapped"] if r["result"].startswith("set"))
    if not args.plan:
        if changed:
            cfg.save()
        (root / REPORT).parent.mkdir(parents=True, exist_ok=True)
        (root / REPORT).write_bytes(report.encode("utf-8"))
    would = sum(1 for r in data["mapped"] if r["result"].startswith("would set"))
    print(f"[adopt-config] {changed or would} value(s) {'would be ' if args.plan else ''}set, "
          f"{len(data['unmapped'])} key(s) without counterpart, {len(data['passages'])} free-text passage(s)"
          + ("" if args.plan else f"; report: {REPORT.as_posix()}"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
