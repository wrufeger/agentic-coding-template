#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: `act-load-settings` — import a portable settings file (or several) into this project:
#          the counterpart to settings_export.py. Runs the same three-way check the reconcile skill
#          runs after a template update, except the "other side" is
#          a settings file instead of a new template state: identical -> nothing twice,
#          new -> adopt, contradicting -> inbox (or a config-key resolution).
#
#          Split as decided (`Q69a`): this script does every *mechanical* judgement itself (new,
#          identical, dead/retired/stale identifiers, cross-file collisions, an own rule repeated
#          across files) and writes the result. Anything that needs *content* judgement — does an
#          imported rule merely restate, extend, or actually contradict one of this project's own
#          rules under a different identifier — it cannot decide alone: `plan` only proposes
#          candidate pairs (same area, own-rule/override text against the project's own-rule/
#          override text) for a model to look at; `apply` takes the verdicts back via --judgments
#          and only then writes. Without --judgments, a candidate pair is left "unreviewed" in the
#          inbox rather than silently applied.
#
#          Built on settings_format.py (parse/serialize, reused read-only), rules.py (project file
#          parser + the same [=]/[~]/[-]/[+] semantics), doctor.py's dead/retired-id corpus
#          (`doctor._build_corpus`, read-only reuse — nothing here writes through doctor.py), and
#          update.py's branch hint (`update._maybe_print_branch_hint`). See the settings file
#          spec ("Export and import") for the full detail.
#
# Usage:
#   python .act/scripts/settings_load.py plan [<file...>] [--candidates-out PATH] [--json]
#       Parse and mechanically check every given file (order = argument order) against the current
#       project and against each other. Writes nothing to the project; --candidates-out writes the
#       candidate-pair list for a model to judge (see "Candidates JSON" below) to that path.
#   python .act/scripts/settings_load.py apply [<file...>] [--judgments PATH] [--yes] [--non-interactive]
#                                               [--resolve FILE=ACTION ...]
#       Same analysis, then writes: new/identical/judged-non-contradicting rules into
#       docs/ai/rules.md / docs/project/coding_rules.md, bundled scripts/checklists/agents/
#       skills into docs/ai/local/<area>/<name> (shown before writing unless --yes) — an
#       agent/skill whose name matches a template role/skill is never written, only reported (it
#       would otherwise start overriding the template unit); a written own agent/skill then gets
#       the tool bridge the target project needs (.claude/agents/<name>.md, skill copies), via the
#       same mechanism init.py/update.py use for a template one — "## setup-required" lines
#       and every unresolved finding into one docs/ai/inbox/todo-<stamp>-settings-<slug>.md. --judgments
#       supplies verdicts for the candidate pairs `plan --candidates-out` produced (see "Judgments
#       JSON" below); a candidate with no verdict stays unapplied and unreviewed in the inbox. A
#       contradiction is resolved automatically, without --judgments, only when
#       docs/ai/config.md sets `settings-conflict-<area>` to `project` or `import` — resolved
#       either way, but always reported, never silent. --resolve FILE=ACTION switches to an
#       entirely different mode that skips all of the above — see "Not fully processed files"
#       below.
#
# No <file...> given (either command): every `.md`/`.zip` directly under `.act-local/import/`
#   (machine-local, gitignored; created if it does not exist yet — README.md there is skipped),
#   sorted by name, is used instead. A file that fails to load (bad zip, unparsable settings.md) is
#   reported and left in place; the rest are still processed together, same as several files given
#   explicitly. `apply` (never `plan` — a dry run moves nothing) then moves every file it did manage
#   to load *and* fully resolve to `.act-local/import/done/`, appending a timestamp on a name
#   collision. "Fully resolve" means nothing from that file was left open (see "Not fully processed
#   files" below) — such a file stays in `.act-local/import/` instead (T32). An empty or missing
#   import folder is a clean "nothing to do", exit 0. Explicit `<file...>` paths on the command line
#   are read from wherever given and are never moved, never offered to --resolve.
#
# Not fully processed files (T33): a file stays in `.act-local/import/` when a plain `apply` (no
#   --resolve) left something of it open — a bundled script/checklist/agent/skill that needed --yes
#   or was declined or refused outright (risky frontmatter, shadowing, a bad path, ...), a candidate
#   pair nobody judged, or a name/id collision with something already in the project. `apply` prints
#   what is open (one line per item, with the reason) and what already applied, then either follows
#   `--resolve FILE=ACTION` (repeatable; FILE is the file's name in `.act-local/import/`; an unknown
#   FILE is a fatal error listing the files actually pending, nothing moved) or, on an interactive
#   run with no matching --resolve, asks the same question with `keep` as the default answer.
#
#   --resolve is a pure filing run (T33 review), not a second attempt at applying anything: as soon
#   as it is given, every file in `.act-local/import/` not named in a --resolve is left completely
#   alone — not analyzed, not moved, not touched at all — and even a named file only gets the one
#   action asked for, nothing from it is applied. No TTY prompt ever happens in this mode (the whole
#   point of --resolve is to answer without one). --resolve together with an explicit <file...> on
#   the command line is a fatal error (there is nothing in `.act-local/import/` to file away).
#   ACTION is one of:
#     keep     (the default either way) — leave the file where it is, offered again next run.
#     partial  — close the file now. Nothing from it applies in this run (nothing does, in this
#                mode) — what it would still leave open is instead worked out with a read-only
#                check (the same analysis `plan` runs, against this file alone), and the file moves
#                to `.act-local/import/done/` with a `<name>.skipped.md` note next to it that names
#                those items, why, and the date of the decision. A file that fails to load at all
#                (bad zip, unparsable settings.md) cannot be given `partial` — there is nothing to
#                analyze — and is refused with a message pointing at keep/ignore/delete instead.
#     ignore   — move the file to `.act-local/import/ignored/`; files there are never offered again.
#                Works for a file that fails to load too.
#     delete   — remove the file outright. Only ever happens via an explicit `--resolve`/interactive
#                answer, never as a default. Works for a file that fails to load too.
#
# Candidates JSON (--candidates-out, and the "candidates" key of `plan --json`):
#   {"candidates": [{"key": "<area>:<import_id>::<target_id>", "area": "rules"|"coding",
#                     "import_file": "<source file>", "import_id": "...", "import_text": "...",
#                     "target_id": "...", "target_text": "..."}, ...]}
#   `key` is what --judgments looks entries up by.
#
# Judgments JSON (--judgments):
#   {"<key>": "same"|"extends"|"contradicts"|"unrelated", ...}
#   A key not listed counts as unjudged. "same"/"contradicts" hold the import entry back (the
#   latter unless a config key resolves it); "extends"/"unrelated" let it be applied.
#
# Output format:
#   plan (default): one section per finding kind, then the candidate pairs, then a summary line.
#     --json: {"findings": [...], "candidates": [...], "setup_required": [...], "counts": {...}}.
#   apply: one line per file/rule actually written, then the same finding sections for whatever
#     was held back, then the inbox file path if one was written, then a summary line.
#   Exit 0 always for a syntactically valid run (findings are not "errors" — that's the point of an
#   inbox); 2 on a fatal error (no .act/ found, an input file that will not parse), never a
#   traceback.

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import stat
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import actlib
import doctor
import frontmatter
import init
import rules
import settings_format as sf
import tiers
import update


# ---------------------------------------------------------------------------
# Reading the input file(s) — .md or .zip, told apart by suffix (spec § "Transport")
#
# A .zip is untrusted input (it travels between projects/machines), so it gets two independent
# checks before anything from it is trusted: _scan_zip_entries() refuses an oversized/too-large/
# symlinked archive outright (nothing read), and _safe_member_relpath() refuses any "files/..."
# member whose area or path could point outside docs/ai/local/<area>/ — belt (here, structural)
# and suspenders (plan_files()'s dest.resolve() containment check, once `root` is known).
# ---------------------------------------------------------------------------

_MAX_ZIP_ENTRIES = 200
_MAX_ZIP_ENTRY_BYTES = 5 * 1024 * 1024
_MAX_ZIP_TOTAL_BYTES = 20 * 1024 * 1024
_ALLOWED_FILE_AREAS = ("scripts", "checklists", "agents", "skills")
_UNSAFE_RELPATH_CHARS = re.compile(r"[:\\]")


@dataclass
class SourceFile:
    label: str                       # for messages/inbox: the file name as given on the command line
    settings: sf.SettingsFile
    payload: dict[str, dict[str, str]]  # area -> {relpath: text}, only for "scripts"/"checklists"


def _scan_zip_entries(zf: zipfile.ZipFile, path: Path) -> None:
    """Refuse the whole archive (raises ValueError, nothing is read) if it is too big to be a
    settings transfer at all, or if any entry is a symlink — a symlinked entry's "content" is a
    target path chosen by whoever built the zip, not file data, and extracting it as if it were
    text would follow that path instead of writing one."""
    infos = zf.infolist()
    if len(infos) > _MAX_ZIP_ENTRIES:
        raise ValueError(f"{path}: {len(infos)} entries — more than the {_MAX_ZIP_ENTRIES} a settings zip can hold")
    total = 0
    for info in infos:
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError(f"{path}: {info.filename} is a symlink entry — refused")
        if info.file_size > _MAX_ZIP_ENTRY_BYTES:
            raise ValueError(f"{path}: {info.filename} is larger than {_MAX_ZIP_ENTRY_BYTES // (1024 * 1024)} MB")
        total += info.file_size
        if total > _MAX_ZIP_TOTAL_BYTES:
            raise ValueError(f"{path}: uncompressed contents exceed {_MAX_ZIP_TOTAL_BYTES // (1024 * 1024)} MB")


def _safe_member_relpath(name: str, path: Path) -> tuple[str, str]:
    """Validate one "files/<area>/<relpath>" zip member name and split it into (area, relpath).
    Raises ValueError — refusing the whole archive, not just this member — for anything that
    could resolve outside docs/ai/local/<area>/: an area other than "scripts"/"checklists", an
    absolute or drive-letter path, a backslash (this relpath is always "/"-joined, coming from a
    zip), or any ".."/empty path segment."""
    _, area, relpath = name.split("/", 2)
    if area not in _ALLOWED_FILE_AREAS:
        raise ValueError(f"{path}: {name}: area {area!r} is not one of {_ALLOWED_FILE_AREAS} — refused")
    if not relpath or relpath.startswith("/") or _UNSAFE_RELPATH_CHARS.search(relpath):
        raise ValueError(f"{path}: unsafe path in zip: {name!r}")
    if any(part in ("", "..") for part in relpath.split("/")):
        raise ValueError(f"{path}: unsafe path in zip: {name!r}")
    return area, relpath


def _declared_file_ids(settings: sf.SettingsFile) -> dict[str, set[str]]:
    """The relpaths settings.md itself lists as a "[+] <relpath>" entry, per
    scripts/checklists/agents/skills area — a zip member not named here is never written, even if
    it otherwise passed _safe_member_relpath() (spec: only write what the settings file itself
    declares)."""
    out: dict[str, set[str]] = {}
    for area_name in _ALLOWED_FILE_AREAS:
        area = settings.area(area_name)
        ids: set[str] = set()
        if area is not None and area.is_modeled():
            for group in area.groups:
                ids.update(e.id for e in group.entries if e.symbol == "+")
        out[area_name] = ids
    return out


def load_source(path: Path) -> SourceFile:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            _scan_zip_entries(zf, path)
            names = zf.namelist()
            if "settings.md" not in names:
                raise ValueError(f"{path}: no settings.md at the root of the zip")
            text = zf.read("settings.md").decode("utf-8")
            settings = sf.parse(text)
            declared = _declared_file_ids(settings)
            payload: dict[str, dict[str, str]] = {}
            for name in names:
                if not name.startswith("files/") or name.endswith("/"):
                    continue
                area, relpath = _safe_member_relpath(name, path)
                if relpath not in declared.get(area, ()):
                    continue  # not listed as a "[+]" entry in this area of settings.md — ignored
                try:
                    payload.setdefault(area, {})[relpath] = zf.read(name).decode("utf-8")
                except UnicodeDecodeError:
                    payload.setdefault(area, {})[relpath] = ""  # binary — reported, never written
        return SourceFile(label=path.name, settings=settings, payload=payload)

    text = path.read_text(encoding="utf-8")
    return SourceFile(label=path.name, settings=sf.parse(text), payload={})


# ---------------------------------------------------------------------------
# Auto-discovery from .act-local/import/ (Q74b) — used when no <file...> is given on the command
# line. Machine-local and gitignored (same folder .gitignore already excludes via ".act-local/"),
# created on demand here rather than depending on init.py/update.py having done it already, so an
# older project that predates this feature still works without a migration step.
# ---------------------------------------------------------------------------

_LOAD_ERRORS = (RuntimeError, ValueError, OSError, zipfile.BadZipFile, json.JSONDecodeError)


def _import_dir(root: Path) -> Path:
    return root / ".act-local" / "import"


def _discover_import_files(root: Path) -> list[Path]:
    """Every `.md`/`.zip` file directly under `.act-local/import/` (not its own `done/` or
    `ignored/` subfolder, and not `README.md`), sorted by name for a reproducible order. `iterdir()`
    only lists direct children, so a subfolder is skipped anyway — the `is_file()` filter below is
    what actually excludes `done/`/`ignored/` themselves, not their names."""
    import_dir = _import_dir(root)
    if not import_dir.is_dir():
        return []
    return sorted(
        p for p in import_dir.iterdir()
        if p.is_file() and p.suffix.lower() in (".md", ".zip") and p.name.lower() != "readme.md"
    )


def _resolve_input_files(root: Path, args: argparse.Namespace) -> tuple[list[Path], bool]:
    """(paths, auto_discovered). Explicit files on the command line are used exactly as given —
    `auto_discovered` False, same all-or-nothing load behavior as before a bad one aborts the
    whole run (see cmd_plan/cmd_apply). With none given, `.act-local/import/` is used instead (and
    created if missing) — `auto_discovered` True, which also gates the lenient per-file loading and
    (for `apply` only) the move to `done/` below."""
    if args.files:
        return [Path(p) for p in args.files], False
    _import_dir(root).mkdir(parents=True, exist_ok=True)
    return _discover_import_files(root), True


def _load_sources_lenient(paths: list[Path]) -> tuple[list[SourceFile], list[Path], list[tuple[Path, str]]]:
    """Like `[load_source(p) for p in paths]`, except one bad file (unparsable settings.md, a
    refused zip) is reported and skipped instead of aborting every other file in the batch — the
    auto-discovery behavior Q74b asks for ("failed ones stay in place, with a message"). Explicit
    command-line paths keep the old all-or-nothing behavior (load_source() called directly, letting
    main()'s outer handler turn a failure into exit 2) — this is only used for auto-discovered
    files. Returns (sources, the paths that produced them — same order, for the done/ move below,
    failures)."""
    sources: list[SourceFile] = []
    loaded_paths: list[Path] = []
    failures: list[tuple[Path, str]] = []
    for path in paths:
        try:
            sources.append(load_source(path))
            loaded_paths.append(path)
        except _LOAD_ERRORS as exc:
            failures.append((path, str(exc)))
    return sources, loaded_paths, failures


def _move_to_done(root: Path, path: Path) -> Path:
    """Move an auto-discovered file that was processed into `.act-local/import/done/`, appending a
    timestamp on a name collision rather than overwriting an earlier run's file of the same name."""
    done_dir = _import_dir(root) / "done"
    done_dir.mkdir(parents=True, exist_ok=True)
    dest = done_dir / path.name
    if dest.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = done_dir / f"{path.stem}-{stamp}{path.suffix}"
    shutil.move(str(path), str(dest))
    return dest


def _move_to_ignored(root: Path, path: Path) -> Path:
    """Move a file the human chose `ignore` for into `.act-local/import/ignored/` — same
    collision handling as `_move_to_done`. Files there are never re-discovered
    (`_discover_import_files` only looks at direct children of `import/`, `ignored/` is a
    subfolder just like `done/`)."""
    ignored_dir = _import_dir(root) / "ignored"
    ignored_dir.mkdir(parents=True, exist_ok=True)
    dest = ignored_dir / path.name
    if dest.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        dest = ignored_dir / f"{path.stem}-{stamp}{path.suffix}"
    shutil.move(str(path), str(dest))
    return dest


def _write_skipped_note(done_path: Path, file_label: str, items: list["OpenItem"],
                         applied: Optional[int]) -> Path:
    """`partial` resolution: the source file moves to done/ even though something was left open —
    this note (next to it) records what was discarded and why, so the decision stays readable
    later instead of just vanishing once the source file is out of import/. `applied` is the
    number of rule/file entries this same run actually applied for this file before the partial
    decision — known in the normal apply flow, where write_resolutions()/write_files() ran first.
    In the pure --resolve filing run nothing is ever applied (T33 review), so that count cannot
    honestly be reported; pass None there and the line is left out instead of printing a number
    that was never determined."""
    note_path = done_path.parent / f"{done_path.name}.skipped.md"
    lines = [f"# Discarded on partial import of {file_label}", ""]
    if applied is not None:
        lines.append(f"Applied before this decision: {applied} item(s).")
        lines.append("")
    lines.append(f"Decision date: {date.today().isoformat()}.")
    lines.append("")
    lines.append("Discarded (not applied, will not be retried):")
    lines.append("")
    lines.extend(f"- `{item.ref}` — {item.reason}" for item in items)
    note_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return note_path


_RESOLVE_ACTIONS = ("keep", "partial", "ignore", "delete")


def _parse_resolve_args(raw: list[str]) -> dict[str, str]:
    """--resolve FILE=ACTION, repeatable. Raises ValueError (caught by main(), turned into exit 2)
    for a malformed entry or an unknown action — the same treatment _load_judgments() gives a bad
    --judgments file. A file name given more than once: the last one wins, same as argparse would
    for a single-valued option."""
    out: dict[str, str] = {}
    for raw_item in raw:
        if "=" not in raw_item:
            raise ValueError(f"--resolve {raw_item!r}: expected FILE=ACTION")
        # rpartition, not partition: the action is always the last "="-separated segment, so a
        # file name that itself contains "=" (e.g. "a=b.md") still splits correctly.
        file_name, _, action = raw_item.rpartition("=")
        file_name, action = file_name.strip(), action.strip().lower()
        if not file_name:
            raise ValueError(f"--resolve {raw_item!r}: missing file name")
        if action not in _RESOLVE_ACTIONS:
            raise ValueError(f"--resolve {raw_item!r}: unknown action {action!r} — expected one of {list(_RESOLVE_ACTIONS)}")
        out[file_name] = action
    return out


def _prompt_resolve(file_name: str, items: list["OpenItem"], applied: int) -> str:
    """Interactive follow-up (TTY, not --non-interactive): the same summary render_incomplete_file
    produces, then one input() for the decision. Default 'keep' on empty input or anything not
    recognized — never defaults to 'delete'."""
    print()
    print(render_incomplete_file(file_name, items, applied))
    try:
        answer = input(f"{file_name}: keep/partial/ignore/delete [keep]: ").strip().lower()
    except (EOFError, OSError):
        # A tty that turns out to have nothing to read from (seen on some shells — isatty() can
        # say yes right up until the read itself) — same safe fallback as no answer at all.
        return "keep"
    mapping = {"": "keep", "k": "keep", "keep": "keep", "p": "partial", "partial": "partial",
               "i": "ignore", "ignore": "ignore", "d": "delete", "delete": "delete"}
    return mapping.get(answer, "keep")


# ---------------------------------------------------------------------------
# One line of a settings file, flattened to a comparable shape
# ---------------------------------------------------------------------------

_RE_REPLACES_PREFIX = re.compile(r"^replaces:\s*")
_FENCE_LINE = re.compile(r"^\s*(?:`{3,}|~{3,})", re.MULTILINE)


@dataclass
class ImportEntry:
    file_label: str
    area: str
    group_label: Optional[str]   # coding set name for a nested group, None for a flat entry
    symbol: str                  # "=" "~" "-" "+"
    id: str
    inline: Optional[str]
    body: Optional[str]
    fingerprint: Optional[str] = None  # sha256 of the template group's body at export time
                                        # (B106.1) — only set for "~"/"-"; None falls back to the
                                        # coarser version-only "changed since export" check.

    @property
    def text(self) -> str:
        parts = [p for p in (self.inline, self.body) if p]
        return "\n".join(parts).strip()

    def flat_text(self) -> str:
        """Single-line rendering for a project file (rules.py's own-rule/replaces lines are
        single-line only — see the header comment of _write_own_rule/_write_replaces). A "~"
        entry's `inline` carries a "replaces:" marker (settings_export.py writes it for both the
        one-line and the multi-line shape) — stripped here, *before* joining with `body`, so a
        multi-line override neither keeps the marker as its own flattened segment nor leaves a
        bare "/ " behind once _replaces_line() removes it afterwards (both were the same bug: the
        marker has to go before flattening, not after)."""
        inline = _RE_REPLACES_PREFIX.sub("", self.inline) if self.inline else self.inline
        parts = [p for p in (inline, self.body) if p]
        text = "\n".join(parts).strip()
        return " / ".join(line.strip() for line in text.splitlines() if line.strip())

    def has_fenced_content(self) -> bool:
        """True if `body` itself contains a code-fence line (the settings.md transport fence
        around a "~" body is already stripped by the parser — this catches a fence that is part
        of the actual rule text, e.g. a code example inside an override). Flattening such an
        entry to one project-file line loses that structure; the caller notes it in the inbox."""
        return bool(self.body and _FENCE_LINE.search(self.body))


def collect_entries(source: SourceFile) -> list[ImportEntry]:
    out: list[ImportEntry] = []
    for area in source.settings.areas:
        if not area.is_modeled():
            continue
        for group in area.groups:
            for entry in group.entries:
                out.append(ImportEntry(
                    file_label=source.label, area=area.name, group_label=group.label,
                    symbol=entry.symbol, id=entry.id, inline=entry.inline, body=entry.body,
                    fingerprint=entry.fingerprint,
                ))
    return out


# ---------------------------------------------------------------------------
# Findings — one shape for both plan output and the inbox
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    kind: str
    area: str
    message: str

    def render(self) -> str:
        return f"[{self.area}] {self.message}"


# ---------------------------------------------------------------------------
# Open items — one entry per thing a source file left unresolved: the basis for the end-of-apply
# summary and the `--resolve`/interactive follow-up below (T33). Deliberately a narrower set than
# `findings` above: a dead id, a judged contradiction, a set-switch decline etc. need a source-file
# edit to ever change, so they are reported but do not keep a file "open" — the reasons below do, because
# a rerun (with --yes/--judgments) or a `--resolve` decision can actually resolve them.
# ---------------------------------------------------------------------------

REASON_DECLINED = "declined by you"
REASON_NEEDS_YES = "needs --yes"
REASON_NEEDS_JUDGMENT = "needs a judgment (content overlap)"
REASON_NAME_COLLISION = "name collision"


def reason_rejected(kind: str) -> str:
    """Open-item reason for a bundled agent/skill the import refused (risky frontmatter, shadowing,
    bad path, ...): named by its finding, not lumped in with a plain name collision. A rerun gives
    the same verdict, so only `partial`, `ignore` or `delete` settle such a file."""
    return f"rejected: {KIND_LABELS.get(kind, kind)}"


@dataclass
class OpenItem:
    file_label: str
    ref: str      # an id, or a docs/ai/local/... path — whatever identifies the item to a human
    reason: str   # one of the REASON_* constants above


# Which open-item reasons a plain rerun (with --yes and/or --judgments) can actually turn into
# "applied" — used by the "kept" message in cmd_apply() (review point 7) so it only suggests a
# rerun when one could really help. REASON_NAME_COLLISION and a reason_rejected(...) result need a
# source-file edit (or partial/ignore/delete) instead: a plain rerun reproduces the exact same
# collision/refusal every time.
_RERUN_HELPS_REASONS = {REASON_NEEDS_YES, REASON_NEEDS_JUDGMENT, REASON_DECLINED}


def _rerun_can_help(items: list[OpenItem]) -> bool:
    return any(item.reason in _RERUN_HELPS_REASONS for item in items)


KIND_LABELS: dict[str, str] = {
    "dead-id": "Dead or retired identifiers (not applied)",
    "changed-since-export": "Template text changed since the export (not applied, review by hand)",
    "id-collision": "Same identifier, different content than the project's own (not applied)",
    "cross-file-collision": "Two of the given files disagree on the same identifier (not applied)",
    "template-candidate": "The same own rule appears in more than one file (a template candidate)",
    "unreviewed-candidate": "Content overlap with a project rule, not yet judged (not applied)",
    "contradicts": "Judged to contradict a project rule (not applied)",
    "conflict-resolved": "Contradiction resolved via docs/ai/config.md `settings-conflict-<area>`",
    "same": "Judged to already say the same thing as a project rule (not applied)",
    "setup-required": "Needs configuration before use",
    "file-collision": "A bundled file has the same name as an existing one (not written)",
    "template-shadowed": "A bundled agent/skill matches a template role/skill name (would shadow it)",
    "name-mismatch": "Frontmatter name does not match the file/folder name (not imported)",
    "invalid-unit-path": "Agent/skill path does not have the required shape (not imported)",
    "risky-frontmatter": "Frontmatter would grant elevated permissions (not imported, add by hand if wanted)",
    "frontmatter-hint": "Frontmatter sets tools/model — kept, review before use",
    "not-supported": "Area not supported yet by this build",
    "unresolved-off": "Switched-off entry has no matching set/group in this project (not applied)",
    "set-switch-declined": "Import wants to switch off a coding set that is active here (kept on, not applied)",
    "invalid-id": "Own-rule identifier uses characters a project file cannot render (not applied)",
    "flattened-content": "Multi-line text contains a code fence that flattening would lose (review by hand)",
    "unparsable-frontmatter": "Frontmatter block never closes cleanly or has a line the parser cannot trust (not imported)",
    "missing-definition": "Skill has no correctly-cased SKILL.md definition file (not imported)",
}
KIND_ORDER = list(KIND_LABELS)


# ---------------------------------------------------------------------------
# Template corpus (dead/retired ids) — reuses doctor.py's own corpus builder read-only
# ---------------------------------------------------------------------------

def _corpus(root: Path, area_name: str) -> "doctor.TemplateCorpus":
    return doctor._build_corpus(root, area_name)


# The settings file's area names ("rules", "coding" — logical categories, spec § "Format — layout")
# do not match rules.py's area keys ("core", "coding" — its two project-file layouts). Translated
# at the one seam between the two vocabularies; everywhere else (Finding.area, candidate keys,
# `settings-conflict-<area>`) keeps the settings-file name, since that is what a settings.md/the
# config key actually says.
SETTINGS_TO_RULES_AREA = {"rules": "core", "coding": "coding"}


# ---------------------------------------------------------------------------
# Target project state
# ---------------------------------------------------------------------------

@dataclass
class TargetArea:
    area: rules.Area
    project: Optional[rules.ProjectFile]
    own_by_id: dict[str, str] = field(default_factory=dict)     # id -> text, id-bearing own rules
    own_texts: list[tuple[Optional[str], str]] = field(default_factory=list)  # every own rule
    override_by_id: dict[str, str] = field(default_factory=dict)


def load_target(root: Path) -> dict[str, TargetArea]:
    """Keyed by the settings-file area name ("rules"/"coding"), not rules.py's own ("core"/"coding")
    — see SETTINGS_TO_RULES_AREA."""
    out: dict[str, TargetArea] = {}
    for area_name, rules_area_name in SETTINGS_TO_RULES_AREA.items():
        area = rules.AREAS[rules_area_name]
        path = root / area.project_file
        project = rules.parse_project_file(path, area) if path.is_file() else None
        ta = TargetArea(area=area, project=project)
        if project is not None:
            for own in project.own_rules:
                if own.id:
                    ta.own_by_id[own.id] = own.text
                ta.own_texts.append((own.id, own.text))
            for override in project.overrides:
                ta.override_by_id[override.id] = override.text
        out[area_name] = ta
    return out


# ---------------------------------------------------------------------------
# Analysis result
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    key: str
    area: str
    import_file: str
    import_id: str
    import_text: str
    target_id: str
    target_text: str

    def as_dict(self) -> dict:
        return {
            "key": self.key, "area": self.area, "import_file": self.import_file,
            "import_id": self.import_id, "import_text": self.import_text,
            "target_id": self.target_id, "target_text": self.target_text,
        }


@dataclass
class Resolution:
    entry: ImportEntry
    action: str            # "apply" | "skip"
    reason: str
    candidates: list[str] = field(default_factory=list)  # candidate keys touching this entry


@dataclass
class Analysis:
    resolutions: list[Resolution] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    setup_required: list[str] = field(default_factory=list)   # "<file>: <line>"
    file_plan: list[dict] = field(default_factory=list)        # scripts/checklists to write
    not_supported: set[str] = field(default_factory=set)
    open_items: list[OpenItem] = field(default_factory=list)


# A handful of very common words, so the candidate-pair fallback keyword filter (only used when a
# project has enough own rules that pairing everything would be noisy — see analyze()) does not
# treat "the"/"a rule about" as a shared topic.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "in", "on", "to", "is", "are", "be", "no", "not",
    "all", "for", "with", "code", "rule", "rules", "project", "source", "get", "gets",
}


def _keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-zA-Z]{4,}", text.lower()) if w not in _STOPWORDS}


# Above this many own-rule/override entries on the target side, pairing every import entry
# against every one of them gets noisy — fall back to a shared-keyword prefilter. Below it, every
# combination is offered as a candidate: real settings-file own-rule counts are small, and a
# genuine collision (see the JSDoc/"no comments" example in the spec) need not share a single word.
_CANDIDATE_FULL_CROSS_LIMIT = 40


def _target_candidates_for(ta: TargetArea) -> list[tuple[str, str]]:
    """(id, text) for every target own rule (id-bearing or not — an unlabeled one gets a
    synthetic id) and override, the candidate-pairing pool for one area."""
    out: list[tuple[str, str]] = []
    for i, (oid, text) in enumerate(ta.own_texts):
        out.append((oid or f"(unlabeled-{i})", text))
    for oid, text in ta.override_by_id.items():
        out.append((oid, text))
    return out


def _candidate_pairs(entry: ImportEntry, pool: list[tuple[str, str]]) -> list[tuple[str, str]]:
    if not pool:
        return []
    if len(pool) <= _CANDIDATE_FULL_CROSS_LIMIT:
        return [(tid, ttext) for tid, ttext in pool if tid != entry.id]
    kws = _keywords(entry.text)
    return [(tid, ttext) for tid, ttext in pool if tid != entry.id and kws & _keywords(ttext)]


# ---------------------------------------------------------------------------
# Dead / retired / "changed since export" — shared by "~" and "-" entries
# ---------------------------------------------------------------------------

def _template_status(root: Path, area_name: str, gid: str, header: sf.SettingsHeader,
                      corpus: "doctor.TemplateCorpus", fingerprint: Optional[str] = None,
                      is_whole_set: bool = False) -> Optional[str]:
    """None if the id is alive and (as far as this project can tell) unchanged since the export;
    otherwise the Finding kind that applies ("dead-id" or "changed-since-export"). `is_whole_set`
    is set for a coding "[-] <set-name> — entire rule set switched off" entry: its id is a coding
    set's file basename (e.g. "bash"), not a template group id, so it is checked against the
    template's coding sets instead of `corpus.ids` (which only holds *group* ids).

    `fingerprint` (B106.1) is the sha256 settings_export.py recorded for this id's template body at
    export time. When present, "changed since export" is decided per identifier — hashing the
    *current* template body of the same id and comparing — instead of the coarser fallback below
    (an older export with no fingerprint at all, or a whole-set entry, which has no body of its own
    to hash): a version bump elsewhere in the template no longer flags an id whose own text never
    changed, and a genuinely changed id is caught even without a version bump (e.g. a same-version
    hotfix)."""
    if is_whole_set:
        if actlib.resolve(f"coding/{gid}.md") is None:
            return "dead-id"
        return None  # a coding set has no "retired:"/version-hash tracking of its own
    if gid not in corpus.ids:
        return "dead-id"  # covers both "never existed" and "retired:" (doctor._build_corpus folds
        # "retired:" into corpus.retired, checked next) — checked together, message differs below
    if fingerprint:
        current_hash = hashlib.sha256(corpus.groups[gid].body.encode("utf-8")).hexdigest()
        return "changed-since-export" if current_hash != fingerprint else None
    lock = actlib.read_lock()
    current_version = (lock.get("template") or {}).get("version", "")
    if header.version and current_version and header.version != current_version:
        # Fallback for an export written before B106.1 (no per-id fingerprint) — best-effort proxy:
        # a target project shares no git history with the settings file's source (ADR-5 — "no
        # merge, no shared history"), so the old rule text at the export's commit cannot be diffed
        # against here. A version mismatch is reported instead of silently trusting a rule the
        # current template may have changed since.
        return "changed-since-export"
    return None


def _dead_message(gid: str, corpus: "doctor.TemplateCorpus", kind: str) -> str:
    if gid in corpus.retired:
        return f"`{gid}` is retired in the current template — not applied"
    return f"`{gid}` no longer exists in the current template — not applied"


# An own-rule id becomes a backtick-wrapped Markdown identifier in docs/ai/rules.md /
# docs/project/coding_rules.md ("- `<id>`: ..."); a backtick, pipe or newline in it would break
# that rendering (or, for a pipe, a table row elsewhere), so anything outside this set is refused
# rather than written verbatim.
_VALID_OWN_ID = re.compile(r"^[A-Za-z0-9._-]+$")


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyze(root: Path, sources: list[SourceFile]) -> Analysis:
    result = Analysis()
    targets = load_target(root)
    corpora = {name: _corpus(root, rname) for name, rname in SETTINGS_TO_RULES_AREA.items()}

    all_entries: list[ImportEntry] = []
    header_by_file: dict[str, sf.SettingsHeader] = {}
    for source in sources:
        all_entries.extend(collect_entries(source))
        header_by_file[source.label] = source.settings.header
        for line in source.settings.setup_required:
            result.setup_required.append(f"{source.label}: {line}")

    # Areas this build does not write at all yet.
    for entry in all_entries:
        if entry.area not in ("rules", "coding", "scripts", "checklists", "agents", "skills"):
            result.not_supported.add(entry.area)

    # --- cross-file collisions: same (area, id) from >1 file, different symbol or text ---------
    # "-"/"~"/"+" all count — two files disagreeing on *what to do* with an id (e.g. one drops
    # it, the other overrides it) is as much a collision as two files overriding it differently.
    by_area_id: dict[tuple[str, str], list[ImportEntry]] = {}
    for entry in all_entries:
        if entry.symbol == "=":
            continue
        by_area_id.setdefault((entry.area, entry.id), []).append(entry)

    excluded_ids: set[tuple[str, str]] = set()
    for (area_name, gid), group in by_area_id.items():
        files = sorted({e.file_label for e in group})
        if len(files) <= 1:
            continue
        symbols = sorted({e.symbol for e in group})
        if len(symbols) > 1:
            excluded_ids.add((area_name, gid))
            result.findings.append(Finding(
                kind="cross-file-collision", area=area_name,
                message=f"`{gid}` — {', '.join(files)} disagree on what to do with it "
                        f"({'/'.join(symbols)}) — not applied from either",
            ))
            continue
        texts = {e.flat_text() for e in group}
        if len(texts) > 1:
            excluded_ids.add((area_name, gid))
            result.findings.append(Finding(
                kind="cross-file-collision", area=area_name,
                message=f"`{gid}` differs between {', '.join(files)} — not applied from either",
            ))
        elif group[0].symbol == "+":
            result.findings.append(Finding(
                kind="template-candidate", area=area_name,
                message=f"`{gid}` — same own rule repeated across {', '.join(files)}; "
                        "candidate to move into the template",
            ))

    seen_ids: set[tuple[str, str]] = set()  # first occurrence wins once cross-file-collision is excluded

    for entry in all_entries:
        area_name = entry.area

        if entry.symbol == "=":
            continue  # unchanged from the template — nothing to write, not a finding

        if area_name in ("scripts", "checklists", "agents", "skills"):
            continue  # handled separately, in plan_files()/plan_units()

        if area_name not in ("rules", "coding"):
            continue  # reported once via not_supported above

        key_id = (area_name, entry.id)
        if entry.symbol in ("+", "~", "-"):
            if key_id in excluded_ids:
                continue
            if key_id in seen_ids:
                continue  # a later file repeating an already-resolved id — first file wins
            seen_ids.add(key_id)

        ta = targets[area_name]
        corpus = corpora[area_name]

        if entry.symbol == "-":
            is_whole_set = area_name == "coding" and entry.group_label is None
            status = _template_status(root, area_name, entry.id, header_by_file[entry.file_label],
                                       corpus, entry.fingerprint, is_whole_set)
            if status:
                result.findings.append(Finding(
                    kind=status, area=area_name, message=_dead_message(entry.id, corpus, status)
                    if status == "dead-id" else f"`{entry.id}` — {KIND_LABELS[status].lower()}",
                ))
                result.resolutions.append(Resolution(entry, "skip", status))
                continue
            active_pset = _whole_set_pset(ta.project, entry.id) if is_whole_set and ta.project is not None else None
            if active_pset is not None and active_pset.enabled:
                result.findings.append(Finding(
                    kind="set-switch-declined", area=area_name,
                    message=f"`{entry.id}` — this coding set is active here; an import never "
                            "switches off an active set, review and switch it off by hand if wanted",
                ))
                result.resolutions.append(Resolution(entry, "skip", "set-switch-declined"))
                continue
            result.resolutions.append(Resolution(entry, "apply", "off"))
            continue

        if entry.symbol == "~":
            status = _template_status(root, area_name, entry.id, header_by_file[entry.file_label],
                                       corpus, entry.fingerprint)
            if status:
                result.findings.append(Finding(
                    kind=status, area=area_name, message=_dead_message(entry.id, corpus, status)
                    if status == "dead-id" else f"`{entry.id}` — {KIND_LABELS[status].lower()}",
                ))
                result.resolutions.append(Resolution(entry, "skip", status))
                continue
            existing = ta.override_by_id.get(entry.id)
            if existing is not None:
                if existing.strip() == entry.flat_text().strip():
                    result.resolutions.append(Resolution(entry, "skip", "same"))
                else:
                    result.findings.append(Finding(
                        kind="id-collision", area=area_name,
                        message=f"`{entry.id}` — project already overrides this with different text",
                    ))
                    result.resolutions.append(Resolution(entry, "skip", "id-collision"))
                    result.open_items.append(OpenItem(entry.file_label, entry.id, REASON_NAME_COLLISION))
                continue
            # new override — subject to candidate pairing against the project's own rules/overrides
        elif entry.symbol == "+":
            if entry.id and not _VALID_OWN_ID.match(entry.id):
                result.findings.append(Finding(
                    kind="invalid-id", area=area_name,
                    message=f"`{entry.id}` — id uses characters other than letters, digits, "
                            "`.`, `_`, `-`; not applied",
                ))
                result.resolutions.append(Resolution(entry, "skip", "invalid-id"))
                continue
            existing = ta.own_by_id.get(entry.id) if entry.id else None
            if existing is not None:
                if existing.strip() == entry.flat_text().strip():
                    result.resolutions.append(Resolution(entry, "skip", "same"))
                    continue
                result.findings.append(Finding(
                    kind="id-collision", area=area_name,
                    message=f"`{entry.id}` — project already has an own rule with this id and different text",
                ))
                result.resolutions.append(Resolution(entry, "skip", "id-collision"))
                result.open_items.append(OpenItem(entry.file_label, entry.id, REASON_NAME_COLLISION))
                continue
            same_text = next((tid for tid, ttext in ta.own_texts if ttext.strip() == entry.flat_text().strip()), None)
            if same_text is not None:
                result.resolutions.append(Resolution(entry, "skip", "same"))
                continue
            # new own rule — subject to candidate pairing

        if entry.has_fenced_content():
            result.findings.append(Finding(
                kind="flattened-content", area=area_name,
                message=f"`{entry.id}` — contains a code fence; would be flattened to a single "
                        "project-file line if applied, review by hand",
            ))

        pool = _target_candidates_for(ta)
        pairs = _candidate_pairs(entry, pool)
        cand_keys: list[str] = []
        for tid, ttext in pairs:
            key = f"{area_name}:{entry.id}::{tid}"
            cand_keys.append(key)
            result.candidates.append(Candidate(
                key=key, area=area_name, import_file=entry.file_label,
                import_id=entry.id, import_text=entry.text,
                target_id=tid, target_text=ttext,
            ))
        result.resolutions.append(Resolution(entry, "apply", "new", candidates=cand_keys))

    return result


# ---------------------------------------------------------------------------
# Applying judgments (apply only) — refines "apply"/"new" resolutions that carry candidates
# ---------------------------------------------------------------------------

def apply_judgments(root: Path, result: Analysis, judgments: dict[str, str]) -> None:
    conflict_cache: dict[str, str] = {}

    def conflict_side(area_name: str) -> Optional[str]:
        if area_name not in conflict_cache:
            config = actlib.read_config()
            value = config.get(f"settings-conflict-{area_name}", "").strip().lower()
            conflict_cache[area_name] = value
        value = conflict_cache[area_name]
        return value if value in ("project", "import") else None

    for res in result.resolutions:
        if res.action != "apply" or not res.candidates:
            continue
        verdicts = [(key, judgments.get(key)) for key in res.candidates]
        judged = [(key, v) for key, v in verdicts if v]
        contradicts = [key for key, v in judged if v == "contradicts"]
        same = [key for key, v in judged if v == "same"]
        unjudged = [key for key, v in verdicts if not v]

        if same:
            res.action, res.reason = "skip", "same"
            result.findings.append(Finding(
                kind="same", area=res.entry.area,
                message=f"`{res.entry.id}` — judged the same as {same[0].split('::', 1)[1]}, not applied",
            ))
            continue

        if contradicts:
            side = conflict_side(res.entry.area)
            target_id = contradicts[0].split("::", 1)[1]
            if side == "import":
                result.findings.append(Finding(
                    kind="conflict-resolved", area=res.entry.area,
                    message=f"`{res.entry.id}` contradicts `{target_id}` — "
                            f"settings-conflict-{res.entry.area}=import: applied anyway",
                ))
                # res.action stays "apply"
            elif side == "project":
                res.action, res.reason = "skip", "conflict-resolved"
                result.findings.append(Finding(
                    kind="conflict-resolved", area=res.entry.area,
                    message=f"`{res.entry.id}` contradicts `{target_id}` — "
                            f"settings-conflict-{res.entry.area}=project: kept the project's rule",
                ))
            else:
                res.action, res.reason = "skip", "contradicts"
                result.findings.append(Finding(
                    kind="contradicts", area=res.entry.area,
                    message=f"`{res.entry.id}` judged to contradict `{target_id}` — not applied",
                ))
            continue

        if unjudged:
            res.action, res.reason = "skip", "unreviewed"
            keys = ", ".join(k.split("::", 1)[1] for k in unjudged)
            result.findings.append(Finding(
                kind="unreviewed-candidate", area=res.entry.area,
                message=f"`{res.entry.id}` — content overlap with {keys}, not yet judged, not applied",
            ))
            result.open_items.append(OpenItem(res.entry.file_label, res.entry.id, REASON_NEEDS_JUDGMENT))
        # "extends"/"unrelated" and everything already judged and not contradicting/same: applied as-is


def mark_unreviewed_without_judgments(result: Analysis) -> None:
    """No --judgments at all: every candidate pair stays unreviewed — same effect as
    apply_judgments() with an empty dict, kept separate so `plan` never has to build one."""
    apply_judgments(Path("."), result, {})


def mark_new_files_pending(result: Analysis) -> None:
    """Read-only stand-in for what write_files() would report for every "new" bundled-file/unit
    plan item (scripts, checklists, agents, skills — plan_files()/plan_units() fill result.file_plan
    for all four the same way), without writing anything or prompting: used by
    `apply --resolve FILE=partial`'s single-file analysis (T33), which must never write. A "new"
    item always needs --yes (or an interactive yes) to actually land, so from a read-only vantage
    point it is exactly as "open" as write_files() would find it — without this, such an item was
    silently dropped from the partial decision's discarded list instead of being reported (found via
    the rev33 probe: hi.py vanished from S.zip.skipped.md)."""
    for item in result.file_plan:
        if item["status"] == "new":
            result.open_items.append(OpenItem(item["file"], item["dest"], REASON_NEEDS_YES))


# ---------------------------------------------------------------------------
# Writing rules/coding files
# ---------------------------------------------------------------------------

def _insert_after_heading(lines: list[str], heading: str, mark: str, new_lines: list[str]) -> list[str]:
    """Insert at the end of the section that `mark` (e.g. `<!-- act:own-rules -->`) opens — the
    mark, not the heading's words, so a translated heading still works (R-work-language); the
    English heading is the fallback for a file without the mark, and both are added if neither
    is there."""
    idx = next((i for i, ln in enumerate(lines) if ln.strip() == mark), None)
    if idx is None:
        idx = next((i for i, ln in enumerate(lines) if ln.strip() == heading), None)
    if idx is None:
        out = list(lines)
        if out and out[-1].strip():
            out.append("")
        out.append(heading)
        out.append(mark)
        out.append("")
        out.extend(new_lines)
        return out
    insert_at = len(lines)
    for i in range(idx + 1, len(lines)):
        if lines[i].strip().startswith("## "):
            insert_at = i
            break
    out = list(lines)
    out[insert_at:insert_at] = new_lines
    return out


def _own_rule_line(entry: ImportEntry) -> str:
    return f"- `{entry.id}`: {entry.flat_text()}"


def _replaces_line(entry: ImportEntry) -> str:
    # flat_text() already strips the "replaces:" marker (before flattening — see its docstring),
    # so there is nothing left to clean up here.
    return f"- replaces `{entry.id}`: {entry.flat_text()}"


def _whole_set_pset(project: rules.ProjectFile, set_label: str) -> Optional[rules.ProjectSet]:
    """The project's ProjectSet whose basename is `set_label` ("bash" for .act/coding/bash.md),
    or None if the project does not import that set at all — the same basename rule
    `_toggle_group_off()` uses to find a whole-set checkbox line, factored out so analyze() can
    ask "is this set currently active?" without duplicating it (Q69a follow-up: an import must
    never switch off a set the project actively uses — see the "-" branch in analyze())."""
    for pset in project.sets:
        label = rules.strip_template_prefix(pset.path).rsplit("/", 1)[-1].removesuffix(".md")
        if label == set_label:
            return pset
    return None


def _toggle_group_off(root: Path, project: rules.ProjectFile, gid: str) -> Optional[tuple[str, bool]]:
    """Flip the project's checkbox for coding group `gid` (or the whole set, if `gid` matches a
    set's basename) to off, in place. Returns (message, applied) — `applied` is False when the
    checkbox was already off (nothing written), so the caller's summary line does not count a
    no-op as a change; returns None if the project does not import that set/group at all (nothing
    to toggle). The whole-set branch below is only reachable for a set analyze() found inactive —
    an active whole set is turned back by analyze() itself (`set-switch-declined`) before a
    resolution ever reaches here."""
    for pset in project.sets:
        set_label = rules.strip_template_prefix(pset.path).rsplit("/", 1)[-1].removesuffix(".md")
        if set_label == gid:
            if not pset.enabled:
                return f"{set_label}: already switched off", False
            lines = project.path.read_text(encoding="utf-8").splitlines()
            # T64: an unchecked set loses its "@" as well, or Claude Code would still import it.
            lines[pset.line - 1] = rules.coding_set_line(
                re.sub(r"\[[ xX]\]", "[ ]", lines[pset.line - 1], count=1))
            project.path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
            return f"{set_label}: whole set switched off", True
        if gid in pset.groups:
            group = pset.groups[gid]
            if not group.enabled:
                return f"`{gid}`: already switched off", False
            lines = project.path.read_text(encoding="utf-8").splitlines()
            lines[group.line - 1] = re.sub(r"\[[ xX]\]", "[ ]", lines[group.line - 1], count=1)
            project.path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
            return f"`{gid}`: group switched off (in {set_label})", True
        if pset.enabled:
            # The project uses this set but never mentions `gid` — it counts as "on" (rules.classify
            # default). Insert a fresh "off" checkbox line right after the set line.
            template = rules.resolve_template_set(pset)
            if template is not None and gid in template.groups:
                lines = project.path.read_text(encoding="utf-8").splitlines()
                lines.insert(pset.line, f"  - [ ] `{gid}`")
                project.path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
                return f"`{gid}`: added and switched off (in {set_label})", True
    return None


def write_resolutions(root: Path, result: Analysis) -> list[tuple[str, bool]]:
    """Writes docs/ai/rules.md and docs/project/coding_rules.md for every resolution marked
    "apply". Returns one (message, applied) pair per rule touched — `applied` is False for a
    no-op report ("already switched off") so a caller's summary line does not count it as a
    change (see _toggle_group_off)."""
    messages: list[tuple[str, bool]] = []
    to_apply = [r for r in result.resolutions if r.action == "apply"]
    if not to_apply:
        return messages

    by_area: dict[str, list[Resolution]] = {}
    for res in to_apply:
        by_area.setdefault(res.entry.area, []).append(res)

    for area_name, resolutions in by_area.items():
        rules_area = rules.AREAS[SETTINGS_TO_RULES_AREA[area_name]]
        path = root / rules_area.project_file
        lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
        own_lines = [_own_rule_line(r.entry) for r in resolutions if r.entry.symbol == "+"]
        replaces_lines = [_replaces_line(r.entry) for r in resolutions if r.entry.symbol == "~"]
        if own_lines:
            lines = _insert_after_heading(lines, "## Own rules", "<!-- act:own-rules -->", own_lines)
        if replaces_lines:
            lines = _insert_after_heading(lines, "## Overrides", "<!-- act:overrides -->", replaces_lines)
        if own_lines or replaces_lines:
            path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8")
            for r in resolutions:
                if r.entry.symbol in ("+", "~"):
                    messages.append((f"{area_name}: `{r.entry.id}` — applied", True))

        off_entries = [r for r in resolutions if r.entry.symbol == "-"]
        if off_entries:
            project = rules.parse_project_file(path, rules_area)
            for r in off_entries:
                outcome = _toggle_group_off(root, project, r.entry.id)
                if outcome is None:
                    result.findings.append(Finding(
                        kind="unresolved-off", area=area_name,
                        message=f"`{r.entry.id}` — this project does not use that coding set, nothing to switch off",
                    ))
                else:
                    message, applied = outcome
                    messages.append((f"{area_name}: {message}", applied))
                    if applied:
                        project = rules.parse_project_file(path, rules_area)  # re-read: lines shifted

    return messages


# ---------------------------------------------------------------------------
# Bundled files (scripts / checklists)
# ---------------------------------------------------------------------------

def plan_files(root: Path, sources: list[SourceFile], result: Analysis) -> None:
    local_root = (root / "docs" / "ai" / "local").resolve()
    for source in sources:
        for area_name, contents in source.payload.items():
            if area_name in ("agents", "skills"):
                continue  # handled separately, in plan_units() below (different collision rules)
            area_root = local_root / area_name
            for relpath, text in contents.items():
                dest = root / "docs" / "ai" / "local" / area_name / relpath
                # Second, independent check that `dest` cannot land outside docs/ai/local/<area>/
                # — load_source()'s _safe_member_relpath() already refused an unsafe zip member
                # name; this re-checks the resolved filesystem path itself before anything is
                # planned to be written there.
                if dest.resolve() != area_root and area_root not in dest.resolve().parents:
                    raise ValueError(f"{source.label}: {relpath}: resolves outside docs/ai/local/{area_name}/ — refused")
                if dest.is_file():
                    existing = dest.read_text(encoding="utf-8")
                    if existing == text:
                        status = "same"
                    else:
                        status = "collision"
                        result.findings.append(Finding(
                            kind="file-collision", area=area_name,
                            message=f"docs/ai/local/{area_name}/{relpath} already exists with different content — not written",
                        ))
                        result.open_items.append(OpenItem(
                            source.label, f"docs/ai/local/{area_name}/{relpath}", REASON_NAME_COLLISION,
                        ))
                else:
                    status = "new"
                if (root / ".act" / area_name / relpath).is_file():
                    result.findings.append(Finding(
                        kind="template-shadowed", area=area_name,
                        message=f"docs/ai/local/{area_name}/{relpath} — a template file of the same "
                                f"name exists (.act/{area_name}/{relpath}); this import would shadow it",
                    ))
                result.file_plan.append({
                    "file": source.label, "area": area_name, "path": relpath,
                    "dest": f"docs/ai/local/{area_name}/{relpath}", "status": status, "text": text,
                })


# ---------------------------------------------------------------------------
# Bundled files (agents / skills) — same new/same/collision shape as plan_files() above, but
# with rules a bare scripts/checklists file does not need:
#
#  - shape: an agent must be a flat "<name>.md" (Claude Code registers a role by that file, not a
#    subdirectory); a skill must be "<name>/<file...>" (a Skill.md lives inside its own folder).
#    Anything else is refused before anything is planned to be written — a nested "sub/x.md" used
#    to slip past the name check below (wrong `unit_name`) and then crash write_unit_bridges()
#    once write_files() had *already* written it (Errno 2 reading a bridge source that was never at
#    the path the crash assumed) — planning now happens for every unit before any of them is
#    allowed to write, and a shape violation is a finding, not a partial write.
#  - name check: Claude Code registers an agent/skill under its frontmatter `name`, not its file or
#    folder name — so both are checked against the template's own role/skill names (and, for
#    agents, their generated "-high" bump variants), case-insensitively, and a mismatch between the
#    frontmatter `name` and the file/folder name is refused too (a mismatch is confusing at best,
#    and would otherwise dodge the shadow check by picking an innocuous file name for a
#    template-shadowing frontmatter `name`, or vice versa).
#  - risky frontmatter: `permissionMode`/`hooks`/`mcpServers` on an agent, `allowed-tools`/`hooks`
#    on a skill — never written silently, even with `--yes`; reported so a human adds it by hand
#    if actually wanted. `tools`/`model` are only a review hint, not refused.
#
# A name colliding with a *template* unit is never written at all: docs/ai/local/agents/<name>.md
# and docs/ai/local/skills/<name>/ both already mean "override this template file/skill" elsewhere
# in this template (actlib.resolve(), init.py's copy_targets()) — silently placing an imported
# own agent/skill there under a template name would start overriding it, exactly what
# "never silently overwrite" forbids.
# ---------------------------------------------------------------------------

_AGENT_RISKY_KEYS = ("permissionMode", "hooks", "mcpServers")
_SKILL_RISKY_KEYS = ("allowed-tools", "hooks")
_HINT_KEYS = ("tools", "model")


def _strict_frontmatter(text: str) -> tuple[dict[str, str], bool, Optional[str]]:
    """A frontmatter reader strict enough for the risky-key/name checks in plan_units() to trust,
    built on the shared frontmatter.parse_frontmatter() (`B111.1` -- this used to be its own
    hand-rolled parser; tiers.split_frontmatter() now shares the same parsing code, see that
    module's docstring). A BOM before the opening '---', CRLF line endings, a quoted key, whitespace
    before the colon, or a closing '---' with no trailing newline at EOF are all still-valid
    frontmatter here (so the fields inside are still checked) -- this only gives up, signalling the
    caller to reject the whole unit, when a '---' block is opened but never closes cleanly, or a
    line inside it is neither 'key: value', quoted, a block-scalar/continuation line, nor blank.

    Returns (fields, True, None) on success, with every key lowercased (callers must compare
    against lowercased key names too; frontmatter.parse_frontmatter() already quote-strips both key
    and value). Returns ({}, True, None) -- same as tiers.split_frontmatter()'s fallback -- when the
    file has no frontmatter block at all; that is not an error, an agent without frontmatter is
    allowed (docstring of plan_units() below). Returns ({}, False, error) when a frontmatter block
    was opened but could not be parsed with confidence -- `error` is
    frontmatter.ParseResult.error's line/value detail, for the caller to fold into its own
    rejection message."""
    result = frontmatter.parse_frontmatter(text)
    if not result.ok:
        return {}, False, result.error
    return {key.lower(): value for key, value in result.fields.items()}, True, None


def _agent_unit_name(relpath: str) -> Optional[str]:
    """A relpath valid as an agent unit is a flat "<name>.md" — no nested directory. None
    otherwise (caller reports it as invalid-unit-path, never writes it)."""
    if "/" in relpath or not relpath.endswith(".md"):
        return None
    return relpath[:-3]


def _skill_unit_name(relpath: str) -> Optional[str]:
    """A relpath valid as a skill unit lives under "<name>/..." — the first path segment. None for
    a flat file with no folder of its own."""
    if "/" not in relpath:
        return None
    name = relpath.split("/", 1)[0]
    return name or None


def _template_agent_names(root: Path) -> set[str]:
    """Every template role's file stem, lowercased, plus each one's "-high" bump-variant name
    (init.py's agent_bridge_variant_targets() generates those from the same role — they are never
    a role of their own to import as)."""
    agents_dir = root / ".act" / "agents"
    names: set[str] = set()
    if agents_dir.is_dir():
        for path in agents_dir.glob("*.md"):
            if path.name.lower() != "readme.md":
                names.add(path.stem.lower())
    names.update(f"{n}-high" for n in list(names))
    return names


def _template_skill_names(root: Path) -> set[str]:
    skills_dir = root / ".act" / "skills"
    if not skills_dir.is_dir():
        return set()
    return {p.name.lower() for p in skills_dir.iterdir() if p.is_dir()}


def plan_units(root: Path, sources: list[SourceFile], result: Analysis) -> None:
    local_root = (root / "docs" / "ai" / "local").resolve()
    template_names = {"agents": _template_agent_names(root), "skills": _template_skill_names(root)}
    definition_relpath = {  # the one file per unit whose frontmatter decides name/risk, area -> fn
        "agents": lambda unit_name: f"{unit_name}.md",
        "skills": lambda unit_name: f"{unit_name}/SKILL.md",
    }
    risky_keys = {"agents": _AGENT_RISKY_KEYS, "skills": _SKILL_RISKY_KEYS}

    for source in sources:
        for area_name, contents in source.payload.items():
            if area_name not in ("agents", "skills"):
                continue
            area_root = local_root / area_name
            unit_of = _agent_unit_name if area_name == "agents" else _skill_unit_name

            # Group every relpath of this payload into its unit first — nothing is written until
            # every unit has been checked, so a later relpath turning out invalid never leaves an
            # earlier one of the same import half-written.
            units: dict[str, list[str]] = {}
            for relpath in contents:
                unit_name = unit_of(relpath)
                if unit_name is None:
                    result.findings.append(Finding(
                        kind="invalid-unit-path",
                        area=area_name,
                        message=(f"files/{area_name}/{relpath} — an agent must be a flat "
                                 "'<name>.md' file, not nested in a folder" if area_name == "agents"
                                 else f"files/{area_name}/{relpath} — a skill must live under "
                                      "'<name>/...', not as a flat file") + "; not imported",
                    ))
                    result.open_items.append(OpenItem(source.label, f"files/{area_name}/{relpath}", reason_rejected("invalid-unit-path")))
                    continue
                units.setdefault(unit_name, []).append(relpath)

            for unit_name, relpaths in sorted(units.items()):
                def _reject(kind: str, message: str) -> None:
                    result.findings.append(Finding(kind=kind, area=area_name, message=message))
                    for rp in relpaths:
                        result.file_plan.append({"file": source.label, "area": area_name, "path": rp,
                                                  "dest": f"docs/ai/local/{area_name}/{rp}", "status": "collision",
                                                  "text": contents[rp]})
                        result.open_items.append(OpenItem(source.label, f"docs/ai/local/{area_name}/{rp}", reason_rejected(kind)))

                def_relpath = definition_relpath[area_name](unit_name)
                def_text = contents.get(def_relpath)
                if def_text is None and area_name == "skills":
                    # An exact "<name>/SKILL.md" is required for a skill -- unlike agents (whose
                    # def_relpath is reconstructed from the very relpath it was derived from, so it
                    # always matches), a skill may ship several files and the one actually named
                    # differently ("skill.md", "Skill.md", ...) would otherwise never be read for
                    # its frontmatter at all, letting a risky key or a name-shadow attempt through
                    # unchecked. Found under a different case: reported, not imported. Not found at
                    # all: reported, not imported.
                    lowered_target = def_relpath.lower()
                    wrong_case = next((rp for rp in relpaths if rp.lower() == lowered_target), None)
                    want_name = def_relpath.rsplit("/", 1)[-1]
                    if wrong_case is not None:
                        _reject("missing-definition",
                                f"docs/ai/local/{area_name}/{unit_name} — definition file found as "
                                f"'{wrong_case}', not '{want_name}' (case must match exactly) — not imported")
                    else:
                        _reject("missing-definition",
                                f"docs/ai/local/{area_name}/{unit_name} — no {want_name} definition "
                                "file — not imported")
                    continue
                frontmatter_name: Optional[str] = None
                dangerous: list[str] = []
                hints: list[str] = []
                if def_text is not None:
                    fields, parsed_ok, parse_error = _strict_frontmatter(def_text)
                    if not parsed_ok:
                        detail = f" ({parse_error})" if parse_error else ""
                        _reject("unparsable-frontmatter",
                                f"docs/ai/local/{area_name}/{unit_name} — {def_relpath} has a "
                                "malformed '---' frontmatter block (opener that never closes cleanly, "
                                "or a line that is neither 'key: value', an indented continuation, nor "
                                f"blank) — not imported{detail}")
                        continue
                    frontmatter_name = fields.get("name")
                    dangerous = [k for k in risky_keys[area_name] if k.lower() in fields]
                    hints = [k for k in _HINT_KEYS if k.lower() in fields]

                shadow_hit = None
                if unit_name.lower() in template_names[area_name]:
                    shadow_hit = unit_name
                elif frontmatter_name and frontmatter_name.lower() in template_names[area_name]:
                    shadow_hit = frontmatter_name
                if shadow_hit is not None:
                    kind_label = "role" if area_name == "agents" else "skill"
                    _reject("template-shadowed",
                            f"docs/ai/local/{area_name}/{unit_name} — matches a template {kind_label} "
                            f"name ('{shadow_hit}', case-insensitive, '-high' variants included) — "
                            "not imported, would silently start overriding it")
                    continue

                if frontmatter_name is not None and frontmatter_name != unit_name:
                    _reject("name-mismatch",
                            f"docs/ai/local/{area_name}/{unit_name} — frontmatter name "
                            f"'{frontmatter_name}' does not match the file/folder name '{unit_name}'")
                    continue

                if dangerous:
                    _reject("risky-frontmatter",
                            f"docs/ai/local/{area_name}/{unit_name} — frontmatter has "
                            f"{', '.join(dangerous)}")
                    continue

                for relpath in relpaths:
                    text = contents[relpath]
                    dest = root / "docs" / "ai" / "local" / area_name / relpath
                    # Same containment re-check as plan_files() — belt (load_source()'s
                    # _safe_member_relpath()) and suspenders (here, on the resolved filesystem
                    # path).
                    if dest.resolve() != area_root and area_root not in dest.resolve().parents:
                        raise ValueError(f"{source.label}: {relpath}: resolves outside docs/ai/local/{area_name}/ — refused")
                    if dest.is_file():
                        existing = dest.read_text(encoding="utf-8")
                        if existing == text:
                            status = "same"
                        else:
                            status = "collision"
                            result.findings.append(Finding(
                                kind="file-collision", area=area_name,
                                message=f"docs/ai/local/{area_name}/{relpath} already exists with different content — not written",
                            ))
                            result.open_items.append(OpenItem(
                                source.label, f"docs/ai/local/{area_name}/{relpath}", REASON_NAME_COLLISION,
                            ))
                    else:
                        status = "new"
                    result.file_plan.append({"file": source.label, "area": area_name, "path": relpath,
                                              "dest": f"docs/ai/local/{area_name}/{relpath}", "status": status, "text": text})

                if hints:
                    result.findings.append(Finding(
                        kind="frontmatter-hint",
                        area=area_name,
                        message=f"docs/ai/local/{area_name}/{unit_name} — frontmatter sets {', '.join(hints)}",
                    ))


def write_unit_bridges(root: Path, result: Analysis) -> list[str]:
    """After write_files() has written every "new" agents/skills file plan_units() approved, this
    generates the tool bridges for them — reusing exactly the mechanism init.py's own
    step_materialize()/update.py's step_refresh_copies() use, not a second implementation of it:
    init.write_agent_bridge_file() for an own role (resolves a tier/reasoning frontmatter into
    model/effort via tiers.py, or copies a fixed-model file verbatim — same rule as any template
    role bridge) and init._write_copy_file() for an own skill's files, once per SKILL_TARGET_DIRS
    entry whose tool is configured. Only items write_files() actually wrote (checked by the
    destination file now existing — a "new" item can still have been declined interactively)
    are bridged. Own-skill copies are also recorded in .act-lock.json's "copies", the same
    tracking init.py/update.py give a template-owned copy, so a later `update` refreshes or rescues
    them like any other (docstring of init.py's copy_targets())."""
    messages: list[str] = []
    written = [item for item in result.file_plan
               if item["area"] in ("agents", "skills") and item["status"] == "new" and (root / item["dest"]).is_file()]
    if not written:
        return messages

    tools = [t.strip().lower() for t in actlib.read_config().get("tools", "").split(",") if t.strip()]

    agent_names = sorted({Path(item["path"]).stem for item in written if item["area"] == "agents"})
    if agent_names and "claude-code" in tools:
        tiers_data = tiers.load_tiers(root)
        overrides = tiers.read_role_overrides(root)
        for name in agent_names:
            bridge_src = root / "docs" / "ai" / "local" / "agents" / f"{name}.md"
            dest = root / ".claude" / "agents" / f"{name}.md"
            message, _created = init.write_agent_bridge_file(
                name, bridge_src, dest, False, root, tiers_data, overrides, False,
            )
            messages.append(f"agents: {message}")

    skill_items = [item for item in written if item["area"] == "skills"]
    if skill_items:
        lock = actlib.read_lock()
        copies = dict(lock.get("copies", {}))
        for item in skill_items:
            src = root / item["dest"]
            for dest_root, tool_gate in init.SKILL_TARGET_DIRS:
                if not init._skill_target_active(tool_gate, tools):
                    continue
                copy_dest = root / dest_root / item["path"]
                message, created = init._write_copy_file(src, copy_dest, False, root)
                messages.append(f"skills: {message}")
                copy_key = f"{dest_root}/{item['path']}"
                if created:
                    copies[copy_key] = {
                        "source": src.relative_to(root).as_posix(),
                        "sha256": actlib.sha256_file(copy_dest),
                    }
                elif copy_key not in copies and copy_dest.is_file() and copy_dest.read_bytes() == src.read_bytes():
                    # A hand-placed copy already sitting there, byte-identical to what this import
                    # just wrote as the own skill's source — not created just now, but legitimate:
                    # tracked in the lock the same as init.py/update.py would for one of theirs, so
                    # a later `update`/doctor.py does not flag it as an untracked duplicate.
                    copies[copy_key] = {
                        "source": src.relative_to(root).as_posix(),
                        "sha256": actlib.sha256_file(copy_dest),
                    }
        if copies != lock.get("copies", {}):
            actlib.write_lock({"copies": copies})

    return messages


def write_files(root: Path, result: Analysis, yes: bool) -> list[str]:
    messages: list[str] = []
    interactive = actlib.is_interactive()
    for item in result.file_plan:
        if item["status"] != "new":
            continue
        dest = root / item["dest"]
        if not yes:
            if interactive:
                print(f"--- {item['dest']} ({item['file']}) ---")
                print(item["text"])
                answer = input(f"Write {item['dest']}? [y/N]: ").strip().lower()
                if answer != "y":
                    result.findings.append(Finding(
                        kind="file-collision", area=item["area"],
                        message=f"{item['dest']} — declined interactively, not written",
                    ))
                    result.open_items.append(OpenItem(item["file"], item["dest"], REASON_DECLINED))
                    continue
            else:
                result.findings.append(Finding(
                    kind="file-collision", area=item["area"],
                    message=f"{item['dest']} — needs --yes or an interactive run, not written",
                ))
                result.open_items.append(OpenItem(item["file"], item["dest"], REASON_NEEDS_YES))
                continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(item["text"], encoding="utf-8")
        item["written"] = True
        messages.append(f"{item['dest']}: written")
    return messages


# ---------------------------------------------------------------------------
# Per-source-file completeness (T32, widened by T33) — a source file may only move to
# .act-local/import/done/ once nothing it contributed is still open. "Open" is exactly what
# result.open_items records: a bundled file write that needs --yes or was declined, a candidate
# pair nobody judged, or a name/id collision with something already in the project. Those are
# "come back and finish this" — unlike a dead id, a cross-file disagreement or a judged
# contradiction, which are final outcomes (fixable only by editing the source file itself, not by
# a rerun or a `--resolve` decision) and so do not block the move. See analyze()/apply_judgments()/
# plan_files()/plan_units()/write_files() for where open_items entries are added.
# ---------------------------------------------------------------------------

def incomplete_source_labels(result: Analysis) -> set[str]:
    return {item.file_label for item in result.open_items}


def open_items_by_file(result: Analysis) -> dict[str, list[OpenItem]]:
    """Every open item, grouped by the source file it came from, in the order they were found."""
    out: dict[str, list[OpenItem]] = {}
    for item in result.open_items:
        out.setdefault(item.file_label, []).append(item)
    return out


def applied_count_by_file(result: Analysis) -> dict[str, int]:
    """How many rule/coding entries and bundled files were actually applied/written, per source
    file — the "how many were already applied" half of the end-of-apply summary."""
    counts: dict[str, int] = {}
    for res in result.resolutions:
        if res.action == "apply":
            counts[res.entry.file_label] = counts.get(res.entry.file_label, 0) + 1
    for item in result.file_plan:
        if item.get("written"):
            counts[item["file"]] = counts.get(item["file"], 0) + 1
    return counts


def render_incomplete_file(file_name: str, items: list[OpenItem], applied: int) -> str:
    """The end-of-apply message for one not-fully-processed file: what is open (one line per
    item, with the reason in plain text), what was already applied, and the four `--resolve`
    options with the matching invocation."""
    lines = [f"{file_name}: {applied} item(s) already applied, {len(items)} still open:"]
    for item in items:
        lines.append(f"  - {item.ref} · {item.reason}")
    lines.append("  Options:")
    lines.append("    keep     (default) leave it, offered again next run")
    lines.append(f"    partial  keep what applied, discard the rest -> apply --resolve {file_name}=partial")
    lines.append(f"    ignore   never offer this file again -> apply --resolve {file_name}=ignore")
    lines.append(f"    delete   remove the file -> apply --resolve {file_name}=delete")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Inbox
# ---------------------------------------------------------------------------

def write_inbox(
    root: Path, findings: list[Finding], setup_required: list[str], sources: list[SourceFile],
) -> tuple[Optional[Path], bool]:
    """Returns (path, is_new). `is_new` is False when an inbox file with the exact same body
    (its `created:` line aside — that one differs by definition on a later day) already exists —
    recognized by a content hash kept in an HTML-comment footer (invisible once rendered, so it
    does not disturb the "opens with two header fields" shape every other inbox entry has, per
    .act/skeleton/inbox/README.md). Without this, re-running the same import
    against a target that has not changed piled up a fresh, identically-worded inbox file every
    time (Q69a follow-up). `kind: todo`, never `report`: a contradiction or a "setup-required" line
    asks someone to resolve or configure something, not merely to read
    (16-inbox-questions-tasks.md § "Arten in der Inbox")."""
    if not findings and not setup_required:
        return None, False

    lines = ["kind: todo", "for: all", "status: open", f"created: {date.today().isoformat()}", "",
             "# settings import findings", "",
             "Source file(s): " + ", ".join(s.label for s in sources), ""]
    for kind in KIND_ORDER:
        group = [f for f in findings if f.kind == kind]
        if not group:
            continue
        lines.append(f"## {KIND_LABELS[kind]}")
        lines.append("")
        lines.extend(f"- {f.render()}" for f in group)
        lines.append("")
    if setup_required:
        lines.append("## Needs configuration before use")
        lines.append("")
        lines.extend(f"- {line}" for line in setup_required)
        lines.append("")

    body = "\n".join(lines).rstrip("\n") + "\n"
    # The `created:` line changes every day by definition, so it is left out of the hash — a
    # same-day re-run and a later-day re-run of the same, unchanged import must both count as
    # "already filed", not just the same-day case (W2).
    hash_body = "\n".join(line for line in lines if not line.startswith("created: "))
    marker = f"<!-- settings-import-sha256: {hashlib.sha256(hash_body.encode('utf-8')).hexdigest()} -->"

    base = root / actlib.INBOX_DIR
    if base.is_dir():
        for existing in sorted(base.glob("*-settings-*.md")):
            try:
                if marker in existing.read_text(encoding="utf-8"):
                    return existing, False
            except OSError:
                continue

    slug = "import"
    when = datetime.now()  # fixed once, so a same-minute retry below keeps the same stamp
    dest = base / actlib.inbox_entry_filename("todo", f"settings-{slug}", when)
    n = 2
    while dest.is_file():
        dest = base / actlib.inbox_entry_filename("todo", f"settings-{slug}-{n}", when)
        n += 1

    base.mkdir(parents=True, exist_ok=True)
    dest.write_text(body + marker + "\n", encoding="utf-8")
    return dest, True


# ---------------------------------------------------------------------------
# Human-readable rendering (plan and the part of apply that mirrors it)
# ---------------------------------------------------------------------------

def render_findings(findings: list[Finding]) -> str:
    lines: list[str] = []
    for kind in KIND_ORDER:
        group = [f for f in findings if f.kind == kind]
        if not group:
            continue
        lines.append(f"== {KIND_LABELS[kind]} ==")
        lines.extend(f.render() for f in group)
        lines.append("")
    return "\n".join(lines)


def render_plan(result: Analysis) -> str:
    lines = [render_findings(result.findings)]
    applied = [r for r in result.resolutions if r.action == "apply"]
    if applied:
        lines.append("== Would apply ==")
        for r in applied:
            note = f" ({len(r.candidates)} candidate pair(s))" if r.candidates else ""
            lines.append(f"[{r.entry.area}] {r.entry.symbol} `{r.entry.id}`{note}")
        lines.append("")
    if result.file_plan:
        lines.append("== Bundled files ==")
        for item in result.file_plan:
            lines.append(f"[{item['area']}] {item['dest']} — {item['status']}")
        lines.append("")
    if result.not_supported:
        lines.append("== Not supported yet ==")
        for area_name in sorted(result.not_supported):
            lines.append(f"'{area_name}' — not supported yet, entries left unread")
        lines.append("")
    lines.append(
        f"{len(result.findings)} finding(s), {len(applied)} rule(s) ready to apply, "
        f"{len(result.candidates)} candidate pair(s), {len(result.setup_required)} setup-required line(s)."
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_plan(args: argparse.Namespace) -> int:
    root = actlib.repo_root()
    paths, auto = _resolve_input_files(root, args)
    if auto and not paths:
        print("settings_load.py: .act-local/import/ is empty — nothing to do")
        return 0
    if auto:
        sources, _loaded_paths, failures = _load_sources_lenient(paths)
        for path, message in failures:
            print(f"settings_load.py: {path.name}: {message} — left in place", file=sys.stderr)
        if not sources:
            print("settings_load.py: every file in .act-local/import/ failed to load — nothing to do")
            return 0
    else:
        sources = [load_source(p) for p in paths]
    result = analyze(root, sources)
    plan_files(root, sources, result)
    plan_units(root, sources, result)
    mark_unreviewed_without_judgments(result)

    if args.candidates_out:
        payload = {"candidates": [c.as_dict() for c in result.candidates]}
        Path(args.candidates_out).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        # Status line, not part of the report: kept off stdout so `--json` output stays parseable
        # even when combined with --candidates-out in the same run.
        print(f"settings_load.py: wrote {len(result.candidates)} candidate pair(s) to {args.candidates_out}", file=sys.stderr)

    if args.json:
        payload = {
            "findings": [{"kind": f.kind, "area": f.area, "message": f.message} for f in result.findings],
            "candidates": [c.as_dict() for c in result.candidates],
            "setup_required": result.setup_required,
            "counts": {
                "findings": len(result.findings),
                "apply": len([r for r in result.resolutions if r.action == "apply"]),
                "candidates": len(result.candidates),
            },
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        sys.stdout.write(render_plan(result))
    return 0


_VALID_JUDGMENT_VALUES = {"same", "extends", "contradicts", "unrelated"}


def _load_judgments(path: Path) -> dict[str, str]:
    """Parse and validate --judgments: must be a JSON object mapping a candidate key to one of
    _VALID_JUDGMENT_VALUES. Raises ValueError — caught by main() and turned into a clean exit 2
    — for anything else (a list, a non-string key/value, an unknown verdict), instead of letting
    a malformed file surface as a traceback further down in apply_judgments()."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: --judgments must be a JSON object of {{key: verdict}}")
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str) or value not in _VALID_JUDGMENT_VALUES:
            raise ValueError(
                f"{path}: invalid judgment {key!r}: {value!r} — expected one of {sorted(_VALID_JUDGMENT_VALUES)}"
            )
    return data


def _cmd_resolve_only(root: Path, paths: list[Path], resolve_map: dict[str, str]) -> int:
    """`apply --resolve FILE=ACTION ...`: a pure filing run (T33 review), not a second attempt at
    applying anything. Only the files named in `resolve_map` are touched at all — every other file
    under `.act-local/import/`, named or not in this call's discovery, is left exactly where it is.
    Nothing is analyzed against the project and nothing is written/applied; `partial` is the only
    action that looks at a file's content at all, and only to work out what it would still leave
    open (read-only, single-file — the same analysis `plan` runs). No TTY prompt happens here
    regardless of `--non-interactive` (the point of `--resolve` is to answer without one).
    `partial` on a file that fails to load is refused, not attempted: with no successful analysis,
    "what was discarded" cannot be reported honestly, so keep/ignore/delete are pointed at instead.
    Returns a nonzero exit code if any single resolution failed (an OSError moving/deleting a file,
    or a refused `partial`) — the ones that succeeded still happened, this only signals that not
    everything asked for did."""
    by_name = {p.name: p for p in paths}
    had_error = False
    ignored_count = 0

    for name in sorted(resolve_map):
        path = by_name[name]
        action = resolve_map[name]

        if action == "keep":
            print(f"settings_load.py: {name}: kept — untouched")
            continue

        if action == "delete":
            try:
                path.unlink()
            except OSError as exc:
                print(f"settings_load.py: {name}: could not delete ({exc}) — left in place", file=sys.stderr)
                had_error = True
                continue
            print(f"settings_load.py: {name}: deleted")
            continue

        if action == "ignore":
            try:
                dest = _move_to_ignored(root, path)
            except OSError as exc:
                print(f"settings_load.py: {name}: could not move to ignored/ ({exc}) — left in place", file=sys.stderr)
                had_error = True
                continue
            ignored_count += 1
            print(f"settings_load.py: {name}: ignored -> {dest.relative_to(root).as_posix()}")
            continue

        # partial: load this one file, read-only-analyze it alone (like `plan`), then file it away.
        try:
            source = load_source(path)
        except _LOAD_ERRORS as exc:
            print(f"settings_load.py: {name}: cannot use partial — the file failed to load ({exc}); "
                  f"use keep, ignore or delete instead", file=sys.stderr)
            had_error = True
            continue
        result = analyze(root, [source])
        plan_files(root, [source], result)
        plan_units(root, [source], result)
        mark_unreviewed_without_judgments(result)
        mark_new_files_pending(result)
        items = open_items_by_file(result).get(name, [])
        try:
            dest = _move_to_done(root, path)
        except OSError as exc:
            print(f"settings_load.py: {name}: could not move to done/ ({exc}) — left in place", file=sys.stderr)
            had_error = True
            continue
        note = _write_skipped_note(dest, name, items, applied=None)
        print(f"settings_load.py: {name}: partial import closed -> "
              f"{dest.relative_to(root).as_posix()} ({len(items)} discarded, see {note.name})")

    if ignored_count:
        print(f"settings_load.py: {ignored_count} file(s) ignored in .act-local/import/ignored/")

    return 2 if had_error else 0


def cmd_apply(args: argparse.Namespace) -> int:
    root = actlib.repo_root()
    paths, auto = _resolve_input_files(root, args)

    resolve_map = _parse_resolve_args(args.resolve)
    if resolve_map:
        if not auto:
            raise ValueError("--resolve only applies to the default .act-local/import/ discovery "
                              "(no explicit file given on the command line)")
        pending_names = {p.name for p in paths}
        unknown = sorted(name for name in resolve_map if name not in pending_names)
        if unknown:
            listing = ", ".join(sorted(pending_names)) if pending_names else "(none)"
            raise ValueError(f"--resolve: unknown file(s) {', '.join(unknown)} — "
                              f"files currently in .act-local/import/: {listing}")
        return _cmd_resolve_only(root, paths, resolve_map)

    if auto and not paths:
        print("settings_load.py: .act-local/import/ is empty — nothing to do")
        return 0
    if auto:
        sources, loaded_paths, failures = _load_sources_lenient(paths)
        for path, message in failures:
            print(f"settings_load.py: {path.name}: {message} — left in place", file=sys.stderr)
        if not sources:
            print("settings_load.py: every file in .act-local/import/ failed to load — nothing to do")
            return 0
    else:
        sources = [load_source(p) for p in paths]
    result = analyze(root, sources)
    plan_files(root, sources, result)
    plan_units(root, sources, result)

    judgments: dict[str, str] = {}
    if args.judgments:
        judgments = _load_judgments(Path(args.judgments))
    apply_judgments(root, result, judgments)

    notes: list[str] = []
    update._maybe_print_branch_hint(root, notes)
    for note in notes:
        print(f"[act] {note}")

    rule_messages = write_resolutions(root, result)
    file_messages = write_files(root, result, args.yes)
    bridge_messages = write_unit_bridges(root, result)
    for message, _applied in rule_messages:
        print(f"settings_load.py: {message}")
    for message in file_messages:
        print(f"settings_load.py: {message}")
    for message in bridge_messages:
        print(f"settings_load.py: {message}")

    inbox_path, inbox_is_new = write_inbox(root, result.findings, result.setup_required, sources)
    if inbox_path is not None:
        if inbox_is_new:
            print(f"settings_load.py: wrote {inbox_path.relative_to(root).as_posix()}")
        else:
            print(f"settings_load.py: same findings already recorded in {inbox_path.relative_to(root).as_posix()}")

    if result.findings:
        sys.stdout.write(render_findings(result.findings))
    if result.not_supported:
        for area_name in sorted(result.not_supported):
            print(f"settings_load.py: area '{area_name}' — not supported yet, entries left unread")

    applied_rules = sum(1 for _message, applied in rule_messages if applied)
    applied_total = applied_rules + len(file_messages)
    print(
        f"settings_load.py: {applied_total} item(s) applied in this run "
        f"({applied_rules} rule(s), {len(file_messages)} file(s)); "
        f"{len(result.findings)} finding(s) in the inbox."
    )

    had_error = False

    if auto:
        # Only the auto-discovered path moves files — never for explicit <file...> paths, and
        # never for `plan` (a dry run moves nothing, see the module docstring's "No <file...>
        # given" section). A file this run could not even load (already reported above, via
        # `failures`) stays where it is, not in `loaded_paths`. A file that loaded fine but left
        # something open (needs --yes, an unjudged candidate pair, a name/id collision) also
        # stays by default — moving it to done/ would read as "nothing left to do" next time
        # (T32) — unless an interactive answer says otherwise here, or a separate
        # `apply --resolve` call later (T33; see _cmd_resolve_only — this function no longer
        # handles --resolve at all, it always exits above before reaching this point).
        incomplete = incomplete_source_labels(result)
        by_file = open_items_by_file(result)
        applied_by_file = applied_count_by_file(result)
        interactive = actlib.is_interactive()
        ignored_count = 0
        for path in loaded_paths:
            if path.name not in incomplete:
                try:
                    dest = _move_to_done(root, path)
                except OSError as exc:
                    print(f"settings_load.py: {path.name}: could not move to done/ ({exc}) — left in place", file=sys.stderr)
                    had_error = True
                    continue
                print(f"settings_load.py: {path.name} -> {dest.relative_to(root).as_posix()}")
                continue

            items = by_file.get(path.name, [])
            applied = applied_by_file.get(path.name, 0)

            # render_incomplete_file's summary is printed exactly once: _prompt_resolve() already
            # prints it itself (right before asking), so an interactive run must not print it here
            # too — only the non-interactive branch (which never calls _prompt_resolve) does.
            if interactive:
                action = _prompt_resolve(path.name, items, applied)
            else:
                print(render_incomplete_file(path.name, items, applied))
                action = "keep"

            if action == "keep":
                if _rerun_can_help(items):
                    print(f"settings_load.py: {path.name}: kept — offered again next run "
                          f"(rerun apply with --yes/--judgments, or use --resolve {path.name}=partial|ignore|delete)",
                          file=sys.stderr)
                else:
                    print(f"settings_load.py: {path.name}: kept — a rerun gives the same result, "
                          f"choose partial, ignore or delete (--resolve {path.name}=partial|ignore|delete)",
                          file=sys.stderr)
                continue
            if action == "partial":
                try:
                    dest = _move_to_done(root, path)
                except OSError as exc:
                    print(f"settings_load.py: {path.name}: could not move to done/ ({exc}) — left in place", file=sys.stderr)
                    had_error = True
                    continue
                note = _write_skipped_note(dest, path.name, items, applied)
                print(f"settings_load.py: {path.name}: partial import closed -> "
                      f"{dest.relative_to(root).as_posix()} ({applied} applied, "
                      f"{len(items)} discarded, see {note.name})")
            elif action == "ignore":
                try:
                    dest = _move_to_ignored(root, path)
                except OSError as exc:
                    print(f"settings_load.py: {path.name}: could not move to ignored/ ({exc}) — left in place", file=sys.stderr)
                    had_error = True
                    continue
                ignored_count += 1
                print(f"settings_load.py: {path.name}: ignored -> {dest.relative_to(root).as_posix()}")
            elif action == "delete":
                try:
                    path.unlink()
                except OSError as exc:
                    print(f"settings_load.py: {path.name}: could not delete ({exc}) — left in place", file=sys.stderr)
                    had_error = True
                    continue
                print(f"settings_load.py: {path.name}: deleted")

        if ignored_count:
            print(f"settings_load.py: {ignored_count} file(s) ignored in .act-local/import/ignored/")

    return 2 if had_error else 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="settings_load.py",
        description="Import a settings file (act-export-settings' output) into this project.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="check only, write nothing to the project")
    plan.add_argument("files", nargs="*", default=[],
                       help="settings.md or settings.zip file(s), in order; default: every "
                            ".md/.zip in .act-local/import/")
    plan.add_argument("--candidates-out", metavar="PATH", help="write the candidate-pair list here as JSON")
    plan.add_argument("--json", action="store_true", help="machine-readable output")

    apply_p = sub.add_parser("apply", help="check, then write what is mechanically clear or judged")
    apply_p.add_argument("files", nargs="*", default=[],
                          help="settings.md or settings.zip file(s), in order; default: every "
                               ".md/.zip in .act-local/import/ (moved to .act-local/import/done/ "
                               "once processed)")
    apply_p.add_argument("--judgments", metavar="PATH", help="JSON verdicts for plan --candidates-out's pairs")
    apply_p.add_argument("--yes", action="store_true", help="write bundled files without asking first")
    apply_p.add_argument("--non-interactive", action="store_true", help="never prompt (same effect as omitting --yes when stdin is not a terminal)")
    apply_p.add_argument("--resolve", action="append", default=[], metavar="FILE=ACTION",
                          help="decide what happens to a not-fully-processed .act-local/import/ file "
                               "(repeatable); ACTION is keep (default, offered again), partial (close it, "
                               "keep what applied, discard the rest), ignore (move to import/ignored/, "
                               "never offered again), or delete (remove the file) — only with the default "
                               "no-argument .act-local/import/ discovery")

    return parser


def main(argv: list[str]) -> int:
    # Same Windows console-encoding fix as every other script here (em dash throughout).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    try:
        if args.command == "plan":
            return cmd_plan(args)
        return cmd_apply(args)
    except (RuntimeError, ValueError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
        print(f"settings_load.py: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
