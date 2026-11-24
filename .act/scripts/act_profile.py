#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: The scope of the template inside one project — docs/ai/config.md § Scope: `profile`
#          (minimal | standard | full) and `exclude` (a comma list of template skills, roles, rule
#          files and topics). One library, used by init.py and update.py (skill copies, role
#          bridges), rules.py (the import lines of docs/ai/local/rules.md) and the session start (topics,
#          the one-line report), so no path writes a copy the project cut. Pure reading: this module
#          writes nothing.
# Rules:   a missing, empty or unknown `profile` is `full`, an empty or `none` `exclude` cuts
#          nothing — a project without the rows is unchanged; `minimal` and `standard` cut template
#          skills and roles only, rule files and topics fall only by name; `shared/10-safety.md`
#          cannot be excluded (a warning, the entry is ignored); an unknown name is a warning, never
#          an error; a project's own skills and roles (docs/ai/local/) are never part of a cut, only
#          the template's units are; nothing here raises on a missing or unreadable file. A docs/ai/config.md
#          that is missing or not UTF-8 asks for nothing new: read_cut() then returns the cut the lock
#          recorded (`readable` False), so nothing the scope cut comes back because the file cannot be read.
#          Active packages (the lock's `packages`) cut the same way, by name: a rule file all of whose rules
#          packages disable, and a topic a package replaces (package_cut(); what a package disables is read
#          from the marks it left in docs/ai/local/rules.md and from its own package.md while that file still has
#          the hash the lock recorded). Pure reading too.

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple, Optional

import actlib

PROFILES = ("minimal", "standard", "full")
DEFAULT_PROFILE = "full"

# What `minimal` keeps; every other template skill and role is cut by it.
CORE_SKILLS = frozenset({
    "act", "act-adopt", "act-bug", "act-commit", "act-compact", "act-doctor", "act-feedback",
    "act-handover", "act-idea", "act-packages", "act-prepare", "act-setup", "act-update",
    "act-config", "act-export-settings", "act-info", "act-load-settings", "act-version",
})
CORE_ROLES = frozenset({"builder", "debugger", "doc-writer", "explorer", "quick-check", "reviewer"})
# What `standard` cuts (web, design and teaching); everything else stays. The design skills go by
# their name prefix, so a design skill added later is cut too without this list changing.
STANDARD_CUT_SKILLS = frozenset({"act-a11y", "act-check-translations", "act-seo", "act-slides", "act-teach"})
STANDARD_CUT_PREFIXES = ("act-design-",)
# Rule files an exclusion never reaches (template-relative, "<layer>/<file>").
LOCKED_RULES = frozenset({"shared/10-safety.md"})

RULE_LAYERS = ("shared", "orchestrator")
_NONE_WORDS = ("", "none", "(not set)")

# The mark rules.py puts on the checkbox line of a rule an active package disables.
PACKAGE_MARK_RE = re.compile(r"[ \t]*<!--\s*act:package\s+(?P<id>[a-z][a-z0-9-]*)\s*-->[ \t]*$")
_RULE_ROW_RE = re.compile(r"^\s+-\s*\[(?P<mark>[ xX])\]\s*`(?P<id>[^`]+)`")
_RULE_HEADING_RE = re.compile(r"^##\s+`(?P<id>R-[^`]+)`")
_FENCE_RE = re.compile(r"^\s{0,3}(?:`{3,}|~{3,})")
_SECTION_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")
_LIST_RE = re.compile(r"^-\s+(?P<item>\S.*?)\s*$")
_RULE_ID_RE = re.compile(r"^R-[a-z0-9]+(?:-[a-z0-9]+)+$")


class Cut(NamedTuple):
    """What the config cuts from the template's units. `skills` and `roles` are names, `rules` the
    root-relative paths of rule files (".act/rules/orchestrator/30-cost.md"), `topics` the topic
    names; `warnings` is one line per entry that could not be applied."""
    profile: str
    exclude: tuple[str, ...]
    skills: frozenset[str]
    roles: frozenset[str]
    rules: frozenset[str]
    topics: frozenset[str]
    warnings: tuple[str, ...]
    readable: bool = True  # False: docs/ai/config.md could not be read, the sets are the cut recorded last time

    @property
    def empty(self) -> bool:
        return not (self.skills or self.roles or self.rules or self.topics)


EMPTY_CUT = Cut(DEFAULT_PROFILE, (), frozenset(), frozenset(), frozenset(), frozenset(), ())


def _clean(value: str) -> str:
    return value.strip().strip("`").strip()


def _names(base: Path, pattern: str, directories: bool) -> dict[str, str]:
    """{lower-case name: real name} of the entries under `base`; a role file or topic by its stem,
    a skill by its folder name, README.md never."""
    found: dict[str, str] = {}
    if not base.is_dir():
        return found
    try:
        for path in sorted(base.glob(pattern)):
            if directories and not path.is_dir():
                continue
            if not directories and (not path.is_file() or path.name.lower() == "readme.md"):
                continue
            name = path.name if directories else path.stem
            found[name.lower()] = name
    except OSError:
        return {}
    return found


def template_skills(root: Path) -> dict[str, str]:
    return _names(root / ".act" / "skills", "*", True)


def template_roles(root: Path) -> dict[str, str]:
    return _names(root / ".act" / "agents", "*.md", False)


def template_topics(root: Path) -> dict[str, str]:
    return _names(root / ".act" / "rules" / "topics", "*.md", False)


def template_rules(root: Path) -> dict[str, str]:
    """{lower-case "<layer>/<file>.md": real} of the rule files a docs/ai/local/rules.md can import."""
    found: dict[str, str] = {}
    for layer in RULE_LAYERS:
        base = root / ".act" / "rules" / layer
        if not base.is_dir():
            continue
        try:
            for path in sorted(base.glob("*.md")):
                if path.is_file():
                    found[f"{layer}/{path.name}".lower()] = f"{layer}/{path.name}"
        except OSError:
            continue
    return found


def profile_value(config: dict[str, str]) -> tuple[str, Optional[str]]:
    """(effective profile, warning or None) of a read_config() result: a missing or empty row is
    `full`, a value that is not one of PROFILES is `full` with a warning."""
    raw = _clean(config.get("profile", "")).lower()
    if not raw:
        return DEFAULT_PROFILE, None
    if raw in PROFILES:
        return raw, None
    return DEFAULT_PROFILE, (f"profile `{_clean(config.get('profile', ''))}` is not one of "
                             f"{' | '.join(PROFILES)} — counted as `{DEFAULT_PROFILE}`")


def exclude_entries(config: dict[str, str]) -> tuple[str, ...]:
    """The names listed in `exclude`, in order, trimmed, without `none`."""
    raw = _clean(config.get("exclude", ""))
    if raw.lower() in _NONE_WORDS:
        return ()
    return tuple(part for part in (_clean(item) for item in raw.split(",")) if part)


def _rule_key(entry: str) -> str:
    """An exclude entry as "<layer>/<file>.md" when it is shaped like a rule file: an optional
    `.act/` and `rules/` prefix and an optional `.md`, e.g. "orchestrator/30-cost"; else ""."""
    text = entry.replace("\\", "/").lower()
    for prefix in (".act/", "rules/"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    parts = text.split("/")
    if len(parts) != 2 or parts[0] not in RULE_LAYERS or not parts[1]:
        return ""
    return text if text.endswith(".md") else text + ".md"


def package_disables(root: Path, packages: "dict[str, dict]") -> set[str]:
    """The rule ids the packages in `packages` (the lock's `packages` record) disable, counting only rows that are
    still unchecked: a rule whose checkbox line in docs/ai/local/rules.md carries the mark of one of them and is
    unchecked (this holds with the package folder gone), unless the package's own `## disables` (read while its
    package.md still has the hash the lock recorded) no longer lists it -- the new version of the package dropped
    it, the row goes back on at the next load -- and the `## disables` of each such package, except for a rule
    the owner checked again by hand (its row is checked and keeps the mark). Never raises."""
    found: set[str] = set()
    try:
        lines = (root / actlib.RULES_FILE).read_text(encoding="utf-8").split("\n")
    except (OSError, UnicodeDecodeError):
        lines = []
    listed: dict[str, set[str]] = {}  # what each package whose package.md can be read lists
    for package_id, entry in packages.items():
        files = entry.get("files") if isinstance(entry.get("files"), dict) else {}
        recorded = files.get("package.md")
        try:
            data = (root / ".act-local" / "packages" / package_id / "package.md").read_bytes()
            text = actlib.fold_crlf(data).decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if isinstance(recorded, str) and actlib.lock_hash(data) == recorded:
            listed[package_id] = set(manifest_disables(text))
    rechecked: set[str] = set()
    for line in lines:
        text = line.rstrip("\r")
        mark = PACKAGE_MARK_RE.search(text)
        row = _RULE_ROW_RE.match(text[:mark.start()] if mark else text)
        if not (mark and row and mark.group("id") in packages):
            continue
        owner, rule_id = mark.group("id"), row.group("id")
        if row.group("mark") != " ":
            rechecked.add(rule_id)  # the owner switched it back on by hand
        elif owner not in listed or rule_id in listed[owner]:
            found.add(rule_id)
    for names in listed.values():
        found.update(names - rechecked)
    return found


def manifest_disables(text: str) -> list[str]:
    """The rule ids listed under `## disables` in the text of a package.md (list lines `- R-...`, in order,
    outside code fences); anything else in the section is not read here."""
    found: list[str] = []
    in_section, fenced = False, False
    for raw in text.split("\n"):
        line = raw.rstrip()
        if _FENCE_RE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        heading = _SECTION_RE.match(line)
        if heading:
            in_section = heading.group("title") == "disables"
            continue
        item = _LIST_RE.match(line.strip()) if in_section else None
        if item and _RULE_ID_RE.match(item.group("item")):
            found.append(item.group("item"))
    return found


def _rule_ids_of(path: Path) -> set[str]:
    """The rule ids of a template rule file (its `## R-...` headings) outside code fences; empty when unreadable."""
    ids: set[str] = set()
    fenced = False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ids
    for raw in text.split("\n"):
        if _FENCE_RE.match(raw):
            fenced = not fenced
        elif not fenced:
            heading = _RULE_HEADING_RE.match(raw.rstrip())
            if heading:
                ids.add(heading.group("id"))
    return ids


def package_cut(root: Path) -> tuple[frozenset[str], frozenset[str]]:
    """(rule files, topics) the active packages take out of the template, as read_cut() names them: a rule
    file of the template all of whose rules the packages disable (never `shared/10-safety.md`), and a topic
    a package replaces (a topic unit in the lock's `units` that is not listed in `extends` and has a template
    topic's name). Nothing here needs a package folder except `## disables` (package_disables()). Empty for a
    project without packages; never raises."""
    try:
        packages = actlib.read_packages(root)
    except Exception:  # noqa: BLE001 - the scope is best effort, an unreadable lock cuts nothing
        return frozenset(), frozenset()
    if not packages:
        return frozenset(), frozenset()
    topics_all = template_topics(root)
    topics: set[str] = set()
    for entry in packages.values():
        units = [u for u in entry.get("units", []) if isinstance(u, str)] if isinstance(entry.get("units"), list) else []
        extends = {u for u in entry.get("extends", []) if isinstance(u, str)} if isinstance(entry.get("extends"), list) else set()
        for unit in units:
            kind, _, name = unit.partition(":")
            if kind == "topic" and unit not in extends and name.lower() in topics_all:
                topics.add(topics_all[name.lower()])
    disabled = package_disables(root, packages)
    rules: set[str] = set()
    if disabled:
        for key, real in template_rules(root).items():
            if key in LOCKED_RULES:
                continue
            ids = _rule_ids_of(root / ".act" / "rules" / real)
            if ids and ids <= disabled:
                rules.add(f".act/rules/{real}")
    return frozenset(rules), frozenset(topics)


def read_cut(root: Path) -> Cut:
    """The cut the project at `root` asks for (see the header). Never raises. A docs/ai/config.md that
    is missing or not UTF-8 asks for nothing new: the result is the cut recorded last time (the lock's
    `applied` and `rules_cut`) with `readable` False, so no caller restores what the scope cut just
    because the file cannot be read."""
    try:
        (root / "docs" / "ai" / "config.md").read_text(encoding="utf-8")
        return _read_cut(root)
    except (OSError, ValueError):
        return _recorded_cut_of(root)


def _recorded_cut_of(root: Path) -> Cut:
    """The cut the lock of the project at `root` recorded (skills and roles in `applied`, rule files in
    `rules_cut`), as an unreadable-config result; the empty cut when none was recorded."""
    lock = actlib.read_lock_at(root)
    applied = lock.get("applied") if lock else None
    recorded = recorded_cut(applied)
    rules = frozenset(actlib.read_rules_cut(root))
    if not (recorded["skills"] or recorded["roles"] or rules):
        return EMPTY_CUT._replace(readable=False)
    warning = ("docs/ai/config.md is not readable — the scope recorded at the last sync stays as it is "
               "(copies, bridges and import lines are neither removed nor restored)")
    return Cut("unknown", (), frozenset(recorded["skills"]), frozenset(recorded["roles"]), rules,
               frozenset(), (warning,), False)


def _read_cut(root: Path) -> Cut:
    config = actlib.read_config(root)
    profile, profile_warning = profile_value(config)
    entries_listed = exclude_entries(config)
    package_rules, package_topics = package_cut(root)
    if profile == DEFAULT_PROFILE and not entries_listed and profile_warning is None:
        if not (package_rules or package_topics):
            return EMPTY_CUT
        return EMPTY_CUT._replace(rules=package_rules, topics=package_topics)
    warnings: list[str] = [profile_warning] if profile_warning else []
    skills_all, roles_all = template_skills(root), template_roles(root)
    topics_all, rules_all = template_topics(root), template_rules(root)
    skills: set[str] = set()
    roles: set[str] = set()
    rules: set[str] = set()
    topics: set[str] = set()

    if profile == "minimal":
        skills |= {name for name in skills_all.values() if name not in CORE_SKILLS}
        roles |= {name for name in roles_all.values() if name not in CORE_ROLES}
    elif profile == "standard":
        skills |= {name for name in skills_all.values()
                   if name in STANDARD_CUT_SKILLS or name.startswith(STANDARD_CUT_PREFIXES)}

    for entry in entries_listed:
        lowered = entry.replace("\\", "/").lower()
        key = _rule_key(entry)
        if key:
            if key in LOCKED_RULES:
                warnings.append(f"exclude `{entry}`: this rule file cannot be excluded — entry ignored")
            elif key in rules_all:
                rules.add(f".act/rules/{rules_all[key]}")
            else:
                warnings.append(f"exclude `{entry}`: no such rule file in the template — ignored")
            continue
        base = lowered[len("skills/"):] if lowered.startswith("skills/") else lowered
        if base in skills_all:
            skills.add(skills_all[base])
            continue
        base = lowered[len("agents/"):] if lowered.startswith("agents/") else lowered
        if base in roles_all:
            roles.add(roles_all[base])
            continue
        base = lowered[len("topics/"):] if lowered.startswith("topics/") else lowered
        base = base[:-3] if base.endswith(".md") else base
        if base in topics_all:
            topics.add(topics_all[base])
            continue
        warnings.append(f"exclude `{entry}`: not a template skill, role, rule file or topic — ignored")
    return Cut(profile, entries_listed, frozenset(skills), frozenset(roles), frozenset(rules) | package_rules,
               frozenset(topics) | package_topics, tuple(warnings))


def snapshot_value(cut: Cut) -> dict[str, list[str]]:
    """What the lock's `applied` record keeps of a cut: the sorted names of the cut skills and roles
    — the units whose copies and bridges the session start and update.py add or remove."""
    return {"skills": sorted(cut.skills), "roles": sorted(cut.roles)}


def recorded_cut(applied: Optional[dict]) -> dict[str, list[str]]:
    """The `cut` part of an `applied` record, well-formed or empty (a record from before this key
    means nothing was cut)."""
    raw = applied.get("cut") if isinstance(applied, dict) else None
    result: dict[str, list[str]] = {"skills": [], "roles": []}
    if isinstance(raw, dict):
        for key in result:
            value = raw.get(key)
            if isinstance(value, list) and all(isinstance(item, str) for item in value):
                result[key] = sorted(value)
    return result


def rule_dest(rel: str) -> str:
    """The key of a cut rule file as exclude spells it: ".act/rules/orchestrator/30-cost.md" ->
    "orchestrator/30-cost.md"."""
    return re.sub(r"^\.act/rules/", "", rel)


def describe(cut: Cut) -> str:
    """The cut in one phrase for the session start: the profile and what the cut takes away, e.g.
    "profile standard — left out: 8 skills, 1 rule file" (counts of what is really left out, so an
    ignored `exclude` entry does not show)."""
    head = f"profile {cut.profile}" + ("" if cut.readable else " (docs/ai/config.md not readable)")
    parts: list[str] = []
    for count, singular in ((len(cut.skills), "skill"), (len(cut.roles), "role"),
                            (len(cut.rules), "rule file"), (len(cut.topics), "topic")):
        if count:
            parts.append(f"{count} {singular}{'' if count == 1 else 's'}")
    return head + (" — left out: " + ", ".join(parts) if parts else "")
