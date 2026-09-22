#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Pull a newer state of the template into an already-initialized project. Nine steps,
#          always in the same order: fetch the template into a temp checkout (nothing from it is
#          run), check whether the project edited .act/ itself since the last update, show the
#          old -> new diff (rule/coding IDs individually), get the user's consent, replace .act/,
#          refresh the template-owned "copies" living outside .act/, run any due migrations, hand
#          off to doctor.py, and write .act-lock.json plus a commit. See
#          docs/project/concepts/ai-dev-app/05-update-and-overrides.md § "Ablauf eines Updates"
#          in the template-pflege repo for the full spec this implements. Stdlib only.
#
# Usage:
#   python .act/scripts/update.py                       # update from the "template" remote / lock source
#   python .act/scripts/update.py --source <path-or-url> --ref <tag-or-commit>
#   python .act/scripts/update.py --plan                 # show steps 1-3, describe 5-9, write nothing
#   python .act/scripts/update.py --yes                  # skip the interactive consent prompt (step 4)
#   python .act/scripts/update.py --on-local-changes rescue|discard|abort   # skip the step-2 prompt
#   python .act/scripts/update.py --non-interactive       # never prompt (implies a default answer)
#   python .act/scripts/update.py --no-commit             # do everything except the final commit
#
# Output format: one numbered line per step ("[n/9] ..."), 1..9 (--plan stops after 3, then one
#   descriptive line each for 5-9), plus a closing "[act] done" line. Exit 0 on success or a clean
#   --plan/abort, 1 if a fatal precondition is not met (no source resolvable, fetch failed, the
#   user chose abort at step 2 or declined at step 4).

from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import actlib
import manifest
import rules


# ---------------------------------------------------------------------------
# Categories — for grouping the step-3 diff the way the spec asks for it
# ---------------------------------------------------------------------------

CATEGORY_DIRS = ("rules", "coding", "skills", "agents", "scripts", "bridges", "hooks", "skeleton")


def _categorize(rel_path: str) -> str:
    top = rel_path.split("/", 1)[0]
    return top if top in CATEGORY_DIRS else "other"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8"
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def _print_step(n: int, text: str) -> None:
    print(f"[{n}/9] {text}")


def _ask_choice(prompt_text: str, choices: tuple[str, ...], default: str) -> str:
    raw = input(f"{prompt_text} [{'/'.join(choices)}] ({default}): ").strip().lower()
    return raw if raw in choices else default


def _make_writable_and_retry(func, path_str, _exc) -> None:
    """onerror/onexc handler for shutil.rmtree: `git clone` leaves files read-only under
    `.git/objects/` on Windows, which rmtree cannot remove without this. Used for both onerror
    (Python < 3.12, gets an exc_info tuple as `_exc`) and onexc (3.12+, gets the exception
    instance) — neither is inspected, both just retry after chmod."""
    try:
        os.chmod(path_str, stat.S_IWRITE)
    except OSError:
        pass
    func(path_str)


def _rmtree_robust(path: Path) -> None:
    """shutil.rmtree that survives the read-only files `git clone` leaves on Windows, so two
    updates in a row from a git source both succeed instead of the second failing to clean up
    after the first."""
    if not path.exists():
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_make_writable_and_retry)
    else:
        shutil.rmtree(path, onerror=_make_writable_and_retry)


def _read_version_file(act_dir: Path) -> tuple[str, str]:
    data = {"version": "", "commit": ""}
    path = act_dir / "VERSION"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() in data:
                data[key.strip()] = value.strip()
    return data["version"], data["commit"]


# ---------------------------------------------------------------------------
# Step 1 — fetch the template into a temp checkout, nothing from it is run
# ---------------------------------------------------------------------------

def _default_source(root: Path) -> str:
    """The "template" remote if the repo has one, else the source recorded in .act-lock.json
    from the last update/init — never a guess."""
    result = _git(["remote", "get-url", "template"], cwd=root, check=False)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    lock = actlib.read_lock()
    return str(lock.get("template", {}).get("source", "") or "")


def _reject_symlinks(act_dir: Path) -> None:
    """Refuses a fetched .act/ tree that contains a symlink. The "nothing from a fetched ref is
    executed" guarantee this script relies on does not cover a symlink pointing outside the
    checkout, which step 5's copytree would otherwise happily follow into the project."""
    for path in act_dir.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(f"fetched .act/ contains a symlink, refusing: {path}")


def step_fetch(source: str, ref: Optional[str], dest: Path, notes: list[str]) -> Path:
    """Fetch `source` (a local directory or a git URL/local repo) into `dest`, at `ref` if given.
    Returns the fetched checkout's .act/ directory. Nothing under `dest` is ever executed here —
    only copied or cloned. A plain local directory (no .git) has only its .act/ copied, matching
    the test fixtures used for this script and so that `--source .` (the project itself) does not
    try to copy itself into itself; a git source (local repo or remote URL) is cloned in full."""
    src_path = Path(source)
    if src_path.is_dir() and not (src_path / ".git").exists():
        if ref:
            notes.append(f"--ref '{ref}' ignored: source '{source}' is a plain directory, not a git checkout")
        src_act = src_path / ".act"
        if not src_act.is_dir():
            raise RuntimeError(f"source has no .act/ directory: {src_path}")
        shutil.copytree(
            src_act, dest / ".act", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        _git(["clone", "--quiet", "--", str(source), str(dest)], cwd=dest.parent)
        if ref:
            _git(["checkout", "--quiet", ref], cwd=dest)
    act_dir = dest / ".act"
    if not act_dir.is_dir():
        raise RuntimeError(f"fetched checkout has no .act/ directory: {dest}")
    _reject_symlinks(act_dir)
    return act_dir


# ---------------------------------------------------------------------------
# Step 2 — local changes in the project's own .act/, against its MANIFEST.json
# ---------------------------------------------------------------------------

def _local_act_differences(act_dir: Path) -> Optional[list[str]]:
    """Same comparison as `manifest.py --check`, without its stdout — returns the list of
    "<path>:<state>" differences, or None if there is no MANIFEST.json to compare against (the
    spec's "no manifest -> treat as no detectable change")."""
    manifest_path = act_dir / "MANIFEST.json"
    if not manifest_path.is_file():
        return None
    try:
        recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    current = manifest.collect_files(act_dir)
    differences: list[str] = []
    for path, recorded_hash in sorted(recorded.items()):
        if path not in current:
            differences.append(f"{path}:missing")
        elif current[path] != recorded_hash:
            differences.append(f"{path}:modified")
    for path in sorted(current):
        if path not in recorded:
            differences.append(f"{path}:added")
    return differences


def _local_act_differences_from_git(root: Path) -> Optional[list[str]]:
    """Fallback for `_local_act_differences` when there is no MANIFEST.json to compare against:
    `git status --porcelain -- .act` tells us which files under .act/ the project has changed or
    added in its working tree. Returns None if git itself can't answer here (not a repo, git
    binary missing) so the caller falls back to its old "nothing detectable" message instead of
    guessing."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", ".act"],
            cwd=root, capture_output=True, text=True, encoding="utf-8",
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    differences: set[str] = set()
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        status, path = line[:2], line[3:]
        if " -> " in path:  # rename: "old -> new"
            path = path.split(" -> ", 1)[1]
        if not path.startswith(".act/"):
            continue
        rel = path[len(".act/"):]
        if "D" in status:
            state = "missing"
        elif status.strip() == "??" or "A" in status:
            state = "added"
        else:
            state = "modified"
        differences.add(f"{rel}:{state}")
    return sorted(differences)


def step_check_local_changes(
    root: Path, on_local_changes: Optional[str], interactive: bool, plan: bool,
) -> tuple[str, Optional[str], list[str]]:
    """Returns (summary, decision, differences). decision is None if there was nothing to decide
    (no manifest and no git, or no differences); otherwise one of "rescue"/"discard"/"abort"."""
    act_dir = root / ".act"
    differences = _local_act_differences(act_dir)
    via_git = False
    if differences is None:
        differences = _local_act_differences_from_git(root)
        via_git = differences is not None
        if differences is None:
            return (
                "no MANIFEST.json to compare against, git unavailable too -> treated as no detectable local change",
                None, [],
            )

    prefix = "local changes in .act/ (via git status, no MANIFEST.json)" if via_git else "local changes in .act/"
    if not differences:
        return (f"no local changes in .act/{' (checked via git status, no MANIFEST.json)' if via_git else ''}", None, [])

    shown = "; ".join(differences)
    if plan:
        return f"{prefix}: {shown} (--plan: not acted on)", None, differences

    if on_local_changes in ("rescue", "discard", "abort"):
        decision = on_local_changes
    elif interactive:
        print(f"[act] {prefix}: {shown}")
        decision = _ask_choice(
            "  rescue to docs/ai/local/, discard, or abort the update?", ("rescue", "discard", "abort"), "abort",
        )
    else:
        decision = "abort"

    return f"{prefix}: {shown} -> {decision}", decision, differences


def _unique_rescue_dest(local_dir: Path, rel: str) -> Path:
    """docs/ai/local/<rel> if that path is free; otherwise <rel>.from-act-<today>, numbered
    further (-2, -3, ...) on collision. Never points at an existing file — a rescue must never
    overwrite something a project already keeps under docs/ai/local/."""
    dest = local_dir / rel
    if not dest.exists():
        return dest
    base = f"{rel}.from-act-{date.today().isoformat()}"
    candidate = local_dir / base
    n = 2
    while candidate.exists():
        candidate = local_dir / f"{base}-{n}"
        n += 1
    return candidate


def _rescue_local_changes(root: Path, differences: list[str]) -> list[tuple[Path, bool]]:
    """Copy every changed/added file's current content to docs/ai/local/<same path>, so it keeps
    winning over the template (actlib.resolve()) after .act/ is replaced. A "missing" entry (the
    project deleted a template file) has nothing to rescue and is skipped. Returns (dest, used_
    fallback_name) pairs — used_fallback_name is True when docs/ai/local/<rel> already existed and
    the rescue was written under a ".from-act-<date>" name instead, to report in the log."""
    act_dir = root / ".act"
    local_dir = root / "docs" / "ai" / "local"
    rescued: list[tuple[Path, bool]] = []
    for entry in differences:
        rel, _, state = entry.rpartition(":")
        if state == "missing":
            continue
        src = act_dir / rel
        if not src.is_file():
            continue
        dest = _unique_rescue_dest(local_dir, rel)
        used_fallback = dest != local_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        rescued.append((dest, used_fallback))
    return rescued


# ---------------------------------------------------------------------------
# Step 3 — show the old -> new diff, categorized; rule/coding files by ID
# ---------------------------------------------------------------------------

def _collect_tree(act_dir: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(act_dir.rglob("*")):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            continue
        if path.name == "MANIFEST.json":
            continue
        files[path.relative_to(act_dir).as_posix()] = actlib.sha256_file(path)
    return files


def _rule_id_diff(old_path: Optional[Path], new_path: Optional[Path]) -> tuple[list[str], list[str], list[str]]:
    """(added_ids, changed_ids, removed_ids) between an old and a new version of the same
    rule/coding set file. Either side may be missing (file added/removed outright). Never raises
    — a file this template's rule grammar can't parse (see rules.py) just yields no IDs, and the
    caller falls back to reporting it as a plain file change."""
    try:
        old_groups = rules.parse_template_set(old_path, "template").groups if old_path else {}
        new_groups = rules.parse_template_set(new_path, "template").groups if new_path else {}
    except OSError:
        return [], [], []
    added = sorted(set(new_groups) - set(old_groups))
    removed = sorted(set(old_groups) - set(new_groups))
    changed = sorted(
        gid for gid in (set(old_groups) & set(new_groups)) if old_groups[gid].body != new_groups[gid].body
    )
    return added, changed, removed


def _print_content_diff(old_path: Path, new_path: Path, limit: int = 20) -> None:
    """Best-effort, capped unified diff for a changed non-rule file — rule/coding .md files keep
    the ID view instead (see the caller). Silently skipped for anything not decodable as UTF-8
    text (binary files); nothing useful to show line by line there."""
    try:
        old_lines = old_path.read_text(encoding="utf-8").splitlines()
        new_lines = new_path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return
    diff_lines = list(difflib.unified_diff(old_lines, new_lines, lineterm=""))
    if not diff_lines:
        return
    for line in diff_lines[:limit]:
        print(f"[act]       {line}")
    remaining = len(diff_lines) - limit
    if remaining > 0:
        print(f"[act]       ... {remaining} more lines")


def step_show_diff(root: Path, new_act_dir: Path) -> tuple[str, bool]:
    """Prints the categorized diff to stdout. Returns (summary, has_changes)."""
    old_act_dir = root / ".act"
    old_files = _collect_tree(old_act_dir)
    new_files = _collect_tree(new_act_dir)

    added = sorted(set(new_files) - set(old_files))
    removed = sorted(set(old_files) - set(new_files))
    changed = sorted(p for p in (set(old_files) & set(new_files)) if old_files[p] != new_files[p])

    if not added and not removed and not changed:
        return "no differences between the current and the fetched .act/", False

    by_category: dict[str, dict[str, list[str]]] = {}
    for state, paths in (("added", added), ("removed", removed), ("changed", changed)):
        for p in paths:
            by_category.setdefault(_categorize(p), {}).setdefault(state, []).append(p)

    for category in (*CATEGORY_DIRS, "other"):
        entries = by_category.get(category)
        if not entries:
            continue
        print(f"[act]   {category}:")
        for state in ("added", "changed", "removed"):
            for rel in entries.get(state, []):
                print(f"[act]     {state}: {rel}")
                if category in ("rules", "coding") and rel.endswith(".md"):
                    old_p = old_act_dir / rel if (old_act_dir / rel).is_file() else None
                    new_p = new_act_dir / rel if (new_act_dir / rel).is_file() else None
                    id_added, id_changed, id_removed = _rule_id_diff(old_p, new_p)
                    for gid in id_added:
                        print(f"[act]       + `{gid}`")
                    for gid in id_changed:
                        print(f"[act]       ~ `{gid}`")
                    for gid in id_removed:
                        print(f"[act]       - `{gid}`")
                elif state == "changed":
                    _print_content_diff(old_act_dir / rel, new_act_dir / rel)

    return f"{len(added)} added, {len(changed)} changed, {len(removed)} removed", True


# ---------------------------------------------------------------------------
# Step 5 — replace .act/, rebuild MANIFEST.json
# ---------------------------------------------------------------------------

def step_replace(root: Path, new_act_dir: Path, plan: bool) -> str:
    if plan:
        return "would remove and replace .act/ with the fetched template, then rebuild MANIFEST.json"
    act_dir = root / ".act"
    if act_dir.exists():
        shutil.rmtree(act_dir)
    shutil.copytree(
        new_act_dir, act_dir, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    manifest.write_manifest(act_dir)
    return "replaced .act/ and rebuilt MANIFEST.json"


# ---------------------------------------------------------------------------
# Step 6 — refresh template-owned skill copies, create bridges for new roles
# ---------------------------------------------------------------------------

# Skill copies (.act/skills/<name>/**, materialized under .claude/skills/ and .agents/skills/ by
# init.py's copy_targets()) go through all four cases the spec asks for — handled below in
# step_refresh_copies(). Role bridges (.act/agents/<name>.md paired with
# .act/bridges/agents/<name>.md, init.py's agent_bridge_targets()) are simpler and handled
# separately in step_new_role_bridges(): an existing one is never touched again, only a role new
# since the last update gets a bridge created.
_PROBE_MODULE_NAMES = ("actlib", "rules", "init", "tiers")


def _project_tools(root: Path) -> list[str]:
    """The project's configured tools (docs/ai/config.md § Project, key "tools"), lowercased —
    the same gate copy_targets()/agent_bridge_targets() use to decide which destinations apply."""
    raw = actlib.read_config().get("tools", "")
    return sorted({t.strip().lower() for t in raw.split(",") if t.strip()})


def _import_fresh_init(new_scripts_dir: Path):
    """
    Import .act/scripts/init.py fresh from the just-installed (step 5 already ran) template, to
    call its copy_targets()/agent_bridge_targets(). Safe to import at this point: step 4 already
    got the user's consent to trust this template state, and by step 5 it is the project's own
    .act/ on disk, not code sitting in the temp checkout. Imported in isolation — the module cache
    entries for actlib/rules/init are swapped out before the import and restored afterwards, so
    the rest of this run keeps using the (older) actlib/rules it already loaded at start-up.
    Returns None on any import error (e.g. an init.py that predates these functions).
    """
    saved = {name: sys.modules.pop(name, None) for name in _PROBE_MODULE_NAMES}
    sys.path.insert(0, str(new_scripts_dir))
    try:
        return importlib.import_module("init")
    except Exception:
        return None
    finally:
        try:
            sys.path.remove(str(new_scripts_dir))
        except ValueError:
            pass
        for name in _PROBE_MODULE_NAMES:
            sys.modules.pop(name, None)
        for name, module in saved.items():
            if module is not None:
                sys.modules[name] = module


def _copy_source_label(root: Path, src: Path) -> str:
    """Project-relative path for a copy's "source" field in .act-lock.json — usually under
    .act/ (e.g. ".act/skills/probe-skill/SKILL.md"), or under docs/ai/local/ when the project
    overrides that file (actlib.resolve(), see init.py's copy_targets())."""
    return src.relative_to(root).as_posix()


def _prune_empty_copy_dirs(start: Path, bases: set[Path], root: Path) -> None:
    """Removes `start`'s parent directory chain while it is empty, stopping at (and never
    removing) one of `bases` — the skill-copy target roots (.claude/skills, .agents/skills, ...).
    Used after deleting a no-longer-shipped copy, so an emptied skill folder does not linger.
    Never climbs above `root` or outside `bases` — if `bases` is empty (no SKILL_TARGET_DIRS found
    on the imported module) or `start` sits outside every base, nothing is removed."""
    if not any(base in start.parents for base in bases):
        return
    current = start.parent
    while current not in bases and current != root and current.is_dir():
        try:
            next(current.iterdir())
            return  # not empty
        except StopIteration:
            pass
        parent = current.parent
        current.rmdir()
        current = parent


def step_refresh_copies(root: Path, plan: bool) -> tuple[str, dict[str, dict]]:
    """Five cases per template-owned skill copy, exactly as the spec lists them: unchanged ->
    replaced; user-edited -> kept, reported; user-deleted -> left deleted (tracked in
    removed_by_user, same field init.py's lock skeleton already reserves for this); no longer
    shipped by the template (removed or renamed there) -> the project's copy is deleted if it
    still matches what the template last shipped (the project never edited it), or kept and
    reported "no longer shipped, kept (edited)" if the project changed it since; new in the
    template -> created. Returns (summary, new_copies) where new_copies is what .act-lock.json's
    "copies" key should become.

    If the updated template's init.py cannot be imported (see _import_fresh_init()), this step is
    aborted entirely rather than silently treating every copy as "no longer shipped" — that would
    drop every copy out of the lock and stop them from ever being refreshed again."""
    if plan:
        return "would replace unchanged copies, keep edited ones (reported), leave deleted ones deleted, create new ones", {}

    lock = actlib.read_lock()
    old_copies: dict[str, dict] = dict(lock.get("copies", {}))
    removed_by_user: list[str] = list(lock.get("removed_by_user", []))

    new_init = _import_fresh_init(root / ".act" / "scripts")
    if new_init is None:
        return "could not load copy_targets() from the updated template; copies left untouched", old_copies
    new_specs: dict[str, Path] = dict(new_init.copy_targets(root, _project_tools(root)))
    copy_bases = {root / dest_root for dest_root, _ in getattr(new_init, "SKILL_TARGET_DIRS", ())}

    new_copies: dict[str, dict] = {}
    replaced, kept, left_deleted, created = [], [], [], []
    no_longer_shipped_removed, no_longer_shipped_kept = [], []
    present_not_taken_over = []

    for dest_rel, old_entry in old_copies.items():
        source_path = new_specs.pop(dest_rel, None)
        dest_path = root / dest_rel
        if source_path is None:
            # the template stopped shipping this copy (removed, or renamed to a different path)
            if not dest_path.is_file():
                continue  # already gone — nothing to remove, nothing left to track
            current_hash = actlib.sha256_file(dest_path)
            if current_hash == old_entry.get("sha256"):
                dest_path.unlink()
                _prune_empty_copy_dirs(dest_path, copy_bases, root)
                no_longer_shipped_removed.append(dest_rel)
            else:
                new_copies[dest_rel] = old_entry
                no_longer_shipped_kept.append(dest_rel)
            continue
        if not dest_path.is_file():
            if dest_rel not in removed_by_user:
                removed_by_user.append(dest_rel)
            left_deleted.append(dest_rel)
            continue
        current_hash = actlib.sha256_file(dest_path)
        if current_hash == old_entry.get("sha256"):
            data = source_path.read_bytes()
            dest_path.write_bytes(data)
            new_hash = hashlib.sha256(data).hexdigest()
            new_copies[dest_rel] = {"source": _copy_source_label(root, source_path), "sha256": new_hash}
            replaced.append(dest_rel)
        else:
            new_copies[dest_rel] = old_entry
            kept.append(dest_rel)

    for dest_rel, source_path in new_specs.items():
        if dest_rel in removed_by_user:
            continue  # the project deliberately removed this one before; do not resurrect it
        dest_path = root / dest_rel
        if dest_path.is_file():
            # something is already there that this run did not put there — leave it, but say so
            present_not_taken_over.append(dest_rel)
            continue
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        data = source_path.read_bytes()
        dest_path.write_bytes(data)
        new_copies[dest_rel] = {"source": _copy_source_label(root, source_path), "sha256": hashlib.sha256(data).hexdigest()}
        created.append(dest_rel)

    actlib.write_lock({"removed_by_user": sorted(set(removed_by_user))})

    parts = []
    if replaced:
        parts.append(f"replaced: {', '.join(replaced)}")
    if kept:
        parts.append(f"kept (edited locally): {', '.join(kept)}")
    if left_deleted:
        parts.append(f"left deleted: {', '.join(left_deleted)}")
    if no_longer_shipped_removed:
        parts.append(f"no longer shipped, removed: {', '.join(no_longer_shipped_removed)}")
    if no_longer_shipped_kept:
        parts.append(f"no longer shipped, kept (edited): {', '.join(no_longer_shipped_kept)}")
    if created:
        parts.append(f"created: {', '.join(created)}")
    if present_not_taken_over:
        parts.append(f"present, not taken over: {', '.join(present_not_taken_over)}")
    return ("; ".join(parts) if parts else "no template-owned copies"), new_copies


def step_new_role_bridges(root: Path, plan: bool, notes: Optional[list[str]] = None) -> tuple[str, list[Path]]:
    """Creates a bridge for any role new since the last update, and a "-high" variant for any
    applicable role — new or already existing — that does not have one yet (13-model-tiers.md §
    4/`Q71`, introduced together with the tier/reasoning scheme: an existing project may already
    have base role bridges from before this existed). An existing .claude/agents/<name>.md (base
    or variant) is never re-created here, matching the rule for role bridges (unlike a skill copy,
    never replaced once written — see step_refresh_copies() above and init.py's
    agent_bridge_targets()); its `model`/`effort` frontmatter is refreshed separately, by
    step_refresh_role_frontmatter() below. `notes`, if given, collects messages the same way
    step_fetch() above does (e.g. a role tiers.json/config.md cannot resolve, § "Pflege der
    Zuordnungstabelle"). Returns (summary, touched_paths)."""
    if plan:
        return (
            "would create bridges for roles new since the last update, and any missing "
            "'-high' variant, leaving existing files untouched",
            [],
        )

    new_init = _import_fresh_init(root / ".act" / "scripts")
    if new_init is None:
        return "could not load agent_bridge_targets() from the updated template", []
    tools = _project_tools(root)
    targets: dict[str, Path] = dict(new_init.agent_bridge_targets(root, tools))
    targets.update(new_init.agent_bridge_variant_targets(root, tools))
    tiers_data = new_init.tiers.load_tiers(root)
    overrides = new_init.tiers.read_role_overrides(root, notes=notes)

    created: list[str] = []
    touched: list[Path] = []
    for dest_rel, source_path in sorted(targets.items()):
        dest_path = root / dest_rel
        if dest_path.is_file():
            continue  # existing role bridge (base or variant) — never re-created, only refreshed
        role = Path(dest_rel).stem
        variant = role.endswith("-high")
        base_role = role[: -len("-high")] if variant else role
        try:
            message, ok = new_init.write_agent_bridge_file(
                base_role, source_path, dest_path, False, root, tiers_data, overrides, variant, notes,
            )
        except (OSError, UnicodeDecodeError) as exc:
            if notes is not None:
                notes.append(f"{dest_rel}: skipped, could not create ({exc.__class__.__name__})")
            continue
        if ok:
            created.append(dest_rel)
            touched.append(dest_path)

    return (f"created: {', '.join(created)}" if created else "no new roles or variants"), touched


def step_refresh_role_frontmatter(root: Path, plan: bool, notes: Optional[list[str]] = None) -> tuple[str, list[Path]]:
    """Re-derives the `model`/`effort` frontmatter of every already-materialized role bridge (base
    and "-high" variant alike, template role or a project's own named in docs/ai/config.md §
    Roles) from the updated .act/tiers.json and that Roles table — the one part of a role bridge
    that *does* change on every update, per 13-model-tiers.md § "Pflege der Zuordnungstabelle".
    Everything else in the file, including a project's own text below the frontmatter, is left
    exactly as it is (tiers.py's refresh_project_bridge_frontmatter() carries that guarantee, and
    also never lets a single unreadable/unwritable file abort this step — it is skipped with a note
    instead, so the update still completes even though `.act/` was already replaced by step 5).
    `notes`, if given, collects those messages. Returns (summary, touched_paths)."""
    if plan:
        return (
            "would refresh model/effort frontmatter on every existing role bridge from the "
            "updated tiers table",
            [],
        )

    new_init = _import_fresh_init(root / ".act" / "scripts")
    if new_init is None or not hasattr(new_init, "tiers"):
        return "could not load tiers.py from the updated template; role bridge frontmatter left untouched", []
    try:
        changed = new_init.tiers.refresh_project_bridge_frontmatter(root, notes=notes)
    except (OSError, UnicodeDecodeError) as exc:
        # Belt and suspenders: refresh_project_bridge_frontmatter() already catches these per file
        # and never lets one bad file raise, but this step must not be able to abort the update
        # (already past step 5 -- .act/ is already replaced) even if that guarantee ever slips.
        if notes is not None:
            notes.append(f"role bridge frontmatter refresh failed ({exc.__class__.__name__}); left as it was")
        return "role bridge frontmatter refresh failed, left untouched", []
    touched = [root / rel for rel in changed]
    return (f"refreshed {len(changed)} role bridge(s)" if changed else "no role bridge frontmatter changes"), touched


# ---------------------------------------------------------------------------
# Step 7 — migrations
# ---------------------------------------------------------------------------

# Contract for a migration module (.act/migrations/NNN-slug.py, id = file stem): a plan(root)
# function returning a description without writing anything, and an apply(root) function that
# performs the change and returns (description, touched_paths). Neither is documented elsewhere
# yet (no migration has shipped so far) — this is the minimal shape that satisfies the spec's
# "--plan first, then run, wiederholbar" and is exercised by this script's test fixtures.

def _load_migration(path: Path):
    saved = sys.modules.pop(path.stem, None)
    spec = importlib.util.spec_from_file_location(f"_act_migration_{path.stem}", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception:
        return None
    finally:
        if saved is not None:
            sys.modules[path.stem] = saved
    return module


def _plan_migrations_summary(new_act_dir: Path) -> str:
    """`--plan` preview of step 7: which migrations the fetched checkout would apply, listed by
    filename only. Never imports them — this script never runs code from a freshly fetched ref
    (see the module docstring); a real run only imports a migration once step 5 has made it the
    project's own .act/, which is what makes importing it safe."""
    migrations_dir = new_act_dir / "migrations"
    if not migrations_dir.is_dir():
        return "no .act/migrations/ directory"
    lock = actlib.read_lock()
    applied = set(lock.get("migrations_applied", []))
    due = sorted(p.stem for p in migrations_dir.glob("[0-9][0-9][0-9]-*.py") if p.stem not in applied)
    if not due:
        return "no due migrations"
    return "would run: " + ", ".join(due)


def step_migrate(root: Path, plan: bool) -> tuple[str, list[str], list[Path]]:
    """Returns (summary, newly_applied_ids, touched_paths)."""
    migrations_dir = root / ".act" / "migrations"
    if not migrations_dir.is_dir():
        return "no .act/migrations/ directory", [], []

    lock = actlib.read_lock()
    applied = set(lock.get("migrations_applied", []))
    due = sorted(p for p in migrations_dir.glob("[0-9][0-9][0-9]-*.py") if p.stem not in applied)
    if not due:
        return "no due migrations", [], []

    if plan:
        planned = []
        for path in due:
            module = _load_migration(path)
            description = module.plan(root) if module and hasattr(module, "plan") else "(could not load plan())"
            planned.append(f"{path.stem}: {description}")
        return "would run: " + "; ".join(planned), [], []

    newly_applied: list[str] = []
    touched: list[Path] = []
    ran = []
    for path in due:
        module = _load_migration(path)
        if module is None or not hasattr(module, "apply"):
            ran.append(f"{path.stem}: skipped, could not load")
            continue
        plan_description = module.plan(root) if hasattr(module, "plan") else ""
        print(f"[act]   {path.stem} --plan: {plan_description}")
        result = module.apply(root)
        description, touched_rel = result if isinstance(result, tuple) else (result, [])
        touched.extend(root / rel for rel in touched_rel)
        newly_applied.append(path.stem)
        ran.append(f"{path.stem}: {description}")
        # Recorded right after each success, not once at the end — a later migration's failure
        # must not make this one rerun on the next attempt.
        actlib.write_lock({"migrations_applied": sorted(applied | set(newly_applied))})

    return "; ".join(ran), newly_applied, touched


# ---------------------------------------------------------------------------
# Step 8 — hand off to doctor.py
# ---------------------------------------------------------------------------

def step_doctor(root: Path, plan: bool) -> tuple[str, Optional[Path]]:
    """Returns (summary, inbox_path). doctor.py's own exit codes: 0 = no findings, 1 = findings
    (not an error — it already wrote docs/ai/inbox/<date>-doctor.md), 2 = a real failure."""
    doctor_path = root / ".act" / "scripts" / "doctor.py"
    if not doctor_path.is_file():
        return "doctor not available", None
    if plan:
        return "would run: python .act/scripts/doctor.py --inbox", None
    result = subprocess.run(
        [sys.executable, str(doctor_path), "--inbox"], cwd=root, capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode not in (0, 1):
        detail = (result.stderr or result.stdout).strip().splitlines()
        last = detail[-1] if detail else f"exit code {result.returncode}"
        return f"doctor.py --inbox failed (update not aborted over this): {last}", None
    if result.returncode == 0:
        return "doctor.py --inbox ran, no findings", None

    lines = result.stdout.splitlines()
    inbox_rel = next(
        (line[len("doctor.py: wrote "):].strip() for line in lines if line.startswith("doctor.py: wrote ")), None,
    )
    count_match = re.match(r"(\d+) finding", lines[-1].strip()) if lines else None
    count = count_match.group(1) if count_match else "some"
    inbox_path = root / inbox_rel if inbox_rel else None
    where = inbox_rel if inbox_rel else "docs/ai/inbox/"
    return f"{count} finding(s) -> {where}", inbox_path


# ---------------------------------------------------------------------------
# Step 9 — .act-lock.json + commit
# ---------------------------------------------------------------------------

def step_lock(root: Path, plan: bool, source: str, new_copies: dict[str, dict]) -> str:
    if plan:
        return "would update .act-lock.json (template.version/commit/source, copies, migrations)"
    version, commit = _read_version_file(root / ".act")
    actlib.write_lock({
        "template": {"version": version, "commit": commit, "source": source},
        "copies": new_copies,
    })
    return f"lock updated (version '{version}')"


def step_commit(root: Path, plan: bool, no_commit: bool, paths: list[Path]) -> str:
    if no_commit:
        return "--no-commit: left staged/unstaged for the caller"
    rels = sorted({str(p.relative_to(root)).replace("\\", "/") for p in paths if p.exists()})
    if not rels:
        return "nothing to commit"
    if plan:
        return f"would commit {len(rels)} path(s): {', '.join(rels)}"
    _git(["add", "--", *rels], cwd=root)
    diff = _git(["diff", "--cached", "--quiet", "--", *rels], cwd=root, check=False)
    if diff.returncode == 0:
        return "nothing staged, no commit made"
    if diff.returncode != 1:
        raise RuntimeError(f"git diff --cached --quiet failed: {diff.stderr.strip()}")
    # `-- rels` restricts the commit to these paths, same as the add above — never the whole
    # index, so changes staged elsewhere by something else running concurrently stay untouched.
    _git(["commit", "-m", "chore: update template", "--", *rels], cwd=root)
    sha = _git(["rev-parse", "--short", "HEAD"], cwd=root).stdout.strip()
    return f"committed {len(rels)} path(s) as {sha}"


# ---------------------------------------------------------------------------
# Branch hint
# ---------------------------------------------------------------------------



def _default_branch(root: Path) -> Optional[str]:
    result = _git(["symbolic-ref", "refs/remotes/origin/HEAD"], cwd=root, check=False)
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().rsplit("/", 1)[-1]
    result = _git(["branch", "--show-current"], cwd=root, check=False)
    return result.stdout.strip() or None


def _maybe_print_branch_hint(root: Path, notes: list[str]) -> None:
    config = actlib.read_config()
    if config.get("update-branch-hint", "").strip().lower() == "off":
        return
    current = _git(["branch", "--show-current"], cwd=root, check=False).stdout.strip()
    default = _default_branch(root)
    if not current or not default or current == default:
        return
    print(
        "[act] This changes rules and bridges project-wide; on a feature branch the others get "
        "it only with the merge."
    )


# ---------------------------------------------------------------------------
# Resume detection — step 3 found no .act/ diff, but a previous run may have been interrupted
# between step 5 (replace) and step 9 (lock write)
# ---------------------------------------------------------------------------

def _resume_needed(root: Path) -> bool:
    """True when .act/ already matches the fetched template (step_show_diff found nothing) but
    the lock's recorded template version/commit does not match what's on disk, or a migration
    under .act/migrations/ is still due — both signs of a run that got as far as step 5 but never
    reached step 9. Steps 6-9 then still need to run instead of reporting "nothing to update"."""
    lock = actlib.read_lock()
    template = lock.get("template", {})
    disk_version, disk_commit = _read_version_file(root / ".act")
    if disk_version != template.get("version", "") or disk_commit != template.get("commit", ""):
        return True
    migrations_dir = root / ".act" / "migrations"
    if not migrations_dir.is_dir():
        return False
    applied = set(lock.get("migrations_applied", []))
    return any(p.stem not in applied for p in migrations_dir.glob("[0-9][0-9][0-9]-*.py"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    # Same Windows console-encoding fix as every other script here (em dash in messages below).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="Pull a newer state of the template into this project.")
    parser.add_argument("--source", help="local directory or git URL/repo to update from (default: 'template' remote, else .act-lock.json)")
    parser.add_argument("--ref", help="tag or commit to update to (default: the source's default branch tip)")
    parser.add_argument("--on-local-changes", choices=("rescue", "discard", "abort"), help="skip the step-2 prompt")
    parser.add_argument("--yes", action="store_true", help="skip the interactive consent prompt (step 4)")
    parser.add_argument("--plan", action="store_true", help="show steps 1-3, describe 5-9, change nothing")
    parser.add_argument("--no-commit", action="store_true", help="do everything except the final commit")
    parser.add_argument("--non-interactive", action="store_true", help="never prompt")
    args = parser.parse_args(argv)

    plan = args.plan
    root = actlib.repo_root()
    interactive = actlib.is_interactive() and not plan
    notes: list[str] = []

    source = args.source or _default_source(root)
    if not source:
        print("update.py: no --source given, no 'template' remote, and no source in .act-lock.json", file=sys.stderr)
        return 1

    tmp_root = Path(root) / ".act-local" / "update-tmp"
    _rmtree_robust(tmp_root)
    tmp_root.mkdir(parents=True, exist_ok=True)
    try:
        new_act_dir = step_fetch(source, args.ref, tmp_root / "checkout", notes)
        _print_step(1, f"fetched '{source}'" + (f" @ {args.ref}" if args.ref else "") + f" -> {new_act_dir}")

        check_summary, decision, differences = step_check_local_changes(root, args.on_local_changes, interactive, plan)
        _print_step(2, check_summary)
        if decision == "abort":
            print("[act] update aborted: local changes in .act/ were not resolved")
            return 1

        diff_summary, has_changes = step_show_diff(root, new_act_dir)
        _print_step(3, diff_summary)

        if plan:
            print("[act]   [5/9] " + step_replace(root, new_act_dir, True))
            print(
                "[act]   [6/9] " + step_refresh_copies(root, True)[0]
                + "; roles: " + step_new_role_bridges(root, True)[0]
                + "; role frontmatter: " + step_refresh_role_frontmatter(root, True)[0]
            )
            print("[act]   [7/9] " + _plan_migrations_summary(new_act_dir))
            print("[act]   [8/9] " + step_doctor(root, True)[0])
            print("[act]   [9/9] " + step_lock(root, True, source, {}))
            print("[act] done - --plan: nothing was written")
            return 0

        if not has_changes:
            if _resume_needed(root):
                print(
                    "[act]   .act/ already matches the fetched template; resuming an interrupted "
                    "update (stale lock or migrations still due)"
                )
            else:
                print("[act] done - nothing to update")
                return 0

        if args.yes:
            consented = True
        elif interactive:
            consented = _ask_choice("[act] Apply this update?", ("y", "n"), "n") == "y"
        else:
            consented = False
        _print_step(4, "consent given" if consented else "consent not given (pass --yes to apply non-interactively)")
        if not consented:
            print("[act] update aborted: no consent")
            return 1

        # The rescue itself only runs once the update is actually approved — a decision made at
        # step 2 must not touch the filesystem if step 4 then declines the whole update.
        if decision == "rescue":
            rescued = _rescue_local_changes(root, differences)
            print(f"[act]   rescued {len(rescued)} file(s) to docs/ai/local/")
            for dest, used_fallback in rescued:
                if used_fallback:
                    print(
                        f"[act]     docs/ai/local/ already had this file, rescued as: "
                        f"{dest.relative_to(root).as_posix()}"
                    )

        _print_step(5, step_replace(root, new_act_dir, False))

        copies_summary, new_copies = step_refresh_copies(root, False)
        role_summary, role_touched = step_new_role_bridges(root, False, notes)
        frontmatter_summary, frontmatter_touched = step_refresh_role_frontmatter(root, False, notes)
        _print_step(6, f"{copies_summary}; roles: {role_summary}; role frontmatter: {frontmatter_summary}")

        migrate_summary, newly_applied, migration_touched = step_migrate(root, False)
        _print_step(7, migrate_summary)

        doctor_summary, doctor_inbox = step_doctor(root, False)
        _print_step(8, doctor_summary)

        _print_step(9, step_lock(root, False, source, new_copies))

        _maybe_print_branch_hint(root, notes)

        commit_paths = [root / ".act", root / ".act-lock.json", *migration_touched]
        commit_paths.extend(root / rel for rel in new_copies)
        commit_paths.extend(role_touched)
        commit_paths.extend(frontmatter_touched)
        if doctor_inbox is not None:
            commit_paths.append(doctor_inbox)
        rescue_dir = root / "docs" / "ai" / "local"
        if decision == "rescue" and rescue_dir.is_dir():
            commit_paths.append(rescue_dir)
        commit_summary = step_commit(root, plan, args.no_commit, commit_paths)
        print(f"[act]   commit: {commit_summary}")

        if notes:
            print(f"[act] done - {len(notes)} open point(s)")
            for note in notes:
                print(f"[act]   note: {note}")
        else:
            print("[act] done")
        return 0
    finally:
        try:
            _rmtree_robust(tmp_root)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
