#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Turn a checkout of this template into a project ("here, in this clone"), or dock onto
#          an existing/empty directory ("--target"). Ten steps, always in the same order: collect
#          config values, resolve git (origin/branch), check git identity, write the per-checkout
#          workspace identity, thin the bridges down to the chosen tools, materialize skeleton +
#          bridges (plus skill copies and role bridges, see copy_targets()/agent_bridge_targets()),
#          append .gitattributes/.gitignore, retire the template's own README(s) and LICENSE (skipped
#          in --target mode -- nothing of the template's own there to decide, only .act/ was copied
#          in), write the lock/cache state, and make the first commit. Never overwrites a file the
#          project already has; anything that needs a decision but can't be asked (non-interactive
#          run) is written to docs/ai/inbox/ instead of guessed. A `language-docs` other than
#          English leaves the scaffold English (marked `act:default`) plus one inbox entry asking to
#          translate it (R-work-language) — init has no model to do that itself. Stdlib only.
#
# Usage:
#   python .act/scripts/init.py                      # set up the current checkout in place
#   python .act/scripts/init.py --target <path>       # create/dock in another directory instead
#   python .act/scripts/init.py --plan                # show the ten steps, change nothing
#   python .act/scripts/init.py --non-interactive      # never prompt; take defaults, log to inbox
#   python .act/scripts/init.py --language-docs de     # docs language without asking (default en);
#                                                      # --language-chat <code|auto> likewise
#   python .act/scripts/init.py --no-commit            # do everything except the final commit
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
from typing import Optional, TypedDict, Union

import actlib
import manifest
import rules
import tiers


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

class ProjectConfig(TypedDict):
    """Return value of step_config(): the resolved project settings, before templating."""
    name: str
    owner: str
    language_chat: str
    language_docs: str
    stack: str
    lint_cmd: str
    typecheck_cmd: str
    test_cmd: str
    tools: list[str]
    mode: str
    feedback_mode: str


class BridgeSpec(TypedDict):
    """One entry of BRIDGES: where a generated file goes and how step 6/7 writes it."""
    dest: str
    tool: str | None
    kind: str


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Recognizable placeholder git identities (step 3). Compared case-insensitively.
PLACEHOLDER_NAMES = {"test", "your name", "user"}
PLACEHOLDER_EMAIL_SUFFIXES = ("@example.com",)

# Known origins of the template itself (step 2). A repo whose "origin" normalizes to one of these
# is the template clone itself, not a project's own remote, so "origin" gets removed outright
# (its address survives only in .act-lock.json's `template.source`, see step_git_in_place — Q73a).
# Extend this list if the template is ever published under another URL; anything not listed here
# is always treated as the project's own remote and left untouched.
# Fallback only. The authoritative source is the "source=" line in .act/VERSION, which the
# template itself maintains; a fork or mirror updates it there instead of patching this script.
KNOWN_TEMPLATE_REMOTES = (
    "github.com/wrufeger/agentic-coding-template",
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
# "docs-index" is a plain, never-overwritten, token-substituted file too (same write path as
# "verbatim"), but deliberately its own kind: it is not merge=ours and not re-derived by
# dispatch.py's fixed 3-entry map (.act/hooks/checks/session.py), so it stays out of cache.json's
# "generated" hashes — nothing there expects a 4th entry (T59).
BRIDGES: dict[str, BridgeSpec] = {
    "AGENTS.md": {"dest": "AGENTS.md", "tool": None, "kind": "verbatim"},
    "rules.md": {"dest": "docs/ai/rules.md", "tool": None, "kind": "verbatim"},
    "coding_rules.md": {"dest": "docs/project/coding_rules.md", "tool": None, "kind": "coding-rules"},
    "CLAUDE.md": {"dest": "CLAUDE.md", "tool": "claude-code", "kind": "verbatim"},
    "settings.hooks.json": {"dest": ".claude/settings.json", "tool": "claude-code", "kind": "json-merge"},
    "docs-readme.md": {"dest": "docs/README.md", "tool": None, "kind": "docs-index"},
}

# Plain skeleton -> docs/ai/ copies (step 6). Placeholders (see CONFIG_TOKENS) are replaced in all
# of them; files without any placeholder just pass through unchanged. The list is read from the
# tree, not kept here: a file added under .act/skeleton/ ships without touching this script.
SKELETON_ROOT = "docs/ai"


def skeleton_files(skeleton_dir: Path) -> list[tuple[str, str]]:
    """Every file under .act/skeleton/, as (path relative to skeleton, destination in the project),
    sorted so a run is reproducible."""
    if not skeleton_dir.is_dir():
        return []
    found = []
    for path in sorted(skeleton_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(skeleton_dir).as_posix()
        found.append((rel, f"{SKELETON_ROOT}/{rel}"))
    return found


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _git(args: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    # In --plan mode the target directory may not exist yet; run git from the nearest existing
    # parent instead of crashing with NotADirectoryError.
    while not cwd.is_dir() and cwd != cwd.parent:
        cwd = cwd.parent
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


def _checkout_source(checkout_root: Path) -> str:
    """The address of the template checkout `init.py` is running from: its own "origin" remote
    URL if it has one, else its absolute local path. Used for `--target` mode (step 2), where
    there is no project "origin" to inspect -- the checkout running init.py *is* the template, so
    its own address is what .act-lock.json's `template.source` needs (Q73a, backlog B105)."""
    origin = _get_remote_url(checkout_root, "origin")
    return origin if origin else str(checkout_root.resolve())


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

# Offered at init time (T58); config.md itself also accepts "manual" (collect, never auto-send) —
# left out here because it is not a useful *first* answer, only something to switch to later.
_FEEDBACK_ON_MODES = ("confirm", "automatic")
# Anything that plainly means "no" also means "off" -- never required to type the exact word.
_FEEDBACK_OFF_ALIASES = ("off", "n", "no", "nein", "aus", "0")
_FEEDBACK_MAX_ATTEMPTS = 3


def _ask_feedback_mode(root: Path, interactive: bool, notes: list[str]) -> str:
    """Offers, once, to report back what worked or was missing about the *working method* to the
    template author — never anything about this project itself (see
    `.act/rules/topics/feedback.md`). Asked only on a genuinely fresh setup: skipped once
    `docs/ai/config.md` already exists, since an established project already made its own choice
    there and the writer in step_materialize never overwrites it anyway (covers both a repeat
    `init` and `--target` docking onto an already set-up project, T58). `interactive` is already
    False for both `--non-interactive` and `--plan` (see main()), so both take the same "stays
    off, note left behind" branch already used by this function's other questions — nothing here
    ever sends anything, it only decides what the config.md row will say.

    Only `confirm`/`automatic`/an off-alias is accepted (case-insensitive); an empty answer or
    anything else re-asks instead of defaulting to anything -- consent must be typed, never
    assumed from a stray keystroke (review finding T58#1/#2). After `_FEEDBACK_MAX_ATTEMPTS` bad
    answers it gives up and stays off, same as the non-interactive case."""
    if (root / "docs" / "ai" / "config.md").is_file():
        return "off"
    if not interactive:
        notes.append(
            "Feedback to the template author is off (default) — turn it on any time in "
            "docs/ai/config.md § Feedback (see TIP-feedback-on)."
        )
        return "off"
    print()
    print("Report back to the template author about the working method?")
    print("- Entries: a short written summary plus a few closed-list settings — never file names/paths, code, or this project's own text.")
    print("- With the default scope (feedback-scope: a,b,c), a send also adds usage numbers: commit/date counts, days active, file count and size, `ai.log` line counts if logging is on, a random project id (persists across sends, not tied to you), and this project's template base commit. Narrow this with `feedback-scope`.")
    print("- confirm (recommended): shows the full payload and asks before every send. automatic: sends without asking.")
    print("- Every actual send is also kept locally under '.act-local/feedback/sent/' (gitignored).")
    print("- Off again any time: docs/ai/config.md § Feedback.")
    for _attempt in range(_FEEDBACK_MAX_ATTEMPTS):
        raw = _ask("Feedback mode - confirm (recommended) / automatic / off", "", True).strip().lower()
        if raw in _FEEDBACK_OFF_ALIASES:
            return "off"
        if raw in _FEEDBACK_ON_MODES:
            return raw
        print("Please answer 'confirm', 'automatic', or 'off' (or n/no) — nothing else is accepted.")
    notes.append(
        "Feedback question left unanswered after 3 tries — stays off. Turn it on any time in "
        "docs/ai/config.md § Feedback (see TIP-feedback-on)."
    )
    return "off"


def _language(key: str, given: Optional[str], prompt_text: str, default: str, interactive: bool,
              notes: list[str]) -> tuple[str, bool]:
    """(value, from_option). An option value wins over the prompt; either way a language name is
    normalized to its code ("Deutsch" -> "de"). A value that is no code is kept as given, with a
    note for the inbox, rather than silently replaced."""
    raw = given if given is not None else _ask(prompt_text, default, interactive)
    code = actlib.normalize_language(raw, allow_auto=(key == "language-chat"))
    if code is None:
        notes.append(f"`{key}` {raw!r} is not a language code — review docs/ai/config.md.")
        return raw.strip(), given is not None
    return code, given is not None


def step_config(root: Path, interactive: bool, notes: list[str],
                languages: Optional[dict[str, Optional[str]]] = None) -> ProjectConfig:
    default_owner = "unknown"
    git_name = _git(["config", "user.name"], cwd=root, check=False).stdout.strip()
    if git_name and not _is_placeholder_name(git_name):
        default_owner = git_name

    name = _ask("Project name", root.name, interactive)
    owner = _ask("Owner", default_owner, interactive)
    languages = languages or {}
    language_chat, chat_given = _language("language-chat", languages.get("language-chat"),
                                          "Chat language (auto = follow the owner's messages)", "auto",
                                          interactive, notes)
    language_docs, docs_given = _language("language-docs", languages.get("language-docs"),
                                          "Docs language (e.g. en, de)", "en", interactive, notes)
    stack = _ask("Stack", "unspecified", interactive)
    lint_cmd = _ask("Lint command", "", interactive)
    typecheck_cmd = _ask("Typecheck command", "", interactive)
    test_cmd = _ask("Test command", "", interactive)
    tools_raw = _ask("Tools (comma-separated, e.g. claude-code)", "claude-code", interactive)
    tools = sorted({t.strip().lower() for t in tools_raw.split(",") if t.strip()})

    unknown_tools = sorted({t for t in tools if actlib.normalize_tool(t) not in actlib.KNOWN_TOOLS})
    if unknown_tools:
        notes.append(
            "Unknown tool id(s) in `tools`: " + ", ".join(unknown_tools)
            + " — known ids: " + ", ".join(sorted(actlib.KNOWN_TOOLS))
            + " (see actlib.TOOL_ALIASES for accepted variant spellings)."
        )

    if not interactive:
        missing = [
            label
            for label, value in (("stack", stack), ("lint", lint_cmd), ("typecheck", typecheck_cmd), ("test", test_cmd))
            if not value or value == "unspecified"
        ] + ([] if chat_given and docs_given else ["language-chat/language-docs (auto/en)"])
        if missing:
            notes.append(
                "Project config uses defaults for: " + ", ".join(missing) + " — review docs/ai/config.md."
            )

    mode = _suggest_mode(root, notes)
    feedback_mode = _ask_feedback_mode(root, interactive, notes)

    return {
        "name": name,
        "owner": owner,
        "language_chat": language_chat,
        "language_docs": language_docs,
        "stack": stack,
        "lint_cmd": lint_cmd,
        "typecheck_cmd": typecheck_cmd,
        "test_cmd": test_cmd,
        "tools": tools,
        "mode": mode,
        "feedback_mode": feedback_mode,
    }


def _suggest_mode(root: Path, notes: list[str]) -> str:
    """Suggest 'solo' or 'team' from the existing history: more than one distinct *real* author
    email means team. Placeholder/test identities are dropped first, with the same check
    `step_identity` uses (`_is_placeholder_identity`) — several name spellings of one person
    (e.g. "Wolfgang" and "Wolfgang Rufeger", same email) must not inflate the count, and a
    throwaway/test identity (e.g. `test <test@example.com>`) must not count as a second author
    just because it used a different email than the real one (T62 I1: three names, one real
    person, used to suggest 'team'). If nothing real is left to compare — every commit looks like
    a placeholder, or there is no history at all — the guess stays 'solo' and a note is left for
    the inbox instead of risking a wrong 'team'.

    Only the *timing* of ID assignment depends on this (see docs/ai/config.md); the layout is the
    same either way, so a wrong guess costs nothing but a line in config.md.
    """
    result = _git(["log", "--format=%an%x09%ae", "-n", "200"], cwd=root, check=False)
    if result.returncode != 0:
        return "solo"
    real_emails: set[str] = set()
    saw_any = False
    for line in result.stdout.splitlines():
        if not line.strip():
            continue
        saw_any = True
        name, _, email = line.partition("\t")
        if _is_placeholder_identity(name, email):
            continue
        real_emails.add(email.strip().lower())
    if not real_emails:
        if saw_any:
            notes.append(
                "Could not tell `mode` (solo/team) apart from the git history — every author "
                "looks like a placeholder or test identity. Left at `solo`; review docs/ai/config.md."
            )
        return "solo"
    return "team" if len(real_emails) > 1 else "solo"


# ---------------------------------------------------------------------------
# Step 2 — resolve git (origin, branch)
# ---------------------------------------------------------------------------

def step_git_in_place(root: Path, plan: bool) -> tuple[str, str, str]:
    """Returns (summary, template_source, template_commit). template_source is the template's own
    address (its "origin" remote URL, before it gets removed below) if that's what "origin"
    pointed at, else empty -- always recorded into .act-lock.json's `template.source`, never left
    implicit in a remote (Q73a): a `git remote rename origin template` used to leave the project
    with a live remote a plain `git pull template main` could update `.act/` through without going
    anywhere near update.py's copies/bridges/migrations/lock -- see backlog Q73a for the incident
    this fixes. `origin` is now removed outright instead, and nothing takes its place.
    template_commit is HEAD of the template checkout *before* the orphan branch below moves it --
    the commit this project was initialized from -- so .act-lock.json's `template.commit` is set
    even when .act/VERSION's own "commit=" line is empty (a template built without that line filled
    in leaves the daily-update check silent until the first update, see the fix this replaces).
    Empty if there is no commit to read (fresh/empty repository)."""
    git_dir = root / ".git"
    if not git_dir.exists():
        if not plan:
            _git(["init"], cwd=root)
            # The initial branch name is whatever this machine's git is configured for (often
            # "main", but "master" or a custom default are common too) — point it at "main"
            # explicitly so the outcome does not depend on that setting. Safe before the first
            # commit: it only moves the unborn HEAD, nothing is renamed or rewritten.
            _git(["symbolic-ref", "HEAD", "refs/heads/main"], cwd=root)
            return "no repository found -> ran 'git init' (branch 'main')", "", ""
        return "no repository found -> would run 'git init' (branch 'main')", "", ""

    parts = ["repository already present"]
    template_source = ""
    origin_url = _get_remote_url(root, "origin")
    if origin_url is None:
        parts.append("no 'origin' remote")
    elif _is_template_remote(origin_url, root):
        if not plan:
            _git(["remote", "remove", "origin"], cwd=root)
            parts.append(f"'origin' ({origin_url}) is the template -> removed (address kept in .act-lock.json only)")
        else:
            parts.append(f"'origin' ({origin_url}) is the template -> would remove (address kept in .act-lock.json only)")
        template_source = origin_url
    else:
        parts.append(f"'origin' ({origin_url}) points elsewhere -> left unchanged")

    has_commit = _git(["rev-parse", "--verify", "-q", "HEAD"], cwd=root, check=False).returncode == 0
    if not has_commit:
        parts.append("no commits yet -> branch left as-is")
        return "; ".join(parts), template_source, ""

    template_commit = _git(["rev-parse", "HEAD"], cwd=root).stdout.strip()

    current = _git(["branch", "--show-current"], cwd=root).stdout.strip()
    if not current:
        parts.append("HEAD is detached -> branch left as-is")
        return "; ".join(parts), template_source, template_commit
    if current == "template":
        parts.append("current branch already named 'template'")
    else:
        if not plan:
            _git(["branch", "-m", current, "template"], cwd=root)
            parts.append(f"branch '{current}' -> renamed to 'template'")
        else:
            parts.append(f"branch '{current}' -> would rename to 'template'")
    if not plan:
        # Pre-check, not the 'git rm' below: a clone with uncommitted changes to tracked files is
        # exactly what makes 'git rm -r --cached .' refuse ("staged content different from both").
        # Catching it here means main() exits before 'checkout --orphan' has touched anything --
        # the alternative (checking 'git rm's own result) would leave the branch already renamed
        # to the orphan 'main' with the template's tree still staged, a harder state to explain.
        dirty = _git(["status", "--porcelain"], cwd=root, check=False).stdout
        tracked_changes = [line for line in dirty.splitlines() if not line.startswith("??")]
        if tracked_changes:
            print(
                f"init.py: clone has {len(tracked_changes)} uncommitted change(s) to tracked file(s) "
                "-- refusing to rebuild 'main' as an orphan branch, since the follow-up "
                "'git rm -r --cached .' would fail on them and leave the whole template tree staged "
                "for the first commit; commit or stash the changes, then run init.py again",
                file=sys.stderr,
            )
            sys.exit(1)
        _git(["checkout", "--orphan", "main"], cwd=root)
        rm_result = _git(["rm", "-r", "--cached", "."], cwd=root, check=False)
        if rm_result.returncode != 0:
            print(
                "init.py: 'git rm -r --cached .' failed after creating the orphan branch -- "
                f"{rm_result.stderr.strip()} -- resolve this in the repository, then run init.py "
                "again (the orphan branch was created but nothing has been committed yet)",
                file=sys.stderr,
            )
            sys.exit(1)
        parts.append("new orphan branch 'main' created")
    else:
        parts.append("would create new orphan branch 'main'")
    return "; ".join(parts), template_source, template_commit


def step_git_target(root: Path, plan: bool, source_act: Path) -> tuple[str, str, str]:
    """Returns (summary, template_source, template_commit) -- unlike step_git_in_place, `root` has
    no "origin" of its own to inspect (it is brand new or foreign), so `template_source` instead
    comes from the checkout init.py is *running from* (source_act.parent): that checkout is the
    template, by definition of being the one docking .act/ onto `root` (Q73a, backlog B105).
    `template_commit` is that same checkout's HEAD (empty if it has none/is not a git repo) --
    same reasoning as step_git_in_place's template_commit, just read from a different repo since
    `root` itself has no history yet to read it from."""
    template_source = _checkout_source(source_act.parent)
    template_commit = _git(["rev-parse", "HEAD"], cwd=source_act.parent, check=False).stdout.strip()
    if (root / ".git").exists():
        return "target already has a repository, left unchanged", template_source, template_commit
    if plan:
        return "would run 'git init' in target", template_source, template_commit
    _git(["init"], cwd=root)
    return "ran 'git init' in target", template_source, template_commit


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
# Step 4 — .act-local/identity.json, .act-local/import/
# ---------------------------------------------------------------------------

def step_workspace_identity(root: Path, plan: bool, owner: str) -> str:
    if actlib.read_identity() is not None:
        return "already present, left unchanged"
    slug = re.sub(r"[^a-z0-9]+", "-", owner.strip().lower()).strip("-") or "user"
    workspace = uuid.uuid4().hex[:12]
    if not plan:
        actlib.write_identity({"identity": slug, "workspace": workspace, "created": date.today().isoformat()})
    return f"identity '{slug}', workspace '{workspace}'" + (" (plan)" if plan else "")


_IMPORT_README_TEXT = """\
# .act-local/import/

Drop a settings file here (`act-export-settings`' output: `act-settings-<date>.md` or `.zip`) and
run `python .act/scripts/settings_load.py apply` with no arguments — it picks up every `.md`/
`.zip` directly in this folder (not this README, not `done/`), sorted by name, and imports them
the same way as `settings_load.py apply <file>` would. `plan` (no arguments) works the same way
for a dry run — it writes nothing and moves nothing.

A file `apply` managed to process is moved to `done/` afterwards (a name collision there gets a
timestamp appended). A file it could not even load (bad zip, unparsable settings.md) is reported
and left here.

This whole folder is machine-local — gitignored via `.act-local/`, never committed. Give a file an
explicit path (`settings_load.py apply <path>`) instead if it should not move.

`act-export-settings` writes its own output to `.act-local/export/` by default (also gitignored) —
the natural place to hand it on to `.act-local/import/` of another checkout.
"""


def step_import_folder(root: Path, plan: bool) -> str:
    """Ensures `.act-local/import/` exists with a short README (Q74b) — created once, never
    overwritten if the README is already there (same "never overwrite" contract as every other
    generated file in this script). settings_load.py also creates this folder on demand itself
    (so a project that predates this step still works without a migration), but init'ing a fresh
    project should not leave the human to discover that only once they first try an import."""
    import_dir = root / ".act-local" / "import"
    readme = import_dir / "README.md"
    if readme.is_file():
        return "import/: .act-local/import/README.md already present, left unchanged"
    if plan:
        return "import/: would create .act-local/import/ + README.md"
    import_dir.mkdir(parents=True, exist_ok=True)
    _write_new_file(readme, _IMPORT_README_TEXT)
    return "import/: .act-local/import/ + README.md created"


# ---------------------------------------------------------------------------
# Step 5 — thin bridges down to the chosen tools
# ---------------------------------------------------------------------------

def step_thin_bridges(tools: list[str]) -> tuple[dict[str, BridgeSpec], str]:
    selected = {key: spec for key, spec in BRIDGES.items() if spec["tool"] is None or spec["tool"] in tools}
    dropped = sorted(set(BRIDGES) - set(selected))
    summary = f"tools={tools or ['(none)']} -> kept: {', '.join(sorted(selected)) or '(none)'}"
    if dropped:
        summary += f"; dropped: {', '.join(dropped)}"
    return selected, summary


# ---------------------------------------------------------------------------
# Step 6 helper — detect coding rule sets (docs/project/coding_rules.md)
# ---------------------------------------------------------------------------

# Priority order for the directly-detected sets — detection itself: `_detect_coding_sets()` below.
# Only used to order *enabled* sets in the generated file; every set the template actually
# ships under .act/coding/ is included either way, checked or not, even one missing here.
CODING_SET_DETECTION_ORDER = [
    "nuxt", "vue", "typescript", "tailwind", "php", "python", "go", "java", "csharp", "bash", "sql",
]


def _detect_coding_sets(root: Path, stack_hint: str, known: set[str]) -> set[str]:
    """Direct hits from the target directory, plus the free-text `stack` config value where its
    text contains a known set's name — before the requires: closure. `known` is every set name
    the template actually ships, so the stack hint can never turn on a set that does not exist."""
    detected: set[str] = set()

    deps: dict[str, object] = {}
    package_json = root / "package.json"
    if package_json.is_file():
        try:
            data = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            for key in ("dependencies", "devDependencies"):
                section = data.get(key)
                if isinstance(section, dict):
                    deps.update(section)
    if "nuxt" in deps:
        detected.add("nuxt")
    if "vue" in deps:
        detected.add("vue")
    if "typescript" in deps or (root / "tsconfig.json").is_file():
        detected.add("typescript")
    if "tailwindcss" in deps or any(root.glob("tailwind.config.*")):
        detected.add("tailwind")

    if (root / "composer.json").is_file():
        detected.add("php")
    if any((root / name).is_file() for name in ("pyproject.toml", "requirements.txt", "setup.py")):
        detected.add("python")
    if (root / "go.mod").is_file():
        detected.add("go")
    if (root / "pom.xml").is_file() or any(root.glob("build.gradle*")):
        detected.add("java")
    if any(root.glob("*.csproj")) or any(root.glob("*.sln")):
        detected.add("csharp")
    scripts_dir = root / "scripts"
    if any(root.glob("*.sh")) or (scripts_dir.is_dir() and any(scripts_dir.glob("*.sh"))):
        detected.add("bash")
    if any(root.glob("*.sql")) or (root / "migrations").is_dir():
        detected.add("sql")

    stack_lower = stack_hint.lower()
    for name in known:
        if name in stack_lower:
            detected.add(name)

    return {name for name in detected if name in known}


def _coding_rules_body(root: Path, cfg: ProjectConfig) -> tuple[str, list[str]]:
    """Build the checkbox list for docs/project/coding_rules.md: every set the template ships,
    detected/enabled ones first (CODING_SET_DETECTION_ORDER), each with all of its groups checked;
    the rest unchecked and without group lines. requires: pulls in further sets (e.g. nuxt pulls
    in vue and typescript) before the list is built. Returns (markdown, enabled_set_names)."""
    coding_dir = root / ".act" / "coding"
    all_names = sorted(p.stem for p in coding_dir.glob("*.md")) if coding_dir.is_dir() else []
    templates = {
        name: rules.parse_template_set(coding_dir / f"{name}.md", "template") for name in all_names
    }

    enabled = _detect_coding_sets(root, cfg["stack"], set(all_names))
    changed = True
    while changed:
        changed = False
        for name in list(enabled):
            for required in templates[name].requires:
                if required in templates and required not in enabled:
                    enabled.add(required)
                    changed = True

    ordered_enabled = [name for name in CODING_SET_DETECTION_ORDER if name in enabled]
    ordered_enabled += sorted(name for name in enabled if name not in CODING_SET_DETECTION_ORDER)
    ordered_rest = sorted(name for name in all_names if name not in enabled)

    lines: list[str] = []
    for name in ordered_enabled:
        # T64: a checked set is written as an import, so Claude Code loads it right after init
        lines.append(rules.coding_set_line(f"- [x] use: .act/coding/{name}.md"))
        for group_id in templates[name].groups:
            lines.append(f"  - [x] `{group_id}`")
    for name in ordered_rest:
        lines.append(rules.coding_set_line(f"- [ ] use: .act/coding/{name}.md"))

    return "\n".join(lines) + ("\n" if lines else ""), ordered_enabled


_CODING_RULES_MARKER = "<!-- act:coding-rules-sets -->"


def _write_coding_rules(
    src: Path, dest: Path, cfg: ProjectConfig, plan: bool, root: Path
) -> tuple[str, bool]:
    """Like _write_text_file, but fills the .act/bridges/coding_rules.md template's rule-set
    marker with the detected list instead of a fixed token substitution. Never overwrites an
    existing project file (the dock-onto-an-existing-project case) — same contract as every other
    generated file in step 6."""
    label = _relative_label(dest, root)
    if dest.is_file():
        return f"{label}: already present, left unchanged", False
    if plan:
        return f"{label}: would create", False
    text = src.read_text(encoding="utf-8")
    if _CODING_RULES_MARKER not in text:
        raise RuntimeError(f"{src}: missing marker '{_CODING_RULES_MARKER}'")
    body, enabled = _coding_rules_body(root, cfg)
    text = text.replace(_CODING_RULES_MARKER, body.rstrip("\n"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(text, encoding="utf-8")
    summary = ", ".join(enabled) if enabled else "(none detected)"
    return f"{label}: created — sets enabled: {summary}", True


def enable_coding_sets(root: Path, requested: set[str], plan: bool) -> tuple[list[str], list[str], list[str]]:
    """Check the given coding rule sets — plus whatever their `requires:` pulls in — in an
    *already-existing* docs/project/coding_rules.md, adding each newly-checked set's group
    checkbox lines the same way `_coding_rules_body()` does for init's own detection. Used by
    `adopt_config.py` (T62 I2) to apply an old project's `Coding-Guidelines` value onto a file
    init.py already materialized (init's own writer never overwrites an existing file, so a set
    the old config named but init's own detection missed — e.g. no `pyproject.toml` yet, or a
    stack hint that didn't mention it — would otherwise stay unchecked forever).

    Returns (sets newly checked by this call, sets from `requested` that were already checked,
    names in `requested` with no matching `.act/coding/<name>.md`). Never overwrites a set that is
    already checked, never touches the file at all under `plan=True` or when there is nothing to
    change, and does nothing (empty, empty, everything unknown) if the project has no
    docs/project/coding_rules.md or no `.act/coding/` to detect sets from at all."""
    dest = root / "docs" / "project" / "coding_rules.md"
    coding_dir = root / ".act" / "coding"
    if not coding_dir.is_dir():
        return [], [], sorted(requested)
    all_names = {p.stem for p in coding_dir.glob("*.md")}
    known = {name for name in requested if name in all_names}
    unknown = sorted(requested - known)
    if not dest.is_file() or not known:
        return [], [], unknown

    templates = {name: rules.parse_template_set(coding_dir / f"{name}.md", "template") for name in all_names}
    closure = set(known)
    changed = True
    while changed:
        changed = False
        for name in list(closure):
            for required in templates[name].requires:
                if required in templates and required not in closure:
                    closure.add(required)
                    changed = True

    project = rules.parse_project_file(dest, rules.AREAS["coding"])
    by_name = {Path(rules.strip_template_prefix(pset.path)).stem: pset for pset in project.sets}
    already = sorted(name for name in known if name in by_name and by_name[name].enabled)
    to_enable = {name: by_name[name] for name in closure if name in by_name and not by_name[name].enabled}
    if not to_enable:
        return [], already, unknown
    if plan:
        return sorted(to_enable), already, unknown

    lines = dest.read_text(encoding="utf-8").splitlines()
    # Process bottom-up so an earlier insertion never shifts the recorded line number of a set
    # still waiting to be enabled.
    for name in sorted(to_enable, key=lambda n: to_enable[n].line, reverse=True):
        idx = to_enable[name].line - 1
        lines[idx] = rules.coding_set_line(re.sub(r"\[\s\]", "[x]", lines[idx], count=1))  # T64: + import
        group_lines = [f"  - [x] `{gid}`" for gid in templates[name].groups]
        lines[idx + 1:idx + 1] = group_lines
    _write_new_file(dest, "\n".join(lines) + "\n")
    return sorted(to_enable), already, unknown


# ---------------------------------------------------------------------------
# Step 6 helper — skill copies (.act/skills/<name>/** -> project copies)
# ---------------------------------------------------------------------------

# Destination root -> tool gate, one entry per skills folder a copy can land in. A gate is either
# a single tool id, a tuple of tool ids (active once any one of them is configured), or None
# (always written, no project has that today). ".agents/skills" is the tool-neutral mirror read
# by every listed tool's own skill loader except claude-code (which has ".claude/skills" instead)
# — confirmed in .github/README.md: "read the same way by Codex, Copilot, Gemini CLI, and Cursor". A
# further tool that reads it needs its id added to that tuple; a further tool with its own skills
# folder needs one more line here, nothing else — copy_targets() below stays unchanged.
SKILL_TARGET_DIRS: list[tuple[str, Optional[Union[str, tuple[str, ...]]]]] = [
    (".claude/skills", "claude-code"),
    (".agents/skills", ("codex", "copilot", "gemini", "cursor")),
]


def _skill_target_active(tool_gate: Optional[Union[str, tuple[str, ...]]], tools: list[str]) -> bool:
    """Whether a SKILL_TARGET_DIRS entry's tool gate is satisfied by the project's configured
    `tools` (docs/ai/config.md § Project): None is always active, a single tool id must be
    present, a tuple of ids needs at least one of them present. Both sides go through
    actlib.normalize_tool() first, so a `tools` value written in a variant spelling
    (.act/tiers.json's now-retired "codex-cli"/"copilot-cli"/"gemini-cli", say) still matches this
    module's own canonical gate ids instead of silently producing no .agents/skills/ at all (F10,
    T60)."""
    normalized_tools = {actlib.normalize_tool(t) for t in tools}
    if tool_gate is None:
        return True
    if isinstance(tool_gate, str):
        return actlib.normalize_tool(tool_gate) in normalized_tools
    return any(actlib.normalize_tool(t) in normalized_tools for t in tool_gate)


_SKILLS_NOT_COPIED = {"act-adopt"}  # runs only from the template checkout itself (backlog B118#11)


def copy_targets(root: Path, tools: list[str]) -> dict[str, Path]:
    """Every skill-copy destination -> its source file, for the given tools. Enumerates
    .act/skills/<name>/** dynamically — a subdirectory is a skill, a plain file right under
    .act/skills/ (such as README.md) is not — so adding a skill needs no change here. Each file
    gets one destination per SKILL_TARGET_DIRS entry whose tool gate passes, so a skill lands in
    every configured tool's own skills folder plus the tool-neutral .agents/ mirror.

    `_SKILLS_NOT_COPIED` is the one exception: act-adopt only makes sense pointed at the template
    checkout it adopts *into* a project, so a copy landing inside that same project would never
    run correctly -- it stays template-only, never materialized as a project skill.

    A project override at docs/ai/local/skills/<name>/<file> wins over the template's own copy of
    that file (actlib.resolve(), same rule as everywhere else in this template) — the returned
    source path is the resolved one, not necessarily the .act/ file.

    Deliberately does *not* enumerate a project's own skill (a docs/ai/local/skills/<name>/
    directory with no .act/skills/<name> counterpart) — unlike a role bridge (see
    agent_bridge_targets()), a skill copy's legitimacy in doctor.py's check_duplicate_units() comes
    from being recorded in .act-lock.json's "copies", not from this function alone; two hand-placed
    files of the same name with no such record is exactly the mistake that check exists to catch
    (T25a). `act-load-settings` writes both the docs/ai/local/ file and its .claude/.agents/ copies
    itself (settings_load.py's write_unit_bridges()), recording the copy in the lock as it goes —
    this function is not in that path."""
    skills_dir = root / ".act" / "skills"
    targets: dict[str, Path] = {}
    if not skills_dir.is_dir():
        return targets
    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        if skill_dir.name in _SKILLS_NOT_COPIED:
            continue
        for src in sorted(skill_dir.rglob("*")):
            if not src.is_file():
                continue
            rel = src.relative_to(skills_dir).as_posix()  # "<name>/<file>"
            resolved = actlib.resolve(f"skills/{rel}")
            source_path = resolved[0] if resolved is not None else src
            for dest_root, tool_gate in SKILL_TARGET_DIRS:
                if not _skill_target_active(tool_gate, tools):
                    continue
                targets[f"{dest_root}/{rel}"] = source_path
    return targets


# ---------------------------------------------------------------------------
# Step 6 helper — role bridges (.act/agents/<name>.md + .act/bridges/agents/<name>.md -> project)
# ---------------------------------------------------------------------------

def agent_bridge_targets(root: Path, tools: list[str]) -> dict[str, Path]:
    """Every role-bridge destination -> its .act/bridges/agents/ source, for the given tools.
    Enumerates .act/agents/<name>.md role files dynamically (README.md is documentation, not a
    role) and only includes a role once its bridge under .act/bridges/agents/ exists too — a role
    with no bridge yet has nothing written. Only "claude-code" has a bridge format today; a tool
    without one is simply never a target.

    Unlike copy_targets(), the destination file is never replaced once written (see
    step_materialize below and update.py's step 6): init creates it once, update only adds bridges
    for roles new since the last run, and an existing bridge is the project's own from that point
    on — R-role-worker forbids `Agent`/`Task` in a role's own `tools` frontmatter, so the body
    below the frontmatter never needs to change after the fact. The one exception, handled by
    write_agent_bridge_file() below rather than here, is the `model`/`effort` frontmatter pair
    itself: re-derived from `.act/tiers.json`/`docs/ai/config.md` § Roles on every `update` and at
    every session start (see tiers.py's refresh_project_bridge_frontmatter()).

    A project's *own* role — a docs/ai/local/agents/<name>.md file with no .act/agents/<name>.md
    counterpart, e.g. one `act-load-settings` just wrote from an imported settings file — is a
    target here too, straight from that file: unlike a template role it has no separate rules file
    to reference, so the docs/ai/local/ file itself doubles as its own bridge source (already
    frontmatter + body, see write_agent_bridge_file()). A name that matches a template role instead
    is that role's docs/ai/local/ override (a different file shape — plain rules text, no
    frontmatter) and is not a bridge source in its own right — and neither is a name matching a
    template role's generated "-high" variant (agent_bridge_variant_targets() below), reserved the
    same way and compared case-insensitively, so an own role can never alias what should be a
    template variant's bridge target."""
    agents_dir = root / ".act" / "agents"
    bridges_dir = root / ".act" / "bridges" / "agents"
    targets: dict[str, Path] = {}
    if "claude-code" not in tools:
        return targets
    template_role_names: set[str] = set()
    if agents_dir.is_dir():
        for role_path in sorted(agents_dir.glob("*.md")):
            if role_path.name.lower() == "readme.md":
                continue
            template_role_names.add(role_path.stem)
            bridge_src = bridges_dir / role_path.name
            if bridge_src.is_file():
                targets[f".claude/agents/{role_path.name}"] = bridge_src

    # Case-insensitive, and reserved for a template role's generated "-high" variant name too
    # (agent_bridge_variant_targets() below writes ".claude/agents/<role>-high.md" for those) —
    # otherwise a docs/ai/local/agents/<role>-high.md would slip through as an "own role" here
    # and end up aliased onto what should be the template variant's bridge target instead
    # (confirmed 2026-09-22, review of T24).
    reserved_role_names = {name.lower() for name in template_role_names}
    reserved_role_names |= {f"{name}-high" for name in reserved_role_names}

    local_agents_dir = root / "docs" / "ai" / "local" / "agents"
    if local_agents_dir.is_dir():
        for role_path in sorted(local_agents_dir.glob("*.md")):
            if role_path.name.lower() == "readme.md":
                continue
            if role_path.stem.lower() in reserved_role_names:
                continue  # the role's docs/ai/local/ override, or a reserved "-high" name, not an own role's bridge source
            targets[f".claude/agents/{role_path.name}"] = role_path
    return targets


def agent_bridge_variant_targets(root: Path, tools: list[str]) -> dict[str, Path]:
    """Every applicable role's "-high" variant destination -> the same .act/bridges/agents/
    source agent_bridge_targets() uses for its base file — the runtime choice of "give this one
    assignment more reasoning" without ever writing a real model ID into an assignment
    (`Q71`). Only a role whose template bridge declares a
    `tier`/`reasoning` pair gets one (an older or hand-authored bridge with a fixed
    `model:` and no `tier:` already has nothing to bump); skipped outright for `tier: expert` or a `reasoning`
    already at the top of the tool's reasoning scale — one step further does not exist there."""
    base_targets = agent_bridge_targets(root, tools)
    if not base_targets:
        return {}
    tiers_data = tiers.load_tiers(root)
    overrides = tiers.read_role_overrides(root)
    scale = (tiers_data.get("claude-code") or {}).get("reasoning_scale") or []
    targets: dict[str, Path] = {}
    for dest_rel, bridge_src in base_targets.items():
        role = Path(dest_rel).stem
        tmpl_fields, _, _ = tiers.split_frontmatter(bridge_src.read_text(encoding="utf-8"))
        if "tier" not in tmpl_fields:
            continue
        template_tier = tmpl_fields.get("tier", "")
        template_reasoning = tmpl_fields.get("reasoning", "")
        # the *effective* tier/reasoning (a project's own override wins, same as
        # effective_model_effort() would apply) decides whether a further bump makes sense — a
        # role overridden to reasoning "max" needs no "-high" file even if the template's own
        # default is lower, and a fixed-model override has no "tier" to be "expert" about.
        override = overrides.get(role, {})
        effective_tier = override.get("tier", template_tier)
        effective_reasoning = override.get("reasoning", template_reasoning)
        if "model" not in override and effective_tier == "expert":
            continue
        if scale and effective_reasoning == scale[-1]:
            continue
        targets[f".claude/agents/{role}-high.md"] = bridge_src
    return targets


def _write_new_file(dest: Path, text: str) -> None:
    """Write a brand-new file with `\\n` line endings, regardless of platform default -- unlike
    `Path.write_text(..., newline=...)` (Python 3.10+), `open()`'s own `newline` parameter has
    always accepted this, so this stays usable on this project's older Python floor too."""
    with open(dest, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def write_agent_bridge_file(
    role: str, bridge_src: Path, dest: Path, plan: bool, root: Path,
    tiers_data: dict, overrides: dict[str, dict[str, str]], variant: bool,
    notes: Optional[list[str]] = None,
) -> tuple[str, bool]:
    """Like _write_copy_file, but for a role bridge (base or "-high" variant): resolves the
    .act/bridges/agents/<role>.md template's `tier`/`reasoning` frontmatter into a concrete
    `model`/`effort` pair via tiers.py instead of copying bytes verbatim. A bridge that already
    carries a fixed `model:` (no `tier:` field — an older or hand-authored bridge) has
    nothing to resolve and is copied verbatim, same as before. A variant additionally gets its
    `name`/`description` reworded for the "-high" file and a `variant-of: <role>` frontmatter field
    -- the one thing that later tells tiers.py's refresh (and this module's own
    agent_bridge_variant_targets(), indirectly, via the destination already existing) that this
    particular "...-high.md" really is a template-generated bump, not a project's own role that
    merely happens to share the suffix. Never overwrites an existing project file, same contract as
    every other generated file here. A freshly created file always gets `\\n` line endings,
    regardless of platform -- see tiers.py's refresh, which instead preserves whatever a file
    already has once one exists. `notes`, if given, collects one message (deduplicated) whenever
    tiers.json/config.md leave `model`/`effort` unresolvable for a *reportable* reason (see
    resolve_tier()); the older-bridge/unresearched-tool cases stay silent, same as before.
    Returns (message, created)."""
    label = _relative_label(dest, root)
    if dest.is_file():
        return f"{label}: already present, left unchanged", False
    if plan:
        return f"{label}: would create", False
    bridge_text = bridge_src.read_text(encoding="utf-8")
    tmpl_fields, _, _ = tiers.split_frontmatter(bridge_text)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if "tier" not in tmpl_fields:
        _write_new_file(dest, bridge_text)
        return f"{label}: created", True
    template_tier = tmpl_fields.get("tier", "")
    template_reasoning = tmpl_fields.get("reasoning", "")
    model, effort, problem, eff_tier, eff_reasoning = tiers.effective_model_effort(
        root, role, template_tier, template_reasoning, tiers_data, overrides,
        tool="claude-code", bump_variant=variant,
    )
    if model is None:
        _write_new_file(dest, bridge_text)
        if problem and notes is not None:
            message = tiers.describe_unresolved_tier(role, "claude-code", eff_tier, eff_reasoning, problem)
            if message not in notes:
                notes.append(message)
        return f"{label}: created (tier/reasoning left unresolved)", True
    text = tiers.render_generated_bridge(bridge_text, model, effort)
    if variant:
        fields, body, order = tiers.split_frontmatter(text)
        if "name" in fields:
            fields["name"] = f"{role}-high"
        if "description" in fields:
            fields["description"] = f"Same as {role}, one reasoning step higher - use only when named explicitly."
        fields["variant-of"] = role
        if "variant-of" not in order:
            insert_at = order.index("name") + 1 if "name" in order else len(order)
            order = order[:insert_at] + ["variant-of"] + order[insert_at:]
        text = tiers.render_frontmatter(fields, order, body)
    _write_new_file(dest, text)
    return f"{label}: created", True


def _copy_source_label(root: Path, src: Path) -> str:
    """Project-relative path for a copy's "source" field in .act-lock.json — usually under
    .act/ (e.g. ".act/skills/probe-skill/SKILL.md"), or under docs/ai/local/ when the project
    overrides that file (actlib.resolve(), see copy_targets() above)."""
    return src.relative_to(root).as_posix()


def _write_copy_file(src: Path, dest: Path, plan: bool, root: Optional[Path] = None) -> tuple[str, bool]:
    """Like _write_text_file, but copies bytes verbatim (no token substitution — a skill or role
    bridge is authored complete under .act/ already) and never overwrites an existing project
    file. Used for skill copies and role bridges alike. Returns (message, created)."""
    label = _relative_label(dest, root)
    if dest.is_file():
        return f"{label}: already present, left unchanged", False
    if plan:
        return f"{label}: would create", False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())
    return f"{label}: created", True


# ---------------------------------------------------------------------------
# Step 6 — materialize skeleton + selected bridges
# ---------------------------------------------------------------------------

def _config_tokens(cfg: ProjectConfig) -> dict[str, str]:
    return {
        "<name>": cfg["name"],
        "<owner>": cfg["owner"],
        "<language-chat>": cfg["language_chat"],
        "<language-docs>": cfg["language_docs"],
        "<stack>": cfg["stack"],
        "<lint-command>": cfg["lint_cmd"] or "(not set)",
        "<typecheck-command>": cfg["typecheck_cmd"] or "(not set)",
        "<test-command>": cfg["test_cmd"] or "(not set)",
        "<tool-list>": ", ".join(cfg["tools"]) or "(none)",
        "<mode>": cfg["mode"],
        # Used by .act/bridges/docs-readme.md's "Data as of" column — the day the index itself
        # (and the files it lists) was first written, not a live-updating value.
        "<today>": date.today().isoformat(),
        # .act/skeleton/config.md § Feedback's `feedback` row (T58) — defaults to "off" via
        # ProjectConfig["feedback_mode"] itself (_ask_feedback_mode's every return path).
        "<feedback-mode>": cfg["feedback_mode"],
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
    """Merges src's hook entries into dest (see actlib.merge_settings_hooks): an entry the bridge
    already defines is replaced in place (a changed timeout/matcher/command never ends up as a
    second, duplicate entry), one the bridge no longer defines is removed, and anything the
    project added itself is left untouched. Idempotent — a second run against its own output
    reports no change and leaves the file byte-for-byte identical (T46)."""
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
    if not actlib.is_valid_hooks_container(current):
        # hooks: null, settings.json itself not an object, an entry that isn't one, ... -- never
        # attempted, never a traceback; --catch-up must not fail permanently on this (T46 review
        # finding 6).
        return f"{_relative_label(dest, root)}: not a valid hooks structure, left unchanged", False
    new_current, changed_events = actlib.merge_settings_hooks(current, bridge_data)
    if not changed_events:
        return f"{_relative_label(dest, root)}: hook entries already up to date, left unchanged", False
    if plan:
        return f"{_relative_label(dest, root)}: would add/update hook entries for {', '.join(changed_events)}", False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(new_current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return f"{_relative_label(dest, root)}: hook entries added/updated ({', '.join(changed_events)})", True


def step_materialize(
    root: Path, plan: bool, cfg: ProjectConfig, selected_bridges: dict[str, BridgeSpec],
    notes: Optional[list[str]] = None,
) -> tuple[list[str], dict[str, Path], list[Path], dict[str, dict]]:
    tokens = _config_tokens(cfg)
    bridges_dir = root / ".act" / "bridges"
    skeleton_dir = root / ".act" / "skeleton"
    messages: list[str] = []
    generated: dict[str, Path] = {}  # bridge name -> written path, for cache.json hashing
    touched: list[Path] = []
    copies: dict[str, dict] = {}  # dest -> {"source", "sha256"}, for .act-lock.json § copies

    for src_name, dest_rel in skeleton_files(skeleton_dir):
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
        elif spec["kind"] == "coding-rules":
            message, created = _write_coding_rules(bridges_dir / key, dest, cfg, plan, root)
            messages.append(message)
            if created:
                generated[spec["dest"]] = dest
            if created or dest.is_file():
                touched.append(dest)
        elif spec["kind"] == "docs-index":
            # Same write path as "verbatim" (never overwrites, token substitution), but not added
            # to `generated` — see the BRIDGES comment above for why. Two things a "verbatim"
            # bridge does not need to guard against: (1) `--target` docking onto a project whose
            # own, older `.act/` predates this bridge (it keeps its own `.act/`, never re-copied —
            # see main()'s "already present in target, left unchanged") has no
            # `.act/bridges/docs-readme.md` to read from at all; skip with a message instead of
            # crashing (review finding T59#4). (2) unlike the others, only mark it `touched` when
            # this run actually created it — `dest.is_file()` alone would sweep a project's own,
            # already-existing (and possibly uncommitted) docs/README.md into this run's commit
            # even though nothing here changed it (review finding T59#5; the same
            # already-exists-so-touched pattern on the other bridges is intentional there and left
            # alone, see the review's own note).
            src = bridges_dir / key
            if not plan and not src.is_file():
                # Under --plan, .act/ itself is never actually copied into a not-yet-existing
                # target (see main()'s "would copy .act/ into target"), so `src` legitimately
                # doesn't exist yet even for a project that *will* have it -- only check for real.
                messages.append(f"{_relative_label(dest, root)}: no {key} under this project's .act/bridges/ yet (older template) — skipped")
            else:
                message, created = _write_text_file(src, dest, tokens, plan, root)
                messages.append(message)
                if created:
                    touched.append(dest)

    for dest_rel, src in copy_targets(root, cfg["tools"]).items():
        dest = root / dest_rel
        message, created = _write_copy_file(src, dest, plan, root)
        messages.append(message)
        if created or dest.is_file():
            touched.append(dest)
        if not plan and dest.is_file():
            copies[dest_rel] = {"source": _copy_source_label(root, src), "sha256": actlib.sha256_file(dest)}

    tiers_data = tiers.load_tiers(root)
    overrides = tiers.read_role_overrides(root)

    for dest_rel, src in agent_bridge_targets(root, cfg["tools"]).items():
        role = Path(dest_rel).stem
        message, created = write_agent_bridge_file(
            role, src, root / dest_rel, plan, root, tiers_data, overrides, False, notes,
        )
        messages.append(message)
        if created or (root / dest_rel).is_file():
            touched.append(root / dest_rel)

    for dest_rel, src in agent_bridge_variant_targets(root, cfg["tools"]).items():
        role = Path(dest_rel).stem[: -len("-high")]
        message, created = write_agent_bridge_file(
            role, src, root / dest_rel, plan, root, tiers_data, overrides, True, notes,
        )
        messages.append(message)
        if created or (root / dest_rel).is_file():
            touched.append(root / dest_rel)

    return messages, generated, touched, copies


# ---------------------------------------------------------------------------
# Step 7 — .gitattributes / .gitignore
# ---------------------------------------------------------------------------

def _append_block(dest: Path, src: Path, plan: bool) -> tuple[str, bool]:
    """Appends whatever lines of src's template block are missing from dest (see
    actlib.merge_text_block) — not just the whole block once, so a project that already has an
    older subset of it (created before a later template revision added a line) gets just the new
    lines instead of staying stuck on what init.py wrote at creation time (T46). Only lines new
    *since* the state this project last applied are ever considered (.act-lock.json §
    bridges_applied[dest.name], refreshed here on every non-plan run) — a project with no such
    record yet (pre-T46-tracking) falls back to "add whatever is missing" once, same as before
    (T46 review finding 4). A candidate conflicting with the project's own line (a gitignore `!x`
    negation, or a .gitattributes line already attributing the same pattern differently) is never
    applied, only named in the summary."""
    if plan and not src.is_file():
        # --target --plan against a not-yet-created directory may not even have .act/ copied
        # yet, so the source block is read lazily, only once we know a write would happen.
        return f"{dest.name}: would append template block", False
    block_text = src.read_text(encoding="utf-8")
    existing = dest.read_text(encoding="utf-8") if dest.is_file() else ""
    lock = actlib.read_lock()
    bridges_applied = dict(lock.get("bridges_applied", {}))
    applied_lines = bridges_applied.get(dest.name)
    new_text, added = actlib.merge_text_block(existing, block_text, applied_lines)
    conflicts = actlib.text_block_conflicts(existing, block_text, applied_lines)
    suffix = f"; {len(conflicts)} conflicting line(s) kept as-is: {', '.join(conflicts)}" if conflicts else ""
    if plan:
        if not added:
            return f"{dest.name}: already present, left unchanged{suffix}", False
        return f"{dest.name}: would add {len(added)} missing line(s){suffix}", False
    bridges_applied[dest.name] = block_text.splitlines()
    actlib.write_lock({"bridges_applied": bridges_applied})
    if not added:
        return f"{dest.name}: already present, left unchanged{suffix}", False
    dest.write_text(new_text, encoding="utf-8")
    label = "template block appended" if not existing else f"{len(added)} missing line(s) added"
    return f"{dest.name}: {label}{suffix}", True


def step_git_files(root: Path, plan: bool) -> tuple[list[str], list[Path]]:
    act_dir = root / ".act"
    attrs_msg, attrs_changed = _append_block(
        root / ".gitattributes", act_dir / "bridges" / "gitattributes", plan,
    )
    ignore_msg, ignore_changed = _append_block(
        root / ".gitignore", act_dir / "bridges" / "gitignore-lines", plan,
    )
    touched = []
    if attrs_changed or (root / ".gitattributes").is_file():
        touched.append(root / ".gitattributes")
    if ignore_changed or (root / ".gitignore").is_file():
        touched.append(root / ".gitignore")
    return [attrs_msg, ignore_msg], touched


# ---------------------------------------------------------------------------
# Step 8 — template's own files (README / LICENSE)
# ---------------------------------------------------------------------------

# First line of a README the template wrote for itself -- .github/README.md (GitHub's landing
# page, has precedence over the root one) and the root README.md before a project replaces it.
# Absent, this file is the project's own and step 8 never touches it, interactive or not. The
# marker alone is *not* enough to act on the file, though (see _retire_template_readme below): it
# only says the file started as the template's; whether it still matches the template is checked
# separately, so an edit made after the marker was written is never silently discarded (rev56/loss).
TEMPLATE_README_MARKER = "<!-- act:template-readme -->"


def _has_template_readme_marker(path: Path) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.readline().strip() == TEMPLATE_README_MARKER
    except OSError:
        return False


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _git_show_at_commit(root: Path, commit: str, rel_path: str) -> Optional[str]:
    """Text of `rel_path` as it was at `commit` in this checkout's own history (still readable at
    step 8 even after step 2's orphan-branch move -- the commit itself is untouched, only what a
    branch points at changes), or None if that cannot be determined: no commit yet (a fresh `git
    init`), the file did not exist there, or git failed for some other reason. Callers treat None
    as "unverifiable", never as "different"."""
    if not commit:
        return None
    result = _git(["show", f"{commit}:{rel_path}"], cwd=root, check=False)
    if result.returncode != 0:
        return None
    return result.stdout


def _retire_template_readme(
    root: Path, plan: bool, rel_path: str, template_commit: str, backup_name: str,
    notes: list[str], on_verified_match,
) -> str:
    """Shared decision for one template-owned README (.github/README.md or the root README.md):
    the marker alone only says the file *started* as the template's; only removing/replacing it
    outright once its current content still matches the template's own version at `template_commit`
    byte-for-byte (line endings normalised) is safe -- a project that kept editing the file after
    cloning (marker survives, text changed) would otherwise lose that edit silently the moment
    `init` runs (rev56/loss, HIGH). A mismatch is left alone, with a note for the inbox instead.

    Without a commit to compare against (no repository yet, so nothing to diff), falls back to the
    marker alone like before T56's review -- but only after backing the current content up to
    `.act-local/<backup_name>` first, so a false positive (an edit the marker happened to survive)
    stays recoverable instead of gone.

    `on_verified_match(plan) -> str` performs the actual remove/replace once content-equality (or
    the no-history fallback) has cleared it, and returns its own step-8 message."""
    path = root / rel_path
    if not path.is_file():
        return f"no {rel_path} present"
    if not _has_template_readme_marker(path):
        return f"{rel_path} left untouched (project's own)"

    current_text = path.read_text(encoding="utf-8")
    template_text = _git_show_at_commit(root, template_commit, rel_path)

    if template_text is not None:
        if _normalize_newlines(template_text) == _normalize_newlines(current_text):
            return on_verified_match(plan)
        short_commit = template_commit[:12]
        note = f"{rel_path} was edited after cloning (differs from the template's version at {short_commit}) -- kept, review manually."
        if note not in notes:
            notes.append(note)
        return f"{rel_path} kept (content differs from the template's version, left for review)"

    if not plan:
        backup = root / ".act-local" / backup_name
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.is_file():
            backup.write_text(current_text, encoding="utf-8")
    note = f"{rel_path}: no template commit to verify against -- acted on the marker alone; previous content saved to .act-local/{backup_name}."
    if note not in notes:
        notes.append(note)
    return on_verified_match(plan)


def _step_own_readmes(
    root: Path, plan: bool, cfg: ProjectConfig, template_commit: str, notes: list[str]
) -> list[str]:
    def remove_github_readme(plan: bool) -> str:
        github_readme = root / ".github" / "README.md"
        github_dir = github_readme.parent
        if plan:
            others = [p for p in github_dir.iterdir() if p != github_readme]
            if not others:
                return ".github/README.md would be removed (template's own), .github/ would be removed (now empty)"
            return ".github/README.md would be removed (template's own)"
        github_readme.unlink()
        try:
            now_empty = not any(github_dir.iterdir())
        except OSError:
            now_empty = False
        if now_empty:
            github_dir.rmdir()
            return ".github/README.md removed (template's own), .github/ removed (now empty)"
        return ".github/README.md removed (template's own)"

    def replace_root_readme(plan: bool) -> str:
        if plan:
            return "README.md would be replaced with a project skeleton"
        src = root / ".act" / "bridges" / "project-readme.md"
        text = src.read_text(encoding="utf-8")
        for token, value in _config_tokens(cfg).items():
            text = text.replace(token, value)
        if cfg["owner"] == "unknown":
            text = text.replace("Maintained by unknown.\n\n", "")
        _write_new_file(root / "README.md", text)
        return "README.md replaced with a project skeleton"

    return [
        _retire_template_readme(
            root, plan, ".github/README.md", template_commit,
            "github-README.template.md", notes, remove_github_readme,
        ),
        _retire_template_readme(
            root, plan, "README.md", template_commit,
            "README.template.md", notes, replace_root_readme,
        ),
    ]


def step_own_files(
    root: Path, plan: bool, interactive: bool, cfg: ProjectConfig, template_commit: str, notes: list[str]
) -> str:
    parts = _step_own_readmes(root, plan, cfg, template_commit, notes)

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

def step_lock_and_cache(
    root: Path, plan: bool, template_origin: str, template_commit: str,
    generated: dict[str, Path], copies: dict[str, dict],
) -> str:
    version, disk_commit = _read_version_file(root)
    # Prefer the commit read straight from the template checkout's own git history
    # (step_git_in_place/step_git_target); .act/VERSION's "commit=" line is only the fallback for
    # when there is no git to read it from at all.
    commit = template_commit or disk_commit
    if not commit:
        # Neither source had one this time (e.g. a re-run, possibly after --no-commit, where the
        # running checkout's own HEAD/.act/VERSION momentarily can't be read) -- never blank out a
        # commit an earlier, successful run already recorded (review finding T58#7). Read the lock
        # file directly by path instead of via actlib.read_lock()/repo_root(): this function is
        # handed `root` explicitly and must not depend on the process's current working directory.
        try:
            existing_lock = json.loads((root / ".act-lock.json").read_text(encoding="utf-8"))
            commit = ((existing_lock.get("template") or {}).get("commit") or "") or commit
        except (OSError, json.JSONDecodeError):
            pass
    manifest_hash = ""
    if not plan:
        # The baseline update.py checks .act/ against: without it, a hand edit under .act/ would
        # go unnoticed and be overwritten by the first update. Written before the lock below so
        # its hash (manifest_sha256) can go in the same lock write, not a second one (Q73a: this
        # is the fingerprint dispatch.py compares against to notice a project .act/ that came from
        # somewhere other than update.py, e.g. a plain `git pull` of the shared history).
        manifest.write_manifest(root / ".act")
        manifest_hash = manifest.manifest_fingerprint(root / ".act")
        # "copies" holds every skill-copy destination materialized in step 6 (copy_targets()),
        # each with its .act/ (or docs/ai/local/ override) source and sha256 — update.py's step 6
        # compares against this hash to tell an unchanged copy from one the project edited. Role
        # bridges (agent_bridge_targets()) are not tracked here: they are never replaced once
        # written, so there is nothing to compare against later.
        actlib.write_lock({
            "template": {"version": version, "commit": commit, "source": template_origin, "manifest_sha256": manifest_hash},
            "copies": copies,
            # present from the start, so a later "nothing changed" never has to add it (T60, G1)
            "removed_by_user": list(actlib.read_lock().get("removed_by_user", [])),
        })
        # .act-lock.json § applied (T60, G1): the values the files just materialized hang on, so the
        # first session start has a snapshot to compare against instead of writing the lock itself.
        # Best-effort — without it, the next update.py run records one.
        try:
            import update as _update
            _update.record_applied(root)
        except Exception:
            pass
    hashes = {rel: actlib.sha256_file(path) for rel, path in generated.items() if path.is_file()}
    if not plan:
        actlib.write_cache({"generated": hashes})
    return (
        f"lock written (version '{version}'), {len(copies)} skill-copy hash(es), "
        f"cache with {len(hashes)} generated bridge(s), MANIFEST.json written"
    )


# ---------------------------------------------------------------------------
# Step 10 — first commit, by pathspec
# ---------------------------------------------------------------------------

def step_commit(root: Path, plan: bool, no_commit: bool, paths: list[Path]) -> str:
    if no_commit:
        # Returns before any `git add`, so nothing is staged either -- say so plainly instead of
        # the previous, inaccurate "staged/unstaged" (review finding T58#7).
        return "would leave uncommitted (--no-commit, nothing staged)" if plan else "left uncommitted (--no-commit, nothing staged)"
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
# Inbox note for a docs scaffold that stays English (T61, `R-work-language`)
# ---------------------------------------------------------------------------

def step_translate_note(root: Path, plan: bool, cfg: ProjectConfig) -> tuple[Optional[Path], str]:
    """With a docs language other than English, the scaffold just written still carries the
    template's English text and its `act:default` mark — init has no model to translate it, so it
    leaves one inbox entry asking for that instead. Reads the language from the config.md actually
    on disk (docking onto a project keeps its own), falling back to the answer from step 1."""
    config_path = root / "docs" / "ai" / "config.md"
    docs_language = cfg["language_docs"]
    if not plan and config_path.is_file():
        docs_language = actlib.language_settings(actlib.read_config())[1]
    if actlib.is_english(docs_language):
        return None, ""
    if plan and not (root / "docs").is_dir():
        return None, f"would note in the inbox: translate the docs scaffold into {docs_language}"
    dest = actlib.write_translate_note(root, docs_language, plan)
    if dest is None:
        return None, f"docs scaffold: no `act:default` file left, or a translation entry exists ({docs_language})"
    verb = "would create" if plan else "created"
    return dest, f"{_relative_label(dest, root)}: {verb} (docs scaffold still English, translate into {docs_language})"


# ---------------------------------------------------------------------------
# Inbox note for open points
# ---------------------------------------------------------------------------

# Markers of an existing project (its own docs, or another AI tool's files) that init.py itself
# never merges -- act-adopt does that (backlog B118#9). Checked in --target mode only: in-place
# runs happen inside the template checkout itself, which has none of these yet.
_ADOPT_HINT_MARKERS = ("docs", "AGENTS.md", "CLAUDE.md", ".claude", "AI-CONFIG.md")


def _existing_project_hint(root: Path) -> str | None:
    found = [name for name in _ADOPT_HINT_MARKERS if (root / name).exists()]
    if not found:
        return None
    return (
        f"  target already has {', '.join(found)} -- see act-adopt to fold an existing project's "
        "docs/AI-tool files in instead of starting from a bare skeleton"
    )


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
    # Step output can carry an em dash (e.g. the coding-rules summary in step 6); on Windows,
    # stdout/stderr otherwise default to the console's legacy code page instead of UTF-8, which
    # would corrupt it. Same fix as .act/scripts/rules.py.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(description="Turn a template checkout into a project, or dock onto an existing directory.")
    parser.add_argument("--target", help="create/dock in this directory instead of the current checkout")
    parser.add_argument("--plan", action="store_true", help="show what would happen, change nothing")
    parser.add_argument("--non-interactive", action="store_true", help="never prompt; take defaults, log open points to the inbox")
    parser.add_argument("--no-commit", action="store_true", help="do everything except the final commit")
    parser.add_argument("--language-docs", metavar="CODE",
                        help="language of docs/ (e.g. de) instead of asking; default en (R-work-language)")
    parser.add_argument("--language-chat", metavar="CODE",
                        help="chat language (a code, or auto = follow the owner's messages) instead of asking")
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
        else:
            hint = _existing_project_hint(root)
            if hint:
                print(hint)
        act_dest = root / ".act"
        if act_dest.resolve() != source_act.resolve():
            if act_dest.exists():
                print("  .act/ already present in target, left unchanged")
            else:
                print("  copying .act/ into target" + (" (plan)" if plan else ""))
                if not plan:
                    shutil.copytree(source_act, act_dest,
                                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
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

    cfg = step_config(root, interactive, notes,
                      {"language-docs": args.language_docs, "language-chat": args.language_chat})
    # `--plan` never prompts (`interactive` above is already False for it), so `feedback_mode` is
    # always "off" here even when a real (non-plan) run at a real terminal would ask -- say that
    # honestly instead of implying "off" is the actual answer (review finding T58#8). Docking
    # `--target` onto a project that already has docs/ai/config.md is unaffected: it would not ask
    # either way (see _ask_feedback_mode), so no relabeling there.
    feedback_display = repr(cfg["feedback_mode"])
    if plan and actlib.is_interactive() and not (root / "docs" / "ai" / "config.md").is_file():
        feedback_display = "'would ask (interactive)'"
    _print_step(
        1,
        f"config: name={cfg['name']!r}, owner={cfg['owner']!r}, language-chat={cfg['language_chat']!r}, "
        f"language-docs={cfg['language_docs']!r}, "
        f"stack={cfg['stack']!r}, tools={cfg['tools']}, mode={cfg['mode']!r}, "
        f"feedback={feedback_display} (suggested, change it in docs/ai/config.md)",
    )

    if is_target:
        summary, template_origin, template_commit = step_git_target(root, plan, source_act)
        _print_step(2, summary)
    else:
        summary, template_origin, template_commit = step_git_in_place(root, plan)
        _print_step(2, summary)

    _print_step(3, step_identity(root, plan, interactive, notes))
    _print_step(4, f"{step_workspace_identity(root, plan, cfg['owner'])}; {step_import_folder(root, plan)}")

    selected_bridges, thin_summary = step_thin_bridges(cfg["tools"])
    _print_step(5, thin_summary)

    materialize_messages, generated, touched_bridges, copies = step_materialize(root, plan, cfg, selected_bridges, notes)
    translate_path, translate_message = step_translate_note(root, plan, cfg)
    if translate_message:
        materialize_messages.append(translate_message)
    _print_step(6, "; ".join(materialize_messages))

    gitfiles_messages, touched_gitfiles = step_git_files(root, plan)
    _print_step(7, "; ".join(gitfiles_messages))

    if is_target:
        _print_step(8, "skipped in --target mode (docking onto an existing project, nothing of the template's own to decide)")
    else:
        _print_step(8, step_own_files(root, plan, interactive, cfg, template_commit, notes))

    _print_step(9, step_lock_and_cache(root, plan, template_origin, template_commit, generated, copies))

    inbox_path = _write_inbox_note(root, cfg["owner"], notes, plan)
    commit_paths = [root / ".act", root / ".act-lock.json", *touched_bridges, *touched_gitfiles]
    if inbox_path is not None:
        commit_paths.append(inbox_path)
    if translate_path is not None and not plan:
        commit_paths.append(translate_path)
    _print_step(10, step_commit(root, plan, args.no_commit, commit_paths))

    if notes:
        print(f"[act] done - {len(notes)} open point(s) " + ("would go to" if plan else "left in") + " docs/ai/inbox/")
    else:
        print("[act] done - no open points")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
