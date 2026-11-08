"""Session start, context lines: compact note, identity, environment overrides, output depth, board
excerpt, chat language, active topics, ideas and the scope.

Split out of session.py, which keeps the entry point and the order of the sub-steps."""
from __future__ import annotations

import json
import os
import re
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
        return ("[act] no identity for this checkout (git user.name is not set or has no letter or digit); board, ideas and new "
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


def _ideas_pending(root: Path) -> "tuple[str, list[str]]":
    """(root-relative path of the session owner's ideas file, its new or changed entries) — see
    ideas.py; ("", []) when there is no identity, no file, or ideas.py cannot be imported. Imported
    lazily like `update`/`rules`: a session start never pays for it unless it is reached, and a
    broken ideas.py must not end the session."""
    try:
        import ideas  # deferred: see the docstring
        path, keys = ideas.pending(root)
        if path is None or not keys:
            return "", []
        return path.relative_to(root).as_posix(), keys
    except Exception:
        return "", []


def _ideas_note(rel: str, keys: list[str]) -> str:
    """The `[act] ideas:` session note: how many entries are new or changed, the first few titles
    (ideas.titles_text), and what to do about them."""
    import ideas  # deferred, as in _ideas_pending
    return (f"[act] ideas: {len(keys)} new or changed in {rel} — {ideas.titles_text(keys)} — "
            "process them per the ideas topic, then `python .act/scripts/ideas.py --seen`")


def _ideas_ensure_notes(root: Path, config: dict[str, str], write: bool) -> list[str]:
    """One note per file ideas.ensure() created for the session owner (or, with write=False, would
    create): the folder README.md of the ideas files and the owner's own file. Best effort."""
    import ideas  # deferred, as in _ideas_pending
    notes: list[str] = []
    english = actlib.is_english(actlib.language_settings(config)[1])
    for path, kind in ideas.ensure(root, plan=not write):
        rel = path.relative_to(root).as_posix()
        if not write:
            notes.append(f"[act] note: {rel} would be created (warn mode, not applied)")
        elif kind == "readme":
            extra = "" if english else " — scaffold in English, translate it once (R-work-language)"
            notes.append(f"[act] note: created {rel} — how the ideas files work{extra}")
        else:
            notes.append(f"[act] note: created {rel} — your own ideas file, one `## <title>` section per idea")
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
    # "ideas" is data-driven too: active while the owner's own ideas file has entries not yet
    # processed (ideas.py).
    if "ideas" not in cut_topics and _ideas_pending(root)[1]:
        resolved = actlib.resolve("rules/topics/ideas.md")
        if resolved is None:
            active.append(("ideas", "missing"))
        else:
            path, _origin = resolved
            active.append(("ideas", path.relative_to(root).as_posix()))
    return active


# ---------------------------------------------------------------------------
# The scope (docs/ai/config.md § Scope: `profile`, `exclude`) — what the template's units the
# project cut means for this start: the import lines of excluded rule files in docs/ai/rules.md
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
    cut = act_profile.read_cut(root)
    core = rules.sync_core_cut(root, write=write)
    printed: list[str] = []
    pending: list[str] = []
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
