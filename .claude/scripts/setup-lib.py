#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Bibliothek fuer Weg 1 ("Neues Projekt") - der duenne CLI-Wrapper .claude/scripts/create-project.py laedt
# dieses Modul und ruft main() auf. Der Wrapper wird von finish-setup.py beim Abschluss der Einrichtung
# entfernt, diese Datei bleibt dauerhaft bestehen (sync-config.py braucht ihre Funktionen fuer den
# laufenden AI-CONFIG.md-Abgleich). main() bricht deshalb ab, sobald die Einrichtung abgeschlossen ist
# (siehe Guard am Anfang von main()).
#
# Zweck: Weg 1 ("Neues Projekt") aus README.md/AGENTS.md umsetzen - AI-CONFIG.md (Formular im Repo-Root,
#        bleibt danach dauerhaft im Projekt) einlesen, Platzhalter (`{{PROJEKTNAME}}` usw.) ersetzen, nicht
#        genutzte Werkzeug-Dateien entfernen, Logging-Schalter in AGENTS.md setzen und die eingesetzten
#        Werte in `.claude/template.json` festhalten. Ergaenzt/ersetzt die frueheren Skills
#        `adapt-template` + `new-idea`. Reine Python-Stdlib, kein Paket noetig. Siehe
#        `.claude/skills/create-project/SKILL.md`, `docs/ai/checklists.md` § "Neues Projekt".
#
# Aufruf:
#   python .claude/scripts/create-project.py --dry-run
#       (Default, auch ohne Argument) AI-CONFIG.md parsen (fehlt sie oder ist sie leer -> Defaults), Plan
#       ausgeben: Werte je Platzhalter, zu entfernende Dateien, Logging-Schalter, Orchestrator-Modell,
#       Commit-Verhalten, Wartung (ein/aus, ggf. Aufgaben bzw. zu entfernende Dateien), offene Platzhalter
#       (nur echte Marken {{GROSS_MIT_UNTERSTRICH}}, nur aus docs/, AGENTS.md, CLAUDE.md, AI-CONFIG.md,
#       README.md, .claude/, .github/ - Mustache-Ausdruecke im Anwendungscode wie "{{ band.name }}" in
#       .vue/.jsx/... zaehlen nicht als Platzhalter, siehe replace_placeholders()).
#   python .claude/scripts/create-project.py --apply
#       Platzhalter ersetzen (ausser .git, AI-CONFIG.md, docs/ai/checklists.md,
#       .claude/skills/create-project/SKILL.md und den beiden Scripten setup-lib.py/update-template.py -
#       dort sind sie absichtlich als Beispiel sichtbar), nicht genannte Werkzeug-Dateien entfernen (nur
#       wenn KI-Werkzeuge gesetzt ist), AI_LOG/AI_LOG_LEVEL in AGENTS.md setzen, "model" in
#       .claude/settings.json setzen (Orchestrator-Modell; "inherit" entfernt den Schluessel; fehlt
#       settings.json, wird uebersprungen), bei Wartung "ein" .claude/maintenance/status.json aus
#       Wartungsaufgaben schreiben, bei "aus" die Wartungsdateien/den Hook/die CLAUDE.md-Verweise entfernen,
#       bei Code-Optimierung "aus" den Agenten .claude/agents/optimizer.md entfernen,
#       Werte in .claude/template.json schreiben (direkt) und - falls ein Git-Remote "template" existiert und
#       noch kein base_commit gesetzt ist - `update-template.py --init` per Subprocess aufrufen.
#       Bricht vor jeder Aenderung ab (Exit 2), wenn KI-Werkzeuge/Orchestrator-Modell/Commit-Verhalten/
#       Wartung/Wartungsaufgaben unbekannte bzw. ungueltige Werte enthalten - sonst wuerde ein Tippfehler
#       (z. B. "Claude" statt "Claude Code") stillschweigend Dateien loeschen oder eine falsche Konfiguration
#       schreiben. AI-CONFIG.md bleibt bestehen (Commit-Verhalten steuert nur den Orchestrator, keine Datei).
#       Laeuft das Script im Template-Checkout selbst (Marker `is_template` in .claude/template.json), ist
#       --apply nur auf einem eigenen Branch erlaubt - auf main/master bricht es ab, sonst wuerde das
#       Template seine Platzhalter verlieren. Auf einem eigenen Branch entsteht das Projekt als Branch des
#       Templates: base_commit = letzter gemeinsamer Commit mit main/master, template_remote = origin, der
#       Marker wird entfernt. Spaetere Updates laufen dann per Merge aus dem Standard-Branch.
#   python .claude/scripts/create-project.py --finish
#       Prueft, dass docs/project/project_description.md ausgefuellt wurde (keine Vorlagenzeile mehr) und
#       docs/ai/ledger.md einen echten Eintrag hat. Schreibt danach AI-CONFIG.md fort statt sie zu loeschen:
#       die Freitext-Abschnitte (## Ziel .. ## Sonstiges, bereits in docs/project/ eingearbeitet) werden
#       durch einen Verweis-Abschnitt "## Projektbeschreibung" ersetzt, ein Datums-Vermerk kommt vor die
#       erste Zeile. Die Tabellen (## Projekt/Technik/Assistenten/...) bleiben unveraendert und wirken
#       danach weiter, per `sync-config.py` laufend abgeglichen. Idempotent: steht der Vermerk schon da,
#       Exit 0 mit Hinweis, keine erneute Aenderung.
#   python .claude/scripts/create-project.py --check
#       Selbstpruefung ohne Bezug zu einem konkreten Projekt-Zuschnitt: prueft je Pfad in den fest
#       verdrahteten Listen OPTIMIZER_REMOVE_PATHS/MAINTENANCE_REMOVE_PATHS/TEMPLATE_ONLY_PATHS
#       (STALE_PATH_CHECK_LISTS), ob er im Repo existiert, und warnt bei fehlenden Pfaden (Hinweis auf eine
#       nach einer Umbenennung/Verschiebung veraltete Liste) - aber nur, solange der is_template-Marker in
#       .claude/template.json noch gesetzt ist (--apply also noch nicht gelaufen ist); danach sind viele
#       dieser Pfade absichtlich entfernt und die Pruefung wird ausgelassen statt Fehlalarm zu schlagen.
#       Schreibt nichts, Exit immer 0.
#
# Exit-Codes: 0 = ok, 2 = Vorbedingungs-/Parsefehler. Ein Fehler dieses Scripts darf nie mit Traceback nach
# aussen dringen: main() laeuft komplett in try/except, Fehlermeldungen auf stderr.

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

CONFIG_REL = "AI-CONFIG.md"
EXCLUDED_FROM_REPLACE = {
    "AI-CONFIG.md",
    # Diese beiden Scripte erklaeren die Platzhalter-Mechanik in ihren Kopfkommentaren ("ersetzt
    # `{{PROJEKTNAME}}` usw.") - wird dort ersetzt, steht danach Unsinn im Kommentar. sync-config.py fuehrt
    # dieselben Marken zusaetzlich als echten Code (RENAME_PLATZHALTER-Dict fuer die Befehls-Schluessel/
    # Rename-Diffs) - dort wuerde eine Ersetzung das Script funktional zerstoeren, nicht nur einen Kommentar
    # verunstalten. Gleiche Liste wie `no_replace` in `.claude/template.json`.
    ".claude/scripts/setup-lib.py",
    ".claude/scripts/update-template.py",
    ".claude/scripts/sync-config.py",
}

# Echte Platzhalter-Marke: {{ + Grossbuchstabe/Ziffer/Unterstrich + }}, ohne Leerzeichen und ohne Punkt/
# Kleinbuchstaben - trifft "{{PROJEKTNAME}}", nicht "{{ band.name }}" oder "{{genre}}" (Mustache-Ausdruecke
# in Anwendungscode). Nur fuer die "Restplatzhalter"-Meldung in replace_placeholders() - die Ersetzung selbst
# arbeitet ohnehin nur mit den bekannten Schluesseln aus values (siehe replace_placeholders).
PLACEHOLDER_PATTERN = re.compile(r"\{\{[A-Z][A-Z0-9_]*\}\}")
# Restplatzhalter werden laut Vorgabe nur aus diesen doku-/steuerungsnahen Pfaden gemeldet - Platzhalter
# sollen nur in docs/ (bzw. den genannten Wurzeldateien) und in der eigenen Steuerung liegen, nicht im
# Anwendungscode.
REPORT_PATH_PREFIXES = ("docs/", ".claude/", ".github/")
REPORT_ROOT_FILES = {"AGENTS.md", "CLAUDE.md", "AI-CONFIG.md", "README.md"}
# Endungen von Template-Sprachen mit derselben {{...}}-Syntax wie unsere Platzhalter - dort ist "{{X}}"
# echter Anwendungscode (Vue/JSX/Twig/Jinja/... Ausdruck), kein auszufuellender Platzhalter.
REPORT_SKIP_SUFFIXES = (
    ".vue", ".jsx", ".tsx", ".svelte", ".hbs", ".mustache", ".twig", ".blade.php", ".j2", ".jinja", ".liquid",
)

KEY_MAP = {
    "Projektname": "projektname",
    "Auftraggeber": "auftraggeber",
    "Orchestrator": "orchestrator",
    "Sprache": "sprache",
    "KI-Werkzeuge": "ki_werkzeuge",
    "Stack": "stack",
    "Orchestrator-Modell": "orchestrator_modell",
    "Commit-Verhalten": "commit_verhalten",
    "Ideen-Ablauf": "ideen_ablauf",
    "Testtiefe": "testtiefe",
    "Schreibstil": "schreibstil",
    "Feedback": "feedback",
    "Feedback-Takt": "feedback_takt",
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
# Steuert nur den Orchestrator (Checkliste "Aufgabe abschliessen"/Skill /commit), keine Datei -
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
FEEDBACK_TAKT_WERTE = {"manuell", "sofort", "stuendlich", "taeglich", "woechentlich", "automatisch"}
FEEDBACK_TAKT_ALIAS = {"stündlich": "stuendlich", "täglich": "taeglich", "wöchentlich": "woechentlich"}
# Mindestabstand je Takt in Stunden - im Script durchgesetzt, nicht nur dokumentiert.
FEEDBACK_TAKT_STUNDEN = {
    "manuell": None, "sofort": 0, "stuendlich": 1, "taeglich": 24, "woechentlich": 168, "automatisch": 1,
}
WARTUNG_WERTE = {"aus", "ein"}
DEFAULT_WARTUNGSAUFGABEN = "kurz=14, docs=30, deps=90"
# Ablageort der Wartungsberichte (.claude/maintenance/reports/YYYY-MM-DD.md) - "docs" legt zusaetzlich
# docs/maintenance/README.md an, siehe setup_docs_maintenance_reports.
WARTUNGSBERICHTE_WERTE = {"intern", "docs"}
# Nur fuer Weg 2 (/apply-template): soll nach dem Befuellen von docs/project/ zusaetzlich der bestehende
# Code geprueft und Verbesserungen vorgeschlagen werden? "fragen" = der Assistent fragt im Chat nach.
CODE_ANALYSE_WERTE = {"nein", "vorschlagen", "fragen"}
# Optionaler Politur-Agent nach jeder Umsetzungswelle: "aus" entfernt ihn, "ein"/"intensiv" behalten ihn
# (die Stufe steuert nur, wie der Orchestrator ihn beauftragt - siehe .claude/agents/optimizer.md).
# "streng" war der frühere Name von "intensiv" - bestehende Projekte duerfen ihn weiter verwenden
# (normalize_code_optimierung bildet ihn auf "intensiv" ab und weist einmal auf die Umbenennung hin).
CODE_OPTIMIERUNG_WERTE = {"aus", "ein", "intensiv"}
CODE_OPTIMIERUNG_ALIASE = {"streng": "intensiv"}
OPTIMIZER_REMOVE_PATHS = [".claude/agents/optimizer.md"]
# Vorgefertigte Regelsaetze je Sprache/Framework (docs/project/coding_rules.d/). Beim Anlegen bleiben nur
# die in AI-CONFIG.md genannten liegen - der Rest kommt bei Bedarf per `guidelines.py --add` aus dem Template
# zurueck. Leere Angabe = keine (kein Ballast im Projekt).
GUIDELINES_DIR = "docs/project/coding_rules.d"
# Nur fuer Weg 2 (/apply-template): sollen vorhandene KI-Arbeitsordner/-Regeldateien auf die
# Template-Struktur migriert und zusammengefuehrt werden (siehe rename-lib.py)? "fragen" = der
# Assistent zeigt den Plan und fragt im Chat nach.
STRUKTUR_MIGRATION_WERTE = {"ja", "nein", "fragen"}
WARTUNGSAUFGABEN_EREIGNISGESTEUERT = {"0", "", "null", "none", "-"}

# Bei Wartung "aus" zu entfernende Pfade - identisch zu den Wartungsdateien unter TOOL_FILES["Claude Code"],
# hier aber unabhaengig davon, ob Claude Code selbst als KI-Werkzeug abgewaehlt wird (Doppelentfernung ist
# tolerant, siehe remove_maintenance_files).
MAINTENANCE_REMOVE_PATHS = [
    ".claude/maintenance",
    ".claude/skills/run-maintenance",
    ".claude/agents/maintenance-orchestrator.md",
    ".claude/scripts/maintenance-check.py",
]

# Gleicher Hinweistext wie _HINWEIS in maintenance-check.py (dort massgeblich) - hier dupliziert, weil
# setup-lib.py status.json direkt schreibt, ohne das Script zu importieren.
MAINTENANCE_HINWEIS = (
    "Aufgabe je Schluessel unter 'aufgaben'. intervall_tage: null = ereignisgesteuert (laeuft nur auf "
    "Zuruf, nie automatisch faellig). Fehlt eine Aufgabe hier, ist sie deaktiviert. Nach einem Lauf setzt "
    "der Orchestrator (bzw. 'maintenance-check.py --done <aufgabe>') letzter_lauf = heute und "
    "naechster_lauf = heute + intervall_tage (bei null nur letzter_lauf). Datumsformat YYYY-MM-DD. Siehe "
    ".claude/maintenance/README.md."
)

# Erste Tabellenspalte in AGENTS.md § "Werkzeugspezifische Ergaenzungsdateien" bzw. README.md
# § "Mit welchem Assistenten?" - identisch fuer beide Tabellen.
TOOL_ROW_KEY = {
    "Claude Code": "Claude Code",
    "Copilot": "GitHub Copilot",
    "Cursor": "Cursor",
    "Aider": "Aider",
    "Gemini CLI": "Gemini CLI",
}

PLACEHOLDER_KEYS = [
    "PROJEKTNAME",
    "AUFTRAGGEBER",
    "ORCHESTRATOR",
    "STACK",
    "DATUM",
    "INSTALL_BEFEHL",
    "DEV_START_BEFEHL",
    "LINT_BEFEHL",
    "TYPECHECK_BEFEHL",
    "TEST_BEFEHL",
    "E2E_BEFEHL",
]


# ---------------------------------------------------------------------------
# Grundlagen
# ---------------------------------------------------------------------------


def _find_root() -> Path:
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[2]


def run_git(root: Path, args, timeout=None):
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(
        ["git", "-c", "core.quotePath=false", "-C", str(root)] + list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        env=env,
        timeout=timeout,
    )


def _load_template_update_module():
    """Laedt update-template.py als Modul (gleicher Ordner) - eine gemeinsame Quelle fuer die Struktur von
    .claude/template.json statt sie hier zu duplizieren."""
    tu_path = Path(__file__).resolve().parent / "update-template.py"
    spec = importlib.util.spec_from_file_location("_template_update", tu_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
# Werte/Platzhalter
# ---------------------------------------------------------------------------


def compute_values(cfg: dict) -> dict:
    today = time.strftime("%Y-%m-%d")
    return {
        "PROJEKTNAME": cfg.get("projektname") or "MyApp",
        "AUFTRAGGEBER": cfg.get("auftraggeber") or "Entwickler",
        "ORCHESTRATOR": cfg.get("orchestrator") or "Fable",
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


def config_warnungen(cfg: dict) -> list:
    """Alles, was der Parser nicht eindeutig lesen konnte - darf nie still verschluckt werden."""
    lines = []
    for raw_key, raw_val, val in cfg.get("gekuerzt") or []:
        lines.append(f"{raw_key}: Klammer-Kommentar abgeschnitten, verwendet wird \"{val}\" (Zeile: {raw_val})")
    return lines


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
    abschliessen" (Skill /commit) umgeht."""
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
    "manuell": "manuell - nur auf Aufruf von /feedback, sonst nie",
}

FEEDBACK_TAKT_TEXT = {
    "manuell": "manuell - kein automatischer Versand",
    "sofort": "sofort - nach jedem brauchbaren Vorschlag",
    "stuendlich": "stuendlich - hoechstens einmal je Stunde",
    "taeglich": "taeglich - hoechstens einmal am Tag",
    "woechentlich": "woechentlich - hoechstens einmal je Woche (Default)",
    "automatisch": "automatisch - der Assistent entscheidet, fruehestens eine Stunde nach der letzten Sendung",
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

DOCS_MAINTENANCE_README = (
    "# Wartungsberichte\n"
    "\n"
    "Berichte liegen hier je Lauf als `YYYY-MM-DD.md`. Das Abschnitts-Schema steht in "
    "`.claude/maintenance/README.md`.\n"
)


def setup_docs_maintenance_reports(root: Path) -> bool:
    """Legt bei 'Wartungsberichte: docs' docs/maintenance/README.md an (idempotent - vorhandene Datei bleibt
    unangetastet). Gibt True zurueck, wenn die Datei neu angelegt wurde."""
    readme = root / "docs" / "maintenance" / "README.md"
    if readme.exists():
        return False
    readme.parent.mkdir(parents=True, exist_ok=True)
    readme.write_text(DOCS_MAINTENANCE_README, encoding="utf-8", newline="\n")
    return True


def normalize_code_analyse(cfg: dict):
    """Gibt (code_analyse, unbekannter_rohwert) zurueck - genau einer der beiden ist None. Default 'fragen'.
    Der Wert steuert keinen Dateieingriff, sondern nur den Ablauf des Skills /apply-template (Weg 2)."""
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


def apply_coding_guidelines(root: Path, gewaehlt) -> list:
    """Entfernt alle nicht gewaehlten Bausteine und schreibt den Index in coding_rules.md neu.
    Gibt die Liste der entfernten Kennungen zurueck."""
    d = root / GUIDELINES_DIR
    if not d.is_dir():
        return []
    entfernt = []
    for f in sorted(d.glob("*.md")):
        if not f.is_file() or f.stem.lower() == "readme":
            continue
        if f.stem.lower() in gewaehlt:
            continue
        try:
            f.unlink()
            entfernt.append(f.stem.lower())
        except OSError:
            pass
    script = Path(__file__).resolve().parent / "guidelines.py"
    if script.exists():
        try:
            subprocess.run(
                [sys.executable or "python3", str(script), "--sync"],
                cwd=str(root), capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    return entfernt


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


def remove_optimizer_files(root: Path) -> list:
    """Entfernt den optionalen Politur-Agenten bei 'Code-Optimierung: aus'. Tolerant, wenn er fehlt (z.B.
    weil Claude Code als Werkzeug abgewaehlt wurde und .claude/agents/ schon weg ist)."""
    removed = []
    for rel in OPTIMIZER_REMOVE_PATHS:
        fp = root / rel
        if not fp.exists():
            continue
        try:
            fp.unlink()
            removed.append(rel)
        except OSError:
            pass
    return removed


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
    /apply-template (Weg 2, migrate-project.py)."""
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


# ---------------------------------------------------------------------------
# Dateiwalk fuer die Platzhalter-Ersetzung
# ---------------------------------------------------------------------------


def _read_text_preserve_newline(path: Path, encoding: str = "utf-8"):
    """Liest eine Textdatei und liefert (text, newline). `text` hat alle Zeilenenden auf '\\n' normalisiert
    (fuer Regex/Vergleich/Ersetzung), `newline` ist '\\r\\n', wenn die Datei im Original CRLF verwendet hat,
    sonst '\\n' - fuer _write_text_preserve_newline. Path.read_text() allein taugt hier nicht: es uebersetzt
    CRLF beim Lesen bereits in '\\n' (universelle Zeilenenden) und macht die Erkennung unmoeglich, deshalb
    Rohbytes lesen. Wirft OSError/UnicodeDecodeError wie read_bytes()/decode() - vom Aufrufer abzufangen."""
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    text = raw.decode(encoding).replace("\r\n", "\n")
    return text, newline


def _write_text_preserve_newline(path: Path, text: str, newline: str, encoding: str = "utf-8") -> None:
    """Schreibt `text` (interne Zeilenenden '\\n') zurueck, wobei '\\n' zu `newline` wird - haelt eine
    CRLF-gepflegte Datei CRLF, eine LF-Datei LF (siehe _read_text_preserve_newline). Path.write_text() kennt
    den newline-Parameter erst ab Python 3.10, deshalb open() direkt (Projekt-Minimum ist 3.9)."""
    with open(path, "w", encoding=encoding, newline=newline) as f:
        f.write(text)


def _iter_text_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fname in filenames:
            fp = Path(dirpath) / fname
            rel = fp.relative_to(root).as_posix()
            if rel in EXCLUDED_FROM_REPLACE:
                continue
            yield fp, rel


# Die Kopfzeile jeder Doku-Datei ("> Datenstand: ... - Status: ...") sagt im Template, dass die Datei noch
# Vorlage ist. Nach dem Anlegen/Nachruesten stimmt das nicht mehr, der Zusatz ist aber kein {{PLATZHALTER}}
# und blieb darum frueher stehen - in bandliste in 8 Dateien, ueber Inhalten, die laengst projektspezifisch
# waren. Deshalb wird er hier mitersetzt. Vokabular der Statuswoerter: docs/README.md § "Konventionen".
STATUS_VORLAGE = "Status: Vorlage, noch nicht projektspezifisch"
STATUS_NACH_SETUP = "Status: Entwurf"


def replace_placeholders(root: Path, values: dict):
    """Ersetzt {{KEY}} in allen Textdateien (ausser den 3 Ausnahmen) und die Vorlagen-Statuszeile. Gibt
    (geaenderte_dateien, verbleibende_platzhalter) zurueck - Letzteres als Liste 'Datei:Zeile' (max 20)."""
    changed = []
    remaining = []
    for fp, rel in _iter_text_files(root):
        try:
            content, newline = _read_text_preserve_newline(fp)
        except (UnicodeDecodeError, OSError):
            continue
        new_content = content
        for key, val in values.items():
            if val is None:
                continue
            new_content = new_content.replace("{{" + key + "}}", str(val))
        if rel.startswith("docs/"):
            new_content = new_content.replace(STATUS_VORLAGE, STATUS_NACH_SETUP)
        if new_content != content:
            try:
                _write_text_preserve_newline(fp, new_content, newline)
                changed.append(rel)
            except OSError:
                continue
        # Restplatzhalter nur aus doku-/steuerungsnahen Pfaden melden - Platzhalter gehoeren laut Vorgabe nur
        # nach docs/, AGENTS.md, CLAUDE.md, AI-CONFIG.md, README.md, .claude/, .github/. Anwendungscode wird
        # generell ausgenommen (u.a. .py-Quelldateien, die "{{" nur als Code-Literal enthalten, sowie
        # Template-Sprachen wie Vue/JSX/Twig, die dieselbe Mustache-Syntax fuer echten Code nutzen, z.B.
        # "{{ band.name }}" in einer .vue-Datei - das ist kein Platzhalter).
        if not (rel.startswith(REPORT_PATH_PREFIXES) or rel in REPORT_ROOT_FILES):
            continue
        if fp.suffix == ".py" or rel.endswith(REPORT_SKIP_SUFFIXES):
            continue
        if len(remaining) < 20 and PLACEHOLDER_PATTERN.search(new_content):
            for i, line in enumerate(new_content.splitlines(), start=1):
                if PLACEHOLDER_PATTERN.search(line):
                    remaining.append(f"{rel}:{i}")
                    if len(remaining) >= 20:
                        break
    return changed, remaining


# ---------------------------------------------------------------------------
# Werkzeug-Dateien entfernen + Tabellenzeilen
# ---------------------------------------------------------------------------


def _remove_table_row(text: str, row_key: str) -> str:
    pattern = re.compile(r"^\|\s*" + re.escape(row_key) + r"\s*\|.*\|[ \t]*\n?", re.MULTILINE)
    return pattern.sub("", text)


def remove_tool_files(root: Path, remove_list) -> list:
    removed = []
    for tool in remove_list:
        for rel in TOOL_FILES.get(tool, []):
            fp = root / rel
            if not fp.exists():
                continue
            try:
                if fp.is_dir():
                    shutil.rmtree(fp)
                else:
                    fp.unlink()
                removed.append(rel)
            except OSError:
                pass

    if remove_list:
        for doc_rel in ("AGENTS.md", "README.md"):
            doc_path = root / doc_rel
            if not doc_path.exists():
                continue
            try:
                text, newline = _read_text_preserve_newline(doc_path)
            except (UnicodeDecodeError, OSError):
                continue
            new_text = text
            for tool in remove_list:
                row_key = TOOL_ROW_KEY.get(tool)
                if row_key:
                    new_text = _remove_table_row(new_text, row_key)
            if new_text != text:
                _write_text_preserve_newline(doc_path, new_text, newline)

    return removed


# ---------------------------------------------------------------------------
# AGENTS.md Logging-Schalter
# ---------------------------------------------------------------------------


def set_logging_switch(root: Path, logging_val: str, logging_tiefe: str) -> bool:
    agents_path = root / "AGENTS.md"
    if not agents_path.exists():
        return False
    try:
        text, newline = _read_text_preserve_newline(agents_path)
    except (UnicodeDecodeError, OSError):
        return False
    new_text = re.sub(r"(?m)^(AI_LOG)=\S+", r"\1=" + logging_val, text)
    new_text = re.sub(r"(?m)^(AI_LOG_LEVEL)=\S+", r"\1=" + logging_tiefe, new_text)
    if new_text != text:
        _write_text_preserve_newline(agents_path, new_text, newline)
        return True
    return False


# ---------------------------------------------------------------------------
# .claude/settings.json: Orchestrator-Modell + Wartungs-Hook/-Permissions
# ---------------------------------------------------------------------------


def _write_json(path: Path, data: dict, newline: str = "\n") -> None:
    """`newline` haelt eine bestehende Datei bei ihrem Zeilenende (CRLF/LF) - Aufrufer, die eine vorhandene
    JSON-Datei lesen, ermitteln es vorher per _read_json_preserve_newline; bei einer neu angelegten Datei
    bleibt der Default '\\n'. Schreibt atomar: erst in eine Temp-Datei im selben Verzeichnis, dann per
    os.replace an ihren Platz (kein Leser sieht eine halb geschriebene Datei, kein gleichzeitiger Schreiber
    verliert seine Aenderung) - gleiches Muster wie maintenance-check.py:save_status. Die Temp-Datei bleibt
    bei einem Fehler nicht liegen."""
    path.parent.mkdir(parents=True, exist_ok=True)
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
    """Liest eine JSON-Datei und liefert (data, newline) - newline wie _read_text_preserve_newline, zum
    Zurueckschreiben mit _write_json(..., newline=newline). Wirft OSError/ValueError (kaputtes JSON) wie
    json.loads(), vom Aufrufer abzufangen."""
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    data = json.loads(raw.decode("utf-8"))
    return data, newline


def set_orchestrator_model(root: Path, modell: str) -> str:
    """Schreibt/entfernt den Top-Level-Schluessel 'model' in .claude/settings.json ('inherit' entfernt ihn).
    Fehlt settings.json (Claude Code als KI-Werkzeug abgewaehlt), wird still uebersprungen."""
    path = root / ".claude" / "settings.json"
    if not path.exists():
        return "settings.json: nicht vorhanden (Claude Code abgewaehlt) - uebersprungen."
    try:
        data, newline = _read_json_preserve_newline(path)
    except (OSError, UnicodeDecodeError, ValueError):
        return "settings.json: konnte nicht gelesen werden - 'model' nicht gesetzt."
    if not isinstance(data, dict):
        return "settings.json: kein JSON-Objekt - 'model' nicht gesetzt."

    if modell == "inherit":
        if "model" in data:
            del data["model"]
            _write_json(path, data, newline)
            return "settings.json: 'model' entfernt (inherit)."
        return "settings.json: 'model' war bereits nicht gesetzt (inherit)."

    if data.get("model") == modell:
        return f"settings.json: 'model' bereits '{modell}'."
    ordered = {"model": modell}
    for k, v in data.items():
        if k != "model":
            ordered[k] = v
    _write_json(path, ordered, newline)
    return f"settings.json: 'model' = '{modell}'."


def _hook_command_desc(entry) -> str:
    """Kurzbeschreibung eines SessionStart-Hook-Eintrags fuer den Bericht (Kommando-Text, gekuerzt) -
    fallback auf den rohen JSON-Dump, falls die Struktur unerwartet ist."""
    try:
        inner = entry.get("hooks")
        if isinstance(inner, list) and inner and isinstance(inner[0], dict):
            cmd = inner[0].get("command")
            if isinstance(cmd, str):
                return cmd[:100] + ("…" if len(cmd) > 100 else "")
    except AttributeError:
        pass
    return json.dumps(entry, ensure_ascii=False)[:100]


def remove_maintenance_hook(root: Path):
    """Entfernt aus .claude/settings.json nur SessionStart-Hooks, deren Kommando SOWOHL
    'maintenance-check.py' ALS AUCH 'CLAUDE_PROJECT_DIR' enthaelt - das Muster der vom Template gesetzten
    Hooks. Die CLAUDE_PROJECT_DIR-Pruefung ist bewusst tolerant (ohne '$', unabhaengig von '${...}'-Klammerung
    und von Windows- vs. Unix-Pfadtrennern), damit z.B. '${CLAUDE_PROJECT_DIR}' statt '$CLAUDE_PROJECT_DIR'
    weiterhin als Template-Hook erkannt wird. Ein fremder, selbst ergaenzter Hook, der maintenance-check.py
    nur nebenbei aufruft (ohne CLAUDE_PROJECT_DIR-Bezug), bleibt stehen und wird ueber die zurueckgegebene
    Liste gemeldet - inklusive Hinweis, dass maintenance-check.py trotzdem entfernt wurde und der Hook damit
    ins Leere zeigt. Die zugehoerigen Permissions werden weiterhin allein anhand von 'maintenance-check.py'
    entfernt (dort gibt es kein CLAUDE_PROJECT_DIR-Muster). Gibt (changed: bool, fremde: list[str]) zurueck;
    fehlt die Datei, still (False, [])."""
    path = root / ".claude" / "settings.json"
    if not path.exists():
        return False, []
    try:
        data, newline = _read_json_preserve_newline(path)
    except (OSError, UnicodeDecodeError, ValueError):
        return False, []
    if not isinstance(data, dict):
        return False, []

    changed = False
    fremde = []
    hooks = data.get("hooks")
    if isinstance(hooks, dict):
        session_start = hooks.get("SessionStart")
        if isinstance(session_start, list):
            new_list = []
            for e in session_start:
                dumped = json.dumps(e, ensure_ascii=False).replace("\\\\", "/")
                if "maintenance-check.py" in dumped and "CLAUDE_PROJECT_DIR" in dumped:
                    continue  # vom Template gesetzt - entfernen
                if "maintenance-check.py" in dumped:
                    fremde.append(_hook_command_desc(e))
                new_list.append(e)
            if len(new_list) != len(session_start):
                hooks["SessionStart"] = new_list
                changed = True

    perms = data.get("permissions")
    if isinstance(perms, dict):
        allow = perms.get("allow")
        if isinstance(allow, list):
            new_allow = [p for p in allow if "maintenance-check.py" not in p]
            if len(new_allow) != len(allow):
                perms["allow"] = new_allow
                changed = True

    if changed:
        _write_json(path, data, newline)
    return changed, fremde


# ---------------------------------------------------------------------------
# Wartung: status.json schreiben bzw. Wartungsdateien/CLAUDE.md-Verweise entfernen
# ---------------------------------------------------------------------------


# Runner/README des Wartungsordners - fehlen sie bei "Wartung: ein" (status.json wird unten trotzdem
# geschrieben), ist das typisch fuer ein per apply-template.py nachgeruestetes Projekt, das nur status.json
# bekommen hat. Siehe check_maintenance_runner_files.
MAINTENANCE_RUNNER_FILES = ["run-maintenance.ps1", "run-maintenance.sh", "README.md"]


def check_maintenance_runner_files(root: Path) -> list:
    """Gibt die Dateinamen aus MAINTENANCE_RUNNER_FILES zurueck, die in .claude/maintenance/ fehlen."""
    d = root / ".claude" / "maintenance"
    return [name for name in MAINTENANCE_RUNNER_FILES if not (d / name).exists()]


def write_maintenance_status(root: Path, aufgaben: dict) -> None:
    path = root / ".claude" / "maintenance" / "status.json"
    data = {
        "aufgaben": {
            name: {"intervall_tage": intervall, "letzter_lauf": None, "naechster_lauf": None}
            for name, intervall in aufgaben.items()
        },
        "_hinweis": MAINTENANCE_HINWEIS,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(path, data)


# Pfade, die nur das TEMPLATE selbst betreffen und in einem abgeleiteten Projekt nichts verloren haben:
# `.github/README.md` (Template-Beschreibung, wird von GitHub vor der Root-README angezeigt) und
# `.templatedev/` (Board/Backlog/Fragen/Ledger/Regeln der Template-Entwicklung - der einzige Ordner im
# Template mit echtem Inhalt statt Platzhaltern). Bare Ordnername ohne Trailing-Slash/Wildcard: greift bei
# Path.exists()/is_dir() (siehe remove_template_intro) direkt, und muss zu DEFAULT_TEMPLATE_ONLY in
# update-template.py passen (kein Import zwischen den Scripten, siehe dort).
TEMPLATE_ONLY_PATHS = [".github/README.md", ".templatedev"]

# Fest verdrahtete Pfadlisten, deren Eintraege nach einer Umbenennung/Verschiebung veraltet sein koennen
# (siehe check_stale_remove_paths) - ohne Gegenprobe faellt so etwas erst auf, wenn der jeweilige
# Entfernen-Schritt eine nicht mehr existierende Datei "erfolgreich" ignoriert.
STALE_PATH_CHECK_LISTS = {
    "OPTIMIZER_REMOVE_PATHS": OPTIMIZER_REMOVE_PATHS,
    "MAINTENANCE_REMOVE_PATHS": MAINTENANCE_REMOVE_PATHS,
    "TEMPLATE_ONLY_PATHS": TEMPLATE_ONLY_PATHS,
}


def check_stale_remove_paths(root: Path) -> list:
    """Selbstpruefung fuer '--check': prueft je Pfad in STALE_PATH_CHECK_LISTS, ob er im Repo existiert.

    Ein fehlender Pfad ist nur dann verdaechtig (typischer Fehler nach einer Umbenennung, z.B. ein Ordner
    wurde umbenannt, aber die Liste hier nicht mitgezogen), wenn die Ausgangslage noch unberuehrt ist - d.h.
    solange der 'is_template'-Marker in .claude/template.json noch gesetzt ist (frischer Template-Checkout
    oder frisch geklontes, noch nicht per --apply zugeschnittenes Projekt). Ist der Marker schon weg, hat
    --apply bereits gelaufen und genau diese Pfade wurden absichtlich entfernt - eine Warnung waere dann ein
    Fehlalarm, deshalb wird die Pruefung dafuer bewusst NICHT ausgefuehrt statt sie nur schwaecher zu
    formulieren. Gibt eine Liste von Warnzeilen zurueck (leer = nichts zu melden)."""
    template_json = root / ".claude" / "template.json"
    try:
        cfg = json.loads(template_json.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        cfg = {}
    if not (isinstance(cfg, dict) and cfg.get("is_template")):
        return [
            "Selbstpruefung der Pfadlisten (STALE_PATH_CHECK_LISTS) uebersprungen: is_template-Marker in "
            ".claude/template.json fehlt bereits - --apply ist auf diesem Repo vermutlich schon gelaufen, "
            "fehlende Pfade waeren dann erwartungsgemaess."
        ]

    warnungen = []
    for listen_name, pfade in STALE_PATH_CHECK_LISTS.items():
        for rel in pfade:
            if not (root / rel).exists():
                warnungen.append(
                    f"WARNUNG: Pfad '{rel}' aus {listen_name} existiert nicht (mehr) im Repo - "
                    "moeglicherweise eine veraltete Liste nach einer Umbenennung/Verschiebung."
                )
    return warnungen


# Abschnitte, die nur gelten, solange das Repo die Vorlage selbst ist. Sie stehen in den Regeldateien
# zwischen diesen Markern und werden beim Anlegen eines Projekts mitsamt der Marker entfernt.
TEMPLATE_ONLY_BLOCK = re.compile(
    r"[ \t]*<!--\s*template-only:start\s*-->.*?<!--\s*template-only:end\s*-->[ \t]*\n?",
    re.DOTALL,
)
TEMPLATE_ONLY_BLOCK_FILES = ["AGENTS.md", "CLAUDE.md"]


def remove_template_intro(root: Path) -> list:
    """Entfernt die nur fuer das Template gedachten Pfade (TEMPLATE_ONLY_PATHS - Dateien oder Ordner, z.B.
    `.templatedev/`) und die `template-only`-Bloecke aus den Regeldateien. Gibt zurueck, was entfernt wurde."""
    removed = []
    for rel in TEMPLATE_ONLY_PATHS:
        fp = root / rel
        if not fp.exists():
            continue
        try:
            if fp.is_dir():
                shutil.rmtree(fp)
            else:
                fp.unlink()
            removed.append(rel)
        except OSError:
            pass
    for rel in TEMPLATE_ONLY_BLOCK_FILES:
        fp = root / rel
        if not fp.is_file():
            continue
        try:
            text, newline = _read_text_preserve_newline(fp)
        except (UnicodeDecodeError, OSError):
            continue
        neu_text, n = TEMPLATE_ONLY_BLOCK.subn("", text)
        if n:
            # Doppelte Leerzeilen, die durch das Entfernen entstehen, wieder zusammenziehen.
            neu_text = re.sub(r"\n{3,}", "\n\n", neu_text)
            try:
                _write_text_preserve_newline(fp, neu_text, newline)
                removed.append(f"{rel} (Abschnitt 'nur Template')")
            except OSError:
                pass
    return removed


def remove_maintenance_files(root: Path) -> list:
    removed = []
    for rel in MAINTENANCE_REMOVE_PATHS:
        fp = root / rel
        if not fp.exists():
            continue
        try:
            if fp.is_dir():
                shutil.rmtree(fp)
            else:
                fp.unlink()
            removed.append(rel)
        except OSError:
            pass
    return removed


def remove_maintenance_references(root: Path) -> dict:
    """Entfernt bei Wartung 'aus' den Sub-Agenten-Eintrag [MAINTENANCE] und die '/run-maintenance'-Zeile aus
    CLAUDE.md (gleiche Technik wie remove_tool_files/_remove_table_row). Wird eine Stelle nicht gefunden,
    still weitermachen - das Ergebnis wird im Bericht genannt."""
    result = {"agent_zeile": False, "skill_zeile": False, "modell_zeile": False, "baum_zeile": False}
    path = root / "CLAUDE.md"
    if not path.exists():
        return result
    try:
        text, newline = _read_text_preserve_newline(path)
    except (UnicodeDecodeError, OSError):
        return result
    new_text = text

    agent_pattern = re.compile(r"^- \*\*\[MAINTENANCE\]\*\*.*\n(?:  .+\n)*", re.MULTILINE)
    if agent_pattern.search(new_text):
        new_text = agent_pattern.sub("", new_text)
        result["agent_zeile"] = True

    skill_pattern = re.compile(r"^\|\s*`/run-maintenance[^\n|]*\|[^\n|]*\|[^\n|]*\|[ \t]*\n?", re.MULTILINE)
    if skill_pattern.search(new_text):
        new_text = skill_pattern.sub("", new_text)
        result["skill_zeile"] = True

    # Zeile der Modell-Zuordnungstabelle (| `maintenance-orchestrator` | ... |)
    modell_pattern = re.compile(
        r"^\|\s*`maintenance-orchestrator`[^\n|]*\|[^\n|]*\|[^\n|]*\|[^\n|]*\|[ \t]*\n?", re.MULTILINE
    )
    if modell_pattern.search(new_text):
        new_text = modell_pattern.sub("", new_text)
        result["modell_zeile"] = True

    # Verweise im Fliesstext und im Projektbaum, die sonst ins Leere zeigen.
    fliesstext = (
        "  `maintenance-orchestrator` prüft regelmäßig, welche Agentenläufe scriptfähig sind.\n"
    )
    if fliesstext in new_text:
        new_text = new_text.replace(fliesstext, "")
        result["baum_zeile"] = True
    baum = "│   │                            # maintenance-orchestrator (optional)\n"
    if baum in new_text:
        new_text = new_text.replace(baum, "")
        result["baum_zeile"] = True
    new_text = new_text.replace(
        "│   ├── agents/                  # builder, explorer, reviewer, doc-writer, quick-check, expert-solver,\n",
        "│   ├── agents/                  # builder, explorer, reviewer, doc-writer, quick-check, expert-solver\n",
    )
    new_text = new_text.replace(
        "│   ├── maintenance/              # optional: Status/Intervalle + Runner für wiederkehrende Wartung\n",
        "",
    )
    new_text = new_text.replace(
        "│   │                            # maintenance-check.py (Fälligkeit der Wartung, SessionStart-Hook)\n",
        "",
    )
    new_text = new_text.replace(
        "│   ├── skills/                  # apply-template, audit-docs, create-project,\n"
        "│   │                            # run-maintenance, update-template, commit\n",
        "│   ├── skills/                  # apply-template, audit-docs, create-project,\n"
        "│   │                            # update-template, commit\n",
    )

    if new_text != text:
        _write_text_preserve_newline(path, new_text, newline)
    return result


# ---------------------------------------------------------------------------
# template.json
# ---------------------------------------------------------------------------


def write_template_json_values(root: Path, values: dict, applied_config: dict = None):
    tu = _load_template_update_module()
    cfg, path = tu.load_template_json(root)
    tu_values = cfg.setdefault("values", {})
    for key in PLACEHOLDER_KEYS:
        val = values.get(key)
        if val is not None:
            tu_values[key] = val
    # Ab hier ist aus dem Checkout ein echtes Projekt geworden - der Template-Marker gilt nicht mehr.
    cfg.pop("is_template", None)
    if applied_config is not None:
        # Vergleichsgrundlage fuer sync-config.py: die zuletzt umgesetzten Werte aus AI-CONFIG.md
        # § Betrieb/Einrichtung (nur die Schluessel, die eine Datei-Wirkung haben - siehe
        # sync-config.py Kopfkommentar). Fehlt dieses Feld (Projekt vor sync-config.py angelegt),
        # gilt der Stand als unbekannt.
        cfg["applied_config"] = applied_config
        cfg["applied_config_stand"] = time.strftime("%Y-%m-%d")
    tu.save_template_json(root, cfg, path)
    return cfg


def build_applied_config(
    values: dict, orch_modell: str, logging_val: str, logging_tiefe: str, wartung_val: str,
    wartungsaufgaben: dict, wartungsberichte: str, code_opt: str, guidelines_gewaehlt, entfernte_tools,
    sprache: str = None, commit_verhalten: str = None, ideen_ablauf: str = None,
    testtiefe: str = None, schreibstil: str = None, feedback: str = None,
    feedback_takt: str = None,
) -> dict:
    """Schnappschuss der Betrieb/Einrichtung-Schluessel, wie sie soeben umgesetzt wurden - Vergleichsgrundlage
    fuer sync-config.py (dort per importlib geladen statt hier verdoppelt). Die meisten Schluessel haben eine
    Datei-Wirkung (siehe sync-config.py compute_diffs); Sprache/Commit-Verhalten haben keine (reines
    Verhalten/Hinweis), werden aber trotzdem gefuehrt, damit eine Aenderung ueberhaupt gemeldet wird - sonst
    faellt sie beim Abgleich durchs Raster (siehe Befund zu "Stack" unten). Bewusst NICHT gefuehrt: "Globale
    Ablage" (eigener, direkt aus AI-CONFIG.md gelesener Schalter von install-global.py, kein KEY_MAP-Eintrag,
    keine Wiederholungssemantik), "Code-Analyse"/"Struktur-Migration"/"Alter Orchestrator-Name" (einmalige
    Weg-2-Bootstrap-Werte fuer /apply-template, nach dem einmaligen Lauf ohne erneute Wirkung - siehe
    sync-config.py Kopfkommentar). Bei KI-Werkzeuge wird bewusst die RESULTIERENDE Entfernliste gespeichert
    (nicht die Roh-Kommaliste aus AI-CONFIG.md) - "leer = alle behalten" waere sonst nicht von "alle explizit
    genannt" zu unterscheiden."""
    return {
        "Projektname": values.get("PROJEKTNAME"),
        "Auftraggeber": values.get("AUFTRAGGEBER"),
        "Orchestrator": values.get("ORCHESTRATOR"),
        "Sprache": sprache,
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
        "Logging": logging_val,
        "Logging-Tiefe": logging_tiefe,
        "Wartung": wartung_val,
        "Wartungsaufgaben": wartungsaufgaben if wartung_val == "ein" else {},
        "Wartungsberichte": wartungsberichte,
        "Code-Optimierung": code_opt,
    }


DEFAULT_BRANCH_NAMES = {"main", "master"}


def init_base_from_default_branch(root: Path, cfg_tu: dict) -> str:
    """Projekt entsteht als Branch im Template-Checkout: base_commit = letzter gemeinsamer Commit mit dem
    Standard-Branch (main/master), damit `update-template.py` spaeter von dort mergen kann."""
    tu = _load_template_update_module()
    base = None
    quelle = None
    for cand in ("main", "master"):
        res = run_git(root, ["rev-parse", "--verify", "--quiet", cand])
        if res.returncode != 0:
            continue
        mb = run_git(root, ["merge-base", "HEAD", cand])
        if mb.returncode == 0 and mb.stdout.strip():
            base, quelle = mb.stdout.strip(), cand
            break
    if not base:
        res = run_git(root, ["rev-parse", "HEAD"])
        if res.returncode != 0 or not res.stdout.strip():
            return "kein Git-Commit gefunden - base_commit nicht gesetzt."
        base, quelle = res.stdout.strip(), "HEAD"
    cfg_tu["base_commit"] = base
    cfg_tu["template_remote"] = "origin"
    cfg_tu["template_branch"] = quelle if quelle != "HEAD" else cfg_tu.get("template_branch") or "main"
    try:
        tu.save_template_json(root, cfg_tu, root / ".claude" / "template.json")
    except Exception as e:
        return f"base_commit konnte nicht geschrieben werden: {e}"
    return (
        f"Projekt als Branch im Template: base_commit = {base[:7]} (aus '{quelle}'), "
        f"template_branch = {cfg_tu['template_branch']}. Updates spaeter per "
        "'update-template.py --check' gegen diesen Branch."
    )


def current_branch(root: Path):
    """Aktueller Branch-Name, oder None (detached HEAD / kein Git)."""
    res = run_git(root, ["rev-parse", "--abbrev-ref", "HEAD"])
    if res.returncode != 0:
        return None
    name = res.stdout.strip()
    return None if name in ("", "HEAD") else name


def template_repo_guard(root: Path):
    """Laeuft dieses Script im Template-Checkout selbst (Marker `is_template` in .claude/template.json)?

    Erlaubt ist das nur auf einem eigenen Branch - dann entsteht das neue Projekt als Branch des Templates,
    was eine gemeinsame Historie und damit spaetere Updates ohne zusaetzlichen Remote ermoeglicht. Auf dem
    Standard-Branch (main/master) waere es ein Unfall: das Template selbst wuerde seine Platzhalter
    verlieren. Gibt (ist_template, branch, fehlermeldung_oder_None) zurueck."""
    try:
        tu = _load_template_update_module()
        cfg_tu, _ = tu.load_template_json(root)
    except Exception:
        return False, None, None
    if not cfg_tu.get("is_template"):
        return False, current_branch(root), None
    # Der Marker wird mitgeklont. Ein Klon nach Anleitung hat aber einen Remote "template" (aus
    # `git remote rename origin template`) - dort ist main der richtige Arbeitsbranch, der Schutz muss
    # schweigen. Fehlt dieser Remote, ist es entweder das Template selbst oder ein Klon ohne Umbenennung -
    # in beiden Faellen ist die Meldung unten die richtige Antwort.
    res_remotes = run_git(root, ["remote"])
    if res_remotes.returncode == 0 and "template" in res_remotes.stdout.split():
        return False, current_branch(root), None
    branch = current_branch(root)
    if branch is None:
        return True, None, (
            "Dies ist der Template-Checkout selbst, und HEAD haengt an keinem Branch (detached HEAD).\n"
            "  Erst einen Branch anlegen: git switch -c projekt/<name>"
        )
    if branch in DEFAULT_BRANCH_NAMES:
        return True, branch, (
            f"Das hier ist noch ein unveraendertes Template und du arbeitest auf '{branch}' - ein --apply\n"
            "  wuerde es zerstoeren (Platzhalter weg, Werkzeug-Dateien geloescht). Drei Wege:\n"
            "    a) Projekt als Branch:   git switch -c projekt/<name>   (Updates spaeter per Merge aus dem\n"
            "       Standard-Branch, kein zusaetzlicher Remote noetig)\n"
            "    b) frisch geklont?       git remote rename origin template && git remote add origin\n"
            "       <eigene-Repo-URL>     (danach laeuft --apply auf main durch)\n"
            "    c) sauber trennen:       git clone <Template-URL> <projekt>, dann Weg b) dort"
        )
    return True, branch, None


def maybe_init_template_update(root: Path, ist_template: bool = False) -> str:
    """Ruft update-template.py --init per Subprocess auf, wenn ein Git-Remote 'template' existiert.
    `ist_template` kommt aus template_repo_guard() und muss uebergeben werden, weil der Marker zu diesem
    Zeitpunkt bereits aus template.json entfernt ist. Gibt eine Statuszeile fuer die Zusammenfassung."""
    tu = _load_template_update_module()
    cfg_tu, _ = tu.load_template_json(root)
    if cfg_tu.get("base_commit"):
        return "base_commit bereits gesetzt (apply-template.py/--init) - --init uebersprungen."
    res = run_git(root, ["remote"])
    remotes = res.stdout.split() if res.returncode == 0 else []
    if "template" not in remotes:
        # Sonderfall "Projekt als Branch im Template-Checkout": es gibt keinen Remote `template`, wohl aber
        # eine gemeinsame Historie mit dem Standard-Branch. Als Basis dient dessen letzter gemeinsamer
        # Commit - spaetere Updates laufen dann per Merge aus dem lokalen Standard-Branch bzw. aus `origin`.
        if ist_template or cfg_tu.get("is_template"):
            return init_base_from_default_branch(root, cfg_tu)
        return "kein Remote 'template' - base_commit nicht gesetzt."
    script = Path(__file__).resolve().parent / "update-template.py"
    py = sys.executable or "python3"
    try:
        res_init = subprocess.run(
            [py, str(script), "--init"],
            cwd=str(root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"update-template.py --init fehlgeschlagen: {e}"
    if res_init.returncode != 0:
        return f"update-template.py --init: {res_init.stderr.strip() or res_init.stdout.strip()}"
    return "update-template.py --init ok (base_commit gesetzt)."


# ---------------------------------------------------------------------------
# --dry-run
# ---------------------------------------------------------------------------


def cmd_dry_run(root: Path) -> int:
    cfg = load_config(root)
    values = compute_values(cfg)
    logging_val, logging_tiefe = logging_settings(cfg)
    remove_list = tools_to_remove(cfg)
    orch_modell, orch_unbekannt = normalize_orchestrator_modell(cfg)
    commit_verhalten, commit_verhalten_unbekannt = normalize_commit_verhalten(cfg)
    ideen_ablauf, ideen_ablauf_unbekannt = normalize_ideen_ablauf(cfg)
    testtiefe, testtiefe_unbekannt = normalize_testtiefe(cfg)
    schreibstil, schreibstil_unbekannt = normalize_schreibstil(cfg)
    feedback, feedback_unbekannt = normalize_feedback(cfg)
    feedback_takt, feedback_takt_unbekannt = normalize_feedback_takt(cfg)
    wartung_val, wartung_unbekannt = normalize_wartung(cfg)
    wartungsberichte, wartungsberichte_unbekannt = normalize_wartungsberichte(cfg)
    code_analyse, code_analyse_unbekannt = normalize_code_analyse(cfg)
    code_opt, code_opt_unbekannt, code_opt_hinweis = normalize_code_optimierung(cfg)
    guidelines_gewaehlt, guidelines_unbekannt = parse_coding_guidelines(cfg, root)
    struktur_migration, struktur_migration_unbekannt = normalize_struktur_migration(cfg)
    wartungsaufgaben_raw = cfg.get("wartungsaufgaben") or DEFAULT_WARTUNGSAUFGABEN
    wartungsaufgaben, wartungsaufgaben_fehler = parse_wartungsaufgaben(wartungsaufgaben_raw)

    lines = ["create-project.py --dry-run", ""]
    _werkzeug, _beleg, _geprueft = detect_ai_tool()
    if _werkzeug:
        _zusatz = "" if _geprueft else " (schwache Marke)"
        lines.append(f"Ausgefuehrt von: {_werkzeug} [{_beleg}]{_zusatz}"
                     " - im Interview als KI-Werkzeug vorauswaehlen, aber bestaetigen lassen.")
        lines.append("")
    # Selbstpruefung der fest verdrahteten Pfadlisten (siehe check_stale_remove_paths) laeuft hier mit:
    # --check allein wuerde niemand aufrufen, der Plan-Lauf dagegen steht in jeder Checkliste.
    for _warnung in check_stale_remove_paths(root):
        lines.append(_warnung)
    if len(lines) > 2:
        lines.append("")
    ist_template, branch, guard_fehler = template_repo_guard(root)
    if guard_fehler:
        lines.append("ACHTUNG - --apply wuerde hier abbrechen:")
        for _zeile in guard_fehler.split(chr(10)):
            lines.append("  " + _zeile)
        lines.append("")
    elif ist_template:
        lines.append(f"Projekt entsteht als Branch '{branch}' im Template-Checkout - der Basis-Commit wird "
                     "aus dem Standard-Branch abgeleitet, spaetere Updates laufen per Merge von dort.")
        lines.append("")
    if not (root / CONFIG_REL).exists():
        lines.append(f"Hinweis: {CONFIG_REL} nicht gefunden - es gelten Defaults.")
    lines.append("Werte:")
    for key in PLACEHOLDER_KEYS:
        val = values.get(key)
        if val is not None:
            lines.append(f"  {{{{{key}}}}} -> {val}")
        else:
            lines.append(f"  {{{{{key}}}}} -> bleibt Platzhalter (nichts angegeben)")

    lines.append("")
    lines.append(f"Logging: AI_LOG={logging_val}, AI_LOG_LEVEL={logging_tiefe}")

    lines.append("")
    if remove_list:
        lines.append("Zu entfernende Werkzeug-Dateien:")
        for tool in remove_list:
            for rel in TOOL_FILES.get(tool, []):
                lines.append(f"  {tool}: {rel}")
    else:
        lines.append("Zu entfernende Werkzeug-Dateien: keine (KI-Werkzeuge leer oder nicht gesetzt).")

    # Wer gerade laeuft, sollte nicht das eigene Werkzeug wegkonfigurieren: --apply wuerde die Dateien des
    # Assistenten entfernen, der den Befehl selbst ausfuehrt. Erlaubt bleibt es (jemand richtet ein Projekt
    # bewusst fuer ein anderes Werkzeug ein), aber ungefragt passieren darf es nicht.
    if _werkzeug and _werkzeug in remove_list:
        lines.append("")
        lines.append(f"ACHTUNG: {_werkzeug} fuehrt diesen Lauf aus, steht aber nicht in 'KI-Werkzeuge' - "
                     "--apply wuerde die eigenen Dateien entfernen.")
        lines.append("  Ist das gewollt (Projekt fuer ein anderes Werkzeug einrichten), bestaetigen lassen; "
                     "sonst 'KI-Werkzeuge' in AI-CONFIG.md ergaenzen.")

    lines.append("")
    if orch_unbekannt:
        lines.append(f"Orchestrator-Modell: \"{orch_unbekannt}\" ist kein bekannter Wert - --apply bricht "
                      "damit ab. Erlaubt: opus, sonnet, haiku, inherit.")
    else:
        lines.append(f"Orchestrator-Modell: {orch_modell}"
                      + (" (kein 'model'-Schluessel in .claude/settings.json)" if orch_modell == "inherit" else ""))

    lines.append("")
    if commit_verhalten_unbekannt:
        lines.append(f"Commit-Verhalten: \"{commit_verhalten_unbekannt}\" ist kein bekannter Wert - --apply "
                      "bricht damit ab. Erlaubt: automatisch, fragen, manuell.")
    else:
        lines.append("Commit-Verhalten: " + COMMIT_VERHALTEN_TEXT[commit_verhalten])
    for _wert, _unbek, _label, _texte, _erlaubt in (
        (ideen_ablauf, ideen_ablauf_unbekannt, "Ideen-Ablauf", IDEEN_ABLAUF_TEXT, IDEEN_ABLAUF_WERTE),
        (testtiefe, testtiefe_unbekannt, "Testtiefe", TESTTIEFE_TEXT, TESTTIEFE_WERTE),
        (schreibstil, schreibstil_unbekannt, "Schreibstil", SCHREIBSTIL_TEXT, SCHREIBSTIL_WERTE),
        (feedback, feedback_unbekannt, "Feedback", FEEDBACK_TEXT, FEEDBACK_WERTE),
        (feedback_takt, feedback_takt_unbekannt, "Feedback-Takt", FEEDBACK_TAKT_TEXT, FEEDBACK_TAKT_WERTE),
    ):
        if _unbek:
            lines.append(f"{_label}: \"{_unbek}\" ist kein bekannter Wert - --apply bricht damit ab. "
                         f"Erlaubt: {', '.join(sorted(_erlaubt))}.")
        else:
            lines.append(f"{_label}: " + _texte[_wert])

    lines.append("")
    if wartung_unbekannt:
        lines.append(f"Wartung: \"{wartung_unbekannt}\" ist kein bekannter Wert - --apply bricht damit ab. "
                      "Erlaubt: aus, ein.")
    elif wartung_val == "ein":
        if wartungsaufgaben_fehler:
            lines.append("Wartung: ein - ungueltige Wartungsaufgaben-Eintraege (--apply bricht damit ab): "
                          + ", ".join(wartungsaufgaben_fehler))
        else:
            lines.append("Wartung: ein - Aufgaben:")
            for name, intervall in wartungsaufgaben.items():
                lines.append(f"  {name}: {intervall} Tage" if intervall else f"  {name}: ereignisgesteuert")
    else:
        lines.append("Wartung: aus - zu entfernende Dateien:")
        for rel in MAINTENANCE_REMOVE_PATHS:
            lines.append(f"  {rel}")

    lines.append("")
    if wartungsberichte_unbekannt:
        lines.append(f"Wartungsberichte: \"{wartungsberichte_unbekannt}\" ist kein bekannter Wert - --apply "
                      "bricht damit ab. Erlaubt: intern, docs.")
    else:
        lines.append("Wartungsberichte: " + WARTUNGSBERICHTE_TEXT[wartungsberichte])
        if wartungsberichte == "docs" and wartung_val != "ein":
            lines.append("  ohne Wirkung, solange Wartung auf \"aus\" steht.")
        elif wartungsberichte == "docs" and not (root / "docs" / "maintenance" / "README.md").exists():
            lines.append("  --apply legt docs/maintenance/README.md an (docs/README.md muss der Index-Tabelle "
                          "danach von Hand ergaenzt werden).")

    lines.append("")
    if code_analyse_unbekannt:
        lines.append(f"Code-Analyse: \"{code_analyse_unbekannt}\" ist kein bekannter Wert - --apply bricht "
                     "damit ab. Erlaubt: nein, vorschlagen, fragen.")
    else:
        lines.append("Code-Analyse (nur Weg 2 /apply-template): " + CODE_ANALYSE_TEXT[code_analyse])

    lines.append("")
    if code_opt_unbekannt:
        lines.append(f"Code-Optimierung: \"{code_opt_unbekannt}\" ist kein bekannter Wert - --apply bricht "
                     "damit ab. Erlaubt: aus, ein, intensiv.")
    else:
        lines.append("Code-Optimierung: " + CODE_OPTIMIERUNG_TEXT[code_opt])
        if code_opt_hinweis:
            lines.append("  Hinweis: " + code_opt_hinweis)

    lines.append("")
    if guidelines_unbekannt:
        lines.append("Coding-Guidelines: unbekannt - " + ", ".join(guidelines_unbekannt)
                     + " (--apply bricht damit ab). Verfuegbar: "
                     + ", ".join(available_guidelines(root)))
    elif guidelines_gewaehlt:
        rest = [g for g in available_guidelines(root) if g not in guidelines_gewaehlt]
        lines.append("Coding-Guidelines: " + ", ".join(guidelines_gewaehlt)
                     + (" (entfernt werden: " + ", ".join(rest) + ")" if rest else ""))
    else:
        lines.append("Coding-Guidelines: keine - alle Bausteine werden entfernt "
                     "(spaeter per guidelines.py --add nachladbar)")

    lines.append("")
    if struktur_migration_unbekannt:
        lines.append(f"Struktur-Migration: \"{struktur_migration_unbekannt}\" ist kein bekannter Wert - "
                      "--apply bricht damit ab. Erlaubt: ja, nein, fragen.")
    else:
        lines.append("Struktur-Migration (nur Weg 2 /apply-template): "
                      + STRUKTUR_MIGRATION_TEXT[struktur_migration])
    alter_name = cfg.get("alter_orchestrator_name")
    if alter_name:
        lines.append(f"Alter Orchestrator-Name: \"{alter_name}\" - wird bei der Struktur-Migration durch "
                      f"\"{values['ORCHESTRATOR']}\" ersetzt.")
    else:
        lines.append("Alter Orchestrator-Name: leer - Kandidaten werden erkannt (migrate-project.py --plan).")

    warnungen = config_warnungen(cfg)
    unbekannt = unbekannte_werkzeuge(cfg)
    if warnungen or unbekannt:
        lines.append("")
        lines.append("Hinweise zu AI-CONFIG.md:")
        for w in warnungen:
            lines.append(f"  {w}")
        for name in unbekannt:
            lines.append(f"  KI-Werkzeuge: \"{name}\" ist kein bekannter Name - --apply bricht damit ab. "
                         f"Erlaubt: {', '.join(sorted(set(TOOL_CANON.values())))}")

    open_keys = [k for k in PLACEHOLDER_KEYS if values.get(k) is None]
    lines.append("")
    lines.append("Offene Werte (bleiben Platzhalter): " + (", ".join(open_keys) if open_keys else "keine"))

    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------------------
# --apply
# ---------------------------------------------------------------------------


def cmd_apply(root: Path) -> int:
    cfg = load_config(root)
    values = compute_values(cfg)
    logging_val, logging_tiefe = logging_settings(cfg)

    # Vor jeder Aenderung: ein Tippfehler in KI-Werkzeuge/Orchestrator-Modell/Wartung darf nicht dazu
    # fuehren, dass stillschweigend Dateien geloescht oder eine falsche Konfiguration geschrieben wird.
    unbekannt = unbekannte_werkzeuge(cfg)
    orch_modell, orch_unbekannt = normalize_orchestrator_modell(cfg)
    commit_verhalten, commit_verhalten_unbekannt = normalize_commit_verhalten(cfg)
    ideen_ablauf, ideen_ablauf_unbekannt = normalize_ideen_ablauf(cfg)
    testtiefe, testtiefe_unbekannt = normalize_testtiefe(cfg)
    schreibstil, schreibstil_unbekannt = normalize_schreibstil(cfg)
    feedback, feedback_unbekannt = normalize_feedback(cfg)
    feedback_takt, feedback_takt_unbekannt = normalize_feedback_takt(cfg)
    wartung_val, wartung_unbekannt = normalize_wartung(cfg)
    wartungsberichte, wartungsberichte_unbekannt = normalize_wartungsberichte(cfg)
    code_analyse, code_analyse_unbekannt = normalize_code_analyse(cfg)
    code_opt, code_opt_unbekannt, code_opt_hinweis = normalize_code_optimierung(cfg)
    guidelines_gewaehlt, guidelines_unbekannt = parse_coding_guidelines(cfg, root)
    struktur_migration, struktur_migration_unbekannt = normalize_struktur_migration(cfg)
    wartungsaufgaben_raw = cfg.get("wartungsaufgaben") or DEFAULT_WARTUNGSAUFGABEN
    wartungsaufgaben, wartungsaufgaben_fehler = parse_wartungsaufgaben(wartungsaufgaben_raw)

    fehler = False
    if unbekannt:
        print("Fehler: --apply abgebrochen, AI-CONFIG.md § KI-Werkzeuge nicht eindeutig:", file=sys.stderr)
        for name in unbekannt:
            print(f"  - unbekannter Name: \"{name}\"", file=sys.stderr)
        print(f"  Erlaubt sind: {', '.join(sorted(set(TOOL_CANON.values())))} "
              "(leer = alle behalten, nichts wird entfernt).", file=sys.stderr)
        fehler = True
    if orch_unbekannt:
        print(f"Fehler: --apply abgebrochen, AI-CONFIG.md § Orchestrator-Modell nicht eindeutig: "
              f"\"{orch_unbekannt}\" - erlaubt sind opus, sonnet, haiku, inherit.", file=sys.stderr)
        fehler = True
    for _unbek, _label, _erlaubt in (
        (ideen_ablauf_unbekannt, "Ideen-Ablauf", IDEEN_ABLAUF_WERTE),
        (testtiefe_unbekannt, "Testtiefe", TESTTIEFE_WERTE),
        (schreibstil_unbekannt, "Schreibstil", SCHREIBSTIL_WERTE),
        (feedback_unbekannt, "Feedback", FEEDBACK_WERTE),
        (feedback_takt_unbekannt, "Feedback-Takt", FEEDBACK_TAKT_WERTE),
    ):
        if _unbek:
            print(f"Fehler: AI-CONFIG.md {_label}: unbekannter Wert \"{_unbek}\" - erlaubt sind "
                  f"{', '.join(sorted(_erlaubt))}.", file=sys.stderr)
            return 2
    if commit_verhalten_unbekannt:
        print(f"Fehler: --apply abgebrochen, AI-CONFIG.md § Commit-Verhalten nicht eindeutig: "
              f"\"{commit_verhalten_unbekannt}\" - erlaubt sind automatisch, fragen, manuell.", file=sys.stderr)
        fehler = True
    if wartung_unbekannt:
        print(f"Fehler: --apply abgebrochen, AI-CONFIG.md § Wartung nicht eindeutig: \"{wartung_unbekannt}\" - "
              "erlaubt sind aus, ein.", file=sys.stderr)
        fehler = True
    if wartungsberichte_unbekannt:
        print(f"Fehler: --apply abgebrochen, AI-CONFIG.md § Wartungsberichte nicht eindeutig: "
              f"\"{wartungsberichte_unbekannt}\" - erlaubt sind intern, docs.", file=sys.stderr)
        fehler = True
    if code_analyse_unbekannt:
        print(f"Fehler: --apply abgebrochen, AI-CONFIG.md § Code-Analyse nicht eindeutig: "
              f"\"{code_analyse_unbekannt}\" - erlaubt sind nein, vorschlagen, fragen.", file=sys.stderr)
        fehler = True
    if code_opt_unbekannt:
        print(f"Fehler: --apply abgebrochen, AI-CONFIG.md § Code-Optimierung nicht eindeutig: "
              f"\"{code_opt_unbekannt}\" - erlaubt sind aus, ein, intensiv.", file=sys.stderr)
        fehler = True
    if guidelines_unbekannt:
        print("Fehler: --apply abgebrochen, AI-CONFIG.md § Coding-Guidelines kennt diese Regelsaetze nicht: "
              + ", ".join(guidelines_unbekannt), file=sys.stderr)
        print("  Verfuegbar: " + ", ".join(available_guidelines(root)), file=sys.stderr)
        fehler = True
    if struktur_migration_unbekannt:
        print(f"Fehler: --apply abgebrochen, AI-CONFIG.md § Struktur-Migration nicht eindeutig: "
              f"\"{struktur_migration_unbekannt}\" - erlaubt sind ja, nein, fragen.", file=sys.stderr)
        fehler = True
    if wartung_val == "ein" and wartungsaufgaben_fehler:
        print("Fehler: --apply abgebrochen, AI-CONFIG.md § Wartungsaufgaben ungueltig: "
              + ", ".join(wartungsaufgaben_fehler), file=sys.stderr)
        print("  Format: name=tage, name=tage (tage: Zahl >= 0, oder leer/'null'/'-' fuer "
              "ereignisgesteuert).", file=sys.stderr)
        fehler = True
    # Schutz vor dem teuersten Unfall: --apply direkt im Template-Checkout auf dem Standard-Branch.
    ist_template, branch, guard_fehler = template_repo_guard(root)
    if guard_fehler:
        print("Fehler: --apply abgebrochen. " + guard_fehler, file=sys.stderr)
        fehler = True
    if fehler:
        return 2

    remove_list = tools_to_remove(cfg)

    changed, remaining = replace_placeholders(root, values)
    removed_files = remove_tool_files(root, remove_list)
    logging_changed = set_logging_switch(root, logging_val, logging_tiefe)
    optimizer_entfernt = remove_optimizer_files(root) if code_opt == "aus" else []
    guidelines_entfernt = apply_coding_guidelines(root, guidelines_gewaehlt)
    intro_entfernt = remove_template_intro(root)
    applied_config = build_applied_config(
        values, orch_modell, logging_val, logging_tiefe, wartung_val, wartungsaufgaben,
        wartungsberichte, code_opt, guidelines_gewaehlt, remove_list,
        sprache=cfg.get("sprache"), commit_verhalten=commit_verhalten,
        ideen_ablauf=ideen_ablauf, testtiefe=testtiefe, schreibstil=schreibstil,
        feedback=feedback, feedback_takt=feedback_takt,
    )
    write_template_json_values(root, values, applied_config)
    init_status = maybe_init_template_update(root, ist_template)
    model_status = set_orchestrator_model(root, orch_modell)

    if wartung_val == "ein":
        write_maintenance_status(root, wartungsaufgaben)
        aufgaben_txt = ", ".join(
            f"{name}={intervall}" if intervall else f"{name}=ereignisgesteuert"
            for name, intervall in wartungsaufgaben.items()
        )
        wartung_status = f"ein - status.json geschrieben ({aufgaben_txt})"
        fehlende_runner = check_maintenance_runner_files(root)
        if fehlende_runner:
            wartung_status += (
                "; ACHTUNG: " + ", ".join(fehlende_runner) + " fehlen in .claude/maintenance/ (typisch fuer "
                "ein per apply-template.py nachgeruestetes Projekt) - holen per 'git show "
                "template/<branch>:.claude/maintenance/<datei> > .claude/maintenance/<datei>' je fehlender "
                "Datei, oder erneut apply-template.py ausfuehren."
            )
    else:
        removed_maintenance = remove_maintenance_files(root)
        hook_removed, hooks_fremde = remove_maintenance_hook(root)
        claude_refs = remove_maintenance_references(root)
        teile = [
            "entfernt: " + (", ".join(removed_maintenance) if removed_maintenance else "(keine, bereits entfernt)"),
            "Hook/Permissions " + ("entfernt" if hook_removed else "(nicht vorhanden)"),
            "CLAUDE.md " + (
                "Agenten-/Skill-Zeile entfernt" if claude_refs["agent_zeile"] and claude_refs["skill_zeile"]
                else "teilweise angepasst (siehe Bericht)" if claude_refs["agent_zeile"] or claude_refs["skill_zeile"]
                else "(Zeilen nicht gefunden oder Datei fehlt)"
            ),
        ]
        for f in hooks_fremde:
            teile.append(
                f"fremder Hook mit maintenance-check.py belassen: {f} - ACHTUNG: maintenance-check.py wurde "
                "entfernt, dieser Hook zeigt damit ins Leere."
            )
        wartung_status = "aus - " + "; ".join(teile)

    if wartungsberichte == "docs" and wartung_val == "ein":
        docs_maintenance_neu = setup_docs_maintenance_reports(root)
        wartungsberichte_status = WARTUNGSBERICHTE_TEXT["docs"] + (
            " - docs/maintenance/README.md neu angelegt" if docs_maintenance_neu
            else " - docs/maintenance/README.md bereits vorhanden"
        )
    elif wartungsberichte == "docs":
        wartungsberichte_status = (WARTUNGSBERICHTE_TEXT["docs"]
                                   + " - nichts angelegt, weil die Wartung ausgeschaltet ist")
    else:
        wartungsberichte_status = WARTUNGSBERICHTE_TEXT["intern"]

    lines = ["create-project.py --apply", ""]
    for w in config_warnungen(cfg):
        lines.append(f"Hinweis: {w}")
    if config_warnungen(cfg):
        lines.append("")
    lines.append(f"Gesetzte Werte: {', '.join(k + '=' + str(v) for k, v in values.items() if v is not None)}")
    lines.append(f"Dateien mit ersetzten Platzhaltern: {len(changed)}")
    lines.append(f"Entfernte Werkzeug-Dateien: {', '.join(removed_files) if removed_files else '(keine)'}")
    lines.append(f"Logging: AI_LOG={logging_val}, AI_LOG_LEVEL={logging_tiefe}" + (" (geschrieben)" if logging_changed else " (unveraendert)"))
    lines.append(f"Orchestrator-Modell: {orch_modell} - {model_status}")
    lines.append("Commit-Verhalten: " + COMMIT_VERHALTEN_TEXT[commit_verhalten])
    lines.append("Ideen-Ablauf: " + IDEEN_ABLAUF_TEXT[ideen_ablauf])
    lines.append("Testtiefe: " + TESTTIEFE_TEXT[testtiefe])
    lines.append("Schreibstil: " + SCHREIBSTIL_TEXT[schreibstil])
    lines.append("Feedback: " + FEEDBACK_TEXT[feedback])
    lines.append("Feedback-Takt: " + FEEDBACK_TAKT_TEXT[feedback_takt])
    lines.append(f"Wartung: {wartung_status}")
    lines.append(f"Wartungsberichte: {wartungsberichte_status}")
    if wartungsberichte == "docs":
        lines.append("  Bitte docs/maintenance/ noch in docs/README.md eintragen.")
    lines.append("Code-Analyse (nur Weg 2 /apply-template): " + CODE_ANALYSE_TEXT[code_analyse])
    lines.append("Code-Optimierung: " + CODE_OPTIMIERUNG_TEXT[code_opt]
                 + (" (entfernt: " + ", ".join(optimizer_entfernt) + ")" if optimizer_entfernt else "")
                 + (" - Hinweis: " + code_opt_hinweis if code_opt_hinweis else ""))
    lines.append("Coding-Guidelines: " + (", ".join(guidelines_gewaehlt) if guidelines_gewaehlt else "keine")
                 + (" (entfernt: " + ", ".join(guidelines_entfernt) + ")" if guidelines_entfernt else ""))
    lines.append("Struktur-Migration (nur Weg 2 /apply-template): "
                  + STRUKTUR_MIGRATION_TEXT[struktur_migration])
    alter_name = cfg.get("alter_orchestrator_name")
    if alter_name:
        lines.append(f"Alter Orchestrator-Name: \"{alter_name}\" - wird bei der Struktur-Migration durch "
                      f"\"{values['ORCHESTRATOR']}\" ersetzt.")
    else:
        lines.append("Alter Orchestrator-Name: leer - Kandidaten werden erkannt (migrate-project.py --plan).")
    if intro_entfernt:
        lines.append("Nur-Template-Dateien entfernt (gelten nicht fuer dieses Projekt): "
                     + ", ".join(intro_entfernt))
    lines.append(f"template.json: {init_status}")

    lines.append("")
    if remaining:
        lines.append(f"Offene Platzhalter (max. 20 gezeigt):")
        for entry in remaining:
            lines.append(f"  {entry}")
    else:
        lines.append("Offene Platzhalter: keine (ausser den bekannten Fundstellen in checklists.md/create-project SKILL.md).")

    lines.append("")
    lines.append("AI-CONFIG-Abschnitte (Hinweis fuer die Doku-Befuellung durch den Skill):")
    for name in SECTION_NAMES:
        content = cfg["sections"].get(name) or "(leer)"
        lines.append(f"  ## {name}: {content if content != '(leer)' else content}")

    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------------------
# --finish
# ---------------------------------------------------------------------------


TEMPLATE_LINE_MARKER = "Wird im Rahmen der Checkliste"
LEDGER_EMPTY_MARKER = "noch kein Eintrag"

# Vermerk, den --finish vor die erste Zeile von AI-CONFIG.md setzt - macht --finish idempotent (steht er
# schon da, war die Einrichtung bereits abgeschlossen) und dient maintenance-check.py als Signal, dass das
# Projekt fertig angelegt ist (vorher waeren alle Wartungsaufgaben "noch nie gelaufen" - kein echter
# Faelligkeitszustand, siehe dort). Gleicher Text dort dupliziert, weil maintenance-check.py setup-lib.py
# nicht importiert.
FINISH_MARKER_TEXT = "Einrichtung abgeschlossen am"

# Ersetzt die Freitext-Abschnitte "## Ziel" .. "## Sonstiges" (SECTION_NAMES) - ihr Inhalt ist zu diesem
# Zeitpunkt in docs/project/ eingearbeitet, siehe Vorbedingungen unten.
FINISH_REPLACEMENT_SECTION = (
    "## Projektbeschreibung\n"
    "\n"
    "Die Angaben aus der Einrichtung sind in `docs/project/project_description.md` und `architecture.md`\n"
    "eingearbeitet — dort weiterpflegen, nicht hier.\n"
)


def cmd_finish(root: Path) -> int:
    config_path = root / CONFIG_REL
    if not config_path.exists():
        print(f"Fehler: {CONFIG_REL} fehlt - Einrichtung kann nicht abgeschlossen werden.", file=sys.stderr)
        return 2

    try:
        config_text, config_newline = _read_text_preserve_newline(config_path, encoding="utf-8-sig")
    except (UnicodeDecodeError, OSError) as e:
        print(f"Fehler: {CONFIG_REL} konnte nicht gelesen werden: {e}", file=sys.stderr)
        return 2

    erste_zeile = config_text.split("\n", 1)[0] if config_text else ""
    if FINISH_MARKER_TEXT in erste_zeile:
        print(f"{CONFIG_REL}: Einrichtung bereits abgeschlossen - keine Aenderung.")
        return 0

    pd_path = root / "docs" / "project" / "project_description.md"
    ledger_path = root / "docs" / "ai" / "ledger.md"

    problems = []
    if pd_path.exists():
        try:
            pd_text = pd_path.read_text(encoding="utf-8")
        except OSError:
            pd_text = ""
        if TEMPLATE_LINE_MARKER in pd_text:
            problems.append(
                "docs/project/project_description.md enthaelt noch die Vorlagenzeile "
                f"'{TEMPLATE_LINE_MARKER}' - erst befuellen."
            )
    else:
        problems.append("docs/project/project_description.md fehlt.")

    if ledger_path.exists():
        try:
            ledger_text = ledger_path.read_text(encoding="utf-8")
        except OSError:
            ledger_text = ""
        if LEDGER_EMPTY_MARKER in ledger_text:
            problems.append("docs/ai/ledger.md hat noch keinen echten Eintrag - erst Ledger-Eintrag schreiben.")
    else:
        problems.append("docs/ai/ledger.md fehlt.")

    if problems:
        print("Fehler: --finish abgebrochen, Vorbedingungen nicht erfuellt:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2

    ziel_match = re.search(r"(?m)^##\s+Ziel\s*$", config_text)
    kopf = config_text[: ziel_match.start()] if ziel_match else config_text
    kopf = kopf.rstrip("\n")

    heute = time.strftime("%Y-%m-%d")
    vermerk = (
        f"> {FINISH_MARKER_TEXT} {heute} — die Tabellen oben bleiben in Kraft und werden per "
        "`sync-config.py` weiter laufend abgeglichen."
    )
    neuer_text = vermerk + "\n\n" + kopf + "\n\n" + FINISH_REPLACEMENT_SECTION

    try:
        _write_text_preserve_newline(config_path, neuer_text, config_newline)
    except OSError as e:
        print(f"Fehler: {CONFIG_REL} konnte nicht geschrieben werden: {e}", file=sys.stderr)
        return 2

    print(f"{CONFIG_REL} fortgeschrieben - Einrichtung abgeschlossen, Datei bleibt bestehen "
          "(Tabellen wirken weiterhin, per sync-config.py).")
    return 0


# ---------------------------------------------------------------------------
# main / Argument-Parsing
# ---------------------------------------------------------------------------


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="create-project.py",
        description="AI-CONFIG.md einlesen und ein neues Projekt aus dem Template zuschneiden (Weg 1).",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="Plan anzeigen, nichts aendern (Default)")
    group.add_argument("--apply", action="store_true", help="Platzhalter ersetzen, Werkzeug-Dateien entfernen, Werte speichern")
    group.add_argument("--finish", action="store_true",
                        help="Vorbedingungen pruefen, AI-CONFIG.md fortschreiben (bleibt bestehen)")
    group.add_argument(
        "--detect", action="store_true",
        help="Nur melden, welches KI-Werkzeug diesen Lauf ausfuehrt (aus der Prozessumgebung), nichts aendern")
    group.add_argument(
        "--check", action="store_true",
        help="Selbstpruefung: fest verdrahtete Pfadlisten (STALE_PATH_CHECK_LISTS) gegen das Repo pruefen, "
        "aendert nichts (Exit 0, auch bei Warnungen)",
    )
    return parser


def _run(argv) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = _find_root()

    if not (root / "AGENTS.md").exists():
        print(
            f"Fehler: {root} sieht nicht nach einem Projekt aus diesem Template aus (AGENTS.md fehlt). "
            "Aufruf im Projekt-Root pruefen (bzw. CLAUDE_PROJECT_DIR).",
            file=sys.stderr,
        )
        return 2

    if args.detect:
        werkzeug, beleg, geprueft = detect_ai_tool()
        if werkzeug:
            zusatz = "" if geprueft else "  (schwache Marke - Quelltextfund oder Konvention, siehe AGENT_MARKERS)"
            print(f"Erkanntes KI-Werkzeug: {werkzeug}   [{beleg}]{zusatz}")
        else:
            print("Kein KI-Werkzeug erkannt - im Interview nachfragen statt vorauswaehlen.")
        return 0
    if args.check:
        warnungen = check_stale_remove_paths(root)
        print("\n".join(warnungen) if warnungen else "Selbstpruefung ok: alle gelisteten Pfade vorhanden.")
        return 0
    if args.apply:
        return cmd_apply(root)
    if args.finish:
        return cmd_finish(root)
    return cmd_dry_run(root)


def _setup_already_complete(root: Path) -> bool:
    """True, wenn .claude/template.json bereits `setup_complete: true` traegt - dann darf die
    Ersteinrichtung nicht mehr laufen, auch wenn diese Bibliothek direkt statt ueber den (dann schon
    entfernten) Wrapper create-project.py aufgerufen wird."""
    template_json = root / ".claude" / "template.json"
    if not template_json.exists():
        return False
    try:
        cfg = json.loads(template_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return isinstance(cfg, dict) and bool(cfg.get("setup_complete"))


def main() -> int:
    try:
        root = _find_root()
        if _setup_already_complete(root) and "--detect" not in sys.argv[1:]:
            print(
                "Fehler: Einrichtung ist abgeschlossen, Ersteinrichtung nicht mehr moeglich; fuer laufende "
                "Aenderungen sync-config.py nutzen.",
                file=sys.stderr,
            )
            return 2
        return _run(sys.argv[1:])
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 - darf nie mit Traceback nach aussen dringen
        print(f"create-project: Fehler: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
