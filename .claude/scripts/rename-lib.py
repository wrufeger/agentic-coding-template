#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Bibliothek fuer Weg 2 ("Projekt nachruesten") - der duenne CLI-Wrapper .claude/scripts/migrate-project.py
# laedt dieses Modul und ruft main() auf. Der Wrapper wird von finish-setup.py beim Abschluss der
# Einrichtung entfernt, diese Datei bleibt dauerhaft bestehen (sync-config.py braucht ihre Funktionen fuer
# den laufenden AI-CONFIG.md-Abgleich).
#
# Zweck: Weg 2 ("Projekt nachruesten") von "nur ergaenzen" auf "auf Template-Struktur migrieren" erweitern.
#        Laeuft IM ZIELREPO (nicht im Template-Checkout), nachdem apply-template.py bereits dorthin
#        kopiert hat. Erkennt vorhandene KI-Arbeitsordner (z.B. fable/, ai/, docs/ki/) samt ihrer
#        Arbeitsdateien (Board/Aufgaben/Fragen/Ledger/Backlog/Checklisten unter beliebigem Namen) und
#        schlaegt vor, sie nach docs/ai/<template-name> zu verschieben; erkennt Dateien, die im Ziel UND im
#        Template existieren und sich inhaltlich unterscheiden (Zusammenfuehren noetig); erkennt einen im
#        Projekt fest verwendeten Orchestrator-Rufnamen (z.B. "Fable") und kann ihn projektweit durch den
#        neuen Namen ersetzen. Siehe .claude/skills/act-apply-template/SKILL.md,
#        docs/ai/checklists.md § "Projekt nachruesten". Reine Python-Stdlib, kein Paket noetig.
#
# Aufruf:
#   python .claude/scripts/migrate-project.py --plan (Default)
#       Erkennt und zeigt den Migrationsplan (Verschieben/gitignorierte Kandidaten/Zusammenfuehren/Fremde
#       KI-Regeldateien/Orchestrator-Name/leere Altordner), schreibt nichts. Exit 0, auch wenn nichts zu tun
#       ist.
#   python .claude/scripts/migrate-project.py --apply
#       Fuehrt den Plan aus: verschiebt Arbeitsdateien per 'git mv' nach docs/ai/<template-name>
#       (Historie bleibt erhalten), loest Zielkollisionen auf (inhaltsgleich -> Altdatei geloescht,
#       unterschiedlich -> Altdatei als docs/ai/<name>.alt.md danebengelegt). Kandidaten, die laut
#       'git check-ignore' im alten Ordner bewusst gitignoriert waren, werden NICHT verschoben, sondern nur
#       gemeldet (bei Bedarf von Hand verschieben). Fuehrt danach automatisch die Orchestrator-Umbenennung
#       aus, wenn ein Name per --rename-orchestrator uebergeben oder in AI-CONFIG.md § "Alter
#       Orchestrator-Name" gesetzt ist - die Bestaetigung (siehe --rename-orchestrator) gilt dabei als
#       erteilt, weil der Plan vorher angezeigt wurde. Vorbedingung: sauberer Arbeitsbaum (git status
#       --porcelain leer) - sonst Exit 2, damit die Migration bei Bedarf rueckgaengig gemacht werden kann.
#       Kein Git-Repo -> Exit 2.
#   python .claude/scripts/migrate-project.py --rename-orchestrator ALT=NEU [--yes]
#       Nur die Namensersetzung (auch einzeln nutzbar, ohne Struktur-Migration). Zeigt zuerst eine
#       Trefferliste (Datei:Zeile, Zeile auf ca. 100 Zeichen gekuerzt, Treffer in [[...]] markiert - bei
#       vielen Treffern die ersten 40 plus Gesamtzahl, siehe collect_rename_hits) sowie je Datei, wie viele
#       Treffer ersetzt wuerden und wie viele wegen Markdown-Schutz uebersprungen werden (siehe unten);
#       schreibt aber nichts und braucht kein --yes (Exit 0). Ohne --yes endet der Lauf mit dem Hinweis,
#       vorher zu committen und zur Bestaetigung --yes anzuhaengen. Erst mit --yes wird tatsaechlich
#       geschrieben - dafuer gilt dieselbe Vorbedingung wie --apply: Git-Repo, sauberer Arbeitsbaum, sonst
#       Exit 2. Ausgelassen werden AI-CONFIG.md, .claude/scripts/*.py, Binaerdateien, nicht versionierte
#       Dateien und die Ordner aus config-lib.py EXCLUDE_DIR_NAMES_REPLACE (node_modules, .venv, dist,
#       build, ...). In .md-Dateien werden zusaetzlich
#       eingerueckte Codebloecke (nur wenn ihnen eine Leerzeile vorausgeht, siehe unten), Fenced Code
#       Blocks (auch in Blockzitaten), Inline-Code in Backticks, URLs (http(s)://, www.) und plausible
#       Pfad-/Dateiangaben mit "/" (z.B. docs/fable/README.md, nicht aber beliebige Wort/Wort-Token)
#       ausgemaskiert - dort wird nie ersetzt, auch nicht mit --yes. Zeilenenden und BOM bleiben erhalten.
#       Mit --plan kombiniert bleibt es immer eine reine Vorschau (auch mit --yes). ACHTUNG: Die Maskierung
#       ist ein Heuristik-Scanner ohne echten Markdown-Parser (kein Fremdpaket) - bekannte Luecke: Inline-
#       Code in Backticks, das ueber einen Zeilenumbruch geht, wird nicht erkannt und damit doch ersetzt.
#       Ergebnis nach dem Schreiben (--yes) deshalb immer mit 'git diff' pruefen (die Ausgabe erinnert
#       daran).
#   python .claude/scripts/migrate-project.py --status
#       Kurzuebersicht: was ist bereits Template-konform, was nicht (Anzahl erkannter Altordner/
#       Verschiebungen/gitignorierter Kandidaten/Zusammenfuehrungen, Orchestrator-Kandidaten).
#
# Erkennung KI-Arbeitsordner (find_ai_dirs): Verzeichnisse bis Tiefe 2 (ohne .git, node_modules, .venv,
# dist, build, .claude), die mindestens eine Datei mit bekanntem Arbeitsdatei-Namen enthalten (siehe
# TARGET_PATTERNS) und dabei entweder selbst {fable, ai, ki, agent, agents, assistant, kiki, copilot}
# heissen - oder, bei beliebigem Namen, mindestens zwei solche Dateien haben. Der Name allein reicht
# bewusst nicht: ein echter Quellcode-Ordner src/ai/ oder Fachdoku unter docs/ki/ wuerde sonst mitwandern.
# Verschoben werden nur .md-Dateien direkt im Ordner (keine Unterordner, kein Quellcode). Davon werden laut
# 'git check-ignore' bewusst gitignorierte Dateien vorab ausgenommen (Punkt 10 der Umbauliste) - eine
# private Notiz im alten Ordner soll nicht in docs/ai/ landen und in den Index geraten.
# docs/ai/ selbst gilt nie als "alt".
#
# Fremde KI-Regeldateien anderer Werkzeuge (find_foreign_ai_regelfiles, Punkt 18 der Umbauliste): .junie/,
# .github/instructions/, .clinerules (Datei oder Ordner), .windsurfrules, .roo/, .roorules, .cursorrules
# (alte Cursor-Form vor .cursor/rules/), .continue/, sowie AGENT.md und eine nicht vom Template abstammende
# AGENTS.md im Root (erkannt am fehlenden Textausschnitt "anbieterneutrale Regeln" - die echte Template-
# AGENTS.md hat den in der Titelzeile). Anders als die KI-Arbeitsordner oben werden diese NICHT verschoben:
# ihr Inhalt sind Stil-/Sicherheitsregeln, die ein Assistent von Hand nach docs/project/coding_rules.md
# eintraegt, bevor die Datei/der Ordner durch einen Verweis auf AGENTS.md ersetzt wird - deshalb eine eigene
# Kategorie im Report statt eines Eintrags unter "Verschieben". Bereits als Werkzeug-Verweisdatei erfasste
# Dateien (GEMINI.md, .aider.conf.yml, .github/copilot-instructions.md, .cursor/**, siehe MERGE_ROOT_FILES/
# MERGE_DIRS) laufen weiter ueber die normale Zusammenfuehren-Erkennung und werden hier nicht doppelt
# gemeldet - fuer sie existiert eine Template-Fassung zum Vergleich.
#
# Prioritaetsregeln bei "Zusammenfuehren" (macht der Assistent, nicht dieses Script) - siehe PRIORITY_RULES:
# .claude/**, AGENTS.md, CLAUDE.md, docs/ai/checklists.md, docs/ai/README.md -> Template gewinnt;
# docs/ai/resources.md -> Template gewinnt, nur der Abschnitt "Eigene Quellen dieses Projekts" bleibt beim
# Projekt (die Datei pflegt das Template, nicht das Projekt); docs/ai/-Arbeitsdateien (sonst) -> Template-
# Struktur, Projekt-Inhalt; docs/project/** -> Projekt gewinnt (Ausnahme
# GEMINI.md/.aider.conf.yml/.github/copilot-instructions.md/docs/README.md/.cursor/** (Werkzeug-
# Verweisdateien) -> Template gewinnt, Projektergaenzungen einarbeiten; AI-CONFIG.md -> Projekt gewinnt
# (dort stehen die Werte des Projekts).
#
# Exit-Codes: 0 = ok (auch "nichts zu tun", auch die Trefferliste ohne --yes), 2 = Vorbedingungsfehler
# (kein Git, unsauberer Arbeitsbaum, ungueltiges --rename-orchestrator, Zielverzeichnis sieht nicht nach
# einem Projekt aus diesem Template aus). Ein Fehler dieses Scripts darf nie mit Traceback nach aussen
# dringen: main() laeuft komplett in try/except, Fehlermeldungen auf stderr.

import argparse
import bisect
import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

# Dieses Script laedt update-template.py/setup-lib.py aus dem Ziel dynamisch nach (siehe _load_module) -
# ohne dies wuerde ein reiner --plan-Lauf ein __pycache__/ im Ziel hinterlassen und damit "git status
# --porcelain" verschmutzen (blockiert dann faelschlich die Vorbedingung von --apply).
sys.dont_write_bytecode = True


def _load_sibling_module(filename: str, mod_name: str):
    """Laedt eine Datei aus demselben Ordner wie dieses Script (nicht aus einem Ziel-Root wie _load_module
    unten) - gleiches Muster wie in files-lib.py/setup-lib.py. dont_write_bytecode ist oben schon gesetzt,
    schreibt also kein __pycache__."""
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Nur fuer die gemeinsame Dateisammlung beim projektweiten Ersetzen (iter_repo_replace_files) - config-lib.py
# haengt selbst von nichts hier ab, kein Ring.
_config_lib = _load_sibling_module("config-lib.py", "_rename_lib_config")

# ---------------------------------------------------------------------------
# Erkennung KI-Arbeitsordner + Arbeitsdateien
# ---------------------------------------------------------------------------

EXCLUDE_DIR_NAMES = {".git", "node_modules", ".venv", "dist", "build", ".claude"}
KNOWN_DIR_NAMES = {"fable", "ai", "ki", "agent", "agents", "assistant", "kiki", "copilot"}

# Reihenfolge wichtig: spezifischere Ziele (Archive) zuerst pruefen, sonst faengt z.B. "aufgaben_archiv"
# schon das "aufgaben"-Muster von tasks.md ab.
CHECK_ORDER = [
    "tasks_archive.md",
    "questions_archive.md",
    "board.md",
    "tasks.md",
    "questions.md",
    "ledger.md",
    "backlog.md",
    "checklists.md",
]

TARGET_PATTERNS = {
    "board.md": [r"board", r"uebersicht", r"übersicht", r"overview", r"start", r"einstieg"],
    "tasks.md": [r"aufgaben", r"tasks", r"todo"],
    "tasks_archive.md": [
        r"aufgaben_archiv", r"tasks_archive", r"todo_archiv", r".*_erledigt",
    ],
    "questions.md": [r"fragen", r"questions"],
    "questions_archive.md": [r"fragen_archiv", r"questions_archive"],
    "ledger.md": [r"ledger", r"journal", r"chronik", r"verlauf", r"chatlog"],
    "backlog.md": [r"backlog", r"umbau", r"umbauliste", r"ideen", r"vorschlaege", r"vorschläge"],
    "checklists.md": [r"checkliste", r"checklists"],
}


def match_target(filename: str):
    """Ordnet einen Dateinamen einer Template-Zieldatei zu (siehe TARGET_PATTERNS), oder None."""
    p = Path(filename)
    if p.suffix.lower() != ".md":
        return None
    norm = p.stem.lower().lstrip("@").replace("-", "_")
    for target in CHECK_ORDER:
        for pat in TARGET_PATTERNS[target]:
            if re.search(pat, norm):
                return target
    return None


def is_ai_dir(dir_path: Path) -> bool:
    """Ein Ordner gilt nur dann als KI-Arbeitsordner, wenn er auch wirklich Arbeitsdateien enthaelt - ein
    bekannter Name allein reicht nicht, sonst wuerde ein echter Quellcode-Ordner (src/ai/, agents/) oder
    Fachdoku unter docs/ki/ mitgerissen und nach docs/ai/ verschoben."""
    needed = 1 if dir_path.name.lower() in KNOWN_DIR_NAMES else 2
    count = 0
    try:
        for f in dir_path.iterdir():
            if f.is_file() and match_target(f.name):
                count += 1
                if count >= needed:
                    return True
    except OSError:
        pass
    return False


def find_ai_dirs(root: Path):
    """Verzeichnisse bis Tiefe 2 (root-relativ), die wie ein alter KI-Arbeitsordner aussehen. docs/ai/
    selbst wird nie gemeldet."""
    result = []

    def walk(dir_path: Path, depth: int):
        try:
            children = sorted(dir_path.iterdir())
        except OSError:
            return
        for child in children:
            if not child.is_dir() or child.name in EXCLUDE_DIR_NAMES:
                continue
            rel = child.relative_to(root).as_posix()
            if rel == "docs/ai":
                continue
            if is_ai_dir(child):
                result.append(child)
            if depth < 2:
                walk(child, depth + 1)

    walk(root, 1)
    return result


def scan_ai_dir(ai_dir: Path):
    """Dateien eines KI-Ordners -> (matched: target->[Path], unmatched: [Path], in_unterordnern: [Path]).

    Nur die direkten Dateien werden zum Verschieben vorgesehen. Markdown in Unterordnern (typisch: ein
    `archiv/`) wird NICHT automatisch verschoben - die Struktur dort ist projektspezifisch und eine
    Zuordnung waere geraten. Solche Dateien werden aber gemeldet, damit sie nicht stillschweigend
    liegenbleiben, waehrend der Ordner ringsum leer wird."""
    matched, unmatched, in_unterordnern = {}, [], []
    try:
        children = sorted(ai_dir.iterdir())
    except OSError:
        return matched, unmatched, in_unterordnern
    for f in children:
        if f.is_dir():
            if f.name in EXCLUDE_DIR_NAMES:
                continue
            try:
                for sub in sorted(f.rglob("*.md")):
                    if sub.is_file():
                        in_unterordnern.append(sub)
            except OSError:
                pass
            continue
        if not f.is_file():
            continue
        target = match_target(f.name)
        if target:
            matched.setdefault(target, []).append(f)
        elif f.suffix.lower() == ".md":
            # Nur Markdown gilt als moegliche Arbeitsdatei. Alles andere (Quellcode, Bilder, Konfiguration)
            # bleibt liegen - es waere sonst nach docs/ai/ verschoben worden.
            unmatched.append(f)
    return matched, unmatched, in_unterordnern


def compute_ignored_paths(root: Path, paths):
    """Von 'paths' (absolute Path-Objekte unterhalb von root) die Teilmenge, die laut 'git check-ignore'
    ignoriert ist - als Menge root-relativer Posix-Pfade. Ein Batch-Aufruf (alle Kandidaten als Argumente)
    statt einem je Datei - bewusst nicht '--stdin': unter Windows haengt Python subprocess das Stdin einer
    Text-Pipe an das Zeilenende os.linesep (CRLF), git bekommt dann "pfad\\r\\n" und matcht nicht mehr. Kein
    Git-Repo (oder Git selbst nicht verfuegbar) -> leere Menge, kein Abbruch - siehe Punkt 10 der
    Umbauliste."""
    if not paths:
        return set()
    rels = sorted({p.relative_to(root).as_posix() for p in paths})
    try:
        res = run_git(root, ["check-ignore", "--"] + rels)
    except OSError:
        return set()
    if res.returncode not in (0, 1):
        return set()
    return {line for line in res.stdout.splitlines() if line}


def build_plan(root: Path):
    """Liefert (ai_dirs, moves, conflicts, in_unterordnern, ignoriert). moves: Liste (src, dest, note).
    conflicts: target -> Liste zusaetzlicher Kandidaten (die nicht verschoben, sondern als unzugeordnet
    gefuehrt werden). ignoriert: Kandidaten, die laut 'git check-ignore' im alten Ordner bewusst gitignoriert
    waren (private Notizen o.ae.) - werden nicht verschoben, sondern separat gemeldet (Punkt 10)."""
    ai_dirs = find_ai_dirs(root)
    target_candidates = {}
    unassigned = []
    in_unterordnern = []
    for d in ai_dirs:
        matched, unmatched, sub_md = scan_ai_dir(d)
        for target, paths in matched.items():
            target_candidates.setdefault(target, []).extend(paths)
        unassigned.extend(unmatched)
        in_unterordnern.extend(sub_md)

    all_candidates = [p for paths in target_candidates.values() for p in paths] + unassigned
    ignored_rels = compute_ignored_paths(root, all_candidates)
    ignored = [p for p in all_candidates if p.relative_to(root).as_posix() in ignored_rels]
    if ignored_rels:
        target_candidates = {
            target: [p for p in paths if p.relative_to(root).as_posix() not in ignored_rels]
            for target, paths in target_candidates.items()
        }
        target_candidates = {target: paths for target, paths in target_candidates.items() if paths}
        unassigned = [p for p in unassigned if p.relative_to(root).as_posix() not in ignored_rels]

    moves = []
    conflicts = {}
    docs_ai = root / "docs" / "ai"
    for target, paths in sorted(target_candidates.items()):
        paths_sorted = sorted(paths, key=lambda p: p.as_posix())
        primary = paths_sorted[0]
        moves.append((primary, docs_ai / target, None))
        if len(paths_sorted) > 1:
            rest = paths_sorted[1:]
            conflicts[target] = rest
            unassigned.extend(rest)

    for p in sorted(set(unassigned), key=lambda p: p.as_posix()):
        moves.append((p, docs_ai / p.name, "unzugeordnet"))

    return (
        ai_dirs,
        moves,
        conflicts,
        sorted(set(in_unterordnern), key=lambda p: p.as_posix()),
        sorted(set(ignored), key=lambda p: p.as_posix()),
    )


def compute_empty_dirs(root: Path, ai_dirs, moved_set=None):
    """Altordner, die nach den geplanten/ausgefuehrten Verschiebungen keine Datei mehr enthalten (rekursiv
    geprueft, nie automatisch geloescht)."""
    empty = []
    for d in ai_dirs:
        remaining = False
        for fp in d.rglob("*"):
            if fp.is_file() and (moved_set is None or fp not in moved_set):
                remaining = True
                break
        if not remaining:
            empty.append(d.relative_to(root).as_posix())
    return sorted(empty)


# ---------------------------------------------------------------------------
# Fremde KI-Regeldateien anderer Werkzeuge (Punkt 18 der Umbauliste)
# ---------------------------------------------------------------------------

# Einzeldateien im Root. ".clinerules" kann laut Cline-Konvention Datei ODER Ordner sein - deshalb zusaetzlich
# unten in FOREIGN_AI_DIRS.
FOREIGN_AI_FILES = [
    ".clinerules",     # Cline (Datei-Form)
    ".windsurfrules",  # Windsurf
    ".roorules",       # Roo Code (eingestellt, kommt in Altprojekten vor)
    ".cursorrules",    # alte Cursor-Form, vor .cursor/rules/
    "AGENT.md",        # Codex/andere
    "AGENTS.md",       # Codex/andere - nur wenn NICHT vom Template abstammend, siehe _TEMPLATE_AGENTS_MARKER
]

# Ordner, deren direkte und verschachtelte Dateien komplett gemeldet werden (kein Arbeitsdatei-Muster wie bei
# find_ai_dirs noetig - der Ordnername allein ist hier eindeutig einem Werkzeug zuzuordnen).
FOREIGN_AI_DIRS = [
    ".junie",               # JetBrains Junie
    ".github/instructions",  # Copilot (Ordner-Form der Custom Instructions)
    ".clinerules",          # Cline (Ordner-Form)
    ".roo",                 # Roo Code (eingestellt)
    ".continue",            # Continue
]

# Textausschnitt aus der Titelzeile dieser Datei ("AGENTS.md - anbieterneutrale Regeln fuer {{PROJEKTNAME}}")
# - bleibt nach der Platzhalter-Ersetzung erhalten, unabhaengig vom Projektnamen. Fehlt er in einer
# root-AGENTS.md, stammt sie nicht von diesem Template (z.B. eine eigene Codex-AGENTS.md) und gehoert in
# diese Kategorie statt in die normale Zusammenfuehren-Erkennung.
_TEMPLATE_AGENTS_MARKER = "anbieterneutrale Regeln"


def _count_lines(content: str) -> int:
    if not content:
        return 0
    return content.count("\n") + (0 if content.endswith("\n") else 1)


def find_foreign_ai_regelfiles(root: Path):
    """Fremde KI-Regeldateien/-ordner anderer Werkzeuge (FOREIGN_AI_FILES/FOREIGN_AI_DIRS) - werden anders
    als die KI-Arbeitsordner (find_ai_dirs) nie verschoben, nur gemeldet: ihr Inhalt (Stil-/
    Sicherheitsregeln) gehoert von Hand nach docs/project/coding_rules.md, danach wird die Datei/der Ordner
    durch einen Verweis auf AGENTS.md ersetzt. Gibt eine nach rel_path sortierte Liste (rel_path, Zeilenzahl)
    zurueck; Binaer-/nicht lesbare Dateien zaehlen mit 0 Zeilen."""
    found = {}

    def add(fp: Path):
        if not fp.is_file():
            return
        rel = fp.relative_to(root).as_posix()
        if rel in found:
            return
        content = _read_text_or_none(fp)
        found[rel] = _count_lines(content) if content is not None else 0

    for name in FOREIGN_AI_FILES:
        fp = root / name
        if not fp.is_file():
            continue
        if name == "AGENTS.md":
            content = _read_text_or_none(fp)
            if content is not None and _TEMPLATE_AGENTS_MARKER in content:
                continue  # stammt von diesem Template - normale Zusammenfuehren-Erkennung greift
        add(fp)

    for name in FOREIGN_AI_DIRS:
        dp = root / name
        if not dp.is_dir():
            continue
        try:
            children = sorted(dp.rglob("*"))
        except OSError:
            continue
        for fp in children:
            add(fp)

    return sorted(found.items())


# ---------------------------------------------------------------------------
# Zusammenfuehren-Kandidaten (Ziel und Template existieren, Inhalt unterscheidet sich)
# ---------------------------------------------------------------------------

MERGE_ROOT_FILES = [
    "AGENTS.md", "CLAUDE.md", "README.md", ".gitignore",
    # Punkt 15 der Umbauliste: weitere Werkzeug-Verweisdateien und Konfiguration, die im Zielrepo schon
    # eigenstaendig existieren koennen - .claude/settings.json passt hier hinein (Einzeldatei, nicht ueber
    # MERGE_DIRS erfasst, da die dortigen Eintraege nur .claude/agents und .claude/skills abdecken).
    "GEMINI.md", ".aider.conf.yml", ".github/copilot-instructions.md", "docs/README.md", "AI-CONFIG.md",
    ".claude/settings.json",
]
# docs/ai gehoert dazu, weil die Prioritaetsregeln unten ausdruecklich docs/ai/checklists.md und
# docs/ai/README.md nennen - ohne den Eintrag wuerden genau diese Dateien nie als "zusammenfuehren" gemeldet.
# .cursor gehoert dazu (Punkt 15) - dieselbe Werkzeug-Verweisdatei-Rolle wie GEMINI.md, nur als Ordner.
MERGE_DIRS = [".claude/agents", ".claude/skills", "docs/ai", "docs/project", ".cursor"]

PRIORITY_RULES = """.claude/**, AGENTS.md, CLAUDE.md, docs/ai/checklists.md, docs/ai/README.md  -> Template gewinnt
docs/ai/resources.md (Template pflegt die Linksammlung)                     -> Template gewinnt, nur
   Abschnitt "Eigene Quellen dieses Projekts" bleibt beim Projekt
docs/ai/ (Arbeitsdateien: board, tasks, questions, ledger, backlog)          -> Template-Struktur,
   Projekt-Inhalt
docs/project/**                                                             -> Projekt gewinnt
docs/project/coding_rules.md                                                -> strengere Regel gewinnt
README.md, .gitignore                                                       -> Projekt gewinnt,
   Template-Anteile werden ergaenzt
GEMINI.md, .aider.conf.yml, .github/copilot-instructions.md, docs/README.md,
.cursor/**                                                                  -> Template gewinnt,
   Projektergaenzungen einarbeiten
AI-CONFIG.md                                                                -> Projekt gewinnt (Projektwerte)"""


def priority_label(rel_path: str) -> str:
    if rel_path in ("AGENTS.md", "CLAUDE.md", "docs/ai/checklists.md", "docs/ai/README.md") or rel_path.startswith(".claude/"):
        return "Template gewinnt"
    # Vor der allgemeinen docs/ai/-Regel: die Datei pflegt das Template (kuratierte Linksammlung), nicht das
    # Projekt - nur ihr Abschnitt "Eigene Quellen dieses Projekts" gehoert dem Projekt.
    if rel_path == "docs/ai/resources.md":
        return 'Template gewinnt, nur Abschnitt "Eigene Quellen dieses Projekts" bleibt beim Projekt'
    if rel_path == "AI-CONFIG.md":
        return "Projekt gewinnt (Projektwerte)"
    if rel_path == "docs/project/coding_rules.md":
        return "strengere Regel gewinnt"
    if rel_path.startswith("docs/project/"):
        return "Projekt gewinnt"
    if rel_path.startswith("docs/ai/"):
        return "Template-Struktur, Projekt-Inhalt"
    if rel_path in ("README.md", ".gitignore"):
        return "Projekt gewinnt, ergaenzt"
    if rel_path in ("GEMINI.md", ".aider.conf.yml", ".github/copilot-instructions.md", "docs/README.md") \
            or rel_path.startswith(".cursor/"):
        return "Template gewinnt, Projektergaenzungen einarbeiten"
    return "Projekt gewinnt"


def find_merge_candidates(root: Path):
    candidates = []
    for rel in MERGE_ROOT_FILES:
        if (root / rel).is_file():
            candidates.append(rel)
    for d in MERGE_DIRS:
        dp = root / d
        if not dp.is_dir():
            continue
        for fp in sorted(dp.rglob("*")):
            if fp.is_file():
                candidates.append(fp.relative_to(root).as_posix())
    return candidates


def compute_merge_entries(root: Path):
    """Liste (rel_path, priority_label) fuer Dateien, die im Ziel UND im Template existieren und sich
    unterscheiden. Leer, wenn kein Template-Remote verfuegbar ist (dann nichts zu vergleichen)."""
    remote, ref = _template_ref(root)
    if not ref:
        return []
    entries = []
    for rel in find_merge_candidates(root):
        res = run_git(root, ["show", f"{ref}:{rel}"])
        if res.returncode != 0:
            continue  # nicht im Template vorhanden -> projektspezifisch, kein Zusammenfuehren noetig
        template_content = res.stdout
        try:
            local_content = (root / rel).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if local_content != template_content:
            entries.append((rel, priority_label(rel)))
    return entries


# ---------------------------------------------------------------------------
# Orchestrator-Name: Erkennung + Ersetzung
# ---------------------------------------------------------------------------

ORCH_PATTERNS = [
    re.compile(r"Orchestrator\s+([A-ZÄÖÜ][\wÄÖÜäöüß-]{1,30})"),
    re.compile(r"([A-ZÄÖÜ][\wÄÖÜäöüß-]{1,30})\s+ist\s+der\s+Orchestrator"),
    re.compile(r"Ich\s+bin\s+([A-ZÄÖÜ][\wÄÖÜäöüß-]{1,30})"),
]


def count_occurrences(root: Path, name: str) -> int:
    pattern = re.compile(r"(?<![\wÄÖÜäöüß])" + re.escape(name) + r"(?![\wÄÖÜäöüß])")
    total = 0
    for fp, _rel in _iter_text_files_for_rename(root):
        content = _read_text_or_none(fp)
        if content is None:
            continue
        total += len(pattern.findall(content))
    return total


def detect_orchestrator_names(root: Path, ai_dirs, moves):
    """Kandidaten fuer den bisherigen Orchestrator-Rufnamen, je Kandidat Trefferzahl im ganzen Repo,
    absteigend sortiert. Ersetzt NIE ungefragt."""
    names = {}
    for d in ai_dirs:
        n = d.name
        names.setdefault(n[:1].upper() + n[1:], None)

    text_sources = []
    for rel in ("CLAUDE.md", "AGENTS.md"):
        fp = root / rel
        if fp.is_file():
            try:
                text_sources.append(fp.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
    for src, dest, _note in moves:
        if dest.name == "board.md":
            try:
                text_sources.append(src.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass

    for text in text_sources:
        for pat in ORCH_PATTERNS:
            for m in pat.finditer(text):
                names.setdefault(m.group(1), None)

    result = []
    for name in names:
        if len(name) < 2:
            continue
        cnt = count_occurrences(root, name)
        if cnt > 0:
            result.append((name, cnt))
    result.sort(key=lambda x: (-x[1], x[0]))
    return result


def _rename_variants(alt: str, neu: str):
    """3 Varianten case-sensitiv: Fable->Neu, fable->neu, FABLE->NEU (Duplikate entfernt, falls alt/neu
    bereits eine bestimmte Schreibweise haben)."""
    pairs = [(alt, neu), (alt.lower(), neu.lower()), (alt.upper(), neu.upper())]
    seen = {}
    for a, n in pairs:
        if a not in seen:
            seen[a] = n
    return list(seen.items())


def _read_text_or_none(fp: Path):
    """Dateiinhalt als Text - None bei Binaerdatei (NUL-Byte), kaputtem UTF-8 oder Lesefehler. Gelesen wird
    ueber Bytes, damit Zeilenenden (CRLF) und ein BOM unveraendert erhalten bleiben."""
    try:
        raw = fp.read_bytes()
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _iter_text_files_for_rename(root: Path):
    """Kandidatendateien fuer die Rufname-Ersetzung - Sammlung per _config_lib.iter_repo_replace_files (nur
    versionierte Dateien, Ausschlussliste fuer Abhaengigkeits-/Build-Ordner wie node_modules, siehe dort/
    Backlog B22 - .claude/ bleibt bewusst drin, Agenten-/Skill-Dateien nennen den Rufnamen), zusaetzlich
    AI-CONFIG.md und alle .claude/scripts/*.py ausgenommen (Script-Code, kein Fliesstext)."""
    for fp, rel in _config_lib.iter_repo_replace_files(root, run_git):
        if rel == "AI-CONFIG.md":
            continue
        if rel.startswith(".claude/scripts/") and rel.endswith(".py"):
            continue
        yield fp, rel


# Punkt 11 der Umbauliste: in Markdown-Dateien werden Codebloecke, Inline-Code, URLs und Pfadangaben beim
# projektweiten Ersetzen ausgemaskiert (nicht angefasst) - sonst traefe die Ersetzung auch Beispiel-Code und
# https://<name>.io/-Links. Kein Fremdpaket, nur ein heuristischer Zeilen-/Regex-Scanner ohne echten
# Markdown-Parser - Ergebnis nach dem Schreiben (--yes) deshalb immer mit 'git diff' pruefen. Bekannte
# Luecke: mehrzeiliges Inline-Code in Backticks wird nicht erkannt (siehe _find_masked_spans_md).

# Optionales Blockzitat-Praefix (">", ggf. verschachtelt "> >") vor der eigentlichen Einrueckung/dem
# Fence-Marker - sonst matcht ein Fence innerhalb eines Blockzitats (Zeile beginnt mit ">") nicht.
_BLOCKQUOTE_PREFIX = r"^(?:[ \t]{0,3}>[ \t]?)*"
_FENCE_OPEN_RE = re.compile(_BLOCKQUOTE_PREFIX + r"[ \t]{0,3}(`{3,}|~{3,})[^\n]*$")


def _is_fence_close(line: str, fence_char: str, fence_len: int) -> bool:
    m = re.match(
        _BLOCKQUOTE_PREFIX + r"[ \t]{0,3}(" + re.escape(fence_char) + r"{" + str(fence_len) + r",})[ \t]*$",
        line,
    )
    return bool(m)


# Wurzelverzeichnisse, an denen ein Token plausibel als Pfad erkannt wird (klein geschrieben verglichen -
# nur eine Heuristik, kein vollstaendiges Verzeichnisregister dieses Repos).
_PATH_ROOT_HINTS = (
    "docs", "src", "scripts", "test", "tests", "lib", "bin", "config", "public", "assets",
    "vendor", "app", "apps", "packages", "cmd", "pkg", "internal", "dist", "build", "node_modules",
)
_PATH_EXT_RE = re.compile(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9]{1,10}$")


def _looks_like_path(token: str) -> bool:
    """Heuristik, ob 'token' (ein Volltext-Treffer auf '\\S*/\\S+') plausibel eine Pfad- oder
    Dateiangabe ist statt zwei durch '/' verbundener Woerter (z.B. 'Kiki/Nova'). Zaehlt als Pfad, wenn er
    mit './', '../', '~/', '/' oder einem gaengigen Wurzelverzeichnis (docs/, src/, .claude/, ...) beginnt,
    oder wenn das letzte Segment wie ein Dateiname mit Endung aussieht (z.B. 'README.md', 'foo.py')."""
    token = token.rstrip(",.;:!?)]}'\"")
    if not token:
        return False
    if token.startswith((".", "~", "/")):
        return True
    first = token.split("/", 1)[0].lower()
    if first in _PATH_ROOT_HINTS:
        return True
    last = token.rsplit("/", 1)[-1]
    return bool(_PATH_EXT_RE.match(last))


def _merge_spans(spans):
    """Sortiert und verschmilzt ueberlappende/angrenzende Zeichenspannen (start, end)."""
    spans = sorted((s for s in spans if s[0] < s[1]), key=lambda s: s[0])
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _find_masked_spans_md(text: str):
    """Zeichenspannen in 'text' (einer Markdown-Datei), die bei der Namensersetzung ausgelassen werden:
    eingerueckte Codebloecke (nur wenn ihnen eine Leerzeile vorausgeht - siehe CommonMark: ein eingerueckter
    Codeblock kann keinen Absatz unterbrechen), Fenced Code Blocks (``` / ~~~, auch mit Sprachangabe und
    auch in Blockzitaten), Inline-Code in Backticks (einzeilig - siehe Kopfkommentar fuer die bekannte
    Luecke bei mehrzeiligem Inline-Code), URLs (http(s)://, www.) und plausible Pfad-/Dateiangaben mit '/'
    in Fliesstext (z.B. docs/fable/README.md - siehe _looks_like_path fuer die Abgrenzung von zufaelligen
    Wort/Wort-Token wie 'Kiki/Nova')."""
    lines = text.splitlines(keepends=True)
    offsets = []
    pos = 0
    for ln in lines:
        offsets.append(pos)
        pos += len(ln)

    protected_line_idx = set()

    # Fenced Code Blocks: komplette Zeilen inklusive Begrenzer.
    fence_char, fence_len, fence_start = None, 0, None
    for i, raw in enumerate(lines):
        line = raw.rstrip("\r\n")
        if fence_char is None:
            m = _FENCE_OPEN_RE.match(line)
            if m:
                marker = m.group(1)
                fence_char, fence_len, fence_start = marker[0], len(marker), i
        elif _is_fence_close(line, fence_char, fence_len):
            for j in range(fence_start, i + 1):
                protected_line_idx.add(j)
            fence_char = None
    if fence_char is not None:
        # Nicht geschlossen bis Dateiende - konservativ den Rest ausmaskieren statt zu raten.
        for j in range(fence_start, len(lines)):
            protected_line_idx.add(j)

    # Eingerueckte Codebloecke: Zeilen mit mind. 4 Leerzeichen oder einem Tab Einrueckung, nicht leer - aber
    # nur, wenn dem Block eine Leerzeile vorausgeht (oder er am Dateianfang steht). Nach CommonMark kann ein
    # eingerueckter Codeblock keinen Absatz unterbrechen: eine eingerueckte Fortsetzungszeile mitten in einem
    # Absatz oder eine eingerueckte Unterliste ist damit KEIN Codeblock und bleibt fuer die Ersetzung offen.
    # Einmal begonnen, bleibt ein Block ueber eingestreute Leerzeilen hinweg geschuetzt, solange danach
    # wieder eingerueckter Text folgt.
    in_indented_block = False
    prev_blank = True  # Dateianfang zaehlt wie eine vorausgehende Leerzeile
    for i, raw in enumerate(lines):
        if i in protected_line_idx:
            in_indented_block = False
            prev_blank = raw.strip(" \t\r\n") == ""
            continue
        is_blank = raw.strip(" \t\r\n") == ""
        if is_blank:
            prev_blank = True
            continue
        stripped = raw.lstrip(" \t")
        indent = raw[: len(raw) - len(stripped)]
        is_indented = "\t" in indent or len(indent) >= 4
        if is_indented and (in_indented_block or prev_blank):
            protected_line_idx.add(i)
            in_indented_block = True
        else:
            in_indented_block = False
        prev_blank = False

    spans = [(offsets[i], offsets[i] + len(lines[i])) for i in protected_line_idx]

    # Inline-Code, URLs, Pfadangaben - zeichenbasiert im Volltext (auch innerhalb sonst ungeschuetzter
    # Zeilen).
    for m in re.finditer(r"`[^`\n]+`", text):
        spans.append(m.span())
    for m in re.finditer(r"(?:https?://|www\.)\S+", text):
        spans.append(m.span())
    for m in re.finditer(r"\S*/\S+", text):
        if _looks_like_path(m.group(0)):
            spans.append(m.span())

    return _merge_spans(spans)


def _apply_rename_to_text(content: str, patterns, spans):
    """Wendet 'patterns' (Liste (compiled_regex, ersatz)) auf 'content' an, laesst aber die Zeichenspannen
    'spans' (sortiert, nicht ueberlappend) unangetastet. Gibt (neuer_text, ersetzt, geschuetzt) zurueck -
    'geschuetzt' zaehlt Treffer, die wegen eines Schutzbereichs nicht ersetzt wurden (nur zur Anzeige)."""
    if not spans:
        new_text = content
        replaced = 0
        for pat, n in patterns:
            new_text, k = pat.subn(n, new_text)
            replaced += k
        return new_text, replaced, 0

    pieces = []
    replaced = 0
    skipped = 0
    pos = 0
    for start, end in spans:
        segment = content[pos:start]
        for pat, n in patterns:
            segment, k = pat.subn(n, segment)
            replaced += k
        pieces.append(segment)
        protected = content[start:end]
        for pat, _n in patterns:
            skipped += len(pat.findall(protected))
        pieces.append(protected)
        pos = end
    tail = content[pos:]
    for pat, n in patterns:
        tail, k = pat.subn(n, tail)
        replaced += k
    pieces.append(tail)
    return "".join(pieces), replaced, skipped


def rename_orchestrator(root: Path, alt: str, neu: str, dry_run: bool = False):
    """Ersetzt ALT durch NEU (3 Schreibvarianten, Wortgrenzen) in allen versionierten Textdateien ausser
    AI-CONFIG.md, .claude/scripts/*.py und den Ordnern aus config-lib.py EXCLUDE_DIR_NAMES_REPLACE. In
    .md-Dateien werden Codebloecke, Inline-Code, URLs und Pfadangaben ausgemaskiert (siehe
    _find_masked_spans_md). Mit dry_run=True wird
    nichts geschrieben (Trefferliste/Vorschau vor --yes) - Rueckgabe wie bei echter Ausfuehrung, nur ohne
    Schreibzugriff und ohne FEHLER-Eintraege. Gibt (per_file: [(rel, ersetzt, geschuetzt)], total,
    fehler: [rel], total_geschuetzt) zurueck. Geschrieben wird ueber Bytes - Zeilenenden und BOM bleiben,
    wie sie waren."""
    if alt == neu:
        return [], 0, [], 0
    variants = _rename_variants(alt, neu)
    patterns = [
        (re.compile(r"(?<![\wÄÖÜäöüß])" + re.escape(a) + r"(?![\wÄÖÜäöüß])"), n)
        for a, n in variants
    ]
    per_file = []
    fehler = []
    total = 0
    total_skipped = 0
    for fp, rel in _iter_text_files_for_rename(root):
        content = _read_text_or_none(fp)
        if content is None:
            continue
        spans = _find_masked_spans_md(content) if fp.suffix.lower() == ".md" else []
        new_content, count_here, skipped_here = _apply_rename_to_text(content, patterns, spans)
        if not count_here and not skipped_here:
            continue
        total_skipped += skipped_here
        if dry_run:
            per_file.append((rel, count_here, skipped_here))
            total += count_here
            continue
        if count_here and new_content != content:
            try:
                fp.write_bytes(new_content.encode("utf-8"))
            except OSError:
                fehler.append(rel)
                continue
            per_file.append((rel, count_here, skipped_here))
            total += count_here
        elif skipped_here:
            per_file.append((rel, 0, skipped_here))
    return per_file, total, fehler, total_skipped


def _pos_in_spans(pos: int, spans) -> bool:
    """True, wenn 'pos' (ein Zeichen-Offset) in einer der sortierten, nicht ueberlappenden Spannen liegt -
    also von der Markdown-Maskierung geschuetzt ist (siehe _find_masked_spans_md)."""
    for start, end in spans:
        if start <= pos < end:
            return True
        if start > pos:
            break
    return False


def _mark_line(line: str, col: int, length: int, width: int = 100) -> str:
    """Kuerzt 'line' auf ca. 'width' Zeichen rund um den Treffer bei line[col:col+length] und markiert ihn
    mit [[...]] - fuer die Trefferliste vor --yes (siehe collect_rename_hits, Punkt 16 der Umbauliste)."""
    marked = line[:col] + "[[" + line[col:col + length] + "]]" + line[col + length:]
    if len(marked) <= width:
        return marked
    half = width // 2
    start = max(0, col - half)
    end = min(len(marked), start + width)
    start = max(0, end - width)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(marked) else ""
    return prefix + marked[start:end] + suffix


def collect_rename_hits(root: Path, alt: str, neu: str, limit: int = 40):
    """Zeilen-Trefferliste vor --yes (Punkt 16 der Umbauliste): je tatsaechlich zu ersetzender Fundstelle
    (Markdown-Schutzbereiche siehe _find_masked_spans_md ausgenommen - die werden ohnehin nie ersetzt) Datei,
    Zeilennummer und die Zeile gekuerzt auf ca. 100 Zeichen mit dem Treffer in [[...]] markiert. Gibt
    (hits, total) zurueck - 'hits' ist auf 'limit' Eintraege begrenzt (Dateireihenfolge von
    _iter_text_files_for_rename, darin Fundstelle vor Fundstelle), 'total' zaehlt alle tatsaechlichen
    Fundstellen im ganzen Repo (nicht nur die angezeigten)."""
    if alt == neu:
        return [], 0
    patterns = [
        re.compile(r"(?<![\wÄÖÜäöüß])" + re.escape(a) + r"(?![\wÄÖÜäöüß])")
        for a, _n in _rename_variants(alt, neu)
    ]
    hits = []
    total = 0
    for fp, rel in _iter_text_files_for_rename(root):
        content = _read_text_or_none(fp)
        if content is None:
            continue
        matches = sorted(
            (m for pat in patterns for m in pat.finditer(content)),
            key=lambda m: m.start(),
        )
        if not matches:
            continue
        spans = _find_masked_spans_md(content) if fp.suffix.lower() == ".md" else []
        lines = content.splitlines()
        offsets = []
        pos = 0
        for ln in content.splitlines(keepends=True):
            offsets.append(pos)
            pos += len(ln)
        for m in matches:
            if _pos_in_spans(m.start(), spans):
                continue
            total += 1
            if len(hits) >= limit or not lines:
                continue
            line_idx = max(0, min(bisect.bisect_right(offsets, m.start()) - 1, len(lines) - 1))
            col = m.start() - offsets[line_idx]
            hits.append((rel, line_idx + 1, _mark_line(lines[line_idx], col, len(m.group(0)))))
    return hits, total


def find_leftover_alt_dirs(root: Path, alt: str):
    """Ordner, die noch exakt wie ALT heissen (case-insensitiv) - werden hier nur gemeldet, nicht
    verschoben (das erledigt die Struktur-Migration)."""
    found = []
    for dirpath, dirnames, _filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIR_NAMES]
        for d in dirnames:
            if d.lower() == alt.lower():
                found.append((Path(dirpath) / d).relative_to(root).as_posix())
    return sorted(found)


# ---------------------------------------------------------------------------
# Git-Grundlagen + Modul-Wiederverwendung (update-template.py / setup-lib.py aus dem Ziel)
# ---------------------------------------------------------------------------


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


def _load_module(root: Path, rel: str, mod_name: str):
    path = root / rel
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        return None
    return mod


def _template_ref(root: Path):
    """(remote, 'remote/branch') aus .claude/template.json - oder (None, None), wenn kein Remote 'template'
    existiert bzw. update-template.py im Ziel fehlt."""
    tu = _load_module(root, ".claude/scripts/update-template.py", "_template_update_mp")
    if tu is None:
        return None, None
    cfg, _path = tu.load_template_json(root)
    remote = cfg.get("template_remote") or "template"
    branch = cfg.get("template_branch") or "main"
    res = run_git(root, ["remote"])
    remotes = res.stdout.split() if res.returncode == 0 else []
    if remote not in remotes:
        return None, None
    return remote, f"{remote}/{branch}"


def _config_orchestrator_values(root: Path):
    """(orchestrator, alter_orchestrator_name) aus AI-CONFIG.md, ueber den setup-lib.py-Parser des Ziels.
    (None, None), wenn AI-CONFIG.md/setup-lib.py fehlen."""
    cfg_path = root / "AI-CONFIG.md"
    if not cfg_path.exists():
        return None, None
    np = _load_module(root, ".claude/scripts/setup-lib.py", "_new_project_mp")
    if np is None:
        return None, None
    try:
        text = cfg_path.read_text(encoding="utf-8-sig")
    except OSError:
        text = ""
    cfg = np.parse_config(text)
    return cfg.get("orchestrator"), cfg.get("alter_orchestrator_name")


# ---------------------------------------------------------------------------
# Root
# ---------------------------------------------------------------------------


def _find_root() -> Path:
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[2]


def _check_root(root: Path) -> int:
    if not (root / "AGENTS.md").exists():
        print(
            f"Fehler: {root} sieht nicht nach einem Projekt aus diesem Template aus (AGENTS.md fehlt). "
            "Aufruf im Projekt-Root pruefen (bzw. CLAUDE_PROJECT_DIR).",
            file=sys.stderr,
        )
        return 2
    return 0


# ---------------------------------------------------------------------------
# --plan
# ---------------------------------------------------------------------------


def cmd_plan(root: Path, forced_alt=None, forced_neu=None) -> int:
    ai_dirs, moves, _conflicts, sub_md, ignored = build_plan(root)
    merge_entries = compute_merge_entries(root)
    foreign = find_foreign_ai_regelfiles(root)
    if forced_alt and forced_neu:
        orch = [(forced_alt, count_occurrences(root, forced_alt))]
    else:
        orch = detect_orchestrator_names(root, ai_dirs, moves)
    moved_set = {m[0] for m in moves}
    empty_dirs = compute_empty_dirs(root, ai_dirs, moved_set)

    if not moves and not merge_entries and not orch and not ignored and not foreign:
        print("migrate-project.py --plan\n\nNichts zu tun.")
        return 0

    lines = ["migrate-project.py --plan", ""]

    lines.append("Verschieben:")
    if moves:
        for src, dest, note in moves[:20]:
            note_txt = f"  ({note})" if note else ""
            lines.append(f"  {src.relative_to(root).as_posix()}  ->  {dest.relative_to(root).as_posix()}{note_txt}")
        if len(moves) > 20:
            lines.append(f"  ... und {len(moves) - 20} weitere")
    else:
        lines.append("  (keine)")

    if ignored:
        lines.append("")
        lines.append("Gitignoriert, bewusst liegengelassen (bei Bedarf von Hand verschieben):")
        for p in ignored[:20]:
            lines.append(f"  {p.relative_to(root).as_posix()}")
        if len(ignored) > 20:
            lines.append(f"  ... und {len(ignored) - 20} weitere")

    lines.append("")
    lines.append("Zusammenfuehren (Inhalt, macht der Assistent):")
    if merge_entries:
        _remote, ref = _template_ref(root)
        for rel, label in merge_entries[:15]:
            lines.append(f"  {rel}  [{label}]  git show {ref}:{rel}")
        if len(merge_entries) > 15:
            lines.append(f"  ... und {len(merge_entries) - 15} weitere")
        lines.append("")
        lines.append("Prioritaetsregeln:")
        lines.extend("  " + l for l in PRIORITY_RULES.splitlines())
    else:
        lines.append("  (keine, oder Template-Remote nicht verfuegbar - siehe .claude/template.json)")

    if foreign:
        lines.append("")
        lines.append(
            "Fremde KI-Regeldateien - Inhalt nach docs/project/coding_rules.md einarbeiten, danach durch "
            "Verweis auf AGENTS.md ersetzen:"
        )
        for rel, n in foreign[:20]:
            lines.append(f"  {rel}  ({n} Zeilen)")
        if len(foreign) > 20:
            lines.append(f"  ... und {len(foreign) - 20} weitere")

    lines.append("")
    lines.append("Orchestrator-Name:")
    if orch:
        for name, cnt in orch[:10]:
            lines.append(f"  {name} ({cnt} Fundstellen)")
    else:
        lines.append("  (keine Kandidaten erkannt)")

    if sub_md:
        lines.append("")
        lines.append("Markdown in Unterordnern (NICHT automatisch verschoben - Struktur ist "
                     "projektspezifisch, bitte selbst zuordnen):")
        for f in sub_md[:20]:
            lines.append(f"  {f.relative_to(root).as_posix()}")
        if len(sub_md) > 20:
            lines.append(f"  ... und {len(sub_md) - 20} weitere")

    if empty_dirs:
        lines.append("")
        lines.append("Leer nach Migration (manuell pruefen und loeschen):")
        for d in empty_dirs:
            lines.append(f"  {d}")

    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------------------
# --status
# ---------------------------------------------------------------------------


def cmd_status(root: Path) -> int:
    ai_dirs, moves, conflicts, sub_md, ignored = build_plan(root)
    merge_entries = compute_merge_entries(root)
    foreign = find_foreign_ai_regelfiles(root)
    orch = detect_orchestrator_names(root, ai_dirs, moves)

    lines = ["migrate-project.py --status", ""]
    lines.append(f"KI-Arbeitsordner (alt) gefunden: {len(ai_dirs)}")
    for d in ai_dirs:
        lines.append(f"  {d.relative_to(root).as_posix()}")
    lines.append(f"docs/ai/ vorhanden: {'ja' if (root / 'docs' / 'ai').is_dir() else 'nein'}")
    lines.append(f"Verschiebungen ausstehend: {len(moves)}")
    lines.append(f"Konflikte (mehrere Kandidaten je Zieldatei): {len(conflicts)}")
    lines.append(f"Gitignoriert (liegengelassen): {len(ignored)}")
    lines.append(f"Zusammenfuehren ausstehend: {len(merge_entries)}")
    lines.append(f"Fremde KI-Regeldateien (Inhalt manuell einarbeiten): {len(foreign)}")
    lines.append(f"Markdown in Unterordnern (manuell zuzuordnen): {len(sub_md)}")
    if orch:
        lines.append("Orchestrator-Kandidaten: " + ", ".join(f"{n}({c})" for n, c in orch[:5]))
    else:
        lines.append("Orchestrator-Kandidaten: (keine)")
    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------------------
# --apply
# ---------------------------------------------------------------------------


def _git_mv(root: Path, rel_src: str, rel_dest: str) -> str:
    """"git" = per 'git mv' bewegt, "shutil" = Rueckfall (Datei nicht getrackt), "fehler" = gar nicht bewegt.
    Ein vorhandenes Ziel wird nie ueberschrieben - der Aufrufer sucht vorher einen freien Namen."""
    dest_path = root / rel_dest
    if dest_path.exists():
        return "fehler"
    res = run_git(root, ["mv", "--", rel_src, rel_dest])
    if res.returncode == 0:
        return "git"
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.move(str(root / rel_src), str(dest_path))
    except OSError:
        return "fehler"
    run_git(root, ["add", "--", rel_dest])
    return "shutil"


def _free_alt_dest(dest: Path) -> Path:
    """Freien Namen fuer eine Altfassung neben dest suchen: name.alt.md, name.alt2.md, ... Ohne das wuerde
    die dritte Quelle mit gleichem Namen die zweite ueberschreiben (stiller Datenverlust)."""
    for i in range(1, 100):
        suffix = ".alt" if i == 1 else f".alt{i}"
        candidate = dest.with_name(dest.stem + suffix + dest.suffix)
        if not candidate.exists():
            return candidate
    return dest.with_name(dest.stem + ".alt99" + dest.suffix)


def _mv_note(status: str) -> str:
    if status == "shutil":
        return "  [shutil.move Rueckfall]"
    if status == "fehler":
        return "  [FEHLER: nicht verschoben, Quelle liegt unveraendert an ihrem Platz]"
    return ""


def execute_move(root: Path, src: Path, dest: Path, note) -> str:
    rel_src = src.relative_to(root).as_posix()
    if dest.exists():
        try:
            same = dest.read_bytes() == src.read_bytes()
        except OSError:
            same = False
        if same:
            res = run_git(root, ["rm", "-f", "--", rel_src])
            if res.returncode != 0:
                try:
                    src.unlink()
                except OSError:
                    pass
            rel_dest = dest.relative_to(root).as_posix()
            return f"  {rel_src}  ==  {rel_dest}  (inhaltsgleich, Altdatei geloescht)"
        alt_dest = _free_alt_dest(dest)
        rel_alt = alt_dest.relative_to(root).as_posix()
        status = _git_mv(root, rel_src, rel_alt)
        return (
            f"  {rel_src}  ->  {rel_alt}  (Ziel existiert bereits und unterscheidet sich - zusammenfuehren)"
            + _mv_note(status)
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    rel_dest = dest.relative_to(root).as_posix()
    status = _git_mv(root, rel_src, rel_dest)
    note_txt = f"  [{note}]" if note else ""
    return f"  {rel_src}  ->  {rel_dest}{note_txt}" + _mv_note(status)


def _format_rename_report(alt: str, neu: str, per_file, total: int, fehler, total_skipped: int, executed: bool):
    """Formatiert das Ergebnis von rename_orchestrator() als Zeilenliste - fuer die echte Ausfuehrung
    (executed=True) wie fuer die Trefferliste vor --yes (executed=False, gleiche Zahlen als Vorschau)."""
    verb = "ersetzt" if executed else "wuerden ersetzt"
    files_touched = sum(1 for _rel, cnt, _skip in per_file if cnt)
    skip_txt = f", {total_skipped} wegen Markdown-Schutz uebersprungen" if total_skipped else ""
    lines = [f"Orchestrator-Name: '{alt}' -> '{neu}' ({total} Treffer {verb} in {files_touched} Dateien{skip_txt})"]
    for rel, cnt, skip in per_file[:30]:
        extra = f"  ({skip} geschuetzt uebersprungen)" if skip else ""
        lines.append(f"  {rel}: {cnt}{extra}")
    if len(per_file) > 30:
        lines.append(f"  ... und {len(per_file) - 30} weitere Dateien")
    for rel in fehler:
        lines.append(f"  FEHLER, nicht geschrieben (schreibgeschuetzt?): {rel}")
    return lines


def check_clean_worktree(root: Path) -> int:
    """Vorbedingung fuer jeden schreibenden Lauf (--apply wie --rename-orchestrator): Git-Repo und sauberer
    Arbeitsbaum - beides schreibt breit ins Repo und ist sonst nicht rueckgaengig zu machen. 0 = ok."""
    res_git = run_git(root, ["rev-parse", "--is-inside-work-tree"])
    if res_git.returncode != 0 or res_git.stdout.strip() != "true":
        print("Fehler: kein Git-Repo - Migration erfordert Git (Historie/Rueckgaengigmachen).", file=sys.stderr)
        return 2
    res_status = run_git(root, ["status", "--porcelain"])
    if res_status.stdout.strip():
        print(
            "Fehler: Arbeitsbaum nicht sauber - erst committen/stashen, damit die Migration rueckgaengig "
            "gemacht werden kann.",
            file=sys.stderr,
        )
        return 2
    return 0


def cmd_apply(root: Path, forced_alt=None, forced_neu=None) -> int:
    rc = check_clean_worktree(root)
    if rc != 0:
        return rc

    ai_dirs, moves, _conflicts, _sub, ignored = build_plan(root)

    lines = ["migrate-project.py --apply", ""]
    lines.append("Verschoben:")
    if moves:
        (root / "docs" / "ai").mkdir(parents=True, exist_ok=True)
        for src, dest, note in moves:
            lines.append(execute_move(root, src, dest, note))
    else:
        lines.append("  (keine - nichts zu verschieben)")

    if ignored:
        lines.append("")
        lines.append("Gitignoriert, bewusst liegengelassen (bei Bedarf von Hand verschieben):")
        for p in ignored:
            lines.append(f"  {p.relative_to(root).as_posix()}")

    empty_dirs = compute_empty_dirs(root, ai_dirs, moved_set=None)
    if empty_dirs:
        lines.append("")
        lines.append("Leer nach Migration (manuell pruefen und loeschen):")
        for d in empty_dirs:
            lines.append(f"  {d}")

    alt, neu = forced_alt, forced_neu
    if not alt:
        cfg_orch, cfg_alt = _config_orchestrator_values(root)
        if cfg_alt:
            alt = cfg_alt
            # Kein fester Rueckfallname: ohne AI-CONFIG.md § Orchestrator wuerde sonst ein fremder Name ins
            # ganze Repo geschrieben.
            neu = neu or cfg_orch

    lines.append("")
    if alt and neu:
        # --apply zeigt den Plan vorher an - die Bestaetigung gilt damit als erteilt, deshalb hier direkt
        # ausfuehren (dry_run=False) statt erneut auf --yes zu warten. Die Trefferliste (wie bei
        # --rename-orchestrator ohne --yes) trotzdem VOR dem Schreiben ausgeben - keine erneute Rueckfrage,
        # nur sichtbar im Protokoll, was gleich geaendert wird.
        hits, hit_total = collect_rename_hits(root, alt, neu)
        lines.append(f"Orchestrator-Name '{alt}' -> '{neu}' - Trefferliste (vor dem Schreiben) - "
                      "Datei:Zeile, Treffer in [[...]] markiert:")
        if hits:
            for rel, lineno, snippet in hits:
                lines.append(f"  {rel}:{lineno}: {snippet}")
            if hit_total > len(hits):
                lines.append(f"  ... insgesamt {hit_total} Treffer, nur die ersten {len(hits)} gezeigt")
        else:
            lines.append("  (keine Treffer)")
        lines.append("")
        per_file, total, fehler, total_skipped = rename_orchestrator(root, alt, neu)
        lines.extend(_format_rename_report(alt, neu, per_file, total, fehler, total_skipped, executed=True))
        leftover = find_leftover_alt_dirs(root, alt)
        if leftover:
            lines.append("  Achtung: Ordner heissen noch wie der alte Name (manuell klaeren):")
            for d in leftover:
                lines.append(f"    {d}")
    elif alt:
        lines.append(f"Orchestrator-Name: alter Name '{alt}' bekannt, aber kein neuer - AI-CONFIG.md § "
                      "\"Orchestrator\" ist leer. Keine Ersetzung ausgefuehrt, bei Bedarf einzeln mit "
                      "--rename-orchestrator ALT=NEU.")
    else:
        lines.append("Orchestrator-Name: kein Name uebergeben und keiner in AI-CONFIG.md § \"Alter "
                      "Orchestrator-Name\" gesetzt - keine Ersetzung ausgefuehrt.")

    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------------------
# main / Argument-Parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="migrate-project.py",
        description="Bestehendes Repo (Weg 2) auf die Template-Struktur migrieren: KI-Arbeitsordner "
        "erkennen/verschieben, Zusammenfuehr-Kandidaten melden, Orchestrator-Rufnamen ersetzen.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--plan", action="store_true", help="Migrationsplan zeigen, nichts schreiben (Default)")
    group.add_argument("--apply", action="store_true", help="Plan ausfuehren")
    group.add_argument("--status", action="store_true", help="Kurzuebersicht Template-Konformitaet")
    parser.add_argument(
        "--rename-orchestrator", metavar="ALT=NEU", default=None,
        help="Orchestrator-Rufnamen ersetzen; zeigt zuerst die Trefferliste (Vorschau, nichts geschrieben) - "
        "erst --yes fuehrt sie aus. Mit --plan kombiniert bleibt es eine reine Vorschau.",
    )
    parser.add_argument(
        "--yes", action="store_true",
        help="Bestaetigt eine per --rename-orchestrator gezeigte Trefferliste und schreibt sie",
    )
    return parser


def _run(argv) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    root = _find_root()
    rc = _check_root(root)
    if rc != 0:
        return rc

    alt, neu = None, None
    if args.rename_orchestrator:
        if "=" not in args.rename_orchestrator:
            print(
                f"Fehler: --rename-orchestrator {args.rename_orchestrator} ist ungueltig - erwartet "
                "ALT=NEU.",
                file=sys.stderr,
            )
            return 2
        alt, neu = (p.strip() for p in args.rename_orchestrator.split("=", 1))
        if not alt or not neu:
            print(
                f"Fehler: --rename-orchestrator {args.rename_orchestrator} ist ungueltig - ALT und NEU "
                "duerfen nicht leer sein.",
                file=sys.stderr,
            )
            return 2

    if args.status:
        return cmd_status(root)
    if args.apply:
        return cmd_apply(root, alt, neu)
    if args.rename_orchestrator and not args.plan:
        # Nur die Namensersetzung, ohne Struktur-Migration. Schreibt in jede Textdatei des Repos und braucht
        # deshalb dieselbe Vorbedingung wie --apply - aber erst beim tatsaechlichen Schreiben (--yes). Die
        # reine Vorschau (kein --yes) schreibt nichts und darf deshalb auch in einem unsauberen Arbeitsbaum
        # laufen (Exit 0).
        if args.yes:
            rc = check_clean_worktree(root)
            if rc != 0:
                return rc
        if alt == neu:
            print(f"Fehler: --rename-orchestrator {args.rename_orchestrator} ist ungueltig - ALT und NEU "
                  "sind identisch.", file=sys.stderr)
            return 2
        per_file, total, fehler, total_skipped = rename_orchestrator(root, alt, neu, dry_run=not args.yes)
        header = f"migrate-project.py --rename-orchestrator {args.rename_orchestrator}"
        if args.yes:
            header += " --yes"
        lines = [header, ""]

        if not args.yes:
            hits, hit_total = collect_rename_hits(root, alt, neu)
            lines.append("Trefferliste (vor dem Schreiben) - Datei:Zeile, Treffer in [[...]] markiert:")
            if hits:
                for rel, lineno, snippet in hits:
                    lines.append(f"  {rel}:{lineno}: {snippet}")
                if hit_total > len(hits):
                    lines.append(f"  ... insgesamt {hit_total} Treffer, nur die ersten {len(hits)} gezeigt")
            else:
                lines.append("  (keine Treffer)")
            lines.append("")

        lines.extend(_format_rename_report(alt, neu, per_file, total, fehler, total_skipped, executed=args.yes))
        leftover = find_leftover_alt_dirs(root, alt)
        if leftover:
            lines.append("Achtung: Ordner heissen noch wie der alte Name (manuell klaeren):")
            for d in leftover:
                lines.append(f"  {d}")
        lines.append("")
        if args.yes:
            lines.append("Geschrieben - Ergebnis mit 'git diff' pruefen.")
        else:
            lines.append(
                "Nichts geschrieben - vorher committen (git diff bleibt dann pruefbar), danach zur "
                "Bestaetigung dieselbe Zeile mit --yes wiederholen."
            )
        print("\n".join(lines))
        return 0

    return cmd_plan(root, alt, neu)


def main() -> int:
    try:
        return _run(sys.argv[1:])
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 - darf nie mit Traceback nach aussen dringen
        print(f"migrate-project: Fehler: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
