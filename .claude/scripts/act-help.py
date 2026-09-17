#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Uebersicht der Projekt-Befehle (/act-…) wie eine man page - Name, Parameter, Kurzbeschreibung,
#        Ausloeser. Liest das Frontmatter aller .claude/skills/*/SKILL.md, deshalb nie veraltet. Sucht dafuer
#        (wie Claude Code selbst) vom Projektordner aufwaerts bis zum Git-Root (`git rev-parse
#        --show-toplevel`, sonst nur der Projektordner) - so findet eine Sitzung in einem Unterordner ohne
#        eigenes ".claude/skills" (z. B. die Pflege-Sitzung in .templatedev/) auch die im Root vererbten
#        Projektbefehle. Bei gleichem Skill-Ordnernamen gewinnt der naehere Ordner (siehe _skill_files()).
#        Wird vom Skill /act aufgerufen, laeuft aber auch direkt. Reine Python-Stdlib.
#
#        Filtert nach Stand des Repos (B48/T5, docs/ai/backlog.md): ein Frontmatter-Feld "phase" je
#        Skill ("setup" | "maintenance", Default "project" - steht seit T5 unter "metadata:", ein flaches
#        "phase:" wird zur Rueckwaertskompatibilitaet weiterhin gelesen) wird gegen .claude/template.json bzw.
#        gegen den Pfad geprueft:
#          - Projektordner ist die Pflege-Sitzung des Templates (".templatedev/" mit "is_template: true" im
#            Root, siehe config-lib.py:is_template_maintenance_dir, T5 Entscheidung Q19 b - kein Marker mehr,
#            eine Sitzung im Template-Root selbst verhaelt sich IMMER wie ein frischer Klon)
#                                                                  -> nur "project" + "maintenance", nie "setup"
#          - keine template.json/nicht lesbar                 -> keine Filterung, alles zeigen
#          - is_template true                                 -> nur "setup" (frischer Klon zum Anlegen)
#          - is_template fehlt, setup_complete (noch) nicht gesetzt -> "setup" + "project" (Weg-2-Ziel:
#                                                                     apply-template.py hat schon kopiert,
#                                                                     die Einrichtung laeuft noch dort - z. B.
#                                                                     act-apply-template bleibt sichtbar)
#          - is_template fehlt, setup_complete gesetzt              -> nur "project" (Einrichtung fertig)
#
# Aufruf:
#   python .claude/scripts/act-help.py            # passende Befehle, je zwei bis drei Zeilen
#   python .claude/scripts/act-help.py all        # wie oben, aber ALLE Befehle, ausgeblendete markiert
#   python .claude/scripts/act-help.py commit     # ein Befehl ausfuehrlich (mit oder ohne act-, auch Teilname;
#                                                 # auch wenn er gerade ausgeblendet ist, dann mit Hinweis)
#   python .claude/scripts/act-help.py --hook     # UserPromptSubmit-Hook: bei Eingabe "/act [name|all]" die
#                                                 # Liste sofort zeigen und die Eingabe NICHT ans Modell geben
#
# Ausgabeformat: Klartext, feste Einrueckung. Exit 0 = ok, 1 = kein passender Befehl, 2 = kein Skill-Ordner.

import io
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

BREITE = 100


def _root() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[2]


def _frontmatter(datei: Path) -> dict:
    """Einfache Schluessel: Wert-Zeilen zwischen den beiden '---' - mehr brauchen SKILL.md-Dateien nicht.
    Ein eingerueckter Block unter einem Top-Level-Schluessel ohne eigenen Wert (z. B. "metadata:") wird EINE
    Ebene tief mitgelesen und als "<eltern>.<kind>" abgelegt (T5: "metadata: / phase: setup" statt eines
    flachen "phase: setup") - kein YAML-Parser, nur genau so viel wie SKILL.md-Frontmatter braucht."""
    werte = {}
    zeilen = datei.read_text(encoding="utf-8").splitlines()
    if not zeilen or zeilen[0].strip() != "---":
        return werte
    eltern = None
    for zeile in zeilen[1:]:
        if zeile.strip() == "---":
            break
        if not zeile.strip():
            continue
        if not zeile.startswith(" "):
            schluessel, _, wert = zeile.partition(":")
            schluessel = schluessel.strip()
            wert = wert.strip().strip('"')
            werte[schluessel] = wert
            eltern = schluessel if not wert else None
        elif eltern and ":" in zeile:
            unter_schluessel, _, unter_wert = zeile.strip().partition(":")
            werte[f"{eltern}.{unter_schluessel.strip()}"] = unter_wert.strip().strip('"')
    return werte


_PHASEN = {"setup", "maintenance", "project"}


def _phase(fm: dict) -> str:
    """Frontmatter-Wert "metadata.phase" (T5), zur Rueckwaertskompatibilitaet ersatzweise das alte flache
    "phase" - normalisiert: Kommentar (#...) und Quotes abschneiden, kleinschreiben. Leer oder unbekannt
    zaehlt als "project" (Default-Phase)."""
    wert = fm.get("metadata.phase") or fm.get("phase", "")
    wert = wert.split("#", 1)[0].strip().strip("\"'").lower()
    return wert if wert in _PHASEN else "project"


def _git_toplevel(start: Path):
    """Git-Root von `start` aus (`git rev-parse --show-toplevel`), oder None (kein Repo, `git` fehlt,
    Timeout) - dann greift in `_skill_search_dirs` der Rueckfall auf den Projektordner allein."""
    try:
        ergebnis = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(start), capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if ergebnis.returncode != 0:
        return None
    ausgabe = ergebnis.stdout.strip()
    if not ausgabe:
        return None
    try:
        return Path(ausgabe).resolve()
    except OSError:
        return None


def _skill_search_dirs(root: Path) -> list:
    """Ordner, in denen nach '.claude/skills/*/SKILL.md' gesucht wird: `root` selbst, dann aufwaerts bis zum
    Git-Root (`git rev-parse --show-toplevel`), naehester Ordner zuerst - so wie Claude Code Skills selbst
    findet. Ausserhalb eines Git-Repos, oder wenn `git` fehlschlaegt, nur `root` allein. Das faengt die
    Pflege-Sitzung in `.templatedev/` (kein eigenes Git-Repo, aber Unterordner des Template-Checkouts) ein:
    Projektbefehle wie /act-idea liegen nur im Root und werden sonst nicht gefunden."""
    root = root.resolve()
    kette = [root]
    top = _git_toplevel(root)
    if top is not None and top != root and top in root.parents:
        aktuell = root
        while aktuell != top:
            aktuell = aktuell.parent
            kette.append(aktuell)
    return kette


def _skill_files(root: Path) -> list:
    """SKILL.md-Dateien aus '.claude/skills' aller Ordner in `_skill_search_dirs(root)`, naehester zuerst.
    Bei gleichem Skill-Ordnernamen (z.B. eine Sperr-Fassung in `.templatedev/.claude/skills/`, die einen
    gleichnamigen Skill im Root ueberschreibt) gewinnt der naehere - der entferntere wird ignoriert, nicht
    zusaetzlich gelistet."""
    gesehen = set()
    dateien = []
    for verzeichnis in _skill_search_dirs(root):
        skills_ordner = verzeichnis / ".claude" / "skills"
        if not skills_ordner.is_dir():
            continue
        for datei in sorted(skills_ordner.glob("*/SKILL.md")):
            skill_ordner_name = datei.parent.name
            if skill_ordner_name in gesehen:
                continue
            gesehen.add(skill_ordner_name)
            dateien.append(datei)
    return dateien


def _befehle(dateien: list) -> list:
    """Nur echte Projekt-Befehle (Praefix 'act-'). Weiterleitungs-Skills ohne Praefix (commit, idea, prepare,
    update-template - Q17 in docs/ai/questions.md) tauchen hier nicht als eigene Befehle auf, siehe
    _kurzformen()."""
    befehle = []
    for datei in dateien:
        fm = _frontmatter(datei)
        name = fm.get("name") or datei.parent.name
        if name == "act" or not name.startswith("act-"):
            continue
        beschreibung = fm.get("description", "")
        kurz, _, ausloeser = beschreibung.partition(" Auslöser - ")
        befehle.append({"name": name, "hint": fm.get("argument-hint", ""), "kurz": kurz.strip(),
                        "ausloeser": ausloeser.strip(), "phase": _phase(fm)})
    return befehle


def _kurzformen(dateien: list) -> list:
    """Namen der Weiterleitungs-Skills ohne 'act-'-Praefix (z.B. 'commit' fuer /act-commit) - nur als
    Alias-Hinweis in der Gesamtuebersicht, nie als eigener Befehl gelistet."""
    namen = []
    for datei in dateien:
        fm = _frontmatter(datei)
        name = fm.get("name") or datei.parent.name
        if name != "act" and not name.startswith("act-"):
            namen.append(name)
    return namen


def _template_config(root: Path):
    """Gibt .claude/template.json als dict zurueck, oder None (Datei fehlt/nicht lesbar/kein Objekt) -
    dann wird nicht gefiltert."""
    pfad = root / ".claude" / "template.json"
    if not pfad.is_file():
        return None
    try:
        daten = json.loads(pfad.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return daten if isinstance(daten, dict) else None


def _load_config_lib_module(root: Path):
    """config-lib.py per importlib (gleicher Ordner) - nur fuer is_template_maintenance_dir() (T5). None bei
    fehlender/kaputter Datei, damit ein Ladefehler hier nie die Befehlsuebersicht selbst zum Absturz bringt."""
    cl_path = Path(__file__).resolve().parent / "config-lib.py"
    if not cl_path.is_file():
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_act_help_config_lib", cl_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:  # noqa: BLE001 - darf /act nie blockieren
        return None


def _erlaubte_phasen(root: Path):
    """Liefert (erlaubte Phasen als Menge oder None fuer 'keine Filterung', Kurzbegruendung fuer /act all)."""
    cl = _load_config_lib_module(root)
    if cl is not None and cl.is_template_maintenance_dir(root):
        return ({"project", "maintenance"},
                "Pflege-Sitzung des Templates (.templatedev/) - nur Projektbefehle + Wartung, nie Einrichtung")
    cfg = _template_config(root)
    if cfg is None:
        return None, "keine .claude/template.json - keine Filterung"
    if cfg.get("is_template"):
        return {"setup"}, "Template-Checkout - frischer Klon zum Anlegen"
    if cfg.get("setup_complete"):
        return {"project"}, "Einrichtung abgeschlossen (setup_complete)"
    return ({"setup", "project"},
            "Einrichtung laeuft (is_template fehlt, setup_complete noch nicht gesetzt) - "
            "act-apply-template bleibt sichtbar")


def _absatz(text: str, einzug: str) -> str:
    return textwrap.fill(text, BREITE, initial_indent=einzug, subsequent_indent=einzug)


def _hook() -> int:
    """Liest die Hook-Nutzlast. Nur bei genau "/act" oder "/act <name>" wird geblockt - dann zeigt Claude Code
    den Grund (die Liste) an, ohne das Modell zu fragen. Alles andere laeuft unveraendert weiter (Exit 0)."""
    try:
        prompt = json.loads(sys.stdin.read() or "{}").get("prompt", "")
    except (ValueError, AttributeError):
        return 0
    m = re.fullmatch(r"\s*/act(?:\s+(\S+))?\s*", prompt or "")  # (\S+) faengt auch "all"
    if not m:
        return 0
    puffer = io.StringIO()
    alt = sys.stdout
    sys.stdout = puffer
    try:
        _ausgabe(m.group(1) or "")
    finally:
        sys.stdout = alt
    sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None
    print(json.dumps({"decision": "block", "reason": puffer.getvalue().rstrip()}, ensure_ascii=False))
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if sys.argv[1:] == ["--hook"]:
        return _hook()
    return _ausgabe(sys.argv[1] if len(sys.argv) > 1 else "")


def _ausgabe(argument: str) -> int:
    root = _root()
    dateien = _skill_files(root)
    if not dateien:
        print(f"Kein Skill-Ordner unter {root}/.claude/skills (auch nicht vererbt von Ordnern darueber "
              "bis zum Git-Root).")
        return 2
    befehle = _befehle(dateien)
    erlaubt, begruendung = _erlaubte_phasen(root)
    sichtbar = lambda b: erlaubt is None or b["phase"] in erlaubt  # noqa: E731

    alle_zeigen = argument.strip().lower() == "all"
    suche = "" if alle_zeigen else argument.lower().removeprefix("/").removeprefix("act-")

    if suche:
        treffer = [b for b in befehle if b["name"].removeprefix("act-") == suche] or \
                  [b for b in befehle if suche in b["name"]]
        if not treffer:
            print(f"Kein Befehl passt zu '{argument}'. Uebersicht: /act")
            return 1
        for b in treffer:
            print(f"/{b['name']} {b['hint']}".rstrip())
            print(_absatz(b["kurz"], "    "))
            if b["ausloeser"]:
                print(_absatz("Auslöser: " + b["ausloeser"], "    "))
            if not sichtbar(b):
                print(_absatz(f"Hinweis: passt derzeit nicht zum Stand dieses Repos ({begruendung}) und "
                              "wird in der Uebersicht /act ausgeblendet - siehe /act all.", "    "))
            print(f"    Anleitung: .claude/skills/{b['name']}/SKILL.md")
            print()
        return 0

    if alle_zeigen:
        print("PROJEKT-BEFEHLE (alle) — /act <name> zeigt einen ausführlich\n")
        for b in befehle:
            markierung = "" if sichtbar(b) else "  [ausgeblendet]"
            print(f"  /{b['name']} {b['hint']}{markierung}".rstrip())
            print(_absatz(b["kurz"], "      "))
        if erlaubt is not None:
            print(f"\nStand: {begruendung}.")
    else:
        gezeigt = [b for b in befehle if sichtbar(b)]
        print("PROJEKT-BEFEHLE — /act <name> zeigt einen ausführlich\n")
        for b in gezeigt:
            print(f"  /{b['name']} {b['hint']}".rstrip())
            print(_absatz(b["kurz"], "      "))
        versteckt = len(befehle) - len(gezeigt)
        if versteckt:
            print(f"\n{versteckt} weitere Befehle ausgeblendet – /act all")

    if erlaubt is not None and "maintenance" in erlaubt:
        print("\nStatt des Befehls genügt meist ein Satz, z. B. „ich hätte da eine Idee“.")
    else:
        print("\nStatt des Befehls genügt meist ein Satz, z. B. „ich hätte da eine Idee“ oder „Feedback: <Text>“.")
    kurz = _kurzformen(dateien)
    if kurz:
        print("Kurzformen ohne Präfix (nur von Hand aufrufbar): " +
              ", ".join(f"/{n}" for n in kurz))
    return 0


if __name__ == "__main__":
    sys.exit(main())
