#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: A small REST client for the project's git host (GitHub, GitHub Enterprise, GitLab.com and
#          self-hosted GitLab) — the one script the skills act-integrations, act-pr and act-issue
#          call. Standard library only, so it runs wherever Python does, with no `gh`/`glab` and no MCP
#          server. Reads are free; every write shows a preview and only runs with --apply, so it is
#          the vetted script for recurring writes to a live system (R-safe-approval).
#
#          Rules that hold without exception:
#            - The access token is read from the environment or from `.env` in the project root
#              (only GITHUB_TOKEN / GH_TOKEN / GITLAB_TOKEN), never from the command line, and it is
#              never printed, logged or put into an error message — only the NAME of the variable is.
#              A token is one line of visible ASCII; a value with a space, tab, line break or control
#              character (a file with a second line) is refused before any request, by name only —
#              http.client would otherwise echo such a header value, escaped past any scrub.
#            - The token is sent only to a confirmed host: github.com / api.github.com, gitlab.com, a
#              host named in the config key `forge-host`, or the host of ACT_FORGE_API_URL (an explicit
#              override) — and never over http, except to loopback (127.0.0.1, ::1, localhost). A
#              global GITHUB_TOKEN / GITLAB_TOKEN therefore never flows to a host that merely answers
#              like a git host. Without confirmation, reads run without the token (public projects);
#              whoami, issues --mine and every write stop before any request with one line naming the
#              host (and so does the same set without any token, naming the variable to set).
#            - A host is letters, digits, dots and hyphens (or an IPv6 address): a remote whose host part
#              holds `@` or `\` is refused, because urlsplit and the socket layer would read it as two
#              different hosts (`git@evil.com\@github.com:g/p` looks like github.com to one of them).
#            - The hoster probe of an unknown host (GET /api/v4/version, /api/v3/meta) never carries
#              a token.
#            - No redirect is followed (a redirect would carry the token to another host).
#            - A network or HTTP failure ends with exit 2 and one line, never a traceback; the text of a
#              ValueError from urllib (an invalid header value or address) is never shown, a service
#              message is scrubbed before it is cut, and an answer of an unexpected shape is one line too.
#
# Usage:
#   python .act/scripts/forge.py [--root DIR] [--remote NAME] [--json] <command> [options]
#
#   Read:
#     detect                              host, kind, project path, API base, where the access comes from,
#                                         whether the host is confirmed for the token
#     whoami | project | default-branch
#     target-branch                       config key `target-branch`, else the remote's default branch
#                                         (API, else origin/HEAD), else development / develop / main
#     issues [--state open|closed|all] [--mine] [--label L] [--limit 15]   (--mine needs the token)
#     issue N
#     prs [--state open|closed|all] [--limit 15]
#     branch-name N                       bugfix/<n>-<short-title> for a `bug`, else feature/<n>-<...>
#   Write (without --apply: preview only, nothing is written; --show-body prints the full text):
#     create-issue --title T --body-file F [--label L ...] [--show-body] [--apply]
#     comment N --body-file F [--show-body] [--apply]
#     close-issue N [--apply]              (GitHub: refuses a pull request; checked with --apply)
#     create-pr --source B --target B --title T --body-file F [--draft] [--show-body] [--apply]
#     close-pr N [--apply]
#
#   Examples:
#     python .act/scripts/forge.py detect
#     python .act/scripts/forge.py issues --mine --limit 5
#     python .act/scripts/forge.py create-pr --source feature/7-x --target main --title "X" --body-file pr.md
#
# Environment:
#   GITHUB_TOKEN / GH_TOKEN / GITLAB_TOKEN   access (or the same names in `.env` in the project root)
#   ACT_FORGE_API_URL                        replaces the API base (tests, proxies); an http(s) address with
#                                            a host, no credentials; its host counts as confirmed
#   ACT_FORGE_KIND                           github | gitlab, replaces the detection (tests)
# Config (docs/ai/config.md § Git hosting): `forge` (github|gitlab, for a host the script cannot tell by
#   name), `forge-host` (a host name or a comma-separated list: the hosts the token may go to besides
#   github.com and gitlab.com), `target-branch`; `auto`, empty, `(not set)` and a missing key all mean
#   "not set".
#
# Output: plain text, or one JSON document with --json. Exit 0 = ok, 2 = failed (one line on stderr).

from __future__ import annotations

import argparse
import http.client
import json
import os
import re
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import actlib

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

API_URL_ENV = "ACT_FORGE_API_URL"
KIND_ENV = "ACT_FORGE_KIND"
TIMEOUT_SECONDS = 15
TOKEN_NAMES = {"github": ("GITHUB_TOKEN", "GH_TOKEN"), "gitlab": ("GITLAB_TOKEN",)}
ALL_TOKEN_NAMES = frozenset(name for names in TOKEN_NAMES.values() for name in names)
KINDS = ("github", "gitlab")
TARGET_CANDIDATES = ("development", "develop", "main")
BRANCH_SLUG_MAX = 40
USER_AGENT = "agentic-coding-template-forge"
FORGE_HOST_KEY = "forge-host"
KNOWN_HOSTS = frozenset(("github.com", "api.github.com", "gitlab.com"))  # the token may always go here (https)
LOOPBACK_HOSTS = frozenset(("127.0.0.1", "::1", "localhost"))  # the only hosts a token may reach over http
MAX_PAGES = 50  # a stop for paging, so a server that never ends its pages cannot keep the script busy
PER_PAGE_MAX = 100  # both hosts cap a page at 100 items
_HOST_RE = re.compile(r"[A-Za-z0-9.-]+|[0-9A-Fa-f:.]+")  # a DNS name or IPv4 address, or an IPv6 address (no brackets)
_TOKEN_RE = re.compile(r"[\x21-\x7e]+")  # one line of visible ASCII: the shape of every GitHub and GitLab token


class ForgeError(Exception):
    """A failure with a one-line message that is safe to print (never contains the token)."""


def config_setting(config: dict[str, str], key: str) -> str:
    """A config value, or "" when the key is missing, empty, `auto` or `(not set)` — all four mean
    "not set" for `forge` and `target-branch`."""
    value = config.get(key, "").strip().strip("`").strip()
    return "" if value.lower() in ("", "auto", "(not set)") else value


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class Remote:
    name: str
    host: str
    project_path: str
    web_base: str  # scheme://host[:port], the web address of the host


@dataclass
class Forge:
    remote: Remote
    kind: str
    kind_reason: str
    api_base: str
    token: str = field(default="", repr=False)
    token_source: str = ""  # "env GITHUB_TOKEN" / ".env GITLAB_TOKEN" / "" (none)
    trusted_hosts: tuple[str, ...] = ()  # hosts named in `forge-host`
    host_confirmed: bool = False  # the API host is one the token may go to (says nothing about http)
    token_block: str = ""  # "" = a token may be sent to the API base, else the one-line reason it may not


@dataclass
class Item:
    """An issue or a pull/merge request, normalized across both hosts."""
    number: int
    title: str
    state: str
    labels: list[str]
    author: str
    assignees: list[str]
    url: str
    body: str = ""
    source: str = ""
    target: str = ""
    is_pr: bool = False


@dataclass
class Response:
    """One HTTP answer, for any status."""
    status: int
    text: str
    headers: dict[str, str] = field(default_factory=dict)  # names in lower case


@dataclass
class WriteAction:
    method: str
    path: str
    payload: dict[str, Any]
    what: str  # e.g. "issue", "comment", "pull request"


# ---------------------------------------------------------------------------
# Remote and kind
# ---------------------------------------------------------------------------

_SCP_LIKE = re.compile(r"^(?:[^@/\s]+@)?(?P<host>[A-Za-z0-9.-]{2,}):(?P<path>[^/].*)$")


def parse_remote_url(url: str, name: str = "origin") -> Remote:
    """Split a remote URL (scp-like, ssh://, https://, with or without .git) into host and project
    path. Credentials embedded in the URL are dropped, the SSH port is ignored (it is not the web port).
    The host is a DNS name, an IPv4 or an IPv6 address (`_HOST_RE`): a host part with `@` or `\\` is
    refused, since urlsplit and the socket layer would read it as two different hosts."""
    text = url.strip()
    if "://" in text:
        parts = urllib.parse.urlsplit(text)
        host = parts.hostname or ""
        path = parts.path
        web_scheme = "http" if parts.scheme == "http" else "https"
        try:
            port = parts.port
        except ValueError:
            port = None
        keep_port = port if web_scheme in ("http", "https") and parts.scheme in ("http", "https") else None
    else:
        match = _SCP_LIKE.match(text)
        if not match:
            raise ForgeError(f"remote '{name}' is not a git host address (expected git@host:path or https://host/path; "
                             "a host is letters, digits, dots and hyphens)")
        host, path, web_scheme, keep_port = match.group("host"), match.group("path"), "https", None
    if host and not _HOST_RE.fullmatch(host):
        raise ForgeError(f"remote '{name}' has an unusable host name: only letters, digits, dots and hyphens, or an "
                         "IPv6 address")
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not host or path.count("/") < 1 or "" in path.split("/"):
        raise ForgeError(f"remote '{name}' has no group/project path (host '{host}')")
    if any(segment in (".", "..") or any(ch in segment for ch in "%?#\\") or segment != segment.strip()
           for segment in path.split("/")):
        raise ForgeError(f"remote '{name}' has an unusable project path (host '{host}'): no '.', '..', '%', '?', '#' "
                         "or backslash in a path segment")
    shown_host = f"[{host}]" if ":" in host else host  # an IPv6 address needs its brackets in a URL
    web_base = f"{web_scheme}://{shown_host}" + (f":{keep_port}" if keep_port else "")
    return Remote(name=name, host=host.lower(), project_path=path, web_base=web_base)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ForgeError(f"cannot run git in {root}: {exc}") from exc


def find_remote(root: Path, wanted: str) -> Remote:
    names = [n for n in _git(root, "remote").stdout.split() if n]
    if not names:
        raise ForgeError(f"no git remote in {root}")
    if wanted:
        if wanted not in names:
            raise ForgeError(f"no remote named '{wanted}' (have: {', '.join(names)})")
        name = wanted
    elif "origin" in names:
        name = "origin"
    elif len(names) == 1:
        name = names[0]
    else:
        raise ForgeError(f"several remotes and no 'origin' ({', '.join(names)}); pick one with --remote")
    result = _git(root, "remote", "get-url", name)
    if result.returncode != 0:
        raise ForgeError(f"cannot read the URL of remote '{name}'")
    return parse_remote_url(result.stdout.strip(), name)


def api_override() -> str:
    """ACT_FORGE_API_URL without a trailing slash, "" when unset. Anything that is not an http(s)
    address with a host, or that carries credentials, a query or a fragment, is a ForgeError — checked
    once at the start, so it never turns into a traceback deep inside a request (the value is not
    echoed: it may hold a secret)."""
    raw = os.environ.get(API_URL_ENV, "").strip().rstrip("/")
    if not raw:
        return ""
    try:
        parts = urllib.parse.urlsplit(raw)
        host, _port = parts.hostname, parts.port
    except ValueError:
        host = None
    if (host is None or parts.scheme not in ("http", "https") or "@" in parts.netloc
            or parts.query or parts.fragment or not _HOST_RE.fullmatch(host)):
        raise ForgeError(f"{API_URL_ENV} must be an http(s) address with a host (letters, digits, dots and hyphens, or "
                         "an IPv6 address) and without credentials, query or fragment, e.g. https://git.example.org/api/v4")
    return raw


def _one_line(text: object) -> str:
    return " ".join(str(text).split())


def fetch(url: str, headers: Optional[dict[str, str]] = None, method: str = "GET",
          data: Optional[bytes] = None, secret: str = "") -> Response:
    """One request, no redirects. Returns the Response for any HTTP status; every failure to get an
    answer (unreachable, timeout, an answer that is no HTTP, a bad address) is a ForgeError with one
    line that never contains `secret`."""

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args: Any, **kwargs: Any) -> None:  # noqa: ARG002
            return None

    def send() -> Response:
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("User-Agent", USER_AGENT)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.build_opener(_NoRedirect).open(request, timeout=TIMEOUT_SECONDS) as response:
                return Response(response.status, response.read().decode("utf-8", errors="replace"),
                                {k.lower(): v for k, v in response.headers.items()})
        except urllib.error.HTTPError as exc:  # the server answered: any status is an answer
            try:
                return Response(exc.code, exc.read().decode("utf-8", errors="replace"),
                                {k.lower(): v for k, v in exc.headers.items()})
            finally:
                exc.close()

    try:
        return send()
    except ValueError as exc:
        # urllib refused the address or a header value; its text echoes that value (`Invalid header value
        # b'Bearer ...'`, escaped, so a scrub would miss it) — the text is not shown, the cause is named instead
        raise ForgeError(f"{method} {url} failed: the request could not be built (an invalid address or header "
                         "value)") from exc
    except (urllib.error.URLError, OSError, http.client.HTTPException) as exc:
        text = f"{method} {url} failed: cannot reach the server ({_one_line(getattr(exc, 'reason', exc))})"
        raise ForgeError(text.replace(secret, "***") if secret else text) from exc


def json_or_none(text: str) -> Any:
    try:
        return json.loads(text)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Which host may receive the token
# ---------------------------------------------------------------------------

def _host_of(text: str) -> str:
    """The lower-case host name of an address or of a bare `host[:port]` entry, "" if there is none."""
    try:
        return (urllib.parse.urlsplit(text if "://" in text else f"//{text}").hostname or "").lower()
    except ValueError:
        return ""


def forge_hosts(config: dict[str, str]) -> tuple[str, ...]:
    """The hosts named in the config key `forge-host` (a name or a comma-separated list; `auto`, empty
    and `(not set)` mean none)."""
    raw = config_setting(config, FORGE_HOST_KEY)
    return tuple(host for host in (_host_of(part.strip().strip("`").strip()) for part in raw.split(",")) if host)


def host_is_confirmed(url: str, trusted: tuple[str, ...]) -> bool:
    """The host of `url` is github.com/gitlab.com, named in `forge-host`, or the host of ACT_FORGE_API_URL."""
    host = _host_of(url)
    if not host:
        return False
    override = _host_of(os.environ.get(API_URL_ENV, "").strip())
    return host in KNOWN_HOSTS or host in trusted or (bool(override) and host == override)


def token_block_reason(url: str, trusted: tuple[str, ...]) -> str:
    """"" when a token may be sent to `url`, else one line saying why not — the host is not confirmed
    (then `forge-host` releases it), or the address is http and not loopback (then only https helps)."""
    host = _host_of(url)
    if not host_is_confirmed(url, trusted):
        return (f"{host or 'the host'} is not a confirmed git host, so no token is sent to it: confirm it and set "
                f"`{FORGE_HOST_KEY}` in docs/ai/config.md § Git hosting")
    if urllib.parse.urlsplit(url).scheme != "https" and host not in LOOPBACK_HOSTS:
        return f"no token is sent over http to {host}: use an https address for the remote"
    return ""


def auth_headers(fg: Forge, url: str) -> dict[str, str]:
    """The request headers for `url`: Accept, plus the token in the header of the hoster — only when
    the token may go to that host (`token_block_reason`)."""
    headers = {"Accept": "application/vnd.github+json" if fg.kind == "github" else "application/json"}
    if fg.token and not token_block_reason(url, fg.trusted_hosts):
        if fg.kind == "github":
            headers["Authorization"] = f"Bearer {fg.token}"
        else:
            headers["PRIVATE-TOKEN"] = fg.token
    return headers


def require_token_allowed(fg: Forge, what: str) -> None:
    """Stops with one line when a token is present but may not be sent to this host (the request `what`
    is not made). Without a token nothing is held back, so nothing is raised."""
    if fg.token and fg.token_block:
        raise ForgeError(f"{what} not sent: {fg.token_block}")


def require_token(fg: Forge, what: str) -> None:
    """For a request that is meaningless without the token (whoami, issues --mine, every write): stops
    with one line, before any request, when there is no token (naming the variable to set) or when it may
    not be sent to this host (`require_token_allowed`)."""
    if not fg.token:
        names = " or ".join(TOKEN_NAMES[fg.kind])
        raise ForgeError(f"{what} not sent: no access token — set {names} in the environment or in .env")
    require_token_allowed(fg, what)


def detect_kind(remote: Remote, config: dict[str, str]) -> tuple[str, str]:
    """Return (kind, reason): host name first, then the `forge` config key, then a read-only probe."""
    forced = os.environ.get(KIND_ENV, "").strip().lower()
    if forced:
        if forced not in KINDS:
            raise ForgeError(f"{KIND_ENV}={forced!r} is not one of {', '.join(KINDS)}")
        return forced, f"{KIND_ENV}"
    if remote.host == "github.com":
        return "github", "host github.com"
    if remote.host == "gitlab.com":
        return "gitlab", "host gitlab.com"
    configured = config_setting(config, "forge").lower()
    if configured:
        if configured not in KINDS:
            raise ForgeError(f"docs/ai/config.md: forge = {configured!r} is not one of {', '.join(KINDS)}")
        return configured, "config key forge"
    override = api_override()
    gitlab_url = f"{override or remote.web_base + '/api/v4'}/version"
    github_url = f"{override or remote.web_base + '/api/v3'}/meta"
    try:
        # Both probes go out without a token, whatever host answers: this is the one request that
        # reaches a host nobody has confirmed yet.
        answer = fetch(gitlab_url)
        data = json_or_none(answer.text)
        # GitLab answers /version with 200, or with a JSON 401 when the instance wants a login.
        if isinstance(data, dict) and ((answer.status == 200 and "version" in data) or answer.status == 401):
            return "gitlab", f"probe {gitlab_url} answered like GitLab (HTTP {answer.status})"
        answer = fetch(github_url)
        if answer.status == 200 and isinstance(json_or_none(answer.text), dict):
            return "github", f"probe {github_url} answered like GitHub Enterprise"
    except ForgeError as exc:
        raise ForgeError(f"cannot tell the hoster of {remote.host}: {exc}; set `forge` (github|gitlab) in docs/ai/config.md") from exc
    raise ForgeError(f"cannot tell the hoster of {remote.host}: neither the GitLab nor the GitHub probe answered; "
                     "set `forge` (github|gitlab) in docs/ai/config.md")


def api_base_for(kind: str, remote: Remote) -> str:
    override = api_override()
    if override:
        return override
    if kind == "github":
        if remote.host == "github.com":
            return "https://api.github.com"
        return f"{remote.web_base}/api/v3"
    return f"{remote.web_base}/api/v4"


# ---------------------------------------------------------------------------
# Access
# ---------------------------------------------------------------------------

def read_dotenv(path: Path) -> dict[str, str]:
    """Only the names in ALL_TOKEN_NAMES are ever taken from the file. A quoted value ends at its closing
    quote (a comment after it is dropped); an unquoted one ends before ` #`."""
    found: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except (OSError, UnicodeDecodeError):
        return found
    for line in lines:
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text.startswith("export "):
            text = text[7:].lstrip()
        key, sep, value = text.partition("=")
        key = key.strip()
        if not sep or key not in ALL_TOKEN_NAMES:
            continue
        value = value.strip()
        if value[:1] in ("'", '"'):
            end = value.find(value[0], 1)
            if end > 0:  # closing quote found: everything after it (a comment) is dropped
                value = value[1:end]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        if value:
            found[key] = value
    return found


def usable_token(value: str, source: str) -> str:
    """`value` when it has the shape of a token — one line of visible ASCII (`_TOKEN_RE`) — else a ForgeError
    that names only `source` ("env GITHUB_TOKEN"). A space, tab, line break, control or non-ASCII character
    means the value was set wrongly (a file with a second line, a pasted line ending); sent as a header it
    would either go out mangled or make http.client echo it in a ValueError, escaped past any scrub."""
    if not _TOKEN_RE.fullmatch(value):
        raise ForgeError(f"{source} is not usable as a token: a token is one line of visible ASCII characters, this "
                         "value holds a space, tab, line break, control or non-ASCII character (a second line in the "
                         "file it was set from?) — it was not used")
    return value


def find_access(kind: str, root: Path) -> tuple[str, str, list[str]]:
    """Return (token, source, notes). `source` names the variable, never the value. A value that is not
    one line of visible ASCII is a ForgeError naming the source (`usable_token`), not a token."""
    names = TOKEN_NAMES[kind]
    notes: list[str] = []
    dotenv = root / ".env"
    if dotenv.is_file():
        ignored = _git(root, "check-ignore", "-q", ".env").returncode
        if ignored == 1:
            notes.append(".env exists in the project root but is not ignored by git — add it to .gitignore before it holds a token")
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return usable_token(value, f"env {name}"), f"env {name}", notes
    if dotenv.is_file():
        values = read_dotenv(dotenv)
        for name in names:
            if name in values:
                return usable_token(values[name], f".env {name}"), f".env {name}", notes
    return "", "", notes


def assemble_forge(root: Path, remote: Remote, config: dict[str, str], kind: str, reason: str) -> tuple[Forge, list[str]]:
    """The Forge for a remote whose kind is known: API base, token (if any), and whether the token may go
    to that API base. Returns (forge, notes from the access lookup)."""
    token, source, notes = find_access(kind, root)
    api_base = api_base_for(kind, remote)
    trusted = forge_hosts(config)
    forge = Forge(remote, kind, reason, api_base, token, source, trusted,
                  host_confirmed=host_is_confirmed(api_base, trusted),
                  token_block=token_block_reason(api_base, trusted))  # act:allow-secret (a call, not a value)
    return forge, notes


def build_forge(root: Path, remote_name: str) -> tuple[Forge, list[str]]:
    remote = find_remote(root, remote_name)
    config = actlib.read_config(root)
    kind, reason = detect_kind(remote, config)
    return assemble_forge(root, remote, config, kind, reason)


# ---------------------------------------------------------------------------
# API calls
# ---------------------------------------------------------------------------

def _service_message(data: Any, text: str, secret: str = "") -> str:
    """The service's own words for a failed request, one line of at most 200 characters; `secret` is
    scrubbed before the cut, so no prefix of it survives at the boundary."""
    message: Any = None
    if isinstance(data, dict):
        message = data.get("message") or data.get("error") or data.get("error_description")
    if message is None:
        message = text.strip()
    if not isinstance(message, str):
        message = json.dumps(message, ensure_ascii=False)
    message = " ".join(message.split())
    if secret:
        message = message.replace(secret, "***")
    return message[:200] or "(no message)"


def call(forge: Forge, method: str, path: str, query: Optional[dict[str, Any]] = None,
         payload: Optional[dict[str, Any]] = None) -> Any:
    """One API call; returns the decoded JSON. Any failure becomes a ForgeError with one line."""
    url = forge.api_base + path
    if method != "GET" or path == "/user":  # a login or a write: the token or nothing
        require_token_allowed(forge, f"{method} {path}")
    if query:
        url += "?" + urllib.parse.urlencode({k: v for k, v in query.items() if v not in (None, "")})
    headers = auth_headers(forge, url)
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    answer = fetch(url, headers, method, data, forge.token)
    parsed = json_or_none(answer.text)
    if not 200 <= answer.status < 300:
        message = _service_message(parsed, answer.text, forge.token)
        raise ForgeError(f"{method} {url} failed: HTTP {answer.status}: {message}")
    if parsed is None and answer.text.strip():
        raise ForgeError(f"{method} {url} failed: HTTP {answer.status} but the answer is not JSON")
    return parsed


def _project_ref(forge: Forge) -> str:
    """The project as it appears in API paths."""
    path = forge.remote.project_path
    if forge.kind == "github":
        return f"/repos/{urllib.parse.quote(path, safe='/')}"
    return f"/projects/{urllib.parse.quote(path, safe='')}"


def _names(values: Any, key: str) -> list[str]:
    out: list[str] = []
    for value in values or []:
        if isinstance(value, dict):
            name = value.get(key)
        else:
            name = value
        if isinstance(name, str):
            out.append(name)
    return out


def _shape_error(what: str, key: str, value: Any, expected: str) -> ForgeError:
    """An answer field of the wrong shape: the type is named, never the value (it is the service's data)."""
    return ForgeError(f"unexpected answer for {what}: '{key}' is {_json_type(value)}, {expected} was expected")


def _number(raw: dict[str, Any], key: str, what: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise _shape_error(what, key, value, "a number")
    return value


def _object(raw: dict[str, Any], key: str, what: str) -> dict[str, Any]:
    """The nested object at `key`; missing or null (a deleted user) is {}, anything else is a ForgeError."""
    value = raw.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise _shape_error(what, key, value, "an object")
    return value


def _list(raw: dict[str, Any], key: str, what: str) -> list[Any]:
    value = raw.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise _shape_error(what, key, value, "a list")
    return value


def _to_item(forge: Forge, raw: dict[str, Any], is_pr: bool, what: str) -> Item:
    """One issue or pull/merge request from the host's answer. A field of an unexpected shape (a number
    that is no number, a user that is a string, labels that are no list) is a ForgeError naming `what`,
    not a traceback."""
    if forge.kind == "github":
        state = str(raw.get("state", ""))
        if is_pr and raw.get("merged_at"):
            state = "merged"
        return Item(
            number=_number(raw, "number", what), title=str(raw.get("title", "")), state=state,
            labels=_names(_list(raw, "labels", what), "name"),
            author=str(_object(raw, "user", what).get("login") or ""),
            assignees=_names(_list(raw, "assignees", what), "login"), url=str(raw.get("html_url", "")),
            body=str(raw.get("body") or ""),
            source=str(_object(raw, "head", what).get("ref") or ""),
            target=str(_object(raw, "base", what).get("ref") or ""), is_pr=is_pr)
    state = str(raw.get("state", ""))
    state = "open" if state == "opened" else state
    return Item(
        number=_number(raw, "iid", what), title=str(raw.get("title", "")), state=state,
        labels=_names(_list(raw, "labels", what), "name"),
        author=str(_object(raw, "author", what).get("username") or ""),
        assignees=_names(_list(raw, "assignees", what), "username"), url=str(raw.get("web_url", "")),
        body=str(raw.get("description") or ""), source=str(raw.get("source_branch") or ""),
        target=str(raw.get("target_branch") or ""), is_pr=is_pr)


def _json_type(data: Any) -> str:
    if data is None:
        return "null"
    for kind, name in ((bool, "a boolean"), (int, "a number"), (float, "a number"), (str, "a string"),
                       (list, "a list"), (dict, "an object")):
        if isinstance(data, kind):
            return name
    return type(data).__name__


def require_list(data: Any, what: str) -> list[dict[str, Any]]:
    if not isinstance(data, list):
        raise ForgeError(f"unexpected answer for {what}: a list was expected, got {_json_type(data)}")
    return [item for item in data if isinstance(item, dict)]


def require_dict(data: Any, what: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ForgeError(f"unexpected answer for {what}: an object was expected, got {_json_type(data)}")
    return data


def _login(forge: Forge) -> str:
    """The login name of the token's user, for the --mine filter; an answer without one stops here, so
    the filter never runs on "None"."""
    data = require_dict(call(forge, "GET", "/user"), "the current user")
    login = data.get("login") if forge.kind == "github" else data.get("username")
    if not isinstance(login, str) or not login.strip():
        raise ForgeError("GET /user answered without a login name, so --mine has nothing to filter on")
    return login.strip()


def _collect(forge: Forge, path: str, query: dict[str, Any], per_page: int, want: int, what: str,
             keep: Callable[[dict[str, Any]], bool] = lambda row: True, max_pages: int = MAX_PAGES) -> list[dict[str, Any]]:
    """Up to `want` rows that pass `keep`, loading page after page until there are enough or the pages
    end (a page shorter than `per_page`), at most `max_pages` pages."""
    kept: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        page_query = {**query, "per_page": per_page, **({"page": page} if page > 1 else {})}
        raw = call(forge, "GET", path, page_query)
        kept += [row for row in require_list(raw, what) if keep(row)]
        if len(kept) >= want or len(raw) < per_page:
            break
    return kept[:want]


def list_issues(forge: Forge, state: str, mine: bool, labels: list[str], limit: int) -> list[Item]:
    path = f"{_project_ref(forge)}/issues"
    if mine:  # "assigned to me" is meaningless without the token: on GitHub the login lookup would fail,
        require_token(forge, "issues --mine")  # on GitLab the request would go out and answer as if signed in
    if forge.kind == "github":
        # /issues also returns pull requests; they are dropped, so a page can hold fewer issues than its
        # size. Full pages of PER_PAGE_MAX, and only the pages `limit` needs plus one: a project whose rows
        # are all pull requests then costs two requests, not MAX_PAGES (`integrations check` reads with a
        # limit of 1, often without a token, against a rate limit of 60 requests an hour).
        query: dict[str, Any] = {"state": state, "labels": ",".join(labels)}
        if mine:
            query["assignee"] = _login(forge)
        pages = -(-limit // PER_PAGE_MAX) + 1
        rows = _collect(forge, path, query, PER_PAGE_MAX, limit, "issues", lambda row: "pull_request" not in row, pages)
        return [_to_item(forge, r, False, "issues") for r in rows]
    query = {"state": "opened" if state == "open" else state, "labels": ",".join(labels)}
    if mine:
        query["scope"] = "assigned_to_me"
    rows = _collect(forge, path, query, min(PER_PAGE_MAX, limit), limit, "issues")
    return [_to_item(forge, r, False, "issues") for r in rows]


def get_issue(forge: Forge, number: int) -> Item:
    raw = require_dict(call(forge, "GET", f"{_project_ref(forge)}/issues/{number}"), f"issue {number}")
    if forge.kind == "github" and "pull_request" in raw:
        raise ForgeError(f"#{number} is a pull request, not an issue (use `prs`)")
    return _to_item(forge, raw, False, f"issue {number}")


def list_prs(forge: Forge, state: str, limit: int) -> list[Item]:
    per_page = min(PER_PAGE_MAX, limit)
    if forge.kind == "github":
        what = "pull requests"
        rows = _collect(forge, f"{_project_ref(forge)}/pulls", {"state": state}, per_page, limit, what)
    else:
        what = "merge requests"
        query = {"state": "opened" if state == "open" else state}
        rows = _collect(forge, f"{_project_ref(forge)}/merge_requests", query, per_page, limit, what)
    return [_to_item(forge, r, True, what) for r in rows]


@dataclass
class Project:
    name: str
    default_branch: str
    visibility: str
    web_url: str


def get_project(forge: Forge) -> Project:
    raw = require_dict(call(forge, "GET", _project_ref(forge)), "the project")
    if forge.kind == "github":
        visibility = str(raw.get("visibility") or ("private" if raw.get("private") else "public"))
        return Project(str(raw.get("full_name", "")), str(raw.get("default_branch") or ""),
                       visibility, str(raw.get("html_url", "")))
    return Project(str(raw.get("path_with_namespace", "")), str(raw.get("default_branch") or ""),
                   str(raw.get("visibility", "")), str(raw.get("web_url", "")))


# ---------------------------------------------------------------------------
# Branch helpers
# ---------------------------------------------------------------------------

_UMLAUTS = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "Ä": "ae", "Ö": "oe", "Ü": "ue"}


def short_title(title: str, limit: int = BRANCH_SLUG_MAX) -> str:
    """ASCII, lowercase, hyphens, at most `limit` characters, cut at a hyphen where possible."""
    text = "".join(_UMLAUTS.get(ch, ch) for ch in title)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    if len(text) > limit:
        cut = text[:limit]
        text = cut.rsplit("-", 1)[0] if "-" in cut and text[limit] != "-" else cut
        text = text.strip("-")
    return text or "issue"


def is_bug(labels: list[str]) -> bool:
    for label in labels:
        lowered = label.lower()
        if lowered == "bug" or lowered.endswith(("::bug", "/bug")):
            return True
    return False


def branch_name(item: Item) -> str:
    prefix = "bugfix" if is_bug(item.labels) else "feature"
    return f"{prefix}/{item.number}-{short_title(item.title)}"


def resolve_target_branch(root: Path, remote_name: str,
                          forge_builder: Callable[[], tuple[Forge, list[str]]]) -> tuple[str, str]:
    """(branch, source) — config key, remote default branch (API, then origin/HEAD), first candidate."""
    configured = config_setting(actlib.read_config(root), "target-branch")
    if configured:
        return configured, "config target-branch"
    remote: Optional[Remote] = None
    try:
        forge, _ = forge_builder()
        remote = forge.remote
        default = get_project(forge).default_branch
        if default:
            return default, "remote default branch (API)"
    except ForgeError:
        pass
    name = remote.name if remote else (remote_name or "origin")
    head = _git(root, "symbolic-ref", "--quiet", f"refs/remotes/{name}/HEAD")
    prefix = f"refs/remotes/{name}/"
    if head.returncode == 0 and head.stdout.strip().startswith(prefix) and head.stdout.strip()[len(prefix):]:
        return head.stdout.strip()[len(prefix):], f"{name}/HEAD"  # `release/x` stays `release/x`
    for candidate in TARGET_CANDIDATES:
        for ref in (f"refs/heads/{candidate}", f"refs/remotes/{name}/{candidate}"):
            if _git(root, "show-ref", "--verify", "--quiet", ref).returncode == 0:
                return candidate, f"first existing of {', '.join(TARGET_CANDIDATES)}"
    raise ForgeError("no target branch: `target-branch` is not set in docs/ai/config.md, the remote's default "
                     f"branch is unknown and none of {', '.join(TARGET_CANDIDATES)} exists")


# ---------------------------------------------------------------------------
# Write actions
# ---------------------------------------------------------------------------

def _read_body(path: str) -> str:
    try:
        if path == "-":
            return sys.stdin.read()
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise ForgeError(f"cannot read body file {path}: {exc}") from exc


def _issue_path(forge: Forge, number: int) -> str:
    return f"{_project_ref(forge)}/issues/{number}"


def plan_create_issue(forge: Forge, title: str, body: str, labels: list[str]) -> WriteAction:
    if forge.kind == "github":
        payload: dict[str, Any] = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
    else:
        payload = {"title": title, "description": body}
        if labels:
            payload["labels"] = ",".join(labels)
    return WriteAction("POST", f"{_project_ref(forge)}/issues", payload, "issue")


def plan_comment(forge: Forge, number: int, body: str) -> WriteAction:
    suffix = "comments" if forge.kind == "github" else "notes"
    return WriteAction("POST", f"{_issue_path(forge, number)}/{suffix}", {"body": body}, "comment")


def plan_close_issue(forge: Forge, number: int) -> WriteAction:
    if forge.kind == "github":
        return WriteAction("PATCH", _issue_path(forge, number), {"state": "closed"}, "issue")
    return WriteAction("PUT", _issue_path(forge, number), {"state_event": "close"}, "issue")


def plan_create_pr(forge: Forge, source: str, target: str, title: str, body: str, draft: bool) -> WriteAction:
    if forge.kind == "github":
        payload: dict[str, Any] = {"title": title, "head": source, "base": target, "body": body, "draft": draft}
        return WriteAction("POST", f"{_project_ref(forge)}/pulls", payload, "pull request")
    if draft and not title.lower().startswith(("draft:", "[draft]")):
        title = f"Draft: {title}"
    payload = {"title": title, "source_branch": source, "target_branch": target, "description": body}
    return WriteAction("POST", f"{_project_ref(forge)}/merge_requests", payload, "merge request")


def plan_close_pr(forge: Forge, number: int) -> WriteAction:
    if forge.kind == "github":
        return WriteAction("PATCH", f"{_project_ref(forge)}/pulls/{number}", {"state": "closed"}, "pull request")
    return WriteAction("PUT", f"{_project_ref(forge)}/merge_requests/{number}", {"state_event": "close"},
                       "merge request")


def summarize_payload(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for key, value in payload.items():
        if isinstance(value, str) and (len(value) > 60 or "\n" in value) and key not in ("title",):
            parts.append(f"{key}=<{len(value)} chars>")
        elif isinstance(value, str):
            parts.append(f"{key}={value[:80]!r}")
        else:
            parts.append(f"{key}={json.dumps(value, ensure_ascii=False)}")
    return " ".join(parts)


def long_texts(payload: dict[str, Any]) -> list[tuple[str, str]]:
    """The payload fields the summary only sizes or cuts: what `--show-body` prints in full."""
    return [(key, value) for key, value in payload.items()
            if isinstance(value, str) and (len(value) > 60 or "\n" in value)]


def result_url(forge: Forge, action: WriteAction, answer: Any, number: Optional[int]) -> str:
    data = answer if isinstance(answer, dict) else {}
    url = data.get("html_url") or data.get("web_url")
    if url:
        return str(url)
    if forge.kind == "gitlab" and action.what == "comment" and number is not None:
        return f"{forge.remote.web_base}/{forge.remote.project_path}/-/issues/{number}#note_{data.get('id', '')}"
    return ""


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def item_line(item: Item) -> str:
    labels = f"  [{', '.join(item.labels)}]" if item.labels else ""
    who = f"  @{item.author}" if item.author else ""
    branches = f"  {item.source} -> {item.target}" if item.is_pr and item.source else ""
    return f"#{item.number}  {item.state}  {item.title}{labels}{who}{branches}"


def item_detail(item: Item) -> str:
    lines = [f"#{item.number}  {item.title}", f"state: {item.state}",
             f"labels: {', '.join(item.labels) or '-'}", f"author: {item.author or '-'}",
             f"assignees: {', '.join(item.assignees) or '-'}", f"url: {item.url}", "", item.body.strip()]
    return "\n".join(lines).rstrip()


class Output:
    def __init__(self, as_json: bool) -> None:
        self.as_json = as_json

    def emit(self, data: Any, text: str) -> None:
        if self.as_json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print(text)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_detect(forge: Forge, out: Output) -> None:
    access = forge.token_source or "none"
    data = {"host": forge.remote.host, "kind": forge.kind, "kind_reason": forge.kind_reason,
            "project_path": forge.remote.project_path, "api_base": forge.api_base,
            "access": access, "remote": forge.remote.name,
            "host_confirmed": forge.host_confirmed, "token_note": forge.token_block}
    if forge.token_block:
        token_line = f"token: {'not sent' if forge.token else 'would not be sent'} - {forge.token_block}"
    else:
        token_line = "token: sent" if forge.token else "token: none"
    out.emit(data, "\n".join([
        f"remote: {forge.remote.name}", f"host: {forge.remote.host}",
        f"kind: {forge.kind} ({forge.kind_reason})", f"project: {forge.remote.project_path}",
        f"api: {forge.api_base}", f"access: {access}",
        f"host confirmed: {'yes' if forge.host_confirmed else 'no'}", token_line]))


def cmd_whoami(forge: Forge, out: Output) -> None:
    require_token(forge, "GET /user")  # without a token, or with one this host may not get, stop before any request
    raw = require_dict(call(forge, "GET", "/user"), "the current user")
    login = str(raw.get("login") or raw.get("username") or "")
    name = str(raw.get("name") or "")
    url = str(raw.get("html_url") or raw.get("web_url") or "")
    out.emit({"login": login, "name": name, "url": url}, f"{login}  {name}  {url}".rstrip())


def cmd_project(forge: Forge, out: Output) -> None:
    project = get_project(forge)
    out.emit(asdict(project), "\n".join([
        f"name: {project.name}", f"default branch: {project.default_branch or '-'}",
        f"visibility: {project.visibility}", f"url: {project.web_url}"]))


def cmd_default_branch(forge: Forge, out: Output) -> None:
    branch = get_project(forge).default_branch
    if not branch:
        raise ForgeError(f"{forge.remote.project_path} reports no default branch (empty repository?)")
    out.emit({"default_branch": branch}, branch)


def cmd_issues(forge: Forge, out: Output, args: argparse.Namespace) -> None:
    items = list_issues(forge, args.state, args.mine, args.label or [], args.limit)
    out.emit([asdict(i) for i in items], "\n".join(item_line(i) for i in items) or "(no issues)")


def cmd_prs(forge: Forge, out: Output, args: argparse.Namespace) -> None:
    items = list_prs(forge, args.state, args.limit)
    label = "pull requests" if forge.kind == "github" else "merge requests"
    out.emit([asdict(i) for i in items], "\n".join(item_line(i) for i in items) or f"(no {label})")


def run_write(forge: Forge, out: Output, action: WriteAction, apply: bool, number: Optional[int] = None,
              show_body: bool = False) -> None:
    url = forge.api_base + action.path
    summary = summarize_payload(action.payload)
    if not apply:
        access = forge.token_source or "none (a real run needs a token)"
        if forge.token and forge.token_block:
            access += f" (not sent: {forge.token_block})"
        lines = ["preview only, nothing is written (add --apply to run it)"]
        if forge.kind_reason.startswith("probe"):
            lines.append("the hoster probe of this unknown host did send read-only GET requests, without a token")
        lines += [f"{action.method} {url}", f"payload: {summary}", f"access: {access}"]
        data: dict[str, Any] = {"applied": False, "method": action.method, "url": url, "payload": summary, "access": access}
        if show_body:
            data["payload_full"] = action.payload
            for key, value in long_texts(action.payload):
                lines += [f"--- {key} ---", value.rstrip("\n"), f"--- end of {key} ---"]
        out.emit(data, "\n".join(lines))
        return
    require_token(forge, f"{action.method} {url}")  # no token, or one this host may not get: stop before any request
    answer = call(forge, action.method, action.path, None, action.payload)
    result = result_url(forge, action, answer, number)
    out.emit({"applied": True, "method": action.method, "url": result}, f"done: {result or url}")


def dispatch(args: argparse.Namespace, root: Path) -> None:
    out = Output(args.json)
    api_override()  # a bad ACT_FORGE_API_URL stops here, before anything is looked up or sent
    if args.command == "target-branch":
        builder = lambda: build_forge(root, args.remote)  # noqa: E731
        branch, source = resolve_target_branch(root, args.remote, builder)
        out.emit({"target_branch": branch, "source": source}, f"{branch}  (source: {source})")
        return
    forge, notes = build_forge(root, args.remote)
    command = args.command
    if forge.token and forge.token_block and (command in ("project", "default-branch", "issue", "prs", "branch-name")
                                              or (command == "issues" and not args.mine)):
        # this read runs without the token: say so, or a 401/404 on a private project looks unexplained
        notes.append(f"the access token ({forge.token_source}) is not sent: {forge.token_block}")
    for note in notes:
        print(f"note: {note}", file=sys.stderr)
    if command == "detect":
        cmd_detect(forge, out)
    elif command == "whoami":
        cmd_whoami(forge, out)
    elif command == "project":
        cmd_project(forge, out)
    elif command == "default-branch":
        cmd_default_branch(forge, out)
    elif command == "issues":
        cmd_issues(forge, out, args)
    elif command == "issue":
        item = get_issue(forge, args.number)
        out.emit(asdict(item), item_detail(item))
    elif command == "prs":
        cmd_prs(forge, out, args)
    elif command == "branch-name":
        name = branch_name(get_issue(forge, args.number))
        out.emit({"branch": name}, name)
    elif command == "create-issue":
        action = plan_create_issue(forge, args.title, _read_body(args.body_file), args.label or [])
        run_write(forge, out, action, args.apply, show_body=args.show_body)
    elif command == "comment":
        run_write(forge, out, plan_comment(forge, args.number, _read_body(args.body_file)), args.apply, args.number,
                  args.show_body)
    elif command == "close-issue":
        if args.apply and forge.kind == "github" and forge.token:
            # GitHub's issue endpoints also close a pull request: look first, and refuse one (the
            # preview stays free of requests, so it does not look)
            require_token_allowed(forge, "PATCH issue")
            get_issue(forge, args.number)
        run_write(forge, out, plan_close_issue(forge, args.number), args.apply)
    elif command == "create-pr":
        action = plan_create_pr(forge, args.source, args.target, args.title, _read_body(args.body_file), args.draft)
        run_write(forge, out, action, args.apply, show_body=args.show_body)
    elif command == "close-pr":
        run_write(forge, out, plan_close_pr(forge, args.number), args.apply)


def positive(text: str) -> int:
    try:
        value = int(text.lstrip("#"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{text!r} is not a number") from exc
    if value < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="REST client for GitHub and GitLab issues and pull/merge requests (stdlib only). "
                    "Writes only preview unless --apply is given. The token comes from the environment or .env, "
                    "never from the command line.")
    parser.add_argument("--root", help="project root (default: found from the current directory)")
    parser.add_argument("--remote", default="", help="git remote to use (default: origin, else the only one)")
    parser.add_argument("--json", action="store_true", help="print one JSON document instead of text")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    for name, text in (("detect", "show host, kind, project, API base, where the access comes from and whether "
                                  "the token may go to the host"),
                       ("whoami", "the user the token belongs to"),
                       ("project", "name, default branch, visibility and URL of the project"),
                       ("default-branch", "the project's default branch"),
                       ("target-branch", "branch for pull requests: config, remote default, or development/develop/main")):
        sub.add_parser(name, help=text)

    states = ("open", "closed", "all")
    issues = sub.add_parser("issues", help="list issues")
    issues.add_argument("--state", choices=states, default="open")
    issues.add_argument("--mine", action="store_true", help="only issues assigned to the token's user (needs the token)")
    issues.add_argument("--label", action="append", help="only with this label (repeatable)")
    issues.add_argument("--limit", type=positive, default=15)
    sub.add_parser("issue", help="show one issue").add_argument("number", type=positive)
    prs = sub.add_parser("prs", help="list pull/merge requests")
    prs.add_argument("--state", choices=states, default="open")
    prs.add_argument("--limit", type=positive, default=15)
    sub.add_parser("branch-name", help="branch name for an issue").add_argument("number", type=positive)

    create_issue = sub.add_parser("create-issue", help="create an issue (preview without --apply)")
    create_issue.add_argument("--title", required=True)
    create_issue.add_argument("--body-file", required=True, help="file with the text, '-' for stdin")
    create_issue.add_argument("--label", action="append")
    comment = sub.add_parser("comment", help="comment on an issue (preview without --apply)")
    comment.add_argument("number", type=positive)
    comment.add_argument("--body-file", required=True)
    close_issue = sub.add_parser("close-issue", help="close an issue (preview without --apply)")
    close_issue.add_argument("number", type=positive)
    create_pr = sub.add_parser("create-pr", help="create a pull/merge request (preview without --apply)")
    create_pr.add_argument("--source", required=True, help="branch with the changes")
    create_pr.add_argument("--target", required=True, help="branch to merge into")
    create_pr.add_argument("--title", required=True)
    create_pr.add_argument("--body-file", required=True)
    create_pr.add_argument("--draft", action="store_true")
    close_pr = sub.add_parser("close-pr", help="close a pull/merge request (preview without --apply)")
    close_pr.add_argument("number", type=positive)
    for name in ("create-issue", "comment", "close-issue", "create-pr", "close-pr"):
        sub.choices[name].add_argument("--apply", action="store_true", help="really send the request")
    for name in ("create-issue", "comment", "create-pr"):
        sub.choices[name].add_argument("--show-body", action="store_true",
                                       help="in the preview, print the full text instead of only its size")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        root = Path(args.root).resolve() if args.root else actlib.repo_root()
        dispatch(args, root)
    except (ForgeError, RuntimeError) as exc:
        print(f"forge: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
