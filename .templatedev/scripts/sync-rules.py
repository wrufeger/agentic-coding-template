#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Haelt die Pflege-Sitzung in .templatedev/ strukturgleich zu einem echten Projekt (T5,
#        docs/project/concepts/project-structure.md). Rendert AGENTS.md, CLAUDE.md, docs/ai/README.md und
#        docs/ai/checklists.md aus dem ARBEITSSTAND des Template-Roots (eine Ebene ueber .templatedev/, NIE
#        aus einem Git-Ref) nach hierher: Platzhalter mit den Werten aus .templatedev/.claude/template.json
#        ersetzt, template-only-Abschnitte entfernt - dieselben echten Funktionen, die auch ein Projekt beim
#        Anlegen/Abschliessen durchlaeuft (setup-lib.py:remove_template_intro/replace_placeholders,
#        finish-setup.py:update_checklists - alle drei per importlib aus ../.claude/scripts/ geladen, das ist
#        lokaler Arbeitsstand, keine Kopie). Ausserdem: die Root-CLAUDE.md fuer diese Sitzung per
#        claudeMdExcludes ausschliessen (sonst laedt eine Sitzung in .templatedev/ zusaetzlich die
#        Platzhalter-Fassung des Roots) und fehlende Formulare aus docs/ai/ des Roots nachziehen (z.B.
#        board.md, questions_archive.md - vorhandene Dateien werden nie ueberschrieben).
#
# Aufruf:
#   python .templatedev/scripts/sync-rules.py --check [--quiet]
#       Prueft, ob die 4 Dateien hier noch dem Root-Arbeitsstand entsprechen, ob der CLAUDE.md-Ausschluss
#       gesetzt ist und ob Formulare fehlen. Exit 0 = alles aktuell, Exit 3 = Abweichungen (kurze Liste),
#       Exit 2 = kein gueltiger Template-Pflege-Ordner (fehlendes/falsches is_template im Root). --quiet
#       (SessionStart-Hook): bei Abweichungen hoechstens eine Zeile, sonst keine Ausgabe; ist dies KEIN
#       Pflege-Ordner, bleibt --quiet still (Exit 0) statt zu stoeren.
#   python .templatedev/scripts/sync-rules.py --diff
#       Unified Diff je abweichender Datei (aktueller Stand hier vs. gerenderter Root-Stand), dazu fehlende
#       Formulare/den CLAUDE.md-Ausschluss als Hinweiszeile. Schreibt nichts.
#   python .templatedev/scripts/sync-rules.py --apply
#       Schreibt die 4 gerenderten Dateien (nur die tatsaechlich abweichenden), setzt claudeMdExcludes in
#       .templatedev/.claude/settings.local.json (gitignored, andere Schluessel bleiben erhalten) und
#       kopiert fehlende Formulare aus dem Root nach docs/ai/ hierher.
#
# Sicherheitsregel (docs/project/coding_rules.md "Aenderungen an der Mechanik"): nie Code aus einem frisch
# geholten Git-Ref ausfuehren, erst recht nicht im --check-Pfad (SessionStart-Hook). Dieses Script liest
# ausschliesslich lokale Dateien des Arbeitsbaums (Path, kein 'git show') und laedt nur die bereits im Root
# liegenden .claude/scripts/*.py per importlib - kein Netzzugriff, kein Git-Aufruf ausser dem harmlosen,
# lokal fehlschlagenden 'git ls-files' innerhalb der temporaeren Renderkopie (files-lib.py:
# iter_repo_replace_files faellt dort auf os.walk zurueck).
#
# Exit-Codes: 0 = ok/aktuell, 2 = kein Template-Pflege-Ordner bzw. Ladefehler, 3 = Abweichungen (nur
#             --check). Ein Fehler dieses Scripts darf nie mit Traceback nach aussen dringen - main() laeuft
#             komplett in try/except, Fehlermeldungen auf stderr.

import argparse
import difflib
import importlib.util
import shutil
import sys
import tempfile
import types
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

# Root-relative Pfade, die aus dem Template-Arbeitsstand nach .templatedev/ gerendert werden - Reihenfolge
# ist auch die Reihenfolge der --check/--diff-Ausgabe.
RENDER_FILES = ["AGENTS.md", "CLAUDE.md", "docs/ai/README.md", "docs/ai/checklists.md"]
CLAUDE_MD_REL = "CLAUDE.md"

HEADER_TEMPLATE = (
    "<!-- generiert von .templatedev/scripts/sync-rules.py aus ../{rel} – nicht bearbeiten, "
    "Änderungen im Template -->"
)

_GUARD_HINT = (
    "sync-rules.py laeuft nur im Pflege-Projekt .templatedev/ eines Template-Checkouts (Root braucht "
    ".claude/template.json mit is_template: true)."
)

# Dateien direkt unter docs/ai/, die dieses Script NICHT als "fehlendes Formular" kopiert - README.md und
# checklists.md werden gerendert (RENDER_FILES), nicht roh kopiert.
_FORM_SKIP = {"README.md", "checklists.md"}


def _paths():
    """(template_root, project_root) - project_root ist IMMER .templatedev/ (parents[1] dieses Scripts unter
    .templatedev/scripts/), template_root der Ordner eine Ebene darueber. Kein CLAUDE_PROJECT_DIR-Bezug: das
    Script hat nur an genau dieser Stelle im Baum einen Sinn (siehe HEADER_TEMPLATE/_GUARD_HINT)."""
    script_path = Path(__file__).resolve()
    return script_path.parents[2], script_path.parents[1]


def _load_template_script(template_root: Path, filename: str, mod_name: str):
    """Laedt .claude/scripts/<filename> DES ROOTS (nicht dieses Ordners hier) per importlib - Bindestriche im
    Dateinamen verbieten ein normales `import`, gleiches Muster wie in allen anderen Scripten dieses
    Templates (siehe z.B. files-lib.py:_load_module)."""
    path = template_root / ".claude" / "scripts" / filename
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_libs(template_root: Path):
    """setup-lib.py (merged config-lib.py/files-lib.py/claudemd-lib.py - liefert u.a.
    is_template_maintenance_dir, remove_template_intro, replace_placeholders, die *_preserve_newline-Helfer,
    _read_json_preserve_newline/_write_json), finish-setup.py (update_checklists) und update-template.py
    (load_template_json, fuer die eigenen .templatedev/.claude/template.json-Werte)."""
    ns = types.SimpleNamespace()
    ns.setup_lib = _load_template_script(template_root, "setup-lib.py", "_sync_rules_setup_lib")
    ns.finish_setup = _load_template_script(template_root, "finish-setup.py", "_sync_rules_finish_setup")
    ns.update_template = _load_template_script(template_root, "update-template.py", "_sync_rules_update_template")
    return ns


def _prepare(template_root: Path, project_root: Path):
    """(libs oder None, ok). ok=False bei jedem Zweifel (kein Pflege-Ordner, Ladefehler) - der Aufrufer
    entscheidet, ob das im Hook-Modus still bleibt oder gemeldet wird (siehe Kopfkommentar)."""
    try:
        libs = _load_libs(template_root)
        ok = bool(libs.setup_lib.is_template_maintenance_dir(project_root))
    except Exception:  # noqa: BLE001 - darf --check --quiet nie mit Traceback stoeren
        return None, False
    return (libs if ok else None), ok


def _with_header(rel: str, text: str) -> str:
    """Fuegt HEADER_TEMPLATE oben ein. Bei CLAUDE.md muss `@AGENTS.md` die ERSTE Zeile bleiben (Claude Code
    laedt Regeldateien nur ueber diese Import-Zeile) - der Kommentar kommt direkt danach."""
    header = HEADER_TEMPLATE.format(rel=rel)
    if rel == CLAUDE_MD_REL:
        first_line, _, rest = text.partition("\n")
        return f"{first_line}\n{header}\n\n{rest.lstrip(chr(10))}"
    return f"{header}\n\n{text.lstrip(chr(10))}"


def render_files(template_root: Path, project_root: Path, libs):
    """Rendert die RENDER_FILES aus dem Root-Arbeitsstand. Rueckgabe {rel: (text, newline)} - text mit
    interner '\\n'-Normalisierung (wie files-lib.py), newline das Original-Zeilenende der Root-Quelle."""
    sl = libs.setup_lib
    values = (libs.update_template.load_template_json(project_root)[0].get("values")) or {}

    tmp_dir = Path(tempfile.mkdtemp(prefix="sync-rules-"))
    try:
        newlines = {}
        for rel in RENDER_FILES:
            text, newline = sl._read_text_preserve_newline(template_root / rel)
            dst = tmp_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            sl._write_text_preserve_newline(dst, text, newline)
            newlines[rel] = newline

        # Dieselben echten Funktionen wie beim Anlegen/Abschliessen eines Projekts - auf der TEMP-Kopie, der
        # echte Template-Root bleibt unberuehrt. remove_template_intro raeumt zusaetzlich TEMPLATE_ONLY_PATHS
        # weg (z.B. .templatedev/) - in der Temp-Kopie existieren die nicht, also ein No-op.
        sl.remove_template_intro(tmp_dir)
        libs.finish_setup.update_checklists(tmp_dir, plan=False)
        sl.replace_placeholders(tmp_dir, values)

        rendered = {}
        for rel in RENDER_FILES:
            text, _ = sl._read_text_preserve_newline(tmp_dir / rel)
            rendered[rel] = (_with_header(rel, text), newlines[rel])
        return rendered
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _read_norm(path: Path):
    """Liest `path` und normalisiert Zeilenenden auf '\\n' (wie render_files) - None, wenn die Datei fehlt
    oder nicht lesbar ist (Vergleichsbasis fuer 'fehlt' vs. 'weicht ab')."""
    if not path.exists():
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        return raw.decode("utf-8-sig").replace("\r\n", "\n")
    except UnicodeDecodeError:
        return None


def _expected_exclude(template_root: Path) -> list:
    return [(template_root / "CLAUDE.md").resolve().as_posix()]


def check_claude_md_exclude(template_root: Path, project_root: Path, libs) -> bool:
    path = project_root / ".claude" / "settings.local.json"
    if not path.exists():
        return False
    try:
        data, _newline = libs.setup_lib._read_json_preserve_newline(path)
    except (OSError, ValueError):
        return False
    vorhanden = data.get("claudeMdExcludes") if isinstance(data, dict) else None
    return isinstance(vorhanden, list) and all(e in vorhanden for e in _expected_exclude(template_root))


def ensure_claude_md_exclude(template_root: Path, project_root: Path, libs) -> str:
    """Setzt claudeMdExcludes in .templatedev/.claude/settings.local.json (gitignored) auf den absoluten
    Pfad der Root-CLAUDE.md - andere Schluessel bleiben erhalten. Atomarer Schreibweg wie ueberall sonst im
    Template (_write_json aus files-lib.py, per setup-lib.py gemergt)."""
    path = project_root / ".claude" / "settings.local.json"
    expected = _expected_exclude(template_root)
    data, newline = {}, "\n"
    if path.exists():
        try:
            data, newline = libs.setup_lib._read_json_preserve_newline(path)
        except (OSError, ValueError):
            data, newline = {}, "\n"
        if not isinstance(data, dict):
            data = {}
    vorhanden = data.get("claudeMdExcludes")
    liste = list(vorhanden) if isinstance(vorhanden, list) else ([vorhanden] if isinstance(vorhanden, str) else [])
    fehlend = [e for e in expected if e not in liste]
    if not fehlend and isinstance(vorhanden, list):
        return "settings.local.json: claudeMdExcludes bereits gesetzt."
    data["claudeMdExcludes"] = liste + fehlend  # eigene Eintraege bleiben erhalten
    path.parent.mkdir(parents=True, exist_ok=True)
    libs.setup_lib._write_json(path, data, newline)
    return "settings.local.json: claudeMdExcludes gesetzt."


def missing_forms(template_root: Path, project_root: Path):
    """Dateien direkt unter dem ROOT-docs/ai/ (dort leere Formulare, siehe AGENTS.md 'Noch nicht
    initialisiert'), die hier unter docs/ai/ noch fehlen - z.B. board.md, questions_archive.md. README.md/
    checklists.md zaehlen nicht mit (werden gerendert, nicht kopiert). Nur Dateien, keine Unterordner
    (template-feedback/ entsteht im Projekt beim ersten Versand von selbst)."""
    src_dir = template_root / "docs" / "ai"
    dst_dir = project_root / "docs" / "ai"
    if not src_dir.is_dir():
        return []
    return sorted(
        f"docs/ai/{fp.name}" for fp in src_dir.iterdir()
        if fp.is_file() and fp.name not in _FORM_SKIP and not (dst_dir / fp.name).exists()
    )


def copy_missing_forms(template_root: Path, project_root: Path):
    rels = missing_forms(template_root, project_root)
    for rel in rels:
        dst = project_root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(template_root / rel, dst)
    return rels


# ---------------------------------------------------------------------------
# Befehle
# ---------------------------------------------------------------------------


def cmd_check(template_root: Path, project_root: Path, quiet: bool) -> int:
    libs, ok = _prepare(template_root, project_root)
    if not ok:
        if quiet:
            return 0
        print(f"sync-rules.py: Fehler: {_GUARD_HINT}", file=sys.stderr)
        return 2

    rendered = render_files(template_root, project_root, libs)
    diffs = []
    for rel, (text, _newline) in rendered.items():
        current = _read_norm(project_root / rel)
        if current is None:
            diffs.append(f"{rel} (fehlt)")
        elif current != text:
            diffs.append(rel)

    if not check_claude_md_exclude(template_root, project_root, libs):
        diffs.append("Ausschluss fehlt (.claude/settings.local.json: claudeMdExcludes)")

    diffs.extend(f"{rel} (Formular fehlt)" for rel in missing_forms(template_root, project_root))

    if not diffs:
        return 0
    if quiet:
        print(
            f"sync-rules.py: {len(diffs)} Abweichung(en) zum Template - "
            "'python .templatedev/scripts/sync-rules.py --diff' pruefen."
        )
        return 3
    print("sync-rules.py: Abweichungen zum Template-Arbeitsstand:")
    for d in diffs:
        print(f"  - {d}")
    return 3


def cmd_diff(template_root: Path, project_root: Path) -> int:
    libs, ok = _prepare(template_root, project_root)
    if not ok:
        print(f"sync-rules.py: Fehler: {_GUARD_HINT}", file=sys.stderr)
        return 2

    rendered = render_files(template_root, project_root, libs)
    printed = False
    for rel, (text, _newline) in rendered.items():
        current = _read_norm(project_root / rel)
        if current == text:
            continue
        printed = True
        diff = difflib.unified_diff(
            (current or "").splitlines(keepends=True), text.splitlines(keepends=True),
            fromfile=f"a/{rel}", tofile=f"b/{rel}",
        )
        sys.stdout.writelines(diff)

    forms = missing_forms(template_root, project_root)
    if forms:
        printed = True
        print(f"Formular(e) fehlen: {', '.join(forms)}")
    if not check_claude_md_exclude(template_root, project_root, libs):
        printed = True
        print(f"settings.local.json: claudeMdExcludes fehlt/weicht ab (soll: {_expected_exclude(template_root)})")

    if not printed:
        print("sync-rules.py: keine Abweichungen.")
    return 0


def cmd_apply(template_root: Path, project_root: Path) -> int:
    libs, ok = _prepare(template_root, project_root)
    if not ok:
        print(f"sync-rules.py: Fehler: {_GUARD_HINT}", file=sys.stderr)
        return 2

    rendered = render_files(template_root, project_root, libs)
    written = []
    for rel, (text, newline) in rendered.items():
        dst = project_root / rel
        if _read_norm(dst) == text:
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        with open(dst, "w", encoding="utf-8", newline=newline) as f:
            f.write(text)
        written.append(rel)

    exclude_msg = ensure_claude_md_exclude(template_root, project_root, libs)
    forms = copy_missing_forms(template_root, project_root)

    suffix = f": {', '.join(written)}" if written else " (bereits aktuell)"
    print(f"sync-rules.py: {len(written)} Datei(en) geschrieben{suffix}.")
    print(exclude_msg)
    print(f"Formulare kopiert: {', '.join(forms)}." if forms else "Formulare: keine fehlenden.")
    return 0


# ---------------------------------------------------------------------------
# main / Argument-Parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sync-rules.py",
        description=(
            "Rendert AGENTS.md/CLAUDE.md/docs/ai/README.md/docs/ai/checklists.md aus dem Template-"
            "Arbeitsstand nach .templatedev/ und haelt den Ausschluss der Root-CLAUDE.md/fehlende "
            "Formulare aktuell."
        ),
    )
    parser.add_argument("--check", action="store_true", help="Auf Abweichungen pruefen (schreibt nichts)")
    parser.add_argument("--diff", action="store_true", help="Unified Diff je abweichender Datei (schreibt nichts)")
    parser.add_argument("--apply", action="store_true", help="Abweichungen schreiben")
    parser.add_argument("--quiet", action="store_true", help="Nur bei --check: keine Ausgabe, wenn aktuell")
    return parser


def _run(argv) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    template_root, project_root = _paths()

    if args.apply:
        return cmd_apply(template_root, project_root)
    if args.diff:
        return cmd_diff(template_root, project_root)
    if args.check:
        return cmd_check(template_root, project_root, args.quiet)

    parser.print_usage(sys.stderr)
    return 2


def main() -> int:
    try:
        return _run(sys.argv[1:])
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 - darf nie mit Traceback nach aussen dringen
        print(f"sync-rules.py: Fehler: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
