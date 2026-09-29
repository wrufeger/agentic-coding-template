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
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


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
    written yet, not as a reason to abort the caller (F9, T60: read_last_applied() previously left
    `UnicodeDecodeError` uncaught, which made update.py abort mid-run and left `.act/` already
    replaced)."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
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
    path.write_text(json.dumps(merged, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return merged


# ---------------------------------------------------------------------------
# .act-lock.json — versioned, tracks the applied template state
# ---------------------------------------------------------------------------

def _default_lock() -> dict:
    return {
        # "source": the template's own address (its git remote URL at the time this project last
        # fetched from it, or a local path if it had none) -- never a git remote in the project
        # itself; see init.py's _checkout_source()/step_git_in_place() and Q73a.
        # "manifest_sha256": sha256 of the .act/MANIFEST.json this project last applied -- lets
        # dispatch.py tell a project .act/ that was pulled in by some other means (e.g. a plain
        # `git pull` of the shared history) from one update.py actually applied, even though both
        # leave .act/ matching its own MANIFEST.json (Q73a).
        "template": {"version": "", "commit": "", "source": "", "manifest_sha256": ""},
        "migrations_applied": [],
        "removed_by_user": [],
        # "bridges_applied": per text-block bridge (currently ".gitignore"/".gitattributes"), the
        # exact line list this project had last applied -- merge_text_block()'s baseline for "only
        # add what's new since then" (T46 review finding 4). Absent for a project from before this
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

def _identity_path() -> Path:
    return repo_root() / ".act-local" / "identity.json"


def read_identity() -> Optional[dict]:
    """Read .act-local/identity.json. Returns None if it does not exist (or is unreadable) —
    callers treat that as "not initialized yet", never as an error."""
    return _read_json(_identity_path())


def identity_slug(text: str) -> str:
    """The short form of a person's name that serves as a workspace identity and as the value of a
    `for:` header ("Wolfgang Rufeger" -> "wolfgang-rufeger"): lowercase, every run of characters
    outside [a-z0-9] collapsed to one "-", trimmed; "user" if nothing survives. init.py forms the
    identity in `.act-local/identity.json` with it, and board.py forms it from a `for:` value before
    comparing (B147), so a hand-written full name still finds its owner."""
    return re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-") or "user"


def recipient_slug(text: str) -> str:
    """The short form of a `for:` value (B147): identity_slug(), but a value with nothing in
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
# sync_dependent_files() (T60 part B) can tell a session start with nothing to do from one where a
# value moved. Versioned inside the lock (G1, T60): config.md and the copies are per branch, so
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
# Languages (T61) — chat and docs language from docs/ai/config.md, and the `act:default` mark on
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
    T61 carries one `language` key; it still counts, as the value for both."""
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
    each writer spelling out its own "if language == 'de'" branch (backlog B118#18). `de` for
    German and its regional variants (`de-AT`), `en` for English and anything else this table does
    not (yet) cover — the scaffold itself only ships those two languages today, so an unlisted
    code falls back to English rather than guessing. Only ever used for prose a person reads
    (a heading, a table header, a status label) — never for a mark, a header field, a config key/
    value, code or a path (those stay exactly as written, R-work-language)."""
    return de if language.strip().lower().split("-")[0] == "de" else en


def remembered_chat_language() -> Optional[str]:
    """The chat language remembered for this person on this machine (`board.py --chat-language`,
    .act-local/identity.json, never versioned) — used only while `language-chat` is `auto`."""
    value = (read_identity() or {}).get("chat_language")
    return value if isinstance(value, str) and value.strip() else None


def is_english(language: str) -> bool:
    """True for "en" and its regional variants ("en-GB") — the language the scaffold ships in."""
    return language.strip().lower().split("-")[0] in ("en", "english")


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


def translate_note_text(language: str, files: list[str]) -> str:
    """The inbox entry asking for the one-time scaffold translation (`R-work-language`) — its own
    prose follows `language` too (B118#18): the project reading it has already set `language-docs`
    away from English, so an English-only note would be as stale as the scaffold it points at."""
    lines = [
        "kind: todo", "for: all", "status: open", "",
        localized(
            language,
            f"# docs scaffold is still English (`act:default`) — translate it into {language}",
            f"# Doku-Gerüst ist noch Englisch (`act:default`) — ins {language} übersetzen",
        ),
        "",
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
            "keys and values, code, paths, and anything a person wrote. Then remove the `act:default` "
            "line (line 1) from the file. `docs/ai/rules.md` is not part of this: it stays English, "
            "the template keeps it current.",
            "Einmal übersetzen, Datei für Datei (`R-work-language`): nur Überschriften, Tabellenköpfe "
            "und Statuswörter im Fließtext sowie Hinweistexte. Unverändert lassen: Marken "
            "(`<!-- act:... -->`), Kopf-Felder und ihre Werte (`status: open|answered|done` bleibt "
            "Englisch, auch in Beispielen), Konfigurationsschlüssel und -werte, Code, Pfade, und alles, "
            "was ein Mensch geschrieben hat. Danach die `act:default`-Zeile (Zeile 1) aus der Datei "
            "entfernen. `docs/ai/rules.md` gehört nicht dazu: sie bleibt Englisch, die Vorlage hält sie "
            "aktuell.",
        ),
    ]
    return "\n".join(lines) + "\n"


def write_translate_note(root: Path, language: str, plan: bool = False) -> Optional[Path]:
    """Write docs/ai/inbox/todo-<stamp>-translate-scaffold.md unless the docs language is English,
    no file carries `act:default`, or such an entry already exists (any stamp). Returns the path
    that was (plan: would be) written, else None."""
    if is_english(language):
        return None
    files = scaffold_default_files(root)
    inbox = root / INBOX_DIR
    if not files or (inbox.is_dir() and any(inbox.glob(f"*{TRANSLATE_NOTE_SUFFIX}"))):
        return None
    dest = inbox / inbox_entry_filename("todo", "translate-scaffold")
    if not plan:
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_text_lf(dest, translate_note_text(language, files))
    return dest


# B102/Q68: `dependency-check: once` (docs/ai/config.md § Dependencies, default) means "runs during
# setup, then only on demand" — this is the setup side of that; the `regularly` side is
# checks.session's own staleness note, see _last_ledger_entry_with_prefix()/_dependency_check_note()
# there.
DEPENDENCY_CHECK_NOTE_SUFFIX = "-dependency-check.md"


def dependency_check_note_text(language: str = "en") -> str:
    """The one-time inbox entry `dependency-check: once` asks for right after setup, in `language`
    (`language-docs`, R-work-language, B118#18)."""
    return (
        "kind: todo\nfor: all\nstatus: open\n\n"
        + localized(language, "# Check dependencies once", "# Abhängigkeiten einmal prüfen") + "\n\n"
        + localized(
            language,
            "`dependency-check` in `docs/ai/config.md` is `once`: run `act-deps` now to inventory "
            "dependency age and known gaps (see `.act/skills/act-deps/SKILL.md`) — after this, it runs "
            "only on demand, not again at every setup.\n",
            "`dependency-check` in `docs/ai/config.md` ist `once`: jetzt `act-deps` ausführen, um Alter "
            "und bekannte Lücken der Abhängigkeiten zu erfassen (siehe `.act/skills/act-deps/SKILL.md`) — "
            "danach läuft es nur noch auf Anfrage, nicht mehr bei jedem Setup.\n",
        )
    )


def write_dependency_check_note(root: Path, dependency_check: str, plan: bool = False) -> Optional[Path]:
    """Write docs/ai/inbox/todo-<stamp>-dependency-check.md when `dependency-check` (read from the
    config.md this run just wrote/kept) is `once` and no such entry exists yet (any stamp — a
    second `init` run must not add a second one). Returns the path that was (plan: would be)
    written, else None."""
    if dependency_check.strip().lower() != "once":
        return None
    inbox = root / INBOX_DIR
    if inbox.is_dir() and any(inbox.glob(f"*{DEPENDENCY_CHECK_NOTE_SUFFIX}")):
        return None
    dest = inbox / inbox_entry_filename("todo", "dependency-check")
    if not plan:
        dest.parent.mkdir(parents=True, exist_ok=True)
        write_text_lf(dest, dependency_check_note_text(docs_language(root)))
    return dest


# ---------------------------------------------------------------------------
# docs/ai/inbox/ — the one place everything waiting on a person lives (ADR-9, T75). Every entry
# carries a `kind:` header field (question | todo | report | note, see INBOX_KINDS); a file without
# one — an older entry, or a hand-written one — counts as DEFAULT_INBOX_KIND ("todo"), never as an
# error. Only `question` also carries an id (`Q<n>`, handed out by entries.py the same way a task or
# backlog item is); the other three kinds are named entirely from `kind`, a timestamp and a slug —
# see inbox_entry_filename(). entries.py owns the id side (KIND_DIR, KIND_PREFIX, _slugify); this
# module only owns the pieces write_translate_note() and other non-entries.py writers need too.
# ---------------------------------------------------------------------------

INBOX_DIR = Path("docs/ai/inbox")
INBOX_KINDS = ("question", "todo", "report", "note")
DEFAULT_INBOX_KIND = "todo"


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
    or a fixed literal like write_translate_note's "todo") already knows it is one of the four."""
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
# otherwise never gets it, T46).
# ---------------------------------------------------------------------------

_HOOK_COMMAND_PREFIX = 'P=""; for c in python3 python'


def _hook_command_suffix(event: str) -> str:
    """The current (post-B126) form: the invocation ends by handing dispatch.py the path this
    command built into `$D` earlier — `"${CLAUDE_PROJECT_DIR:-.}"` anchored, never a bare relative
    ".act/hooks/dispatch.py" (see .act/bridges/settings.hooks.json). A relative path is read
    against the *hook's own* current directory, which a Bash tool's own lasting `cd` moves for the
    rest of the session (B126, 2026-09-25) — Python then can't find the file and exits 2, which
    Claude Code reads as "block", for every tool call, not just Bash's."""
    return f'"$P" "$D" {event}'


def _hook_command_suffix_old_form(event: str) -> str:
    """The pre-B126 form (bare relative ".act/hooks/dispatch.py"), still recognized by
    is_ours_hook so update.py's reconcile replaces it with the current form instead of leaving it
    behind as an unrecognized, un-mergeable duplicate in a project that has not run update.py
    since B126."""
    return f'"$P" .act/hooks/dispatch.py {event}'


# Per event, every extra fixed argument this template's own hooks may pass dispatch.py beyond the
# plain "dispatch.py <event>" call — currently only UserPromptSubmit's dedicated "/act" fast-path
# entry (T67, .act/bridges/settings.hooks.json), a second, synchronous hook for that one event
# next to the plain async one, reaching dispatch.py's own early-exit branch (see its header). Not
# a general "any extra args count" rule on purpose (see is_ours_hook's docstring) — each variant
# is listed here explicitly, same precision as the plain suffix itself.
_HOOK_COMMAND_EXTRA_ARGS: dict[str, tuple[str, ...]] = {
    "UserPromptSubmit": ("--act-check",),
}


def _hook_command_suffixes(event: str) -> list[str]:
    """Every exact tail this template's own hook commands for `event` are known to end with,
    current form first: the current $D-anchored form, the pre-B126 bare-relative form (still
    produced by a project that has not run update.py since B126), and, for the one event with an
    extra fixed argument, each of those two with that argument appended too."""
    bases = [_hook_command_suffix(event), _hook_command_suffix_old_form(event)]
    extra_args = _HOOK_COMMAND_EXTRA_ARGS.get(event, ())
    return bases + [f"{base} {extra}" for base in bases for extra in extra_args]


def is_ours_hook(hook, event: str) -> bool:
    """True if `hook` (one item of a settings.json hook-entry's own "hooks" list) is exactly this
    template's generated wrapper for `event` — matched by its *exact* command text (review T46
    finding 3, replacing an earlier substring check): the fixed interpreter-detection prologue
    this template always uses, ending in the literal dispatch.py invocation for this event (one of
    _hook_command_suffixes(event) — current or pre-B126 form, normally one fixed-argument variant
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
    that hook (T46 review finding 3). Non-dict entries are left exactly where they are. Returns
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
    shape this template's merge was never meant to repair (T46 review finding 6) — the caller
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
    `current["statusLine"]` via merge_settings_status_line() (T76 Welle D, Q106a) — a second,
    unrelated top-level key of the same settings.json, folded into this one function rather than
    given its own call site so init.py's/update.py's existing single call to this function (see
    _merge_settings_hooks) picks it up without either needing to change. A change there is reported
    back the same way a changed hook event is: by the literal string "statusLine" appearing in the
    returned `changed_events` list, even though it is not itself an event name — every caller of
    this function only ever joins that list into a message or checks whether it is empty, never
    matches an entry against a specific event name (T76 Welle D review). Returns
    (new_settings, changed_events) — changed_events is empty when every event's entries and the
    status line already match the bridge, the caller's signal to leave the file on disk untouched.
    Never raises: a malformed `current`/`bridge_data` (not a dict, "hooks" not a dict, an event's
    value not a list, ...) is treated as empty rather than crashing --catch-up (T46 review finding
    6); a caller that wants to report the shape as invalid instead of silently normalizing it checks
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
# statusLine (T76 Welle D, Q106a) — Claude Code's persistent status line, one small script
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
    CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR=1, B126: without it a Bash tool's own `cd` survives
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


def _classify_block_lines(
    existing_text: str, block_text: str, applied_lines: Optional[list[str]],
) -> tuple[list[str], list[str]]:
    """Shared by merge_text_block() and text_block_conflicts(). Candidates are the block's lines
    not yet accounted for: if `applied_lines` is given (this file's .act-lock.json §
    bridges_applied[<name>] from the last time this bridge was applied), only lines new *since*
    that recorded state — so a line the project has since deliberately deleted is never silently
    reinstated, only what the template genuinely added since then. Without a recorded state (an
    old project, from before this tracking existed) this falls back to "add whatever is missing
    from the file", same as before (T46 review finding 4). Of the candidates, one already present
    verbatim needs nothing; one conflicting with the project's own line — a gitignore `!pattern`
    negation, or, for a multi-token line such as a .gitattributes entry, a different existing line
    for the same leading pattern — is never applied, only reported back as a conflict."""
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
    for line in candidates:
        if line in existing_set:
            continue
        if not line.strip() or line.lstrip().startswith("#"):
            to_add.append(line)
            continue
        if ("!" + line) in existing_set:
            conflicts.append(line)
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
                conflicts.append(line)
                continue
        to_add.append(line)
    return to_add, conflicts


def merge_text_block(
    existing_text: str, block_text: str, applied_lines: Optional[list[str]] = None,
) -> tuple[str, list[str]]:
    """Appends whatever lines of `block_text` still need adding (see _classify_block_lines) to
    `existing_text`, as a single appended chunk in the block's own order — not the whole block
    wholesale, so a project that only has an older subset of it gets just the missing lines (T46).
    Returns (new_text, added_lines); added_lines is empty when nothing needed to change, the
    caller's signal to leave the file untouched. A single blank line separates the appended chunk
    from existing content; an empty `existing_text` gets the chunk verbatim. A candidate that
    conflicts with the project's own line (see _classify_block_lines) is silently left out of both
    — never applied, and not "added" — callers that want to report it use
    text_block_conflicts()."""
    to_add, _conflicts = _classify_block_lines(existing_text, block_text, applied_lines)
    if not to_add:
        return existing_text, []
    added_text = "\n".join(to_add) + ("\n" if block_text.endswith("\n") else "")
    if not existing_text:
        new_text = added_text
    elif existing_text.endswith("\n"):
        new_text = existing_text + "\n" + added_text
    else:
        new_text = existing_text + "\n\n" + added_text
    return new_text, to_add


def text_block_conflicts(
    existing_text: str, block_text: str, applied_lines: Optional[list[str]] = None,
) -> list[str]:
    """The subset of merge_text_block()'s candidate lines that were *not* applied because the
    project already carries a conflicting line for the same pattern (T46 review finding 4) — for
    a caller that wants to name them in its summary instead of silently leaving them out."""
    _to_add, conflicts = _classify_block_lines(existing_text, block_text, applied_lines)
    return conflicts


# ---------------------------------------------------------------------------
# Tool identifiers — canonical id vs. accepted variant spellings for one `docs/ai/config.md` §
# Project `tools` entry. Canonical is the short form init.py itself writes there and gates
# SKILL_TARGET_DIRS with ("codex"/"copilot"/"gemini"/"cursor"/"claude-code"/"aider"/"cline"/
# "ollama") — the same set adopt_config.TOOL_MAP maps onto. .act/tiers.json historically used the
# CLI-flavoured "codex-cli"/"copilot-cli"/"gemini-cli" for the same three tools; a project's
# `tools` value written in that spelling silently matched no SKILL_TARGET_DIRS gate at all, so no
# .agents/skills/ was ever created for it (F10, T60). Callers normalize through this table instead
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


def header_block(text: str) -> str:
    """The file's leading run of "key: value" header lines (e.g. "id:", "status:", "for:",
    "created:") — stops at the first blank line or any line that is not itself a header field,
    typically the first Markdown heading. Every place that reads such a field searches this
    substring, never the whole file, so a value can never be spoofed by an example, a fenced code
    block, or another file's header merely quoted in a journal entry (`entries.py`, `board.py`)."""
    lines: list[str] = []
    for line in text.splitlines():
        if not line.strip() or not _HEADER_FIELD_RE.match(line):
            break
        lines.append(line)
    return "\n".join(lines)


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 digest of the file at `path`, read in chunks."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_text_lf(path: Path, text: str) -> None:
    """Write `text` to `path` as UTF-8 with `\\n` line endings regardless of platform default.
    Every generated bridge and scaffold/docs file must come out the same way `.gitattributes`
    (`* text=auto eol=lf`) checks the very same file out as — otherwise the "unchanged since
    generated" hash comparison in .act-local/cache.json flips on nothing but the checkout's own
    line endings (B134). `open()`'s own `newline` parameter has always accepted this value, unlike
    `Path.write_text(..., newline=...)` (Python 3.10+), which this project's floor (3.9) lacks."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def normalized_sha256(path: Path) -> str:
    """SHA-256 of `path` with CRLF folded to LF first — unless it holds a NUL byte (binary) — the
    same folding manifest.py's content_hash() applies to every file under .act/. A generated
    bridge or scaffold file checked out or written with CRLF must hash the same as its LF
    counterpart (B134), so a comparison against this hash never flips on line endings alone."""
    data = path.read_bytes()
    if b"\x00" not in data:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def generated_hash(path: Path) -> str:
    """The hash to record in .act-local/cache.json's "generated" map right after (re)writing a
    generated file: normalized_sha256(), so the recorded value reads the same back regardless of
    which platform generated it (B134)."""
    return normalized_sha256(path)


def generated_unchanged(path: Path, recorded_hash: str) -> bool:
    """True if `path` still matches what .act-local/cache.json's "generated" map recorded for it
    at generation time. Compared with line endings normalized first (normalized_sha256()), so a
    checkout's line endings alone never make an untouched generated file look "changed locally"
    (B134). A cache entry from before this fix recorded the raw-byte hash (sha256_file()) — that
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
