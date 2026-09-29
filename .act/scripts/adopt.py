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
#                      docs/ai/work/archive/legacy/<old path>, its AI-tool config path segments
#                      renamed first (B128, legacy_rel()) so no tool reads the archived copy as
#                      its own configuration, then run init.py --target.
#            --finish  after the content step (skill act-adopt / T52) marked every `adopt` row
#                      done: turn adopted ai-config files into bridges, remove adopted sources
#                      and `delete` rows, bridge adopted own skills/roles (targets under
#                      docs/ai/local/skills|agents/) the way act-load-settings does, drop
#                      .claude/settings.json entries that run a removed script, remove the
#                      act:default mark from adopt targets (docs/ai/config.md keeps it: values
#                      only, its text stays scaffold), bend dead references in docs/project/
#                      and docs/README.md to the new place (link targets only), write
#                      docs/ai/work/archive/legacy/_act-renames.md (old path -> renamed path table;
#                      not "README.md", which a `legacy` row for a project's own root README.md
#                      could land at) where B128 renamed anything, run doctor.py, write one inbox
#                      report.
#          Never commits (moves and removals are staged by path only). Stdlib only.
#
# Usage:
#   python .act/scripts/adopt.py --target <project> --apply [--plan] [--language-docs <code>] [--language-chat <code|auto>]
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
import posixpath
import re
import shlex
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
# Not "README.md": a `legacy` row for a root-level README.md (act-adopt/SKILL.md step 6 proposes
# `keep` for a project-doc README.md, but a table may still choose `legacy`) would land at exactly
# that path and get silently overwritten by write_legacy_readme() (B128 follow-up) — a name the
# rename mapping can never itself produce protects it (see the duplicate-destination and
# LEGACY_README checks in validate()).
LEGACY_README = f"{LEGACY_ROOT}/_act-renames.md"

# B128: an AI tool reads a `.claude/`, `.codex/`, ... folder or a `CLAUDE.md`/`AGENTS.md`/`GEMINI.md`
# file as its own configuration wherever it sits — including nested below docs/ai/work/archive/legacy/,
# and including nested anywhere inside a directory a legacy move takes wholesale (e.g. an old
# `app/.claude/` inside a moved `app/`). Every path a legacy move puts there goes through legacy_rel()
# first, so the archived copy never loads as configuration again — applied to every segment, at any
# depth (everywhere but under ".github", which has its own two rules below).
LEGACY_DIR_RENAME = {".claude": "_claude", ".codex": "_codex", ".gemini": "_gemini",
                     ".cursor": "_cursor", ".agents": "_agents"}
# Files renamed wherever they sit, any depth, by appending ".legacy" to the name.
LEGACY_FILE_RENAME = ("CLAUDE.md", "AGENTS.md", "GEMINI.md", "CLAUDE.local.md")


def legacy_rel(path: str) -> str:
    """`path` (a plain relative posix path, as validate() requires) with every tool-config segment
    renamed, at any depth, so no AI tool reads the legacy copy as its own configuration (B128): every
    segment named ``.claude``/``.codex``/``.gemini``/``.cursor``/``.agents`` -> ``_claude``/…,
    wherever it sits (a nested ``app/.claude/`` renamed the same as a top-level one); every
    ``.github`` segment's own ``agents``/``prompts`` child -> ``_agents``/``_prompts`` (its own other
    content, e.g. workflows/, is untouched) and its ``copilot-instructions.md`` child exactly ->
    ``copilot-instructions.md.legacy``; a file named ``CLAUDE.md``/``AGENTS.md``/``GEMINI.md``/
    ``CLAUDE.local.md`` at any depth gets ``.legacy`` appended to its name. The one function every
    legacy-destination computation in this script goes through — never build
    f"{LEGACY_ROOT}/{path}" directly. Renames only the path string itself; for a directory moved
    wholesale, the files nested inside still need moving to match (see legacy_move())."""
    parts = list(PurePosixPath(path).parts)
    if not parts:
        return path
    out = []
    i, n = 0, len(parts)
    while i < n:
        part = parts[i]
        if part == ".github" and i + 1 < n and parts[i + 1] == "copilot-instructions.md" and i + 2 == n:
            out.append(part)
            out.append("copilot-instructions.md.legacy")
            i += 2
            continue
        if part == ".github" and i + 1 < n and parts[i + 1] in ("agents", "prompts"):
            out.append(part)
            out.append("_" + parts[i + 1])
            i += 2
            continue
        if part in LEGACY_DIR_RENAME:
            out.append(LEGACY_DIR_RENAME[part])
            i += 1
            continue
        if part in LEGACY_FILE_RENAME:
            out.append(part + ".legacy")
            i += 1
            continue
        out.append(part)
        i += 1
    return "/".join(out)


def legacy_dest(path: str) -> str:
    """Where `path` lands under the legacy archive, tool-config segments renamed (legacy_rel())."""
    return f"{LEGACY_ROOT}/{legacy_rel(path)}"
BACKUP_ROOT = ".act-local/adopt/backup"    # files init.py merges into, restored by --abort
BACKED_UP = (".claude/settings.json",)
ACTIONS = ("adopt", "legacy", "keep", "delete")

# Actions each scan class may take. "unknown" may take any, but a non-keep action needs the row's
# own `confirmed: true`; so does `delete` on a project-doc row (CONFIRM_NEEDED below).
ALLOWED_ACTIONS: dict = {
    "ai-config": {"adopt", "keep", "legacy", "delete"},
    # legacy (T65, Q93 open): an old skill/agent/script kept byte-identical in the archive, e.g. on a
    # name collision with a template unit — as scan and skill propose it.
    "ai-machinery": {"adopt", "legacy", "delete", "keep"},
    "work": {"adopt", "legacy", "keep", "delete"},
    "log": {"legacy", "keep"},
    "project-doc": {"adopt", "legacy", "keep", "delete"},
    # A part of the predecessor template (adopt_scan.py: in its base_commit tree or a known part).
    "predecessor": set(ACTIONS),
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
    # passes Windows' 260-character limit sooner than the original did. Only for adopt's own calls
    # — the owner's later `git commit` does not get it, hence long_legacy_paths() before --apply.
    # --literal-pathspecs: a path is a path, never a pattern — `notes[1].md` must not match
    # `notes1.md` in `ls-files`, `add` or `rm` (every git call of this script goes through here).
    result = subprocess.run(["git", "--literal-pathspecs", "-c", "core.quotePath=false",
                             "-c", "core.longpaths=true", "-C", str(root), *args],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and result.returncode != 0:
        shown = " ".join(args[:4]) + (" …" if len(args) > 4 else "")
        raise RuntimeError(f"git {shown} failed (exit {result.returncode}): {result.stderr.strip()[:400]}")
    return result


# Windows' MAX_PATH: 260 characters including the terminating NUL, so a path of 260 or more
# characters fails in any git call without core.longpaths ("Filename too long"); a directory
# fails from 248 on (room for an 8.3 name), so a later checkout or clone drops the files in it.
WIN_MAX_PATH = 260
WIN_MAX_DIR = 248


def _win_len(path: str) -> int:
    """Length as Windows counts it: UTF-16 code units (a character outside the BMP counts twice)."""
    return len(path.encode("utf-16-le")) // 2


def repo_longpaths(root: Path) -> bool:
    """core.longpaths as the repository's own config says (local, global, system) — without the
    `-c` override _git() adds, because the owner's later commits run without it."""
    result = subprocess.run(["git", "-C", str(root), "config", "--type=bool", "--get", "core.longpaths"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    return result.returncode == 0 and result.stdout.strip() == "true"


def long_legacy_paths(root: Path, moves: list) -> list:
    """(length, absolute path) of every file a move would put at or above WIN_MAX_PATH, or into a
    folder at or above WIN_MAX_DIR (then the folder is named, with a trailing backslash), longest
    first. Empty outside Windows and where the repository sets core.longpaths itself."""
    if os.name != "nt" or repo_longpaths(root):
        return []
    found = {}
    for path, dest, _action, _colliding in moves:
        for rel in _files_below(root / path):
            full = (f"{root}\\{dest}" + (f"/{rel}" if rel else "")).replace("/", "\\")
            folder = full.rsplit("\\", 1)[0]
            if _win_len(full) >= WIN_MAX_PATH:
                found[full] = _win_len(full)
            elif _win_len(folder) >= WIN_MAX_DIR:
                found[folder + "\\"] = _win_len(folder)
    return sorted(((length, full) for full, length in found.items()), reverse=True)


def index_files(root: Path, base: str) -> set:
    """Every path in the git index at or below `base` (one call)."""
    out = _git(root, "ls-files", "-z", "--cached", "--", base).stdout
    return {p for p in out.split("\0") if p}


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


def _prune_empty_below(base: Path) -> None:
    """Remove directories left empty under `base` (base itself included if it ends up empty),
    deepest first."""
    if not base.is_dir():
        return
    for dirpath, _dirs, _files in list(os.walk(base, topdown=False)):
        current = Path(dirpath)
        try:
            if not any(current.iterdir()):
                current.rmdir()
        except OSError:
            pass


def legacy_rename_nested(dest: Path) -> dict:
    """After a whole directory landed at `dest` byte-identical (a plain move preserves every
    internal name), rename every file inside whose relative path legacy_rel() would change (B128,
    any depth — legacy_rel() only rewrites the path string, this makes the file system match it):
    move each such file to its renamed relative location under `dest`, then remove directories left
    empty by that (e.g. a nested `.claude/` once every file below it moved to `_claude/`). Returns
    old-relative -> new-relative for every file actually moved (empty if legacy_rel() changed
    nothing below `dest`) — --apply records it so --abort can reverse it before moving the unit
    back. `dest` itself (the row's own top-level rename) is not touched here, only what is below
    it — legacy_dest() already renamed that part."""
    if not dest.is_dir():
        return {}
    renamed = {}
    for rel in sorted(_files_below(dest)):
        new_rel = legacy_rel(rel)
        if new_rel == rel:
            continue
        src, dst = dest / rel, dest / new_rel
        if dst.exists():
            raise RuntimeError(f"legacy rename destination already exists: {dest}/{new_rel}")
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)
        renamed[rel] = new_rel
    if renamed:
        _prune_empty_below(dest)
    return renamed


def legacy_rename_nested_undo(dest: Path, renamed: dict) -> None:
    """Reverse legacy_rename_nested(): move every renamed file back to its original relative
    place under `dest`, before the unit as a whole is moved back out of the legacy archive."""
    for rel, new_rel in renamed.items():
        src, dst = dest / new_rel, dest / rel
        if not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)
    if renamed:
        _prune_empty_below(dest)


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
        out = _git(root, "ls-files", "-o", *extra, "--exclude-standard", "--", rel).stdout
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
        elif cls == "predecessor" and action == "delete" and scan_row.get("origin") != "template only" \
                and not confirmed:
            problems.append(f"{where}: predecessor row not \"template only\" (origin {scan_row.get('origin')!r}) "
                            "with action 'delete' needs \"confirmed\": true")
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
    problems += legacy_destination_problems(rows, moved_first)
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


def legacy_moves(rows: list, moved_first) -> list:
    """(path, dest) for every row this adoption's --apply moves into the legacy archive: every
    `legacy` row, and every `adopt`/`keep` row whose source collides with what init.py writes
    itself (moved_first — mirrors cmd_apply's own `moves` list, built the same way)."""
    out = []
    for row in rows:
        path, action = row.get("path"), row.get("action")
        if not isinstance(path, str) or not _is_safe_rel(path):
            continue
        if action == "legacy" or (action in ("adopt", "keep") and moved_first(path)):
            out.append((path, legacy_dest(path)))
    return out


def legacy_destination_problems(rows: list, moved_first) -> list:
    """Two checks on where --apply's legacy moves would land, run in validate() so a --plan (and
    thus every real --apply, which always validates first) refuses them before anything moves:
    a destination that collides with LEGACY_README (reserved for the rename table
    write_legacy_readme() writes — B128 follow-up), and two sources landing on the same
    destination (compared case-insensitively, as the file system may), where the second
    os.replace() would otherwise silently overwrite the first."""
    problems = []
    seen: dict = {}
    for path, dest in legacy_moves(rows, moved_first):
        if dest == LEGACY_README:
            problems.append(f"{path!r}: would move to {dest!r}, reserved for the rename table "
                            f"({LEGACY_README})")
        key = _key(dest)
        if key in seen and seen[key] != path:
            problems.append(f"{path!r} and {seen[key]!r} both land at {dest!r} in the legacy "
                            "archive (paths compared case-insensitively where the file system is)")
        else:
            seen[key] = path
    return problems


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

def accounting(root: Path, rows: list, state: dict, phase: str, scan_rows: Optional[dict] = None) -> tuple:
    """(lines, ok): one line per table row, where its content is now; ok is False if any row is
    neither at its target, in legacy with matching checksums, deleted (listed) nor kept.
    `scan_rows` (path -> scan.json row): only "finish" reaches the adopt-source wording that
    needs it, "apply" never does (adopt rows return before that point)."""
    scan_rows = scan_rows or {}
    sums = _read_json(root / ADOPT_DIR / "legacy-checksums.json") or {}
    moved = state.get("moved", {})
    removed_early = set(state.get("removed_at_apply", []))
    bridged = set(state.get("bridged", []))
    # A legacy copy counts only if it is on disk AND in the git index: a copy git could not stage
    # (a path too long, an ignore rule) is lost with the next commit that records the removal.
    indexed = index_files(root, LEGACY_ROOT) if moved else set()
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
            unstaged = [f"{moved[path]}/{rel}" if rel else moved[path] for rel in now
                        if "__pycache__/" not in rel and not rel.endswith((".pyc", ".pyo"))]
            unstaged = [p for p in unstaged if p not in indexed]
            label = "in legacy" if action == "legacy" else f"in legacy ({action}, moved before init)"
            status = f"{label} (checksum {'ok' if good else 'MISMATCH'}"
            if unstaged:
                status += f", NOT IN GIT INDEX: {len(unstaged)} file(s), first {unstaged[0]}"
            if action != "adopt":
                emit(path, f"{status}) -> {moved[path]}", good and not unstaged)
                continue
            # An adopt row moved before init (init writes at its place): counted as adopted, the
            # original's legacy copy checked all the same.
            targets = _targets(row)
            how = "into itself" if path in targets else "original moved before init"
            original = f"{how}; original in legacy, checksum {'ok' if good else 'MISMATCH'}" + (
                f", NOT IN GIT INDEX: {len(unstaged)} file(s), first {unstaged[0]}" if unstaged else "")
            if phase == "apply":
                emit(path, f"adoption pending ({original} -> {moved[path]})", good and not unstaged)
                continue
            missing = [t for t in targets if not os.path.lexists(root / t)]
            if not targets or missing:
                emit(path, f"at target: MISSING {', '.join(missing) or '(no target)'} ({original})", False)
                continue
            emit(path, f"at target: {', '.join(targets)} ({original} -> {moved[path]})", good and not unstaged)
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
            if path in bridged:
                source = "bridge"
            elif not os.path.lexists(root / path):
                source = "source removed"
            elif _is_protected(_note_of(row, (scan_rows or {}).get(path))):
                source = "source stays (protected)"
            elif any(PurePosixPath(t).parts[:4] in (OWN_SKILLS, OWN_AGENTS) for t in targets):
                # An own skill/agent: --finish removes it (to_remove), the tool copy is written
                # separately (bridge_own_units) — "protected" would claim a note nobody wrote
                # (B118 #14, cosmetic: this branch means the removal has not run yet or failed).
                source = "source stays (own unit — not yet removed)"
            else:
                source = "source stays (unexpected, not a protected note)"
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
    out = _git(root, "ls-files", "-o").stdout
    return {line.strip() for line in out.splitlines() if line.strip()}


def ignored_files(root: Path) -> set:
    """Every untracked file a .gitignore rule covers — never staged, never in a commit list."""
    out = _git(root, "ls-files", "-o", "-i", "--exclude-standard").stdout
    return {line.strip() for line in out.splitlines() if line.strip()}


def _hash_path(path: Path) -> Optional[str]:
    if not os.path.lexists(path):
        return None
    files = _files_below(path)
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode("utf-8")).hexdigest()


def way_back(root: Path) -> str:
    return f"python {Path(__file__).name} --target {root} --abort"


def cmd_apply(root: Path, plan: bool, language_docs: Optional[str] = None,
              language_chat: Optional[str] = None) -> int:
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
            moves.append((path, legacy_dest(path), action, colliding))
        elif colliding and action == "delete":
            early_deletes.append(path)
    clash = [dest for _p, dest, _a, _c in moves if os.path.lexists(root / dest)]
    if clash:
        raise Refused([f"legacy destination already exists: {dest}" for dest in clash])
    too_long = long_legacy_paths(root, moves)
    if too_long:
        raise Refused([f"{len(too_long)} legacy path(s) would reach {WIN_MAX_PATH} characters or more (a folder: "
                       f"{WIN_MAX_DIR}; the old path plus {len(LEGACY_ROOT) + 1}), and core.longpaths is not set: git fails "
                       f"on them (\"Filename too long\") and the next commit would drop the copies. Run "
                       f"`git -C {root} config core.longpaths true`, then --apply again",
                       *[f"{length} characters: {full}" for length, full in too_long[:5]]])
    to_rescue = {path: local_files(root, path) for path in [*(m[0] for m in moves), *early_deletes]}
    to_rescue = {path: files for path, files in to_rescue.items() if files}

    no_commit = init_supports_no_commit()
    # --language-docs/--language-chat are passed on only when given (B148 1): the skill fixes the
    # language before --apply (from the sighting's language hint, else with the owner), so init.py
    # writes docs/ai/config.md and its own todos in it right away. Without them init.py starts
    # with its English default, and adopt_config.py (step 5) sets `language-docs` afterwards from
    # an old AI-CONFIG.md/template.json if there is one — a project without either stays English.
    init_cmd = [sys.executable, str(SCRIPTS_DIR / "init.py"), "--target", str(root), "--non-interactive"]
    if language_docs:
        init_cmd += ["--language-docs", language_docs]
    if language_chat:
        init_cmd += ["--language-chat", language_chat]
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
        # What --apply was told explicitly: adopt_config.py treats these keys as project values (B148 1).
        "languages": {key: value for key, value in (("language-docs", language_docs),
                                                    ("language-chat", language_chat)) if value},
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
            renamed = legacy_rename_nested(root / dest)  # B128, nested: rename what a plain move left as-is
            if renamed:
                new_state.setdefault("moved_renames", {})[path] = renamed
            new_state["moved"][path] = dest
            _write_json(state_path, new_state)
            after = _files_below(root / dest)
            checksums[path] = {"legacy": dest, "files": after}
            expected = {renamed.get(rel, rel): digest for rel, digest in before.items()}
            if after != expected:
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
    new = {f for f in untracked_files(root) - before_untracked if not f.startswith(own)}
    ignored = new & ignored_files(root)
    # `created` is what a commit takes (never a git-ignored file: `git add` refuses those);
    # `created_ignored` only tells --abort what else init.py left behind (byte code, .act-local/).
    new_state["created"] = sorted(new - ignored)
    new_state["created_hashes"] = {f: _sha256(root / f) for f in new_state["created"] if (root / f).is_file()}
    new_state["created_ignored"] = {f: _sha256(root / f) for f in sorted(ignored) if (root / f).is_file()}
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
    legacy_dests = list(moved.values())
    stage_error = None
    try:
        for start in range(0, len(staged), 50):
            _git(root, "add", "-A", "--", *staged[start:start + 50])
        # -f: a legacy copy is taken as it is, even if a .gitignore rule matches its name (ai.log);
        # byte code inside a moved unit stays out (regenerable, never staged at the old place).
        for start in range(0, len(legacy_dests), 50):
            _git(root, "add", "-A", "-f", "--", *legacy_dests[start:start + 50])
        byte_code = sorted(f for f in index_files(root, LEGACY_ROOT)
                           if "__pycache__/" in f or f.endswith((".pyc", ".pyo")))
        for start in range(0, len(byte_code), 50):
            _git(root, "rm", "-q", "--cached", "--", *byte_code[start:start + 50])
    except RuntimeError as exc:
        stage_error = str(exc)
        new_state.update({"state": "stage-failed", "error": f"staging the moves failed: {exc}"})
    # What --apply leaves changed in tracked files: --abort treats anything beyond this as work.
    new_state["dirty_after_apply"] = tracked_changes(root)
    # A backed-up file (.claude/settings.json) is git-ignored: tracked_changes() never sees it.
    # Its hash right here, once init.py is done, is --abort's own baseline for "changed since
    # --apply" (B118 #1) — the pre-init backup above is only what gets restored, not that baseline.
    new_state["backup_after_apply"] = {rel: _sha256(root / rel) for rel in BACKED_UP if (root / rel).is_file()}
    _write_json(state_path, new_state)
    if stage_error:
        # No accounting: a move git could not stage is lost with the next commit of the removal.
        print(f"[adopt] ERROR: git could not stage the moves — stopped, nothing verified: {stage_error}",
              file=sys.stderr)
        print(f"[adopt] fix the cause git names above (for a path too long: git -C {root} config "
              f"core.longpaths true), then take the way back and start again: {way_back(root)}", file=sys.stderr)
        return 1
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
        # Git-ignored files init.py left (byte code is regenerable, anything else only unchanged).
        ignored = state.get("created_ignored", {})
        for rel, expected in ignored.items():
            path = root / rel
            if not _is_safe_rel(rel) or not path.is_file():
                continue
            if "__pycache__/" in rel or rel.endswith((".pyc", ".pyo")) or _sha256(path) == expected:
                path.unlink()
        _prune_empty_dirs(root, [*created, *ignored])
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
        legacy_rename_nested_undo(root / dest, state.get("moved_renames", {}).get(old, {}))
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

    kept_changed = []
    for original, saved_at in state.get("backup", {}).items():
        if (root / saved_at).is_file():
            baseline = state.get("backup_after_apply", {}).get(original)
            # A tracked file is already handled above ("checkout"): it is back at its pre-apply
            # committed content there, which content_changes()/--force cover if it was edited.
            # Only a git-ignored one slips past that (B118 #1) — is_tracked() here, not before the
            # checkout above, so a file the project untracks only on this branch still counts.
            if (baseline is not None and (root / original).is_file() and not is_tracked(root, original)
                    and _sha256(root / original) != baseline):
                # Changed during the content step, nothing that said so on a plain overwrite —
                # keep a copy, warn, but do not refuse the abort over it.
                dest = root / ABORTED_ROOT / original
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / original, dest)
                kept_changed.append(original)
            (root / original).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(root / saved_at, root / original)
            (root / saved_at).unlink()
            _prune_empty_dirs(root, [saved_at])
    if kept_changed:
        print(f"[adopt] changed since --apply (git-ignored, not tracked), kept as a copy under "
              f"{ABORTED_ROOT}/, restored the pre-apply original instead: {', '.join(kept_changed)}")

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

# A whole word, not negated (B118 #3): "no override"/"not an override" must not count as the
# note meaning an override, only "override" (or "an override", "override of X", ...) does.
OVERRIDE_RE = re.compile(r"(?<!no )(?<!not )(?<!not an )(?<!kein )(?<!keine )(?<!keinen )(?<!ohne )(?<!nicht als )\boverrides?\b", re.IGNORECASE)


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
            if clash and OVERRIDE_RE.search(row.get("note") or ""):
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


REFS_IN_REPORT = 50  # more references than this: the report names REFS_FILE instead of listing them
REFS_FILE = f"{ADOPT_DIR}/references.txt"            # the full list, written by every --finish
REFS_PLAN_FILE = f"{ADOPT_DIR}/references.plan.txt"  # the same list, written by --finish --plan
REFS_SCOPE = "docs/project/ and docs/README.md"     # where references are bent
REFS_SCOPE_DE = "docs/project/ und docs/README.md"  # the same, for a German report (B148 2)


DOC_SUFFIXES = {".md", ".txt", ".rst", ".adoc"}
LINK_RE = re.compile(r"(\]\()([^)\s]+)(\))")            # a Markdown link target: ](target)
REFDEF_RE = re.compile(r"^( {0,3}\[[^\]]+\]:[ \t]*<?)([^\s<>]+)()")  # a reference definition: [x]: target
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")          # a fence line: its character and length count
CODE_SPAN_RE = re.compile(r"(`+)(.+?)(?<!`)\1(?!`)")     # an inline code span: a run of N backticks, closed by N
INDENTED_RE = re.compile(r"^(?: {4}|\t)")               # indented code (or a deeply nested list: left as it is)
SUCCESSOR_SKIP = ("docs/ai/inbox/", "docs/ai/proposals/")  # side outputs of an adopt row, never its successor
AMBIGUOUS = "\0ambiguous"  # successors(): an adopt row naming more than one main target


def successors(rows: list, state: dict, gone: list) -> dict:
    """gone source -> its new place (legacy copy, or the one successor an adopt row names); None
    where there is none (a delete row), AMBIGUOUS where an adopt row names several targets."""
    moved, by_path, out = state.get("moved", {}), {r["path"]: r for r in rows}, {}
    for path in dict.fromkeys(gone):
        row = by_path.get(path)
        if path in moved:
            out[path] = moved[path]
        elif row and row.get("action") == "adopt":
            main = [t for t in _targets(row) if not t.startswith(SUCCESSOR_SKIP)]
            out[path] = main[0] if len(main) == 1 else AMBIGUOUS
        else:
            out[path] = None
    return out


def emptied_folders(root: Path, gone: list, pending: list, succ: dict) -> dict:
    """Folders above a gone source that hold no file once --finish is done (`pending`: sources it
    still removes) -> their legacy folder if there is one, else None — a reference to such a
    folder is dead as well (T65: docs/project/coding_rules.d/ with every file a delete row)."""
    out, full = {}, set()
    for path in dict.fromkeys(gone):
        folder = posixpath.dirname(path)
        while folder and folder not in out and folder not in full:
            base = root / folder
            files = (f for f in (base.rglob("*") if base.is_dir() else []) if f.is_file())
            if any(not any(_at_or_below(f.relative_to(root).as_posix(), p) for p in pending) for f in files):
                full.add(folder)
                break
            if folder not in succ:
                legacy = legacy_dest(folder)
                out[folder] = legacy if (root / legacy).is_dir() else None
            folder = posixpath.dirname(folder)
    return out


def _tree_paths(root: Path, commit: str) -> frozenset:
    """Every file path (recursively) git tracked at `commit` — the tree before the adoption
    started, so _new_place() can tell a reference that was already broken there (B118 #20) from
    one the adoption itself left without a successor."""
    result = _git(root, "ls-tree", "-r", "--name-only", commit, check=False)
    return frozenset(line for line in result.stdout.split("\n") if line) if result.returncode == 0 else frozenset()


def _existed_before(before: frozenset, rel: str) -> bool:
    return rel in before or any(p.startswith(rel + "/") for p in before)


def _new_place(root: Path, rel: str, succ: dict, before: frozenset = frozenset()) -> tuple:
    """(new path or None, why it stays or None, sources `rel` is or lies below). A new place that
    does not exist (a folder adopted into one file: its pages have no place of their own) stays.
    `before`: _tree_paths() at the commit --apply started from — a `rel` missing there already
    was dead before the adoption touched anything (B118 #20), not a successor the adoption owes."""
    hits = [(src, new) for src, new in succ.items() if rel == src or rel.startswith(src + "/")]
    sources = [src for src, _new in hits]
    if not hits:
        return None, None, sources
    # All hits are `rel` or folders above it: the most specific one names the new place (a file
    # row below a folder that the adoption emptied).
    src, new = max(hits, key=lambda hit: len(hit[0]))
    if new is None:
        return None, "no successor", sources
    if new == AMBIGUOUS:
        return None, "ambiguous: several targets", sources
    new += rel[len(src):]
    if not os.path.lexists(root / new):
        if before and not _existed_before(before, rel):
            return None, "already dead before", sources
        return None, f"new place missing: {new}", sources
    return new, None, sources


def _mention_re(path: str):
    return re.compile(r"(?<![\w./-])" + re.escape(path) + r"(?![\w-]|\.\w)")


def _reference_files(root: Path, exclude: frozenset = frozenset()) -> list:
    """The files whose references --finish bends (REFS_SCOPE): docs/README.md and every doc file
    under docs/project/ — except `exclude` (B118 #19: the same set --finish itself is about to
    remove, so --plan and the real run scan the same files and count the same)."""
    def kept(rel: str) -> bool:
        return rel not in exclude and not any(rel == e or rel.startswith(e + "/") for e in exclude)

    index, base_dir = root / "docs" / "README.md", root / "docs" / "project"
    files = [index] if index.is_file() and kept("docs/README.md") else []
    if base_dir.is_dir():
        files += [f for f in sorted(base_dir.rglob("*")) if f.is_file() and f.suffix.lower() in DOC_SUFFIXES
                  and kept(f.relative_to(root).as_posix())]
    return files


def _span_readings(root: Path, content: str, folder: str, succ: dict, before: frozenset = frozenset()) -> tuple:
    """(readings, sources) for a path alone in backticks — text, never changed (Q91 a): read
    relative to the file's folder and relative to the root (spelled ./ or ../: the folder only; a
    leading /: the root only). `readings` describes every reading that meets a gone source with
    its new place or why there is none ('' if none meets one)."""
    readings = []
    if not content.startswith("/"):
        readings.append(("relative to the file", posixpath.normpath(posixpath.join(folder, content))))
    if not content.startswith(("./", "../")):
        readings.append(("relative to the root", posixpath.normpath(content.lstrip("/"))))
    found, sources = [], []
    for label, reading in dict.fromkeys(readings):
        if reading == "." or reading.startswith("../"):
            continue  # outside the repository
        new, why, hit = _new_place(root, reading, succ, before)
        if hit:
            sources += hit
            found.append(f"{label}: {reading} -> {new}" if new else f"{label}: {reading}, {why}")
    return "; ".join(found), sources


def rewrite_references(root: Path, succ: dict, plan: bool, exclude: frozenset = frozenset(),
                       before: frozenset = frozenset()) -> tuple:
    """Dead references in REFS_SCOPE to gone sources (`succ`), bent to the new place — the link
    target only (Q91 a): the target of a Markdown link `](…)` or of a reference definition
    `[x]: …` outside code, resolved against the file's folder (a leading /: the root), written
    back the same way, anchor kept, only where the new place exists. Nothing else changes: a path
    in backticks is text and only listed ("mention in text — not changed", both readings, see
    _span_readings); fenced blocks (character and length tracked) and indented lines are never
    touched. Returns (changes, left): '<file>:<line>: <old> -> <new>' each, and
    '<file>:<line>: <path> … (<why>)' for every reference left as it is. With `plan`, nothing is
    written. `exclude`: files --finish itself is about to remove, scanned by neither --plan nor
    the real run (B118 #19). `before`: see _new_place() (B118 #20)."""
    changes, left = [], []
    if not succ:
        return changes, left
    mentions = {src: _mention_re(src) for src in succ}
    for file in _reference_files(root, exclude):
        try:
            text = file.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # never rewrite a file in another encoding
        rel_file = file.relative_to(root).as_posix()
        folder = posixpath.dirname(rel_file)
        lines, fence, edited = text.splitlines(keepends=True), None, False
        for number, line in enumerate(lines, 1):
            body = line.lstrip("﻿") if number == 1 else line
            marker = FENCE_RE.match(body)
            if fence is None and marker:
                fence = (marker.group(1)[0], len(marker.group(1)))
                in_code = True
            elif fence is not None:
                in_code = True
                closing = body.strip()
                if marker and closing == marker.group(1) and closing[0] == fence[0] and len(closing) >= fence[1]:
                    fence = None
            else:
                in_code = bool(INDENTED_RE.match(body))
            if in_code:
                left += [f"{rel_file}:{number}: {src} (in a code block)" for src, rx in mentions.items() if rx.search(line)]
                continue
            handled = set()

            def link(match):
                target = match.group(2)
                path, sep, anchor = target.partition("#")
                if not path or "://" in path or path.startswith("mailto:"):
                    return match.group(0)
                resolved = path.lstrip("/") if path.startswith("/") else posixpath.normpath(posixpath.join(folder, path))
                new, why, sources = _new_place(root, resolved, succ, before)
                handled.update(sources)
                if new is None:
                    if why:
                        left.append(f"{rel_file}:{number}: {target} ({why})")
                    return match.group(0)
                new_target = ("/" + new) if path.startswith("/") else posixpath.relpath(new, folder or ".")
                new_target += ("/" if path.endswith("/") and not new_target.endswith("/") else "") + sep + anchor
                changes.append(f"{rel_file}:{number}: {target} -> {new_target}")
                return f"{match.group(1)}{new_target}{match.group(3)}"

            def code(match):
                content = match.group(2)
                if len(match.group(1)) == 1 and content == content.strip() and " " not in content:
                    readings, sources = _span_readings(root, content, folder, succ, before)
                    handled.update(sources)
                    if readings:
                        left.append(f"{rel_file}:{number}: `{content}` — {readings} (mention in text — not changed)")
                return match.group(0)  # text: never changed

            line = REFDEF_RE.sub(link, line, count=1)
            parts, pos = [], 0
            for span in CODE_SPAN_RE.finditer(line):
                parts += [LINK_RE.sub(link, line[pos:span.start()]), code(span)]
                pos = span.end()
            parts.append(LINK_RE.sub(link, line[pos:]))
            new_line = "".join(parts)
            if new_line != lines[number - 1]:
                lines[number - 1], edited = new_line, True
            left += [f"{rel_file}:{number}: {src} (mentioned in the text)" for src, rx in mentions.items()
                     if src not in handled and rx.search(new_line)]
        if edited and not plan:
            file.write_bytes("".join(lines).encode("utf-8"))
    return changes, left


def _code(text: str) -> str:
    """`text` as one Markdown code span, also when it holds backticks itself."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    pad = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def write_references(root: Path, refs: tuple, plan: bool) -> str:
    """The full list — every reference bent and every one left, with its reason — written to
    REFS_FILE (REFS_PLAN_FILE with `plan`); returns that path."""
    changes, left = refs
    rel = REFS_PLAN_FILE if plan else REFS_FILE
    head = "# would be rewritten (old -> new)" if plan else "# rewritten (old -> new)"
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join([head, *changes, "", "# left unchanged (reason in brackets)", *left]) + "\n",
                    encoding="utf-8")
    return rel


def refs_summary(refs: tuple) -> str:
    """'<n> rewritten, <m> left unchanged (<k> <reason>, ...)'."""
    changes, left = refs
    reasons: dict = {}
    for line in left:
        why = line.rsplit(" (", 1)[-1].rstrip(")").split(":")[0]
        reasons[why] = reasons.get(why, 0) + 1
    detail = ", ".join(f"{n} {why}" for why, n in sorted(reasons.items(), key=lambda item: -item[1]))
    return f"{len(changes)} rewritten, {len(left)} left unchanged" + (f" ({detail})" if detail else "")


def group_left_by_target(left: list) -> list:
    """(target, count, files) per distinct target mentioned in `left` (B129.6: a project can carry
    a few hundred left-unchanged mentions of one old path across docs/project/ — too long for a
    human to read line by line; grouped by the referenced path/text, sorted by count then target,
    `files` sorted and de-duplicated). Each line in `left` is
    "<file>:<line number>: <target> (<reason>)"; `target` here is everything before the reason's
    opening "(" — the same text `refs_summary()` reads the reason from, on the other side of the
    split. The full, ungrouped list stays at REFS_FILE/REFS_PLAN_FILE (write_references())."""
    groups: dict = {}
    for line in left:
        file_part, _sep, rest = line.partition(":")
        rest = rest.split(":", 1)[1].strip() if ":" in rest else rest.strip()
        target = rest.rsplit(" (", 1)[0]
        entry = groups.setdefault(target, {"count": 0, "files": set()})
        entry["count"] += 1
        entry["files"].add(file_part)
    rows = [(target, info["count"], sorted(info["files"])) for target, info in groups.items()]
    rows.sort(key=lambda row: (-row[1], row[0]))
    return rows


# Settings entries that run a removed script (T65): the script a hook command or a Bash(...)
# permission rule executes — the first word of a simple command, or the word after an
# interpreter — written relative to the project (bare, ./ or through $CLAUDE_PROJECT_DIR), never
# an absolute path, one into another repository, or a script that is only an argument.
SCRIPT_SUFFIXES = (".py", ".sh", ".ps1", ".bat", ".cmd", ".js", ".mjs", ".cjs", ".ts", ".rb", ".pl")
INTERPRETERS = {"python", "python3", "py", "bash", "sh", "zsh", "node", "pwsh", "powershell", "deno", "bun",
                "ruby", "perl"}
SHELL_WORDS = {"if", "then", "do", "else", "elif", "while", "until", "{", "!", "time", "exec", "command", "env"}
PROJECT_PREFIXES = ("$CLAUDE_PROJECT_DIR/", "${CLAUDE_PROJECT_DIR}/", "%CLAUDE_PROJECT_DIR%/", "./")
SHELL_VAR_RE = re.compile(r"^\$(?:\w+|\{\w+\})$")  # "$P" — a variable holding the interpreter
SETTINGS_FILE = ".claude/settings.json"
SETTINGS_LOCAL = ".claude/settings.local.json"


def _project_script(word: str) -> Optional[str]:
    """`word` as a project-relative script path, or None (absolute, outside, a pattern, no script)."""
    for prefix in PROJECT_PREFIXES:
        if word.startswith(prefix):
            word = word[len(prefix):]
            break
    word = re.sub(r":?\*+$", "", word)  # a permission pattern: path:* or path*
    if not word or "*" in word or word.startswith(("/", "~", "$", "%", "..")) or re.match(r"^[A-Za-z]:", word):
        return None
    word = posixpath.normpath(word)
    return word if word.lower().endswith(SCRIPT_SUFFIXES) and not word.startswith("..") else None


def executed_scripts(command: str) -> list:
    """Project-relative scripts `command` executes (see above); `bash -c '…'` is read again."""
    text = command.replace('\\"', '"').replace("\\", "/")
    try:
        lexer = shlex.shlex(text, posix=True, punctuation_chars=";&|()")
        lexer.whitespace_split = True
        words = list(lexer)
    except ValueError:
        words = text.split()
    found, at_start, i = [], True, 0
    while i < len(words):
        word = words[i]
        i += 1
        if word and set(word) <= set(";&|()"):
            at_start = True
            continue
        if not at_start or word in SHELL_WORDS or re.match(r"^\w+=", word):
            continue
        at_start = False
        name = posixpath.basename(word).lower()
        name = name[:-4] if name.endswith(".exe") else name
        if name not in INTERPRETERS and not SHELL_VAR_RE.match(word):
            script = _project_script(word)
            found += [script] if script else []
            continue
        while i < len(words) and words[i].startswith("-") and words[i] not in ("-c", "-File", "-f"):
            i += 1
        if i < len(words) and words[i] in ("-c", "-File", "-f") and i + 1 < len(words):
            if words[i] == "-c" and name in ("bash", "sh", "zsh"):
                found += executed_scripts(words[i + 1])
            elif words[i] != "-c":
                found += [s for s in [_project_script(words[i + 1])] if s]
            i += 2
        elif i < len(words) and not (words[i] and set(words[i]) <= set(";&|()")):
            found += [s for s in [_project_script(words[i])] if s]
            i += 1
    return list(dict.fromkeys(found))


def _entry_scripts(entry: str, kind: str) -> list:
    """Scripts a settings entry executes: a hook or statusLine command, or a Bash(...) rule (a
    Read/Edit/Write rule executes nothing)."""
    if kind == "rule":
        match = re.match(r"^Bash\((.*)\)$", entry.strip(), re.S)
        return executed_scripts(match.group(1)) if match else []
    return executed_scripts(entry)


def _json_layout(text: str, data) -> Optional[tuple]:
    """(indent, ensure_ascii, newline, final newline) with which json.dumps gives back `text`
    exactly — None if no such layout exists (then the file is not rewritten)."""
    newline = "\r\n" if "\r\n" in text else "\n"
    first = next((line for line in text.split(newline) if line[:1] in (" ", "\t")), "  ")
    indent = "\t" if first.startswith("\t") else len(first) - len(first.lstrip(" "))
    final = text.endswith(newline)
    for ascii_only in (False, True):
        layout = (indent, ascii_only, newline, final)
        if _json_dump(data, layout) == text:
            return layout
    return None


def _json_dump(data, layout: tuple) -> str:
    indent, ascii_only, newline, final = layout
    return json.dumps(data, indent=indent, ensure_ascii=ascii_only).replace("\n", newline) + (newline if final else "")


# B129.7a: substring of the predecessor's own inline Python SessionStart hook (checks
# docs/ai/config.md by hand, prints its own message, "exit 0" — no script of its own, so
# _entry_scripts() never has anything to flag it by).
PREDECESSOR_HOOK_SIGNATURE = "AI-CONFIG-Abgleich"


def prune_settings(root: Path, dead: list, pending: list, plan: bool, gone: list = ()) -> tuple:
    """(removed, notes): hook commands and Bash(...) permission rules in .claude/settings.json whose
    executed script lies at or below a delete or legacy row this adoption removed (`dead`; for a
    --plan, `pending` is what the real run still removes), taken out — an emptied hook group and
    an event it empties go with them (an event that was empty already stays), everything else
    stays byte for byte (line endings included); written only if json.dumps reproduces the file
    exactly, otherwise listed for removal by hand. Also listed, never removed: an entry whose
    script was already missing before the adoption, one whose script an adopt row removed
    (another source in `gone`), a statusLine, and everything in .claude/settings.local.json.
    With `plan`, nothing is written."""
    removed, notes = [], []

    def verdict(script: str) -> Optional[str]:
        """'dead', a reason to list the entry, or None (the script is there)."""
        leaving = any(_at_or_below(script, p) for p in pending)
        if os.path.lexists(root / script) and not leaving:
            return None
        if any(_at_or_below(script, p) for p in dead):
            return "dead"
        if leaving or any(_at_or_below(script, p) for p in gone):
            return f"script {script} removed by this adoption (adopt row) — re-point or remove it by hand"
        return f"script {script} was already missing before the adoption — remove it by hand"

    def judge(entry: str, kind: str, where: str, rel: str) -> bool:
        """True if the entry goes; lists it in `notes` where it only needs a look."""
        scripts = _entry_scripts(entry, kind)
        if not scripts and kind == "command" and PREDECESSOR_HOOK_SIGNATURE in entry:
            return True  # B129.7a: the predecessor's own inline hook, runs no script of its own
        verdicts = [v for v in (verdict(s) for s in scripts) if v]
        if "dead" in verdicts:
            return True
        notes.extend(f"{rel}: {where}: {entry} — {v}" for v in verdicts)
        return False

    for rel in (SETTINGS_FILE, SETTINGS_LOCAL):
        path = root / rel
        if not path.is_file():
            continue
        try:
            text = path.read_bytes().decode("utf-8")
            data = json.loads(text)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            notes.append(f"{rel}: not read ({exc.__class__.__name__}) — check its hooks and permissions by hand")
            continue
        if not isinstance(data, dict):
            continue
        hits = []
        perms = data.get("permissions")
        for key, rules in (perms.items() if isinstance(perms, dict) else []):
            if isinstance(rules, list):
                out = [r for r in rules if isinstance(r, str) and judge(r, "rule", f"permissions.{key}", rel)]
                hits += [f"permissions.{key}: {r}" for r in out]
                perms[key] = [r for r in rules if r not in out]
        hooks = data.get("hooks")
        for event, groups in (list(hooks.items()) if isinstance(hooks, dict) else []):
            if not isinstance(groups, list):
                continue
            kept_groups = []
            for group in groups:
                entries = group.get("hooks") if isinstance(group, dict) else None
                if not isinstance(entries, list):
                    kept_groups.append(group)
                    continue
                out = [h for h in entries if isinstance(h, dict) and isinstance(h.get("command"), str)
                       and judge(h["command"], "command", f"hooks.{event}", rel)]
                hits += [f"hooks.{event}: {h['command']}" for h in out]
                if len(out) < len(entries) or not entries:
                    group["hooks"] = [h for h in entries if not any(h is g for g in out)]
                    kept_groups.append(group)
            if kept_groups or not groups:
                hooks[event] = kept_groups
            else:
                del hooks[event]
        status = data.get("statusLine")
        if isinstance(status, dict) and isinstance(status.get("command"), str):
            reasons = [v for v in (verdict(s) for s in _entry_scripts(status["command"], "command")) if v]
            notes += [f"{rel}: statusLine: {status['command']} — "
                      + ("runs a removed script, check it by hand" if v == "dead" else v) for v in reasons]
        if not hits:
            continue
        if rel == SETTINGS_LOCAL:
            notes += [f"{rel}: {hit} — runs a removed script, left in place (local file)" for hit in hits]
            continue
        layout = _json_layout(text, json.loads(text))
        if layout is None:
            notes += [f"{rel}: {hit} — runs a removed script; the file's layout is not reproducible, "
                      "remove it by hand" for hit in hits]
            continue
        removed += [f"{rel}: {hit}" for hit in hits]
        if not plan:
            path.write_bytes(_json_dump(data, layout).encode("utf-8"))
    return removed, notes


# Adopt targets that keep the act:default mark: docs/ai/config.md takes over values only — its
# text stays the template's scaffold and so stays on the translation list (R-work-language).
KEEP_DEFAULT_MARK = {"docs/ai/config.md"}


def strip_default_marks(root: Path, targets: list, plan: bool, created: Optional[dict] = None) -> list:
    """Adopt targets (files, or files below a folder target) whose line 1 is the `act:default`
    mark: that line removed (a BOM stays), nothing else — the file now holds adopted content and
    is no longer scaffold to translate. KEEP_DEFAULT_MARK keeps it, and so does a file init.py
    created whose content is still what it was after --apply (`created`: state created_hashes —
    a scaffold file inside a folder target). Returns the root-relative paths."""
    import actlib
    marked = set(actlib.scaffold_default_files(root)) - KEEP_DEFAULT_MARK
    done = []
    created = created or {}
    for rel in sorted(p for p in marked if any(_at_or_below(p, t) for t in targets)):
        path = root / rel
        if created.get(rel) and created[rel] == _sha256(path):
            continue  # unchanged since --apply: still scaffold
        text = path.read_bytes().decode("utf-8")
        first, rest = (text.split("\n", 1) + [""])[:2]
        if not plan:
            path.write_bytes((("﻿" if first.startswith("﻿") else "") + rest).encode("utf-8"))
        done.append(rel)
    return done


def legacy_readme_rows(moved: dict) -> list:
    """(old path, renamed path) for every legacy move this adoption actually renamed (B128,
    legacy_rel()) — sorted, ready for a Markdown table row each. Empty when nothing was renamed."""
    return sorted((old, new) for old, new in moved.items() if legacy_rel(old) != old)


def write_legacy_readme(root: Path, moved: dict, plan: bool) -> Optional[str]:
    """{LEGACY_README} (`act:default`, English — R-work-language translates it like any other
    scaffold): why a few paths under the legacy archive differ from their old one (B128 — an AI
    tool reads a `.claude/` folder, or a `CLAUDE.md`/`AGENTS.md`/`GEMINI.md` file, as its own
    configuration wherever it sits, archive included) and the old-path -> renamed-path table.
    Written (overwriting an earlier one from the same project) only where this run's `moved`
    renamed at least one path; returns the path written, or None (nothing renamed, or `plan`)."""
    rows = legacy_readme_rows(moved)
    if not rows:
        return None
    if plan:
        return LEGACY_README
    lines = [
        "<!-- act:default -->",
        "# Archived material — renamed paths",
        "",
        "Everything under this folder is a byte-identical copy `adopt.py` made of material the "
        "adoption moved out of the way (`docs/ai/work/archive/legacy/<old path>`) — reference "
        "material only, nothing here is loaded by any tool.",
        "",
        "A few paths differ from their old one on purpose (`B128`): an AI tool reads a `.claude/` "
        "folder, or a file named `CLAUDE.md`/`AGENTS.md`/`GEMINI.md`, as its own configuration "
        "wherever it sits — nested here included. Those are renamed so nothing here loads again:",
        "",
        "| Old path | Here |",
        "| :--- | :--- |",
        *(f"| `{old}` | `{new}` |" for old, new in rows),
        "",
    ]
    path = root / LEGACY_README
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return LEGACY_README


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


def write_report(root: Path, rows: list, state: dict, doctor: tuple, refs: tuple, acc: list,
                 extra: tuple = ((), (), (), "")) -> Path:
    """The inbox report. `extra`: (settings entries removed, settings notes, files whose
    act:default mark was removed, path of the full reference list). A pure report of what the
    tool did (reviewing the branch and committing is still up to a human, but nothing here asks
    for a decision) -- `kind: report`, never `todo` (16-inbox-questions-tasks.md § "Arten in der
    Inbox")."""
    import actlib
    inbox = root / actlib.INBOX_DIR
    when = datetime.now()  # fixed once, so a same-minute retry below keeps the same stamp
    dest = inbox / actlib.inbox_entry_filename("report", "adoption-report", when)
    n = 2
    while dest.exists():  # same-minute collision (concept doc: "-2", "-3" as before)
        dest = inbox / actlib.inbox_entry_filename("report", f"adoption-report-{n}", when)
        n += 1
    moved = state.get("moved", {})
    by_action = {a: [r for r in rows if r["action"] == a and (a == "adopt" or r["path"] not in moved)] for a in ACTIONS}

    # Every heading/table-header/fixed phrase below follows `language-docs` (R-work-language) —
    # `root` is already a set-up project by the time --finish runs this, so its own config.md is
    # the source of truth, same helper every other writer in this template uses.
    language = actlib.docs_language(root)
    L = lambda en, de: actlib.localized(language, en, de)  # noqa: E731

    def adopted_note(row: dict) -> str:
        if row["path"] in state.get("bridged", []):
            return " (" + L("now a bridge", "jetzt eine Brücke") + ")"
        if row["path"] in moved:
            how = L("into itself", "in sich selbst") if row["path"] in _targets(row) \
                else L("original moved before init", "Original vor init verschoben")
            return f" ({how}; " + L("original in legacy", "Original im Legacy-Archiv") + f": {_code(moved[row['path']])})"
        return ""

    none = L("none", "keine")
    settings_removed, settings_notes, unmarked, refs_file = extra
    out = ["kind: report", "for: all", "status: open", f"created: {date.today().isoformat()}", "",
           L("# Adoption report (`adopt.py --finish`)", "# Übernahmebericht (`adopt.py --finish`)"), "",
           L(f"Branch `{state.get('branch', BRANCH)}` (from `{state.get('base_branch', '?')}`), nothing committed by "
             "adopt.py. Review the branch, then commit per path or drop it.",
             f"Branch `{state.get('branch', BRANCH)}` (von `{state.get('base_branch', '?')}`), nichts von adopt.py "
             "committet. Branch prüfen, dann je Pfad committen oder verwerfen."),
           "", L("## Adopted (source → target)", "## Übernommen (Quelle → Ziel)"), ""]
    out += [f"- {_code(r['path'])} → {', '.join(_code(t) for t in _targets(r))}{adopted_note(r)}"
            for r in by_action["adopt"]] or [f"- {none}"]
    out += ["", L("## `act:default` mark removed (adopted content, no longer scaffold)",
                  "## Marke `act:default` entfernt (übernommener Inhalt, kein Gerüst mehr)"), ""]
    out += [f"- {_code(rel)}" for rel in unmarked] or [f"- {none}"]
    out += ["", L(f"## Entries in {_code(SETTINGS_FILE)} removed (they ran a removed script; not staged)",
                  f"## Einträge in {_code(SETTINGS_FILE)} entfernt (sie riefen ein entferntes Script auf; nicht vorgemerkt)"), ""]
    out += [f"- {_code(line)}" for line in settings_removed] or [f"- {none}"]
    if settings_notes:
        out += ["", L("Remove it by hand, or check:", "Von Hand entfernen, oder prüfen:"), ""] \
               + [f"- {_code(line)}" for line in settings_notes]
    out += ["", L("## Own skills and roles bridged (as `act-load-settings` does)",
                  "## Eigene Skills und Rollen verbrückt (wie `act-load-settings`)"), ""]
    out += [f"- {_code('docs/ai/local/' + unit)}" for unit in state.get("own_units", [])] or [f"- {none}"]
    out += ["", L("## Moved to legacy (byte-identical, see `.act-local/adopt/legacy-checksums.json`)",
                  "## Ins Legacy-Archiv verschoben (bytegleich, siehe `.act-local/adopt/legacy-checksums.json`)"), ""]
    out += [f"- {_code(old)} → {_code(new)}" for old, new in moved.items()] or [f"- {none}"]
    out += ["", L("## Deleted", "## Gelöscht"), ""]
    out += [f"- {_code(r['path'])}" for r in by_action["delete"]] or [f"- {none}"]
    out += ["", L("## Kept in place", "## An Ort und Stelle belassen"), ""]
    out += [f"- {_code(r['path'])}" for r in by_action["keep"]] or [f"- {none}"]
    out += ["", L(f"## doctor.py (exit {doctor[0]})", f"## doctor.py (Exit {doctor[0]})"), ""]
    out += [f"- {line}" for line in doctor[1][:30]] or ["- " + L("no findings", "keine Befunde")]
    changes, left = refs
    out += ["", L(f"## References in {REFS_SCOPE} rewritten (link target only, not staged)",
                  f"## Verweise in {REFS_SCOPE_DE} umgeschrieben (nur Verweisziel, nicht vorgemerkt)"), ""]
    if len(changes) > REFS_IN_REPORT:
        out += ["- " + L(f"{len(changes)} rewritten — the full list: {_code(refs_file or REFS_FILE)}",
                        f"{len(changes)} umgeschrieben — die volle Liste: {_code(refs_file or REFS_FILE)}")]
    else:
        out += [f"- {_code(line)}" for line in changes] or [f"- {none}"]
    # B129.6: a raw line per left-unchanged reference ran to 143 lines in the first real adoption —
    # too long for a human; grouped by target (old path/text mentioned) instead, the full list
    # stays at refs_file (write_references()).
    out += ["", L(f"## References in {REFS_SCOPE} left unchanged (no successor, ambiguous, plain text), by target",
                  f"## Verweise in {REFS_SCOPE_DE} unverändert gelassen (kein Nachfolger, mehrdeutig, reiner Text), nach Ziel"), ""]
    grouped = group_left_by_target(left)
    if grouped:
        out += [f"| {L('Target', 'Ziel')} | {L('Count', 'Anzahl')} | {L('Files', 'Dateien')} |", "| :--- | ---: | :--- |"]
        for target, count, files in grouped:
            shown = ", ".join(_code(f) for f in files[:5])
            if len(files) > 5:
                shown += ", " + L(f"+{len(files) - 5} more", f"+{len(files) - 5} weitere")
            out.append(f"| {_code(target)} | {count} | {shown} |")
        out += ["", L(f"full list: {_code(refs_file or REFS_FILE)}", f"volle Liste: {_code(refs_file or REFS_FILE)}")]
    else:
        out += [f"- {none}"]
    out += ["", L("## Accounting", "## Bilanz"), "", "```text", *[line.strip() for line in acc], "```", ""]
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
    # A target adopt_config.py changed itself (rule-set marks in coding_rules.md) and nobody since:
    # its content was still not adopted, so it counts as unchanged for the check below.
    touched = (_read_json(root / ADOPT_DIR / "config-touched.json") or {}).get("paths")
    touched = touched if isinstance(touched, dict) else {}

    def config_only(target: str) -> bool:
        entry = touched.get(target)
        return (isinstance(entry, dict) and (root / target).is_file()
                and entry.get("sha256") == _sha256(root / target))

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
                    elif target in hashes and config_only(target):
                        problems.append(f"{row['path']!r}: target {target!r} changed since --apply only by "
                                        "adopt_config.py (config-touched.json) — content not adopted?")
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
    # Dead references in docs/project/: every source that is gone after this run (not bridged, not
    # standing again at its place) and its new place, bent mechanically (Q91 a).
    gone = [p for p in moved if not os.path.lexists(root / p)] + to_remove + \
           [p for p in state.get("removed_at_apply", []) if not os.path.lexists(root / p)]
    succ = successors(rows, state, gone)
    succ.update(emptied_folders(root, gone, to_remove, succ))
    # Settings entries that run a script of a delete or legacy row (T65); adopt targets whose
    # act:default mark goes because they now hold adopted content.
    actions_of = {row["path"]: row["action"] for row in rows}
    dead = [p for p in dict.fromkeys(gone) if actions_of.get(p) in ("delete", "legacy")]
    adopt_targets = [t for row in rows if row["action"] == "adopt" for t in _targets(row)
                     if not t.startswith(SUCCESSOR_SKIP)]
    # Same for --plan and the real run below (B118 #19/#20): neither scans a file this same
    # --finish is about to remove, and both tell a reference dead before the adoption apart from
    # one only missing a successor.
    refs_exclude = frozenset(to_remove)
    refs_before = _tree_paths(root, state.get("base_commit", "HEAD"))
    if plan:
        settings_removed, settings_notes = prune_settings(root, dead, to_remove, plan=True, gone=gone)
        print(f"[adopt] {prefix}remove {len(settings_removed)} entr{'y' if len(settings_removed) == 1 else 'ies'} "
              f"from {SETTINGS_FILE} that run a removed script:")
        for line in settings_removed:
            print(f"    {line}")
        for line in settings_notes:
            print(f"    check by hand: {line}")
        for rel in strip_default_marks(root, adopt_targets, plan=True, created=state.get("created_hashes")):
            print(f"[adopt] {prefix}remove the act:default mark (line 1) from {rel} (adopted content)")
        refs = rewrite_references(root, succ, plan=True, exclude=refs_exclude, before=refs_before)
        refs_file = write_references(root, refs, plan=True)
        print(f"[adopt] references in {REFS_SCOPE} (plan): {refs_summary(refs)} — full list: {refs_file}")
        legacy_readme = write_legacy_readme(root, state.get("moved", {}), plan=True)
        if legacy_readme:
            print(f"[adopt] {prefix}write {legacy_readme} (renamed paths table)")
        print(f"[adopt] {prefix}run doctor.py, write the inbox report")
        harvest = root / ADOPT_DIR / "harvest.md"
        if harvest.is_file():
            print(f"[adopt] {harvest.relative_to(root).as_posix()} has candidates for the "
                  f"template — ask consent after --finish (feedback.py --target {root} ...), "
                  f"see SKILL.md step 7.")
        print(f"[adopt] plan only, nothing changed (except {refs_file})")
        return 0

    state.setdefault("rescued", {})
    try:
        for files in to_rescue.values():
            rescue(root, files, state["rescued"], lambda: _write_json(state_path, state))
    except (OSError, RuntimeError) as exc:
        _write_json(state_path, state)
        raise Refused(f"stopped before any removal: {exc}")
    bridged = []
    language_chat, language_docs = actlib.language_settings(actlib.read_config())
    cfg_tokens = init_mod._config_tokens({
        "name": actlib.read_config().get("name", root.name), "owner": actlib.read_config().get("owner", ""),
        "language_chat": language_chat, "language_docs": language_docs,
        "stack": actlib.read_config().get("stack", ""),
        "lint_cmd": "", "typecheck_cmd": "", "test_cmd": "", "tools": tools,
        "mode": actlib.read_config().get("mode", "solo"),
        # init.py's ProjectConfig gained "feedback_mode" (T58); only the <feedback-mode> token uses it.
        "feedback_mode": actlib.read_config().get("feedback", "off"),
    })
    cache = actlib.read_cache()
    removed = []
    try:
        for path in to_bridge:
            key, spec = bridges[path]
            if spec["kind"] == "verbatim":
                dest = root / path
                dest.unlink(missing_ok=True)  # a re-run after a stop may find it gone already
                init_mod._write_text_file(root / ".act" / "bridges" / key, dest, cfg_tokens, False, root)
                cache["generated"][path] = actlib.sha256_file(dest)
                _git(root, "add", "--", path)
            bridged.append(path)
        for path in to_remove:
            if is_tracked(root, path):
                _git(root, "rm", "-r", "-q", "--", path)
            if os.path.lexists(root / path):
                _remove_path(root / path)
            removed.append(path)
    except RuntimeError as exc:
        # A failed git call is never followed by an accounting: state stays "applied", the same
        # --finish continues (a written bridge is rewritten, a removed path is skipped).
        if bridged:
            actlib.write_cache({"generated": cache["generated"]})
        state["error"] = f"--finish stopped: {exc}"
        _write_json(state_path, state)
        raise Refused(f"stopped during --finish, nothing verified: {exc}. Done so far: {len(bridged)} bridged, "
                      f"{len(removed)} removed. Fix the cause git names (for a path too long: git -C {root} "
                      f"config core.longpaths true), then run --finish again — or {way_back(root)}")
    state.pop("error", None)
    if bridged:
        actlib.write_cache({"generated": cache["generated"]})
    # After the removals: an own unit may carry the name its old tool folder had.
    unit_messages = bridge_own_units(root, units) if units else []
    for message in unit_messages:
        print(f"[adopt] {message}")

    # Before doctor.py, which checks the hooks: entries that run a removed script go first.
    settings_removed, settings_notes = prune_settings(root, dead, [], plan=False, gone=gone)
    for line in settings_removed:
        print(f"[adopt] removed from {line} (ran a removed script)")
    for line in settings_notes:
        print(f"[adopt] check by hand: {line}")
    unmarked = strip_default_marks(root, adopt_targets, plan=False, created=state.get("created_hashes"))
    for rel in unmarked:
        print(f"[adopt] removed the act:default mark (line 1) from {rel} (adopted content)")
    refs = rewrite_references(root, succ, plan=False, exclude=refs_exclude, before=refs_before)
    refs_file = write_references(root, refs, plan=False)
    legacy_readme = write_legacy_readme(root, state.get("moved", {}), plan=False)
    if legacy_readme:
        print(f"[adopt] wrote {legacy_readme} (renamed paths table)")
    doctor = run_doctor(root)
    state.update({"bridged": bridged, "removed_at_finish": to_remove,
                  "own_units": [f"{area}/{name}" for area, name in units],
                  "settings_removed": settings_removed, "unmarked": unmarked})
    acc, ok = accounting(root, rows, state, "finish", scan_rows)
    report = write_report(root, rows, state, doctor, refs, acc,
                          (settings_removed, settings_notes, unmarked, refs_file))
    state.update({"state": "finished", "finished": datetime.now().isoformat(timespec="seconds"),
                  "report": report.relative_to(root).as_posix(), "doctor_exit": doctor[0]})
    _write_json(state_path, state)
    print(f"[adopt] doctor.py: exit {doctor[0]}, {len(doctor[1])} finding(s)")
    for line in doctor[1][:10]:
        print(f"    {line}")
    print(f"[adopt] references in {REFS_SCOPE}: {refs_summary(refs)} — full list: {refs_file}")
    print(f"[adopt] report: {report.relative_to(root).as_posix()}")
    harvest = root / ADOPT_DIR / "harvest.md"
    if harvest.is_file():
        # B124/Q26 b: step 6 wrote candidates for the template while reading the old project; the
        # consent question (feedback.py --target) is asked now, not before — see SKILL.md step 7.
        print(f"[adopt] {harvest.relative_to(root).as_posix()} has candidates for the template — "
              f"ask consent now (feedback.py --target {root} ...), see SKILL.md step 7.")
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
  log           legacy, keep                 ai-machinery  adopt, legacy, delete, keep
  ai-config     adopt, legacy, keep, delete  work          adopt, legacy, keep, delete
  project-doc   adopt, legacy, keep; delete only with confirmed
  predecessor   adopt, legacy, keep; delete only "template only" (scan origin) or with confirmed
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
the file system is; a scan.json that no longer matches a fresh scan (--apply); on Windows a
legacy path of 260 characters or more while the repository does not set core.longpaths
(`git config core.longpaths true`).
Source/test/content trees (first path segment): {', '.join(sorted(CONTENT_TREES))}, test*.

--apply: clean tree (untracked only under .act-local/), new branch {BRANCH} (an existing branch
  refuses; a recorded state prints it and exits 0), `legacy` rows moved byte-identical to
  {LEGACY_ROOT}/<old path> (sha256 before = after) — with every AI-tool config path segment
  renamed first (B128: `.claude`/`.codex`/`.gemini`/`.cursor`/`.agents` -> `_claude`/…,
  `.github/agents`/`.github/prompts` -> `_agents`/`_prompts`, `.github/copilot-instructions.md`
  -> `….legacy`, a `CLAUDE.md`/`AGENTS.md`/`GEMINI.md` at any depth -> `….legacy`, so no tool
  reads the archived copy as its own configuration) — then staged by path; a git
  call that fails stops the run with no accounting. An old skill/agent carrying the name of a
  template unit, or a file at a place init.py writes itself (docs/ai/ skeleton, docs/ai/rules.md,
  docs/project/coding_rules.md, docs/README.md), moves there too unless it is a delete row
  (removed) — a kept file at such a place stays and init leaves it. Then init.py --target
  --non-interactive --no-commit (detected at runtime; only an init.py without that flag makes its
  own first commit instead); existing CLAUDE.md/AGENTS.md stay until --finish.
--finish: every adopt row done with its target on disk; adopted ai-config files that init has a
  bridge for become that bridge (protected rows stay as they are), other adopted sources and
  delete rows removed (git rm); an adopt target docs/ai/local/skills/<name>/... or
  docs/ai/local/agents/<name>.md is an own unit and gets its tool copies/bridge like
  act-load-settings writes them (skill copies recorded in .act-lock.json § copies) — refused if
  <name> is a template unit's (that would be an override; a row note "override" leaves it to the
  template's copy mechanism); doctor.py, references to moved/removed paths, report
  docs/ai/inbox/report-<stamp>-adoption-report.md. A reference in {REFS_SCOPE}
  to a path that is gone — or to a folder the adoption leaves without any file — is bent to its
  new place (legacy copy, or the one successor of an adopt row), the link target only (Q91 a):
  the target of a Markdown link or of a reference definition `[x]: path` (relative stays
  relative, anchor kept); no other text changes, code blocks never. A path in backticks is text:
  never changed, only listed ("mention in text — not changed") with both readings, relative to
  the file and to the root. The full list, bent and left with the reason, goes to
  {REFS_FILE} (--finish --plan: {REFS_PLAN_FILE},
  the terminal gets the counts); the report lists it inline up to {REFS_IN_REPORT} lines. Hook commands and
  Bash(...) permission rules in {SETTINGS_FILE} whose executed script (the first word of a
  command, or the word after python/bash/node/… or "$VAR"; bare, ./ or $CLAUDE_PROJECT_DIR/ path)
  lies at or below a gone delete or legacy row are removed — an emptied hook group or event with
  them, nothing else changes, line endings kept; a script that is only an argument, Read/Edit/
  Write rules and entries on scripts still on disk never. Listed for removal by hand instead: a
  file whose layout json.dumps cannot reproduce, an entry whose script was already missing before
  the adoption or went with an adopt row, a statusLine, and {SETTINGS_LOCAL}.
  An adopt target (or a file below one that changed since --apply) whose line 1 is
  <!-- act:default --> loses that line — except docs/ai/config.md (values adopted, its text
  stays scaffold to translate).
  {LEGACY_README} (act:default, old path -> renamed path table) is written when B128 renamed at
  least one legacy path; nothing when it did not.
  --finish --plan shows all of it first. A second --finish says "already finished".
  An adopt target that still has the content it had right after --apply, or that only
  adopt_config.py changed since (its hash as recorded in {ADOPT_DIR}/config-touched.json), is
  refused ("content not adopted?").
--apply --language-docs <code> --language-chat <code|auto>: passed on to init.py (B148 1), so the
  docs language and the init todos are right from the start. They are recorded in state.json
  ("languages") and adopt_config.py keeps them; it sets `language-docs` from an old AI-CONFIG.md
  only where none was given.
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
    mode.add_argument("--finish", action="store_true",
                      help="bridges, removals, settings entries, marks, references, doctor, inbox report")
    mode.add_argument("--abort", action="store_true", help="the way back after --apply: undo it, delete the branch")
    parser.add_argument("--plan", action="store_true", help="validate and show what would happen, change nothing")
    parser.add_argument("--force", action="store_true",
                        help=f"with --abort: copy work done since --apply to {ABORTED_ROOT}/ first, then abort")
    parser.add_argument("--language-docs", metavar="CODE",
                        help="with --apply: language of docs/ (e.g. de), passed on to init.py; default en")
    parser.add_argument("--language-chat", metavar="CODE",
                        help="with --apply: chat language (a code, or auto), passed on to init.py")
    return parser


def main(argv: list) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    root = Path(args.target).expanduser().resolve()
    if (args.language_docs or args.language_chat) and not args.apply:
        print("adopt.py: --language-docs/--language-chat only go with --apply", file=sys.stderr)
        return 2
    import actlib
    languages: dict[str, Optional[str]] = {}
    for option, value, allow_auto in (("--language-docs", args.language_docs, False),
                                      ("--language-chat", args.language_chat, True)):
        code = actlib.normalize_language(value, allow_auto=allow_auto) if value else None
        if value and code is None:
            print(f"adopt.py: {option} {value!r} is not a language code (e.g. en, de"
                  f"{', or auto' if allow_auto else ''})", file=sys.stderr)
            return 2
        languages[option] = code
    if not root.is_dir():
        print(f"adopt.py: target is not a directory: {root}", file=sys.stderr)
        return 2
    if root == TEMPLATE_ACT.parent.resolve():
        print("adopt.py: the target is this template checkout itself", file=sys.stderr)
        return 2
    try:
        if args.abort:
            return cmd_abort(root, args.plan, args.force)
        if args.apply:
            return cmd_apply(root, args.plan, languages["--language-docs"], languages["--language-chat"])
        return cmd_finish(root, args.plan)
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
