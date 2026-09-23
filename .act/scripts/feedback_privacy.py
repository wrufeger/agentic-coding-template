#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: The privacy checks that decide whether a string may leave the project as part of a
#          feedback payload (.act/scripts/feedback.py) — patterns for secrets, mail addresses, IP
#          addresses, absolute paths, long hex values (keys/hashes) and foreign URLs, plus a
#          stricter check for a link that is meant to be shared on purpose. Split out from
#          feedback.py into its own module so the secret-scan check (`secret-scan` in
#          docs/ai/config.md § Checks, R-safe-no-secret-diff) can reuse the same patterns instead
#          of maintaining a second copy. Stdlib only, no project-specific knowledge — every
#          function here takes plain text and returns plain findings, never touches the
#          filesystem or a payload's schema. The one exception is `template_repo`, an optional
#          parameter check_text() accepts: it narrows (never widens) the github.com exception to
#          one specific repo path; the caller reads that address, this module never does.
#
# Usage: not run directly — imported, e.g. `import feedback_privacy` from a script in the same
#        directory (.act/scripts/).
#
# Output format: this module has no CLI of its own. check_text()/check_link() each return a list
#        of short English strings, one per finding; an empty list means "nothing objectionable".
#
# Hardening (2026-09-23, after a reviewer probe found several bypasses): every check below runs
# against the text AFTER _normalize() — Unicode NFKC (turns fullwidth "ｐａｓｓｗｏｒｄ" into plain
# ASCII) with every Unicode "format" character (category Cf: zero-width space/joiner and friends,
# used to split "pass​word" apart) stripped first. Every pattern that can appear in mixed
# case is case-insensitive (`re.I`). A handful of category-specific patterns were added rather
# than trying to out-guess every possible obfuscation — see the constants below for what each one
# targets.

from __future__ import annotations

import re
import unicodedata

# Rather one false positive too many: a rejected message costs a minute, a leaked credential
# cannot be called back. Every pattern here is intentionally broad.
#
# Boundaries are `(?<![A-Za-z0-9])`/`(?![A-Za-z0-9])`, NOT `\b`: in a regex, "_" is a WORD
# character, so `\bsecret\b` never matches inside "SECRET_TOKEN" or "DB_PASSWORD" — there is no
# `\b` transition between a letter and an underscore. Found in a reviewer probe (2026-09-23): a
# compound identifier like `SECRET_TOKEN`/`API_KEY`/`DB_PASSWORD`/`apiKey` pasted into free text
# slipped straight through. Treating "not a letter or digit" as the boundary instead fixes this
# for every plain alternative below (`api[_-]?key`/`private[_-]?key` already tolerated `_`/`-`
# themselves; the fix is only in how the boundary on either SIDE of the whole match is defined).
SECRET_WORDS = re.compile(
    r"(?i)(?<![A-Za-z0-9])(pass(word|wort)|secret|token|api[_-]?key|credential|zugangsdaten|"
    r"private[_-]?key|kennwort|pwd|bearer)(?![A-Za-z0-9])")
# Recognizable prefixes of real token formats (GitHub PAT/OAuth/refresh/user-to-server, GitLab PAT,
# Slack, AWS access key id, Anthropic/OpenAI-style secret keys) — specific enough that a plain
# prefix match is a safe, low-noise signal on its own. Same non-`\b` boundary as SECRET_WORDS, on
# the leading edge only (nothing anchors the trailing edge — the token body is greedy on purpose).
TOKEN_PREFIX = re.compile(
    r"(?i)(?<![A-Za-z0-9])(gh[pousr]_|github_pat_|glpat-|xox[abprs]-|AKIA|sk-ant-|sk-)[A-Za-z0-9_-]{8,}")
EMAIL = re.compile(r"(?i)[\w.+-]+(?:@|%40)[\w-]+\.[\w.]+")
IP_ADDRESS = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
# IPv6: does not try to match a whole address (compressed "::" forms are irregular to anchor) —
# finding a run of two or more "hexgroup:" segments plus a trailing group is signal enough.
IPV6 = re.compile(r"(?i)\b(?:[0-9a-f]{1,4}:){2,7}[0-9a-f]{1,4}\b")
WINDOWS_PATH = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")
# UNIX-style absolute paths: the classic top-level directories, PLUS a Git-Bash-style single-letter
# drive path (/c/Users/..., /d/dev/...) and a bare leading slash into /mnt, /root or /tmp.
UNIX_PATH = re.compile(r"(?<![\w.])/(?:home|Users|var|etc|opt|srv|mnt|root|tmp)/|(?<![\w.])/[a-z]/[\w.-]")
UNC_PATH = re.compile(r"\\\\[\w.-]")
HOME_PATH = re.compile(r"(?<![\w./-])~/")
URL = re.compile(r"(?i)https?://[^\s)]+")
# A bare "www."-host with no scheme is still a link, just one URL alone wouldn't catch.
WWW_HOST = re.compile(r"(?i)\bwww\.[a-z0-9-]+(?:\.[a-z0-9-]+)+(?:/\S*)?")
LONG_HEX = re.compile(r"(?i)\b[0-9a-f]{32,}\b")
# Loose but effective base64-shaped run (28+ chars from the base64 alphabet) — catches an
# accidentally pasted token/basic-auth string that isn't hex and doesn't contain "secret"/"token".
BASE64ISH = re.compile(r"\b[A-Za-z0-9+/]{28,}={0,2}\b")
# A git commit hash in a payload's own "template_base" field is exempt from LONG_HEX (a hash
# describes the template, not the project) but must still look like a real hash — feedback.py
# checks that field against this pattern instead of running it through check_text().
COMMIT_HASH = re.compile(r"(?i)[0-9a-f]{7,40}")

# Hosts that must never appear in a link meant to be shared: pointing at an intranet or a local
# instance is worthless to a stranger and reveals what is running there.
_PRIVATE_HOST = re.compile(
    r"(?i)^(?:localhost$|127\.|10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.|\[?::1)"
    r"|\.(?:local|internal|intern|lan|home|test|invalid|example)$")

_CF_CATEGORY = "Cf"


def _normalize(text: str) -> str:
    """NFKC-normalizes and drops every Unicode "format" character (zero-width space/joiner and
    the like) — both are cheap, common ways to break a pattern match apart without changing what a
    human reading the text sees."""
    text = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in text if unicodedata.category(ch) != _CF_CATEGORY)


def _split_host_path(url: str) -> tuple[str, str]:
    """(host, path) of an http(s) URL, lowercased host, no port/userinfo/query/fragment. Never
    raises — an unparsable fragment just yields an empty host."""
    rest = re.sub(r"(?i)^https?://", "", url)
    host_part, _, path = rest.partition("/")
    host_part = host_part.split("@")[-1]  # strip userinfo, if any
    host = host_part.split(":", 1)[0].lower()
    return host, "/" + path


def check_text(text: str, endpoint: str, *, template_repo: str | None = None) -> list[str]:
    """Findings for a free-text string, or [] if it looks unobjectionable. `endpoint` is the
    feedback endpoint's own URL — a link back to it is never flagged as "foreign". A link to
    exactly the host `github.com` is allowed too — narrowed to `template_repo` (an "owner/repo"
    path, as read from .act-lock.json § template by the caller) when one is given; without it, any
    github.com URL is allowed."""
    text = _normalize(text)
    findings: list[str] = []
    if SECRET_WORDS.search(text):
        findings.append("word from the credentials vocabulary")
    if TOKEN_PREFIX.search(text):
        findings.append("looks like a real access token")
    if EMAIL.search(text):
        findings.append("email address")
    if IP_ADDRESS.search(text):
        findings.append("IP address")
    elif IPV6.search(text):
        findings.append("IPv6 address")
    if WINDOWS_PATH.search(text) or UNIX_PATH.search(text) or UNC_PATH.search(text) or HOME_PATH.search(text):
        findings.append("absolute file path")
    if LONG_HEX.search(text):
        findings.append("long hex value (key? hash?)")
    elif BASE64ISH.search(text):
        findings.append("long base64-shaped value (key? token?)")
    for url in URL.findall(text):
        if url.startswith(endpoint):
            continue
        host, path = _split_host_path(url)
        if host == "github.com":
            if template_repo is None:
                continue
            repo = template_repo.strip("/").lower()
            trimmed = path.strip("/").lower()
            if trimmed == repo or trimmed.startswith(repo + "/"):
                continue
        findings.append(f"foreign URL ({url[:40]})")
    for host_match in WWW_HOST.findall(text):
        findings.append(f"link without scheme ({host_match[:40]})")
    return findings


def check_link(url: str) -> list[str]:
    """Findings for a link that is meant to be shared on purpose (--add --kind link), or [] if it
    may go out. Stricter than check_text(): a shared link must be a real, public http(s) address."""
    url = _normalize(url or "")
    findings: list[str] = []
    if not re.match(r"(?i)^https?://", url):
        return ["not an http(s) address"]
    host, _path = _split_host_path(url)
    rest = re.sub(r"(?i)^https?://", "", url)
    if "@" in rest.split("/", 1)[0]:
        findings.append("credentials in the address")
    if not host or _PRIVATE_HOST.search(host):
        findings.append(f"not publicly reachable ({host or url[:40]})")
    if len(url) > 300:
        findings.append("address longer than 300 characters")
    return findings
