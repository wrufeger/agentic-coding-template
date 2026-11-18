#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: tool copies for a project's own skills and roles — a skill written by hand under
#          docs/ai/local/skills/<name>/ gets its copies under .claude/skills/ and .agents/skills/
#          (recorded in .act-lock.json § copies, exactly as settings_load.py's write_unit_bridges()
#          and update.py do), a role under docs/ai/local/agents/<name>.md gets its Claude Code bridge
#          under .claude/agents/. Called from the session start (hooks/checks/session.py) and from
#          update.py, so a hand-made unit needs no import step.
# Rules:   idempotent; an untracked copy that exists with other content is never overwritten (reported);
#          a tracked copy that still equals its recorded hash follows a changed source (refreshed), a
#          stale hash on a copy that equals its source is re-recorded silently, a copy edited by hand
#          (differs from both) is left alone (doctor.py names it); a name
#          that is a template skill/role is that unit's override, not an own unit, and is skipped
#          with a note; nothing is ever deleted here (a removed own unit's copies stay, update.py's
#          refresh decides about unedited ones); never raises out of ensure_own_unit_copies(); a
#          destination in the lock's removed_by_user (or committed once and missing now) stays
#          removed; a symlink/junction, or a file resolving outside its unit folder, is skipped; an
#          unreadable .act-lock.json means nothing is written.
# Call:    python .act/scripts/unit_copies.py          # create what is missing, print what happened

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Optional

import actlib


def _tools(config_tools: str) -> list[str]:
    """The tools to write copies for: the lock's `applied.tools` (what the project's copies were last
    synced for), else docs/ai/config.md § Project `tools`."""
    applied = actlib.read_last_applied()
    listed = applied.get("tools") if isinstance(applied, dict) else None
    if isinstance(listed, list) and all(isinstance(t, str) for t in listed) and listed:
        raw = listed
    else:
        raw = [t for t in config_tools.split(",") if t.strip()]
    return sorted({actlib.normalize_tool(t) for t in raw})


def copy_tools() -> list[str]:
    """The tools to write copies for, as the own-unit copies use them (the lock's `applied.tools`, else
    docs/ai/config.md § Project `tools`); package_load.py writes the copies of packages to the same targets."""
    return _tools(actlib.read_config().get("tools", ""))


def _template_names(root: Path, sub: str) -> set[str]:
    base = root / ".act" / sub
    if not base.is_dir():
        return set()
    if sub == "skills":
        return {p.name.lower() for p in base.iterdir() if p.is_dir()}
    return {p.stem.lower() for p in base.glob("*.md") if p.name.lower() != "readme.md"}


def _own_skills(root: Path) -> list[Path]:
    base = root / "docs" / "ai" / "local" / "skills"
    if not base.is_dir():
        return []
    template = _template_names(root, "skills")
    return sorted(p for p in base.iterdir()
                  if p.is_dir() and ((p / "SKILL.md").is_file() or p.name.lower() in template))


def _own_roles(root: Path) -> list[Path]:
    base = root / "docs" / "ai" / "local" / "agents"
    if not base.is_dir():
        return []
    return sorted(p for p in base.glob("*.md") if p.name.lower() != "readme.md")


def _lock_problem(root: Path) -> str:
    """"" if .act-lock.json is absent or parses to an object, else why it cannot be read — then
    nothing is written (actlib.read_lock() would answer with defaults, and a write would replace
    the unreadable file, merge-conflict markers and all)."""
    path = root / ".act-lock.json"
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return f"{exc.__class__.__name__}: {exc}"
    return "" if isinstance(data, dict) else f"top level is {type(data).__name__}, expected an object"


def _escapes(path: Path, container: Path) -> bool:
    """True if `path` is a symlink, or resolves (junctions, symlinked parents) outside `container`."""
    try:
        if path.is_symlink():
            return True
        path.resolve().relative_to(container.resolve())
    except (OSError, ValueError):
        return True
    return False


def _link_like(directory: Path, base: Path) -> bool:
    """True if `directory` is a symlink or a junction: it does not resolve to base/<its own name>."""
    try:
        return directory.is_symlink() or directory.resolve() != base.resolve() / directory.name
    except OSError:
        return True


def dest_is_linked(root: Path, dest_rel: str) -> bool:
    """True if the file `dest_rel` (root-relative), or any folder above it below `root`, is a symlink
    or a junction — a write there would land outside the project's own tree."""
    dest = root / dest_rel
    try:
        if dest.is_symlink():
            return True
        return any(_link_like(folder, folder.parent) for folder in dest.parents
                   if folder != root and root in folder.parents)
    except OSError:
        return True


def ensure_own_unit_copies(
    root: Path, history_check: Optional[Callable[[list[str]], set[str]]] = None,
) -> tuple[list[str], dict[str, dict], list[Path]]:
    """Create the missing tool copies of every own skill and own role, and bring a tracked, unedited
    copy of an own skill up to its source.

    Returns (messages, recorded, touched): one line per thing worth saying (created, refreshed, foreign
    copy kept, name collision), the "copies" entries this call added or changed in .act-lock.json (the
    caller of an update merges them into the value it writes itself), and the files it created or
    refreshed. A call with nothing to do returns ([], {}, []) and writes nothing — a second call
    changes nothing. Any error ends in one message line, never an exception.

    A tracked copy (key in the lock's copies) of an own skill: if it still matches its recorded hash
    and differs from what its source would write, it is overwritten and re-recorded ("refreshed from
    its source"); if it already equals that, a stale recorded hash is re-recorded silently; if it
    differs from both (edited by hand), it is left alone, no write, no message. A tracked copy that
    is missing stays for update.py to decide.

    A destination listed in the lock's removed_by_user is never recreated; `history_check` (update.py's
    _paths_in_git_history) additionally names destinations that were committed once and are missing
    now — deleted by the project — and those stay deleted too. A symlinked/junctioned skill folder or
    file, and a file resolving outside its own unit folder, is skipped with a note. An unreadable
    .act-lock.json means nothing is done and nothing written."""
    messages: list[str] = []
    recorded: dict[str, dict] = {}
    touched: list[Path] = []
    try:
        skills, roles = _own_skills(root), _own_roles(root)
        if not skills and not roles:
            return messages, recorded, touched
        problem = _lock_problem(root)
        if problem:
            messages.append(f"own skill/role copies not checked: .act-lock.json is unreadable ({problem}) — "
                            "fix or restore it, nothing was written")
            return messages, recorded, touched
        import init  # deferred: only a project with own units pays for it

        tools = _tools(actlib.read_config().get("tools", ""))
        template_skills = _template_names(root, "skills")
        template_roles = _template_names(root, "agents")
        lock = actlib.read_lock()
        copies: dict[str, dict] = dict(lock.get("copies", {}))
        removed_by_user = set(lock.get("removed_by_user", []))
        tiers_data = init.tiers.load_tiers(root)
        overrides = init.tiers.read_role_overrides(root)

        # every copy that is missing and may be made: (dest key, source file) / (bridge, role file, source)
        skill_jobs: list[tuple[str, Path]] = []
        tracked_jobs: list[tuple[str, Path]] = []  # tracked copies of own skills: followed to their source
        role_jobs: list[tuple[str, Path, Path]] = []
        skills_base = root / "docs" / "ai" / "local" / "skills"
        for skill_dir in skills:
            name = skill_dir.name
            if name.lower() in template_skills:
                messages.append(
                    f"skill '{name}' in docs/ai/local/skills/ has the name of a template skill — "
                    "treated as its override, no own copy made")
                continue
            if _link_like(skill_dir, skills_base):
                messages.append(f"skill '{name}' is a symlink or junction — skipped, no copy made")
                continue
            for src in sorted(p for p in skill_dir.rglob("*")
                              if p.is_file() and not actlib.is_bytecode_cache(p.relative_to(skill_dir))):
                rel = f"{name}/{src.relative_to(skill_dir).as_posix()}"
                if _escapes(src, skill_dir):
                    messages.append(f"docs/ai/local/skills/{rel}: symlink or outside its skill folder — skipped")
                    continue
                for dest_root, gate in init.SKILL_TARGET_DIRS:
                    if not init._skill_target_active(gate, tools):
                        continue
                    key = f"{dest_root}/{rel}"
                    if key in removed_by_user:
                        continue  # removed by hand: stays removed
                    if key in copies:
                        tracked_jobs.append((key, src))  # tracked: follows its source, below
                        continue
                    skill_jobs.append((key, src))

        own_dir = (root / "docs" / "ai" / "local" / "agents").resolve()
        if roles and any(actlib.normalize_tool(t) in ("claude-code", "copilot") for t in tools):
            targets = init.agent_bridge_targets(root, tools)
            for role_path in roles:
                lowered = role_path.stem.lower()
                if lowered in template_roles or (lowered.endswith("-high") and lowered[:-5] in template_roles):
                    messages.append(
                        f"role '{role_path.stem}' in docs/ai/local/agents/ has the name of a template role "
                        "(or its -high variant) — treated as its override, no own bridge made")
                    continue
                if _escapes(role_path, own_dir):
                    messages.append(f"docs/ai/local/agents/{role_path.name}: symlink or outside its folder — skipped")
                    continue
                for dest_rel, src in targets.items():
                    if init.bridge_target_parts(dest_rel)[1] != role_path.stem:
                        continue
                    if src.resolve() != role_path.resolve():
                        continue
                    if dest_rel in removed_by_user or (root / dest_rel).is_file():
                        continue  # removed by hand: stays removed; present: only model/effort are refreshed
                    role_jobs.append((dest_rel, role_path, src))

        missing = [key for key, _src in skill_jobs if not (root / key).is_file()]
        missing += [dest_rel for dest_rel, _role_path, _src in role_jobs]
        deleted_before = history_check(missing) if history_check is not None and missing else set()

        for key, src in skill_jobs:
            dest = root / key
            if key in deleted_before and not dest.is_file():
                continue  # committed once, missing now: the project deleted it
            data = init.skill_copy_bytes(root, key, src, tiers_data, overrides)
            entry = {"source": src.relative_to(root).as_posix(), "sha256": actlib.lock_hash(data)}
            if dest.is_file():
                if actlib.fold_crlf(dest.read_bytes()) == actlib.fold_crlf(data):
                    recorded[key] = entry  # identical, hand-placed: taken over
                else:
                    messages.append(f"{key}: present with other content, kept, not taken over")
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            recorded[key] = entry
            touched.append(dest)
            messages.append(f"{key}: created")
        for key, src in tracked_jobs:
            dest = root / key
            if dest_is_linked(root, key) or not dest.is_file():
                continue  # missing: update.py decides; a link (file or folder) is never written through
            try:
                data = init.skill_copy_bytes(root, key, src, tiers_data, overrides)
                new_hash = actlib.lock_hash(data)
                old_hash = copies[key].get("sha256") if isinstance(copies[key], dict) else None
                current = dest.read_bytes()
                entry = {"source": src.relative_to(root).as_posix(), "sha256": new_hash}
                if actlib.fold_crlf(current) == actlib.fold_crlf(data):
                    if old_hash != new_hash:
                        recorded[key] = entry  # stale hash on a copy equal to its source: re-recorded
                elif actlib.matches_lock_hash(current, old_hash):
                    dest.write_bytes(data)  # unedited, and its source moved on
                    recorded[key] = entry
                    touched.append(dest)
                    messages.append(f"{key}: refreshed from its source")
                # else: edited by hand (differs from both) — left alone, doctor.py names it
            except OSError as exc:  # one unwritable copy must not stop the rest
                messages.append(f"{key}: not refreshed ({exc.__class__.__name__}: {exc})")
        if recorded:
            copies.update(recorded)
            actlib.write_lock({"copies": copies})

        for dest_rel, role_path, src in role_jobs:
            if dest_rel in deleted_before:
                continue
            dest = root / dest_rel
            text, created = init.write_agent_bridge_file(
                role_path.stem, src, dest, False, root, tiers_data, overrides, False)
            if created:
                touched.append(dest)
                messages.append(f"{dest_rel}: created")
            else:
                messages.append(text)
    except Exception as exc:  # noqa: BLE001 — a session start must never fail over this best-effort step
        messages.append(f"own skill/role copies not checked ({exc.__class__.__name__}: {exc})")
    return messages, recorded, touched


def main(argv: Optional[list[str]] = None) -> int:
    # Messages can carry non-ASCII characters (em dash); a Windows console or a redirect otherwise
    # uses a legacy code page instead of UTF-8, which would corrupt or crash on them. Same fix as
    # .act/scripts/rules.py.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    argparse.ArgumentParser(
        description="Create the missing tool copies of the project's own skills (docs/ai/local/skills/) "
                    "and roles (docs/ai/local/agents/); idempotent, prints what happened.",
    ).parse_args(argv)
    root = actlib.repo_root()
    messages, _recorded, _touched = ensure_own_unit_copies(root)
    for line in messages or ["own skill/role copies: nothing to do"]:
        print(f"[act] {line}")
    return 0


if __name__ == "__main__":
    try:
        from usage import count_script_run
        count_script_run(__file__)
    except ImportError:
        pass
    sys.exit(main(sys.argv[1:]))
