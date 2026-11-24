"""Session start, context lines: compact note, identity, environment overrides, output depth, board
excerpt, chat language, active topics, whiteboard, the scope and the packages.

Split out of session.py, which keeps the entry point and the order of the sub-steps."""
from __future__ import annotations

import json
import os
import re
import stat
import sys
import time
from datetime import date
from pathlib import Path
from typing import Callable, Optional

import actlib

# ---------------------------------------------------------------------------
# Chat language at session start (R-human-language) — only while `language-chat` is `auto`:
# the language remembered for this person on this machine (`board.py --chat-language`,
# .act-local/identity.json), so the assistant does not have to guess it again, or the hint how to
# remember it once recognized. A fixed `language-chat` needs no line; config.md already says it.
# ---------------------------------------------------------------------------

# Environment variables the template reads as overrides (docs/ai/config.md carries the project
# values; these win for one run). Names only are ever reported, never values.
_ENV_OVERRIDES = (
    "AGENTIC_FEEDBACK_URL",
    "ACT_FORGE_API_URL",
    "ACT_FORGE_KIND",
    "ACT_SEMGREP_CMD",
    "ACT_MCP_LIST_COMMAND",
    "ACT_MCP_LIST_TIMEOUT",
    "ACT_MCP_CATALOG",
    "ACT_SECRET_READ",
    "ACT_OUTSIDE_ROOT",
)


_COMPACT_TASKS_LIMIT = 5
_TASK_ID_RE = re.compile(r"^([A-Za-z]+\d+)-")
_STATE_STAMP_RE = re.compile(r"^State (\d{4}-\d{2}-\d{2} \d{2}:\d{2})")


def _board_file_hint(root: Path) -> str:
    """The board file this project actually uses (`board` in config.md, decided the way board.py
    does): docs/ai/board.md for `docs` and `shared`, .act-local/board-<branch>.md for `local`."""
    import board
    mode = actlib.read_config(root).get("board", "").strip().lower() or "docs"
    if mode == "local":
        branch = board.get_branch(root)
        return f".act-local/board-{board.sanitize_branch(branch) if branch is not None else 'no-git'}.md"
    return "docs/ai/board.md"


def _compact_note(root: Path) -> str:
    """After a compaction (SessionStart `source: compact`) the summary may have lost detail:
    name the open tasks with their last working-state line (.act-local/state/, the data the board
    shows) and point to the board, so the state is re-read before work continues. The task with
    the most recent state line comes first (then started ones, then the rest); at most _COMPACT_TASKS_LIMIT are listed."""
    import board  # deferred like update above: a session start never pays for it otherwise
    lines = [
        "[act] context was compacted -- the summary may have lost detail. Before continuing, re-read "
        f"the state of the open task(s) (full list: {_board_file_hint(root)}):"
    ]
    tasks_dir = root / board.TASKS_DIR
    files = sorted(p for p in tasks_dir.glob("*.md") if p.name.lower() != "readme.md") if tasks_dir.is_dir() else []
    entries: list[tuple[bool, str, str]] = []
    for path in files:
        try:
            started = "started:" in actlib.header_block(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            started = False
        id_match = _TASK_ID_RE.match(path.name)
        label = id_match.group(1) if id_match else path.stem
        title = board._first_heading(path) or path.stem
        last_state = board._last_state_line(root, path.name)
        stamp_match = _STATE_STAMP_RE.match(last_state or "")
        stamp = stamp_match.group(1) if stamp_match else ""
        entries.append((started, stamp, f"- {label} {title}" + (f" -- state: {last_state}" if last_state else " -- no state recorded")))
    entries.sort(key=lambda item: not item[0])  # stable: started tasks first ...
    entries.sort(key=lambda item: item[1], reverse=True)  # ... then the most recent last state line first
    if not entries:
        lines.append("- no open task on file")
    lines.extend(text if len(text) <= 300 else text[:299] + "…" for _started, _stamp, text in entries[:_COMPACT_TASKS_LIMIT])
    if len(entries) > _COMPACT_TASKS_LIMIT:
        lines.append(f"- (+{len(entries) - _COMPACT_TASKS_LIMIT} more on the board)")
    return "\n".join(lines)


def _identity_note(root: Path) -> Optional[str]:
    """Make sure this checkout has an identity (.act-local/identity.json is gitignored, so a fresh
    clone or a second machine lacks it): create it from `git config user.name` and say so in one
    line; with no usable git name say that none exists. None when it was there already."""
    status, data = actlib.ensure_identity(root)
    if status == "created" and data:
        blocked = actlib.link_problem(root, root / ".act-local" / "identity.json")
        if blocked:  # nothing was written: do not say "created"
            return (f"[act] identity `{data['identity']}` taken from git user.name but not stored: {blocked}; "
                    "set it with `python .act/scripts/board.py --identity <name>` once `.act-local` is a real folder")
        return (f"[act] identity `{data['identity']}` created from git user.name (workspace "
                f"{data.get('workspace', '?')}); change with `python .act/scripts/board.py --identity <name>`")
    if status == "unreadable":
        return ("[act] `.act-local/identity.json` is unreadable: fix it or run "
                "`python .act/scripts/board.py --identity <name>`")
    if status == "none":
        return ("[act] no identity for this checkout (git user.name is not set or has no letter or digit); board, whiteboard and new "
                "entries need one: ask the human for their name, then run "
                "`python .act/scripts/board.py --identity <name>`")
    return None


def _env_override_note() -> Optional[str]:
    """One note naming every active environment override, or None when none is set."""
    active = [name for name in _ENV_OVERRIDES if os.environ.get(name, "").strip()]
    if not active:
        return None
    return "[act] note: environment overrides active: " + ", ".join(active)


_OUTPUT_DEPTHS = ("verbose", "normal", "sparse")


def _outside_root_note(root: Path, config: dict[str, str]) -> Optional[str]:
    """One-time note (per project and machine) for a project whose config.md has no `outside-root`
    row: the check runs there as `warn`. Marker file: .act-local/outside-root-note.json."""
    if "outside-root" in config or os.environ.get("ACT_OUTSIDE_ROOT", "").strip().lower() in ("block", "warn", "off"):
        return None
    marker = root / ".act-local" / "outside-root-note.json"
    if marker.exists():
        return None
    if not actlib.local_write_ok(root, marker):
        return None  # .act-local is a link or leaves the project: nothing is written through it
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"noted": date.today().isoformat()}) + "\n", encoding="utf-8")
    except OSError:
        return None  # cannot record it: say nothing rather than repeat at every start
    return ("[act] note: the check `outside-root` runs here as `warn` (no row in docs/ai/config.md § Checks). "
            "To block, set `outside-root | block`; list neighbour repos in `outside-root-allow` "
            "(`../other (read)` for read-only).")


def _output_depth_line(config: dict[str, str]) -> Optional[str]:
    """Names `output-depth` once when it is not `normal` (levels: R-human-chat); an unknown value
    falls back to `normal` and says so. Nothing for `normal` or an empty value."""
    value = str(config.get("output-depth", "")).strip()
    if not value or value.lower() == "normal":
        return None
    if value.lower() in _OUTPUT_DEPTHS:
        return f"[act] output depth: {value.lower()} (docs/ai/config.md; levels in R-human-chat)"
    return (f"[act] output depth: {value!r} is not one of {' | '.join(_OUTPUT_DEPTHS)} — "
            f"treated as normal (docs/ai/config.md)")


_BOARD_AT_START_VALUES = ("on", "off")
_EXCERPT_MARK = "\x00act-board-excerpt\x00"


def _board_excerpt_block(root: Path, config: dict[str, str]) -> str:
    """The `board-at-start` excerpt for the session start: a header line plus the board's
    "Open tasks", "Waiting for you" and "Answered" sections (board.render_excerpt), "" when the switch
    is `off` or nothing is waiting, answered or open (or the inbox and tasks directories do not exist). A missing or empty key counts as `on`;
    an unknown value counts as `on` too and says so in one extra line."""
    value = str(config.get("board-at-start", "")).strip().strip("`").lower()
    note = ""
    if value == "off":
        return ""
    if value and value not in _BOARD_AT_START_VALUES:
        note = (f"[act] board-at-start: {config.get('board-at-start', '').strip()!r} is not one of "
                f"{' | '.join(_BOARD_AT_START_VALUES)} — treated as on (docs/ai/config.md)\n")
    import board  # deferred like _compact_note
    board_file = _board_file_hint(root)
    body = board.render_excerpt(root, board_file=board_file)
    if not body.strip():
        return note.rstrip("\n")
    return (f"{note}[act] board excerpt (what a bare \"continue\" works from; `board-at-start` in "
            f"docs/ai/config.md; full board: {board_file}):\n{body}")




def _chat_language_line(config: dict[str, str]) -> Optional[str]:
    chat, docs = actlib.language_settings(config)
    if chat != "auto":
        return None
    remembered = actlib.remembered_chat_language()
    if remembered:
        return f"[act] chat language: {remembered} (remembered on this machine; docs stay {docs})"
    return (f"[act] chat language: auto, none remembered yet — recognize it from the owner's messages, "
            f"then `python .act/scripts/board.py --chat-language <code>` (until then: {docs})")


# ---------------------------------------------------------------------------
# Active topics at session start — a topic with a switch (logging, feedback, ...) only ever
# matters once its own switch is on; this names, in the table's own order, which ones are
# active this session and where their rule file lives, so the orchestrator (and a human reading
# the transcript) can tell without opening docs/ai/config.md first.
# ---------------------------------------------------------------------------

_TOPIC_SWITCHES: tuple[tuple[str, str, Callable[[str], bool]], ...] = (
    ("logging", "logging", lambda value: value.strip().lower() == "on"),
    ("feedback", "feedback", lambda value: value.strip().lower() not in ("", "off")),
)

# "ide" (topics/ide.md) is not gated by a docs/ai/config.md switch like the two above -- it is
# detected instead, from whether an IDE-shaped MCP server is actually configured for this project
# -- reading it never runs anything, only .mcp.json and Claude's own settings
# files, the same sources Claude Code itself reads its MCP server list from. A name or command
# containing one of these (case-insensitive) counts as "IDE-shaped" -- best-effort, JetBrains'
# `idea` MCP plugin is the only one confirmed as of this writing; a project using a different IDE
# MCP server under an unrecognized name sees "ide" inactive until this list is extended. Only the
# template can extend it -- dispatch.py loads check modules from .act/hooks/ alone and has no project
# override for them -- so a project reports a missing name as feedback (topics/feedback.md).
_IDE_SERVER_NAME_HINTS = ("idea", "jetbrains", "intellij", "pycharm", "webstorm", "rider", "clion")
# Server names that count as an IDE server only when they match *exactly* (case-insensitive), never
# as a substring: Claude Code's own IDE integration (the VS Code and JetBrains extensions) registers
# its server as plain `ide` -- its tools reach the hooks as `mcp__ide__executeCode` and
# `mcp__ide__getDiagnostics` -- and "ide" as a
# substring would match "provider", "video", "guide" and the like in any server name or command.
# It is never configured in .mcp.json or ~/.claude.json (the extension injects it), so this mainly
# serves checks/mcp_ide.py's own "is this an IDE server" judgment; _servers_match_ide_hint honours
# it too, for a project that happens to name a configured server exactly that.
_IDE_SERVER_EXACT_NAMES = frozenset({"ide"})


def _is_ide_server_name(server: str) -> bool:
    """True if `server` (an MCP server's own name, as in `mcp__<server>__<tool>` or a config
    file's `mcpServers` key) counts as an IDE server: exactly one of _IDE_SERVER_EXACT_NAMES, or
    containing one of _IDE_SERVER_NAME_HINTS -- case-insensitive either way. The one definition
    checks/mcp_ide.py and dispatch.py's fail-closed fallback share with the topic detection here."""
    lowered = server.lower()
    return lowered in _IDE_SERVER_EXACT_NAMES or any(hint in lowered for hint in _IDE_SERVER_NAME_HINTS)


def _servers_match_ide_hint(servers: dict) -> bool:
    """True if some entry of `servers` (an `mcpServers` object: name -> {"command": ...,
    "args": [...], "url": ...}) has a name that is an IDE server's (_is_ide_server_name) or a
    command/args/url that looks like a JetBrains-family IDE server (see _IDE_SERVER_NAME_HINTS).
    Shared by every source _ide_mcp_connected reads from -- project-local config files and the
    owner's user-wide one alike."""
    for name, entry in servers.items():
        if _is_ide_server_name(str(name)):
            return True
        haystack = str(name)
        if isinstance(entry, dict):
            for field in ("command", "url"):
                value = entry.get(field)
                if isinstance(value, str):
                    haystack += " " + value
            args = entry.get("args")
            if isinstance(args, list):
                haystack += " " + " ".join(a for a in args if isinstance(a, str))
        haystack = haystack.lower()
        if any(hint in haystack for hint in _IDE_SERVER_NAME_HINTS):
            return True
    return False


def _user_mcp_servers(root: Path) -> list:
    """Every `mcpServers` object the owner's user-wide `~/.claude.json` carries that could apply to
    this project (review finding 6): a JetBrains IDE's own MCP server is often registered there,
    user-wide, rather than in a project-local `.mcp.json` -- `_ide_mcp_connected` reading only
    project-local files never sees it. Two places in that file define one: the top-level
    `mcpServers` object (Claude Code's own user-wide default, applied to every project) and
    `projects[<root>].mcpServers` (a project-specific addition/override Claude Code also reads
    from there, keyed by this project's own absolute path). Read-only, and only ever these two
    objects' own keys (server name, `command`/`args`/`url`) are ever looked at or returned -- never
    any other content the file might carry (session history, OAuth tokens, other projects'
    entries). Best-effort: a missing, unreadable, or malformed file contributes nothing; read once,
    as a whole, rather than incrementally -- this file can be large (home-directory session
    state), but a second, independent parse pass over it would cost more than one plain
    `json.loads` already does."""
    path = Path.home() / ".claude.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []
    found: list = []
    top_servers = data.get("mcpServers")
    if isinstance(top_servers, dict):
        found.append(top_servers)
    projects = data.get("projects")
    if isinstance(projects, dict):
        for key, project_entry in projects.items():
            if not isinstance(key, str) or not _same_project_path(key, root):
                continue
            if isinstance(project_entry, dict):
                project_servers = project_entry.get("mcpServers")
                if isinstance(project_servers, dict):
                    found.append(project_servers)
    return found


def _same_project_path(key: str, root: Path) -> bool:
    """True if `key` (a `projects` key of `~/.claude.json`) names `root`. Claude Code writes those
    keys in POSIX form even on Windows (`D:/dev/x`, confirmed against a real file on 2026-09-26),
    while `str(root)` is `D:\\dev\\x` -- a plain dict lookup never matched there. Compared after os.path.normcase/normpath on both sides, so neither slash
    direction nor drive-letter case matters; no filesystem access."""
    return os.path.normcase(os.path.normpath(key)) == os.path.normcase(os.path.normpath(str(root)))


def _ide_mcp_connected(root: Path) -> bool:
    """True if some configured MCP server's name or command looks like a JetBrains-family IDE
    server (see _IDE_SERVER_NAME_HINTS) -- read from .mcp.json and .claude/settings*.json under
    `root` (the "mcpServers" object each of those files can carry), and from the owner's user-wide
    `~/.claude.json` (review finding 6: `_user_mcp_servers`, since a JetBrains plugin's own server
    is often registered there instead of in a project-local file). Best-effort and read-only: a
    missing/unreadable/malformed file simply contributes nothing, never an error."""
    candidates = [root / ".mcp.json", root / ".claude" / "settings.json", root / ".claude" / "settings.local.json"]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        servers = data.get("mcpServers") if isinstance(data, dict) else None
        if isinstance(servers, dict) and _servers_match_ide_hint(servers):
            return True
    for servers in _user_mcp_servers(root):
        if _servers_match_ide_hint(servers):
            return True
    return False


def _whiteboard_pending(root: Path) -> "tuple[str, list[str], list[str], list[str]]":
    """(root-relative path of the session owner's whiteboard, its new or changed entries, its due date
    reminders, its event reminders to check) — see whiteboard.py; ("", [], [], []) when there is no
    identity, no file, nothing to report, or whiteboard.py cannot be imported. Imported lazily like
    `update`/`rules`: a session start never pays for it unless it is reached, and a broken
    whiteboard.py must not end the session."""
    try:
        import whiteboard  # deferred: see the docstring
        path, found = whiteboard.pending(root)
        if path is None or not found:
            return "", [], [], []
        return path.relative_to(root).as_posix(), found.new, found.due, found.check
    except Exception:
        return "", [], [], []


def _whiteboard_notes(rel: str, new: list[str], due: list[str], check: list[str]) -> list[str]:
    """The `[act] whiteboard:` session notes, one line for each of: entries new or changed, date reminders
    that are due, event reminders to check — each with the count, the first few titles
    (whiteboard.titles_text) and what to do about them."""
    import whiteboard  # deferred, as in _whiteboard_pending
    done = "process them per the whiteboard topic, then `python .act/scripts/whiteboard.py --seen`"
    notes: list[str] = []
    if new:
        notes.append(f"[act] whiteboard: {len(new)} new or changed in {rel} — {whiteboard.titles_text(new)} — {done}")
    if due:
        notes.append(f"[act] whiteboard: {len(due)} due in {rel} — {whiteboard.titles_text(due)} — {done}")
    if check:
        notes.append(f"[act] whiteboard: {len(check)} to check in {rel} — {whiteboard.titles_text(check)} — "
                     "has the event come? If so, process the entry per the whiteboard topic; if not, leave it")
    return notes


def _whiteboard_ensure_notes(root: Path, config: dict[str, str], write: bool) -> list[str]:
    """One note per file whiteboard.ensure() created for the session owner (or, with write=False, would
    create): docs/ai/README.md and the owner's own whiteboard. Best effort."""
    import whiteboard  # deferred, as in _whiteboard_pending
    notes: list[str] = []
    english = actlib.is_english(actlib.language_settings(config)[1])
    for path, kind in whiteboard.ensure(root, plan=not write):
        rel = path.relative_to(root).as_posix()
        if not write:
            notes.append(f"[act] note: {rel} would be created (warn mode, not applied)")
        elif kind == "readme":
            extra = "" if english else " — scaffold in English, translate it once (R-work-language)"
            notes.append(f"[act] note: created {rel} — how the whiteboards work{extra}")
        else:
            notes.append(f"[act] note: created {rel} — your own whiteboard, one `## <kind>: <title>` section per entry")
    return notes


def _active_topics(root: Path, config: dict[str, str]) -> list[tuple[str, str]]:
    """(topic name, path to show) for every topic in _TOPIC_SWITCHES whose switch is active, in
    the table's own order. The path follows actlib.resolve()'s own local-over-template
    precedence (docs/ai/local/rules/topics/<name>.md wins over .act/rules/topics/<name>.md — the
    same rule every other override in this template follows, e.g. rules.py/doctor.py/init.py),
    shown relative to the project root; "missing" if neither exists (a switch turned on before
    the topic file was ever added to this template version, or one a project deleted by hand
    without turning the switch off — reported rather than silently skipped either way). A topic
    the project's scope excludes (docs/ai/config.md § Scope: `exclude`) is not named."""
    active: list[tuple[str, str]] = []
    try:
        import act_profile  # deferred like rules/update: a broken module must not end the session
        cut_topics = act_profile.read_cut(root).topics
    except Exception:  # noqa: BLE001
        cut_topics = frozenset()
    for name, config_key, is_active in _TOPIC_SWITCHES:
        if name in cut_topics or not is_active(config.get(config_key, "")):
            continue
        resolved = actlib.resolve(f"rules/topics/{name}.md")
        if resolved is None:
            active.append((name, "missing"))
        else:
            path, _origin = resolved
            active.append((name, path.relative_to(root).as_posix()))
    # "ide" is not one of _TOPIC_SWITCHES' config-driven entries -- it is detected instead, see
    # _ide_mcp_connected's own docstring.
    if "ide" not in cut_topics and _ide_mcp_connected(root):
        resolved = actlib.resolve("rules/topics/ide.md")
        if resolved is None:
            active.append(("ide", "missing"))
        else:
            path, _origin = resolved
            active.append(("ide", path.relative_to(root).as_posix()))
    # "whiteboard" is data-driven too: active while the owner's own whiteboard has entries to
    # process, a date reminder due or an event reminder to check (whiteboard.py).
    if "whiteboard" not in cut_topics and any(_whiteboard_pending(root)[1:]):
        resolved = actlib.resolve("rules/topics/whiteboard.md")
        if resolved is None:
            active.append(("whiteboard", "missing"))
        else:
            path, _origin = resolved
            active.append(("whiteboard", path.relative_to(root).as_posix()))
    return active


# ---------------------------------------------------------------------------
# The scope (docs/ai/config.md § Scope: `profile`, `exclude`) — what the template's units the
# project cut means for this start: the import lines of excluded rule files in docs/ai/local/rules.md
# (rules.sync_core_cut), the copies of skills and roles (update.sync_dependent_files, which runs
# earlier and follows the snapshot in the lock), and one line that names the cut. Skills, roles
# and rules are fixed when a session starts, so a change takes effect from the next one.
# ---------------------------------------------------------------------------

def _scope_notes(root: Path, write: bool, copies_moved: bool) -> tuple[list[str], list[str]]:
    """(lines to print, lines for the warn digest) for the scope. `copies_moved` says that the cut
    skills or roles differed from the lock's snapshot before the copies were synced for this start.
    Applies the rules.md import lines under `write` (session-start-refresh `block`); under `warn`
    only names what would change. Silent for a project that never cut anything and has nothing
    to restore."""
    import act_profile  # deferred, see _active_topics
    import rules
    import package_load
    printed: list[str] = []
    pending: list[str] = []
    if (root / actlib.LEGACY_RULES_FILE).is_file():
        # The project's rule file is still at its old place (or both places hold one): no rule file is written
        # and no package synced until update.py has moved it or the owner has merged the two; the start says so.
        return printed, pending
    # What active packages bring (import blocks, disabled rules, skill and role copies) goes first: the scope below
    # reads the marks it leaves. A package that is not intact is named every start, its files stay as they are.
    try:
        package_changed = package_load.sync_packages(root, write=write)
    except Exception as exc:  # noqa: BLE001 - the scope below still runs
        package_changed = []
        printed.append(f"[act] note: packages not applied ({exc.__class__.__name__}: {exc})")
    if package_changed:
        if write:
            printed.append(f"[act] note: packages: {', '.join(package_changed[:6])}"
                           + (f" and {len(package_changed) - 6} more" if len(package_changed) > 6 else "")
                           + " brought in line with the packages in .act-lock.json")
        else:
            pending.append(f"[act] note: packages: {len(package_changed)} file(s) would be brought in line with the "
                           "packages in .act-lock.json (warn mode, not applied)")
    for package_id, why in sorted(package_load.plan_for(root, actlib.read_packages(root)).problems.items()):
        printed.append(_package_problem_line(root, package_id, why))
    cut = act_profile.read_cut(root)
    core = rules.sync_core_cut(root, write=write)
    if cut.warnings:
        printed.append("[act] note: scope (docs/ai/config.md § Scope): " + "; ".join(cut.warnings))
    if core.problem:
        printed.append(f"[act] note: scope (docs/ai/config.md § Scope): {core.problem}")
    moved_rules = core.switched_off + core.restored
    if write:
        changed = copies_moved or bool(moved_rules)
    else:
        changed = False
        if copies_moved or moved_rules:
            parts = (["skill/role copies"] if copies_moved else []) + (
                [f"import lines of {', '.join(moved_rules)}"] if moved_rules else [])
            pending.append("[act] note: scope (profile/exclude) changed: "
                           f"{' and '.join(parts)} would be switched (warn mode, not applied)")
    if cut.empty and not changed:
        return printed, pending
    line = f"[act] scope: {act_profile.describe(cut)}"
    if changed:
        line += " — changed at this start, takes effect from the next session"
    printed.append(line)
    return printed, pending


# ---------------------------------------------------------------------------
# Packages (docs/ai/config.md § Packages, format: .act/formats/package.md) — what a session start says and does
# about them. It never activates one and never runs package code (no install.py, no check module): what it may do
# is unpack a zip that `packages.py fetch` (or the owner) put into .act-local/packages/ into a resting folder, so
# the owner can see it, and name what needs a person: a package whose folder is missing or not intact, a newer
# zip, a resting folder (once per id and version; `init.py --target` and `act-adopt` carry the packages of a source
# project this way) and one summary line for the active packages. A resting folder is read by nothing until
# `/act-packages add`.
# ---------------------------------------------------------------------------

_PACKAGES_DIR = ".act-local/packages"
_ZIP_NAME_RE = re.compile(r"^([a-z][a-z0-9-]{1,30})-(\d+)\.(\d+)\.(\d+)\.zip\Z")
_HEADER_VERSION_RE = re.compile(r"^version:[ \t]*(\d+\.\d+\.\d+)[ \t]*\r?$", re.MULTILINE)
_ZIP_STAGE_LIMIT = 8 * 1024 * 1024  # bytes: a larger zip is not unpacked at a session start (`add` reads it directly)
_STAGE_MIN_LEFT = 3.0               # seconds of the start's budget that must be left before a zip is staged
_STAGE_RESERVE = 1.0                # seconds of the start's budget the unpacking leaves for the checks after it
_ZIP_NOTES_KEY = "package_zip_notes"  # .act-local/cache.json: zips already reported, by name -> size:mtime
_REST_NOTES_KEY = "package_rest_notes"  # .act-local/cache.json: resting folders already named, by id -> version text
_PACKAGE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}\Z")
_MODULE_LOADED = time.monotonic()


def _start_left() -> float:
    """Seconds left of the session start's time budget: checks.common._HOOK_BUDGET counted from when dispatch.py
    began, from the load of this module when something else called (a probe)."""
    started = getattr(sys.modules.get("__main__"), "_HOOK_STARTED", None)
    if isinstance(started, bool) or not isinstance(started, (int, float)):
        started = _MODULE_LOADED
    budget = getattr(sys.modules.get("checks.common"), "_HOOK_BUDGET", 8.0)
    return float(started) + float(budget) - time.monotonic()


def _config_word(config: dict[str, str], key: str, default: str) -> str:
    value = str(config.get(key, "")).strip().strip("`").strip().lower()
    return value or default


def _parse_version(text: str) -> "Optional[tuple[int, int, int]]":
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", text.strip())
    return (int(match.group(1)), int(match.group(2)), int(match.group(3))) if match else None


def _version_text(version: "tuple[int, int, int]") -> str:
    return ".".join(str(part) for part in version)


def _package_problem_line(root: Path, package_id: str, why: list[str]) -> str:
    """The note for an active package that is not loaded: a missing folder names the way to get it (fetch, then add),
    anything else (a file differs from the lock, a link in the way) names doctor.py."""
    folder = root / ".act-local" / "packages" / package_id
    if not os.path.lexists(folder):
        return (f"[act] note: package {package_id} is not loaded: its folder {_PACKAGES_DIR}/{package_id}/ is missing here "
                f"(the folder is not versioned, a fresh clone has the lock only) — python .act/scripts/packages.py fetch "
                f"{package_id}, then `/act-packages add {package_id}`")
    return f"[act] note: package {package_id} is not loaded: {why[0]} — python .act/scripts/doctor.py"


def _package_zips(root: Path) -> "dict[str, tuple[tuple[int, int, int], Path]]":
    """The newest `<id>-<X.Y.Z>.zip` per id directly in .act-local/packages/ (plain files only)."""
    base = root / ".act-local" / "packages"
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return {}
    found: dict[str, tuple[tuple[int, int, int], Path]] = {}
    for name in names:
        match = _ZIP_NAME_RE.match(name)
        if not match:
            continue
        try:
            info = os.lstat(base / name)
        except OSError:
            continue
        if not stat.S_ISREG(info.st_mode) or actlib.is_redirect(info):
            continue
        version = (int(match.group(2)), int(match.group(3)), int(match.group(4)))
        if match.group(1) not in found or version > found[match.group(1)][0]:
            found[match.group(1)] = (version, base / name)
    return found


def _resting_version(root: Path, package_id: str) -> "Optional[tuple[int, int, int]]":
    """The version in the package.md of the folder .act-local/packages/<id>/ (a plain file in a plain folder), None
    when there is none or it cannot be read."""
    folder = root / ".act-local" / "packages" / package_id
    path = folder / "package.md"
    try:
        if actlib.is_redirect(os.lstat(folder)) or actlib.is_redirect(os.lstat(path)):
            return None
        with open(path, "rb") as stream:
            head = stream.read(4000).decode("utf-8", errors="replace")
    except OSError:
        return None
    found = _HEADER_VERSION_RE.search(head)
    return _parse_version(found.group(1)) if found else None


def _resting_folders(root: Path) -> "tuple[dict[str, str], bool]":
    """({id: version text}, complete) of the plain folders `.act-local/packages/<id>/` that hold a `package.md` (no
    link; a name that is no package id, such as `.staging`, is skipped). The version is read from the head of the
    package.md as _resting_version does, `unknown` when it cannot be read. `complete` is False when the start's time
    ran out before every folder was looked at."""
    base = root / ".act-local" / "packages"
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return {}, True
    found: dict[str, str] = {}
    for name in names:
        if not _PACKAGE_ID_RE.match(name):
            continue
        if _start_left() <= 0:
            return found, False
        try:
            info = os.lstat(base / name)
            if not stat.S_ISDIR(info.st_mode) or actlib.is_redirect(info) or not os.path.lexists(base / name / "package.md"):
                continue
        except OSError:
            continue
        version = _resting_version(root, name)
        found[name] = _version_text(version) if version else "unknown"
    return found, True


def _zip_signature(path: Path) -> str:
    try:
        info = os.lstat(path)
    except OSError:
        return ""
    return f"{info.st_size}:{info.st_mtime_ns}"


def _stage_zip(root: Path, package_id: str, version: "tuple[int, int, int]", zip_path: Path) -> "tuple[str, str]":
    """Unpack one zip into a staging folder, read it, and only when it is valid move the package folder to
    .act-local/packages/<id>/ (resting). Returns (outcome, line): `ready` (moved), `invalid` (refused; the first reason
    is in the line), `later` (the time budget is spent while unpacking or after it, or the move to the final name was
    refused: nothing moved, the next start tries again), `skip` (a folder of that name appeared meanwhile: nothing to
    say). Nothing partial is ever left under the final name: the move is one rename of a folder that was complete and
    checked. An OSError out of the staging is a zip that is not usable, reported once like any other."""
    import package_scan
    import packages
    name = zip_path.name
    if _start_left() < _STAGE_MIN_LEFT:
        return "later", (f"[act] note: package zip {name} not unpacked: this session start's time is used up; "
                         "it is tried again at the next start")
    try:
        staged = packages.stage(zip_path, root, lambda: _start_left() - _STAGE_RESERVE)
    except packages.StageTimeout:
        return "later", (f"[act] note: package zip {name} not unpacked: this session start's time ran out while unpacking; "
                         "it is tried again at the next start")
    except packages.PackageRefused as error:
        return "invalid", f"[act] note: package zip {name} is not usable: {error.reasons[0]} — left as it was"
    except (OSError, ValueError) as error:  # ValueError: the staging folder could not be removed again (discard refuses)
        return "invalid", f"[act] note: package zip {name} is not usable ({error.__class__.__name__}) — left as it was"
    try:
        result = packages.analyze(staged.folder, root)
        reasons = list(result.reasons) or packages.named_by_id(package_id, zip_path, result)
        if reasons:
            return "invalid", f"[act] note: package zip {name} is not usable: {reasons[0]} — left as it was"
        original = packages.VERIFY_TIMEOUT
        packages.VERIFY_TIMEOUT = max(1.0, min(float(original), _start_left() - 1.0))
        try:
            state, why = packages.origin(staged.copy, root, name)
        finally:
            packages.VERIFY_TIMEOUT = original
        if state == "bad":
            return "invalid", f"[act] note: package zip {name} is not usable: {why} — left as it was"
        if state == "unverified" and "timed out" in why:
            return "later", (f"[act] note: package zip {name} not unpacked: the signature check ran out of time; "
                             "it is tried again at the next start")
        findings = package_scan.scan(staged.folder)
        if _start_left() < 0:
            return "later", (f"[act] note: package zip {name} not unpacked: this session start's time is used up; "
                             "it is tried again at the next start")
        admitted, note = packages.admission(state, root)
        target = root / ".act-local" / "packages" / package_id
        if os.path.lexists(target):
            return "skip", ""
        if not actlib.local_write_ok(root, target):
            return "invalid", f"[act] note: package zip {name} not unpacked: .act-local is a link or leaves the project"
        try:
            os.rename(staged.folder, target)
        except OSError as error:
            return "later", (f"[act] note: package zip {name} not unpacked ({error.__class__.__name__}): its folder could not be moved "
                             "into place; it is tried again at the next start")
        return "ready", (f"[act] package {package_id} {_version_text(version)} is ready, resting in {_PACKAGES_DIR}/{package_id}/ "
                         f"(origin: {state}, {len(findings)} scan finding(s)"
                         + ("" if admitted else f"; not admitted: {note}")
                         + f"): nothing is active — see the plan with `/act-packages add {package_id}`")
    except OSError as error:
        return "invalid", f"[act] note: package zip {name} not unpacked ({error.__class__.__name__}) — left as it was"
    finally:
        try:
            packages.discard(staged)
        except (OSError, ValueError):
            pass


def _relaxations(manifest: "Optional[bytes]") -> "tuple[int, int]":
    """(disabled rules, weaker checks) a package.md names, counted by package_scan as the static scan lists them (a
    manifest larger than the scan reads counts for none)."""
    import package_scan
    return package_scan.relaxation_counts(package_scan.scan_text(manifest))


def _packages_summary(root: Path, config: dict[str, str], active: "dict[str, dict]") -> str:
    """One line for the active packages: names with versions, the relaxations they bring (the rules they disable and
    the checks they set weaker, counted as the static scan counts them, but from the hash-checked `package.md` bytes of
    each intact package only, never from other files that lie in its folder) and the value of `packages-unverified`."""
    import package_load
    disabled = weaker = 0
    unreadable: list[str] = []
    for package_id, entry in sorted(active.items()):
        package = package_load.read_package(root, package_id, entry)
        if not package.intact:
            unreadable.append(package_id)
            continue
        package_disabled, package_weaker = _relaxations(package.data.get("package.md"))
        disabled += package_disabled
        weaker += package_weaker
    names = ", ".join(f"{package_id} {entry.get('version', '?')}" for package_id, entry in sorted(active.items()))
    mode = _config_word(config, "packages-unverified", "block")
    shown = mode if mode in ("block", "scan", "allow") else f"{mode} (counts as block)"
    line = (f"[act] packages: {names} · relaxations: {disabled + weaker} ({disabled} disabled rule(s), {weaker} weaker "
            f"check(s)) · packages-unverified: {shown}")
    if unreadable:
        line += f" · not counted, not intact: {', '.join(unreadable)}"
    return line


def _package_notes(root: Path, config: dict[str, str], write: bool) -> tuple[list[str], list[str]]:
    """(lines to print, lines for the warn digest) about packages at a session start. With `write` a zip
    `<id>-<version>.zip` in .act-local/packages/ whose id has no folder and no lock entry is unpacked to a resting
    folder once (see _stage_zip); without it (`session-start-refresh: warn`) nothing is written and the zip is only
    named. A zip of an id that has a folder or a lock entry is never touched: when its version is higher, one line
    names it (`packages-update: ask`). The last line summarizes the active packages. With `write` the staging folders
    older than a day are removed first (packages.prune_staging). A resting folder `.act-local/packages/<id>/` of an id
    that is not in the lock is named once per id and version (`rests in`; the `is ready` line of a zip unpacked at this
    start counts as naming it), remembered under `package_rest_notes` in the cache (an id whose folder is gone is
    dropped from it); without `write` the line is printed and nothing is remembered."""
    printed: list[str] = []
    pending: list[str] = []
    if write and os.path.lexists(root / ".act-local" / "packages" / ".staging"):
        import packages
        packages.prune_staging(root)  # what an earlier start left behind when it was cut off; never raises
    active = actlib.read_packages(root)
    zips = _package_zips(root)
    ask = _config_word(config, "packages-update", "ask") == "ask"
    cache = actlib.read_cache()
    remembered = cache.get(_ZIP_NOTES_KEY, {}) if zips else {}
    remembered = remembered if isinstance(remembered, dict) else {}
    rest_remembered = cache.get(_REST_NOTES_KEY, {})
    rest_remembered = rest_remembered if isinstance(rest_remembered, dict) else {}
    rest_noted = dict(rest_remembered)
    noted = {name: sig for name, sig in remembered.items() if any(path.name == name for _v, path in zips.values())}
    waiting: list[str] = []
    for package_id, (version, zip_path) in sorted(zips.items()):
        if package_id in active or os.path.lexists(root / ".act-local" / "packages" / package_id):
            have = (_parse_version(str(active[package_id].get("version", ""))) if package_id in active
                    else _resting_version(root, package_id))
            if ask and have is not None and version > have:
                printed.append(f"[act] package {package_id}: newer version {_version_text(version)} ready (have "
                               f"{_version_text(have)}): `/act-packages add {package_id}` shows the plan and the diff")
            continue
        signature = _zip_signature(zip_path)
        if noted.get(zip_path.name) == signature:
            continue  # reported before, the zip has not changed since
        if not write:
            waiting.append(zip_path.name)
            continue
        if int(signature.split(":")[0] or 0) > _ZIP_STAGE_LIMIT:
            noted[zip_path.name] = signature
            printed.append(f"[act] note: package zip {zip_path.name} is larger than a session start unpacks "
                           f"({int(signature.split(':')[0]) // (1024 * 1024)} MB): `/act-packages add {package_id}` reads it directly")
            continue
        outcome, line = _stage_zip(root, package_id, version, zip_path)
        if line:
            printed.append(line)
        if outcome in ("ready", "invalid"):
            noted[zip_path.name] = signature
        if outcome == "ready":
            rest_noted[package_id] = _version_text(version)  # the `is ready` line named the folder
    resting, complete = _resting_folders(root)
    if complete:
        rest_noted = {package_id: version for package_id, version in rest_noted.items() if package_id in resting}
    for package_id, version in sorted(resting.items()):
        if package_id in active or rest_noted.get(package_id) == version:
            continue
        printed.append(f"[act] package {package_id} {version} rests in {_PACKAGES_DIR}/{package_id}/ (not active): "
                       f"`/act-packages add {package_id}` shows the plan")
        rest_noted[package_id] = version
    if not write:
        rest_noted = rest_remembered  # printed, nothing remembered
    changed_cache: dict = {}
    if write and noted != remembered:
        changed_cache[_ZIP_NOTES_KEY] = noted
    if write and rest_noted != rest_remembered:
        changed_cache[_REST_NOTES_KEY] = rest_noted
    if changed_cache:
        try:
            actlib.write_cache(changed_cache)
        except OSError:
            pass
    if waiting:
        pending.append(f"[act] note: package zip(s) {', '.join(waiting)} would be unpacked to a resting folder "
                       "(warn mode, not applied)")
    if active:
        printed.append(_packages_summary(root, config, active))
    return printed, pending
