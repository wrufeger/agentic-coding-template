#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Turn a checkout of this template into a project ("here, in this clone"), or dock onto
#          an existing/empty directory ("--target"). Ten steps, always in the same order: collect
#          config values, resolve git (origin/branch -- in-place, the old history moves to a
#          'template' branch and 'main' is rebuilt as an orphan; once the first commit below has
#          landed on it, 'template' is deleted outright so nobody can merge it back into 'main',
#          T76/Q101b), check git identity, write the per-checkout workspace identity, thin the
#          bridges down to the chosen tools, materialize skeleton + bridges (plus skill copies and
#          role bridges, see copy_targets()/agent_bridge_targets(); in-place, a root CLAUDE.md/
#          AGENTS.md still carrying the template's own bootstrap marker is replaced by its project
#          bridge here too, see _bootstrap_entry_files/TEMPLATE_BOOTSTRAP_MARKER -- --target never
#          has one to replace), append .gitattributes/.gitignore, retire the template's own
#          README(s) and LICENSE (skipped in --target mode -- nothing of the template's own there
#          to decide, only .act/ was copied in), write the lock/cache state, and make the first
#          commit. Never overwrites a file the project already has; anything that needs a decision
#          but can't be asked (non-interactive run) is written to docs/ai/inbox/ instead of guessed.
#          A `language-docs` other than English leaves the scaffold English (marked `act:default`)
#          plus one inbox entry asking to translate it (R-work-language) — init has no model to do
#          that itself. Stdlib only.
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
from typing import NamedTuple, Optional, TypedDict, Union

import actlib
import manifest
import rules
import security_scan
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


def _remote_tracking_commit(root: Path, remote: str, branch: str) -> Optional[str]:
    """SHA of `<remote>/<branch>` if that remote-tracking ref exists, else None -- must be read
    before `remote` is ever touched (`git remote remove` deletes its tracking refs along with it,
    review HIGH/B142/T76 S1+S3): once gone, there is no way left to tell a plain clone's HEAD apart
    from a HEAD that already carries commits of the project's own."""
    result = _git(["rev-parse", "--verify", "-q", f"refs/remotes/{remote}/{branch}"], cwd=root, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def _commits_ahead_of(root: Path, ref: str) -> Optional[int]:
    """How many commits HEAD has that `ref` lacks -- None (never confused with an actual 0) if the
    count itself could not be read."""
    result = _git(["rev-list", "--count", "HEAD", "--not", ref], cwd=root, check=False)
    if result.returncode != 0:
        return None
    try:
        return int(result.stdout.strip())
    except ValueError:
        return None


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

def _template_dev_checkout_reason(root: Path) -> str:
    """Non-empty reason string if `root` looks like the template's own development checkout,
    never a project to build in place (B130): either the maintainer marker
    '.act-local/template-dev' is present, or 'git worktree list' shows more than one worktree for
    this repository — the template's own dev checkout is routinely one of several worktrees of the
    same repo (e.g. alongside the checkout that became this "next" build). Empty string ("") for a
    plain clone, which proceeds exactly as before."""
    if (root / ".act-local" / "template-dev").exists():
        return "the '.act-local/template-dev' marker is present"
    result = _git(["worktree", "list"], cwd=root, check=False)
    if result.returncode == 0:
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        if len(lines) > 1:
            return f"this repository has {len(lines)} worktrees (git worktree list)"
    return ""


# Files init itself leaves behind in every project it sets up -- .act-lock.json (step 9,
# step_lock_and_cache) and docs/ai/config.md (step 6, materialized from the skeleton) -- and that a
# template clone never has: neither is tracked in the template's own repository (its docs live under
# .act/skeleton/). Either one alone counts: a run with --no-commit, or one that broke off after step
# 6, has the config file on disk but no lock yet.
_SET_UP_PROJECT_MARKERS = (".act-lock.json", "docs/ai/config.md")


def _set_up_project_reason(root: Path) -> str:
    """Non-empty reason string if `root` is a project that already went through init -- an in-place
    run (no --target) must refuse there, see main() (T76 wave D review, round 2: step 2 would rename
    the project's branch to 'template' and rebuild 'main' as an orphan, the B130 check above never
    covers a project). "" for a plain clone or a directory init has never touched."""
    found = [name for name in _SET_UP_PROJECT_MARKERS if (root / name).is_file()]
    if not found:
        return ""
    return f"this is already a set-up project ({' and '.join(found)} present)"


class GitInPlaceResult(NamedTuple):
    """Return shape of step_git_in_place -- a plain tuple used to read like keyword arguments at
    both ends (review HIGH/B142/T76 S1+S3 added the last three fields, see below)."""
    summary: str
    template_source: str
    template_commit: str
    orphan_rebuilt: bool
    # Commit to compare a template-owned root file's *current* content against (the bootstrap
    # CLAUDE.md/AGENTS.md, the READMEs -- see _retire_template_readme/_bootstrap_entry_files):
    # origin's remote-tracking commit when that was readable, i.e. the template's own version
    # regardless of any commit the owner may have added on top locally after cloning; falls back to
    # `template_commit` (plain HEAD) when there was no origin/tracking ref to read at all. Using
    # `template_commit` unconditionally used to compare a file against *its own already-committed,
    # edited copy* whenever the owner had committed an edit before running init -- always a
    # "verified match" that way, so the edit was silently discarded (review HIGH, data loss).
    verify_commit: str
    # Whether the caller (main(), step 10) may delete the old 'template' branch once the first
    # commit on the rebuilt 'main' lands. False whenever any of the three conditions in
    # _old_branch_disposition below does not hold -- see there for what each means and why all
    # three have to be checked *before* 'origin' is removed a few lines down (its tracking refs go
    # with it).
    can_delete_old_branch: bool
    # Human-readable reason `can_delete_old_branch` is False, for the inbox note -- empty when it
    # is True or when there is no 'template' branch to begin with (orphan_rebuilt is False).
    keep_old_branch_reason: str
    # Tip of the old branch right after the rename below (== template_commit whenever a rename/
    # orphan-rebuild actually happens) -- read once here rather than re-derived at deletion time,
    # since by then 'template' itself is gone. Used only for the "(was <sha>)" report.
    old_branch_tip: str


def _old_branch_disposition(
    root: Path, plan: bool, has_commit: bool, current: str,
) -> tuple[Optional[str], Optional[int]]:
    """Read-only, called before 'origin' or the current branch are touched: (origin_tip,
    own_commits). origin_tip is the SHA `refs/remotes/origin/<current>` pointed at, or None if that
    ref does not exist (no 'origin', a shallow/unusual clone, or -- moot once own_commits is used --
    'origin' never was the template to begin with). own_commits is how many commits HEAD has that
    origin_tip lacks (None if origin_tip itself is None) -- 0 for an untouched clone, more than 0
    once the owner has committed anything locally before running init (T76 S1). Both must be read
    here, before 'git remote remove origin' a few lines below deletes the very ref they read from."""
    if not (has_commit and current):
        return None, None
    origin_tip = _remote_tracking_commit(root, "origin", current)
    if origin_tip is None:
        return None, None
    own_commits = _commits_ahead_of(root, f"refs/remotes/origin/{current}")
    return origin_tip, own_commits


def step_git_in_place(root: Path, plan: bool) -> GitInPlaceResult:
    """Returns a GitInPlaceResult (see there for each field). template_source is the template's own
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
    Empty if there is no commit to read (fresh/empty repository).
    orphan_rebuilt is True once this call reaches the point of (re)building 'main' as an orphan
    branch off the old history now on 'template' (True under `plan` too, meaning "would") -- the
    caller (main()) uses it, after the first real commit on the new 'main' actually lands (step
    10), to remove the now-superseded 'template' branch, but only when can_delete_old_branch also
    holds (Wolfgang 2026-09-25, Q101b: nobody should be able to merge the old history back into
    'main'; the template's own history stays reachable on GitHub, updates from here on only via
    update.py -- but that decision assumed an untouched clone, review HIGH/B142/T76 S1+S3: it never
    covered a clone the owner already committed into, or an existing project's repo repurposed in
    place, either of which would lose history found nowhere else). Never True for the "no
    repository"/"no commits yet"/"detached HEAD"/"refused, dirty tree" returns below -- there is no
    'template' branch to remove in any of those cases.

    The dirty-tree check below runs first, before 'origin' is touched or the branch renamed --
    read-only, so a refusal leaves the clone exactly as it was found (review B116/1: it used to run
    after both of those, so a refusal still removed 'origin' -- the only place `template.source`
    could still be read from -- and renamed the branch, with no way back except 'git stash' plus a
    second run that then found 'origin' already gone)."""
    git_dir = root / ".git"
    if not git_dir.exists():
        if not plan:
            _git(["init"], cwd=root)
            # The initial branch name is whatever this machine's git is configured for (often
            # "main", but "master" or a custom default are common too) — point it at "main"
            # explicitly so the outcome does not depend on that setting. Safe before the first
            # commit: it only moves the unborn HEAD, nothing is renamed or rewritten.
            _git(["symbolic-ref", "HEAD", "refs/heads/main"], cwd=root)
            return GitInPlaceResult("no repository found -> ran 'git init' (branch 'main')", "", "", False, "", False, "", "")
        return GitInPlaceResult("no repository found -> would run 'git init' (branch 'main')", "", "", False, "", False, "", "")

    # B130: the template-dev-checkout refusal used to live here. It now runs in main(), before
    # step_config's questions (step 1) rather than only here at step 2 -- see main()'s own comment
    # at the call site. By the time this function runs, that check has already passed.

    # Read-only look-ahead: is an orphan rebuild of 'main' coming up at all below? That's the only
    # thing a dirty tracked file threatens (via the follow-up 'git rm -r --cached .'), and it only
    # happens when there is a commit to rebuild from and HEAD is on a branch (not detached) -- same
    # conditions the rest of this function checks further down, just answered here first so nothing
    # has to be undone if the answer is "refuse".
    has_commit = _git(["rev-parse", "--verify", "-q", "HEAD"], cwd=root, check=False).returncode == 0
    current = _git(["branch", "--show-current"], cwd=root).stdout.strip()
    if has_commit and current:
        dirty = _git(["status", "--porcelain"], cwd=root, check=False).stdout
        tracked_changes = [line for line in dirty.splitlines() if not line.startswith("??")]
        if tracked_changes:
            reason = (
                f"{len(tracked_changes)} uncommitted change(s) to tracked file(s) -- the follow-up "
                "'git rm -r --cached .' would fail on them"
            )
            advice = (
                "git stash the changes (not commit: a commit made on this branch would become "
                "'template.commit', a state the template itself never had), then run init.py again"
            )
            if plan:
                return GitInPlaceResult(
                    "repository already present; would refuse to rebuild 'main' as an orphan "
                    f"branch ({reason}); 'origin' and the current branch would be left unchanged; {advice}",
                    "", "", False, "", False, "", "",
                )
            print(
                f"init.py: clone has {reason} -- refusing to rebuild 'main' as an orphan branch; "
                f"'origin' and the current branch are left unchanged; {advice}",
                file=sys.stderr,
            )
            sys.exit(1)

    # Review HIGH/B142/T76 S1+S3: read before 'origin' is touched below -- 'git remote remove
    # origin' takes its tracking refs with it, and those refs are the only way left afterwards to
    # tell an untouched clone's HEAD apart from one the owner already committed into.
    origin_tip, own_commits = _old_branch_disposition(root, plan, has_commit, current)

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

    if not has_commit:
        parts.append("no commits yet -> branch left as-is")
        return GitInPlaceResult("; ".join(parts), template_source, "", False, "", False, "", "")

    template_commit = _git(["rev-parse", "HEAD"], cwd=root).stdout.strip()
    verify_commit = origin_tip or template_commit

    if not current:
        parts.append("HEAD is detached -> branch left as-is")
        return GitInPlaceResult("; ".join(parts), template_source, template_commit, False, verify_commit, False, "", "")
    if current == "template":
        parts.append("current branch already named 'template'")
    else:
        if not plan:
            _git(["branch", "-m", current, "template"], cwd=root)
            parts.append(f"branch '{current}' -> renamed to 'template'")
        else:
            parts.append(f"branch '{current}' -> would rename to 'template'")
    if not plan:
        # The dirty-tree check that used to sit here now runs at the top of the function, before
        # 'origin' or the branch were touched at all -- see the docstring and review B116/1.
        _git(["checkout", "--orphan", "main"], cwd=root)
        rm_result = _git(["rm", "-r", "--cached", "."], cwd=root, check=False)
        if rm_result.returncode != 0:
            print(
                "init.py: 'git rm -r --cached .' failed after creating the orphan branch -- "
                f"{rm_result.stderr.strip()} -- the orphan branch was created but nothing has been "
                "committed yet; 'git checkout -f template' clears the index again and abandons the "
                "failed rebuild (the branch rename above already happened), then run init.py once more"
                + (f"; 'origin' was already removed -- re-add it first (git remote add origin {origin_url}) "
                   "so the template address lands in .act-lock.json" if template_source else ""),
                file=sys.stderr,
            )
            sys.exit(1)
        parts.append("new orphan branch 'main' created")
    else:
        parts.append("would create new orphan branch 'main'")

    # Review HIGH/B142/T76 S1+S3: delete only once *all three* hold -- (a) 'origin' really was the
    # template (template_source set), (b) no commits sit on this branch that 'origin' doesn't also
    # have (own_commits == 0, read above before 'origin' was touched), (c) the branch's tip is still
    # exactly the commit 'origin' had (origin_tip == template_commit -- (b) already guarantees this
    # whenever origin_tip is known, since HEAD cannot both equal and be ahead of the same ref; kept
    # as an explicit condition here so a future change to either half doesn't quietly rely on that).
    can_delete_old_branch = bool(template_source) and origin_tip is not None and own_commits == 0 and origin_tip == template_commit
    if can_delete_old_branch:
        keep_old_branch_reason = ""
    elif not template_source:
        keep_old_branch_reason = "'origin' was not the template's address -- the previous history is this project's own"
    elif origin_tip is None or own_commits is None:
        keep_old_branch_reason = "could not verify it against 'origin' (no matching remote-tracking ref to compare with)"
    else:
        keep_old_branch_reason = f"{own_commits} commit(s) were added to it after cloning, before this run"
    return GitInPlaceResult(
        "; ".join(parts), template_source, template_commit, True,
        verify_commit, can_delete_old_branch, keep_old_branch_reason, template_commit,
    )


def step_git_target(root: Path, plan: bool, source_act: Path) -> tuple[str, str, str]:
    """Returns (summary, template_source, template_commit) -- unlike step_git_in_place, `root` has
    no "origin" of its own to inspect (it is brand new or foreign), so `template_source` instead
    comes from the checkout init.py is *running from* (source_act.parent): that checkout is the
    template, by definition of being the one docking .act/ onto `root` (Q73a, backlog B105).
    `template_commit` is that same checkout's HEAD (empty if it has none/is not a git repo) --
    same reasoning as step_git_in_place's template_commit, just read from a different repo since
    `root` itself has no history yet to read it from.

    The initial branch is pinned to 'main' exactly like step_git_in_place's own 'git init' branch
    (B140 a) -- otherwise it follows this machine's `init.defaultBranch` (often 'main', but
    'master' or a custom default are common too, same reasoning as the in-place comment above).
    Only a repository this call creates itself gets that treatment: an existing repository at
    `root` (the first branch below) is left untouched, branch included -- the adopt path
    (adopt.py calling this with an existing project's repo already in place) must never move a
    project's own branch out from under it. 'git init' followed by 'git symbolic-ref HEAD
    refs/heads/main' works on Git versions before 2.28 too (no '-b main' needed), unlike 'git init
    -b main'/'git branch -m main', and is safe before the first commit: it only moves the unborn
    HEAD, nothing is renamed or rewritten."""
    template_source = _checkout_source(source_act.parent)
    template_commit = _git(["rev-parse", "HEAD"], cwd=source_act.parent, check=False).stdout.strip()
    if (root / ".git").exists():
        return "target already has a repository, left unchanged", template_source, template_commit
    if plan:
        return "would run 'git init' in target (branch 'main')", template_source, template_commit
    _git(["init"], cwd=root)
    _git(["symbolic-ref", "HEAD", "refs/heads/main"], cwd=root)
    return "ran 'git init' in target (branch 'main')", template_source, template_commit


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
    actlib.write_text_lf(dest, text)  # B134: LF regardless of platform, matches .gitattributes
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
    """Write a brand-new file with `\\n` line endings, regardless of platform default (B134) --
    see actlib.write_text_lf()."""
    actlib.write_text_lf(dest, text)


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
    src: Path, dest: Path, tokens: dict[str, str], plan: bool, root: Path | None = None,
    force: bool = False,
) -> tuple[str, bool]:
    """Never overwrites an existing project file. Returns (message, created). `force` is the one
    exception: a root CLAUDE.md/AGENTS.md whose template bootstrap marker `_bootstrap_entry_files`
    already verified and cleared (or, under `plan`, would clear) -- `dest.is_file()` is skipped so
    the message says "would create"/"created" instead of "already present" for it."""
    label = _relative_label(dest, root)
    if dest.is_file() and not force:
        return f"{label}: already present, left unchanged", False
    if plan:
        return f"{label}: would create", False
    text = src.read_text(encoding="utf-8")
    for token, value in tokens.items():
        text = text.replace(token, value)
    actlib.write_text_lf(dest, text)  # B134: LF regardless of platform, matches .gitattributes
    return f"{label}: created", True


def _merge_settings_hooks(src: Path, dest: Path, plan: bool, root: Path | None = None) -> tuple[str, bool]:
    """Merges src's hook entries and top-level "env" keys into dest (see
    actlib.merge_settings_hooks / actlib.merge_settings_env): a hook entry the bridge already
    defines is replaced in place (a changed timeout/matcher/command never ends up as a second,
    duplicate entry), one the bridge no longer defines is removed, and anything the project added
    itself — hooks or env keys alike — is left untouched; an env key (e.g.
    CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR, B126) is only ever added when missing, never
    overwritten. Idempotent — a second run against its own output reports no change and leaves the
    file byte-for-byte identical (T46)."""
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
    new_current, env_changed = actlib.merge_settings_env(new_current, bridge_data)
    if not changed_events and not env_changed:
        return f"{_relative_label(dest, root)}: hook entries already up to date, left unchanged", False
    parts = []
    if changed_events:
        parts.append(f"hook entries for {', '.join(changed_events)}")
    if env_changed:
        parts.append("env")
    if plan:
        return f"{_relative_label(dest, root)}: would add/update {', '.join(parts)}", False
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(new_current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return f"{_relative_label(dest, root)}: added/updated {', '.join(parts)}", True


# ---------------------------------------------------------------------------
# Step 6 helper -- Weg C: carry over a source project's own deviations (concept
# docs/project/concepts/ai-dev-app/08-new-project.md lines 60-125, decided 2026-09-20, Q56d, backlog
# B91). `--target <dir>` run from a checkout that is itself an already set-up project (its own
# docs/ai/config.md exists) carries that project's own rule/coding-rule deviations plus its whole
# docs/ai/local/ tree into the freshly materialized target -- never the `use:` set selection
# (coding_rules.md), never work state (docs/ai/inbox/, docs/ai/work/, docs/project/ beyond the two
# named sections). What does not fit (a group id the target has no match for) is named in the
# inbox, never silently dropped. `--no-local` opts out.
# ---------------------------------------------------------------------------

def _configured_project_root(path: Path) -> bool:
    """Whether `path` is itself an already set-up project (not a plain template clone) -- same
    signal `_ask_feedback_mode` already uses for "has this project made its own choice yet"."""
    return (path / "docs" / "ai" / "config.md").is_file()


def _insert_after_mark(text: str, mark_name: str, new_lines: list[str]) -> tuple[str, bool]:
    """Insert `new_lines` right after the `<!-- act:<mark_name> -->` line in `text`. (text, False)
    unchanged if the mark is not present at all (a template version with a different section
    layout -- nothing to insert into)."""
    marker = f"<!-- act:{mark_name} -->"
    idx = text.find(marker)
    if idx == -1:
        return text, False
    insert_at = idx + len(marker)
    return text[:insert_at] + "\n\n" + "\n".join(new_lines) + text[insert_at:], True


def _carry_over_area(root: Path, source_root: Path, area: "rules.Area", plan: bool,
                      dest_was_preexisting: bool, notes: list[str]) -> Optional[str]:
    """One area (docs/ai/rules.md or docs/project/coding_rules.md): copy the source project's
    switched-off groups (with their reason) and its '## Overrides'/'## Own rules' sections into
    the target's freshly materialized file of the same area -- only for a group id the target file
    already carries a checkbox line for (a set the target never enabled has none, so the `use:`
    selection itself is never touched here). Never overwrites a target file that already has
    overrides/own rules of its own, and never touches one at all if it pre-dates this run
    (`dest_was_preexisting`, B143#4b): docking `--target` onto an already set-up project whose file
    just has no '## Overrides'/'## Own rules' section yet still means a person made those checkbox
    choices on purpose -- only a file this run itself materialized from the skeleton is fair game."""
    source_path = source_root / area.project_file
    dest_path = root / area.project_file
    if not source_path.is_file() or not dest_path.is_file():
        return None
    if dest_was_preexisting:
        return None
    source_project = rules.parse_project_file(source_path, area)
    has_deviation = source_project.overrides or source_project.own_rules or any(
        not group.enabled for pset in source_project.sets for group in pset.groups.values()
    )
    if not has_deviation:
        return None

    target_project = rules.parse_project_file(dest_path, area)
    if target_project.overrides or target_project.own_rules:
        return (f"{area.name}: {_relative_label(dest_path, root)} already has its own overrides/"
                "own rules, left unchanged")

    source_group_state = {
        gid: group for pset in source_project.sets for gid, group in pset.groups.items()
    }
    target_group_ids = {gid for pset in target_project.sets for gid in pset.groups}

    lines = dest_path.read_text(encoding="utf-8").splitlines()
    toggled: list[str] = []
    for pset in target_project.sets:
        for gid, group in pset.groups.items():
            source_group = source_group_state.get(gid)
            if source_group is None or source_group.enabled:
                continue
            idx = group.line - 1
            lines[idx] = re.sub(r"\[[xX]\]", "[ ]", lines[idx], count=1)
            if source_group.reason and "—" not in lines[idx]:
                lines[idx] = lines[idx].rstrip() + f" — {source_group.reason}"
            toggled.append(gid)

    missing = sorted(gid for gid in source_group_state if gid not in target_group_ids)

    override_lines = [f"- replaces `{o.id}`: {o.text}" for o in source_project.overrides]
    own_rule_lines = [
        (f"- `{r.id}`: {r.text}" if r.id else f"- {r.text}") for r in source_project.own_rules
    ]

    text = "\n".join(lines) + "\n"
    inserted: list[str] = []
    if override_lines:
        text, ok = _insert_after_mark(text, "overrides", override_lines)
        if ok:
            inserted.append(f"{len(override_lines)} override(s)")
    if own_rule_lines:
        text, ok = _insert_after_mark(text, "own-rules", own_rule_lines)
        if ok:
            inserted.append(f"{len(own_rule_lines)} own rule(s)")

    parts: list[str] = []
    if toggled:
        parts.append(f"{len(toggled)} group(s) switched off ({', '.join(sorted(toggled))})")
    if inserted:
        parts.append(", ".join(inserted))
    if missing:
        notes.append(
            f"Source project deviation(s) for {', '.join(missing)} could not be carried over "
            f"into {_relative_label(dest_path, root)} -- the target has no matching group there."
        )
        parts.append(f"{len(missing)} id(s) skipped, see inbox")
    if not parts:
        return None
    if plan:
        return f"{area.name}: would carry over {', '.join(parts)}"
    actlib.write_text_lf(dest_path, text)
    return f"{area.name}: carried over {', '.join(parts)}"


_SECRET_LIKE_NAMES = re.compile(r"(?i)^\.env(\..*)?$")


def _git_tracked_files(repo_root: Path, subpath: str) -> Optional[list[str]]:
    """Repo-root-relative (posix) paths of files `repo_root`'s own git tracks under `subpath` --
    None if `repo_root` is not a git checkout (or the command fails), never an empty list mistaken
    for "not a repo". Untracked and gitignored files never show up here at all (B143#2) -- the
    caller does not need to special-case them separately."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "ls-files", "-z", "--", subpath],
            capture_output=True, check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout.decode("utf-8", errors="replace")
    return [p for p in raw.split("\0") if p]


def _git_head_blobs(repo_root: Path, subpath: str) -> Optional[dict[str, str]]:
    """Repo-root-relative (posix) path -> mode ("100644"/"100755" a file, "120000" a symlink) of
    every blob under `subpath` in `repo_root`'s HEAD commit -- None if there is no HEAD to read
    (a repository without commits) or the command fails. Submodule entries (type "commit") are
    left out: nothing to copy there. `-z`: paths raw, never quoted."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "ls-tree", "-r", "-z", "HEAD", "--", subpath],
            capture_output=True, check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    blobs: dict[str, str] = {}
    for record in result.stdout.decode("utf-8", errors="replace").split("\0"):
        meta, _tab, path = record.partition("\t")
        fields = meta.split()
        if len(fields) >= 3 and fields[1] == "blob" and path:
            blobs[path] = fields[0]
    return blobs


def _git_differs_from_head(repo_root: Path, subpath: str) -> set[str]:
    """Tracked files under `subpath` whose index or working tree differs from HEAD -- a staged or
    unstaged edit, a file added but not committed, a local delete -- repo-root-relative posix.
    Empty when there is no HEAD or the command fails (nothing could be copied from HEAD then
    either, and the caller reports that on its own)."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "diff", "HEAD", "--name-only", "-z", "--", subpath],
            capture_output=True, check=False,
        )
    except OSError:
        return set()
    if result.returncode != 0:
        return set()
    return {p for p in result.stdout.decode("utf-8", errors="replace").split("\0") if p}


def _git_head_blob_bytes(repo_root: Path, rel: str) -> Optional[bytes]:
    """Content of `rel` exactly as HEAD has it, raw bytes -- `git cat-file blob` applies neither
    eol conversion nor a textconv filter, so binary content survives -- None if unreadable."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "cat-file", "blob", f"HEAD:{rel}"],
            capture_output=True, check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout


def _carry_over_local_dir(
    root: Path, source_root: Path, plan: bool, notes: list[str],
) -> tuple[Optional[str], list[Path]]:
    """Copy of the source project's docs/ai/local/ (its own rule/skill/agent/script/checklist
    overrides) into the target. Git-tracked files only (B143#2, review of T76 wave D): an
    untracked or gitignored file under the source's docs/ai/local/ (a machine-local note, a
    stray `.env`) is data the source project itself chose to keep out of its own history and
    never leaves it through this copy either. Content comes from the source's HEAD commit, never
    from its working tree (T76 wave D review, round 2): a tracked file the source is still
    editing -- an unstaged or staged edit, a file added but never committed -- has not been
    decided for its own history yet, so it does not leave the project through this copy either
    (the line B143#2 already drew, applied to content); the copy then equals what a fresh clone
    of the source at HEAD would hold, the one state the source can name later. Whatever differs
    is named in the inbox instead of silently taken along or silently dropped. A committed file
    is still skipped, and named in the inbox, if it is a symlink (the link target could point
    anywhere) or its name looks like a secret (`.env`, `.env.*`). Never overwrites a file the
    target already has. Returns (summary, list of dest paths actually copied -- for the caller's
    commit pathspec, never a whole-directory add that would sweep in the target's own untracked
    files too)."""
    source_dir = source_root / "docs" / "ai" / "local"
    if not source_dir.is_dir():
        return None, []
    tracked = _git_tracked_files(source_root, "docs/ai/local")
    if tracked is None:
        notes.append(
            f"docs/ai/local of the source project ({source_root}) is not tracked by git there -- "
            "nothing was copied from it; review it by hand."
        )
        return "docs/ai/local: source not tracked by git, skipped", []
    tracked_set = set(tracked)
    # Named separately from `skipped_unsafe` below -- these were never even a candidate (git
    # itself never offered them), so "not copied" is expected, but still worth naming: the source
    # project might not realize a file it meant to share sits outside its own git tracking.
    untracked = sorted(
        p.relative_to(source_root).as_posix()
        for p in source_dir.rglob("*")
        if (p.is_file() or p.is_symlink()) and "__pycache__" not in p.parts
        and p.relative_to(source_root).as_posix() not in tracked_set
    )
    committed = _git_head_blobs(source_root, "docs/ai/local")
    differing = _git_differs_from_head(source_root, "docs/ai/local") if committed is not None else set()

    dest_dir = root / "docs" / "ai" / "local"
    created = 0
    skipped_existing = 0
    skipped_unsafe: list[str] = []
    not_committed: list[str] = []
    uncommitted_edits: list[str] = []
    unreadable: list[str] = []
    copied: list[Path] = []
    for rel in sorted(tracked):
        src = source_root / rel
        rel_to_local = Path(rel).relative_to("docs/ai/local")
        mode = committed.get(rel) if committed is not None else None
        if mode is None:
            not_committed.append(rel)  # in the index only (staged, never committed), or no HEAD at all
            continue
        # Symlink by HEAD's own mode *or* by the working tree (a checkout without symlink support
        # materializes a 120000 entry as a plain file, an owner may have swapped a file for a link
        # locally) -- either way it is not copied.
        if mode == "120000" or src.is_symlink() or _SECRET_LIKE_NAMES.match(Path(rel).name):
            skipped_unsafe.append(rel)
            continue
        dest = dest_dir / rel_to_local
        if dest.is_file():
            skipped_existing += 1
            continue
        if not plan:
            content = _git_head_blob_bytes(source_root, rel)
            if content is None:
                unreadable.append(rel)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
        created += 1
        copied.append(dest)
        if rel in differing:
            uncommitted_edits.append(rel)
    if not (created or skipped_existing or skipped_unsafe or untracked or not_committed or unreadable):
        return None, []
    summary = f"docs/ai/local: {'would copy' if plan else 'copied'} {created} file(s) as committed in the source (HEAD)"
    if skipped_existing:
        summary += f", {skipped_existing} already present"
    if skipped_unsafe:
        summary += f", {len(skipped_unsafe)} skipped (symlink or secret-like name)"
        notes.append(
            "docs/ai/local of the source project had file(s) not copied (symlink or secret-like "
            f"name): {', '.join(skipped_unsafe)} -- review and copy them by hand if they are "
            "actually needed."
        )
    if uncommitted_edits:
        summary += f", {len(uncommitted_edits)} with uncommitted edit(s) in the source (HEAD version taken)"
        notes.append(
            "docs/ai/local of the source project has uncommitted edit(s) to tracked file(s) -- copied "
            f"as last committed there (HEAD), the working-tree edits were not taken along: "
            f"{', '.join(uncommitted_edits)} -- commit them in the source project and copy them by "
            "hand if they are meant to be shared."
        )
    if not_committed:
        summary += f", {len(not_committed)} tracked but never committed, skipped"
        notes.append(
            "docs/ai/local of the source project has tracked file(s) without a committed version "
            f"(staged only, or a repository without commits) -- not copied: {', '.join(not_committed)} "
            "-- commit them in the source project first, then copy them by hand if they are meant "
            "to be shared."
        )
    if unreadable:
        summary += f", {len(unreadable)} could not be read from HEAD"
        notes.append(
            "docs/ai/local of the source project: file(s) could not be read from its HEAD commit "
            f"(`git cat-file blob` failed), not copied: {', '.join(unreadable)} -- review by hand."
        )
    if untracked:
        summary += f", {len(untracked)} untracked/gitignored file(s) skipped"
        notes.append(
            "docs/ai/local of the source project had untracked/gitignored file(s), not copied "
            f"(never file content, only the path -- R-safe-no-secret-log): {', '.join(untracked)} "
            "-- review and copy them by hand (add to git first) if they are actually meant to be shared."
        )
    return summary, (copied if not plan else [])


def step_source_project(
    root: Path, plan: bool, source_checkout: Path, take_local: bool,
    dest_was_preexisting: dict[str, bool], notes: list[str],
) -> tuple[Optional[str], list[Path]]:
    """Weg C entry point, called only in `--target` mode (see main()). `source_checkout` is the
    checkout init.py is running from (source_act.parent) -- the project whose own deviations get
    carried over, if it has any of its own to begin with. `dest_was_preexisting` says, per
    `area.project_file`, whether the target already had that file before this run materialized it
    (B143#4b) -- passed straight through to `_carry_over_area`. Returns the summary plus the list
    of `docs/ai/local/` dest paths this run actually copied (B143#1: for the caller's commit
    pathspec, never the whole directory)."""
    if not take_local:
        return "source project: --no-local -- skipped", []
    if not _configured_project_root(source_checkout):
        return None, []
    summaries: list[str] = []
    for area in (rules.AREAS["core"], rules.AREAS["coding"]):
        summary = _carry_over_area(
            root, source_checkout, area, plan, dest_was_preexisting.get(area.project_file, False), notes,
        )
        if summary:
            summaries.append(summary)
    local_summary, copied = _carry_over_local_dir(root, source_checkout, plan, notes)
    if local_summary:
        summaries.append(local_summary)
    if not summaries:
        return "source project: nothing to take over", []
    return "source project: " + "; ".join(summaries), copied


# ---------------------------------------------------------------------------
# Step 6 helper -- Owner profile (Q103 a1/b1/c1, concept 08 SS "Voreinstellungen"). Read only as an
# init source, never as a runtime load path (settings_export.py's own docstring). Genuinely one
# profile file: settings_export.profile_dir()/"settings.md" -- imported via settings_load.py's own
# analyze()/apply machinery rather than a second read of the settings-file format. Runs after
# step_source_project so precedence falls out of the file state it compares against: a group/id
# the source project already carried over is no longer "new" by the time this runs, so the profile
# only ever fills a genuine gap, never overrides a Weg C decision.
# ---------------------------------------------------------------------------

def _profile_display_path() -> str:
    """Platform-generic form of the owner profile's location for text that ends up committed
    (B143#4 LOW) -- the real, absolute path (with the OS user name in it under Windows) is fine to
    print to the terminal, never to write into a file that lands in the project's own history."""
    if sys.platform == "win32":
        return r"%APPDATA%\act\settings.md"
    return "~/.config/act/settings.md"


def _profile_entry_lines(result) -> list[str]:
    """Compact 'id + kind' summary of what an owner profile would apply -- no rule/file text, just
    enough to identify each entry (Q103 a1: the todo names the entries, not just that some exist)."""
    lines = [f"[{r.entry.area}] {r.entry.symbol} `{r.entry.id}`"
             for r in result.resolutions if r.action == "apply"]
    lines.extend(f"[{item['area']}] {item['dest']} (new file)"
                 for item in result.file_plan if item["status"] == "new")
    return lines


def step_owner_profile(
    root: Path, plan: bool, interactive: bool, take_profile: bool, auto_apply: bool,
    notes: list[str],
) -> tuple[str, list[Path]]:
    """`auto_apply` (`--profile`, Q103 a1's "catch up" path) shows the same entry list an
    interactive run would, but applies it right away without asking -- for a deliberate, explicit
    re-run of `init.py` on an already set-up project, not for a run that merely happens to be
    interactive."""
    import settings_export
    import settings_load

    if not take_profile:
        return "owner profile: --no-profile -- skipped", []

    profile_path = settings_export.profile_dir() / "settings.md"
    if not profile_path.is_file():
        return "owner profile: none found", []
    try:
        source = settings_load.load_source(profile_path)
    except (OSError, ValueError, KeyError) as exc:
        notes.append(f"Owner profile at {_profile_display_path()} could not be read ({exc}) -- review it by hand.")
        return f"owner profile: {profile_path} -- could not be read, see inbox", []

    result = settings_load.analyze(root, [source])
    settings_load.plan_files(root, [source], result)
    settings_load.plan_units(root, [source], result)
    settings_load.mark_unreviewed_without_judgments(result)
    entry_lines = _profile_entry_lines(result)
    display_path = _profile_display_path()

    # An entry that needs a verdict (settings_load marks it "skip" plus a finding) is not in
    # entry_lines, but must still reach the inbox rather than vanish.
    if not entry_lines and not result.findings:
        return "owner profile: found, nothing new to add", []

    if not auto_apply and not interactive:
        review_note = (f"\n  plus {len(result.findings)} entr(ies) that need review before they could apply"
                       if result.findings else "")
        notes.append(
            f"An owner profile is available at {display_path} but was not applied automatically "
            "(non-interactive run). Entries it would add:\n  " + ("\n  ".join(entry_lines) or "(none directly)")
            + review_note +
            "\nReview it and, if it fits, apply it: `python .act/scripts/init.py --profile` run "
            "inside this project (no `--target`: in a project that is already set up, init.py "
            "runs the owner-profile step alone and commits only what it wrote -- nothing else is "
            f"touched), or `python .act/scripts/settings_load.py plan {display_path}` then `apply` "
            "the same path."
        )
        return f"owner profile: found at {display_path} -> non-interactive, left for the inbox", []

    if entry_lines:
        print(f"Owner profile at {display_path} would add:")
        for line in entry_lines:
            print(f"  {line}")
        if not auto_apply:
            answer = _ask("Apply the owner profile above?", "n", True).strip().lower()
            if answer not in ("y", "yes", "j", "ja"):
                return "owner profile: found, declined", []
    if plan:
        return f"owner profile: would apply {display_path}", []

    rule_messages = settings_load.write_resolutions(root, result)
    file_messages = settings_load.write_files(root, result, True)
    bridge_messages = settings_load.write_unit_bridges(root, result)
    written_paths = [root / item["dest"] for item in result.file_plan if item.get("written")]
    written_paths.extend(_resolution_area_files(root, result))
    written_paths.extend(_owner_profile_bridge_paths(root, result))
    if result.findings:
        inbox_path, _is_new = settings_load.write_inbox(root, result.findings, result.setup_required, [source])
        if inbox_path is not None:
            written_paths.append(inbox_path)
    applied = sum(1 for _message, ok in rule_messages if ok) + len(file_messages) + len(bridge_messages)
    summary = f"owner profile: applied {applied} item(s) from {display_path}"
    if result.findings:
        summary += f", {len(result.findings)} finding(s) in the inbox"
    return summary, written_paths


def _owner_profile_bridge_paths(root: Path, result) -> list[Path]:
    """Re-derives the destination paths `settings_load.write_unit_bridges()` may just have written
    for a "new" agents/skills item, without duplicating its write logic or changing its return
    type (out of this assignment's write scope) -- checked by the file now existing, same
    "written, not just planned" test `write_unit_bridges()` itself already uses. Listing a path it
    did not actually touch after all costs nothing: the caller's commit pathspec skips anything
    that does not exist (B143#1)."""
    written_items = [item for item in result.file_plan
                      if item["area"] in ("agents", "skills") and item["status"] == "new"
                      and (root / item["dest"]).is_file()]
    if not written_items:
        return []
    tools = [t.strip().lower() for t in actlib.read_config().get("tools", "").split(",") if t.strip()]
    paths: list[Path] = []
    if "claude-code" in tools:
        for item in written_items:
            if item["area"] != "agents":
                continue
            dest = root / ".claude" / "agents" / f"{Path(item['path']).stem}.md"
            if dest.is_file():
                paths.append(dest)
    for item in written_items:
        if item["area"] != "skills":
            continue
        for dest_root, tool_gate in SKILL_TARGET_DIRS:
            if not _skill_target_active(tool_gate, tools):
                continue
            dest = root / dest_root / item["path"]
            if dest.is_file():
                paths.append(dest)
    return paths


def _resolution_area_files(root: Path, result) -> list[Path]:
    """The rule files (docs/ai/rules.md, docs/project/coding_rules.md) `settings_load.
    write_resolutions()` edits for the entries it applies -- for the caller's commit pathspec. In a
    full run those files are already among step 6's `touched_bridges`; a profile-only run
    (run_profile_only, `init.py --profile` in a set-up project) has no such list and would otherwise
    leave the very file the profile changed out of its own commit. Listing a file the write then
    did not change after all costs nothing: an unchanged path stages nothing."""
    import settings_load
    files: list[Path] = []
    for resolution in result.resolutions:
        if resolution.action != "apply":
            continue
        area_key = settings_load.SETTINGS_TO_RULES_AREA.get(resolution.entry.area)
        if area_key is None:
            continue
        path = root / rules.AREAS[area_key].project_file
        if path not in files:
            files.append(path)
    return files


def step_source_and_profile(
    root: Path, plan: bool, interactive: bool, source_checkout: Path,
    take_local: bool, take_profile: bool, auto_apply: bool, dest_was_preexisting: dict[str, bool],
    notes: list[str],
) -> tuple[str, list[Path]]:
    """Combined Weg C (source project, concept 08) + owner profile entry point (Q103 b1, B143#3c).
    Interactive (or `auto_apply`, `--profile`): one list with provenance per entry, one question --
    covers whichever of the two sources has something to offer, applies both together or neither;
    `auto_apply` shows the same list but skips the question (Q103 a1's "catch up" path). Plain
    non-interactive, no `--profile`: unchanged split behavior -- Weg C stays applied by default
    (concept 08's own default, `--no-local` opts out of it), the profile stays for the inbox
    instead (Q103 a1, `--no-profile` opts out of even that note)."""
    if not interactive and not auto_apply:
        source_summary, source_paths = step_source_project(
            root, plan, source_checkout, take_local, dest_was_preexisting, notes,
        )
        profile_summary, profile_paths = step_owner_profile(
            root, plan, False, take_profile, False, notes,
        )
        summary = "; ".join(s for s in (source_summary, profile_summary) if s)
        return summary, [*source_paths, *profile_paths]

    # Interactive: preview both sources without writing anything (plan=True / analyze-only), build
    # one combined list, ask once.
    import settings_export
    import settings_load

    combined_lines: list[str] = []
    has_source = take_local and _configured_project_root(source_checkout)
    if has_source:
        preview_notes: list[str] = []  # discarded -- a real note only makes sense once actually applied
        for area in (rules.AREAS["core"], rules.AREAS["coding"]):
            summary = _carry_over_area(
                root, source_checkout, area, True,
                dest_was_preexisting.get(area.project_file, False), preview_notes,
            )
            if summary:
                combined_lines.append(f"[source project] {summary}")
        local_summary, _copied = _carry_over_local_dir(root, source_checkout, True, preview_notes)
        if local_summary:
            combined_lines.append(f"[source project] {local_summary}")

    profile_display = _profile_display_path()
    profile_source = None
    profile_result = None
    if take_profile:
        profile_path = settings_export.profile_dir() / "settings.md"
        if profile_path.is_file():
            try:
                profile_source = settings_load.load_source(profile_path)
            except (OSError, ValueError, KeyError) as exc:
                notes.append(f"Owner profile at {_profile_display_path()} could not be read ({exc}) -- review it by hand.")
            if profile_source is not None:
                profile_result = settings_load.analyze(root, [profile_source])
                settings_load.plan_files(root, [profile_source], profile_result)
                settings_load.plan_units(root, [profile_source], profile_result)
                settings_load.mark_unreviewed_without_judgments(profile_result)
                combined_lines.extend(
                    f"[owner profile] {line}" for line in _profile_entry_lines(profile_result)
                )
                if profile_result.findings:
                    combined_lines.append(
                        f"[owner profile] {len(profile_result.findings)} entr(ies) need review -- listed in the inbox"
                    )

    if not combined_lines:
        source_summary = None
        if not take_local:
            source_summary = "source project: --no-local -- skipped"
        elif has_source:
            source_summary = "source project: nothing to take over"
        profile_summary = None
        if not take_profile:
            profile_summary = "owner profile: --no-profile -- skipped"
        elif profile_source is None:
            profile_summary = "owner profile: none found"
        return "; ".join(s for s in (source_summary, profile_summary) if s), []

    print("The following would be carried over into this project:")
    for line in combined_lines:
        print(f"  {line}")
    if not auto_apply:
        answer = _ask("Apply the above?", "n", True).strip().lower()
        if answer not in ("y", "yes", "j", "ja"):
            return "source project/owner profile: shown, declined", []
    if plan:
        return "source project/owner profile: would apply " + "; ".join(combined_lines), []

    committed: list[Path] = []
    summaries: list[str] = []
    if has_source:
        source_summary, source_paths = step_source_project(
            root, False, source_checkout, True, dest_was_preexisting, notes,
        )
        if source_summary:
            summaries.append(source_summary)
        committed.extend(source_paths)
    if profile_result is not None and profile_source is not None:
        rule_messages = settings_load.write_resolutions(root, profile_result)
        file_messages = settings_load.write_files(root, profile_result, True)
        bridge_messages = settings_load.write_unit_bridges(root, profile_result)
        written_paths = [root / item["dest"] for item in profile_result.file_plan if item.get("written")]
        written_paths.extend(_resolution_area_files(root, profile_result))
        written_paths.extend(_owner_profile_bridge_paths(root, profile_result))
        if profile_result.findings:
            inbox_path, _is_new = settings_load.write_inbox(
                root, profile_result.findings, profile_result.setup_required, [profile_source],
            )
            if inbox_path is not None:
                written_paths.append(inbox_path)
        applied = sum(1 for _m, ok in rule_messages if ok) + len(file_messages) + len(bridge_messages)
        profile_summary = f"owner profile: applied {applied} item(s) from {profile_display}"
        if profile_result.findings:
            profile_summary += f", {len(profile_result.findings)} finding(s) in the inbox"
        summaries.append(profile_summary)
        committed.extend(written_paths)
    return "; ".join(summaries), committed


def step_materialize(
    root: Path, plan: bool, cfg: ProjectConfig, selected_bridges: dict[str, BridgeSpec],
    notes: Optional[list[str]] = None, is_target: bool = False, template_commit: str = "",
) -> tuple[list[str], dict[str, Path], list[Path], dict[str, dict]]:
    tokens = _config_tokens(cfg)
    bridges_dir = root / ".act" / "bridges"
    skeleton_dir = root / ".act" / "skeleton"
    messages: list[str] = []
    generated: dict[str, Path] = {}  # bridge name -> written path, for cache.json hashing
    touched: list[Path] = []
    copies: dict[str, dict] = {}  # dest -> {"source", "sha256"}, for .act-lock.json § copies

    # T76/Q101a: the root CLAUDE.md/AGENTS.md a plain clone opens with (marker
    # TEMPLATE_BOOTSTRAP_MARKER) belong to the template, not a project -- never touched in
    # `--target` mode (a target directory never had them to begin with), cleared here in-place so
    # the bridge writer below creates the real project bridge in their place instead of reporting
    # "already present, left unchanged".
    force_recreate: set[str] = set()
    if not is_target:
        bootstrap_messages, force_recreate = _bootstrap_entry_files(
            root, plan, template_commit, notes if notes is not None else [], selected_bridges,
        )
        messages.extend(bootstrap_messages)

    for src_name, dest_rel in skeleton_files(skeleton_dir):
        message, created = _write_text_file(skeleton_dir / src_name, root / dest_rel, tokens, plan, root)
        messages.append(message)
        if created or (root / dest_rel).is_file():
            touched.append(root / dest_rel)

    for key, spec in selected_bridges.items():
        dest = root / spec["dest"]
        if spec["kind"] == "verbatim":
            message, created = _write_text_file(
                bridges_dir / key, dest, tokens, plan, root, force=spec["dest"] in force_recreate,
            )
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
    actlib.write_text_lf(dest, new_text)  # B134: LF regardless of platform, matches .gitattributes
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


def _has_marker(path: Path, marker: str) -> bool:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.readline().strip() == marker
    except OSError:
        return False


def _has_template_readme_marker(path: Path) -> bool:
    return _has_marker(path, TEMPLATE_README_MARKER)


# First line of the template's own root entry files (CLAUDE.md, AGENTS.md) before a clone is
# turned into a project (T76, Q101a): tells an AI tool opening the bare clone that it is sitting
# in the template, not a project, and to follow .act/skills/act-setup/SKILL.md. `step_materialize`
# (step 6) clears a file still carrying this marker so its own bridge-writer creates the real
# project bridge in its place (see _bootstrap_entry_files below); `--target` and `act-adopt` never
# touch these two files at all -- they only ever copy/materialize .act/ and the bridges under it,
# and a target directory never had the template's own root files to begin with.
TEMPLATE_BOOTSTRAP_MARKER = "<!-- act:bootstrap -->"
# Root bootstrap files with no project bridge behind them (see _bootstrap_entry_files).
_BOOTSTRAP_ONLY_FILES = ("GEMINI.md",)


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
    notes: list[str], on_verified_match, marker: str = TEMPLATE_README_MARKER,
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
    the no-history fallback) has cleared it, and returns its own step-8 message. `marker` is the
    first-line mark that says the file started as the template's -- TEMPLATE_README_MARKER by
    default, or TEMPLATE_BOOTSTRAP_MARKER for the root CLAUDE.md/AGENTS.md bootstrap files
    (_bootstrap_entry_files below)."""
    path = root / rel_path
    if not path.is_file():
        return f"no {rel_path} present"
    if not _has_marker(path, marker):
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


def _bootstrap_entry_files(
    root: Path, plan: bool, template_commit: str, notes: list[str],
    selected_bridges: dict[str, BridgeSpec],
) -> tuple[list[str], set[str]]:
    """Called from step_materialize (step 6), before the bridge writer runs: root AGENTS.md/
    CLAUDE.md (and any future bridge of the same shape, e.g. GEMINI.md, see `root_entry_files`
    below) still carrying TEMPLATE_BOOTSTRAP_MARKER on their first line are the template's own
    (a bare clone opened before `init` -- see the root files themselves and
    .act/skills/act-setup/SKILL.md, T76/Q101a), so they are removed here to make way for the real
    project bridge; the same verified-match safety net as `_retire_template_readme` applies (a
    file whose marker is gone -- edited after cloning -- is left alone; one somehow edited with the
    marker still on it is left alone too, with a note, rather than discarding the edit). Never
    called for `--target` (a target directory never had these files at all, see `step_materialize`).
    `selected_bridges` (this run's step 5 result) says which of them actually get a replacement
    written below -- CLAUDE.md's bridge is gated on the `claude-code` tool, so a project that
    doesn't use it never gets one back; the message says so instead of always claiming "replaced"
    (review finding, wording only -- the removal itself was already correct).

    Returns (messages, dest names -- "AGENTS.md"/"CLAUDE.md"/... -- removed here, or that would be
    removed under `plan`): the bridge writer treats a name in that set as absent even though
    `dest.is_file()` may still be true (a `plan` run touches nothing), instead of reporting
    "already present, left unchanged" for a file about to be replaced."""
    messages: list[str] = []
    force: set[str] = set()
    selected_dests = {spec["dest"] for spec in selected_bridges.values()}

    def remove_entry(rel_path: str, will_be_replaced: bool):
        replaced_by = (
            "replaced by its project bridge below" if will_be_replaced
            else "this project's tools don't include one that uses it, so nothing replaces it"
        )
        def _do(inner_plan: bool) -> str:
            verb = "would be removed" if inner_plan else "removed"
            if not inner_plan:
                (root / rel_path).unlink()
            return f"{rel_path} {verb} (template bootstrap file, {replaced_by})"
        return _do

    # Every root-level bootstrap entry file the template ships: derived from BRIDGES itself (kind
    # "verbatim", dest with no "/") rather than a hardcoded ("AGENTS.md", "CLAUDE.md") pair, so a
    # bridge added there later (e.g. GEMINI.md) is covered automatically, without touching this
    # function again. GEMINI.md ships as a bootstrap file too (Gemini CLI reads it, not AGENTS.md)
    # but has no project bridge, so it is added by name and simply removed.
    root_entry_names = [
        spec["dest"] for spec in BRIDGES.values()
        if spec["kind"] == "verbatim" and spec["dest"].endswith(".md") and "/" not in spec["dest"]
    ]
    root_entry_names += [name for name in _BOOTSTRAP_ONLY_FILES if name not in root_entry_names]
    root_entry_files = [(name, f"{Path(name).stem}.template.md") for name in root_entry_names]
    for rel_path, backup_name in root_entry_files:
        if not (root / rel_path).is_file():
            continue
        message = _retire_template_readme(
            root, plan, rel_path, template_commit, backup_name, notes,
            remove_entry(rel_path, rel_path in selected_dests), marker=TEMPLATE_BOOTSTRAP_MARKER,
        )
        messages.append(message)
        if "removed" in message:
            force.add(rel_path)
    return messages, force


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
    generated_hashes: Optional[dict[str, str]] = None,
) -> str:
    """`generated_hashes` (T76 wave D review, round 3): the fingerprint of each generated bridge
    exactly as step 6 wrote it -- read by main() right after step_materialize, *before* the same
    run's carry-over (Weg C, owner profile) edits docs/ai/rules.md or coding_rules.md (a group
    switched off with its reason, an own rule). Hashing here, after those edits, used to record
    the edited state as "generated": the first session start (checks/session.py _refresh_bridges,
    likewise update.py's refresh) then saw an "unchanged" bridge and wrote it back raw from
    .act/bridges/, silently dropping everything carried over (orchestrator's own run, 2026-09-26).
    With the pre-carry-over hash recorded, the edited file counts as "edited locally" from the
    start -- the same state as a checkbox the owner unticks by hand, which the refresh leaves
    alone. Falls back to hashing here when not given (nothing edited in between)."""
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
    if generated_hashes is None:
        generated_hashes = {rel: actlib.generated_hash(path) for rel, path in generated.items() if path.is_file()}
    hashes = dict(generated_hashes)
    if not plan:
        actlib.write_cache({"generated": hashes})
    return (
        f"lock written (version '{version}'), {len(copies)} skill-copy hash(es), "
        f"cache with {len(hashes)} generated bridge(s), MANIFEST.json written"
    )


# ---------------------------------------------------------------------------
# Step 10 — first commit, by pathspec
# ---------------------------------------------------------------------------

def _remove_old_template_branch(root: Path, plan: bool, old_branch_tip: str) -> str:
    """Removes the local 'template' branch step_git_in_place left behind (the clone's old history,
    now superseded by the orphan 'main' step 10 just committed) -- so nobody can later merge it
    back into 'main' by accident (Wolfgang 2026-09-25, Q101b); the template's own history stays
    reachable on GitHub regardless, and updates from here on only ever come in via update.py, never
    a merge. Called only when GitInPlaceResult.can_delete_old_branch was True (see main()) -- an
    untouched clone, verified against 'origin' before it was removed (review HIGH/B142/T76 S1+S3;
    see step_git_in_place/_old_branch_disposition for the conditions checked and why deleting on
    weaker evidence used to lose a project's own commits). Called only once the first real commit on
    the new 'main' has actually landed (see main()) -- deleting it any earlier would risk losing the
    old history with nothing committed yet to replace it. A failed delete (e.g. the branch is
    checked out elsewhere, or already gone) is reported, never fatal -- the commit on 'main' already
    stands either way. `old_branch_tip` (read in step_git_in_place, before the branch's own history
    became unreachable) is only for the report -- "(was <sha>)" -- so the deleted commit stays
    findable in `git reflog`/`git fsck --unreachable` without anyone having to remember it."""
    short_tip = f" (was {old_branch_tip[:12]})" if old_branch_tip else ""
    if plan:
        return f"would remove old 'template' branch{short_tip}"
    result = _git(["branch", "-D", "template"], cwd=root, check=False)
    if result.returncode != 0:
        return f"old 'template' branch left in place -- delete failed: {result.stderr.strip()}"
    return f"old 'template' branch removed{short_tip}"


INIT_COMMIT_MESSAGE = "chore: initialize project from template"
PROFILE_COMMIT_MESSAGE = "chore: apply owner profile (init.py --profile)"


def step_commit(root: Path, plan: bool, no_commit: bool, paths: list[Path],
                message: str = INIT_COMMIT_MESSAGE) -> str:
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
    _git(["commit", "-m", message], cwd=root)
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


def step_dependency_check_note(root: Path, plan: bool) -> tuple[Optional[Path], str]:
    """B102/Q68: `dependency-check: once` (the skeleton's default, docs/ai/config.md § Dependencies)
    means the check "runs during setup and then only on demand" — this leaves the one-time inbox
    entry that turns that into an actual prompt to run `act-deps`, so `once` is not merely a
    stated intent. Reads the value from the config.md this run just wrote (docking onto a project
    keeps its own value); a plan run without a config.md yet assumes the skeleton default `once`,
    same fallback shape as step_translate_note."""
    config_path = root / "docs" / "ai" / "config.md"
    dependency_check = "once"
    if not plan and config_path.is_file():
        dependency_check = actlib.read_config().get("dependency-check", "once")
    if dependency_check.strip().lower() != "once":
        return None, ""
    if plan:
        return None, "would note in the inbox: check dependencies once (`act-deps`)"
    dest = actlib.write_dependency_check_note(root, dependency_check, plan)
    if dest is None:
        return None, "dependency check: entry already exists"
    return dest, f"{_relative_label(dest, root)}: created (dependency-check: once — run `act-deps`)"


# ---------------------------------------------------------------------------
# B117/Q86a a — offer `security-check: deps` once a tool Art B could use is actually installed on
# this machine (never switch the value silently, see step_security_check_offer's own docstring).
# ---------------------------------------------------------------------------

SECURITY_CHECK_OFFER_NOTE_SUFFIX = "-security-check-deps.md"


def security_check_offer_note_text(root: Path, tools: dict[str, str]) -> str:
    language = actlib.docs_language(root)
    tool_list = ", ".join(sorted(tools))
    heading = actlib.localized(
        language,
        "# Turn on the dependency-vulnerability check?",
        "# Die Abhängigkeits-Sicherheitsprüfung einschalten?",
    )
    body = actlib.localized(
        language,
        f"`security-check` in `docs/ai/config.md` is `local` (the default): only Art A (dangerous "
        f"patterns) runs on commit. This machine already has {tool_list} installed, which Art B "
        "(a live dependency-vulnerability lookup, `.act/scripts/security_scan.py`) can use — set "
        "`security-check` to `deps` in `docs/ai/config.md` to turn it on (see that file's own "
        "`security-check` row for what it does and does not cover). Left as `local` until you "
        "decide — this note does not change the value itself.\n",
        f"`security-check` in `docs/ai/config.md` steht auf `local` (Vorgabe): nur Art A "
        f"(gefährliche Muster) läuft beim Commit. Auf dieser Maschine ist bereits {tool_list} "
        "installiert, was Art B (eine Live-Abfrage bekannter Abhängigkeits-Schwachstellen, "
        "`.act/scripts/security_scan.py`) nutzen kann — `security-check` in `docs/ai/config.md` "
        "auf `deps` setzen, um sie einzuschalten (siehe die `security-check`-Zeile dort für Umfang "
        "und Grenzen). Bleibt auf `local`, bis entschieden ist — dieser Hinweis ändert den Wert "
        "nicht selbst.\n",
    )
    return f"kind: todo\nfor: all\nstatus: open\n\n{heading}\n\n{body}"


def step_security_check_offer(root: Path, plan: bool) -> tuple[Optional[Path], str]:
    """B117/Q86a a: `init` offers `security-check: deps` (never switches to it silently) once an
    installed tool actually matches a lock file this project has (2026-09-27 review, item 16: not
    merely "some tool from `TOOL_NAMES` is on PATH" -- a machine with npm installed but no
    `package-lock.json` here has nothing Art B could use yet) — an inbox note, the same
    non-interactive shape `step_dependency_check_note` already uses for its own one-time ask, since
    `init.py` never prompts on its own (`actlib.is_interactive()` reads false from the assistant's
    own Bash tool). Only while the project's own `security-check` value is still the skeleton
    default `local` — a project that already chose `off`/`deps`/`full` for itself is never
    second-guessed here. A plan run without a config.md yet, one with no lock file at all, or one
    whose scan turns up nothing installed for the lock files it does have, offers/notes nothing.
    Writes directly with actlib's own public inbox helpers (`INBOX_DIR`/`inbox_entry_filename`/
    `write_text_lf`) rather than a new actlib function of its own, the same way every other
    `step_*` function here already uses them."""
    config_path = root / "docs" / "ai" / "config.md"
    security_check = "local"
    if not plan and config_path.is_file():
        security_check = actlib.read_config().get("security-check", "local")
    if security_check.strip().lower() != "local":
        return None, ""
    try:
        lock_files = security_scan.detect_lock_files(root)
    except OSError as exc:
        print(f"[act] security-check offer: could not scan for lock files ({exc})", file=sys.stderr)
        lock_files = {}
    if not lock_files:
        return None, ""
    try:
        tools = security_scan.available_tools()
    except OSError as exc:
        print(f"[act] security-check offer: could not detect installed tools ({exc})", file=sys.stderr)
        tools = {}
    relevant: dict[str, str] = {}
    if "osv-scanner" in tools:
        relevant["osv-scanner"] = tools["osv-scanner"]
    if "npm" in lock_files and "npm" in tools:
        relevant["npm"] = tools["npm"]
    if "composer" in lock_files and "composer" in tools:
        relevant["composer"] = tools["composer"]
    if "pip-audit" in tools and any(
        path.name in security_scan.PIP_AUDIT_LOCK_NAMES for path in lock_files.get("python", [])
    ):
        relevant["pip-audit"] = tools["pip-audit"]
    if not relevant:
        return None, ""
    if plan:
        return None, "would note in the inbox: offer security-check: deps (a tool is installed)"
    inbox = root / actlib.INBOX_DIR
    if inbox.is_dir() and any(inbox.glob(f"*{SECURITY_CHECK_OFFER_NOTE_SUFFIX}")):
        return None, "security-check offer: entry already exists"
    dest = inbox / actlib.inbox_entry_filename("todo", "security-check-deps")
    dest.parent.mkdir(parents=True, exist_ok=True)
    actlib.write_text_lf(dest, security_check_offer_note_text(root, relevant))
    return dest, (f"{_relative_label(dest, root)}: created (security-check: deps offer — "
                  f"{', '.join(sorted(relevant))} installed)")


# ---------------------------------------------------------------------------
# Inbox note for open points
# ---------------------------------------------------------------------------

# Markers of an existing project (its own docs, or another AI tool's files) that init.py itself
# never merges -- act-adopt does that (backlog B118#9). Checked in --target mode only: in-place
# runs happen inside the template checkout itself, which has none of these yet.
_ADOPT_HINT_MARKERS = ("docs", "AGENTS.md", "CLAUDE.md", ".claude", "AI-CONFIG.md")


def _existing_project_hint(root: Path, source_act: Path) -> str | None:
    """`source_act` is the template checkout this run is executing from (.act/) -- act-adopt is
    never copied into a project (_SKILLS_NOT_COPIED), so the hint points at the skill file there,
    not at a path that may not exist under `root`."""
    # adopt.py --apply writes its own state file at this fixed path *before* it shells out to
    # init.py --target (its ADOPT_DIR + "state.json") -- if it is already there, this run came from
    # act-adopt itself, and telling act-adopt to see act-adopt would be circular noise (review
    # B116/4). Not a flag or an env var: adopt.py has neither, and this marker it already writes
    # says the same thing without touching adopt.py at all. The one edge case this misses -- a
    # stale state.json left over from an earlier, unrelated adopt attempt -- just suppresses a hint
    # that would have been wrong for a different reason anyway (the project *is* mid-adoption).
    if (root / ".act-local" / "adopt" / "state.json").exists():
        return None
    found = [name for name in _ADOPT_HINT_MARKERS if (root / name).exists()]
    if not found:
        return None
    skill_path = source_act / "skills" / "act-adopt" / "SKILL.md"
    return (
        f"  target already has {', '.join(found)} -- see {skill_path} to fold an existing project's "
        "docs/AI-tool files in instead of starting from a bare skeleton"
    )


def _write_inbox_note(root: Path, owner: str, notes: list[str], plan: bool) -> Path | None:
    # Each note asks the owner to look at (and often fix) something init.py could not decide on
    # its own -- an action, not just a read -- so `kind: todo` (16-inbox-questions-tasks.md §
    # "Arten in der Inbox"), never `report`. A second run before this one is answered reuses the
    # same file (matched by the fixed "init-notes" slug) instead of adding another -- but only
    # while that file is still open or answered; a `done` one (already acted on) never blocks a
    # fresh note silently.
    if not notes:
        return None
    inbox_dir = root / actlib.INBOX_DIR
    existing = sorted(inbox_dir.glob("todo-*-init-notes.md")) if inbox_dir.is_dir() else []
    blocking = None
    for candidate in existing:
        try:
            text = candidate.read_text(encoding="utf-8")
        except OSError:
            continue
        match = re.search(r"(?im)^status:\s*(.*?)\s*$", actlib.header_block(text))
        status = match.group(1).strip() if match else "open"  # no status field: treat as open
        if status in ("open", "answered"):
            blocking = candidate
    dest = blocking if blocking is not None else inbox_dir / actlib.inbox_entry_filename("todo", "init-notes")
    n = 2
    while blocking is None and dest.exists():  # a `done` one from the same minute: never overwrite it
        dest = inbox_dir / f"todo-{actlib.entry_stamp()}-{n}-init-notes.md"  # still matches the glob above
        n += 1
    if blocking is not None or plan:
        return None if plan else dest
    title = actlib.localized(
        actlib.docs_language(root),
        "# Open points from `init.py` (non-interactive run)",
        "# Offene Punkte von `init.py` (nicht-interaktiver Lauf)",
    )
    lines = ["kind: todo", f"for: {owner}", "status: open", f"created: {date.today().isoformat()}",
              "", title, ""]
    lines.extend(f"- {note}" for note in notes)
    actlib.write_text_lf(dest, "\n".join(lines) + "\n")  # B134: LF regardless of platform
    return dest


# ---------------------------------------------------------------------------
# `init.py --profile` inside a project that is already set up (Q103 a1's "catch up" path)
# ---------------------------------------------------------------------------

def run_profile_only(root: Path, plan: bool, interactive: bool, no_commit: bool, reason: str) -> int:
    """What `init.py --profile` does inside a project that already went through init (no
    `--target`; main() lands here instead of refusing, T76 wave D review round 2): the owner
    profile a non-interactive first run only left a todo for is applied now, and nothing else
    happens. Exactly one step -- step_owner_profile with `auto_apply` (entries shown, applied
    without a question, whatever needs a verdict goes to the settings inbox) -- then a commit of
    the paths that step wrote plus its own inbox note, if any. Nothing of a full run: no step 2
    (the branch rename and orphan rebuild the guard in main() exists to prevent), no bridges, no
    skeleton, no lock, and no .act-local/cache.json rewrite either -- a docs/ai/rules.md the
    profile changed then no longer matches its recorded hash, which is exactly the "edited locally,
    left alone" state the session-start bridge refresh preserves (checks/session.py
    _refresh_bridges); re-recording the hash would hand the file back to that refresh."""
    print(f"[act] --profile: {reason} -> owner-profile step only, nothing else is touched")
    notes: list[str] = []
    summary, written_paths = step_owner_profile(root, plan, interactive, True, True, notes)
    print(f"  {summary}")
    owner = actlib.read_config().get("owner", "").strip() or "unknown"
    inbox_path = _write_inbox_note(root, owner, notes, plan)
    commit_paths = list(written_paths)
    if inbox_path is not None:
        commit_paths.append(inbox_path)
    print(f"  {step_commit(root, plan, no_commit, commit_paths, message=PROFILE_COMMIT_MESSAGE)}")
    if notes:
        print(f"[act] done - {len(notes)} open point(s) " + ("would go to" if plan else "left in") + " docs/ai/inbox/")
    else:
        print("[act] done - no open points")
    return 0


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

    parser = argparse.ArgumentParser(
        description="Turn a template checkout into a project, or dock onto an existing directory "
                    "(--target). Inside a project that is already set up, only --profile runs (see "
                    "there); bringing .act/ up to date is update.py's job.",
    )
    parser.add_argument("--target", help="create/dock in this directory instead of the current checkout")
    parser.add_argument("--plan", action="store_true", help="show what would happen, change nothing")
    parser.add_argument("--non-interactive", action="store_true", help="never prompt; take defaults, log open points to the inbox")
    parser.add_argument("--no-commit", action="store_true", help="do everything except the final commit")
    parser.add_argument("--no-local", action="store_true",
                        help="--target only: don't carry over the source checkout's own rule/coding-rule "
                             "deviations and docs/ai/local/ (Weg C, on by default)")
    parser.add_argument("--no-profile", action="store_true",
                        help="don't offer the owner profile at %%APPDATA%%\\act\\settings.md / "
                             "~/.config/act/settings.md (Q103, on by default)")
    parser.add_argument("--profile", action="store_true",
                        help="apply the owner profile without asking (its entries are shown first). "
                             "Inside a project that is already set up (no --target) this is the only "
                             "step that runs -- nothing else is touched, only what it wrote is "
                             "committed (Q103 a1's 'catch up' path after a non-interactive first "
                             "run); in a fresh clone or with --target it is part of the full run")
    parser.add_argument("--language-docs", metavar="CODE",
                        help="language of docs/ (e.g. de) instead of asking; default en (R-work-language)")
    parser.add_argument("--language-chat", metavar="CODE",
                        help="chat language (a code, or auto = follow the owner's messages) instead of asking")
    args = parser.parse_args(argv)
    if args.profile and args.no_profile:
        parser.error("--profile and --no-profile contradict each other")

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
            hint = _existing_project_hint(root, source_act)
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

        # B130: refuse before asking anything -- when this checkout is the template's own
        # development checkout, never a project to build in place, this has to be caught before
        # step_config's own questions (step 1), not only once step_git_in_place (step 2) runs --
        # otherwise a refusal still means the owner was asked project name/owner/stack first for
        # nothing. Read-only, so a refusal leaves the clone exactly as it was found.
        dev_reason = _template_dev_checkout_reason(root)
        if dev_reason:
            marker_present = (root / ".act-local" / "template-dev").exists()
            advice = "run with '--target <dir>' to build a project (or a throwaway probe) elsewhere"
            if marker_present:
                advice += (
                    ", or delete '.act-local/template-dev' if this really is a fresh clone meant "
                    "to become a project"
                )
            if plan:
                print(
                    f"[act] repository already present; would refuse to run in place ({dev_reason}); "
                    f"'origin' and the current branch would be left unchanged; {advice}"
                )
                return 0
            print(
                f"init.py: {dev_reason} -- refusing to run in place; 'origin' and the current "
                f"branch are left unchanged; {advice}",
                file=sys.stderr,
            )
            sys.exit(1)

        # T76 wave D review (round 2, HIGH): a project that already went through init -- its own
        # .act-lock.json (step 9) or docs/ai/config.md (step 6) is there -- is never "a clone to
        # turn into a project" again. Step 2 would rename its current branch to 'template' and
        # rebuild 'main' as an orphan with none of the project's own history on it; the B130 check
        # above cannot catch this (a project is neither the dev checkout nor a multi-worktree
        # repository). Refused here, read-only, before step_config's questions -- with one
        # deliberate exception: `--profile`, Q103 a1's "catch up" path, runs the owner-profile
        # step alone (run_profile_only) and nothing else.
        set_up_reason = _set_up_project_reason(root)
        if set_up_reason:
            if args.profile:
                return run_profile_only(root, plan, actlib.is_interactive() and not plan, args.no_commit, set_up_reason)
            consequence = (
                "step 2 would rename the current branch to 'template' and rebuild 'main' as an "
                "orphan branch without this project's own history"
            )
            advice = (
                "to apply the owner profile here, run 'init.py --profile' (in a set-up project only "
                "that step runs); to bring .act/ up to date, run 'python .act/scripts/update.py'; "
                "to build a new project from this one, run 'init.py --target <dir>'"
            )
            if plan:
                print(f"[act] {set_up_reason}; would refuse to run in place ({consequence}); nothing changed; {advice}")
                return 0
            print(
                f"init.py: {set_up_reason} -- refusing to run in place: {consequence}; nothing was "
                f"changed; {advice}",
                file=sys.stderr,
            )
            sys.exit(1)

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

    orphan_rebuilt = False
    can_delete_old_branch = False
    old_branch_tip = ""
    if is_target:
        summary, template_origin, template_commit = step_git_target(root, plan, source_act)
        verify_commit = template_commit
        _print_step(2, summary)
    else:
        git_result = step_git_in_place(root, plan)
        summary = git_result.summary
        template_origin = git_result.template_source
        template_commit = git_result.template_commit
        orphan_rebuilt = git_result.orphan_rebuilt
        verify_commit = git_result.verify_commit
        can_delete_old_branch = git_result.can_delete_old_branch
        old_branch_tip = git_result.old_branch_tip
        _print_step(2, summary)
        if orphan_rebuilt and not can_delete_old_branch:
            notes.append(
                f"The old branch 'template' was kept -- {git_result.keep_old_branch_reason}. "
                "Review it, fold anything worth keeping into 'main', or delete it yourself "
                "once you're sure (`git branch -D template`)."
            )

    _print_step(3, step_identity(root, plan, interactive, notes))
    _print_step(4, f"{step_workspace_identity(root, plan, cfg['owner'])}; {step_import_folder(root, plan)}")

    selected_bridges, thin_summary = step_thin_bridges(cfg["tools"])
    _print_step(5, thin_summary)

    # B143#4b: whether the target already had its own docs/ai/rules.md / coding_rules.md *before*
    # this run -- captured here, before step_materialize can create either from the skeleton, so
    # `_carry_over_area` only ever touches a file this run itself materialized, never a docked
    # project's own already-established checkbox choices.
    dest_was_preexisting = {
        area.project_file: (root / area.project_file).is_file()
        for area in (rules.AREAS["core"], rules.AREAS["coding"])
    } if is_target else {}

    materialize_messages, generated, touched_bridges, copies = step_materialize(
        root, plan, cfg, selected_bridges, notes, is_target=is_target, template_commit=verify_commit,
    )
    # Fingerprint of every generated bridge exactly as written -- taken now, before this step's
    # carry-over below (Weg C / owner profile) may edit docs/ai/rules.md or coding_rules.md; step 9
    # records these instead of re-hashing the edited files (see step_lock_and_cache). Nothing else
    # between here and step 9 touches a generated file: step 7 writes .gitignore/.gitattributes,
    # step 8 README.md/LICENSE only.
    generated_hashes = {rel: actlib.generated_hash(path) for rel, path in generated.items() if path.is_file()}
    translate_path, translate_message = step_translate_note(root, plan, cfg)
    if translate_message:
        materialize_messages.append(translate_message)
    dependency_check_path, dependency_check_message = step_dependency_check_note(root, plan)
    if dependency_check_message:
        materialize_messages.append(dependency_check_message)
    security_check_offer_path, security_check_offer_message = step_security_check_offer(root, plan)
    if security_check_offer_message:
        materialize_messages.append(security_check_offer_message)
    imported_paths: list[Path] = []
    if is_target:
        combined_summary, combined_paths = step_source_and_profile(
            root, plan, interactive, source_act.parent, not args.no_local, not args.no_profile,
            args.profile, dest_was_preexisting, notes,
        )
        if combined_summary:
            materialize_messages.append(combined_summary)
        imported_paths.extend(combined_paths)
    else:
        profile_summary, profile_paths = step_owner_profile(
            root, plan, interactive, not args.no_profile, args.profile, notes,
        )
        materialize_messages.append(profile_summary)
        imported_paths.extend(profile_paths)
    _print_step(6, "; ".join(materialize_messages))

    gitfiles_messages, touched_gitfiles = step_git_files(root, plan)
    _print_step(7, "; ".join(gitfiles_messages))

    # README.md/LICENSE at the repo root, whatever step 8 below did with them (replaced, kept
    # as-is, or left as the project's own) -- always re-added to the new commit here, in-place
    # only: step 2's orphan rebuild of 'main' drops every path from the index, including these two,
    # so leaving them out of `commit_paths` would leave them as untracked residue after step 10's
    # pathspec commit even though nothing about them needs a human decision (found in T76's own
    # probe, tests/probes/t76-bootstrap; --target never touches them, same reasoning as step 8).
    own_root_files: list[Path] = []
    if is_target:
        _print_step(8, "skipped in --target mode (docking onto an existing project, nothing of the template's own to decide)")
    else:
        _print_step(8, step_own_files(root, plan, interactive, cfg, verify_commit, notes))
        own_root_files = [p for p in (root / "README.md", root / "LICENSE") if p.is_file()]

    _print_step(9, step_lock_and_cache(root, plan, template_origin, template_commit, generated, copies, generated_hashes))

    inbox_path = _write_inbox_note(root, cfg["owner"], notes, plan)
    commit_paths = [
        root / ".act", root / ".act-lock.json", *touched_bridges, *touched_gitfiles, *own_root_files,
        # Weg C (docs/ai/local/ copy) and the owner-profile import (scripts/checklists/agents/
        # skills + their tool bridges) each report exactly the paths they wrote (B143#1) -- never a
        # whole-directory add (`docs/ai/local`, `.claude`, `.agents`), which would sweep in
        # anything else already sitting there, including a target's own untracked files.
        *imported_paths,
    ]
    if inbox_path is not None:
        commit_paths.append(inbox_path)
    if translate_path is not None and not plan:
        commit_paths.append(translate_path)
    if dependency_check_path is not None and not plan:
        commit_paths.append(dependency_check_path)
    if security_check_offer_path is not None and not plan:
        commit_paths.append(security_check_offer_path)
    commit_message = step_commit(root, plan, args.no_commit, commit_paths)
    # The old 'template' branch is only ever removed once a real commit landed on the new 'main'
    # (never under --plan, --no-commit, or a run that had nothing to commit) *and*
    # can_delete_old_branch held (review HIGH/B142/T76 S1+S3) -- see _remove_old_template_branch
    # and step_git_in_place/_old_branch_disposition.
    commit_landed = commit_message.startswith("committed") or (plan and commit_message.startswith("would commit"))
    if orphan_rebuilt and can_delete_old_branch and not is_target and not args.no_commit and commit_landed:
        commit_message += f"; {_remove_old_template_branch(root, plan, old_branch_tip)}"
    _print_step(10, commit_message)

    if notes:
        print(f"[act] done - {len(notes)} open point(s) " + ("would go to" if plan else "left in") + " docs/ai/inbox/")
    else:
        print("[act] done - no open points")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
