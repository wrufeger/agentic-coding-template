#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Template-Updates in ein aus diesem Template abgeleitetes Projekt per Git-Merge einspielen, ohne
#        dass echte Werte wieder durch Platzhalter (`{{PROJEKTNAME}}` usw.) ersetzt werden. Verwaltet dazu
#        `.claude/template.json` (Remote/Branch des Templates, zuletzt eingespielter Basis-Commit, die
#        eingesetzten Platzhalterwerte, Dateien/Ordner, deren Projektfassung bei Konflikten immer gewinnt,
#        Update-Historie). Siehe AGENTS.md § "Template-Herkunft und Updates", CLAUDE.md § 2 (Skill
#        `/act-update-template`), docs/ai/checklists.md § "Template-Update". Reine Python-Stdlib, kein Paket
#        noetig.
#
# Aufruf:
#   python .claude/scripts/update-template.py --init [--url URL] [--base HASH] [--set KEY=WERT ...]
#       Legt Remote "template" an (falls noetig), ermittelt/uebernimmt den Basis-Commit, speichert Werte.
#   python .claude/scripts/update-template.py --set KEY=WERT [--set KEY=WERT ...]
#       Nur Platzhalterwerte schreiben (ohne Remote/Basis-Commit anzufassen).
#   python .claude/scripts/update-template.py --check [--quiet]
#       Prueft, ob das Template neuer ist als der gespeicherte Basis-Commit (mit fetch, Timeout 20s).
#       Exit 0 = aktuell/nicht konfiguriert (bei --quiet), 2 = nicht konfiguriert/Netzwerkfehler (ohne
#       --quiet), 3 = Update verfuegbar (Ausgabe: Commits, geaenderte Dateien, keep_local-Markierung).
#   python .claude/scripts/update-template.py --apply [--commit]
#       Mergt template/<branch> in den Arbeitsbaum (git merge --no-ff --no-commit). Schlaegt der Merge aus
#       einem anderen Grund als offenen Konflikten fehl (z.B. "not something we can merge"), bricht --apply
#       SOFORT ab (Exit 2) - VOR jedem Schreibzugriff auf .claude/template.json, damit ein sauberer
#       Arbeitsbaum fuer den naechsten Versuch zurueckbleibt. Erst danach werden Konflikte in
#       .claude/template.json feldweise gemergt (auch "both added" beim Bootstrap, siehe unten):
#       base_commit/updates/template_remote/template_branch/template_url/is_template immer aus der
#       Projektfassung OHNE Rueckfall auf das Template, wenn das Feld dort fehlt (fehlt es im Projekt, soll
#       es fehlen); values feldweise (Projektwert gewinnt je Schluessel, neue Platzhalter aus dem Template
#       werden mit null ergaenzt, damit sie nicht unersetzt in Zieldateien stehen bleiben); keep_local/
#       no_replace/template_only als Vereinigung (Projekt zuerst, dann neue Template-Eintraege) - unabhaengig
#       von keep_local selbst. Schlaegt das Parsen einer Seite fehl, faellt es auf das alte Verhalten zurueck
#       (Projektfassung komplett). Konflikte vom Typ "DD" (von beiden geloescht)
#       werden immer automatisch bereinigt (unstrittig). Ein Konflikt vom Typ "DU" auf einem template_only-
#       Pfad (siehe DEFAULT_TEMPLATE_ONLY, z.B. .templatedev/ - create-project.py entfernt den Ordner beim
#       Anlegen, seitdem "geloescht" aus Sicht des 3-Way-Merges) wird immer automatisch als "geloescht belassen"
#       entschieden, ohne Rename-Pruefung - der Pfad ist bewusst und dauerhaft ausgeschlossen, nie eine
#       Migration. Jeder ANDERE Konflikt vom Typ "DU" (vom Projekt geloescht, im Template geaendert) wird NUR
#       DANN automatisch als "geloescht belassen" entschieden, wenn der Pfad in keep_local steht UND keine
#       Umbenennung erkennbar ist (siehe --conflicts) - das Script darf sonst nicht allein entscheiden, ob die
#       Loeschung bewusst war oder nur eine Umbenennung/Verschiebung ist (typisch: docs/ai/ auf eigene
#       Dateinamen migriert). Sonstige Konflikte in keep_local-Pfaden werden automatisch zugunsten der
#       Projektfassung geloest; alle uebrigen (inkl. offen gelassener DU-Faelle) muessen von Hand geloest
#       werden (Analyse siehe --conflicts, danach --continue). Ohne Konflikte bzw. nach deren Aufloesung:
#       template_only-Pfade werden aus dem Arbeitsbaum entfernt, falls sie doch hereingekommen sind (siehe
#       _remove_template_only, greift NIE im Template-Checkout selbst); ABGEWAEHLTE Pfade ebenso (siehe
#       abgewaehlte_pfade(): was AI-CONFIG.md auf "aus" stehen hat, bleibt draussen - ein "DU"-Konflikt darauf
#       wird ohne Rueckfrage als "geloescht belassen" entschieden, und eine im Template neu angelegte Datei
#       darunter wird nach dem Merge wieder entfernt, weil sie gar keinen Konflikt ausloest); Platzhalter in den vom Merge
#       beruehrten Textdateien (ausser keep_local und no_replace) ersetzen, base_commit/updates fortschreiben,
#       git add.
#   python .claude/scripts/update-template.py --continue [--commit]
#       Nach manueller Konfliktaufloesung: prueft, dass keine Konflikte mehr offen sind, fuehrt den
#       Abschlussschritt von --apply aus.
#   python .claude/scripts/update-template.py --conflicts
#       Nur waehrend eines laufenden Merges (MERGE_HEAD vorhanden, sonst Hinweis + Exit 0): analysiert jeden
#       noch offenen Konflikt fuer den Assistenten (Art, Prioritaetsregel, Zeilenumfang der Aenderung je
#       Seite, Umbenennungs-Kandidat bei "DU" per Git-Rename-Erkennung bzw. Inhaltsaehnlichkeit unter
#       docs/ai/; bei "AU"/"UA" - beide Seiten haben dieselbe Datei verschoben - beide Zielpfade per
#       Git-Rename-Erkennung, passende git-Befehle zum Nachschauen). Schreibt nichts, loest nichts auf -
#       reine Analyse fuer die inhaltliche Zusammenfuehrung, die der Assistent macht.
#   python .claude/scripts/update-template.py --abort
#       Bricht einen laufenden Merge ab (git merge --abort); .claude/template.json bleibt unveraendert.
#   python .claude/scripts/update-template.py --status
#       Zeigt Konfiguration, Remote-URL, base_commit, letztes Update, Anzahl ausstehender Commits (ohne
#       fetch, also ggf. veralteter Stand), ob eine gemeinsame Historie mit base_commit existiert
#       (graft-Status) sowie ob gerade ein Merge laeuft und wie viele Konflikte offen sind.
#   python .claude/scripts/update-template.py --graft
#       Fuer per `apply-template.py` nachgeruestete Projekte (kein gemeinsamer Vorfahr mit dem Template):
#       stellt per leerem Merge (`git merge -s ours --allow-unrelated-histories`) eine gemeinsame Historie
#       zu base_commit her, OHNE den Arbeitsbaum zu veraendern - danach funktionieren --check/--apply wie
#       bei einem per `git clone` angelegten Projekt. Voraussetzung: sauberer Arbeitsbaum, base_commit
#       gesetzt (siehe .claude/template.json), Remote vorher gefetcht (macht `apply-template.py` bzw. der
#       Skill /act-apply-template bereits). Existiert bereits ein gemeinsamer Vorfahr (`git merge-base HEAD
#       base_commit`), ist --graft ein No-op (Exit 0, Hinweis).
#
# --commit auf --apply/--continue erstellt den Merge-Commit direkt; ohne --commit bleiben die Aenderungen
# gestaged, damit sie vor dem Commit geprueft werden koennen.
#
# Bootstrap (bestehendes Projekt hat dieses Script noch nicht): mit
#   CLAUDE_PROJECT_DIR=<projekt> python <template-checkout>/.claude/scripts/update-template.py --init ...
#   aufrufen - die Root kommt strikt aus CLAUDE_PROJECT_DIR, das Script selbst kann ausserhalb des
#   Projekts liegen. Fehlt .claude/template.json im Projekt, wird intern mit einer leeren Default-
#   Konfiguration gearbeitet (--init legt die Datei an; --check --quiet ohne Datei ist still Exit 0).
#
# keep_local (template.json) = Projektfassung gewinnt BEI KONFLIKTEN und wird nie platzhalter-ersetzt;
# konfliktfreie Template-Aenderungen an diesen Dateien merged git ganz normal mit hinein.
# Vergleichsziel (compare_ref): normalerweise <template_remote>/<template_branch>. Fehlt der Remote,
# existiert aber ein lokaler Branch dieses Namens, wird lokal verglichen und nicht gefetcht - das ist
# der Fall "Projekt entstand als Branch im Template-Checkout" (siehe create-project.py).
# no_replace (template.json) = Dateien, die den Platzhalter selbst dokumentieren; sie werden gemergt, aber
# nie ersetzt.
# template_only (template.json) = Pfade, die es nur im Template gibt (siehe DEFAULT_TEMPLATE_ONLY). --check
# zeigt sie getrennt als ausgelassen statt als einzuspielende Aenderung; --apply/--continue entfernt sie nach
# dem Merge wieder aus dem Arbeitsbaum. Greift NIE im Template-Checkout selbst (Marker "is_template").
#
# git laeuft immer nicht-interaktiv (GIT_TERMINAL_PROMPT=0, stdin geschlossen): ein privates Template ohne
# hinterlegten Credential-Helper meldet einen Fehler, statt im Hook auf eine Passworteingabe zu warten.
#
# Exit-Codes: 0 = ok/aktuell (auch --conflicts ohne laufenden Merge bzw. ohne offene Konflikte), 2 =
#             Konfigurations-/Vorbedingungsfehler, 3 = Update verfuegbar (nur --check), 4 = Konflikte offen
#             (nur --apply/--continue). Ein Fehler dieses Scripts darf nie mit Traceback nach aussen
#             dringen: main() laeuft komplett in try/except, Fehlermeldungen auf stderr. `--check --quiet`
#             schreibt nie auf stdout, ausser es gibt tatsaechlich ein Update.

import argparse
import ast
import difflib
import fnmatch
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

# Windows liest sonst in der ANSI-Codepage - Pfade mit Umlauten kaemen als Mojibake an (dasselbe Muster wie
# in ai-log.py/create-project.py; try/except, damit aeltere Python-Versionen ohne reconfigure() nicht scheitern).
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

DEFAULT_VALUE_KEYS = [
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

DEFAULT_KEEP_LOCAL = [
    "docs/project/**",
    "docs/ai/board.md",
    "docs/ai/tasks.md",
    "docs/ai/questions.md",
    "docs/ai/questions_archive.md",
    "docs/ai/ledger.md",
    "docs/ai/backlog.md",
    "docs/ai/tasks_archive.md",
    "README.md",
    "AI-CONFIG.md",
    ".env.example",
    ".github/workflows/ci.yml",
    ".mcp.json.example",
    ".claude/maintenance/status.json",
]

# Dateien, die den Platzhalter selbst dokumentieren (Beispielaufzaehlungen in Checklisten/Skills). Sie werden
# normal gemergt, aber NIE ersetzt - sonst macht ein Update aus "Alle Platzhalter (`{{PROJEKTNAME}}`, ...)"
# die Zeile "Alle Platzhalter (`Kundenportal`, ...)" und die Anleitung ist kaputt.
DEFAULT_NO_REPLACE = [
    ".claude/scripts/setup-lib.py",
    ".claude/scripts/update-template.py",
    ".claude/scripts/sync-config.py",
]

# Pfade, die es NUR im Template-Checkout selbst gibt (Muss zu TEMPLATE_ONLY_PATHS in setup-lib.py passen -
# kein Import zwischen den Scripten, jedes bleibt fuer sich Stdlib-eigenstaendig, siehe DEFAULT_NO_REPLACE
# oben). `create-project.py` entfernt sie beim Anlegen eines Projekts, `apply-template.py` kopiert sie nie -
# ein Merge darf sie darum nie ins Projekt tragen: `.templatedev/` (Board/Backlog/Fragen/Ledger/Regeln der
# Template-Entwicklung, seit T5 in `.templatedev/docs/ai/` bzw. `.templatedev/docs/project/` - schliesst
# dessen eigenen `.claude/skills/act-process-feedback`, den Skill der Template-Pflege, mit ein), `.github/
# README.md` (Template-Beschreibung fuer GitHub, hat Vorrang vor der Projekt-README) und
# `.claude/scripts/template-welcome.py` (Hinweis-Hook fuer einen frischen Template-Klon - der zugehoerige
# UserPromptSubmit-Eintrag in settings.json bleibt normale Merge-Sache, siehe remove_welcome_hook() in
# files-lib.py). Bare Pfade ohne Wildcard: _remove_template_only() braucht sie so fuer `git rm -r -f` und
# das Path.exists()/is_dir()-Fallback (ein Ordner-Eintrag entfernt den Ordner rekursiv); matches_keep_local()
# deckt dank Ordner-Praefix-Logik trotzdem auch einzelne Dateien darunter ab (z.B. ".templatedev/docs/ai/backlog.md").
# Werden normal gemergt (--check zeigt sie nur getrennt als "nicht eingespielt"), aber --apply/--continue
# entfernt sie danach wieder aus dem Arbeitsbaum - siehe _remove_template_only().
DEFAULT_TEMPLATE_ONLY = [
    ".github/README.md",
    ".templatedev",
    ".claude/scripts/template-welcome.py",  # Hinweis-Hook fuer einen frischen Template-Klon (Review 2026-09-17)
]

# F4 (Review): Diese vier Pfade lagen VOR der Umbenennung auf das `act-`-Praefix (Commit 993b82e) unter
# genau demselben Namen, aber mit dem VOLLEN Skill-Inhalt - ein damals angelegtes/geklontes Projekt hat dort
# also noch seine platzhalter-ersetzte Vollfassung liegen (z.B. echte Werte statt `{{PROJEKTNAME}}`). Seit
# der Umbenennung sind es reine Weiterleitungen auf `.claude/skills/act-<name>/SKILL.md` ("Verweist auf ...
# und fuehrt dessen Anleitung aus."). Ein Update MUSS hier IMMER die Template-Seite gewinnen lassen -
# unabhaengig vom Konflikt-Code (UU/AA/DU je nach Historie des Projekts) - die alte Vollfassung ist nie die
# richtige Antwort, auch nicht lokal veraendert; der eigentliche Skill-Inhalt lebt unveraendert unter
# `act-<name>/` weiter, es geht nichts verloren. Bare Pfade (Ordner) wie DEFAULT_TEMPLATE_ONLY oben -
# matches_keep_local() deckt per Ordner-Praefix-Logik die einzelne SKILL.md-Datei darunter ab.
FORWARDER_TEMPLATE_WINS_PATHS = [
    ".claude/skills/commit",
    ".claude/skills/idea",
    ".claude/skills/prepare",
    ".claude/skills/update-template",
]

# Pfade, die ein abgewaehlter Schalter aus dem Projekt entfernt hat. Quelle ist `applied_config` in
# template.json (der zuletzt umgesetzte Stand von AI-CONFIG.md) - bewusst KEINE eigene Liste in
# template.json: die waere eine zweite Wahrheit neben AI-CONFIG.md und wuerde veralten, sobald jemand
# zurueckschaltet. Die Pfade muessen zu MAINTENANCE_REMOVE_PATHS/OPTIMIZER_REMOVE_PATHS/TOOL_FILES in
# setup-lib.py passen - dupliziert statt importiert, wie DEFAULT_TEMPLATE_ONLY oben (jedes Script bleibt
# fuer sich Stdlib-eigenstaendig, siehe DEFAULT_NO_REPLACE).
ABGEWAEHLT_SCHALTER_PATHS = {
    "Wartung": [
        ".claude/maintenance",
        ".claude/skills/act-run-maintenance",
        ".claude/agents/maintenance-orchestrator.md",
        ".claude/scripts/maintenance-check.py",
        # Altname vor act-Praefix, 2026-09-17: haelt den alten Ordnernamen ebenfalls draussen, falls ein
        # Projekt den Umbenennungs-Merge noch nicht eingespielt hat.
        ".claude/skills/act-run-maintenance",
    ],
    "Code-Optimierung": [".claude/agents/optimizer.md"],
}
ABGEWAEHLT_TOOL_PATHS = {
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


def abgewaehlte_pfade(cfg: dict) -> list:
    """Pfade, die dieses Projekt per AI-CONFIG.md abgewaehlt hat (Wartung/Code-Optimierung aus, KI-Werkzeug
    gestrichen). Ein Merge darf sie nicht wieder hereintragen: Ohne das faengt jede Template-Aenderung an so
    einer Datei einen "DU"-Konflikt zur Entscheidung, und eine im Template NEU angelegte Datei darunter kaeme
    voellig konfliktfrei zurueck - beides ist nicht, was "aus" bedeutet.
    Leere Liste, wenn `applied_config` fehlt (Projekt aelter als sync-config.py): Dann ist nicht bekannt, was
    bewusst abgewaehlt wurde, und Raten waere schlimmer als Einspielen."""
    if cfg.get("is_template"):
        return []
    angewandt = cfg.get("applied_config")
    if not isinstance(angewandt, dict):
        return []
    pfade = []
    for schluessel, liste in ABGEWAEHLT_SCHALTER_PATHS.items():
        if str(angewandt.get(schluessel) or "").strip().lower() == "aus":
            pfade.extend(liste)
    werkzeuge = angewandt.get("KI-Werkzeuge-entfernt")
    if isinstance(werkzeuge, list):
        for werkzeug in werkzeuge:
            pfade.extend(ABGEWAEHLT_TOOL_PATHS.get(str(werkzeug), []))
    return sorted(dict.fromkeys(pfade))

# ---------------------------------------------------------------------------
# B38: abgeschlossene Projekte (setup_complete) - Setup-only-Abschnitte, die /act-finalize (finish-setup.py)
# entfernt hat, duerfen ein Update nicht zurueckholen. Statt die Marker/Listen hier zu duplizieren, werden
# finish-setup.py und setup-lib.py als Module NACHGELADEN (importlib, gleicher Ordner) - siehe
# .templatedev/docs/project/coding_rules.md "Pfadlisten haengen zusammen". Betroffen: REMOVE_ITEMS (ganze Dateien/Ordner, z.B.
# create-project.py) und zwei Text-Ausschnitte innerhalb sonst normal gepflegter Dateien (template-only-
# Bloecke in AGENTS.md/CLAUDE.md, Checklisten-Abschnitte in docs/ai/checklists.md).
#
# SICHERHEITSREGEL (Security-Fix, 2026-09-17): finish-setup.py existiert in einem ABGESCHLOSSENEN Projekt
# lokal nicht mehr - ohne Vorsicht muesste der fehlende lokale Stand aus einem GIT-REF nachgeladen werden,
# und einer dieser Refs ist bei --check der frisch gefetchte, ungeprueft Template-Remote (--check --quiet
# laeuft als SessionStart-Hook, also OHNE menschliches Zutun). `exec_module` auf so einem Ref waere beliebige
# Codeausfuehrung direkt aus dem Remote. Deshalb zwei getrennte Wege:
#   - setup_removed_paths() (Ganzdatei-Konstanten REMOVE_ITEMS/SELF_REL, u.a. fuer --check) fuehrt NIEMALS
#     Code aus einem Ref aus - fehlt die lokale Datei, werden die beiden Konstanten rein STATISCH per `ast`
#     aus dem Ref-Text gelesen (_read_finish_setup_constants_from_ref), nie per exec_module.
#   - _strip_setup_only_text()/_resolve_setup_only_text_conflict() (nur im menschlich gestarteten --apply/
#     --continue, braucht echte Funktionen wie update_checklists()) laedt Code aus einem Ref nur, wenn dieser
#     Ref explizit als `accepted_ref` uebergeben wird (siehe _load_sibling_module) - in der Praxis
#     pre_merge_head/base_commit (Stand, den das Projekt bereits kennt), NIE MERGE_HEAD/der Template-Ref.
#     Ist dort keine finish-setup.py vorhanden, bleibt der Konflikt offen statt automatisch geloest zu werden.
# ---------------------------------------------------------------------------

_SIBLING_MODULE_CACHE = {}


def _sibling_path_conflicted(root: Path, filename: str) -> bool:
    """Review-Befund (Security-Fix, 2026-09-17): waehrend eines LAUFENDEN Merges kann git fuer einen
    'modify/delete'-Konflikt (typisch fuer finish-setup.py: das Projekt hat die Datei entfernt, das Template
    hat sie geaendert) die THEIRS-Fassung bereits unaufgeloest in den Arbeitsbaum geschrieben, BEVOR
    irgendeine Konfliktaufloesung gelaufen ist. Ein blosses `Path.is_file()` auf der Festplatte ist in diesem
    Fenster also KEIN verlaessliches Signal fuer 'lokale, bereits angenommene Datei' - es kann stattdessen
    frisch gemergten, ungeprueften Template-Inhalt liefern und exec_module wuerde ihn ausfuehren. Deshalb vor
    jedem lokalen Ladeversuch von `.claude/scripts/<filename>` pruefen, ob der Pfad gerade ein ungeloester
    Merge-Konflikt ist (`git ls-files --unmerged`) - wenn ja, gilt die Datei NICHT als lokal ladbar, der
    Aufrufer faellt auf den (accepted_ref-gesicherten) Ref-Fallback zurueck. Ohne `root` (kein Git-Kontext)
    wird nichts geprueft (False) - das entspricht dem bisherigen Verhalten ausserhalb eines Merges."""
    if root is None:
        return False
    res = run_git(root, ["ls-files", "--unmerged", "--", f".claude/scripts/{filename}"])
    return res.returncode == 0 and bool(res.stdout.strip())


def _load_sibling_module_from_path(path: Path, mod_name: str):
    """Kern von _load_sibling_module() ohne Cache: laedt genau die Datei unter `path` als Modul `mod_name`.
    Liefert None statt zu werfen, wenn die Datei fehlt oder nicht ladbar ist."""
    try:
        spec = importlib.util.spec_from_file_location(mod_name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def _load_sibling_module(filename: str, mod_name: str, root: Path = None, ref: str = None, accepted_ref=None):
    """Laedt ein Geschwister-Script (gleicher Ordner wie dieses hier) als Modul - Bindestriche im Dateinamen
    verbieten ein normales `import`, daher importlib.util wie setup-lib.py/_load_template_update_module().
    Wird nur gelesen (Konstanten/Funktionen), nie veraendert.

    Review-Befund (B38 greift nicht): in einem ABGESCHLOSSENEN Projekt hat /act-finalize (finish-setup.py)
    genau diese Datei (finish-setup.py selbst, siehe SELF_REL) bereits aus `.claude/scripts/` entfernt - der
    lokale Ladeversuch schlaegt dort also IMMER fehl, B38 griff nie. Fehlt die Datei lokal, kann sie
    stattdessen per `git show <ref>:.claude/scripts/<filename>` aus einem Git-Objekt geladen werden.

    SICHERHEITSREGEL (Security-Fix, 2026-09-17): Dieser Ref-Fallback fuehrt den geladenen Text per
    `exec_module` AUS - er darf deshalb niemals fuer einen frisch gefetchten, ungeprueften Ref laufen (z.B.
    den Template-Remote-Branch oder MERGE_HEAD eines laufenden Merges). `accepted_ref` erzwingt das: der
    Ref-Fallback wird NUR versucht, wenn `ref` in `accepted_ref` enthalten ist (ein einzelner Ref-String oder
    eine Sammlung von Refs) - der Aufrufer muss also an dieser Stelle ausdruecklich erklaeren, dass er `ref`
    fuer bereits angenommenen Projektstand haelt (typischerweise `pre_merge_head`/`base_commit`, NIE
    `MERGE_HEAD`/der Template-Ref). Fehlt `accepted_ref` oder steht `ref` nicht darin, wird der Fallback
    ueberhaupt nicht versucht (Rueckgabe wie "nicht ladbar", kein Fehler). Ist ein Ref einmal als angenommen
    geladen worden, darf das Ergebnis unter demselben (inhaltsadressierten) Commit-Hash wiederverwendet werden
    - derselbe Hash bezeichnet immer denselben Inhalt, ein zweiter Aufrufer mit demselben `ref` bekommt also
    nichts, was nicht schon einmal akzeptiert wurde.

    Bei Erfolg wird der Text in eine Temp-Datei geschrieben, importiert und die Temp-Datei danach wieder
    entfernt (shutil.rmtree, kein 'rm -rf'). Cache-Schluessel (filename, ref): verschiedene Referenzen sollen
    nicht dieselbe (evtl. veraltete) Fassung wiederverwenden. Liefert None, wenn weder lokal noch per
    akzeptiertem Git-Ref ladbar ist - der jeweilige Aufrufer ueberspringt B38 dann einfach (kein Fehler,
    altes Verhalten)."""
    cache_key = (filename, ref)
    if cache_key in _SIBLING_MODULE_CACHE:
        return _SIBLING_MODULE_CACHE[cache_key]

    local_path = Path(__file__).resolve().parent / filename
    mod = None
    if local_path.is_file() and not _sibling_path_conflicted(root, filename):
        mod = _load_sibling_module_from_path(local_path, mod_name)

    ref_ok = ref is not None and accepted_ref is not None and (
        ref == accepted_ref if isinstance(accepted_ref, str) else ref in accepted_ref
    )
    if mod is None and root is not None and ref_ok:
        res = run_git(root, ["show", f"{ref}:.claude/scripts/{filename}"])
        if res.returncode == 0 and res.stdout:
            tmp_dir = tempfile.mkdtemp(prefix="update-template-sibling-")
            try:
                tmp_path = Path(tmp_dir) / filename
                tmp_path.write_text(res.stdout, encoding="utf-8", newline="")
                mod = _load_sibling_module_from_path(tmp_path, mod_name)
            finally:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    _SIBLING_MODULE_CACHE[cache_key] = mod
    return mod


def _finish_setup_module(root: Path = None, ref: str = None, accepted_ref=None):
    return _load_sibling_module(
        "finish-setup.py", "_update_template_finish_setup", root=root, ref=ref, accepted_ref=accepted_ref
    )


def _setup_lib_module():
    """setup-lib.py wird von /act-finalize NIE entfernt (siehe Kopfkommentar dort: es bleibt dauerhaft, weil
    sync-config.py seine Funktionen laufend braucht) und liegt darum in JEDEM Projekt lokal vor - anders als
    finish-setup.py gibt es hier keinen sinnvollen Ref-Fallback (niedrige Prioritaet, Review-Befund): selbst
    wenn man ihn erzwaenge, laedt setup-lib.py beim Import seine Geschwister config-lib.py/files-lib.py/
    claudemd-lib.py relativ zu `__file__` (siehe setup-lib.py Zeilen ~95-112) - aus einem Git-Ref in ein
    Temp-Verzeichnis kopiert, fehlen diese Geschwister dort, und der Import schlaegt zuverlaessig fehl. Rein
    lokaler Ladeversuch; liefert None, wenn die Datei ausnahmsweise fehlt (Aufrufer ueberspringt B38 dann)."""
    return _load_sibling_module("setup-lib.py", "_update_template_setup_lib")


def _config_lib_module():
    # config-lib.py bleibt in JEDEM Projekt liegen (finish-setup.py:REMOVE_ITEMS entfernt es nie, siehe
    # CLAUDE.md Projektstruktur - sync-config.py braucht es laufend) - kein Git-Ref-Fallback noetig.
    return _load_sibling_module("config-lib.py", "_update_template_config_lib")


# ---------------------------------------------------------------------------
# B37: AI-CONFIG.md steht in keep_local und wird bei einem normalen Merge nie automatisch mitgezogen - neue
# Tabellen-Schluessel, die das Template mitbringt, muessen deshalb NACH einem erfolgreichen --apply/
# --continue extra ergaenzt werden. Dieselbe Logik wie sync-config.py --apply (config-lib.py:
# ai_config_missing_keys()/insert_missing_ai_config_rows(), per importlib geladen, siehe _config_lib_module
# oben), hier direkt im Anschluss an ein Template-Update statt erst beim naechsten sync-config.py-Lauf.
# ---------------------------------------------------------------------------

_CONFLICT_MARKER_RE = re.compile(r"^<<<<<<< ", re.MULTILINE)


def _has_conflict_markers(text: str) -> bool:
    """True, wenn text noch echte Git-Konfliktmarker enthaelt. 'git add' prueft den Dateiinhalt nicht - ein
    Pfad kann also als aufgeloest gelten (kein offener Konflikt mehr im Index), obwohl noch '<<<<<<<'-Zeilen
    darin stehen (versehentlich zu frueh hinzugefuegt). Genau dieser Fall darf AI-CONFIG.md nicht anfassen."""
    return bool(_CONFLICT_MARKER_RE.search(text))


def _tu_namespace():
    """Winziges Stellvertreter-Objekt mit genau den drei Funktionen, die
    config-lib.py:fetch_template_ai_config_text() als `tu` erwartet (load_template_json/compare_ref/run_git)
    - alle drei stehen bereits in DIESEM Modul. sys.modules[__name__] waere nicht zuverlaessig: wird
    update-template.py seinerseits per importlib nachgeladen (siehe setup-lib.py/config-lib.py selbst), landet
    es dort ueblicherweise gar nicht in sys.modules."""
    return types.SimpleNamespace(load_template_json=load_template_json, compare_ref=compare_ref, run_git=run_git)


def _read_text_with_newline(path: Path):
    """Minimal-Variante von files-lib.py:_read_text_preserve_newline (hier nicht nachgeladen, um keine
    weitere Modul-Abhaengigkeit fuer nur zwei Zeilen einzuziehen) - liest utf-8(-sig) und meldet, ob die
    Rohdatei CRLF enthielt, damit insert_missing_ai_config_rows() (arbeitet intern mit '\\n') beim
    Zurueckschreiben dieselbe Konvention erhaelt."""
    raw = path.read_bytes()
    newline = "\r\n" if b"\r\n" in raw else "\n"
    return raw.decode("utf-8-sig"), newline


def _write_text_with_newline(path: Path, text: str, newline: str) -> None:
    with open(path, "w", encoding="utf-8", newline=newline) as f:
        f.write(text)


def apply_ai_config_missing_keys(root: Path, cfg: dict, ref: str = None) -> list:
    """B37: nach einem erfolgreichen --apply/--continue (cmd_apply ruft das hier NUR, wenn keine Konflikte
    mehr offen sind) fehlende AI-CONFIG.md-Tabellenzeilen aus dem Template ergaenzen und 'git add'. Greift
    NIE im Template-Checkout selbst, und NIE, solange AI-CONFIG.md noch Konfliktmarker enthaelt (siehe
    _has_conflict_markers) - dann nur ein Hinweis auf 'sync-config.py --apply' nach dem manuellen Aufloesen.
    `ref`: der schon aufgeloeste Vergleichs-/Merge-Ref des Aufrufers (z.B. MERGE_HEAD) - wird UNVERAENDERT
    mit fetch=False an config-lib.py:ai_config_missing_keys() durchgereicht (Review-Befund "zweiter Fetch":
    der Aufrufer hat den Fetch fuer diesen Lauf bereits erledigt, ein zweiter waere unnoetiger
    Netzwerkzugriff).
    Rueckgabe: Report-Zeilen fuer die --apply-Ausgabe (leer = nichts zu tun/zu melden)."""
    if cfg.get("is_template"):
        return []
    cl = _config_lib_module()
    if cl is None or not hasattr(cl, "ai_config_missing_keys"):
        return []
    config_rel = getattr(cl, "CONFIG_REL", "AI-CONFIG.md")
    path = root / config_rel
    if not path.is_file():
        return []
    try:
        text, newline = _read_text_with_newline(path)
    except (OSError, UnicodeDecodeError):
        return [f"{config_rel}: nicht lesbar - Schluessel nicht ergaenzt."]
    if _has_conflict_markers(text):
        return [
            f"{config_rel}: enthaelt noch Konfliktmarker - Schluessel NICHT ergaenzt. Erst manuell "
            "aufloesen, danach 'python .claude/scripts/sync-config.py --apply' ausfuehren."
        ]
    try:
        missing, hinweise_manuell, hinweis, fehler = cl.ai_config_missing_keys(
            root, tu=_tu_namespace(), ref=ref, fetch=False
        )
    except Exception as e:  # noqa: BLE001 - darf --apply nicht zum Absturz bringen
        return [f"{config_rel}: Schluesselabgleich fehlgeschlagen ({e})."]
    lines = []
    if hinweis:
        lines.append(hinweis)
    if fehler:
        lines.append(f"{config_rel}: {fehler}")
    if missing:
        new_text = cl.insert_missing_ai_config_rows(text, missing)
        if new_text != text:
            _write_text_with_newline(path, new_text, newline)
            run_git(root, ["add", "--", config_rel])
        lines.append(
            f"{config_rel}: {len(missing)} Zeile(n) ergaenzt: "
            + ", ".join(f"{m['tabelle']}/{m['schluessel']}" for m in missing)
        )
    # Review-Befund: hinweise_manuell IMMER ausgeben, auch wenn 'missing' leer ist (vorher fruehes
    # 'return lines' bei 'if not missing' - eine ganze fehlende Tabelle oder ein verschobener Schluessel
    # brauchen die manuelle Pruefung unabhaengig davon, ob sonst noch etwas automatisch ergaenzt wurde).
    if hinweise_manuell:
        lines.append(f"{config_rel}: von Hand pruefen:")
        for eintrag in hinweise_manuell:
            lines.append(f"  - {eintrag}")
    return lines


def report_ai_config_missing(root: Path, cfg: dict, ref: str = None) -> list:
    """B37 fuer --check: nur MELDEN (nichts schreiben), ob die Template-Fassung von AI-CONFIG.md
    Tabellen-Schluessel kennt, die im Projekt fehlen. Leer, wenn nichts fehlt oder der Abgleich nicht moeglich
    ist (kein Remote, Template-Checkout selbst, Lesefehler) - config-lib.py:ai_config_missing_keys() liefert
    dafuer bereits den stillen Fallback ([], [], None, None). `ref`: wie bei apply_ai_config_missing_keys()
    der schon aufgeloeste Vergleichs-Ref des Aufrufers, fetch=False vermeidet einen zweiten 'git fetch'."""
    if cfg.get("is_template"):
        return []
    cl = _config_lib_module()
    if cl is None or not hasattr(cl, "ai_config_missing_keys"):
        return []
    try:
        missing, hinweise_manuell, _hinweis, _fehler = cl.ai_config_missing_keys(
            root, tu=_tu_namespace(), ref=ref, fetch=False
        )
    except Exception:
        return []
    config_rel = getattr(cl, "CONFIG_REL", "AI-CONFIG.md")
    lines = []
    if missing:
        lines.append(
            f"{config_rel}: {len(missing)} Schluessel im Template neu, im Projekt noch nicht: "
            + ", ".join(f"{m['tabelle']}/{m['schluessel']}" for m in missing)
        )
    # Review-Befund: hinweise_manuell (verschobene Schluessel, ganze fehlende Tabellen - schon als fertiger
    # Freitext von config-lib.py formuliert) IMMER ausgeben, nicht nur bei "ganze Tabelle(n) fehlen".
    if hinweise_manuell:
        lines.append(f"{config_rel}: von Hand pruefen:")
        for eintrag in hinweise_manuell:
            lines.append(f"  - {eintrag}")
    return lines


def _read_finish_setup_constants_from_ref(root: Path, ref: str):
    """Liest REMOVE_ITEMS/SELF_REL aus `.claude/scripts/finish-setup.py` in Ref `ref`, OHNE den Code
    auszufuehren. Sicherheitsregel (siehe B38-Kommentarblock oben): setup_removed_paths() laeuft u.a. in
    `--check`, einem SessionStart-Hook, der bei JEDEM Sitzungsstart automatisch und ohne menschliches Zutun
    auf einen frisch gefetchten, ungeprueften Template-Ref zugreift - `exec_module` waere dort beliebige
    Codeausfuehrung direkt aus dem Remote. Stattdessen wird der Quelltext per `git show` geholt und rein
    STATISCH per `ast` geparst: ausgewertet werden nur Zuweisungen auf Modulebene mit literalen Werten
    (`ast.literal_eval`) - Funktionsaufrufe, Imports, Schleifen oder sonstige dynamische Konstrukte werden
    ignoriert und koennen dadurch nichts ausloesen.

    Rueckgabe (REMOVE_ITEMS oder None, SELF_REL oder None) - None je Wert bei fehlendem Ref, Parse-Fehler
    oder wenn die Konstante keine einfache literale Zuweisung ist (z.B. aus einer zukuenftigen, anders
    aufgebauten Template-Fassung)."""
    res = run_git(root, ["show", f"{ref}:.claude/scripts/finish-setup.py"])
    if res.returncode != 0 or not res.stdout:
        return None, None
    try:
        tree = ast.parse(res.stdout)
    except Exception:
        return None, None
    remove_items, self_rel = None, None
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            value = ast.literal_eval(node.value)
        except Exception:  # TypeError bei z. B. {[1]: 2} - praeparierter Text darf --check nicht abbrechen
            continue
        if target.id == "REMOVE_ITEMS" and isinstance(value, list):
            remove_items = value
        elif target.id == "SELF_REL" and isinstance(value, str):
            self_rel = value
    return remove_items, self_rel


def _safe_rel_path(rel) -> bool:
    """Nur nicht-leere, relative Pfade ohne '..'-Segment und ohne Laufwerk/Wurzel. Schutz fuer Pfadlisten, die
    aus einem Ref gelesen werden und spaeter geloescht werden koennen: '' oder '.' waere die Projektwurzel,
    'C:/x' oder '/x' ein Ziel ausserhalb des Repos."""
    if not isinstance(rel, str) or not rel.strip():
        return False
    norm = rel.replace("\\", "/")
    if norm.startswith("/") or ":" in norm:
        return False
    teile = [t for t in norm.split("/") if t not in ("", ".")]
    return bool(teile) and ".." not in teile


def setup_removed_paths(cfg: dict, root: Path = None, ref: str = None) -> list:
    """Pfade, die /act-finalize (finish-setup.py, Liste REMOVE_ITEMS + SELF_REL) aus einem ABGESCHLOSSENEN
    Projekt entfernt hat (`setup_complete` in template.json) - dieselbe Rolle wie template_only()/
    abgewaehlte_pfade() fuer diese Kategorie: ein Update darf sie nicht zurueckholen, das Template pflegt sie
    ja fuer andere (noch nicht abgeschlossene) Projekte weiter. Leer, solange setup_complete fehlt (Einrichtung
    laeuft noch - dort SOLLEN diese Pfade normal mitkommen) oder im Template-Checkout selbst.

    Sicherheitsregel (siehe B38-Kommentarblock oben): fuehrt NIEMALS Code aus einem Ref aus, auch nicht aus
    einem `ref`, der auf den ersten Blick vertrauenswuerdig wirkt - diese Funktion laeuft u.a. in `--check`
    (SessionStart-Hook) mit dem frisch gefetchten Template-Ref. Die lokale, bereits im Projekt liegende
    finish-setup.py (falls vorhanden - siehe Review-Befund "B38 greift nicht") wird weiterhin normal per
    `exec_module` geladen, das ist im Regelfall unkritisch (eigene, bereits committete Projektdatei) - AUSSER
    waehrend eines laufenden Merges, in dem git die Datei fuer einen offenen 'modify/delete'-Konflikt schon
    mit der THEIRS-Fassung in den Arbeitsbaum geschrieben haben kann (siehe _sibling_path_conflicted): dann
    zaehlt sie NICHT als lokal ladbar. Fehlt sie lokal bzw. ist der Pfad konfliktbehaftet (der Normalfall in
    einem abgeschlossenen Projekt bzw. waehrend --apply) und ist `root`/`ref` gegeben, werden die Konstanten
    stattdessen rein STATISCH gelesen (_read_finish_setup_constants_from_ref)."""
    if cfg.get("is_template") or not cfg.get("setup_complete"):
        return []
    local_path = Path(__file__).resolve().parent / "finish-setup.py"
    if local_path.is_file() and not _sibling_path_conflicted(root, "finish-setup.py"):
        fs = _load_sibling_module_from_path(local_path, "_update_template_finish_setup")
        if fs is not None:
            items = getattr(fs, "REMOVE_ITEMS", None)
            pfade = {rel for rel, _kind in items} if isinstance(items, list) else set()
            self_rel = getattr(fs, "SELF_REL", None)
            if self_rel:
                pfade.add(self_rel)
            return sorted(pfade)
    if root is None or not ref:
        return []
    remove_items, self_rel = _read_finish_setup_constants_from_ref(root, ref)
    pfade = set()
    if isinstance(remove_items, list):
        for entry in remove_items:
            if isinstance(entry, (tuple, list)) and entry and _safe_rel_path(entry[0]):
                pfade.add(entry[0])
    if _safe_rel_path(self_rel):
        pfade.add(self_rel)
    return sorted(pfade)


# Dateien, in denen NUR ein Ausschnitt Setup-only ist (Rest bleibt normale Template-Logik, siehe
# priority_label: "Template gewinnt, Projektergaenzungen einarbeiten") - fuer diese greift setup_removed_paths()
# nicht (kein Ganzdatei-Fall), sondern _strip_setup_only_text() unten.
SETUP_ONLY_TEXT_STRIP_PATHS = ("AGENTS.md", "CLAUDE.md", "docs/ai/checklists.md")


def _strip_setup_only_text(rel_path: str, text: str, root: Path = None, accepted_refs=()):
    """Entfernt aus `text` denselben Ausschnitt, den /act-finalize aus dieser Datei entfernen wuerde -
    template-only-Bloecke (setup-lib.py: remove_template_intro()/TEMPLATE_ONLY_BLOCK) in AGENTS.md/CLAUDE.md,
    Checklisten-Abschnitte "Neues Projekt"/"Projekt nachruesten"/"Einrichtung abschliessen"
    (finish-setup.py: update_checklists()/CHECKLIST_TITLES) in docs/ai/checklists.md. Ruft dazu die ECHTEN
    Funktionen der beiden Scripte auf einem Temp-Verzeichnis auf (keine Nachbildung der Entfernungslogik) -
    reine Textoperation, ruehrt das eigentliche Projekt nicht an. `text` selbst stammt vom Aufrufer meist von
    der Template-Seite (theirs) - das ist unkritisch, hier wird nur Text verarbeitet, kein Code daraus
    ausgefuehrt.

    Sicherheitsregel (siehe B38-Kommentarblock oben): fuer AGENTS.md/CLAUDE.md wird ausschliesslich die
    lokale setup-lib.py geladen (_setup_lib_module(), IMMER vorhanden, siehe deren Docstring) - kein
    Ref-Fallback noetig oder moeglich. Fuer docs/ai/checklists.md (finish-setup.py existiert in einem
    abgeschlossenen Projekt lokal nicht mehr) wird das Modul nur aus einem Ref geladen, der in
    `accepted_refs` steht - typischerweise (pre_merge_head, base_commit), NIE der frisch gefetchte
    Template-Ref/MERGE_HEAD (siehe _load_sibling_module `accepted_ref`). Rueckgabe (neuer_text, bool
    geaendert); unveraendert (text, False), wenn kein Modul geladen werden konnte (fehlt lokal UND in jedem
    Kandidaten aus `accepted_refs`) oder nichts zu entfernen war - der Konflikt bleibt dann fuer die manuelle
    Aufloesung offen (siehe _resolve_setup_only_text_conflict)."""
    norm = rel_path.replace("\\", "/")
    if norm in ("AGENTS.md", "CLAUDE.md"):
        sl = _setup_lib_module()
        fn = getattr(sl, "remove_template_intro", None) if sl else None
        if fn is None:
            return text, False
        tmp_dir = tempfile.mkdtemp(prefix="update-template-setup-only-")
        try:
            tmp_root = Path(tmp_dir)
            fp = tmp_root / norm
            fp.write_text(text, encoding="utf-8", newline="")
            try:
                fn(tmp_root)
            except Exception:
                return text, False
            new_text = fp.read_text(encoding="utf-8")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return new_text, new_text != text
    if norm == "docs/ai/checklists.md":
        candidates = tuple(r for r in accepted_refs if r)
        fs = None
        for candidate in candidates:
            fs = _finish_setup_module(root=root, ref=candidate, accepted_ref=candidates)
            if fs is not None:
                break
        fn = getattr(fs, "update_checklists", None) if fs else None
        if fn is None:
            return text, False
        tmp_dir = tempfile.mkdtemp(prefix="update-template-setup-only-")
        try:
            tmp_root = Path(tmp_dir)
            fp = tmp_root / "docs" / "ai" / "checklists.md"
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(text, encoding="utf-8", newline="")
            try:
                fn(tmp_root, plan=False)
            except Exception:
                return text, False
            new_text = fp.read_text(encoding="utf-8")
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return new_text, new_text != text
    return text, False


def _resolve_setup_only_text_conflict(root: Path, rel_path: str, base_commit, ours_commit, theirs_commit):
    """B38: rel_path ist eine der SETUP_ONLY_TEXT_STRIP_PATHS und steht im Konflikt, das Projekt hat die
    Einrichtung bereits abgeschlossen. Entfernt aus der Template-Fassung zuerst denselben Setup-Ausschnitt,
    den /act-finalize entfernen wuerde (_strip_setup_only_text), und fuehrt danach base/ours/die bereinigte
    Template-Fassung per 'git merge-file' zusammen - meist verschwindet der Konflikt dabei vollstaendig
    (der einzige Unterschied war der Setup-Ausschnitt). Bleibt danach noch ein echter inhaltlicher Konflikt,
    wird die bereinigte Fassung trotzdem in den Arbeitsbaum geschrieben (weniger/kleinere Konfliktmarker fuer
    die manuelle Aufloesung), aber NICHT gestaged - der Pfad bleibt als offen gemeldet.

    Rueckgabe: Hinweistext bei sauberer automatischer Loesung, sonst None (kein B38-Fall, oder Restkonflikt
    bleibt offen).

    Sicherheitsregel: `theirs_commit` (MERGE_HEAD/Template-Ref) liefert hier NUR den Text der Template-Seite
    (Daten, per `git show` gelesen) - die Funktion, die diesen Text bereinigt, wird dagegen ausschliesslich
    aus `ours_commit`/`base_commit` geladen (siehe _strip_setup_only_text `accepted_refs`), also aus Stand,
    den das Projekt bereits kennt. `theirs_commit` wird nie an `_strip_setup_only_text` als ladbarer Ref
    durchgereicht."""
    theirs_res = run_git(root, ["show", f"{theirs_commit}:{rel_path}"])
    if theirs_res.returncode != 0:
        return None
    stripped_theirs, changed = _strip_setup_only_text(
        rel_path, theirs_res.stdout, root=root, accepted_refs=(ours_commit, base_commit)
    )
    if not changed:
        return None  # kein Setup-only-Ausschnitt betroffen - normaler Konflikt, bleibt offen

    ours_res = run_git(root, ["show", f"{ours_commit}:{rel_path}"])
    if ours_res.returncode != 0:
        return None
    base_res = run_git(root, ["show", f"{base_commit}:{rel_path}"]) if base_commit else None
    base_text = base_res.stdout if (base_res is not None and base_res.returncode == 0) else ""

    tmp_dir = tempfile.mkdtemp(prefix="update-template-mergefile-")
    try:
        ours_fp = Path(tmp_dir) / "ours"
        base_fp = Path(tmp_dir) / "base"
        theirs_fp = Path(tmp_dir) / "theirs"
        ours_fp.write_text(ours_res.stdout, encoding="utf-8", newline="")
        base_fp.write_text(base_text, encoding="utf-8", newline="")
        theirs_fp.write_text(stripped_theirs, encoding="utf-8", newline="")
        try:
            res_mf = subprocess.run(
                ["git", "merge-file", "-p", "-L", "HEAD", "-L", "base", "-L", "Template (Setup-Abschnitt entfernt)",
                 str(ours_fp), str(base_fp), str(theirs_fp)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
        except OSError:
            return None
        # Review-Befund: 'git merge-file' liefert bei einem sauberen Merge 0, bei N verbleibenden Konflikten
        # N (>0, Ausgabe mit Konfliktmarkern - beides gueltiger Text auf stdout) und bei einem echten Fehler
        # (ungueltige Eingabe, per Signal beendet) < 0 bzw. >= 128 - dort ist stdout nicht vertrauenswuerdig
        # (kann leer oder unvollstaendig sein). In diesem Fehlerfall NICHTS schreiben und den Konflikt so
        # stehen lassen, wie er vor diesem Versuch war, statt eine kaputte Datei in den Arbeitsbaum zu legen.
        if res_mf.returncode < 0 or res_mf.returncode >= 128 or not res_mf.stdout:
            return None
        (root / rel_path).write_text(res_mf.stdout, encoding="utf-8", newline="")
        if res_mf.returncode == 0:
            run_git(root, ["add", "--", rel_path])
            return "Setup-Abschnitt aus Template-Seite verworfen, danach konfliktfrei gemergt"
        return None  # echter Restkonflikt (1..127) - Datei hat jetzt weniger Marker, bleibt aber offen
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# Prioritaetsregel je Pfad fuer --conflicts (dieselbe Aussage wie PRIORITY_RULES/priority_label in
# rename-lib.py - dort nachsehen/nachziehen, falls sich die Regeln je aendern - z.B. die
# docs/ai/resources.md-Sonderregel unten). Die Regeln stehen hier nur noch als priority_label()-Logik, ohne
# eigene String-Konstante (die gab es fuer --conflicts nie zu lesen).


def priority_label(rel_path: str) -> str:
    norm = rel_path.replace("\\", "/")
    if norm in ("AGENTS.md", "CLAUDE.md", "docs/ai/checklists.md", "docs/ai/README.md") or norm.startswith(".claude/"):
        return "Template gewinnt, Projektergaenzungen einarbeiten"
    if norm == "docs/project/coding_rules.md":
        return "strengere Regel gewinnt"
    if norm.startswith("docs/project/"):
        return "Projekt gewinnt"
    # docs/ai/resources.md pflegt das TEMPLATE (kuratierte Linksammlung), nicht das Projekt - anders als der
    # Rest von docs/ai/. Ausnahme: der Abschnitt "Eigene Quellen dieses Projekts" am Ende der Datei ist
    # Projekt-Inhalt und bleibt beim Projekt. Muss VOR der allgemeinen docs/ai/-Regel stehen, sonst greift sie
    # nie (die naechste Regel unten ist ebenfalls startswith("docs/ai/") und wuerde sonst zuerst zutreffen).
    if norm == "docs/ai/resources.md":
        return "Template gewinnt, nur Abschnitt 'Eigene Quellen dieses Projekts' bleibt beim Projekt"
    if norm.startswith("docs/ai/"):
        return "Template-Struktur, Projekt-Inhalt"
    if norm in ("README.md", ".gitignore"):
        return "Projekt gewinnt, Template ergaenzt"
    return "abwaegen"


# XY-Status (git status --porcelain=v1) -> (kurzes Ein-Wort-Label fuer die --apply-Konfliktliste,
# ausfuehrliche Art-Beschreibung fuer --conflicts). "DU"/"UD" beziehen sich auf HEAD ("uns", das Projekt);
# beim Merge template -> Projekt ist "uns" also immer das Projekt, "die andere Seite" das Template.
_CONFLICT_KINDS = {
    "UU": ("beide-geaendert", "beide geaendert"),
    "AA": ("beide-neu", "von beiden neu angelegt"),
    "DU": ("geloescht/geaendert", "vom Projekt geloescht, im Template geaendert"),
    "UD": ("geaendert/geloescht", "vom Projekt geaendert, im Template geloescht"),
    "DD": ("beide-geloescht", "von beiden geloescht"),
    "AU": ("neu/geaendert", "vom Projekt neu angelegt, im Template geaendert"),
    "UA": ("geaendert/neu", "vom Projekt geaendert, im Template neu angelegt"),
}


def _conflict_kind_word(code: str) -> str:
    return _CONFLICT_KINDS.get(code, (code or "?", code or "unbekannt"))[0]


def _conflict_art(code: str) -> str:
    return _CONFLICT_KINDS.get(code, (code or "?", code or "unbekannt"))[1]


TEMPLATE_JSON_REL = ".claude/template.json"

_HINWEIS = (
    "Speichert die Herkunft dieses Projekts gegenueber dem Template (Remote, Basis-Commit, eingesetzte "
    "Platzhalterwerte) fuer spaetere Updates per Merge. Wird von `update-template.py --init` befuellt; "
    "`values` nie Secrets."
)


# ---------------------------------------------------------------------------
# Grundlagen
# ---------------------------------------------------------------------------


def _find_root() -> Path:
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[2]


def run_git(root: Path, args, timeout=None):
    # core.quotePath=false: Pfade mit Umlauten kommen unveraendert zurueck (sonst "docs/\303\234bersicht.md"
    # und der Pfad laesst sich weder oeffnen noch an git zurueckgeben).
    # GIT_TERMINAL_PROMPT=0 + stdin=DEVNULL: nie interaktiv nach Zugangsdaten fragen - im SessionStart-Hook
    # wuerde das haengen, statt eines Fehlers.
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


def _remote_exists(root: Path, remote: str) -> bool:
    res = run_git(root, ["remote"])
    remotes = res.stdout.split() if res.returncode == 0 else []
    return remote in remotes


def compare_ref(root: Path, cfg: dict):
    """Vergleichsziel fuer Template-Updates -> (ref, fetch_noetig) oder (None, False).

    Normalfall: der Remote-Branch `<remote>/<branch>`. Entsteht das Projekt dagegen als Branch im
    Template-Checkout selbst (create-project.py setzt dann base_commit aus main/master), gibt es keinen
    passenden Remote - dann wird gegen den gleichnamigen LOKALEN Branch verglichen und nicht gefetcht."""
    remote = cfg.get("template_remote") or "template"
    branch = cfg.get("template_branch") or "main"
    if _remote_exists(root, remote):
        return f"{remote}/{branch}", True
    if run_git(root, ["rev-parse", "--verify", "--quiet", branch]).returncode == 0:
        return branch, False
    return None, False


def default_config() -> dict:
    return {
        "template_remote": "template",
        "template_branch": "main",
        "template_url": None,
        "base_commit": None,
        "values": {k: None for k in DEFAULT_VALUE_KEYS},
        "keep_local": list(DEFAULT_KEEP_LOCAL),
        "no_replace": list(DEFAULT_NO_REPLACE),
        "template_only": list(DEFAULT_TEMPLATE_ONLY),
        "updates": [],
        "_hinweis": _HINWEIS,
    }


def load_template_json(root: Path):
    path = root / TEMPLATE_JSON_REL
    cfg = default_config()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                cfg.update(data)
                if not isinstance(cfg.get("values"), dict):
                    cfg["values"] = default_config()["values"]
                if not isinstance(cfg.get("keep_local"), list):
                    cfg["keep_local"] = list(DEFAULT_KEEP_LOCAL)
                if not isinstance(cfg.get("no_replace"), list):
                    cfg["no_replace"] = list(DEFAULT_NO_REPLACE)
                if not isinstance(cfg.get("template_only"), list):
                    cfg["template_only"] = list(DEFAULT_TEMPLATE_ONLY)
                if not isinstance(cfg.get("updates"), list):
                    cfg["updates"] = []
        except (OSError, ValueError):
            pass  # kaputte/unlesbare Datei -> mit Default weiterarbeiten, wird beim naechsten Save repariert
    return cfg, path


def save_template_json(root: Path, cfg: dict, path: Path) -> None:
    ordered = {
        "template_remote": cfg.get("template_remote", "template"),
        "template_branch": cfg.get("template_branch", "main"),
        "template_url": cfg.get("template_url"),
        "base_commit": cfg.get("base_commit"),
        "values": cfg.get("values") or {},
        "keep_local": cfg.get("keep_local") or list(DEFAULT_KEEP_LOCAL),
        "no_replace": cfg.get("no_replace") if isinstance(cfg.get("no_replace"), list) else list(DEFAULT_NO_REPLACE),
        "template_only": cfg.get("template_only") if isinstance(cfg.get("template_only"), list) else list(DEFAULT_TEMPLATE_ONLY),
        "updates": cfg.get("updates") or [],
    }
    # Unbekannte Felder (z.B. "is_template", vom Template-Checkout selbst gesetzt) nicht verwerfen - nur
    # die oben bereits behandelten Schluessel und den abschliessenden Hinweistext auslassen.
    for key, value in cfg.items():
        if key in ordered or key == "_hinweis":
            continue
        ordered[key] = value
    ordered["_hinweis"] = cfg.get("_hinweis") or _HINWEIS
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomar schreiben: erst in eine Temp-Datei im selben Verzeichnis, dann per os.replace an ihren Platz -
    # bricht der Lauf (z.B. --apply) danach ab, bleibt entweder der alte oder der vollstaendige neue Stand
    # liegen, nie ein halb geschriebener. Die Temp-Datei bleibt bei einem Fehler nicht liegen.
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=str(path.parent),
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as f:
            tmp_path = f.name
            json.dump(ordered, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    except BaseException:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        raise


def matches_keep_local(rel_path: str, patterns) -> bool:
    norm = rel_path.replace("\\", "/")
    for pat in patterns:
        if fnmatch.fnmatchcase(norm, pat):
            return True
        # Ein Muster ohne Wildcard-Zeichen steht fuer eine einzelne Datei ODER einen ganzen Ordner (z.B.
        # ".templatedev" in DEFAULT_TEMPLATE_ONLY - dort bare, weil _remove_template_only() den Pfad direkt
        # fuer Path.exists()/is_dir()/`git rm -r -f` braucht). Ohne diese Zeile wuerde ein solcher
        # Ordner-Eintrag keine der Dateien darunter treffen, weil fnmatch ohne Wildcard nur exakte Gleichheit
        # kennt - die Datei muesste sonst zusaetzlich als Wildcard-Variante gepflegt werden.
        if not any(ch in pat for ch in "*?[") and norm.startswith(pat.rstrip("/") + "/"):
            return True
    return False


def _short(root: Path, commit: str) -> str:
    if not commit:
        return "?"
    res = run_git(root, ["rev-parse", "--short", commit])
    return res.stdout.strip() if res.returncode == 0 else str(commit)[:7]


# ---------------------------------------------------------------------------
# --init / --set
# ---------------------------------------------------------------------------


def cmd_init(root: Path, cfg: dict, path: Path, url_arg, base_arg, set_pairs) -> int:
    remote = cfg.get("template_remote") or "template"
    branch = cfg.get("template_branch") or "main"

    if not _remote_exists(root, remote):
        url = url_arg or cfg.get("template_url")
        if not url:
            print(
                f"Fehler: kein Remote '{remote}' vorhanden und keine URL angegeben. Mit --url <URL> "
                f"angeben, oder vorher 'git remote add {remote} <URL>' ausfuehren.",
                file=sys.stderr,
            )
            return 2
        res_add = run_git(root, ["remote", "add", remote, url])
        if res_add.returncode != 0:
            print(f"Fehler: 'git remote add {remote} {url}' fehlgeschlagen: {res_add.stderr.strip()}", file=sys.stderr)
            return 2
        cfg["template_url"] = url
    else:
        if url_arg:
            cfg["template_url"] = url_arg
        elif not cfg.get("template_url"):
            res_url = run_git(root, ["remote", "get-url", remote])
            if res_url.returncode == 0:
                cfg["template_url"] = res_url.stdout.strip()

    res_fetch = run_git(root, ["fetch", remote])
    if res_fetch.returncode != 0:
        print(f"Fehler: 'git fetch {remote}' fehlgeschlagen: {res_fetch.stderr.strip()}", file=sys.stderr)
        return 2

    if base_arg:
        res_verify = run_git(root, ["rev-parse", "--verify", base_arg])
        if res_verify.returncode != 0:
            print(f"Fehler: --base {base_arg} ist kein gueltiger Commit.", file=sys.stderr)
            return 2
        base_full = res_verify.stdout.strip()
    else:
        res_mb = run_git(root, ["merge-base", "HEAD", f"{remote}/{branch}"])
        if res_mb.returncode != 0:
            print(
                f"Fehler: kein gemeinsamer Vorfahr zwischen HEAD und {remote}/{branch} gefunden. Entweder "
                "--base <HASH> angeben, oder sicherstellen, dass dieses Projekt per "
                "'git clone <Template-URL> <projekt>' + 'git remote rename origin template' angelegt wurde "
                "(gemeinsame Historie mit dem Template).",
                file=sys.stderr,
            )
            return 2
        base_full = res_mb.stdout.strip()

    cfg["base_commit"] = base_full
    _apply_set_pairs(cfg, set_pairs)

    save_template_json(root, cfg, path)
    print_status(root, cfg)
    return 0


def _apply_set_pairs(cfg: dict, set_pairs) -> None:
    values = cfg.setdefault("values", {})
    for pair in set_pairs or []:
        if "=" not in pair:
            print(f"Warnung: --set {pair} ignoriert (erwartet KEY=WERT).", file=sys.stderr)
            continue
        key, value = pair.split("=", 1)
        values[key.strip()] = value


def cmd_set(root: Path, cfg: dict, path: Path, set_pairs) -> int:
    if not set_pairs:
        print("Fehler: --set benoetigt mindestens ein KEY=WERT.", file=sys.stderr)
        return 2
    _apply_set_pairs(cfg, set_pairs)
    save_template_json(root, cfg, path)
    print("Werte gespeichert:")
    for k, v in (cfg.get("values") or {}).items():
        if v is not None:
            print(f"  {k} = {v}")
    return 0


# ---------------------------------------------------------------------------
# --check
# ---------------------------------------------------------------------------


def cmd_check(root: Path, cfg: dict, quiet: bool) -> int:
    remote = cfg.get("template_remote") or "template"
    branch = cfg.get("template_branch") or "main"

    # B36: ein liegen gebliebener, bereits fertig gemergter aber nie committeter Merge ist wichtiger als jede
    # quiet-Unterdrueckung - erscheint sonst bei jedem Sitzungsstart nicht, obwohl der Arbeitsbaum seit dem
    # letzten '--apply' einen halben Merge traegt. Nur fuer Merges vom Template-Remote (siehe
    # _merge_is_from_template) - ein gewoehnlicher Feature-Merge geht diesen Hook nichts an.
    merge_head = _merge_head(root)
    if merge_head and _merge_is_from_template(root, cfg, merge_head):
        offene, _status_map = _list_conflicts(root)
        if offene:
            print(f"Template-Update: Merge laeuft noch (MERGE_HEAD {merge_head[:7]}), {len(offene)} "
                  "Konflikt(e) offen - '--conflicts' zeigt sie, danach '--continue [--commit]'.")
        else:
            print(f"Template-Update: WARNUNG - Merge ist fertig aufgeloest (MERGE_HEAD {merge_head[:7]}), "
                  "aber noch NICHT committet. Erst 'git commit' (bzw. '--continue --commit'), sonst bleibt "
                  "der Arbeitsbaum als halber Merge stehen.")
        return 3

    ref, fetch_noetig = compare_ref(root, cfg)
    if cfg.get("base_commit") is None or ref is None:
        if quiet:
            return 0
        print(f"Template-Update: nicht konfiguriert (Remote '{remote}' bzw. Branch '{branch}'/base_commit "
              "fehlt) - zuerst '--init' ausfuehren.")
        return 2

    if fetch_noetig:
        try:
            res_fetch = run_git(root, ["fetch", remote], timeout=20)
        except subprocess.TimeoutExpired:
            if quiet:
                return 0
            print(f"Template-Update: 'git fetch {remote}' hat das Zeitlimit (20s) ueberschritten.")
            return 2
        if res_fetch.returncode != 0:
            if quiet:
                return 0
            print(f"Template-Update: 'git fetch {remote}' fehlgeschlagen: {res_fetch.stderr.strip()}")
            return 2

    base = cfg["base_commit"]
    res_count = run_git(root, ["rev-list", "--count", f"{base}..{ref}"])
    if res_count.returncode != 0:
        if quiet:
            return 0
        print(f"Template-Update: Vergleich fehlgeschlagen ({res_count.stderr.strip()}).")
        return 2
    try:
        count = int(res_count.stdout.strip() or "0")
    except ValueError:
        count = 0

    if count == 0:
        # B37: auch ohne ausstehende Commits koennen im Template neue AI-CONFIG.md-Schluessel stecken, die
        # dieses Projekt (keep_local, nie automatisch gemergt) noch nicht kennt. 'ref' ist hier bereits
        # aufgeloest (und ggf. schon gefetcht, siehe oben) - report_ai_config_missing() bekommt ihn samt
        # fetch=False mit, loest also KEINEN zweiten 'git fetch' mehr aus (Review-Befund "zweiter Fetch").
        # Trotzdem NICHT unter --quiet: der SessionStart-Hook soll keine zusaetzliche Ausgabe bekommen, die
        # dort niemand liest - interaktiv (ohne --quiet) bleibt der Hinweis erhalten.
        if not quiet:
            ai_config_lines = report_ai_config_missing(root, cfg, ref=ref)
            if ai_config_lines:
                for line in ai_config_lines:
                    print(line)
                return 0
            print(f"Template-Update: aktuell (kein Unterschied zu {ref}).")
        return 0

    base_short = _short(root, base)
    head_short = _short(root, ref)

    lines = [f"Template-Update verfuegbar: {count} Commits (base {base_short} -> {head_short})", ""]
    res_log = run_git(root, ["log", "--oneline", f"{base}..{ref}"])
    if res_log.returncode == 0:
        lines.extend(res_log.stdout.splitlines()[:20])

    keep_local = cfg.get("keep_local") or []
    template_only = cfg.get("template_only") or []
    is_template = bool(cfg.get("is_template"))
    res_diff = run_git(root, ["diff", "--name-status", f"{base}..{ref}"])
    diff_lines_raw = res_diff.stdout.splitlines() if res_diff.returncode == 0 else []

    # template_only-Pfade (siehe DEFAULT_TEMPLATE_ONLY) NIE als einzuspielende Aenderung zeigen - sie werden
    # nie ins Projekt gemergt (--apply raeumt sie danach ohnehin wieder weg). Greift nie im Template-Checkout
    # selbst (is_template): dort sind es normale, gepflegte Dateien.
    abgewaehlt = abgewaehlte_pfade(cfg)
    setup_removed = setup_removed_paths(cfg, root=root, ref=ref)
    normal_lines, template_only_lines, abgewaehlt_lines, setup_removed_lines = [], [], [], []
    for raw_line in diff_lines_raw:
        parts = raw_line.split("\t")
        rel_path = parts[-1] if parts else raw_line
        if not is_template and matches_keep_local(rel_path, template_only):
            template_only_lines.append(rel_path)
        elif not is_template and matches_keep_local(rel_path, abgewaehlt):
            # Die Vorschau darf nichts ankuendigen, was --apply anschliessend wieder wegraeumt.
            abgewaehlt_lines.append(rel_path)
        elif not is_template and matches_keep_local(rel_path, setup_removed):
            # B38: /act-finalize hat den Pfad aus diesem abgeschlossenen Projekt entfernt - kommt beim
            # Merge nicht zurueck, siehe cmd_apply().
            setup_removed_lines.append(rel_path)
        else:
            normal_lines.append(raw_line)

    lines.append("")
    lines.append("Geaenderte Dateien:")
    for raw_line in normal_lines[:30]:
        parts = raw_line.split("\t")
        rel_path = parts[-1] if parts else raw_line
        marker = "  (keep_local)" if matches_keep_local(rel_path, keep_local) else ""
        lines.append(raw_line + marker)

    if template_only_lines:
        lines.append("")
        lines.append("Nur im Template, wird nicht eingespielt:")
        for rel_path in template_only_lines[:30]:
            lines.append(f"  {rel_path}")

    if abgewaehlt_lines:
        lines.append("")
        lines.append("Abgewaehlt (AI-CONFIG.md), wird nicht eingespielt:")
        for rel_path in abgewaehlt_lines[:30]:
            lines.append(f"  {rel_path}")

    if setup_removed_lines:
        lines.append("")
        lines.append("Setup abgeschlossen (/act-finalize entfernt), wird nicht eingespielt:")
        for rel_path in setup_removed_lines[:30]:
            lines.append(f"  {rel_path}")

    # Review-Befund "zweiter Fetch": 'ref' ist hier bereits aufgeloest/gefetcht (siehe oben) - fetch=False
    # in report_ai_config_missing() erspart einen zweiten 'git fetch'. Weiterhin nur interaktiv (nicht unter
    # --quiet/SessionStart-Hook), damit dort keine zusaetzliche Ausgabe entsteht, die niemand liest.
    if not quiet:
        ai_config_lines = report_ai_config_missing(root, cfg, ref=ref)
        if ai_config_lines:
            lines.append("")
            lines.extend(ai_config_lines)

    lines.append("")
    lines.append("Einspielen: Skill /act-update-template bzw. python .claude/scripts/update-template.py --apply")
    print("\n".join(lines))
    return 3


# ---------------------------------------------------------------------------
# --apply / --continue
# ---------------------------------------------------------------------------


def get_unmerged_status(root: Path) -> dict:
    """path -> XY-Statuscode fuer alle unaufgeloesten (unmerged) Pfade.

    '-z' ist Pflicht: ohne das setzt `git status --porcelain` Pfade mit Leerzeichen in Anfuehrungszeichen
    ("docs/project/mit leer zeichen.md") - core.quotePath=false schaltet nur das Oktal-Escaping der Umlaute
    ab, nicht die Anfuehrungszeichen. Ein so verpackter Pfad passt auf kein keep_local-Muster und laesst
    sich nicht an git zurueckgeben; der Konflikt bliebe stumm liegen."""
    res = run_git(root, ["status", "--porcelain=v1", "-z"])
    out = {}
    if res.returncode != 0:
        return out
    records = [r for r in res.stdout.split("\0") if r]
    idx = 0
    while idx < len(records):
        record = records[idx]
        idx += 1
        if len(record) < 4:
            continue
        code = record[:2]
        rel_path = record[3:]
        # Bei Umbenennungen/Kopien folgt der alte Pfad als eigener Datensatz - ueberspringen, sonst wird er
        # als eigener Eintrag fehlgedeutet.
        if code[0] in ("R", "C") or code[1] in ("R", "C"):
            idx += 1
            continue
        if code[0] == "U" or code[1] == "U" or code in ("DD", "AA"):
            out[rel_path] = code
    return out


def _remaining_conflicts(root: Path):
    # -z wie in get_unmerged_status: keine Anfuehrungszeichen/Escapes um Sonderpfade.
    res = run_git(root, ["diff", "--name-only", "-z", "--diff-filter=U"])
    if res.returncode != 0:
        return []
    return [p for p in res.stdout.split("\0") if p.strip()]


def _list_conflicts(root: Path):
    """Alle noch offenen Konflikt-Pfade -> (sortierte Liste, Pfad->XY-Code). Vereinigung aus
    '--diff-filter=U' und 'status --porcelain=v1' (siehe get_unmerged_status) - deckt auch die Faelle ab,
    die im jeweils anderen Kommando fehlen wuerden (z.B. DD)."""
    status_map = get_unmerged_status(root)
    paths = set(status_map.keys())
    paths.update(_remaining_conflicts(root))
    return sorted(paths), status_map


def _merge_head(root: Path):
    res = run_git(root, ["rev-parse", "-q", "--verify", "MERGE_HEAD"])
    return res.stdout.strip() if res.returncode == 0 else None


def _merge_is_from_template(root: Path, cfg: dict, merge_head: str) -> bool:
    """B36: grobe, netzwerkfreie Erkennung, ob ein laufender Merge (MERGE_HEAD) vom Template-Remote stammt -
    fuer die Warnung in --check/--status vor einem halb abgeschlossenen Template-Update. Prueft nur den
    bereits lokal bekannten Stand (kein fetch - --check --quiet laeuft als SessionStart-Hook und darf nicht
    zusaetzlich Netzwerkzeit kosten): merge_head gilt als "vom Template" wenn er Vorfahr von (oder gleich)
    dem Remote-Tracking-Branch <remote>/<branch> ist.

    Review-Befund: bewusst KEIN Rueckfall auf den gleichnamigen LOKALEN Branch, wenn der Remote fehlt - anders
    als compare_ref() (dort ein legitimer Sonderfall: Projekt als Branch im Template-Checkout selbst). Hier
    waere das ein staendiger Fehlalarm: Nach jedem gewoehnlichen Merge in den lokalen 'main' ist der gemergte
    Commit trivialerweise dessen Vorfahr, ganz unabhaengig vom Template. Ohne bekannten Template-Remote also
    lieber False (keine Warnung) als ein falscher Alarm bei jedem Feature-Merge."""
    if not merge_head:
        return False
    remote = cfg.get("template_remote") or "template"
    branch = cfg.get("template_branch") or "main"
    if not _remote_exists(root, remote):
        return False
    candidate = f"{remote}/{branch}"
    if run_git(root, ["rev-parse", "--verify", "--quiet", candidate]).returncode != 0:
        return False
    res = run_git(root, ["merge-base", "--is-ancestor", merge_head, candidate])
    return res.returncode == 0


def _find_renames(root: Path, ref_a, ref_b: str) -> dict:
    """Git-eigene Rename-Erkennung ref_a..ref_b (Default-Aufruf: base_commit..HEAD) -> {alter_pfad:
    (neuer_pfad, aehnlichkeit_als_string)}. Leer, wenn ref_a fehlt oder der Aufruf fehlschlaegt."""
    if not ref_a:
        return {}
    res = run_git(root, ["diff", "--find-renames=40%", "--name-status", ref_a, ref_b])
    if res.returncode != 0:
        return {}
    mapping = {}
    for line in res.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or not parts[0].startswith("R"):
            continue
        mapping[parts[1]] = (parts[2], parts[0][1:])
    return mapping


def _cap_text(text: str) -> str:
    """Vergleichstext beschneiden: erste 200 Zeilen, hoechstens 20000 Zeichen. Die Zeichengrenze ist
    noetig, weil ratio() quadratisch laeuft - 200 Zeilen koennen auch 1 MB sein (generierte Dateien)."""
    return "\n".join(text.splitlines()[:200])[:20000]


def _similarity(a: str, b: str) -> float:
    """Inhaltsaehnlichkeit 0..1. quick_ratio() taugt NUR als billiger Vorfilter (obere Schranke): sie
    zaehlt gemeinsame Zeichen ohne Reihenfolge und liegt fuer zwei beliebige deutsche Markdown-Skelette
    bei 0.75-0.90, fuer zwei Zufallstexte sogar bei 0.998 - als Mass waere jede Datei die Umbenennung
    jeder anderen. Gemessen wird darum mit ratio(), und mit autojunk=False: die Heuristik haelt bei
    Zeichenvergleichen jedes haeufige Zeichen fuer "Junk" und drueckt echte Umbenennungen mit
    Nacharbeit von 0.78 auf 0.40."""
    if difflib.SequenceMatcher(None, a, b).quick_ratio() < 0.60:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def _rename_fallback_scan(root: Path, rel_path: str, template_ref: str):
    """Kein Treffer per Git-Rename-Erkennung -> unter docs/ai/ nach .md-Dateien suchen, deren Inhalt (erste
    200 Zeilen) zu >= 60% mit der Template-Fassung von rel_path uebereinstimmt (SequenceMatcher, Stdlib,
    siehe _similarity). Liefert (rel_kandidat, ratio) oder None."""
    res = run_git(root, ["show", f"{template_ref}:{rel_path}"])
    if res.returncode != 0:
        return None
    template_text = _cap_text(res.stdout)
    docs_ai = root / "docs" / "ai"
    if not docs_ai.is_dir():
        return None
    own_name = Path(rel_path).name
    best = None
    for fp in sorted(docs_ai.glob("*.md")):
        if fp.name == own_name:
            continue
        try:
            content = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        ratio = _similarity(template_text, _cap_text(content))
        if ratio >= 0.60 and (best is None or ratio > best[1]):
            best = (fp.relative_to(root).as_posix(), ratio)
    return best


def _rename_candidate(root: Path, rel_path: str, rename_map: dict, merge_head):
    """(neuer_pfad, aehnlichkeit_in_prozent_oder_None) oder None - erst git-Rename-Erkennung (rename_map,
    siehe _find_renames), dann Fallback ueber Inhaltsaehnlichkeit unter docs/ai/ gegen die Template-Fassung
    (merge_head:rel_path). Nur fuer "DU"-Konflikte sinnvoll."""
    hit = rename_map.get(rel_path)
    if hit:
        neu, score = hit
        try:
            return neu, int(score)
        except ValueError:
            return neu, None
    if merge_head:
        fb = _rename_fallback_scan(root, rel_path, merge_head)
        if fb:
            return fb[0], int(round(fb[1] * 100))
    return None


def _reverse_rename(rename_map: dict, new_path: str):
    """Kehrt eine Rename-Map (alter_pfad -> (neuer_pfad, ...)) um: liefert den alten Pfad, dessen Ziel
    new_path ist, oder None."""
    for alt, (neu, _score) in rename_map.items():
        if neu == new_path:
            return alt
    return None


def _rename_pair_both_sides(rel_path: str, code: str, rename_map: dict, rename_map_theirs: dict):
    """Fuer "AU"/"UA"-Konflikte (rename/rename: beide Seiten haben dieselbe Basisdatei verschoben, aber auf
    unterschiedliche neue Pfade) -> (projekt_pfad, template_pfad) oder None, wenn die andere Seite nicht
    ueber die Git-Rename-Erkennung auffindbar ist. rename_map = base..HEAD (Projekt), rename_map_theirs =
    base..Template. rel_path ist bereits einer der beiden Zielpfade (der eigene, laut code)."""
    if code == "AU":
        alt = _reverse_rename(rename_map, rel_path)
        if alt is None:
            return None
        hit = rename_map_theirs.get(alt)
        if not hit:
            return None
        return rel_path, hit[0]
    if code == "UA":
        alt = _reverse_rename(rename_map_theirs, rel_path)
        if alt is None:
            return None
        hit = rename_map.get(alt)
        if not hit:
            return None
        return hit[0], rel_path
    return None


def _sh_quote(rel_path: str) -> str:
    """Pfad so einfassen, dass der ausgegebene git-Befehl auch mit Leerzeichen kopierbar bleibt."""
    if all(c.isalnum() or c in "._-/" for c in rel_path):
        return rel_path
    return "'" + rel_path.replace("'", "'\\''") + "'"


def _numstat_lines(root: Path, ref_a, ref_b, rel_path: str):
    """Summe added+deleted Zeilen (git diff --numstat) fuer rel_path zwischen ref_a und ref_b - oder None
    bei fehlender Ref, Fehler oder Binaerdatei ("-" statt Zahl)."""
    if not ref_a or not ref_b:
        return None
    res = run_git(root, ["diff", "--numstat", ref_a, ref_b, "--", rel_path])
    if res.returncode != 0:
        return None
    out = res.stdout.strip()
    if not out:
        # Leere Ausgabe heisst "unveraendert" (0) ODER "auf beiden Seiten gar nicht vorhanden" - letzteres
        # bei umbenannten Pfaden. Dann ist "0 Zeilen geaendert" irrefuehrend ("Template hat nichts
        # geaendert, also Projektfassung nehmen"), richtig ist "?".
        if run_git(root, ["cat-file", "-e", f"{ref_b}:{rel_path}"]).returncode != 0:
            return None
        return 0
    parts = out.splitlines()[0].split("\t")
    if len(parts) < 2:
        return None
    try:
        return int(parts[0]) + int(parts[1])
    except ValueError:
        return None


def _print_unresolved(root: Path, still_open, intro: str) -> None:
    status_map = get_unmerged_status(root)
    print(intro, file=sys.stderr)
    for rel_path in still_open:
        kind = _conflict_kind_word(status_map.get(rel_path, "?"))
        print(f"  - {rel_path}  ({kind})", file=sys.stderr)
    print("Analyse je Konflikt: python .claude/scripts/update-template.py --conflicts", file=sys.stderr)


def _git_show_json(root: Path, revision: str, rel_path: str):
    """git show <revision>:<rel_path> -> geparstes JSON-Dict. revision ist ein normaler Commit/Branch-Verweis
    (z.B. der Stand vor dem Merge, oder die Vergleichs-Ref des Templates) - KEIN Merge-Stage-Index: waehrend
    eines echten Konflikts gibt es zwar zusaetzlich ":2"/":3" im Index, aber .claude/template.json mergt git
    bei reinen Listenergaenzungen an unterschiedlichen Stellen oft klaglos OHNE Konflikt (siehe Kopfkommentar/
    _resolve_template_json_merge) - dann existieren gar keine Stages, wohl aber die beiden Commits.

    Rueckgabe (dict, False) bei Erfolg, (None, False) wenn der Pfad bei dieser Revision fehlt (kein Fehler -
    z.B. "both added": vor dem Merge existierte die Datei projektseitig noch nicht), (None, True) wenn
    Inhalt vorhanden, aber kein gueltiges JSON-Objekt (echter Parse-Fehler)."""
    res = run_git(root, ["show", f"{revision}:{rel_path}"])
    if res.returncode != 0:
        return None, False
    try:
        data = json.loads(res.stdout)
    except ValueError:
        return None, True
    if not isinstance(data, dict):
        return None, True
    return data, False


# Felder, die bei einem Konflikt auf .claude/template.json IMMER aus der Projektfassung (ours) stammen UND
# OHNE Rueckfall auf theirs, wenn ours das Feld nicht hat ("fehlt im Projekt" heisst hier "soll fehlen", nicht
# "aus dem Template nachladen") - je Feld begruendet:
#   - is_template: Sentinel des Template-Checkouts selbst (create-project.py entfernt ihn dort, wo daraus
#     ein echtes Projekt wird). Faellt er im Projekt weg, darf ein Merge ihn nicht aus dem Template
#     zurueckholen - genau das war der Review-Fund (Projekt hielt sich danach faelschlich fuer den
#     Template-Checkout).
#   - base_commit/updates: reine Projekt-Historie GEGENUEBER diesem Template - die eigene template.json des
#     Templates hat dazu keine sinnvolle Aussage (dort stehen bestenfalls null/[]). base_commit wird direkt
#     danach in _finalize ohnehin ueberschrieben, updates dort fortgeschrieben - ein Theirs-Fallback waere
#     hier zwar folgenlos, aber semantisch falsch, deshalb einheitlich behandelt.
#   - template_remote/template_branch/template_url: wo DIESES Projekt sein Template findet - eine
#     Projektentscheidung (--init/--url), keine Aussage des Templates ueber sich selbst.
# "values" ist bewusst NICHT hier drin: dort gewinnt zwar ebenfalls immer der Projektwert je Schluessel, aber
# neue Platzhalter, die nur das Template mitbringt, muessen ergaenzt werden (sonst bleiben sie in
# Zieldateien als "{{NEUER_PLATZHALTER}}" unersetzt stehen) - kein Ganzfeld-Fallback wie bei den obigen
# Feldern, siehe _merge_template_json_values().
_TEMPLATE_JSON_OURS_FIELDS = (
    "base_commit",
    "updates",
    "template_remote",
    "template_branch",
    "template_url",
    "is_template",
)


def _merge_template_json_values(ours_values, theirs_values):
    """Merged das 'values'-Dict (Platzhalterwerte) schluesselweise: ein vorhandener Projektschluessel
    gewinnt IMMER (auch wenn sein Wert null ist - bewusst noch nicht gesetzt). Schluessel, die nur das
    Template mitbringt (neuer Platzhalter seit dem letzten Update), werden mit Wert null ergaenzt, damit sie
    ueberhaupt in der Konfiguration auftauchen und im naechsten Schritt ersetzt/gemeldet werden koennen -
    ohne einen vorhandenen Projektwert zu ueberschreiben.

    Rueckgabe: (merged_dict oder None, wenn beide Seiten leer/fehlend sind; sortierte Liste der neu
    ergaenzten Schluessel)."""
    ours_values = ours_values if isinstance(ours_values, dict) else {}
    theirs_values = theirs_values if isinstance(theirs_values, dict) else {}
    if not ours_values and not theirs_values:
        return None, []
    merged = dict(ours_values)
    neu = sorted(key for key in theirs_values if key not in merged)
    for key in neu:
        merged[key] = None
    return merged, neu


def _merge_template_json_fields(ours, theirs):
    """Feldweiser Merge von .claude/template.json bei einem Merge-Konflikt (siehe Kopfkommentar).

    ours/theirs: geparste Dicts (siehe _git_show_json) oder None, wenn diese Stufe fehlt. Rueckgabe
    (merged_dict, hinweistext) oder (None, fehlertext), wenn keine Seite verwertbar ist."""
    if ours is None and theirs is None:
        return None, "keine Seite lesbar"

    merged = {}
    for key in _TEMPLATE_JSON_OURS_FIELDS:
        if ours is not None and key in ours:
            merged[key] = ours[key]
        # kein "elif theirs...": siehe Begruendung an der Konstante - fehlt das Feld im Projekt, bleibt es
        # auch nach dem Merge weg statt aus dem Template nachgeladen zu werden.

    values_merged, neu_values = _merge_template_json_values(
        (ours or {}).get("values"), (theirs or {}).get("values")
    )
    if values_merged is not None:
        merged["values"] = values_merged

    keep_local_ours = (ours or {}).get("keep_local") or []
    keep_local_theirs = (theirs or {}).get("keep_local") or []
    no_replace_ours = (ours or {}).get("no_replace") or []
    no_replace_theirs = (theirs or {}).get("no_replace") or []
    template_only_ours = (ours or {}).get("template_only") or []
    template_only_theirs = (theirs or {}).get("template_only") or []
    # Vereinigung, Reihenfolge: erst die Projekt-Eintraege in ihrer Reihenfolge, dann die neuen aus dem
    # Template, Duplikate raus. dict.fromkeys() haelt genau diese Reihenfolge und entfernt Duplikate.
    merged["keep_local"] = list(dict.fromkeys(list(keep_local_ours) + list(keep_local_theirs)))
    merged["no_replace"] = list(dict.fromkeys(list(no_replace_ours) + list(no_replace_theirs)))
    merged["template_only"] = list(dict.fromkeys(list(template_only_ours) + list(template_only_theirs)))
    neu_keep_local = [p for p in keep_local_theirs if p not in keep_local_ours]
    neu_no_replace = [p for p in no_replace_theirs if p not in no_replace_ours]
    neu_template_only = [p for p in template_only_theirs if p not in template_only_ours]

    # Unbekannte Felder: Projektfassung gewinnt, nur-im-Template-vorhandene Felder werden uebernommen.
    # "values" steht bewusst mit dabei, obwohl es nicht mehr in _TEMPLATE_JSON_OURS_FIELDS steht - es ist
    # oben bereits schluesselweise gemergt (_merge_template_json_values); ohne diesen Eintrag wuerde die
    # Schleife es hier als "unbekanntes Feld" nochmal aus ours ueberschreiben und die frisch ergaenzten
    # Template-Schluessel wieder verwerfen.
    known = set(_TEMPLATE_JSON_OURS_FIELDS) | {"keep_local", "no_replace", "template_only", "values"}
    for key, value in (ours or {}).items():
        if key not in known:
            merged[key] = value
    for key, value in (theirs or {}).items():
        if key not in known and key not in merged:
            merged[key] = value

    hinweis = (
        f"template.json feldweise zusammengefuehrt: keep_local +{len(neu_keep_local)}, "
        f"no_replace +{len(neu_no_replace)}, template_only +{len(neu_template_only)}"
    )
    if neu_values:
        hinweis += f", values +{len(neu_values)} neu ({', '.join(neu_values)}) - Werte pruefen/setzen"
    return merged, hinweis


def _resolve_template_json_merge(root: Path, cfg: dict, ours_ref: str, theirs_ref: str, rel_path: str):
    """Fuehrt .claude/template.json feldweise zusammen (siehe _merge_template_json_fields) - UNABHAENGIG
    davon, ob git den Pfad als Konflikt markiert hat: reine Listenergaenzungen an unterschiedlichen Stellen
    (Projekt ergaenzt keep_local, Template ergaenzt no_replace) mergt git oft klaglos automatisch, und der
    abschliessende save_template_json(cfg) in _finalize wuerde eine so automatisch gemergte Fassung sonst
    unbemerkt wieder verwerfen, weil cfg noch den Vor-Merge-Stand des Projekts traegt (siehe
    .templatedev/docs/ai/backlog.md Punkt 1 - genau dieser Fall blieb bisher unbemerkt liegen). ours_ref/theirs_ref:
    Commit vor dem Merge (Projekt) bzw. die Vergleichs-Ref des Templates.

    Schreibt bei Erfolg das Ergebnis in cfg (in place) UND auf die Platte, git add - das loest nebenbei auch
    einen echten Git-Konflikt auf diesem Pfad auf. Rueckgabe: Hinweistext fuer den Report, oder None, wenn
    der Pfad auf keiner Seite existiert (nichts zu tun)."""
    ours_data, ours_err = _git_show_json(root, ours_ref, rel_path)
    theirs_data, theirs_err = _git_show_json(root, theirs_ref, rel_path)

    if ours_data is None and theirs_data is None and not ours_err and not theirs_err:
        return None  # Pfad existiert auf keiner Seite - nichts zu tun

    if not ours_err and not theirs_err:
        merged, note = _merge_template_json_fields(ours_data, theirs_data)
        if merged is not None:
            cfg.clear()
            cfg.update(merged)
            save_template_json(root, cfg, root / rel_path)
            run_git(root, ["add", "--", rel_path])
            return note

    # Fallback: Parsen einer Seite fehlgeschlagen -> altes Verhalten (Projektfassung gewinnt komplett, bzw.
    # die einzige lesbare Seite, wenn die Projektfassung selbst kaputt ist).
    fallback_data = ours_data if ours_data is not None else theirs_data
    if fallback_data is not None:
        cfg.clear()
        cfg.update(fallback_data)
        save_template_json(root, cfg, root / rel_path)
        run_git(root, ["add", "--", rel_path])
    grund = "Parsen einer Seite fehlgeschlagen" if (ours_err or theirs_err) else "kein Feld-Merge moeglich"
    return f"immer Projektfassung ({grund})"


def cmd_apply(root: Path, cfg: dict, path: Path, do_commit: bool, continuing: bool) -> int:
    remote = cfg.get("template_remote") or "template"
    branch = cfg.get("template_branch") or "main"

    if not continuing:
        ref, fetch_noetig = compare_ref(root, cfg)
        if cfg.get("base_commit") is None or ref is None:
            print(f"Fehler: nicht konfiguriert (Remote '{remote}' bzw. Branch '{branch}'/base_commit fehlt) "
                  "- zuerst '--init' ausfuehren.", file=sys.stderr)
            return 2

        res_status = run_git(root, ["status", "--porcelain"])
        if res_status.stdout.strip():
            print("Fehler: Arbeitsbaum nicht sauber - erst committen/stashen, dann erneut versuchen.", file=sys.stderr)
            return 2

        if fetch_noetig:
            res_fetch = run_git(root, ["fetch", remote])
            if res_fetch.returncode != 0:
                print(f"Fehler: 'git fetch {remote}' fehlgeschlagen: {res_fetch.stderr.strip()}", file=sys.stderr)
                return 2

        base = cfg.get("base_commit")
        if base:
            res_pending = run_git(root, ["rev-list", "--count", f"{base}..{ref}"])
            if res_pending.returncode == 0:
                try:
                    pending = int(res_pending.stdout.strip() or "0")
                except ValueError:
                    pending = None
                if pending == 0:
                    print(f"Template-Update: aktuell (kein Unterschied zu {ref}) - nichts zu tun.")
                    return 0

        pre_merge_head = run_git(root, ["rev-parse", "HEAD"]).stdout.strip()
        res_merge = run_git(root, ["merge", "--no-ff", "--no-commit", ref])

        # Vor dem Aufloesen von TEMPLATE_JSON_REL feststellen, ob es UEBERHAUPT unaufgeloeste Pfade gab -
        # sonst wuerde "danach keine Konflikte mehr offen" (z.B. weil TEMPLATE_JSON_REL der einzige war und
        # gleich aufgeloest wird) faelschlich als "Merge aus anderem Grund fehlgeschlagen" gewertet.
        merge_failed_hard = res_merge.returncode != 0 and not get_unmerged_status(root)

        # Harten Merge-Fehler (nicht: offene Konflikte) SOFORT melden und abbrechen - VOR jedem Schreibzugriff
        # auf .claude/template.json. _resolve_template_json_merge() schreibt die Datei auf die Platte und
        # macht ein 'git add'; das darf bei einem Abbruch nicht passieren, sonst bleibt ein schmutziger
        # Arbeitsbaum zurueck (M .claude/template.json), der den dokumentierten Wiederholungsweg blockiert
        # (cmd_apply verlangt oben einen sauberen Arbeitsbaum) - war der Review-Fund.
        if merge_failed_hard:
            print(f"Fehler: 'git merge {ref}' fehlgeschlagen: {res_merge.stderr.strip()}", file=sys.stderr)
            return 2

        # .claude/template.json IMMER feldweise mergen - unabhaengig davon, ob git sie hier als Konflikt
        # markiert hat (siehe _resolve_template_json_merge). base_commit/updates werden ohnehin gleich
        # danach im Abschlussschritt aus dem hier gemergten cfg neu geschrieben. Das erledigt nebenbei auch
        # einen echten Git-Konflikt auf dem Pfad (git add loest ihn auf) - unten also aus den weiter zu
        # bearbeitenden Konflikten herausnehmen.
        template_json_note = _resolve_template_json_merge(root, cfg, pre_merge_head, ref, TEMPLATE_JSON_REL)
        if template_json_note:
            print(f"{TEMPLATE_JSON_REL}: {template_json_note}")

        if res_merge.returncode != 0:
            # get_unmerged_status() erst JETZT (nach _resolve_template_json_merge) neu abfragen: dessen
            # 'git add' hat einen echten Konflikt auf TEMPLATE_JSON_REL bereits aufgeloest (z.B. war es der
            # einzige Konflikt ueberhaupt - "both added" beim Bootstrap) - der Pfad taucht hier also nur
            # noch auf, falls er NICHT ueber diesen Mechanismus geloest werden konnte.
            conflicts = get_unmerged_status(root)

            keep_local = cfg.get("keep_local") or []
            template_only = cfg.get("template_only") or []
            abgewaehlt = abgewaehlte_pfade(cfg)
            is_template = bool(cfg.get("is_template"))
            merge_head = _merge_head(root)
            # B38: root/ref (=merge_head) durchreichen - finish-setup.py existiert in einem abgeschlossenen
            # Projekt lokal nicht mehr, siehe setup_removed_paths()/_load_sibling_module() oben.
            setup_removed = setup_removed_paths(cfg, root=root, ref=merge_head)
            rename_map = _find_renames(root, cfg.get("base_commit"), "HEAD")
            auto_resolved, deleted_kept, dd_removed, du_decision, template_only_removed = [], [], [], [], []
            abgewaehlt_removed = []
            setup_removed_removed, setup_only_resolved, setup_only_remaining = [], [], []
            forwarder_template_wins, forwarder_template_wins_changed = [], []
            for rel_path, code in conflicts.items():
                if code == "DD":
                    # von beiden geloescht - unstrittig, unabhaengig von keep_local: nichts zu bewahren.
                    res_rm = run_git(root, ["rm", "--", rel_path])
                    if res_rm.returncode != 0:
                        run_git(root, ["rm", "--cached", "--", rel_path])
                    dd_removed.append(rel_path)
                elif not is_template and matches_keep_local(rel_path, FORWARDER_TEMPLATE_WINS_PATHS):
                    # F4: reine Weiterleitung, Template gewinnt IMMER - unabhaengig vom Konflikt-Code. Inhalt
                    # direkt aus dem Template-Ref schreiben (statt 'checkout --theirs', das bei DU/AU/UA nicht
                    # zuverlaessig eine Stage-3-Fassung hat) und 'git add'.
                    res_show = run_git(root, ["show", f"{merge_head}:{rel_path}"]) if merge_head else None
                    if res_show is not None and res_show.returncode == 0:
                        fp = root / rel_path
                        fp.parent.mkdir(parents=True, exist_ok=True)
                        fp.write_text(res_show.stdout, encoding="utf-8", newline="")
                        run_git(root, ["add", "--", rel_path])
                        forwarder_template_wins.append(rel_path)
                        # Review-Befund: das Template gewinnt hier IMMER, auch wenn die Projektfassung (HEAD
                        # vor diesem Merge) gegenueber der gemeinsamen Basis lokal veraendert war - diese
                        # Aenderung geht dabei kommentarlos verloren. Deshalb pruefen und, falls ja, im Report
                        # sichtbar machen samt Rueckweg zur alten Fassung.
                        base_commit = cfg.get("base_commit")
                        ours_res = run_git(root, ["show", f"{pre_merge_head}:{rel_path}"])
                        base_res = run_git(root, ["show", f"{base_commit}:{rel_path}"]) if base_commit else None
                        if ours_res.returncode == 0 and (
                            base_res is None or base_res.returncode != 0 or base_res.stdout != ours_res.stdout
                        ):
                            forwarder_template_wins_changed.append(rel_path)
                    # sonst: im Template-Ref nicht (mehr) vorhanden - Konflikt bleibt offen, von Hand loesen
                elif code == "DU" and not is_template and matches_keep_local(rel_path, template_only):
                    # Projekt hat den Pfad nie (mehr), Template hat ihn geaendert - genau der Fall, fuer den
                    # template_only existiert (z.B. .templatedev/: create-project.py entfernt den Ordner
                    # beim Anlegen, seitdem "geloescht" aus Sicht des 3-Way-Merges). Keine Rename-Pruefung noetig -
                    # dieser Pfad ist bewusst und dauerhaft ausgeschlossen, keine zu bewahrende Migration.
                    res_rm = run_git(root, ["rm", "--", rel_path])
                    if res_rm.returncode != 0:
                        run_git(root, ["rm", "--cached", "--", rel_path])
                    template_only_removed.append(rel_path)
                elif code == "DU" and not is_template and matches_keep_local(rel_path, abgewaehlt):
                    # Projekt hat den Schalter in AI-CONFIG.md auf "aus" gestellt, das Template hat die Datei
                    # geaendert. Auch das ist keine Entscheidung fuer {{AUFTRAGGEBER}}: Er hat sie schon
                    # getroffen, sonst stuende der Schalter nicht auf "aus". Keine Rename-Pruefung noetig -
                    # abgewaehlte Pfade werden entfernt, nicht verschoben.
                    res_rm = run_git(root, ["rm", "--", rel_path])
                    if res_rm.returncode != 0:
                        run_git(root, ["rm", "--cached", "--", rel_path])
                    abgewaehlt_removed.append(rel_path)
                elif code == "DU" and not is_template and matches_keep_local(rel_path, setup_removed):
                    # B38: /act-finalize (finish-setup.py) hat den Pfad aus diesem ABGESCHLOSSENEN Projekt
                    # entfernt (z.B. create-project.py, ein Einrichtungs-Skill-Ordner) - das Template pflegt
                    # ihn fuer andere, noch nicht abgeschlossene Projekte weiter. {{AUFTRAGGEBER}} hat diese
                    # Entscheidung mit dem Abschluss der Einrichtung bereits getroffen, keine Rename-Pruefung
                    # noetig.
                    res_rm = run_git(root, ["rm", "--", rel_path])
                    if res_rm.returncode != 0:
                        run_git(root, ["rm", "--cached", "--", rel_path])
                    setup_removed_removed.append(rel_path)
                elif not is_template and cfg.get("setup_complete") and rel_path.replace("\\", "/") in SETUP_ONLY_TEXT_STRIP_PATHS:
                    # B38: nur ein AUSSCHNITT dieser Datei ist Setup-only (template-only-Block bzw.
                    # Checklisten-Abschnitt) - kein Ganzdatei-Fall wie oben. Erst den Ausschnitt aus der
                    # Template-Seite verwerfen, dann versuchen, den Rest konfliktfrei zu mergen.
                    note = _resolve_setup_only_text_conflict(root, rel_path, cfg.get("base_commit"), pre_merge_head, merge_head)
                    if note:
                        setup_only_resolved.append(f"{rel_path} ({note})")
                    else:
                        setup_only_remaining.append(rel_path)
                elif code == "DU":
                    # Vom Projekt geloescht, vom Template geaendert. Das Script darf das NICHT allein
                    # entscheiden, wenn die "Loeschung" in Wahrheit nur eine Umbenennung/Verschiebung ist
                    # (typisch: docs/ai/ auf eigene Dateinamen migriert) - sonst geht die Template-Aenderung
                    # unbemerkt verloren. Automatisch "geloescht belassen" nur, wenn der Pfad in keep_local
                    # steht (das Projekt hat bewusst entschieden) UND keine Umbenennung erkennbar ist.
                    kandidat = _rename_candidate(root, rel_path, rename_map, merge_head)
                    if kandidat is None and matches_keep_local(rel_path, keep_local):
                        res_rm = run_git(root, ["rm", "--", rel_path])
                        if res_rm.returncode != 0:
                            run_git(root, ["rm", "--cached", "--", rel_path])
                        deleted_kept.append(rel_path)
                    else:
                        du_decision.append(rel_path)
                elif matches_keep_local(rel_path, keep_local):
                    res_co = run_git(root, ["checkout", "--ours", "--", rel_path])
                    if res_co.returncode == 0:
                        run_git(root, ["add", "--", rel_path])
                        auto_resolved.append(rel_path)
                    # sonst: keine "ours"-Fassung vorhanden -> Konflikt bleibt offen, von Hand loesen

            if forwarder_template_wins:
                print("Weiterleitungs-Skill (F4), Template gewinnt immer: " + ", ".join(sorted(forwarder_template_wins)))
            if forwarder_template_wins_changed:
                print(
                    "WARNUNG: davon lokal veraendert (gegenueber der Basis), trotzdem ueberschrieben - alte "
                    "Fassung: 'git show HEAD:<Pfad>' (nach dem Commit stattdessen 'git show ORIG_HEAD:<Pfad>'): "
                    + ", ".join(sorted(forwarder_template_wins_changed))
                )
            if auto_resolved:
                print("keep_local automatisch uebernommen (Projektfassung gewinnt): " + ", ".join(sorted(auto_resolved)))
            if template_only_removed:
                print("Nur im Template, wird nicht eingespielt: " + ", ".join(sorted(template_only_removed)))
            if abgewaehlt_removed:
                print("Abgewaehlt (AI-CONFIG.md), bleibt draussen: " + ", ".join(sorted(abgewaehlt_removed)))
            if setup_removed_removed:
                print("Setup abgeschlossen (/act-finalize entfernt), bleibt draussen: " + ", ".join(sorted(setup_removed_removed)))
            if setup_only_resolved:
                print("Setup abgeschlossen: Setup-Abschnitt der Template-Seite verworfen, automatisch gemergt: " + ", ".join(sorted(setup_only_resolved)))
            if setup_only_remaining:
                print("Setup abgeschlossen: Setup-Abschnitt verworfen, Restkonflikt noch offen: " + ", ".join(sorted(setup_only_remaining)))
            if dd_removed:
                print("Von beiden geloescht (unstrittig) -> entfernt: " + ", ".join(sorted(dd_removed)))
            if deleted_kept:
                print("Vom Projekt geloescht (keep_local, bewusst), im Template geaendert -> geloescht belassen: " + ", ".join(sorted(deleted_kept)))
            if du_decision:
                print("Vom Projekt geloescht, im Template geaendert (Entscheidung noetig): " + ", ".join(sorted(du_decision)))

            still_open = _remaining_conflicts(root)
            if still_open:
                _print_unresolved(root, still_open, "Fehler: ungeloeste Konflikte - bitte manuell aufloesen und danach '--continue' ausfuehren:")
                return 4
    else:
        res_head = run_git(root, ["rev-parse", "-q", "--verify", "MERGE_HEAD"])
        if res_head.returncode != 0:
            print("Fehler: kein laufender Merge gefunden (MERGE_HEAD fehlt).", file=sys.stderr)
            return 2
        still_open = _remaining_conflicts(root)
        if still_open:
            _print_unresolved(root, still_open, "Fehler: noch ungeloeste Konflikte:")
            return 4

    return _finalize(root, cfg, path, do_commit)


def _remove_template_only(root: Path, cfg: dict) -> list:
    """Entfernt Pfade aus `template_only` (siehe DEFAULT_TEMPLATE_ONLY), falls der Merge sie ins Projekt
    gebracht hat - IM TEMPLATE-CHECKOUT SELBST (Marker "is_template") niemals, dort sind es normale, vom
    Template selbst gepflegte Dateien. 'git rm -r -f --ignore-unmatch' entfernt Index UND Arbeitsbaum in
    einem Schritt und meldet keinen Fehler, wenn der Pfad gar nicht existiert; ein danach trotzdem noch
    vorhandener Pfad (z.B. von git nicht erfasste Dateien) wird direkt vom Dateisystem geloescht, damit keine
    Karteileiche zurueckbleibt. Laeuft VOR dem Staging der Platzhalter-Ersetzung in _finalize(), damit ein
    anschliessender Merge-Commit diese Pfade schon nicht mehr enthaelt. Rueckgabe: sortierte Liste der
    tatsaechlich entfernten Pfade (leer = nichts zu tun)."""
    if cfg.get("is_template"):
        return []
    template_only = cfg.get("template_only") if isinstance(cfg.get("template_only"), list) else list(DEFAULT_TEMPLATE_ONLY)
    return _remove_paths(root, template_only)


def _remove_paths(root: Path, pfade) -> list:
    """Gemeinsame Mechanik fuer _remove_template_only() und das Aufraeumen abgewaehlter Pfade: 'git rm -r -f
    --ignore-unmatch' raeumt Index UND Arbeitsbaum in einem Schritt und meldet keinen Fehler, wenn der Pfad
    gar nicht existiert; was danach noch daliegt (von git nicht erfasste Dateien), wird direkt vom
    Dateisystem geloescht, damit keine Karteileiche zurueckbleibt."""
    removed = []
    wurzel = root.resolve()
    for rel_path in pfade:
        if not _safe_rel_path(rel_path):
            print(f"Uebersprungen (unsicherer Pfad, nicht geloescht): {rel_path!r}", file=sys.stderr)
            continue
        fp = root / rel_path
        try:
            fp.resolve().relative_to(wurzel)
        except ValueError:
            print(f"Uebersprungen (ausserhalb des Projekts, nicht geloescht): {rel_path!r}", file=sys.stderr)
            continue
        existed = fp.exists()
        run_git(root, ["rm", "-r", "-f", "--ignore-unmatch", "--", rel_path])
        if fp.exists():
            try:
                if fp.is_dir():
                    shutil.rmtree(fp, ignore_errors=True)
                else:
                    fp.unlink()
            except OSError:
                pass
        if existed:
            removed.append(rel_path)
    return sorted(removed)


def _finalize(root: Path, cfg: dict, path: Path, do_commit: bool) -> int:
    # MERGE_HEAD (falls ein Merge laeuft - _finalize() wird auch ohne einen laufenden Merge aufgerufen,
    # z.B. nie von cmd_apply direkt ohne vorheriges '--apply') schon hier aufloesen: setup_removed_paths()
    # braucht ihn als Fallback-Ref, falls finish-setup.py lokal fehlt (siehe dort). Wird weiter unten (B36)
    # fuer new_base_full wiederverwendet statt ein zweites Mal aufgeloest.
    merge_head = _merge_head(root)

    removed_template_only = _remove_template_only(root, cfg)
    if removed_template_only:
        print("Nur im Template, aus dem Projekt entfernt: " + ", ".join(removed_template_only))

    # Abgewaehlte Pfade: Der Merge kann dort auch DATEIEN NEU angelegt haben, die es im Projekt noch nie gab -
    # die erzeugen keinen Konflikt und kaemen sonst unbemerkt zurueck (Backlog 31).
    removed_abgewaehlt = _remove_paths(root, abgewaehlte_pfade(cfg))
    if removed_abgewaehlt:
        print("Abgewaehlt (AI-CONFIG.md), aus dem Projekt entfernt: " + ", ".join(removed_abgewaehlt))

    # B38: dasselbe fuer abgeschlossene Projekte - Pfade, die /act-finalize entfernt hat, koennen ohne
    # Konflikt neu vom Merge hereinkommen (Datei existierte im Projekt schon lange nicht mehr).
    removed_setup = _remove_paths(root, setup_removed_paths(cfg, root=root, ref=merge_head))
    if removed_setup:
        print("Setup abgeschlossen (/act-finalize entfernt), aus dem Projekt entfernt: " + ", ".join(removed_setup))

    res_cached = run_git(root, ["diff", "--cached", "--name-only"])
    res_unstaged = run_git(root, ["diff", "--name-only"])
    touched = set()
    if res_cached.returncode == 0:
        touched.update(p for p in res_cached.stdout.splitlines() if p.strip())
    if res_unstaged.returncode == 0:
        touched.update(p for p in res_unstaged.stdout.splitlines() if p.strip())

    keep_local = cfg.get("keep_local") or []
    no_replace = cfg.get("no_replace") if isinstance(cfg.get("no_replace"), list) else list(DEFAULT_NO_REPLACE)
    values = cfg.get("values") or {}
    remaining_placeholders = []

    for rel_path in sorted(touched):
        if rel_path == TEMPLATE_JSON_REL:
            continue
        if matches_keep_local(rel_path, keep_local):
            continue
        fp = root / rel_path
        if not fp.exists() or not fp.is_file():
            continue
        try:
            raw = fp.read_bytes()
        except OSError:
            continue
        try:
            # Byteweise lesen/decodieren statt read_text(): read_text() macht per Default eine
            # Zeilenende-Uebersetzung (universal newlines, \r\n -> \n) - eine bewusst mit CRLF gepflegte
            # Datei wuerde dann beim Zurueckschreiben still auf LF umgestellt. decode() fasst \r\n als
            # gewoehnliche Zeichen im String an, die Ersetzung unten laesst sie unangetastet.
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue  # keine Textdatei (oder nicht lesbar) -> unangetastet lassen

        if matches_keep_local(rel_path, no_replace):
            # dokumentiert den Platzhalter selbst -> nie ersetzen, aber melden
            if "{{" in content:
                remaining_placeholders.append(rel_path + " (no_replace, Beispiele - so gewollt)")
            continue

        new_content = content
        for key, val in values.items():
            if val is None:
                continue
            new_content = new_content.replace("{{" + key + "}}", str(val))

        if new_content != content:
            try:
                fp.write_bytes(new_content.encode("utf-8"))
            except OSError:
                continue
            run_git(root, ["add", "--", rel_path])

        if "{{" in new_content:
            remaining_placeholders.append(rel_path)

    # B36: der tatsaechlich gemergte Commit ist MERGE_HEAD - NICHT der zwischenzeitlich frisch gefetchte
    # Remote-Stand aus compare_ref(). Zwischen '--apply' (legt den Merge an) und '--continue' (loest ihn ab)
    # kann ein erneutes 'git fetch template' (z.B. durch den --check-SessionStart-Hook) den Remote-Branch
    # bereits weitergeschoben haben - compare_ref() wuerde dann auf einen Commit zeigen, dessen Aenderungen
    # NIE tatsaechlich in den Arbeitsbaum gemergt wurden, und base_commit faelschlich darauf vorspringen.
    # MERGE_HEAD existiert hier zuverlaessig (ein Merge wurde angelegt, git loescht ihn erst bei 'git commit'
    # weiter unten) - nur ohne laufenden Merge (z.B. Aufruf ohne vorherige Konflikte) auf compare_ref()
    # zurueckfallen. 'merge_head' wurde schon ganz oben aufgeloest (siehe dort) - hier nicht erneut abfragen,
    # ein 'git commit' weiter unten wuerde MERGE_HEAD sonst zwischen den beiden Aufrufen verschwinden lassen.
    if merge_head:
        new_base_full = merge_head
    else:
        ref, _fetch_noetig = compare_ref(root, cfg)
        if ref is None:
            ref = f"{cfg.get('template_remote') or 'template'}/{cfg.get('template_branch') or 'main'}"
        res_new = run_git(root, ["rev-parse", ref])
        if res_new.returncode != 0:
            print(f"Fehler: '{ref}' nicht aufloesbar: {res_new.stderr.strip()}", file=sys.stderr)
            return 2
        new_base_full = res_new.stdout.strip()

    old_base = cfg.get("base_commit")
    commits_count = 0
    if old_base:
        res_cnt = run_git(root, ["rev-list", "--count", f"{old_base}..{new_base_full}"])
        if res_cnt.returncode == 0:
            try:
                commits_count = int(res_cnt.stdout.strip() or "0")
            except ValueError:
                commits_count = 0

    old_short = _short(root, old_base) if old_base else "?"
    new_short = _short(root, new_base_full)

    cfg["base_commit"] = new_base_full
    cfg.setdefault("updates", []).append(
        {
            "date": time.strftime("%Y-%m-%d"),
            "from": old_short,
            "to": new_short,
            "commits": commits_count,
        }
    )
    save_template_json(root, cfg, path)
    run_git(root, ["add", "--", TEMPLATE_JSON_REL])

    # B37: erst jetzt, wo garantiert keine Konflikte mehr offen sind (cmd_apply ruft _finalize() nur dann
    # auf) - AI-CONFIG.md steht in keep_local, ein Merge zieht neue Template-Schluessel dort sonst nie mit.
    # ref=new_base_full: derselbe, gerade erst aufgeloeste Merge-/Vergleichs-Commit - fetch=False in
    # apply_ai_config_missing_keys() erspart einen zweiten 'git fetch' (Review-Befund "zweiter Fetch").
    for line in apply_ai_config_missing_keys(root, cfg, ref=new_base_full):
        print(line)

    if remaining_placeholders:
        print("Warnung: '{{' bleibt uebrig (kein Wert in values gesetzt) - manuell pruefen:")
        for rel_path in remaining_placeholders:
            print(f"  - {rel_path}")

    if do_commit:
        res_status = run_git(root, ["status", "--porcelain"])
        if not res_status.stdout.strip():
            print("Keine Aenderungen - nichts zu committen.")
            return 0
        msg = f"chore(template): Update auf {new_short} ({commits_count} Commits)"
        res_commit = run_git(root, ["commit", "-m", msg])
        if res_commit.returncode != 0:
            print(f"Fehler: Commit fehlgeschlagen: {res_commit.stderr.strip()}", file=sys.stderr)
            return 2
        print(f"Commit erstellt: {msg}")
    else:
        print("Aenderungen sind gestaged - pruefen, dann committen.")

    return 0


# ---------------------------------------------------------------------------
# --conflicts
# ---------------------------------------------------------------------------


def cmd_conflicts(root: Path, cfg: dict) -> int:
    res_git = run_git(root, ["rev-parse", "--is-inside-work-tree"])
    if res_git.returncode != 0 or res_git.stdout.strip() != "true":
        print("Fehler: kein Git-Repo.", file=sys.stderr)
        return 2

    merge_head = _merge_head(root)
    if not merge_head:
        print("Kein laufender Merge (MERGE_HEAD fehlt) - '--conflicts' zeigt nur waehrend eines laufenden "
              "'--apply' etwas an; siehe 'git status'.")
        return 0

    paths, status_map = _list_conflicts(root)
    if not paths:
        print("Keine offenen Konflikte.")
        return 0

    base = cfg.get("base_commit")
    rename_map = _find_renames(root, base, "HEAD")
    rename_map_theirs = _find_renames(root, base, merge_head)

    lines = []
    for rel_path in paths:
        code = status_map.get(rel_path, "?")
        lines.append(rel_path)
        lines.append(f"  art:        {_conflict_art(code)}")
        lines.append(f"  regel:      {priority_label(rel_path)}")

        t_n = _numstat_lines(root, base, merge_head, rel_path)
        p_n = _numstat_lines(root, base, "HEAD", rel_path)
        lines.append(f"  template:   {t_n if t_n is not None else '?'} Zeilen geaendert (base..ref)")
        lines.append(f"  projekt:    {p_n if p_n is not None else '?'} Zeilen geaendert (base..HEAD)")

        if code == "DU":
            kandidat = _rename_candidate(root, rel_path, rename_map, merge_head)
            if kandidat:
                neu, pct = kandidat
                pct_txt = f"{pct}%" if pct is not None else "?"
                lines.append(f"  umbenannt?: {neu} (Aehnlichkeit {pct_txt})")
        elif code in ("AU", "UA"):
            # Beide Seiten haben dieselbe Basisdatei verschoben (rename/rename-Konflikt) - rel_path selbst
            # ist bereits der eine Zielpfad, gesucht wird der jeweils andere.
            paar = _rename_pair_both_sides(rel_path, code, rename_map, rename_map_theirs)
            if paar:
                projekt_pfad, template_pfad = paar
                lines.append(f"  umbenannt?: Projekt -> {projekt_pfad} | Template -> {template_pfad}")

        base_txt = base or "<base_commit fehlt>"
        q = _sh_quote(rel_path)
        befehle = [f"git show {merge_head}:{q}"]
        # Bei "DU" gibt es die Datei in HEAD nicht mehr - der Befehl wuerde nur einen git-Fehler liefern.
        if code != "DU":
            befehle.append(f"git show HEAD:{q}")
        befehle.append(f"git diff {base_txt} {merge_head} -- {q}")
        lines.append("  befehle:    " + "  |  ".join(befehle))
        lines.append("")

    lines.append("Weiter: Datei inhaltlich zusammenfuehren (Prioritaetsregel beachten), je geloestem Pfad")
    lines.append("'git add <pfad>', danach 'update-template.py --continue [--commit]'.")
    lines.append("Bei 'umbenannt?': die Template-Aenderung gehoert in die NEUE Datei - die alte bleibt")
    lines.append("geloescht (kein 'git add' auf den alten Pfad).")
    lines.append("Bei beidseitiger Umbenennung (Projekt und Template -> unterschiedliche neue Pfade) wird in")
    lines.append("den PROJEKT-Pfad zusammengefuehrt; der Template-Pfad wird entfernt (kein 'git add' darauf).")
    print("\n".join(lines).rstrip())
    return 0


# ---------------------------------------------------------------------------
# --graft
# ---------------------------------------------------------------------------


def _has_common_ancestor(root: Path, base_commit: str) -> bool:
    res = run_git(root, ["merge-base", "HEAD", base_commit])
    return res.returncode == 0 and bool(res.stdout.strip())


def cmd_graft(root: Path, cfg: dict) -> int:
    base_commit = cfg.get("base_commit")
    if not base_commit:
        print("Fehler: kein base_commit in .claude/template.json - zuerst apply-template.py bzw. --init ausfuehren.", file=sys.stderr)
        return 2

    res_status = run_git(root, ["status", "--porcelain"])
    if res_status.stdout.strip():
        print("Fehler: Arbeitsbaum nicht sauber - erst committen/stashen, dann erneut versuchen.", file=sys.stderr)
        return 2

    res_verify = run_git(root, ["cat-file", "-e", base_commit])
    if res_verify.returncode != 0:
        print(
            f"Fehler: base_commit {base_commit} ist lokal nicht bekannt - erst 'git fetch "
            f"{cfg.get('template_remote') or 'template'}' ausfuehren.",
            file=sys.stderr,
        )
        return 2

    if _has_common_ancestor(root, base_commit):
        print(f"Bereits verknuepft: gemeinsamer Vorfahr mit {_short(root, base_commit)} existiert schon - nichts zu tun.")
        return 0

    base_short = _short(root, base_commit)
    msg = f"chore(template): Herkunft mit Template verknuepft (Basis {base_short})"
    res_merge = run_git(root, ["merge", "-s", "ours", "--allow-unrelated-histories", "--no-edit", "-m", msg, base_commit])
    if res_merge.returncode != 0:
        print(f"Fehler: 'git merge -s ours {base_commit}' fehlgeschlagen: {res_merge.stderr.strip()}", file=sys.stderr)
        return 2

    print(f"Verknuepft: Merge-Commit erstellt ({msg}). Arbeitsbaum unveraendert, --check/--apply funktionieren jetzt normal.")
    return 0


# ---------------------------------------------------------------------------
# --abort / --status
# ---------------------------------------------------------------------------


def cmd_abort(root: Path) -> int:
    res_head = run_git(root, ["rev-parse", "-q", "--verify", "MERGE_HEAD"])
    if res_head.returncode != 0:
        print("Kein laufender Merge gefunden - nichts zu tun.")
        return 0
    res_abort = run_git(root, ["merge", "--abort"])
    if res_abort.returncode != 0:
        print(f"Fehler: 'git merge --abort' fehlgeschlagen: {res_abort.stderr.strip()}", file=sys.stderr)
        return 2
    print("Merge abgebrochen (git merge --abort). .claude/template.json unveraendert.")
    return 0


def print_status(root: Path, cfg: dict) -> None:
    remote = cfg.get("template_remote") or "template"
    branch = cfg.get("template_branch") or "main"
    print(f"template_remote: {remote}")
    print(f"template_branch: {branch}")

    res_url = run_git(root, ["remote", "get-url", remote])
    url = res_url.stdout.strip() if res_url.returncode == 0 else (cfg.get("template_url") or "(kein Remote)")
    print(f"remote-url:      {url}")

    base = cfg.get("base_commit")
    print(f"base_commit:     {base or '(nicht gesetzt)'}")

    updates = cfg.get("updates") or []
    if updates:
        last = updates[-1]
        print(f"letztes update:  {last.get('date')} - {last.get('from')} -> {last.get('to')} ({last.get('commits')} Commits)")
    else:
        print("letztes update:  (noch keins)")

    ref_status, _f = compare_ref(root, cfg)
    if base and ref_status:
        ref = ref_status
        res_count = run_git(root, ["rev-list", "--count", f"{base}..{ref}"])
        if res_count.returncode == 0:
            print(f"ausstehend:      {res_count.stdout.strip()} Commits (lokaler Stand, ohne fetch)")
        else:
            print("ausstehend:      unbekannt (Ref nicht aufloesbar - noch nicht gefetcht?)")
    else:
        print("ausstehend:      unbekannt (nicht konfiguriert)")

    if base:
        res_cat = run_git(root, ["cat-file", "-e", base])
        if res_cat.returncode != 0:
            print("verknuepft:      unbekannt (base_commit lokal nicht bekannt - fetch fehlt)")
        elif _has_common_ancestor(root, base):
            print("verknuepft:      ja (gemeinsamer Vorfahr mit base_commit vorhanden)")
        else:
            print("verknuepft:      nein - '--graft' ausfuehren (nur fuer nachgeruestete Projekte noetig)")
    else:
        print("verknuepft:      -")

    values = cfg.get("values") or {}
    gesetzt = [k for k, v in values.items() if v is not None]
    print(f"values gesetzt:  {', '.join(gesetzt) if gesetzt else '(keine)'}")

    merge_head = _merge_head(root)
    if merge_head:
        offene, _status_map = _list_conflicts(root)
        von_template = _merge_is_from_template(root, cfg, merge_head)
        quelle = "vom Template-Update" if von_template else "unbekannter Herkunft"
        if offene:
            print(f"merge:           laeuft (MERGE_HEAD {merge_head[:7]}, {quelle}), {len(offene)} "
                  "Konflikt(e) offen - siehe '--conflicts'")
        else:
            # B36: git hat den Merge bereits vollstaendig aufgeloest (keine offenen Konflikte mehr), aber
            # niemand hat committet - ohne diese Warnung faellt das leicht durch, weil 'git status' allein es
            # nicht klar von einem gewoehnlichen "Aenderungen gestaged" unterscheidet.
            print(f"merge:           WARNUNG: fertig aufgeloest ({quelle}), aber NICHT committet "
                  f"(MERGE_HEAD {merge_head[:7]}) - 'git commit' bzw. '--continue --commit' ausfuehren, "
                  "oder '--abort' zum Verwerfen.")
    else:
        print("merge:           kein laufender Merge")


def cmd_status(root: Path, cfg: dict) -> int:
    print_status(root, cfg)
    return 0


# ---------------------------------------------------------------------------
# main / Argument-Parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="update-template.py",
        description="Template-Updates per Git-Merge einspielen, ohne echte Werte durch Platzhalter zu ersetzen.",
    )
    parser.add_argument("--init", action="store_true", help="Remote/Basis-Commit/Werte initialisieren")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=WERT", help="Platzhalterwert setzen")
    parser.add_argument("--check", action="store_true", help="Auf Template-Updates pruefen (mit fetch)")
    parser.add_argument("--apply", action="store_true", help="Template-Update per Merge einspielen")
    parser.add_argument("--continue", dest="cont", action="store_true", help="Nach manueller Konfliktaufloesung fortsetzen")
    parser.add_argument("--conflicts", action="store_true", help="Offene Konflikte eines laufenden Merges analysieren (schreibt nichts)")
    parser.add_argument("--abort", action="store_true", help="Laufenden Merge abbrechen")
    parser.add_argument("--status", action="store_true", help="Konfiguration/Stand anzeigen")
    parser.add_argument("--graft", action="store_true", help="Gemeinsame Historie mit base_commit herstellen (nachgeruestete Projekte)")
    parser.add_argument("--quiet", action="store_true", help="Nur bei --check: keine Ausgabe, wenn aktuell/nicht konfiguriert")
    parser.add_argument("--commit", action="store_true", help="Nur bei --apply/--continue: Merge-Commit direkt erstellen")
    parser.add_argument("--url", default=None, help="Nur bei --init: Remote-URL des Templates")
    parser.add_argument("--base", default=None, help="Nur bei --init: Basis-Commit explizit vorgeben")
    return parser


def _run(argv) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    root = _find_root()

    # T5: die Pflege-Sitzung des Templates in .templatedev/ hat kein eigenes Template, gegen das gemergt
    # werden koennte - "Update" heisst dort stattdessen "Root-Arbeitsstand neu rendern" (sync-rules.py,
    # siehe .templatedev/docs/project/concepts/project-structure.md). --check/--apply/--status leiten
    # deshalb dorthin weiter statt zu verweigern; alles andere (--graft, --continue, Remote-Operationen)
    # bleibt gesperrt - fuer einen echten Merge gibt es hier keinen Sinn.
    cl = _config_lib_module()
    if cl.is_template_maintenance_dir(root):
        sync_rules = root / "scripts" / "sync-rules.py"
        if args.check:
            sr_args = ["--check"] + (["--quiet"] if args.quiet else [])
        elif args.apply:
            sr_args = None  # --diff zuerst zeigen, danach --apply (siehe unten)
        elif args.status:
            sr_args = ["--check"]
        else:
            print(f"update-template.py: Fehler: {cl.TEMPLATE_MAINTENANCE_DIR_HINWEIS}", file=sys.stderr)
            return 2

        if not sync_rules.is_file():
            print(f"update-template.py: Fehler: {sync_rules} fehlt.", file=sys.stderr)
            return 2

        if args.apply:
            res_diff = subprocess.run([sys.executable, str(sync_rules), "--diff"])
            if res_diff.returncode != 0:
                return res_diff.returncode
            res_apply = subprocess.run([sys.executable, str(sync_rules), "--apply"])
            return res_apply.returncode

        res = subprocess.run([sys.executable, str(sync_rules)] + sr_args)
        return res.returncode

    cfg, path = load_template_json(root)

    if args.status:
        return cmd_status(root, cfg)
    if args.graft:
        return cmd_graft(root, cfg)
    if args.abort:
        return cmd_abort(root)
    if args.conflicts:
        return cmd_conflicts(root, cfg)
    if args.cont:
        return cmd_apply(root, cfg, path, args.commit, continuing=True)
    if args.apply:
        return cmd_apply(root, cfg, path, args.commit, continuing=False)
    if args.check:
        return cmd_check(root, cfg, args.quiet)
    if args.init:
        return cmd_init(root, cfg, path, args.url, args.base, args.set)
    if args.set:
        return cmd_set(root, cfg, path, args.set)

    parser.print_usage(sys.stderr)
    return 2


def main() -> int:
    try:
        return _run(sys.argv[1:])
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 - darf nie mit Traceback nach aussen dringen
        print(f"update-template: Fehler: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
