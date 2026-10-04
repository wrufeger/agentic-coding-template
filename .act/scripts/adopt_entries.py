#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Batch writer for the content step of an adoption (skill `act-adopt`). The model reads
#          the old material in whatever format it has and writes one JSON list of entries; this
#          script only checks that list and writes one entry file per item — task/backlog/ledger/
#          question/todo/report/note through entries.py's own validate_entry()/create_entry() (the
#          same files `entries.py new` writes; "question"/"todo"/"report"/"note" all land under
#          docs/ai/inbox/ now — "question" keeps its `Q<n>`, "todo" its `U<n>`
#          id, report and note never carry one), "proposal" through its own write_proposal() below
#          (proposals are not one of entries.py's kinds: no id, filed straight under
#          docs/ai/proposals/ with the header its own README asks for). "inbox" is accepted as an
#          old-batch alias for "todo" (normalized before anything else runs) so a batch written
#          against the old format still works. It decides nothing: on the first doubt the whole
#          batch is refused and nothing is written.
#          Old ids of the kind's own scheme are kept ("id"); any other old number goes into
#          "formerly" and the entry gets the next free id (solo) or none yet (team) — a proposal
#          never has an id either way. The body is written exactly as given, so the human's wording
#          survives byte for byte; a name collision on disk (proposal or any other kind) never
#          overwrites, entries.py's own _create_unique() appends a numeric suffix instead.
#          Afterwards <target>/.act-local/adopt/entries-map.json says which new file came from which
#          source (path and line), so the skill can fill in the adoption table's targets and "done".
#          Stdlib only.
#
# Usage:
#   python .act/scripts/adopt_entries.py --target <project> --from <batch.json> --plan   # check, show
#   python .act/scripts/adopt_entries.py --target <project> --from <batch.json>          # write
#
# Batch format (UTF-8 JSON): a list, or {"entries": [...]}, of objects with the keys
#   kind       task | backlog | question | todo | report | note | proposal | reserved  (required)
#              ("inbox" is accepted too, an alias for "todo" from before the one-inbox migration)
#   title      one line, becomes the heading (reserved: a short reason, kept for traceability only)
#   source     {"path": "<old file>", "line": <n>} or "<old file>:<n>"            (required)
#   id         keep this id: T/B/Q/U<n>, optional sub-letter (task/backlog/question/todo, or required
#              for "reserved" — the old id that never gets a live entry but must stay unused)
#   formerly   the old id of another scheme, written as "formerly: <old id>"
#   body       text below the heading, verbatim   | body_file  a UTF-8 file holding it instead
#   status     open | answered | done (question/todo/report/note) | for   recipient identity
#              (task/todo/report/note — a question is always "for: all"; a task without one
#              gets this checkout's identity)
#   target     rules | coding | checklists | config               (proposal only, required)
#   author     free text for the header                (proposal only; default: see below)
# Unknown keys are refused, so a misspelt field is never dropped silently. "target"/"author" on
# anything but a proposal, "id"/"status"/"for" on a proposal, or "formerly"/"status"/"for"/"target"/
# "author"/"body"/"body_file" on a reserved item are refused the same way — a proposal never
# carries an id, and docs/ai/proposals/README.md's header has no room for them; a reserved item
# writes no file at all, only its id.
# "ledger" is deliberately not a kind here: a journal/protocol source is always a `log` row in the
# adoption table (action "legacy"), never reinterpreted as a new entry.
# A source whose scan or table note marks it protected (adopt.py's own PROTECTED_MARKERS — "never
# bridge"/"git-ignored/local": a local, git-ignored file adopt.py itself never moves or deletes) is
# refused for every kind, on the script's own account — not merely because the skill text said so.
#
# Output format:
#   A "refused:" block listing every problem (stderr, exit 1), or one line per entry
#   ("would create" / "created" <kind> <id> <path> <- <source>, "reserved"/"already reserved
#   <id>" for a reserved item, "skipped (already written, unchanged)" for an item a stopped
#   earlier run already wrote byte-for-byte), a per-kind count line, and the map path.
#   Exit 0 on success and on --plan; 1 if refused or a write failed midway (the map then lists what
#   was written, and a re-run with the same batch picks up where it stopped instead of refusing the
#   whole batch again); 2 on a usage error (target missing, no .act/, unreadable batch).

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import actlib  # noqa: E402
import entries  # noqa: E402

MAP_PATH = Path(".act-local/adopt/entries-map.json")
FIELDS = {"kind", "title", "source", "id", "formerly", "body", "body_file", "status", "for",
          "target", "author"}
PROPOSAL_KIND = "proposal"
PROPOSAL_TARGETS = {"rules", "coding", "checklists", "config"}
PROPOSAL_DIR = Path("docs/ai/proposals")
RESERVED_KIND = "reserved"
RESERVED_ONLY_FIELDS = {"formerly", "status", "for", "target", "author", "body", "body_file"}
# The kinds this batch format accepts (usage comment above, "kind" row) — deliberately narrower
# than entries.py's own KIND_DIR: "ledger" is a valid entries.py kind but never a valid one here
# (header comment above, "\"ledger\" is deliberately not a kind here") — a journal/protocol source
# is always a `log` row in the adoption table, never reinterpreted as an entry through this script.
# "inbox" is kept here only as an old-batch alias, normalized to "todo" in load_batch() before
# anything else sees it.
ADOPT_KINDS = {"task", "backlog", "question", "todo", "report", "note", "inbox",
               PROPOSAL_KIND, RESERVED_KIND}

# adopt.py's own scan/table notes and protection markers, read here
# read-only (mirrors adopt.py's _note_of()/_is_protected(), never imports adopt.py itself — that
# module has heavier side effects on import than this script needs).
SCAN_PATH = Path(".act-local/adopt/scan.json")
TABLE_PATH = Path(".act-local/adopt/table.json")
PROTECTED_MARKERS = ("never bridge", "git-ignored/local")


class Refused(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("refused")
        self.problems = problems


def _read_json(path: Path) -> Optional[object]:
    try:
        return json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _source(value: object) -> Optional[tuple[str, Optional[int]]]:
    """(path, line) from {"path", "line"} or "path:line"; None if it is neither."""
    if isinstance(value, dict) and isinstance(value.get("path"), str) and value["path"].strip():
        line = value.get("line")
        return (value["path"].strip(), line) if line is None or (isinstance(line, int) and line > 0) else None
    if isinstance(value, str) and value.strip():
        path, sep, line = value.strip().rpartition(":")
        if sep and line.isdigit() and path:
            return path, int(line)
        return value.strip(), None
    return None


def _encodable(value: str) -> bool:
    try:
        value.encode("utf-8")
        return True
    except UnicodeEncodeError:
        return False


def _label(src: tuple[str, Optional[int]]) -> str:
    return f"{src[0]}:{src[1]}" if src[1] else src[0]


def _default_author(src: Optional[tuple[str, Optional[int]]]) -> str:
    return f"adopted (formerly {_label(src)})" if src else "adopted"


def _protected_sources(root: Path) -> set[str]:
    """Every scan.json path whose scan or table note marks it protected — same two markers, same
    "scan note; table note" join as adopt.py's own _note_of()/_is_protected(). Missing or unreadable scan.json/table.json: nothing is known protected here (adopt.py
    itself refuses --apply/--finish long before this script would ever run against such a
    target)."""
    scan = _read_json(root / SCAN_PATH) or {}
    table = _read_json(root / TABLE_PATH) or {}
    scan_notes = {r.get("path"): r.get("note") or "" for r in scan.get("rows", []) if isinstance(r, dict)}
    table_notes = {r.get("path"): r.get("note") or "" for r in table.get("rows", []) if isinstance(r, dict)}
    protected = set()
    for path in set(scan_notes) | set(table_notes):
        note = "; ".join(n for n in (scan_notes.get(path), table_notes.get(path)) if n)
        if any(marker in note for marker in PROTECTED_MARKERS):
            protected.add(path)
    return protected


def _key(rel: str) -> str:
    """Comparison key for a relative path — mirrors adopt.py's own _key()/_at_or_below() (case-
    folded where the file system is, "\\" normalized to "/"), so a protected *folder* row (e.g.
    ".act-local", noted "git-ignored/local") is compared on "/" boundaries here exactly as
    adopt.py itself compares it, instead of drifting into two different notions of "below"."""
    return os.path.normcase(rel).replace("\\", "/")


def _source_is_protected(path: str, protected: set[str]) -> bool:
    """Whether `path` is a protected scan/table row itself, or sits *below* one that names a
    folder — a folder-level "never bridge"/"git-ignored/local" row must
    guard every file under it, not just an exact match on that row's own path. Compared at "/"
    segment boundaries, so a protected row "foo" never falsely protects "foobar/baz.txt"."""
    key = _key(path)
    return any(key == _key(p) or key.startswith(_key(p) + "/") for p in protected)


def merge_reserved_ids(root: Path, ids: list[str]) -> list[str]:
    """Merge `ids` into entries.RESERVED_IDS_PATH (a plain {"ids": [...]} list, deduplicated) so
    entries.py's _next_id() keeps landing above an old id the content step decided not to give a
    live entry at all. Returns the ids that were actually new — an id already present is
    silently idempotent, the same "retry is harmless" contract every other kind here has."""
    path = root / entries.RESERVED_IDS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    current: set[str] = set()
    for old_path in (path, root / entries.RESERVED_IDS_OLD_PATH):  # carry the old place's ids over
        data = _read_json(old_path)
        if isinstance(data, dict):
            current |= set(data.get("ids", []))
    new = sorted(i for i in ids if i not in current)
    if new:
        path.write_text(json.dumps({"ids": sorted(current | set(ids))}, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    return new


def write_proposal(root: Path, item: dict) -> Path:
    """Write one proposal file under docs/ai/proposals/ — not one of entries.py's own kinds (no
    id, no KIND_DIR entry): the skeleton's own docs/ai/proposals/README.md asks for a header
    naming author, date and target, one file per proposed change. Reuses entries.py's own
    _slugify()/_create_unique() so a name collision never overwrites an existing file — a numeric
    suffix is appended instead, same as every other kind here."""
    entry_dir = root / PROPOSAL_DIR
    entry_dir.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    header = f"author: {item['author']}\ndate: {today}\ntarget: {item['target']}\n\n"
    text = header + f"# {item['title']}\n\n" + item["body"]
    return entries._create_unique(entry_dir, f"{today}-{entries._slugify(item['title'])}.md", text)


def load_batch(batch_path: Path, root: Path) -> list[dict]:
    """The batch as a list of normalized items, or Refused with every problem found."""
    data = _read_json(batch_path)
    if isinstance(data, dict):
        data = data.get("entries")
    if not isinstance(data, list):
        raise Refused([f"{batch_path}: expected a JSON list (or {{\"entries\": [...]}}) in UTF-8"])
    protected = _protected_sources(root)
    problems: list[str] = []
    items: list[dict] = []
    seen_ids: dict[str, str] = {}
    seen_keys: set = set()
    for index, raw in enumerate(data, 1):
        where = f"entry {index}"
        if not isinstance(raw, dict):
            problems.append(f"{where}: not an object")
            continue
        unknown = sorted(set(raw) - FIELDS)
        if unknown:
            problems.append(f"{where}: unknown key(s) {', '.join(unknown)}")
        kind, title = raw.get("kind"), raw.get("title")
        if kind == "inbox":  # old-batch alias, normalized once here (see ADOPT_KINDS comment)
            kind = "todo"
        src = _source(raw.get("source"))
        if src is None:
            problems.append(f"{where}: \"source\" missing or malformed (path and optional line > 0)")
        else:
            where = f"entry {index} ({_label(src)})"
        text_fields = {k: raw.get(k) for k in ("id", "formerly", "status", "for", "body", "body_file",
                                               "target", "author")}
        bad_types = [k for k, v in text_fields.items() if v is not None and not isinstance(v, str)]
        if not isinstance(kind, str) or not isinstance(title, str) or bad_types:
            problems.append(f"{where}: kind and title must be strings" +
                            (f"; not a string: {', '.join(bad_types)}" if bad_types else ""))
            continue
        # JSON admits lone surrogates ("\ud800"); they cannot be written as UTF-8 and would stop
        # the batch midway — refuse them here, before anything is written.
        unencodable = [k for k, v in (("title", title), *text_fields.items()) if isinstance(v, str) and not _encodable(v)]
        if unencodable:
            problems.append(f"{where}: not encodable as UTF-8 (lone surrogate): {', '.join(unencodable)}")
            continue
        if kind not in ADOPT_KINDS:
            problems.append(f"{where}: unknown kind {kind!r} "
                            "(task | backlog | question | todo | report | note | proposal | reserved)")
            continue
        # Refused on the script's own account, for every kind — not left to
        # the skill text alone.
        if src is not None and _source_is_protected(src[0], protected):
            problems.append(f"{where}: source {src[0]!r} is protected (adopt.py's scan/table note: "
                            "\"never bridge\" or \"git-ignored/local\") — its content is never adopted")
        if kind == RESERVED_KIND:
            if not entries._single_line(title):
                problems.append(f"{where}: a one-line, non-empty title is required")
            id_value = raw.get("id")
            if not isinstance(id_value, str) or not id_value.strip():
                problems.append(f"{where}: \"id\": required for a reserved item (the old id that must stay unused)")
            else:
                match = entries._ID_ARG_RE.match(id_value.strip())
                if not match or match.group(1).upper() not in entries.KIND_PREFIX.values():
                    problems.append(f"{where}: \"id\" {id_value!r}: must be T/B/Q/U<n> (optional sub-letter)")
            forbidden = sorted(k for k in RESERVED_ONLY_FIELDS if raw.get(k) is not None)
            if forbidden:
                problems.append(f"{where}: {', '.join(forbidden)}: a reserved item only takes id/title/source "
                                "(it writes no file)")
        elif kind == PROPOSAL_KIND:
            if not entries._single_line(title):
                problems.append(f"{where}: a one-line, non-empty title is required")
            for forbidden in ("id", "status", "for"):
                if raw.get(forbidden) is not None:
                    problems.append(f"{where}: {forbidden!r}: a proposal never takes one "
                                    "(docs/ai/proposals/README.md's header has no room for it)")
            if raw.get("formerly") is not None:
                problems.append(f"{where}: \"formerly\": a proposal never takes one "
                                "(its origin is carried by \"author\"/\"source\" instead)")
            target = raw.get("target")
            if not isinstance(target, str) or target.strip() not in PROPOSAL_TARGETS:
                problems.append(f"{where}: \"target\" must be one of "
                                f"{', '.join(sorted(PROPOSAL_TARGETS))} (a proposal, not the "
                                "adoption table's own \"target\")")
            author = raw.get("author")
            if author is not None and not entries._single_line(author):
                problems.append(f"{where}: \"author\" must be a one-line, non-empty value")
        else:
            status = raw.get("status")
            # entries.validate_entry() only knows entries.py new's own "open"/"answered" — "done"
            # is an adoption-only value (an old, already-settled entry) for a question
            # or another inbox kind; it never blocks validate_entry's other checks, and the "done"
            # value itself is still written below (create_entry() writes status verbatim).
            checked_status = None if status == "done" and kind in actlib.INBOX_KINDS else status
            for problem in entries.validate_entry(None, kind, title, raw.get("id"), raw.get("formerly"),
                                                  checked_status, raw.get("for")):
                problems.append(f"{where}: {problem.replace('--', '')}")
            if raw.get("target") is not None or raw.get("author") is not None:
                problems.append(f"{where}: \"target\"/\"author\" only apply to a proposal entry")
        body = raw.get("body")
        if raw.get("body_file") is not None:
            if body is not None:
                problems.append(f"{where}: give body or body_file, not both")
            body_path = Path(raw["body_file"])
            body_path = body_path if body_path.is_absolute() else root / body_path
            try:
                body = body_path.read_bytes().decode("utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                problems.append(f"{where}: body_file {raw['body_file']}: cannot read as UTF-8 ({exc.__class__.__name__})")
        entry_id = entries._canonical_id(raw["id"].strip()) if raw.get("id") else None
        if entry_id:
            if entry_id in seen_ids:
                problems.append(f"{where}: id {entry_id} twice in the batch (also {seen_ids[entry_id]})")
            seen_ids[entry_id] = where
        if src:
            key = (src, kind, title.strip())
            if key in seen_keys:
                problems.append(f"{where}: the same source, kind and title twice in the batch")
            seen_keys.add(key)
        author = raw.get("author") if kind == PROPOSAL_KIND else None
        items.append({"kind": kind, "title": title.strip(), "source": src, "id": entry_id,
                      "formerly": raw.get("formerly"), "status": raw.get("status"),
                      "for": raw.get("for"), "body": body or "",
                      "target": (raw.get("target") or "").strip() if kind == PROPOSAL_KIND else None,
                      "author": (author.strip() if author else _default_author(src)) if kind == PROPOSAL_KIND else None})
    if problems:
        raise Refused(problems)
    return items


def read_map(root: Path) -> dict:
    data = _read_json(root / MAP_PATH)
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return {"entries": [], "by_source": {}}
    data.setdefault("by_source", {})
    return data


def _strip_volatile(text: str) -> str:
    """Drop the one header line that always differs between two writes of the very same content —
    a `created:` timestamp (entries.py's create_entry()) or a `date:` line (write_proposal(), which
    stamps today's date) — so two otherwise-identical texts compare equal below."""
    # Header only (up to the first blank line): the same line inside a body is content. Line
    # endings are unified first -- read_text() already folds CRLF, the expected text may not.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    head, sep, body = text.partition("\n\n")
    head = "\n".join(line for line in head.split("\n") if not line.startswith(("created: ", "date: ")))
    return head + sep + body


def _expected_text(row: dict, item: dict, root: Optional[Path] = None) -> str:
    """The exact file text this run would produce for `item`, mirroring entries.create_entry()/
    write_proposal() header-for-header — using the id this row already carries (an explicit
    `item["id"]` was already checked to match `row["id"]` by the caller; an auto-assigned one keeps
    whatever id the earlier run happened to hand out). A placeholder `created:`/`date:` line is
    included so _strip_volatile() drops it from both this text and the file's real one alike."""
    if item["kind"] == PROPOSAL_KIND:
        header = f"author: {item['author']}\ndate: PLACEHOLDER\ntarget: {item['target']}\n\n"
        return header + f"# {item['title']}\n\n" + (item["body"] or "")
    # "question"/"todo"/"report"/"note" all now live under docs/ai/inbox/ (actlib.INBOX_KINDS) and
    # carry a `kind:` header line, id/formerly/kind/for/status/created in that exact order -- kept
    # in sync with entries.create_entry() header-for-header, same as the rest of this function.
    header_lines: list[str] = []
    entry_id = row.get("id")
    if entry_id:
        header_lines.append(f"id: {entry_id}")
    if item["formerly"] is not None:
        header_lines.append(f"formerly: {item['formerly'].strip()}")
    if item["kind"] == "task":
        # a task carries `for:` too (create_entry(): the item's value, else this identity)
        task_for = (entries._recipient_value(item["for"]) if item["for"] is not None
                    else entries._own_identity(root))
        if task_for:
            header_lines.append(f"for: {task_for}")
    if item["kind"] in actlib.INBOX_KINDS:
        header_lines.append(f"kind: {item['kind']}")
        header_lines.append("for: all" if item["kind"] == "question"
                            else f"for: {entries._recipient_value(item['for'])}")
        header_lines.append(f"status: {item['status'] or 'open'}")
    header_lines.append("created: PLACEHOLDER")
    return "\n".join(header_lines) + "\n\n" + f"# {item['title'].strip()}\n\n" + (item["body"] or "")


def _row_file(root: Path, row: dict) -> Optional[Path]:
    """The file `row` (an entries-map.json row from a previous, possibly stopped, run) points to,
    or None if it cannot be found at all. Tolerant of the docs/ai/questions/ -> docs/ai/inbox/
    migration: if the row's own path no longer exists,
    the same filename is tried under actlib.INBOX_DIR instead — a row surviving from before the
    migration would otherwise look unwritten and adopt the same entry a second time."""
    path = root / str(row.get("file", ""))
    if path.is_file():
        return path
    moved = root / actlib.INBOX_DIR / path.name
    return moved if moved.is_file() else None


def _row_matches(root: Path, row: dict, item: dict) -> bool:
    """Whether `row` (an entries-map.json row from a previous, possibly stopped, run) already
    holds this exact item: a re-run of the same batch then skips it instead of
    refusing the whole batch as "already adopted". Compares id/formerly (and, for a proposal,
    target/author) as a cheap early exit, then the file's own text against _expected_text(),
    volatile timestamp line stripped from both — the *whole* reconstructed text, not merely a
    trailing-body check, so a shortened or emptied body, or a changed status/for, is a real
    conflict, not a retry, and stays refused (`text.endswith(body)` used to
    let a truncated body and, worse, an emptied one (`return True` unconditionally) slip through as
    "unchanged", and status/for were never compared at all)."""
    if item["id"] and (row.get("id") or None) != item["id"]:
        return False  # a kept id must match; an auto-assigned one (item["id"] is None) never asked for a
        # particular id in the first place, so whatever id the earlier run happened to hand out is fine
    if (row.get("formerly") or None) != (item["formerly"] or None):
        return False
    if item["kind"] == PROPOSAL_KIND:
        if (row.get("proposal_target") or None) != (item["target"] or None):
            return False
        if (row.get("author") or None) != (item["author"] or None):
            return False
    path = _row_file(root, row)
    if path is None:
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return _strip_volatile(text) == _strip_volatile(_expected_text(row, item, root))


def check_target(root: Path, items: list[dict], mapping: dict) -> tuple[list[str], dict[int, str]]:
    """(problems, skip): conflicts with what is already on disk — a kept id that is taken (an
    entry or the archive — never a legacy collection file, see entries.used_ids()), an item
    adopted before with different content — and, separately, `skip`: index -> file for an item a
    previous run already wrote byte-for-byte (see _row_matches()). A reserved item (no
    file, entries.RESERVED_IDS_PATH instead) is never "done" here — merging it is idempotent on
    its own, checked in run()."""
    problems: list[str] = []
    used = {kind: entries.used_ids(root, kind) for kind in entries.KIND_PREFIX}
    done = {}
    for row in mapping["entries"]:
        if isinstance(row, dict) and _row_file(root, row) is not None:
            # "kind" is normalized the same way load_batch() already normalized item["kind"]
            # ("inbox" -> "todo") — an older map row written before that alias existed would
            # otherwise never match here, and the same source/title would be adopted a second time.
            row_kind = entries._canonical_kind(row.get("kind")) if isinstance(row.get("kind"), str) else row.get("kind")
            done[(row.get("source_path"), row.get("source_line"), row_kind, row.get("title"))] = row
    skip: dict[int, str] = {}
    for index, item in enumerate(items):
        if item["kind"] == RESERVED_KIND:
            continue
        src = item["source"]
        row = done.get((src[0], src[1], item["kind"], item["title"]))
        if row and _row_matches(root, row, item):
            skip[index] = row["file"]
            continue
        if item["id"] and item["id"] in used.get(item["kind"], set()):
            problems.append(f"{_label(src)}: id {item['id']} already taken (an entry or the archive)")
        if row:
            problems.append(f"{_label(src)}: already adopted as {row['file']} with different content "
                            "— resolve by hand")
    return problems, skip


def plan_ids(root: Path, items: list[dict], reserved: tuple[str, ...] = ()) -> None:
    """Fill item["planned"] with the id each item will get: kept ids first (they are written
    first), then the next free ones in batch order — "team" mode leaves those empty.
    `reserved`: this same batch's "reserved" ids. The real run merges
    them into entries.RESERVED_IDS_PATH before it lets entries.create_entry() compute each id
    (see run()), so entries._next_id() already sees them on disk by then; --plan never calls that
    merge, so without also treating them as used here, --plan would show a lower id (e.g. "would
    create task [T3]") than the id the real run then actually hands out (T4) for a "reserved T3" in
    the very same batch."""
    team = entries._mode(root) == "team"
    kept = tuple(item["id"] for item in items if item["id"]) + reserved
    extra: dict[str, list[str]] = {}
    for item in items:
        if item["id"]:
            item["planned"] = item["id"]
        elif item["kind"] in entries.KIND_PREFIX and not team:
            new_id = entries._next_id(root, item["kind"], kept + tuple(extra.get(item["kind"], [])))
            extra.setdefault(item["kind"], []).append(new_id)
            item["planned"] = new_id
        else:
            item["planned"] = None


def write_map(root: Path, mapping: dict) -> None:
    path = root / MAP_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    by_source: dict[str, list[str]] = {}
    for row in mapping["entries"]:
        by_source.setdefault(row["source_path"], []).append(row["file"])
    mapping["by_source"] = by_source
    path.write_text(json.dumps(mapping, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run(root: Path, batch_path: Path, plan: bool) -> int:
    items = load_batch(batch_path, root)
    mapping = read_map(root)
    problems, skip = check_target(root, items, mapping)
    if problems:
        raise Refused(problems)
    # A "reserved" item writes no file, just an id that must stay unused — merged into
    # entries.RESERVED_IDS_PATH separately below, never through create_entry()/plan_ids().
    # An item a stopped earlier run already wrote byte-for-byte (`skip`) is left alone —
    # neither rewritten nor allowed to consume a fresh id.
    reserved_idx = [i for i, item in enumerate(items) if item["kind"] == RESERVED_KIND]
    write_items = [item for i, item in enumerate(items) if i not in skip and i not in set(reserved_idx)]
    plan_ids(root, write_items, tuple(items[i]["id"] for i in reserved_idx))
    order = [i for i in write_items if i["id"]] + [i for i in write_items if not i["id"]]
    counts: dict[str, int] = {}
    for item in order:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    if reserved_idx:
        counts[RESERVED_KIND] = len(reserved_idx)
    summary = ", ".join(f"{k}: {n}" for k, n in sorted(counts.items()))
    if skip:
        summary += (", " if summary else "") + f"{len(skip)} skipped (already written)"

    if plan:
        for i in sorted(skip):
            print(f"[adopt-entries] skip {items[i]['kind']} (already written, unchanged) {skip[i]} "
                  f"<- {_label(items[i]['source'])}")
        for i in reserved_idx:
            item = items[i]
            print(f"[adopt-entries] would reserve {item['id']} (never reused) <- {_label(item['source'])}")
        for item in order:
            tag = item["planned"] or "no id"
            if item["id"]:
                tag += " (kept)"
            if item["formerly"]:
                tag += f", formerly {item['formerly'].strip()}"
            print(f"[adopt-entries] would create {item['kind']} [{tag}] {item['title']!r} <- {_label(item['source'])}")
        print(f"[adopt-entries] {summary} — plan only, nothing written")
        return 0

    for i in sorted(skip):
        print(f"[adopt-entries] skipped {items[i]['kind']} (already written, unchanged) {skip[i]} "
              f"<- {_label(items[i]['source'])}")
    stamp = datetime.now().isoformat(timespec="seconds")
    try:
        if reserved_idx:
            newly = merge_reserved_ids(root, [items[i]["id"] for i in reserved_idx])
            for i in reserved_idx:
                item = items[i]
                tag = "reserved" if item["id"] in newly else "already reserved"
                print(f"[adopt-entries] {tag} {item['id']} (never reused) <- {_label(item['source'])}")
        for item in order:
            if item["kind"] == PROPOSAL_KIND:
                dest, written_id = write_proposal(root, item), None
            else:
                dest, written_id = entries.create_entry(root, item["kind"], item["title"], item["id"], item["formerly"],
                                                        item["status"], item["for"], item["body"])
            rel = dest.relative_to(root).as_posix()
            mapping["entries"].append({
                "source_path": item["source"][0], "source_line": item["source"][1], "kind": item["kind"],
                "title": item["title"], "id": written_id, "formerly": item["formerly"], "file": rel,
                "written": stamp, "proposal_target": item.get("target"), "author": item.get("author"),
            })
            print(f"[adopt-entries] created {item['kind']} [{written_id or 'no id'}] {rel} <- {_label(item['source'])}")
    except (OSError, UnicodeError) as exc:
        write_map(root, mapping)
        print(f"adopt_entries.py: stopped: {exc} — {MAP_PATH.as_posix()} lists what was written; fix the "
              "cause and run again with the same batch — entries and reserved ids already written are "
              "recognized and skipped, only the rest is written", file=sys.stderr)
        return 1
    write_map(root, mapping)
    print(f"[adopt-entries] {summary}")
    print(f"[adopt-entries] map: {MAP_PATH.as_posix()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adopt_entries.py",
        description="Write a checked batch of adopted entries (tasks, backlog, questions, todos, reports, "
                    "notes, proposals) as entry files; the whole batch is refused on any conflict.",
    )
    parser.add_argument("--target", metavar="DIR", required=True, help="the project (already set up by adopt.py --apply)")
    parser.add_argument("--from", dest="batch", metavar="JSON", required=True, help="the batch file (UTF-8 JSON)")
    parser.add_argument("--plan", action="store_true", help="check and show what would be written, write nothing")
    return parser


def main(argv: list[str]) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    args = build_parser().parse_args(argv)
    root = Path(args.target).expanduser().resolve()
    batch_path = Path(args.batch).expanduser().resolve()
    if not (root / ".act").is_dir():
        print(f"adopt_entries.py: {root} has no .act/ — run adopt.py --apply (or init.py) first", file=sys.stderr)
        return 2
    if not batch_path.is_file():
        print(f"adopt_entries.py: batch file not found: {batch_path}", file=sys.stderr)
        return 2
    os.chdir(root)  # entries.py/actlib read docs/ai/config.md ("mode") from the working directory's project
    try:
        return run(root, batch_path, args.plan)
    except Refused as exc:
        print("refused (nothing written):", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
