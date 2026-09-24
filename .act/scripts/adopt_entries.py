#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Batch writer for the content step of an adoption (skill act-adopt, docs/project/concepts/
#          ai-dev-app/11-build-decisions.md § "Stufe 6" in the template-pflege repo). The model reads
#          the old material in whatever format it has and writes one JSON list of entries; this
#          script only checks that list and writes one entry file per item — task/backlog/question/
#          inbox through entries.py's own validate_entry()/create_entry() (the same files
#          `entries.py new` writes), "proposal" through its own write_proposal() below (proposals
#          are not one of entries.py's kinds: no id, filed straight under docs/ai/proposals/ with
#          the header its own README asks for). It decides nothing: on the first doubt the whole
#          batch is refused and nothing is written.
#          Old ids of the kind's own scheme are kept ("id", Q79 a); any other old number goes into
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
#   kind       task | backlog | question | inbox | proposal                       (required)
#   title      one line, becomes the heading                                      (required)
#   source     {"path": "<old file>", "line": <n>} or "<old file>:<n>"            (required)
#   id         keep this id: T/B/Q<n>, optional sub-letter (task/backlog/question only)
#   formerly   the old id of another scheme, written as "formerly: <old id>"
#   body       text below the heading, verbatim   | body_file  a UTF-8 file holding it instead
#   status     open | answered (question/inbox)   | for        recipient identity (inbox only)
#   target     rules | coding | checklists | config               (proposal only, required)
#   author     free text for the header                (proposal only; default: see below)
# Unknown keys are refused, so a misspelt field is never dropped silently. "target"/"author" on
# anything but a proposal, or "id"/"status"/"for" on a proposal, are refused the same way — a
# proposal never carries an id, and docs/ai/proposals/README.md's header has no room for them.
# "ledger" is deliberately not a kind here: a journal/protocol source is always a `log` row in the
# adoption table (action "legacy"), never reinterpreted as a new entry.
#
# Output format:
#   A "refused:" block listing every problem (stderr, exit 1), or one line per entry
#   ("would create" / "created" <kind> <id> <path> <- <source>), a per-kind count line, and the
#   map path. Exit 0 on success and on --plan; 1 if refused or a write failed midway (the map then
#   lists what was written); 2 on a usage error (target missing, no .act/, unreadable batch).

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import entries  # noqa: E402

MAP_PATH = Path(".act-local/adopt/entries-map.json")
FIELDS = {"kind", "title", "source", "id", "formerly", "body", "body_file", "status", "for",
          "target", "author"}
PROPOSAL_KIND = "proposal"
PROPOSAL_TARGETS = {"rules", "coding", "checklists", "config"}
PROPOSAL_DIR = Path("docs/ai/proposals")
# The kinds this batch format accepts (usage comment above, "kind" row) — deliberately narrower
# than entries.py's own KIND_DIR: "ledger" is a valid entries.py kind but never a valid one here
# (header comment above, "\"ledger\" is deliberately not a kind here") — a journal/protocol source
# is always a `log` row in the adoption table, never reinterpreted as an entry through this script.
ADOPT_KINDS = {"task", "backlog", "question", "inbox", PROPOSAL_KIND}


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
    return entries._create_unique(entry_dir, today, entries._slugify(item["title"]), text)


def load_batch(batch_path: Path, root: Path) -> list[dict]:
    """The batch as a list of normalized items, or Refused with every problem found."""
    data = _read_json(batch_path)
    if isinstance(data, dict):
        data = data.get("entries")
    if not isinstance(data, list):
        raise Refused([f"{batch_path}: expected a JSON list (or {{\"entries\": [...]}}) in UTF-8"])
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
            problems.append(f"{where}: unknown kind {kind!r} (task | backlog | question | inbox | proposal)")
            continue
        if kind == PROPOSAL_KIND:
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
            for problem in entries.validate_entry(None, kind, title, raw.get("id"), raw.get("formerly"),
                                                  raw.get("status"), raw.get("for")):
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


def check_target(root: Path, items: list[dict], mapping: dict) -> list[str]:
    """Conflicts with what is already on disk: a kept id that is taken (an entry or the archive —
    never a legacy collection file, see entries.used_ids()), an item adopted before."""
    problems: list[str] = []
    used = {kind: entries.used_ids(root, kind) for kind in entries.KIND_PREFIX}
    done = {}
    for row in mapping["entries"]:
        if isinstance(row, dict) and (root / str(row.get("file", ""))).is_file():
            done[(row.get("source_path"), row.get("source_line"), row.get("kind"), row.get("title"))] = row["file"]
    for item in items:
        src = item["source"]
        if item["id"] and item["id"] in used.get(item["kind"], set()):
            problems.append(f"{_label(src)}: id {item['id']} already taken (an entry or the archive)")
        previous = done.get((src[0], src[1], item["kind"], item["title"]))
        if previous:
            problems.append(f"{_label(src)}: already adopted as {previous}")
    return problems


def plan_ids(root: Path, items: list[dict]) -> None:
    """Fill item["planned"] with the id each item will get: kept ids first (they are written
    first), then the next free ones in batch order — "team" mode leaves those empty."""
    team = entries._mode(root) == "team"
    kept = tuple(item["id"] for item in items if item["id"])
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
    problems = check_target(root, items, mapping)
    if problems:
        raise Refused(problems)
    plan_ids(root, items)
    order = [i for i in items if i["id"]] + [i for i in items if not i["id"]]
    counts: dict[str, int] = {}
    for item in order:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    if plan:
        for item in order:
            tag = item["planned"] or "no id"
            if item["id"]:
                tag += " (kept)"
            if item["formerly"]:
                tag += f", formerly {item['formerly'].strip()}"
            print(f"[adopt-entries] would create {item['kind']} [{tag}] {item['title']!r} <- {_label(item['source'])}")
        print("[adopt-entries] " + ", ".join(f"{k}: {n}" for k, n in sorted(counts.items())) + " — plan only, nothing written")
        return 0

    stamp = datetime.now().isoformat(timespec="seconds")
    try:
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
        print(f"adopt_entries.py: stopped: {exc} — {MAP_PATH.as_posix()} lists what was written; "
              "fix the cause and run again with the entries not yet written", file=sys.stderr)
        return 1
    write_map(root, mapping)
    print("[adopt-entries] " + ", ".join(f"{k}: {n}" for k, n in sorted(counts.items())))
    print(f"[adopt-entries] map: {MAP_PATH.as_posix()}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="adopt_entries.py",
        description="Write a checked batch of adopted entries (tasks, backlog, questions, inbox, proposals) "
                    "as entry files; the whole batch is refused on any conflict.",
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
