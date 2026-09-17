#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Bibliothek fuer alles rund um AI-CONFIG.md: Wortlisten der zulaessigen Werte je Schluessel (KEY_MAP,
# *_WERTE/*_ALIAS/*_TEXT), das Tabellen-/Altformat-Parsing (parse_config/load_config), die Normalisierer je
# Schluessel (normalize_*) und die Ableitung von Platzhalterwerten/Orchestrator-Rufname (compute_values,
# default_orchestrator/detect_ai_tool) sowie den Schnappschuss fuer sync-config.py (build_applied_config).
# Herausgetrennt aus setup-lib.py (Backlog der Template-Pflege, Q4), das als duenne Fassade
# (Re-Export dieser drei Module) plus dem eigentlichen Setup-Ablauf bestehen bleibt - siehe dort. Reine
# Python-Stdlib, kein Paket noetig, keine Abhaengigkeit von files-lib.py/claudemd-lib.py (sonst Zyklus).
# Zusaetzlich die gemeinsame Dateisammlung fuers projektweite Ersetzen (EXCLUDE_DIR_NAMES_REPLACE/
# iter_repo_replace_files) - genutzt von files-lib.py (Platzhalter/Befehls-Werte) und rename-lib.py
# (Rufname), siehe dort.

import importlib.util
import json
import os
import re
import subprocess
import time
from pathlib import Path


CONFIG_REL = "AI-CONFIG.md"

KEY_MAP = {
    "Projektname": "projektname",
    "Auftraggeber": "auftraggeber",
    "Orchestrator": "orchestrator",
    "KI-Werkzeuge": "ki_werkzeuge",
    "Stack": "stack",
    "Orchestrator-Modell": "orchestrator_modell",
    "Commit-Verhalten": "commit_verhalten",
    "Ideen-Ablauf": "ideen_ablauf",
    "Testtiefe": "testtiefe",
    "Schreibstil": "schreibstil",
    "Feedback": "feedback",
    "Feedback-Takt": "feedback_takt",
    "Feedback-Umfang": "feedback_umfang",
    "Logging": "logging",
    "Logging-Tiefe": "logging_tiefe",
    "Wartung": "wartung",
    "Wartungsaufgaben": "wartungsaufgaben",
    "Wartungsberichte": "wartungsberichte",
    "Code-Analyse": "code_analyse",
    "Code-Optimierung": "code_optimierung",
    "Coding-Guidelines": "coding_guidelines",
    "Struktur-Migration": "struktur_migration",
    "Alter Orchestrator-Name": "alter_orchestrator_name",
    "Install-Befehl": "install_befehl",
    "Dev-Start-Befehl": "dev_start_befehl",
    "Lint-Befehl": "lint_befehl",
    "Typecheck-Befehl": "typecheck_befehl",
    "Test-Befehl": "test_befehl",
    "E2E-Befehl": "e2e_befehl",
}

KEY_LOOKUP = {k.lower(): v for k, v in KEY_MAP.items()}

SECTION_NAMES = ["Ziel", "Nutzer", "Features", "Non-Scope", "Architektur", "Risiken", "Sonstiges"]

TOOL_CANON = {
    "claude code": "Claude Code",
    "copilot": "Copilot",
    "github copilot": "Copilot",
    "cursor": "Cursor",
    "aider": "Aider",
    "gemini cli": "Gemini CLI",
    "gemini": "Gemini CLI",
    "cline": "Cline",
    "chatgpt/codex": "ChatGPT/Codex",
    "chatgpt": "ChatGPT/Codex",
    "codex": "ChatGPT/Codex",
    "ollama": "Ollama",
}

# Welches KI-Werkzeug fuehrt diesen Lauf gerade aus? Die Scripte werden vom Assistenten gestartet und erben
# dessen Prozessumgebung - daran laesst sich das Werkzeug erkennen, statt {{AUFTRAGGEBER}} im Interview
# danach zu fragen, was er offensichtlich gerade benutzt.
#
# EINEN STANDARD GIBT ES NICHT (Stand 2026-09-14). Zwei konkurrierende Vorschlaege:
#   - AGENT=<werkzeug> als Gegenstueck zu CI=true (agentsmd/agents.md#136). Umgesetzt von Goose, gelesen
#     von Bun; fuer Claude Code offen (anthropics/claude-code#24838), fuer Codex abgelehnt
#     (openai/codex#13416, "not planned").
#   - AI_AGENT=<name> - wird von Dritt-Bibliotheken (Vercel detect-agent, unjs/std-env) GELESEN, aber kein
#     Hersteller dokumentiert, dass er sie SETZT.
# Beide werden unten als schwache Rueckfallebene ausgewertet, nicht als verlaessliche Marke.
#
# Fuer GitHub Copilot CLI, Aider und Windsurf gibt es KEINE Marke - dort wird gefragt statt erkannt. Das ist
# Absicht: Eine erfundene Variable waere schlechter als keine, weil sie eine falsche Vorauswahl erzeugt.
# (Aiders OR_APP_NAME=Aider ist ein Nebeneffekt von OpenRouter, keine Selbstauskunft.)
#
# Der Copilot Coding Agent in GitHub Actions ist nicht sicher erkennbar: GITHUB_ACTIONS=true sagt nichts
# ueber Copilot, und beobachtbar bleibt nur GITHUB_ACTOR="copilot-swe-agent[bot]" - eine Beobachtung aus
# echten Laeufen, keine zugesagte Marke. Deshalb hier bewusst nicht aufgenommen.
#
# Spalte "beleg": gemessen (selbst in einer laufenden Sitzung gesehen) > doku (Hersteller dokumentiert es) >
# quelltext (im Repo des Herstellers gefunden, aber Implementierungsdetail) > schwach (Konvention oder
# Dritt-Quelle). Eine Fehlerkennung ist nicht schlimm, weil die Auswahl im Interview bestaetigt wird -
# geraten wird trotzdem nicht: Was nicht erkannt wird, liefert None.
AGENT_MARKERS = [
    # (Variable, geforderter Wert oder None = "gesetzt genuegt", Werkzeug, beleg, Quelle)
    ("CLAUDECODE", "1", "Claude Code", "gemessen",
     "code.claude.com/docs/en/env-vars; hier am 2026-09-14 in einer Sitzung gesehen"),
    ("GEMINI_CLI", None, "Gemini CLI", "doku",
     "google-gemini/gemini-cli, docs/tools/shell.md"),
    ("CLINE_ACTIVE", None, "Cline", "doku",
     "cline/cline Discussion #5366, vom Betreiber bestaetigt"),
    ("CURSOR_AGENT", None, "Cursor", "doku",
     "cursor.com/docs/agent/tools/terminal - vom Hersteller als Implementierungsdetail behandelt"),
    ("COPILOT_AGENT", "1", "Copilot", "quelltext",
     "microsoft/vscode PR#316267 - nur VS Code Agent Mode, sehr jung; die Copilot-CLI setzt nichts"),
    ("CODEX_SANDBOX", None, "ChatGPT/Codex", "quelltext",
     "codex-rs process_manager.rs - Nebeneffekt der Sandbox, keine Identitaetsmarke"),
]

# Rueckfallebene: die beiden konkurrierenden Konventionen. AGENT=<werkzeug> ist der aussichtsreichere
# Vorschlag, AI_AGENT=<werkzeug>_<version>_<modus> wird von Dritt-Bibliotheken erwartet. Beide werden gegen
# TOOL_CANON aufgeloest, damit kuenftige Werkzeuge ohne eigene Zeile oben erkannt werden.
AGENT_GENERIC_VARS = ("AGENT", "AI_AGENT")

# Rufname des Orchestrators, wenn AI-CONFIG.md keinen nennt: der Kurzname dessen, was tatsaechlich arbeitet.
# Wo das Werkzeug ein waehlbares Modell hat (Claude Code), ist das MODELL der Name - der Assistent heisst dann
# wie das Modell, auf dem er laeuft, statt wie ein Produkt. Sonst der Kurzname des Werkzeugs. Wer mit Gemini
# CLI anlegt, soll nicht mit einem Assistenten namens "Opus" weiterarbeiten.
ORCHESTRATOR_MODELL_NAME = {
    "opus": "Opus",
    "sonnet": "Sonnet",
    "haiku": "Haiku",
    "inherit": "Claude",
}
ORCHESTRATOR_WERKZEUG_NAME = {
    "Gemini CLI": "Gemini",
    "Copilot": "Copilot",
    "Cursor": "Cursor",
    "Aider": "Aider",
    "ChatGPT/Codex": "Codex",
    "Cline": "Cline",
    "Ollama": "Ollama",
}
# Wird gar nichts erkannt, bleibt es beim historischen Standardnamen - er aendert nichts an bestehenden
# Projekten und ist besser als ein geratener.
ORCHESTRATOR_FALLBACK = "Fable"


def default_orchestrator(cfg=None, env=None):
    """(Rufname, Begruendung) - der Name, der gilt, wenn AI-CONFIG.md keinen nennt."""
    werkzeug, beleg, _stark = detect_ai_tool(env)
    if werkzeug == "Claude Code":
        modell = (cfg or {}).get("orchestrator_modell")
        modell = (modell or "opus").strip().lower()
        name = ORCHESTRATOR_MODELL_NAME.get(modell)
        if name:
            return name, f"Claude Code auf {modell} ({beleg})"
        return ORCHESTRATOR_MODELL_NAME["opus"], f"Claude Code, Modell unbekannt - Standardmodell ({beleg})"
    if werkzeug and werkzeug in ORCHESTRATOR_WERKZEUG_NAME:
        return ORCHESTRATOR_WERKZEUG_NAME[werkzeug], f"{werkzeug} erkannt ({beleg})"
    return ORCHESTRATOR_FALLBACK, "kein Werkzeug erkannt - Standardname"


def detect_ai_tool(env=None):
    """Erkennt das ausfuehrende KI-Werkzeug an der Prozessumgebung.

    Rueckgabe: (werkzeug, beleg_text, stark) - werkzeug ist ein kanonischer Name aus TOOL_CANON, beleg_text
    die Fundstelle als "VARIABLE=wert" fuer die Anzeige, stark sagt, ob die Marke dokumentiert oder gemessen
    ist (True) oder nur Quelltext-/Konventionsfund (False). (None, None, False), wenn nichts erkannt wurde -
    dann wird gefragt statt geraten.
    """
    env = os.environ if env is None else env
    for var, erwartet, werkzeug, beleg, _quelle in AGENT_MARKERS:
        wert = env.get(var)
        if not wert:
            continue
        if erwartet is not None and wert != erwartet:
            continue
        return werkzeug, f"{var}={wert}", beleg in ("gemessen", "doku")
    for var in AGENT_GENERIC_VARS:
        roh = (env.get(var) or "").strip()
        if not roh:
            continue
        praefix = roh.split("_", 1)[0].replace("-", " ").lower()
        if praefix in TOOL_CANON:
            return TOOL_CANON[praefix], f"{var}={roh}", False
    return None, None, False


# Nur Werkzeuge mit eigenen Dateien im Repo koennen entfernt werden; ChatGPT/Codex, Ollama und Cline
# haben keine (Cline liest AGENTS.md direkt).
TOOL_FILES = {
    "Copilot": [".github/copilot-instructions.md"],
    "Cursor": [".cursor"],
    "Aider": [".aider.conf.yml"],
    "Gemini CLI": ["GEMINI.md"],
    "Claude Code": [
        "CLAUDE.md",
        ".claude/agents",
        ".claude/skills",
        ".claude/settings.json",
        ".claude/settings.local.json.example",
        ".claude/maintenance",
    ],
}
REMOVABLE_TOOLS = list(TOOL_FILES.keys())

# Orchestrator-Modell (steuert "model" in .claude/settings.json) und Wartung (ein/aus).
ORCHESTRATOR_MODELLE = {"opus", "sonnet", "haiku", "inherit"}
# Steuert nur den Orchestrator (Checkliste "Aufgabe abschliessen"/Skill /act-commit), keine Datei -
# analog zu Code-Analyse/Code-Optimierung.
COMMIT_VERHALTEN_WERTE = {"automatisch", "fragen", "manuell"}

# Rein verhaltenssteuernde Schalter: Sie aendern keine Datei, sondern wie der Orchestrator arbeitet. Trotzdem
# gefuehrt und in applied_config gespeichert, damit sync-config.py eine Aenderung ueberhaupt meldet.
IDEEN_ABLAUF_WERTE = {"automatisch", "konzept", "direkt"}
TESTTIEFE_WERTE = {"alles", "e2e", "integration", "unit", "ohne"}
# Reihenfolge = Umfang, von "am meisten" nach "am wenigsten". Jede Stufe schliesst die folgenden ein.
TESTTIEFE_REIHE = ["alles", "e2e", "integration", "unit", "ohne"]
SCHREIBSTIL_WERTE = {"kurz", "normal", "ausfuehrlich"}
SCHREIBSTIL_ALIAS = {"ausführlich": "ausfuehrlich", "stichpunkte": "kurz", "stichpunktartig": "kurz"}

# Freiwillige Rueckmeldung an den Template-Autor (AGENTS.md, .claude/scripts/feedback.py). Zwei Schalter:
# WIE gesendet wird und WIE OFT. Default ist "aus" - ohne ausdrueckliche Entscheidung verlaesst nichts das
# Projekt, auch nicht versehentlich durch eine uebersehene Zeile.
FEEDBACK_WERTE = {"aus", "bestaetigen", "automatisch", "manuell"}
FEEDBACK_ALIAS = {"nein": "aus", "ja": "automatisch", "bestätigen": "bestaetigen", "fragen": "bestaetigen"}
FEEDBACK_TAKT_WERTE = {"manuell", "sofort", "stuendlich", "taeglich", "woechentlich", "automatisch", "adaptiv"}
FEEDBACK_TAKT_ALIAS = {"stündlich": "stuendlich", "täglich": "taeglich", "wöchentlich": "woechentlich"}
# Mindestabstand je Takt in Stunden - im Script durchgesetzt, nicht nur dokumentiert. "adaptiv" hat keinen
# festen Abstand: Dort rechnet feedback.py aus, wie oft am Projekt gearbeitet wird, und erinnert entsprechend
# (ein Entwickler, der einmal die Woche codet, soll nicht woechentlich gefragt werden).
FEEDBACK_TAKT_STUNDEN = {
    "manuell": None, "sofort": 0, "stuendlich": 1, "taeglich": 24, "woechentlich": 168, "automatisch": 1,
    "adaptiv": None,
}
# WAS gesammelt und gesendet werden darf - Mehrfachauswahl, Kommaliste. Die Registrierung (Datum, Weg,
# Ausfuellart, Template-Stand) und von Hand geschriebene Rueckmeldungen gehen immer mit; die drei Kennungen
# steuern nur, was der Assistent von sich aus dazustellt. Echte Dateien aus docs/ sind bewusst NICHT
# waehlbar (Entscheidung 2026-09-15): Das widerspraeche der Zusage "nie Dateien, nie Projektbezug".
FEEDBACK_UMFANG_WERTE = {"a", "b", "c"}
FEEDBACK_UMFANG_ALIAS = {
    "statistik": "a", "statistiken": "a",
    "regeln": "b", "struktur": "b",
    "werkzeuge": "c", "tools": "c",
    "alles": "a,b,c", "nichts": "",
}
DEFAULT_FEEDBACK_UMFANG = "a,b,c"
WARTUNG_WERTE = {"aus", "ein"}
DEFAULT_WARTUNGSAUFGABEN = "kurz=14, docs=30, deps=90"
# Ablageort der Wartungsberichte (.claude/maintenance/reports/YYYY-MM-DD.md) - "docs" legt zusaetzlich
# docs/maintenance/README.md an, siehe setup_docs_maintenance_reports.
WARTUNGSBERICHTE_WERTE = {"intern", "docs"}
# Nur fuer Weg 2 (/act-apply-template): soll nach dem Befuellen von docs/project/ zusaetzlich der bestehende
# Code geprueft und Verbesserungen vorgeschlagen werden? "fragen" = der Assistent fragt im Chat nach.
CODE_ANALYSE_WERTE = {"nein", "vorschlagen", "fragen"}
# Optionaler Politur-Agent nach jeder Umsetzungswelle: "aus" entfernt ihn, "ein"/"intensiv" behalten ihn
# (die Stufe steuert nur, wie der Orchestrator ihn beauftragt - siehe .claude/agents/optimizer.md).
# "streng" war der frühere Name von "intensiv" - bestehende Projekte duerfen ihn weiter verwenden
# (normalize_code_optimierung bildet ihn auf "intensiv" ab und weist einmal auf die Umbenennung hin).
CODE_OPTIMIERUNG_WERTE = {"aus", "ein", "intensiv"}
CODE_OPTIMIERUNG_ALIASE = {"streng": "intensiv"}
# Vorgefertigte Regelsaetze je Sprache/Framework (docs/project/coding_rules.d/). Beim Anlegen bleiben nur
# die in AI-CONFIG.md genannten liegen - der Rest kommt bei Bedarf per `guidelines.py --add` aus dem Template
# zurueck. Leere Angabe = keine (kein Ballast im Projekt).
GUIDELINES_DIR = "docs/project/coding_rules.d"
# Nur fuer Weg 2 (/act-apply-template): sollen vorhandene KI-Arbeitsordner/-Regeldateien auf die
# Template-Struktur migriert und zusammengefuehrt werden (siehe rename-lib.py)? "fragen" = der
# Assistent zeigt den Plan und fragt im Chat nach.
STRUKTUR_MIGRATION_WERTE = {"ja", "nein", "fragen"}
WARTUNGSAUFGABEN_EREIGNISGESTEUERT = {"0", "", "null", "none", "-"}


# ---------------------------------------------------------------------------
# AI-CONFIG.md parsen
# ---------------------------------------------------------------------------


def _strip_trailing_comment(value: str) -> str:
    """Schneidet an der ersten oeffnenden Klammer ab (Erklaerungskommentar, ggf. ueber Zeilenende hinaus
    unbalanciert). Bleibt danach nichts uebrig, ist der Wert nicht gesetzt (Nutzer hat die Vorlagenzeile
    unveraendert gelassen). Nur fuer das alte "Schluessel: Wert"-Format - in einer Tabellenzelle ist der
    gesamte Zellinhalt der Wert, auch wenn er Klammern enthaelt."""
    return value.split("(", 1)[0].strip()


_TABLE_SEPARATOR_CELL = re.compile(r"^[:\-]+$")


def _split_table_row(line: str):
    """Zerlegt eine Markdown-Tabellenzeile ('| a | b | c |') in ihre Zellen, oder None, wenn die Zeile keine
    Tabellenzeile ist (kein Rand-'|'). Trennt an nicht-escapten '|' - escapte '\\|' (typisch in Spalte 3
    "automatisch \\| fragen \\| manuell") bleiben Teil der Zelle. Kein Verlass auf eine feste Spaltenzahl -
    nur die ersten beiden Zellen werden ausgewertet."""
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None
    cells = [c.strip() for c in re.split(r"(?<!\\)\|", stripped)]
    if cells and cells[0] == "":
        cells = cells[1:]
    if cells and cells[-1] == "":
        cells = cells[:-1]
    return cells or None


def _clean_table_key(raw: str) -> str:
    """Spalte 1 einer Tabellenzeile: Backticks/Sternchen (Markdown-Hervorhebung) entfernen, trimmen."""
    return raw.replace("`", "").replace("*", "").strip()


def parse_config(text: str) -> dict:
    """Liest sowohl das neue Tabellenformat (Schluessel/Wert je Tabellenzeile, Spalten 3+ sind Erklaerung)
    als auch das aeltere "Schluessel: Wert (Kommentar)"-Format - beide duerfen sogar in derselben Datei
    stehen. Bei doppeltem Schluessel gewinnt der zuletzt in der Datei gefundene Wert (Zeilen werden der Reihe
    nach verarbeitet, spaetere ueberschreiben fruehere)."""
    cfg = {v: None for v in KEY_MAP.values()}
    cfg["sections"] = {name: "" for name in SECTION_NAMES}
    cfg["gekuerzt"] = []

    lines = text.splitlines() if text else []
    current_section = None
    section_buf = []

    def flush_section():
        if current_section is not None:
            cfg["sections"][current_section] = "\n".join(section_buf).strip()

    for line in lines:
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            flush_section()
            name = heading.group(1).strip()
            current_section = name if name in SECTION_NAMES else None
            section_buf = []
            continue
        if current_section is not None:
            section_buf.append(line)
            continue

        cells = _split_table_row(line)
        if cells is not None:
            if len(cells) < 2:
                continue
            key_cell, val_cell = _clean_table_key(cells[0]), cells[1].strip()
            if key_cell.lower() == "schlüssel" or _TABLE_SEPARATOR_CELL.match(cells[0].strip()):
                continue  # Kopf- bzw. Trennzeile der Tabelle
            key = KEY_LOOKUP.get(key_cell.lower())
            if key:
                cfg[key] = val_cell if val_cell else None
            continue

        # Altes Format: AI-CONFIG.md fuehrte die Schluessel-Liste eingerueckt (4 Leerzeichen) - fuehrenden
        # Leerraum daher tolerieren, sonst wird keine einzige Zeile erkannt.
        m = re.match(r"^[ \t]*([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9\- ]*):\s?(.*)$", line)
        if m and KEY_LOOKUP.get(m.group(1).strip().lower()):
            raw_key = m.group(1).strip()
            key = KEY_LOOKUP[raw_key.lower()]
            raw_val = m.group(2).strip()
            val = _strip_trailing_comment(raw_val)
            if val and val != raw_val:
                cfg["gekuerzt"].append((raw_key, raw_val, val))
            cfg[key] = val if val else None
    flush_section()

    # KI-Werkzeuge -> Liste kanonischer Namen
    tools = []
    unbekannt = []
    if cfg.get("ki_werkzeuge"):
        for part in cfg["ki_werkzeuge"].split(","):
            raw = part.strip()
            if not raw:
                continue
            if raw.lower() in TOOL_CANON:
                tools.append(TOOL_CANON[raw.lower()])
            else:
                unbekannt.append(raw)
    cfg["ki_werkzeuge_liste"] = tools
    cfg["ki_werkzeuge_unbekannt"] = unbekannt

    return cfg


def load_config(root: Path) -> dict:
    path = root / CONFIG_REL
    text = ""
    if path.exists():
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError:
            text = ""
    return parse_config(text)


# ---------------------------------------------------------------------------
# Backlog B37 (Backlog der Template-Pflege): neue Schluessel aus der Template-Fassung von AI-CONFIG.md, die in
# der (per keep_local nie gemergten) Projektfassung sonst still verloren gehen. Reine Textoperation auf den
# Tabellen-Zeilen - unabhaengig von KEY_MAP/parse_config, damit auch ein Schluessel erkannt wird, den DIESE
# (ggf. aeltere) config-lib.py noch gar nicht kennt. Funktioniert mit UND ohne die Erlaeuterungsabsaetze
# zwischen den Tabellen (Backlog B41, geplante Auslagerung in eine Hilfedatei) - Prosazeilen zwischen zwei
# Tabellen werden hier wie in parse_config() einfach uebersprungen, keine Tabellenzeile beginnt mit "|".
# ---------------------------------------------------------------------------


def _parse_table_sections(text: str) -> dict:
    """Zerlegt eine Markdown-Datei mit '## Ueberschrift' + Tabelle (Format wie AI-CONFIG.md: Spalte 1 =
    Schluessel) in ihre Tabellen-Abschnitte. Gibt {ueberschrift: {"keys": {schluessel_lower: {"key":
    schluessel, "cells": [zelle, ...]}}, "order": [schluessel_lower, ...], "insert_after": zeilenindex}}
    zurueck - "insert_after" ist der 0-basierte Index der letzten Datenzeile dieser Tabelle in 'lines'
    (text.splitlines()), zum Einfuegen einer neuen Zeile direkt danach. Ueberschriften ohne Tabelle darunter
    (z.B. die Freitextabschnitte 'Ziel', 'Nutzer' ...) tauchen im Ergebnis nicht auf. Zeilen innerhalb eines
    Codeblocks (```...```) zaehlen nie als Tabellenzeile oder Ueberschrift, auch wenn sie wie eine aussehen
    (Review-Befund F5b) - eine Beispielzeile in einer Anleitung soll keinen Schluessel vortaeuschen."""
    sections = {}
    heading = None
    in_code_block = False
    for i, line in enumerate(text.splitlines()):
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            continue
        if in_code_block:
            continue
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            heading = m.group(1).strip()
            continue
        cells = _split_table_row(line)
        if cells is None or heading is None or len(cells) < 2:
            continue
        key_raw = _clean_table_key(cells[0])
        if key_raw.lower() == "schlüssel" or _TABLE_SEPARATOR_CELL.match(cells[0].strip()):
            continue  # Kopf- bzw. Trennzeile der Tabelle
        entry = sections.setdefault(heading, {"keys": {}, "order": [], "insert_after": i})
        key_lower = key_raw.lower()
        if key_lower not in entry["keys"]:
            entry["order"].append(key_lower)
        entry["keys"][key_lower] = {"key": key_raw, "cells": cells}
        entry["insert_after"] = i
    return sections


def missing_ai_config_rows(project_text: str, template_text: str):
    """Vergleicht die Tabellen-Schluessel aus 'project_text' (Projektfassung von AI-CONFIG.md) gegen
    'template_text' (Template-Fassung, z.B. aus fetch_template_ai_config_text) - ueber die GANZE Datei,
    ohne Gross-/Kleinschreibung, nicht nur innerhalb derselben Ueberschrift (Review-Befund F2: sonst wird
    ein Schluessel, den das Template in eine andere Tabelle verschoben oder dessen Ueberschrift es
    umbenannt hat, ein zweites Mal mit leerem Wert eingefuegt - parse_config() nimmt bei doppeltem
    Schluessel den zuletzt gefundenen Wert, der vorhandene Nutzerwert waere dann weg). Gibt (missing,
    hinweise_manuell) zurueck:
      - missing: Liste von {"tabelle": Ueberschrift, "schluessel": Anzeigename, "zeile": fertige Markdown-
        Tabellenzeile mit geleerter Wert-Spalte (Spalte 2) - leer heisst Standard, siehe AI-CONFIG.md-Kopf},
        NUR fuer Schluessel, die im PROJEKT unter KEINER Ueberschrift vorkommen und deren Ziel-Tabelle im
        Projekt existiert (sonst kein sicherer Einfuegepunkt).
      - hinweise_manuell: Freitext-Hinweise fuer Faelle, die NICHT automatisch behandelt werden: eine ganze
        Tabelle fehlt im Projekt, oder ein Schluessel steht im Projekt unter einer ANDEREN Ueberschrift als
        im Template (vermutlich verschoben/umbenannt) - wird nur gemeldet, nicht verschoben, der
        vorhandene Wert bleibt unangetastet."""
    proj = _parse_table_sections(project_text)
    tpl = _parse_table_sections(template_text)

    # Schluessel -> Ueberschrift, ueber die GESAMTE Projektdatei (nicht nur je Tabelle), ohne Gross-/
    # Kleinschreibung - so faellt ein verschobener/umbenannter Schluessel als "verschoben" auf statt als
    # "fehlt" missverstanden zu werden. Kommt ein Schluessel im Projekt (fehlerhaft) mehrfach vor, gewinnt
    # die zuerst gefundene Tabelle (setdefault).
    proj_key_heading = {}
    for heading, section in proj.items():
        for key_lower in section["order"]:
            proj_key_heading.setdefault(key_lower, heading)

    missing = []
    hinweise_manuell = []
    for heading, tpl_section in tpl.items():
        proj_section = proj.get(heading)
        if proj_section is None:
            hinweise_manuell.append(
                f"Tabelle '{heading}' fehlt im Projekt - Schluessel darin nicht automatisch einfuegbar: "
                + ", ".join(tpl_section["keys"][k]["key"] for k in tpl_section["order"])
            )
        for key_lower in tpl_section["order"]:
            eintrag = tpl_section["keys"][key_lower]
            proj_heading = proj_key_heading.get(key_lower)
            if proj_heading is None:
                if proj_section is None:
                    continue  # schon oben als fehlende Tabelle gemeldet, kein Einfuegepunkt
                cells = list(eintrag["cells"])
                if len(cells) > 1:
                    cells[1] = ""  # Wert-Spalte leeren = Standard (siehe AI-CONFIG.md-Kopf)
                missing.append({
                    "tabelle": heading, "schluessel": eintrag["key"],
                    "zeile": "| " + " | ".join(cells) + " |",
                })
            elif proj_heading != heading:
                hinweise_manuell.append(
                    f"Schluessel '{eintrag['key']}' steht im Projekt unter '{proj_heading}', im Template "
                    f"unter '{heading}' - vermutlich verschoben, bitte von Hand pruefen (Wert bleibt "
                    "erhalten, wird nicht automatisch verschoben)."
                )
            # sonst: derselbe Schluessel steht im Projekt schon unter derselben Tabelle - nichts zu tun
    return missing, hinweise_manuell


def insert_missing_ai_config_rows(text: str, missing: list) -> str:
    """Fuegt die von missing_ai_config_rows gelieferten Zeilen in 'text' ein - je Tabelle direkt nach deren
    letzter vorhandener Datenzeile (_parse_table_sections § insert_after). Mehrere neue Zeilen derselben
    Tabelle landen in der Reihenfolge von 'missing' direkt hintereinander. Tabellen ohne Einfuegepunkt (im
    Text nicht gefunden) werden uebersprungen, nicht erzwungen. Gibt den neuen Text zurueck (Zeilenenden
    '\\n', wie beim Rest dieses Moduls - Newline-Erhalt beim Schreiben ist Sache des Aufrufers, siehe
    files-lib.py _read_text_preserve_newline/_write_text_preserve_newline)."""
    if not missing:
        return text
    by_table = {}
    for m in missing:
        by_table.setdefault(m["tabelle"], []).append(m["zeile"])
    sections = _parse_table_sections(text)
    einfuegepunkte = [
        (sections[heading]["insert_after"], zeilen) for heading, zeilen in by_table.items() if heading in sections
    ]
    lines = text.splitlines()
    trailing_newline = text.endswith("\n")
    for idx, zeilen in sorted(einfuegepunkte, key=lambda t: t[0], reverse=True):
        for zeile in reversed(zeilen):
            lines.insert(idx + 1, zeile)
    return "\n".join(lines) + ("\n" if trailing_newline else "")


def _load_template_update_module():
    """Laedt update-template.py als Modul (gleicher Ordner, per importlib - Bindestrich im Dateinamen
    verbietet ein normales `import`). Gleiches Muster wie in files-lib.py/sync-config.py; hier dupliziert
    (kein Ring config-lib.py <-> update-template.py - update-template.py laedt umgekehrt nichts aus
    config-lib.py)."""
    tu_path = Path(__file__).resolve().parent / "update-template.py"
    spec = importlib.util.spec_from_file_location("_config_lib_tu", tu_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def fetch_template_ai_config_text(root: Path, tu=None, ref: str = None, fetch: bool = True):
    """Holt AI-CONFIG.md aus dem Template-Remote (`git show <ref>:AI-CONFIG.md`). `tu` ist das schon
    geladene update-template.py-Modul (z.B. von sync-config.py); fehlt es, wird es selbst nachgeladen
    (_load_template_update_module) - so ist diese Funktion auch von update-template.py selbst per importlib
    aufrufbar (config-lib.py laden, siehe files-lib.py fuer dasselbe Muster in die andere Richtung), ohne
    dass update-template.py dafuer geaendert werden muesste.
    `ref`: schon aufgeloeste Referenz (z.B. von sync-config.py:_get_ref/resolve_template_ref, das denselben
    Ref fuer mehrere Diffs in einem --apply-Lauf teilt) - wird dann UNVERAENDERT benutzt, kein erneutes
    compare_ref/git fetch (Review-Befund F3: vermeidet doppeltes Fetchen in einem Lauf, der auch andere
    Diffs bedient). Ohne 'ref' (Default) wird sie wie zuvor selbst ueber `.claude/template.json` §
    template_remote/template_branch aufgeloest (siehe update-template.py:compare_ref).
    `fetch`: nur wirksam, wenn 'ref' NICHT gegeben ist. True (Default) fetcht bei Bedarf einmal - fuer
    --apply. False ueberspringt den Netzwerkzugriff komplett und vergleicht nur gegen den lokal schon
    bekannten Remote-Stand (refs/remotes/<remote>/<branch> aus einem frueheren Fetch) - fuer --check/den
    SessionStart-Hook (Review-Befund F3: dort darf kein Netzwerkzugriff blockieren/Meldungen verschlucken).
    Ohne lokalen Stand schlaegt danach nur 'git show' fehl (kein Absturz, kein Haengen).
    Rueckgabe (text_oder_None, hinweis_oder_None, fehler_oder_None):
      - Kein Template-Remote/keine aufloesbare Referenz (nur wenn 'ref' nicht gegeben war) -> (None, None,
        None). Laut Auftrag (Backlog B37) ist das der STILLE Fallback ohne Remote, kein Fehler.
      - 'git show' schlaegt fehl (Datei im Ref nicht gefunden/Ref lokal nicht vorhanden) -> (None,
        hinweis_oder_None, fehlertext).
      - Erfolg -> (text, hinweis_oder_None, None). 'hinweis' ist zusaetzlich und informativ (z.B.
        fehlgeschlagener 'git fetch' - dann wird mit dem lokalen Stand weitergearbeitet)."""
    if tu is None:
        tu = _load_template_update_module()
    hinweis = None
    if ref is None:
        tpl_cfg, _path = tu.load_template_json(root)
        if tpl_cfg.get("is_template"):
            return None, None, None  # Template-Checkout selbst hat nichts, wogegen verglichen werden koennte
        ref, fetch_noetig = tu.compare_ref(root, tpl_cfg)
        if ref is None:
            return None, None, None  # kein Remote/Branch - stiller Fallback, siehe Docstring
        if fetch and fetch_noetig:
            remote = tpl_cfg.get("template_remote") or "template"
            try:
                res_fetch = tu.run_git(root, ["fetch", remote], timeout=20)
            except Exception as e:  # noqa: BLE001 - Netzwerk-/Timeoutfehler duerfen nicht durchschlagen
                res_fetch = None
                hinweis = f"'git fetch {remote}' fehlgeschlagen ({e}) - arbeite mit vorhandenem Stand weiter."
            if res_fetch is not None and res_fetch.returncode != 0:
                hinweis = f"'git fetch {remote}' fehlgeschlagen (offline?) - arbeite mit vorhandenem Stand weiter."
    res = tu.run_git(root, ["show", f"{ref}:{CONFIG_REL}"])
    if res.returncode != 0:
        return None, hinweis, f"{CONFIG_REL} in '{ref}' nicht gefunden."
    return res.stdout, hinweis, None


def ai_config_missing_keys(root: Path, tu=None, ref: str = None, fetch: bool = True):
    """Kompletter Ablauf fuer Backlog B37: Template-Fassung von AI-CONFIG.md holen (siehe
    fetch_template_ai_config_text - `ref`/`fetch` werden unveraendert durchgereicht, siehe dort) und ihre
    Tabellen-Schluessel gegen die Projektfassung vergleichen (siehe missing_ai_config_rows). `tu` wie dort -
    optional, wird sonst selbst nachgeladen. Alter Aufruf `ai_config_missing_keys(root, tu)` verhaelt sich
    unveraendert (ref=None, fetch=True = wie zuvor).
    Rueckgabe (missing, hinweise_manuell, hinweis, fehler) - 'missing'/'hinweise_manuell' wie
    missing_ai_config_rows(), leer bei fehlendem Remote (stiller Fallback) oder Lesefehler. Aufrufer:
    sync-config.py (--check meldet 'missing'/'hinweise_manuell', --apply fuegt 'missing' per
    insert_missing_ai_config_rows ein, schreibt AI-CONFIG.md zurueck und meldet 'hinweise_manuell' nur)."""
    template_text, hinweis, fehler = fetch_template_ai_config_text(root, tu, ref=ref, fetch=fetch)
    if template_text is None:
        return [], [], hinweis, fehler
    project_path = root / CONFIG_REL
    try:
        project_text = project_path.read_text(encoding="utf-8-sig")
    except OSError:
        project_text = ""
    missing, hinweise_manuell = missing_ai_config_rows(project_text, template_text)
    return missing, hinweise_manuell, hinweis, fehler


# ---------------------------------------------------------------------------
# Werte/Platzhalter
# ---------------------------------------------------------------------------


def compute_values(cfg: dict) -> dict:
    today = time.strftime("%Y-%m-%d")
    return {
        "PROJEKTNAME": cfg.get("projektname") or "MyApp",
        "AUFTRAGGEBER": cfg.get("auftraggeber") or "Entwickler",
        "ORCHESTRATOR": cfg.get("orchestrator") or default_orchestrator(cfg)[0],
        "STACK": cfg.get("stack"),
        "DATUM": today,
        "INSTALL_BEFEHL": cfg.get("install_befehl"),
        "DEV_START_BEFEHL": cfg.get("dev_start_befehl"),
        "LINT_BEFEHL": cfg.get("lint_befehl"),
        "TYPECHECK_BEFEHL": cfg.get("typecheck_befehl"),
        "TEST_BEFEHL": cfg.get("test_befehl"),
        "E2E_BEFEHL": cfg.get("e2e_befehl"),
    }


def logging_settings(cfg: dict):
    return (cfg.get("logging") or "aus", cfg.get("logging_tiefe") or "INFO")


def unbekannte_werkzeuge(cfg: dict) -> list:
    return list(cfg.get("ki_werkzeuge_unbekannt") or [])


def normalize_orchestrator_modell(cfg: dict):
    """Gibt (modell, unbekannter_rohwert) zurueck - genau einer der beiden ist None. Default 'opus'."""
    raw = cfg.get("orchestrator_modell")
    if not raw:
        return "opus", None
    val = raw.strip().lower()
    if val not in ORCHESTRATOR_MODELLE:
        return None, raw
    return val, None


def normalize_commit_verhalten(cfg: dict):
    """Gibt (commit_verhalten, unbekannter_rohwert) zurueck - genau einer der beiden ist None. Default
    'automatisch'. Der Wert aendert keine Datei, sondern nur, wie der Orchestrator mit der Checkliste "Aufgabe
    abschliessen" (Skill /act-commit) umgeht."""
    raw = cfg.get("commit_verhalten")
    if not raw:
        return "automatisch", None
    val = raw.strip().lower()
    if val not in COMMIT_VERHALTEN_WERTE:
        return None, raw
    return val, None


def _normalize_einfach(cfg: dict, key: str, erlaubt: set, default: str, alias: dict = None):
    """Gemeinsame Normalisierung der reinen Verhaltensschalter. Gibt (wert, unbekannter_rohwert) zurueck -
    genau einer der beiden ist None."""
    raw = cfg.get(key)
    if not raw:
        return default, None
    val = raw.strip().lower()
    if alias:
        val = alias.get(val, val)
    if val not in erlaubt:
        return None, raw
    return val, None


def normalize_ideen_ablauf(cfg: dict):
    """Wie mit einer Idee/einem Aenderungswunsch umgegangen wird (Checkliste "Idee oder Aenderungswunsch
    aufnehmen"). Default "automatisch"."""
    return _normalize_einfach(cfg, "ideen_ablauf", IDEEN_ABLAUF_WERTE, "automatisch")


def normalize_testtiefe(cfg: dict):
    """Wie weit getestet wird. Default "alles"."""
    return _normalize_einfach(cfg, "testtiefe", TESTTIEFE_WERTE, "alles")


def normalize_feedback(cfg: dict):
    """Wie die freiwillige Rueckmeldung gesendet wird. Default "aus"."""
    return _normalize_einfach(cfg, "feedback", FEEDBACK_WERTE, "aus", FEEDBACK_ALIAS)


def normalize_feedback_takt(cfg: dict):
    """Wie oft gesendet wird. Default "woechentlich" - wirkt nur, wenn Feedback nicht "aus"/"manuell" ist."""
    return _normalize_einfach(cfg, "feedback_takt", FEEDBACK_TAKT_WERTE, "woechentlich", FEEDBACK_TAKT_ALIAS)


def normalize_feedback_umfang(cfg: dict):
    """Was der Assistent von sich aus sammeln darf - Kommaliste aus a/b/c (Mehrfachauswahl).
    Rueckgabe wie die uebrigen Normalisierer: (wert, unbekannt_oder_None). `wert` ist die sortierte,
    entdoppelte Kommaliste; leer bedeutet "nur Registrierung und von Hand geschriebenes Feedback".
    Unbekannte Kennungen werden NICHT still verworfen, sondern gemeldet - sonst sammelt das Projekt
    stillschweigend weniger, als {{AUFTRAGGEBER}} eingetragen hat."""
    roh = (cfg.get("feedback_umfang") or "").strip()
    if not roh:
        roh = DEFAULT_FEEDBACK_UMFANG
    teile, unbekannt = [], []
    for stueck in roh.split(","):
        wert = stueck.strip().lower()
        if not wert:
            continue
        wert = FEEDBACK_UMFANG_ALIAS.get(wert, wert)
        for einzeln in wert.split(","):  # Alias "alles" loest sich zu mehreren Kennungen auf
            einzeln = einzeln.strip()
            if not einzeln:
                continue
            if einzeln in FEEDBACK_UMFANG_WERTE:
                teile.append(einzeln)
            else:
                unbekannt.append(stueck.strip())
    return ",".join(sorted(dict.fromkeys(teile))), (", ".join(dict.fromkeys(unbekannt)) or None)


def normalize_schreibstil(cfg: dict):
    """Wie ausfuehrlich Fragen, Aufgaben und Antworten formuliert werden. Default "kurz"."""
    return _normalize_einfach(cfg, "schreibstil", SCHREIBSTIL_WERTE, "kurz", SCHREIBSTIL_ALIAS)


IDEEN_ABLAUF_TEXT = {
    "automatisch": "automatisch - Konzept bei allem, was eine Entscheidung braucht; Kleinigkeiten direkt "
                   "als Aufgabe, die Abkuerzung wird ausgesprochen (Default)",
    "konzept": "konzept - immer erst Konzept, Optionen und Entscheidung, auch bei Kleinigkeiten",
    "direkt": "direkt - kein Konzept, jeder Wunsch wird sofort Aufgabe oder Backlog-Punkt",
}

TESTTIEFE_TEXT = {
    "alles": "alles - Unit, Integration und E2E (Default)",
    "e2e": "e2e - Unit, Integration und E2E fuer die Hauptwege, ohne Randfaelle im Browser",
    "integration": "integration - Unit- und Integrationstests, keine E2E",
    "unit": "unit - nur Unit-Tests",
    "ohne": "ohne - keine Tests; 'fertig' braucht dann einen anderen Beleg (Aufruf von aussen, Screenshot)",
}

SCHREIBSTIL_TEXT = {
    "kurz": "kurz - auf den Punkt, stichpunktartig (Default)",
    "normal": "normal - ein Satz Begruendung, wo er traegt",
    "ausfuehrlich": "ausfuehrlich - Fragen, Texte und Aufgaben vollstaendig und nachvollziehbar begruendet",
}

FEEDBACK_TEXT = {
    "aus": "aus - es wird nichts an den Template-Autor gesendet (Default)",
    "bestaetigen": "bestaetigen - vor jedem Versand wird die Nutzlast gezeigt und gefragt",
    "automatisch": "automatisch - der Assistent sendet ohne Rueckfrage, protokolliert in docs/ai/template-feedback/",
    "manuell": "manuell - nur auf Aufruf von /act-feedback, sonst nie",
}

FEEDBACK_TAKT_TEXT = {
    "manuell": "manuell - kein automatischer Versand",
    "sofort": "sofort - nach jedem brauchbaren Vorschlag",
    "stuendlich": "stuendlich - hoechstens einmal je Stunde",
    "taeglich": "taeglich - hoechstens einmal am Tag",
    "woechentlich": "woechentlich - hoechstens einmal je Woche (Default)",
    "automatisch": "automatisch - der Assistent entscheidet, fruehestens eine Stunde nach der letzten Sendung",
    "adaptiv": "adaptiv - richtet sich danach, wie oft am Projekt gearbeitet wird (Vorschlag)",
}

# Was der Assistent von sich aus sammeln darf. Registrierung und von Hand geschriebenes Feedback gehen immer
# mit - diese Kennungen steuern nur das, was er selbst zusammentraegt.
FEEDBACK_UMFANG_TEXT = {
    "a": "a - Kennzahlen aus git log und Dateisystem (Weg, Datum, Commit-Haeufigkeit, Repo-Groesse)",
    "b": "b - Aenderungen an den KI-Regeln und an der Struktur der Doku, als Beschreibung",
    "c": "c - Werkzeug-Nutzung (MCP-Server, Skills, Agenten, Scripte)",
}

COMMIT_VERHALTEN_TEXT = {
    "automatisch": "automatisch - committet abgenommene Arbeit selbst (Default)",
    "fragen": "fragen - schlaegt den Commit vor und wartet auf Zustimmung",
    "manuell": "manuell - nur auf ausdrueckliche Anweisung",
}


def normalize_wartung(cfg: dict):
    """Gibt (wartung, unbekannter_rohwert) zurueck - genau einer der beiden ist None. Default 'aus'."""
    raw = cfg.get("wartung")
    if not raw:
        return "aus", None
    val = raw.strip().lower()
    if val not in WARTUNG_WERTE:
        return None, raw
    return val, None


def normalize_wartungsberichte(cfg: dict):
    """Gibt (wartungsberichte, unbekannter_rohwert) zurueck - genau einer der beiden ist None. Default
    'docs' (docs/maintenance/, versioniert, im Doku-Index sichtbar)."""
    raw = cfg.get("wartungsberichte")
    if not raw:
        return "docs", None
    val = raw.strip().lower()
    if val not in WARTUNGSBERICHTE_WERTE:
        return None, raw
    return val, None


WARTUNGSBERICHTE_TEXT = {
    "intern": "intern - .claude/maintenance/reports/ (gitignored)",
    "docs": "docs - docs/maintenance/ (versioniert, im Doku-Index sichtbar, Default)",
}


def normalize_code_analyse(cfg: dict):
    """Gibt (code_analyse, unbekannter_rohwert) zurueck - genau einer der beiden ist None. Default 'fragen'.
    Der Wert steuert keinen Dateieingriff, sondern nur den Ablauf des Skills /act-apply-template (Weg 2)."""
    raw = cfg.get("code_analyse")
    if not raw:
        return "fragen", None
    val = raw.strip().lower()
    if val not in CODE_ANALYSE_WERTE:
        return None, raw
    return val, None


def available_guidelines(root: Path):
    """Kennungen der im Repo vorhandenen Regelsatz-Bausteine (Dateiname ohne .md, ohne README)."""
    d = root / GUIDELINES_DIR
    if not d.is_dir():
        return []
    return sorted(
        f.stem.lower() for f in d.glob("*.md") if f.is_file() and f.stem.lower() != "readme"
    )


def parse_coding_guidelines(cfg: dict, root: Path):
    """Gibt (gewaehlt: [kennung], unbekannt: [rohwert]) zurueck. Leere Angabe -> ([], [])."""
    raw = (cfg.get("coding_guidelines") or "").strip()
    if not raw:
        return [], []
    vorhanden = set(available_guidelines(root))
    gewaehlt, unbekannt = [], []
    for teil in (t.strip().lower() for t in raw.split(",")):
        if not teil:
            continue
        if teil in vorhanden:
            if teil not in gewaehlt:
                gewaehlt.append(teil)
        else:
            unbekannt.append(teil)
    return gewaehlt, unbekannt


def normalize_code_optimierung(cfg: dict):
    """Gibt (code_optimierung, unbekannter_rohwert, alias_hinweis) zurueck - von den ersten beiden ist genau
    einer None. Default 'aus'. Der frühere Wert 'streng' bleibt als Eingabe gueltig, wird auf 'intensiv'
    abgebildet, alias_hinweis nennt dann die Umbenennung (sonst None)."""
    raw = cfg.get("code_optimierung")
    if not raw:
        return "aus", None, None
    val = raw.strip().lower()
    if val in CODE_OPTIMIERUNG_ALIASE:
        neu = CODE_OPTIMIERUNG_ALIASE[val]
        return neu, None, f"Code-Optimierung: \"{val}\" heisst jetzt \"{neu}\" - bitte in AI-CONFIG.md nachziehen."
    if val not in CODE_OPTIMIERUNG_WERTE:
        return None, raw, None
    return val, None, None


CODE_OPTIMIERUNG_TEXT = {
    "aus": "aus - Agent optimizer wird entfernt",
    "ein": "ein - eine Politur-Runde je Umsetzungswelle (kuerzer, lesbarer)",
    "intensiv": "intensiv - bis zu zwei Runden, zusaetzlich Geschwindigkeit und Speicher",
}


CODE_ANALYSE_TEXT = {
    "nein": "nein - nur docs/project/ aus dem Bestand befuellen",
    "vorschlagen": "vorschlagen - danach Bestand pruefen, Verbesserungen nach docs/ai/backlog.md",
    "fragen": "fragen - nach dem Befuellen von docs/project/ im Chat nachfragen (Default)",
}


def normalize_struktur_migration(cfg: dict):
    """Gibt (struktur_migration, unbekannter_rohwert) zurueck - genau einer der beiden ist None. Default
    'fragen'. Der Wert aendert selbst keine Datei, sondern steuert nur den Ablauf des Skills
    /act-apply-template (Weg 2, migrate-project.py)."""
    raw = cfg.get("struktur_migration")
    if not raw:
        return "fragen", None
    val = raw.strip().lower()
    if val not in STRUKTUR_MIGRATION_WERTE:
        return None, raw
    return val, None


STRUKTUR_MIGRATION_TEXT = {
    "ja": "ja - KI-Arbeitsordner/-Regeldateien auf Template-Struktur migrieren und zusammenfuehren",
    "nein": "nein - nur fehlende Dateien ergaenzen, Vorhandenes unangetastet lassen",
    "fragen": "fragen - Plan zeigen (migrate-project.py --plan) und im Chat nachfragen (Default)",
}


def parse_wartungsaufgaben(raw: str):
    """Format 'name=tage, name=tage'. tage: Zahl >= 0, oder 0/leer/'null'/'-' = ereignisgesteuert (None).
    Gibt (dict name->intervall_tage_oder_None, liste_ungueltiger_eintraege) zurueck."""
    result = {}
    errors = []
    for pair in (p.strip() for p in raw.split(",")):
        if not pair:
            continue
        if "=" not in pair:
            errors.append(pair)
            continue
        name, val = (part.strip() for part in pair.split("=", 1))
        if not name:
            errors.append(pair)
            continue
        if val.lower() in WARTUNGSAUFGABEN_EREIGNISGESTEUERT:
            result[name] = None
            continue
        try:
            intervall = int(val)
        except ValueError:
            errors.append(pair)
            continue
        if intervall < 0:
            errors.append(pair)
            continue
        result[name] = intervall if intervall > 0 else None
    return result, errors


def tools_to_remove(cfg: dict):
    keep = set(cfg.get("ki_werkzeuge_liste") or [])
    if not keep:
        return []  # leer = alle behalten, nichts entfernen
    return [t for t in REMOVABLE_TOOLS if t not in keep]


def build_applied_config(
    values: dict, orch_modell: str, logging_val: str, logging_tiefe: str, wartung_val: str,
    wartungsaufgaben: dict, wartungsberichte: str, code_opt: str, guidelines_gewaehlt, entfernte_tools,
    commit_verhalten: str = None, ideen_ablauf: str = None,
    testtiefe: str = None, schreibstil: str = None, feedback: str = None,
    feedback_takt: str = None, feedback_umfang: str = None,
) -> dict:
    """Schnappschuss der Betrieb/Einrichtung-Schluessel, wie sie soeben umgesetzt wurden - Vergleichsgrundlage
    fuer sync-config.py (dort per importlib geladen statt hier verdoppelt). Die meisten Schluessel haben eine
    Datei-Wirkung (siehe sync-config.py compute_diffs); Commit-Verhalten hat keine (reines Verhalten/Hinweis),
    wird aber trotzdem gefuehrt, damit eine Aenderung ueberhaupt gemeldet wird - sonst faellt sie beim Abgleich
    durchs Raster (siehe Befund zu "Stack" unten). Bewusst NICHT gefuehrt: "Globale
    Ablage" (eigener, direkt aus AI-CONFIG.md gelesener Schalter von install-global.py, kein KEY_MAP-Eintrag,
    keine Wiederholungssemantik), "Code-Analyse"/"Struktur-Migration"/"Alter Orchestrator-Name" (einmalige
    Weg-2-Bootstrap-Werte fuer /act-apply-template, nach dem einmaligen Lauf ohne erneute Wirkung - siehe
    sync-config.py Kopfkommentar). Bei KI-Werkzeuge wird bewusst die RESULTIERENDE Entfernliste gespeichert
    (nicht die Roh-Kommaliste aus AI-CONFIG.md) - "leer = alle behalten" waere sonst nicht von "alle explizit
    genannt" zu unterscheiden."""
    return {
        "Projektname": values.get("PROJEKTNAME"),
        "Auftraggeber": values.get("AUFTRAGGEBER"),
        "Orchestrator": values.get("ORCHESTRATOR"),
        "Stack": values.get("STACK"),
        "KI-Werkzeuge-entfernt": sorted(entfernte_tools or []),
        "Coding-Guidelines": sorted(guidelines_gewaehlt or []),
        "Install-Befehl": values.get("INSTALL_BEFEHL"),
        "Dev-Start-Befehl": values.get("DEV_START_BEFEHL"),
        "Lint-Befehl": values.get("LINT_BEFEHL"),
        "Typecheck-Befehl": values.get("TYPECHECK_BEFEHL"),
        "Test-Befehl": values.get("TEST_BEFEHL"),
        "E2E-Befehl": values.get("E2E_BEFEHL"),
        "Orchestrator-Modell": orch_modell,
        "Commit-Verhalten": commit_verhalten,
        "Ideen-Ablauf": ideen_ablauf,
        "Testtiefe": testtiefe,
        "Schreibstil": schreibstil,
        "Feedback": feedback,
        "Feedback-Takt": feedback_takt,
        "Feedback-Umfang": feedback_umfang,
        "Logging": logging_val,
        "Logging-Tiefe": logging_tiefe,
        "Wartung": wartung_val,
        "Wartungsaufgaben": wartungsaufgaben if wartung_val == "ein" else {},
        "Wartungsberichte": wartungsberichte,
        "Code-Optimierung": code_opt,
    }


# ---------------------------------------------------------------------------
# Datei-Sammlung fuers projektweite Ersetzen (Platzhalter, Rufname, Befehls-Werte) - Backlog B22
# ---------------------------------------------------------------------------
#
# Gemeinsame Sammelstelle fuer files-lib.py (_iter_text_files, Platzhalter-/Befehls-Ersetzung) und
# rename-lib.py (_iter_text_files_for_rename, Rufname-Ersetzung) - vorher hatte nur rename-lib.py eine
# Ausschlussliste (RENAME_SKIP_DIR_NAMES), files-lib.py keine. Dadurch lief eine Befehls-Ersetzung (z.B.
# Test-Befehl "npm test" -> ein neuer Wert, per sync-config.py --apply) auch durch node_modules/ - Beleg aus
# einem abgeleiteten Projekt: Treffer in node_modules/@typescript-eslint/.../inferSingleRun.js und
# node_modules/baseline-browser-mapping/package.json (dort kommt "npm test" o.ae. rein zufaellig als
# Code-/Script-Literal vor).

# Bekannte Abhaengigkeits-/Build-Ordner, die nie absichtlich einen gesuchten Platzhalter/Rufnamen/
# Befehls-Wert enthalten - ein Treffer dort ist immer ein Zufallstreffer in generiertem/fremdem Code. Union
# aus der bisherigen RENAME_SKIP_DIR_NAMES (rename-lib.py) und der fuer B22 vorgegebenen Liste, damit die
# schon bestehende Rufname-Ersetzung keinen Schutz verliert.
EXCLUDE_DIR_NAMES_REPLACE = {
    ".git", "node_modules", ".venv", "venv", "dist", "build", "out", "target", "vendor", "coverage",
    "__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".next", ".tox", ".gradle", ".idea",
    ".nuxt", ".output",
}


def iter_repo_replace_files(root: Path, run_git):
    """Liefert (Path, rel_posix) fuer jede Kandidatendatei einer projektweiten Ersetzung. Bevorzugt werden
    versionierte UND unversionierte-aber-nicht-ignorierte Dateien ('git ls-files -z --cached --others
    --exclude-standard' - '-z' wegen Pfaden mit Leerzeichen/Umlauten, wie an anderen Git-Aufrufen dieses
    Ordners): git kennt gitignorierte Dateien (node_modules & Co.) dort weiterhin gar nicht erst, aber auch
    frisch von apply-template.py kopierte, noch nicht committete Dateien zaehlen mit - ohne '--others' meldete
    ein Weg-2-Lauf ohne Zwischen-Commit "0 ersetzte Dateien" und liess Platzhalter in allen frisch kopierten
    Dateien stehen (Review 2026-09-17). '--cached'/'--others' koennen sich ueberschneiden (z.B. bei einer
    Teil-Stage), deshalb wird hier selbst dedupliziert statt auf ein '--deduplicate' von 'git ls-files' zu
    setzen (das gibt es erst ab neueren Git-Versionen, die Mindest-Git-Version dieses Templates ist offen).
    Zusaetzlich wird jeder Pfad gegen EXCLUDE_DIR_NAMES_REPLACE geprueft - ein Sicherheitsnetz, z.B. fuer
    versehentlich eingecheckte Abhaengigkeitsordner. Ohne Git (kein Repo, 'git' fehlt im PATH, Timeout,
    Fehler-Returncode) Fallback auf os.walk ab 'root' - dort greift nur die Ausschlussliste (keine
    .gitignore-Wirkung), aber immer noch besser als vorher (gar keine Ausnahme). 'run_git' ist die
    run_git(root, args, timeout=None)-Funktion des Aufrufers (jedes Script hat seine eigene Kopie, siehe
    Kopfkommentare von files-lib.py/rename-lib.py - keine gemeinsame Abhaengigkeit auf subprocess-Ebene)."""
    def _excluded(rel: str) -> bool:
        return any(part in EXCLUDE_DIR_NAMES_REPLACE for part in Path(rel).parts[:-1])

    res = None
    try:
        res = run_git(root, ["ls-files", "-z", "--cached", "--others", "--exclude-standard"], timeout=30)
    except (OSError, subprocess.SubprocessError):
        res = None
    if res is not None and res.returncode == 0:
        seen = set()
        for rel in res.stdout.split("\0"):
            if not rel or rel in seen or _excluded(rel):
                continue
            seen.add(rel)
            yield root / rel, rel
        return

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIR_NAMES_REPLACE]
        for fname in filenames:
            fp = Path(dirpath) / fname
            yield fp, fp.relative_to(root).as_posix()
