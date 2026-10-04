#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Carry the settings of an older German AI-CONFIG.md (the predecessor template's control
#          file) over into the project's docs/ai/config.md during an adoption (skill `act-adopt`).
#          Only keys with a real counterpart are written, and only where config.md still
#          holds what init wrote without being told (the skeleton default, see DEFAULTS) — a value
#          the project already set is never overwritten, only reported next to the old one. German
#          values are translated (aus -> off, wöchentlich -> weekly, ...) — see VALUE_MAP: the
#          German words are the predecessor template's own literal config values, read verbatim
#          from an old project's AI-CONFIG.md, so they must stay German to be recognized.
#          Every other key, every
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
#   <target>/.act-local/adopt/config-report.md; then one "[adopt-config] ..." summary line. A
#   `language-docs` other than English also leaves a docs/ai/inbox/U<n>-translate-scaffold.md
#   entry (the scaffold init wrote is still English, R-work-language) unless one exists already. An
#   old AI-CONFIG.md without any language row sets `language-docs` to `de` — the old template was
#   always German — and its "Mapped" row says that this is an assumption. A language given to
#   adopt.py --apply (state.json "languages") is a project value instead: no assumption, no
#   overwrite from the language row, the row reads "kept: set at --apply". `Coding-Guidelines`
#   checks the named sets (plus whatever their `requires:` pulls in) straight in
#   docs/project/coding_rules.md, group checkboxes included — its "Mapped" row says which
#   were newly checked, already checked, or matched no rule set. A lint/typecheck/test command
#   that names a path the adoption is removing (`.act-local/adopt/table.json` action
#   delete/legacy, or simply nothing left on disk) is still set as given, but flagged in its
#   result. If the most recent docs/ai/inbox/U<n>-init-notes.md (init.py's
#   non-interactive run) is still around, it is updated in place — `for: unknown` becomes the
#   adopted owner, and a short "Filled in by adopt_config.py" section lists what else this run
#   set; the human's own wording there, if any, is only ever appended to, never edited.
#   Its "Project config uses defaults for: ..." line loses every key this run set (and a language
#   already set by adopt.py --apply --language-docs/--language-chat); a note with nothing left in
#   it is removed.
#   --plan: the same report ("would set"), nothing written. Exit 0 on success, on --plan, and when
#   nothing to adopt was found at all (no AI-CONFIG.md, no .claude/template.json with values —
#   the normal case for a project that was never the old template); 2 if the target has no
#   docs/ai/config.md, or an explicitly given --source does not exist.

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

import actlib
import adopt
import entries
import init

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
    # The old template's one language row (`| Sprache | Deutsch |`, until it was dropped for a
    # fixed German) is the docs language (R-work-language); the chat language stays `auto`.
    "sprache": "language-docs",
}
KEY_MAP.update({new: new for new in ("name", "owner", "stack", "tools", "feedback-cadence",
                                     "feedback-scope", "log-level", "language-chat", "language-docs")})
TEMPLATE_JSON_KEYS = {"PROJEKTNAME": "projektname", "AUFTRAGGEBER": "auftraggeber", "STACK": "stack",
                      "LINT_BEFEHL": "lint-befehl", "TYPECHECK_BEFEHL": "typecheck-befehl",
                      "TEST_BEFEHL": "test-befehl"}
NOTES: dict[str, str] = {}
# The old key whose value is a comma list of rule-set names (Nuxt/Vue/TypeScript/SQL/...) — routed
# straight into docs/project/coding_rules.md's checkboxes (init.enable_coding_sets) instead
# of the plain key/value mapping below; never added to KEY_MAP so the main loop skips it.
CODING_GUIDELINES_KEY = "coding-guidelines"

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
# An old AI-CONFIG.md without any language row comes from the template's later, always-German
# versions ("Die Arbeitssprache ist fest Deutsch") — `language-docs` is then assumed `de`, and the
# report says so (build()).
ASSUMED_DOCS_LANGUAGE = "de"
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
    "log-level": {"", "INFO"}, "language-chat": {"", "<language-chat>", "auto"},
    "language-docs": {"", "<language-docs>", "en"},
}
NOT_SET = "(not set)"
EMPTY_VALUES = {"", "—", "–", "-"}
# An absolute path (POSIX "/...", Windows "C:/..."/"C:\\...", a UNC "\\\\host\\...") or a
# "scheme://" URL — _removed_command_paths() never treats one of these as something the
# adoption could have removed.
_ABS_OR_URL_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]|\w+://)")


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
    # The legacy copy of a tool-config path is renamed (adopt.legacy_rel()) so no AI tool
    # reads it as its own configuration from inside the archive — check under that name, not `rel`.
    for candidate in (root / rel, root / LEGACY_ROOT / adopt.legacy_rel(rel)):
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
    if new_key in ("language-chat", "language-docs"):
        code = actlib.normalize_language(value, allow_auto=(new_key == "language-chat"))
        return (code, "") if code else (None, f"value {value!r} is no language code (or `auto` for docs)")
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


def _apply_coding_guidelines(root: Path, row: dict, plan: bool) -> dict:
    """Turn one old `Coding-Guidelines` row (a comma list of rule-set names) into a "Mapped" report
    row, actually checking the named sets in docs/project/coding_rules.md along the way
    (init.enable_coding_sets). Unlike the plain key/value mapping below, there is no
    single `docs/ai/config.md` cell to compare against a default, so the report says what
    happened directly instead of "set"/"kept"/"same"."""
    names = {p.strip().lower() for p in row["value"].strip("`").split(",") if p.strip()}
    if not names:
        return dict(row, new="coding_rules.md", result="not set: empty in the old file")
    newly, already, unknown = init.enable_coding_sets(root, names, plan)
    verb = "would check" if plan else "checked"
    parts = []
    if newly:
        parts.append(f"{verb} in docs/project/coding_rules.md: {', '.join(newly)}")
        if not plan:
            _record_coding_rules_touch(root)
            parts.append("hash change recorded in .act-local/adopt/config-touched.json "
                          "(paths.\"docs/project/coding_rules.md\".sha256) for --finish")
    if already:
        parts.append(f"already checked in docs/project/coding_rules.md: {', '.join(already)}")
    if unknown:
        parts.append(f"no matching rule set in docs/project/coding_rules.md: {', '.join(unknown)}")
    result = "; ".join(parts) if parts else "not set: docs/project/coding_rules.md not found"
    return dict(row, new="coding_rules.md", result=result)


def _record_coding_rules_touch(root: Path) -> None:
    """Leaves a small, separate record at .act-local/adopt/config-touched.json — {"paths": {<rel
    path>: {"sha256", "changed_by"}}} — with the post-write hash of docs/project/coding_rules.md,
    for adopt.py's own --finish (a different builder) to tell apart from
    "nobody filled this in": --finish's `target_hashes` snapshot is taken right after init.py runs,
    before this script checks any boxes, so its own "content not adopted?" comparison already sees
    a real change here and needs nothing from this file to stay correct today — this record is
    only so --finish (or anything else reading target_hashes) can, if it chooses to, recognize that
    this particular change came from adopt_config.py rather than a human, should it ever need that
    distinction (e.g. a checkbox reverted back to init's own default would otherwise look
    unchanged again). adopt_config.py never writes into adopt.py's own state.json directly."""
    dest = root / "docs" / "project" / "coding_rules.md"
    if not dest.is_file():
        return
    record_path = root / ".act-local" / "adopt" / "config-touched.json"
    data: dict = {}
    if record_path.is_file():
        try:
            loaded = json.loads(record_path.read_bytes().decode("utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            pass
    paths = data.get("paths")
    if not isinstance(paths, dict):
        paths = {}
    paths["docs/project/coding_rules.md"] = {"sha256": actlib.sha256_file(dest), "changed_by": "adopt_config.py"}
    data["paths"] = paths
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _read_table_rows(root: Path) -> list[dict]:
    """`.act-local/adopt/table.json`'s "rows" (adopt_scan.py's classification of every old path),
    or [] once it is gone or was never written (e.g. `--source` used standalone, without the rest
    of an `act-adopt` run) — the same "nothing to check against" case _removed_command_paths()
    already falls back on."""
    try:
        data = json.loads((root / ".act-local" / "adopt" / "table.json").read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    rows = data.get("rows") if isinstance(data, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _removed_command_paths(root: Path, command: str, table_rows: list[dict]) -> list[str]:
    """Every path-shaped token of an old lint/typecheck/test `command` that the adoption is about
    to remove: listed in `table_rows` with action `delete`/`legacy` (e.g. the predecessor
    template's own `.claude/scripts/*.py`), or — with no table at hand — simply nothing left on
    disk once a glob's literal prefix is stripped. Used to flag a just-adopted command before it
    silently breaks; the command's value itself is still set unchanged, this only adds to
    the report. Skips an absolute path or a URL-like token outright — it
    is never something the adoption could have removed, and `root.glob()` raises
    `NotImplementedError` on a non-relative pattern; the glob call itself stays guarded too, in
    case a pattern is otherwise malformed."""
    removed = {r["path"] for r in table_rows if r.get("action") in ("delete", "legacy") and isinstance(r.get("path"), str)}
    found: list[str] = []
    for token in command.strip("`").split():
        if "/" not in token:
            continue
        if _ABS_OR_URL_RE.match(token):
            continue
        literal = token.split("*", 1)[0].rstrip("/")
        if not literal:
            continue
        if any(p == token or p.startswith(literal) for p in removed):
            found.append(token)
            continue
        try:
            missing = not (root / literal).exists() and not list(root.glob(literal + "*"))
        except (NotImplementedError, ValueError, OSError):
            missing = False
        if missing:
            found.append(token)
    return found


def _init_notes_path(root: Path) -> Optional[Path]:
    """The docs/ai/inbox/U<n>-init-notes.md that belongs to *this* adoption's own init.py run —
    read from .act-local/adopt/state.json's "created" list (adopt.py records every path init.py
    left behind there right after running it), rather than guessing by filename recency, which
    could just as well pick up a stale note left over from an unrelated, earlier init.py run in
    the same project. Falls back to the most recently dated file under
    docs/ai/inbox/ when there is no state.json to read at all (adopt_config.py run standalone,
    without adopt.py --apply first) — the same guess this function made before."""
    try:
        state = json.loads((root / ".act-local" / "adopt" / "state.json").read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        state = None
    if isinstance(state, dict) and isinstance(state.get("created"), list):
        match = next((c for c in state["created"] if isinstance(c, str)
                      and c.startswith("docs/ai/inbox/") and c.endswith("-init-notes.md")), None)
        if match:
            candidate = root / match
            return candidate if candidate.is_file() else None
    inbox_dir = root / actlib.INBOX_DIR
    # any name form (U<n>-… or the older todo-<stamp>-…); the newest by modification time, since
    # ids do not sort as text (U9 after U10)
    candidates = list(inbox_dir.glob("*-init-notes.md")) if inbox_dir.is_dir() else []
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


_IDENTITY_PLACEHOLDERS = {None, "unknown", "user"}


def _slugify_owner(owner: str) -> str:
    """Same rule as init.py's step_workspace_identity() (actlib.identity_slug)."""
    return actlib.identity_slug(owner)


def _identity_created_by_init(root: Path, path: Path) -> bool:
    """Whether init.py created `path` (.act-local/identity.json) in this adoption's own run and
    nobody changed it since: adopt.py records every git-ignored file init.py left, with its hash,
    in .act-local/adopt/state.json's "created_ignored". init derives such an identity from
    `git config user.name` — the person running the adoption, who is not necessarily the owner
    named in the old configuration."""
    try:
        state = json.loads((root / ".act-local" / "adopt" / "state.json").read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False
    created = state.get("created_ignored") if isinstance(state, dict) else None
    rel = path.relative_to(root).as_posix()
    expected = created.get(rel) if isinstance(created, dict) else None
    return bool(expected) and path.is_file() and adopt._sha256(path) == expected


def _update_workspace_identity(root: Path, mapped: list[dict], plan: bool,
                               mode: str = "solo") -> tuple[Optional[str], Optional[str]]:
    """.act-local/identity.json `identity` set to the adopted owner's slug, once this run
    actually set `owner` and either the current identity is a placeholder (`unknown`/`user`) or
    the file/key is missing (always rewritten), or init.py created the file in this adoption's own
    run, it is unchanged since (_identity_created_by_init) and `mode` is not `team` (solo: the
    adopter is the owner). In `team` mode init's guess is the real adopting person, who may differ
    from the owner: the file stays and a note names the mismatch. Never overwrites an identity a
    person or an earlier init.py run picked for this checkout. Reads/writes the file by `root`
    directly rather than through actlib's read_identity()/write_identity(): those resolve the repo
    root from the current working directory (actlib.repo_root()), which is not necessarily `root`
    here. Returns (new slug or None, mismatch note or None); nothing is written with `plan`."""
    owner_row = next((r for r in mapped if r["new"] == "owner" and r["result"].startswith("set")), None)
    if owner_row is None:
        return None, None
    owner = owner_row["result"].split(":", 1)[1].strip()
    if not owner:
        return None, None
    path = root / ".act-local" / "identity.json"
    try:
        current = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        current = {}
    if not isinstance(current, dict):
        return None, None
    slug = _slugify_owner(owner)
    if current.get("identity") not in _IDENTITY_PLACEHOLDERS:
        if not _identity_created_by_init(root, path):
            return None, None
        if mode.strip().lower() == "team":
            if current.get("identity") == slug:
                return None, None
            return None, (f"workspace identity `{current.get('identity')}` (from git user.name) differs from "
                          f"the owner `{slug}`; mode is team, so it was left unchanged — edit "
                          ".act-local/identity.json if this checkout belongs to the owner")
    if plan:
        return slug, None
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = dict(current)
    merged["identity"] = slug
    path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return slug, None


# init.py's line in the init-notes todo (step_config, non-interactive): the config keys it left at a
# default. Each label below is what init.py prints for one key; adopt_config removes the ones it
# has set since, so the note never lists a key that has a value by now.
_DEFAULTS_NOTE_RE = re.compile(r"^- Project config uses defaults for: (.*?) — review docs/ai/config\.md\.\s*$")
_LANGUAGE_DEFAULTS_LABEL = "language-chat/language-docs (auto/en)"
_DEFAULTS_LABELS = {"stack": "stack", "commands (lint)": "lint", "commands (typecheck)": "typecheck",
                    "commands (test)": "test"}


def _prune_defaults_note(lines: list[str], set_keys: set[str], language_set: set[str]) -> bool:
    """Drop from init.py's "Project config uses defaults for: ..." line every key this run has set
    (`set_keys`: the `new` names of the "set" rows; `language_set`: which of language-chat/
    language-docs hold a non-default value in config.md now). The line disappears when nothing is
    left of it. Returns True if a line changed."""
    covered = {label for key, label in _DEFAULTS_LABELS.items() if key in set_keys}
    for index, line in enumerate(lines):
        match = _DEFAULTS_NOTE_RE.match(line)
        if not match:
            continue
        remaining: list[str] = []
        for label in (part.strip() for part in match.group(1).split(",")):
            if label == _LANGUAGE_DEFAULTS_LABEL:
                if "language-docs" in language_set and "language-chat" in language_set:
                    continue
                if "language-docs" in language_set:
                    label = "language-chat (auto)"
                elif "language-chat" in language_set:
                    label = "language-docs (en)"
            elif label == "language-docs (en)" and "language-docs" in language_set:
                continue
            elif label == "language-chat (auto)" and "language-chat" in language_set:
                continue
            elif label in covered:
                continue
            remaining.append(label)
        new_line = (f"- Project config uses defaults for: {', '.join(remaining)} — review docs/ai/config.md."
                    if remaining else None)
        if new_line == line:
            return False
        if new_line is None:
            del lines[index]
        else:
            lines[index] = new_line
        return True
    return False


_FEEDBACK_OFF_NOTE_PREFIX = "- Feedback to the template author is off (default)"


def _prune_feedback_note(lines: list[str]) -> bool:
    """Drop init.py's "Feedback to the template author is off (default) ..." line once adoption set
    `feedback` in config.md — the line would otherwise keep claiming the opposite. Returns True if
    a line was removed."""
    kept = [line for line in lines if not line.startswith(_FEEDBACK_OFF_NOTE_PREFIX)]
    if len(kept) == len(lines):
        return False
    lines[:] = kept
    return True


def _note_is_empty(lines: list[str]) -> bool:
    """True if `lines` (a note file) hold only the header block, the title and blank lines — nothing
    a person would still read or has written."""
    body = lines
    if "" in lines:
        body = lines[lines.index("") + 1:]
    return all(not line.strip() or line.startswith("# ") for line in body)


def _update_init_notes(root: Path, mapped: list[dict], plan: bool, language: str = "en") -> Optional[Path]:
    """Bring the docs/ai/inbox/U<n>-init-notes.md belonging to this adoption's own init.py run
    (see _write_inbox_note there, and _init_notes_path() above) up to date with what this
    adoption just filled in, instead of leaving it to say `for: unknown` or list config defaults
    that no longer apply: its `for:` line becomes the adopted owner once one was set, and
    a short section lists every other key this run set. Only ever appends or rewrites the
    machine-written `for:` line — a human's own comment further down the file is never touched.
    Does nothing under `plan`, without such a file, or when this run set nothing (a repeat run, or
    one with no old config to draw from). The `for:` line sits below `kind: todo` in the header
    now (init.py's own _write_inbox_note()), not necessarily on line 0 — found by prefix instead.
    `language` (`language-docs`, R-work-language) picks the heading text this appends; the marker
    lookup below checks both language variants, so a repeat run in either language after
    `language-docs` changed between two adoption runs still finds the section already there
    instead of appending it a second time."""
    if plan:
        return None
    dest = _init_notes_path(root)
    if dest is None:
        return None
    set_rows = [r for r in mapped if r["result"].startswith("set")]
    if not set_rows:
        return None
    lines = dest.read_text(encoding="utf-8").splitlines()
    changed = False
    owner_row = next((r for r in set_rows if r["new"] == "owner"), None)
    if owner_row:
        for_index = next((i for i, line in enumerate(lines[:10])
                          if line.strip().lower() == "for: unknown"), None)
        if for_index is not None:
            new_owner = owner_row["result"].split(":", 1)[1].strip()
            if new_owner:
                lines[for_index] = f"for: {_slugify_owner(new_owner)}"
                changed = True
    # The "uses defaults for" line must not list what this run (or --language-docs at
    # --apply) has set since. A note with nothing left in it is removed instead of rewritten.
    current_config = ConfigFile(root / CONFIG) if (root / CONFIG).is_file() else None
    language_set = set()
    if current_config is not None:
        for key in ("language-chat", "language-docs"):
            value = (current_config.get(key) or "").strip().strip("`")
            if value and value not in DEFAULTS[key]:
                language_set.add(key)
    language_set |= {r["new"] for r in set_rows if r["new"] in ("language-chat", "language-docs")}
    if _prune_defaults_note(lines, {r["new"] for r in set_rows}, language_set):
        changed = True
        if _note_is_empty(lines):
            dest.unlink()
            return dest
    if any(r["new"] == "feedback" for r in set_rows) and _prune_feedback_note(lines):
        changed = True
        if _note_is_empty(lines):
            dest.unlink()
            return dest
    marker = actlib.localized(language, "## Filled in by `adopt_config.py`",
                              "## Ausgefüllt von `adopt_config.py`")
    markers_either_language = ("## Filled in by `adopt_config.py`", "## Ausgefüllt von `adopt_config.py`")
    joined = "\n".join(lines)
    if not any(candidate in joined for candidate in markers_either_language):
        keys = sorted({r["new"] for r in set_rows})
        note_text = actlib.localized(
            language, "Now set in docs/ai/config.md: {}.", "Jetzt gesetzt in docs/ai/config.md: {}.",
        ).format(", ".join(f"`{k}`" for k in keys))
        lines += ["", marker, "", note_text]
        changed = True
    if not changed:
        return None
    # newline="\n": read via splitlines() above (line endings already stripped), so the write must
    # force LF itself — a plain write_text() would otherwise use os.linesep (CRLF on Windows).
    with open(dest, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(lines) + "\n")
    return dest


def _decode_mixed(raw: bytes) -> tuple[str, int, int]:
    """Decode `raw` as UTF-8, but a byte that is not valid UTF-8 as Windows-1252 on its own (a
    byte cp1252 leaves undefined becomes U+FFFD) — so a mostly-UTF-8 file with a few foreign bytes
    keeps its correct characters instead of turning all of them into mojibake. Returns the text,
    the number of non-ASCII characters that decoded as valid UTF-8, and the number of bytes that
    needed the Windows-1252 fallback."""
    out: list[str] = []
    utf8_chars = 0
    fallback_bytes = 0
    position = 0
    while position < len(raw):
        try:
            tail = raw[position:].decode("utf-8")
            out.append(tail)
            utf8_chars += sum(1 for char in tail if ord(char) > 127)
            break
        except UnicodeDecodeError as exc:
            head = raw[position:position + exc.start].decode("utf-8")
            out.append(head)
            utf8_chars += sum(1 for char in head if ord(char) > 127)
            bad = raw[position + exc.start:position + exc.start + 1]
            out.append(bad.decode("cp1252", errors="replace"))
            fallback_bytes += 1
            position += exc.start + 1
    return "".join(out), utf8_chars, fallback_bytes


def _read_source_text(source: Optional[Path]) -> tuple[str, Optional[str]]:
    """Decode the old AI-CONFIG.md: UTF-8 first; a file that is UTF-8 apart from a few stray bytes
    keeps its UTF-8 characters and reads only those bytes as Windows-1252 (_decode_mixed); a file
    with no valid multi-byte UTF-8 at all is read as Windows-1252 whole (common for a hand-edited
    file from an older editor). Returns the text plus a note for the report when a fallback was used
    or even that failed to map every byte."""
    if source is None:
        return "", None
    raw = source.read_bytes()
    try:
        return raw.decode("utf-8"), None
    except UnicodeDecodeError:
        pass
    text, utf8_chars, fallback_bytes = _decode_mixed(raw)
    if utf8_chars and fallback_bytes:
        note = f"read as UTF-8 with some Windows-1252 bytes ({source.name})"
        if "\uFFFD" in text:
            note += " -- some bytes matched neither and were replaced"
        return text, note
    try:
        return raw.decode("cp1252"), f"read as Windows-1252, not UTF-8 ({source.name})"
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace"), (
            f"read as Windows-1252, not UTF-8 ({source.name}) -- some bytes matched neither and were replaced")


def _languages_from_apply(root: Path) -> dict[str, str]:
    """The languages adopt.py --apply was given explicitly (state.json "languages"):
    {"language-docs": "en", ...}, empty if none or no state file."""
    try:
        state = json.loads((root / adopt.ADOPT_DIR / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    languages = state.get("languages") if isinstance(state, dict) else None
    return {k: v for k, v in languages.items() if k in ("language-docs", "language-chat") and isinstance(v, str)} \
        if isinstance(languages, dict) else {}


def build(root: Path, source: Optional[Path], template_json: Optional[Path], cfg: ConfigFile, plan: bool) -> dict:
    text, encoding_note = _read_source_text(source)
    rows, passages = parse_old_config(text)
    fallback = read_template_values(template_json)
    defaults = {k: set(v) for k, v in DEFAULTS.items()}
    defaults["name"].add(root.name)
    user = _git_user(root)
    if user:
        defaults["owner"].add(user)

    by_old: dict[str, dict] = {}
    unmapped: list[dict] = []
    coding_guidelines_row: Optional[dict] = None
    for row in rows:
        key = row["key"].lower()
        if key == CODING_GUIDELINES_KEY:
            if coding_guidelines_row is None:  # first one wins, same as by_old's own dedup
                coding_guidelines_row = row
            continue
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

    fixed = _languages_from_apply(root)
    if source is not None and "language-docs" not in fixed and not any(KEY_MAP.get(k) == "language-docs" for k in by_old):
        by_old["(no language row)"] = {
            "key": "(no language row)", "value": ASSUMED_DOCS_LANGUAGE, "section": "(assumption)",
            "line": None, "origin": source.name, "target": "language-docs",
            "assumed": "assumption: no language row, the old template was always German",
        }

    verb = "would set" if plan else "set"
    mapped: list[dict] = []
    command_parts: dict[int, tuple[str, dict]] = {}
    for old_key, row in by_old.items():
        new_key = row.get("target") or KEY_MAP[old_key]
        if new_key.startswith("commands:"):
            value, note = translate("commands", row["value"])
            if value is None:
                mapped.append(dict(row, new="commands", result=f"not set: {note}"))
            else:
                command_parts[int(new_key.split(":")[1])] = (value, row)
            continue
        value, note = translate(new_key, row["value"])
        current = cfg.get(new_key)
        if new_key in fixed:
            # Given to adopt.py --apply, so a project value — never guessed or overwritten.
            result = f"kept: set at --apply ({fixed[new_key]})"
        elif value is None:
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
        if row.get("assumed"):
            result += f" — {row['assumed']}"
        mapped.append(dict(row, new=new_key, result=result))

    if command_parts:
        table_rows = _read_table_rows(root)
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
                    removed = _removed_command_paths(root, value, table_rows)
                    if removed:
                        outcome[i] += (" — command refers to a path that the adoption removes: "
                                        + ", ".join(removed))
                else:
                    outcome[i] = f"kept: project value {parts[i]!r}"
            if any(r.startswith(verb) for r in outcome.values()):
                cfg.set("commands", ", ".join(parts))
        for i, (value, row) in sorted(command_parts.items()):
            label = ("lint", "typecheck", "test")[i]
            mapped.append(dict(row, new=f"commands ({label})", result=outcome[i]))

    if coding_guidelines_row is not None:
        mapped.append(_apply_coding_guidelines(root, coding_guidelines_row, plan))

    return {"source": source, "template_json": template_json, "mapped": mapped, "unmapped": unmapped,
            "passages": passages, "encoding_note": encoding_note}


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ") if value is not None else ""


def _fence(text: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def render(root: Path, data: dict, plan: bool, language: str = "en") -> str:
    def rel(path: Optional[Path]) -> str:
        return path.relative_to(root).as_posix() if path else "none"

    L = lambda en, de: actlib.localized(language, en, de)  # noqa: E731 - local shorthand, this
    # function's own headings/table headers/placeholders only (R-work-language: this report
    # becomes part of a file under docs/ once the `act-adopt` skill embeds it as an inbox entry's
    # body, so it follows `language-docs` the same as any other writer here).

    # No leading "# ..." title here: this report becomes the *body* of an
    # inbox entry the `act-adopt` skill titles itself (entries.py always writes its own
    # "# <title>" heading first) — a second, identical H1 right below it read as a doubled
    # heading. The standalone copy under .act-local/adopt/config-report.md loses nothing by it;
    # the "Source: ..." line already says what this is.
    out = [f"Source: `{rel(data['source'])}` · fallback: `{rel(data['template_json'])}` · target: `{CONFIG.as_posix()}`"
           + (" · " + L("plan only, nothing written", "nur Plan, nichts geschrieben") if plan else "")
           + (f" · {data['encoding_note']}" if data.get("encoding_note") else ""), "",
           f"## {L('Mapped', 'Übernommen')}", "",
           f"| {L('Old key', 'Alter Schlüssel')} | {L('Old value', 'Alter Wert')} | {L('Key', 'Schlüssel')} | {L('Result', 'Ergebnis')} |",
           "| :--- | :--- | :--- | :--- |"]
    out += [f"| {_cell(r['key'])} | {_cell(r['value'])} | `{r['new']}` | {_cell(r['result'])} |" for r in data["mapped"]] \
        or [f"| — | — | — | {L('nothing to map', 'nichts zu übernehmen')} |"]
    out += ["", f"## {L('No counterpart', 'Keine Entsprechung')}", "",
            f"| {L('Old key', 'Alter Schlüssel')} | {L('Old value', 'Alter Wert')} | {L('Section', 'Abschnitt')} | {L('Note', 'Hinweis')} |",
            "| :--- | :--- | :--- | :--- |"]
    out += [f"| {_cell(r['key'])} | {_cell(r['value'])} | {_cell(r['section'])} | {_cell(r['note'])} |"
            for r in data["unmapped"]] or [f"| — | — | — | {L('none', 'keine')} |"]
    out += ["", f"## {L('Free text (no counterpart — the owner decides where it goes)', 'Freitext (keine Entsprechung — der Owner entscheidet, wohin damit)')}", ""]
    if not data["passages"]:
        out.append(f"- {L('none', 'keine')}")
    for p in data["passages"]:
        fence = _fence(p["text"])
        out += [f"### {p['section']} ({L('lines', 'Zeilen')} {p['first']}–{p['last']})", "", f"{fence}text", p["text"], fence, ""]
    if data.get("identity_note"):
        out += ["", f"## {L('Workspace identity', 'Arbeitsplatz-Identität')}", "", f"- {data['identity_note']}"]
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
        # Not an error: a project that was never the old template has no AI-CONFIG.md and
        # no .claude/template.json with values to begin with — the normal case, not a failure of
        # this run. No report is written; there is nothing to report.
        print("adopt_config.py: nothing to adopt — no old configuration found")
        return 0

    cfg = ConfigFile(config_path)
    data = build(root, source, template_json, cfg, args.plan)
    # The report's own headings/table headers follow `language-docs` too (R-work-language) — read
    # after build(), which may just have set it itself from the old AI-CONFIG.md's `Sprache` row,
    # so a fresh German adoption's report comes out German from this very run, not only the next.
    current = {k: v for k in ("language-docs", "language") if (v := cfg.get(k)) is not None}
    docs_language = actlib.language_settings(current)[1]
    identity_slug, identity_note = _update_workspace_identity(
        root, data["mapped"], args.plan, cfg.get("mode") or "solo")
    data["identity_note"] = identity_note
    report = render(root, data, args.plan, docs_language)
    print(report, end="")
    changed = sum(1 for r in data["mapped"] if r["result"].startswith("set"))
    if not args.plan:
        if changed:
            cfg.save()
        (root / REPORT).parent.mkdir(parents=True, exist_ok=True)
        (root / REPORT).write_bytes(report.encode("utf-8"))
    would = sum(1 for r in data["mapped"] if r["result"].startswith("would set"))
    # A docs language other than English leaves the scaffold init wrote to translate (R-work-language):
    # one inbox entry, the same one init.py writes when it is asked for that language itself.
    note = entries.write_translate_note(root, docs_language, args.plan)
    init_notes = _update_init_notes(root, data["mapped"], args.plan, docs_language)
    print(f"[adopt-config] {changed or would} value(s) {'would be ' if args.plan else ''}set, "
          f"{len(data['unmapped'])} key(s) without counterpart, {len(data['passages'])} free-text passage(s)"
          + ("" if args.plan else f"; report: {REPORT.as_posix()}")
          + (f"; {'would write' if args.plan else 'wrote'} {note.relative_to(root).as_posix()}" if note else "")
          + (f"; {'updated' if init_notes.exists() else 'removed (nothing left in it)'} "
             f"{init_notes.relative_to(root).as_posix()}" if init_notes else "")
          + (f"; {'would set' if args.plan else 'set'} .act-local/identity.json identity to '{identity_slug}'"
             if identity_slug else "")
          + (f"; note: {identity_note}" if identity_note else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
