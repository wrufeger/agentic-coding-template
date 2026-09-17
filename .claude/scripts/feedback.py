#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Freiwillige Rueckmeldung eines abgeleiteten Projekts an den Template-Autor - damit aus der Arbeit in
#        echten Projekten bessere Standardregeln, Skripte, Skills und eine klarere Mensch/KI-Kommunikation im
#        Template entstehen. Gemeldet wird NICHT das Projekt, sondern was sich an der ARBEITSWEISE bewaehrt
#        oder gefehlt hat.
#
#        Vier Dinge gelten ausnahmslos und sind der Grund, warum dieses Script existiert, statt einfach
#        Dateien hochzuladen:
#          1. Es wird NIE eine Datei gesendet. Die KI LIEST sehr wohl `.claude/`, `CLAUDE.md`, `AGENTS.md`
#             und `docs/ai/` - aber sie schickt daraus nur das, was fuer FREMDE nuetzlich ist: welche Regel
#             ergaenzt wurde, welcher Ablauf sich bewaehrt hat, welcher MCP-Server eingebunden wurde. Ohne
#             Projektbezug, ohne Namen, ohne Daten. Die Dateien selbst enthalten Servernamen,
#             Datenbanknamen, Kennzahlen und Zitate - das ist NICHT anonym und verlaesst das Projekt nie.
#          2. Es wird NIE ohne Einwilligung gesendet (consent in .claude/template.json).
#          3. Jede Sendung wird PROTOKOLLIERT: die vollstaendige Nutzlast landet versioniert unter
#             docs/ai/template-feedback/. Der Assistent sendet autonom, ohne Rueckfrage und ohne die Nutzlast
#             ins Terminal zu schreiben - wie jedes andere Programm auch. Nachvollziehbar bleibt es trotzdem,
#             aber ueber das Protokoll im Repo: Es faellt im naechsten Diff auf, laesst sich nachlesen, wenn
#             jemand es wissen will, und nicht erst, wenn er zufaellig hinsieht. Wer vorab sehen will, was
#             gesendet wuerde, ruft --plan auf.
#          4. Hoechstens EINMAL JE WOCHE, und erstmals nach dem Abschluss der Einrichtung. --force hebt die
#             Sperre auf; das ist der manuelle Fall.
#        Zusaetzlich laeuft jede Zeichenkette durch eine Pruefung auf Geheimnisse, Pfade, Mailadressen, IPs
#        und fremde URLs (siehe _verdaechtig). Schlaegt sie an, wird NICHT gesendet, sondern gemeldet.
#
# Aufruf:
#   python .claude/scripts/feedback.py --status
#       Zeigt: Einwilligung ja/nein, Ziel-URL, wie viele Eintraege im Ausgang liegen, wann zuletzt gesendet
#       wurde. Schreibt nichts.
#   python .claude/scripts/feedback.py --enable [--repo-url <url>] [--protokoll versionieren|lokal] | --disable
#       Setzt bzw. widerruft die Einwilligung in .claude/template.json. --repo-url ist optional und wird nur
#       mitgesendet, wenn sie oeffentlich erreichbar ist; ohne sie bleibt die Meldung ohne Projektbezug.
#       --protokoll lokal traegt die Nutzlast-Dateien in .gitignore ein - fuer Projekte, deren Repo
#       oeffentlich ist oder die das Protokoll schlicht nicht im Verlauf haben wollen. Default:
#       versionieren (Nachweis im Diff).
#   python .claude/scripts/feedback.py --add --art <regel|script|skill|ablauf|doku|fehler>
#                                      --titel "<eine Zeile>" --text "<2-6 Saetze>"
#       Legt einen Verbesserungs-Eintrag in den lokalen Ausgang (.claude/feedback-outbox.json, gitignored).
#       Sendet nichts. Der Text wird fuer einen Fremden geschrieben: Muster statt Projekt, keine Namen, keine
#       Pfade, kein Code.
#   python .claude/scripts/feedback.py --plan        (Default)
#       Zeigt die vollstaendige Nutzlast, die gesendet wuerde. Schreibt und sendet nichts.
#   python .claude/scripts/feedback.py --send [--force]
#       Sendet, wenn Einwilligung vorliegt, der Filter nichts beanstandet und die letzte Sendung mindestens
#       sieben Tage her ist. Schreibt die Nutzlast nach docs/ai/template-feedback/, leert den Ausgang und
#       vermerkt den Zeitpunkt. --force hebt nur die Wochensperre auf, nichts sonst.
#   python .claude/scripts/feedback.py --direkt "<Text>"
#       Sendet eine von Hand geschriebene Nachricht SOFORT - unabhaengig von Einwilligung, Modus und Takt.
#       Begruendung: Wer den Text selbst schreibt und den Versand selbst ausloest, hat damit alles getan,
#       wofuer die Einwilligung sonst da ist. Steht Feedback auf "aus", geht ausschliesslich der Text hinaus
#       (keine Projekt-Kennung, kein Kontext); sonst gehen Projekt-Kennung, Template-Stand, Weg und
#       Ausfuellart mit, damit sich mehrere Meldungen desselben Projekts zusammenfuehren lassen. Der Filter
#       laeuft auch hier: ein versehentlich mitkopierter Pfad oder ein Token wird gemeldet statt gesendet.
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
import subprocess
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

# Schema der von Hand geschriebenen Nachricht (--direkt). Eigene Nummer, weil sie anders aufgebaut ist als
# die gesammelte Meldung: Pflicht ist nur `text`, alles Uebrige ist optionaler Kontext.
SCHEMA_DIREKT = 2

# Herkunftskennung, die jede Meldung mitfuehrt. BEWUSST OEFFENTLICH und eingecheckt - sie ist kein Geheimnis
# und soll auch keines sein: Sie sagt dem Endpunkt nur, dass die Meldung aus einem Projekt kommt, das dieses
# Template benutzt, und haelt zufaelligen Muell drauusen. Wer sie faelschen will, liest sie hier ab; dagegen
# hilft sie nicht und soll sie nicht helfen.
# Der Name ist mit Absicht NICHT "secret"/"token"/"key": Solche Woerter werden in genau dieser Kette
# herausgefiltert - vom Geheimnis-Filter unten, von Log-Filtern, von Sicherheitsscannern. Eine Kennung, die
# unterwegs weggeputzt wird, waere schlimmer als keine. Aus demselben Grund ist der Wert lesbarer Text und
# keine lange Hex-Kette (die faengt _LANGE_HEX ab).
HERKUNFT = "agentic-coding-template/1"

# Der fruehere Ausgang (.claude/feedback-outbox.json) ist entfallen: Eintraege liegen jetzt als Paar
# <name>.md + <name>.json direkt unter docs/ai/template-feedback/ und wandern beim Senden nach sent/.
# Damit steht schon VOR dem Versand im Repo, was hinausgehen soll - sichtbar im Diff, nicht in einer
# versteckten Datei.
# Protokoll jeder Sendung - versioniert, damit im Repo nachlesbar bleibt, was hinausgegangen ist.
LOG_DIR_REL = "docs/ai/template-feedback"
# ... es sei denn, {{AUFTRAGGEBER}} will das Protokoll lokal halten (--enable --protokoll lokal). Dann
# nimmt .gitignore genau die Nutzlast-Dateien aus; die README des Ordners bleibt versioniert, damit im Repo
# nachlesbar bleibt, DASS gesendet wird - nur nicht mehr, WAS.
GITIGNORE_GLOB = "docs/ai/template-feedback/*.json"
GITIGNORE_KOPF = "# Protokoll der Rueckmeldungen (feedback.py) - auf Wunsch lokal, nicht versioniert"
CONFIG_REL = "AI-CONFIG.md"
# Mindestabstand je Takt in Stunden (None = kein automatischer Versand). Gleiche Tabelle wie in setup-lib.py;
# hier noch einmal, weil feedback.py bewusst ohne Abhaengigkeit zu setup-lib.py auskommt - es laeuft auch,
# wenn die Einrichtungswerkzeuge laengst entfernt sind.
TAKT_STUNDEN = {
    "manuell": None, "sofort": 0, "stuendlich": 1, "taeglich": 24, "woechentlich": 168, "automatisch": 1,
}
MODUS_ALIAS = {"nein": "aus", "ja": "automatisch", "bestätigen": "bestaetigen", "fragen": "bestaetigen"}
TAKT_ALIAS = {"stündlich": "stuendlich", "täglich": "taeglich", "wöchentlich": "woechentlich"}
TEMPLATE_JSON_REL = ".claude/template.json"
ARTEN = ("regel", "script", "skill", "ablauf", "doku", "fehler", "mcp", "link")
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
_WIN_PFAD = re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]")
_UNIX_PFAD = re.compile(r"(?<![\w.])/(?:home|Users|var|etc|opt|srv)/")
_URL = re.compile(r"https?://[^\s)]+")
_LANGE_HEX = re.compile(r"\b[0-9a-f]{32,}\b")

# Hosts, die nie in einem geteilten Link stehen duerfen: Ein Verweis auf ein Intranet oder eine lokale
# Instanz ist fuer Fremde wertlos und verraet zugleich, wie es dort drinnen heisst.
_HOST_TABU = re.compile(
    r"^(?:localhost$|127\.|10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.|\[?::1)"
    r"|\.(?:local|internal|intern|lan|home|test|invalid|example)$", re.I)


def _link_pruefen(url: str):
    """Gibt eine Liste von Beanstandungen zurueck - leer heisst: der Link darf mitgesendet werden."""
    treffer = []
    if not re.match(r"(?i)^https?://", url or ""):
        return ["keine http(s)-Adresse"]
    rest = re.sub(r"(?i)^https?://", "", url)
    host = rest.split("/", 1)[0].split("?", 1)[0]
    if "@" in host:
        treffer.append("Zugangsdaten in der Adresse")
        host = host.split("@", 1)[1]
    host = host.split(":", 1)[0]
    if _HOST_TABU.search(host):
        treffer.append(f"nicht oeffentlich erreichbar ({host})")
    if len(url) > 300:
        treffer.append("Adresse laenger als 300 Zeichen")
    return treffer



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


def _config_wert(root: Path, schluessel: str, default: str, alias: dict) -> str:
    """Liest die Spalte "Wert" einer Zeile aus AI-CONFIG.md. AI-CONFIG.md ist die Steuerung - nicht
    template.json, dort stehen nur Projekt-ID und Zeitstempel."""
    fp = root / CONFIG_REL
    if not fp.exists():
        return default
    try:
        text = fp.read_text(encoding="utf-8-sig")
    except OSError:
        return default
    m = re.search(r"(?m)^\|\s*" + re.escape(schluessel) + r"\s*\|([^|]*)\|", text)
    if not m:
        return default
    wert = m.group(1).strip().lower()
    if not wert:
        return default
    return alias.get(wert, wert)


def _config_setzen(root: Path, schluessel: str, wert: str) -> bool:
    """Schreibt die Spalte "Wert" genau einer Zeile in AI-CONFIG.md. Nur diese Zelle, nichts sonst."""
    fp = root / CONFIG_REL
    if not fp.exists():
        return False
    try:
        text = fp.read_text(encoding="utf-8-sig")
    except OSError:
        return False
    muster = re.compile(r"(?m)^(\|\s*" + re.escape(schluessel) + r"\s*\|)([^|]*)(\|)")
    if not muster.search(text):
        return False
    neu = muster.sub(lambda m: m.group(1) + " " + wert + " " + m.group(3), text, count=1)
    try:
        fp.write_text(neu, encoding="utf-8")
    except OSError:
        return False
    return True


def _modus(root: Path) -> str:
    return _config_wert(root, "Feedback", "aus", MODUS_ALIAS)


def _takt(root: Path) -> str:
    return _config_wert(root, "Feedback-Takt", "woechentlich", TAKT_ALIAS)


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
    """Zieladresse, IMMER mit abschliessendem Schraegstrich.

    Belegt am 2026-09-15 am echten Endpunkt: Ohne den Schraegstrich antwortet der Webserver mit 301 auf die
    Variante MIT Schraegstrich - und urllib macht bei einer Weiterleitung aus dem POST ein GET. Die Meldung
    kaeme also nie an, und der Client saehe nur ein unverstaendliches "405". Eine Zeile Vorsorge ist billiger
    als diese Fehlersuche im fremden Projekt."""
    roh = (os.environ.get(ENDPOINT_ENV) or FEEDBACK_ENDPOINT).rstrip("/")
    return roh + "/"


def _ist_eintrag(fp: Path) -> bool:
    """Trennt Eintraege von Sendeprotokollen - beide liegen als .json im selben Ordner. Ein Eintrag hat
    eine gleichnamige .md daneben UND die Felder art/titel/text. Ohne diese Pruefung wanderte ein
    Protokoll der letzten Sendung als "Eintrag" in die naechste Nutzlast (im Test genau so passiert)."""
    if not fp.with_suffix(".md").exists():
        return False
    try:
        daten = json.loads(fp.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return False
    return isinstance(daten, dict) and {"art", "titel", "text"} <= set(daten)


def _wartende_dateien(root: Path) -> list:
    """Die noch nicht gesendeten Eintraege: je Eintrag eine <name>.json (Daten) neben einer <name>.md
    (Zusammenfassung zum Lesen). Gesendetes liegt in sent/ und zaehlt hier nicht mehr mit; die
    Sendeprotokolle bleiben, wo sie sind - sie sind der Nachweis, kein Eintrag."""
    ordner = root / LOG_DIR_REL
    if not ordner.is_dir():
        return []
    return sorted(fp for fp in ordner.glob("*.json") if _ist_eintrag(fp))


def _outbox(root: Path) -> list:
    """Die wartenden Eintraege als Liste von dicts - das Format, das in die Nutzlast geht."""
    eintraege = []
    for fp in _wartende_dateien(root):
        try:
            daten = json.loads(fp.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        if isinstance(daten, dict):
            eintraege.append(daten)
    return eintraege


_UMLAUTE = {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}


def _slug(titel: str) -> str:
    roh = (titel or "eintrag").lower()
    for zeichen, ersatz in _UMLAUTE.items():
        roh = roh.replace(zeichen, ersatz)
    roh = "".join(c if c.isalnum() else "-" for c in roh)
    roh = "-".join(t for t in roh.split("-") if t)[:50]
    return roh or "eintrag"


def _eintrag_schreiben(root: Path, eintrag: dict) -> Path:
    """Legt das Paar <name>.json / <name>.md an. Die .md ist fuer Menschen (auch fuer den, der das Projekt
    fuehrt und im Diff sehen soll, was hinausgehen wuerde), die .json fuer den Empfaenger."""
    ordner = root / LOG_DIR_REL
    ordner.mkdir(parents=True, exist_ok=True)
    basis = f"{eintrag.get('datum', time.strftime('%Y-%m-%d'))}-{_slug(eintrag.get('titel', ''))}"
    name, nummer = basis, 2
    while (ordner / f"{name}.json").exists():
        name, nummer = f"{basis}-{nummer}", nummer + 1
    (ordner / f"{name}.json").write_text(
        json.dumps(eintrag, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    zeilen = [f"# {eintrag.get('titel') or '(ohne Titel)'}", "",
              f"- Art: `{eintrag.get('art')}`", f"- Datum: {eintrag.get('datum')}"]
    if eintrag.get("url"):
        zeilen.append(f"- Link: {eintrag['url']}")
    zeilen += ["- Status: wartet auf Versand", "", eintrag.get("text") or "", ""]
    (ordner / f"{name}.md").write_text("\n".join(zeilen), encoding="utf-8")
    return ordner / f"{name}.json"


FRAGEBOGEN_REL = "docs/ai/template-feedback/feedback.md"
_ANTWORT = re.compile(r"(?m)^##\s+(?P<frage>.+?)\s*$\n(?P<rumpf>(?:(?!^##\s).*\n?)*)")


def _fragebogen_lesen(root: Path) -> list:
    """Die vom Menschen geschriebenen Antworten aus feedback.md - je Abschnitt die Zeilen unter '> '.
    Leer gebliebene Fragen fallen weg; der Abschnitt 'Bereits gesendet' ist Archiv und wird nie erneut
    gesendet."""
    fp = root / FRAGEBOGEN_REL
    if not fp.exists():
        return []
    try:
        text = fp.read_text(encoding="utf-8-sig")
    except OSError:
        return []
    raus = []
    for treffer in _ANTWORT.finditer(text.split("\n---\n")[0]):
        frage = treffer.group("frage").strip()
        antwort = " ".join(
            zeile.lstrip("> ").strip()
            for zeile in treffer.group("rumpf").splitlines()
            if zeile.strip().startswith(">") and zeile.strip(" >")
        ).strip()
        if antwort:
            raus.append({"frage": frage, "antwort": antwort})
    return raus


def _fragebogen_zuruecksetzen(root: Path, antworten: list) -> None:
    """Nach dem Versand: Antworten als Kurzfassung ans Ende haengen, die '> '-Zeilen wieder leeren.
    Die Fragen und Ueberschriften bleiben stehen - die Datei ist danach wieder benutzbar."""
    fp = root / FRAGEBOGEN_REL
    if not fp.exists() or not antworten:
        return
    try:
        text = fp.read_text(encoding="utf-8-sig")
    except OSError:
        return
    kopf, trenner, archiv = text.partition("\n---\n")
    neu_kopf = re.sub(r"(?m)^>[ \t]*\S.*$", "> ", kopf)
    block = [f"\n### Gesendet am {time.strftime('%Y-%m-%d')}", ""]
    for eintrag in antworten:
        block.append(f"- **{eintrag['frage']}:** {eintrag['antwort']}")
    block.append("")
    fp.write_text(neu_kopf + (trenner or "\n---\n") + archiv + "\n".join(block), encoding="utf-8")


def _nach_sent(root: Path) -> int:
    """Nach erfolgreichem Versand: Paare nach sent/ verschieben. Sie bleiben damit nachlesbar - der Nachweis
    ist der ganze Zweck des Ordners -, zaehlen aber nicht mehr als wartend."""
    ziel = root / LOG_DIR_REL / "sent"
    ziel.mkdir(parents=True, exist_ok=True)
    bewegt = 0
    for fp in _wartende_dateien(root):
        for endung in (".json", ".md"):
            quelle = fp.with_suffix(endung)
            if quelle.exists():
                quelle.replace(ziel / quelle.name)
        bewegt += 1
    return bewegt


def _feedback_block(tj: dict) -> dict:
    block = tj.get("feedback")
    return block if isinstance(block, dict) else {}


def _schalter(tj: dict) -> dict:
    """Nur die Schalterstellungen aus applied_config, die in einer geschlossenen Wortliste stehen."""
    angewandt = tj.get("applied_config") or {}
    return {k: angewandt.get(k) for k in SCHALTER_WHITELIST if angewandt.get(k)}


def _mcp_server(root: Path) -> dict:
    """Welche MCP-Server das Projekt nutzt - aber nur Kennungen, die im mitgelieferten Katalog stehen.
    Alles andere (selbstgebaute oder firmeninterne Server) wird nur gezaehlt: Ein Servername wie
    "kunde-abrechnung-db" waere ein Projektbezug, und genau den soll die Meldung nicht enthalten."""
    katalog = root / ".claude" / "mcp-katalog.md"
    config = root / "AI-CONFIG.md"
    if not katalog.exists() or not config.exists():
        return {}
    try:
        bekannt = set(re.findall(r"(?m)^\|\s*`([a-z0-9-]+)`\s*\|", katalog.read_text(encoding="utf-8-sig")))
        zeile = re.search(r"(?m)^\|\s*MCP-Server\s*\|([^|]*)\|",
                          config.read_text(encoding="utf-8-sig"))
    except OSError:
        return {}
    if not zeile:
        return {}
    genannt = [s.strip().strip("`") for s in zeile.group(1).split(",") if s.strip()]
    aus_katalog = sorted({s for s in genannt if s in bekannt})
    andere = len([s for s in genannt if s not in bekannt])
    ergebnis = {}
    if aus_katalog:
        ergebnis["aus_katalog"] = aus_katalog
    if andere:
        ergebnis["andere"] = andere
    return ergebnis


def _umfang(root: Path) -> set:
    """Welche Kennungen aus AI-CONFIG.md § Feedback-Umfang gelten. Unbekanntes wird ignoriert - im Zweifel
    wird WENIGER gesammelt, nicht mehr."""
    roh = _config_wert(root, "Feedback-Umfang", "a,b,c", {})
    return {t.strip().lower() for t in roh.split(",") if t.strip().lower() in {"a", "b", "c"}}


def _git(root: Path, *args) -> str:
    """git-Aufruf, der nie stoert: Faellt er aus (kein Repo, kein git, Timeout), gibt es eben keine Zahlen."""
    try:
        res = subprocess.run(["git", "-C", str(root)] + list(args), capture_output=True, text=True,
                             timeout=20)
    except (OSError, subprocess.SubprocessError):
        return ""
    return res.stdout if res.returncode == 0 else ""


def _kennzahlen(root: Path) -> dict:
    """Umfang a: Zahlen aus `git log` und Dateisystem - NUR Zahlen, nie Namen, nie Pfade, nie Texte.
    Was sich nicht ermitteln laesst, faellt weg statt geschaetzt zu werden (Entscheidung 2026-09-15)."""
    zahlen = {}
    protokoll = _git(root, "log", "--format=%ad", "--date=short").split()
    if protokoll:
        zahlen["commits"] = len(protokoll)
        zahlen["tage_aktiv"] = len(set(protokoll))
        zahlen["erster_commit"] = protokoll[-1]
        zahlen["letzter_commit"] = protokoll[0]
        seit = time.strftime("%Y-%m-%d", time.localtime(time.time() - 30 * 86400))
        zahlen["commits_30_tage"] = sum(1 for d in protokoll if d >= seit)
    ki_doku = _git(root, "log", "--format=%h", "--", "docs/ai").split()
    if ki_doku:
        zahlen["commits_docs_ai"] = len(ki_doku)
    dateien, bytes_gesamt = 0, 0
    for pfad in root.rglob("*"):
        teile = pfad.relative_to(root).parts
        if any(t in (".git", "node_modules", ".venv", "dist", "build", ".output", ".nuxt") for t in teile):
            continue
        if pfad.is_file():
            dateien += 1
            try:
                bytes_gesamt += pfad.stat().st_size
            except OSError:
                pass
    zahlen["dateien"] = dateien
    zahlen["groesse_mb"] = round(bytes_gesamt / 1_048_576, 1)
    log = root / "ai.log"
    if log.exists():  # nur, wenn das Logging ueberhaupt laeuft - es ist standardmaessig aus
        try:
            zeilen = log.read_text(encoding="utf-8", errors="ignore").splitlines()
            zahlen["log_zeilen"] = len(zeilen)
            zahlen["log_sitzungen"] = sum(1 for z in zeilen if "[session]" in z and " start" in z)
        except OSError:
            pass
    return zahlen


def _regel_aenderungen(root: Path) -> dict:
    """Umfang b: Wie oft an den KI-Regeln und an der Doku-Struktur gearbeitet wurde - als ZAHL je Bereich,
    nie als Inhalt. Ob jemand eine Regel ergaenzt hat, ist fuers Template interessant; WAS darin steht,
    beschreibt der Assistent in einem eigenen Eintrag (--add), wenn es fuer Fremde taugt."""
    bereiche = {
        "agents_md": "AGENTS.md", "claude_md": "CLAUDE.md",
        "agenten": ".claude/agents", "skills": ".claude/skills", "scripte": ".claude/scripts",
        "checklisten": "docs/ai/checklists.md",
    }
    raus = {}
    for name, pfad in bereiche.items():
        treffer = _git(root, "log", "--format=%h", "--", pfad).split()
        if treffer:
            raus[name] = len(treffer)
    return raus


def _werkzeug_nutzung(root: Path) -> dict:
    """Umfang c: Wie viele Agenten, Skills und Scripte es gibt und wie viele davon NICHT aus dem Template
    stammen. Namen selbstgebauter Dateien bleiben drauusen - sie verraten oft das Projekt."""
    raus = {}
    for name, ordner, muster in (("agenten", ".claude/agents", "*.md"),
                                 ("skills", ".claude/skills", "*"),
                                 ("scripte", ".claude/scripts", "*.py")):
        d = root / ordner
        if d.is_dir():
            raus[name] = len([p for p in d.glob(muster) if p.name != "README.md"])
    return raus


def _nutzlast(root: Path, tj: dict) -> dict:
    fb = _feedback_block(tj)
    angewandt = tj.get("applied_config") or {}
    umfang = _umfang(root)
    nutzlast = {
        "schema": 1,
        "herkunft": HERKUNFT,
        "projekt_id": fb.get("projekt_id"),
        "datum": time.strftime("%Y-%m-%d"),
        "template_basis": tj.get("base_commit"),
        "weg": fb.get("weg"),
        "ausfuellart": fb.get("ausfuellart"),
        "umfang": ",".join(sorted(umfang)),
        "werkzeuge_entfernt": angewandt.get("KI-Werkzeuge-entfernt") or [],
        "regelsaetze": angewandt.get("Coding-Guidelines") or [],
        "schalter": _schalter(tj),
        "eintraege": _outbox(root),
    }
    # Was der Mensch selbst geschrieben hat, geht immer mit - unabhaengig vom gewaehlten Umfang. Der Umfang
    # steuert, was der ASSISTENT von sich aus sammelt, nicht was {{AUFTRAGGEBER}} sagen will.
    antworten = _fragebogen_lesen(root)
    if antworten:
        nutzlast["fragebogen"] = antworten
    # Die drei Umfaenge sind einzeln abwaehlbar - was nicht gewaehlt ist, wird gar nicht erst erhoben.
    if "a" in umfang:
        nutzlast["kennzahlen"] = _kennzahlen(root)
    if "b" in umfang:
        nutzlast["regel_aenderungen"] = _regel_aenderungen(root)
    if "c" in umfang:
        nutzlast["mcp_server"] = _mcp_server(root)
        nutzlast["werkzeuge"] = _werkzeug_nutzung(root)
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
                if k == "url" and wert.get("art") == "link":
                    continue  # bewusst gesetzt und eigens geprueft, siehe _link_pruefen
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
    if nutzlast.get("art") == "direkt":
        print("Inhalt:   eine von Hand geschriebene Nachricht")
    else:
        print(f"Eintraege: {len(nutzlast.get('eintraege') or [])}")
    print("")
    print("Vollstaendige Nutzlast:")
    for zeile in json.dumps(nutzlast, indent=2, ensure_ascii=False).split("\n"):
        print("  " + zeile)


def _protokoll_lokal(root: Path) -> bool:
    """True, wenn .gitignore die Nutzlast-Dateien des Protokolls ausnimmt."""
    gi = root / ".gitignore"
    if not gi.exists():
        return False
    return any(z.strip() == GITIGNORE_GLOB for z in gi.read_text(encoding="utf-8").splitlines())


def _protokoll_lokal_setzen(root: Path, lokal: bool) -> str:
    """Traegt die Nutzlast-Dateien in .gitignore ein bzw. nimmt den Eintrag wieder heraus.

    Rueckgabe: kurze Meldung fuer die Ausgabe. Angefasst wird nur die eigene Zeile samt Kopfkommentar -
    alles andere in .gitignore bleibt unberuehrt.
    """
    gi = root / ".gitignore"
    vorhanden = _protokoll_lokal(root)
    if lokal == vorhanden:
        return f"Protokoll: {'lokal (bereits in .gitignore)' if lokal else 'versioniert (unveraendert)'}"
    zeilen = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    if lokal:
        if zeilen and zeilen[-1].strip():
            zeilen.append("")
        zeilen += [GITIGNORE_KOPF, GITIGNORE_GLOB]
        gi.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
        return f"Protokoll: lokal - {GITIGNORE_GLOB} in .gitignore eingetragen"
    behalten, i = [], 0
    while i < len(zeilen):
        if zeilen[i].strip() == GITIGNORE_GLOB:
            if behalten and behalten[-1].strip() == GITIGNORE_KOPF:
                behalten.pop()
            i += 1
            continue
        behalten.append(zeilen[i])
        i += 1
    gi.write_text("\n".join(behalten).rstrip("\n") + "\n", encoding="utf-8")
    return f"Protokoll: versioniert - {GITIGNORE_GLOB} aus .gitignore entfernt"


def cmd_status(root: Path) -> int:
    tj = _template_json(root)
    fb = _feedback_block(tj)
    modus, takt = _modus(root), _takt(root)
    print(f"Feedback:  {modus}   (Takt: {takt}, aus {CONFIG_REL})")
    print(f"Ziel:      {_endpoint()}")
    print(f"Projekt-ID: {fb.get('projekt_id') or '- (entsteht bei --enable)'}")
    print(f"Wartend:   {len(_outbox(root))} Eintraege ({LOG_DIR_REL}/, je .md + .json)")
    gesendet = list((root / LOG_DIR_REL / "sent").glob("*.json")) if (root / LOG_DIR_REL / "sent").is_dir() else []
    print(f"Gesendet:  {len(gesendet)} Eintraege ({LOG_DIR_REL}/sent/)")
    print(f"Protokoll: {LOG_DIR_REL}/ - "
          f"{'lokal, per .gitignore ausgenommen' if _protokoll_lokal(root) else 'versioniert (im Diff sichtbar)'}")
    print(f"Zuletzt gesendet: {fb.get('zuletzt_gesendet') or 'nie'}")
    if fb.get("repo_url"):
        print(f"Repo-URL:  {fb['repo_url']}")
    if modus == "aus":
        print("")
        print("Nichts wird gesendet. Einschalten: feedback.py --enable [--modus bestaetigen|automatisch|manuell]")
    return 0


def cmd_enable(root: Path, repo_url, an: bool, weg=None, ausfuellart=None, modus=None, protokoll=None) -> int:
    tj = _template_json(root)
    fb = _feedback_block(tj)
    ziel = (modus or "automatisch") if an else "aus"
    if ziel not in ("aus", "bestaetigen", "automatisch", "manuell"):
        print("Fehler: --modus muss aus, bestaetigen, automatisch oder manuell sein.", file=sys.stderr)
        return 2
    if protokoll not in (None, "versionieren", "lokal"):
        print("Fehler: --protokoll muss versionieren oder lokal sein.", file=sys.stderr)
        return 2
    if not _config_setzen(root, "Feedback", ziel):
        print(f"Fehler: Zeile 'Feedback' in {CONFIG_REL} nicht gefunden - bitte dort von Hand setzen.",
              file=sys.stderr)
        return 2
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
    print(f"{CONFIG_REL}: Feedback = {ziel}   (Takt: {_takt(root)})")
    if protokoll is not None:
        print(_protokoll_lokal_setzen(root, protokoll == "lokal"))
    if an:
        wo = "lokal, per .gitignore ausgenommen" if _protokoll_lokal(root) else "versioniert"
        print(f"Ziel: {_endpoint()} - Protokoll jeder Sendung unter {LOG_DIR_REL}/ ({wo})")
    return 0


def cmd_add(root: Path, art: str, titel: str, text: str, url=None) -> int:
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
    if art == "link":
        if not url:
            print("Fehler: --art link braucht --url.", file=sys.stderr)
            return 2
        schlecht = _link_pruefen(url)
        if schlecht:
            print("Nicht uebernommen - die Adresse ist ungeeignet:", file=sys.stderr)
            for grund in schlecht:
                print(f"  - {grund}", file=sys.stderr)
            return 1
    elif url:
        print("Fehler: --url gibt es nur mit --art link.", file=sys.stderr)
        return 2
    beanstandet = _verdaechtig(titel, _endpoint()) + _verdaechtig(text, _endpoint())
    if beanstandet:
        print("Nicht uebernommen - der Text enthaelt:", file=sys.stderr)
        for grund in sorted(set(beanstandet)):
            print(f"  - {grund}", file=sys.stderr)
        print("Beschreibe das Muster, nicht das Projekt: keine Pfade, keine Namen, kein Code.",
              file=sys.stderr)
        return 1
    eintrag = {"art": art, "titel": titel, "text": text, "datum": time.strftime("%Y-%m-%d")}
    if url:
        eintrag["url"] = url
    ziel = _eintrag_schreiben(root, eintrag)
    print(f"Uebernommen: {ziel.relative_to(root).as_posix()} (+ gleichnamige .md zum Lesen). "
          f"{len(_outbox(root))} Eintrag/Eintraege warten. Ansehen: feedback.py --plan")
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
    if _modus(root) == "aus":
        print("Feedback ist aus - es wuerde nichts gesendet (einschalten: --enable).")
        return 0
    print("Unbedenklich. Senden: feedback.py --send")
    return 0


def _tage_seit(stempel) -> float:
    """Tage seit dem Zeitstempel 'JJJJ-MM-TT HH:MM'. Sehr gross, wenn nie gesendet oder unlesbar."""
    if not stempel:
        return 1e9
    try:
        gesendet = time.mktime(time.strptime(str(stempel)[:16], "%Y-%m-%d %H:%M"))
    except ValueError:
        return 1e9
    return (time.time() - gesendet) / 86400.0


def _protokollieren(root: Path, nutzlast: dict, endpoint: str) -> Path:
    ordner = root / LOG_DIR_REL
    ordner.mkdir(parents=True, exist_ok=True)
    fp = ordner / (time.strftime("%Y-%m-%d_%H%M") + ".json")
    fp.write_text(json.dumps({"gesendet_an": endpoint, "zeit": time.strftime("%Y-%m-%d %H:%M"),
                              "nutzlast": nutzlast}, indent=2, ensure_ascii=False) + "\n",
                  encoding="utf-8")
    return fp


def cmd_send(root: Path, force: bool, ja: bool) -> int:
    tj = _template_json(root)
    fb = _feedback_block(tj)
    modus, takt = _modus(root), _takt(root)
    if modus == "aus":
        print(f"Abbruch: Feedback ist aus ({CONFIG_REL}).", file=sys.stderr)
        return 2
    if modus == "manuell" and not force:
        print("Nichts gesendet: Feedback steht auf 'manuell' - Versand nur ueber /act-feedback (--force).")
        return 0
    stunden_min = TAKT_STUNDEN.get(takt)
    if stunden_min is None and not force:
        print("Nichts gesendet: Takt steht auf 'manuell' - Versand nur ueber /act-feedback (--force).")
        return 0
    stunden = _tage_seit(fb.get("zuletzt_gesendet")) * 24.0
    if stunden_min is not None and stunden < stunden_min and not force:
        print(f"Nichts gesendet: letzte Sendung vor {stunden:.1f} h, Takt '{takt}' erlaubt fruehestens nach "
              f"{stunden_min} h. Der Ausgang bleibt erhalten und geht beim naechsten Mal mit.")
        return 0
    nutzlast = _nutzlast(root, tj)
    endpoint = _endpoint()
    fehler = _pruefen(nutzlast, endpoint)
    if fehler:
        print("Beanstandet - nicht gesendet:", file=sys.stderr)
        for f in fehler:
            print(f"  - {f}", file=sys.stderr)
        return 1
    if modus == "bestaetigen" and not ja:
        _zeige(nutzlast, endpoint)
        print("")
        print("Modus 'bestaetigen': nichts gesendet. Zum Senden dieselbe Zeile mit --yes wiederholen.")
        return 0
    code, fehlertext = _posten(endpoint, nutzlast)
    if fehlertext:
        print(f"Abbruch: {fehlertext} Ausgang bleibt erhalten.", file=sys.stderr)
        return 2
    protokoll = _protokollieren(root, nutzlast, endpoint)
    fb["zuletzt_gesendet"] = time.strftime("%Y-%m-%d %H:%M")
    tj["feedback"] = fb
    _template_json_schreiben(root, tj)
    _fragebogen_zuruecksetzen(root, nutzlast.get("fragebogen") or [])
    bewegt = _nach_sent(root)
    anzahl = len(nutzlast.get("eintraege") or [])
    nachsatz = ("liegt nur lokal (.gitignore)" if _protokoll_lokal(root)
                else "gehoert in den naechsten Commit")
    print(f"Rueckmeldung gesendet (HTTP {code}, {anzahl} Eintraege). "
          f"Protokoll: {protokoll.relative_to(root).as_posix()} - {nachsatz}.")
    if bewegt:
        print(f"{bewegt} Eintrag/Eintraege nach {LOG_DIR_REL}/sent/ verschoben.")
    return 0


class _KeineWeiterleitung(urllib.request.HTTPRedirectHandler):
    """Weiterleitungen werden NICHT gefolgt. Grund: urllib macht aus einem umgeleiteten POST ein GET - die
    Nutzlast waere weg, und der Empfaenger antwortete mit einem irrefuehrenden 405. Lieber ein klarer
    Fehler mit der Zieladresse, die in AI-CONFIG/Script gehoert."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_SENDER = urllib.request.build_opener(_KeineWeiterleitung)


def _posten(endpoint: str, nutzlast: dict):
    """(code, fehlertext). Genau ein POST, ohne Weiterleitung, mit lesbarer Diagnose."""
    daten = json.dumps(nutzlast, ensure_ascii=False).encode("utf-8")
    anfrage = urllib.request.Request(
        endpoint, data=daten, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8",
                 "User-Agent": "agentic-coding-template-feedback/1"})
    try:
        with _SENDER.open(anfrage, timeout=TIMEOUT_S) as antwort:
            return antwort.status, None
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            ziel = e.headers.get("Location", "(ohne Ziel)")
            return None, (f"Der Empfaenger leitet weiter auf {ziel} - eine Weiterleitung frisst den Inhalt "
                          f"des POST. Trage genau diese Adresse als Ziel ein.")
        return None, f"Empfaenger antwortet mit HTTP {e.code}."
    except (urllib.error.URLError, OSError) as e:
        return None, f"nicht erreichbar ({e})."


DIREKT_MAX = 4000


def cmd_direkt(root: Path, text: str, ja: bool) -> int:
    """Eine von Hand geschriebene Nachricht senden. Dieser Weg ist bewusst NICHT an die Einwilligung
    gebunden: Wer den Text selbst schreibt und den Versand selbst ausloest, hat damit alles getan, wofuer
    die Einwilligung sonst da ist. Steht Feedback auf "aus", geht ausschliesslich der Text hinaus - keine
    Projekt-Kennung, kein Kontext, nichts, was das Projekt wiedererkennbar macht. Sonst darf der Kontext
    mit, damit sich mehrere Meldungen desselben Projekts zusammenfuehren lassen."""
    text = (text or "").strip()
    if not text:
        print("Abbruch: kein Text angegeben.", file=sys.stderr)
        return 2
    if len(text) > DIREKT_MAX:
        print(f"Abbruch: Text laenger als {DIREKT_MAX} Zeichen - bitte kuerzen.", file=sys.stderr)
        return 2

    endpoint = _endpoint()
    # Auch ein selbst geschriebener Satz laeuft durch den Filter: Ein versehentlich mitkopierter Pfad oder
    # ein Token ist genauso heraus, wie wenn der Assistent ihn geschrieben haette. Abgelehnt wird hier aber
    # nicht endgueltig - der Grund wird genannt, damit {{AUFTRAGGEBER}} umformulieren kann.
    beanstandet = _verdaechtig(text, endpoint)
    if beanstandet:
        print("Nicht gesendet - der Text enthaelt etwas, das das Projekt verraten koennte:", file=sys.stderr)
        for grund in beanstandet:
            print(f"  - {grund}", file=sys.stderr)
        print("  Bitte ohne diese Stelle neu formulieren.", file=sys.stderr)
        return 1

    tj = _template_json(root)
    fb = _feedback_block(tj)
    modus = _modus(root)
    nutzlast = {"schema": SCHEMA_DIREKT, "herkunft": HERKUNFT, "art": "direkt",
                "datum": time.strftime("%Y-%m-%d"), "text": text}
    if modus != "aus":
        nutzlast["projekt_id"] = fb.get("projekt_id")
        nutzlast["template_basis"] = tj.get("base_commit")
        for schluessel in ("weg", "ausfuellart"):
            if fb.get(schluessel):
                nutzlast[schluessel] = fb[schluessel]
        nutzlast = {k: v for k, v in nutzlast.items() if v is not None}

    _zeige(nutzlast, endpoint)
    print("")
    if modus == "aus":
        print("Feedback steht auf 'aus' - es geht ausschliesslich dieser Text hinaus, ohne Projekt-Kennung.")

    code, fehlertext = _posten(endpoint, nutzlast)
    if fehlertext:
        print(f"Abbruch: {fehlertext}", file=sys.stderr)
        return 2

    protokoll = _protokollieren(root, nutzlast, endpoint)
    nachsatz = "liegt nur lokal (.gitignore)" if _protokoll_lokal(root) else "gehoert in den naechsten Commit"
    print(f"Nachricht gesendet (HTTP {code}). Protokoll: {protokoll.relative_to(root).as_posix()} - {nachsatz}.")
    return 0


def cmd_clear(root: Path) -> int:
    """Verwirft die wartenden Eintraege. Was bereits gesendet wurde, liegt in sent/ und bleibt dort -
    das Protokoll ist der Nachweis und wird nie geleert."""
    anzahl = 0
    for fp in _wartende_dateien(root):
        for endung in (".json", ".md"):
            kandidat = fp.with_suffix(endung)
            if kandidat.exists():
                kandidat.unlink()
        anzahl += 1
    print(f"Ausgang geleert ({anzahl} Eintraege verworfen). Gesendetes in sent/ bleibt unangetastet.")
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
    gruppe.add_argument("--send", action="store_true",
                        help="Senden, wenn Einwilligung, Filter und Wochensperre es zulassen")
    gruppe.add_argument("--clear", action="store_true", help="Ausgang leeren")
    gruppe.add_argument("--direkt", default=None, metavar="TEXT",
                        help="Eine von Hand geschriebene Nachricht sofort senden - geht IMMER, auch bei "
                             "Feedback: aus (dann ohne Projekt-Kennung und ohne Kontext)")
    parser.add_argument("--art", default=None, help=f"mit --add: {', '.join(ARTEN)}")
    parser.add_argument("--titel", default=None, help="mit --add: eine Zeile")
    parser.add_argument("--text", default=None, help="mit --add: zwei bis sechs Saetze")
    parser.add_argument("--url", default=None,
                        help="mit --add --art link: die oeffentliche Adresse aus docs/ai/resources.md")
    parser.add_argument("--repo-url", default=None, help="mit --enable: oeffentliche Repo-URL (optional)")
    parser.add_argument("--protokoll", default=None, choices=["versionieren", "lokal"],
                        help="mit --enable: Sendeprotokoll versionieren (Default) oder per .gitignore "
                             "lokal halten")
    parser.add_argument("--weg", default=None, choices=["neu", "nachgeruestet"],
                        help="mit --enable: wie das Projekt entstanden ist")
    parser.add_argument("--ausfuellart", default=None, choices=["leer", "interview", "config"],
                        help="mit --enable: wie AI-CONFIG.md befuellt wurde")
    parser.add_argument("--force", action="store_true",
                        help="mit --send: Takt- und Modus-Sperre uebergehen (das tut /act-feedback)")
    parser.add_argument("--yes", action="store_true",
                        help="mit --send und Modus 'bestaetigen': nach Ansicht tatsaechlich senden")
    parser.add_argument("--modus", default=None,
                        help="mit --enable: aus, bestaetigen, automatisch (Default), manuell")
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
        return cmd_enable(root, args.repo_url, True, args.weg, args.ausfuellart, args.modus,
                          args.protokoll)
    if args.disable:
        return cmd_enable(root, None, False)
    if args.add:
        return cmd_add(root, args.art, args.titel, args.text, args.url)
    if args.direkt is not None:
        return cmd_direkt(root, args.direkt, args.yes)
    if args.send:
        return cmd_send(root, args.force, args.yes)
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
