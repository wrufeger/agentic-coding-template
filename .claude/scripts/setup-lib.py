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
#        `.claude/skills/act-create-project/SKILL.md`, `docs/ai/checklists.md` § "Neues Projekt".
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
#       .claude/skills/act-create-project/SKILL.md und den beiden Scripten setup-lib.py/update-template.py -
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
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


# ---------------------------------------------------------------------------
# config-lib.py/files-lib.py/claudemd-lib.py laden (Aufteilung Backlog/.templatedev/questions.md Q4:
# setup-lib.py war 2461 Zeilen und blockierte parallele Auftraege, die die Datei gleichzeitig brauchten).
# Diese Datei bleibt die Fassade: jeder Name aus den drei Modulen (ausser Dunder-Attributen) landet per
# _merge_module() in diesen globalen Namensraum - sowohl fuer den Ablauf unten (bare Namen wie vor der
# Aufteilung) als auch fuer Aufrufer wie sync-config.py, die weiterhin `cp.<name>` (cp = dieses Modul per
# importlib) verwenden. Bindestriche im Dateinamen verbieten ein normales `import`, daher importlib.util wie
# in sync-config.py/rename-lib.py (_load_module). config-lib.py haengt von keinem der beiden anderen ab,
# files-lib.py nur von config-lib.py, claudemd-lib.py nur von files-lib.py - kein Ring.
# ---------------------------------------------------------------------------


def _load_sibling_module(filename: str, mod_name: str):
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _merge_module(mod) -> None:
    for _name, _value in vars(mod).items():
        if _name.startswith("__") and _name.endswith("__"):
            continue
        globals()[_name] = _value


_merge_module(_load_sibling_module("config-lib.py", "_setup_lib_config"))
_merge_module(_load_sibling_module("files-lib.py", "_setup_lib_files"))
_merge_module(_load_sibling_module("claudemd-lib.py", "_setup_lib_claudemd"))


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


def config_warnungen(cfg: dict) -> list:
    """Alles, was der Parser nicht eindeutig lesen konnte - darf nie still verschluckt werden."""
    lines = []
    for raw_key, raw_val, val in cfg.get("gekuerzt") or []:
        lines.append(f"{raw_key}: Klammer-Kommentar abgeschnitten, verwendet wird \"{val}\" (Zeile: {raw_val})")
    return lines


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


# Pfade, die nur das TEMPLATE selbst betreffen und in einem abgeleiteten Projekt nichts verloren haben:
# `.github/README.md` (Template-Beschreibung, wird von GitHub vor der Root-README angezeigt) und
# `.templatedev/` (Board/Backlog/Fragen/Ledger/Regeln der Template-Entwicklung - der einzige Ordner im
# Template mit echtem Inhalt statt Platzhaltern). Bare Ordnername ohne Trailing-Slash/Wildcard: greift bei
# Path.exists()/is_dir() (siehe remove_template_intro) direkt, und muss zu DEFAULT_TEMPLATE_ONLY in
# update-template.py passen (kein Import zwischen den Scripten, siehe dort).
TEMPLATE_ONLY_PATHS = [".github/README.md", ".templatedev", ".claude/skills/act-process-feedback"]

# Fest verdrahtete Pfadlisten, deren Eintraege nach einer Umbenennung/Verschiebung veraltet sein koennen
# (siehe check_stale_remove_paths) - ohne Gegenprobe faellt so etwas erst auf, wenn der jeweilige
# Entfernen-Schritt eine nicht mehr existierende Datei "erfolgreich" ignoriert.
STALE_PATH_CHECK_LISTS = {
    "OPTIMIZER_REMOVE_PATHS": OPTIMIZER_REMOVE_PATHS,
    "MAINTENANCE_REMOVE_PATHS": MAINTENANCE_REMOVE_PATHS,
    "TEMPLATE_ONLY_PATHS": TEMPLATE_ONLY_PATHS,
}

# Pfade, die ABSICHTLICH nie im Template-Repo selbst existieren: Altnamen von vor dem `act-`-Praefix
# (Umbenennung 2026-09-17), die in einer der Listen oben stehen bleiben, damit Projekte, die den
# Umbenennungs-Merge noch nicht eingespielt haben, ihre alten Skill-Ordner beim Abschalten trotzdem
# losgeworden (Backlog #B42, .templatedev/backlog.md). check_stale_remove_paths soll dafuer NICHT warnen -
# das waere hier immer ein Fehlalarm, keine vergessene Umbenennung. Bei einer echten Umbenennung/Verschiebung
# einer der Listen bleibt die Selbstpruefung fuer alle anderen Eintraege wirksam.
LEGACY_REMOVE_PATHS = {
    ".claude/skills/run-maintenance",
}


def check_stale_remove_paths(root: Path) -> list:
    """Selbstpruefung fuer '--check': prueft je Pfad in STALE_PATH_CHECK_LISTS, ob er im Repo existiert.

    Ein fehlender Pfad ist nur dann verdaechtig (typischer Fehler nach einer Umbenennung, z.B. ein Ordner
    wurde umbenannt, aber die Liste hier nicht mitgezogen), wenn die Ausgangslage noch unberuehrt ist - d.h.
    solange der 'is_template'-Marker in .claude/template.json noch gesetzt ist (frischer Template-Checkout
    oder frisch geklontes, noch nicht per --apply zugeschnittenes Projekt). Ist der Marker schon weg, hat
    --apply bereits gelaufen und genau diese Pfade wurden absichtlich entfernt - eine Warnung waere dann ein
    Fehlalarm, deshalb wird die Pruefung dafuer bewusst NICHT ausgefuehrt statt sie nur schwaecher zu
    formulieren. Pfade aus LEGACY_REMOVE_PATHS werden nie gemeldet (siehe dort). Gibt eine Liste von
    Warnzeilen zurueck (leer = nichts zu melden)."""
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
            if rel in LEGACY_REMOVE_PATHS:
                continue
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
    feedback_umfang, feedback_umfang_unbekannt = normalize_feedback_umfang(cfg)
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
    if not cfg.get("orchestrator"):
        _name, _grund = default_orchestrator(cfg)
        lines.append(f"Orchestrator-Rufname: {_name}   ({_grund}; in AI-CONFIG.md eintragen, um ihn zu "
                     "aendern)")
        lines.append("")
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
    if feedback_umfang_unbekannt:
        lines.append(f"Feedback-Umfang: \"{feedback_umfang_unbekannt}\" ist keine bekannte Kennung - --apply "
                     f"bricht damit ab. Erlaubt: {', '.join(sorted(FEEDBACK_UMFANG_WERTE))} (Kommaliste).")
    elif feedback_umfang:
        for kennung in feedback_umfang.split(","):
            lines.append("Feedback-Umfang: " + FEEDBACK_UMFANG_TEXT[kennung])
    else:
        lines.append("Feedback-Umfang: leer - nur Registrierung und von Hand geschriebenes Feedback")

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
        lines.append("Code-Analyse (nur Weg 2 /act-apply-template): " + CODE_ANALYSE_TEXT[code_analyse])

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
        lines.append("Struktur-Migration (nur Weg 2 /act-apply-template): "
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
    feedback_umfang, feedback_umfang_unbekannt = normalize_feedback_umfang(cfg)
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
        (feedback_umfang_unbekannt, "Feedback-Umfang", FEEDBACK_UMFANG_WERTE),
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
    removed_files, _behalten_tools = remove_tool_files(root, remove_list)
    logging_changed = set_logging_switch(root, logging_val, logging_tiefe)
    optimizer_entfernt, _behalten_opt = remove_optimizer_files(root) if code_opt == "aus" else ([], {})
    guidelines_entfernt = apply_coding_guidelines(root, guidelines_gewaehlt)
    intro_entfernt = remove_template_intro(root)
    applied_config = build_applied_config(
        values, orch_modell, logging_val, logging_tiefe, wartung_val, wartungsaufgaben,
        wartungsberichte, code_opt, guidelines_gewaehlt, remove_list,
        sprache=cfg.get("sprache"), commit_verhalten=commit_verhalten,
        ideen_ablauf=ideen_ablauf, testtiefe=testtiefe, schreibstil=schreibstil,
        feedback=feedback, feedback_takt=feedback_takt, feedback_umfang=feedback_umfang,
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
        removed_maintenance, _behalten_maint = remove_maintenance_files(root)
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
    lines.append("Feedback-Umfang: " + (feedback_umfang or "leer (nur Registrierung und eigenes Feedback)"))
    lines.append(f"Wartung: {wartung_status}")
    lines.append(f"Wartungsberichte: {wartungsberichte_status}")
    if wartungsberichte == "docs":
        lines.append("  Bitte docs/maintenance/ noch in docs/README.md eintragen.")
    lines.append("Code-Analyse (nur Weg 2 /act-apply-template): " + CODE_ANALYSE_TEXT[code_analyse])
    lines.append("Code-Optimierung: " + CODE_OPTIMIERUNG_TEXT[code_opt]
                 + (" (entfernt: " + ", ".join(optimizer_entfernt) + ")" if optimizer_entfernt else "")
                 + (" - Hinweis: " + code_opt_hinweis if code_opt_hinweis else ""))
    lines.append("Coding-Guidelines: " + (", ".join(guidelines_gewaehlt) if guidelines_gewaehlt else "keine")
                 + (" (entfernt: " + ", ".join(guidelines_entfernt) + ")" if guidelines_entfernt else ""))
    lines.append("Struktur-Migration (nur Weg 2 /act-apply-template): "
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
        lines.append("Offene Platzhalter: keine (ausser den bekannten Fundstellen in checklists.md/act-create-project SKILL.md).")

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
