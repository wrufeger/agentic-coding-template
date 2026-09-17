#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Letzter Schritt nach "Neues Projekt"/"Projekt nachruesten" (siehe docs/ai/checklists.md) - entfernt
#        alle Spuren der Einrichtungswerkzeuge aus einem fertig eingerichteten Projekt, AUSSER dem
#        Update-Weg (der bleibt dauerhaft nutzbar). Siehe AGENTS.md, CLAUDE.md. Reine Python-Stdlib, kein
#        Paket noetig.
#
# Aufruf:
#   python .claude/scripts/finish-setup.py [--plan]
#       (Default, auch ohne Argument) Zeigt nur, was passieren wuerde - schreibt/loescht nichts.
#   python .claude/scripts/finish-setup.py --apply
#       Fuehrt die Aufraeumung tatsaechlich aus.
#   python .claude/scripts/finish-setup.py --check [--quiet]
#       Fuer den SessionStart-Hook (.claude/settings.json): erinnert daran, dass der Abschluss (Skill
#       `/act-finalize`) noch aussteht. Faellig = `.claude/template.json` hat kein `setup_complete: true` UND
#       mindestens eine Datei/ein Ordner aus REMOVE_ITEMS liegt noch im Repo. Faellig -> kurze Erinnerung
#       (2-3 Zeilen) auf stdout, Exit 3. Nicht faellig (setup_complete bereits true, nichts mehr aus
#       REMOVE_ITEMS vorhanden, template.json fehlt/kaputt, oder Template-Checkout selbst) -> KEINE Ausgabe,
#       Exit 0 - der Normalfall bei jeder Sitzung, darf nichts kosten. --quiet aendert daran nichts (wie bei
#       maintenance-check.py --check: die Ausgabe ist bereits so kurz, dass es nichts zu unterdruecken gibt;
#       der Schalter existiert nur aus Konsistenz mit update-template.py/sync-config.py). --check schreibt
#       nie etwas.
#
# Schutz Template-Checkout: traegt .claude/template.json den Marker `is_template: true` (das Template-Repo
#   selbst, in dem die Einrichtungswerkzeuge gepflegt statt entfernt werden), verweigern --plan/--apply den
#   Dienst (Meldung auf stderr, Exit 2) - --check bleibt dort ebenfalls still (Exit 0), wie oben beschrieben.
#
# Entfernt (jeweils nur, wenn vorhanden - fehlende Eintraege sind kein Fehler):
#   .claude/scripts/create-project.py, .claude/scripts/apply-template.py,
#   .claude/scripts/migrate-project.py, .claude/scripts/install-global.py,
#   .claude/skills/act-create-project/, .claude/skills/act-apply-template/, .claude/skills/act-finalize/
#   (der Skill, der dieses Script aufruft - danach zeigt er ins Leere; zusaetzlich die alten,
#   unpraefigierten Ordnernamen als Uebergang fuer Projekte vor dem act-Praefix, siehe REMOVE_ITEMS),
#   .claude/TEMPLATE-LICENSE (nur wenn das Projekt eine eigene LICENSE/LICENSE.md/LICENSE.txt hat - sonst
#   bleibt sie liegen und wird gemeldet), sich selbst (.claude/scripts/finish-setup.py, immer zuletzt).
#   Getrackte Dateien/Ordner werden per "git rm" entfernt, sonst per Dateisystem (shutil/Path.unlink).
#   Ist das Repo gar nicht unter Git, wird das gemeldet und komplett auf dem Dateisystem gearbeitet.
#
# Bleibt ausdruecklich unangetastet: update-template.py, sync-config.py, guidelines.py, ai-log.py,
#   setup-lib.py, rename-lib.py, maintenance-check.py, die Skills act-update-template/act-commit/act-audit-docs,
#   sowie alles unter docs/, was Projektinhalt ist. Dieses Script ruehrt keine dieser Dateien an.
#
# Weitere Schritte:
#   - .claude/template.json: setzt "setup_complete": true und "setup_completed_at": "<heute, YYYY-MM-DD>".
#     Vorhandene Felder bleiben erhalten (nur gelesen, zwei Felder ergaenzt, atomar zurueckgeschrieben -
#     Temp-Datei im selben Ordner, dann os.replace, kein Ueberrest im Fehlerfall). Fehlt/ist kaputt die
#     Datei, wird das unter "Noch einzuarbeiten" gemeldet, nichts geschrieben.
#   - .claude/settings.json: entfernt aus hooks.SessionStart genau die Eintraege, deren "command"
#     "finish-setup.py" enthaelt (der eigene Erinnerungs-Hook), andere Hooks (ai-log, update-template,
#     sync-config, maintenance-check) bleiben stehen. Wird SessionStart dadurch leer, entfaellt der
#     Schluessel, wird hooks dadurch leer, ebenfalls. Format/Zeilenende bleiben erhalten (atomar
#     geschrieben wie template.json). Fehlt die Datei/der Eintrag, nur eine Zeile in der Ausgabe, kein
#     Fehler. Gleiches Muster wie remove_maintenance_hook() in create-project.py/setup-lib.py.
#   - docs/ai/checklists.md: entfernt die Abschnitte "## Neues Projekt", "## Projekt nachruesten" und
#     "## Einrichtung abschliessen" - alle drei beschreiben die Einrichtung und fuehren danach in die Irre
#     (ueberschriftenbasiert: von der Ueberschrift bis zur naechsten gleichrangigen Ueberschrift), inkl.
#     etwaiger Inhaltsverzeichnis-Zeilen, die per Markdown-Link auf einen der Abschnitte verweisen.
#     Nur wenn ALLE Ueberschriften genau einmal gefunden werden - sonst bleibt die Datei unangetastet und
#     wird unter "Noch einzuarbeiten" gemeldet.
#   - Meldet (loescht nichts), ob fremde KI-Regeldateien mit echtem Inhalt im Repo liegen
#     (.junie/guidelines.md, .clinerules, .windsurfrules, .cursorrules, .github/instructions/, AGENT.md,
#     .roorules). "Echter Inhalt" = mehr als 15 Zeilen und keine Zeile verweist auf "AGENTS.md".
#
# Exit-Codes: 0 = ok (--plan/--apply, auch wenn Einzelpunkte unter "Noch einzuarbeiten" offen blieben; sowie
#   --check, wenn nichts faellig ist), 2 = Vorbedingungsfehler (unbekannte Argumente, --plan/--apply im
#   Template-Checkout), 3 = --check: Abschluss steht aus. Root kommt aus CLAUDE_PROJECT_DIR, sonst aus dem
#   Pfad dieses Scripts (parents[2]). main() laeuft komplett in try/except - kein Traceback nach aussen.

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

REMOVE_ITEMS = [
    (".claude/scripts/create-project.py", "file"),
    (".claude/scripts/apply-template.py", "file"),
    (".claude/scripts/migrate-project.py", "file"),
    (".claude/scripts/install-global.py", "file"),
    (".claude/skills/act-create-project", "dir"),
    (".claude/skills/act-apply-template", "dir"),
    # Der Skill, der dieses Script aufruft - nach dem Abschluss zeigt er ins Leere und muss mit weg.
    (".claude/skills/act-finalize", "dir"),
    # Altname vor act-Praefix, 2026-09-17: faengt Projekte ab, die den Umbenennungs-Merge noch nicht
    # eingespielt haben und die Skill-Ordner noch unter dem alten Namen liegen haben.
    (".claude/skills/create-project", "dir"),
    (".claude/skills/apply-template", "dir"),
    (".claude/skills/finalize", "dir"),
]
TEMPLATE_LICENSE_REL = ".claude/TEMPLATE-LICENSE"
OWN_LICENSE_NAMES = ("LICENSE", "LICENSE.md", "LICENSE.txt")
SELF_REL = ".claude/scripts/finish-setup.py"
TEMPLATE_JSON_REL = ".claude/template.json"
SETTINGS_JSON_REL = ".claude/settings.json"
CHECKLISTS_REL = "docs/ai/checklists.md"
CHECKLIST_TITLES = ["Neues Projekt", "Projekt nachrüsten", "Einrichtung abschließen"]
FOREIGN_RULE_FILES = [
    ".junie/guidelines.md",
    ".clinerules",
    ".windsurfrules",
    ".cursorrules",
    "AGENT.md",
    ".roorules",
]
FOREIGN_RULE_DIRS = [".github/instructions"]
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")


# ---------------------------------------------------------------------------
# Grundlagen
# ---------------------------------------------------------------------------


def _find_root() -> Path:
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[2]


def _is_git_repo(root: Path) -> bool:
    try:
        res = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return res.returncode == 0 and res.stdout.strip() == "true"


def _git_tracked(root: Path, rel: str) -> bool:
    try:
        res = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--error-unmatch", "--", rel],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return res.returncode == 0


def _git_rm(root: Path, rel: str, is_dir: bool) -> None:
    args = ["git", "-C", str(root), "rm", "-f"]
    if is_dir:
        args.append("-r")
    args += ["--", rel]
    res = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if res.returncode != 0:
        raise RuntimeError((res.stderr or res.stdout).strip() or "git rm fehlgeschlagen")


def _remove(root: Path, rel: str, kind: str, is_git: bool) -> None:
    """Entfernt eine Datei/einen Ordner per git rm (falls getrackt) oder Dateisystem."""
    p = root / rel
    if is_git and _git_tracked(root, rel):
        _git_rm(root, rel, kind == "dir")
        return
    if kind == "dir":
        shutil.rmtree(p)
    else:
        p.unlink()


def _has_own_license(root: Path) -> bool:
    return any((root / name).is_file() for name in OWN_LICENSE_NAMES)


def _load_template_json(root: Path):
    """Gibt das geparste template.json als dict zurueck, oder None (fehlt/kaputt/kein Objekt) - beides ein
    stiller, kein fehlerhafter Zustand fuer --check und den Template-Guard."""
    path = root / TEMPLATE_JSON_REL
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _load_config_lib_module():
    """config-lib.py per importlib (gleicher Ordner) - nur fuer is_template_maintenance_dir()/
    TEMPLATE_MAINTENANCE_DIR_HINWEIS (T5), sonst bleibt dieses Script bewusst frei von der Bibliothek."""
    cl_path = Path(__file__).resolve().parent / "config-lib.py"
    spec = importlib.util.spec_from_file_location("_finish_setup_config_lib", cl_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _is_template_checkout(root: Path) -> bool:
    data = _load_template_json(root)
    return bool(data) and data.get("is_template") is True


# ---------------------------------------------------------------------------
# .claude/template.json
# ---------------------------------------------------------------------------


def _atomic_write_json(path: Path, data: dict, newline: str = "\n") -> None:
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline=newline,
            dir=str(path.parent),
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as f:
            tmp_path = f.name
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    except BaseException:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


def _read_json_preserve_newline(path: Path):
    """Liest eine JSON-Datei und liefert (data, newline) - newline ist 'CRLF' falls in der Rohdatei
    enthalten, sonst 'LF' - zum formatwahrenden Zurueckschreiben mit _atomic_write_json(..., newline=...).
    Wirft OSError/ValueError (kaputtes JSON), vom Aufrufer abzufangen. Gleiches Muster wie
    create-project.py/setup-lib.py."""
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    data = json.loads(raw.decode("utf-8"))
    return data, newline


def update_template_json(root: Path, plan: bool, today_str: str):
    """Gibt (label, todo_hinweis) zurueck. label ist None, wenn nichts zu tun ist (bereits gesetzt)."""
    path = root / TEMPLATE_JSON_REL
    if not path.exists():
        return None, f"{TEMPLATE_JSON_REL} fehlt - setup_complete konnte nicht gesetzt werden."
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"{TEMPLATE_JSON_REL} nicht lesbar ({exc}) - setup_complete nicht gesetzt."
    if not isinstance(data, dict):
        return None, f"{TEMPLATE_JSON_REL} ist kein JSON-Objekt - setup_complete nicht gesetzt."
    if data.get("setup_complete") is True and data.get("setup_completed_at"):
        return None, None
    if plan:
        return f"{TEMPLATE_JSON_REL}: setup_complete/setup_completed_at setzen", None
    data["setup_complete"] = True
    data["setup_completed_at"] = today_str
    _atomic_write_json(path, data)
    return f"{TEMPLATE_JSON_REL}: setup_complete=true, setup_completed_at={today_str}", None


# ---------------------------------------------------------------------------
# .claude/settings.json - eigenen SessionStart-Hook entfernen
# ---------------------------------------------------------------------------


def remove_finish_setup_hook(root: Path, plan: bool):
    """Gibt (label, todo_hinweis) zurueck. Entfernt aus .claude/settings.json nur SessionStart-Hooks, deren
    Kommando 'finish-setup.py' enthaelt - andere Hooks (ai-log, update-template, sync-config,
    maintenance-check) bleiben unangetastet. Wird SessionStart dadurch leer, wird der Schluessel entfernt;
    wird hooks dadurch leer, ebenfalls. Format (Einrueckung, Zeilenende, Reihenfolge) bleibt erhalten -
    gleiches Muster wie remove_maintenance_hook() in create-project.py/setup-lib.py, hier nur ohne die dort
    zusaetzliche CLAUDE_PROJECT_DIR-Bedingung (der Auftrag verlangt nur den Treffer auf 'finish-setup.py')."""
    path = root / SETTINGS_JSON_REL
    if not path.exists():
        return None, f"{SETTINGS_JSON_REL} fehlt - SessionStart-Hook nicht entfernt."
    try:
        data, newline = _read_json_preserve_newline(path)
    except (OSError, ValueError) as exc:
        return None, f"{SETTINGS_JSON_REL} nicht lesbar ({exc}) - SessionStart-Hook nicht entfernt."
    if not isinstance(data, dict):
        return None, f"{SETTINGS_JSON_REL} ist kein JSON-Objekt - SessionStart-Hook nicht entfernt."

    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return None, None
    session_start = hooks.get("SessionStart")
    if not isinstance(session_start, list):
        return None, None

    new_list = [e for e in session_start if "finish-setup.py" not in json.dumps(e, ensure_ascii=False)]
    if len(new_list) == len(session_start):
        return None, None

    if plan:
        return f"{SETTINGS_JSON_REL}: SessionStart-Hook fuer finish-setup.py entfernen", None

    if new_list:
        hooks["SessionStart"] = new_list
    else:
        del hooks["SessionStart"]
    if not hooks:
        del data["hooks"]
    _atomic_write_json(path, data, newline)
    return f"{SETTINGS_JSON_REL}: SessionStart-Hook fuer finish-setup.py entfernt", None


# ---------------------------------------------------------------------------
# docs/ai/checklists.md
# ---------------------------------------------------------------------------


def _find_heading(lines, title):
    return [i for i, line in enumerate(lines) if HEADING_RE.match(line) and HEADING_RE.match(line).group(2).strip() == title]


def _section_end(lines, start_idx, level):
    for j in range(start_idx + 1, len(lines)):
        m = HEADING_RE.match(lines[j])
        if m and len(m.group(1)) <= level:
            return j
    return len(lines)


def update_checklists(root: Path, plan: bool):
    """Gibt (label, todo_hinweis) zurueck."""
    path = root / CHECKLISTS_REL
    if not path.exists():
        return None, f"{CHECKLISTS_REL} fehlt - Abschnitte nicht entfernt."
    text = path.read_text(encoding="utf-8")
    trailing_newline = text.endswith("\n")
    lines = text.split("\n")
    if trailing_newline:
        lines = lines[:-1]

    ranges = {}
    for title in CHECKLIST_TITLES:
        idxs = _find_heading(lines, title)
        if len(idxs) != 1:
            found = "fehlt" if not idxs else f"{len(idxs)}x vorhanden"
            return None, (
                f"{CHECKLISTS_REL}: Ueberschrift '## {title}' {found} - nicht eindeutig, Datei "
                "unangetastet gelassen."
            )
        start = idxs[0]
        level = len(HEADING_RE.match(lines[start]).group(1))
        ranges[title] = (start, _section_end(lines, start, level))

    remove_idx = set()
    for start, end in ranges.values():
        remove_idx.update(range(start, end))
    for i, line in enumerate(lines):
        if i in remove_idx or HEADING_RE.match(line):
            continue
        for title in CHECKLIST_TITLES:
            if re.search(r"\[\s*" + re.escape(title) + r"\s*\]\(", line):
                remove_idx.add(i)
                break

    if plan:
        return f"{CHECKLISTS_REL}: Abschnitte {', '.join(CHECKLIST_TITLES)} entfernen", None

    new_lines = [line for i, line in enumerate(lines) if i not in remove_idx]
    new_text = "\n".join(new_lines) + ("\n" if trailing_newline else "")
    path.write_text(new_text, encoding="utf-8", newline="\n")
    return f"{CHECKLISTS_REL}: Abschnitte {', '.join(CHECKLIST_TITLES)} entfernt", None


# ---------------------------------------------------------------------------
# Fremde KI-Regeldateien (nur Meldung, keine Aenderung)
# ---------------------------------------------------------------------------


def _has_real_content(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    lines = text.splitlines()
    if len(lines) <= 15:
        return False
    return not any("AGENTS.md" in line for line in lines)


def check_foreign_rules(root: Path):
    findings = []
    for rel in FOREIGN_RULE_FILES:
        p = root / rel
        if p.is_file() and _has_real_content(p):
            findings.append(rel)
    for rel in FOREIGN_RULE_DIRS:
        d = root / rel
        if d.is_dir():
            for f in sorted(d.rglob("*")):
                if f.is_file() and _has_real_content(f):
                    findings.append(str(f.relative_to(root)).replace("\\", "/"))
    return findings


# ---------------------------------------------------------------------------
# --check (SessionStart-Hook)
# ---------------------------------------------------------------------------


def cmd_check(root: Path, quiet: bool) -> int:
    """quiet aendert das Verhalten bewusst nicht (wie maintenance-check.py --check): die Erinnerung ist
    bereits so kurz, dass es nichts zu unterdruecken gibt - der Schalter existiert nur aus Konsistenz mit
    update-template.py/sync-config.py."""
    del quiet
    data = _load_template_json(root)
    if not data or data.get("is_template") is True or data.get("setup_complete") is True:
        return 0
    if _load_config_lib_module().is_template_maintenance_dir(root):
        return 0
    remaining = sum(1 for rel, _kind in REMOVE_ITEMS if (root / rel).exists())
    if remaining == 0:
        return 0
    print("Einrichtung noch nicht abgeschlossen: Einrichtungswerkzeuge liegen noch im Projekt.")
    print(f"{remaining} Einrichtungsdatei(en)/-ordner betroffen.")
    print("Alles fertig? Mit /act-finalize abschliessen - das entfernt sie.")
    return 3


# ---------------------------------------------------------------------------
# Hauptablauf
# ---------------------------------------------------------------------------


def run(root: Path, plan: bool) -> int:
    if _is_template_checkout(root):
        print(
            "finish-setup.py: Dies ist der Template-Checkout selbst (is_template) - hier werden die "
            "Einrichtungswerkzeuge gepflegt, nicht geloescht. Abbruch.",
            file=sys.stderr,
        )
        return 2
    cl = _load_config_lib_module()
    if cl.is_template_maintenance_dir(root):
        print(f"finish-setup.py: Fehler: {cl.TEMPLATE_MAINTENANCE_DIR_HINWEIS}", file=sys.stderr)
        return 2
    is_git = _is_git_repo(root)

    removed = []
    skipped = []
    kept = []
    changed = []
    todo = []

    print(f"finish-setup.py - Modus: {'PLAN' if plan else 'APPLY'}")
    print(f"Projekt: {root}")
    if not is_git:
        print("Hinweis: kein Git-Repository erkannt - arbeite direkt auf dem Dateisystem.")
    print()

    for rel, kind in REMOVE_ITEMS:
        p = root / rel
        if not p.exists():
            skipped.append(rel)
            continue
        if plan:
            removed.append(rel)
            continue
        try:
            _remove(root, rel, kind, is_git)
            removed.append(rel)
        except (OSError, RuntimeError) as exc:
            todo.append(f"{rel}: Entfernen fehlgeschlagen ({exc})")

    lic_path = root / TEMPLATE_LICENSE_REL
    if not lic_path.exists():
        skipped.append(TEMPLATE_LICENSE_REL)
    elif not _has_own_license(root):
        kept.append(f"{TEMPLATE_LICENSE_REL} (keine eigene LICENSE im Projekt gefunden)")
    elif plan:
        removed.append(TEMPLATE_LICENSE_REL)
    else:
        try:
            _remove(root, TEMPLATE_LICENSE_REL, "file", is_git)
            removed.append(TEMPLATE_LICENSE_REL)
        except (OSError, RuntimeError) as exc:
            todo.append(f"{TEMPLATE_LICENSE_REL}: Entfernen fehlgeschlagen ({exc})")

    today_str = date.today().strftime("%Y-%m-%d")
    label, hint = update_template_json(root, plan, today_str)
    if label:
        changed.append(label)
    if hint:
        todo.append(hint)

    label, hint = remove_finish_setup_hook(root, plan)
    if label:
        changed.append(label)
    if hint:
        todo.append(hint)

    label, hint = update_checklists(root, plan)
    if label:
        changed.append(label)
    if hint:
        todo.append(hint)

    for rel in check_foreign_rules(root):
        todo.append(
            f"{rel}: enthaelt eigenen Regelinhalt - gehoert nach docs/project/coding_rules.md, "
            "Datei danach nur noch mit Verweis auf AGENTS.md."
        )

    kept.append(
        "update-template.py, sync-config.py, guidelines.py, ai-log.py, setup-lib.py, rename-lib.py, "
        "maintenance-check.py sowie die Skills act-update-template/act-commit/act-audit-docs (unangetastet)"
    )

    if plan:
        removed.append(f"{SELF_REL} (zuletzt)")
    else:
        try:
            _remove(root, SELF_REL, "file", is_git)
            removed.append(SELF_REL)
        except (OSError, RuntimeError) as exc:
            todo.append(f"{SELF_REL}: Entfernen fehlgeschlagen ({exc})")

    def _print_block(title, items):
        print(title + ":")
        if items:
            for item in items:
                print(f"  - {item}")
        else:
            print("  (keine)")
        print()

    _print_block("Entfernt" if not plan else "Wird entfernt", removed)
    _print_block("Geändert" if not plan else "Wird geändert", changed)
    _print_block("Übersprungen (nicht vorhanden)", skipped)
    _print_block("Bleibt bewusst liegen", kept)
    _print_block("Noch einzuarbeiten", todo)

    if plan:
        print("Naechster Schritt: Plan pruefen, dann mit --apply ausfuehren.")
    else:
        print("Naechster Schritt: Ergebnis pruefen, dann Commit per Pathspec (Checkliste \"Aufgabe abschliessen\").")
    return 0


def main(argv=None) -> int:
    try:
        parser = argparse.ArgumentParser(
            description="Entfernt die Einrichtungswerkzeuge aus einem fertig eingerichteten Projekt."
        )
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--plan", action="store_true", help="Nur zeigen, was passieren wuerde (Default).")
        group.add_argument("--apply", action="store_true", help="Aenderungen tatsaechlich ausfuehren.")
        group.add_argument("--check", action="store_true", help="Fuer den SessionStart-Hook: Erinnerung, wenn der Abschluss noch aussteht.")
        parser.add_argument("--quiet", action="store_true", help="Nur zusammen mit --check (siehe Kopfkommentar; aendert das Verhalten hier nicht).")
        args = parser.parse_args(argv)
        root = _find_root()
        if args.check:
            return cmd_check(root, args.quiet)
        plan = not args.apply
        return run(root, plan)
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else 2
        return code if code == 0 else 2
    except Exception as exc:  # noqa: BLE001 - nie ein Traceback nach aussen
        print(f"finish-setup.py: Fehler - {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
