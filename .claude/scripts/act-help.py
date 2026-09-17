#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Uebersicht der Projekt-Befehle (/act-…) wie eine man page - Name, Parameter, Kurzbeschreibung,
#        Ausloeser. Liest das Frontmatter aller .claude/skills/*/SKILL.md, deshalb nie veraltet. Wird vom
#        Skill /act aufgerufen, laeuft aber auch direkt. Reine Python-Stdlib.
#
# Aufruf:
#   python .claude/scripts/act-help.py            # alle Befehle, je zwei bis drei Zeilen
#   python .claude/scripts/act-help.py commit     # ein Befehl ausfuehrlich (mit oder ohne act-, auch Teilname)
#   python .claude/scripts/act-help.py --hook     # UserPromptSubmit-Hook: bei Eingabe "/act [name]" die Liste
#                                                 # sofort zeigen und die Eingabe NICHT ans Modell geben
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
                        "ausloeser": ausloeser.strip()})
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


def _absatz(text: str, einzug: str) -> str:
    return textwrap.fill(text, BREITE, initial_indent=einzug, subsequent_indent=einzug)


def _hook() -> int:
    """Liest die Hook-Nutzlast. Nur bei genau "/act" oder "/act <name>" wird geblockt - dann zeigt Claude Code
    den Grund (die Liste) an, ohne das Modell zu fragen. Alles andere laeuft unveraendert weiter (Exit 0)."""
    try:
        prompt = json.loads(sys.stdin.read() or "{}").get("prompt", "")
    except (ValueError, AttributeError):
        return 0
    m = re.fullmatch(r"\s*/act(?:\s+(\S+))?\s*", prompt or "")
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
    suche = argument.lower().removeprefix("/").removeprefix("act-")

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
            print(f"    Anleitung: .claude/skills/{b['name']}/SKILL.md")
            print()
        return 0

    print("PROJEKT-BEFEHLE — /act <name> zeigt einen ausführlich\n")
    for b in befehle:
        print(f"  /{b['name']} {b['hint']}".rstrip())
        print(_absatz(b["kurz"], "      "))
    print("\nStatt des Befehls genügt meist ein Satz, z. B. „ich hätte da eine Idee“ oder „Feedback: <Text>“.")
    kurz = _kurzformen(root)
    if kurz:
        print("Kurzformen ohne Präfix (nur von Hand aufrufbar): " +
              ", ".join(f"/{n}" for n in kurz))
    return 0


if __name__ == "__main__":
    sys.exit(main())
