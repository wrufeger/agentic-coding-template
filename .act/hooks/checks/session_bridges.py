"""Session start, derived files: board refresh and the tool bridges (CLAUDE.md, roles, hook entries)
re-derived from their sources.

Split out of session.py, which keeps the entry point and the order of the sub-steps."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

import actlib

def _refresh_board(root: Path) -> None:
    """Run .act/scripts/board.py if it exists yet (a parallel task builds it); do nothing,
    silently, otherwise — per the build order for this script."""
    board_script = root / ".act" / "scripts" / "board.py"
    if not board_script.is_file():
        return
    try:
        subprocess.run([sys.executable, str(board_script)], cwd=root, timeout=15, capture_output=True)
    except (OSError, subprocess.TimeoutExpired):
        pass  # a broken board refresh must not block the session


# Destination (repo-root-relative) -> source filename under .act/bridges/, for exactly the
# bridges .act/bridges/gitattributes marks `merge=ours`. Only these are re-derived here; keep
# this map and that file's merge=ours lines in sync if a later stage adds more bridges.
_BRIDGE_MAP = {
    "CLAUDE.md": "CLAUDE.md",
    "AGENTS.md": "AGENTS.md",
    "docs/ai/rules.md": "rules.md",
}


def _bootstrap_marker() -> Optional[str]:
    """init.py's TEMPLATE_BOOTSTRAP_MARKER (the first line "<!-- act:bootstrap -->" a bare
    template clone's own root CLAUDE.md/AGENTS.md carry before `init` ever runs),
    imported lazily like `update`/`rules` elsewhere in this module so a session start never pays
    for init.py's own (much larger) import cost unless this one constant is actually needed.
    None if init.py cannot be imported at all -- the caller then treats every bootstrap check as
    "not a bootstrap file", the same fail-open stance every other best-effort note here takes."""
    try:
        from init import TEMPLATE_BOOTSTRAP_MARKER  # deferred: see the header comment
    except Exception:
        return None
    return TEMPLATE_BOOTSTRAP_MARKER


def _first_line(path: Path) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.readline().strip()
    except OSError:
        return ""


def _is_bootstrap_copy(dest_path: Path, lock_present: bool, marker: Optional[str]) -> bool:
    """True when `dest_path` is not the project's own CLAUDE.md/AGENTS.md but a copy of the
    template's own bootstrap file (first line `marker`) that landed on top of it -- a raw `git
    pull` of the template's shared history bringing in its root entry files verbatim rather than
    going through `update.py`. Only meaningful once the project is actually set up
    (`.act-lock.json` present, `lock_present`): a bare clone not yet run through `init` legitimately
    still carries the marker on its own root files, and those are `init`'s job to replace, not
    this one's (see `_bootstrap_entry_files` in init.py)."""
    if not lock_present or marker is None:
        return False
    return _first_line(dest_path) == marker


def _apply_artifact_setting(root: Path, config: dict[str, str], write: bool) -> tuple[list[str], list[str]]:
    """Applies the `artifacts` value of docs/ai/config.md to an existing .claude/settings.json
    (actlib.merge_settings_artifact); a project without that file gets none. With `write=False`
    (session-start-refresh `warn`) nothing is written: the second list holds the "would ..." notes.
    Returns (notes to print, notes for the warn digest)."""
    path = root / ".claude" / "settings.json"
    if not path.is_file() or not (root / ".act-lock.json").is_file():
        return [], []
    try:
        current = json.loads(path.read_text(encoding="utf-8"))  # a BOM file stays alone, as in init/update
    except (OSError, ValueError):
        return [], []
    new_current, changed, notes, booking = actlib.merge_settings_artifact(
        root, current, actlib.artifacts_mode(config), once=True)
    if write:
        try:
            if changed:
                path.write_text(json.dumps(new_current, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            # the booking goes into the lock only after settings.json is written
            actlib.write_settings_booking(root, booking)
        except OSError:
            return [], []
    if write:
        return notes, []
    # warn: the conflict note already went out once via the cache; a pending change is only named
    pending = [n for n in notes if n.startswith("Artifact")]
    would = ["[act] note: Artifact tool would be switched off (`artifacts: off`; warn mode, not applied)"
             if n.startswith("Artifact tool switched off") else
             "[act] note: Artifact tool would no longer be switched off (`artifacts: on`; warn mode, not applied)"
             for n in pending]
    return [n for n in notes if n not in pending], would


def _follow_rules_md(root: Path, write: bool) -> list[str]:
    """Notes on what a locally edited docs/ai/rules.md lacks of the template and what was entered into
    it (rules.add_missing_core_entries; with write=False only said, nothing written). Never raises."""
    try:
        import rules  # deferred like the other rules.py uses here: a broken rules.py must not end the session
        result = rules.add_missing_core_entries(root, write=write)
    except Exception:  # noqa: BLE001 - a failed look is no reason to stop the session
        return []
    notes: list[str] = []
    if result.messages:
        verb = "entered" if write else "would be entered (warn mode, not applied)"
        notes.append(f"[act] note: docs/ai/rules.md {verb}: {'; '.join(result.messages)}")
    notes.extend(f"[act] note: docs/ai/rules.md: {problem}" for problem in result.problems)
    # No record of what was offered yet: files it does not import are named, once (the cache keeps the
    # wording shown last), never entered here — the first update starts the record from git.
    unlisted_note = ""
    if result.unlisted:
        unlisted_note = (f"[act] note: docs/ai/rules.md does not import {', '.join(result.unlisted)}; nothing "
                         f"tells whether you left them out on purpose. To enter them: {rules.ADD_MISSING_COMMAND}")
    try:
        if actlib.read_cache().get("rules_unlisted_note", "") != unlisted_note:
            if write:
                actlib.write_cache({"rules_unlisted_note": unlisted_note})
            if unlisted_note:
                notes.append(unlisted_note)
    except Exception:  # noqa: BLE001 - a broken cache must not hide the note
        if unlisted_note:
            notes.append(unlisted_note)
    return notes


def _scoped_bridge_text(root: Path, dest_rel: str, text: str, record: bool = False) -> str:
    """`text` of a generated bridge as this project's scope (docs/ai/config.md § Scope; act_profile.py)
    wants it written: for docs/ai/rules.md the import line of each excluded rule file is the bare path
    (rules.apply_core_cut), any other bridge is returned as it is. With `record` the lines it switches
    off are first entered in the lock's `rules_cut`, so the scope can switch them on again when the
    exclusion ends; when that cannot be written (no lock, a lock that cannot be read), or on any
    failure, the text is returned uncut — a line cut without its record would never come back."""
    if dest_rel != "docs/ai/rules.md":
        return text
    try:
        import act_profile  # deferred like rules/update: a broken module must not end the session
        import rules
        cut_files = act_profile.read_cut(root).rules
        if not cut_files or actlib.read_lock_at(root) is None:
            return text
        cut_text, switched = rules.apply_core_cut(text, cut_files)
        if not switched:
            return text
        if record:
            recorded = set(actlib.read_rules_cut(root))
            if not set(switched) <= recorded and not actlib.write_rules_cut(root, sorted(recorded | set(switched))):
                return text
        return cut_text
    except Exception:  # noqa: BLE001 - the scope is best effort; the uncut bridge is always a valid file
        return text


def _refresh_bridges(root: Path, write: bool, only_changed: bool = True) -> tuple[list[str], list[str], list[str]]:
    """
    Re-derive every generated bridge that is still exactly as it was last generated (current
    hash matches .act-local/cache.json) from its .act/bridges/ source — this stands in for a
    registered `merge=ours` driver (see .act/bridges/gitattributes), which needs a per-machine
    `git config` no checkout is guaranteed to have. A bridge whose hash no longer matches was
    edited locally and is left untouched either way.

    One exception: a root CLAUDE.md/AGENTS.md that is not locally edited at all but a raw
    copy of the *template's own* bootstrap file (see `_is_bootstrap_copy`) never counts as "edited
    locally" — it never was the project's file to begin with, whatever its recorded hash says — so
    it is rewritten from the template source the same as an unchanged bridge, just reported
    separately (`bootstrapped`) rather than folded into `refreshed`.

    With `write=False` (check-mode-`warn`), nothing is written — the "refreshed"/"bootstrapped"
    lists report what would have changed instead, and (`only_changed`) only a bridge whose content
    really differs from its source. update.py's --plan passes `only_changed=False`: it runs before
    the new template is installed, so the installed sources say nothing about what will change.

    Returns (changed, refreshed, bootstrapped): `changed` are destinations left alone because
    they were edited locally; `refreshed` are destinations re-derived from the template (or that
    would have been, under write=False) because they still matched their last-generated hash;
    `bootstrapped` are destinations re-derived because they turned out to be the template's own
    bootstrap file instead (or that would have been, under write=False).

    Each file is written and cached individually rather than batching the cache write
    until after the whole loop — a read/write failure partway through the map (a locked file, a
    permission error) used to leave every file processed *before* the failure both unrecorded in
    the cache and outside the caller's `touched` list (built from `refreshed`, since that append
    happened before the write was even attempted), so a bridge the update genuinely rewrote never
    made it into the commit and then looked "edited locally" at every later run because its
    recorded hash never caught up with what was actually on disk. Now a failure on one file only
    ever costs that one file (left for the next run to retry, its old recorded hash still
    matching its unwritten content) — every file already written stays written, cached, and
    reported.
    """
    cache = actlib.read_cache()
    generated = cache["generated"]
    changed: list[str] = []
    refreshed: list[str] = []
    bootstrapped: list[str] = []
    lock_present = (root / ".act-lock.json").is_file()
    marker = _bootstrap_marker()

    for dest_rel, source_name in _BRIDGE_MAP.items():
        dest_path = root / dest_rel
        source_path = root / ".act" / "bridges" / source_name
        if not dest_path.is_file() or not source_path.is_file():
            continue  # not generated yet, or template source missing — nothing to do here

        recorded_hash = generated.get(dest_rel)
        if recorded_hash is None:
            continue  # never tracked as generated — not ours to touch

        is_bootstrap = _is_bootstrap_copy(dest_path, lock_present, marker)

        # Compared with line endings normalized (and still accepts an older, raw-byte
        # recorded hash) so a checkout's own line endings never make an untouched bridge look
        # "changed locally" on their own. Skipped for a bootstrap copy: its hash never
        # matches the recorded one either, but that mismatch is not a local edit to preserve.
        if not is_bootstrap and not actlib.generated_unchanged(dest_path, recorded_hash):
            changed.append(dest_rel)
            continue

        target_list = bootstrapped if is_bootstrap else refreshed

        # An unedited bridge that already equals its source (line endings aside) has nothing to
        # refresh. Rewriting it with LF would only change the bytes of a CRLF checkout
        # (core.autocrlf=true): git then lists the file as modified although `git diff` is empty.
        # docs/ai/rules.md is compared and written with the scope's cut applied (docs/ai/config.md §
        # Scope: an excluded rule file's import line is the bare path), on both sides, so a copy the
        # cut already reached is "the same" and a copy that was not yet cut is cut once, not flipped
        # back by this refresh and cut again by the scope step.
        try:
            same = (not is_bootstrap and
                    _scoped_bridge_text(root, dest_rel, source_path.read_text(encoding="utf-8").replace("\r\n", "\n"))
                    == _scoped_bridge_text(root, dest_rel, dest_path.read_text(encoding="utf-8").replace("\r\n", "\n")))
        except (OSError, UnicodeDecodeError):
            same = False

        if not write:
            # Only what would actually change.
            if not (same and only_changed):
                target_list.append(dest_rel)
            continue

        if same and only_changed:
            # Nothing to write. An older-format recorded hash still moves to the current form, as
            # a rewrite would have done, so a later renormalization can't make it look edited.
            current = actlib.generated_hash(dest_path)
            if generated.get(dest_rel) != current:
                generated[dest_rel] = current
                actlib.write_cache({"generated": generated})
            continue

        if not actlib.local_write_ok(root, root / ".act-local" / "cache.json"):
            continue  # the new hash could not be recorded: a rewrite would make the next start see the bridge as edited
        try:
            content = _scoped_bridge_text(root, dest_rel, source_path.read_text(encoding="utf-8"), record=True)
            actlib.write_text_lf(dest_path, content)
            generated[dest_rel] = actlib.generated_hash(dest_path)
        except (OSError, UnicodeDecodeError):
            continue  # left for the next run; every file already handled above stays reported
        target_list.append(dest_rel)
        actlib.write_cache({"generated": generated})

    return changed, refreshed, bootstrapped
