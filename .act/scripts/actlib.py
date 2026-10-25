#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Shared library for every script under .act/scripts/ and .act/hooks/ — the single place that
#          knows how to resolve template vs. project files, and how to read/write the small state files
#          the template keeps outside of .act/ (lock file, per-checkout identity, generated-file cache,
#          project config). Stdlib only, no third-party dependencies.
#
# Usage: not run directly — imported, e.g. `import actlib` from a script in the same directory
#        (.act/scripts/ or .act/hooks/, both add their own directory to sys.path automatically).
#
# Output format: this module has no CLI output of its own; each function's return value is documented
#        at the function.
#
# Conventions used throughout:
#   - All paths are pathlib.Path, resolved relative to repo_root() unless documented otherwise.
#   - All file I/O is UTF-8, explicit.
#   - JSON files are written with indent=2, sorted only where noted, and a trailing newline.
#   - "Unknown fields" in a JSON state file (keys not part of the documented schema) are preserved on
#     write: a write merges onto the file's current content instead of replacing it outright.

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


# Pauses between the replace attempts below, in seconds: about 0.35 s in all, so a hook stays fast.
_REPLACE_RETRY_PAUSES = (0.05, 0.05, 0.1, 0.15)


def replace_file(src: "str | os.PathLike[str]", dst: "str | os.PathLike[str]") -> None:
    """os.replace(src, dst), with a few short retries on Windows only. There a virus scanner, an
    indexer or an IDE can hold the just-written file open for a moment, and the rename then fails
    with PermissionError although nothing is wrong. If the fifth attempt fails too, its PermissionError
    is raised unchanged (not wrapped). On every other platform this is a plain os.replace."""
    if sys.platform != "win32":
        os.replace(src, dst)
        return
    for pause in _REPLACE_RETRY_PAUSES:
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            time.sleep(pause)
    os.replace(src, dst)


# ---------------------------------------------------------------------------
# Root and path resolution
# ---------------------------------------------------------------------------

def repo_root(start: Optional[Path] = None) -> Path:
    """
    Find the project root by walking upward from `start` (default: the current working
    directory) until a directory containing a `.act` subdirectory is found.

    Works regardless of the working directory the caller was invoked from, as long as it is
    somewhere inside the project tree.

    Raises RuntimeError if no `.act` directory is found up to the filesystem root.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".act").is_dir():
            return candidate
    raise RuntimeError(
        "repo_root: no '.act' directory found in any parent of "
        f"'{current}' — is this run inside a template-managed project?"
    )


def resolve(path: str) -> Optional[tuple[Path, str]]:
    """
    Resolve a template-relative path (e.g. "rules/shared/00-core.md") against the single
    override rule used everywhere in this template — checklists, topic rules, scripts alike:

      1. docs/ai/local/<path>  — project override, wins if present
      2. .act/<path>           — template default

    Returns a (resolved_path, origin) tuple, where origin is "local" or "template", or None if
    neither location has the file.
    """
    root = repo_root()
    local_path = root / "docs" / "ai" / "local" / path
    if local_path.is_file():
        return local_path, "local"
    template_path = root / ".act" / path
    if template_path.is_file():
        return template_path, "template"
    return None


# ---------------------------------------------------------------------------
# JSON state files — shared read/write helpers
# ---------------------------------------------------------------------------

def _read_json(path: Path) -> Optional[dict]:
    """Read a JSON object from `path`. Returns None if the file is missing, unreadable, not valid
    UTF-8, or not a JSON object (never raises for those cases — callers fall back to a default).
    `ValueError` covers both `json.JSONDecodeError` and `UnicodeDecodeError` (both are subclasses
    of it) — a state file with a few corrupted bytes is treated the same as one that was never
    written yet, not as a reason to abort the caller (read_last_applied() previously left
    `UnicodeDecodeError` uncaught, which made update.py abort mid-run and left `.act/` already
    replaced). A leading BOM (a file saved by Windows PowerShell 5) is read as UTF-8 too, not
    treated as unreadable — otherwise write_lock() would rewrite the lock from an empty object and
    drop every key it held."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json_merged(path: Path, data: dict) -> dict:
    """Write `data` to `path` as JSON, merging onto whatever is already there so unknown top-level
    keys already present on disk survive the write. Creates the parent directory if needed.
    Returns the merged dict actually written."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_json(path)
    merged = dict(existing or {})
    merged.update(data)
    if existing is not None and merged == existing:
        return merged  # nothing changed: leave the file (and a versioned one's git status) alone
    overwrite_text(path, json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
    return merged


# ---------------------------------------------------------------------------
# .act-lock.json — versioned, tracks the applied template state
# ---------------------------------------------------------------------------

def _default_lock() -> dict:
    return {
        # "source": the template's own address (its git remote URL at the time this project last
        # fetched from it, or a local path if it had none) -- never a git remote in the project
        # itself; see init.py's _checkout_template_ref()/step_git_in_place().
        # "manifest_sha256": sha256 of the .act/MANIFEST.json this project last applied -- lets
        # dispatch.py tell a project .act/ that was pulled in by some other means (e.g. a plain
        # `git pull` of the shared history) from one update.py actually applied, even though both
        # leave .act/ matching its own MANIFEST.json.
        "template": {"version": "", "commit": "", "source": "", "manifest_sha256": ""},
        "migrations_applied": [],
        "removed_by_user": [],
        # "bridges_applied": per text-block bridge (currently ".gitignore"/".gitattributes"), the
        # exact line list this project had last applied -- merge_text_block()'s baseline for "only
        # add what's new since then". Absent for a project from before this
        # tracking existed; see _append_block()'s fallback for that case.
        "bridges_applied": {},
    }


def read_lock() -> dict:
    """Read .act-lock.json at the repo root. Returns a fresh, valid skeleton (see _default_lock)
    if the file does not exist yet; missing required keys in an existing file are filled in with
    defaults without touching any other key present."""
    path = repo_root() / ".act-lock.json"
    data = _read_json(path)
    if data is None:
        return _default_lock()
    result = _default_lock()
    result.update(data)
    return result


def write_lock(data: dict) -> dict:
    """Merge `data` onto .act-lock.json at the repo root and write it back. Any field already in
    the file that is not part of `data` (including fields unknown to this template version) is
    kept. Returns the merged dict actually written."""
    path = repo_root() / ".act-lock.json"
    return _write_json_merged(path, data)


# ---------------------------------------------------------------------------
# .act-local/identity.json — per-checkout identity, gitignored
# ---------------------------------------------------------------------------

def _identity_path(root: Optional[Path] = None) -> Path:
    return (root or repo_root()) / ".act-local" / "identity.json"


def read_identity(root: Optional[Path] = None) -> Optional[dict]:
    """Read .act-local/identity.json of `root` (default: repo_root(), cwd-based). Returns None if
    it does not exist (or is unreadable) — callers treat that as "not initialized yet", never as
    an error."""
    return _read_json(_identity_path(root))


def identity_slug(text: str) -> str:
    """The short form of a person's name that serves as a workspace identity and as the value of a
    `for:` header ("Wolfgang Rufeger" -> "wolfgang-rufeger"): lowercase, every run of characters
    outside [a-z0-9] collapsed to one "-", trimmed; "user" if nothing survives. init.py forms the
    identity in `.act-local/identity.json` with it, and board.py forms it from a `for:` value before
    comparing, so a hand-written full name still finds its owner."""
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-") or "user"


def recipient_slug(text: str) -> str:
    """The short form of a `for:` value: identity_slug(), but a value with nothing in
    [a-z0-9] (`张伟`, `???`) stays as its trimmed lowercase raw text instead of collapsing to
    "user" — else every such name would count as the person whose identity is `user`."""
    raw = text.strip().lower()
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-") or raw


def write_identity(data: dict) -> dict:
    """Merge `data` (expected keys: identity, workspace, created) onto .act-local/identity.json,
    creating the .act-local/ directory if needed. Returns the merged dict actually written."""
    return _write_json_merged(_identity_path(), data)


# ---------------------------------------------------------------------------
# .act-local/cache.json — generated-file cache, gitignored
# ---------------------------------------------------------------------------

def _cache_path() -> Path:
    return repo_root() / ".act-local" / "cache.json"


def read_cache() -> dict:
    """Read .act-local/cache.json. Returns {"generated": {}} if the file is missing or unreadable,
    and fills in a missing "generated" key so callers can always index into it directly."""
    data = _read_json(_cache_path()) or {}
    data.setdefault("generated", {})
    return data


def write_cache(data: dict) -> dict:
    """Merge `data` (expected key: "generated", a dict mapping path -> sha256) onto
    .act-local/cache.json, creating the .act-local/ directory if needed. Returns the merged dict
    actually written."""
    merged = _write_json_merged(_cache_path(), data)
    merged.setdefault("generated", {})
    return merged


# ---------------------------------------------------------------------------
# .act-lock.json § applied — the docs/ai/config.md values the dependent files were last synced
# for (`tools`, every role's Roles-table entry, the role bridges present then), so update.py's
# sync_dependent_files() can tell a session start with nothing to do from one where a
# value moved. Versioned inside the lock: config.md and the copies are per branch, so
# the record of what they were synced for travels with them — a per-checkout file read a branch
# switch as a value change. A .act-local/last-applied.json from before is read as a fallback
# until the first write, which removes it.
# ---------------------------------------------------------------------------

def _last_applied_path() -> Path:
    return repo_root() / ".act-local" / "last-applied.json"


def read_last_applied() -> Optional[dict]:
    """The lock's `applied` record, else a legacy .act-local/last-applied.json, else None —
    callers treat None as "never snapshotted yet", not as an error, and validate the shape
    themselves (a hand-edited lock can hold anything)."""
    applied = (_read_json(repo_root() / ".act-lock.json") or {}).get("applied")
    if isinstance(applied, dict):
        return applied
    return _read_json(_last_applied_path())


def write_last_applied(data: dict) -> dict:
    """Replace the lock's `applied` record with `data` (written only if it differs, see
    _write_json_merged) and drop a legacy .act-local/last-applied.json. Returns `data`."""
    write_lock({"applied": data})
    try:
        _last_applied_path().unlink()
    except OSError:
        pass
    return data


# ---------------------------------------------------------------------------
# docs/ai/config.md — project configuration as a Markdown key/value table
# ---------------------------------------------------------------------------

def read_config(root: Optional[Path] = None) -> dict[str, str]:
    """
    Read docs/ai/config.md as a simple key/value table: the first two cells of any Markdown table
    row are taken as (key, value), so a third column such as "Guards" in the Checks table is
    ignored; backticks around the key are dropped. The header row and the "---" separator row are
    skipped.
    Robust against a missing file and against lines that are not a two-cell table row — those are
    silently ignored rather than raising.

    `root` defaults to repo_root() (cwd-based); pass it explicitly when the caller already has a
    project root apart from cwd (adopt.py/adopt_config.py/feedback.py running --target against a
    project elsewhere, a probe doing the same).
    """
    path = (root or repo_root()) / "docs" / "ai" / "config.md"
    config: dict[str, str] = {}
    if not path.is_file():
        return config
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return config

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        inner = stripped[1:-1]
        cells = [cell.strip() for cell in inner.split("|")]
        if len(cells) < 2:
            continue
        key, value = cells[0].strip("`").strip(), cells[1]
        if not key:
            continue
        if _is_separator_cell(key) and _is_separator_cell(value):
            continue
        if _is_header_row(lines, index):
            continue
        config[key] = value
    return config


def _is_header_row(lines: list[str], index: int) -> bool:
    """True if the table row at `index` is a header row: the next non-empty line is a
    separator row. Word-free on purpose — the header may be written in any language."""
    for following in lines[index + 1:]:
        stripped = following.strip()
        if not stripped:
            continue
        if not (stripped.startswith("|") and stripped.endswith("|")):
            return False
        cells = [cell.strip() for cell in stripped[1:-1].split("|")]
        return bool(cells) and all(_is_separator_cell(cell) for cell in cells)
    return False


def _is_separator_cell(cell: str) -> bool:
    """True for a Markdown table separator cell such as ":---", "---", "---:", ":---:"."""
    body = cell.strip(":")
    return bool(body) and set(body) == {"-"}


# ---------------------------------------------------------------------------
# Languages — chat and docs language from docs/ai/config.md, and the `act:default` mark on
# docs scaffold files still in the template's English. The mechanism reads marks, never words:
# a scaffold file translated by hand keeps working as long as its marks and header fields stay.
# ---------------------------------------------------------------------------

DEFAULT_MARK = "<!-- act:default -->"
_DEFAULT_MARK_RE = re.compile(r"^\ufeff?\s*<!--\s*act:default\b[^>]*-->\s*$")
TRANSLATE_NOTE_SUFFIX = "-translate-scaffold.md"
# Status values the mechanism knows in an entry's `status:` header field — never translated.
STATUS_VALUES = ("open", "answered", "done")
# Language names an older file or a person may spell out -> the code the config keys take; a value
# that already looks like a code ("de", "pt-BR") passes through lower-cased.
LANGUAGE_NAMES = {"deutsch": "de", "german": "de", "englisch": "en", "english": "en",
                  "französisch": "fr", "french": "fr", "spanisch": "es", "spanish": "es"}
_LANGUAGE_CODE_RE = re.compile(r"^[a-z]{2,3}(?:-[a-z0-9]{2,8})?$")


def normalize_language(value: str, allow_auto: bool = False) -> Optional[str]:
    """A language code for `value` ("Deutsch" -> "de", "EN" -> "en", "pt-BR" -> "pt-br"), "auto"
    where `allow_auto` permits it, or None if it is neither a known name nor shaped like a code."""
    word = value.strip().strip("`").strip().lower()
    if word in ("auto", "automatisch", "automatic"):
        return "auto" if allow_auto else None
    code = LANGUAGE_NAMES.get(word, word)
    return code if _LANGUAGE_CODE_RE.match(code) else None


def language_settings(config: dict[str, str]) -> tuple[str, str]:
    """(chat language, docs language) from a read_config() result. `language-chat` defaults to
    "auto" (follow the owner's own messages), `language-docs` to "en". A config.md from before
    the language split carries one `language` key; it still counts, as the value for both."""
    legacy = config.get("language", "").strip()
    chat = config.get("language-chat", "").strip() or legacy or "auto"
    docs = config.get("language-docs", "").strip() or (legacy if legacy.lower() != "auto" else "") or "en"
    return normalize_language(chat, allow_auto=True) or chat, normalize_language(docs) or docs


def docs_language(root: Optional[Path] = None) -> str:
    """`language-docs` for `root` (default: repo_root()) — the language every file this
    template's own scripts write under docs/ (inbox entries, reports, journal titles) follows
    (`R-work-language`). A thin wrapper over read_config()/language_settings() so a writer needs
    neither name itself."""
    return language_settings(read_config(root))[1]


def localized(language: str, en: str, de: str) -> str:
    """`en` or `de`, picked by `language` (typically docs_language()'s return value) — the one
    shared lookup every fixed heading/label a script writes under docs/ goes through instead of
    each writer spelling out its own "if language == 'de'" branch. `de` for
    German and its regional variants (`de-AT`), `en` for English and anything else this table does
    not (yet) cover — the scaffold itself only ships those two languages today, so an unlisted
    code falls back to English rather than guessing. Only ever used for prose a person reads
    (a heading, a table header, a status label) — never for a mark, a header field, a config key/
    value, code or a path (those stay exactly as written, R-work-language)."""
    return de if language.strip().lower().split("-")[0] == "de" else en


def answer_label(language: str) -> str:
    """The empty label a new question ends with (`entries.py new question`): the human writes the
    answer on the lines below it, so an answer booked later has exactly one place to go and never
    gets a second label. In `language` (`language-docs`) through localized()."""
    return localized(language, "**Answer:**", "**Antwort:**")


def remembered_chat_language() -> Optional[str]:
    """The chat language remembered for this person on this machine (`board.py --chat-language`,
    .act-local/identity.json, never versioned) — used only while `language-chat` is `auto`."""
    value = (read_identity() or {}).get("chat_language")
    return value if isinstance(value, str) and value.strip() else None


def is_english(language: str) -> bool:
    """True for "en" and its regional variants ("en-GB") — the language the scaffold ships in."""
    return language.strip().lower().split("-")[0] in ("en", "english")


TEMPLATE_REPO_NAME = "agentic-coding-template"


def _normalize_repo_url(url: str) -> str:
    """A remote address without surrounding blanks, trailing slashes and a `.git` suffix."""
    return url.strip().rstrip("/").removesuffix(".git").rstrip("/")


def is_template_repo_url(url: str, lock_source: str = "") -> bool:
    """True when a remote address names the template repository: its repository name (the last
    path part after `/` or `:`, without `.git`) equals `agentic-coding-template` exactly, or the
    normalized address equals the template source recorded in .act-lock.json. A sibling such as
    `agentic-coding-template-docs` or a fork `my-agentic-coding-template-x` is not the template."""
    cleaned = _normalize_repo_url(url)
    if not cleaned:
        return False
    if lock_source.strip() and cleaned == _normalize_repo_url(lock_source):
        return True
    return re.split(r"[/:\\]", cleaned)[-1] == TEMPLATE_REPO_NAME


def scaffold_default_files(root: Path) -> list[str]:
    """Every file under docs/ whose first line is the `act:default` mark — scaffold text as the
    template ships it, not yet translated or taken over by the project. Sorted, root-relative.
    Only line 1 counts: the mark quoted in prose or an example elsewhere is not the mark."""
    base = root / "docs"
    if not base.is_dir():
        return []
    found = []
    for path in sorted(base.rglob("*.md")):
        try:
            with path.open(encoding="utf-8") as handle:
                first = handle.readline()
        except (OSError, UnicodeDecodeError):
            continue
        if _DEFAULT_MARK_RE.match(first):
            found.append(path.relative_to(root).as_posix())
    return found


_SECTION_REF_RE = re.compile(
    r"§\s*(?:\"([^\"\n]+)\"|„([^“”\n]+)[“”]|`([^`\n]+)`|([A-Za-z][\w-]*))"
)
_DOC_PATH_RE = re.compile(r"`?(docs/[\w./-]+\.md)`?")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")
SECTION_REF_LIST_CAP = 30


def scaffold_section_refs(root: Path, files: list[str]) -> list[str]:
    """Lines `file:line -> target § heading` for every `§` reference in a scaffold file that
    points at a heading of ANOTHER scaffold file: the path named within 120 characters before the
    `§` (the line may wrap in between) is the target file, and the quoted/backticked/bare word
    after it must equal one of that file's headings (case-insensitive). A reference whose target
    file or heading cannot be determined this way is left out. Deterministic: files in the given
    order, references in text order."""
    headings: dict[str, dict[str, str]] = {}
    texts: dict[str, str] = {}
    for rel in files:
        try:
            texts[rel] = (root / rel).read_text(encoding="utf-8-sig")
        except (OSError, UnicodeDecodeError):
            continue
        found: dict[str, str] = {}
        for line in texts[rel].splitlines():
            match = _HEADING_RE.match(line)
            if match:
                found.setdefault(match.group(1).strip("` ").lower(), match.group(1).strip())
        headings[rel] = found
    out: list[str] = []
    for rel in files:
        text = texts.get(rel)
        if text is None:
            continue
        for ref in _SECTION_REF_RE.finditer(text):
            word = next(g for g in ref.groups() if g).strip().strip("`").lower()
            before = text[max(0, ref.start() - 120):ref.start()]
            paths = _DOC_PATH_RE.findall(before)
            target = paths[-1] if paths else ""
            if not target or target == rel or target not in headings:
                continue
            heading = headings[target].get(word)
            if heading is None:
                continue
            line_no = text.count("\n", 0, ref.start()) + 1
            out.append(f"{rel}:{line_no} -> {target} § {heading}")
    return out


def translate_note_parts(
    language: str, files: list[str], root: Optional[Path] = None,
) -> tuple[str, str]:
    """(title, body) of the inbox todo asking for the one-time scaffold translation
    (`R-work-language`) — its own prose follows `language` too: the project reading it has already
    set `language-docs` away from English, so an English-only note would be as stale as the
    scaffold it points at."""
    title = localized(
        language,
        f"docs scaffold is still English (`act:default`) — translate it into {language}",
        f"Doku-Gerüst ist noch Englisch (`act:default`) — ins {language} übersetzen",
    )
    lines = [
        localized(
            language,
            f"`language-docs` in `docs/ai/config.md` is `{language}`, but these scaffold files are still "
            "the template's English text:",
            f"`language-docs` in `docs/ai/config.md` ist `{language}`, aber diese Gerüstdateien sind noch "
            "der englische Text der Vorlage:",
        ),
        "",
    ]
    lines.extend(f"- `{rel}`" for rel in files)
    lines += [
        "",
        localized(
            language,
            "Translate once, file by file (`R-work-language`): headings, table headers, status words "
            "in prose and hint texts only. Leave unchanged: marks (`<!-- act:... -->`), header fields "
            "and their values (`status: open|answered|done` stays English, in examples too), config "
            "keys and values, code, paths, and anything a person wrote. Common English technical terms "
            "(Skill, Worker, Override, Inbox, Backlog, Board, Hook, Commit, Branch …) stay as they are, "
            "above all in headings; a short explanation at most once in the text below. Then remove the "
            "`act:default` line (line 1) from the file. `docs/ai/rules.md` is not part of this: it stays "
            "English, the template keeps it current.",
            "Einmal übersetzen, Datei für Datei (`R-work-language`): nur Überschriften, Tabellenköpfe "
            "und Statuswörter im Fließtext sowie Hinweistexte. Unverändert lassen: Marken "
            "(`<!-- act:... -->`), Kopf-Felder und ihre Werte (`status: open|answered|done` bleibt "
            "Englisch, auch in Beispielen), Konfigurationsschlüssel und -werte, Code, Pfade, und alles, "
            "was ein Mensch geschrieben hat. Gängige englische Fachbegriffe (Skill, Worker, Override, "
            "Inbox, Backlog, Board, Hook, Commit, Branch …) bleiben stehen, vor allem in Überschriften; "
            "eine kurze Erklärung höchstens einmal im Text darunter. Danach die `act:default`-Zeile "
            "(Zeile 1) aus der Datei entfernen. `docs/ai/rules.md` gehört nicht dazu: sie bleibt "
            "Englisch, die Vorlage hält sie aktuell.",
        ),
    ]
    lines += [
        "",
        localized(
            language,
            "Headings that other scaffold files refer to: translate the reference together with the "
            "heading, so a `§ \"Heading\"` in one file keeps pointing at the heading in the other.",
            "Überschriften, auf die andere Gerüstdateien verweisen: den Verweis zusammen mit der "
            "Überschrift übersetzen, damit ein `§ \"Überschrift\"` in der einen Datei weiter auf die "
            "Überschrift in der anderen zeigt.",
        ),
    ]
    refs = scaffold_section_refs(root, files) if root is not None else []
    if refs:
        lines.append("")
        lines.extend(f"- `{ref}`" for ref in refs[:SECTION_REF_LIST_CAP])
        if len(refs) > SECTION_REF_LIST_CAP:
            more = len(refs) - SECTION_REF_LIST_CAP
            lines.append(localized(language, f"- +{more} more", f"- +{more} weitere"))
    return title, "\n".join(lines) + "\n"


# `dependency-check: once` (docs/ai/config.md § Dependencies; the default is `regularly`) means "runs during
# setup, then only on demand" — this is the setup side of that; the `regularly` side is
# checks.session's own staleness note, see _last_ledger_entry_with_prefix()/_dependency_check_note()
# there.
DEPENDENCY_CHECK_NOTE_SUFFIX = "-dependency-check.md"


def dependency_check_note_parts(language: str = "en") -> tuple[str, str]:
    """(title, body) of the one-time inbox todo `dependency-check: once` asks for right after
    setup, in `language` (`language-docs`, R-work-language)."""
    return (
        localized(language, "Check dependencies once", "Abhängigkeiten einmal prüfen"),
        localized(
            language,
            "`dependency-check` in `docs/ai/config.md` is `once`: run `act-deps` now to inventory "
            "dependency age and known gaps (see `.act/skills/act-deps/SKILL.md`) — after this, it runs "
            "only on demand, not again at every setup.\n",
            "`dependency-check` in `docs/ai/config.md` ist `once`: jetzt `act-deps` ausführen, um Alter "
            "und bekannte Lücken der Abhängigkeiten zu erfassen (siehe `.act/skills/act-deps/SKILL.md`) — "
            "danach läuft es nur noch auf Anfrage, nicht mehr bei jedem Setup.\n",
        ),
    )


# ---------------------------------------------------------------------------
# docs/ai/inbox/ — the one place everything waiting on a person lives. Every entry
# carries a `kind:` header field (question | todo | report | note, see INBOX_KINDS); a file without
# one — an older entry, or a hand-written one — counts as DEFAULT_INBOX_KIND ("todo"), never as an
# error. `question` (`Q<n>`) and `todo` (`U<n>`) also carry an id, handed out by entries.py the same
# way a task or backlog item is (a team project: by `entries.py assign`); report and note are named
# entirely from `kind`, a timestamp and a slug — see inbox_entry_filename(). entries.py owns the id side (KIND_DIR, KIND_PREFIX, _slugify); this
# module only owns the pieces the other writers need too (the filename form below, the note texts above).
# ---------------------------------------------------------------------------

INBOX_DIR = Path("docs/ai/inbox")
INBOX_KINDS = ("question", "todo", "report", "note")
DEFAULT_INBOX_KIND = "todo"


def created_stamp(when: Optional[datetime] = None) -> str:
    """The value for an entry's `created:` header field: local time as an ISO timestamp with
    seconds ("2026-10-04T09:30:12"). Every writer of `created:` uses this one helper so the field
    never holds a bare date in one entry and a timestamp in the next; readers still accept both."""
    return (when or datetime.now()).isoformat(timespec="seconds")


def entry_stamp(when: Optional[datetime] = None) -> str:
    """Local-time "YYYYMMDD-HHMM" for an inbox filename or a team-mode entry filename awaiting its
    id — the same clock and precision as an entry's own `created:` header field, just without the
    punctuation a filename can't carry. `when` defaults to now(); a caller passes it explicitly only
    to keep a filename and its `created:` value from a shared instant apart by a whisker."""
    return (when or datetime.now()).strftime("%Y%m%d-%H%M")


def inbox_entry_filename(kind: str, slug: str, when: Optional[datetime] = None) -> str:
    """"<kind>-<stamp>-<slug>.md" — the filename for an inbox entry that carries no id of its own
    (todo | report | note; a question keeps its id-based name, entries.py's own concern). `kind` is
    used as given, not validated against INBOX_KINDS here — the caller (entries.py's validate_entry,
    or a fixed literal) already knows it is one of the four."""
    return f"{kind}-{entry_stamp(when)}-{slug}.md"


def inbox_kind(text: str) -> str:
    """The `kind:` value from `text`'s header block (header_block(), never the body), or
    DEFAULT_INBOX_KIND if the field is missing, empty, or not one of INBOX_KINDS — an older entry
    or a hand-written one without the field is a "todo", not an error."""
    match = re.search(r"(?im)^kind:\s*(\S+)\s*$", header_block(text))
    if not match:
        return DEFAULT_INBOX_KIND
    value = match.group(1).strip().lower()
    return value if value in INBOX_KINDS else DEFAULT_INBOX_KIND


# ---------------------------------------------------------------------------
# Bridge merges — hook entries (.claude/settings.json) and appended text blocks
# (.gitattributes/.gitignore). Shared by init.py (first write, a project's own .act/ already on
# disk) and update.py (reconciling an *existing* project against a newer template state — a
# project initialized before a bridge existed, or before a later template revision changed it,
# otherwise never gets it).
# ---------------------------------------------------------------------------

_HOOK_COMMAND_PREFIX = 'P=""; for c in python3 python'


def _hook_command_suffix(event: str) -> str:
    """The current form: the invocation ends by handing dispatch.py the path this
    command built into `$D` earlier — `"${CLAUDE_PROJECT_DIR:-.}"` anchored, never a bare relative
    ".act/hooks/dispatch.py" (see .act/bridges/settings.hooks.json). A relative path is read
    against the *hook's own* current directory, which a Bash tool's own lasting `cd` moves for the
    rest of the session — Python then can't find the file and exits 2, which
    Claude Code reads as "block", for every tool call, not just Bash's."""
    return f'"$P" "$D" {event}'


def _hook_command_suffix_old_form(event: str) -> str:
    """The older form (bare relative ".act/hooks/dispatch.py"), still recognized by
    is_ours_hook so update.py's reconcile replaces it with the current form instead of leaving it
    behind as an unrecognized, un-mergeable duplicate in a project that has not run update.py
    since that form changed."""
    return f'"$P" .act/hooks/dispatch.py {event}'


# Per event, every extra fixed argument this template's own hooks may pass dispatch.py beyond the
# plain "dispatch.py <event>" call — currently only UserPromptSubmit's dedicated "/act" fast-path
# entry (.act/bridges/settings.hooks.json), a second, synchronous hook for that one event
# next to the plain async one, reaching dispatch.py's own early-exit branch (see its header). Not
# a general "any extra args count" rule on purpose (see is_ours_hook's docstring) — each variant
# is listed here explicitly, same precision as the plain suffix itself.
# SubagentStart carries one more per worker-rules part (.act/hooks/checks/worker_rules.py): the
# commands differ so Claude Code does not merge them as duplicates, and a count change here must
# follow .act/bridges/settings.hooks.json.
WORKER_RULES_PARTS = 12

_HOOK_COMMAND_EXTRA_ARGS: dict[str, tuple[str, ...]] = {
    "UserPromptSubmit": ("--act-check",),
    "SubagentStart": tuple(f"--worker-rules {number}" for number in range(1, WORKER_RULES_PARTS + 1)),
}


def _hook_command_suffixes(event: str) -> list[str]:
    """Every exact tail this template's own hook commands for `event` are known to end with,
    current form first: the current $D-anchored form, the older bare-relative form (still
    produced by a project that has not run update.py since it changed), and, for the one event with
    an
    extra fixed argument, each of those two with that argument appended too."""
    bases = [_hook_command_suffix(event), _hook_command_suffix_old_form(event)]
    extra_args = _HOOK_COMMAND_EXTRA_ARGS.get(event, ())
    return bases + [f"{base} {extra}" for base in bases for extra in extra_args]


def is_ours_hook(hook, event: str) -> bool:
    """True if `hook` (one item of a settings.json hook-entry's own "hooks" list) is exactly this
    template's generated wrapper for `event` — matched by its *exact* command text (not a
    substring
    check):
    the fixed interpreter-detection prologue
    this template always uses, ending in the literal dispatch.py invocation for this event (one of
    _hook_command_suffixes(event) — current or older form, normally one fixed-argument variant
    each, see that function), optionally followed by "; true" for the events that must never block
    the harness. A project's own hook that merely happens to also invoke dispatch.py (e.g.
    "python3 .act/hooks/dispatch.py PreToolUse --project-flag") does not match any of these exact
    forms and is correctly left alone — classification is per *hook*, not per entry, so a project
    hook sharing an entry with a template hook (same matcher) keeps its own hook and entry
    untouched."""
    if not isinstance(hook, dict):
        return False
    command = hook.get("command", "")
    if not isinstance(command, str) or not command.startswith(_HOOK_COMMAND_PREFIX):
        return False
    return any(command.endswith(suffix) or command.endswith(suffix + "; true")
               for suffix in _hook_command_suffixes(event))


def _filter_ours_hooks(entry, event: str) -> tuple[Optional[dict], bool]:
    """Strips every `is_ours_hook` hook out of one settings.json hook-entry's "hooks" list.
    Returns (filtered_entry, removed_any): filtered_entry is `entry` itself, unchanged, when
    nothing was ours to remove; a new dict with the surviving (project-owned) hooks when some
    were; or None when nothing is left, telling the caller to drop the entry entirely. Malformed
    input (not a dict, or "hooks" not a list) is returned as-is, untouched — never raises."""
    if not isinstance(entry, dict):
        return entry, False
    hooks_list = entry.get("hooks")
    if not isinstance(hooks_list, list):
        return entry, False
    kept_hooks = [hook for hook in hooks_list if not is_ours_hook(hook, event)]
    if len(kept_hooks) == len(hooks_list):
        return entry, False
    if not kept_hooks:
        return None, True
    new_entry = dict(entry)
    new_entry["hooks"] = kept_hooks
    return new_entry, True


def merge_hook_event_entries(
    existing_entries: list, bridge_entries: list, event: str,
) -> tuple[list, bool]:
    """Replaces every hook `is_ours_hook` recognizes for `event`, wherever it sits among
    `existing_entries`, with the bridge's current set of entries for that event, inserted at the
    position the first affected entry used to occupy — so a changed matcher/timeout/command is
    updated in place and a hook the bridge no longer defines (e.g. a retired matcher) is dropped
    instead of left behind as a stale duplicate. An entry that loses its only (template) hook is
    dropped; an entry that keeps a surviving project hook stays, at its own position, with just
    that hook. Non-dict entries are left exactly where they are. Returns
    (new_entries, changed) — changed is False when the result is byte-for-byte the input, the
    caller's signal that nothing needs writing (keeps a second run a true no-op)."""
    kept: list = []
    touched_positions: list[int] = []
    for entry in existing_entries:
        filtered, removed_any = _filter_ours_hooks(entry, event)
        if removed_any:
            touched_positions.append(len(kept))
        if filtered is not None:
            kept.append(filtered)
    insert_at = touched_positions[0] if touched_positions else len(kept)
    new_entries = kept[:insert_at] + list(bridge_entries) + kept[insert_at:]
    return new_entries, new_entries != existing_entries


def is_valid_hooks_container(data) -> bool:
    """True if `data` is shaped enough to merge into as a settings.json: a dict whose optional
    "hooks" key, if present, is itself a dict mapping event name -> list of entry dicts. Anything
    else (hooks: null, a list instead of a dict, an entry that is not itself a dict, ...) is a
    shape this template's merge was never meant to repair — the caller
    reports it and leaves the file exactly as it is, rather than half-merging into something that
    was never a valid settings file to begin with."""
    if not isinstance(data, dict):
        return False
    hooks = data.get("hooks", {})
    if not isinstance(hooks, dict):
        return False
    for entries in hooks.values():
        if not isinstance(entries, list):
            return False
        for entry in entries:
            if not isinstance(entry, dict):
                return False
    return True


def merge_settings_hooks(current: dict, bridge_data: dict) -> tuple[dict, list[str]]:
    """Merges bridge_data["hooks"] (a parsed .act/bridges/*.json hook bridge, e.g.
    settings.hooks.json) onto `current` (a parsed .claude/settings.json, or {} for a fresh one),
    event by event, via merge_hook_event_entries(). Also merges bridge_data["statusLine"] onto
    `current["statusLine"]` via merge_settings_status_line() — a second,
    unrelated top-level key of the same settings.json, folded into this one function rather than
    given its own call site so init.py's/update.py's existing single call to this function (see
    _merge_settings_hooks) picks it up without either needing to change. A change there is reported
    back the same way a changed hook event is: by the literal string "statusLine" appearing in the
    returned `changed_events` list, even though it is not itself an event name — every caller of
    this function only ever joins that list into a message or checks whether it is empty, never
    matches an entry against a specific event name. Returns
    (new_settings, changed_events) — changed_events is empty when every event's entries and the
    status line already match the bridge, the caller's signal to leave the file on disk untouched.
    Never raises: a malformed `current`/`bridge_data` (not a dict, "hooks" not a dict, an event's
    value not a list, ...) is treated as empty rather than crashing --catch-up; a caller that wants
    to report the shape as invalid instead of silently
    normalizing it checks
    is_valid_hooks_container() first."""
    current = current if isinstance(current, dict) else {}
    bridge_hooks = bridge_data.get("hooks") if isinstance(bridge_data, dict) else None
    bridge_hooks = bridge_hooks if isinstance(bridge_hooks, dict) else {}
    raw_hooks = current.get("hooks")
    hooks = dict(raw_hooks) if isinstance(raw_hooks, dict) else {}
    changed_events: list[str] = []
    for event in sorted(set(bridge_hooks) | set(hooks)):
        bridge_entries = bridge_hooks.get(event)
        bridge_entries = bridge_entries if isinstance(bridge_entries, list) else []
        existing_entries = hooks.get(event)
        existing_entries = existing_entries if isinstance(existing_entries, list) else []
        new_entries, changed = merge_hook_event_entries(existing_entries, bridge_entries, event)
        if changed:
            changed_events.append(event)
        if new_entries:
            hooks[event] = new_entries
        elif event in hooks:
            del hooks[event]
    new_current = dict(current)
    if hooks:
        new_current["hooks"] = hooks
    else:
        new_current.pop("hooks", None)
    new_current, status_line_changed = merge_settings_status_line(new_current, bridge_data)
    if status_line_changed:
        changed_events.append("statusLine")
    return new_current, changed_events


# ---------------------------------------------------------------------------
# statusLine — Claude Code's persistent status line, one small script
# (.act/hooks/statusline.py) the same bridge (settings.hooks.json) now also carries as a top-level
# "statusLine" key. Unlike a hook, a statusLine entry is a single dict, not a per-event list, so it
# gets its own small "is this still ours" check (_is_ours_status_line()) instead of reusing
# is_ours_hook(): "ours" only ever replaces "ours", a project's own statusLine (any command that
# does not match this exact template-generated one) is never touched, matching every other bridge's
# "the project's own choice always wins" rule.
# ---------------------------------------------------------------------------

def status_line_command() -> str:
    """The exact shell command for the template's statusLine bridge entry: the same
    interpreter-detection prologue the hook commands use (_HOOK_COMMAND_PREFIX), invoking
    .act/hooks/statusline.py with no event argument (it takes none, unlike dispatch.py) and no
    trailing "; true" — a statusLine command's stdout is read as the line to show regardless of its
    exit code, but a missing interpreter or file must still resolve to an empty line rather than an
    error banner, hence the same "exit 0 either way" guard as every other generated hook command."""
    return (
        f'{_HOOK_COMMAND_PREFIX}; do "$c" -c \'import sys; sys.exit(0 if sys.version_info>=(3,9) '
        'else 1)\' >/dev/null 2>&1 && { P="$c"; break; }; done; '
        'D="${CLAUDE_PROJECT_DIR:-.}/.act/hooks/statusline.py"; '
        'if [ -z "$P" ]; then exit 0; fi; if [ ! -f "$D" ]; then exit 0; fi; "$P" "$D"'
    )


def _is_ours_status_line(entry) -> bool:
    """True if `entry` (current["statusLine"]) is exactly this template's own generated entry —
    matched the same way is_ours_hook() matches a hook: by exact command text, not merely by also
    invoking statusline.py somehow. A project's own statusLine that happens to differ in any way
    (a wrapped call, extra flags, a completely different script) is correctly left alone."""
    if not isinstance(entry, dict):
        return False
    return entry.get("type") == "command" and entry.get("command") == status_line_command()


def _user_wide_status_line_path() -> Path:
    """Claude Code's own user-wide settings file, via Path.home() so a redirected HOME/USERPROFILE
    (a test, a probe) is honored the same way the rest of this module resolves a user-level path —
    never hard-coded to one platform's profile layout."""
    return Path.home() / ".claude" / "settings.json"


def _user_wide_status_line() -> Optional[dict]:
    """The "statusLine" entry from the user-wide settings file, or None. Read-only, best-effort: a
    missing file, one that isn't valid JSON, or a "statusLine" that isn't a dict all just mean
    "nothing to report" here — this check exists only to notice a person's own choice, never to
    validate or touch that file."""
    try:
        data = json.loads(_user_wide_status_line_path().read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    status = data.get("statusLine") if isinstance(data, dict) else None
    return status if isinstance(status, dict) else None


def merge_settings_status_line(current: dict, bridge_data: dict) -> tuple[dict, bool]:
    """Merges bridge_data["statusLine"] onto current["statusLine"]: added when the project has none
    yet, replaced when the project's current one is still exactly this template's own previously
    generated entry (_is_ours_status_line()) — so a project that has since set its own statusLine
    keeps it untouched forever, the same "a project's own choice, once set, always wins" rule every
    other bridge here follows (merge_settings_env, is_ours_hook). Before adding or replacing, also
    checks the user-wide settings file (_user_wide_status_line(), read-only): a person who already
    set a status line for themselves, once, for every project, is not silently shadowed by one this
    project's own settings.json would otherwise gain — the project is left with none, and the
    reason goes to stderr in one line (`.act/skeleton/config.md` says how to turn either off).
    Returns (new_current, changed); changed is False and new_current is `current` itself, unchanged,
    when there is nothing to add/replace — the caller's signal that the file needs no write for this
    part either. Never raises: a malformed `current`/`bridge_data` (not a dict, "statusLine" not a
    dict) is treated as empty/absent, same convention as merge_settings_hooks/merge_settings_env."""
    current = current if isinstance(current, dict) else {}
    bridge_status = bridge_data.get("statusLine") if isinstance(bridge_data, dict) else None
    if not isinstance(bridge_status, dict):
        return current, False
    existing = current.get("statusLine")
    if existing == bridge_status:
        return current, False
    if existing is not None and not _is_ours_status_line(existing):
        return current, False  # the project's own statusLine always wins, never overwritten
    if _user_wide_status_line() is not None:
        print(
            f"actlib: a user-wide statusLine is already set ({_user_wide_status_line_path()}) — "
            "this project keeps none of its own (docs/ai/config.md tells you how to turn either off)",
            file=sys.stderr,
        )
        return current, False
    new_current = dict(current)
    new_current["statusLine"] = bridge_status
    return new_current, True


def merge_settings_env(current: dict, bridge_data: dict) -> tuple[dict, bool]:
    """Merges bridge_data["env"] (e.g. settings.hooks.json's top-level "env" key —
    CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR=1: without it a Bash tool's own `cd` survives
    across tool calls, breaking the hooks' file lookup by relative path) onto `current["env"]`.
    Additive only — adds a key `current` does not already have, never overwrites or removes a key
    the project set itself, even to a different value. Returns (new_current, changed); `changed`
    is False and `new_current` is `current` itself, unchanged, when there is nothing to add — the
    caller's signal that the file needs no write for this part either. Never raises: a malformed
    `current`/`bridge_data` is treated as empty, same convention as merge_settings_hooks."""
    current = current if isinstance(current, dict) else {}
    bridge_env = bridge_data.get("env") if isinstance(bridge_data, dict) else None
    bridge_env = bridge_env if isinstance(bridge_env, dict) else {}
    raw_env = current.get("env")
    env = raw_env if isinstance(raw_env, dict) else {}
    missing = {key: value for key, value in bridge_env.items() if key not in env}
    if not missing:
        return current, False
    new_env = dict(env)
    new_env.update(missing)
    new_current = dict(current)
    new_current["env"] = new_env
    return new_current, True


# The Claude Code setting that drops the Artifact tool from the session's tool list, and the
# .act-lock.json key under which the entries this mechanism set itself are booked.
ARTIFACT_SETTING = "enableArtifact"
SETTINGS_BOOKED_KEY = "settings_applied"


def artifacts_mode(config: dict[str, str]) -> str:
    """The `artifacts` row of docs/ai/config.md: "on" (leave the setting alone) or "off". A missing
    row or any other value counts as "off", the default."""
    return "on" if config.get("artifacts", "").strip().lower() == "on" else "off"


def merge_settings_artifact(
    root: Path, current: dict, mode: str, *, once: bool = False, plan: bool = False,
) -> tuple[dict, bool, list[str], Optional[dict]]:
    """Applies the `artifacts` config value to a project's .claude/settings.json content `current`.
    "off": sets `enableArtifact: false` when the key is missing and returns that entry as booked, so
    the mechanism can tell its own entry from the project's. "on" means "leave alone", not "switch
    on": it removes only a booked entry, and with nothing booked changes nothing. A value the
    project set itself is never overwritten; one that contradicts "off" (anything but false) is
    reported instead, with `once` only the first time that state is seen (remembered in
    .act-local/cache.json -- the only thing this function writes, and only with `once`). `plan`
    words the notes as "would ...".
    Returns (new_current, changed, notes, booking). `booking` is None when the lock needs no change,
    else the new content of .act-lock.json § settings_applied (possibly empty). It is never written
    here: the caller writes settings.json first and only then calls write_settings_booking, so a
    failed write leaves no booking behind. `new_current` is `current` itself when the settings file
    needs no write. Nothing is done when the lock exists but is unreadable (booking would overwrite
    it) or `current` is not a dict. Never raises for those."""
    if not isinstance(current, dict):
        return current, False, [], None
    lock_path = root / ".act-lock.json"
    lock = _read_json(lock_path)
    if lock is None and lock_path.is_file():
        return current, False, [], None
    booked = lock.get(SETTINGS_BOOKED_KEY) if isinstance(lock, dict) else None
    booked = dict(booked) if isinstance(booked, dict) else {}
    is_booked = ARTIFACT_SETTING in booked
    present = ARTIFACT_SETTING in current
    notes: list[str] = []
    new_current, changed = current, False
    booking: Optional[dict] = None
    conflict = ""
    if mode == "off":
        if not present:
            new_current = dict(current)
            new_current[ARTIFACT_SETTING] = False
            changed = True
            booked[ARTIFACT_SETTING] = False
            booking = booked
            notes.append(f"Artifact tool {'would be ' if plan else ''}switched off (template default) — set "
                         "`artifacts: on` in docs/ai/config.md to keep it; takes effect from the next session")
        elif current[ARTIFACT_SETTING] is not False:
            conflict = repr(current[ARTIFACT_SETTING])
    elif is_booked:
        booked.pop(ARTIFACT_SETTING, None)
        booking = booked
        if present and current[ARTIFACT_SETTING] is False:
            new_current = {k: v for k, v in current.items() if k != ARTIFACT_SETTING}
            changed = True
            notes.append("Artifact tool no longer switched off by the template (`artifacts: on`) — "
                         "takes effect from the next session")
    cache_path = root / ".act-local" / "cache.json"
    if conflict:
        text = (f"[act] note: .claude/settings.json has {ARTIFACT_SETTING}: {conflict}, which contradicts "
                "`artifacts: off` in docs/ai/config.md — the project's value is kept; set "
                "`artifacts: on` there to match, or remove the line")
        if once:
            cache = _read_json(cache_path) or {}
            if cache.get("artifact_conflict_hint") != conflict:
                _write_json_merged(cache_path, {"artifact_conflict_hint": conflict})
                notes.append(text)
        else:
            notes.append(text)
    elif once and (_read_json(cache_path) or {}).get("artifact_conflict_hint"):
        _write_json_merged(cache_path, {"artifact_conflict_hint": ""})
    return new_current, changed, notes, booking


def write_settings_booking(root: Path, booking: Optional[dict]) -> None:
    """Writes the `booking` merge_settings_artifact returned into .act-lock.json § settings_applied;
    an empty one removes the key. None, an unreadable lock, or an empty booking with no lock file
    do nothing."""
    if booking is None:
        return
    lock_path = root / ".act-lock.json"
    lock = _read_json(lock_path)
    if lock is None:
        if lock_path.is_file() or not booking:
            return
        lock = {}
    new_lock = dict(lock)
    if booking:
        new_lock[SETTINGS_BOOKED_KEY] = booking
    else:
        new_lock.pop(SETTINGS_BOOKED_KEY, None)
    if new_lock != lock or not lock_path.is_file():
        overwrite_text(lock_path, json.dumps(new_lock, indent=2, ensure_ascii=False) + "\n")


# Earlier wordings of a template block line that a project from before line-state tracking
# (.act-lock.json § bridges_applied) may still carry unchanged. Such a project has no record of what the
# template wrote, so only a line matching one of these verbatim counts as the template's own and
# is replaced by the current wording; any other line for the same pattern is the project's.
PREVIOUS_BLOCK_LINES: tuple[str, ...] = (
    "/CLAUDE.md merge=ours",
    "/AGENTS.md merge=ours",
    "/docs/ai/rules.md merge=ours",
)


def _classify_block_lines(
    existing_text: str, block_text: str, applied_lines: Optional[list[str]],
) -> tuple[list[str], list[str], list[tuple[str, str]]]:
    """Shared by merge_text_block() and text_block_conflicts(). Candidates are the block's lines
    not yet accounted for: if `applied_lines` is given (this file's .act-lock.json §
    bridges_applied[<name>] from the last time this bridge was applied), only lines new *since*
    that recorded state — so a line the project has since deliberately deleted is never silently
    reinstated, only what the template genuinely added since then. Without a recorded state (an
    old project, from before this tracking existed) this falls back to "add whatever is missing
    from the file", same as before. Of the candidates, one already present
    verbatim needs nothing; one conflicting with the project's own line — a gitignore `!pattern`
    negation, or, for a multi-token line such as a .gitattributes entry, a different existing line
    for the same leading pattern — is never applied, only reported back as a conflict, unless that
    existing line is one the template itself set earlier (it is in `applied_lines`, or, with no
    recorded state, it is one of PREVIOUS_BLOCK_LINES): then it is returned as a replacement
    (old line, new line) and the new wording takes its place. Comment and
    blank lines travel with the pattern line that follows them: they are added only together with
    it, so a reworded comment alone never leaves an orphan line at the end of a project's file."""
    existing_lines = existing_text.splitlines()
    existing_set = set(existing_lines)
    block_lines = block_text.splitlines()
    if applied_lines is None:
        candidates = [line for line in block_lines if line not in existing_set]
    else:
        applied_set = set(applied_lines)
        candidates = [line for line in block_lines if line not in applied_set]

    to_add: list[str] = []
    conflicts: list[str] = []
    replacements: list[tuple[str, str]] = []
    pending_notes: list[str] = []  # comment/blank candidates waiting for the pattern line they describe
    candidate_set = set(candidates)
    for line in block_lines:  # in block order, so a note belongs to the next pattern line below it
        is_note = not line.strip() or line.lstrip().startswith("#")
        if line not in candidate_set or line in existing_set:
            if not is_note:
                pending_notes = []  # the notes above described a line that needs nothing
            continue
        if is_note:
            pending_notes.append(line)
            continue
        if ("!" + line) in existing_set:
            conflicts.append(line)
            pending_notes = []
            continue
        tokens = line.split()
        if len(tokens) > 1:
            pattern = tokens[0]
            conflicting = next(
                (existing for existing in existing_lines
                 if existing != line and not existing.lstrip().startswith("#")
                 and existing.split()[:1] == [pattern]),
                None,
            )
            if conflicting is not None:
                template_set = set(applied_lines) if applied_lines is not None else set(PREVIOUS_BLOCK_LINES)
                if conflicting in template_set:
                    replacements.append((conflicting, line))
                else:
                    conflicts.append(line)
                pending_notes = []
                continue
        to_add.extend(pending_notes)
        pending_notes = []
        to_add.append(line)
    return to_add, conflicts, replacements


def merge_text_block(
    existing_text: str, block_text: str, applied_lines: Optional[list[str]] = None,
) -> tuple[str, list[str]]:
    """Appends whatever lines of `block_text` still need adding (see _classify_block_lines) to
    `existing_text`, as a single appended chunk in the block's own order — not the whole block
    wholesale, so a project that only has an older subset of it gets just the missing lines.
    Lines of the template's own earlier wording are replaced in place and listed in added_lines too.
    Returns (new_text, added_lines); added_lines is empty when nothing needed to change, the
    caller's signal to leave the file untouched. A single blank line separates the appended chunk
    from existing content; an empty `existing_text` gets the chunk verbatim. A candidate that
    conflicts with the project's own line (see _classify_block_lines) is silently left out of both
    — never applied, and not "added" — callers that want to report it use
    text_block_conflicts()."""
    to_add, _conflicts, replacements = _classify_block_lines(existing_text, block_text, applied_lines)
    if replacements:
        swap = dict(replacements)
        done: set[str] = set()
        kept: list[str] = []
        for line in existing_text.splitlines():
            if line in swap:
                if line not in done:  # in place of the first occurrence; a repeated old line is dropped
                    kept.append(swap[line])
                    done.add(line)
                continue
            kept.append(line)
        existing_text = "\n".join(kept) + ("\n" if existing_text.endswith("\n") else "")
    replaced = [new for _old, new in replacements]
    if not to_add:
        return existing_text, replaced
    added_text = "\n".join(to_add) + ("\n" if block_text.endswith("\n") else "")
    if not existing_text:
        new_text = added_text
    elif existing_text.endswith("\n"):
        new_text = existing_text + "\n" + added_text
    else:
        new_text = existing_text + "\n\n" + added_text
    return new_text, replaced + to_add


def text_block_conflicts(
    existing_text: str, block_text: str, applied_lines: Optional[list[str]] = None,
) -> list[str]:
    """The subset of merge_text_block()'s candidate lines that were *not* applied because the
    project already carries a conflicting line for the same pattern — for
    a caller that wants to name them in its summary instead of silently leaving them out."""
    _to_add, conflicts, _replacements = _classify_block_lines(existing_text, block_text, applied_lines)
    return conflicts


# ---------------------------------------------------------------------------
# Tool identifiers — canonical id vs. accepted variant spellings for one `docs/ai/config.md` §
# Project `tools` entry. Canonical is the short form init.py itself writes there and gates
# SKILL_TARGET_DIRS with ("codex"/"copilot"/"gemini"/"cursor"/"claude-code"/"aider"/"cline"/
# "ollama") — the same set adopt_config.TOOL_MAP maps onto. .act/tiers.json historically used the
# CLI-flavoured "codex-cli"/"copilot-cli"/"gemini-cli" for the same three tools; a project's
# `tools` value written in that spelling silently matched no SKILL_TARGET_DIRS gate at all, so no
# .agents/skills/ was ever created for it. Callers normalize through this table instead
# of comparing raw strings; an id not listed here (including every already-canonical one) is
# returned unchanged by normalize_tool() — the caller's own job to flag as unknown against
# KNOWN_TOOLS, see doctor.py's check_unknown_tools().
# ---------------------------------------------------------------------------

KNOWN_TOOLS = frozenset({
    "claude-code", "codex", "copilot", "gemini", "cursor", "aider", "cline", "ollama",
})

TOOL_ALIASES: dict[str, str] = {
    "codex-cli": "codex",
    "copilot-cli": "copilot",
    "gemini-cli": "gemini",
}


def normalize_tool(name: str) -> str:
    """Canonical tool id for one `tools` entry: strips/lowercases `name`, then maps it through
    TOOL_ALIASES if it is a known variant spelling. Returns the stripped/lowercased id unchanged
    when it is not in TOOL_ALIASES — already-canonical ids and genuinely unknown ones alike."""
    key = name.strip().lower()
    return TOOL_ALIASES.get(key, key)


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------

_HEADER_FIELD_RE = re.compile(r"^[A-Za-z][A-Za-z-]*:\s")


FRONTMATTER_DELIMITER = "---"


def split_header(text: str) -> tuple[str, str]:
    """Split `text` into (head, body) with head + body == text exactly. The head is the file's
    header with its line endings (and a leading UTF-8 BOM), the body everything after it, blank
    separator line included. Two forms are read alike: the plain form (a leading run of "key:
    value" lines, ended by a blank line or the first line that is not a field, typically the
    Markdown heading) and frontmatter (a `---` line as the very first line, field lines, the first
    following `---` line closing it, which is part of the head too). Frontmatter counts only when
    every line between the two delimiters is a field line or blank; otherwise the file has no
    header at all. A `---` further down, such as a reply block in an inbox entry's body followed
    by `status: done`, is never a header, so a value can't be spoofed from there."""
    start = 1 if text.startswith("\ufeff") else 0  # a hand-saved UTF-8 BOM is not content
    lines = text[start:].split("\n")
    count = 0
    if lines[0].rstrip() == FRONTMATTER_DELIMITER:
        for index in range(1, len(lines)):
            line = lines[index]
            if line.rstrip() == FRONTMATTER_DELIMITER:
                count = index + 1
                break
            if line.strip() and not _HEADER_FIELD_RE.match(line.rstrip("\r")):
                break
    else:
        while count < len(lines) and lines[count].strip() and _HEADER_FIELD_RE.match(lines[count].rstrip("\r")):
            count += 1
    head_length = start + sum(len(line) + 1 for line in lines[:count])
    return text[:head_length], text[head_length:]


def is_frontmatter(head: str) -> bool:
    """True if `head`, as split_header() returned it, is a frontmatter block (opens with `---`)."""
    return head.removeprefix("\ufeff").startswith(FRONTMATTER_DELIMITER)


def header_block(text: str) -> str:
    """The file's header fields as "key: value" lines (e.g. "id:", "status:", "for:", "created:"),
    joined by "\\n", without any frontmatter delimiters; split_header() says which two forms are
    read and what ends a header. Every place that reads such a field searches this substring,
    never the whole file, so a value can never be spoofed by an example, a fenced code block, or
    another file's header merely quoted in a journal entry (`entries.py`, `board.py`)."""
    head = split_header(text)[0]
    lines = [line.rstrip("\r") for line in head.removeprefix("\ufeff").split("\n")]
    return "\n".join(line for line in lines if _HEADER_FIELD_RE.match(line))


def writes_frontmatter(kind: str) -> bool:
    """True if an entry of this kind is written with its header as frontmatter: every kind
    entries.py writes (INBOX_KINDS and the `inbox` alias, task, backlog, ledger) plus the proposals
    adopt_entries.py files under docs/ai/proposals/. The one place
    that decides it. Every writer asks here, every reader accepts both forms regardless."""
    return kind in INBOX_KINDS or kind in ("inbox", "task", "backlog", "ledger", "proposal")


def format_header(fields: list[str], frontmatter: bool) -> str:
    """Render header `fields` (each a "key: value" line) as text ending in a newline: between
    `---` lines when `frontmatter`, else as the plain run of lines. The caller adds the blank
    separator line and the heading."""
    lines = [FRONTMATTER_DELIMITER, *fields, FRONTMATTER_DELIMITER] if frontmatter else list(fields)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry ids in single files and in archive collections
# ---------------------------------------------------------------------------
# An archived entry is one file with an `id:` header field; after `entries.py compact` many archived
# entries share one collection file per kind and month. Every reader that needs "which ids exist
# here" (entries.py, doctor.py, a language server) calls entry_ids() instead of reading the header
# itself, so a collection can never hide an id from the scan.

COLLECTION_MARK = "<!-- act:archive-collection -->"  # first line of a collection file
_ID_PARTS_RE = re.compile(r"^([A-Za-z]+)0*(\d+)([A-Za-z]?)$")
_HEADER_ID_RE = re.compile(r"(?im)^id:\s*([A-Za-z]+\d+[a-z]?)\s*$")
_SECTION_ANCHOR_RE = re.compile(r'^<a id="([^"\n]+)"></a>\s*$')
_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_FENCE_CLOSE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})\s*$")
FenceState = Optional[tuple[str, int]]  # (fence character, fence length) while inside a fenced code block


def fence_step(state: FenceState, line: str) -> FenceState:
    """The fence state after `line`, as CommonMark has it: a run of 3+ backticks or tildes opens a block
    (a backtick fence may not carry a backtick in its info string), and only a run of the same character
    at least as long, with nothing after it, closes it. A shorter or other run inside is plain text."""
    line = line.rstrip("\r")
    if state is None:
        opened = _FENCE_OPEN_RE.match(line)
        if opened and not (opened.group(1)[0] == "`" and "`" in opened.group(2)):
            return (opened.group(1)[0], len(opened.group(1)))
        return None
    closed = _FENCE_CLOSE_RE.match(line)
    if closed and closed.group(1)[0] == state[0] and len(closed.group(1)) >= state[1]:
        return None
    return state


def fence_closer(state: FenceState) -> str:
    """The line that closes the open fence `state` (an empty string if none is open)."""
    return state[0] * state[1] if state else ""


def canonical_id(raw: str) -> str:
    """An id with its number normalised, so "X012" and "X12" compare equal and a sub-letter is
    lower case ("X55A" -> "X55a"). Anything that is not letters + digits comes back upper-cased."""
    match = _ID_PARTS_RE.match(raw.strip())
    if not match:
        return raw.strip().upper()
    letters, digits, sub = match.groups()
    return f"{letters.upper()}{int(digits)}{sub.lower()}"


def is_collection(text: str) -> bool:
    """True if `text` is an archive collection file (it opens with COLLECTION_MARK)."""
    return text.removeprefix("﻿").startswith(COLLECTION_MARK)


def collection_sections(text: str) -> list[tuple[str, int]]:
    """(canonical id, 1-based line of the anchor) for every entry section of a collection: a line
    `<a id="<id>"></a>` directly followed by a heading `## <id> — <title>` naming the same id. A pair
    inside a fenced code block is an example and does not count, except that a section boundary always
    resets the fence state, so a fence an earlier section left unclosed cannot hide the sections after
    it; a section without an id (its anchor is not an id) is not listed."""
    lines = text.removeprefix("﻿").split("\n")
    found: list[tuple[str, int]] = []
    fence: FenceState = None
    for index, line in enumerate(lines):
        line = line.rstrip("\r")
        anchor = _SECTION_ANCHOR_RE.match(line)
        if anchor and _ID_PARTS_RE.match(anchor.group(1)) and index + 1 < len(lines):
            heading = lines[index + 1].rstrip("\r")
            if heading == f"## {anchor.group(1)}" or heading.startswith(f"## {anchor.group(1)} — "):
                found.append((canonical_id(anchor.group(1)), index + 1))
                fence = None
                continue
        fence = fence_step(fence, line)
    return found


def entry_ids(text: str) -> list[str]:
    """The canonical ids an entry file carries: its `id:` header field for a single entry (zero or
    one), every section id for an archive collection. Only the header block is read for a single
    entry, never the body, so a quoted header cannot spoof an id."""
    if is_collection(text):
        return [entry_id for entry_id, _line in collection_sections(text)]
    match = _HEADER_ID_RE.search(header_block(text))
    return [canonical_id(match.group(1))] if match else []


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of the file at `path`, read in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def overwrite_text(path: Path, text: str, newline: Optional[str] = None) -> None:
    """Write `text` to `path` as UTF-8, creating the parent folder and replacing any existing content.
    On Windows `open(path, "w")` truncates through CREATE_ALWAYS, which the system refuses for a file
    carrying the Hidden attribute (PermissionError 13) — editors and older tools often set it on
    dotfiles such as `.gitignore`. An existing file is therefore opened with "r+" and cut with
    `truncate()`, which also keeps its attributes. `newline` is passed to `open()` as is."""
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "r+" if sys.platform == "win32" and path.is_file() else "w"
    try:
        with open(path, mode, encoding="utf-8", newline=newline) as handle:
            handle.write(text)
            if mode == "r+":
                handle.truncate()
    except PermissionError as exc:
        if sys.platform == "win32":
            raise PermissionError(
                exc.errno, f"{exc.strerror}: {path} — if the file is read-only or hidden, clear the "
                f"attribute first with: attrib -R -H \"{path}\"") from exc
        raise


def write_text_lf(path: Path, text: str) -> None:
    """Write `text` to `path` as UTF-8 with `\\n` line endings regardless of platform default.
    Every generated bridge and scaffold/docs file must come out the same way the template's
    `.gitattributes` block (`text eol=lf` on the bridges and the per-person board) checks the
    very same file out as — otherwise the "unchanged since
    generated" hash comparison in .act-local/cache.json flips on nothing but the checkout's own
    line endings. `open()`'s own `newline` parameter has always accepted this value, unlike
    `Path.write_text(..., newline=...)` (Python 3.10+), which this project's floor (3.9) lacks."""
    overwrite_text(path, text, newline="\n")


def fold_crlf(data: bytes) -> bytes:
    """`data` with CRLF folded to LF, unless it holds a NUL byte (binary)."""
    return data if b"\x00" in data else data.replace(b"\r\n", b"\n")


def lock_hash(data: bytes) -> str:
    """The hash recorded in the lock for a copy written from `data`: over the LF form, so the value
    reads the same whether a checkout later holds the copy with CRLF or LF."""
    return hashlib.sha256(fold_crlf(data)).hexdigest()


def matches_lock_hash(current: bytes, recorded: Optional[str]) -> bool:
    """True if the copy `current` is the one the lock recorded: raw or folded bytes against a recorded
    hash over raw or folded bytes. A lock written before the hash was folded holds the CRLF form when
    the copy was written with core.autocrlf=true, so the copy's CRLF expansion counts too."""
    if not recorded:
        return False
    folded = fold_crlf(current)
    candidates = {hashlib.sha256(current).hexdigest(), hashlib.sha256(folded).hexdigest()}
    if b"\x00" not in current:
        candidates.add(hashlib.sha256(folded.replace(b"\n", b"\r\n")).hexdigest())
    return recorded in candidates


MIN_GIT_VERSION = (2, 25)  # git add/commit --pathspec-from-file


def git_version() -> Optional[tuple[int, ...]]:
    """The installed git's version as a tuple of ints (e.g. (2, 56, 0)), or None if it cannot be read."""
    try:
        out = subprocess.run(["git", "--version"], capture_output=True, text=True, encoding="utf-8").stdout
    except OSError:
        return None
    found = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", out)
    return tuple(int(part) for part in found.groups() if part is not None) if found else None


def git_version_problem() -> Optional[str]:
    """A message when git is missing or older than MIN_GIT_VERSION (it names the version found), else None."""
    version = git_version()
    need = ".".join(str(n) for n in MIN_GIT_VERSION)
    if version is None:
        return f"git not found or its version unreadable; Git {need} or newer is required"
    if version[:2] < MIN_GIT_VERSION:
        return f"Git {need} or newer is required (--pathspec-from-file), found {'.'.join(str(n) for n in version)}"
    return None


def git_pathspec_stdin(args: list[str], rels: list[str], cwd: Path, check: bool = True) -> "subprocess.CompletedProcess[str]":
    """Run `git <args> --pathspec-from-file=- --pathspec-file-nul` with `rels` on stdin, so the path
    list never meets the command-line length limit (Windows: about 32,000 characters). Needs Git 2.25
    or newer (`add`, `commit`). An empty list is refused: git would read it as "no pathspec" and act
    on the whole index."""
    if not rels:
        raise ValueError(f"git {' '.join(args)}: empty path list, refusing to act on the whole index")
    full = [*args, "--pathspec-from-file=-", "--pathspec-file-nul"]
    result = subprocess.run(
        ["git", *full], cwd=cwd, capture_output=True, text=True, encoding="utf-8",
        input="".join(f"{rel}\0" for rel in rels),
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(full)} failed: {result.stderr.strip()}")
    return result


def normalized_sha256(path: Path) -> str:
    """SHA-256 of `path` with CRLF folded to LF first — unless it holds a NUL byte (binary) — the
    same folding manifest.py's content_hash() applies to every file under .act/. A generated
    bridge or scaffold file checked out or written with CRLF must hash the same as its LF
    counterpart, so a comparison against this hash never flips on line endings alone."""
    data = path.read_bytes()
    if b"\x00" not in data:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def generated_hash(path: Path) -> str:
    """The hash to record in .act-local/cache.json's "generated" map right after (re)writing a
    generated file: normalized_sha256(), so the recorded value reads the same back regardless of
    which platform generated it."""
    return normalized_sha256(path)


def generated_unchanged(path: Path, recorded_hash: str) -> bool:
    """True if `path` still matches what .act-local/cache.json's "generated" map recorded for it
    at generation time. Compared with line endings normalized first (normalized_sha256()), so a
    checkout's line endings alone never make an untouched generated file look "changed locally". A
    cache entry from before this fix recorded the raw-byte hash
    (sha256_file()) — that
    still counts as unchanged too, so an existing project's cache does not spuriously flag every
    bridge as edited the first time it runs against this fix. Also covers the CRLF variant of that
    same old raw-byte form: a session start once wrote the file with CRLF and recorded its raw
    hash, git later checked the file out as LF — the file's normalized bytes re-expanded to CRLF
    still hash to the same recorded value. A caller that gets True back from one of these old-form
    matches should re-record generated_hash(path) so the cache moves to the normalized form."""
    if not recorded_hash or not path.is_file():
        return False
    normalized = normalized_sha256(path)
    if normalized == recorded_hash:
        return True
    if sha256_file(path) == recorded_hash:
        return True
    data = path.read_bytes()
    if b"\x00" not in data:
        crlf_data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        if hashlib.sha256(crlf_data).hexdigest() == recorded_hash:
            return True
    return False


def is_interactive() -> bool:
    """True if this run should be treated as interactive: stdin is a real terminal and the caller
    did not pass --non-interactive."""
    if "--non-interactive" in sys.argv:
        return False
    try:
        return sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False
