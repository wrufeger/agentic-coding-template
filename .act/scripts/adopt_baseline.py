#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: Baseline check of an existing project before its first commit with this template (skill
#          `act-adopt`). A project taken over has never been through the template's commit checks, so the
#          first commit would be held for patterns that were there long before (an `innerHTML` call, SQL
#          built by concatenation) and a secret in the code would only show up then. This script looks
#          once, read-only by default, and reports:
#            1. `.gitignore`: which secret-file patterns are missing. The names come from the template's
#               own list of secret files (checks/secret_read.py: `.env` variants, private-key names, key
#               and keystore extensions; `.env.example`/`.sample`/`.template` and `*.pub` stay free), never
#               a second list here. A pattern counts as covered when `git check-ignore` already ignores a
#               sample file name of it. Proposed lines are printed; `--write-gitignore` appends them.
#            2. The commit checks, run once over the tracked and the untracked-but-not-ignored files of the
#               target: the secret scan (checks/secret_scan.py `_scan_new_file`, honouring
#               `act:allow-secret` and `docs/ai/local/secret-accepted.md` as the commit does), the
#               dangerous-pattern scan (checks/danger_scan.py `_scan_new_file`, with the coding sets and
#               the `security-check` level of the target's own config) and, for a file whose name is a
#               secret file (git ignoring it later does not help once it is tracked), the name check of
#               secret_read. No pattern is implemented here. Files under `.act/` and `.act-local/` are not
#               scanned, binary files and files over 2 MB are skipped.
#            3. `--book` records the findings as backlog entries in the target through the target's own
#               `entries.py new backlog`. One entry per file for a secret (each one needs its own rotation
#               and removal), one entry per rule for a dangerous pattern (a fix is usually one decision
#               applied to every place). Without `--book` the entries are only listed (dry run). An entry
#               carries a line `baseline: <key>`, so running `--book` again creates nothing twice.
#          A secret value is never printed, written to an entry or logged: file, line and rule only.
#
#          What this does to the first commit. The dangerous-pattern check holds a (reader, file, rule)
#          once and lets the repeat through; `--book` writes the booked `file|rule` keys to
#          `.act-local/danger-scan-hints/baseline.json` (git-ignored, one list for the project), and only
#          the keys whose file a backlog entry names after this run (a booking that failed adds none). The check
#          (checks/danger_scan.py) lets a finding through without that first hold when its exact
#          `file|rule` key is in the list; it reads the list only, never writes it and never copies it into
#          its per-reader hints, and a malformed or linked list counts as empty. The key has no line
#          number, so a later new occurrence of a booked rule in the same file passes too. A secret finding is not
#          silenced by booking: the secret scan holds again on every attempt until the value is removed
#          (and rotated), the line is marked `act:allow-secret`, or the line is listed in
#          `docs/ai/local/secret-accepted.md` (the hold message prints the finished entry).
#
# Usage:
#   python .act/scripts/adopt_baseline.py --target <dir>                       # report + dry run, changes nothing
#   python .act/scripts/adopt_baseline.py --target <dir> --write-gitignore     # also append the missing patterns
#   python .act/scripts/adopt_baseline.py --target <dir> --book                # also create the backlog entries
#
# Output format: sections `.gitignore`, `findings`, `backlog`; one line per finding
#   `  <file>:<line>  <rule>`; the last line `baseline: N finding(s) ...` (or `baseline: nothing to
#   report`). Exit 0 whenever the check ran (findings or not), 2 for a bad target or a failed booking.
#
# Known limits:
#   - the scans read files as they are on disk, not a diff: a line already tracked is reported once, not
#     "added";
#   - without the target's `docs/project/coding_rules.md` (no coding set switched on) or with
#     `security-check: off` the dangerous-pattern scan is skipped, and the output says so;
#   - the dangerous-pattern scan here has no cap: it reports and books every hit of a file (the commit
#     check stops at five, but drops booked keys before it counts);
#   - entries are written in the target's `language-docs` for `en` and `de`, English for any other.

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

_SCRIPTS = Path(__file__).resolve().parent
for _path in (_SCRIPTS, _SCRIPTS.parent / "hooks"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import actlib  # noqa: E402
from checks import danger_scan, secret_read, secret_scan  # noqa: E402

_SKIP_PREFIXES = (".act/", ".act-local/", ".git/")
_BINARY_PROBE = 8192
_BASELINE_HINTS = Path(".act-local") / danger_scan._HINTS_DIRNAME / "baseline.json"
_GITIGNORE_HEADER = "# secret files (added by the act-adopt baseline check)"

# Sample file names per gitignore pattern: a pattern is covered when git ignores its samples.
_ENV_PATTERNS = ((".env", (".env",)), (".env.*", (".env.local", ".env.production")))


def _secret_patterns() -> list[tuple[str, tuple[str, ...]]]:
    """(gitignore pattern, sample names) built from secret_read's own lists, in a stable order."""
    patterns: list[tuple[str, tuple[str, ...]]] = list(_ENV_PATTERNS)
    prefixes = secret_read._SEPARATOR_PREFIXES
    for name in sorted(secret_read._BASENAMES - {".env", "credentials", ".npmrc", *prefixes}):
        patterns.append((name, (name,)))
    for prefix in prefixes:
        patterns.append((f"{prefix}*", (prefix, f"{prefix}-work", f"{prefix}_old")))
    for extension in sorted(secret_read._EXTENSIONS):
        patterns.append((f"*.{extension}", (f"server.{extension}",)))
    return patterns


def _git(target: Path, args: list[str], check_ok: tuple[int, ...] = (0,)) -> Optional[subprocess.CompletedProcess]:
    try:
        done = actlib.git_run(target, args, timeout=60, config=("core.quotePath=false",), text=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done if done.returncode in check_ok else None


def _is_ignored(target: Path, name: str) -> bool:
    done = _git(target, ["check-ignore", "-q", "--no-index", "--", name], check_ok=(0, 1))
    return done is not None and done.returncode == 0


def missing_gitignore_lines(target: Path) -> list[str]:
    """The lines to add to the target's `.gitignore`: every uncovered secret pattern, with the
    `.env.*` exceptions after it so the example files stay tracked."""
    lines: list[str] = []
    for pattern, samples in _secret_patterns():
        if not all(_is_ignored(target, sample) for sample in samples):
            lines.append(pattern)
    if ".env.*" in lines:
        lines.extend(f"!{name}" for name in sorted(secret_read.SECRET_EXCEPTIONS))
    if any(line.endswith("*") and line.startswith("id_") for line in lines):
        lines.append("!*.pub")
    return lines


def write_gitignore(target: Path, lines: list[str]) -> None:
    """Append `lines` under a header comment; keeps the file's line ending, never rewrites what is there."""
    path = target / ".gitignore"
    existing = path.read_bytes() if path.is_file() else b""
    newline = "\r\n" if b"\r\n" in existing else "\n"
    text = existing.decode("utf-8", "surrogateescape")
    if text and not text.endswith("\n"):
        text += newline
    if text:
        text += newline
    text += newline.join([_GITIGNORE_HEADER, *lines]) + newline
    path.write_bytes(text.encode("utf-8", "surrogateescape"))


def _tree_files(target: Path) -> list[str]:
    names: list[str] = []
    for args in (["ls-files", "-z"], ["ls-files", "-z", "--others", "--exclude-standard"]):
        done = _git(target, args)
        if done is None:
            continue
        names.extend(n for n in done.stdout.decode("utf-8", "replace").split("\0") if n)
    seen: set[str] = set()
    return [n for n in names if not (n in seen or seen.add(n)) and not n.startswith(_SKIP_PREFIXES)]


def _is_binary(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            return b"\0" in handle.read(_BINARY_PROBE)
    except OSError:
        return True


def scan_tree(target: Path) -> tuple[list[dict], list[str]]:
    """(findings, notes). A finding: kind `secret` | `danger`, file, line (int or None), rule, key."""
    findings: list[dict] = []
    notes: list[str] = []
    files = [n for n in _tree_files(target) if (target / n).is_file() and not (target / n).is_symlink()]
    toplevel = str(target)
    accepted = secret_scan._LazyAccepted(toplevel, None)

    level = actlib.security_check_level(actlib.read_config(target))
    patterns = () if level == "off" else danger_scan._active_patterns(danger_scan._enabled_coding_sets(target))
    if not patterns:
        notes.append(
            "dangerous-pattern scan skipped: " + (
                "security-check is off" if level == "off"
                else "no coding rule set is switched on in docs/project/coding_rules.md"))

    skipped_binary = 0
    for rel in files:
        path = target / rel
        label = None if secret_scan._is_env_filename(rel) else secret_read.secret_label(rel, None)
        if label:
            findings.append({"kind": "secret", "file": rel, "line": None,
                             "rule": f"secret file name ({label})", "key": f"secret|{rel}"})
        if _is_binary(path):
            skipped_binary += 1
            continue
        hits: list[dict] = []
        secret_scan._scan_new_file(path, rel, hits, [], accepted)
        for hit in hits:  # hit["value"] is deliberately never read
            findings.append({"kind": "secret", "file": rel, "line": hit.get("line"),
                             "rule": hit["kind"], "key": f"secret|{rel}"})
        if patterns:
            dangers: list[dict] = []
            danger_scan._scan_new_file(path, rel, patterns, dangers, limit=None)  # every hit, no cap
            for hit in dangers:
                pattern = hit["pattern"]
                findings.append({"kind": "danger", "file": rel, "line": hit["line"],
                                 "rule": pattern.label, "key": f"danger|{pattern.id}", "rule_id": pattern.id})
    if skipped_binary:
        notes.append(f"{skipped_binary} binary file(s) skipped")
    return findings, notes


_TEXT = {
    "en": {
        "leak_title": "Secret in {file}: rotate and remove",
        "leak_lead": "The baseline check of the adopted project found a possible secret in `{file}`.",
        "leak_todo": "Rotate the credential, take it out of the file (an environment variable or an untracked "
                       "config file), and clear it from the history if the repository was ever shared.",
        "danger_title": "Dangerous pattern: {rule}",
        "danger_lead": "The baseline check of the adopted project found this pattern, which the commit check "
                       "would hold for: {rule}.",
        "danger_todo": "Review each place; fix it, or mark the line `act:allow-danger` where it is intended.",
        "danger_note": "Note: booking this entry puts the listed files on the baseline "
                       "(`.act-local/danger-scan-hints/baseline.json`), so the commit check does not hold for "
                       "this rule in these files. The baseline stays in force after the first commit, with no "
                       "expiry: from then on a new hit of this rule in a listed file passes too. It ends when "
                       "you remove the `<file>|<rule-id>` key from `baseline.json`, or delete that file.",
        "places": "Places (file:line):",
        "priority_high": "Priority: high.",
        "priority_medium": "Priority: medium.",
    },
    "de": {
        "leak_title": "Geheimnis in {file}: erneuern und entfernen",
        "leak_lead": "Die Bestandsprüfung des übernommenen Projekts fand in `{file}` einen möglichen Zugangswert.",
        "leak_todo": "Den Zugang erneuern, den Wert aus der Datei nehmen (Umgebungsvariable oder nicht versionierte "
                       "Konfigurationsdatei) und, falls das Repository je geteilt wurde, aus dem Verlauf entfernen.",
        "danger_title": "Gefährliches Muster: {rule}",
        "danger_lead": "Die Bestandsprüfung des übernommenen Projekts fand dieses Muster, das die Commit-Prüfung "
                       "aufhalten würde: {rule}.",
        "danger_todo": "Jede Stelle prüfen und beheben, oder die Zeile mit `act:allow-danger` markieren, wo es "
                       "gewollt ist.",
        "danger_note": "Hinweis: Mit diesem Eintrag stehen die genannten Dateien in der Bestandsliste "
                       "(`.act-local/danger-scan-hints/baseline.json`), die Commit-Prüfung hält für diese Regel in "
                       "diesen Dateien also nicht an. Die Liste gilt nach dem ersten Commit unbefristet weiter: ein "
                       "neuer Treffer dieser Regel in einer genannten Datei geht ab dann ebenfalls durch. Sie endet, "
                       "wenn du den Schlüssel `<Datei>|<Regel-Kennung>` aus der `baseline.json` entfernst oder die "
                       "Datei löschst.",
        "places": "Stellen (Datei:Zeile):",
        "priority_high": "Priorität: hoch.",
        "priority_medium": "Priorität: mittel.",
    },
}


def planned_entries(findings: list[dict], language: str) -> list[dict]:
    """One entry per key: {key, title, body}. The body names places and rules, never a value."""
    text = _TEXT.get(language, _TEXT["en"])
    grouped: dict[str, list[dict]] = {}
    for finding in findings:
        grouped.setdefault(finding["key"], []).append(finding)
    entries: list[dict] = []
    for key, items in grouped.items():
        first = items[0]
        places = sorted({(i["file"], i["line"] or 0, i["rule"]) for i in items})
        if first["kind"] == "secret":
            title = text["leak_title"].format(file=first["file"])
            lead, todo, priority = text["leak_lead"].format(file=first["file"]), text["leak_todo"], text["priority_high"]
            rows = [f"- {f}" + (f":{n}" if n else "") + f" ({r})" for f, n, r in places]
        else:
            title = text["danger_title"].format(rule=first["rule"])
            lead, priority = text["danger_lead"].format(rule=first["rule"]), text["priority_medium"]
            todo = text["danger_todo"] + "\n\n" + text["danger_note"]
            rows = [f"- {f}:{n}" for f, n, _r in places]
        body = "\n".join([lead, "", priority, "", todo, "", text["places"], *rows, "", f"baseline: {key}", ""])
        entries.append({"key": key, "title": title, "body": body, "kind": first["kind"],
                        "rows": rows, "files": sorted({i["file"] for i in items})})
    return entries


def _find_entry(target: Path, key: str) -> Optional[Path]:
    """The open backlog entry that carries the line `baseline: <key>` (the whole line, exact). Only files
    directly in `docs/ai/work/backlog/` count: an archived or deleted entry, a ledger or a journal that
    quotes the line is not a booking."""
    folder = target / "docs" / "ai" / "work" / "backlog"
    if not folder.is_dir():
        return None
    needle = f"baseline: {key}"
    for path in sorted(folder.glob("*.md")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(line.rstrip("\r") == needle for line in text.split("\n")):
            return path
    return None


def _add_places(path: Path, key: str, entry: dict) -> set[str]:
    """Make the existing entry at `path` name every file of `entry` (rows added before its `baseline:` line);
    returns the files it names afterwards."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return set()
    lines = text.split("\n")
    named = {f for f in entry["files"] if any(line.startswith(f"- {f}:") for line in lines)}
    missing = [f for f in entry["files"] if f not in named]
    if not missing:
        return named
    at = next((n for n, line in enumerate(lines) if line.rstrip("\r") == f"baseline: {key}"), None)
    if at is None:
        return named
    rows = [row for row in entry["rows"] if any(row.startswith(f"- {f}:") for f in missing)]
    at = at - 1 if at > 0 and lines[at - 1] == "" else at
    lines[at:at] = rows
    try:
        path.write_text("\n".join(lines), encoding="utf-8")
    except OSError:
        return named
    return named | set(missing)


def book(target: Path, entries_plan: list[dict]) -> tuple[int, set[str]]:
    """Create the entries through the target's entries.py. Returns (number that failed, the `file|rule-id`
    keys of the dangerous-pattern entries that name their file after this run)."""
    covered: set[str] = set()
    script = target / ".act" / "scripts" / "entries.py"
    if not script.is_file():
        print(f"baseline: cannot book, {script} does not exist (run after adopt.py --apply)", file=sys.stderr)
        return len(entries_plan), covered
    folder = target / ".act-local" / "adopt" / "baseline"
    folder.mkdir(parents=True, exist_ok=True)
    failed = 0
    for number, entry in enumerate(entries_plan, start=1):
        rule_id = entry["key"].split("|", 1)[1] if entry["kind"] == "danger" else ""
        existing = _find_entry(target, entry["key"])
        if existing is not None:
            print(f"  already booked: {entry['key']}")
            if rule_id:
                named = _add_places(existing, entry["key"], entry)
                covered.update(f"{f}|{rule_id}" for f in named)
                if named != set(entry["files"]):
                    failed += 1
                    print(f"  could not add all places to the entry of {entry['key']}", file=sys.stderr)
            continue
        body_file = folder / f"entry-{number}.md"
        body_file.write_text(entry["body"], encoding="utf-8")
        done = subprocess.run(
            [sys.executable, str(script), "new", "backlog", entry["title"], "--body-file", str(body_file)],
            cwd=str(target), capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if done.returncode == 0 and _find_entry(target, entry["key"]) is not None:
            print(f"  {done.stdout.strip()}")
            if rule_id:
                covered.update(f"{f}|{rule_id}" for f in entry["files"])
        else:
            failed += 1
            print(f"  failed to book {entry['key']}: exit {done.returncode}: {done.stderr.strip()[:200]}", file=sys.stderr)
    return failed, covered


def write_danger_baseline(target: Path, keys: set[str]) -> int:
    """Remember the `file|rule` keys that a backlog entry names, for the commit check."""
    if not keys:
        return 0
    path = target / _BASELINE_HINTS
    known: set[str] = set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list) and all(isinstance(item, str) for item in data):
            known = set(data)
        else:
            print(f"baseline: {path} is not a list of strings, treated as empty and rewritten", file=sys.stderr)
    except (OSError, ValueError):
        pass
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(known | keys), ensure_ascii=False), encoding="utf-8")
    return len(keys)


def main(argv: Optional[list[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(
        description="Baseline check of an existing project before its first commit: missing secret-file "
                    "patterns in .gitignore, the commit scans run once over the tree, findings booked as "
                    "backlog entries. Read-only unless a switch says otherwise; never prints a secret value.")
    parser.add_argument("--target", required=True, help="the project to check (a Git repository)")
    parser.add_argument("--write-gitignore", action="store_true", help="append the missing patterns to .gitignore")
    parser.add_argument("--book", action="store_true", help="create the backlog entries (default: list them)")
    args = parser.parse_args(argv)

    target = Path(args.target).resolve()
    top = _git(target, ["rev-parse", "--show-toplevel"]) if target.is_dir() else None
    if top is None or Path(top.stdout.decode("utf-8", "replace").strip()).resolve() != target:
        print(f"baseline: {target} is not the top folder of a Git repository", file=sys.stderr)
        return 2

    print(".gitignore")
    lines = missing_gitignore_lines(target)
    if not lines:
        print("  all secret-file patterns are covered")
    elif args.write_gitignore:
        write_gitignore(target, lines)
        print(f"  appended {len(lines)} line(s) to .gitignore:")
    else:
        print(f"  {len(lines)} line(s) missing (add with --write-gitignore):")
    for line in lines:
        print(f"    {line}")

    findings, notes = scan_tree(target)
    print("findings")
    for note in notes:
        print(f"  note: {note}")
    for finding in sorted(findings, key=lambda f: (f["file"], f["line"] or 0, f["rule"])):
        where = f"{finding['file']}:{finding['line']}" if finding["line"] else finding["file"]
        print(f"  {where}  {finding['rule']}")
    if not findings:
        print("  none")

    failed = 0
    plan = planned_entries(findings, actlib.docs_language(target))
    if plan:
        print("backlog" + ("" if args.book else " (dry run, add --book to create)"))
        if args.book:
            failed, covered = book(target, plan)
            write_danger_baseline(target, covered)
        else:
            for entry in plan:
                print(f"  would book: {entry['title']}")

    if not findings and not lines:
        print("baseline: nothing to report")
    else:
        print(f"baseline: {len(findings)} finding(s) in {len({f['file'] for f in findings})} file(s), "
              f"{len(plan)} entr{'y' if len(plan) == 1 else 'ies'}, {len(lines)} gitignore line(s)")
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
