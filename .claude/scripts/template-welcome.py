#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: In einem frisch geklonten Template-Checkout (B51, .templatedev/backlog.md) bekommt das Modell zu
#        jeder Eingabe zusaetzlichen Kontext mit, wofuer dieses Repo da ist - unabhaengig davon, was die
#        Eingabe im Wortlaut ist. Keine eigene Bewertung mehr per Regex/Muster: das Modell sieht den
#        Gesprächsverlauf selbst und entscheidet, ob die Eingabe erkennbar "Projekt anlegen"/"nachruesten"
#        meint (auch als Freitext oder als Antwort in einem laufenden Anlege-/Nachruest-Gespraech) oder ob
#        erst kurz erklaert werden soll, wofuer das Repo da ist. Kostet ein paar Token je Eingabe -
#        ausdruecklich in Ordnung (Wolfgang, 2026-09-17).
#
#        Erkennung frischer Klon vs. Pflege-Checkout ueber die lokale, gitignorierte Marker-Datei
#        .templatedev/.maintainer (siehe .gitignore) - bewusst nicht ueber den Git-Remote:
#          - Marker vorhanden                                  -> kein Kontext (Pflege-Checkout)
#          - is_template fehlt/nicht lesbar/kein Objekt        -> kein Kontext (kein Template mehr)
#          - is_template: true, kein Marker                    -> frischer Klon: Kontext bei jeder Eingabe
#
#        Ausnahme: Eingaben, die nur die Befehlsliste zeigen sollen ("/act", "/act all", "/act <name>"),
#        bekommen keinen Kontext - dafuer blockt bereits der eigene Hook in act-help.py mit der Liste, ein
#        zweiter Kontext waere doppelt. "/act-create-project" & Co. (Bindestrich direkt nach "act") sind davon
#        NICHT betroffen und bekommen den Kontext ganz normal mit - schadet dort nicht.
#
#        Robust im Zweifel: kaputtes JSON, fehlende/kaputte template.json, jeder Lesefehler - dann wird NIE
#        etwas ausgegeben (Exit 0, keine Ausgabe). Kein Block mehr (kein "decision": "block") - nur noch
#        additionalContext, das Modell entscheidet selbst weiter. Format nach der Claude-Code-Hook-Doku
#        (https://code.claude.com/docs/en/hooks, Abschnitt zur JSON-Ausgabe von UserPromptSubmit-Hooks):
#        {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": "..."}}
#
# Aufruf:
#   python .claude/scripts/template-welcome.py --hook    # UserPromptSubmit-Hook (settings.json)
#
# Ausgabeformat: im frischen Klon ein JSON-Objekt {"hookSpecificOutput": {...}} auf stdout (siehe oben),
# sonst keine Ausgabe. Exit immer 0.

import json
import os
import re
import sys
from pathlib import Path

KONTEXT = """Automatischer Hinweis des Hooks template-welcome.py, keine Nutzeranweisung.

Dieses Repo ist ein frisch geklonter Checkout des Agentic-Coding-Templates, noch kein eigenes \
Projekt.

Geht es bei dieser Eingabe erkennbar darum, ein neues Projekt anzulegen oder ein bestehendes Repo damit \
nachzuruesten - auch als Befehl, als Freitext oder als Antwort in einem laufenden Anlege-/Nachruest-\
Gespraech -, dann normal weiterarbeiten.

Sonst zuerst kurz erklaeren, wofuer dieses Repo da ist, und die beiden Wege nennen:
Weg 1, neues Projekt: /act-create-project oder ein Satz wie "Erstelle eine neue Anwendung in <pfad>" \
(auch "ein leeres Projekt").
Weg 2, bestehendes Repo nachruesten: /act-apply-template oder ein Satz wie "Nutze das Template in <pfad>".
/act zeigt alle Befehle.

Hinweis fuer Template-Pfleger (dem Nutzer nennen, nie selbst anlegen): Wer diese Vorlage selbst \
weiterentwickelt, legt einmalig .templatedev/.maintainer an - danach bleibt dieser Hinweis aus.

Steht "is_template" in einem abgeleiteten Projekt faelschlich noch in .claude/template.json, dem Nutzer \
nennen (nie selbst ausfuehren): .templatedev/.maintainer anlegen oder den Schluessel "is_template" entfernen.

Andere Auftraege nicht ausfuehren, bevor sich der Nutzer fuer einen der beiden Wege entschieden hat oder \
ausdruecklich bestaetigt, dass er trotzdem so arbeiten will."""

# Nur die reine Befehlsliste ("/act", "/act all", "/act <name>") - matcht NICHT "/act-create-project" & Co.,
# da dort direkt nach "act" ein Bindestrich statt Whitespace/Ende folgt.
_ACT_NUR_LISTE = re.compile(r"^/act(\s+\S+)?\s*$", re.IGNORECASE)


def _root() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[2]


def _ist_frischer_klon(root: Path) -> bool:
    """True nur bei is_template:true ohne Pflege-Marker. Jeder Lesefehler/jede unerwartete Form -> False,
    also kein Kontext - im Zweifel nichts ausgeben."""
    try:
        if (root / ".templatedev" / ".maintainer").is_file():
            return False
        cfg = json.loads((root / ".claude" / "template.json").read_text(encoding="utf-8"))
        return isinstance(cfg, dict) and bool(cfg.get("is_template"))
    except (OSError, ValueError):
        return False


def main() -> int:
    if sys.argv[1:] != ["--hook"]:
        return 0
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        prompt = payload.get("prompt", "")
        if not isinstance(prompt, str):
            return 0
        if not _ist_frischer_klon(_root()):
            return 0
        if _ACT_NUR_LISTE.match(prompt.strip()):
            return 0  # act-help.py blockt hier schon selbst mit der Liste - kein doppelter Kontext
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        ausgabe = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": KONTEXT}}
        print(json.dumps(ausgabe, ensure_ascii=False))
    except Exception:
        # Letzte Schranke: irgendein unerwarteter Fehler gibt nichts aus.
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
