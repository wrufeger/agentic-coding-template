#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Find out which ways lead from this project to its repo host and issue tracker (REST access
#          through forge.py, MCP servers) and what each one can do, and keep the result in
#          docs/project/integrations.md so act-pr and act-issue know it (skill act-integrations).
#          Only ever reads: the probes are whoami, project, and an issue list with limit 1. A write
#          capability (create issue, comment, create PR/MR) is never tried — it is reported as
#          "access present, not tried", with the token's scope where the service reveals it for
#          reading (GitLab GET /personal_access_tokens/self, GitHub header X-OAuth-Scopes).
#          The token goes only to a confirmed host (forge.py: github.com / api.github.com, gitlab.com,
#          `forge-host`, the host of ACT_FORGE_API_URL; never over http except to loopback). For any
#          other host the reads run without it and whoami and the write capabilities show the own state
#          "host not confirmed" (with the way out: `forge-host` in docs/ai/config.md § Git hosting); for
#          a confirmed host reached over plain http they show "http only — use https" — neither is a
#          failure. Every row's detail is scrubbed of the token value, whatever the service echoed.
#          Also names the entry of .act/mcp-catalog.md for a detected repo host that has no matching MCP
#          server (only the field lines `id` and `serves` are read; no catalog, no hint, no failure).
#          Standard library only; the access token is never printed or stored, only the NAME of the
#          variable it came from.
#
# Usage:
#   python .act/scripts/integrations.py check [--write] [--json] [--root DIR] [--remote NAME]
#                                             [--mcp CAPABILITY=TOOL ...]
#       Detect and probe. --write also writes docs/project/integrations.md (table capability x way x
#       state x date, who checked, headings in `language-docs`, a machine line with the check date).
#       --mcp names an MCP tool the assistant sees in its session for a capability (read-project,
#       read-issues, create-issue, comment, create-pr) — only the assistant can see those tools, so
#       the skill passes them in; repeatable.
#   python .act/scripts/integrations.py status [--max-age-days 30] [--root DIR]
#       Exit 0 if docs/project/integrations.md exists and is not older than --max-age-days; exit 3
#       (one line, "run act-integrations") if it is missing, has no check date or is too old.
#       act-pr and act-issue rely on exactly this contract.
#
#   Examples:
#     python .act/scripts/integrations.py check
#     python .act/scripts/integrations.py check --write --mcp read-issues=mcp__github__list_issues
#     python .act/scripts/integrations.py status --max-age-days 30
#
# Environment:
#   GITHUB_TOKEN / GH_TOKEN / GITLAB_TOKEN   access, read as forge.py reads it (environment, else .env)
#   ACT_MCP_LIST_COMMAND     replaces `claude mcp list` (tests); ACT_MCP_LIST_TIMEOUT seconds (default 20)
#   ACT_MCP_CATALOG          replaces the path of .act/mcp-catalog.md (tests)
#   ACT_FORGE_API_URL / ACT_FORGE_KIND   as for forge.py (tests, proxies)
#
# Output: plain text, or one JSON document with --json. Exit 0 = ok, 2 = failed, 3 = status: run the
# skill (missing or stale).

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import actlib
import forge

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

DOC_RELATIVE = Path("docs") / "project" / "integrations.md"
MACHINE_KEY = "act:integrations-checked"
MACHINE_RE = re.compile(r"<!--\s*act:integrations-checked:\s*(\d{4}-\d{2}-\d{2})\s*-->")
DEFAULT_MAX_AGE_DAYS = 30
MCP_LIST_TIMEOUT_DEFAULT = 20
EXIT_STALE = 3
CATALOG_PATH = Path(__file__).resolve().parent.parent / "mcp-catalog.md"
_CATALOG_FIELD = re.compile(r"^-\s+(id|serves):\s*(.*?)\s*$")

CAPABILITIES = ("read-project", "read-issues", "create-issue", "comment", "create-pr")
WRITE_CAPABILITIES = ("create-issue", "comment", "create-pr")
REST = "rest"
MCP = "mcp"


@dataclass
class Row:
    capability: str  # "whoami" or one of CAPABILITIES
    way: str  # REST | MCP
    state: str  # ok | failed | none | untried | blocked | unconfirmed | insecure | unknown
    detail: str = ""


@dataclass
class RestInfo:
    remote: str = ""  # "origin"
    host: str = ""
    project: str = ""
    kind: str = ""
    kind_reason: str = ""
    access: str = ""  # variable NAME, e.g. "env GITHUB_TOKEN"; never the value
    host_confirmed: bool = False  # the API host is one the token may go to (forge.py)
    token_note: str = ""  # why a token would not be sent to the API base ("" = it would be)
    notes: list[str] = field(default_factory=list)
    problem: str = ""  # why the REST way is not usable at all


@dataclass
class McpInfo:
    configured: list[str] = field(default_factory=list)  # names from .mcp.json
    configured_note: str = ""
    listed: Optional[list[dict[str, str]]] = None  # name + status from `claude mcp list`; None = unknown
    listed_note: str = ""


# ---------------------------------------------------------------------------
# REST
# ---------------------------------------------------------------------------

def _scrub(text: str, secret: str) -> str:
    return text.replace(secret, "***") if secret else text


def _get(fg: forge.Forge, path: str) -> forge.Response:
    """One GET with the token (where forge.auth_headers lets it go), no redirect, with the response
    headers (forge.call returns only the decoded JSON). An HTTP status never raises; a server that
    cannot be reached or answers with no HTTP raises ForgeError with a one-line, scrubbed message."""
    url = fg.api_base + path
    return forge.fetch(url, forge.auth_headers(fg, url), secret=fg.token)


def token_scopes(fg: forge.Forge) -> Optional[list[str]]:
    """The token's scopes as the service reveals them for reading, or None when it does not (a
    fine-grained GitHub token, an OAuth or project token on GitLab, any error)."""
    try:
        if fg.kind == "github":
            answer = _get(fg, "/user")
            raw = answer.headers.get("x-oauth-scopes")
            if answer.status != 200 or raw is None:
                return None
            return [s.strip() for s in raw.split(",") if s.strip()]
        answer = _get(fg, "/personal_access_tokens/self")
        data = forge.json_or_none(answer.text)
        if answer.status == 200 and isinstance(data, dict) and isinstance(data.get("scopes"), list):
            return [str(s) for s in data["scopes"]]
    except forge.ForgeError:
        pass
    return None


def write_state(fg: forge.Forge, public: bool, scopes: Optional[list[str]]) -> tuple[str, str]:
    """(state, detail) for every write capability, decided from the token's scopes alone."""
    if scopes is None:
        return "untried", "scope not visible for this token type"
    shown = ", ".join(scopes) or "-"
    if fg.kind == "github":
        if "repo" in scopes or ("public_repo" in scopes and public):
            return "untried", f"scopes: {shown}"
        return "blocked", f"scopes: {shown}; writing needs `repo`" + ("" if public else " (private project)")
    if "api" in scopes:
        return "untried", f"scopes: {shown}"
    return "blocked", f"scopes: {shown}; writing needs `api`"


def _other_names(root: Path, kind: str) -> list[str]:
    """Names of token variables set for the OTHER hoster — a hint when the wrong one is set."""
    others = [n for k, names in forge.TOKEN_NAMES.items() if k != kind for n in names]
    found = [f"env {n}" for n in others if os.environ.get(n, "").strip()]
    dotenv = root / ".env"
    if dotenv.is_file():
        values = forge.read_dotenv(dotenv)
        found += [f".env {n}" for n in others if n in values]
    return found


def _no_way(problem: str, info: RestInfo) -> tuple[RestInfo, list[Row]]:
    info.problem = problem
    rows = [Row(c, REST, "none", problem) for c in ("whoami", *CAPABILITIES)]
    return info, rows


def probe_rest(root: Path, remote_name: str) -> tuple[RestInfo, list[Row]]:
    info = RestInfo()
    try:
        remote = forge.find_remote(root, remote_name)
    except forge.ForgeError as exc:
        return _no_way(str(exc), info)
    info.remote, info.host, info.project = remote.name, remote.host, remote.project_path
    config = actlib.read_config(root)
    try:
        forge.api_override()
        kind, reason = forge.detect_kind(remote, config)
        fg, notes = forge.assemble_forge(root, remote, config, kind, reason)
    except forge.ForgeError as exc:
        return _no_way(str(exc), info)
    token = fg.token
    info.kind, info.kind_reason, info.access, info.notes = kind, reason, fg.token_source, list(notes)
    info.host_confirmed, info.token_note = fg.host_confirmed, fg.token_block
    withheld = bool(token and fg.token_block)  # a token is set, but may not go to this host
    held_state = "unconfirmed" if not fg.host_confirmed else "insecure"  # why: the host itself, or plain http

    rows: list[Row] = []
    names = " or ".join(forge.TOKEN_NAMES[kind])
    other = _other_names(root, kind)
    if other:
        info.notes.append(f"a token variable for the other hoster is set ({', '.join(other)}), but this remote is {kind}")

    def attempt(capability: str, action: Any) -> Any:
        try:
            value, detail = action()
        except forge.ForgeError as exc:
            rows.append(Row(capability, REST, "failed", _scrub(str(exc), token)))
            return None
        rows.append(Row(capability, REST, "ok", detail))
        return value

    if withheld:  # reads below run without the token; whoami and the writes need it
        who = None
        rows.append(Row("whoami", REST, held_state, fg.token_block))
    elif token:
        who = attempt("whoami", lambda: _whoami(fg))
    else:
        who = None
        rows.append(Row("whoami", REST, "none", f"no token: set {names} in the environment or in .env"))
    project = attempt("read-project", lambda: _project(fg))
    attempt("read-issues", lambda: _issues(fg))

    if who is None:
        for capability in WRITE_CAPABILITIES:
            if withheld:
                rows.append(Row(capability, REST, held_state, fg.token_block))
            else:
                rows.append(Row(capability, REST, "none",
                                f"no token: set {names}" if not token else "token not accepted (see whoami)"))
    else:
        public = project is not None and project.visibility == "public"
        state, detail = write_state(fg, public, token_scopes(fg))
        for capability in WRITE_CAPABILITIES:
            rows.append(Row(capability, REST, state, detail))
    for row in rows:  # whatever the service echoed (a scope header, a project name), the value never lands in a row
        row.detail = _scrub(row.detail, token)
    return info, rows


def _whoami(fg: forge.Forge) -> tuple[str, str]:
    data = forge.require_dict(forge.call(fg, "GET", "/user"), "the current user")
    login = str(data.get("login") or data.get("username") or "")
    return login, f"@{login}"


def _project(fg: forge.Forge) -> tuple[forge.Project, str]:
    project = forge.get_project(fg)
    return project, f"{project.name}, default branch {project.default_branch or '-'}, {project.visibility}"


def _issues(fg: forge.Forge) -> tuple[list[forge.Item], str]:
    items = forge.list_issues(fg, "open", False, [], 1)
    return items, "read one open issue" if items else "answered, no open issue"


# ---------------------------------------------------------------------------
# MCP
# ---------------------------------------------------------------------------

def read_mcp_json(root: Path) -> tuple[list[str], str]:
    """Server NAMES from .mcp.json; never the commands, arguments or env values (they may hold secrets)."""
    path = root / ".mcp.json"
    if not path.is_file():
        return [], "no .mcp.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return [], f".mcp.json unreadable ({type(exc).__name__})"
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        return [], ".mcp.json has no mcpServers"
    return sorted(str(name) for name in servers), ""


_LIST_LINE = re.compile(r"^(?P<name>.+?):\s+(?P<rest>\S.*)$")


def parse_mcp_list(text: str) -> list[dict[str, str]]:
    """Name and a normalized status per line of `claude mcp list` — the rest of the line (address,
    command line) is dropped on purpose."""
    found: list[dict[str, str]] = []
    for line in text.splitlines():
        match = _LIST_LINE.match(line.strip())
        if not match or match.group("name").lower().startswith("checking"):
            continue
        rest = match.group("rest").lower()
        if "needs authentication" in rest:
            status = "needs-auth"
        elif "failed" in rest or "✗" in rest:
            status = "failed"
        elif "connected" in rest or "✓" in rest:
            status = "connected"
        else:
            status = "unknown"
        found.append({"name": match.group("name").strip(), "status": status})
    return found


def run_mcp_list(root: Path) -> tuple[Optional[list[dict[str, str]]], str]:
    """(servers, note); servers is None when the answer is unknown — never an exception."""
    override = os.environ.get("ACT_MCP_LIST_COMMAND", "").strip()
    if override:
        command = shlex.split(override)
    else:
        found = shutil.which("claude")
        if not found:
            return None, "`claude` is not on the path"
        command = [found, "mcp", "list"]
    try:
        seconds = float(os.environ.get("ACT_MCP_LIST_TIMEOUT", "") or MCP_LIST_TIMEOUT_DEFAULT)
    except ValueError:
        seconds = float(MCP_LIST_TIMEOUT_DEFAULT)
    try:
        proc = subprocess.Popen(command, cwd=str(root), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                start_new_session=(os.name != "nt"))  # own process group: killpg below
    except (OSError, ValueError) as exc:
        return None, f"`claude mcp list` could not run ({type(exc).__name__})"
    try:
        stdout, _stderr = proc.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        _kill_process_tree(proc)
        return None, f"`claude mcp list` did not answer within {seconds:g} s"
    if proc.returncode != 0:
        return None, f"`claude mcp list` failed (exit {proc.returncode})"
    return parse_mcp_list(stdout), ""


def _kill_process_tree(proc: "subprocess.Popen[str]") -> None:
    """Stop `proc` and everything it started, then let go of its pipes. `subprocess.run(timeout=...)`
    kills only the direct child; on Windows `claude` is `claude.cmd`, whose node grandchild keeps the pipes
    open, so waiting for the output would hang far past the limit. Best effort: `taskkill /T /F` on
    Windows, the process group elsewhere. Checked with a stand-in that leaves a sleeping grandchild
    holding the pipes (tests/probes/t1-integrations); not checked against a real `claude.cmd` hang."""
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                           stdin=subprocess.DEVNULL, timeout=10, check=False)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.communicate(timeout=5)
    except subprocess.TimeoutExpired:  # a survivor still holds the pipes: stop waiting for them
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass


def probe_mcp(root: Path, tools: dict[str, str]) -> tuple[McpInfo, list[Row]]:
    info = McpInfo()
    info.configured, info.configured_note = read_mcp_json(root)
    info.listed, info.listed_note = run_mcp_list(root)
    names = sorted(set(info.configured) | {s["name"] for s in (info.listed or [])})
    rows: list[Row] = []
    for capability in CAPABILITIES:
        if capability in tools:
            rows.append(Row(capability, MCP, "untried", f"tool {tools[capability]}"))
        elif names:
            rows.append(Row(capability, MCP, "unknown", f"servers: {', '.join(names)}; tools are visible to the assistant only"))
        else:
            rows.append(Row(capability, MCP, "none", "no MCP server found"))
    return info, rows


# ---------------------------------------------------------------------------
# MCP catalog (only the field lines `id` and `serves`)
# ---------------------------------------------------------------------------

def read_catalog(path: Optional[Path] = None) -> list[tuple[str, list[str]]]:
    """(id, serves) per entry of .act/mcp-catalog.md; an empty list when the file is missing, unreadable
    or has no entry - never an exception."""
    if path is None:
        override = os.environ.get("ACT_MCP_CATALOG", "").strip()
        path = Path(override) if override else CATALOG_PATH
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return []
    entries: list[tuple[str, list[str]]] = []
    fields: dict[str, str] = {}

    def close() -> None:
        if fields.get("id"):
            serves = [v.strip().lower() for v in fields.get("serves", "").split(",") if v.strip()]
            entries.append((fields["id"], serves))

    for line in text.splitlines():
        if line.startswith("## "):
            close()
            fields = {}
            continue
        match = _CATALOG_FIELD.match(line)
        if match and match.group(1) not in fields:
            fields[match.group(1)] = match.group(2).replace("`", "").strip()
    close()
    return entries


def catalog_hints(kind: str, mcp: McpInfo) -> list[dict[str, str]]:
    """The catalog entries that serve the detected repo host, unless an MCP server of the session or of
    `.mcp.json` already carries the entry's id or the host's name."""
    if not kind:
        return []
    names = [n.lower() for n in [*mcp.configured, *[s["name"] for s in (mcp.listed or [])]]]
    hints: list[dict[str, str]] = []
    for entry_id, serves in read_catalog():
        if kind.lower() not in serves:
            continue
        if any(entry_id.lower() in name or kind.lower() in name for name in names):
            continue
        hints.append({"id": entry_id, "serves": kind,
                      "hint": f"no MCP server for {kind} found; the catalog entry `{entry_id}` "
                              f"(.act/mcp-catalog.md) describes one - ask act-integrations to propose it"})
    return hints


# ---------------------------------------------------------------------------
# Result, report, file
# ---------------------------------------------------------------------------

@dataclass
class Result:
    date: str
    checked_by: str
    rest: RestInfo
    mcp: McpInfo
    rows: list[Row]
    catalog_hints: list[dict[str, str]] = field(default_factory=list)  # {"id", "serves", "hint"}


def who_checked() -> str:
    try:
        identity = actlib.read_identity()
    except RuntimeError:
        identity = None
    name = str((identity or {}).get("identity") or "").strip()
    return name or "unknown"


def run_check(root: Path, remote_name: str, tools: dict[str, str]) -> Result:
    rest, rest_rows = probe_rest(root, remote_name)
    mcp, mcp_rows = probe_mcp(root, tools)
    return Result(datetime.date.today().isoformat(), who_checked(), rest, mcp, rest_rows + mcp_rows,
                  catalog_hints(rest.kind, mcp))


def _labels(language: str) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    def t(en: str, de: str) -> str:
        return actlib.localized(language, en, de)

    capabilities = {
        "whoami": t("Sign in as the token's user (whoami)", "Als Token-Benutzer anmelden (whoami)"),
        "read-project": t("Read project", "Projekt lesen"),
        "read-issues": t("Read issues", "Issues lesen"),
        "create-issue": t("Create issue", "Issue anlegen"),
        "comment": t("Comment", "Kommentieren"),
        "create-pr": t("Create pull/merge request", "PR/MR anlegen"),
    }
    ways = {REST: t("REST (forge.py)", "REST (forge.py)"), MCP: "MCP"}
    states = {
        "ok": t("works", "funktioniert"),
        "failed": t("failed", "fehlgeschlagen"),
        "none": t("no access", "kein Zugang"),
        "untried": t("access present, not tried", "Zugang vorhanden, nicht erprobt"),
        "blocked": t("token scope too small", "Token-Berechtigung reicht nicht"),
        "unconfirmed": t("host not confirmed", "Host nicht bestätigt"),
        "insecure": t("http only — use https", "nur http — https verwenden"),
        "unknown": t("unknown", "unbekannt"),
    }
    return capabilities, ways, states


def _cell(text: str) -> str:
    return " ".join(text.replace("|", "/").split())


def render_table(result: Result, language: str, with_date: bool) -> list[str]:
    capabilities, ways, states = _labels(language)
    t = lambda en, de: actlib.localized(language, en, de)  # noqa: E731
    head = [t("Capability", "Fähigkeit"), t("Way", "Weg"), t("State", "Stand")]
    if with_date:
        head.append(t("Checked", "Geprüft"))
    lines = ["| " + " | ".join(head) + " |", "| " + " | ".join(":---" for _ in head) + " |"]
    for row in result.rows:
        state = states[row.state] + (f" — {row.detail}" if row.detail else "")
        cells = [capabilities[row.capability], ways[row.way], _cell(state)]
        if with_date:
            cells.append(result.date)
        lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    return lines


def render_doc(result: Result, language: str) -> str:
    t = lambda en, de: actlib.localized(language, en, de)  # noqa: E731
    rest, mcp = result.rest, result.mcp
    lines = [f"<!-- {MACHINE_KEY}: {result.date} -->",
             t("# Integrations", "# Integrationen"), "",
             t(f"Checked on {result.date} by {result.checked_by} with "
               "`python .act/scripts/integrations.py check --write` (skill `act-integrations`). Only read "
               "calls were made; a write capability is never tried, so it reads \"access present, not "
               "tried\" at best (`R-safe-approval`). The file holds no token, only the names of the variables.",
               f"Geprüft am {result.date} von {result.checked_by} mit "
               "`python .act/scripts/integrations.py check --write` (Skill `act-integrations`). Es wurde nur "
               "gelesen; eine schreibende Fähigkeit wird nie erprobt und steht höchstens als \"Zugang "
               "vorhanden, nicht erprobt\" da (`R-safe-approval`). Die Datei enthält kein Token, nur die "
               "Namen der Variablen."), "",
             t("## Capabilities", "## Fähigkeiten"), ""]
    lines += render_table(result, language, with_date=True)
    lines += ["", t("## Project and access", "## Projekt und Zugang"), ""]
    if rest.problem:
        lines.append(t(f"- REST: not usable — {rest.problem}", f"- REST: nicht nutzbar — {rest.problem}"))
    else:
        lines += [t(f"- Remote: `{rest.remote}` → {rest.host}, project `{rest.project}`",
                    f"- Remote: `{rest.remote}` → {rest.host}, Projekt `{rest.project}`"),
                  t(f"- Host kind: {rest.kind} ({rest.kind_reason})", f"- Hoster: {rest.kind} ({rest.kind_reason})"),
                  t(f"- Access from: {rest.access or 'nothing found'}",
                    f"- Zugang aus: {rest.access or 'nichts gefunden'}"),
                  t(f"- Host confirmed for the token: {'yes' if rest.host_confirmed else 'no'} (`forge-host`)",
                    f"- Host für das Token bestätigt: {'ja' if rest.host_confirmed else 'nein'} (`forge-host`)")]
        if rest.token_note:
            lines.append(f"- {t('Note', 'Hinweis')}: {rest.token_note}")
    for note in rest.notes:
        lines.append(f"- {t('Note', 'Hinweis')}: {note}")
    lines += ["", t("## MCP servers", "## MCP-Server"), ""]
    lines.append(t(f"- `.mcp.json`: {', '.join(mcp.configured) or mcp.configured_note or 'none'}",
                   f"- `.mcp.json`: {', '.join(mcp.configured) or mcp.configured_note or 'keine'}"))
    if mcp.listed is None:
        lines.append(t(f"- `claude mcp list`: unknown ({mcp.listed_note})", f"- `claude mcp list`: unbekannt ({mcp.listed_note})"))
    else:
        shown = ", ".join(f"{s['name']} ({s['status']})" for s in mcp.listed) or t("none", "keine")
        lines.append(f"- `claude mcp list`: {shown}")
    lines += ["", t("The CLI tools `gh` and `glab` are not used.", "Die Werkzeuge `gh` und `glab` werden nicht verwendet.")]
    return "\n".join(lines) + "\n"


def render_text(result: Result) -> str:
    rest, mcp = result.rest, result.mcp
    lines = [f"checked: {result.date} by {result.checked_by}"]
    if rest.problem:
        lines.append(f"rest: not usable - {rest.problem}")
    else:
        lines += [f"remote: {rest.remote} -> {rest.host} {rest.project}",
                  f"hoster: {rest.kind} ({rest.kind_reason})", f"access: {rest.access or 'none found'}",
                  f"host confirmed for the token: {'yes' if rest.host_confirmed else 'no'}"]
        if rest.token_note:
            lines.append(f"token: {rest.token_note}")
    lines += [f"note: {n}" for n in rest.notes]
    lines.append(f"mcp .mcp.json: {', '.join(mcp.configured) or mcp.configured_note or 'none'}")
    if mcp.listed is None:
        lines.append(f"mcp list: unknown ({mcp.listed_note})")
    else:
        lines.append("mcp list: " + (", ".join(f"{s['name']} ({s['status']})" for s in mcp.listed) or "none"))
    lines += [f"hint: {h['hint']}" for h in result.catalog_hints]
    lines.append("")
    lines += render_table(result, "en", with_date=False)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def parse_mcp_tools(values: list[str]) -> dict[str, str]:
    tools: dict[str, str] = {}
    for value in values:
        capability, sep, tool = value.partition("=")
        capability, tool = capability.strip(), tool.strip()
        if not sep or capability not in CAPABILITIES or not tool:
            raise ValueError(f"--mcp {value!r}: expected CAPABILITY=TOOL with CAPABILITY one of {', '.join(CAPABILITIES)}")
        tools[capability] = tool
    return tools


def cmd_check(root: Path, args: argparse.Namespace) -> int:
    try:
        tools = parse_mcp_tools(args.mcp or [])
    except ValueError as exc:
        print(f"integrations: {exc}", file=sys.stderr)
        return 2
    result = run_check(root, args.remote, tools)
    written = ""
    if args.write:
        language = actlib.docs_language(root)
        path = root / DOC_RELATIVE
        try:
            actlib.write_text_lf(path, render_doc(result, language))
        except OSError as exc:
            print(f"integrations: cannot write {path}: {exc}", file=sys.stderr)
            return 2
        written = DOC_RELATIVE.as_posix()
    if args.json:
        data = asdict(result)
        data["written"] = written
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render_text(result))
        if written:
            print(f"\nwritten: {written}")
    return 0


def cmd_status(root: Path, args: argparse.Namespace) -> int:
    path = root / DOC_RELATIVE
    hint = "run act-integrations"
    if not path.is_file():
        print(f"{DOC_RELATIVE.as_posix()} is missing - {hint}")
        return EXIT_STALE
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"{DOC_RELATIVE.as_posix()} is unreadable ({type(exc).__name__}) - {hint}")
        return EXIT_STALE
    match = MACHINE_RE.search(text)
    if not match:
        print(f"{DOC_RELATIVE.as_posix()} has no check date - {hint}")
        return EXIT_STALE
    try:
        checked = datetime.date.fromisoformat(match.group(1))
    except ValueError:
        print(f"{DOC_RELATIVE.as_posix()} has an invalid check date - {hint}")
        return EXIT_STALE
    age = (datetime.date.today() - checked).days
    if age > args.max_age_days:
        print(f"{DOC_RELATIVE.as_posix()} was checked {age} days ago (limit {args.max_age_days}) - {hint}")
        return EXIT_STALE
    print(f"{DOC_RELATIVE.as_posix()} checked {checked.isoformat()} ({max(age, 0)} days ago)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Find and probe (read-only) the ways to the repo host and issue tracker, and keep "
                    "the result in docs/project/integrations.md. Never writes to a live system.")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", help="project root (default: found from the current directory)")
    check = sub.add_parser("check", parents=[common], help="detect, probe read-only, optionally write the file")
    check.add_argument("--write", action="store_true", help="write docs/project/integrations.md")
    check.add_argument("--json", action="store_true", help="print one JSON document instead of text")
    check.add_argument("--remote", default="", help="git remote to use (default: origin, else the only one)")
    check.add_argument("--mcp", action="append", metavar="CAPABILITY=TOOL",
                       help="an MCP tool the assistant sees for a capability (repeatable)")
    status = sub.add_parser("status", parents=[common], help="exit 0 if the file exists and is fresh, else 3")
    status.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = Path(args.root).resolve() if args.root else actlib.repo_root()
        os.chdir(root)  # actlib.read_identity() looks from the working directory
        if args.command == "check":
            return cmd_check(root, args)
        return cmd_status(root, args)
    except (forge.ForgeError, RuntimeError) as exc:
        print(f"integrations: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
