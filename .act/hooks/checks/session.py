#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: SessionStart handling — inbox "answered, not yet processed" count (the single inbox at
#          docs/ai/inbox/, all kinds — question/todo/report/note),
#          bridge/role-frontmatter re-derivation, board refresh, sync of the files that
#          hang on a
#          docs/ai/config.md value — skill copies, CLAUDE.md and hook entries on `tools`, a role's
#          bridges on its "## Roles" row (tier/reasoning/model) — when one moved since the last
#          snapshot (see update.sync_dependent_files(), imported lazily at that one
#          call site so a session start
#          never pays for/depends on `update`'s own imports — entries, rules, ... — just for this
#          best-effort sub-step), template-awareness notes (check 2b), the active-topics
#          status line, the import check and, only as a fallback, a short form of the
#          orchestrator-only rules when docs/ai/rules.md does not import them (all gated by
#          their own docs/ai/config.md row, see _check_mode), and the scope of docs/ai/config.md
#          § Scope (`profile`, `exclude`; act_profile.py): the import lines of excluded rule files,
#          one line naming the cut, topics left out. refresh_session() is
#          the single SessionStart entry point dispatch.py calls; everything below feeds into it.
#          Unlike the PreToolUse checks, this is not a list of independent pass/fail gates — every
#          sub-step is its own best-effort note or side effect, and refresh_session() must never
#          fail the session over any of them.
#
# Layout:  this module keeps the entry point (refresh_session), the order of the sub-steps and the
#          assembly of the output (_collect_session, _fit_context); the sub-steps live in
#          session_notes (inbox counts, docs-audit/dependency/compaction hints), session_bridges
#          (board refresh, bridges), session_update (template awareness, update lookup),
#          session_scans (dependency scan, act-local-tidy), session_rules (orchestrator rules),
#          session_context (compact note, identity, topics, ideas, scope). Every name stays
#          reachable as checks.session.<name>.

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import sys
from pathlib import Path
from typing import Optional

import actlib
import tiers

from .common import _check_mode
from .session_notes import (
    _DEPENDENCY_CHECK_DUE_DAYS, _DEPENDENCY_CHECK_TITLE_PREFIX, _DOCS_AUDIT_TITLE_PREFIX, _LEDGER_CREATED_RE,
    _LEDGER_DATE_IN_NAME_RE, _LEDGER_HEADING_RE, _STATUS_RE, _commits_since, _compact_due_note,
    _count_inbox_open, _count_inbox_waiting, _current_branch, _dependency_check_note, _docs_audit_note,
    _last_docs_audit_entry, _last_ledger_entry_with_prefix, _ledger_entry_date, _parse_archive_compact,
    _parse_docs_audit_due,
)
from .session_bridges import (
    _BRIDGE_MAP, _apply_artifact_setting, _bootstrap_marker, _first_line, _follow_rules_md,
    _is_bootstrap_copy, _refresh_board, _refresh_bridges,
)
from .session_update import (
    _advisory_notes, _check_update_awareness, _commit_day, _folder_source_result,
    _locked_commit, _ls_remote_output, _manifest_fingerprint, _pending_update_note,
    _pulled_without_update, _remote_commit_label, _remote_release_available, _remote_update_available,
    _run_advisory_lookup, _run_update_check_worker, _run_update_lookup, _spawn_update_check_worker,
    _update_channel, _update_channel_follows_tip_without_tags, _update_channel_is_default,
    _update_check_result_path, _update_check_state_path, _version_tuple,
)
from .session_scans import (
    _check_act_local_tidy, _check_security_scan_awareness, _consume_pending_security_scan_note,
    _consume_pending_tidy_note, _run_act_local_tidy_worker,
    _run_security_scan_worker, _security_scan_result_path,
    _security_scan_state_path, _spawn_act_local_tidy_worker, _spawn_security_scan_worker,
)
from .session_rules import (
    _CHECKBOX_RE, _OVERRIDE_RE, _RULE_ID_IN_TEXT_RE, _SECTION_HEADING_RE, _deliver_orchestrator_rules,
    _filter_orchestrator_file, _orchestrator_rules_imported, _orchestrator_short_lines, _read_rule_states,
)
from .session_context import (
    _EXCERPT_MARK, _IDE_SERVER_EXACT_NAMES, _IDE_SERVER_NAME_HINTS, _TOPIC_SWITCHES, _active_topics,
    _board_excerpt_block, _chat_language_line, _compact_note, _env_override_note, _ide_mcp_connected,
    _ideas_ensure_notes, _ideas_note, _ideas_pending, _identity_note, _is_ide_server_name, _output_depth_line,
    _outside_root_note, _same_project_path, _scope_notes, _servers_match_ide_hint, _user_mcp_servers,
)

__all__ = [
    "_current_branch",
    "_STATUS_RE",
    "_count_inbox_waiting",
    "_count_inbox_open",
    "_DOCS_AUDIT_TITLE_PREFIX",
    "_LEDGER_HEADING_RE",
    "_LEDGER_CREATED_RE",
    "_LEDGER_DATE_IN_NAME_RE",
    "_parse_docs_audit_due",
    "_ledger_entry_date",
    "_last_ledger_entry_with_prefix",
    "_last_docs_audit_entry",
    "_commits_since",
    "_docs_audit_note",
    "_DEPENDENCY_CHECK_TITLE_PREFIX",
    "_DEPENDENCY_CHECK_DUE_DAYS",
    "_dependency_check_note",
    "_parse_archive_compact",
    "_compact_due_note",
    "_refresh_board",
    "_BRIDGE_MAP",
    "_TOPIC_SWITCHES",
    "_IDE_SERVER_NAME_HINTS",
    "_IDE_SERVER_EXACT_NAMES",
    "_is_ide_server_name",
    "_servers_match_ide_hint",
    "_user_mcp_servers",
    "_same_project_path",
    "_ide_mcp_connected",
    "_active_topics",
    "_scope_notes",
    "_bootstrap_marker",
    "_first_line",
    "_is_bootstrap_copy",
    "_refresh_bridges",
    "_manifest_fingerprint",
    "_pulled_without_update",
    "_update_check_state_path",
    "_ls_remote_output",
    "_update_channel",
    "_version_tuple",
    "_remote_release_available",
    "_update_channel_is_default",
    "_update_channel_follows_tip_without_tags",
    "_folder_source_result",
    "_remote_update_available",
    "_update_check_result_path",
    "_pending_update_note",
    "_commit_day",
    "_remote_commit_label",
    "_locked_commit",
    "_run_update_check_worker",
    "_spawn_update_check_worker",
    "_check_update_awareness",
    "_run_update_lookup",
    "_run_advisory_lookup",
    "_advisory_notes",
    "_security_scan_state_path",
    "_security_scan_result_path",
    "_run_security_scan_worker",
    "_spawn_security_scan_worker",
    "_consume_pending_security_scan_note",
    "_check_security_scan_awareness",
    "_consume_pending_tidy_note",
    "_run_act_local_tidy_worker",
    "_spawn_act_local_tidy_worker",
    "_check_act_local_tidy",
    "_CHECKBOX_RE",
    "_OVERRIDE_RE",
    "_SECTION_HEADING_RE",
    "_RULE_ID_IN_TEXT_RE",
    "_read_rule_states",
    "_filter_orchestrator_file",
    "_deliver_orchestrator_rules",
    "_chat_language_line",
    "_orchestrator_short_lines",
    "_orchestrator_rules_imported",
    "CONTEXT_LIMIT",
    "_fit_context",
    "_board_excerpt_block",
    "_fit_excerpt",
    "_human_line",
    "_old_imports_note",
    "_changed_bridge_note",
    "_ideas_pending",
    "_ideas_note",
    "_ideas_ensure_notes",
    "_compact_note",
    "refresh_session",
]

# ---------------------------------------------------------------------------
# Session-start output — one JSON object: `additionalContext` for the model, kept under the
# 10,000-character cap above which Claude Code moves a hook's output into a file and shows only a
# preview (hooks.md: "capped at 10,000 characters ... a preview of up to the first 2,000
# characters"), and one
# top-level `systemMessage` line for the human ("Warning message shown to the user"). Plain text
# and JSON never mixed: everything the sub-steps print is captured and goes into the context.
# ---------------------------------------------------------------------------

CONTEXT_LIMIT = 9000  # characters; the harness cap is 10,000 per field, this leaves a margin
_LOCAL_SKIP_NOTE = "[act] note: writes behind a link were skipped"  # the one line about refused writes below .act-local
_TIDY_LINK_NOTE = "[act] note: act-local-tidy: skipped"  # act-local-tidy's own line when .act-local is linked
_RULES_MARK = "\x00act-orchestrator-rules\x00"
# Older forms Claude Code never loads: "@.act/..." (resolved from docs/ai/) and the orchestrator
# files listed in backticks instead of imported.
_OLD_IMPORT_RE = re.compile(r"^(?:@\.act/|`\.act/rules/orchestrator/)", re.MULTILINE)


def _old_rules_imports(root: Path) -> tuple[int, str]:
    """(count, sha256) of older "@.act/..." import lines left in docs/ai/rules.md — Claude Code
    resolves them from docs/ai/ and never finds them. (0, "") when there are none."""
    path = root / "docs" / "ai" / "rules.md"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return 0, ""
    count = len(_OLD_IMPORT_RE.findall(text))
    return (count, actlib.sha256_file(path)) if count else (0, "")


def _old_imports_note(root: Path) -> Optional[str]:
    """One note per state of a docs/ai/rules.md that still carries the old import form — one
    changed locally or never recorded as generated; an unchanged one was just re-derived by
    _refresh_bridges. Shown once, again only after the file changed and is still wrong.
    Remembered in .act-local/cache.json."""
    count, digest = _old_rules_imports(root)
    if not count:
        return None
    cache = actlib.read_cache()
    if cache.get("rules_import_hint") == digest:
        return None
    actlib.write_cache({"rules_import_hint": digest})
    return (f"[act] note: docs/ai/rules.md names {count} rule file(s) in a form "
            "Claude Code never loads (\"@.act/...\" or `.act/rules/orchestrator/...`) — write each "
            "as \"@../../.act/...\" (check: python .act/scripts/rules.py --imports)")


def _changed_bridge_note(root: Path, dest_rel: str) -> Optional[str]:
    """One note per changed state of a generated bridge that was edited locally: remembered
    by the pair (edited file's own content hash, template source's content hash) in
    .act-local/cache.json ("bridge_change_notes"), same pattern as _old_imports_note()'s
    "rules_import_hint" -- so it is not repeated at every session start while the edit stands, and
    noted again once the file changes further. The template source's own hash is part of the key
    too: a template update to the bridge source (e.g. .act/bridges/rules.md) while the project's
    copy stays locally edited must note again once -- the project's edit is now against a template
    version it has never been compared to, even though the local file itself did not change. This
    matters most for docs/ai/rules.md, which projects are invited to edit (own rules, § "Own
    rules")."""
    dest_path = root / dest_rel
    try:
        digest = actlib.normalized_sha256(dest_path)
    except OSError:
        return None
    source_name = _BRIDGE_MAP.get(dest_rel)
    source_path = root / ".act" / "bridges" / source_name if source_name else None
    try:
        source_digest = actlib.normalized_sha256(source_path) if source_path else ""
    except OSError:
        source_digest = ""
    key = f"{digest}:{source_digest}"
    cache = actlib.read_cache()
    notes = dict(cache.get("bridge_change_notes", {}))
    if notes.get(dest_rel) == key:
        return None
    notes[dest_rel] = key
    actlib.write_cache({"bridge_change_notes": notes})
    return f"[act] note: {dest_rel} was changed locally, template version not applied"


def _chat_language_short(config: dict[str, str]) -> str:
    chat, docs = actlib.language_settings(config)
    if chat != "auto":
        return chat
    return actlib.remembered_chat_language() or f"auto (until known: {docs})"


def _human_line(state: dict) -> Optional[str]:
    """The `systemMessage`: one line with the rule files loaded, chat language, and the inbox: entries
    answered but not yet processed, and the open ones (the status line's "waiting for you" count) --
    preceded by one line per active template advisory (state["advisory"]), when there are any."""
    advisory_lines = [str(line) for line in state.get("advisory") or []]
    if advisory_lines:
        # a warning of the template author goes first, each on its own line, ahead of the `act ·` line
        rest = _human_line({key: value for key, value in state.items() if key != "advisory"})
        return "\n".join(advisory_lines + ([rest] if rest else []))
    if not state:
        return None
    parts: list[str] = []
    if "files" in state:
        unresolved = state.get("unresolved", 0)
        parts.append(f"rules loaded: {state['files']} files"
                     + (f", {unresolved} import(s) not found" if unresolved else ""))
    if "chat" in state:
        parts.append(f"chat: {state['chat']}")
    answered = state.get("inbox", 0)
    open_count = state.get("inbox_open", 0)
    if answered or open_count:
        parts.append(f"inbox: {answered} answered to process, {open_count} open")
    if state.get("ideas"):
        parts.append(f"ideas: {state['ideas']} new")
    if state.get("old_imports"):
        parts.append("docs/ai/rules.md uses the old import form, see note")
    if state.get("update"):
        parts.append(f"update {state['update']} available")
    if state.get("tidy"):
        parts.append(str(state["tidy"]))
    if state.get("encoding"):
        parts.append(str(state["encoding"]))
    return "act · " + " · ".join(parts) if parts else None


def _fit_excerpt(text: str, excerpt: str, rules_text: str) -> str:
    """`text` with _EXCERPT_MARK replaced by `excerpt` (cut at a line boundary to the room left under
    CONTEXT_LIMIT, dropped when under ~300 characters would fit); the excerpt gives way first."""
    mark = _EXCERPT_MARK + "\n"
    base = text.replace(mark, "").replace(_RULES_MARK + "\n", rules_text)
    if not excerpt or mark not in text:
        return text.replace(mark, "")
    room = CONTEXT_LIMIT - len(base) - 1
    if len(excerpt) + 1 > room:
        if room < 300:
            return text.replace(mark, "")
        cut = "(cut to fit the session notes)"
        head, _, rest = excerpt.partition("\n")  # the header line always stays
        head = head[:max(room - len(cut) - 2, 0)]
        rest = rest[:max(room - len(head) - len(cut) - 3, 0)].rsplit("\n", 1)[0] if rest else ""
        excerpt = head + "\n" + (rest + "\n" if rest else "") + cut
    return text.replace(mark, excerpt + "\n")


def _fit_context(text: str, rules_full: str, rules_compact: str, excerpt: str = "") -> str:
    """Put the fallback orchestrator-rules block (usually empty) in place of its mark and the board
    excerpt in place of its mark, and keep the whole under CONTEXT_LIMIT: first the excerpt gives
    way (cut, then dropped), then the tip/reminder line, then the rules shrink to their ids; should
    even that not fit, the text is cut at a line boundary with a pointer to
    .act-local/session-start.txt, where the whole output is kept."""
    def without_tip(value: str) -> str:
        return "".join(line for line in value.splitlines(keepends=True)
                       if not line.startswith(("[act] tip", "[act] reminder")))

    full = _fit_excerpt(text, excerpt, rules_full).replace(_RULES_MARK + "\n", rules_full)
    compact = _fit_excerpt(text, excerpt, rules_compact).replace(_RULES_MARK + "\n", rules_compact)
    fitted = full
    for candidate in (full, without_tip(full), without_tip(compact)):
        fitted = candidate
        if len(fitted) <= CONTEXT_LIMIT:
            return fitted.rstrip("\n")
    stored = False
    try:
        root = actlib.repo_root()
        path = root / ".act-local" / "session-start.txt"
        if actlib.local_write_ok(root, path):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(full, encoding="utf-8")
            stored = True
    except (OSError, RuntimeError):
        pass
    tail = ("[act] note: session notes cut here — all of them in .act-local/session-start.txt" if stored
            else "[act] note: session notes cut here — the full text could not be stored")
    # The note about a refused write (a link in the way) is not cut away: it says why the rest is missing.
    pinned = "".join(line for line in fitted.splitlines(keepends=True) if line.startswith(_LOCAL_SKIP_NOTE))
    body = fitted.replace(pinned, "", 1) if pinned else fitted
    kept = body[:CONTEXT_LIMIT - len(tail) - len(pinned) - 1].rsplit("\n", 1)[0]
    return kept + "\n" + pinned + tail


def _session_title_for(payload: dict) -> Optional[str]:
    """The title `session-name` asks for, or None. Claude Code applies a SessionStart title only
    when the session starts, resumes or forks, so any other source gets none; a title the human
    already set (`/rename`, `--name`) arrives as `session_title` and is never overwritten. Any
    error means no title - the rest of the session-start output stays as it is."""
    try:
        if payload.get("source") not in ("startup", "resume", "fork"):
            return None
        existing = payload.get("session_title")
        if isinstance(existing, str) and existing.strip():
            return None
        return actlib.session_title(actlib.read_config(), actlib.repo_root())
    except Exception:  # never fail the session over a title
        return None


def refresh_session(payload: dict) -> int:
    """Check 2: runs only for SessionStart. Never fails the session. Prints exactly one JSON
    object: the notes and the status line as `hookSpecificOutput.additionalContext`, one
    human-readable line as `systemMessage`; nothing at all outside a template-managed project."""
    state: dict = {}
    rules_text = {"full": "", "compact": "", "excerpt": ""}
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        try:
            in_project = _collect_session(payload, state, rules_text)
        except Exception as exc:  # never fail the session over a note
            print(f"[act] note: session start stopped early ({exc.__class__.__name__})")
            in_project = True
    if not in_project:
        return 0
    context = _fit_context(buffer.getvalue(), rules_text["full"], rules_text["compact"], rules_text["excerpt"])
    output: dict = {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": context}}
    title = _session_title_for(payload)
    if title:
        output["hookSpecificOutput"]["sessionTitle"] = title
    message = _human_line(state)
    if message:
        output["systemMessage"] = message
    sys.stdout.write(json.dumps(output, ensure_ascii=False) + "\n")
    return 0


def _collect_session(payload: dict, state: dict, rules_text: dict) -> bool:
    """Everything refresh_session() reports, printed line by line (refresh_session captures it).
    Every sub-step is best effort and swallows its own errors; the fixed-format status line comes
    right after every other note except two deliberate exceptions: the "topics active" line,
    printed first of all and even when `session-start-refresh` is "off", and an "update available"
    note, which is always a previous run's background finding and prints after the status line
    (see _check_update_awareness's pre_notes/post_notes split). Fills `state` for the human line
    and `rules_text` with the orchestrator-rules block (full and compact), whose place in the
    output is marked by _RULES_MARK. Returns False outside a template-managed project."""
    config = actlib.read_config()

    try:
        root = actlib.repo_root()
    except RuntimeError:
        return False  # not inside a template-managed project — nothing to report

    # Printed ahead of the session-start-refresh on/off/warn gate below, and regardless of it: a
    # topic's own switch (docs/ai/config.md § Logging/Feedback), not this check, decides whether
    # it is active, and its rule file has to be named either way — "session-start-refresh: off"
    # only turns off the bridge/board/rules re-derivation this function does, not topic awareness.
    # The identity first, so the "ideas" topic below already sees one created now (fresh clone). It is
    # written even when session-start-refresh is "warn" or "off": without it nothing else works.
    try:
        identity_note = _identity_note(root)
    except Exception as exc:  # never block the session over an identity
        print(f"[act] identity check failed ({exc.__class__.__name__})", file=sys.stderr)
        identity_note = None
    if identity_note:
        print(identity_note)

    try:
        encoding_note = actlib.config_encoding_problem(root)
    except Exception:  # informational only, must never block the session
        encoding_note = ""
    if encoding_note:
        print(f"[act] note: {encoding_note}")
        state["encoding"] = "docs/ai/config.md is not UTF-8, see note"

    try:
        topics = _active_topics(root, config)
    except Exception:
        topics = []
    if topics:
        print("[act] topics active: " + ", ".join(f"{name} ({path})" for name, path in topics))
    try:
        language_line = _chat_language_line(config)
        state["chat"] = _chat_language_short(config)
    except Exception:
        language_line = None
    if language_line:
        print(language_line)
    try:
        depth_line = _output_depth_line(config)
    except Exception:
        depth_line = None  # informational only, must never block the session
    if depth_line:
        print(depth_line)

    # The template author's warnings come first among the notes (they must not be cut off by the context
    # limit) and are independent of `session-start-refresh`: they show whatever that row says.
    for advisory_note in _advisory_notes(root, config, state):
        print(advisory_note)

    try:
        env_note = _env_override_note()
    except Exception:
        env_note = None  # informational only, must never block the session
    if env_note:
        print(env_note)

    try:
        outside_note = _outside_root_note(root, config)
    except Exception:
        outside_note = None  # informational only, must never block the session
    if outside_note:
        print(outside_note)

    try:
        audit_note = _docs_audit_note(root, config)
    except Exception:
        audit_note = None  # informational only, must never block the session
    if audit_note:
        print(audit_note)

    if payload.get("source") == "compact":
        try:
            compact_note = _compact_note(root)
        except Exception:
            compact_note = None  # informational only, must never block the session
        if compact_note:
            print(compact_note)

    ideas_rel, ideas_keys = _ideas_pending(root)
    state["ideas"] = len(ideas_keys)
    if ideas_keys:
        try:
            print(_ideas_note(ideas_rel, ideas_keys))
        except Exception:
            pass  # informational only, must never block the session

    try:
        dependency_note = _dependency_check_note(root, config)
    except Exception:
        dependency_note = None  # informational only, must never block the session
    if dependency_note:
        print(dependency_note)

    try:
        compact_due = _compact_due_note(root, config)
    except Exception:
        compact_due = None  # informational only, must never block the session
    if compact_due:
        print(compact_due)

    mode = _check_mode(config, "session-start-refresh", default="block")
    if mode == "off":
        return True

    # Under `warn` nothing is applied, so the same drift would be named again at every session
    # start. The "would ..." notes are collected here instead of printed on the spot, and printed
    # once after the last of them -- only when their set differs from the one recorded last time
    # (the first `warn` run has no record yet and records it).
    warn_notes: list[str] = []

    branch = _current_branch(root)

    # The incident log (restored files, warn hits that wrote, crashed or slow checks, escalated workers, model switches) goes
    # into the inbox as one report of the day before the inbox is counted below.
    if mode == "block":
        try:
            import incidents
            delivered = incidents.deliver(root)
            if delivered:
                print(f"[act] incident log: {delivered[1]} new event(s) in {delivered[0].relative_to(root).as_posix()}")
        except Exception:
            pass  # informational only, must never block the session
    elif mode == "warn":
        # nothing is written under `warn`: only say that events wait, so the owner knows they are not delivered
        try:
            import incidents
            waiting_events = incidents.pending(root)
            if waiting_events:
                print(f"[act] incident log: {waiting_events} event(s) waiting, not delivered while "
                      "session-start-refresh is `warn`")
        except Exception:
            pass  # informational only, must never block the session

    waiting = 0
    try:
        waiting = _count_inbox_waiting(root)
    except Exception:
        pass
    state["inbox"] = waiting
    try:
        state["inbox_open"] = _count_inbox_open(root)
    except Exception:
        state["inbox_open"] = 0

    # The session owner's own ideas file (and the folder README) created on first use — in a
    # project that predates the ideas files, or for a second person who just joined.
    try:
        for note in _ideas_ensure_notes(root, config, write=(mode == "block")):
            print(note)
    except Exception:
        pass  # best effort, must never block the session

    # Whether a feedback reminder to the template author is due right now
    # (.act/scripts/feedback.py --due's own logic) — folded into the status line like the inbox
    # count above, and counted as an "open point" that silences the tip/reminder line below (same
    # reasoning as the inbox count: the thing that is waiting comes first, self-promotion later).
    # Imported lazily and wrapped in its own try/except, like every other sub-step in this
    # function — a broken tips.py must never take the session-start hook down with it.
    feedback_due = False
    try:
        from . import tips as _tips
        feedback_due = _tips.is_feedback_due(root)
    except Exception:
        feedback_due = False

    changed_bridges: list[str] = []
    refreshed_bridges: list[str] = []
    bootstrap_bridges: list[str] = []
    try:
        changed_bridges, refreshed_bridges, bootstrap_bridges = _refresh_bridges(root, write=(mode == "block"))
    except Exception:
        pass

    # `artifacts` (config.md): the Artifact tool is switched off through .claude/settings.json,
    # applied like the bridges above -- written under `block`, only named once under `warn`.
    try:
        artifact_notes, artifact_warn = _apply_artifact_setting(root, config, write=(mode == "block"))
        for note in artifact_notes:
            print(note if note.startswith("[act]") else f"[act] note: {note}")
        warn_notes.extend(artifact_warn)
    except Exception:
        pass  # best effort, must never block the session

    try:
        _refresh_board(root)
    except Exception:
        pass

    scope_copies_moved = False
    try:
        import act_profile
        snapshot = actlib.read_last_applied()
        scope_copies_moved = (
            isinstance(snapshot, dict) and isinstance(snapshot.get("tools"), list)
            and act_profile.recorded_cut(snapshot) != act_profile.snapshot_value(act_profile.read_cut(root)))
    except Exception:
        scope_copies_moved = False

    # Files that hang on a docs/ai/config.md value — skill copies, CLAUDE.md and the
    # hook entries on `tools`, a role's bridges on its "## Roles" row (tier/reasoning/model) — are
    # synced here when that value moved since the .act-local/last-applied.json snapshot, not only
    # on the next `update.py` run. A plain comparison, no scan unless something moved (see
    # update.sync_dependent_files()). "block" syncs; "warn" only names what is pending.
    if mode in ("block", "warn"):
        try:
            import update  # deferred: see the header comment above 
            if mode == "block":
                sync_summary, _sync_copies, _sync_touched = update.sync_dependent_files(root, always_run=False)
                if sync_summary:
                    print(f"[act] note: docs/ai/config.md changed -- dependent files synced: {sync_summary}")
            else:
                pending = update.pending_dependent_changes(root)
                if pending:
                    warn_notes.append(f"[act] note: docs/ai/config.md changed ({pending}) -- dependent files would be synced (warn mode, not applied)")
        except Exception as exc:
            # Never silent — a sync that stopped midway is finished by the next session start
            # (it keeps its snapshot unwritten) or by update.py --catch-up.
            print(f"[act] note: syncing files that depend on docs/ai/config.md failed ({exc.__class__.__name__}) -- "
                  "retried next session, or run `python .act/scripts/update.py --catch-up`")

    # A skill or role written by hand under docs/ai/local/ gets its tool copies/bridge here, no
    # import step needed (unit_copies.py). Best-effort: a first look at the two folders costs
    # nothing for a project without own units. A "not checked" line is an error and is shown every
    # session until it goes away; every other note (kept-as-is edited copy, template-named override)
    # is printed again only when its text changes (cache), so it is not repeated daily.
    if mode == "block":
        own_note = ""
        own_error = ""
        try:
            import unit_copies  # deferred like update above
            try:
                import update as _update
                history_check = _update._paths_in_git_history
            except Exception:
                history_check = None
            own_messages, _own_recorded, _own_touched = unit_copies.ensure_own_unit_copies(
                root, history_check=(lambda rels: history_check(root, rels)) if history_check else None)
            errors = [m for m in own_messages if "not checked" in m]
            others = [m for m in own_messages if "not checked" not in m]
            if errors:
                own_error = "[act] note: " + "; ".join(errors)
            if others:
                own_note = "[act] note: own skills/roles: " + "; ".join(others)
        except Exception as exc:
            own_error = f"[act] note: own skill/role copies not checked ({exc.__class__.__name__})"
        if own_error:
            print(own_error)
        try:
            if actlib.read_cache().get("own_copies_note", "") != own_note:
                actlib.write_cache({"own_copies_note": own_note})
                if own_note:
                    print(own_note)
        except Exception:
            if own_note:
                print(own_note)

    for dest_rel in changed_bridges:
        if dest_rel == "docs/ai/rules.md":
            # Edited locally, so not re-derived: enter what the template has and the file does not know
            # (the same function update.py uses), leave everything the owner wrote as it is.
            entry_notes = _follow_rules_md(root, write=(mode == "block"))
            if mode == "block":
                for entry_note in entry_notes:
                    print(entry_note)
            else:
                warn_notes.extend(entry_notes)
        if dest_rel == "docs/ai/rules.md" and _old_rules_imports(root)[0]:
            continue  # the more specific import note below replaces this one
        note = _changed_bridge_note(root, dest_rel)
        if note:
            print(note)
    if mode == "warn":
        for dest_rel in refreshed_bridges:
            warn_notes.append(f"[act] note: {dest_rel} would be refreshed from .act/bridges/ (warn mode, not applied)")
    # A raw `git pull` can land the template's own bootstrap CLAUDE.md/AGENTS.md (marker
    # "<!-- act:bootstrap -->") on top of the project's real bridge in an already set-up project.
    # _refresh_bridges tells that apart from an actual local edit and rewrites it here — self-
    # resolving, so no once-per-state cache entry like _changed_bridge_note's is needed: once
    # rewritten, the marker is gone and this cannot fire again for the same file.
    for dest_rel in bootstrap_bridges:
        verb = "replaced by" if mode == "block" else "would be replaced by (warn mode, not applied)"
        bootstrap_note = (f"[act] note: {dest_rel}: template bootstrap file {verb} the project bridge "
                          "(a raw git pull brought it in)")
        if mode == "block":
            print(bootstrap_note)
        else:
            warn_notes.append(bootstrap_note)

    # What Claude Code actually loads. A checked coding set becomes an "@" import (and an
    # unchecked one loses it) so the checkboxes in docs/project/coding_rules.md decide; a locally
    # changed docs/ai/rules.md still importing "@.act/..." gets one note; then the imports are
    # followed from CLAUDE.md exactly the way Claude Code does (rules.resolve_imports).
    reached: list[str] = []
    try:
        import rules  # deferred like update above: a broken rules.py must not end the session
        coding_fixed = rules.sync_coding_imports(root, write=(mode == "block"))
        if coding_fixed:
            verb = "set to" if mode == "block" else "would be set to (warn mode)"
            coding_note = (f"[act] note: docs/project/coding_rules.md: {coding_fixed} set line(s) {verb} "
                           "their checkbox (checked = @-import)")
            if mode == "block":
                print(coding_note)
            else:
                warn_notes.append(coding_note)
        try:
            method_sync = rules.sync_method_imports(root, write=(mode == "block"))
            if method_sync.changed:
                verb = "brought in line" if mode == "block" else "would be brought in line (warn mode)"
                method_note = (f"[act] note: docs/project/coding_rules.md: method sets {verb} with the "
                               "methods row of docs/ai/config.md")
                if mode == "block":
                    print(method_note)
                else:
                    warn_notes.append(method_note)
        except Exception as exc:  # noqa: BLE001 - the methods sync is a best-effort step, never a reason to end the session
            print(f"[act] note: methods not applied ({exc.__class__.__name__})")
        try:
            scope_lines, scope_pending = _scope_notes(root, mode == "block", scope_copies_moved)
            for scope_line in scope_lines:
                print(scope_line)
            warn_notes.extend(scope_pending)
        except Exception as exc:  # noqa: BLE001 - the scope is a best-effort step, never a reason to end the session
            print(f"[act] note: scope not applied ({exc.__class__.__name__})")
        old_note = _old_imports_note(root)
        if old_note:
            state["old_imports"] = True
            print(old_note)
        if (root / "CLAUDE.md").is_file():
            reached, unresolved = rules.resolve_imports(root, "CLAUDE.md")
            state["files"] = len(reached)
            state["unresolved"] = len(unresolved)
            if unresolved:
                print(f"[act] note: {len(unresolved)} @-import(s) Claude Code cannot follow — "
                      "python .act/scripts/rules.py --imports")
    except Exception as exc:
        print(f"[act] note: import check failed ({exc.__class__.__name__})")

    # Role bridges (.claude/agents/*.md): only the `model`/`effort` frontmatter pair is refreshed
    # here, never the rest of the file — see tiers.py's refresh_project_bridge_frontmatter() for
    # why this differs from _refresh_bridges above, which replaces a whole file or leaves it alone.
    role_frontmatter_changed: list[str] = []
    tier_notes: list[str] = []
    try:
        role_frontmatter_changed = tiers.refresh_project_bridge_frontmatter(root, apply=(mode == "block"), notes=tier_notes)
    except Exception:
        pass
    if mode == "warn":
        for dest_rel in role_frontmatter_changed:
            warn_notes.append(f"[act] note: {dest_rel} model/effort would be refreshed from tiers.json/config.md (warn mode, not applied)")
    if mode == "warn":
        try:
            # Several notes carry only a name or a count, and a bridge note reads the same for every
            # template revision, so the key also holds the hash of everything the notes derive from:
            # a further change of any of them is new drift even when the wording is identical.
            key_parts = list(warn_notes)
            for rel in ("docs/ai/config.md", "docs/project/coding_rules.md", ".act/tiers.json"):
                try:
                    key_parts.append(f"{rel}:{actlib.normalized_sha256(root / rel)}")
                except OSError:
                    key_parts.append(f"{rel}:-")
            key_parts.append("applied:" + json.dumps(actlib.read_lock().get("applied"), sort_keys=True))
            key_parts += [
                f"{dest_rel}:{actlib.normalized_sha256(root / '.act' / 'bridges' / _BRIDGE_MAP[dest_rel])}"
                for dest_rel in refreshed_bridges + bootstrap_bridges if dest_rel in _BRIDGE_MAP]
            digest = hashlib.sha256("\n".join(key_parts).encode("utf-8")).hexdigest() if warn_notes else ""
            recorded = actlib.read_cache().get("warn_notes_digest", "")
            if digest != recorded:
                if digest or recorded:
                    actlib.write_cache({"warn_notes_digest": digest})
                for note in warn_notes:
                    print(note)
        except Exception:
            for note in warn_notes:
                print(note)  # a broken record must never hide the drift itself
    elif mode == "block":
        # A run that syncs makes the earlier warn record obsolete: the same drift arriving again
        # later is new, not already reported.
        try:
            if actlib.read_cache().get("warn_notes_digest"):
                actlib.write_cache({"warn_notes_digest": ""})
        except Exception:
            pass
    # An unknown tier/reasoning value (config.md § Roles or tiers.json) is reported once here as a
    # single line, whatever the role count — previously this only ever surfaced in init.py/
    # update.py's own notes, never at session start.
    if tier_notes:
        print("[act] note: " + "; ".join(tier_notes))

    post_update_notes: list[str] = []
    try:
        pre_update_notes, post_update_notes = _check_update_awareness(root, config, state)
        for note in pre_update_notes:
            print(note)
    except Exception:
        pass  # template-awareness is informational only, must never block the session

    try:
        post_update_notes.extend(_check_security_scan_awareness(root, config))
    except Exception:
        pass  # security-check's own daily scan is informational only, must never block the session

    try:
        post_update_notes.extend(_check_act_local_tidy(root, config, state))
    except Exception:
        pass  # keeping .act-local/ small is housekeeping, must never block the session

    rules_delivered: Optional[int] = None
    for key, compact in (("full", False), ("compact", True)):
        captured = io.StringIO()
        try:
            with contextlib.redirect_stdout(captured):
                count = _deliver_orchestrator_rules(root, config, compact=compact, reached=reached)
            rules_delivered = count if key == "full" else rules_delivered
        except Exception:
            pass  # a broken rules delivery must not block the session
        rules_text[key] = captured.getvalue()
    print(_RULES_MARK)

    inbox_part = f" · inbox: {waiting} waiting" if waiting else ""
    rules_via = " (via import)" if _orchestrator_rules_imported(reached) else ""
    rules_part = f" · rules: {rules_delivered}{rules_via}" if rules_delivered is not None else ""
    roles_part = f" · role-bridges refreshed: {len(role_frontmatter_changed)}" if mode == "block" and role_frontmatter_changed else ""
    feedback_part = " · feedback due" if feedback_due else ""
    ideas_part = f" · ideas: {len(ideas_keys)} new" if ideas_keys else ""
    print(f"[act] branch={branch}{inbox_part}{ideas_part}{feedback_part} · board updated{rules_part}{roles_part}")
    # The board excerpt (`board-at-start`) follows the status line, ahead of the postscript notes
    # and the tip, which stay last. Not after a compaction: _compact_note already names the tasks
    # and their state. Its text is kept apart and put in place by _fit_context, which shortens or
    # drops it first when the output gets tight.
    if payload.get("source") != "compact":
        try:
            excerpt = _board_excerpt_block(root, config)
        except Exception:
            excerpt = ""  # informational only, must never block the session
        if excerpt:
            rules_text["excerpt"] = excerpt
            print(_EXCERPT_MARK)
    # Printed after the status line, not before: an "update available" note here is always a
    # previous SessionStart's background finding (_pending_update_note), never something
    # this run just checked, so it reads as a postscript rather than part of this run's status.
    for note in post_update_notes:
        print(note)
    # At most one line, last of all — either a due reminder from docs/ai/local/reminders.md
    # (user's own, always checked first) or a rotated .act/tips.md tip (config.md § Tips),
    # silenced by `output-depth: sparse` and by any open point above (inbox/feedback
    # due) inside tips.session_line() itself. Same lazy-import-and-swallow pattern as every other
    # sub-step here.
    try:
        from . import tips as _tips
        tip_line = _tips.session_line(payload, root, config,
                                       waiting + (1 if feedback_due else 0) + len(ideas_keys))
    except Exception:
        tip_line = None
    # Every write the steps above refused, one line in all. With `.act-local` itself linked act-local-tidy has
    # said so already (every reason is then the same one): no second line.
    skipped = actlib.take_local_skips()
    if any(note.startswith(_TIDY_LINK_NOTE) for note in post_update_notes):
        skipped = [reason for reason in skipped if not reason.startswith(".act-local is a link")]
    if skipped:
        more = f" (+{len(skipped) - 1} more)" if len(skipped) > 1 else ""
        print(f"{_LOCAL_SKIP_NOTE} ({skipped[0]}{more})")
    if tip_line:
        print(tip_line)
    return True
