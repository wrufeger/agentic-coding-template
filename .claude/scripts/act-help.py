#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Uebersicht der Projekt-Befehle (/act-…) wie eine man page - Name, Parameter, Kurzbeschreibung,
#        Ausloeser. Liest das Frontmatter aller .claude/skills/*/SKILL.md, deshalb nie veraltet. Wird vom
#        Skill /act aufgerufen, laeuft aber auch direkt. Reine Python-Stdlib.
#
#        Filtert nach Stand des Repos (B48/B51, .templatedev/backlog.md): ein Frontmatter-Feld "phase" je
#        Skill ("setup" | "maintenance", Default "project") wird gegen .claude/template.json geprueft:
#          - keine template.json/nicht lesbar                 -> keine Filterung, alles zeigen
#          - is_template true, kein Marker .templatedev/.maintainer -> nur "setup" (frischer Klon zum Anlegen)
#          - is_template true, Marker .templatedev/.maintainer da   -> "setup" + "maintenance"
#                                                                     (Template-Pflege-Checkout - die lokale,
#                                                                     gitignorierte Marker-Datei ersetzt seit
#                                                                     B51 die fruehere Erkennung ueber den
#                                                                     Git-Remote "template", die einen Klon ohne
#                                                                     die dokumentierte Remote-Umbenennung nicht
#                                                                     von der Pflege selbst unterscheiden konnte)
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
import sys
import textwrap
from pathlib import Path

BREITE = 100


def _root() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[2]


def _frontmatter(datei: Path) -> dict:
    """Einfache Schluessel: Wert-Zeilen zwischen den beiden '---' - mehr brauchen SKILL.md-Dateien nicht."""
    werte = {}
    zeilen = datei.read_text(encoding="utf-8").splitlines()
    if not zeilen or zeilen[0].strip() != "---":
        return werte
    for zeile in zeilen[1:]:
        if zeile.strip() == "---":
            break
        if ":" in zeile and not zeile.startswith(" "):
            schluessel, _, wert = zeile.partition(":")
            werte[schluessel.strip()] = wert.strip().strip('"')
    return werte


_PHASEN = {"setup", "maintenance", "project"}


def _phase(fm: dict) -> str:
    """Frontmatter-Wert "phase" normalisiert: Kommentar (#...) und Quotes abschneiden, kleinschreiben.
    Leer oder unbekannt zaehlt als "project" (Default-Phase)."""
    wert = fm.get("phase", "")
    wert = wert.split("#", 1)[0].strip().strip("\"'").lower()
    return wert if wert in _PHASEN else "project"


def _befehle(root: Path) -> list:
    """Nur echte Projekt-Befehle (Praefix 'act-'). Weiterleitungs-Skills ohne Praefix (commit, idea, prepare,
    update-template - Q17 in .templatedev/questions.md) tauchen hier nicht als eigene Befehle auf, siehe
    _kurzformen()."""
    befehle = []
    for datei in sorted((root / ".claude" / "skills").glob("*/SKILL.md")):
        fm = _frontmatter(datei)
        name = fm.get("name") or datei.parent.name
        if name == "act" or not name.startswith("act-"):
            continue
        beschreibung = fm.get("description", "")
        kurz, _, ausloeser = beschreibung.partition(" Auslöser - ")
        befehle.append({"name": name, "hint": fm.get("argument-hint", ""), "kurz": kurz.strip(),
                        "ausloeser": ausloeser.strip(), "phase": _phase(fm)})
    return befehle


def _kurzformen(root: Path) -> list:
    """Namen der Weiterleitungs-Skills ohne 'act-'-Praefix (z.B. 'commit' fuer /act-commit) - nur als
    Alias-Hinweis in der Gesamtuebersicht, nie als eigener Befehl gelistet."""
    namen = []
    for datei in sorted((root / ".claude" / "skills").glob("*/SKILL.md")):
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


def _hat_pflege_marker(root: Path) -> bool:
    """True bei der lokalen, gitignorierten Marker-Datei .templatedev/.maintainer - Zeichen dafuer, dass
    hier an der Vorlage selbst entwickelt wird (B51, .templatedev/regeln.md). Ersetzt seit B51 die Erkennung
    ueber den Git-Remote "template"."""
    return (root / ".templatedev" / ".maintainer").is_file()


def _erlaubte_phasen(root: Path):
    """Liefert (erlaubte Phasen als Menge oder None fuer 'keine Filterung', Kurzbegruendung fuer /act all)."""
    cfg = _template_config(root)
    if cfg is None:
        return None, "keine .claude/template.json - keine Filterung"
    if cfg.get("is_template"):
        if _hat_pflege_marker(root):
            return ({"setup", "maintenance"},
                    "Template-Checkout, Marker .templatedev/.maintainer vorhanden - Pflege-Checkout")
        return {"setup"}, "Template-Checkout ohne Marker .templatedev/.maintainer - frischer Klon zum Anlegen"
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
    if not (root / ".claude" / "skills").is_dir():
        print(f"Kein Skill-Ordner unter {root}/.claude/skills")
        return 2
    befehle = _befehle(root)
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

    print("\nStatt des Befehls genügt meist ein Satz, z. B. „ich hätte da eine Idee“ oder „Feedback: <Text>“.")
    kurz = _kurzformen(root)
    if kurz:
        print("Kurzformen ohne Präfix (nur von Hand aufrufbar): " +
              ", ".join(f"/{n}" for n in kurz))
    return 0


if __name__ == "__main__":
    sys.exit(main())
