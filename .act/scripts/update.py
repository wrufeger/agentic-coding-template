#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Pull a newer state of the template into an already-initialized project. Ten steps,
#          always in the same order: fetch the template into a temp checkout (nothing from it is
#          run), check whether the project edited .act/ itself since the last update, show the
#          old -> new diff (rule/coding IDs individually), get the user's consent, replace .act/,
#          refresh the template-owned "copies" living outside .act/, reconcile the
#          .claude/settings.json hook entries and the .gitattributes/.gitignore template blocks
#          against whatever init.py last wrote for this project (a project initialized
#          before a bridge existed, or before a later template revision changed one, otherwise
#          never gets it), run any due migrations, hand off to doctor.py, and write
#          .act-lock.json plus a commit. Stdlib only.
#
#          There is no "template" git remote to update from — the template's address lives
#          only in .act-lock.json's `template.source`, set by init.py. A project .act/ that got
#          replaced by something *other* than this script (e.g. a plain `git pull` of the shared
#          history some projects still keep from before init.py stopped adding a remote) looks,
#          once it lands, exactly like
#          an update.py run that crashed between step 5 and step 10: .act/ already matches a clean
#          template state, but .act-lock.json/copies/role bridges/migrations are still behind. A
#          normal run notices this itself (step 3 finds no diff, then resumes instead of reporting
#          "nothing to update"); --catch-up does the same without a fetch, for when there is
#          nothing new to fetch in the first place.
#
# Usage:
#   python .act/scripts/update.py                       # update from .act-lock.json's recorded source
#   python .act/scripts/update.py --source <path-or-url> --ref <tag-or-commit>
#   python .act/scripts/update.py --plan                 # show steps 1-3, describe 5-10, write nothing
#   python .act/scripts/update.py --allow-downgrade       # accept a fetched state older than (or unrelated to) the installed commit
#   python .act/scripts/update.py --yes               # skip the interactive consent prompt (step 4)
#   python .act/scripts/update.py --on-local-changes rescue|discard|abort   # skip the step-2 prompt
#   python .act/scripts/update.py --non-interactive       # never prompt (implies a default answer)
#   python .act/scripts/update.py --no-commit             # do everything except the final commit
#   python .act/scripts/update.py --catch-up              # no fetch; finish steps 6-10 from .act/ as-is
#
# Output format: one numbered line per step ("[n/10] ..."), 1..10 (--plan stops after 3, then one
#   descriptive line each for 5-10), plus a closing "[act] done" line. Exit 0 on success or a clean
#   --plan/abort, 1 if a fatal precondition is not met (no source resolvable, fetch failed, the
#   fetched state is older than/unrelated to the installed commit without --allow-downgrade, the
#   user chose abort at step 2 or declined at step 4, or --catch-up found .act/ hand-edited).

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
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import actlib
import entries
import manifest
import rules
import tiers


# ---------------------------------------------------------------------------
# Categories — for grouping the step-3 diff the way the spec asks for it
# ---------------------------------------------------------------------------

CATEGORY_DIRS = (
    "rules", "coding", "skills", "agents", "scripts", "bridges", "hooks", "skeleton", "migrations",
)


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
    print(f"[{n}/10] {text}")


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
    """The source recorded in .act-lock.json from the last update/init comes first. A remote named
    "template" (left behind by the predecessor template's update script, or added by hand) is
    taken only when the lock names no source; when both exist and differ, one line says which one
    was used, so a leftover remote never silently decides where updates come from."""
    lock = actlib.read_lock()
    locked = str(lock.get("template", {}).get("source", "") or "")
    result = _git(["remote", "get-url", "template"], cwd=root, check=False)
    remote = result.stdout.strip() if result.returncode == 0 else ""
    if locked:
        if remote and remote.rstrip("/").removesuffix(".git") != locked.rstrip("/").removesuffix(".git"):
            print(f"update.py: using the source from .act-lock.json ({locked}); the git remote 'template' "
                  f"points elsewhere ({remote}) and is ignored.")
        return locked
    if remote:
        print(f"update.py: .act-lock.json names no source; using the git remote 'template' ({remote}).")
    return remote


def _source_origin(root: Path, source: str, explicit: Optional[str]) -> str:
    """Where `source` came from, in words: the --source option, the source recorded in
    .act-lock.json, or the git remote 'template'."""
    if explicit:
        return "the --source option"
    locked = str(actlib.read_lock().get("template", {}).get("source", "") or "")
    if locked and locked == source:
        return "the source recorded in .act-lock.json"
    return "the git remote 'template'"


def _fetch_failure_message(root: Path, source: str, args: argparse.Namespace, error: Exception) -> str:
    """The message printed when step 1 fails: what failed, which source, where that source came
    from, and the way out (name another one with --source/--ref)."""
    origin = _source_origin(root, source, args.source)
    ref_part = f" at ref '{args.ref}'" if args.ref else ""
    return (
        f"update.py: could not fetch the template from '{source}'{ref_part} (taken from {origin}): {error}\n"
        "update.py: name another source with --source <path-or-url> (and --ref <tag-or-commit> for a "
        "specific state), or correct the source recorded in .act-lock.json / the git remote 'template'."
    )


def _reject_symlinks(act_dir: Path) -> None:
    """Refuses a fetched .act/ tree that contains a symlink. The "nothing from a fetched ref is
    executed" guarantee this script relies on does not cover a symlink pointing outside the
    checkout, which step 5's copytree would otherwise happily follow into the project."""
    for path in act_dir.rglob("*"):
        if path.is_symlink():
            raise RuntimeError(f"fetched .act/ contains a symlink, refusing: {path}")


def step_fetch(
    source: str, ref: Optional[str], dest: Path, notes: list[str]
) -> tuple[Path, Optional[str]]:
    """Fetch `source` (a local directory or a git URL/local repo) into `dest`, at `ref` if given.
    Returns (the fetched checkout's .act/ directory, its git commit if one is known). Nothing
    under `dest` is ever executed here — only copied or cloned. A plain local directory (no .git)
    has only its .act/ copied and no commit to report (matching the test fixtures used for this
    script, and so that `--source .` — the project itself — does not try to copy itself into
    itself); a git source (local repo or remote URL) is cloned in full and its HEAD's commit is
    read back, so `step_lock`/`_resume_needed` have the actual fetched commit to record and
    compare against, instead of whatever `.act/VERSION`'s own (often unmaintained) "commit=" line
    says."""
    src_path = Path(source)
    commit: Optional[str] = None
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
        rev = _git(["rev-parse", "HEAD"], cwd=dest, check=False)
        if rev.returncode == 0 and rev.stdout.strip():
            commit = rev.stdout.strip()
    act_dir = dest / ".act"
    if not act_dir.is_dir():
        raise RuntimeError(f"fetched checkout has no .act/ directory: {dest}")
    _reject_symlinks(act_dir)
    return act_dir, commit


def _history_relation(checkout: Path, fetched: str, installed: str) -> str:
    """How the fetched commit relates to the installed one (the lock's template.commit), judged by
    read-only git plumbing inside the fetched checkout: "same", "newer" (installed is an ancestor of
    fetched, the normal update), "older" (fetched is an ancestor of installed: a downgrade),
    "unknown" (the installed commit is not in the fetched history at all, or the histories
    diverged). Nothing from the checkout is executed."""
    if fetched == installed:
        return "same"
    if _git(["cat-file", "-e", f"{installed}^{{commit}}"], cwd=checkout, check=False).returncode != 0:
        return "unknown"
    if _git(["merge-base", "--is-ancestor", installed, fetched], cwd=checkout, check=False).returncode == 0:
        return "newer"
    if _git(["merge-base", "--is-ancestor", fetched, installed], cwd=checkout, check=False).returncode == 0:
        return "older"
    return "unknown"


def _downgrade_warning(checkout: Path, fetched: Optional[str], source: str) -> Optional[str]:
    """A warning text when the fetched state is not a successor of the installed one, else None
    (also None for a plain-directory source without a commit, or a lock without a commit)."""
    installed = str(actlib.read_lock().get("template", {}).get("commit", "") or "")
    if not fetched or not installed:
        return None
    relation = _history_relation(checkout, fetched, installed)
    if relation == "older":
        return (
            f"WARNING: downgrade. Installed template commit {installed[:12]}, but '{source}' only has the "
            f"older {fetched[:12]}. Name the right source with --source <path-or-url> (e.g. your local template "
            "checkout), or pass --allow-downgrade to go back on purpose."
        )
    if relation == "unknown":
        return (
            f"WARNING: the installed template commit {installed[:12]} is not part of the history of "
            f"'{source}' (fetched {fetched[:12]}). Likely cause: the source recorded in .act-lock.json points at "
            "a repo that does not contain the installed commit, e.g. a local template checkout with unpushed "
            "commits; applying this could silently downgrade .act/. Use --source <local template checkout>, "
            "or pass --allow-downgrade if this state is meant."
        )
    return None


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
                "cannot tell hand edits under .act/ without git history or MANIFEST.json — "
                "they will be replaced",
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
# separately in step_new_role_bridges(): an existing one is only touched again when its role's row
# in docs/ai/config.md § Roles changed (sync_dependent_files()), otherwise only a role new since
# the last update gets a bridge created.
# "entries" and "board" are here because init.py imports entries (which imports board): left out, the
# fresh init.py would bind the entries module this run loaded at start-up — the older one, without the
# functions the new init.py calls — and, being cached, board's older copy under it. "unit_copies"
# imports init the same way, so a cached copy of it would keep the older init bound.
_PROBE_MODULE_NAMES = ("actlib", "rules", "init", "tiers", "frontmatter", "ideas", "entries", "board", "unit_copies")


def _project_tools(root: Path) -> list[str]:
    """The project's configured tools (docs/ai/config.md § Project, key "tools"), lowercased —
    the same gate copy_targets()/agent_bridge_targets() use to decide which destinations apply."""
    raw = actlib.read_config().get("tools", "")
    return sorted({actlib.normalize_tool(t) for t in raw.split(",") if t.strip()})


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


def _new_backup_dir(root: Path) -> Path:
    """A fresh, not yet existing .act-local/backup/<YYYYmmdd-HHMMSS>[-n]/ folder for one
    sync_dependent_files() run — one folder per run, so a second run never
    overwrites the first one's backups. Not created here; _backup_file() creates it on first use."""
    base = root / ".act-local" / "backup"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate, n = base / stamp, 1
    while candidate.exists():
        n += 1
        candidate = base / f"{stamp}-{n}"
    return candidate


def _backup_file(backup_dir: Optional[Path], dest_rel: str, dest_path: Path) -> bool:
    """Copies a locally-edited skill copy or role bridge to <backup_dir>/<dest_rel> before
    sync_dependent_files() resets or removes it. Returns whether the backup really landed (same
    size as the original) — a caller leaves the file untouched whenever it did not (a path
    past Windows' 260-character limit, or .act-local/backup blocked by a plain file, must never be
    followed by the overwrite)."""
    if backup_dir is None:
        return False
    target = backup_dir / dest_rel
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(dest_path, target)
        return target.stat().st_size == dest_path.stat().st_size
    except OSError:
        return False


def _report_reset_edits(root: Path, backup_dir: Path, reset: list[str]) -> Optional[Path]:
    """Files one inbox entry (docs/ai/inbox/, via entries.py) listing every locally-edited skill
    copy or role bridge sync_dependent_files() just reset or removed because the docs/ai/config.md
    value it depends on changed, so the edit is noticed rather than silently lost — the previous
    content is under `backup_dir`, and the entry points at docs/ai/local/ for an override that
    survives the next config change too. Returns the entry's path (for the caller's own commit
    tracking) or None on failure — best-effort: a broken inbox write must never fail the sync."""
    try:
        backup_label = backup_dir.relative_to(root).as_posix()
    except ValueError:
        backup_label = backup_dir.as_posix()
    body = (
        "A docs/ai/config.md value these files depend on (`tools`, or a role's row in the "
        "\"## Roles\" table) changed, and the following files had been edited locally. They were "
        "reset to the template's version (or removed, where the new value no longer calls for "
        f"them); the edited content is under `{backup_label}/<path>` (gitignored). For an edit "
        "that should survive future config changes, put it under `docs/ai/local/` instead — "
        "`docs/ai/local/skills/<name>/<file>` for a skill, `docs/ai/local/agents/<role>.md` for a "
        "role (see `.act/skills/README.md`).\n\n"
        + "\n".join(f"- `{rel}`" for rel in reset) + "\n"
    )
    try:
        path, _entry_id = entries.create_entry(
            root, "todo",
            "Locally edited files were reset by a config change",
            status="open", body=body,
        )
        return path
    except Exception:
        return None


def _list_part(label: str, items: list[str], brief: bool) -> str:
    """One "label: a, b, c" summary part — under `brief` (the session-start note) a long list
    shrinks to its count, so the note stays one readable line."""
    if brief and len(items) > 5:
        return f"{label}: {len(items)} files"
    return f"{label}: {', '.join(items)}"


def _own_copy_source(root: Path, entry: dict) -> Optional[Path]:
    """The live docs/ai/local/ source a tracked copy's lock entry points at, or None. A
    relative-looking "docs/ai/local/..." string can still escape that folder via "..", or (on
    Windows) via a second drive-absolute segment such as "C:/evil/path" silently replacing `root`
    in the "/" join below (confirmed: pathlib's Path.__truediv__ drops the left side when the right
    side is absolute) -- resolved first and checked to really land under docs/ai/local/."""
    source_rel = entry.get("source", "")
    if not source_rel or not source_rel.startswith("docs/ai/local/") or Path(source_rel).is_absolute():
        return None
    local_root = (root / "docs" / "ai" / "local").resolve()
    candidate = (root / source_rel).resolve()
    if candidate != local_root and local_root not in candidate.parents:
        return None
    return candidate if candidate.is_file() else None


def _skill_dir_active(new_init, dest_root: str, tools: list[str]) -> bool:
    gate = dict(getattr(new_init, "SKILL_TARGET_DIRS", ())).get(dest_root)
    check = getattr(new_init, "_skill_target_active", None)
    return True if check is None else bool(check(gate, tools))


def _dest_skill_dir(new_init, dest_rel: str) -> Optional[str]:
    for dest_root, _gate in getattr(new_init, "SKILL_TARGET_DIRS", ()):
        if dest_rel.startswith(dest_root + "/"):
            return dest_root
    return None


def _fold(data: bytes) -> bytes:
    """CRLF folded to LF, unless binary — the same rule as manifest.content_hash() (a checkout
    with core.autocrlf=true writes every copy with CRLF; that is not an edit)."""
    return data if b"\x00" in data else data.replace(b"\r\n", b"\n")


def _unedited(current: bytes, recorded_sha: Optional[str]) -> bool:
    return recorded_sha in (hashlib.sha256(current).hexdigest(), hashlib.sha256(_fold(current)).hexdigest())


def _write_bytes(dest_path: Path, data: bytes) -> bool:
    """Writes one copy; False instead of an exception on failure (one unwritable file must not
    stop the rest of the run, nor leave the files already written untracked)."""
    try:
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(data)
        return True
    except OSError:
        return False


def _copy_data(new_init, root: Path, dest_rel: str, source_path: Path, tiers_data: dict, overrides: dict) -> bytes:
    """The bytes a copy should hold: the source, with a SKILL.md's reasoning field derived by the
    updated init.py (skill_copy_bytes()); plain bytes when that init.py predates it."""
    render = getattr(new_init, "skill_copy_bytes", None)
    if render is None:
        return source_path.read_bytes()
    return render(root, dest_rel, source_path, tiers_data, overrides)


def step_refresh_copies(
    root: Path, plan: bool, *, restore_paths: frozenset[str] = frozenset(),
    restore_dirs: frozenset[str] = frozenset(), backup_dir: Optional[Path] = None,
    brief: bool = False,
) -> tuple[str, dict[str, dict], list[str], list[Path]]:
    """Five cases per template-owned skill copy, exactly as the spec lists them: unchanged ->
    replaced; user-edited -> kept, reported; user-deleted -> left deleted (tracked in
    removed_by_user, same field init.py's lock skeleton already reserves for this); no longer
    shipped by the template (removed or renamed there) or no longer targeted (its tool left
    `tools`) -> the project's copy is deleted if it still matches what the template last shipped
    (the project never edited it), or kept and reported "no longer shipped, kept (edited)" if the
    project changed it since; new in the template -> created (or taken over, if a byte-identical
    file is already there — e.g. from an earlier run that stopped midway). Returns (summary,
    new_copies, reset_edited, removed): new_copies is what .act-lock.json's "copies" key should
    become, reset_edited lists the edited copies this run backed up and reset (see
    `restore_paths` below), removed the files it deleted (for the caller's commit).

    A sixth case sits outside that list: a project's *own* skill (settings_load.py's
    write_unit_bridges() recorded its copies in the lock the same way, but init.py's
    copy_targets() deliberately never enumerates them — see that function's docstring). Such a
    copy's lock "source" points at a live docs/ai/local/skills/<name>/<file> — that is what tells
    it apart from a copy the template truly stopped shipping (confirmed 2026-09-22: without this
    check the first `update` after importing an own skill deleted it outright). Its copies follow
    the same tool gate as a template skill's: refreshed in every active SKILL_TARGET_DIRS
    folder, created in one that became active, removed (unedited only) from one that no longer is.

    `restore_paths`/`restore_dirs`: set by sync_dependent_files() to exactly
    the destinations and skill folders a moved `tools` value newly targets — empty for a plain call
    and for any other change, so every case above stays as it was. For those only, a user-deleted
    copy is recreated (its removed_by_user record cleared), and a user-edited one is backed up into
    `backup_dir` (_backup_file) and then reset to the template's version — or, if the backup did
    not land, left as it is and reported "kept (backup failed)". `brief` shortens long lists
    in the summary to a count (session start).

    If the updated template's init.py cannot be imported (see _import_fresh_init()), this step is
    aborted entirely rather than silently treating every copy as "no longer shipped" — that would
    drop every copy out of the lock and stop them from ever being refreshed again."""
    if plan:
        return (
            "would replace unchanged copies, keep edited ones (reported), leave deleted ones "
            "deleted unless a `tools` change newly targets them, create new ones",
            {}, [], [],
        )

    lock = actlib.read_lock()
    old_copies: dict[str, dict] = dict(lock.get("copies", {}))
    removed_by_user: list[str] = list(lock.get("removed_by_user", []))

    new_init = _import_fresh_init(root / ".act" / "scripts")
    if new_init is None:
        return "could not load copy_targets() from the updated template; copies left untouched", old_copies, [], []
    tools = _project_tools(root)
    new_specs: dict[str, Path] = dict(new_init.copy_targets(root, tools))
    copy_bases = {root / dest_root for dest_root, _ in getattr(new_init, "SKILL_TARGET_DIRS", ())}
    try:
        tiers_data = new_init.tiers.load_tiers(root)
        role_rows = new_init.tiers.read_role_overrides(root)
    except (OSError, ValueError, KeyError, AttributeError, TypeError) as exc:
        print(f"note: tiers/role rows unreadable ({type(exc).__name__}: {exc}); skill copies written without reasoning")
        tiers_data, role_rows = {}, {}

    # A project's own skill gets a copy in every active skill folder, like a template skill.
    local_skills = (root / "docs" / "ai" / "local" / "skills").resolve()
    active_dirs = [d for d, _ in getattr(new_init, "SKILL_TARGET_DIRS", ()) if _skill_dir_active(new_init, d, tools)]
    restore = set(restore_paths)
    for entry in old_copies.values():
        own = _own_copy_source(root, entry)
        if own is None or local_skills not in own.parents:
            continue
        rel = own.relative_to(local_skills).as_posix()
        for dest_root in active_dirs:
            dest = f"{dest_root}/{rel}"
            if dest not in new_specs:
                new_specs[dest] = own
                if dest_root in restore_dirs:
                    restore.add(dest)

    new_copies: dict[str, dict] = {}
    replaced, kept, left_deleted, created, adopted, failed = [], [], [], [], [], []
    no_longer_shipped_removed, no_longer_shipped_kept = [], []
    present_not_taken_over = []
    restored, restored_edited, backup_failed = [], [], []
    removed_paths: list[Path] = []

    def _record(dest_rel: str, source_path: Path, data: bytes) -> None:
        new_copies[dest_rel] = {"source": _copy_source_label(root, source_path), "sha256": hashlib.sha256(data).hexdigest()}

    for dest_rel, old_entry in old_copies.items():
        source_path = new_specs.pop(dest_rel, None)
        dest_path = root / dest_rel
        if source_path is None:
            own = _own_copy_source(root, old_entry)
            dest_root = _dest_skill_dir(new_init, dest_rel)
            if own is not None and (dest_root is None or _skill_dir_active(new_init, dest_root, tools)):
                source_path = own  # an own copy outside the usual layout: refreshed as before
            else:
                # the template stopped shipping this copy (removed, or renamed to a different
                # path), or its folder's tool left `tools` (for an own skill)
                if not dest_path.is_file():
                    continue  # already gone — nothing to remove, nothing left to track
                try:
                    unedited = _unedited(dest_path.read_bytes(), old_entry.get("sha256"))
                    if unedited:
                        dest_path.unlink()
                except OSError:
                    new_copies[dest_rel] = old_entry
                    failed.append(dest_rel)
                    continue
                if unedited:
                    _prune_empty_copy_dirs(dest_path, copy_bases, root)
                    no_longer_shipped_removed.append(dest_rel)
                    removed_paths.append(dest_path)
                else:
                    new_copies[dest_rel] = old_entry
                    no_longer_shipped_kept.append(dest_rel)
                continue
        try:
            data = _copy_data(new_init, root, dest_rel, source_path, tiers_data, role_rows)
        except OSError:
            new_copies[dest_rel] = old_entry
            failed.append(dest_rel)
            continue
        if not dest_path.is_file():
            if dest_rel in restore:
                # `tools` moved and newly targets this destination — recreate it and
                # drop any removed_by_user record instead of leaving it deleted forever.
                if not _write_bytes(dest_path, data):
                    failed.append(dest_rel)
                    continue
                _record(dest_rel, source_path, data)
                if dest_rel in removed_by_user:
                    removed_by_user.remove(dest_rel)
                restored.append(dest_rel)
                continue
            if dest_rel not in removed_by_user:
                removed_by_user.append(dest_rel)
            left_deleted.append(dest_rel)
            continue
        try:
            current = dest_path.read_bytes()
        except OSError:
            new_copies[dest_rel] = old_entry
            failed.append(dest_rel)
            continue
        if _unedited(current, old_entry.get("sha256")):
            if _fold(current) != _fold(data):
                if not _write_bytes(dest_path, data):
                    new_copies[dest_rel] = old_entry
                    failed.append(dest_rel)
                    continue
                replaced.append(dest_rel)
            _record(dest_rel, source_path, data)
        elif dest_rel in restore:
            # Same trigger, for a locally-edited copy — reset only after the edit is
            # safely backed up; sync_dependent_files() files one inbox entry for the run.
            if not _backup_file(backup_dir, dest_rel, dest_path):
                new_copies[dest_rel] = old_entry
                backup_failed.append(dest_rel)
                continue
            if not _write_bytes(dest_path, data):
                new_copies[dest_rel] = old_entry
                failed.append(dest_rel)
                continue
            _record(dest_rel, source_path, data)
            restored_edited.append(dest_rel)
        else:
            new_copies[dest_rel] = old_entry
            kept.append(dest_rel)

    for dest_rel, source_path in new_specs.items():
        if dest_rel in removed_by_user and dest_rel not in restore:
            continue  # the project deliberately removed this one before; do not resurrect it
        dest_path = root / dest_rel
        try:
            data = _copy_data(new_init, root, dest_rel, source_path, tiers_data, role_rows)
            existing = dest_path.read_bytes() if dest_path.is_file() else None
        except OSError:
            failed.append(dest_rel)
            continue
        if existing is not None:
            if _fold(existing) == _fold(data):
                # byte-identical already — e.g. written by an earlier run that stopped midway
                _record(dest_rel, source_path, data)
                adopted.append(dest_rel)
                continue
            # something is already there that this run did not put there — leave it, but say so
            present_not_taken_over.append(dest_rel)
            continue
        if not _write_bytes(dest_path, data):
            failed.append(dest_rel)
            continue
        _record(dest_rel, source_path, data)
        if dest_rel in removed_by_user:
            removed_by_user.remove(dest_rel)
        created.append(dest_rel)

    if sorted(set(removed_by_user)) != sorted(set(lock.get("removed_by_user", []))):
        # written only when it changed ("nothing to change" must leave the lock untouched)
        actlib.write_lock({"removed_by_user": sorted(set(removed_by_user))})

    parts = []
    for label, items in (
        ("replaced", replaced),
        ("kept (edited locally)", kept),
        ("left deleted", left_deleted),
        ("restored (value changed)", restored),
        ("reset, edit backed up (value changed)", restored_edited),
        ("kept (backup failed)", backup_failed),
        ("no longer shipped, removed", no_longer_shipped_removed),
        ("no longer shipped, kept (edited)", no_longer_shipped_kept),
        ("created", created),
        ("taken over (identical)", adopted),
        ("present, not taken over", present_not_taken_over),
        ("failed, left as it was", failed),
    ):
        if items:
            parts.append(_list_part(label, items, brief))
    return ("; ".join(parts) if parts else "no changes to template-owned copies"), new_copies, restored_edited, removed_paths


_BRIDGE_DERIVED_LINE_RE = re.compile(r"(model|effort|tier|reasoning)\s*:")


def _bridge_core(text: str, drop: tuple[str, ...] = ()) -> str:
    """A role bridge's text minus what changes on its own: the `model:`/`effort:` frontmatter
    lines tiers.py re-derives at every session start and update, the `tier:`/`reasoning:` lines an
    unresolved bridge still carries, and line endings. What is left differs from the template's
    rendering only where a person edited the file."""
    text = text.replace("\r\n", "\n")
    match = re.match(r"---\n(.*?\n)---\n", text, re.S)
    if not match:
        return text
    kept = [line for line in match.group(1).splitlines(keepends=True)
            if not _BRIDGE_DERIVED_LINE_RE.match(line)
            and not any(line.startswith(f"{key}:") for key in drop)]
    return "---\n" + "".join(kept) + "---\n" + text[match.end():]


def _bridge_edited(
    new_init, root: Path, dest_path: Path, role: str, source_path: Optional[Path], variant: bool,
    tiers_data: dict, overrides: dict,
) -> bool:
    """Whether an existing role bridge differs from what init.py's write_agent_bridge_file() renders
    for it under `overrides` (the Roles table it was generated from), compared via _bridge_core().
    Unreadable, or no source to render from, counts as edited — the safe side: it gets backed up
    before anything happens to it."""
    if source_path is None:
        return True
    try:
        current = dest_path.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            reference_path = Path(tmp) / dest_path.name
            new_init.write_agent_bridge_file(
                role, source_path, reference_path, False, root, tiers_data, overrides, variant, None,
            )
            reference = reference_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return True
    # A variant whose model is unresolvable under `overrides` renders verbatim, without its
    # "-high" name/description/variant-of — those three lines then say nothing about an edit.
    drop = ("name", "description", "variant-of") if variant and "variant-of:" not in reference else ()
    return _bridge_core(current, drop) != _bridge_core(reference, drop)


def _in_git_history(root: Path, rel: str) -> bool:
    """Whether `rel` was ever committed — a missing role bridge that was, and that no snapshot or
    lock entry explains otherwise, was deleted by the project, not never created (fallback for
    a checkout without .act-local/last-applied.json yet). Single-path convenience wrapper around
    _paths_in_git_history() below — prefer that one for more than a handful of paths (one
    `git log`
    call for the whole set instead of one per path)."""
    return bool(_paths_in_git_history(root, [rel]))


def _paths_in_git_history(root: Path, rels: list[str]) -> set[str]:
    """Which of `rels` were ever committed, found with a single `git log` call across all of them
    instead of one call per path — step_new_role_bridges() below can otherwise ask this
    once per missing role bridge. A commit touching any of `rels` lists every path it touched
    under `--name-only`; intersecting that combined output with `rels` is enough to answer "ever
    committed" for each one, without needing to know *which* commit did it."""
    if not rels:
        return set()
    try:
        result = _git(["log", "--format=", "--name-only", "--", *rels], cwd=root, check=False)
    except (OSError, ValueError):
        return set()
    if result.returncode != 0:
        return set()
    rel_set = set(rels)
    return {line for line in result.stdout.splitlines() if line in rel_set}


def _role_bridge_targets(new_init, root: Path, tools: list[str]) -> tuple[dict[str, Path], dict[str, Path]]:
    """(base targets, "-high" variant targets) from the given init module — see init.py's
    agent_bridge_targets()/agent_bridge_variant_targets()."""
    return (
        dict(new_init.agent_bridge_targets(root, tools)),
        dict(new_init.agent_bridge_variant_targets(root, tools)),
    )


def step_new_role_bridges(
    root: Path, plan: bool, notes: Optional[list[str]] = None, *,
    changed_roles: frozenset[str] = frozenset(), force_all: bool = False,
    old_overrides: Optional[dict[str, dict[str, str]]] = None,
    known: frozenset[str] = frozenset(), backup_dir: Optional[Path] = None, brief: bool = False,
) -> tuple[str, list[Path], list[str], bool]:
    """Creates a bridge for any role new since the last update, and a "-high" variant for any
    applicable role — new or already existing — that does not have one yet.
    An existing .claude/agents/<name>.md (base or variant) is otherwise never touched
    here; its `model`/`effort` frontmatter is refreshed separately, by
    step_refresh_role_frontmatter() below.

    A missing bridge the project deleted stays deleted (same rule as a skill copy): it is
    recorded in .act-lock.json's removed_by_user as soon as it is recognised as deleted — already
    listed there, in the last snapshot's "bridges" (`known`, see sync_dependent_files()), or ever
    committed (_in_git_history) — and only a missing bridge none of those explain is created as new.

    For a role in `changed_roles` (its row in docs/ai/config.md § Roles changed since the last
    snapshot — or every role, with `force_all`, when `claude-code` just joined `tools`), its
    bridges follow the new value: a missing one is recreated and its removed_by_user record
    dropped; an edited one (compared against the rendering under `old_overrides`, the table it was
    generated from — see _bridge_edited()) is backed up into `backup_dir` and regenerated, or left
    as it is and reported "kept (backup failed)" if the backup did not land; a template-generated
    "-high" variant (frontmatter `variant-of: <role>`) the new value no longer calls for is removed
    the same way — a project's own "...-high" role without that field is never touched.

    `notes`, if given, collects messages the same way step_fetch() above does. Returns (summary,
    touched_paths, reset_or_removed_edited, had_failure) — the last one true when a bridge that
    should have been created or refreshed could not be written (an OSError/UnicodeDecodeError from
    write_agent_bridge_file, independent of whether `notes` was given): sync_dependent_files() uses
    it to skip writing its snapshot on such a run, so the failed bridge is retried on
    the next comparison instead of silently counting as already applied."""
    if plan:
        return (
            "would create bridges for roles new since the last update, and any missing "
            "'-high' variant, leaving existing and deleted files untouched unless their role's "
            "row in docs/ai/config.md changed",
            [], [], False,
        )

    new_init = _import_fresh_init(root / ".act" / "scripts")
    if new_init is None:
        return "could not load agent_bridge_targets() from the updated template", [], [], True
    tools = _project_tools(root)
    base_targets, variant_targets = _role_bridge_targets(new_init, root, tools)
    targets = {**base_targets, **variant_targets}
    tiers_data = new_init.tiers.load_tiers(root)
    overrides = new_init.tiers.read_role_overrides(root, notes=notes)
    reference_overrides = overrides if old_overrides is None else old_overrides
    lock = actlib.read_lock()
    removed_by_user: list[str] = list(lock.get("removed_by_user", []))

    created, restored, reset, left_deleted, kept_failed, dropped = [], [], [], [], [], []
    touched: list[Path] = []
    had_failure = False

    def _role_of(dest_rel: str) -> str:
        stem = Path(dest_rel).stem
        return stem[: -len("-high")] if dest_rel in variant_targets else stem

    # Precompute which missing bridges need the git-history fallback, then ask once
    # for the whole batch rather than once per file inside the loop below — the loop's own
    # branching (is_file/follows_value/removed_by_user/known) is deterministic ahead of time,
    # since none of it depends on state the loop itself mutates.
    _needs_git_check = [
        dest_rel for dest_rel in sorted(targets)
        if not (root / dest_rel).is_file()
        and not (force_all or _role_of(dest_rel) in changed_roles)
        and dest_rel not in removed_by_user and dest_rel not in known
    ]
    _history_hits = _paths_in_git_history(root, _needs_git_check)

    for dest_rel, source_path in sorted(targets.items()):
        dest_path = root / dest_rel
        role = _role_of(dest_rel)
        variant = dest_rel in variant_targets
        follows_value = force_all or role in changed_roles
        if dest_path.is_file():
            # An existing bridge is never re-created, edited or not: the only part of it that hangs
            # on the role's value is the `model`/`effort` pair, which step_refresh_role_frontmatter()
            # and every session start re-derive in place — a project's own text in it survives
            # (see tiers.py's refresh_project_bridge_frontmatter(), t27/tier_test.sh).
            continue
        elif follows_value:
            bucket = restored
        elif dest_rel in removed_by_user or dest_rel in known or dest_rel in _history_hits:
            if dest_rel not in removed_by_user:
                removed_by_user.append(dest_rel)
            left_deleted.append(dest_rel)
            continue
        else:
            bucket = created
        try:
            _message, ok = new_init.write_agent_bridge_file(
                role, source_path, dest_path, False, root, tiers_data, overrides, variant, notes,
            )
        except (OSError, UnicodeDecodeError) as exc:
            if notes is not None:
                notes.append(f"{dest_rel}: skipped, could not create ({exc.__class__.__name__})")
            had_failure = True
            continue
        if ok:
            bucket.append(dest_rel)
            touched.append(dest_path)
            if dest_rel in removed_by_user:
                removed_by_user.remove(dest_rel)
        else:
            had_failure = True

    # A changed role's template-generated "-high" variant the new value no longer calls for (e.g.
    # the role moved to tier "expert", or to the top reasoning step).
    changed = {_role_of(rel) for rel in targets} if force_all else set(changed_roles)
    for role in sorted(changed):
        dest_rel = f".claude/agents/{role}-high.md"
        dest_path = root / dest_rel
        if dest_rel in targets or not dest_path.is_file():
            continue
        try:
            fields, _body, _order = new_init.tiers.split_frontmatter(dest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
        if fields.get("variant-of") != role:
            continue  # a project's own "...-high" role, not a generated variant
        source_path = base_targets.get(f".claude/agents/{role}.md")
        edited = _bridge_edited(new_init, root, dest_path, role, source_path, True, tiers_data, reference_overrides)
        if edited and not _backup_file(backup_dir, dest_rel, dest_path):
            kept_failed.append(dest_rel)
            had_failure = True
            continue
        try:
            dest_path.unlink()
        except OSError:
            continue
        dropped.append(dest_rel)
        touched.append(dest_path)
        if edited:
            reset.append(dest_rel)

    if sorted(set(removed_by_user)) != sorted(set(lock.get("removed_by_user", []))):
        # written only when it changed ("nothing to change" must leave the lock untouched)
        actlib.write_lock({"removed_by_user": sorted(set(removed_by_user))})

    parts = [
        _list_part(label, items, brief) for label, items in (
            ("created", created),
            ("restored (value changed)", restored),
            ("reset, edit backed up (value changed)", reset),
            ("removed (no longer applies)", dropped),
            ("left deleted", left_deleted),
            ("kept (backup failed)", kept_failed),
        ) if items
    ]
    return ("; ".join(parts) if parts else "no new roles or variants"), touched, reset, had_failure


# ---------------------------------------------------------------------------
# sync_dependent_files() — a docs/ai/config.md value that files depend on
# (`tools` for skill copies and, via `claude-code`, role bridges; a role's row in the "## Roles"
# table for that role's bridges) gets its dependent files installed after the fact by whichever
# mechanism notices the change first — update.py or the next session start — compared against the
# snapshot in .act-local/last-applied.json. Without a change, a deleted file stays deleted.
# ---------------------------------------------------------------------------

def _remove_role_bridges(
    new_init, root: Path, old_tools: list[str], old_roles: dict, brief: bool,
) -> tuple[Optional[str], list[Path]]:
    """`claude-code` left `tools` (Offen 1, decided 2026-09-24): its role bridges go the way of its
    skill copies — every bridge the old `tools` value targeted is removed if unedited
    (_bridge_edited against the Roles table it was generated from), and left in place and reported
    if edited. Returns (summary part or None, removed paths)."""
    base_targets, variant_targets = _role_bridge_targets(new_init, root, old_tools)
    tiers_data = new_init.tiers.load_tiers(root)
    removed, kept = [], []
    removed_paths: list[Path] = []
    for dest_rel, source_path in sorted({**base_targets, **variant_targets}.items()):
        dest_path = root / dest_rel
        if not dest_path.is_file():
            continue
        variant = dest_rel in variant_targets
        role = Path(dest_rel).stem[: -len("-high")] if variant else Path(dest_rel).stem
        if _bridge_edited(new_init, root, dest_path, role, source_path, variant, tiers_data, old_roles):
            kept.append(dest_rel)
            continue
        try:
            dest_path.unlink()
        except OSError:
            kept.append(dest_rel)
            continue
        removed.append(dest_rel)
        removed_paths.append(dest_path)
    parts = []
    if removed:
        parts.append(_list_part("claude-code left tools, removed", removed, brief))
    if kept:
        parts.append(_list_part("claude-code left tools, kept (edited)", kept, brief))
    return ("; ".join(parts) or None), removed_paths


def _render_tool_bridge(new_init, root: Path, key: str, spec: dict) -> Optional[str]:
    """The text init.py would write for a tool-gated BRIDGES entry into an empty project — the
    reference a removal compares against. None if it cannot be rendered."""
    src = root / ".act" / "bridges" / key
    try:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / Path(spec["dest"]).name
            if spec["kind"] == "json-merge":
                new_init._merge_settings_hooks(src, dest, False, None)
            else:
                new_init._write_text_file(src, dest, {}, False, None)
            return dest.read_text(encoding="utf-8") if dest.is_file() else None
    except (OSError, ValueError):
        return None


def _sync_tool_bridges(
    new_init, root: Path, old_tools: list[str], new_tools: list[str],
) -> tuple[list[str], list[Path]]:
    """The BRIDGES entries init.py gates on a tool (CLAUDE.md — "verbatim" — and
    .claude/settings.json's hook entries — "json-merge" — both on `claude-code`) follow that tool
    in `tools`: created (hook entries merged) when it joins; removed when it leaves, but only if
    the file is still exactly what init.py generates (or what cache.json last recorded as
    generated) — otherwise left in place and reported. Returns (summary parts, touched paths)."""
    bridges = getattr(new_init, "BRIDGES", {})
    cache = actlib.read_cache()
    generated: dict = dict(cache.get("generated", {}))
    parts: list[str] = []
    touched: list[Path] = []
    for key, spec in bridges.items():
        tool = spec.get("tool")
        if tool is None or spec.get("kind") not in ("verbatim", "json-merge"):
            continue
        dest_rel = spec["dest"]
        dest = root / dest_rel
        src = root / ".act" / "bridges" / key
        try:
            if tool in new_tools and tool not in old_tools:
                if spec["kind"] == "json-merge":
                    message, changed = new_init._merge_settings_hooks(src, dest, False, root)
                else:
                    message, changed = new_init._write_text_file(src, dest, {}, False, root)
                    if changed:
                        generated[dest_rel] = actlib.generated_hash(dest)
                if changed:
                    parts.append(f"{dest_rel}: created ({tool} joined tools)")
                    touched.append(dest)
            elif tool in old_tools and tool not in new_tools and dest.is_file():
                current = dest.read_text(encoding="utf-8")
                reference = _render_tool_bridge(new_init, root, key, spec)
                same = (reference is not None and current.replace("\r\n", "\n") == reference.replace("\r\n", "\n")) \
                    or actlib.generated_unchanged(dest, generated.get(dest_rel, ""))
                if same:
                    dest.unlink()
                    generated.pop(dest_rel, None)
                    parts.append(f"{dest_rel}: removed ({tool} left tools)")
                    touched.append(dest)
                else:
                    parts.append(f"{dest_rel}: kept, edited ({tool} left tools)")
        except (OSError, ValueError) as exc:
            parts.append(f"{dest_rel}: failed ({exc.__class__.__name__}), left as it was")
    if generated != cache.get("generated", {}):
        actlib.write_cache({"generated": generated})
    return parts, touched


def _read_tools(root: Path) -> tuple[Optional[list[str]], Optional[str]]:
    """(normalized `tools`, None) — or (None, problem) when nothing may be synced from the row:
    docs/ai/config.md unreadable or without a `tools` row (read as "no tools", it would remove
    every skill copy), or an id actlib.KNOWN_TOOLS does not know (a typo such as "claude code"
    would otherwise read as "claude-code left" and remove the whole Claude integration)."""
    path = root / "docs" / "ai" / "config.md"
    try:
        path.read_text(encoding="utf-8")
        config = actlib.read_config()
    except (OSError, ValueError):
        return None, "docs/ai/config.md is not readable"
    if "tools" not in config:
        return None, "docs/ai/config.md has no `tools` row"
    raw = [t for t in config["tools"].split(",") if t.strip()]
    unknown = sorted({t.strip() for t in raw if actlib.normalize_tool(t) not in actlib.KNOWN_TOOLS})
    if unknown:
        return None, f"docs/ai/config.md `tools` holds unknown id(s): {', '.join(unknown)}"
    return sorted({actlib.normalize_tool(t) for t in raw}), None


def _dependent_values(root: Path) -> tuple[Optional[dict], Optional[str]]:
    """The docs/ai/config.md values the dependent files hang on, for the snapshot comparison:
    `tools` and every role's complete Roles-table entry (tier/reasoning/model — each of them decides
    whether a "-high" variant exists and what the bridge's frontmatter says, init.py's
    agent_bridge_variant_targets()). (None, problem) when `tools` cannot be used (_read_tools)."""
    tools, problem = _read_tools(root)
    if tools is None:
        return None, problem
    try:
        roles = tiers.read_role_overrides(root)
    except Exception:
        roles = {}
    return {"tools": tools, "roles": roles}, None


def _valid_snapshot(last: Optional[dict]) -> bool:
    """The `applied` record comes from a versioned, hand-editable file — only a well-formed
    one counts as a snapshot; anything else is treated like none at all."""
    if not isinstance(last, dict):
        return False
    tools, roles = last.get("tools"), last.get("roles")
    return (
        isinstance(tools, list) and all(isinstance(t, str) for t in tools)
        and isinstance(roles, dict)
        and all(isinstance(entry, dict) and all(isinstance(v, str) for v in entry.values()) for entry in roles.values())
    )


def _write_snapshot(root: Path, current: dict, new_init=None) -> None:
    """Records `current` in .act-lock.json § applied, and the role bridges present under it in
    .act-local/cache.json § known_bridges — the files a later run reads as "known", so a missing one
    of them was deleted by the project (only files that exist, never mere targets). Per
    checkout on purpose: a fresh clone falls back to the git history (_in_git_history)."""
    actlib.write_last_applied(dict(current))
    new_init = new_init if new_init is not None else _import_fresh_init(root / ".act" / "scripts")
    if new_init is not None:
        try:
            base_targets, variant_targets = _role_bridge_targets(new_init, root, current["tools"])
            actlib.write_cache({"known_bridges": sorted(
                rel for rel in set(base_targets) | set(variant_targets) if (root / rel).is_file()
            )})
        except (OSError, UnicodeDecodeError, ValueError):
            pass


def record_applied(root: Path) -> bool:
    """For init.py: records the freshly created project's values as its first snapshot, so the first
    session start already has something to compare against without writing the lock itself.
    Returns whether a snapshot was written."""
    current, _problem = _dependent_values(root)
    if current is None:
        return False
    _write_snapshot(root, current)
    return True


def _sync_note_once(problem: Optional[str]) -> None:
    """One session-start note per distinct problem, remembered per checkout in
    .act-local/cache.json — never in the versioned lock."""
    cache = actlib.read_cache()
    if cache.get("sync_note") == problem:
        return
    actlib.write_cache({"sync_note": problem})
    if problem:
        print(f"[act] note: {problem} -- skill copies, CLAUDE.md and role bridges left untouched until it is fixed")


def _compare_snapshot(root: Path) -> dict:
    """Current values against .act-lock.json § applied, without writing anything. {"problem": ...}
    when `tools` cannot be used (_read_tools); otherwise the values plus what moved."""
    current, problem = _dependent_values(root)
    if current is None:
        return {"problem": problem}
    last = actlib.read_last_applied()
    has_snapshot = _valid_snapshot(last)
    old_tools: list[str] = sorted({actlib.normalize_tool(t) for t in last["tools"]}) if has_snapshot else current["tools"]
    old_roles: dict = last["roles"] if has_snapshot else current["roles"]
    bridges = actlib.read_cache().get("known_bridges")
    known = frozenset(b for b in bridges if isinstance(b, str)) if isinstance(bridges, list) else frozenset()
    return {
        "problem": None, "current": current, "has_snapshot": has_snapshot,
        "old_tools": old_tools, "old_roles": old_roles, "known": known,
        "tools_moved": old_tools != current["tools"],
        "changed_roles": frozenset(
            role for role in set(old_roles) | set(current["roles"])
            if old_roles.get(role) != current["roles"].get(role)
        ),
    }


def pending_dependent_changes(root: Path) -> Optional[str]:
    """What a session start under `session-start-refresh: warn` reports instead of syncing:
    the moved values in one short line, nothing written, no scan. None when nothing is pending (or
    no snapshot exists yet)."""
    state = _compare_snapshot(root)
    if state["problem"]:
        return state["problem"]
    if not state["has_snapshot"]:
        return None
    moved = []
    if state["tools_moved"]:
        old, new = set(state["old_tools"]), set(state["current"]["tools"])
        change = [f"+{t}" for t in sorted(new - old)] + [f"-{t}" for t in sorted(old - new)]
        moved.append(f"tools ({', '.join(change)})")
    if state["changed_roles"]:
        moved.append(f"roles ({', '.join(sorted(state['changed_roles']))})")
    return "; ".join(moved) or None


def _skill_rows_moved(root: Path, changed_roles: frozenset) -> bool:
    """Whether a changed row in docs/ai/config.md § Roles names a skill (a template skill folder or a
    project's own under docs/ai/local/skills/) -- its copy's reasoning field hangs on that row."""
    if not changed_roles:
        return False
    names: set[str] = set()
    for base in (root / ".act" / "skills", root / "docs" / "ai" / "local" / "skills"):
        if base.is_dir():
            names.update(p.name for p in base.iterdir() if p.is_dir())
    return bool(names & set(changed_roles))


def sync_dependent_files(
    root: Path, *, always_run: bool, notes: Optional[list[str]] = None,
) -> tuple[Optional[str], dict[str, dict], list[Path]]:
    """The shared entry point for step_refresh_copies()/step_new_role_bridges() and the tool-gated
    files, called from update.py (`always_run=True`, _finish_update/--catch-up) and from session
    start (.act/hooks/checks/session.py's refresh_session(), `always_run=False`).

    Each dependency is handled on its own: a moved `tools` value restores or resets only the
    skill copies and skill folders it newly targets (copy_targets(new) minus copy_targets(old),
    own skills included); what it no longer targets is removed by step_refresh_copies()'s "no
    longer shipped" case (kept if edited). A changed role row touches only that role's bridges.
    `tools` touches the files that hang on a tool themselves: CLAUDE.md and the hook entries
    in .claude/settings.json (_sync_tool_bridges) and — via `claude-code` — every role bridge
    (all restored when it joins, unedited ones removed when it leaves, _remove_role_bridges).

    The comparison runs against .act-lock.json § applied (versioned, so a branch switch is no
    value change). `always_run=True`: both steps always run, as update.py's own job (template-side
    changes) needs; only the comparison decides what is restored, reset or removed.
    `always_run=False`: a plain comparison first — no scan, no write unless a value moved; no
    snapshot yet means nothing to compare against, so nothing happens (update.py or init.py writes
    the first one). The summary is then brief: only what changed, long lists as a count.

    `tools` unusable — unreadable, missing, or holding an unknown id: nothing is synced
    and nothing recorded; update.py reports it in its step line, session start prints one note
    per distinct problem.

    Returns (summary, new_copies, touched): summary is None whenever nothing ran; new_copies is
    .act-lock.json's new "copies" value (unchanged when the copy step did not run); touched is every
    file created, reset or removed plus the inbox entry for backed-up edits, for commit tracking."""
    def lock_copies() -> dict[str, dict]:
        return dict(actlib.read_lock().get("copies", {}))

    state = _compare_snapshot(root)
    if state["problem"]:
        if always_run:
            return f"{state['problem']}; skill copies and role bridges left untouched", lock_copies(), []
        _sync_note_once(state["problem"])
        return None, lock_copies(), []
    if not always_run and actlib.read_cache().get("sync_note"):
        _sync_note_once(None)

    current = state["current"]
    old_tools, old_roles = state["old_tools"], state["old_roles"]
    tools_moved, changed_roles = state["tools_moved"], state["changed_roles"]
    claude_joined = "claude-code" in current["tools"] and "claude-code" not in old_tools
    claude_left = "claude-code" in old_tools and "claude-code" not in current["tools"]
    brief = not always_run

    if not always_run and (not state["has_snapshot"] or (not tools_moved and not changed_roles)):
        return None, lock_copies(), []

    new_init = _import_fresh_init(root / ".act" / "scripts")
    backup_dir = _new_backup_dir(root)
    parts: list[str] = []
    touched: list[Path] = []
    reset_edited: list[str] = []

    new_copies = lock_copies()
    if always_run or tools_moved or _skill_rows_moved(root, changed_roles):
        restore: frozenset[str] = frozenset()
        restore_dirs: frozenset[str] = frozenset()
        if tools_moved and new_init is not None:
            restore = frozenset(
                set(new_init.copy_targets(root, current["tools"])) - set(new_init.copy_targets(root, old_tools))
            )
            restore_dirs = frozenset(
                d for d, _ in getattr(new_init, "SKILL_TARGET_DIRS", ())
                if _skill_dir_active(new_init, d, current["tools"]) and not _skill_dir_active(new_init, d, old_tools)
            )
        copies_summary, new_copies, copies_reset, copies_removed = step_refresh_copies(
            root, False, restore_paths=restore, restore_dirs=restore_dirs, backup_dir=backup_dir, brief=brief,
        )
        # update.py's own step_lock() writes "copies" too, but never runs at session start — this
        # call is what persists it there (harmless duplicate from update.py: same value, merged;
        # written only if it changed, see actlib._write_json_merged).
        actlib.write_lock({"copies": new_copies})
        if not (brief and copies_summary.startswith("no changes")):
            parts.append(copies_summary)
        reset_edited.extend(copies_reset)
        touched.extend(copies_removed)

    if tools_moved and new_init is not None:
        tool_parts, tool_touched = _sync_tool_bridges(new_init, root, old_tools, current["tools"])
        parts.extend(tool_parts)
        touched.extend(tool_touched)
        if claude_left:
            removed_summary, removed_paths = _remove_role_bridges(new_init, root, old_tools, old_roles, brief)
            if removed_summary:
                parts.append(f"roles: {removed_summary}")
            touched.extend(removed_paths)

    role_bridges_failed = False
    if always_run or changed_roles or claude_joined:
        role_summary, role_touched, roles_reset, role_bridges_failed = step_new_role_bridges(
            root, False, notes, changed_roles=changed_roles, force_all=claude_joined,
            old_overrides=old_roles, known=state["known"], backup_dir=backup_dir, brief=brief,
        )
        if not (brief and role_summary == "no new roles or variants"):
            parts.append(f"roles: {role_summary}")
        touched.extend(role_touched)
        reset_edited.extend(roles_reset)

    # A role bridge that could not be written must not count as "applied" — skip the
    # snapshot write so the next comparison (this same config value vs. the still-old snapshot)
    # retries it, instead of silently treating the failed write as done.
    if not role_bridges_failed:
        _write_snapshot(root, current, new_init)
    elif notes is not None:
        notes.append("snapshot not updated: at least one role bridge failed to write — will retry next run")
    if reset_edited:
        inbox_entry = _report_reset_edits(root, backup_dir, reset_edited)
        if inbox_entry is not None:
            touched.append(inbox_entry)
    return ("; ".join(parts) or "nothing to change"), new_copies, touched


def step_refresh_role_frontmatter(root: Path, plan: bool, notes: Optional[list[str]] = None) -> tuple[str, list[Path]]:
    """Re-derives the `model`/`effort` frontmatter of every already-materialized role bridge (base
    and "-high" variant alike, template role or a project's own named in docs/ai/config.md §
    Roles) from the updated .act/tiers.json and that Roles table — the one part of a role bridge
    that *does* change on every update, via tiers.py's refresh_project_bridge_frontmatter().
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
# Step 7 — reconcile hook entries (.claude/settings.json) and the .gitattributes/.gitignore
# template blocks against the just-replaced .act/ (init.py only ever writes these once, at
# creation time — a project initialized before a bridge existed, or before a later template
# revision changed one, is otherwise stuck on whatever it got back then, forever)
# ---------------------------------------------------------------------------

def step_hooks_and_gitfiles(root: Path, plan: bool) -> tuple[str, list[Path]]:
    """Re-applies init.py's hook-entry merge (every BRIDGES entry of kind "json-merge", gated by
    the project's configured tools the same way init.py gates it) and its
    .gitattributes/.gitignore template-block append, using the just-installed template's own
    init.py (loaded via _import_fresh_init, same as step_refresh_copies above) — so this reuses
    exactly the merge logic a fresh `init.py` run would apply instead of a second copy of it that
    could drift out of sync. Idempotent (a second run reports nothing to do), and safe to call
    from --catch-up too (its .act/ already matches a clean template state). Returns (summary,
    touched_paths)."""
    if plan:
        return (
            "would reconcile .claude/settings.json hook entries and the "
            ".gitattributes/.gitignore template blocks",
            [],
        )

    new_init = _import_fresh_init(root / ".act" / "scripts")
    if new_init is None:
        return (
            "could not load the updated template's init.py; hook entries and "
            ".gitattributes/.gitignore left untouched",
            [],
        )

    touched: list[Path] = []
    parts: list[str] = []

    tools = _project_tools(root)
    for key, spec in new_init.BRIDGES.items():
        if spec["kind"] != "json-merge":
            continue
        if spec["tool"] is not None and spec["tool"] not in tools:
            continue
        src = root / ".act" / "bridges" / key
        dest = root / spec["dest"]
        if not src.is_file():
            continue
        message, changed = new_init._merge_settings_hooks(src, dest, False, root)
        parts.append(message)
        if changed:
            touched.append(dest)

    # Not new_init.step_git_files(): its own touched-list also includes an *unchanged* existing
    # file (right for init.py's own first-ever commit, where the whole file is new either way),
    # which here would sweep a project's own, unrelated, already-uncommitted .gitignore/
    # .gitattributes edits into "chore: update template". Call
    # _append_block() directly instead and only mark a file touched when it actually changed.
    act_dir = root / ".act"
    attrs_msg, attrs_changed = new_init._append_block(
        root / ".gitattributes", act_dir / "bridges" / "gitattributes", False,
    )
    ignore_msg, ignore_changed = new_init._append_block(
        root / ".gitignore", act_dir / "bridges" / "gitignore-lines", False,
    )
    parts.append(attrs_msg)
    parts.append(ignore_msg)
    if attrs_changed:
        touched.append(root / ".gitattributes")
    if ignore_changed:
        touched.append(root / ".gitignore")

    return ("; ".join(parts) if parts else "nothing to reconcile"), touched


# ---------------------------------------------------------------------------
# Step 8 — migrations
# ---------------------------------------------------------------------------

# Contract for a migration module (.act/migrations/NNN-slug.py, id = file stem): a plan(root)
# function returning a description without writing anything, and an apply(root) function that
# performs the change and returns (description, touched_paths). Neither is documented elsewhere
# yet — this is the minimal shape that satisfies the spec's "--plan first, then run, repeatable"
# and is exercised by this script's test fixtures; 001-one-inbox.py is the first
# migration to actually ship it.

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


def _due_migration_ids(migrations_dir: Path) -> list[str]:
    """Migration ids (file stems) under `migrations_dir` not yet recorded as applied in the lock,
    sorted. Shared by the --plan preview and the consent-prompt note below, so a run that skips
    showing a diff (resume mode, --catch-up) still names which migrations it is about to apply
    instead of hiding them behind a plain "apply?"."""
    if not migrations_dir.is_dir():
        return []
    lock = actlib.read_lock()
    applied = set(lock.get("migrations_applied", []))
    return sorted(p.stem for p in migrations_dir.glob("[0-9][0-9][0-9]-*.py") if p.stem not in applied)


def _plan_migrations_summary(new_act_dir: Path) -> str:
    """`--plan` preview of step 7: which migrations the fetched checkout would apply, listed by
    filename only. Never imports them — this script never runs code from a freshly fetched ref
    (see the module docstring); a real run only imports a migration once step 5 has made it the
    project's own .act/, which is what makes importing it safe."""
    migrations_dir = new_act_dir / "migrations"
    if not migrations_dir.is_dir():
        return "no .act/migrations/ directory"
    due = _due_migration_ids(migrations_dir)
    if not due:
        return "no due migrations"
    return "would run: " + ", ".join(due)


def _due_migrations_note(migrations_dir: Path) -> str:
    """Parenthetical for a consent prompt: which migrations this run would apply. Resume mode (no
    .act/ diff left to show — it already matches the fetched template) and --catch-up both skip
    straight to a bare "apply?"/"catch up?" question; without this, approving either one would be
    a blind yes on migrations that a normal update's diff (step 3) would otherwise have surfaced.
    Empty string if none are due, so the prompt text is unchanged in the common case."""
    due = _due_migration_ids(migrations_dir)
    if not due:
        return ""
    return f" ({len(due)} migration(s) due: {', '.join(due)})"


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
# Step 9 — refresh the generated bridges, then hand off to doctor.py
# ---------------------------------------------------------------------------

def _refresh_generated_bridges(root: Path, plan: bool) -> tuple[str, list[Path]]:
    """Re-derives CLAUDE.md/AGENTS.md/docs/ai/rules.md from .act/bridges/ (whichever of them is
    still exactly as it was last generated) before doctor.py runs — the same re-derivation
    dispatch.py's SessionStart hook does for an unedited copy (checks.session._refresh_bridges).
    Without this, doctor's import check (check_imports) still sees the *old* docs/ai/
    rules.md — the one from before this update replaced .act/rules/ — and reports every rule
    file new in this template revision as "named but not imported", a false positive that would
    otherwise clear itself only the next time a session starts. Reuses the hook's own
    function rather than rebuilding the re-derivation logic a second time, so a later change to
    which bridges dispatch.py re-derives never has to be kept in sync in two places.

    Returns (summary, touched) — `touched` are the absolute paths actually rewritten (empty under
    plan, which must write nothing, same contract as every other step here)."""
    hooks_dir = root / ".act" / "hooks"
    if not hooks_dir.is_dir():
        return "bridge refresh skipped (.act/hooks not found)", []
    hooks_path = str(hooks_dir)
    added = hooks_path not in sys.path
    if added:
        sys.path.insert(0, hooks_path)
    try:
        from checks.session import _refresh_bridges
    except Exception as exc:  # best effort — a hook-side import error must not abort the update
        return f"bridge refresh skipped ({exc})", []
    finally:
        if added:
            sys.path.remove(hooks_path)

    try:
        changed, refreshed, bootstrapped = _refresh_bridges(root, write=not plan)
    except Exception as exc:  # same as the session hook: a failed refresh is reported, never aborts the update
        return f"bridge refresh failed ({exc})", []
    if not refreshed and not changed and not bootstrapped:
        return "no generated bridges due for refresh", []
    verb = "would refresh" if plan else "refreshed"
    parts = [f"{verb} {', '.join(refreshed)}"] if refreshed else []
    if bootstrapped:
        # A raw `git pull` landed the template's own bootstrap CLAUDE.md/AGENTS.md on top
        # of the project's real bridge -- not a local edit, rewritten the same as `refreshed`
        # above, just called out separately so `--catch-up` explains why the "edited locally"
        # rule did not apply here.
        bootstrap_verb = "would replace" if plan else "replaced"
        parts.append(f"{bootstrap_verb} {', '.join(bootstrapped)} (template bootstrap file, not a local edit)")
    if changed:
        parts.append(f"left {', '.join(changed)} (edited locally)")
    touched = [] if plan else [root / rel for rel in refreshed + bootstrapped]
    return "; ".join(parts), touched


def step_doctor(root: Path, plan: bool) -> tuple[str, Optional[Path], list[Path]]:
    """Returns (summary, inbox_path, touched). doctor.py's own exit codes: 0 = no findings, 1 =
    findings (not an error — it already wrote docs/ai/inbox/report-<YYYYMMDD-HHMM>-doctor.md), 2 = a real
    failure. `touched` carries the bridge files _refresh_generated_bridges rewrote, so the caller
    can add them to the commit alongside the inbox file."""
    bridge_summary, bridge_touched = _refresh_generated_bridges(root, plan)
    doctor_path = root / ".act" / "scripts" / "doctor.py"
    if not doctor_path.is_file():
        return f"{bridge_summary}; doctor not available", None, bridge_touched
    if plan:
        return f"{bridge_summary}; would run: python .act/scripts/doctor.py --inbox", None, []
    result = subprocess.run(
        [sys.executable, str(doctor_path), "--inbox"], cwd=root, capture_output=True, text=True, encoding="utf-8",
    )
    if result.returncode not in (0, 1):
        detail = (result.stderr or result.stdout).strip().splitlines()
        last = detail[-1] if detail else f"exit code {result.returncode}"
        return f"{bridge_summary}; doctor.py --inbox failed (update not aborted over this): {last}", None, bridge_touched
    if result.returncode == 0:
        return f"{bridge_summary}; doctor.py --inbox ran, no findings", None, bridge_touched

    lines = result.stdout.splitlines()
    inbox_rel = next(
        (line[len("doctor.py: wrote "):].strip() for line in lines if line.startswith("doctor.py: wrote ")), None,
    )
    count_match = re.match(r"(\d+) finding", lines[-1].strip()) if lines else None
    count = count_match.group(1) if count_match else "some"
    inbox_path = root / inbox_rel if inbox_rel else None
    where = inbox_rel if inbox_rel else "docs/ai/inbox/"
    return f"{bridge_summary}; {count} finding(s) -> {where}", inbox_path, bridge_touched


# ---------------------------------------------------------------------------
# Step 10 — .act-lock.json + commit
# ---------------------------------------------------------------------------

def step_lock(
    root: Path, plan: bool, source: str, new_copies: dict[str, dict], fetched_commit: Optional[str],
    keep_commit: bool = False,
) -> str:
    """`fetched_commit` is what step_fetch actually cloned (None for a plain-directory source, or
    when this is a catch-up run with no fetch at all) — recorded as-is when known, so a later
    session's `git ls-remote` comparison (dispatch.py) has something real to compare against;
    falls back to .act/VERSION's own "commit=" line otherwise. `keep_commit` (a plain --catch-up:
    nothing was fetched, so nothing new is known) keeps the lock's recorded commit and source
    when neither the fetch nor VERSION names one -- an empty commit would switch off the
    downgrade guard and every reader of the installed commit."""
    if plan:
        return "would update .act-lock.json (template.version/commit/source, copies, migrations)"
    version, disk_commit = _read_version_file(root / ".act")
    commit = fetched_commit if fetched_commit is not None else disk_commit
    if keep_commit and not commit:
        old = actlib.read_lock().get("template", {})
        commit = str(old.get("commit", "") or "")
        source = source or str(old.get("source", "") or "")
    manifest_hash = manifest.manifest_fingerprint(root / ".act")
    actlib.write_lock({
        "template": {"version": version, "commit": commit, "source": source, "manifest_sha256": manifest_hash},
        "copies": new_copies,
    })
    return f"lock updated (version '{version}')"


def step_commit(root: Path, plan: bool, no_commit: bool, paths: list[Path]) -> str:
    if no_commit:
        return "--no-commit: left staged/unstaged for the caller"
    all_rels = {str(p.relative_to(root)).replace("\\", "/"): p for p in paths}
    rels = sorted(rel for rel, p in all_rels.items() if p.exists())
    missing = sorted(rel for rel, p in all_rels.items() if not p.exists())
    if missing:
        # A file this run deleted goes into the commit too — but only one git still tracks,
        # named by path (never a tree-wide add); an untracked one has nothing to commit.
        tracked = _git(["ls-files", "--", *missing], cwd=root, check=False)
        rels = sorted(set(rels) | {line.strip() for line in tracked.stdout.splitlines() if line.strip() in missing})
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
# between step 5 (replace) and step 10 (lock write)
# ---------------------------------------------------------------------------

def _migrations_due(root: Path, lock: dict) -> bool:
    migrations_dir = root / ".act" / "migrations"
    if not migrations_dir.is_dir():
        return False
    applied = set(lock.get("migrations_applied", []))
    return any(p.stem not in applied for p in migrations_dir.glob("[0-9][0-9][0-9]-*.py"))


def _resume_needed(root: Path, fetched_commit: Optional[str]) -> bool:
    """True when .act/ already matches the fetched template (step_show_diff found nothing) but the
    run that put it there never finished going through update.py — either an update.py run that
    crashed between step 5 and step 10, or a project's .act/ having been brought to that state by
    something other than update.py entirely (e.g. a plain `git pull` of the shared history:
    both look identical from here, and both need the same catch-up). Steps 6-10 then still need to
    run instead of reporting "nothing to update".

    When `fetched_commit` is known (a git source), it is compared directly against the lock's
    recorded commit — the correct, unambiguous signal. For a plain-directory source (no git commit
    to compare, e.g. this script's own test fixtures) this falls back to the previous check: the
    disk .act/VERSION text against what the lock recorded."""
    lock = actlib.read_lock()
    template = lock.get("template", {})
    if fetched_commit is not None:
        if fetched_commit != template.get("commit", ""):
            return True
        return _migrations_due(root, lock)
    disk_version, disk_commit = _read_version_file(root / ".act")
    if disk_version != template.get("version", "") or disk_commit != template.get("commit", ""):
        return True
    return _migrations_due(root, lock)


# ---------------------------------------------------------------------------
# Self-relaunch — step 5 just replaced .act/scripts/{update,init,actlib,entries,board}.py on disk, but this
# process already has the *old* versions loaded in memory (Python does not hot-reload a running
# module); steps 6-10 calling into their own top-level functions (not the ones already reached via
# _import_fresh_init, e.g. step_hooks_and_gitfiles itself) would otherwise run with whatever
# update.py looked like before this update, and only actually apply their own new behaviour on
# some *later*, unrelated invocation (the original gap). entries.py and board.py are in the list
# because update.py imports them at start-up (entries is used by _report_reset_edits). If any of
# them changed, re-exec a fresh process against the now-current update.py --catch-up (.act/ already
# matches; no fetch/diff/replace needed) so steps 6-10 run under their own current code, in the
# same overall `update.py` call the user made. Never reached in --plan (that branch returns
# before step 5's real call).
#
# Contract with the child: no new CLI arguments — a future child from an
# update further down the line would reject one it doesn't know yet — so what the parent already
# knows and the child cannot recompute for itself (the commit --catch-up's own no-fetch path never
# learns, and the consent/rescue decisions already made at steps 2/4) crosses via three env vars,
# read back only under the guard var below. This env-var contract is the stable half of the two:
# once named here, a var keeps its name and meaning, because the process that *sets* it is
# whatever update.py was on disk *before* this update (potentially much older than the one
# defining these names) and the process that *reads* it is always the fresh, current one -- a
# rename here breaks every project updating from a pre-rename version. Add a new var instead of
# repurposing one.
# ---------------------------------------------------------------------------

_SELF_RELAUNCH_GUARD_ENV = "ACT_UPDATE_RESTARTED"
_SELF_RELAUNCH_FETCHED_COMMIT_ENV = "ACT_UPDATE_FETCHED_COMMIT"
_SELF_RELAUNCH_RESCUE_ENV = "ACT_UPDATE_RESCUE"
_SELF_RELAUNCH_NOTES_ENV = "ACT_UPDATE_NOTES"
_SELF_RELAUNCH_FILES = ("update.py", "init.py", "actlib.py", "entries.py", "board.py")


def _scripts_fingerprint(root: Path) -> dict[str, str]:
    fingerprint = {}
    for name in _SELF_RELAUNCH_FILES:
        path = root / ".act" / "scripts" / name
        fingerprint[name] = actlib.sha256_file(path) if path.is_file() else ""
    return fingerprint


def _relaunch_after_replace(
    root: Path, args, source: str,
    fetched_commit: Optional[str], rescue_active: bool, notes: list[str],
) -> int:
    """--catch-up, not a plain re-run: the fetch/diff this process already did (steps 1-3) must
    not happen twice, and step 4's consent already covers this continuation, not a second
    decision -- hence --yes regardless of whether the original run passed it. `fetched_commit`
    (else --catch-up's step 10 would write an empty lock commit, making every later session think
    an update is still pending and update.py commit again next time), `rescue_active` (else a
    rescue's own files under docs/ai/local/ would be left out of this commit) and `notes`
    (anything step 1-3 already found, e.g. "--ref ignored") cross to the child via env, per the
    contract above -- guarded so a plain, user-run --catch-up never picks up stale values from the
    calling shell's own environment. The guard env var on the child is belt-and-suspenders against
    a recursive third generation of this (in practice unreachable: --catch-up's own code path
    never calls step_replace, so this check never fires for it) -- not needed for the single hop
    this actually performs, but cheap insurance against a future change coupling the two paths."""
    print("[act]   .act/scripts/update.py (or init.py/actlib.py) changed with this update -- continuing under the new version")
    child_argv = [
        sys.executable, str(root / ".act" / "scripts" / "update.py"),
        "--catch-up", "--source", source, "--yes",
    ]
    if args.no_commit:
        child_argv.append("--no-commit")
    if args.non_interactive:
        child_argv.append("--non-interactive")
    env = dict(os.environ)
    env[_SELF_RELAUNCH_GUARD_ENV] = "1"
    if fetched_commit:
        env[_SELF_RELAUNCH_FETCHED_COMMIT_ENV] = fetched_commit
    if rescue_active:
        env[_SELF_RELAUNCH_RESCUE_ENV] = "1"
    if notes:
        env[_SELF_RELAUNCH_NOTES_ENV] = json.dumps(notes)
    # The child's own output must appear after everything this process has already printed, not
    # interleaved ahead of it -- both share the same inherited stdout/stderr.
    sys.stdout.flush()
    sys.stderr.flush()
    result = subprocess.run(child_argv, cwd=root, env=env)
    return result.returncode


# ---------------------------------------------------------------------------
# Steps 6-10 + commit — shared by the normal flow (after step 5 replaces .act/) and --catch-up
# (which skips fetch/diff/replace because .act/ is already a clean, fetched-equivalent state)
# ---------------------------------------------------------------------------

def _finish_update(
    root: Path, no_commit: bool, source: str, notes: list[str],
    fetched_commit: Optional[str], rescue_active: bool, keep_commit: bool = False,
) -> int:
    sync_summary, new_copies, sync_touched = sync_dependent_files(root, always_run=True, notes=notes)
    # Own skills/roles written by hand under docs/ai/local/ get their tool copies/bridge too; the
    # entries are merged into new_copies because step_lock() below writes that value as a whole.
    try:
        import unit_copies
        own_messages, own_recorded, own_touched = unit_copies.ensure_own_unit_copies(
            root, history_check=lambda rels: _paths_in_git_history(root, rels))
        new_copies = {**new_copies, **own_recorded}
        sync_touched = [*sync_touched, *own_touched]
        # a template-named local unit is that unit's override — a normal mechanism, no note per run
        own_messages = [m for m in own_messages if "has the name of a template" not in m]
        notes.extend(f"own skills/roles: {message}" for message in own_messages if not message.endswith(": created"))
        if own_messages:
            sync_summary = "; ".join(filter(None, [sync_summary, f"own skills/roles: {'; '.join(own_messages)}"]))
    except Exception as exc:
        notes.append(f"own skill/role copies not checked ({exc.__class__.__name__}: {exc})")
    frontmatter_summary, frontmatter_touched = step_refresh_role_frontmatter(root, False, notes)
    _print_step(6, f"{sync_summary}; role frontmatter: {frontmatter_summary}")

    hooks_gitfiles_summary, hooks_gitfiles_touched = step_hooks_and_gitfiles(root, False)
    _print_step(7, hooks_gitfiles_summary)

    migrate_summary, newly_applied, migration_touched = step_migrate(root, False)
    _print_step(8, migrate_summary)

    doctor_summary, doctor_inbox, doctor_touched = step_doctor(root, False)
    _print_step(9, doctor_summary)

    _print_step(10, step_lock(root, False, source, new_copies, fetched_commit, keep_commit))

    _maybe_print_branch_hint(root, notes)

    commit_paths = [root / ".act", root / ".act-lock.json", *migration_touched]
    commit_paths.extend(root / rel for rel in new_copies)
    commit_paths.extend(sync_touched)
    commit_paths.extend(frontmatter_touched)
    commit_paths.extend(hooks_gitfiles_touched)
    commit_paths.extend(doctor_touched)
    if doctor_inbox is not None:
        commit_paths.append(doctor_inbox)
    rescue_dir = root / "docs" / "ai" / "local"
    if rescue_active and rescue_dir.is_dir():
        commit_paths.append(rescue_dir)
    commit_summary = step_commit(root, False, no_commit, commit_paths)
    print(f"[act]   commit: {commit_summary}")

    # A successful update makes any pending background-check result stale -- drop it
    # rather than let session.py's SessionStart hook report an "update available" the lock no
    # longer agrees with. Best-effort: a missing file is the common case, not an error.
    try:
        (root / ".act-local" / "update-check-result.json").unlink()
    except OSError:
        pass

    if notes:
        print(f"[act] done - {len(notes)} open point(s)")
        for note in notes:
            print(f"[act]   note: {note}")
    else:
        print("[act] done")
    return 0


# ---------------------------------------------------------------------------
# --catch-up — .act/ was already brought to a clean template state by something other than
# update.py (e.g. a plain `git pull` of the shared history); no fetch, no diff, no replace
# needed, only .act-lock.json/copies/role bridges/migrations are behind.
# ---------------------------------------------------------------------------

def _run_catch_up(root: Path, plan: bool, interactive: bool, args, source: str, notes: list[str]) -> int:
    act_dir = root / ".act"
    manifest_path = act_dir / "MANIFEST.json"
    if not manifest_path.is_file():
        print(
            "update.py: --catch-up needs .act/MANIFEST.json on disk (none found) -- run a normal update instead",
            file=sys.stderr,
        )
        return 1
    try:
        recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        recorded = None
    if recorded is None or manifest.collect_files(act_dir) != recorded:
        print(
            "update.py: --catch-up refused -- .act/ does not match its own MANIFEST.json "
            "(looks hand-edited; run a normal update to resolve that first)",
            file=sys.stderr,
        )
        return 1

    # Only under the self-relaunch guard (never for a plain, user-run --catch-up, which must not
    # pick up stale values left over in the calling shell's own environment): the parent's
    # fetched_commit/rescue_active/notes, which this no-fetch path has no way to learn on its own
    # See _relaunch_after_replace()'s docstring for the contract.
    restarted = os.environ.get(_SELF_RELAUNCH_GUARD_ENV) == "1"
    inherited_fetched_commit = os.environ.get(_SELF_RELAUNCH_FETCHED_COMMIT_ENV) if restarted else None
    inherited_rescue = restarted and os.environ.get(_SELF_RELAUNCH_RESCUE_ENV) == "1"
    if restarted:
        raw_notes = os.environ.get(_SELF_RELAUNCH_NOTES_ENV)
        if raw_notes:
            try:
                notes.extend(json.loads(raw_notes))
            except (json.JSONDecodeError, TypeError):
                pass

    print("[act] catch-up: .act/ already matches a clean template state -- only .act-lock.json/copies/roles/migrations are behind")

    if plan:
        print(
            "[act]   [6/10] " + step_refresh_copies(root, True)[0]
            + "; roles: " + step_new_role_bridges(root, True)[0]
            + "; role frontmatter: " + step_refresh_role_frontmatter(root, True)[0]
        )
        print("[act]   [7/10] " + step_hooks_and_gitfiles(root, True)[0])
        print("[act]   [8/10] " + _plan_migrations_summary(act_dir))
        print("[act]   [9/10] " + step_doctor(root, True)[0])
        print("[act]   [10/10] " + step_lock(root, True, source, {}, None))
        print("[act] done - --plan: nothing was written")
        return 0

    if args.yes:
        consented = True
    elif interactive:
        consented = _ask_choice(
            f"[act] Catch .act-lock.json up to the .act/ already on disk?{_due_migrations_note(act_dir / 'migrations')}",
            ("y", "n"), "n",
        ) == "y"
    else:
        consented = False
    if not consented:
        print("[act] catch-up aborted: no consent")
        return 1

    return _finish_update(root, args.no_commit, source, notes, inherited_fetched_commit, inherited_rescue,
                          keep_commit=not restarted)


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
    parser.add_argument("--source", help="local directory or git URL/repo to update from (default: the source recorded in .act-lock.json; a 'template' remote only when the lock names none)")
    parser.add_argument("--ref", help="tag or commit to update to (default: the source's default branch tip)")
    parser.add_argument("--allow-downgrade", action="store_true", help=(
        "apply the fetched state even when it is older than the installed template commit, or when "
        "the installed commit is not in the source's history (default: refuse, --plan only warns)"
    ))
    parser.add_argument("--on-local-changes", choices=("rescue", "discard", "abort"), help="skip the step-2 prompt")
    parser.add_argument("--yes", action="store_true", help="skip the interactive consent prompt (step 4)")
    parser.add_argument("--plan", action="store_true", help="show steps 1-3, describe 5-10, change nothing")
    parser.add_argument("--no-commit", action="store_true", help="do everything except the final commit")
    parser.add_argument("--non-interactive", action="store_true", help="never prompt")
    parser.add_argument("--catch-up", action="store_true", help=(
        "skip the fetch/diff/replace; finish steps 6-10 from the .act/ already on disk (e.g. after "
        "a plain 'git pull' of the template outside update.py) -- refuses unless that tree "
        "still matches its own MANIFEST.json"
    ))
    args = parser.parse_args(argv)

    plan = args.plan
    root = actlib.repo_root()
    interactive = actlib.is_interactive() and not plan
    notes: list[str] = []

    source = args.source or _default_source(root)
    if not source:
        print("update.py: no --source given, no source in .act-lock.json, and no 'template' remote", file=sys.stderr)
        return 1

    if args.catch_up:
        return _run_catch_up(root, plan, interactive, args, source, notes)

    tmp_root = Path(root) / ".act-local" / "update-tmp"
    _rmtree_robust(tmp_root)
    tmp_root.mkdir(parents=True, exist_ok=True)
    try:
        try:
            new_act_dir, fetched_commit = step_fetch(source, args.ref, tmp_root / "checkout", notes)
        except RuntimeError as error:
            print(_fetch_failure_message(root, source, args, error), file=sys.stderr)
            return 1
        _print_step(1, f"fetched '{source}'" + (f" @ {args.ref}" if args.ref else "") + f" -> {new_act_dir}")

        downgrade = _downgrade_warning(new_act_dir.parent, fetched_commit, source)
        if downgrade:
            if plan:
                print(f"[act] {downgrade}  (--plan: a real run would refuse)", file=sys.stderr)
            elif args.allow_downgrade:
                print(f"[act] {downgrade}  (continuing: --allow-downgrade)", file=sys.stderr)
            else:
                print(f"update.py: refusing to continue.\n[act] {downgrade}", file=sys.stderr)
                return 1

        check_summary, decision, differences = step_check_local_changes(root, args.on_local_changes, interactive, plan)
        _print_step(2, check_summary)
        if decision == "abort":
            print("[act] update aborted: local changes in .act/ were not resolved")
            return 1

        diff_summary, has_changes = step_show_diff(root, new_act_dir)
        _print_step(3, diff_summary)

        if plan:
            print("[act]   [5/10] " + step_replace(root, new_act_dir, True))
            print(
                "[act]   [6/10] " + step_refresh_copies(root, True)[0]
                + "; roles: " + step_new_role_bridges(root, True)[0]
                + "; role frontmatter: " + step_refresh_role_frontmatter(root, True)[0]
            )
            print("[act]   [7/10] " + step_hooks_and_gitfiles(root, True)[0])
            print("[act]   [8/10] " + _plan_migrations_summary(new_act_dir))
            print("[act]   [9/10] " + step_doctor(root, True)[0])
            print("[act]   [10/10] " + step_lock(root, True, source, {}, fetched_commit))
            print("[act] done - --plan: nothing was written")
            return 0

        resume_migrations_note = ""
        if not has_changes:
            if _resume_needed(root, fetched_commit):
                # No .act/ diff to show (step 3 already said so) — name the due migrations here
                # instead, so this prompt is not a blind yes on them (they would otherwise only
                # have been visible in a normal update's diff).
                resume_migrations_note = _due_migrations_note(new_act_dir / "migrations")
                print(
                    "[act]   .act/ already matches the fetched template; resuming an interrupted "
                    "update (stale lock, e.g. a crashed update or a plain 'git pull' outside "
                    "update.py, or migrations still due)"
                )
            else:
                print("[act] done - nothing to update")
                return 0

        if args.yes:
            consented = True
        elif interactive:
            consented = _ask_choice(f"[act] Apply this update?{resume_migrations_note}", ("y", "n"), "n") == "y"
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

        old_fingerprint = _scripts_fingerprint(root)
        _print_step(5, step_replace(root, new_act_dir, False))

        if (
            os.environ.get(_SELF_RELAUNCH_GUARD_ENV) != "1"
            and _scripts_fingerprint(root) != old_fingerprint
        ):
            return _relaunch_after_replace(root, args, source, fetched_commit, decision == "rescue", notes)

        return _finish_update(root, args.no_commit, source, notes, fetched_commit, decision == "rescue")
    finally:
        try:
            _rmtree_robust(tmp_root)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
