#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Gets a package, reads it and makes it active or inactive: validates a package folder or zip against the
#          template and prints what installing it would do, fetches a package zip with its signature into
#          `.act-local/packages/`, installs a package (`add`) and takes it out again (`remove`). A package brings
#          rules, coding sets, skills, roles, topics, scripts and check modules into a project on the template
#          (format: `.act/formats/package.md`). The safe half of getting one lives here: a zip or folder is copied
#          into a fresh staging folder (`.act-local/packages/.staging/`) after every safety check, its origin is
#          read from a signature (`ssh-keygen -Y verify`, keys in `.act/package-signers`) and `packages-unverified`
#          decides whether an unverified one is admitted. `add` and `remove` always show the plan and a diff of every
#          project file first and write only with an explicit `--yes` and a code; what a package changes is derived
#          by `package_load.py` from the lock's record, so `remove` restores the project byte for byte. Only `add
#          --yes` runs a package's `install.py`; plan, fetch, list, remove and every session-start path never do. It
#          also lists the packages the lock records (`.act-lock.json`, key `packages`, helpers in actlib.py) and the
#          folders resting under `.act-local/packages/`, naming a package that is broken (its folder is missing or a
#          file differs from the lock) with the fix. `settings` shows or sets the answers to the questions of a package's
#          `## settings` section: one row per key in a block of its own below the table of § Packages in
#          docs/ai/config.md (`remove --yes` drops the block, an update drops rows the new version no longer asks).
# Usage:
#   python .act/scripts/packages.py plan <zip|folder>       # stage, check origin and admission, print the plan
#   python .act/scripts/packages.py fetch <id> [--source <place>]   # download zip and signature of a package
#   python .act/scripts/packages.py index [--source <place>] [--json]   # what the first source's index.json lists
#   python .act/scripts/packages.py add <zip|folder|id> [--yes <code>]   # show plan and diff; with --yes install
#   python .act/scripts/packages.py remove <id> [--keep] [--yes <id>]    # show the diff; with --yes take it out
#   python .act/scripts/packages.py list                    # packages in the lock and resting folders
#   python .act/scripts/packages.py settings <id> [<key>=<value> ...]   # show or set a package's settings
# Output format:
#   plan, valid:   a head (package, license, tools, contains-code, sha256, contents), `origin: <state> (<why>)`
#                  and `admitted: yes|no (<why>)`, one line per file (`pre|post|root <path> -> <effect>`), one
#                  line per config line (disables, asks, config line), a closing line saying nothing was
#                  written; exit 0 (the plan is information: `admitted: no` does not change the exit code).
#   plan, refused: `refused: <source>` and one `- <reason>` line per reason (all of them, not only the
#                  first) on stderr; exit 1. The staging folder is removed either way, nothing else is written.
#   fetch:         `fetch: <id> <version> from <source>`, one line per file (wrote, replaced, unchanged) and
#                  `origin: <state> (<why>)`; exit 0. A source that cannot deliver, a refused index or a bad
#                  signature: reasons on stderr, exit 1. A time-out aborts with a message and writes nothing.
#   index:         reads `index.json` of the first source of `packages-sources` (or `--source`) that answers, with the
#                  rules of `fetch` (https or a local folder, no UNC, time and size limits; a bad file is refused and
#                  the next source is tried, a time-out aborts), and prints `index: <source>` and one line per package:
#                  id, version, the mark `active <version>` / `resting` as `list` knows them, and where the index has
#                  them `contents` (first line), `tools`, `stack` and `RED <reason>`; `--json` prints the same as JSON.
#                  Writes nothing. Exit 0, 1 when no source delivers a good index or the lock cannot be read.
#   add:           a bare id is the newest `.act-local/packages/<id>-<version>.zip`, else the resting folder
#                  `.act-local/packages/<id>/` (unverified), else refused naming `fetch`. Without `--yes`: the plan
#                  with origin and admission, with `packages-unverified: scan` the findings of the static scan
#                  (`RED ` lines), `install <id> <version> (new)` or `update <old> -> <new>` with the units an update
#                  drops, the list of project files that change and a unified diff of each (rules.md, skill and role
#                  copies, docs/ai/config.md, .act-lock.json), the line `install exactly this: ... add <source> --yes
#                  <code>` (the code is the first 12 hex digits of the package's sha256) and a closing line saying
#                  nothing was written; exit 0. A refusal (every reason) exits 1. With `--yes <code>`: a wrong code
#                  refuses and writes nothing; the right one moves the staged folder to `.act-local/packages/<id>/`
#                  (an old one moved aside first), sets the check rows, records the lock entry and loads the package
#                  (package_load.sync_packages); a failure on the way puts everything back (exit 1). Then, for
#                  `contains-code: yes` and an `install.py`, it runs it once (time limit 300 s; on a time-out or exit
#                  other than 0 the package stays installed, exit 1, the message names `remove`), and for an
#                  `install.md` it prints one line telling the AI agent to follow it now.
#   remove:        without `--yes`: the file list and diff, the line naming the folder that goes (none with `--keep`)
#                  and `remove exactly this: ... remove <id> --yes <id>`; exit 0. With `--yes <id>`: the check rows
#                  given back, the lock entry dropped, the package unloaded, then the folder deleted (never followed
#                  into a link). Works when the folder is already missing; a folder resting in `.act-local/packages/`
#                  with no lock entry is deleted the same way.
#   list:          one line per package in the lock (id, version, source, check; a broken one adds `broken:` lines and
#                  the fix) and one per resting folder; `no packages` when both are empty. A lock that cannot be
#                  read: reason, exit 1.
#   settings:      without pairs: the keys the package declares with their question and current value (`(not set)` when
#                  there is no row), and the rows of its block that it no longer declares. With `<key>=<value>` pairs:
#                  every key must be one the package's `## settings` declares (read from the hash-checked package.md of
#                  an intact active package) and every value one line without `|`; then each row is written to
#                  docs/ai/config.md (`<key>: <old> -> <new>`), nothing is committed. A refusal names the reason and
#                  writes nothing, exit 1.
# Exit:    0 ok, 1 refused (plan, fetch, index, add, remove, settings) or failed, or lock unreadable (list), 2 usage error
#          or not inside a project.
# Stdlib only.

from __future__ import annotations

import argparse
import contextlib
import difflib
import hashlib
import json
import os
import re
import secrets
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import actlib
import config
import package_load
import package_scan

# Template units that moved into a package keep their name: a new unit with one of these names needs no prefix.
OUTSOURCED_UNITS = {"act-teach", "act-slides"}

ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}\Z")
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)\Z")
REQUIRES_RE = re.compile(r"^>=(\d+)\.(\d+)\.(\d+)\Z")
RULE_ID_RE = re.compile(r"^R-[a-z0-9]+(?:-[a-z0-9]+)+\Z")
SETTING_KEY_RE = re.compile(r"^[a-z][a-z0-9-]*\Z")
CHECK_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*\Z")
UNIT_NAME_RE = re.compile(r"^[a-z][a-z0-9-]*\Z")
MODULE_NAME_RE = re.compile(r"^[a-z_][a-z0-9_]*\Z")
RULE_HEADING_RE = re.compile(r"^##\s+`([^`]+)`")
SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")
LIST_RE = re.compile(r"^-\s+(.*\S)\s*$")
CHECK_ROW_RE = re.compile(r"^\|\s*`([a-z0-9-]+)`\s*\|\s*([^|]*?)\s*\|")
FENCE_RE = re.compile(r"^\s*(```|~~~)")

HEADER_FIELDS = ("id", "version", "requires-template", "tools", "license", "contains-code")
SECTIONS = ("Contents", "disables", "settings", "checks")
SIDES = ("pre-template", "post-template")
SIDE_FOLDERS = ("rules", "coding", "skills", "agents", "topics", "scripts", "hooks")
ROOT_FILES = ("package.md", "install.py", "install.md")
CHECK_VALUES = ("block", "warn", "off")  # the template's own modes
MODE_DEFAULTS = ("block", "warn", "off")  # a check row with another default (a level, a list) takes no on/off/warn
CONTENTS_LINES = 12
LABELS = {"coding": "coding set", "check": "check module"}


def label(kind: str) -> str:
    return LABELS.get(kind, kind)


@dataclass
class Template:
    """What the installed template has: unit names, rule ids, the checks of the skeleton's config and its version."""
    skills: set[str] = field(default_factory=set)
    roles: set[str] = field(default_factory=set)
    coding: set[str] = field(default_factory=set)
    topics: set[str] = field(default_factory=set)
    scripts: set[str] = field(default_factory=set)
    checks: set[str] = field(default_factory=set)
    rules: set[str] = field(default_factory=set)
    check_defaults: dict[str, str] = field(default_factory=dict)
    version: Optional[tuple[int, int, int]] = None
    version_error: str = ""

    def names(self, kind: str) -> set[str]:
        return {"skill": self.skills, "role": self.roles, "coding": self.coding, "topic": self.topics,
                "script": self.scripts, "check": self.checks, "rule": self.rules}[kind]


@dataclass
class Analysis:
    """The result of reading a package folder. `reasons` empty means the package is valid."""
    folder: Path
    reasons: list[str] = field(default_factory=list)
    header: dict[str, str] = field(default_factory=dict)
    contents: str = ""
    disables: list[str] = field(default_factory=list)
    settings: list[tuple[str, str]] = field(default_factory=list)
    checks: list[tuple[str, str]] = field(default_factory=list)
    files: dict[str, str] = field(default_factory=dict)       # package-relative path -> lock_hash of the file
    lines: list[tuple[str, str, str]] = field(default_factory=list)  # (tag, path, effect), in plan order
    units: list[str] = field(default_factory=list)            # "<kind>:<name>", sorted
    extends: list[str] = field(default_factory=list)          # the units that only extend a template unit or rule, sorted

    @property
    def package_id(self) -> str:
        return self.header.get("id", "")


def stable(text: str) -> Optional[tuple[int, int, int]]:
    match = VERSION_RE.match(text.strip())
    return (int(match.group(1)), int(match.group(2)), int(match.group(3))) if match else None



def _stems(folder: Path, suffix: str, skip: tuple[str, ...] = ("README.md",)) -> set[str]:
    if not folder.is_dir():
        return set()
    return {p.stem for p in folder.iterdir() if p.is_file() and p.suffix == suffix and p.name not in skip}


def rule_ids(text: str) -> list[str]:
    """The `## \\`R-...\\`` headings of a rule file, outside code fences, in order (not validated)."""
    found: list[str] = []
    fenced = False
    for raw in text.split("\n"):
        if FENCE_RE.match(raw):
            fenced = not fenced
            continue
        match = None if fenced else RULE_HEADING_RE.match(raw.rstrip())
        if match:
            found.append(match.group(1))
    return found


def read_template(root: Path) -> Template:
    """The template's units and rule ids under `root/.act`, the checks of its skeleton config and the installed
    version (`.act/VERSION`, `version=`). Nothing here raises: a part that cannot be read stays empty."""
    act = root / ".act"
    tpl = Template()
    skills = act / "skills"
    if skills.is_dir():
        tpl.skills = {p.name for p in skills.iterdir() if p.is_dir()}
    tpl.roles = _stems(act / "agents", ".md")
    tpl.coding = _stems(act / "coding", ".md")
    tpl.topics = _stems(act / "rules" / "topics", ".md")
    tpl.scripts = _stems(act / "scripts", ".py")
    tpl.checks = _stems(act / "hooks" / "checks", ".py")
    rules = act / "rules"
    if rules.is_dir():
        for path in sorted(rules.rglob("*.md")):
            try:
                text = path.read_bytes().decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            tpl.rules.update(item for item in rule_ids(text) if RULE_ID_RE.match(item))
    try:
        in_checks = False
        for raw in (act / "skeleton" / "config.md").read_bytes().decode("utf-8").split("\n"):
            if raw.startswith("## "):
                in_checks = raw.strip() == "## Checks"
                continue
            match = CHECK_ROW_RE.match(raw) if in_checks else None
            if match:
                tpl.check_defaults[match.group(1)] = match.group(2)
    except (OSError, UnicodeDecodeError):
        pass
    try:
        for raw in (act / "VERSION").read_bytes().decode("utf-8").splitlines():
            name, _, value = raw.partition("=")
            if name.strip() == "version":
                tpl.version = stable(value)
                if tpl.version is None:
                    tpl.version_error = f"`version={value.strip()}` in .act/VERSION is not X.Y.Z"
        if tpl.version is None and not tpl.version_error:
            tpl.version_error = "no `version=` line in .act/VERSION"
    except (OSError, UnicodeDecodeError) as error:
        tpl.version_error = f"cannot read .act/VERSION: {error}"
    return tpl


def _scan(folder: Path, reasons: list[str]) -> tuple[list[str], list[str]]:
    """Every file and folder below `folder` as `/`-separated relative paths, never entering a link or junction;
    a link, a junction or anything that is no plain file or folder is a reason."""
    files: list[str] = []
    dirs: list[str] = []
    stack: list[tuple[str, Path]] = [("", folder)]
    while stack:
        rel, path = stack.pop()
        try:
            with os.scandir(path) as listing:
                entries = sorted(listing, key=lambda entry: entry.name)
        except OSError as error:
            reasons.append(f"cannot read the folder `{rel or '.'}`: {error}")
            continue
        for entry in entries:
            child = f"{rel}/{entry.name}" if rel else entry.name
            try:
                info = os.lstat(entry.path)
            except OSError as error:
                reasons.append(f"cannot examine `{child}`: {error}")
                continue
            if actlib.is_redirect(info):
                reasons.append(f"`{child}` is a symbolic link or junction; a package holds plain files and folders only")
            elif stat.S_ISDIR(info.st_mode):
                dirs.append(child)
                stack.append((child, Path(entry.path)))
            elif stat.S_ISREG(info.st_mode):
                files.append(child)
            else:
                reasons.append(f"`{child}` is neither a plain file nor a folder")
    return sorted(files), sorted(dirs)


def _read_manifest(folder: Path, tpl: Template, result: Analysis) -> None:
    """Header and sections of package.md into `result`; every fault is a reason."""
    reasons = result.reasons
    try:
        text = actlib.fold_crlf((folder / "package.md").read_bytes()).decode("utf-8")
    except OSError as error:
        reasons.append(f"package.md cannot be read: {error}")
        return
    except UnicodeDecodeError:
        reasons.append("package.md is not UTF-8")
        return
    head, body = actlib.split_header(text)
    fields: dict[str, str] = {}
    if not head.lstrip("﻿").startswith("---"):
        reasons.append("package.md must start with a header between two `---` lines, each line `key: value`")
    else:
        for raw in actlib.frontmatter_lines(text) or []:
            if not raw.strip():
                continue
            key, _, value = raw.partition(":")
            key = key.strip()
            if key in fields:
                reasons.append(f"header field `{key}` appears twice")
            fields[key] = value.strip()
    for name in HEADER_FIELDS:
        if not fields.get(name):
            reasons.append(f"header field `{name}` is missing or empty")
    result.header = {name: fields[name] for name in HEADER_FIELDS if fields.get(name)}
    header = result.header
    if "id" in header and not ID_RE.match(header["id"]):
        reasons.append(f"header field `id` must match ^[a-z][a-z0-9-]{{1,30}}$, got `{header['id']}`")
        del header["id"]
    elif "id" in header and (header["id"] == "act" or header["id"].startswith("act-")):
        reasons.append(f"header field `id` must not be `act` or start with `act-`: that is the template's namespace, got `{header['id']}`")
        del header["id"]
    if "version" in header and not VERSION_RE.match(header["version"]):
        reasons.append(f"header field `version` must read X.Y.Z, got `{header['version']}`")
    if "requires-template" in header:
        match = REQUIRES_RE.match(header["requires-template"])
        if not match:
            reasons.append(f"header field `requires-template` must read `>=X.Y.Z`, got `{header['requires-template']}`")
        elif tpl.version is None:
            reasons.append(f"cannot check `requires-template` ({header['requires-template']}): "
                           f"the installed template version is unreadable ({tpl.version_error})")
        else:
            need = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
            if need > tpl.version:
                have = ".".join(str(n) for n in tpl.version)
                reasons.append(f"the package requires template >={'.'.join(str(n) for n in need)}, "
                               f"the installed template is {have}")
    if "tools" in header:
        names = [actlib.normalize_tool(item) for item in header["tools"].split(",")]
        unknown = [name or "(empty)" for name in names if name not in actlib.KNOWN_TOOLS]
        if unknown:
            reasons.append(f"header field `tools` names unknown tool(s): {', '.join(unknown)} "
                           f"(known: {', '.join(sorted(actlib.KNOWN_TOOLS))})")
        else:
            header["tools"] = ", ".join(names)
    if "contains-code" in header and header["contains-code"] not in ("yes", "no"):
        reasons.append(f"header field `contains-code` must be `yes` or `no`, got `{header['contains-code']}`")

    sections: dict[str, list[str]] = {}
    current: Optional[str] = None
    fenced = False
    for raw in body.split("\n"):
        if FENCE_RE.match(raw):
            fenced = not fenced
        match = None if fenced else SECTION_RE.match(raw.rstrip())
        if match:
            name = match.group(1)
            if name not in SECTIONS:
                reasons.append(f"unknown section `## {name}` (sections: {', '.join('## ' + s for s in SECTIONS)})")
                current = None
            elif name in sections:
                reasons.append(f"section `## {name}` appears twice")
                current = None
            else:
                sections[name] = []
                current = name
            continue
        if current is not None:
            sections[current].append(raw.rstrip())
    result.contents = "\n".join(sections.get("Contents", [])).strip()

    def items(name: str) -> list[str]:
        found: list[str] = []
        for raw in sections.get(name, []):
            line = raw.strip()
            if not line:
                continue
            match = LIST_RE.match(line)
            if match:
                found.append(match.group(1))
            else:
                reasons.append(f"section `## {name}`: `{line[:60]}` is not a list line `- ...`")
        return found

    for rule in items("disables"):
        if not RULE_ID_RE.match(rule):
            reasons.append(f"`## disables`: `{rule}` is not a rule id (R-<area>-<name>)")
        elif rule not in tpl.rules:
            reasons.append(f"`## disables`: `{rule}` is no rule of the installed template")
        elif rule in result.disables:
            reasons.append(f"`## disables`: `{rule}` appears twice")
        else:
            result.disables.append(rule)
    seen: set[str] = set()
    for item in items("settings"):
        key, _, question = item.partition(":")
        key, question = key.strip(), question.strip()
        if not SETTING_KEY_RE.match(key) or not question:
            reasons.append(f"`## settings`: `{item[:60]}` must read `- <key>: <question>` with a key like ^[a-z][a-z0-9-]*$")
        elif header.get("id") and not (key.startswith(header["id"] + "-") and len(key) > len(header["id"]) + 1):
            reasons.append(f"`## settings`: key `{key}` must be named `{header['id']}-<key>`")
        elif key in actlib.CONFIG_SCHEMA or key in tpl.check_defaults:
            reasons.append(f"`## settings`: key `{key}` is a key of the template's docs/ai/config.md; a package setting "
                           "must not share its name with one")
        elif key in seen:
            reasons.append(f"`## settings`: key `{key}` appears twice")
        else:
            seen.add(key)
            result.settings.append((key, question))
    seen = set()
    for item in items("checks"):
        name, _, value = item.partition(":")
        name, value = name.strip(), value.strip()
        if not CHECK_NAME_RE.match(name) or value not in CHECK_VALUES:
            reasons.append(f"`## checks`: `{item[:60]}` must read `- <check>: block|warn|off`")
        elif name not in tpl.check_defaults:
            reasons.append(f"`## checks`: `{name}` is no check of the template's config (.act/skeleton/config.md, section Checks)")
        elif tpl.check_defaults[name] not in MODE_DEFAULTS:
            reasons.append(f"`## checks`: `{name}` takes no block/warn/off value (its template value is `{tpl.check_defaults[name]}`)")
        elif name in seen:
            reasons.append(f"`## checks`: check `{name}` appears twice")
        else:
            seen.add(name)
            result.checks.append((name, value))


def _effect(kind: str, name: str, side: str, tpl: Template, result: Analysis) -> Optional[str]:
    """What a unit does, or None with a reason when it is refused."""
    reasons = result.reasons
    pkg_id = result.package_id
    where = "pre-template" if side == "pre" else "post-template"
    exists = name in tpl.names(kind)
    if kind in ("script", "check"):
        if exists:
            reasons.append(f"{label(kind)} `{name}` has the name of a template {label(kind)}; "
                           "a package does not replace template code")
            return None
    elif exists:
        if kind == "rule":
            if side == "pre":
                own = f"R-{pkg_id}-<name>" if pkg_id else "R-<id>-<name>"
                reasons.append(f"rule `{name}` is a template rule and cannot be defined in {where}/ (its own row would be "
                               f"off, the row of that id is the one `## disables` unchecks): to replace it, list `- {name}` "
                               f"under `## disables` and bring a rule of the package's own id `{own}`; to extend it, "
                               "put the text in post-template/")
                return None
            return f"extends rule {name}"
        if kind == "coding" and side == "pre":
            reasons.append(f"coding set `{name}` is a template coding set: a package cannot cut the template's set yet "
                           f"({where}/ would replace it); put the text in post-template/ to extend it")
            return None
        return f"replaces {label(kind)} {name}" if side == "pre" else f"extends {label(kind)} {name}"
    if not pkg_id:
        return None  # no valid package id: the expected name cannot be told
    if kind not in ("rule", "script", "check") and name in OUTSOURCED_UNITS:
        return f"adds {label(kind)} {name} (template unit moved into a package)"
    if kind == "rule":
        want, ok = f"R-{pkg_id}-<name>", name.startswith(f"R-{pkg_id}-") and len(name) > len(pkg_id) + 3
    elif kind in ("script", "check"):
        underscored = pkg_id.replace("-", "_")
        want, ok = f"{underscored}_<name>", name.startswith(f"{underscored}_") and len(name) > len(underscored) + 1
    else:
        want, ok = f"{pkg_id}-<name>", name.startswith(f"{pkg_id}-") and len(name) > len(pkg_id) + 1
    if not ok:
        reasons.append(f"new {label(kind)} `{name}` must be named `{want}`")
        return None
    return f"adds {label(kind)} {name}"


def analyze(folder: Path, root: Path) -> Analysis:
    """Read and validate the package in `folder` against the template and the lock at `root`. Writes nothing."""
    result = Analysis(folder=folder)
    reasons = result.reasons
    tpl = read_template(root)
    try:
        top = os.lstat(folder)
    except OSError as error:
        reasons.append(f"cannot read the package folder `{folder}`: {error}")
        return result
    if actlib.is_redirect(top):
        reasons.append(f"the package folder `{folder}` is a symbolic link or junction")
        return result
    if not stat.S_ISDIR(top.st_mode):
        reasons.append(f"`{folder}` is not a folder")
        return result
    files, dirs = _scan(folder, reasons)

    # --- layout
    for rel in sorted(set(files) | set(dirs)):
        parts = rel.split("/")
        is_dir = rel in dirs
        if len(parts) == 1:
            if is_dir and parts[0] not in SIDES or not is_dir and parts[0] not in ROOT_FILES:
                reasons.append(f"unknown entry at the package root: `{rel}` "
                               f"(allowed: {', '.join(ROOT_FILES)}, {', '.join(SIDES)})")
        elif parts[0] in SIDES and len(parts) == 2:
            if not is_dir:
                reasons.append(f"`{rel}`: a file directly in {parts[0]}/ (allowed folders: {', '.join(SIDE_FOLDERS)})")
            elif parts[1] not in SIDE_FOLDERS:
                reasons.append(f"unknown folder `{rel}` (allowed: {', '.join(SIDE_FOLDERS)})")
        elif parts[0] in SIDES and parts[1] == "hooks" and len(parts) == 3:
            if not is_dir or parts[2] != "checks":
                reasons.append(f"`{rel}`: hooks/ holds only the folder `checks`")
    if "package.md" not in files:
        reasons.append("package.md is missing")
    else:
        _read_manifest(folder, tpl, result)

    # --- units
    owners: dict[str, tuple[str, list[str], Optional[str]]] = {}   # "<kind>:<name>" -> (side tag, files, effect)
    placed: dict[str, list[str]] = {}                # file -> effects
    for rel in files:
        parts = rel.split("/")
        if len(parts) < 3 or parts[0] not in SIDES or parts[1] not in SIDE_FOLDERS:
            continue
        side, tag, folder_name = parts[0], parts[0].split("-")[0], parts[1]
        units: list[tuple[str, str]] = []  # (kind, name) this file belongs to
        if folder_name == "skills":
            if len(parts) < 4:
                reasons.append(f"`{rel}`: skills/ holds one folder per skill")
            elif not UNIT_NAME_RE.match(parts[2]):
                reasons.append(f"`{rel}`: skill name `{parts[2]}` must match ^[a-z][a-z0-9-]*$")
            else:
                units.append(("skill", parts[2]))
        elif folder_name in ("coding", "agents", "topics", "rules"):
            if len(parts) != 3 or not parts[2].endswith(".md"):
                reasons.append(f"`{rel}`: {folder_name}/ holds .md files directly in it only")
            elif folder_name == "rules":
                try:
                    ids = rule_ids(actlib.fold_crlf((folder / rel).read_bytes()).decode("utf-8"))
                except (OSError, UnicodeDecodeError) as error:
                    reasons.append(f"`{rel}` cannot be read as UTF-8 text: {error}")
                    continue
                if not ids:
                    reasons.append(f"`{rel}` has no rule heading (## `R-<area>-<name>` — Title)")
                for item in ids:
                    if not RULE_ID_RE.match(item):
                        reasons.append(f"`{rel}`: heading `{item}` is not a rule id (R-<area>-<name>)")
                    else:
                        units.append(("rule", item))
            elif not UNIT_NAME_RE.match(parts[2][:-3]):
                reasons.append(f"`{rel}`: name `{parts[2][:-3]}` must match ^[a-z][a-z0-9-]*$")
            else:
                units.append(({"coding": "coding", "agents": "role", "topics": "topic"}[folder_name], parts[2][:-3]))
        elif folder_name == "scripts" or (folder_name == "hooks" and len(parts) > 2 and parts[2] == "checks"):
            depth = 3 if folder_name == "scripts" else 4
            if len(parts) != depth or not parts[-1].endswith(".py"):
                reasons.append(f"`{rel}`: {'scripts' if depth == 3 else 'hooks/checks'}/ holds .py files directly in it only")
            elif not MODULE_NAME_RE.match(parts[-1][:-3]):
                reasons.append(f"`{rel}`: module name `{parts[-1][:-3]}` must match ^[a-z_][a-z0-9_]*$")
            else:
                units.append(("script" if depth == 3 else "check", parts[-1][:-3]))
        else:
            reasons.append(f"`{rel}`: hooks/ holds only the folder `checks`")
        for kind, name in units:
            key = f"{kind}:{name}"
            if key not in owners:
                owners[key] = (tag, [rel], _effect(kind, name, tag, tpl, result))
                continue
            other_tag, members, _ = owners[key]
            if other_tag != tag:
                message = f"{label(kind)} `{name}` is brought by both pre-template/ and post-template/"
            elif kind == "rule":
                message = f"rule `{name}` is defined more than once (`{members[0]}` and `{rel}`)"
            else:
                message = ""
                if rel not in members:
                    members.append(rel)
            if message and message not in reasons:
                reasons.append(message)
    for key, (tag, members, effect) in sorted(owners.items()):
        for rel in members:
            placed.setdefault(rel, []).append(effect or "refused (see reasons)")
        if key.startswith("skill:") and f"{tag}-template/skills/{key[6:]}/SKILL.md" not in files:
            reasons.append(f"skill `{key[6:]}` has no SKILL.md")

    # --- code
    header = result.header
    code_paths = [rel for rel in files if rel == "install.py"
                  or (len(rel.split("/")) > 2 and (rel.split("/")[1] == "scripts"
                                                    or rel.split("/")[1:3] == ["hooks", "checks"]))]
    if header.get("contains-code") == "no" and code_paths:
        reasons.append("`contains-code: no` but the package holds code: " + ", ".join(code_paths[:5])
                       + (f" (+{len(code_paths) - 5} more)" if len(code_paths) > 5 else ""))

    # --- other packages in the lock
    mine = {key for key in owners}
    my_extends = {key for key, (_, _, effect) in owners.items() if effect and effect.startswith("extends")}
    if result.package_id:
        for other, entry in sorted(actlib.read_packages(root).items()):
            if other == result.package_id:
                continue
            brought = {u for u in entry.get("units", []) if isinstance(u, str)} if isinstance(entry.get("units"), list) else set()
            extended = {u for u in entry.get("extends", []) if isinstance(u, str)} if isinstance(entry.get("extends"), list) else set()
            for key in sorted(mine & brought):
                if key in my_extends and key in extended:
                    continue  # two extensions of the same template unit or rule: both are appended
                kind, _, name = key.partition(":")
                reasons.append(f"{label(kind)} `{name}` is already brought by package `{other}`")

    # --- files, plan lines and the package's own units
    for rel in files:
        try:
            result.files[rel] = actlib.lock_hash((folder / rel).read_bytes())
        except OSError as error:
            reasons.append(f"`{rel}` cannot be read: {error}")
    result.units = sorted(owners)
    result.extends = sorted(my_extends)
    for rel in files:
        parts = rel.split("/")
        if len(parts) == 1 and rel in ROOT_FILES:
            result.lines.append(("root", rel, {"package.md": "the package description (header and sections)",
                                               "install.py": "runs once at install, after the files are in place",
                                               "install.md": "the AI-guided setup, read after the install"}[rel]))
    for side in SIDES:
        for rel in files:
            parts = rel.split("/")
            if parts[0] == side and rel in placed:
                result.lines.append((side.split("-")[0], "/".join(parts[1:]), "; ".join(placed[rel])))
    return result


def lock_entry(result: Analysis, source: str, check: str) -> dict:
    """The record for the lock's `packages` key (see actlib.merge_package) from a valid analysis. Nothing calls
    this to write yet: it fixes the shape. `units` is what a later install collides on, `extends` the part of it that only extends a template unit or rule (rule ids are not
    in a file path); `config` holds the check lines the package sets."""
    return {"version": result.header.get("version", ""), "source": source, "sha256": actlib.package_hash(result.files),
            "check": check, "files": dict(sorted(result.files.items())), "units": list(result.units), "extends": list(result.extends),
            "config": [f"{name}: {value}" for name, value in result.checks]}


PLAN_CLOSING = "plan only: nothing was written into the project"


def render_plan(result: Analysis, origin_lines: Optional[list[str]] = None, closing: Optional[str] = PLAN_CLOSING) -> list[str]:
    header = result.header
    out = [f"package: {header.get('id', '?')} {header.get('version', '?')}",
           f"license: {header.get('license', '?')}",
           f"tools: {header.get('tools', '?')}",
           f"contains-code: {header.get('contains-code', '?')}",
           f"requires-template: {header.get('requires-template', '?')}",
           f"sha256: {actlib.package_hash(result.files)}"]
    if result.contents:
        text = result.contents.split("\n")
        out.append("contents:")
        out += [f"  {line}" if line else "" for line in text[:CONTENTS_LINES]]
        if len(text) > CONTENTS_LINES:
            out.append(f"  ... (+{len(text) - CONTENTS_LINES} more lines)")
    out += origin_lines or []
    out.append("files:")
    out += [f"  {tag:<4} {path} -> {effect}" for tag, path, effect in result.lines]
    out.append("config:")
    config: list[str] = [f"  disables rule {rule}" for rule in result.disables]
    config += [f"  asks {key}: {question}" for key, question in result.settings]
    config += [f"  config line `{name}: {value}` (from package {header.get('id', '?')})" for name, value in result.checks]
    out += config or ["  (none)"]
    if closing:
        out.append(closing)
    return out


# --- fetch, staging and origin: the safe half of getting a package ------------------------------------------------
# Nothing here activates a package: a zip or a folder is copied into a fresh staging folder after every safety
# check, its origin is read from a signature, and `packages-unverified` decides whether an unverified one is admitted.

STAGING_PARTS = (".act-local", "packages", ".staging")
STAGING_MAX_AGE = 24 * 60 * 60  # seconds a staging folder may stay before `prune_staging` removes it
WINDOWS_DEVICES = frozenset(["con", "prn", "aux", "nul"] + [f"com{n}" for n in range(1, 10)] + [f"lpt{n}" for n in range(1, 10)])
MAX_ENTRIES = 2000
MAX_BYTES = 50 * 1024 * 1024
MAX_INDEX_BYTES = 1024 * 1024
NET_TIMEOUT = 30        # seconds one network operation may take
NET_DEADLINE = 120      # seconds a whole download may take
VERIFY_TIMEOUT = 20     # seconds ssh-keygen may take
SIGNERS_FILE = ".act/package-signers"
LOCAL_SIGNERS_FILE = "docs/ai/local/package-signers"  # the project's own keys, same form; never part of the template
SIGNERS_IDENTITY = "act-packages"
SIGNATURE_NAMESPACE = "act-package"
DEFAULT_SOURCES = "https://github.com/wrufeger/act-packages/releases/latest/download/"
DRIVE_RE = re.compile(r"^[A-Za-z]:")
SCHEME_RE = re.compile(r"^([A-Za-z][A-Za-z0-9+.-]*)://")
FILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*\Z")
REPARSE_ATTRIBUTE = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT in the low bits of a zip entry's external attributes
REASON_LIMIT = 20


class PackageRefused(Exception):
    """A zip, folder, index or download that is refused; `reasons` names each entry and why, none is written."""

    def __init__(self, reasons: "list[str] | str") -> None:
        self.reasons = [reasons] if isinstance(reasons, str) else list(reasons)
        super().__init__("; ".join(self.reasons))


class FetchTimeout(Exception):
    """A network operation ran past its time limit: the fetch is aborted, nothing is retried or written."""


class StageTimeout(Exception):
    """The time a caller gave `stage` ran out while it unpacked: the staging folder is removed, nothing is kept."""


@dataclass
class Staged:
    """A package copied into a fresh staging folder: `staging` is that folder, `folder` the package folder inside
    it, `source` what was given (as text), `zip_path` the zip it came from (None for a folder). `copy` is the one
    copy of that zip made in the staging folder (with its `.sig` next to it, when there is one): the signature is
    verified on it (origin(staged.copy, ...)) and the package is unpacked from it, so what is verified is what is read.
    `base` is the `.staging` folder `staging` was made in and `created` the folders made on the way, removed again
    by `discard`."""
    staging: Path
    folder: Path
    source: str
    zip_path: Optional[Path]
    base: Optional[Path] = None
    created: list[Path] = field(default_factory=list)
    copy: Optional[Path] = None


def _shown(name: str) -> str:
    """A name from a zip or an index as text a message can carry: printable ASCII, escapes for the rest."""
    return "`" + name.encode("ascii", "backslashreplace").decode("ascii") + "`"


def _make_staging(root: Path) -> tuple[Path, Path, list[Path]]:
    """A fresh folder `<root>/.act-local/packages/.staging/<random>/`: (it, the `.staging` folder, the folders made on
    the way). A folder on the way that is a link or no folder is refused."""
    created: list[Path] = []
    current = root
    for part in STAGING_PARTS:
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            try:
                os.mkdir(current)
            except OSError as error:
                _remove_empty(created)
                raise PackageRefused(f"cannot make the staging folder `{current}`: {error}")
            created.append(current)
            continue
        except OSError as error:
            raise PackageRefused(f"cannot examine `{current}`: {error}")
        if actlib.is_redirect(info) or not stat.S_ISDIR(info.st_mode):
            _remove_empty(created)
            raise PackageRefused(f"`{current}` is a link or no folder; the staging folder is made in a plain one")
    for _ in range(20):
        path = current / secrets.token_hex(8)
        try:
            os.mkdir(path)
        except FileExistsError:
            continue
        except OSError as error:
            _remove_empty(created)
            raise PackageRefused(f"cannot make the staging folder `{path}`: {error}")
        return path, current, created
    _remove_empty(created)
    raise PackageRefused(f"cannot find a free name for a staging folder in `{current}`")


def _remove_empty(folders: list[Path]) -> None:
    """Remove the folders (last made first) that are empty; one that is not stays."""
    for folder in reversed(folders):
        try:
            if actlib.is_redirect(os.lstat(folder)):
                continue
            os.rmdir(folder)
        except OSError:
            pass


def _drop_link(path: str) -> None:
    """Remove a link or junction itself, never what it points to."""
    try:
        os.unlink(path)
    except OSError:
        os.rmdir(path)


def _remove_tree(path: Path) -> None:
    """Delete the folder `path` and everything below it with the language's own calls: a link or junction below it
    is removed itself and never entered; a read-only file is made writable first."""
    info = os.lstat(path)
    if actlib.is_redirect(info) or not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"`{path}` is a link or no folder; not removed")
    stack: list[tuple[str, bool]] = [(str(path), False)]
    while stack:
        current, visited = stack.pop()
        if visited:
            os.rmdir(current)
            continue
        stack.append((current, True))
        with os.scandir(current) as listing:
            entries = list(listing)
        for entry in entries:
            child = os.lstat(entry.path)
            if actlib.is_redirect(child):
                _drop_link(entry.path)
            elif stat.S_ISDIR(child.st_mode):
                stack.append((entry.path, False))
            else:
                try:
                    os.unlink(entry.path)
                except PermissionError:
                    os.chmod(entry.path, stat.S_IWRITE)
                    os.unlink(entry.path)


def discard(staged: Staged) -> None:
    """Remove exactly the staging folder recorded at creation, after checking that every part from `.act-local` down
    to it is still a folder and no link or junction, then the folders `stage` made on the way when they are
    empty again. Missing is fine; anything else that is not the recorded place is left alone and refused."""
    path = staged.staging
    base = staged.base
    if base is None or path.parent != base or base.name != STAGING_PARTS[2] or base.parent.name != STAGING_PARTS[1] \
            or base.parent.parent.name != STAGING_PARTS[0] or not re.fullmatch(r"[0-9a-f]{16}", path.name):
        raise ValueError(f"discard: `{path}` is not a folder made by stage() below `.act-local/packages/.staging/`")
    for step in (base.parent.parent, base.parent, base, path):  # `.act-local`, `packages`, `.staging`, the folder
        try:
            info = os.lstat(step)
        except FileNotFoundError:
            _remove_empty(staged.created)
            return  # nothing below a missing part: nothing to remove
        if actlib.is_redirect(info) or not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"discard: `{step}` is a link or no folder now; left alone")
    _remove_tree(path)
    _remove_empty(staged.created)


def prune_staging(root: Path, max_age: float = STAGING_MAX_AGE, now: Optional[float] = None) -> list[str]:
    """Remove the folders below `<root>/.act-local/packages/.staging/` that are older than `max_age` seconds (what a
    run that was cut off left behind); returns the names removed. Never raises: what cannot be removed stays for the
    next time. The path is followed part by part from `root` and every part from `.act-local` down to `.staging` must
    be a plain folder, no link or junction; below it only a plain folder named like the ones `stage` makes (16 hex
    digits) is looked at, a link, a file or any other name is left alone, and a link inside a folder is removed
    itself and never entered."""
    current = Path(root)
    for part in STAGING_PARTS:
        current = current / part
        try:
            info = os.lstat(current)
        except OSError:
            return []
        if actlib.is_redirect(info) or not stat.S_ISDIR(info.st_mode):
            return []
    limit = (time.time() if now is None else now) - max_age
    try:
        names = sorted(os.listdir(current))
    except OSError:
        return []
    removed: list[str] = []
    for name in names:
        if not re.fullmatch(r"[0-9a-f]{16}", name):
            continue
        path = current / name
        try:
            info = os.lstat(path)
            if actlib.is_redirect(info) or not stat.S_ISDIR(info.st_mode) or info.st_mtime >= limit:
                continue
            _remove_tree(path)
        except (OSError, ValueError):
            continue
        removed.append(name)
    return removed


def _bad_part(part: str) -> str:
    """Why a path part cannot be written on every system, "" when it can: a `:` (an NTFS alternate data stream, a
    drive) or a Windows device name (`con`, `prn`, `aux`, `nul`, `com1`-`com9`, `lpt1`-`lpt9`), with or without an
    extension, in any case, with trailing dots or blanks (which Windows drops)."""
    if ":" in part:
        return "a `:` in a name (an NTFS stream or drive)"
    if part.rstrip(" .").split(".")[0].rstrip(" ").lower() in WINDOWS_DEVICES:
        return "a Windows device name (con, prn, aux, nul, com1-9, lpt1-9) in a name"
    return ""


def _zip_entries(zf: zipfile.ZipFile) -> tuple[list[tuple[zipfile.ZipInfo, str, bool]], str]:
    """Read every entry of the zip, extract none: (entry, normalized name, is a folder) per entry and the package
    root inside the zip (`""` or `"<top>/"`). Every entry that is refused gives a reason naming it."""
    infos = zf.infolist()
    reasons: list[str] = []
    if len(infos) > MAX_ENTRIES:
        raise PackageRefused(f"the zip holds {len(infos)} entries, more than {MAX_ENTRIES}")
    total = 0
    seen: dict[str, str] = {}
    entries: list[tuple[zipfile.ZipInfo, str, bool]] = []
    for info in infos:
        name = info.orig_filename  # as stored: zipfile turns a backslash into `/` in `filename` on Windows
        shown = _shown(name)
        is_dir = name.endswith("/")
        parts = (name[:-1] if is_dir else name).split("/")
        reason = ""
        if "\\" in name:
            reason = "a backslash in the name"
        elif name.startswith("/"):
            reason = "an absolute path"
        elif DRIVE_RE.match(parts[0]):
            reason = "a drive letter"
        elif ".." in parts:
            reason = "a `..` part"
        elif "" in parts:
            reason = "an empty part"
        elif any(_bad_part(part) for part in parts):
            reason = next(_bad_part(part) for part in parts if _bad_part(part))
        else:
            mode = info.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or info.external_attr & REPARSE_ATTRIBUTE:
                reason = "a symbolic link or another entry that is no plain file or folder"
            elif (is_dir and kind == stat.S_IFREG) or (not is_dir and kind == stat.S_IFDIR):
                reason = "a type that does not match its name (file or folder)"
            elif info.flag_bits & 0x1:
                reason = "an encrypted entry"
        if reason:
            reasons.append(f"entry {shown} refused: {reason}")
            continue
        normal = [part for part in parts if part != "."]
        if not normal:
            continue  # `./`: the root itself
        key = "/".join(normal).lower()
        if key in seen:
            reasons.append(f"entry {shown} refused: two names equal ignoring case ({_shown(seen[key])})")
            continue
        seen[key] = name
        total += 0 if is_dir else info.file_size
        entries.append((info, "/".join(normal), is_dir))
    if total > MAX_BYTES:
        reasons.append(f"the zip holds {total} bytes uncompressed, more than {MAX_BYTES}")
    file_keys = {norm.lower() for _, norm, is_dir in entries if not is_dir}
    for _, norm, _ in entries:
        parts = norm.split("/")
        for count in range(1, len(parts)):
            if "/".join(parts[:count]).lower() in file_keys:
                reasons.append(f"entry {_shown(norm)} refused: it lies below the file `{'/'.join(parts[:count])}`")
                break
    if not reasons:
        files = {norm for _, norm, is_dir in entries if not is_dir}
        tops = {norm.split("/")[0] for _, norm, _ in entries}
        if "package.md" in files:
            return entries, ""
        if len(tops) == 1 and f"{next(iter(tops))}/package.md" in files:
            return entries, next(iter(tops)) + "/"
        reasons.append("no `package.md` at the zip root or in its one top folder")
    raise PackageRefused(reasons[:REASON_LIMIT] + ([f"... and {len(reasons) - REASON_LIMIT} more"]
                                                  if len(reasons) > REASON_LIMIT else []))


def _extract_zip(zf: zipfile.ZipFile, entries: list[tuple[zipfile.ZipInfo, str, bool]], target: Path,
                 time_left: Optional[Callable[[], float]] = None) -> None:
    """Write the checked entries below `target`; the total written stops at MAX_BYTES whatever the zip declared. A
    folder that cannot be made is a refusal of the entry like a file that cannot be written. `time_left` (a call that
    gives the seconds left) is looked at before each entry and each chunk: below zero the extraction stops with
    StageTimeout, and the caller removes what was written."""
    top = target.resolve()
    written = 0
    for info, norm, is_dir in entries:
        if time_left is not None and time_left() < 0:
            raise StageTimeout(f"the time ran out while unpacking before entry {_shown(norm)}")
        dest = target.joinpath(*norm.split("/"))
        if top not in dest.resolve().parents:
            raise PackageRefused(f"entry {_shown(norm)} refused: it would be written outside the staging folder")
        try:
            (dest if is_dir else dest.parent).mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise PackageRefused(f"entry {_shown(norm)} cannot be created ({error.__class__.__name__}): {error}")
        if is_dir:
            continue
        try:
            with zf.open(info) as source, open(dest, "xb") as out:
                while True:
                    if time_left is not None and time_left() < 0:
                        raise StageTimeout(f"the time ran out while unpacking entry {_shown(norm)}")
                    chunk = source.read(65536)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > MAX_BYTES:
                        raise PackageRefused(f"the zip gives more than {MAX_BYTES} bytes uncompressed; extraction stopped")
                    out.write(chunk)
        except (zipfile.BadZipFile, NotImplementedError, RuntimeError, OSError, EOFError, zlib.error) as error:
            raise PackageRefused(f"entry {_shown(norm)} cannot be read: {error}")


def _folder_files(source: Path) -> tuple[list[str], list[str]]:
    """The files and folders of the package folder `source`, relative with `/`, each refused thing a reason: a link or
    junction anywhere, an entry that is no plain file or folder, more than MAX_ENTRIES entries or MAX_BYTES bytes."""
    try:
        info = os.lstat(source)
    except OSError as error:
        raise PackageRefused(f"cannot read `{source}`: {error}")
    reasons: list[str] = []
    if actlib.is_redirect(info):
        raise PackageRefused(f"`{source}` is a symbolic link or junction; a package holds plain files and folders only")
    files, dirs = _scan(source, reasons)
    if not reasons:
        for rel in sorted(set(files) | set(dirs)):
            for part in rel.split("/"):
                if _bad_part(part):
                    reasons.append(f"`{rel}` refused: {_bad_part(part)}")
                    break
        if len(files) + len(dirs) > MAX_ENTRIES:
            reasons.append(f"the folder holds {len(files) + len(dirs)} entries, more than {MAX_ENTRIES}")
        size = 0
        for rel in files:
            try:
                size += os.lstat(source / rel).st_size
            except OSError as error:
                reasons.append(f"cannot examine `{rel}`: {error}")
        if size > MAX_BYTES:
            reasons.append(f"the folder holds {size} bytes, more than {MAX_BYTES}")
    if reasons:
        raise PackageRefused(reasons[:REASON_LIMIT])
    return files, dirs


def _is_unc(text: str) -> bool:
    """Whether a place is a UNC path (`\\\\host\\share`, `//host/share`): reaching it would open a network share."""
    return text.startswith(("\\\\", "//"))


def _unc_reason(place: str) -> str:
    return (f"`{place}` is a UNC path (a network share); a package comes from a local folder or file, "
            "copy it to a local disk first")


def _copy_plain(source: Path, dest: Path, budget: int, over: str) -> int:
    """Copy the plain file `source` to the new file `dest`, counting the bytes actually copied: more than `budget`
    refuses with `over`. A link in place of the file (never followed where the system can say so) or anything but a
    regular file is refused. Returns the bytes copied."""
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(source, flags)
    except OSError as error:
        raise PackageRefused(f"cannot read `{source.name}`: {error}")
    written = 0
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise PackageRefused(f"`{source.name}` is no plain file")
        try:
            with open(dest, "xb") as out:
                while True:
                    chunk = handle.read(65536)
                    if not chunk:
                        break
                    written += len(chunk)
                    if written > budget:
                        raise PackageRefused(over)
                    out.write(chunk)
        except OSError as error:
            raise PackageRefused(f"cannot copy `{source.name}`: {error}")
    return written


def stage(source: Path, root: Path, time_left: Optional[Callable[[], float]] = None) -> Staged:
    """A zip or a folder copied or unpacked into a fresh `.act-local/packages/.staging/<random>/` of the project `root`,
    after every safety check (a refused zip or folder raises PackageRefused with a reason per entry and writes
    nothing, the staging folder included). A zip is copied once into the staging folder (`zip/package.zip`, its `.sig`
    next to it); every check and the unpacking read that copy, and `origin(staged.copy, root)` verifies it, so what is
    verified is what is installed. Refused are an absolute path, a drive letter, a `:` or Windows device name in a
    part, a `..` part, a backslash, an empty part, a symbolic link or any other entry that is no plain file or
    folder, two names equal ignoring case, more than MAX_ENTRIES entries or MAX_BYTES bytes, and a zip whose
    `package.md` is neither at its root nor in its one top folder. A folder is refused for a link or junction
    anywhere, the same names and the same limits, the bytes counted as they are copied. A UNC path is refused before
    anything is opened. The package is below `package/` in the staging folder. With `time_left` (a call that gives
    the seconds left) the unpacking of a zip stops when it is below zero: the staging folder is removed and
    StageTimeout raised, never a partly unpacked package left behind. The caller removes the staging with
    `discard(staged)`, in a `finally`."""
    if _is_unc(str(source)):
        raise PackageRefused(_unc_reason(str(source)))
    source = Path(source)
    try:
        info = os.lstat(source)
    except OSError as error:
        raise PackageRefused(f"cannot read the package folder `{source}` (a folder or a zip is expected): {error}")
    if actlib.is_redirect(info):
        raise PackageRefused(f"`{source}` is a symbolic link or junction; a package holds plain files and folders only")
    if stat.S_ISDIR(info.st_mode):
        files, dirs = _folder_files(source)
        staging, base, created = _make_staging(root)
        staged = Staged(staging, staging / "package", str(source), None, base, created)
        try:
            (staging / "package").mkdir()
            for rel in dirs:
                (staging / "package" / rel).mkdir(parents=True, exist_ok=True)
            copied = 0
            for rel in files:
                copied += _copy_plain(source / rel, staging / "package" / rel, MAX_BYTES - copied,
                                      f"the folder holds more than {MAX_BYTES} bytes (counted while copying)")
        except BaseException:
            discard(staged)
            raise
        return staged
    if not stat.S_ISREG(info.st_mode):
        raise PackageRefused(f"`{source}` is neither a zip file nor a folder")
    staging, base, created = _make_staging(root)
    staged = Staged(staging, staging / "package", str(source), source, base, created)
    try:
        (staging / "zip").mkdir()
        copy = staging / "zip" / "package.zip"
        _copy_plain(source, copy, MAX_BYTES, f"the zip file is larger than {MAX_BYTES} bytes")
        staged.copy = copy
        sig = Path(str(source) + ".sig")
        try:
            sig_info = os.lstat(sig)
        except OSError:
            sig_info = None
        if sig_info is not None and stat.S_ISREG(sig_info.st_mode) and not actlib.is_redirect(sig_info):
            _copy_plain(sig, Path(str(copy) + ".sig"), MAX_INDEX_BYTES, f"the signature file is larger than {MAX_INDEX_BYTES} bytes")
        try:
            archive = zipfile.ZipFile(copy)
        except (zipfile.BadZipFile, OSError) as error:
            raise PackageRefused(f"`{source}` is not a readable zip file: {error}")
        with archive:
            entries, prefix = _zip_entries(archive)
            (staging / "package").mkdir()
            _extract_zip(archive, entries, staging / "package", time_left)
        if prefix:
            staged.folder = staging.joinpath("package", *prefix.strip("/").split("/"))
    except BaseException:
        discard(staged)
        raise
    return staged


def _signers_have_key(path: Path) -> bool:
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return any(line.strip() and not line.lstrip().startswith("#") for line in text.splitlines())


def _find_program(name: str) -> Optional[str]:
    """`name` found in the absolute entries of PATH only, never the current folder or another relative entry (on
    Windows `shutil.which` looks in the current folder first, so a program a package left there would run). On
    Windows the extensions of PATHEXT are tried."""
    extensions = [""]
    if os.name == "nt":
        extensions = [ext.lower() for ext in os.environ.get("PATHEXT", ".EXE;.CMD;.BAT").split(";") if ext] or [".exe"]
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        entry = entry.strip().strip('"')
        if not entry or not os.path.isabs(entry):
            continue
        for extension in extensions:
            candidate = os.path.join(entry, name + extension)
            if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
    return None


def origin(zip_path: Optional[Path], root: Path, label: Optional[str] = None) -> tuple[str, str]:
    """Who vouches for a package zip: `("verified" | "unverified" | "bad", reason)`. `verified` only when
    `ssh-keygen -Y verify` (identity `act-packages`, namespace `act-package`, the keys of `.act/package-signers` and
    of the project's own `docs/ai/local/package-signers`, a key line of either may verify) accepts `<zip>.sig` for
    the zip (exit 0); `bad` when a `.sig` exists, a key is installed and verification fails;
    `unverified` for a folder (no zip), no `.sig`, no key line in either signers file, no `ssh-keygen`, or a time-out
    of it (never a pass). `ssh-keygen` is looked for in the absolute entries of PATH only. The program runs with an
    argument list, no shell, and a time limit. `label` is the name a message gives the signature file (default: its
    own name), for a copy that lies under another name."""
    if zip_path is None or not Path(zip_path).is_file():
        return "unverified", "a folder carries no signature (only a zip does)"
    zip_path = Path(zip_path)
    sig = Path(str(zip_path) + ".sig")
    if not sig.is_file():
        return "unverified", f"no signature file `{(label or zip_path.name) + '.sig'}` next to the zip"
    signers = [root / name for name in (SIGNERS_FILE, LOCAL_SIGNERS_FILE) if _signers_have_key(root / name)]
    if not signers:
        return "unverified", (f"no key line in `{SIGNERS_FILE}` or `{LOCAL_SIGNERS_FILE}` (they hold comments only or "
                              f"are missing)")
    program = _find_program("ssh-keygen")
    if program is None:
        return "unverified", "ssh-keygen was not found in PATH"
    failure = ""
    for signers_file in signers:  # a key line of either file may verify the signature
        command = [program, "-Y", "verify", "-f", str(signers_file), "-I", SIGNERS_IDENTITY, "-n", SIGNATURE_NAMESPACE,
                   "-s", str(sig)]
        try:
            with open(zip_path, "rb") as stream:
                done = subprocess.run(command, stdin=stream, capture_output=True, text=True, encoding="utf-8",
                                      errors="replace", timeout=VERIFY_TIMEOUT)
        except subprocess.TimeoutExpired:
            return "unverified", f"ssh-keygen timed out after {VERIFY_TIMEOUT} s"
        except OSError as error:
            return "unverified", f"ssh-keygen could not run: {error}"
        lines = [line.strip() for line in (done.stdout + "\n" + done.stderr).splitlines() if line.strip()]
        if done.returncode == 0:
            return "verified", lines[0] if lines else "the signature verifies"
        failure = failure or ("the signature does not verify" + (f": {lines[0]}" if lines else ""))
    return "bad", failure


def admission(state: str, root: Path) -> tuple[bool, str]:
    """Whether a package with this origin state is admitted, and why: `verified` yes; `bad` no in every mode;
    `unverified` by `packages-unverified` (`block` no, `scan` yes with the note "scan required", `allow` yes with a
    warning; an unknown value counts as `block`)."""
    if state == "verified":
        return True, "verified signature"
    if state == "bad":
        return False, "the signature does not verify; refused in every mode"
    if state != "unverified":
        return False, f"unknown origin state `{state}`"
    mode = actlib.read_config(root).get("packages-unverified", "block").strip("`").strip().lower()
    if mode == "scan":
        return True, "unverified; scan required (packages-unverified: scan)"
    if mode == "allow":
        return True, "warning: unverified, admitted because packages-unverified is allow"
    if mode == "block":
        return False, "unverified and packages-unverified is block"
    return False, f"unverified and packages-unverified `{mode}` is unknown, which counts as block"


class _HttpsOnly(urllib.request.HTTPRedirectHandler):
    """Follows a redirect only to an `https://` address."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001 - urllib's signature
        if not newurl.lower().startswith("https://"):
            raise PackageRefused(f"a redirect leads to `{newurl}`; only https:// addresses are followed")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _response_socket(response: object) -> Optional[socket.socket]:
    """The socket under an http.client response, to set its time limit; None when it cannot be reached."""
    try:
        sock = response.fp.raw._sock  # type: ignore[attr-defined]  # no public way to it
    except AttributeError:
        return None
    return sock if hasattr(sock, "settimeout") else None


def _http_get(url: str, limit: int) -> bytes:
    """The body of an `https://` address, at most `limit` bytes, within NET_TIMEOUT per operation and NET_DEADLINE
    in all: before each read the socket's time limit is set to the time left (at most NET_TIMEOUT), so a server
    sending one byte at a time cannot hold the call past the deadline (FetchTimeout); anything that is no success
    is a PackageRefused naming the address."""
    opener = urllib.request.build_opener(_HttpsOnly)
    request = urllib.request.Request(url, headers={"User-Agent": "act-packages-fetch"})
    started = time.monotonic()

    def late() -> FetchTimeout:
        if time.monotonic() - started >= NET_DEADLINE - 0.5:
            return FetchTimeout(f"`{url}` took longer than {NET_DEADLINE} s")
        return FetchTimeout(f"`{url}` did not answer within {NET_TIMEOUT} s")

    try:
        with opener.open(request, timeout=NET_TIMEOUT) as response:
            length = response.headers.get("Content-Length", "")
            if length.isdigit() and int(length) > limit:
                raise PackageRefused(f"`{url}` announces {length} bytes, more than {limit}")
            sock = _response_socket(response)
            data = bytearray()
            while True:
                left = NET_DEADLINE - (time.monotonic() - started)
                if left <= 0:
                    raise FetchTimeout(f"`{url}` took longer than {NET_DEADLINE} s")
                if sock is not None:
                    sock.settimeout(min(NET_TIMEOUT, left))
                chunk = response.read1(65536)
                if not chunk:
                    break
                data += chunk
                if len(data) > limit:
                    raise PackageRefused(f"`{url}` gives more than {limit} bytes")
    except urllib.error.HTTPError as error:
        raise PackageRefused(f"`{url}` answered HTTP {error.code}")
    except urllib.error.URLError as error:
        if isinstance(error.reason, (TimeoutError, socket.timeout)):
            raise late()
        raise PackageRefused(f"`{url}` cannot be reached: {error.reason}")
    except (TimeoutError, socket.timeout):
        raise late()
    except OSError as error:
        raise PackageRefused(f"`{url}` cannot be read: {error}")
    return bytes(data)


def _local_get(path: Path, limit: int) -> bytes:
    try:
        info = os.lstat(path)
    except OSError as error:
        raise PackageRefused(f"cannot read `{path}`: {error}")
    if actlib.is_redirect(info) or not stat.S_ISREG(info.st_mode):
        raise PackageRefused(f"`{path}` is a link or no plain file")
    if info.st_size > limit:
        raise PackageRefused(f"`{path}` holds {info.st_size} bytes, more than {limit}")
    try:
        return path.read_bytes()
    except OSError as error:
        raise PackageRefused(f"cannot read `{path}`: {error}")


def _index_packages(index: bytes, place: str) -> dict:
    """The `packages` object of the bytes of an `index.json`; a document of another shape is refused."""
    try:
        data = json.loads(index.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise PackageRefused(f"the index of `{place}` is not valid JSON")
    packages = data.get("packages") if isinstance(data, dict) else None
    if not isinstance(packages, dict):
        raise PackageRefused(f"the index of `{place}` has no `packages` object")
    return packages


def _index_entry(index: bytes, package_id: str, place: str) -> Optional[tuple[str, str, str]]:
    """(version, zip name, sig name) of `package_id` in the bytes of an `index.json`, None when it lists no such
    package; a document of another shape or a version or file name that is not plain is refused."""
    entry = _index_packages(index, place).get(package_id)
    if entry is None:
        return None
    return _entry_fields(package_id, entry)


def _entry_fields(package_id: str, entry: object) -> tuple[str, str, str]:
    """(version, zip name, sig name) of one index entry; an entry of another shape or a version or file name that is
    not plain is refused."""
    if not isinstance(entry, dict):
        raise PackageRefused(f"the index entry of `{package_id}` is no object")
    version, zip_name, sig_name = (entry.get(key) for key in ("version", "zip", "sig"))
    if not isinstance(version, str) or not VERSION_RE.match(version):
        raise PackageRefused(f"the index entry of `{package_id}` has no version X.Y.Z")
    for key, value in (("zip", zip_name), ("sig", sig_name)):
        if not isinstance(value, str) or not FILE_NAME_RE.match(value) or ".." in value:
            raise PackageRefused(f"the index entry of `{package_id}`: `{key}` must be a plain file name (no `/`, `\\`, "
                                 f"`..`, `:`), got {_shown(str(value))}")
    return version, zip_name, sig_name


def _source_get(place: str) -> Callable[[str, int], bytes]:
    """The reader of one source: `get(file name, byte limit)` gives the bytes of a file of an `https://` address or of
    a local folder; a UNC path, any other scheme or something that is no folder is refused before anything is opened."""
    if _is_unc(place):
        raise PackageRefused(f"source {_unc_reason(place)}")
    scheme = SCHEME_RE.match(place)
    if scheme and scheme.group(1).lower() != "https":
        raise PackageRefused(f"source `{place}`: only https:// addresses and local folders are sources "
                             f"(`{scheme.group(1)}://` is not)")
    if scheme:
        base = place if place.endswith("/") else place + "/"

        def get(name: str, limit: int) -> bytes:
            return _http_get(base + urllib.parse.quote(name), limit)
    else:
        folder = Path(place)
        if not folder.is_dir():
            raise PackageRefused(f"source `{place}` is not a folder")

        def get(name: str, limit: int) -> bytes:
            return _local_get(folder / name, limit)
    return get


def _fetch_one(place: str, package_id: str) -> Optional[tuple[str, bytes, bytes]]:
    """(version, zip bytes, sig bytes) from one source, None when its index lists no such package. A source is an
    `https://` address or a local folder holding `index.json`."""
    get = _source_get(place)
    found = _index_entry(get("index.json", MAX_INDEX_BYTES), package_id, place)
    if found is None:
        return None
    version, zip_name, sig_name = found
    return version, get(zip_name, MAX_BYTES), get(sig_name, MAX_BYTES)


def _store(root: Path, items: list[tuple[str, bytes]]) -> list[str]:
    """Write each (file name, bytes) into `<root>/.act-local/packages/` through a temporary name and a rename, all
    temporary files first so a failure leaves the final names as they were. A file of the same name is replaced only
    when its content differs. Returns one line per file saying what happened."""
    created: list[Path] = []
    current = root
    for part in STAGING_PARTS[:2]:
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            os.mkdir(current)
            created.append(current)
            continue
        if actlib.is_redirect(info) or not stat.S_ISDIR(info.st_mode):
            raise PackageRefused(f"`{current}` is a link or no folder")
    notes: list[str] = []
    pending: list[tuple[Path, Path]] = []
    done = False
    try:
        for name, data in items:
            final = current / name
            try:
                info = os.lstat(final)
            except FileNotFoundError:
                info = None
            replaced = False
            if info is not None:
                if actlib.is_redirect(info) or not stat.S_ISREG(info.st_mode):
                    raise PackageRefused(f"`{final}` is a link or no plain file; left alone")
                if final.read_bytes() == data:
                    notes.append(f"unchanged .act-local/packages/{name} (same content)")
                    continue
                replaced = True
            temp = current / f".{name}.{secrets.token_hex(4)}.part"
            with open(temp, "xb") as out:
                out.write(data)
            pending.append((temp, final))
            notes.append(f"{'replaced' if replaced else 'wrote'} .act-local/packages/{name} ({len(data)} bytes"
                         + (", content differs)" if replaced else ")"))
        for temp, final in pending:
            os.replace(temp, final)
        pending = []
        done = True
    finally:
        for temp, _ in pending:
            try:
                os.remove(temp)
            except OSError:
                pass
        if not done:
            _remove_empty(created)
    return notes


def _sources(place: Optional[str], root: Path) -> list[str]:
    """`--source` alone, else the comma list of `packages-sources` in order."""
    if place:
        return [place]
    return [item.strip() for item in actlib.read_config(root).get("packages-sources", DEFAULT_SOURCES).split(",")
            if item.strip()]


def cmd_fetch(package_id: str, place: Optional[str], root: Path) -> int:
    """Download `<id>`'s zip and signature from the first source that lists it (`--source` or the config key
    `packages-sources`), keep them as `.act-local/packages/<id>-<version>.zip` and `.zip.sig`, print the origin.
    Never unpacks and never activates. Exit 0 done, 1 not fetched or the signature is bad, 2 usage."""
    if not ID_RE.match(package_id):
        print(f"fetch: `{package_id}` is no package id (^[a-z][a-z0-9-]{{1,30}}$)", file=sys.stderr)
        return 2
    sources = _sources(place, root)
    if not sources:
        print("fetch: no source (`packages-sources` is empty and no --source was given)", file=sys.stderr)
        return 2
    problems: list[str] = []
    for source in sources:
        try:
            found = _fetch_one(source, package_id)
        except FetchTimeout as error:
            print(f"fetch: {error}; aborted, nothing was written", file=sys.stderr)
            return 1
        except PackageRefused as error:
            problems.append(f"{source}: {error}")
            continue
        if found is None:
            problems.append(f"{source}: the index lists no package `{package_id}`")
            continue
        version, zip_bytes, sig_bytes = found
        name = f"{package_id}-{version}.zip"
        try:
            notes = _store(root, [(name, zip_bytes), (name + ".sig", sig_bytes)])
        except (PackageRefused, OSError) as error:
            print(f"fetch: {error}; nothing was kept", file=sys.stderr)
            return 1
        print(f"fetch: {package_id} {version} from {source}")
        for note in notes:
            print(f"  {note}")
        state, why = origin(root / ".act-local" / "packages" / name, root)
        print(f"origin: {state} ({why})")
        if state == "bad":
            print("fetch: the signature does not verify; do not add this package", file=sys.stderr)
            return 1
        return 0
    print(f"fetch: no source delivered `{package_id}`", file=sys.stderr)
    for problem in problems:
        print(f"- {problem}", file=sys.stderr)
    return 1


def _print_refused(source: "Path | str", reasons: list[str]) -> int:
    print(f"refused: {source}", file=sys.stderr)
    for reason in reasons:
        print(f"- {reason}", file=sys.stderr)
    return 1


def cmd_plan(source: Path, root: Path) -> int:
    """Stage a zip or folder, read its origin and admission, print z1's plan of the staged copy; the staging is
    removed in every case."""
    try:
        staged = stage(source, root)
    except PackageRefused as error:
        return _print_refused(source, error.reasons)
    try:
        result = analyze(staged.folder, root)
        if result.reasons:
            return _print_refused(source, result.reasons)
        state, why = origin(staged.copy, root, staged.zip_path.name if staged.zip_path else None)
        admitted, note = admission(state, root)
        print("\n".join(render_plan(result, [f"origin: {state} ({why})",
                                              f"admitted: {'yes' if admitted else 'no'} ({note})"])))
    finally:
        discard(staged)
    return 0


# --- add and remove: the human's way to make a package active, inactive or newer ----------------------------------
# Always plan and diff first, then an explicit yes with a code; every write is derived from the lock record and the
# package folder (package_load), so the way back is the same derivation without the package.

INDEX_TEXT_LIMIT = 20000   # characters of one optional text field of an index entry
INDEX_LINE_LIMIT = 160     # characters of one value `index` prints on its line


@dataclass
class IndexRow:
    """One package of an index: the fields `fetch` needs and the optional ones a person reads."""
    id: str
    version: str
    contents: str = ""
    tools: list[str] = field(default_factory=list)
    stack: list[str] = field(default_factory=list)
    red: Optional[str] = None


def _entry_text(package_id: str, key: str, value: object) -> str:
    if not isinstance(value, str) or len(value) > INDEX_TEXT_LIMIT:
        raise PackageRefused(f"the index entry of `{package_id}`: `{key}` must be text of at most {INDEX_TEXT_LIMIT} "
                             "characters")
    return value


def _entry_list(package_id: str, key: str, value: object) -> list[str]:
    """A comma list or a list of strings as a list of non-empty items."""
    if isinstance(value, str):
        items: list[str] = value.split(",")
    elif isinstance(value, list) and all(isinstance(item, str) for item in value):
        items = value
    else:
        raise PackageRefused(f"the index entry of `{package_id}`: `{key}` must be a comma list or a list of strings")
    found = [item.strip() for item in items if item.strip()]
    if len(found) > 50 or any(len(item) > 80 for item in found):
        raise PackageRefused(f"the index entry of `{package_id}`: `{key}` has more than 50 items or an item over 80 "
                             "characters")
    return found


def _index_rows(index: bytes, place: str) -> list[IndexRow]:
    """Every package of the bytes of an `index.json`, sorted by id. One entry that is bad (an id that is no package id,
    a version, file name or optional field of the wrong kind) refuses the whole file."""
    rows: list[IndexRow] = []
    for package_id, entry in sorted(_index_packages(index, place).items()):
        if not ID_RE.match(package_id):
            raise PackageRefused(f"the index of `{place}` lists {_shown(package_id)}, which is no package id")
        version, _, _ = _entry_fields(package_id, entry)
        row = IndexRow(package_id, version)
        if "contents" in entry:
            row.contents = _entry_text(package_id, "contents", entry["contents"])
        if "tools" in entry:
            row.tools = _entry_list(package_id, "tools", entry["tools"])
        if "stack" in entry:
            row.stack = _entry_list(package_id, "stack", entry["stack"])
        if "red" in entry:
            row.red = _entry_text(package_id, "red", entry["red"])
            if not row.red.strip():
                raise PackageRefused(f"the index entry of `{package_id}`: `red` is empty; leave it out for a package "
                                     "that is not red")
        rows.append(row)
    return rows


def _line_text(text: str) -> str:
    """The first non-empty line of `text`, printable characters only, cut to INDEX_LINE_LIMIT."""
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    first = "".join(ch if ch.isprintable() else " " for ch in first)
    return first if len(first) <= INDEX_LINE_LIMIT else first[:INDEX_LINE_LIMIT - 3] + "..."


def _resting_folders(root: Path, packages: dict[str, dict]) -> list[str]:
    """The folders under `.act-local/packages/` that the lock does not record (they rest)."""
    resting: list[str] = []
    base = root / ".act-local" / "packages"
    if base.is_dir():
        for entry in sorted(base.iterdir(), key=lambda p: p.name):
            try:
                info = os.lstat(entry)
            except OSError:
                continue
            if stat.S_ISDIR(info.st_mode) and not actlib.is_redirect(info) and entry.name not in packages \
                    and not entry.name.startswith("."):
                resting.append(entry.name)
    return resting


def _lock_unreadable(root: Path) -> bool:
    return (root / ".act-lock.json").exists() and actlib.read_lock_at(root) is None


def cmd_index(place: Optional[str], as_json: bool, root: Path) -> int:
    """List the packages of the first source (`--source` or `packages-sources`, in order) whose `index.json` can be
    read and is good, marking those the lock records (`active`, `broken`) and the folders resting. Same source rules
    as `fetch`; writes nothing. Exit 0, 1 when no source delivers or the lock cannot be read, 2 usage."""
    if _lock_unreadable(root):
        print("index: .act-lock.json cannot be read (not UTF-8 or no JSON object); fix or restore it first",
              file=sys.stderr)
        return 1
    sources = _sources(place, root)
    if not sources:
        print("index: no source (`packages-sources` is empty and no --source was given)", file=sys.stderr)
        return 2
    problems: list[str] = []
    for source in sources:
        try:
            rows = _index_rows(_source_get(source)("index.json", MAX_INDEX_BYTES), source)
        except FetchTimeout as error:
            print(f"index: {error}; aborted", file=sys.stderr)
            return 1
        except PackageRefused as error:
            problems.append(f"{source}: {error}")
            continue
        for problem in problems:
            print(f"index: skipped {problem}", file=sys.stderr)
        return _print_index(source, rows, root, as_json)
    print("index: no source delivered an index", file=sys.stderr)
    for problem in problems:
        print(f"- {problem}", file=sys.stderr)
    return 1


def _print_index(source: str, rows: list[IndexRow], root: Path, as_json: bool) -> int:
    packages = actlib.read_packages(root)
    resting = set(_resting_folders(root, packages))
    found: list[dict[str, object]] = []
    for row in rows:
        entry = packages.get(row.id)
        broken = bool(entry is not None and package_load.read_package(root, row.id, entry).problems)
        active = str(entry.get("version") or "-") if entry is not None else None
        found.append({"id": row.id, "version": row.version, "contents": row.contents, "tools": row.tools,
                      "stack": row.stack, "red": row.red, "active": active, "broken": broken,
                      "resting": row.id in resting,
                      "newer": bool(entry is not None and _is_older(active, row.version))})
    if as_json:
        print(json.dumps({"source": source, "packages": found}, indent=2, ensure_ascii=True))
        return 0
    print(f"index: {source} ({len(found)} package{'' if len(found) == 1 else 's'})")
    for item in found:
        marks: list[str] = []
        if item["active"] is not None:
            marks.append(f"active {item['active']}" + (", broken" if item["broken"] else "")
                         + (", newer in the index" if item["newer"] else ""))
        if item["resting"]:
            marks.append("resting")
        parts = [f"  {item['id']} {item['version']}"]
        if marks:
            parts.append(f"[{'; '.join(marks)}]")
        if item["contents"]:
            parts.append(f"contents: {_line_text(str(item['contents']))}")
        if item["tools"]:
            parts.append(f"tools: {_line_text(', '.join(item['tools']))}")  # type: ignore[arg-type]
        if item["stack"]:
            parts.append(f"stack: {_line_text(', '.join(item['stack']))}")  # type: ignore[arg-type]
        if item["red"] is not None:
            parts.append(f"RED {_line_text(str(item['red']))}")
        print("  ".join(parts))
    return 0


CONFIG_REL = "docs/ai/config.md"
LOCK_REL = ".act-lock.json"
CACHE_REL = ".act-local/cache.json"
CODE_LENGTH = 12        # hex digits of the raw-bytes package hash a `--yes` must carry
INSTALL_TIMEOUT = 300   # seconds an install.py may take
INSTALL_OUTPUT_LIMIT = 20000  # bytes of an install.py's output that are shown


@dataclass
class Candidate:
    """A package that is staged, read, admitted and refused for no reason: ready to be shown or installed."""
    staged: Staged
    result: Analysis
    state: str
    why: str
    note: str
    entry: dict
    code: str
    source: Optional[Path] = None

    @property
    def package_id(self) -> str:
        return self.result.package_id


def raw_code(folder: Path, files: "list[str] | dict[str, str]") -> str:
    """The `--yes` code of a package: the first CODE_LENGTH hex digits of the package hash computed over the raw
    bytes of every file, with no line-ending folding: any byte that changes after the plan was shown changes the
    code. (The lock's `sha256` stays as it is: over the LF form, so it reads the same on every machine.)"""
    hashes: dict[str, str] = {}
    for rel in files:
        try:
            hashes[rel] = hashlib.sha256((folder / rel).read_bytes()).hexdigest()
        except OSError as error:
            raise PackageRefused(f"`{rel}` cannot be read: {type(error).__name__}")
    return actlib.package_hash(hashes)[:CODE_LENGTH]


def newest_zip(root: Path, package_id: str) -> Optional[Path]:
    """The `<id>-<version>.zip` of the highest version in `.act-local/packages/`, a plain file only; None when none."""
    base = root / ".act-local" / "packages"
    pattern = re.compile(re.escape(package_id) + r"-(\d+)\.(\d+)\.(\d+)\.zip\Z")
    newest: Optional[tuple[tuple[int, int, int], Path]] = None
    try:
        names = os.listdir(base)
    except OSError:
        return None
    for name in sorted(names):
        match = pattern.match(name)
        if not match:
            continue
        try:
            info = os.lstat(base / name)
        except OSError:
            continue
        if not stat.S_ISREG(info.st_mode) or actlib.is_redirect(info):
            continue
        key = (int(match.group(1)), int(match.group(2)), int(match.group(3)))
        if newest is None or key > newest[0]:
            newest = (key, base / name)
    return newest[1] if newest else None



def _resolve_source(arg: str, root: Path) -> Path:
    """What `add <arg>` reads: a path as given, or for a bare package id the newest fetched zip, else the resting
    folder `.act-local/packages/<id>/` (read as a folder, so unverified); refused naming `fetch` when there is neither.
    An id-shaped argument is always an id: a folder of that name is given as `./<name>`."""
    if not ID_RE.match(arg):
        return Path(arg)
    found = newest_zip(root, arg)
    if found is not None:
        return found
    folder = root / ".act-local" / "packages" / arg
    try:
        info = os.lstat(folder)
    except OSError:
        info = None
    if info is not None and stat.S_ISDIR(info.st_mode) and not actlib.is_redirect(info):
        return folder
    raise PackageRefused(f"no package `{arg}` in .act-local/packages/ (neither a zip `{arg}-<version>.zip` nor a folder "
                         f"`{arg}/`); get it with: python .act/scripts/packages.py fetch {arg}")


def named_by_id(arg: str, source: Path, result: Analysis) -> list[str]:
    """What `add <id>` takes by name must be what its name says: the package.md of the zip or folder carries that id,
    and a zip `<id>-<version>.zip` carries that version. Each difference is a reason."""
    reasons: list[str] = []
    if result.package_id != arg:
        reasons.append(f"you asked for `{arg}`, but package.md says id `{result.package_id}` ({source.name})")
    named = re.fullmatch(re.escape(arg) + r"-(\d+\.\d+\.\d+)\.zip", source.name)
    if named and result.header.get("version") != named.group(1):
        reasons.append(f"the file name says version {named.group(1)}, but package.md says version "
                       f"{result.header.get('version')} ({source.name})")
    return reasons


def declared_settings(manifest: Optional[bytes]) -> list[tuple[str, str]]:
    """(key, question) of each `- <key>: <question>` line of the `## settings` section of a package.md, in order.
    Reads the bytes it is given and nothing else; a line that is no list line is skipped (`analyze` refuses it)."""
    if manifest is None:
        return []
    found: list[tuple[str, str]] = []
    for line in package_scan.manifest_sections(manifest.decode("utf-8", errors="replace")).get("settings", []):
        match = LIST_RE.match(line)
        if match:
            key, _, question = match.group(1).partition(":")
            found.append((key.strip(), question.strip()))
    return found


def _is_older(new: object, old: object) -> bool:
    """True when both are `X.Y.Z` versions and `new` is the lower one."""
    low, high = stable(str(new)), stable(str(old))
    return low is not None and high is not None and low < high


def _prepare(arg: str, root: Path) -> Candidate:
    """Stage what `arg` names, read it, find its origin and admission. Any refusal raises PackageRefused with every
    reason and removes the staging; otherwise the caller owns the staging (`discard`)."""
    source = _resolve_source(arg, root)
    staged = stage(source, root)
    try:
        result = analyze(staged.folder, root)
        zip_name = staged.zip_path.name if staged.zip_path else None
        state, why = origin(staged.copy, root, zip_name)
        admitted, note = admission(state, root)
        reasons = list(result.reasons)
        if not result.reasons and ID_RE.match(arg):
            reasons += named_by_id(arg, source, result)
        if not admitted:
            reasons.append(f"not admitted: {note}")
        if reasons:
            raise PackageRefused(reasons)
        entry = lock_entry(result, zip_name or f"folder {source.name}", state)
        return Candidate(staged, result, state, why, note, entry, raw_code(staged.folder, result.files), source)
    except BaseException:
        discard(staged)
        raise


def _quote(text: str) -> str:
    """`text` as one word of a command line a person can paste."""
    return text if re.fullmatch(r"[A-Za-z0-9_./:\\+=@%-]+", text) else '"' + text.replace('"', '\\"') + '"'


def _current(root: Path, rel: str) -> Optional[bytes]:
    try:
        return (root / rel).read_bytes()
    except OSError:
        return None


def _read_config(root: Path) -> Optional[str]:
    """docs/ai/config.md as text, None when it is missing."""
    try:
        return (root / CONFIG_REL).read_bytes().decode("utf-8")
    except FileNotFoundError:
        return None
    except UnicodeDecodeError:
        raise PackageRefused(f"{CONFIG_REL} is not valid UTF-8; nothing was changed")
    except OSError as error:
        raise PackageRefused(f"{CONFIG_REL} cannot be read: {error}")


def _config_after(before: Optional[str], package_id: str, old: Optional[dict], checks: list[tuple[str, str]],
                  settings: Optional[list[str]] = None) -> Optional[str]:
    """The config text after the package's check rows are set (an update gives the old version's rows back first and
    drops the settings rows the new version, which declares the keys `settings`, no longer asks); None when there is
    no config file and nothing to set. A row that cannot be set raises PackageRefused."""
    if before is None:
        if checks:
            raise PackageRefused(f"{CONFIG_REL} is missing: the package sets check rows there")
        return None
    text = before
    try:
        if old is not None:
            text = config.revert_package_checks(text, package_id)
            if settings is not None:
                text = config.prune_package_settings(text, package_id, settings)
        if checks:
            text = config.apply_package_checks(text, package_id, checks)
    except config.PackageCheckConflict as error:
        raise PackageRefused(f"{CONFIG_REL}: {error}")
    return text


def _lock_after(root: Path, package_id: str, entry: Optional[dict], plan: Optional["package_load.Plan"]) -> Optional[bytes]:
    """The bytes `.act-lock.json` holds when `entry` is recorded for `package_id` (None: the package is dropped) and
    the loading in `plan` has run: the lock's record of the copies (`package_copies`), the template copies put back,
    no empty `packages` or `package_copies` key. Mirrors actlib.merge_package/drop_package and package_load's record
    writer; the probe compares it with what the real run leaves."""
    data = actlib.read_lock_at(root)
    if data is None:
        return None
    wanted = dict(data)
    raw = wanted.get(actlib.PACKAGES_LOCK_KEY)
    packages = dict(raw) if isinstance(raw, dict) else {}
    if entry is None:
        packages.pop(package_id, None)
    else:
        packages[package_id] = entry
    wanted[actlib.PACKAGES_LOCK_KEY] = packages
    if plan is not None:
        if plan.record:
            wanted[package_load.COPIES_KEY] = dict(sorted(plan.record.items()))
        else:
            wanted.pop(package_load.COPIES_KEY, None)
        if plan.restored and isinstance(wanted.get("copies"), dict):
            wanted["copies"] = {**wanted["copies"], **plan.restored}
    if wanted.get(actlib.PACKAGES_LOCK_KEY) == {}:
        del wanted[actlib.PACKAGES_LOCK_KEY]
    return (json.dumps(wanted, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _diff_lines(rel: str, before: Optional[bytes], after: Optional[bytes]) -> list[str]:
    """A unified diff of one project file; `/dev/null` for a file that is new or goes."""
    try:
        old = [] if before is None else before.decode("utf-8").splitlines()
        new = [] if after is None else after.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return [f"Binary file {rel} differs"]
    lines = list(difflib.unified_diff(old, new, "/dev/null" if before is None else f"a/{rel}",
                                      "/dev/null" if after is None else f"b/{rel}", lineterm=""))
    return lines or [f"{rel}: only line endings or the final newline differ"]


def _render_changes(root: Path, target: dict[str, Optional[bytes]]) -> list[str]:
    """The list of project files whose content would change (project path -> new bytes, None = the file goes), then
    one unified diff for each."""
    changed = {rel: (_current(root, rel), data) for rel, data in sorted(target.items()) if _current(root, rel) != data}
    if not changed:
        return ["project files this changes: none"]
    out = [f"project files this changes ({len(changed)}):"]
    for rel, (before, after) in changed.items():
        out.append(f"  {'new' if before is None else 'deleted' if after is None else 'changed':<8}{rel}")
    for rel, (before, after) in changed.items():
        out.append("")
        out += _diff_lines(rel, before, after)
    return out


def _print_scan(candidate: Candidate, root: Path) -> None:
    """With `packages-unverified: scan`, the findings of the static scan of an unverified package, red on a terminal."""
    mode = actlib.read_config(root).get("packages-unverified", "block").strip("`").strip().lower()
    if candidate.state != "unverified" or mode != "scan":
        return
    findings = package_scan.scan(candidate.staged.folder)
    print("scan of the unverified package (packages-unverified: scan; a clean scan is no endorsement):")
    red, reset = (package_scan.RED, package_scan.RESET) if sys.stdout.isatty() else ("", "")
    for finding in findings or ["(no findings)"]:
        print(f"  {red}{finding}{reset}")


def _add_notes(candidate: Candidate, old: Optional[dict], root: Path) -> list[str]:
    """What `add` does besides writing the files shown: the kind of install, what an update drops and what happens to
    the folder that stands in the way."""
    result, entry = candidate.result, candidate.entry
    version = entry.get("version", "?")
    where = f".act-local/packages/{candidate.package_id}/"
    dest = root / ".act-local" / "packages" / candidate.package_id
    if old is None:
        lines = [f"install {candidate.package_id} {version} (new)"]
    else:
        kind = "downgrade" if _is_older(version, old.get("version")) else "update"
        lines = [f"{kind} {candidate.package_id} {old.get('version') or '?'} → {version}"]
        kept = {unit for unit in entry.get("units", []) if isinstance(unit, str)}
        old_units = old.get("units") if isinstance(old.get("units"), list) else []
        lines += [f"drops {unit} (its copy goes)" for unit in old_units if isinstance(unit, str) and unit not in kept]
    if old is not None:
        lines.append(f"folder {where} is replaced by this package (the old version's folder is deleted)")
    elif _folder_state(dest) == "folder":
        try:
            same = candidate.source is not None and Path(candidate.source).resolve() == dest.resolve()
        except OSError:
            same = False
        if same:
            lines.append(f"the resting folder {where} is the source: it is copied and then replaced by the copy")
        else:
            lines.append(f"the resting folder {where} (not in the lock) is replaced by this package and deleted")
    else:
        lines.append(f"folder {where} is made from this package")
    if result.header.get("contains-code") == "yes" and "install.py" in result.files:
        lines.append("install.py runs once after the files are in place (time limit "
                     f"{INSTALL_TIMEOUT} s; it stays installed when it fails)")
    if "install.md" in result.files:
        lines.append(f"install.md: after the install the AI agent is told to follow .act-local/packages/"
                     f"{candidate.package_id}/install.md")
    return lines


def _what(error: BaseException) -> str:
    """An error as text for a message: the class and, for an OS error, the path and the system's words -- never the
    content of a file."""
    if isinstance(error, OSError) and error.filename:
        return f"{type(error).__name__} on `{error.filename}`: {error.strerror or ''}".rstrip(": ")
    return f"{type(error).__name__}: {error}"


def _shown_output(path: Path) -> list[str]:
    """The lines an install.py wrote to its output file, cut at INSTALL_OUTPUT_LIMIT bytes."""
    try:
        with open(path, "rb") as handle:
            data = handle.read(INSTALL_OUTPUT_LIMIT + 1)
    except OSError as error:
        return [f"(the output could not be read: {type(error).__name__})"]
    cut = len(data) > INSTALL_OUTPUT_LIMIT
    lines = data[:INSTALL_OUTPUT_LIMIT].decode("utf-8", errors="replace").splitlines()
    if cut:
        lines = lines[:-1] + [f"(output cut after {INSTALL_OUTPUT_LIMIT} bytes; the rest is not shown)"]
    return lines


def _run_install(root: Path, package_id: str, staging: Path) -> int:
    """Run the installed package's install.py once (argument list, cwd the project root, time limit). Its output goes
    to a file in the staging folder, so a child process it leaves behind cannot hold the run up; at the time limit
    the whole process tree is ended (actlib.end_process_tree). The output is shown afterwards, bounded. 0 ok."""
    script = root / ".act-local" / "packages" / package_id / "install.py"
    remove_hint = f"to take the package out again: python .act/scripts/packages.py remove {package_id}"
    out_path = staging / "install-output.txt"
    timed_out = False
    try:
        with open(out_path, "wb") as sink:
            proc = subprocess.Popen([sys.executable, str(script)], cwd=root, stdin=subprocess.DEVNULL, stdout=sink,
                                    stderr=subprocess.STDOUT, start_new_session=(os.name != "nt"))
            try:
                code = proc.wait(timeout=INSTALL_TIMEOUT)
            except subprocess.TimeoutExpired:
                actlib.end_process_tree(proc)
                timed_out, code = True, 1
            except BaseException:  # Ctrl+C in a manual run: never leave the install behind
                actlib.end_process_tree(proc)
                raise
    except OSError as error:
        print(f"add: install.py of `{package_id}` could not run ({_what(error)}); the package stays installed; " + remove_hint,
              file=sys.stderr)
        return 1
    for line in _shown_output(out_path):
        print(f"  install.py: {line}")
    with contextlib.suppress(OSError):  # a process it left behind may still hold the file: the staging stays then
        out_path.unlink()
    if timed_out:
        print(f"add: install.py of `{package_id}` did not finish within {INSTALL_TIMEOUT} s (it and what it started were "
              f"ended); the package stays installed; " + remove_hint, file=sys.stderr)
        return 1
    if code != 0:
        print(f"add: install.py of `{package_id}` exited with {code}; the package stays installed; " + remove_hint,
              file=sys.stderr)
        return 1
    return 0


@dataclass
class _Undo:
    """What `add` did so far, so a failure puts the project back."""
    dest: Path
    old_entry: Optional[dict]
    aside: Optional[Path] = None       # where the old folder was moved to
    folder_in: bool = False            # the new folder stands at dest
    locked: bool = False               # the lock write was started: it may hold the new entry, fully or in part
    lock_was: Optional[bytes] = None   # the lock's bytes before
    config_was: Optional[bytes] = None
    config_written: bool = False       # the config write was started
    saved: dict[str, Optional[bytes]] = field(default_factory=dict)  # files the loading may write: their bytes before


def _attempt(problems: list[str], what: str, step: "Callable[[], object]") -> None:
    """Run one undo step; a failure is named in `problems` and the next step still runs."""
    try:
        step()
    except Exception as error:  # noqa: BLE001 - every step is tried and each failure is named
        problems.append(f"{what}: {_what(error)}")


def _snapshot(root: Path, plan: Optional["package_load.Plan"]) -> dict[str, Optional[bytes]]:
    """The bytes (None = the file does not exist) of every project file the loading can write: what the plan writes,
    `docs/ai/rules.md` (the cut of its import lines) and the generated-file cache."""
    rels = set(plan.writes) if plan is not None else set()
    return {rel: _current(root, rel) for rel in sorted(rels | {package_load.RULES_MD, CACHE_REL})}


def _restore_files(root: Path, saved: dict[str, Optional[bytes]], problems: list[str]) -> None:
    """Put the files of `_snapshot` back byte for byte; one that did not exist is deleted and the empty folders its
    copy left are removed."""
    for rel, data in saved.items():
        def step(rel: str = rel, data: Optional[bytes] = data) -> None:
            path = root / rel
            if data is None:
                if os.path.lexists(path):
                    path.unlink()
                package_load._prune(root, rel)
            elif _current(root, rel) != data:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        _attempt(problems, f"restore {rel}", step)


def _rollback(root: Path, package_id: str, undo: _Undo, staging: Path) -> list[str]:
    """Undo what `add` did, in the reverse order; every step on its own, each failure named in the result. The
    lock, the config and the files the loading may have written come back from their saved bytes: nothing is derived
    again, and nothing runs before the first write."""
    problems: list[str] = []
    if undo.folder_in:
        _attempt(problems, "take the new folder out again", lambda: os.replace(undo.dest, staging / "failed"))
    if undo.aside is not None:
        _attempt(problems, "put the old folder back", lambda: os.replace(undo.aside, undo.dest))
    if undo.locked and undo.lock_was is not None:
        _attempt(problems, f"restore {LOCK_REL}", lambda: (root / LOCK_REL).write_bytes(undo.lock_was))
    if undo.config_written and undo.config_was is not None:
        _attempt(problems, f"restore {CONFIG_REL}", lambda: (root / CONFIG_REL).write_bytes(undo.config_was))
    if undo.locked:
        _restore_files(root, undo.saved, problems)
    return problems


def _install(candidate: Candidate, old: Optional[dict], config_before: Optional[str], config_after: Optional[str],
             root: Path, plan: "package_load.Plan") -> int:
    """The writes of `add --yes`, in the order: the folder (an old one moved aside first), docs/ai/config.md, the lock
    entry, then package_load.sync_packages. A failure on the way puts everything back and exits 1."""
    package_id = candidate.package_id
    staging = candidate.staged.staging
    dest = root / ".act-local" / "packages" / package_id
    undo = _Undo(dest, old)
    try:
        try:
            info = os.lstat(dest)
        except FileNotFoundError:
            info = None
        if info is not None:
            if actlib.is_redirect(info) or not stat.S_ISDIR(info.st_mode):
                raise PackageRefused(f"`{dest}` is a link or no folder; left alone")
            (staging / "aside").mkdir()
            os.replace(dest, staging / "aside" / package_id)
            undo.aside = staging / "aside" / package_id
        os.replace(candidate.staged.folder, dest)
        undo.folder_in = True
        package = package_load.read_package(root, package_id, candidate.entry)
        if not package.intact:
            raise PackageRefused("the installed folder differs from what was checked: " + "; ".join(package.problems[:3]))
        if config_after is not None and config_after != config_before:
            undo.config_was = (root / CONFIG_REL).read_bytes()
            undo.config_written = True  # marked before the write: a write that fails half-way is undone too
            (root / CONFIG_REL).write_bytes(config_after.encode("utf-8"))
        undo.lock_was = (root / LOCK_REL).read_bytes()
        undo.saved = _snapshot(root, plan)
        undo.locked = True
        if not actlib.merge_package(root, package_id, candidate.entry):
            raise PackageRefused(f"{LOCK_REL} cannot be written")
        changed = package_load.sync_packages(root, strict=True)
    except BaseException as error:
        problems = _rollback(root, package_id, undo, staging)
        print(f"add: failed ({_what(error)}); everything was put back"
              + ("" if not problems else "; but not all of it: " + "; ".join(problems)
                 + " (run `python .act/scripts/doctor.py` and `python .act/scripts/packages.py list`)"),
              file=sys.stderr)
        if not isinstance(error, Exception):
            raise
        return 1
    entry = candidate.entry
    kind = "new" if old is None else "downgrade" if _is_older(entry.get("version"), old.get("version")) else "update"
    print(f"installed {package_id} {entry.get('version')} ({kind}), origin {candidate.state}")
    written = set(changed) | {LOCK_REL}
    if undo.config_written:
        written.add(CONFIG_REL)
    for rel in sorted(written):
        print(f"  changed {rel}")
    if candidate.result.header.get("contains-code") == "yes" and "install.py" in candidate.result.files:
        if _run_install(root, package_id, staging) != 0:
            return 1
    if "install.md" in candidate.result.files:
        print(f"install.md: AI agent, follow .act-local/packages/{package_id}/install.md now (this step follows the "
              "owner's yes to the plan shown, given in chat; --yes only carries it out; that counts as the owner's "
              "instruction for this installation only)")
    return 0


def cmd_add(arg: str, code: Optional[str], root: Path) -> int:
    """Stage what `arg` names (a zip, a folder or a package id), check it and show what installing it changes: the
    plan, the origin and admission, a unified diff of every project file, and the exact command with the code. With
    `--yes <code>` (the first CODE_LENGTH hex digits of the package hash) it installs exactly that package, else it
    writes nothing. Exit 0 done or shown, 1 refused or failed."""
    if actlib.read_lock_at(root) is None:
        print(f"add: {LOCK_REL} is missing or cannot be read; the package is recorded there, so fix or restore it first",
              file=sys.stderr)
        return 1
    try:
        candidate = _prepare(arg, root)
    except PackageRefused as error:
        return _print_refused(arg, error.reasons)
    try:
        package_id = candidate.package_id
        packages = actlib.read_packages(root)
        old = packages.get(package_id)
        after = dict(packages)
        after[package_id] = candidate.entry
        try:
            config_before = _read_config(root)
            config_after = _config_after(config_before, package_id, old, candidate.result.checks,
                                         [key for key, _ in candidate.result.settings])
        except PackageRefused as error:
            return _print_refused(arg, error.reasons)
        plan = package_load.plan_for(root, after, folders={package_id: candidate.staged.folder})
        if plan.problems.get(package_id):
            return _print_refused(arg, [f"the staged package cannot be loaded: {item}" for item in plan.problems[package_id]])
        target: dict[str, Optional[bytes]] = dict(plan.writes)
        if config_after is not None:
            target[CONFIG_REL] = config_after.encode("utf-8")
        target[LOCK_REL] = _lock_after(root, package_id, candidate.entry, plan)
        if code is None:
            origin_lines = [f"origin: {candidate.state} ({candidate.why})", f"admitted: yes ({candidate.note})"]
            print("\n".join(render_plan(candidate.result, origin_lines, closing=None)))
            _print_scan(candidate, root)
            print("")
            print("\n".join(_add_notes(candidate, old, root)))
            for message in plan.messages:
                print(f"note: {message}")
            print("")
            print("\n".join(_render_changes(root, target)))
            print("")
            print(f"install exactly this: python .act/scripts/packages.py add {_quote(arg)} --yes {candidate.code}")
            print("dry run: nothing was written into the project")
            return 0
        if code.strip().lower() != candidate.code:
            return _print_refused(arg, ["the --yes code is not the code of the package that this gives now (wrong, or the "
                                        "package changed since the plan): run `add` without --yes and use the code of "
                                        "its last lines"])
        _print_scan(candidate, root)
        return _install(candidate, old, config_before, config_after, root, plan)
    finally:
        try:
            discard(candidate.staged)
        except (OSError, ValueError) as error:  # e.g. a process install.py left behind still holds a file in it
            print(f"add: the staging folder {candidate.staged.staging} could not be removed ({_what(error)}); "
                  "delete it by hand when nothing uses it any more", file=sys.stderr)


def _folder_state(folder: Path) -> str:
    """`folder`, `missing` or `other` (a link or no folder) for a package folder."""
    try:
        info = os.lstat(folder)
    except OSError:
        return "missing"
    return "folder" if stat.S_ISDIR(info.st_mode) and not actlib.is_redirect(info) else "other"


def _delete_package_folder(root: Path, package_id: str) -> str:
    """Delete `.act-local/packages/<id>/` (the literal path, recorded first), after checking that `.act-local`,
    `packages` and the folder are plain folders and no link; the delete never follows a link. Returns what happened."""
    base = root / ".act-local" / "packages"
    target = base / package_id
    if not ID_RE.match(package_id) or target.parent != base:
        raise ValueError(f"`{package_id}` is no package id")
    for step in (root / ".act-local", base, target):
        info = os.lstat(step)
        if actlib.is_redirect(info) or not stat.S_ISDIR(info.st_mode):
            raise ValueError(f"`{step}` is a link or no folder; left alone")
    _remove_tree(target)
    return f"deleted .act-local/packages/{package_id}/"


def cmd_remove(package_id: str, keep: bool, yes: Optional[str], root: Path) -> int:
    """Take a package out: the plan and diff of what that changes, then with `--yes <id>` the writes (config rows given
    back, the lock entry dropped, package_load.sync_packages, then the folder deleted unless `--keep`). Works when
    the folder is already missing, and for a folder resting in `.act-local/packages/` that the lock does not record."""
    if actlib.read_lock_at(root) is None:
        print(f"remove: {LOCK_REL} is missing or cannot be read; fix or restore it first", file=sys.stderr)
        return 1
    packages = actlib.read_packages(root)
    entry = packages.get(package_id)
    folder = root / ".act-local" / "packages" / package_id
    state = _folder_state(folder)
    if entry is None and state != "folder":
        print(f"remove: `{package_id}` is not in the lock and there is no folder .act-local/packages/{package_id}/",
              file=sys.stderr)
        return 1
    after = {key: value for key, value in packages.items() if key != package_id}
    try:
        config_before = _read_config(root)
    except PackageRefused as error:
        return _print_refused(package_id, error.reasons)
    config_after = None
    if config_before is not None:  # the check rows go back, the package's settings block goes
        config_after = config.drop_package_settings(config.revert_package_checks(config_before, package_id), package_id)
    plan = package_load.plan_for(root, after) if entry is not None else None
    target: dict[str, Optional[bytes]] = dict(plan.writes) if plan else {}
    if config_after is not None:
        target[CONFIG_REL] = config_after.encode("utf-8")
    if entry is not None:
        target[LOCK_REL] = _lock_after(root, package_id, None, plan)
    where = f".act-local/packages/{package_id}/"
    if state == "missing":
        folder_line = f"folder {where} is already missing"
    elif state == "other":
        folder_line = f"folder {where} is a link or no folder: left alone"
    elif keep:
        folder_line = f"folder {where} stays (--keep): it rests there and nothing loads from it"
    else:
        folder_line = f"folder {where} is deleted"
    if yes is None:
        if entry is not None:
            print(f"remove {package_id} {entry.get('version') or '?'} (active in the lock)")
        else:
            print(f"remove {package_id}: not in the lock, a folder resting in .act-local/packages/")
        if plan is not None:
            for message in plan.messages:
                print(f"note: {message}")
        print(folder_line)
        print("")
        print("\n".join(_render_changes(root, target)))
        print("")
        print(f"remove exactly this: python .act/scripts/packages.py remove {package_id}{' --keep' if keep else ''} --yes {package_id}")
        print("dry run: nothing was written into the project")
        return 0
    if yes.strip() != package_id:
        return _print_refused(package_id, [f"`--yes` must carry the package id `{package_id}`, not `{yes}`"])
    config_was, lock_was = _current(root, CONFIG_REL), _current(root, LOCK_REL)
    saved = _snapshot(root, plan)
    started = {"config": False, "lock": False}
    try:
        changed: list[str] = []
        if config_after is not None and config_after != config_before:
            started["config"] = True  # marked before the write: a write that fails half-way is undone too
            (root / CONFIG_REL).write_bytes(config_after.encode("utf-8"))
            changed.append(CONFIG_REL)
        if entry is not None:
            started["lock"] = True
            actlib.drop_package(root, package_id)
            changed += [LOCK_REL, *package_load.sync_packages(root, strict=True)]
    except Exception as error:  # noqa: BLE001 - named, with what is left to do
        problems: list[str] = []
        if started["lock"] and lock_was is not None:
            _attempt(problems, f"restore {LOCK_REL}", lambda: (root / LOCK_REL).write_bytes(lock_was))
        if started["config"] and config_was is not None:
            _attempt(problems, f"restore {CONFIG_REL}", lambda: (root / CONFIG_REL).write_bytes(config_was))
        if started["lock"]:
            _restore_files(root, saved, problems)
        print(f"remove: failed ({_what(error)}); everything was put back"
              + ("" if not problems else "; but not all of it: " + "; ".join(problems)
                 + " (run `python .act/scripts/packages.py list` and `python .act/scripts/doctor.py`)"),
              file=sys.stderr)
        return 1
    print(f"removed {package_id}")
    for rel in sorted(set(changed)):
        print(f"  changed {rel}")
    if state == "folder" and not keep:
        try:
            print(f"  {_delete_package_folder(root, package_id)}")
        except (OSError, ValueError) as error:
            print(f"remove: the package is out, but its folder could not be deleted ({type(error).__name__}: {error}); "
                  f"delete {where} by hand", file=sys.stderr)
            return 1
    elif state == "folder":
        print(f"  kept {where} (resting)")
    _remove_empty([root / ".act-local" / "packages"])  # made by the install; gone when nothing else is in it
    return 0


def cmd_list(root: Path) -> int:
    if _lock_unreadable(root):
        print("packages: .act-lock.json cannot be read (not UTF-8 or no JSON object); fix or restore it first",
              file=sys.stderr)
        return 1
    packages = actlib.read_packages(root)
    resting = _resting_folders(root, packages)
    if not packages and not resting:
        print("no packages")
        return 0
    if packages:
        print("packages in the lock:")
        for pkg_id, entry in sorted(packages.items()):
            print(f"  {pkg_id} {entry.get('version') or '-'}  source: {entry.get('source') or '-'}  "
                  f"check: {entry.get('check') or '-'}")
            problems = package_load.read_package(root, pkg_id, entry).problems
            if problems:
                print(f"    broken: {'; '.join(problems[:3])}" + (" ..." if len(problems) > 3 else ""))
                print(f"    nothing loads from it until: python .act/scripts/packages.py add {pkg_id}  (again, with a "
                      f"zip or folder of the same package), or: python .act/scripts/packages.py remove {pkg_id}")
    if resting:
        print("resting in .act-local/packages/ (not in the lock):")
        for name in resting:
            print(f"  {name}")
    return 0


def cmd_settings(package_id: str, pairs: list[str], root: Path) -> int:
    """Show or set the settings of an active package: the keys its `## settings` section declares, kept in
    docs/ai/config.md in a block of their own below the table of § Packages. Without `pairs` it shows; with
    `<key>=<value>` pairs it writes them, after checking every key against the package and every value (one line, no
    `|`); a refusal writes nothing. Exit 0 shown or written, 1 refused."""
    if actlib.read_lock_at(root) is None:
        print(f"settings: {LOCK_REL} is missing or cannot be read; fix or restore it first", file=sys.stderr)
        return 1
    packages = actlib.read_packages(root)
    entry = packages.get(package_id)
    if entry is None:
        active = ", ".join(sorted(packages)) or "none"
        print(f"settings: `{package_id}` is not an active package (not in the lock; active: {active}); add it first: "
              f"python .act/scripts/packages.py add {package_id}", file=sys.stderr)
        return 1
    package = package_load.read_package(root, package_id, entry)
    if not package.intact:
        print(f"settings: package `{package_id}` is broken ({'; '.join(package.problems[:3])}), so its settings cannot "
              f"be read; fix it: python .act/scripts/packages.py add {package_id} (again), or python .act/scripts/packages.py remove {package_id}",
              file=sys.stderr)
        return 1
    declared = declared_settings(package.data.get("package.md"))
    questions = dict(declared)
    try:
        text = _read_config(root)
    except PackageRefused as error:
        return _print_refused(package_id, error.reasons)
    if text is None:
        print(f"settings: {CONFIG_REL} is missing; nothing was changed", file=sys.stderr)
        return 1
    current = config.package_settings(text, package_id)
    version = entry.get("version") or "?"
    if not pairs:
        print(f"settings of {package_id} {version} ({CONFIG_REL}, section Packages):")
        for key, question in declared:
            print(f"  {key} = {current[key] if key in current else '(not set)'}")
            print(f"    {question}")
        for key, value in current.items():
            if key not in questions:
                print(f"  {key} = {value}  (this version of the package does not ask it)")
        if not declared:
            print(f"  {package_id} declares no settings")
        else:
            print(f"set with: python .act/scripts/packages.py settings {package_id} <key>=<value> ...")
        return 0
    values: dict[str, str] = {}
    reasons: list[str] = []
    for pair in pairs:
        key, equals, value = pair.partition("=")
        key = key.strip()
        if not equals or not key:
            reasons.append(f"`{pair[:60]}` must read <key>=<value>")
        elif key not in questions:
            asked = ", ".join(f"`{name}`" for name, _ in declared) or "none"
            reasons.append(f"`{key}` is no setting of package `{package_id}` (it asks: {asked})")
        elif key in values:
            reasons.append(f"`{key}` is given twice")
        else:
            values[key] = value
    if reasons:
        print(f"settings: refused, nothing was written ({'; '.join(reasons)})", file=sys.stderr)
        return 1
    try:
        after = config.set_package_settings(text, package_id, values, tuple(key for key, _ in declared))
    except config.PackageSettingError as error:
        print(f"settings: refused, nothing was written ({error})", file=sys.stderr)
        return 1
    if after == text:
        print("settings: unchanged")
        return 0
    try:
        actlib.write_text_atomic(root / CONFIG_REL, after)
    except OSError as error:
        print(f"settings: {CONFIG_REL} cannot be written ({type(error).__name__}); nothing was changed", file=sys.stderr)
        return 1
    for key, value in values.items():
        print(f"{key}: {current[key] if key in current else '(not set)'} -> {value.strip()}")
    print(f"written to {CONFIG_REL}; nothing was committed")
    return 0


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(
        prog="packages.py",
        description="Validate a package zip or folder against the template and print the plan, fetch a package "
                    "zip with its signature into .act-local/packages/, list what a source's index offers, add a package (plan and diff first, then "
                    "--yes with the code shown), remove one, show or set a package's settings, or list the packages the "
                    "lock records and the folders resting there. Only `add --yes` runs package code (its install.py).")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="stage a package zip or folder, check its origin and admission and print what "
                                       "installing it would do (exit 1 with every reason when it is refused)")
    plan.add_argument("source", help="the package zip, or the package folder (package.md, pre-template/, post-template/, "
                                     "install.py, install.md)")
    fetch = sub.add_parser("fetch", help="download a package zip and its signature into .act-local/packages/ "
                                         "(never unpacks, never activates) and print its origin")
    fetch.add_argument("id", help="the package id")
    fetch.add_argument("--source", help="one place instead of `packages-sources`: an https:// address or a local "
                                        "folder holding index.json")
    index = sub.add_parser("index", help="list the packages of the first source whose index.json answers (id, version, "
                                         "contents, tools, stack, RED reason), marking the active and resting ones; "
                                         "writes nothing")
    index.add_argument("--source", help="one place instead of `packages-sources`: an https:// address or a local "
                                        "folder holding index.json")
    index.add_argument("--json", action="store_true", help="print the same as JSON")
    add = sub.add_parser("add", help="show what installing a package changes (plan, origin, a diff of every project "
                                     "file) and with --yes <code> install it; the same id again is an update")
    add.add_argument("source", help="a package zip (with <zip>.sig next to it), a package folder, or a package id: the "
                                    "newest .act-local/packages/<id>-<version>.zip, else the resting folder "
                                    ".act-local/packages/<id>/ (a folder named like an id: ./<name>)")
    add.add_argument("--yes", metavar="CODE", help="install exactly the package whose code this is (the first 12 hex "
                                                   "digits of its sha256, shown by the run without --yes)")
    remove = sub.add_parser("remove", help="show what taking a package out changes and with --yes <id> do it")
    remove.add_argument("id", help="the package id")
    remove.add_argument("--keep", action="store_true", help="keep the folder .act-local/packages/<id>/ (it rests, "
                                                            "nothing loads from it)")
    remove.add_argument("--yes", metavar="ID", help="take the package out; the value is the package id again")
    sub.add_parser("list", help="packages in the lock (id, version, source, check) and folders resting under "
                                ".act-local/packages/ that the lock does not record")
    settings = sub.add_parser("settings", help="show or set the settings an active package asks for "
                                               "(its `## settings` section), kept in docs/ai/config.md")
    settings.add_argument("id", help="the package id")
    settings.add_argument("pairs", nargs="*", metavar="KEY=VALUE",
                          help="a key the package declares and its value (one line, no `|`); without any: show")
    args = parser.parse_args(argv)
    try:
        root = actlib.repo_root()
    except RuntimeError as error:
        print(f"packages: {error}", file=sys.stderr)
        return 2
    if args.command == "plan":
        return cmd_plan(Path(args.source), root)
    if args.command == "fetch":
        return cmd_fetch(args.id, args.source, root)
    if args.command == "index":
        return cmd_index(args.source, args.json, root)
    if args.command == "add":
        return cmd_add(args.source, args.yes, root)
    if args.command == "remove":
        if not ID_RE.match(args.id):
            print(f"remove: `{args.id}` is no package id (^[a-z][a-z0-9-]{{1,30}}$)", file=sys.stderr)
            return 2
        return cmd_remove(args.id, args.keep, args.yes, root)
    if args.command == "settings":
        if not ID_RE.match(args.id):
            print(f"settings: `{args.id}` is no package id (^[a-z][a-z0-9-]{{1,30}}$)", file=sys.stderr)
            return 2
        return cmd_settings(args.id, args.pairs, root)
    return cmd_list(root)


if __name__ == "__main__":
    try:
        from usage import count_script_run
        count_script_run(__file__)
    except ImportError:
        pass
    sys.exit(main(sys.argv[1:]))
