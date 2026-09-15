#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Bibliothek fuer Datei- und Pfadoperationen des Setup-Ablaufs: Platzhalter-Ersetzung
# (replace_placeholders/_iter_text_files), der Datenverlust-Schutz beim Entfernen (ungesicherte_pfade) samt
# der drei remove_*_files-Funktionen, Hook-Pflege in .claude/settings.json, Orchestrator-Modell/Logging-
# Schalter setzen und die JSON-/Text-Schreibhelfer (_read_*/_write_*). Herausgetrennt aus setup-lib.py
# (Backlog/.templatedev/questions.md Q4), das als duenne Fassade (Re-Export dieser drei Module) plus dem
# eigentlichen Setup-Ablauf bestehen bleibt - siehe dort. Braucht TOOL_FILES aus config-lib.py (per
# importlib, gleiches Muster wie sync-config.py/rename-lib.py - Bindestrich im Dateinamen verbietet ein
# normales `import`); run_git und _load_template_update_module sind hier bewusst dupliziert (wie in vielen
# anderen Scripten dieses Ordners), um keinen Ring config-lib <-> files-lib <-> setup-lib zu riskieren.

import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path


def _load_module(filename: str, mod_name: str):
    path = Path(__file__).resolve().parent / filename
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_config_lib = _load_module("config-lib.py", "_files_lib_config")
TOOL_FILES = _config_lib.TOOL_FILES


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
    spec = importlib.util.spec_from_file_location("_files_lib_tu", tu_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
OPTIMIZER_REMOVE_PATHS = [".claude/agents/optimizer.md"]

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


# ---------------------------------------------------------------------------
# Schutz vor Datenverlust beim Entfernen (Backlog #30, .templatedev/backlog.md)
# ---------------------------------------------------------------------------
#
# Abschalten loescht Dateien - das bleibt so, darf aber nie Dateien treffen, die nirgendwo sonst liegen:
# gitignorierte Berichte (z.B. .claude/maintenance/reports/), noch ungetrackte oder lokal geaenderte
# Dateien. Ohne Commit/Remote sind sie nach dem Loeschen unwiederbringlich weg.


def ungesicherte_pfade(root: Path, rels) -> dict:
    """Prueft die root-relativen Pfade in 'rels' (Dateien oder Ordner) per 'git status' auf Inhalt, der beim
    Loeschen verloren waere. Liefert {root-relativer_posix_pfad: grund}; bei einem Ordner sind das die
    einzelnen betroffenen Dateien darunter, nicht der Ordner selbst. Grund ist 'gitignoriert' (Status '!!'),
    'ungetrackt' ('??') oder 'lokal geaendert' (jeder andere Status, z.B. ' M', 'MM', 'AM', 'A '). '-z' ist
    Pflicht (Pfade mit Leerzeichen/Umlauten, siehe rename-lib.py compute_ignored_paths).
    Ist git nicht aufrufbar (kein Repo, git fehlt, Timeout) -> NICHT pruefbar: jeder angegebene Pfad wird
    dann selbst als ungesichert gemeldet (Grund 'nicht pruefbar'), damit im Zweifel nichts geloescht wird,
    statt blind zu loeschen."""
    vorhanden = [rel for rel in rels if (root / rel).exists()]
    if not vorhanden:
        return {}
    try:
        res = run_git(root, ["status", "--porcelain", "--ignored", "-z", "--"] + vorhanden, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return {rel: "nicht pruefbar (git nicht aufrufbar)" for rel in vorhanden}
    if res.returncode != 0:
        return {rel: "nicht pruefbar (kein Git-Repo?)" for rel in vorhanden}

    gruende = {"!!": "gitignoriert", "??": "ungetrackt"}
    ergebnis = {}
    teile = res.stdout.split("\0")
    i = 0
    while i < len(teile):
        eintrag = teile[i]
        i += 1
        if not eintrag:
            continue
        code = eintrag[:2]
        pfad = eintrag[3:]
        if code[0] in ("R", "C"):
            i += 1  # Umbenennung/Kopie: naechstes Feld ist der alte Pfad, hier nicht gebraucht
        ergebnis[pfad] = gruende.get(code, "lokal geaendert")
    return ergebnis


def _entferne_pfad(fp: Path) -> bool:
    """Loescht Datei oder Ordner ohne Ruecksicht auf ungesicherten Inhalt (Altverhalten)."""
    try:
        if fp.is_dir():
            shutil.rmtree(fp)
        else:
            fp.unlink()
        return True
    except OSError:
        return False


def _blockierender_eintrag(pfad_rel: str, ungesichert: dict):
    """Liefert den Grund aus 'ungesichert' (siehe ungesicherte_pfade), der 'pfad_rel' blockiert, oder None.
    Drei Faelle: exakter Treffer; 'pfad_rel' ist selbst ein komplett ignorierter/ungetrackter Ordner, den
    'git status' als einen Eintrag mit Schraegstrich meldet statt jede Datei einzeln aufzufuehren
    (traditioneller Modus, siehe compute_ignored_paths in rename-lib.py fuer denselben Effekt bei
    check-ignore); oder 'pfad_rel' liegt unterhalb eines solchen gemeldeten Ordners."""
    if pfad_rel in ungesichert:
        return ungesichert[pfad_rel]
    mit_slash = pfad_rel.rstrip("/") + "/"
    if mit_slash in ungesichert:
        return ungesichert[mit_slash]
    for eintrag, grund in ungesichert.items():
        praefix = eintrag if eintrag.endswith("/") else eintrag + "/"
        if pfad_rel.startswith(praefix):
            return grund
    return None


def _entferne_geschuetzt(root: Path, rel: str, ungesichert: dict):
    """Loescht root/rel, laesst aber jede in 'ungesichert' gelistete Datei stehen. Rueckgabe
    (vollstaendig_geloescht, behalten) - behalten: {rel_pfad: grund}. Eine einzelne Datei wird entweder ganz
    geloescht oder ganz behalten; ein Ordner wird teilweise geleert (leere Unterordner danach entfernt)."""
    fp = root / rel
    grund = _blockierender_eintrag(rel, ungesichert)
    if grund is not None:
        return False, {rel: grund}
    if not fp.is_dir():
        return _entferne_pfad(fp), {}

    behalten = {}
    for dirpath, _dirnames, filenames in os.walk(fp, topdown=False):
        ordner = Path(dirpath)
        for name in filenames:
            datei = ordner / name
            datei_rel = datei.relative_to(root).as_posix()
            datei_grund = _blockierender_eintrag(datei_rel, ungesichert)
            if datei_grund is not None:
                behalten[datei_rel] = datei_grund
                continue
            try:
                datei.unlink()
            except OSError:
                pass
        try:
            ordner.rmdir()  # nur noch leere Ordner verschwinden
        except OSError:
            pass
    return not fp.exists(), behalten


def remove_optimizer_files(root: Path, schutz: bool = False):
    """Entfernt den optionalen Politur-Agenten bei 'Code-Optimierung: aus'. Tolerant, wenn er fehlt (z.B.
    weil Claude Code als Werkzeug abgewaehlt wurde und .claude/agents/ schon weg ist). Bei schutz=True
    bleiben ungesicherte Dateien stehen (siehe ungesicherte_pfade). Rueckgabe (removed, behalten)."""
    ungesichert = ungesicherte_pfade(root, OPTIMIZER_REMOVE_PATHS) if schutz else {}
    removed = []
    behalten = {}
    for rel in OPTIMIZER_REMOVE_PATHS:
        fp = root / rel
        if not fp.exists():
            continue
        if schutz:
            ok, keep = _entferne_geschuetzt(root, rel, ungesichert)
            behalten.update(keep)
            if ok:
                removed.append(rel)
            continue
        if _entferne_pfad(fp):
            removed.append(rel)
    return removed, behalten


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


def remove_tool_files(root: Path, remove_list, schutz: bool = False):
    """Entfernt die Dateien abgewaehlter KI-Werkzeuge. Bei schutz=True bleiben ungesicherte Dateien stehen
    (siehe ungesicherte_pfade) - Rueckgabe dann (removed, behalten), sonst behalten immer leer."""
    alle_rels = [rel for tool in remove_list for rel in TOOL_FILES.get(tool, [])]
    ungesichert = ungesicherte_pfade(root, alle_rels) if schutz else {}
    removed = []
    behalten = {}
    for tool in remove_list:
        for rel in TOOL_FILES.get(tool, []):
            fp = root / rel
            if not fp.exists():
                continue
            if schutz:
                ok, keep = _entferne_geschuetzt(root, rel, ungesichert)
                behalten.update(keep)
                if ok:
                    removed.append(rel)
                continue
            if _entferne_pfad(fp):
                removed.append(rel)

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

    return removed, behalten


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


def remove_maintenance_files(root: Path, schutz: bool = False):
    """Entfernt die Wartungsdateien bei 'Wartung: aus'. Bei schutz=True bleiben ungesicherte Dateien stehen
    (siehe ungesicherte_pfade) - Rueckgabe dann (removed, behalten), sonst behalten immer leer. Betrifft vor
    allem .claude/maintenance/reports/ (gitignoriert, siehe .gitignore) - ohne schutz waeren die Berichte
    unwiederbringlich weg (Backlog #30)."""
    ungesichert = ungesicherte_pfade(root, MAINTENANCE_REMOVE_PATHS) if schutz else {}
    removed = []
    behalten = {}
    for rel in MAINTENANCE_REMOVE_PATHS:
        fp = root / rel
        if not fp.exists():
            continue
        if schutz:
            ok, keep = _entferne_geschuetzt(root, rel, ungesichert)
            behalten.update(keep)
            if ok:
                removed.append(rel)
            continue
        if _entferne_pfad(fp):
            removed.append(rel)
    return removed, behalten


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
