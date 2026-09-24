#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Mechanical executor of an approved adoption table (skill `act-adopt`, steps
#          4 and 7). Runs from a template checkout against a
#          project that was sighted with adopt_scan.py and whose owner approved one action per
#          sighted source in <target>/.act-local/adopt/table.json. Decides nothing itself: every
#          row is validated strictly first, and the whole run is refused on the first doubt.
#            --apply   on a new branch "act-adopt": move every `legacy` row (and every old skill/
#                      agent that carries the name of a template unit) byte-identical to
#                      docs/ai/work/archive/legacy/<old path>, then run init.py --target.
#            --finish  after the content step (skill act-adopt / T52) marked every `adopt` row
#                      done: turn adopted ai-config files into bridges, remove adopted sources
#                      and `delete` rows, bridge adopted own skills/roles (targets under
#                      docs/ai/local/skills|agents/) the way act-load-settings does, run
#                      doctor.py, list references in docs/project/ to moved/removed paths, write
#                      one inbox report.
#          Never commits (moves and removals are staged by path only). Stdlib only.
#
# Usage:
#   python .act/scripts/adopt.py --target <project> --apply [--plan]
#   python .act/scripts/adopt.py --target <project> --finish [--plan]
#   python .act/scripts/adopt.py --target <project> --abort [--plan] [--force]   # the way back
#   (--plan: validate and print what would happen, change nothing)
#
# Output format:
#   Plain text: a "refused:" block listing every problem (exit 1), or one line per action taken,
#   followed by the "nothing lost" accounting — one line per table row ("kept", "in legacy
#   (checksum ok)", "deleted", "at target: …", …) and a total line. Exit 0 on success, on a
#   --plan run and on an idempotent re-run ("already adopted" / "already finished"); 1 if the run
#   was refused or the accounting found a row that is neither at its target, in legacy, deleted
#   nor kept; 2 on a usage error (target missing, not a git repository).
#   State files, all under <target>/.act-local/adopt/: state.json (applied/finished, what moved
#   where), legacy-checksums.json (sha256 per moved file, before = after).

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Optional

import adopt_scan

TEMPLATE_ACT = Path(__file__).resolve().parent.parent  # the template checkout's .act/
SCRIPTS_DIR = TEMPLATE_ACT / "scripts"

ADOPT_DIR = ".act-local/adopt"
BRANCH = "act-adopt"
LEGACY_ROOT = "docs/ai/work/archive/legacy"
RESCUED_ROOT = ".act-local/adopt/rescued"  # ignored/untracked files out of a moved or removed unit
ABORTED_ROOT = ".act-local/adopt/aborted"  # copies of work --abort --force had to discard
BACKUP_ROOT = ".act-local/adopt/backup"    # files init.py merges into, restored by --abort
BACKED_UP = (".claude/settings.json",)
ACTIONS = ("adopt", "legacy", "keep", "delete")

# Actions each scan class may take. "unknown" may take any, but a non-keep action needs the row's
# own `confirmed: true`; so does `delete` on a project-doc row (CONFIRM_NEEDED below).
ALLOWED_ACTIONS: dict = {
    "ai-config": {"adopt", "keep", "legacy", "delete"},
    "ai-machinery": {"adopt", "delete", "keep"},
    "work": {"adopt", "legacy", "keep", "delete"},
    "log": {"legacy", "keep"},
    "project-doc": {"adopt", "legacy", "keep", "delete"},
    "unknown": set(ACTIONS),
}
CONFIRM_NEEDED = {("project-doc", "delete")} | {("unknown", a) for a in ("adopt", "legacy", "delete")}

# A scan note containing one of these protects the row: never delete, never move into the tracked
# legacy archive, never turn into a bridge (CLAUDE.local.md, .mcp.json, .claude/settings.local.json,
# any git-ignored row). The scan's note counts even if the table dropped it. A unit folder that is
# tracked but holds git-ignored files ("contains git-ignored files") is not protected, but see
# local_files(): it moves or goes only with `confirmed: true`, those files rescued first.
PROTECTED_MARKERS = ("never bridge", "git-ignored/local")
LINK_MARKERS = ("link to ", "contains link ")

# First path segments of source, test and content trees: nothing below them is moved or removed
# without the row's own `confirmed: true` (T50 review). Any first segment starting with "test"
# counts as well (tests/, testing/, test-data/).
CONTENT_TREES = {
    "src", "lib", "app", "apps", "packages", "server", "client", "pages", "components", "public",
    "static", "assets", "content", "spec", "specs", "__tests__", "e2e", "fixtures",
}

# Tool folders whose direct children are skill folders / agent files (adopt_scan MACHINERY_DIRS).
SKILL_PARENTS = {".claude/skills", ".codex/skills"}
AGENT_PARENTS = {".claude/agents", ".codex/agents", ".github/agents"}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

class Refused(Exception):
    """A precondition failed; the message (or list) is printed, nothing was changed."""

    def __init__(self, problems):
        super().__init__("refused")
        self.problems = problems if isinstance(problems, list) else [problems]


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    # core.longpaths: legacy paths nest the old path below docs/ai/work/archive/legacy/, which
    # passes Windows' 260-character limit sooner than the original did.
    result = subprocess.run(["git", "-c", "core.quotePath=false", "-c", "core.longpaths=true",
                             "-C", str(root), *args],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def _read_json(path: Path) -> Optional[dict]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Refused(f"{path.name}: not readable JSON ({exc})")
    if not isinstance(data, dict):
        raise Refused(f"{path.name}: expected a JSON object")
    return data


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _files_below(path: Path) -> dict:
    """relative posix path ("" for a single file) -> sha256, for a file or every file in a dir."""
    if path.is_file():
        return {"": _sha256(path)}
    out = {}
    for dirpath, _dirs, files in os.walk(path):
        for name in files:
            full = Path(dirpath) / name
            out[full.relative_to(path).as_posix()] = _sha256(full)
    return dict(sorted(out.items()))


def _remove_path(path: Path) -> None:
    def _chmod_retry(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, onerror=_chmod_retry)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _is_safe_rel(rel: str) -> bool:
    """Plain relative posix path; no segment Windows would silently alter (trailing dot/space)."""
    if not rel or "\\" in rel or rel.startswith("/") or ":" in rel:
        return False
    return all(part not in ("", ".", "..") and not part.endswith((".", " ")) for part in rel.split("/"))


def _key(rel: str) -> str:
    """Comparison key for a relative path: case-folded where the file system is (Windows)."""
    return os.path.normcase(rel).replace("\\", "/")


def _at_or_below(rel: str, base: str) -> bool:
    a, b = _key(rel), _key(base)
    return a == b or a.startswith(b + "/")


def local_files(root: Path, rel: str) -> list:
    """Untracked and git-ignored files below a unit folder `rel` — they would vanish with a move
    into the tracked legacy archive or a removal. Byte-code caches are regenerable and skipped."""
    if not (root / rel).is_dir():
        return []
    found = set()
    for extra in ((), ("-i",)):
        out = _git(root, "ls-files", "-o", *extra, "--exclude-standard", "--", rel, check=False).stdout
        found.update(line.strip() for line in out.splitlines() if line.strip())
    return sorted(f for f in found if "__pycache__/" not in f and not f.endswith((".pyc", ".pyo")))


def rescue(root: Path, files: list, record: dict, save) -> None:
    """Move each file to RESCUED_ROOT/<same path>, byte-identical, and record it in `record` (then
    `save()`) as soon as it is moved. A destination that already exists stops the run."""
    for rel in files:
        dest = f"{RESCUED_ROOT}/{rel}"
        if os.path.lexists(root / dest):
            raise RuntimeError(f"rescue destination already exists: {dest}")
        before = _sha256(root / rel)
        (root / dest).parent.mkdir(parents=True, exist_ok=True)
        os.replace(root / rel, root / dest)
        record[rel] = dest
        save()
        if _sha256(root / dest) != before:
            raise RuntimeError(f"checksum mismatch rescuing {rel}")


def tracked_changes(root: Path) -> dict:
    """Tracked paths that differ from HEAD (staged or not) -> sha256 now (None: gone)."""
    out = {}
    for rel in _git(root, "diff", "--name-only", "HEAD").stdout.splitlines():
        rel = rel.strip()
        if rel:
            out[rel] = _sha256(root / rel) if (root / rel).is_file() else None
    return out


def _targets(row: dict) -> list:
    value = row.get("target")
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


def _is_content_tree(rel: str) -> bool:
    first = rel.split("/", 1)[0].lower()
    return first in CONTENT_TREES or first.startswith("test")


def _note_of(row: dict, scan_row: Optional[dict]) -> str:
    notes = [n for n in ((scan_row or {}).get("note"), row.get("note")) if n]
    return "; ".join(notes)


def _is_protected(note: str) -> bool:
    return any(marker in note for marker in PROTECTED_MARKERS)


def template_units() -> tuple:
    """(skill names, agent names) the template ships under .act/skills/ and .act/agents/."""
    skills = {p.name for p in (TEMPLATE_ACT / "skills").iterdir() if p.is_dir()} if (TEMPLATE_ACT / "skills").is_dir() else set()
    agents = {p.stem for p in (TEMPLATE_ACT / "agents").glob("*.md") if p.stem != "README"}
    return skills, agents


def init_destinations() -> set:
    """Files init.py writes but never overwrites: the skeleton under docs/ai/ and the bridges
    except AGENTS.md/CLAUDE.md (those stay until --finish by design) and the hook merge into
    .claude/settings.json (a merge, not a write). Read from init.py itself, not repeated here."""
    init_mod = _load_init()
    dests = {dest for _src, dest in init_mod.skeleton_files(TEMPLATE_ACT / "skeleton")}
    dests |= {spec["dest"] for spec in init_mod.BRIDGES.values()
              if spec["kind"] != "json-merge" and spec["dest"] not in ("AGENTS.md", "CLAUDE.md")}
    return dests


def collides_with_template(rel: str, skills: set, agents: set) -> bool:
    """An old unit at a place where init.py writes a template copy or role bridge of the same name
    (the "-high" variant of a role included) — init never overwrites, so it has to move first."""
    p = PurePosixPath(rel)
    parent = p.parent.as_posix()
    if parent in SKILL_PARENTS:
        return p.name in skills
    if parent in AGENT_PARENTS:
        stem = p.name.split(".", 1)[0]
        return stem in agents or (stem.endswith("-high") and stem[: -len("-high")] in agents)
    return False


# ---------------------------------------------------------------------------
# Loading and validation
# ---------------------------------------------------------------------------

def load_inputs(root: Path) -> tuple:
    adopt_dir = root / ADOPT_DIR
    scan = _read_json(adopt_dir / "scan.json")
    if scan is None:
        raise Refused(f"{ADOPT_DIR}/scan.json missing: run adopt_scan.py --target {root} first")
    table = _read_json(adopt_dir / "table.json")
    if table is None:
        raise Refused(f"{ADOPT_DIR}/table.json missing: the approved adoption table is required")
    rows = table.get("rows")
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise Refused("table.json: expected {\"rows\": [ {...}, ... ]}")
    return scan, table, rows


def validate(root: Path, scan: dict, rows: list, on_disk: bool, moved_first=lambda _path: False) -> list:
    """Every problem with the table, as one line each (empty list: valid). `on_disk` adds the
    checks that only make sense before --apply changed the tree (existence, links, fresh scan).
    `moved_first(path)`: the source leaves its place before init (a name/place init.py writes
    itself), so a target equal to the source path is legitimate there."""
    problems = []
    scan_rows = {r["path"]: r for r in scan.get("rows", []) if isinstance(r, dict) and "path" in r}
    seen, seen_keys = set(), set()
    for index, row in enumerate(rows, 1):
        path = row.get("path")
        where = f"row {index} ({path!r})"
        if not isinstance(path, str) or not _is_safe_rel(path):
            problems.append(f"{where}: unknown path (not a plain relative posix path)")
            continue
        if _key(path) in seen_keys:
            problems.append(f"{where}: listed twice (paths compared case-insensitively where the file system is)")
            continue
        seen.add(path)
        seen_keys.add(_key(path))
        scan_row = scan_rows.get(path)
        if scan_row is None:
            problems.append(f"{where}: path not in scan.json")
            continue
        cls, action = row.get("class"), row.get("action")
        if cls != scan_row.get("class"):
            problems.append(f"{where}: class {cls!r} differs from scan.json ({scan_row.get('class')!r})")
            continue
        if action not in ACTIONS:
            problems.append(f"{where}: unknown action {action!r} (one of {', '.join(ACTIONS)})")
            continue
        if action not in ALLOWED_ACTIONS.get(cls, set()):
            problems.append(f"{where}: action {action!r} not allowed for class {cls!r} "
                            f"(allowed: {', '.join(sorted(ALLOWED_ACTIONS.get(cls, ())))})")
        confirmed = row.get("confirmed") is True
        if (cls, action) in CONFIRM_NEEDED and not confirmed:
            problems.append(f"{where}: {cls} row with action {action!r} needs \"confirmed\": true")
        for key, kind in (("done", bool), ("confirmed", bool)):
            if key in row and not isinstance(row[key], kind):
                problems.append(f"{where}: {key!r} must be true/false")
        targets = row.get("target")
        if targets is not None and not (isinstance(targets, str) or
                                        (isinstance(targets, list) and all(isinstance(t, str) for t in targets))):
            problems.append(f"{where}: target must be a path or a list of paths")
            targets = None
        for target in _targets(row) if targets is not None else []:
            if not _is_safe_rel(target):
                problems.append(f"{where}: target {target!r} is not a plain relative posix path")
            elif _at_or_below(target, path) and not (_key(target) == _key(path) and moved_first(path)):
                problems.append(f"{where}: target {target!r} is the source itself (it would be removed)")
        note = _note_of(row, scan_row)
        protected = _is_protected(note)
        if protected and action in ("delete", "legacy"):
            problems.append(f"{where}: note {note!r} forbids {action!r}")
        if protected and action == "adopt":
            bridge_dests = {"AGENTS.md", "CLAUDE.md", "docs/ai/rules.md", ".claude/settings.json"}
            if path in bridge_dests or any(t in bridge_dests for t in _targets(row)):
                problems.append(f"{where}: note {note!r} forbids a bridge overwrite")
        if action != "keep" and any(marker in note for marker in LINK_MARKERS):
            problems.append(f"{where}: a link (note {note!r}) may only be kept")
        elif action != "keep" and on_disk and adopt_scan.link_target(root, path):
            problems.append(f"{where}: below a symlink/junction, may only be kept")
        if action != "keep" and _is_content_tree(path) and not confirmed:
            problems.append(f"{where}: below a source/test/content tree, {action!r} needs \"confirmed\": true")
        if on_disk and not os.path.lexists(root / path):
            problems.append(f"{where}: unknown path (not on disk)")
        elif on_disk and (action != "keep" or moved_first(path)) and not protected:
            found = local_files(root, path)
            if found and not confirmed:
                problems.append(f"{where}: holds {len(found)} untracked/git-ignored file(s) that a move or removal "
                                f"would lose ({', '.join(found[:3])}); needs \"confirmed\": true — they are then "
                                f"rescued to {RESCUED_ROOT}/")
    problems += target_conflicts(rows, leaving_paths(rows, scan_rows, moved_first))
    for path in sorted(set(scan_rows) - seen):
        problems.append(f"scan.json row {path!r} has no table row (one row per sighted source)")
    if on_disk:
        fresh_rows, _hint, _info = adopt_scan.run(root)
        fresh = {(r.path, r.cls) for r in fresh_rows}
        stored = {(p, r.get("class")) for p, r in scan_rows.items()}
        if fresh != stored:
            diff = sorted(fresh ^ stored)[:5]
            problems.append("scan.json is stale (the tree changed since the sighting) — re-run adopt_scan.py; "
                            f"first differences: {', '.join(f'{p} [{c}]' for p, c in diff)}")
    return problems


def leaving_paths(rows: list, scan_rows: dict, moved_first) -> list:
    """Paths whose current content leaves its place: delete and legacy rows, and adopt sources
    that --finish removes or turns into a bridge (not protected ones, not those moved before init,
    whose place init.py fills with the template's own file)."""
    out = []
    for row in rows:
        path, action = row.get("path"), row.get("action")
        if not isinstance(path, str):
            continue
        if action in ("delete", "legacy"):
            out.append(path)
        elif action == "adopt" and not moved_first(path) and not _is_protected(_note_of(row, scan_rows.get(path))):
            out.append(path)
    return out


def target_conflicts(rows: list, leaving: list) -> list:
    """A target equal to or below a path that is deleted, archived, removed or bridged would be
    gone after --finish while the accounting counted it as "at target"."""
    problems = []
    for row in rows:
        if row.get("action") != "adopt":
            continue
        for target in _targets(row) if isinstance(row.get("target"), (str, list)) else []:
            if not isinstance(target, str):
                continue
            for other in leaving:
                if other != row.get("path") and _at_or_below(target, other):
                    problems.append(f"{row.get('path')!r}: target {target!r} is at or below {other!r}, "
                                    "which is deleted, archived, removed or bridged")
    return problems


# ---------------------------------------------------------------------------
# Git preconditions
# ---------------------------------------------------------------------------

def check_repo(root: Path) -> None:
    top = _git(root, "rev-parse", "--show-toplevel", check=False)
    if top.returncode != 0:
        raise Refused(f"{root} is not a git repository")
    if os.path.normcase(str(Path(top.stdout.strip()).resolve())) != os.path.normcase(str(root)):
        raise Refused(f"{root} is not the top of its git repository ({top.stdout.strip()})")
    if _git(root, "rev-parse", "--verify", "--quiet", "HEAD", check=False).returncode != 0:
        raise Refused("the repository has no commit yet")


def dirty_paths(root: Path) -> list:
    out = _git(root, "status", "--porcelain", "--untracked-files=all").stdout.splitlines()
    return [line[3:] for line in out if line and not line[3:].startswith(".act-local/")]


def branch_exists(root: Path) -> bool:
    return _git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{BRANCH}", check=False).returncode == 0


def current_branch(root: Path) -> str:
    return _git(root, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


def is_tracked(root: Path, rel: str) -> bool:
    return bool(_git(root, "ls-files", "--", rel).stdout.strip())


# ---------------------------------------------------------------------------
# Accounting — "nothing lost"
# ---------------------------------------------------------------------------

def accounting(root: Path, rows: list, state: dict, phase: str) -> tuple:
    """(lines, ok): one line per table row, where its content is now; ok is False if any row is
    neither at its target, in legacy with matching checksums, deleted (listed) nor kept."""
    sums = _read_json(root / ADOPT_DIR / "legacy-checksums.json") or {}
    moved = state.get("moved", {})
    removed_early = set(state.get("removed_at_apply", []))
    bridged = set(state.get("bridged", []))
    lines, ok, counts = [], True, {}

    def emit(path: str, status: str, good: bool = True) -> None:
        nonlocal ok
        ok = ok and good
        key = status.split(" (")[0].split(":")[0]
        counts[key] = counts.get(key, 0) + 1
        lines.append(f"  {'ok  ' if good else 'FAIL'} {path}: {status}")

    for row in rows:
        path, action = row["path"], row["action"]
        if path in moved:
            entry = sums.get(path, {})
            dest = root / moved[path]
            now = _files_below(dest) if dest.exists() else {}
            good = bool(entry) and now == entry.get("files")
            label = "in legacy" if action == "legacy" else f"in legacy ({action}, moved before init)"
            emit(path, f"{label} (checksum {'ok' if good else 'MISMATCH'}) -> {moved[path]}", good)
            continue
        if action == "delete":
            if path in removed_early:
                emit(path, "deleted (before init; the template's own file may now stand there)")
            elif not os.path.lexists(root / path):
                emit(path, "deleted")
            elif phase == "apply":
                emit(path, "delete pending (--finish)")
            else:
                emit(path, "deleted: still on disk", False)
        elif action == "keep":
            emit(path, "kept", os.path.lexists(root / path))
        elif action == "legacy":
            emit(path, "legacy: not moved", False)
        else:  # adopt
            if phase == "apply":
                emit(path, "adoption pending (content step, then --finish)", os.path.lexists(root / path))
                continue
            targets = _targets(row)
            missing = [t for t in targets if not os.path.lexists(root / t)]
            if not targets or missing:
                emit(path, f"at target: MISSING {', '.join(missing) or '(no target)'}", False)
                continue
            source = "bridge" if path in bridged else (
                "source stays (protected)" if os.path.lexists(root / path) else "source removed")
            emit(path, f"at target: {', '.join(targets)} ({source})")
    for original, saved in state.get("rescued", {}).items():
        emit(original, f"rescued (untracked/ignored file of a moved or removed unit) -> {saved}",
             (root / saved).is_file())
    lines.append("  total: " + ", ".join(f"{n} {k}" for k, n in sorted(counts.items())) +
                 f" — {len(rows)} row(s), {'nothing lost' if ok else 'ACCOUNTING FAILED'}")
    return lines, ok


# ---------------------------------------------------------------------------
# --apply
# ---------------------------------------------------------------------------

def init_supports_no_commit() -> bool:
    result = subprocess.run([sys.executable, str(SCRIPTS_DIR / "init.py"), "--help"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    return "--no-commit" in result.stdout


def untracked_files(root: Path) -> set:
    """Every untracked file, git-ignored ones included (one git call) — the before/after snapshot
    that tells --abort exactly which files init.py created."""
    out = _git(root, "ls-files", "-o", check=False).stdout
    return {line.strip() for line in out.splitlines() if line.strip()}


def _hash_path(path: Path) -> Optional[str]:
    if not os.path.lexists(path):
        return None
    files = _files_below(path)
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode("utf-8")).hexdigest()


def way_back(root: Path) -> str:
    return f"python {Path(__file__).name} --target {root} --abort"


def cmd_apply(root: Path, plan: bool) -> int:
    state_path = root / ADOPT_DIR / "state.json"
    state = _read_json(state_path)
    if state and state.get("state") in ("applied", "finished"):
        print(f"already adopted or in progress: state '{state['state']}' since {state.get('applied', '?')} "
              f"on branch {state.get('branch', BRANCH)} (next: {'--finish' if state['state'] == 'applied' else 'nothing'})")
        return 0
    if state:
        reason = state.get("error") or f"init.py exit {state.get('init_exit')}"
        raise Refused(f"a previous --apply stopped with state '{state.get('state')}' ({reason}); "
                      f"moved so far: {len(state.get('moved', {}))}. Way back: {way_back(root)}")
    check_repo(root)
    if branch_exists(root):
        raise Refused(f"branch '{BRANCH}' already exists: already adopted or in progress (no state.json)")
    if current_branch(root) == "HEAD":
        raise Refused(f"HEAD is detached: check out the branch the adoption starts from (git checkout <branch>); "
                      f"'{BRANCH}' is created from it and --abort returns to it")
    scan, _table, rows = load_inputs(root)
    skills, agents = template_units()
    init_dests = init_destinations()

    def moved_first(path: str) -> bool:
        return collides_with_template(path, skills, agents) or path in init_dests

    problems = validate(root, scan, rows, on_disk=True, moved_first=moved_first)
    dirty = dirty_paths(root)
    if dirty:
        problems.append(f"working tree not clean (only .act-local/ may be untracked): {', '.join(dirty[:8])}")
    if problems:
        raise Refused(problems)

    moves, early_deletes, shadowed = [], [], []
    for row in rows:
        path, action = row["path"], row["action"]
        colliding = collides_with_template(path, skills, agents) or path in init_dests
        if path in init_dests and action == "keep":
            shadowed.append(path)  # kept means kept: init then leaves the project's file in place
        elif action == "legacy" or (colliding and action in ("adopt", "keep")):
            moves.append((path, f"{LEGACY_ROOT}/{path}", action, colliding))
        elif colliding and action == "delete":
            early_deletes.append(path)
    clash = [dest for _p, dest, _a, _c in moves if os.path.lexists(root / dest)]
    if clash:
        raise Refused([f"legacy destination already exists: {dest}" for dest in clash])
    to_rescue = {path: local_files(root, path) for path in [*(m[0] for m in moves), *early_deletes]}
    to_rescue = {path: files for path, files in to_rescue.items() if files}

    no_commit = init_supports_no_commit()
    init_cmd = [sys.executable, str(SCRIPTS_DIR / "init.py"), "--target", str(root), "--non-interactive"]
    if no_commit:
        init_cmd.append("--no-commit")
    prefix = "would " if plan else ""
    print(f"[adopt] {prefix}create and switch to branch '{BRANCH}' (from '{current_branch(root)}')")
    for path, files in to_rescue.items():
        print(f"[adopt] {prefix}rescue {len(files)} untracked/ignored file(s) of {path} to {RESCUED_ROOT}/ (confirmed)")
    for path, dest, action, colliding in moves:
        reason = f" (action {action}, init.py writes the template's own there)" if colliding and action != "legacy" else ""
        print(f"[adopt] {prefix}move {path} -> {dest}{reason}")
    for path in early_deletes:
        print(f"[adopt] {prefix}delete {path} before init (init.py writes the template's own there)")
    for path in shadowed:
        print(f"[adopt] note: {path} is kept, so init.py leaves it and does not write the template's version")
    print(f"[adopt] {prefix}run {' '.join(Path(c).name if i < 2 else c for i, c in enumerate(init_cmd))}")
    if not no_commit:
        print("[adopt] note: init.py has no --no-commit, it makes its own first commit on the branch "
              "(its own paths only; the legacy moves are staged afterwards, never committed)")
    if plan:
        print("[adopt] plan only, nothing changed")
        return 0

    base = current_branch(root)
    base_commit = _git(root, "rev-parse", "HEAD").stdout.strip()
    before_untracked = untracked_files(root)
    new_state = {
        "state": "apply-failed", "applied": datetime.now().isoformat(timespec="seconds"),
        "branch": BRANCH, "base_branch": base, "base_commit": base_commit,
        "moved": {}, "removed_at_apply": [], "rescued": {}, "created": [],
        "actions": {row["path"]: row["action"] for row in rows},
    }
    _git(root, "checkout", "-q", "-b", BRANCH)
    _write_json(state_path, new_state)

    # Byte-identical move: sha256 per file before, move, sha256 again at the destination. Plain
    # file-system moves (staged only after init.py). Any failure stops here with state
    # "apply-failed" and what was already moved, for --abort.
    checksums = {}
    try:
        for path, files in to_rescue.items():
            rescue(root, files, new_state["rescued"], lambda: _write_json(state_path, new_state))
        for path, dest, _action, _colliding in moves:
            before = _files_below(root / path)
            (root / dest).parent.mkdir(parents=True, exist_ok=True)
            os.replace(root / path, root / dest)
            new_state["moved"][path] = dest
            _write_json(state_path, new_state)
            after = _files_below(root / dest)
            checksums[path] = {"legacy": dest, "files": after}
            if after != before:
                raise RuntimeError(f"checksum mismatch after moving {path} -> {dest}")
        for path in early_deletes:
            _remove_path(root / path)
            new_state["removed_at_apply"].append(path)
    except (OSError, RuntimeError) as exc:
        new_state["error"] = str(exc)
        _write_json(root / ADOPT_DIR / "legacy-checksums.json", checksums)
        _write_json(state_path, new_state)
        raise Refused(f"stopped before init: {exc}. Moved so far: {len(new_state['moved'])}, "
                      f"removed: {len(new_state['removed_at_apply'])}. Way back: {way_back(root)}")
    _write_json(root / ADOPT_DIR / "legacy-checksums.json", checksums)
    new_state["backup"] = {}
    for rel in BACKED_UP:  # init.py merges hook entries into it; --abort puts the original back
        if (root / rel).is_file():
            (root / BACKUP_ROOT / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / rel, root / BACKUP_ROOT / rel)
            new_state["backup"][rel] = f"{BACKUP_ROOT}/{rel}"
    _write_json(state_path, new_state)

    print(f"[adopt] running init.py --target (non-interactive){' --no-commit' if no_commit else ''}")
    head_before = _git(root, "rev-parse", "HEAD").stdout.strip()
    result = subprocess.run(init_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    for line in (result.stdout + result.stderr).splitlines():
        print(f"    {line if len(line) <= 200 else line[:199] + '…'}")
    head_after = _git(root, "rev-parse", "HEAD").stdout.strip()
    own = (f"{LEGACY_ROOT}/", f"{ADOPT_DIR}/")
    new_state["created"] = sorted(f for f in untracked_files(root) - before_untracked if not f.startswith(own))
    new_state["created_hashes"] = {f: _sha256(root / f) for f in new_state["created"] if (root / f).is_file()}
    new_state.update({
        "state": "applied" if result.returncode == 0 else "init-failed",
        "init_exit": result.returncode, "init_commit": head_after if head_after != head_before else None,
        # What each adopt target looked like after init: --finish refuses one that is unchanged.
        "target_hashes": {t: _hash_path(root / t) for row in rows if row["action"] == "adopt"
                          for t in _targets(row) if os.path.lexists(root / t)},
    })
    _write_json(state_path, new_state)

    # Stage exactly what adopt moved or removed (the index then equals a `git mv`/`git rm`), by path.
    moved = new_state["moved"]
    staged = [path for path in [*moved, *early_deletes]
              if not os.path.lexists(root / path) and is_tracked(root, path)]
    staged += list(moved.values())
    try:
        for start in range(0, len(staged), 50):
            _git(root, "add", "-A", "--", *staged[start:start + 50])
    except RuntimeError as exc:
        print(f"[adopt] WARNING: staging the moves failed ({exc}); the files are moved and verified, "
              f"stage them by path before committing")
    # What --apply leaves changed in tracked files: --abort treats anything beyond this as work.
    new_state["dirty_after_apply"] = tracked_changes(root)
    _write_json(state_path, new_state)
    if result.returncode != 0:
        print(f"[adopt] init.py failed (exit {result.returncode}). Way back: {way_back(root)}")
        return 1
    if new_state["init_commit"]:
        print(f"[adopt] init.py committed {new_state['init_commit'][:7]} on '{BRANCH}' (its own paths only)")
    lines, ok = accounting(root, rows, new_state, "apply")
    print("[adopt] accounting after --apply:")
    print("\n".join(lines))
    print(f"[adopt] state 'applied'. Next: adopt the content (act-adopt), mark rows done, then --finish. "
          f"Way back: {way_back(root)}")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# --abort
# ---------------------------------------------------------------------------

def _prune_empty_dirs(root: Path, rel_files: list) -> None:
    """Remove directories left empty by removed files, deepest first, never the root itself."""
    dirs = sorted({str(PurePosixPath(f).parent) for f in rel_files}, key=lambda d: -d.count("/"))
    for rel in dirs:
        current = PurePosixPath(rel)
        while current.as_posix() not in ("", "."):
            path = root / current.as_posix()
            try:
                if path.is_dir() and not any(path.iterdir()):
                    path.rmdir()
                else:
                    break
            except OSError:
                break
            current = current.parent


def _files_at(root: Path, rel: str) -> list:
    """Relative paths of every file at `rel` (the file itself, or every file below a folder)."""
    path = root / rel
    if path.is_file():
        return [rel]
    if not path.is_dir():
        return []
    return sorted(p.relative_to(root).as_posix() for p in path.rglob("*") if p.is_file())


def content_changes(root: Path, state: dict) -> list:
    """Files --abort would destroy that hold work done after --apply: a file init.py created whose
    content changed, a tracked file changed beyond what --apply left, and anything new at a place a
    moved unit has to return to."""
    created = state.get("created_hashes", {})
    after = state.get("dirty_after_apply", {})
    changed = {rel for rel, digest in created.items() if (root / rel).is_file() and _sha256(root / rel) != digest}
    for rel, digest in tracked_changes(root).items():
        if digest is not None and after.get(rel, "-") != digest:
            changed.add(rel)
    for old in state.get("moved", {}):
        for rel in _files_at(root, old):
            expected = created.get(rel) or after.get(rel)
            if expected is None or _sha256(root / rel) != expected:
                changed.add(rel)
    return sorted(changed)


def cmd_abort(root: Path, plan: bool, force: bool) -> int:
    """The way back after --apply (or a stopped --apply), as a resumable sequence — state.json is
    rewritten after every step, so a second --abort continues where the first one stopped. Only
    files recorded as created by init.py and still unchanged are removed; a moved unit goes back
    only from a legacy copy that still holds exactly the moved content. Work done after --apply (a
    changed file init.py created, an uncommitted edit to a tracked file, a new file where a moved
    unit returns) refuses the abort; with --force those files are first copied to
    .act-local/adopt/aborted/<path> and listed, then removed or reset. A commit on the branch other
    than init.py's own refuses it too."""
    state_path = root / ADOPT_DIR / "state.json"
    state = _read_json(state_path)
    if not state:
        print("nothing to abort: no state.json (already aborted, or never applied)")
        return 0
    branch, base = state.get("branch", BRANCH), state.get("base_branch", "")
    if state.get("state") == "finished":
        raise Refused(f"already finished: review branch '{branch}' and drop it by hand "
                      f"(git checkout {base} && git branch -D {branch})")
    check_repo(root)
    if not base or base == "HEAD":
        raise Refused(f"the recorded start is a detached HEAD ({state.get('base_commit', '?')[:12]}): check out the "
                      f"branch you started from, delete '{branch}' by hand, and remove {ADOPT_DIR}/state.json")
    progress = state.setdefault("abort", {"steps": [], "saved": {}, "restored": [], "unrestored_rescue": []})
    steps = progress["steps"]

    def save() -> None:
        _write_json(state_path, state)

    changed = []
    if not steps:
        if current_branch(root) != branch:
            raise Refused(f"not on branch '{branch}' (on '{current_branch(root)}')")
        own = {c for c in (state.get("init_commit"),) if c}
        extra = [c for c in _git(root, "rev-list", f"{state['base_commit']}..{branch}").stdout.split() if c not in own]
        if extra:
            raise Refused(f"'{branch}' carries {len(extra)} commit(s) besides init.py's ({', '.join(c[:7] for c in extra[:5])}) "
                          f"that --abort would lose. Keep them on a branch (git branch {branch}-work {branch}), "
                          f"then take them off '{branch}' without touching any file "
                          f"(git reset --soft {(state.get('init_commit') or state['base_commit'])[:12]}); their files then "
                          f"count as work since --apply, which --abort --force saves to {ABORTED_ROOT}/")
        changed = content_changes(root, state)
        if changed and not force:
            raise Refused([f"changed since --apply, --abort would lose it: {rel}" for rel in changed] +
                          [f"re-run with --abort --force to copy these to {ABORTED_ROOT}/ first"])
    prefix = "would " if plan else ""
    print(f"[adopt] {prefix}save {len(changed)} changed file(s) to {ABORTED_ROOT}/, remove "
          f"{len(state.get('created', []))} file(s) init.py created, put back {len(state.get('moved', {}))} moved and "
          f"{len(state.get('rescued', {}))} rescued file(s), check out '{base}', delete branch '{branch}'"
          + (f" (resuming after: {', '.join(steps)})" if steps else ""))
    if plan:
        print("[adopt] plan only, nothing changed")
        return 0

    if "saved" not in steps:
        for rel in changed:
            dest = root / ABORTED_ROOT / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / rel, dest)
            progress["saved"][rel] = _sha256(root / rel)
        steps.append("saved")
        save()
    saved = progress["saved"]

    def removable(rel: str, expected: Optional[str]) -> bool:
        digest = _sha256(root / rel)
        return digest == expected or saved.get(rel) == digest

    if "created" not in steps:
        created = state.get("created_hashes") or {rel: None for rel in state.get("created", [])}
        for rel, expected in created.items():
            path = root / rel
            if not _is_safe_rel(rel) or not path.is_file():
                continue
            if expected is None or removable(rel, expected):  # None: an apply-failed state, init never ran
                path.unlink()
            else:
                print(f"[adopt] WARNING: {rel} changed and was not saved, left in place")
        _prune_empty_dirs(root, list(created))
        steps.append("created")
        save()

    if "unstage" not in steps:
        _git(root, "reset", "-q")  # unstage the moves; the files themselves are put back below
        steps.append("unstage")
        save()

    sums = _read_json(root / ADOPT_DIR / "legacy-checksums.json") or {}
    after = state.get("dirty_after_apply", {})
    for old, dest in state.get("moved", {}).items():
        if old in progress["restored"]:
            continue
        want = (sums.get(old) or {}).get("files")
        if want is None:
            raise Refused(f"no checksum recorded for {old}; nothing touched there")
        if not os.path.lexists(root / dest) or _files_below(root / dest) != want:
            if os.path.lexists(root / old) and _files_below(root / old) == want:
                progress["restored"].append(old)
                save()
                continue
            raise Refused(f"cannot put back {old}: {dest} no longer holds the moved content (state kept, "
                          f"steps done: {', '.join(steps)})")
        for rel in _files_at(root, old):
            if not removable(rel, after.get(rel)):
                raise Refused(f"cannot put back {old}: {rel} is in the way and was not saved (use --force)")
        in_the_way = _files_at(root, old)
        for rel in in_the_way:
            (root / rel).unlink()
        _prune_empty_dirs(root, in_the_way)
        if (root / old).is_dir() and not any((root / old).rglob("*")):
            shutil.rmtree(root / old)  # only empty folders left
        (root / old).parent.mkdir(parents=True, exist_ok=True)
        os.replace(root / dest, root / old)
        _prune_empty_dirs(root, [dest])
        progress["restored"].append(old)
        save()

    for original, saved_at in state.get("rescued", {}).items():
        if os.path.lexists(root / saved_at) and not os.path.lexists(root / original):
            (root / original).parent.mkdir(parents=True, exist_ok=True)
            os.replace(root / saved_at, root / original)
            _prune_empty_dirs(root, [saved_at])
            save()
        elif os.path.lexists(root / saved_at) and original not in progress["unrestored_rescue"]:
            progress["unrestored_rescue"].append(original)  # the original place is taken: keep the copy
            save()

    if "checkout" not in steps:
        if current_branch(root) != base:
            _git(root, "checkout", "-q", "-f", base)  # tracked files as on the base branch
        steps.append("checkout")
        save()

    for original, saved_at in state.get("backup", {}).items():
        if (root / saved_at).is_file():
            (root / original).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / saved_at, root / original)
            (root / saved_at).unlink()
            _prune_empty_dirs(root, [saved_at])

    if branch_exists(root):
        _git(root, "branch", "-q", "-D", branch)
    for name in ("state.json", "legacy-checksums.json"):
        if (root / ADOPT_DIR / name).is_file():
            (root / ADOPT_DIR / name).unlink()
    print(f"[adopt] aborted: back on '{base}', branch '{branch}' deleted")
    if saved:
        print(f"[adopt] saved before the abort ({ABORTED_ROOT}/): {', '.join(sorted(saved))}")
    if progress["unrestored_rescue"]:
        print(f"[adopt] rescued files whose place was taken, still under {RESCUED_ROOT}/: "
              f"{', '.join(progress['unrestored_rescue'])}")
    left = [f for f in _git(root, "ls-files", "-o", "--exclude-standard").stdout.splitlines()
            if f.strip() and not f.startswith(".act-local/")]
    if left:
        print(f"[adopt] left in place (not created by adopt/init): {', '.join(left[:10])}")
    return 0


# ---------------------------------------------------------------------------
# --finish
# ---------------------------------------------------------------------------

def _load_init():
    """init.py as a module — its bridge writer (_write_text_file) and bridge table (BRIDGES,
    step_thin_bridges) are reused so a bridge written here is byte-for-byte what init writes."""
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import init  # noqa: E402 — imported late on purpose, only --finish needs it
    return init


def bridge_plan(init_mod, tools: list) -> dict:
    """ai-config destination -> (bridge key, spec) for the bridges the project's tools select."""
    selected, _summary = init_mod.step_thin_bridges(tools)
    return {spec["dest"]: (key, spec) for key, spec in selected.items()}


OWN_SKILLS = ("docs", "ai", "local", "skills")
OWN_AGENTS = ("docs", "ai", "local", "agents")


def own_units(rows: list) -> tuple:
    """(units, overrides, problems) for adopt rows whose target is an own skill
    (docs/ai/local/skills/<name>/...) or an own role (docs/ai/local/agents/<name>.md). units:
    sorted (area, name) pairs --finish bridges like act-load-settings does. A name the template
    ships itself is refused — at that place the file overrides the template unit, it is not an own
    unit — unless the row's note says "override": then it is left to the template's own copy
    mechanism (init/update resolve docs/ai/local/ first), no bridge written here."""
    skills, agents = template_units()
    units, overrides, problems = set(), set(), []
    for row in rows:
        if row.get("action") != "adopt":
            continue
        for target in _targets(row):
            parts = PurePosixPath(target).parts
            if parts[:4] == OWN_SKILLS and len(parts) >= 5:
                area, name, clash = "skills", parts[4], parts[4] in skills
            elif parts[:4] == OWN_AGENTS and len(parts) >= 5:
                if len(parts) > 5 or not parts[4].endswith(".md"):
                    problems.append(f"{row['path']!r}: target {target!r}: an own role is a flat docs/ai/local/agents/<name>.md")
                    continue
                stem = parts[4][: -len(".md")]
                area, name = "agents", stem
                clash = stem in agents or (stem.endswith("-high") and stem[: -len("-high")] in agents)
            else:
                continue
            if clash and "override" in (row.get("note") or ""):
                overrides.add((area, name))
            elif clash:
                problems.append(f"{row['path']!r}: target {target!r} carries the name of the template's own "
                                f"{area[:-1]} {name!r} — there it overrides the template unit, it is not an own one: "
                                "give it its own name, or put \"override\" in the row's note if an override is meant")
            else:
                units.add((area, name))
    return sorted(units), sorted(overrides), problems


def bridge_own_units(root: Path, units: list) -> list:
    """Bridge own skills/roles through settings_load.write_unit_bridges() — the act-load-settings
    path: role bridge per tool, skill copies to every configured SKILL_TARGET_DIRS entry, each
    copy recorded in .act-lock.json § copies. Returns its messages."""
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    import settings_load  # noqa: E402 — only --finish needs it
    plan = []
    for area, name in units:
        if area == "skills":
            base = root / "docs" / "ai" / "local" / "skills" / name
            for file in sorted(p for p in base.rglob("*") if p.is_file()):
                rel = file.relative_to(base).as_posix()
                plan.append({"area": "skills", "status": "new", "path": f"{name}/{rel}",
                             "dest": f"docs/ai/local/skills/{name}/{rel}"})
        else:
            plan.append({"area": "agents", "status": "new", "path": f"{name}.md",
                         "dest": f"docs/ai/local/agents/{name}.md"})
    return settings_load.write_unit_bridges(root, settings_load.Analysis(file_plan=plan))


def find_references(root: Path, paths: list) -> list:
    """'<file>:<line>: <path>' for every mention of a moved/removed path under docs/project/."""
    base = root / "docs" / "project"
    hits = []
    if not base.is_dir() or not paths:
        return hits
    for file in sorted(base.rglob("*")):
        if not file.is_file() or file.suffix.lower() not in {".md", ".txt", ".rst", ".adoc"}:
            continue
        try:
            text = file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            for path in paths:
                if path in line:
                    hits.append(f"{file.relative_to(root).as_posix()}:{number}: {path}")
    return hits


def run_doctor(root: Path) -> tuple:
    """(exit code, finding lines) of the project's own doctor.py."""
    doctor = root / ".act" / "scripts" / "doctor.py"
    result = subprocess.run([sys.executable, str(doctor), "--json"], cwd=str(root),
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        findings = json.loads(result.stdout).get("findings", [])
    except json.JSONDecodeError:
        return result.returncode, [(result.stdout + result.stderr).strip()[:300]]
    return result.returncode, [f"{f.get('path')}:{f.get('line') or ''}: [{f.get('kind')}] {f.get('message')}"
                               for f in findings]


def write_report(root: Path, rows: list, state: dict, doctor: tuple, refs: list, acc: list) -> Path:
    inbox = root / "docs" / "ai" / "inbox"
    stem = f"{date.today().isoformat()}-adoption-report"
    dest, n = inbox / f"{stem}.md", 2
    while dest.exists():
        dest, n = inbox / f"{stem}-{n}.md", n + 1
    moved = state.get("moved", {})
    by_action = {a: [r for r in rows if r["action"] == a and r["path"] not in moved] for a in ACTIONS}
    out = ["for: all", "status: open", "", "# Adoption report (`adopt.py --finish`)", "",
           f"Branch `{state.get('branch', BRANCH)}` (from `{state.get('base_branch', '?')}`), nothing committed by "
           "adopt.py. Review the branch, then commit per path or drop it.", "", "## Adopted (source → target)", ""]
    out += [f"- `{r['path']}` → {', '.join(f'`{t}`' for t in _targets(r))}"
            + (" (now a bridge)" if r["path"] in state.get("bridged", []) else "") for r in by_action["adopt"]] or ["- none"]
    out += ["", "## Own skills and roles bridged (as `act-load-settings` does)", ""]
    out += [f"- `docs/ai/local/{unit}`" for unit in state.get("own_units", [])] or ["- none"]
    out += ["", "## Moved to legacy (byte-identical, see `.act-local/adopt/legacy-checksums.json`)", ""]
    out += [f"- `{old}` → `{new}`" for old, new in moved.items()] or ["- none"]
    out += ["", "## Deleted", ""]
    out += [f"- `{r['path']}`" for r in by_action["delete"]] or ["- none"]
    out += ["", "## Kept in place", ""]
    out += [f"- `{r['path']}`" for r in by_action["keep"]] or ["- none"]
    out += ["", f"## doctor.py (exit {doctor[0]})", ""]
    out += [f"- {line}" for line in doctor[1][:30]] or ["- no findings"]
    out += ["", "## References in docs/project/ to moved or removed paths", ""]
    out += [f"- `{line}`" for line in refs[:50]] or ["- none"]
    out += ["", "## Accounting", "", "```text", *[line.strip() for line in acc], "```", ""]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(out), encoding="utf-8")
    return dest


def cmd_finish(root: Path, plan: bool) -> int:
    state_path = root / ADOPT_DIR / "state.json"
    state = _read_json(state_path)
    if state and state.get("state") == "finished":
        print(f"already finished ({state.get('finished', '?')}); report: {state.get('report', '?')}")
        return 0
    if not state or state.get("state") != "applied":
        raise Refused(f"no applied adoption (state: {state.get('state') if state else 'none'}): run --apply first")
    check_repo(root)
    if current_branch(root) != state.get("branch", BRANCH):
        raise Refused(f"not on branch '{state.get('branch', BRANCH)}' (on '{current_branch(root)}')")
    scan, _table, rows = load_inputs(root)
    moved_before_init = set(state.get("moved", {})) | set(state.get("removed_at_apply", []))
    problems = validate(root, scan, rows, on_disk=False, moved_first=moved_before_init.__contains__)
    actions = state.get("actions", {})
    hashes = state.get("target_hashes", {})
    for row in rows:
        if actions.get(row.get("path")) != row.get("action"):
            problems.append(f"{row.get('path')!r}: action changed since --apply "
                            f"({actions.get(row.get('path'))!r} -> {row.get('action')!r})")
        if row.get("action") == "adopt":
            if row.get("done") is not True:
                problems.append(f"{row['path']!r}: adopt row not done yet (\"done\": true after the content step)")
            elif not _targets(row):
                problems.append(f"{row['path']!r}: adopt row has no target")
            else:
                for target in _targets(row):
                    if not os.path.lexists(root / target):
                        problems.append(f"{row['path']!r}: target {target!r} not on disk")
                    elif target in hashes and hashes[target] == _hash_path(root / target):
                        problems.append(f"{row['path']!r}: target {target!r} unchanged since --apply "
                                        "— content not adopted?")
    units, overrides, unit_problems = own_units(rows)
    problems += unit_problems
    if problems:
        raise Refused(problems)

    os.chdir(root)  # actlib (used by init's helpers) finds the project from the working directory
    init_mod = _load_init()
    import actlib
    tools = [t.strip() for t in actlib.read_config().get("tools", "").split(",") if t.strip()]
    bridges = bridge_plan(init_mod, tools)
    scan_rows = {r["path"]: r for r in scan.get("rows", [])}
    moved = state.get("moved", {})
    to_bridge, to_remove, protected_stay = [], [], []
    for row in rows:
        path, action = row["path"], row["action"]
        if path in moved or path in state.get("removed_at_apply", []):
            continue
        if action == "delete":
            to_remove.append(path)
        elif action == "adopt":
            if _is_protected(_note_of(row, scan_rows.get(path))):
                protected_stay.append(path)
            elif row["class"] == "ai-config" and path in bridges:
                to_bridge.append(path)
            else:
                to_remove.append(path)
    # Checked again against what really leaves now, before anything changes.
    problems = target_conflicts(rows, [*to_remove, *to_bridge])
    confirmed_rows = {row["path"] for row in rows if row.get("confirmed") is True}
    to_rescue = {}
    for path in to_remove:
        found = local_files(root, path)
        if found and path not in confirmed_rows:
            problems.append(f"{path!r}: holds {len(found)} untracked/git-ignored file(s) that the removal would "
                            f"lose ({', '.join(found[:3])}); needs \"confirmed\": true — they are then rescued "
                            f"to {RESCUED_ROOT}/")
        elif found:
            to_rescue[path] = found
    if problems:
        raise Refused(problems)
    prefix = "would " if plan else ""
    for path, files in to_rescue.items():
        print(f"[adopt] {prefix}rescue {len(files)} untracked/ignored file(s) of {path} to {RESCUED_ROOT}/ (confirmed)")
    for path in to_bridge:
        kind = bridges[path][1]["kind"]
        print(f"[adopt] {prefix}turn {path} into its bridge" +
              (" (hook entries already merged by init, file stays)" if kind != "verbatim" else ""))
    for path in to_remove:
        print(f"[adopt] {prefix}remove {path}")
    for path in protected_stay:
        print(f"[adopt] leave {path} in place (protected note: never bridged, never removed)")
    for area, name in units:
        print(f"[adopt] {prefix}bridge own {area[:-1]} {name!r} into the tool folders (as act-load-settings does)")
    for area, name in overrides:
        print(f"[adopt] leave {area[:-1]} {name!r} to the template's copy mechanism (override of a template unit)")
    if plan:
        print(f"[adopt] {prefix}run doctor.py, check docs/project/ references, write the inbox report")
        print("[adopt] plan only, nothing changed")
        return 0

    state.setdefault("rescued", {})
    try:
        for files in to_rescue.values():
            rescue(root, files, state["rescued"], lambda: _write_json(state_path, state))
    except (OSError, RuntimeError) as exc:
        _write_json(state_path, state)
        raise Refused(f"stopped before any removal: {exc}")
    bridged = []
    cfg_tokens = init_mod._config_tokens({
        "name": actlib.read_config().get("name", root.name), "owner": actlib.read_config().get("owner", ""),
        "language": actlib.read_config().get("language", "en"), "stack": actlib.read_config().get("stack", ""),
        "lint_cmd": "", "typecheck_cmd": "", "test_cmd": "", "tools": tools,
        "mode": actlib.read_config().get("mode", "solo"),
        # init.py's ProjectConfig gained "feedback_mode" (T58); only the <feedback-mode> token uses it.
        "feedback_mode": actlib.read_config().get("feedback", "off"),
    })
    cache = actlib.read_cache()
    for path in to_bridge:
        key, spec = bridges[path]
        if spec["kind"] == "verbatim":
            dest = root / path
            dest.unlink()
            init_mod._write_text_file(root / ".act" / "bridges" / key, dest, cfg_tokens, False, root)
            cache["generated"][path] = actlib.sha256_file(dest)
            _git(root, "add", "--", path)
        bridged.append(path)
    if bridged:
        actlib.write_cache({"generated": cache["generated"]})
    for path in to_remove:
        if is_tracked(root, path):
            _git(root, "rm", "-r", "-q", "--", path)
        if os.path.lexists(root / path):
            _remove_path(root / path)
    # After the removals: an own unit may carry the name its old tool folder had.
    unit_messages = bridge_own_units(root, units) if units else []
    for message in unit_messages:
        print(f"[adopt] {message}")

    doctor = run_doctor(root)
    refs = find_references(root, [*moved, *to_remove, *state.get("removed_at_apply", [])])
    state.update({"bridged": bridged, "removed_at_finish": to_remove,
                  "own_units": [f"{area}/{name}" for area, name in units]})
    acc, ok = accounting(root, rows, state, "finish")
    report = write_report(root, rows, state, doctor, refs, acc)
    state.update({"state": "finished", "finished": datetime.now().isoformat(timespec="seconds"),
                  "report": report.relative_to(root).as_posix(), "doctor_exit": doctor[0]})
    _write_json(state_path, state)
    print(f"[adopt] doctor.py: exit {doctor[0]}, {len(doctor[1])} finding(s)")
    for line in doctor[1][:10]:
        print(f"    {line}")
    print(f"[adopt] references in docs/project/ to moved/removed paths: {len(refs)}")
    for line in refs[:20]:
        print(f"    {line}")
    print(f"[adopt] report: {report.relative_to(root).as_posix()}")
    print("[adopt] accounting after --finish:")
    print("\n".join(acc))
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

EPILOG = f"""\
TABLE <target>/{ADOPT_DIR}/table.json — {{"rows": [...]}}, exactly one row per scan.json row:
  path       as in scan.json          class   as in scan.json (must match)
  action     adopt | legacy | keep | delete
  target     adopt only: destination path or list of paths (filled by the content step)
  done       adopt only: true once the content is at its target (required for --finish)
  confirmed  true: the owner confirmed this one row (see below)      note  free text

ALLOWED ACTIONS PER CLASS
  log           legacy, keep                 ai-machinery  adopt, delete, keep
  ai-config     adopt, legacy, keep, delete  work          adopt, legacy, keep, delete
  project-doc   adopt, legacy, keep; delete only with confirmed
  unknown       keep; adopt/legacy/delete only with confirmed

REFUSED (whole run, with a list) on: a path that is not plain relative posix or not on disk; a
path not in scan.json, or a scan.json row without a table row; a class differing from scan.json;
a disallowed action; a row whose note (scan's or table's) says "never bridge"/"git-ignored/local"
with action delete or legacy, or adopt into a bridge file; any non-keep action on a link or below
one; any non-keep action below a source/test/content tree (see below) without confirmed; a unit
folder holding untracked or git-ignored files that would be moved or removed, without confirmed
(with it, those files go to {RESCUED_ROOT}/ first); an adopt target equal to or below its own
source (unless the source moves before init) or below any path that is deleted, archived, removed
or bridged; a path segment ending in a dot or space; paths are compared case-insensitively where
the file system is; a scan.json that no longer matches a fresh scan (--apply).
Source/test/content trees (first path segment): {', '.join(sorted(CONTENT_TREES))}, test*.

--apply: clean tree (untracked only under .act-local/), new branch {BRANCH} (an existing branch
  refuses; a recorded state prints it and exits 0), `legacy` rows moved byte-identical to
  {LEGACY_ROOT}/<old path> (sha256 before = after). An old skill/agent carrying the
  name of a template unit, or a file at a place init.py writes itself (docs/ai/ skeleton,
  docs/ai/rules.md, docs/project/coding_rules.md), moves there too unless it is a delete row
  (removed) — a kept file at such a place stays and init leaves it. Then init.py --target
  --non-interactive --no-commit (detected at runtime; only an init.py without that flag makes its
  own first commit instead); existing CLAUDE.md/AGENTS.md stay until --finish.
--finish: every adopt row done with its target on disk; adopted ai-config files that init has a
  bridge for become that bridge (protected rows stay as they are), other adopted sources and
  delete rows removed (git rm); an adopt target docs/ai/local/skills/<name>/... or
  docs/ai/local/agents/<name>.md is an own unit and gets its tool copies/bridge like
  act-load-settings writes them (skill copies recorded in .act-lock.json § copies) — refused if
  <name> is a template unit's (that would be an override; a row note "override" leaves it to the
  template's copy mechanism); doctor.py, docs/project/ references to moved/removed paths,
  report docs/ai/inbox/<date>-adoption-report.md. A second --finish says "already finished".
  An adopt target that still has the content it had right after --apply is refused ("content not
  adopted?").
--apply refuses a detached HEAD. It backs up .claude/settings.json (init.py merges hooks into it).
--abort: the way back after --apply or a stopped --apply, resumable (state.json is rewritten after
  every step). Refused while {BRANCH} carries a commit other than init.py's, and while work was
  done since --apply — a changed file init.py created, an uncommitted edit to a tracked file, a
  new file where a moved unit returns — unless --force, which first copies those files to
  {ABORTED_ROOT}/<path> and lists them. Then: removes the files init.py created that are
  unchanged (or saved), puts moved units back only from a legacy copy that still holds the moved
  content, puts rescued files back, checks out the base branch, restores the settings backup,
  deletes {BRANCH} and the state. New files it did not create are left in place and listed.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adopt.py",
        description="Carry out an approved adoption table: move legacy sources, install the template, "
                    "then bridge/remove adopted sources. Never commits.",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--target", metavar="DIR", required=True, help="the project to adopt (a git repository)")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--apply", action="store_true", help="branch, legacy moves, init.py --target")
    mode.add_argument("--finish", action="store_true", help="bridges, removals, doctor, inbox report")
    mode.add_argument("--abort", action="store_true", help="the way back after --apply: undo it, delete the branch")
    parser.add_argument("--plan", action="store_true", help="validate and show what would happen, change nothing")
    parser.add_argument("--force", action="store_true",
                        help=f"with --abort: copy work done since --apply to {ABORTED_ROOT}/ first, then abort")
    return parser


def main(argv: list) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    root = Path(args.target).expanduser().resolve()
    if not root.is_dir():
        print(f"adopt.py: target is not a directory: {root}", file=sys.stderr)
        return 2
    if root == TEMPLATE_ACT.parent.resolve():
        print("adopt.py: the target is this template checkout itself", file=sys.stderr)
        return 2
    try:
        if args.abort:
            return cmd_abort(root, args.plan, args.force)
        return cmd_apply(root, args.plan) if args.apply else cmd_finish(root, args.plan)
    except Refused as exc:
        print("refused:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"adopt.py: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        # A file held open or a permission problem mid-way: state.json records what is done, so
        # the same command continues from there.
        print(f"adopt.py: stopped: {exc} — state kept, run the same command again to continue", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
