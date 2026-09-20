#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Turn a checkout of this template into a project ("here, in this clone"), or dock onto
#          an existing/empty directory ("--target"). Ten steps, always in the same order: collect
#          config values, resolve git (origin/branch), check git identity, write the per-checkout
#          workspace identity, thin the bridges down to the chosen tools, materialize skeleton +
#          bridges, append .gitattributes/.gitignore, handle the template's own LICENSE, write the
#          lock/cache state, and make the first commit. Never overwrites a file the project already
#          has; anything that needs a decision but can't be asked (non-interactive run) is written
#          to docs/ai/inbox/ instead of guessed. Stdlib only.
#
# Usage:
#   python .act/scripts/init.py                      # set up the current checkout in place
#   python .act/scripts/init.py --target <path>       # create/dock in another directory instead
#   python .act/scripts/init.py --plan                # show the ten steps, change nothing
#   python .act/scripts/init.py --non-interactive      # never prompt; take defaults, log to inbox
#
# Output format: one numbered line per step ("[n/10] ..."), 1..10, plus a closing "[act] done"
#   line. Exit 0 on success (a --plan run included), 1 if a fatal precondition is not met (e.g.
#   --target points at an unwritable path).

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path

import actlib


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Recognizable placeholder git identities (step 3). Compared case-insensitively.
PLACEHOLDER_NAMES = {"test", "your name", "user"}
PLACEHOLDER_EMAIL_SUFFIXES = ("@example.com",)

# Known origins of the template itself (step 2). A repo whose "origin" normalizes to one of these
# is the template clone itself, not a project's own remote, so it gets renamed to "template".
# Extend this list if the template is ever published under another URL; anything not listed here
# is always treated as the project's own remote and left untouched.
# Fallback only. The authoritative source is the "source=" line in .act/VERSION, which the
# template itself maintains; a fork or mirror updates it there instead of patching this script.
KNOWN_TEMPLATE_REMOTES = (
    "github.com/wrufeger/agentic-coding-template",
    "git.rufeger.de/tools/template-agentic-coding-project",
)


def template_remotes(root):
    """Known origins of the template: the "source=" line of .act/VERSION plus the fallbacks."""
    found = []
    version_file = root / ".act" / "VERSION"
    try:
        for line in version_file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "source" and value.strip():
                found.append(value.strip())
    except OSError:
        pass
    return tuple(found) + KNOWN_TEMPLATE_REMOTES

# Every generated bridge, keyed by its name under .act/bridges/. "tool" gates step 5 (None = always
# written); "kind" picks how step 6/7 writes it. The three "verbatim" bridges are exactly the ones
# .gitattributes marks `merge=ours` and dispatch.py re-derives — their hashes go into cache.json.
BRIDGES = {
    "AGENTS.md": {"dest": "AGENTS.md", "tool": None, "kind": "verbatim"},
    "rules.md": {"dest": "docs/ai/rules.md", "tool": None, "kind": "verbatim"},
    "CLAUDE.md": {"dest": "CLAUDE.md", "tool": "claude-code", "kind": "verbatim"},
    "settings.hooks.json": {"dest": ".claude/settings.json", "tool": "claude-code", "kind": "json-merge"},
}

# Plain skeleton -> docs/ai/ copies (step 6). Placeholders (see CONFIG_TOKENS) are replaced in all
# of them; files without any placeholder just pass through unchanged.
SKELETON_FILES = (
    ("config.md", "docs/ai/config.md"),
    ("inbox/README.md", "docs/ai/inbox/README.md"),
    ("local/README.md", "docs/ai/local/README.md"),
    ("proposals/README.md", "docs/ai/proposals/README.md"),
    ("work/README.md", "docs/ai/work/README.md"),
)


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


def _ask(prompt_text: str, default: str, interactive: bool) -> str:
    if not interactive:
        return default
    raw = input(f"{prompt_text} [{default}]: ").strip()
    return raw or default


def _is_placeholder_name(name: str) -> bool:
    return not name.strip() or name.strip().lower() in PLACEHOLDER_NAMES


def _is_placeholder_identity(name: str, email: str) -> bool:
    if _is_placeholder_name(name) or not email.strip():
        return True
    email_l = email.strip().lower()
    return any(email_l.endswith(suffix) for suffix in PLACEHOLDER_EMAIL_SUFFIXES)


def _normalize_remote(url: str) -> str:
    """Reduce a remote URL to "<host>/<path>", no scheme/user/credentials/.git suffix, lowercase,
    so an SSH form (git@host:path) and an HTTPS form (https://host/path) compare equal."""
    normalized = url.strip()
    normalized = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.-]*://", "", normalized)
    normalized = re.sub(r"^[^@/]+@", "", normalized)
    if "/" not in normalized.split(":", 1)[0]:
        normalized = normalized.replace(":", "/", 1)
    normalized = normalized.rstrip("/")
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    return normalized.lower()


def _is_template_remote(url: str, root: Path | None = None) -> bool:
    normalized = _normalize_remote(url)
    known_remotes = template_remotes(root) if root is not None else KNOWN_TEMPLATE_REMOTES
    return any(_normalize_remote(known) in normalized for known in known_remotes)


def _get_remote_url(root: Path, name: str) -> str | None:
    result = _git(["remote", "get-url", name], cwd=root, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _read_version_file(root: Path) -> tuple[str, str]:
    data = {"version": "", "commit": ""}
    path = root / ".act" / "VERSION"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep and key.strip() in data:
                data[key.strip()] = value.strip()
    return data["version"], data["commit"]


# ---------------------------------------------------------------------------
# Step 1 — config values
# ---------------------------------------------------------------------------

def step_config(root: Path, interactive: bool, notes: list[str]) -> dict[str, object]:
    default_owner = "unknown"
    git_name = _git(["config", "user.name"], cwd=root, check=False).stdout.strip()
    if git_name and not _is_placeholder_name(git_name):
        default_owner = git_name

    name = _ask("Project name", root.name, interactive)
    owner = _ask("Owner", default_owner, interactive)
    language = _ask("Chat/doc language", "en", interactive)
    stack = _ask("Stack", "unspecified", interactive)
    lint_cmd = _ask("Lint command", "", interactive)
    typecheck_cmd = _ask("Typecheck command", "", interactive)
    test_cmd = _ask("Test command", "", interactive)
    tools_raw = _ask("Tools (comma-separated, e.g. claude-code)", "claude-code", interactive)
    tools = sorted({t.strip().lower() for t in tools_raw.split(",") if t.strip()})

    if not interactive:
        missing = [
            label
            for label, value in (("stack", stack), ("lint", lint_cmd), ("typecheck", typecheck_cmd), ("test", test_cmd))
            if not value or value == "unspecified"
        ]
        if missing:
            notes.append(
                "Project config uses defaults for: " + ", ".join(missing) + " — review docs/ai/config.md."
            )

    return {
        "name": name,
        "owner": owner,
        "language": language,
        "stack": stack,
        "lint_cmd": lint_cmd,
        "typecheck_cmd": typecheck_cmd,
        "test_cmd": test_cmd,
        "tools": tools,
    }


# ---------------------------------------------------------------------------
# Step 2 — resolve git (origin, branch)
# ---------------------------------------------------------------------------

def step_git_in_place(root: Path, plan: bool) -> tuple[str, str]:
    """Returns (summary, origin_url_if_it_was_the_template_else_empty)."""
    git_dir = root / ".git"
    if not git_dir.exists():
        if not plan:
            _git(["init"], cwd=root)
            # The initial branch name is whatever this machine's git is configured for (often
            # "main", but "master" or a custom default are common too) — point it at "main"
            # explicitly so the outcome does not depend on that setting. Safe before the first
            # commit: it only moves the unborn HEAD, nothing is renamed or rewritten.
            _git(["symbolic-ref", "HEAD", "refs/heads/main"], cwd=root)
            return "no repository found -> ran 'git init' (branch 'main')", ""
        return "no repository found -> would run 'git init' (branch 'main')", ""

    parts = ["repository already present"]
    template_origin = ""
    origin_url = _get_remote_url(root, "origin")
    if origin_url is None:
        parts.append("no 'origin' remote")
    elif _is_template_remote(origin_url, root):
        if not plan:
            _git(["remote", "rename", "origin", "template"], cwd=root)
            parts.append(f"'origin' ({origin_url}) is the template -> renamed to 'template'")
        else:
            parts.append(f"'origin' ({origin_url}) is the template -> would rename to 'template'")
        template_origin = origin_url
    else:
        parts.append(f"'origin' ({origin_url}) points elsewhere -> left unchanged")

    has_commit = _git(["rev-parse", "--verify", "-q", "HEAD"], cwd=root, check=False).returncode == 0
    if not has_commit:
        parts.append("no commits yet -> branch left as-is")
        return "; ".join(parts), template_origin

    current = _git(["branch", "--show-current"], cwd=root).stdout.strip()
    if not current:
        parts.append("HEAD is detached -> branch left as-is")
        return "; ".join(parts), template_origin
    if current == "template":
        parts.append("current branch already named 'template'")
    else:
        if not plan:
            _git(["branch", "-m", current, "template"], cwd=root)
            parts.append(f"branch '{current}' -> renamed to 'template'")
        else:
            parts.append(f"branch '{current}' -> would rename to 'template'")
    if not plan:
        _git(["checkout", "--orphan", "main"], cwd=root)
        _git(["rm", "-r", "--cached", "."], cwd=root, check=False)
        parts.append("new orphan branch 'main' created")
    else:
        parts.append("would create new orphan branch 'main'")
    return "; ".join(parts), template_origin


def step_git_target(root: Path, plan: bool) -> str:
    if (root / ".git").exists():
        return "target already has a repository, left unchanged"
    if plan:
        return "would run 'git init' in target"
    _git(["init"], cwd=root)
    return "ran 'git init' in target"


# ---------------------------------------------------------------------------
# Step 3 — git identity
# ---------------------------------------------------------------------------

def step_identity(root: Path, plan: bool, interactive: bool, notes: list[str]) -> str:
    name = _git(["config", "user.name"], cwd=root, check=False).stdout.strip()
    email = _git(["config", "user.email"], cwd=root, check=False).stdout.strip()
    if not _is_placeholder_identity(name, email):
        return f"identity ok ({name} <{email}>)"

    shown = f"{name or '(none)'} <{email or '(none)'}>"
    if not interactive:
        notes.append(f"Git identity looks unset or like a placeholder ({shown}) — set `git config user.name`/`user.email`.")
        return f"identity unset/placeholder ({shown}) -> non-interactive, left for the inbox"

    answer = _ask(f"Git identity looks like a placeholder ({shown}). Set it now? [g]lobal/[r]epo-only/[n]o", "n", True).strip().lower()
    if answer in ("g", "global", "r", "repo", "repo-only"):
        new_name = _ask("  name", name, True)
        new_email = _ask("  email", email, True)
        scope = "--global" if answer.startswith("g") else None
        if new_name and new_email and not plan:
            if scope:
                _git(["config", scope, "user.name", new_name], cwd=root)
                _git(["config", scope, "user.email", new_email], cwd=root)
            else:
                _git(["config", "user.name", new_name], cwd=root)
                _git(["config", "user.email", new_email], cwd=root)
        where = "globally" if scope else "for this repo"
        return f"identity set {where} to {new_name} <{new_email}>"

    notes.append(f"Git identity left as a placeholder ({shown}).")
    return "identity left unchanged"


# ---------------------------------------------------------------------------
# Step 4 — .act-local/identity.json
# ---------------------------------------------------------------------------

def step_workspace_identity(root: Path, plan: bool, owner: str) -> str:
    if actlib.read_identity() is not None:
        return "already present, left unchanged"
    slug = re.sub(r"[^a-z0-9]+", "-", owner.strip().lower()).strip("-") or "user"
    workspace = uuid.uuid4().hex[:12]
    if not plan:
        actlib.write_identity({"identity": slug, "workspace": workspace, "created": date.today().isoformat()})
    return f"identity '{slug}', workspace '{workspace}'" + (" (plan)" if plan else "")


# ---------------------------------------------------------------------------
# Step 5 — thin bridges down to the chosen tools
# ---------------------------------------------------------------------------

def step_thin_bridges(tools: list[str]) -> tuple[dict[str, dict], str]:
    selected = {key: spec for key, spec in BRIDGES.items() if spec["tool"] is None or spec["tool"] in tools}
    dropped = sorted(set(BRIDGES) - set(selected))
    summary = f"tools={tools or ['(none)']} -> kept: {', '.join(sorted(selected)) or '(none)'}"
    if dropped:
        summary += f"; dropped: {', '.join(dropped)}"
    return selected, summary


# ---------------------------------------------------------------------------
# Step 6 — materialize skeleton + selected bridges
# ---------------------------------------------------------------------------

def _config_tokens(cfg: dict[str, object]) -> dict[str, str]:
    return {
        "<name>": str(cfg["name"]),
        "<owner>": str(cfg["owner"]),
        "<language>": str(cfg["language"]),
        "<stack>": str(cfg["stack"]),
        "<lint-command>": str(cfg["lint_cmd"]) or "(not set)",
        "<typecheck-command>": str(cfg["typecheck_cmd"]) or "(not set)",
        "<test-command>": str(cfg["test_cmd"]) or "(not set)",
        "<tool-list>": ", ".join(cfg["tools"]) or "(none)",
    }


def _relative_label(path: Path, root: Path | None = None) -> str:
    """Short, readable path for the step messages - absolute paths make them unreadable."""
    try:
        base = root if root is not None else Path.cwd()
        return path.relative_to(base).as_posix()
    except ValueError:
        return path.as_posix()


def _write_text_file(
    src: Path, dest: Path, tokens: dict[str, str], plan: bool, root: Path | None = None
) -> tuple[str, bool]:
    """Never overwrites an existing project file. Returns (message, created)."""
    label = _relative_label(dest, root)
    if dest.is_file():
        return f"{label}: already present, left unchanged", False
    if plan:
        return f"{label}: would create", False
    text = src.read_text(encoding="utf-8")
    for token, value in tokens.items():
        text = text.replace(token, value)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    return f"{label}: created", True


def _merge_settings_hooks(src: Path, dest: Path, plan: bool, root: Path | None = None) -> tuple[str, bool]:
    if plan and not src.is_file():
        # --target --plan against a not-yet-created directory: .act/ was never copied, so there
        # is nothing to read from yet — report the intent without touching the filesystem.
        return f"{_relative_label(dest, root)}: would create/merge hook entries", False
    bridge_data = json.loads(src.read_text(encoding="utf-8"))
    if dest.is_file():
        try:
            current = json.loads(dest.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return f"{_relative_label(dest, root)}: not valid JSON, left unchanged", False
    else:
        current = {}
    hooks = current.setdefault("hooks", {})
    changed_events: list[str] = []
    for event, entries in bridge_data.get("hooks", {}).items():
        existing_entries = hooks.setdefault(event, [])
        for entry in entries:
            if entry not in existing_entries:
                existing_entries.append(entry)
                changed_events.append(event)
    if not changed_events:
        return f"{_relative_label(dest, root)}: hook entries already present, left unchanged", False
    if plan:
        return f"{_relative_label(dest, root)}: would add hook entries for {', '.join(sorted(set(changed_events)))}", False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return f"{_relative_label(dest, root)}: hook entries added ({', '.join(sorted(set(changed_events)))})", True


def step_materialize(
    root: Path, plan: bool, cfg: dict[str, object], selected_bridges: dict[str, dict]
) -> tuple[list[str], dict[str, Path], list[Path]]:
    tokens = _config_tokens(cfg)
    bridges_dir = root / ".act" / "bridges"
    skeleton_dir = root / ".act" / "skeleton"
    messages: list[str] = []
    generated: dict[str, Path] = {}  # bridge name -> written path, for cache.json hashing
    touched: list[Path] = []

    for src_name, dest_rel in SKELETON_FILES:
        message, created = _write_text_file(skeleton_dir / src_name, root / dest_rel, tokens, plan, root)
        messages.append(message)
        if created or (root / dest_rel).is_file():
            touched.append(root / dest_rel)

    for key, spec in selected_bridges.items():
        dest = root / spec["dest"]
        if spec["kind"] == "verbatim":
            message, created = _write_text_file(bridges_dir / key, dest, tokens, plan, root)
            messages.append(message)
            if created:
                generated[spec["dest"]] = dest
            if created or dest.is_file():
                touched.append(dest)
        elif spec["kind"] == "json-merge":
            message, changed = _merge_settings_hooks(bridges_dir / key, dest, plan, root)
            messages.append(message)
            if changed or dest.is_file():
                touched.append(dest)

    return messages, generated, touched


# ---------------------------------------------------------------------------
# Step 7 — .gitattributes / .gitignore
# ---------------------------------------------------------------------------

def _append_block(dest: Path, src: Path, marker: str, plan: bool) -> tuple[str, bool]:
    existing = dest.read_text(encoding="utf-8") if dest.is_file() else ""
    if marker in existing:
        return f"{dest.name}: already present, left unchanged", False
    if plan:
        # --target --plan against a not-yet-created directory may not even have .act/ copied
        # yet, so the source block is read lazily, only once we know a write would happen.
        return f"{dest.name}: would append template block", False
    block_text = src.read_text(encoding="utf-8")
    if not existing:
        new_text = block_text
    elif existing.endswith("\n"):
        new_text = existing + "\n" + block_text
    else:
        new_text = existing + "\n\n" + block_text
    dest.write_text(new_text, encoding="utf-8")
    return f"{dest.name}: template block appended", True


def step_git_files(root: Path, plan: bool) -> tuple[list[str], list[Path]]:
    act_dir = root / ".act"
    attrs_msg, attrs_changed = _append_block(
        root / ".gitattributes", act_dir / "bridges" / "gitattributes", "/CLAUDE.md merge=ours", plan,
    )
    ignore_msg, ignore_changed = _append_block(
        root / ".gitignore", act_dir / "bridges" / "gitignore-lines", ".act-local/", plan,
    )
    touched = []
    if attrs_changed or (root / ".gitattributes").is_file():
        touched.append(root / ".gitattributes")
    if ignore_changed or (root / ".gitignore").is_file():
        touched.append(root / ".gitignore")
    return [attrs_msg, ignore_msg], touched


# ---------------------------------------------------------------------------
# Step 8 — template's own files (LICENSE / README)
# ---------------------------------------------------------------------------

def step_own_files(root: Path, plan: bool, interactive: bool, notes: list[str]) -> str:
    parts = []
    readme = root / "README.md"
    parts.append("README.md left untouched (project's own)" if readme.is_file() else "no README.md present")

    license_path = root / "LICENSE"
    if not license_path.is_file():
        parts.append("no LICENSE file present")
        return "; ".join(parts)

    if not interactive:
        notes.append("LICENSE is still the template's license file — review and replace if it doesn't apply.")
        parts.append("LICENSE left as-is -> non-interactive, left for the inbox")
        return "; ".join(parts)

    answer = _ask("Keep the template's LICENSE file for this project? [y/n]", "y", True).strip().lower()
    if answer.startswith("n"):
        if not plan:
            license_path.unlink()
        parts.append("LICENSE removed (template's license did not apply)")
    else:
        parts.append("LICENSE kept as-is (review before publishing)")
    return "; ".join(parts)


# ---------------------------------------------------------------------------
# Step 9 — .act-lock.json + .act-local/cache.json
# ---------------------------------------------------------------------------

def step_lock_and_cache(root: Path, plan: bool, template_origin: str, generated: dict[str, Path]) -> str:
    version, commit = _read_version_file(root)
    if not plan:
        actlib.write_lock({"template": {"version": version, "commit": commit, "source": template_origin}})
    hashes = {rel: actlib.sha256_file(path) for rel, path in generated.items() if path.is_file()}
    if not plan:
        actlib.write_cache({"generated": hashes})
    return f"lock written (version '{version}'), cache with {len(hashes)} generated bridge(s)"


# ---------------------------------------------------------------------------
# Step 10 — first commit, by pathspec
# ---------------------------------------------------------------------------

def step_commit(root: Path, plan: bool, paths: list[Path]) -> str:
    rels = sorted({str(p.relative_to(root)).replace(os.sep, "/") for p in paths if p.exists()})
    if not rels:
        return "nothing to commit"
    if plan:
        return f"would commit {len(rels)} path(s): {', '.join(rels)}"
    _git(["add", "--", *rels], cwd=root)
    diff = _git(["diff", "--cached", "--name-only"], cwd=root)
    if not diff.stdout.strip():
        return "nothing staged, no commit made"
    _git(["commit", "-m", "chore: initialize project from template"], cwd=root)
    sha = _git(["rev-parse", "--short", "HEAD"], cwd=root).stdout.strip()
    return f"committed {len(rels)} path(s) as {sha}"


# ---------------------------------------------------------------------------
# Inbox note for open points
# ---------------------------------------------------------------------------

def _write_inbox_note(root: Path, owner: str, notes: list[str], plan: bool) -> Path | None:
    if not notes:
        return None
    dest = root / "docs" / "ai" / "inbox" / f"{date.today().isoformat()}-init-notes.md"
    if dest.is_file() or plan:
        return None if plan else dest
    lines = [f"for: {owner}", "", "# Open points from `init.py` (non-interactive run)", ""]
    lines.extend(f"- {note}" for note in notes)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Turn a template checkout into a project, or dock onto an existing directory.")
    parser.add_argument("--target", help="create/dock in this directory instead of the current checkout")
    parser.add_argument("--plan", action="store_true", help="show what would happen, change nothing")
    parser.add_argument("--non-interactive", action="store_true", help="never prompt; take defaults, log open points to the inbox")
    args = parser.parse_args(argv)

    plan = args.plan
    source_act = Path(__file__).resolve().parent.parent  # .act/
    is_target = args.target is not None

    if is_target:
        root = Path(args.target).resolve()
        print(f"[act] target mode: {root}")
        if not root.exists():
            print("  creating target directory" + (" (plan)" if plan else ""))
            if not plan:
                root.mkdir(parents=True)
        act_dest = root / ".act"
        if act_dest.resolve() != source_act.resolve():
            if act_dest.exists():
                print("  .act/ already present in target, left unchanged")
            else:
                print("  copying .act/ into target" + (" (plan)" if plan else ""))
                if not plan:
                    shutil.copytree(source_act, act_dest)
        if not plan:
            os.chdir(root)
        elif not act_dest.exists():
            # Plan run against a target that doesn't exist yet: nothing on disk to resolve
            # against, so later steps only report what they would do with the given config.
            pass
    else:
        root = actlib.repo_root()
        if not plan:
            os.chdir(root)

    interactive = actlib.is_interactive() and not plan
    notes: list[str] = []

    cfg = step_config(root, interactive, notes)
    _print_step(1, f"config: name={cfg['name']!r}, owner={cfg['owner']!r}, language={cfg['language']!r}, stack={cfg['stack']!r}, tools={cfg['tools']}")

    if is_target:
        _print_step(2, step_git_target(root, plan))
        template_origin = ""
    else:
        summary, template_origin = step_git_in_place(root, plan)
        _print_step(2, summary)

    _print_step(3, step_identity(root, plan, interactive, notes))
    _print_step(4, step_workspace_identity(root, plan, str(cfg["owner"])))

    selected_bridges, thin_summary = step_thin_bridges(list(cfg["tools"]))
    _print_step(5, thin_summary)

    materialize_messages, generated, touched_bridges = step_materialize(root, plan, cfg, selected_bridges)
    _print_step(6, "; ".join(materialize_messages))

    gitfiles_messages, touched_gitfiles = step_git_files(root, plan)
    _print_step(7, "; ".join(gitfiles_messages))

    if is_target:
        _print_step(8, "skipped in --target mode (docking onto an existing project, nothing of the template's own to decide)")
    else:
        _print_step(8, step_own_files(root, plan, interactive, notes))

    _print_step(9, step_lock_and_cache(root, plan, template_origin, generated))

    inbox_path = _write_inbox_note(root, str(cfg["owner"]), notes, plan)
    commit_paths = [root / ".act", root / ".act-lock.json", *touched_bridges, *touched_gitfiles]
    if inbox_path is not None:
        commit_paths.append(inbox_path)
    _print_step(10, step_commit(root, plan, commit_paths))

    if notes:
        print(f"[act] done - {len(notes)} open point(s) " + ("would go to" if plan else "left in") + " docs/ai/inbox/")
    else:
        print("[act] done - no open points")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
