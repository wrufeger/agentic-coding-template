#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Purpose: `act-export-settings` — write the project's own rule deviations (and, with a switch,
#          local scripts/checklists) to a portable settings file, for `act-load-settings` in
#          another project or for the Owner's profile (`--profile`). Built on
#          .act/scripts/settings_format.py (data model, parser, serializer, secrets scan) and
#          reuses .act/scripts/rules.py's project-file parser/classifier instead of re-reading
#          docs/ai/rules.md or docs/project/coding_rules.md by hand. See settings_format.py's own
#          docstring (`Q60a`-`Q61d`) for the full detail.
#
#          This build stage covers the `rules` and `coding` areas (own rules, switched-off
#          groups/sets, `replaces` overrides) plus, behind their own switches, `scripts`,
#          `checklists`, `agents` and `skills` from docs/ai/local/.
#
# Usage:
#   python .act/scripts/settings_export.py
#       Only [~]/[-]/[+] deviations (the "=" default is left out) for rules + coding, as a single
#       settings.md written to .act-local/export/act-settings-<date>.md (machine-local, gitignored;
#       the folder is created if it does not exist yet).
#   python .act/scripts/settings_export.py --all
#       Same, but every included rule/group is listed, "=" ones included.
#   python .act/scripts/settings_export.py --with-scripts --with-checklists --with-agents --with-skills
#       Also includes docs/ai/local/scripts/, docs/ai/local/checklists/, docs/ai/local/agents/ (the
#       project's own roles) and docs/ai/local/skills/ (its own skills) — each file shown
#       individually before being written on import. Any of the four switches forces --with-files.
#   python .act/scripts/settings_export.py --with-files
#       Writes a .zip (settings.md at its root + files/<area>/<name>) instead of a plain .md, even
#       without local scripts/checklists/agents/skills.
#   python .act/scripts/settings_export.py --strict
#       Abort with exit 1 and the finding list instead of substituting placeholders — for "goes
#       out to strangers". Without it, a finding becomes a visible "<setup:KIND>" placeholder plus
#       a "## setup-required" line, and the run still succeeds.
#   python .act/scripts/settings_export.py --out <path>
#       Write there instead of the default .act-local/export/act-settings-<date>.md|.zip.
#   python .act/scripts/settings_export.py --profile
#       Write the same export (same format, same switches — settings.md or, with --with-files, a
#       zip) to the Owner's profile instead of .act-local/export/: Windows "%APPDATA%\act\
#       settings.md", else "$XDG_CONFIG_HOME/act/settings.md" (falling back to "~/.config/act/
#       settings.md") — resolved from the environment/Path.home() at run time, never a hard-coded
#       path (`docs/project/coding_rules.md` § "Pfade außerhalb des Projekts" in the template-pflege
#       repo). This is the grounds a future `init` reads to hand the same setup to a fresh clone
#       (`Q57d`) — init.py does not read the profile yet, only this export writes it. An existing
#       profile file is never silently overwritten: it is renamed to "<name>.bak-<stamp>" first, and
#       the run says so. Mutually exclusive with --out.
#
# Output format: one line on stdout naming the file written and the number of placeholders
#   inserted ("review before sharing"), plus a line naming the backup path when --profile replaced
#   an existing profile file. --strict prints "<location> — <hint>" per finding to stderr instead
#   and writes nothing. Exit 0 on success, 1 on a --strict abort, 2 on a fatal error (no .act/
#   found, or --profile combined with --out) — never a traceback.

from __future__ import annotations

import argparse
import hashlib
import os
import re
import sys
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import actlib
import rules
import settings_format as sf
import tiers


# ---------------------------------------------------------------------------
# Header (template version this export was taken against)
# ---------------------------------------------------------------------------

def _template_version(root: Path) -> tuple[str, str]:
    """(version, commit) — from .act-lock.json § "template" if it has values, else from the
    "version="/"commit=" lines of .act/VERSION (the lock file does not exist yet this early in the
    build; VERSION is the fallback of record)."""
    lock = actlib.read_lock()
    template = lock.get("template") or {}
    version, commit = str(template.get("version") or ""), str(template.get("commit") or "")
    if version or commit:
        return version, commit

    values: dict[str, str] = {}
    version_path = root / ".act" / "VERSION"
    if version_path.is_file():
        for line in version_path.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.partition("=")
            if sep:
                values[key.strip()] = value.strip()
    return values.get("version", ""), values.get("commit", "")


def build_header(root: Path) -> sf.SettingsHeader:
    version, commit = _template_version(root)
    return sf.SettingsHeader(version=version, commit=commit, date=date.today().isoformat())
    # No "source": the file is meant to be shared, and the project name is not the reader's business.


# ---------------------------------------------------------------------------
# Owner's profile location (`--profile`, Q57d/Q60b) — platform-appropriate, resolved fresh on every
# call from the environment/Path.home(), never a hard-coded path (coding_rules.md § "Pfade außerhalb
# des Projekts"): reading it fresh each time is also what lets a test point HOME/APPDATA/
# XDG_CONFIG_HOME at a scratch directory without touching the real profile.
# ---------------------------------------------------------------------------

def profile_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Roaming") / "act"
    base = os.environ.get("XDG_CONFIG_HOME")
    return (Path(base) if base else Path.home() / ".config") / "act"


def _group_fingerprint(tgroup: "rules.TemplateGroup") -> str:
    """sha256 of a template group's full section body (heading included, same text
    doctor.py._check_overrides() hashes for its own stale-override tracking) — the per-identifier
    "changed since export" fingerprint (B106.1)."""
    return hashlib.sha256(tgroup.body.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# rules / coding areas — built from rules.py's own parser + classifier
# ---------------------------------------------------------------------------

def _own_rule_id(prefix: str, own: "rules.OwnRule", used: set[str]) -> str:
    """`id` if the project already gave the own rule one, else a generated "<prefix>-local-<slug>"
    (Q61b: a settings-file own rule is a normal "R-local-…"/"CR-local-…" rule id, not a free-
    floating note) — de-duplicated against `used` if the slug collides. The slug is built from the
    *scanned* (secret-redacted) text, not the raw one, and drops any "<setup:...>" placeholder
    outright rather than turning it into slug words — an id must never itself carry a secret
    fragment that the body text just had replaced out of it."""
    if own.id:
        return own.id
    scanned = re.sub(r"<setup:[^>]*>", "", sf.scan(own.text).text)
    slug = re.sub(r"[^a-z0-9]+", "-", scanned.lower()).strip("-")[:40] or "rule"
    candidate = f"{prefix}-local-{slug}"
    suffix = 2
    while candidate in used:
        candidate = f"{prefix}-local-{slug}-{suffix}"
        suffix += 1
    return candidate


def _entry_for_group(symbol: str, group_id: str, project_group: Optional["rules.ProjectGroup"],
                      override: Optional["rules.Override"],
                      fingerprint: Optional[str] = None) -> sf.SettingsEntry:
    """`fingerprint` (B106.1) is the sha256 of the template group's body text at export time — set
    only for "~"/"-" (an "=" entry is unchanged by definition, and a template body has nothing to
    fingerprint for a "+" own rule). settings_load.py compares it against the same group's *current*
    body in the target project to report "changed since export" per identifier, not just per
    template version."""
    if symbol == "~" and override is not None:
        if "\n" in override.text:
            return sf.SettingsEntry(symbol="~", id=group_id, inline="replaces:", body=override.text,
                                     fingerprint=fingerprint)
        return sf.SettingsEntry(symbol="~", id=group_id, inline=f"replaces: {override.text}",
                                 fingerprint=fingerprint)
    if symbol == "-":
        reason = project_group.reason if project_group else None
        inline = f"reason: {reason}" if reason else None
        return sf.SettingsEntry(symbol="-", id=group_id, inline=inline, fingerprint=fingerprint)
    return sf.SettingsEntry(symbol="=", id=group_id)


def build_rules_area(root: Path, show_all: bool) -> Optional[sf.SettingsArea]:
    area_def = rules.AREAS["core"]
    path = root / area_def.project_file
    if not path.is_file():
        return None
    project = rules.parse_project_file(path, area_def)
    override_by_id = {o.id: o for o in project.overrides}

    entries: list[sf.SettingsEntry] = []
    seen: set[str] = set()
    for pset in project.sets:
        template = rules.resolve_template_set(pset)
        if template is None:
            continue
        for group_id, tgroup in template.groups.items():
            if group_id in seen:
                continue
            seen.add(group_id)
            symbol = rules.classify(group_id, pset.groups.get(group_id), override_by_id)
            if symbol == "=" and not show_all:
                continue
            fingerprint = _group_fingerprint(tgroup) if symbol in ("~", "-") else None
            entries.append(_entry_for_group(symbol, group_id, pset.groups.get(group_id),
                                             override_by_id.get(group_id), fingerprint))

    used_ids = seen | set(override_by_id)
    for own in project.own_rules:
        own_id = _own_rule_id("R", own, used_ids)
        used_ids.add(own_id)
        entries.append(sf.SettingsEntry(symbol="+", id=own_id, body=own.text))

    if not entries:
        return None
    return sf.SettingsArea(name="rules", groups=[sf.SettingsGroup(label=None, entries=entries)])


def build_coding_area(root: Path, show_all: bool) -> Optional[sf.SettingsArea]:
    area_def = rules.AREAS["coding"]
    path = root / area_def.project_file
    if not path.is_file():
        return None
    project = rules.parse_project_file(path, area_def)
    override_by_id = {o.id: o for o in project.overrides}

    groups: list[sf.SettingsGroup] = []
    flat: list[sf.SettingsEntry] = []  # whole-set-off lines + own rules — not nested per set
    seen: set[str] = set()

    for pset in project.sets:
        set_label = rules.strip_template_prefix(pset.path).rsplit("/", 1)[-1].removesuffix(".md")
        if not pset.enabled:
            # A whole set switched off is the normal state of a project that never opted into it —
            # not a preference worth carrying into another project's settings file. Individual
            # groups/ids switched off *within* an active set are still exported below.
            continue
        template = rules.resolve_template_set(pset)
        if template is None:
            continue
        group_entries: list[sf.SettingsEntry] = []
        for group_id, tgroup in template.groups.items():
            seen.add(group_id)
            symbol = rules.classify(group_id, pset.groups.get(group_id), override_by_id)
            if symbol == "=" and not show_all:
                continue
            fingerprint = _group_fingerprint(tgroup) if symbol in ("~", "-") else None
            group_entries.append(_entry_for_group(symbol, group_id, pset.groups.get(group_id),
                                                   override_by_id.get(group_id), fingerprint))
        if group_entries:
            groups.append(sf.SettingsGroup(label=set_label, entries=group_entries))

    used_ids = seen | set(override_by_id)
    for own in project.own_rules:
        own_id = _own_rule_id("CR", own, used_ids)
        used_ids.add(own_id)
        flat.append(sf.SettingsEntry(symbol="+", id=own_id, body=own.text))

    if flat:
        groups.append(sf.SettingsGroup(label=None, entries=flat))
    if not groups:
        return None
    return sf.SettingsArea(name="coding", groups=groups)


# ---------------------------------------------------------------------------
# agents — one entry per own role, header fields as body, full file in the zip
# ---------------------------------------------------------------------------

def build_agents_area(root: Path) -> tuple[Optional[sf.SettingsArea], dict[str, str]]:
    """Every docs/ai/local/agents/<name>.md (the project's own roles — see init.py's
    agent_bridge_targets(); README.md is documentation, not a role) as one "[+] <name>.md" entry
    whose body lists the file's own frontmatter fields in order (model, or tier/reasoning, plus
    tools/description/...) — readable in settings.md without opening the zip. The entry id carries
    the ".md" suffix so it equals the zip member's relpath under files/agents/, the same "id ==
    relpath" contract build_local_files_area() below uses for scripts/checklists/skills.
    Returns (area_or_None, {id: full file text}) — the caller scans/redacts the file text
    separately, same as build_local_files_area()."""
    base = root / "docs" / "ai" / "local" / "agents"
    if not base.is_dir():
        return None, {}
    template_agents_dir = root / ".act" / "agents"
    entries: list[sf.SettingsEntry] = []
    contents: dict[str, str] = {}
    for path in sorted(base.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        if path.is_symlink():
            print(f"settings_export.py: skipped symlink {path.name} under docs/ai/local/agents/", file=sys.stderr)
            continue
        if (template_agents_dir / path.name).is_file():
            # A docs/ai/local/agents/<name>.md whose name matches a template role is that role's
            # override text (actlib.resolve()), not an own role of its own — exporting it as one
            # would hand the next project a "[+] <name>.md" own-agent entry that silently starts
            # overriding the very same template role there too (settings_load.py's plan_units()
            # now refuses exactly that on import; not shipping it in the first place is the other
            # half of the same fix).
            print(f"settings_export.py: skipped override {path.stem} (template role) — not exported as an own role", file=sys.stderr)
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        fields, _, order = tiers.split_frontmatter(text)
        body_lines = [f"{key}: {fields[key]}" for key in order if key != "name" and key in fields]
        contents[path.name] = text
        entries.append(sf.SettingsEntry(symbol="+", id=path.name, body="\n".join(body_lines) or None))
    if not entries:
        return None, {}
    return sf.SettingsArea(name="agents", groups=[sf.SettingsGroup(label=None, entries=entries)]), contents


# ---------------------------------------------------------------------------
# scripts / checklists / skills — plain files under docs/ai/local/, only with their switch
# ---------------------------------------------------------------------------

def build_local_files_area(root: Path, subdir: str, area_name: str) -> tuple[Optional[sf.SettingsArea], dict[str, str]]:
    """Every text file under docs/ai/local/<subdir>/, each as one "[+] <relpath>" entry pointing
    at "files/<area_name>/<relpath>" (Q61c). Returns (area_or_None, {relpath: file text}) — the
    caller scans/redacts the file text separately and writes it into the zip under that same path,
    so a leaked value inside a script/checklist is caught exactly like a leaked value in a rule.

    A file that matches a template unit of the same shape/name is a project's *override* of that
    template file (actlib.resolve() — the same "docs/ai/local/<path> wins over .act/<path>" rule a
    checklist/script/skill uses), not an own file of its own (`B111.4`, review of `T24`) — exporting
    it as a plain "[+] <relpath>" would hand the next project a file that silently starts
    overriding the same template unit there too, exactly like build_agents_area() above already
    refuses for an own role. Skipped, with one stderr note per skipped name, same as there:
    "scripts"/"checklists" match by relpath directly (a script/checklist is a flat file, no
    sub-folder of its own), "skills" match by the first path segment (a skill's own folder)."""
    base = root / "docs" / "ai" / "local" / subdir
    if not base.is_dir():
        return None, {}
    template_dir = root / ".act" / subdir
    template_skills_dir = root / ".act" / "skills"
    skipped_overrides: set[str] = set()
    entries: list[sf.SettingsEntry] = []
    contents: dict[str, str] = {}
    for path in sorted(base.rglob("*")):
        if path.is_symlink():
            print(f"settings_export.py: skipped symlink {path.relative_to(base).as_posix()} under "
                  f"docs/ai/local/{subdir}/", file=sys.stderr)
            continue
        if not path.is_file() or "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            continue
        rel = path.relative_to(base).as_posix()
        if area_name == "skills":
            skill_name = rel.split("/", 1)[0]
            if (template_skills_dir / skill_name).is_dir():
                # Same "override, not own" case as build_agents_area() above, for a
                # docs/ai/local/skills/<name>/ whose name matches a template skill.
                if skill_name not in skipped_overrides:
                    skipped_overrides.add(skill_name)
                    print(f"settings_export.py: skipped override {skill_name} (template skill) — "
                          "not exported as an own skill", file=sys.stderr)
                continue
        elif area_name in ("scripts", "checklists") and (template_dir / rel).is_file():
            if rel not in skipped_overrides:
                skipped_overrides.add(rel)
                print(f"settings_export.py: skipped override {rel} (template {area_name[:-1]}) — "
                      f"not exported as an own {area_name[:-1]}", file=sys.stderr)
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue  # not a text file — out of scope for a settings transfer, skipped silently
        contents[rel] = text
        entries.append(sf.SettingsEntry(symbol="+", id=rel, inline=f"file: files/{area_name}/{rel}"))
    if not entries:
        return None, {}
    return sf.SettingsArea(name=area_name, groups=[sf.SettingsGroup(label=None, entries=entries)]), contents


# ---------------------------------------------------------------------------
# Extra scan pass — ids, group labels, header fields, zip file names
# ---------------------------------------------------------------------------

def scan_ids_and_labels(settings: sf.SettingsFile, file_payload: dict[str, dict[str, str]],
                         located: list[tuple[str, "sf.ScanFinding"]]) -> None:
    """sf.redact() only scans an entry's `inline`/`body` free text (and an unmodeled area's `raw`
    text) — it leaves ids, group labels and the header untouched, on the assumption that those are
    template-given identifiers. A project's own rule id, a hand-picked coding-set label or a
    docs/ai/local/ script file name is *not* guaranteed to be — so this second pass runs the same
    scan() over all of them and mutates `settings`/`file_payload` in place, appending every finding
    to `located` exactly like redact() does, so a --strict run sees the whole picture in one abort
    and a normal run gets one combined "## setup-required" list.

    For a scripts/checklists entry (`area.name` is a key of `file_payload`), the id *is* the file's
    relative path — the same path the zip writes it under as "files/<area>/<id>". If scan() touches
    it, the file_payload key and the entry's "file: files/..." inline text are renamed to match, so
    settings.md and the zip stay consistent with each other."""
    header = settings.header
    for attr in ("version", "commit", "date", "source"):
        value = getattr(header, attr)
        if not value:
            continue
        result = sf.scan(value)
        if result.findings:
            for finding in result.findings:
                located.append((f"header: {attr}", finding))
            setattr(header, attr, result.text)

    for area in settings.areas:
        if not area.is_modeled():
            continue
        contents = file_payload.get(area.name)
        for group in area.groups:
            if group.label:
                result = sf.scan(group.label)
                if result.findings:
                    for finding in result.findings:
                        located.append((f"{area.name}: group label", finding))
                    group.label = result.text
            for entry in group.entries:
                result = sf.scan(entry.id)
                if not result.findings:
                    continue
                for finding in result.findings:
                    located.append((f"{area.name}: id", finding))
                old_id, entry.id = entry.id, result.text
                if contents is not None and old_id in contents:
                    contents[entry.id] = contents.pop(old_id)
                    entry.inline = f"file: files/{area.name}/{entry.id}"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="settings_export.py",
        description="Write the project's rule deviations (and, with a switch, local scripts/checklists) "
                     "to a portable settings file.",
    )
    parser.add_argument("--all", action="store_true", help="include unchanged ('=') rules/groups too")
    parser.add_argument("--with-scripts", action="store_true", help="include docs/ai/local/scripts/ (forces --with-files)")
    parser.add_argument("--with-checklists", action="store_true", help="include docs/ai/local/checklists/ (forces --with-files)")
    parser.add_argument("--with-agents", action="store_true", help="include docs/ai/local/agents/, the project's own roles (forces --with-files)")
    parser.add_argument("--with-skills", action="store_true", help="include docs/ai/local/skills/, the project's own skills (forces --with-files)")
    parser.add_argument("--with-files", action="store_true", help="write a .zip even without --with-scripts/--with-checklists/--with-agents/--with-skills")
    parser.add_argument("--strict", action="store_true", help="abort on any finding instead of substituting a placeholder")
    parser.add_argument("--out", metavar="PATH", default=None,
                         help="output path (default: .act-local/export/act-settings-<date>.md|.zip)")
    parser.add_argument("--profile", action="store_true",
                         help="write to the Owner's profile (platform config dir) instead of "
                              "--out/the default location; backs up an existing profile file first")
    return parser


def main(argv: list[str]) -> int:
    # Settings text carries an em dash ("—") throughout; on Windows, stdout/stderr default to the
    # console's legacy code page instead of UTF-8, which would otherwise corrupt it. Same fix as
    # .act/scripts/rules.py and doctor.py.
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

    if args.profile and args.out:
        print("settings_export.py: --profile and --out are mutually exclusive", file=sys.stderr)
        return 2

    try:
        root = actlib.repo_root()
    except RuntimeError as exc:
        print(f"settings_export.py: {exc}", file=sys.stderr)
        return 2

    with_files = args.with_files or args.with_scripts or args.with_checklists or args.with_agents or args.with_skills

    areas: list[sf.SettingsArea] = []
    for area in (build_rules_area(root, args.all), build_coding_area(root, args.all)):
        if area is not None:
            areas.append(area)

    file_payload: dict[str, dict[str, str]] = {}  # area name -> {relpath: text}
    if args.with_scripts:
        area, contents = build_local_files_area(root, "scripts", "scripts")
        if area is not None:
            areas.append(area)
            file_payload["scripts"] = contents
    if args.with_checklists:
        area, contents = build_local_files_area(root, "checklists", "checklists")
        if area is not None:
            areas.append(area)
            file_payload["checklists"] = contents
    if args.with_agents:
        area, contents = build_agents_area(root)
        if area is not None:
            areas.append(area)
            file_payload["agents"] = contents
    if args.with_skills:
        area, contents = build_local_files_area(root, "skills", "skills")
        if area is not None:
            areas.append(area)
            file_payload["skills"] = contents

    settings = sf.SettingsFile(header=build_header(root), areas=areas)
    redacted, located = sf.redact(settings)
    scan_ids_and_labels(redacted, file_payload, located)

    for area_name, contents in file_payload.items():
        for rel, text in list(contents.items()):
            result = sf.scan(text)
            contents[rel] = result.text
            for finding in result.findings:
                located.append((f"{area_name}: {rel}", finding))

    if args.strict and located:
        print("settings_export.py: aborted — findings that would need a placeholder:", file=sys.stderr)
        for location, finding in located:
            print(f"  {location} — {finding.hint} ({finding.kind})", file=sys.stderr)
        return 1

    redacted.setup_required = sf.setup_required_lines(located)
    text = sf.serialize(redacted)

    # No --out and no --profile: the machine-local, gitignored .act-local/export/ (Q74b) — never
    # the project root, so a forgotten export never ends up staged for a commit. --out is used
    # exactly as given; --profile goes to the Owner's profile instead (Q57d/Q60b).
    ext = "zip" if with_files else "md"
    if args.profile:
        out_path = profile_dir() / f"settings.{ext}"
    elif args.out:
        out_path = Path(args.out)
    else:
        out_path = root / ".act-local" / "export" / f"act-settings-{settings.header.date}.{ext}"

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # An existing profile is never silently overwritten (§ "Voreinstellungen" in the concept) — a
    # settings.md/.zip already there is a prior export/import cycle's own state, not scratch output.
    # --out never gets this treatment: an explicit path is the caller's own choice to overwrite.
    backup_path: Optional[Path] = None
    if args.profile and out_path.exists():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = out_path.with_name(f"{out_path.name}.bak-{stamp}")
        out_path.replace(backup_path)

    if with_files:
        with zipfile.ZipFile(out_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("settings.md", text)
            for area_name, contents in file_payload.items():
                for rel, redacted_text in contents.items():
                    zf.writestr(f"files/{area_name}/{rel}", redacted_text)
    else:
        out_path.write_text(text, encoding="utf-8")

    print(f"settings_export.py: wrote {out_path} — review before sharing ({len(located)} placeholder(s) inserted).")
    if backup_path is not None:
        print(f"settings_export.py: existing profile backed up to {backup_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
