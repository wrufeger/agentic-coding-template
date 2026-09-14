#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Freiwillige Rueckmeldung eines abgeleiteten Projekts an den Template-Autor - damit aus der Arbeit in
#        echten Projekten bessere Standardregeln, Skripte, Skills und eine klarere Mensch/KI-Kommunikation im
#        Template entstehen. Gemeldet wird NICHT das Projekt, sondern was sich an der ARBEITSWEISE bewaehrt
#        oder gefehlt hat.
#
#        Drei Dinge gelten ausnahmslos und sind der Grund, warum dieses Script existiert, statt einfach
#        Dateien hochzuladen:
#          1. Es wird NIE eine Datei gesendet. Die Nutzlast ist eine kurze, von Hand verfasste Zusammenfassung
#             plus eine Handvoll Werte aus geschlossenen Wortlisten (Schalterstellungen, Werkzeugnamen).
#             "docs/ai/" enthaelt Fragen, Antworten, Servernamen, Datenbanknamen und Zitate des Auftraggebers
#             - das ist NICHT anonym und wird nicht verschickt.
#          2. Es wird NIE ohne Einwilligung gesendet (consent in .claude/template.json, ausdruecklich gesetzt).
#          3. Es wird NIE ungesehen gesendet: --plan zeigt die vollstaendige Nutzlast als Klartext, --send
#             zeigt sie erneut und fragt, sofern nicht --yes gesetzt ist.
#        Zusaetzlich laeuft jede Zeichenkette durch eine Pruefung auf Geheimnisse, Pfade, Mailadressen, IPs
#        und fremde URLs (siehe _verdaechtig). Schlaegt sie an, wird NICHT gesendet, sondern gemeldet.
#
# Aufruf:
#   python .claude/scripts/feedback.py --status
#       Zeigt: Einwilligung ja/nein, Ziel-URL, wie viele Eintraege im Ausgang liegen, wann zuletzt gesendet
#       wurde. Schreibt nichts.
#   python .claude/scripts/feedback.py --enable [--repo-url <url>] | --disable
#       Setzt bzw. widerruft die Einwilligung in .claude/template.json. --repo-url ist optional und wird nur
#       mitgesendet, wenn sie oeffentlich erreichbar ist; ohne sie bleibt die Meldung ohne Projektbezug.
#   python .claude/scripts/feedback.py --add --art <regel|script|skill|ablauf|doku|fehler>
#                                      --titel "<eine Zeile>" --text "<2-6 Saetze>"
#       Legt einen Verbesserungs-Eintrag in den lokalen Ausgang (.claude/feedback-outbox.json, gitignored).
#       Sendet nichts. Der Text wird fuer einen Fremden geschrieben: Muster statt Projekt, keine Namen, keine
#       Pfade, kein Code.
#   python .claude/scripts/feedback.py --plan        (Default)
#       Zeigt die vollstaendige Nutzlast, die gesendet wuerde. Schreibt und sendet nichts.
#   python .claude/scripts/feedback.py --send [--yes]
#       Zeigt die Nutzlast und sendet sie nach Bestaetigung. Danach wird der Ausgang geleert und der
#       Zeitpunkt vermerkt. Ohne Einwilligung: Abbruch mit Exit 2.
#   python .claude/scripts/feedback.py --clear
#       Leert den Ausgang, ohne zu senden.
#
# Ausgabeformat: Klartext-Bloecke, die Nutzlast als eingerueckter JSON-Block. Exit 0 = ok, 1 = Nutzlast
#   beanstandet (nicht gesendet), 2 = Abbruch (keine Einwilligung, fehlende Angabe, Transportfehler).
#
# Gilt nur fuer abgeleitete Projekte. Im Template-Checkout selbst (is_template in .claude/template.json)
# verweigert das Script jede Aktion - die Entwicklung des Templates meldet sich nicht an sich selbst.

import argparse
import json
import os
import re
import sys
import time
import uuid
import urllib.error
import urllib.request
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

# Ziel der Meldung. Bewusst hier als Konstante und nicht in .templatedev/: Dieser Ordner wird beim Anlegen
# eines Projekts entfernt (template_only), die Adresse muss aber genau dort verfuegbar sein, wo gesendet wird.
# Wer das Template forkt, aendert diese Zeile. Fuer Tests laesst sich die Adresse per Umgebungsvariable
# uebersteuern, ohne die Datei anzufassen.
FEEDBACK_ENDPOINT = "https://rufeger.de/agentic-coding-feedback"
ENDPOINT_ENV = "AGENTIC_FEEDBACK_URL"

OUTBOX_REL = ".claude/feedback-outbox.json"
TEMPLATE_JSON_REL = ".claude/template.json"
ARTEN = ("regel", "script", "skill", "ablauf", "doku", "fehler")
TITEL_MAX = 120
TEXT_MAX = 1200
TIMEOUT_S = 15

# Werte, die gesendet werden duerfen, weil sie aus geschlossenen Wortlisten stammen und nichts ueber das
# Projekt aussagen - nur darueber, wie das Template eingestellt wurde.
SCHALTER_WHITELIST = (
    "Orchestrator-Modell", "Commit-Verhalten", "Logging", "Logging-Tiefe", "Wartung",
    "Wartungsberichte", "Code-Optimierung", "Ideen-Ablauf", "Testtiefe", "Schreibstil",
)

# Muster, die in keiner Zeichenkette der Nutzlast vorkommen duerfen. Lieber ein Fehlalarm zu viel: Eine
# abgelehnte Meldung kostet eine Minute, eine durchgerutschte Zugangsdaten-Zeile ist nicht zurueckzuholen.
_SECRET_WOERTER = re.compile(
    r"(?i)\b(pass(wort|word)|secret|token|api[_-]?key|credential|zugangsdaten|private[_-]?key)\b")
_MAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_IP = re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b")
_WIN_PFAD = re.compile(r"[A-Za-z]:[\\/]")
_UNIX_PFAD = re.compile(r"(?<![\w.])/(?:home|Users|var|etc|opt|srv)/")
_URL = re.compile(r"https?://[^\s)]+")
_LANGE_HEX = re.compile(r"\b[0-9a-f]{32,}\b")


def _verdaechtig(text: str, endpoint: str):
    """Gibt eine Liste von Beanstandungen zurueck - leer heisst: unbedenklich."""
    treffer = []
    if _SECRET_WOERTER.search(text):
        treffer.append("Wort aus dem Umfeld von Zugangsdaten")
    if _MAIL.search(text):
        treffer.append("Mailadresse")
    if _IP.search(text):
        treffer.append("IP-Adresse")
    if _WIN_PFAD.search(text) or _UNIX_PFAD.search(text):
        treffer.append("absoluter Dateipfad")
    if _LANGE_HEX.search(text):
        treffer.append("langer Hex-Wert (Schluessel? Hash?)")
    for url in _URL.findall(text):
        if not url.startswith(endpoint) and "github.com" not in url:
            treffer.append(f"fremde URL ({url[:40]})")
    return treffer


def _root() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    hier = Path(__file__).resolve().parent
    for kandidat in (hier.parent.parent, hier.parent, hier):
        if (kandidat / "AGENTS.md").exists():
            return kandidat
    return Path.cwd().resolve()


def _template_json(root: Path) -> dict:
    fp = root / TEMPLATE_JSON_REL
    if not fp.exists():
        return {}
    try:
        return json.loads(fp.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def _template_json_schreiben(root: Path, daten: dict) -> None:
    fp = root / TEMPLATE_JSON_REL
    fp.write_text(json.dumps(daten, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _endpoint() -> str:
    return (os.environ.get(ENDPOINT_ENV) or FEEDBACK_ENDPOINT).rstrip("/")


def _outbox(root: Path) -> list:
    fp = root / OUTBOX_REL
    if not fp.exists():
        return []
    try:
        daten = json.loads(fp.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    return daten if isinstance(daten, list) else []


def _outbox_schreiben(root: Path, eintraege: list) -> None:
    (root / OUTBOX_REL).write_text(
        json.dumps(eintraege, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _feedback_block(tj: dict) -> dict:
    block = tj.get("feedback")
    return block if isinstance(block, dict) else {}


def _schalter(tj: dict) -> dict:
    """Nur die Schalterstellungen aus applied_config, die in einer geschlossenen Wortliste stehen."""
    angewandt = tj.get("applied_config") or {}
    return {k: angewandt.get(k) for k in SCHALTER_WHITELIST if angewandt.get(k)}


def _nutzlast(root: Path, tj: dict) -> dict:
    fb = _feedback_block(tj)
    angewandt = tj.get("applied_config") or {}
    nutzlast = {
        "schema": 1,
        "projekt_id": fb.get("projekt_id"),
        "datum": time.strftime("%Y-%m-%d"),
        "template_basis": tj.get("base_commit"),
        "weg": fb.get("weg"),
        "ausfuellart": fb.get("ausfuellart"),
        "werkzeuge_entfernt": angewandt.get("KI-Werkzeuge-entfernt") or [],
        "regelsaetze": angewandt.get("Coding-Guidelines") or [],
        "schalter": _schalter(tj),
        "eintraege": _outbox(root),
    }
    if fb.get("repo_url"):
        nutzlast["repo_url"] = fb["repo_url"]
    return nutzlast


def _pruefen(nutzlast: dict, endpoint: str) -> list:
    """Jede Zeichenkette der Nutzlast gegen _verdaechtig pruefen. Rueckgabe: Liste von Beanstandungen."""
    fehler = []

    def lauf(wert, pfad):
        if isinstance(wert, str):
            for grund in _verdaechtig(wert, endpoint):
                fehler.append(f"{pfad}: {grund}")
        elif isinstance(wert, dict):
            for k, v in wert.items():
                lauf(v, f"{pfad}.{k}")
        elif isinstance(wert, list):
            for i, v in enumerate(wert):
                lauf(v, f"{pfad}[{i}]")

    for k, v in nutzlast.items():
        if k in ("repo_url", "projekt_id"):
            continue  # bewusst angegeben, siehe --enable --repo-url
        lauf(v, k)
    return fehler


def _zeige(nutzlast: dict, endpoint: str) -> None:
    print(f"Ziel:     {endpoint}")
    print(f"Eintraege: {len(nutzlast.get('eintraege') or [])}")
    print("")
    print("Vollstaendige Nutzlast:")
    for zeile in json.dumps(nutzlast, indent=2, ensure_ascii=False).split("\n"):
        print("  " + zeile)


def cmd_status(root: Path) -> int:
    tj = _template_json(root)
    fb = _feedback_block(tj)
    zustand = "eingeschaltet" if fb.get("consent") is True else "aus"
    print(f"Feedback:  {zustand}")
    print(f"Ziel:      {_endpoint()}")
    print(f"Projekt-ID: {fb.get('projekt_id') or '- (entsteht bei --enable)'}")
    print(f"Ausgang:   {len(_outbox(root))} Eintraege ({OUTBOX_REL}, gitignored)")
    print(f"Zuletzt gesendet: {fb.get('zuletzt_gesendet') or 'nie'}")
    if fb.get("repo_url"):
        print(f"Repo-URL:  {fb['repo_url']}")
    if fb.get("consent") is not True:
        print("")
        print("Nichts wird gesendet. Einschalten: feedback.py --enable")
    return 0


def cmd_enable(root: Path, repo_url, an: bool, weg=None, ausfuellart=None) -> int:
    tj = _template_json(root)
    fb = _feedback_block(tj)
    fb["consent"] = bool(an)
    fb["datum"] = time.strftime("%Y-%m-%d")
    # Eine zufaellige, hier erzeugte Kennung - kein Name, kein Pfad, kein Hash aus Projektdaten. Sie macht
    # mehrere Meldungen desselben Projekts zusammenfuehrbar, ohne das Projekt zu benennen. Wer sie loswerden
    # will, loescht den feedback-Block in .claude/template.json; die naechste Einwilligung erzeugt eine neue.
    if an and not fb.get("projekt_id"):
        fb["projekt_id"] = uuid.uuid4().hex
    fb["endpoint"] = _endpoint()
    if weg in ("neu", "nachgeruestet"):
        fb["weg"] = weg
    if ausfuellart in ("leer", "interview", "config"):
        fb["ausfuellart"] = ausfuellart
    if repo_url:
        if not repo_url.startswith("https://"):
            print("Fehler: --repo-url muss mit https:// beginnen (oeffentlich erreichbar).", file=sys.stderr)
            return 2
        fb["repo_url"] = repo_url
    tj["feedback"] = fb
    _template_json_schreiben(root, tj)
    print("Feedback " + ("eingeschaltet" if an else "ausgeschaltet") + f" (vermerkt in {TEMPLATE_JSON_REL}).")
    if an:
        print(f"Ziel: {_endpoint()} - gesendet wird erst auf ausdruecklichen Aufruf von --send.")
    return 0


def cmd_add(root: Path, art: str, titel: str, text: str) -> int:
    if art not in ARTEN:
        print(f"Fehler: --art muss eines von {', '.join(ARTEN)} sein.", file=sys.stderr)
        return 2
    titel = (titel or "").strip()
    text = (text or "").strip()
    if not titel or not text:
        print("Fehler: --titel und --text werden beide gebraucht.", file=sys.stderr)
        return 2
    if len(titel) > TITEL_MAX or len(text) > TEXT_MAX:
        print(f"Fehler: Titel max. {TITEL_MAX}, Text max. {TEXT_MAX} Zeichen.", file=sys.stderr)
        return 2
    beanstandet = _verdaechtig(titel, _endpoint()) + _verdaechtig(text, _endpoint())
    if beanstandet:
        print("Nicht uebernommen - der Text enthaelt:", file=sys.stderr)
        for grund in sorted(set(beanstandet)):
            print(f"  - {grund}", file=sys.stderr)
        print("Beschreibe das Muster, nicht das Projekt: keine Pfade, keine Namen, kein Code.",
              file=sys.stderr)
        return 1
    eintraege = _outbox(root)
    eintraege.append({"art": art, "titel": titel, "text": text, "datum": time.strftime("%Y-%m-%d")})
    _outbox_schreiben(root, eintraege)
    print(f"Uebernommen ({len(eintraege)} im Ausgang). Ansehen: feedback.py --plan")
    return 0


def cmd_plan(root: Path) -> int:
    tj = _template_json(root)
    nutzlast = _nutzlast(root, tj)
    endpoint = _endpoint()
    _zeige(nutzlast, endpoint)
    print("")
    fehler = _pruefen(nutzlast, endpoint)
    if fehler:
        print("Beanstandet - so wird NICHT gesendet:")
        for f in fehler:
            print(f"  - {f}")
        return 1
    if _feedback_block(tj).get("consent") is not True:
        print("Feedback ist aus - es wuerde nichts gesendet (einschalten: --enable).")
        return 0
    print("Unbedenklich. Senden: feedback.py --send")
    return 0


def cmd_send(root: Path, ja: bool) -> int:
    tj = _template_json(root)
    if _feedback_block(tj).get("consent") is not True:
        print("Abbruch: keine Einwilligung hinterlegt (feedback.py --enable).", file=sys.stderr)
        return 2
    nutzlast = _nutzlast(root, tj)
    endpoint = _endpoint()
    _zeige(nutzlast, endpoint)
    print("")
    fehler = _pruefen(nutzlast, endpoint)
    if fehler:
        print("Beanstandet - nicht gesendet:", file=sys.stderr)
        for f in fehler:
            print(f"  - {f}", file=sys.stderr)
        return 1
    if not ja:
        print("Nichts gesendet. Zum tatsaechlichen Senden dieselbe Zeile mit --yes wiederholen.")
        return 0
    daten = json.dumps(nutzlast, ensure_ascii=False).encode("utf-8")
    anfrage = urllib.request.Request(
        endpoint, data=daten, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8",
                 "User-Agent": "agentic-coding-template-feedback/1"})
    try:
        with urllib.request.urlopen(anfrage, timeout=TIMEOUT_S) as antwort:
            code = antwort.status
    except urllib.error.HTTPError as e:
        print(f"Abbruch: Empfaenger antwortet mit HTTP {e.code}. Ausgang bleibt erhalten.", file=sys.stderr)
        return 2
    except (urllib.error.URLError, OSError) as e:
        print(f"Abbruch: nicht erreichbar ({e}). Ausgang bleibt erhalten.", file=sys.stderr)
        return 2
    fb = _feedback_block(tj)
    fb["zuletzt_gesendet"] = time.strftime("%Y-%m-%d %H:%M")
    tj["feedback"] = fb
    _template_json_schreiben(root, tj)
    _outbox_schreiben(root, [])
    print(f"Gesendet (HTTP {code}). Ausgang geleert.")
    return 0


def cmd_clear(root: Path) -> int:
    anzahl = len(_outbox(root))
    _outbox_schreiben(root, [])
    print(f"Ausgang geleert ({anzahl} Eintraege verworfen).")
    return 0


def _run(argv) -> int:
    parser = argparse.ArgumentParser(
        prog="feedback.py",
        description="Freiwillige Rueckmeldung an den Template-Autor - nie ohne Einwilligung, nie ungesehen.")
    gruppe = parser.add_mutually_exclusive_group()
    gruppe.add_argument("--status", action="store_true", help="Zustand anzeigen")
    gruppe.add_argument("--enable", action="store_true", help="Einwilligung setzen")
    gruppe.add_argument("--disable", action="store_true", help="Einwilligung widerrufen")
    gruppe.add_argument("--add", action="store_true", help="Verbesserungs-Eintrag in den Ausgang legen")
    gruppe.add_argument("--plan", action="store_true", help="Nutzlast zeigen, nichts senden (Default)")
    gruppe.add_argument("--send", action="store_true", help="Nutzlast zeigen und senden")
    gruppe.add_argument("--clear", action="store_true", help="Ausgang leeren")
    parser.add_argument("--art", default=None, help=f"mit --add: {', '.join(ARTEN)}")
    parser.add_argument("--titel", default=None, help="mit --add: eine Zeile")
    parser.add_argument("--text", default=None, help="mit --add: zwei bis sechs Saetze")
    parser.add_argument("--repo-url", default=None, help="mit --enable: oeffentliche Repo-URL (optional)")
    parser.add_argument("--weg", default=None, choices=["neu", "nachgeruestet"],
                        help="mit --enable: wie das Projekt entstanden ist")
    parser.add_argument("--ausfuellart", default=None, choices=["leer", "interview", "config"],
                        help="mit --enable: wie AI-CONFIG.md befuellt wurde")
    parser.add_argument("--yes", action="store_true", help="mit --send: tatsaechlich senden")
    args = parser.parse_args(argv)

    root = _root()
    tj = _template_json(root)
    if tj.get("is_template") is True:
        print("Dieses Repo ist das Template selbst - es meldet sich nicht an sich selbst. Nichts getan.",
              file=sys.stderr)
        return 2

    if args.status:
        return cmd_status(root)
    if args.enable:
        return cmd_enable(root, args.repo_url, True, args.weg, args.ausfuellart)
    if args.disable:
        return cmd_enable(root, None, False)
    if args.add:
        return cmd_add(root, args.art, args.titel, args.text)
    if args.send:
        return cmd_send(root, args.yes)
    if args.clear:
        return cmd_clear(root)
    return cmd_plan(root)


def main() -> int:
    try:
        return _run(sys.argv[1:])
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 - darf nie mit Traceback nach aussen dringen
        print(f"feedback: Fehler: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
