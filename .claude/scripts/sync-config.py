#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: AI-CONFIG.md wirkt laufend, nicht nur beim Anlegen (`create-project.py --apply`) - dieses Script
#        gleicht ab, was sich seit dem letzten Lauf geaendert hat, und setzt es um. Vergleichsgrundlage ist
#        `.claude/template.json` § `applied_config` (von `create-project.py --apply` bzw. `--adopt`
#        geschrieben) gegen den aktuellen Stand von AI-CONFIG.md. Baut bewusst NICHTS von dessen Parser/
#        Normalisierern nach, sondern laedt create-project.py, migrate-project.py, guidelines.py,
#        maintenance-check.py und update-template.py per importlib (Muster wie install-global.py) und ruft
#        deren Funktionen direkt auf - Hinzufuegen (dort) und Entfernen (hier) laufen so nie auseinander.
#        Reine Python-Stdlib, kein Paket noetig. Siehe AI-CONFIG.md (Kopf), CLAUDE.md § 1.
#
# Aufruf:
#   python .claude/scripts/sync-config.py --check [--quiet]
#       (Default) Vergleicht AI-CONFIG.md gegen `applied_config`, schreibt NICHTS. Je Abweichung eine Zeile:
#       Schluessel, alter Wert, neuer Wert, geplante Wirkung, automatisch oder "braucht --yes". Fehlt
#       `applied_config` (Projekt vor diesem Script angelegt): Stand als "unbekannt" erklaeren, `--adopt`
#       vorschlagen, nichts pruefen. --quiet: bei nichts Offenem KEINE Ausgabe (fuer den SessionStart-Hook);
#       ist etwas offen, eine Kurzzeile statt der vollen Liste. Exit 0 = alles gleich, 3 = etwas offen (bzw.
#       `applied_config` unbekannt), 2 = AI-CONFIG.md nicht eindeutig lesbar (wie create-project.py --apply).
#   python .claude/scripts/sync-config.py --apply [--yes]
#       Setzt die automatischen Aenderungen um (Ergaenzungen: Dateien nachladen, Schalter setzen). Die
#       zusagepflichtigen (loeschen, projektweite Ersetzung) NUR zusammen mit --yes - ohne --yes werden sie
#       aufgelistet und uebersprungen. Schreibt `applied_config` danach fort (nur die Schluessel, die
#       tatsaechlich umgesetzt wurden). Exit 0 = alles umgesetzt, 3 = zusagepflichtige Punkte offen
#       geblieben (ohne --yes), 2 = wie oben bzw. kein Template-Remote fuer eine faellige Datei-Ergaenzung.
#   python .claude/scripts/sync-config.py --adopt
#       Uebernimmt den aktuellen AI-CONFIG.md-Stand als "umgesetzt", OHNE etwas zu aendern - fuer ein Projekt,
#       das die Umstellung von Hand nachgezogen hat, oder fuer den allerersten Lauf ohne `applied_config`.
#   python .claude/scripts/sync-config.py --status
#       Zeigt den Inhalt von `applied_config` und das Datum des letzten Abgleichs (bzw. "unbekannt").
#
# Datei-Ergaenzungen (KI-Werkzeuge/Wartung/Code-Optimierung) kommen per `git show <remote>/<branch>:<pfad>`
# aus dem Template-Remote (`.claude/template.json` § template_remote/template_branch) - vorher wird
# `git fetch <remote>` versucht; schlaegt das fehl, wird mit dem lokalen Stand weitergearbeitet (Hinweis statt
# Abbruch). Fehlt der Remote ganz, wird nichts geraten: Hinweis auf `update-template.py --init`, Exit 2/3 fuer
# die betroffenen Punkte. Nachgeladene Dateien werden mit den Werten aus `.claude/template.json` § `values`
# von ihren Platzhaltern befreit; am Ende steht in keiner geschriebenen Datei mehr "{{".
#
# Exit-Codes: 0 = ok, 2 = Vorbedingungsfehler (AI-CONFIG.md nicht eindeutig, Template-Remote fehlt fuer eine
# faellige Ergaenzung), 3 = etwas offen (--check) bzw. zusagepflichtige Punkte uebersprungen (--apply ohne
# --yes). Ein Fehler dieses Scripts darf nie mit Traceback nach aussen dringen - main() laeuft in try/except.

import argparse
import importlib.util
import json
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
# Module per importlib laden (Muster wie install-global.py/migrate-project.py) - Parser/Normalisierer/
# Datei-Operationen leben in den jeweiligen Scripten, hier nur aufrufen.
# ---------------------------------------------------------------------------


def _find_root() -> Path:
    import os

    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[2]


def _load_module(root: Path, filename: str, mod_name: str):
    path = root / ".claude" / "scripts" / filename
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_modules(root: Path):
    """Gibt ein dict der benoetigten Module zurueck - fehlende (z.B. maintenance-check.py bei
    'Wartung: aus') werden als None eingetragen, Aufrufer pruefen das an der jeweiligen Stelle."""
    return {
        "cp": _load_module(root, "create-project.py", "_sync_cp"),
        "mp": _load_module(root, "migrate-project.py", "_sync_mp"),
        "gl": _load_module(root, "guidelines.py", "_sync_gl"),
        "mc": _load_module(root, "maintenance-check.py", "_sync_mc"),
        "tu": _load_module(root, "update-template.py", "_sync_tu"),
    }


# ---------------------------------------------------------------------------
# Template-Ref (fuer Datei-Ergaenzungen) + Datei-Fetch mit Platzhalter-Ersetzung
# ---------------------------------------------------------------------------


def resolve_template_ref(root: Path, tu):
    """(ref, hinweis_oder_None, fehler_oder_None). Genau eines von (ref, fehler) ist gesetzt. `hinweis`
    meldet einen fehlgeschlagenen Fetch (offline) - dann wird mit dem lokalen Stand weitergearbeitet."""
    if tu is None:
        return None, None, "update-template.py fehlt - kann den Template-Stand nicht ermitteln."
    tpl_cfg, _path = tu.load_template_json(root)
    ref, fetch_noetig = tu.compare_ref(root, tpl_cfg)
    if ref is None:
        return None, None, (
            "kein Template-Remote/-Branch gefunden - `python .claude/scripts/update-template.py --init` "
            "richtet ihn ein."
        )
    hinweis = None
    if fetch_noetig:
        remote = tpl_cfg.get("template_remote") or "template"
        try:
            res_fetch = tu.run_git(root, ["fetch", remote], timeout=20)
        except Exception as e:  # noqa: BLE001 - Netzwerk-/Timeoutfehler duerfen nicht durchschlagen
            res_fetch = None
            hinweis = f"'git fetch {remote}' fehlgeschlagen ({e}) - arbeite mit vorhandenem Stand weiter."
        if res_fetch is not None and res_fetch.returncode != 0:
            hinweis = (
                f"'git fetch {remote}' fehlgeschlagen (offline?) - arbeite mit vorhandenem Stand weiter."
            )
    res_verify = tu.run_git(root, ["rev-parse", "--verify", "--quiet", ref])
    if res_verify.returncode != 0:
        return None, hinweis, f"Referenz '{ref}' nicht aufloesbar (auch nicht nach Fetch)."
    return ref, hinweis, None


def _git_ls_tree(tu, root: Path, ref: str, rel: str):
    res = tu.run_git(root, ["ls-tree", "-r", "--name-only", ref, "--", rel])
    if res.returncode != 0:
        return []
    return [l.strip() for l in res.stdout.splitlines() if l.strip()]


def fetch_paths(tu, root: Path, ref: str, rels, values: dict):
    """Holt jeden Pfad aus `rels` (Datei ODER Ordner, rekursiv per ls-tree) aus dem Template-Ref - nur
    Dateien, die lokal noch NICHT existieren (nie stillschweigend ueberschreiben). Ersetzt {{KEY}} mit den
    Werten aus `values` (== template.json § values). Gibt (geholt, vorhanden, fehler, offene_platzhalter)
    zurueck, je eine Liste relativer Pfade."""
    geholt, vorhanden, fehler, offen = [], [], [], []
    for rel in rels:
        dateien = _git_ls_tree(tu, root, ref, rel)
        if not dateien:
            dateien = [rel]  # kein Ordner (oder im Ref nicht als Baum gefunden) - als einzelne Datei versuchen
        for f in dateien:
            fp = root / f
            if fp.exists():
                vorhanden.append(f)
                continue
            res = tu.run_git(root, ["show", f"{ref}:{f}"])
            if res.returncode != 0:
                fehler.append(f)
                continue
            content = res.stdout
            for key, val in (values or {}).items():
                if val is not None:
                    content = content.replace("{{" + key + "}}", str(val))
            try:
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_text(content, encoding="utf-8", newline="\n")
            except OSError:
                fehler.append(f)
                continue
            geholt.append(f)
            if "{{" in content:
                offen.append(f)
    return geholt, vorhanden, fehler, offen


def plain_replace_in_repo(cp, root: Path, alt: str, neu: str):
    """Ersetzt ALT durch NEU wortwoertlich (kein Markdown-Schutz, keine Gross-/Kleinschreib-Varianten) in
    allen Textdateien (dieselbe Datei-Auswahl wie cp.replace_placeholders, zusaetzlich werden ALLE
    .claude/scripts/*.py-Dateien ausgespart - ein Befehls-Wert koennte sonst zufaellig ein Code-Literal in
    einem Script treffen). Fuer Befehls-Werte/Platzhalter, die AUCH in Codebloecken stehen sollen (anders als
    ein Rufname, der dort nur zufaellig vorkommen kann - siehe rename_orchestrator).
    Gibt (per_file: [(rel, anzahl)], total, fehler: [rel]) zurueck."""
    if alt == neu:
        return [], 0, []
    per_file, fehler = [], []
    total = 0
    for fp, rel in cp._iter_text_files(root):
        if rel.startswith(".claude/scripts/") and rel.endswith(".py"):
            continue
        try:
            content, newline = cp._read_text_preserve_newline(fp)
        except (UnicodeDecodeError, OSError):
            continue
        count = content.count(alt)
        if not count:
            continue
        new_content = content.replace(alt, neu)
        try:
            cp._write_text_preserve_newline(fp, new_content, newline)
        except OSError:
            fehler.append(rel)
            continue
        per_file.append((rel, count))
        total += count
    return per_file, total, fehler


# ---------------------------------------------------------------------------
# Wartungs-Hook in .claude/settings.json ergaenzen (Gegenstueck zu create-project.py:remove_maintenance_hook)
# ---------------------------------------------------------------------------


def _maintenance_hook_pieces_from_ref(tu, root: Path, ref: str):
    """(hook_eintraege, permission_eintraege) fuer maintenance-check.py aus der Template-Version von
    .claude/settings.json - dieselbe Erkennung (Kommando enthaelt 'maintenance-check.py' UND
    'CLAUDE_PROJECT_DIR') wie create-project.py:remove_maintenance_hook, nur in die Gegenrichtung."""
    res = tu.run_git(root, ["show", f"{ref}:.claude/settings.json"])
    if res.returncode != 0:
        return [], []
    try:
        data = json.loads(res.stdout)
    except ValueError:
        return [], []
    hooks = []
    session_start = (data.get("hooks") or {}).get("SessionStart")
    if isinstance(session_start, list):
        for e in session_start:
            dumped = json.dumps(e, ensure_ascii=False).replace("\\\\", "/")
            if "maintenance-check.py" in dumped and "CLAUDE_PROJECT_DIR" in dumped:
                hooks.append(e)
    allow = (data.get("permissions") or {}).get("allow")
    perms = [p for p in allow if "maintenance-check.py" in p] if isinstance(allow, list) else []
    return hooks, perms


def add_maintenance_hook(cp, tu, root: Path, ref: str) -> str:
    path = root / ".claude" / "settings.json"
    if not path.exists():
        return "settings.json fehlt - Hook nicht gesetzt (Claude Code vermutlich abgewaehlt)."
    hooks_neu, perms_neu = _maintenance_hook_pieces_from_ref(tu, root, ref)
    if not hooks_neu and not perms_neu:
        return "Hook-Vorlage im Template nicht gefunden - Hook nicht gesetzt."
    try:
        data, newline = cp._read_json_preserve_newline(path)
    except (OSError, UnicodeDecodeError, ValueError):
        return "settings.json konnte nicht gelesen werden - Hook nicht gesetzt."
    if not isinstance(data, dict):
        return "settings.json: kein JSON-Objekt - Hook nicht gesetzt."

    changed = False
    session_start = data.setdefault("hooks", {}).setdefault("SessionStart", [])
    vorhanden = {json.dumps(e, ensure_ascii=False).replace("\\\\", "/") for e in session_start}
    for e in hooks_neu:
        if json.dumps(e, ensure_ascii=False).replace("\\\\", "/") not in vorhanden:
            session_start.append(e)
            changed = True
    allow = data.setdefault("permissions", {}).setdefault("allow", [])
    for p in perms_neu:
        if p not in allow:
            allow.append(p)
            changed = True
    if changed:
        cp._write_json(path, data, newline)
        return "settings.json: Hook + Permission fuer maintenance-check.py ergaenzt."
    return "settings.json: Hook/Permission bereits vorhanden."


# Runner-Dateien statt des ganzen Ordners holen - status.json NICHT mitfetchen, das schreibt
# write_maintenance_status() gleich danach passend zu AI-CONFIG.md § Wartungsaufgaben.
def maintenance_fetch_paths(cp):
    return [
        ".claude/skills/run-maintenance",
        ".claude/agents/maintenance-orchestrator.md",
        ".claude/scripts/maintenance-check.py",
    ] + [f".claude/maintenance/{name}" for name in cp.MAINTENANCE_RUNNER_FILES]


# ---------------------------------------------------------------------------
# Aktuellen AI-CONFIG.md-Stand als Schnappschuss lesen (dieselbe Form wie applied_config)
# ---------------------------------------------------------------------------


def compute_current(cp, root: Path):
    """(cfg, values, snapshot, fehler, hinweise). `fehler` = Liste unbekannter/ungueltiger Werte (wie
    create-project.py --apply) - ist sie nicht leer, darf nichts umgesetzt werden. `hinweise` sind
    informative Meldungen ohne Abbruch (z.B. der 'streng'->'intensiv'-Alias)."""
    cfg = cp.load_config(root)
    values = cp.compute_values(cfg)
    logging_val, logging_tiefe = cp.logging_settings(cfg)
    fehler = []
    hinweise = []

    orch_modell, orch_unbekannt = cp.normalize_orchestrator_modell(cfg)
    if orch_unbekannt:
        fehler.append(f"Orchestrator-Modell: \"{orch_unbekannt}\" unbekannt (opus, sonnet, haiku, inherit).")
    wartung_val, wartung_unbekannt = cp.normalize_wartung(cfg)
    if wartung_unbekannt:
        fehler.append(f"Wartung: \"{wartung_unbekannt}\" unbekannt (aus, ein).")
    wartungsberichte, wb_unbekannt = cp.normalize_wartungsberichte(cfg)
    if wb_unbekannt:
        fehler.append(f"Wartungsberichte: \"{wb_unbekannt}\" unbekannt (intern, docs).")
    code_opt, code_opt_unbekannt, code_opt_hinweis = cp.normalize_code_optimierung(cfg)
    if code_opt_unbekannt:
        fehler.append(f"Code-Optimierung: \"{code_opt_unbekannt}\" unbekannt (aus, ein, intensiv).")
    if code_opt_hinweis:
        hinweise.append(code_opt_hinweis)
    # Bewusst NICHT cp.parse_coding_guidelines() (dessen "unbekannt" nur den LOKALEN Ordner prueft) - eine
    # Kennung, die lokal fehlt, aber im Template existiert, waere sonst faelschlich "unbekannt". Die echte
    # Pruefung (lokal + Template-Katalog) macht guidelines.py --add beim Ausfuehren.
    guidelines_gewaehlt = []
    for teil in (cfg.get("coding_guidelines") or "").split(","):
        k = teil.strip().lower()
        if k and k not in guidelines_gewaehlt:
            guidelines_gewaehlt.append(k)
    wartungsaufgaben_raw = cfg.get("wartungsaufgaben") or cp.DEFAULT_WARTUNGSAUFGABEN
    wartungsaufgaben, wa_fehler = cp.parse_wartungsaufgaben(wartungsaufgaben_raw)
    if wartung_val == "ein" and wa_fehler:
        fehler.append("Wartungsaufgaben ungueltig: " + ", ".join(wa_fehler))
    unbekannte_tools = cp.unbekannte_werkzeuge(cfg)
    if unbekannte_tools:
        fehler.append("KI-Werkzeuge unbekannt: " + ", ".join(unbekannte_tools))

    remove_list = cp.tools_to_remove(cfg)
    snapshot = cp.build_applied_config(
        values, orch_modell, logging_val, logging_tiefe, wartung_val, wartungsaufgaben,
        wartungsberichte, code_opt, guidelines_gewaehlt, remove_list,
    )
    return cfg, values, snapshot, fehler, hinweise


# ---------------------------------------------------------------------------
# Diffs berechnen
# ---------------------------------------------------------------------------

# Projektname/Auftraggeber/Orchestrator: echte Rufnamen, die zufaellig in Beispiel-Code/URLs auftauchen
# koennen - dafuer rename_orchestrator() (Markdown-Schutz fuer Codebloecke/URLs, siehe migrate-project.py).
RENAME_KEYS = ["Projektname", "Auftraggeber", "Orchestrator"]
# Befehls-Schluessel: der Wert (oder die Marke, wenn er leer ist) soll UEBERALL ersetzt werden, auch in
# Codebloecken (z.B. docs/project/setup.md zeigt den Install-Befehl absichtlich in einem Codebeispiel) -
# dafuer NICHT rename_orchestrator (dessen Markdown-Maskierung wuerde genau diese Stellen auslassen),
# sondern ein einfacher, ungemaskter Ersatz (siehe plain_replace_in_repo).
BEFEHL_KEYS = ["Install-Befehl", "Dev-Start-Befehl", "Lint-Befehl", "Typecheck-Befehl", "Test-Befehl", "E2E-Befehl"]
RENAME_PLATZHALTER = {
    "Projektname": "{{PROJEKTNAME}}", "Auftraggeber": "{{AUFTRAGGEBER}}", "Orchestrator": "{{ORCHESTRATOR}}",
    "Install-Befehl": "{{INSTALL_BEFEHL}}", "Dev-Start-Befehl": "{{DEV_START_BEFEHL}}",
    "Lint-Befehl": "{{LINT_BEFEHL}}", "Typecheck-Befehl": "{{TYPECHECK_BEFEHL}}",
    "Test-Befehl": "{{TEST_BEFEHL}}", "E2E-Befehl": "{{E2E_BEFEHL}}",
}


def compute_diffs(old: dict, current: dict) -> list:
    """Liste von dicts {key, old, new, kategorie(automatisch|zusage), kind, wirkung, ...zusatz}."""
    diffs = []

    for key, kind in [(k, "rename") for k in RENAME_KEYS] + [(k, "befehl_replace") for k in BEFEHL_KEYS]:
        ov, nv = old.get(key), current.get(key)
        if ov == nv:
            continue
        alt = ov if ov is not None else RENAME_PLATZHALTER[key]
        neu = nv if nv is not None else RENAME_PLATZHALTER[key]
        if alt == neu:
            continue
        diffs.append({
            "key": key, "old": ov, "new": nv, "kategorie": "zusage", "kind": kind, "marker": [key],
            "alt": alt, "neu": neu, "wirkung": f"projektweite Ersetzung '{alt}' -> '{neu}'",
        })

    old_entfernt = set(old.get("KI-Werkzeuge-entfernt") or [])
    new_entfernt = set(current.get("KI-Werkzeuge-entfernt") or [])
    hinzu = sorted(old_entfernt - new_entfernt)
    weg = sorted(new_entfernt - old_entfernt)
    if hinzu:
        diffs.append({
            "key": "KI-Werkzeuge", "old": sorted(old_entfernt), "new": sorted(new_entfernt),
            "kategorie": "automatisch", "kind": "tools_add", "werkzeuge": hinzu,
            "marker": ["KI-Werkzeuge-entfernt"], "wirkung": f"Dateien nachladen: {', '.join(hinzu)}",
        })
    if weg:
        diffs.append({
            "key": "KI-Werkzeuge", "old": sorted(old_entfernt), "new": sorted(new_entfernt),
            "kategorie": "zusage", "kind": "tools_remove", "werkzeuge": weg,
            "marker": ["KI-Werkzeuge-entfernt"], "wirkung": f"Dateien entfernen: {', '.join(weg)}",
        })

    old_gl = set(old.get("Coding-Guidelines") or [])
    new_gl = set(current.get("Coding-Guidelines") or [])
    add_gl = sorted(new_gl - old_gl)
    rem_gl = sorted(old_gl - new_gl)
    if add_gl:
        diffs.append({
            "key": "Coding-Guidelines", "old": sorted(old_gl), "new": sorted(new_gl),
            "kategorie": "automatisch", "kind": "guidelines_add", "ids": add_gl,
            "marker": ["Coding-Guidelines"], "wirkung": f"Regelsatz ergaenzen: {', '.join(add_gl)}",
        })
    if rem_gl:
        diffs.append({
            "key": "Coding-Guidelines", "old": sorted(old_gl), "new": sorted(new_gl),
            "kategorie": "zusage", "kind": "guidelines_remove", "ids": rem_gl,
            "marker": ["Coding-Guidelines"], "wirkung": f"Regelsatz entfernen: {', '.join(rem_gl)}",
        })

    if old.get("Orchestrator-Modell") != current.get("Orchestrator-Modell"):
        diffs.append({
            "key": "Orchestrator-Modell", "old": old.get("Orchestrator-Modell"),
            "new": current.get("Orchestrator-Modell"), "kategorie": "automatisch", "kind": "orch_modell",
            "marker": ["Orchestrator-Modell"],
            "wirkung": f"'model' in .claude/settings.json = '{current.get('Orchestrator-Modell')}'",
        })

    if (old.get("Logging"), old.get("Logging-Tiefe")) != (current.get("Logging"), current.get("Logging-Tiefe")):
        diffs.append({
            "key": "Logging/Logging-Tiefe",
            "old": f"{old.get('Logging')}/{old.get('Logging-Tiefe')}",
            "new": f"{current.get('Logging')}/{current.get('Logging-Tiefe')}",
            "kategorie": "automatisch", "kind": "logging", "marker": ["Logging", "Logging-Tiefe"],
            "wirkung": "AI_LOG/AI_LOG_LEVEL in AGENTS.md setzen",
        })

    old_w, new_w = old.get("Wartung"), current.get("Wartung")
    if old_w != new_w:
        kat = "automatisch" if (old_w == "aus" and new_w == "ein") else "zusage"
        wirkung = (
            "Wartungsdateien + Hook nachladen, status.json schreiben" if kat == "automatisch"
            else "Wartungsdateien + Hook entfernen"
        )
        diffs.append({"key": "Wartung", "old": old_w, "new": new_w, "kategorie": kat, "kind": "wartung",
                      "marker": ["Wartung"], "wirkung": wirkung})

    if new_w == "ein" and old.get("Wartungsaufgaben") != current.get("Wartungsaufgaben"):
        diffs.append({
            "key": "Wartungsaufgaben", "old": old.get("Wartungsaufgaben"), "new": current.get("Wartungsaufgaben"),
            "kategorie": "automatisch", "kind": "wartungsaufgaben", "marker": ["Wartungsaufgaben"],
            "wirkung": "maintenance-check.py --set (+ entfallene Aufgaben abschalten)",
        })

    if old.get("Wartungsberichte") != current.get("Wartungsberichte"):
        neu_wb = current.get("Wartungsberichte")
        wirkung = "docs/maintenance/README.md anlegen" if neu_wb == "docs" else "keine Datei-Aenderung"
        diffs.append({
            "key": "Wartungsberichte", "old": old.get("Wartungsberichte"), "new": neu_wb,
            "kategorie": "automatisch", "kind": "wartungsberichte", "marker": ["Wartungsberichte"],
            "wirkung": wirkung,
        })

    old_co, new_co = old.get("Code-Optimierung"), current.get("Code-Optimierung")
    if old_co != new_co:
        if old_co == "aus" and new_co in ("ein", "intensiv"):
            kind, kat, wirkung = "code_opt_add", "automatisch", "optimizer.md nachladen"
        elif old_co in ("ein", "intensiv") and new_co == "aus":
            kind, kat, wirkung = "code_opt_remove", "zusage", "optimizer.md entfernen"
        else:
            kind, kat, wirkung = "code_opt_level", "automatisch", "keine Datei-Aenderung (nur Verhalten)"
        diffs.append({"key": "Code-Optimierung", "old": old_co, "new": new_co, "kategorie": kat,
                      "kind": kind, "marker": ["Code-Optimierung"], "wirkung": wirkung})

    return diffs


# ---------------------------------------------------------------------------
# Diffs ausfuehren
# ---------------------------------------------------------------------------


def execute_diff(mods, root: Path, cfg: dict, values: dict, current: dict, diff: dict, yes: bool, ref_holder: dict):
    """Fuehrt einen Diff aus (oder liefert bei zusage ohne yes nur die Vorschau-Zeilen). Gibt eine Liste
    Berichtzeilen zurueck; haengt bei Erfolg den Schluessel an ref_holder['executed'] (Menge der
    tatsaechlich umgesetzten Snapshot-Schluessel, fuer die spaetere applied_config-Aktualisierung)."""
    cp, mp, gl, mc, tu = mods["cp"], mods["mp"], mods["gl"], mods["mc"], mods["tu"]
    kind = diff["kind"]
    lines = []

    if kind == "rename":
        per_file, total, fehler, total_skipped = mp.rename_orchestrator(root, diff["alt"], diff["neu"], dry_run=not yes)
        lines.extend(mp._format_rename_report(diff["alt"], diff["neu"], per_file, total, fehler, total_skipped, executed=yes))
        if yes:
            ref_holder["executed"].add(diff["key"])
        return lines

    if kind == "befehl_replace":
        if not yes:
            lines.append(f"(Vorschau) wuerde '{diff['alt']}' -> '{diff['neu']}' ersetzen (kein Markdown-Schutz).")
            return lines
        per_file, total, fehler = plain_replace_in_repo(cp, root, diff["alt"], diff["neu"])
        verb = "ersetzt" if not fehler else "ersetzt (mit Fehlern)"
        lines.append(f"'{diff['alt']}' -> '{diff['neu']}': {total} Treffer {verb} in {len(per_file)} Dateien")
        for rel, cnt in per_file[:20]:
            lines.append(f"  {rel}: {cnt}")
        for rel in fehler:
            lines.append(f"  FEHLER, nicht geschrieben: {rel}")
        ref_holder["executed"].add(diff["key"])
        return lines

    if kind == "tools_add":
        ref, hinweis, fehler = _get_ref(ref_holder, tu, root)
        if hinweis:
            lines.append(hinweis)
        if fehler:
            lines.append(f"KI-Werkzeuge nachladen: {fehler}")
            return lines
        for tool in diff["werkzeuge"]:
            rels = cp.TOOL_FILES.get(tool, [])
            geholt, vorhanden, fehl, offen = fetch_paths(tu, root, ref, rels, values)
            lines.append(f"  {tool}: geholt {geholt or '(keine)'}" + (f", schon da {vorhanden}" if vorhanden else "")
                         + (f", FEHLER {fehl}" if fehl else ""))
            if offen:
                lines.append(f"    Achtung, noch Platzhalter offen: {offen}")
        _set_partial(ref_holder, "KI-Werkzeuge-entfernt",
                     _get_partial(ref_holder, "KI-Werkzeuge-entfernt", diff["old"]) - set(diff["werkzeuge"]))
        ref_holder["executed"].add("KI-Werkzeuge-entfernt")
        return lines

    if kind == "tools_remove":
        if not yes:
            lines.append(f"(Vorschau) wuerde entfernen: {diff['werkzeuge']}")
            return lines
        removed = cp.remove_tool_files(root, diff["werkzeuge"])
        lines.append(f"Entfernt: {removed or '(nichts gefunden)'}")
        _set_partial(ref_holder, "KI-Werkzeuge-entfernt",
                     _get_partial(ref_holder, "KI-Werkzeuge-entfernt", diff["old"]) | set(diff["werkzeuge"]))
        ref_holder["executed"].add("KI-Werkzeuge-entfernt")
        return lines

    if kind == "guidelines_add":
        if gl is None:
            lines.append("guidelines.py fehlt - Regelsatz nicht ergaenzt.")
            return lines
        tu_mod = gl._load_template_update_module()
        rc = gl.cmd_add(root, tu_mod, ",".join(diff["ids"]))
        if rc == 0:
            _set_partial(ref_holder, "Coding-Guidelines",
                         _get_partial(ref_holder, "Coding-Guidelines", diff["old"]) | set(diff["ids"]))
            ref_holder["executed"].add("Coding-Guidelines")
        else:
            lines.append("guidelines.py --add ist fehlgeschlagen (siehe Ausgabe oben).")
        return lines

    if kind == "guidelines_remove":
        if not yes:
            lines.append(f"(Vorschau) wuerde entfernen: {diff['ids']}")
            return lines
        if gl is None:
            lines.append("guidelines.py fehlt - Regelsatz nicht entfernt.")
            return lines
        tu_mod = gl._load_template_update_module()
        rc = gl.cmd_remove(root, tu_mod, ",".join(diff["ids"]))
        if rc == 0:
            _set_partial(ref_holder, "Coding-Guidelines",
                         _get_partial(ref_holder, "Coding-Guidelines", diff["old"]) - set(diff["ids"]))
            ref_holder["executed"].add("Coding-Guidelines")
        return lines

    if kind == "orch_modell":
        status = cp.set_orchestrator_model(root, diff["new"])
        lines.append(status)
        ref_holder["executed"].add("Orchestrator-Modell")
        return lines

    if kind == "logging":
        logging_val = current.get("Logging")
        logging_tiefe = current.get("Logging-Tiefe")
        changed = cp.set_logging_switch(root, logging_val, logging_tiefe)
        lines.append(f"AGENTS.md: AI_LOG={logging_val}, AI_LOG_LEVEL={logging_tiefe}"
                     + (" (geschrieben)" if changed else " (unveraendert)"))
        ref_holder["executed"].add("Logging")
        ref_holder["executed"].add("Logging-Tiefe")
        return lines

    if kind == "wartung" and diff["new"] == "ein":
        ref, hinweis, fehler = _get_ref(ref_holder, tu, root)
        if hinweis:
            lines.append(hinweis)
        if fehler:
            lines.append(f"Wartung nachladen: {fehler}")
            return lines
        geholt, vorhanden, fehl, offen = fetch_paths(tu, root, ref, maintenance_fetch_paths(cp), values)
        lines.append(f"Wartungsdateien geholt: {geholt or '(keine, schon vollstaendig)'}")
        if fehl:
            lines.append(f"  FEHLER: {fehl}")
        if offen:
            lines.append(f"  Achtung, noch Platzhalter offen: {offen}")
        lines.append(add_maintenance_hook(cp, tu, root, ref))
        cp.write_maintenance_status(root, current.get("Wartungsaufgaben") or {})
        lines.append("status.json geschrieben aus AI-CONFIG.md § Wartungsaufgaben.")
        ref_holder["executed"].add("Wartung")
        ref_holder["executed"].add("Wartungsaufgaben")
        return lines

    if kind == "wartung" and diff["new"] == "aus":
        if not yes:
            lines.append("(Vorschau) wuerde Wartungsdateien + Hook entfernen.")
            return lines
        removed = cp.remove_maintenance_files(root)
        hook_removed, hooks_fremde = cp.remove_maintenance_hook(root)
        claude_refs = cp.remove_maintenance_references(root)
        lines.append(f"Entfernt: {removed or '(keine)'}; Hook " + ("entfernt" if hook_removed else "(nicht vorhanden)"))
        for f in hooks_fremde:
            lines.append(f"  fremder Hook belassen (zeigt jetzt ins Leere): {f}")
        if claude_refs["agent_zeile"] != claude_refs["skill_zeile"]:
            lines.append("  CLAUDE.md-Verweise nur teilweise angepasst - ggf. von Hand pruefen.")
        ref_holder["executed"].add("Wartung")
        return lines

    if kind == "wartungsaufgaben":
        # mc frisch nachladen statt des beim Start geladenen mods["mc"] - der kann None sein, wenn
        # "Wartung: aus->ein" in diesem Lauf maintenance-check.py erst soeben nachgeladen hat.
        mc = _load_module(root, "maintenance-check.py", "_sync_mc_late")
        if mc is None:
            lines.append("maintenance-check.py fehlt - Wartungsaufgaben nicht gesetzt.")
            return lines
        neu = current.get("Wartungsaufgaben") or {}
        alt = old_wartungsaufgaben_ref = diff["old"] or {}
        set_arg = ",".join(f"{name}={intervall if intervall else 0}" for name, intervall in neu.items())
        if set_arg:
            mc.cmd_set(root, set_arg)
        entfallen = sorted(set(alt) - set(neu))
        if entfallen:
            data, path = mc.load_status_raw(root)
            if isinstance(data, dict) and isinstance(data.get("aufgaben"), dict):
                for name in entfallen:
                    data["aufgaben"].pop(name, None)
                mc.save_status(root, data, path)
            lines.append(f"Abgeschaltet (nicht mehr in AI-CONFIG.md): {entfallen}")
        ref_holder["executed"].add("Wartungsaufgaben")
        return lines

    if kind == "wartungsberichte":
        if diff["new"] == "docs":
            neu_angelegt = cp.setup_docs_maintenance_reports(root)
            lines.append("docs/maintenance/README.md " + ("neu angelegt." if neu_angelegt else "bereits vorhanden."))
        else:
            lines.append("Keine Datei-Aenderung (docs/maintenance/ bleibt liegen, falls vorhanden).")
        ref_holder["executed"].add("Wartungsberichte")
        return lines

    if kind == "code_opt_add":
        ref, hinweis, fehler = _get_ref(ref_holder, tu, root)
        if hinweis:
            lines.append(hinweis)
        if fehler:
            lines.append(f"Code-Optimierung nachladen: {fehler}")
            return lines
        geholt, vorhanden, fehl, offen = fetch_paths(tu, root, ref, cp.OPTIMIZER_REMOVE_PATHS, values)
        lines.append(f"optimizer.md: {'geholt' if geholt else 'bereits vorhanden' if vorhanden else 'FEHLER'}")
        if fehl:
            lines.append(f"  FEHLER: {fehl}")
        ref_holder["executed"].add("Code-Optimierung")
        return lines

    if kind == "code_opt_remove":
        if not yes:
            lines.append("(Vorschau) wuerde optimizer.md entfernen.")
            return lines
        removed = cp.remove_optimizer_files(root)
        lines.append(f"Entfernt: {removed or '(nichts gefunden)'}")
        ref_holder["executed"].add("Code-Optimierung")
        return lines

    if kind == "code_opt_level":
        lines.append("Nur Stand uebernommen - Agentenverhalten liest AI-CONFIG.md direkt, keine Datei geaendert.")
        ref_holder["executed"].add("Code-Optimierung")
        return lines

    lines.append(f"Unbekannte Diff-Art '{kind}' - uebersprungen.")
    return lines


def _set_partial(ref_holder: dict, key: str, value) -> None:
    """Merkt sich fuer `key` den tatsaechlich erreichten Stand (statt des vollen Zielwerts aus `current`) -
    noetig, weil add/remove-Diffs (Coding-Guidelines, KI-Werkzeuge) sich denselben Schluessel/marker teilen
    und in einem Lauf nur einer von beiden ausgefuehrt werden kann (der andere braucht --yes)."""
    ref_holder.setdefault("applied_values", {})[key] = sorted(value)


def _get_partial(ref_holder: dict, key: str, base_default: list) -> set:
    return set(ref_holder.get("applied_values", {}).get(key, base_default))


def _get_ref(ref_holder: dict, tu, root: Path):
    """Ermittelt den Template-Ref hoechstens einmal je Lauf (mehrere Diffs teilen sich Fetch/Verify)."""
    if "ref" not in ref_holder:
        ref_holder["ref"], ref_holder["hinweis"], ref_holder["fehler"] = resolve_template_ref(root, tu)
    hinweis = ref_holder.pop("hinweis", None)  # nur einmal ausgeben
    return ref_holder["ref"], hinweis, ref_holder["fehler"]


# ---------------------------------------------------------------------------
# Kommandos
# ---------------------------------------------------------------------------


def _print_unbekannt(root: Path) -> None:
    print(
        "applied_config: unbekannt - dieses Projekt wurde vor sync-config.py angelegt (oder AI-CONFIG.md\n"
        "  wurde von Hand auf das neue Format umgestellt). Es wird nichts automatisch umgesetzt.\n"
        "  Entspricht der aktuelle Datei-/Repo-Stand bereits AI-CONFIG.md? Dann:\n"
        "    python .claude/scripts/sync-config.py --adopt\n"
        "  Sonst zuerst von Hand nachziehen (siehe AI-CONFIG.md), danach --adopt."
    )


def cmd_check(root: Path, mods: dict, quiet: bool) -> int:
    cp, tu = mods["cp"], mods["tu"]
    tpl_cfg, _path = tu.load_template_json(root)
    if tpl_cfg.get("is_template"):
        # Der Template-Checkout selbst hat kein Projekt, das synchron sein muesste - AI-CONFIG.md ist hier
        # Vorlage, nicht Steuerung. Ohne diese Ausnahme meldete der SessionStart-Hook bei jeder Sitzung an
        # der Vorlage "applied_config unbekannt", und zwar dauerhaft, weil es nie ein --adopt geben wird.
        if not quiet:
            print("Template-Checkout (is_template) - hier gibt es nichts abzugleichen, AI-CONFIG.md ist Vorlage.")
        return 0
    old = tpl_cfg.get("applied_config")
    if not isinstance(old, dict):
        if quiet:
            print("sync-config: applied_config unbekannt - `python .claude/scripts/sync-config.py --check` fuer Details.")
            return 3
        _print_unbekannt(root)
        return 3

    cfg, values, current, fehler, hinweise = compute_current(cp, root)
    if fehler:
        print("Fehler: AI-CONFIG.md nicht eindeutig:", file=sys.stderr)
        for f in fehler:
            print(f"  - {f}", file=sys.stderr)
        return 2

    diffs = compute_diffs(old, current)
    if not diffs:
        if not quiet:
            for h in hinweise:
                print("Hinweis: " + h)
            print("sync-config: AI-CONFIG.md und Repo-Stand sind synchron.")
        return 0

    if quiet:
        auto = sum(1 for d in diffs if d["kategorie"] == "automatisch")
        zusage = len(diffs) - auto
        print(f"sync-config: {len(diffs)} Aenderung(en) offen ({auto} automatisch, {zusage} braucht --yes) - "
              "`python .claude/scripts/sync-config.py --check` fuer Details.")
        return 3

    for h in hinweise:
        print("Hinweis: " + h)
    for d in diffs:
        flag = "automatisch" if d["kategorie"] == "automatisch" else "braucht --yes"
        print(f"{d['key']}: {d['old']!r} -> {d['new']!r} — {d['wirkung']} [{flag}]")
    auto = sum(1 for d in diffs if d["kategorie"] == "automatisch")
    print(f"\n{len(diffs)} Aenderung(en) offen ({auto} automatisch, {len(diffs) - auto} braucht --yes).")
    return 3


def cmd_apply(root: Path, mods: dict, yes: bool) -> int:
    cp, tu = mods["cp"], mods["tu"]
    tpl_cfg, path = tu.load_template_json(root)
    old = tpl_cfg.get("applied_config")
    if not isinstance(old, dict):
        _print_unbekannt(root)
        return 3

    cfg, values, current, fehler, hinweise = compute_current(cp, root)
    if fehler:
        print("Fehler: --apply abgebrochen, AI-CONFIG.md nicht eindeutig:", file=sys.stderr)
        for f in fehler:
            print(f"  - {f}", file=sys.stderr)
        return 2

    diffs = compute_diffs(old, current)
    for h in hinweise:
        print("Hinweis: " + h)
    if not diffs:
        print("sync-config: nichts zu tun - AI-CONFIG.md und Repo-Stand sind schon synchron.")
        return 0

    ref_holder = {"executed": set()}
    offen_ohne_yes = []
    versucht = []
    for d in diffs:
        if d["kategorie"] == "zusage" and not yes:
            offen_ohne_yes.append(d)
            continue
        versucht.append(d)
        print(f"== {d['key']}: {d['wirkung']} ==")
        for line in execute_diff(mods, root, cfg, values, current, d, yes, ref_holder):
            print("  " + line)

    fehlgeschlagen = [d for d in versucht if not all(m in ref_holder["executed"] for m in d["marker"])]

    if offen_ohne_yes:
        print("\nOhne --yes uebersprungen (loeschen/projektweite Ersetzung, braucht Zusage):")
        for d in offen_ohne_yes:
            print(f"  {d['key']}: {d['old']!r} -> {d['new']!r} — {d['wirkung']}")
    if fehlgeschlagen:
        print("\nNicht abgeschlossen (siehe Meldungen oben, applied_config bleibt fuer diese Schluessel unveraendert):")
        for d in fehlgeschlagen:
            print(f"  {d['key']}: {d['old']!r} -> {d['new']!r}")

    neu_applied = dict(old)
    applied_values = ref_holder.get("applied_values", {})
    for key in ref_holder["executed"]:
        neu_applied[key] = applied_values.get(key, current.get(key))
    cp.write_template_json_values(root, values, neu_applied)
    print(f"\napplied_config aktualisiert ({len(ref_holder['executed'])} Schluessel).")
    return 3 if (offen_ohne_yes or fehlgeschlagen) else 0


def cmd_adopt(root: Path, mods: dict) -> int:
    cp = mods["cp"]
    cfg, values, current, fehler, hinweise = compute_current(cp, root)
    if fehler:
        print("Fehler: --adopt abgebrochen, AI-CONFIG.md nicht eindeutig:", file=sys.stderr)
        for f in fehler:
            print(f"  - {f}", file=sys.stderr)
        return 2
    for h in hinweise:
        print("Hinweis: " + h)
    cp.write_template_json_values(root, values, current)
    print("applied_config uebernommen - naechster Abgleich vergleicht ab jetzt gegen diesen Stand.")
    return 0


def cmd_status(root: Path, mods: dict) -> int:
    tu = mods["tu"]
    tpl_cfg, _path = tu.load_template_json(root)
    old = tpl_cfg.get("applied_config")
    stand = tpl_cfg.get("applied_config_stand")
    if not isinstance(old, dict):
        if tpl_cfg.get("is_template"):
            print("Template-Checkout (is_template) - kein applied_config, hier gibt es nichts abzugleichen.")
        else:
            print("applied_config: unbekannt (Projekt vor sync-config.py angelegt, oder noch nie --adopt/--apply gelaufen).")
        return 0
    print(f"applied_config (Stand: {stand or 'unbekannt'}):")
    for key, val in old.items():
        print(f"  {key}: {val!r}")
    return 0


# ---------------------------------------------------------------------------
# main / Argument-Parsing
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sync-config.py",
        description="AI-CONFIG.md laufend gegen den Repo-Stand abgleichen (Ergaenzungen automatisch, "
        "Loeschen/projektweite Ersetzung nur mit --yes).",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="Nur anzeigen, was offen ist (Default)")
    group.add_argument("--apply", action="store_true", help="Automatische Aenderungen umsetzen")
    group.add_argument("--adopt", action="store_true", help="Aktuellen Stand als 'umgesetzt' uebernehmen")
    group.add_argument("--status", action="store_true", help="Zuletzt umgesetzten Stand anzeigen")
    parser.add_argument("--yes", action="store_true", help="Zusammen mit --apply: auch zusagepflichtige Aenderungen umsetzen")
    parser.add_argument("--quiet", action="store_true", help="Zusammen mit --check: nur bei offenen Punkten eine Kurzzeile (SessionStart-Hook)")
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

    mods = load_modules(root)
    if mods["cp"] is None or mods["tu"] is None:
        print("Fehler: create-project.py/update-template.py fehlen unter .claude/scripts/ - kann nicht abgleichen.",
              file=sys.stderr)
        return 2

    if args.apply:
        return cmd_apply(root, mods, args.yes)
    if args.adopt:
        return cmd_adopt(root, mods)
    if args.status:
        return cmd_status(root, mods)
    return cmd_check(root, mods, args.quiet)


def main() -> int:
    try:
        return _run(sys.argv[1:])
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 - darf nie mit Traceback nach aussen dringen
        print(f"sync-config: Fehler: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
