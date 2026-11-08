"""Session start, notes: inbox counts and the staleness hints for the docs audit, the dependency check
and archive compaction.

Split out of session.py, which keeps the entry point and the order of the sub-steps."""
from __future__ import annotations

import re
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import actlib

# ---------------------------------------------------------------------------
# Check 2 — session start: inbox count, bridge re-derivation, board refresh,
#           orchestrator-only rules as a fallback short form
# ---------------------------------------------------------------------------

def _current_branch(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    name = result.stdout.strip()
    return name if result.returncode == 0 and name else "unknown"


_STATUS_RE = re.compile(r"^status:\s*(\S+)", re.IGNORECASE)


def _load_statusline():
    """The status line module, loaded by path (it carries the board module); None when either is
    unusable."""
    import importlib.util
    path = Path(__file__).resolve().parent.parent / "statusline.py"
    spec = importlib.util.spec_from_file_location("_act_statusline", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if getattr(module, "board", None) is None or getattr(module, "actlib", None) is None:
        return None
    return module


def _count_inbox_open(root: Path) -> int:
    """Open inbox entries addressed to this identity or to everyone -- the very number the status
    line shows as "waiting for you" (statusline._waiting_summary()), loaded by path so the two can
    never count differently. 0 when the status line module or the board cannot be used."""
    module = _load_statusline()
    return 0 if module is None else module._waiting_summary(root)[0]


def _count_inbox_waiting(root: Path) -> int:
    """
    Count inbox entries that are "answered, not yet processed": a file in actlib.INBOX_DIR (the
    single inbox, one file per entry, every kind — question/todo/report/note)
    whose header says `status: answered`.

    The header carries `for:` (who it is addressed to, absent for a question), `kind:`, and for a
    question an `id:` too — none of which matter here, only `status:` does. `status` runs `open`
    -> `answered` -> `done` (a question keeps that same lifecycle; it used to live
    under docs/ai/questions/, which no longer exists): the human
    (or the assistant, when the answer came up in chat) sets `answered`, and whoever works the
    entry into its place sets `done`. Only `answered` is counted — `open` is still waiting on a
    person, `done` is finished and never appears here. This one count now covers what used
    to be two separate counts (inbox entries and questions) before the two lived in one place.
    """
    # Counted with the board's own classification (board.for_assistant()): an open or answered
    # entry with `triage: open` in its header block, or an answered entry that is not a note; a
    # done entry never counts, an answered note waits for the human.
    module = _load_statusline()
    if module is None:
        return 0
    inbox_entries = module.board.read_inbox_entries(root)
    if inbox_entries is None:
        return 0
    return sum(1 for entry in inbox_entries if module.board.for_assistant(entry))


# ---------------------------------------------------------------------------
# Docs-audit freshness at session start: a hint, never a blocker, on how long ago the
# last full `act-audit-docs` sweep ran (skills/act-audit-docs/SKILL.md: a full pass logs a journal
# entry whose title starts with "act-audit-docs", a spot check of one area does not). "Full" is
# decided purely by that title prefix, never by which files a partial pass touched.
# ---------------------------------------------------------------------------

_DOCS_AUDIT_TITLE_PREFIX = "act-audit-docs"
_LEDGER_HEADING_RE = re.compile(r"^#\s+(.*)$")
_LEDGER_CREATED_RE = re.compile(r"^created:\s*(.+)$", re.IGNORECASE)
_LEDGER_DATE_IN_NAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-")


def _parse_docs_audit_due(raw: str) -> "tuple[int, int]":
    """Parse the `docs-audit-due` value (docs/ai/config.md § Docs audit), e.g. "30d/100c" -> (30,
    100). Falls back to the template default (30, 100) for a missing or malformed value -- same
    "an unrecognized value is treated as absent" rule _check_mode follows for the block/warn/off
    checks, just for a value shape of its own."""
    match = re.match(r"^\s*(\d+)\s*d\s*/\s*(\d+)\s*c\s*$", raw, re.IGNORECASE)
    if not match:
        return 30, 100
    return int(match.group(1)), int(match.group(2))


def _ledger_entry_date(lines: list[str], filename: str) -> Optional[date]:
    """The date a journal entry counts as made on: the `created:` header field
    (entries.py writes an ISO timestamp there) if present and parseable, else the
    `YYYY-MM-DD-` date prefix every ledger filename carries (entries.py new ledger <title>).
    None if neither yields a usable date."""
    for line in lines[:5]:  # created: is the first header line (second in frontmatter, after ---)
        created_match = _LEDGER_CREATED_RE.match(line.strip())
        if created_match:
            try:
                return datetime.fromisoformat(created_match.group(1).strip()).date()
            except ValueError:
                break
    name_match = _LEDGER_DATE_IN_NAME_RE.match(filename)
    if name_match:
        try:
            return date.fromisoformat(name_match.group(1))
        except ValueError:
            return None
    return None


def _last_ledger_entry_with_prefix(root: Path, title_prefix: str) -> "tuple[Optional[date], bool]":
    """(most recent date of a journal entry whose `# ` heading starts with `title_prefix`, whether
    the ledger directory exists at all). None as the date means either the directory does not
    exist, or it exists but holds no matching entry -- the caller tells the two apart via the
    second element. Shared by `_docs_audit_note` (prefix `act-audit-docs`) and the
    `dependency-check: regularly` staleness note (prefix `act-deps`) rather than each
    keeping its own copy of the same ledger scan.

    Filters by filename first (the ledger filename carries the same slug the heading does,
    `entries.py new ledger <title>`) before reading a file in full: with a project of any size,
    reading every ledger entry just to check its heading is wasteful when the filename already
    rules almost all of them out."""
    ledger_dir = root / "docs" / "ai" / "work" / "ledger"
    if not ledger_dir.is_dir():
        return None, False
    slug_start = title_prefix.lower().replace(" ", "-")
    best: Optional[date] = None
    for path in ledger_dir.glob("*.md"):
        if path.name.lower() == "readme.md":
            continue
        name_lower = path.name.lower()
        # entries.py new ledger <title> names the file "<YYYY-MM-DD>-<slug>.md" -- the slug (the
        # title, lowercased/hyphenated) follows the date prefix, so a filename that does not
        # contain the wanted slug at all cannot hold a matching heading either.
        if slug_start not in name_lower:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        title: Optional[str] = None
        for line in lines:
            heading_match = _LEDGER_HEADING_RE.match(line)
            if heading_match:
                title = heading_match.group(1).strip()
                break
        if title is None or not title.startswith(title_prefix):
            continue
        when = _ledger_entry_date(lines, path.name)
        if when is not None and (best is None or when > best):
            best = when
    return best, True


def _last_docs_audit_entry(root: Path) -> "tuple[Optional[date], bool]":
    """(most recent date of a full act-audit-docs sweep, whether the ledger directory exists at
    all) -- see `_last_ledger_entry_with_prefix`."""
    return _last_ledger_entry_with_prefix(root, _DOCS_AUDIT_TITLE_PREFIX)


def _commits_since(root: Path, when: date) -> int:
    """Number of commits on HEAD authored since `when` (inclusive of that day) -- 0 on any error
    (no git, not a repository, timeout): silence over a wrong number, same as every other
    best-effort sub-step in this module."""
    try:
        # A bare "--since=YYYY-MM-DD" is parsed against the current time of day (review finding
        # c) -- a commit made earlier *today*, before this hook's own clock time, would otherwise
        # be silently excluded from "since `when`". Pinning the time to midnight makes the whole
        # of `when`'s day count, matching what a human reading "since 2026-08-01" expects.
        result = subprocess.run(
            ["git", "rev-list", "--count", f"--since={when.isoformat()}T00:00:00", "HEAD"],
            cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 0
    if result.returncode != 0:
        return 0
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def _docs_audit_note(root: Path, config: dict[str, str]) -> Optional[str]:
    """One-time-per-state hint (never a blocker): how long ago the last full
    `act-audit-docs` sweep ran, in days and commits, once either exceeds the `docs-audit-due`
    threshold; or, once only, that there is no such entry on record yet at all. Only while
    `docs/project/` exists -- nothing to audit otherwise, so neither note fires without it (review
    finding b: the docstring already said this, the "overdue" branch did not actually check it).
    `off` skips the whole check.

    The overdue note is throttled to once a day (review finding a: config.md calls it a "one-time
    note", but a session start recurs many times a day -- including a resume/compact, which is not
    a fresh session in any way that matters here) via `.act-local/cache.json`'s
    `docs_audit_overdue_last_noted`, the same per-day-state pattern `_check_update_awareness`'s
    `_already_checked_today` uses for its own once-a-day network check."""
    if not (root / "docs" / "project").is_dir():
        return None
    raw = config.get("docs-audit-due", "").strip()
    if raw.lower() == "off":
        return None
    days_due, commits_due = _parse_docs_audit_due(raw)

    when, _ledger_exists = _last_docs_audit_entry(root)
    if when is None:
        cache = actlib.read_cache()
        if cache.get("docs_audit_never_noted"):
            return None
        actlib.write_cache({"docs_audit_never_noted": True})
        return "[act] note: no full docs audit on record yet -- act-audit-docs when convenient"

    age_days = (date.today() - when).days
    commits_since = _commits_since(root, when)
    if age_days <= days_due and commits_since <= commits_due:
        return None
    cache = actlib.read_cache()
    today = date.today().isoformat()
    if cache.get("docs_audit_overdue_last_noted") == today:
        return None
    actlib.write_cache({"docs_audit_overdue_last_noted": today})
    return (f"[act] note: docs last fully audited {age_days} days / {commits_since} commits ago "
            "-- act-audit-docs when convenient")


# ---------------------------------------------------------------------------
# `dependency-check: regularly` staleness note at session start: same shape as
# `_docs_audit_note` above (fixed 30-day threshold, no commit count -- `act-deps` has no config.md
# knob for that), reusing `_last_ledger_entry_with_prefix` instead of its own ledger scan.
# ---------------------------------------------------------------------------

_DEPENDENCY_CHECK_TITLE_PREFIX = "act-deps"
_DEPENDENCY_CHECK_DUE_DAYS = 30


def _dependency_check_note(root: Path, config: dict[str, str]) -> Optional[str]:
    """With `dependency-check: regularly`, a note (at most once a day, per state, same pattern as
    `_docs_audit_note`'s own overdue note) once the last `act-deps` run (a journal entry titled
    `act-deps: ...`) is older than 30 days, or once only when none is on record yet. `never` and
    `once` print nothing here: `once` is entirely init.py's one-time inbox
    entry (`entries.write_dependency_check_note`), not a recurring session-start note."""
    mode = config.get("dependency-check", "regularly").strip().lower()
    if mode != "regularly":
        return None
    when, _ledger_exists = _last_ledger_entry_with_prefix(root, _DEPENDENCY_CHECK_TITLE_PREFIX)
    cache = actlib.read_cache()
    if when is None:
        if cache.get("dependency_check_never_noted"):
            return None
        actlib.write_cache({"dependency_check_never_noted": True})
        return ("[act] note: no `act-deps` run on record yet -- act-deps when convenient "
                "(dependency-check: regularly)")
    age_days = (date.today() - when).days
    if age_days <= _DEPENDENCY_CHECK_DUE_DAYS:
        return None
    today = date.today().isoformat()
    if cache.get("dependency_check_overdue_last_noted") == today:
        return None
    actlib.write_cache({"dependency_check_overdue_last_noted": today})
    return (f"[act] note: last act-deps run {age_days} days ago -- act-deps when convenient "
            "(dependency-check: regularly)")


_COMPACT_KEEP_DAYS = 7  # entries archived within the last week stay single files (as `entries.py compact` has it)


def _parse_archive_compact(raw: str) -> "Optional[tuple[int, int]]":
    """Parse the `archive-compact` value (docs/ai/config.md § Archive), e.g. "30d 300" -> (30, 300);
    `off` -> None. A missing or malformed value counts as the default (30, 300)."""
    if raw.strip().lower() == "off":
        return None
    match = re.match(r"^\s*(\d+)\s*d\s+(\d+)\s*$", raw, re.IGNORECASE)
    return (int(match.group(1)), int(match.group(2))) if match else (30, 300)


def _single_entry_days(root: Path, folder: Path, journal: bool) -> "list[date]":
    """The date of every single entry file in `folder`, counted like `entries.py compact` does
    (entries.ArchiveDays: Git only for an archived file without `archived:`). A collection, a README
    and the monthly overview are no single entries."""
    import entries
    days: list[date] = []
    if not folder.is_dir():
        return days
    dating = entries.ArchiveDays(root)
    for path in folder.glob("*.md"):
        if path.name.lower() == "readme.md" or (not journal and re.match(r"^\d{4}-\d{2}\.md$", path.name)):
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if actlib.is_collection(text):
            continue
        try:
            name_day = entries.ArchiveDays.name_day(path, journal, bool(actlib.entry_ids(text)))
        except ValueError:
            continue  # an impossible date in the file name: `compact` leaves the file alone
        days.append(dating.day(path, actlib.header_block(text), journal, name_day))
    return days


def _compact_due_note(root: Path, config: dict[str, str]) -> Optional[str]:
    """With `archive-compact` not `off`, a note (at most once a day) once the archive or the journal
    folder is due for `entries.py compact`: its oldest single entry is older than the day limit, or it
    holds more single files than the count limit, and at least one entry is older than a week. Names
    the number of entries. In team mode only on the default branch, so two branches never write the
    same month file."""
    limits = _parse_archive_compact(config.get("archive-compact", "30d 300"))
    if limits is None:
        return None
    max_days, max_files = limits
    today = date.today()
    stamp = today.isoformat()
    if actlib.read_cache().get("compact_due_last_noted") == stamp:
        return None  # noted today already: skip reading the folders
    if config.get("mode", "solo").strip().lower() == "team":
        import entries
        if _current_branch(root) != entries._default_branch(root):
            return None
    reasons: list[str] = []
    foldable = 0
    for label, folder, journal in (("archive", root / "docs" / "ai" / "work" / "archive", False),
                                   ("journal", root / "docs" / "ai" / "work" / "ledger", True)):
        days = _single_entry_days(root, folder, journal)
        old = sum(1 for day in days if (today - day).days > _COMPACT_KEEP_DAYS)
        if not old:
            continue
        oldest = (today - min(days)).days
        if oldest > max_days:
            reasons.append(f"{label}: oldest entry {oldest} days old")
        elif len(days) > max_files:
            reasons.append(f"{label}: {len(days)} single files")
        else:
            continue
        foldable += old
    if not reasons:
        return None
    actlib.write_cache({"compact_due_last_noted": stamp})
    return (f"[act] note: archive compaction is due ({'; '.join(reasons)}; limits {max_days}d / {max_files} files): "
            f"{foldable} entr(ies) older than {_COMPACT_KEEP_DAYS} days to merge, no worker -- act-compact at the next "
            "task boundary (archive-compact in docs/ai/config.md)")
