#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Weg 1 ("Neues Projekt") aus README.md/AGENTS.md umsetzen - CONFIG.md (Formular im Repo-Root)
#        einlesen, Platzhalter (`{{PROJEKTNAME}}` usw.) ersetzen, nicht genutzte Werkzeug-Dateien entfernen,
#        Logging-Schalter in AGENTS.md setzen und die eingesetzten Werte in `.claude/template.json`
#        festhalten. Ergaenzt/ersetzt die frueheren Skills `adapt-template` + `new-idea`. Reine Python-
#        Stdlib, kein Paket noetig. Siehe `.claude/skills/new-project/SKILL.md`,
#        `docs/ai/checklists.md` § "Neues Projekt".
#
# Aufruf:
#   python .claude/scripts/new-project.py --dry-run
#       (Default, auch ohne Argument) CONFIG.md parsen (fehlt sie oder ist sie leer -> Defaults), Plan
#       ausgeben: Werte je Platzhalter, zu entfernende Dateien, Logging-Schalter, offene Platzhalter.
#   python .claude/scripts/new-project.py --apply
#       Platzhalter ersetzen (ausser .git, CONFIG.md, docs/ai/checklists.md,
#       .claude/skills/new-project/SKILL.md und den beiden Scripten new-project.py/template-update.py -
#       dort sind sie absichtlich als Beispiel sichtbar), nicht genannte Werkzeug-Dateien entfernen (nur
#       wenn KI-Werkzeuge gesetzt ist), AI_LOG/AI_LOG_LEVEL in AGENTS.md setzen, Werte in
#       .claude/template.json schreiben (direkt) und - falls ein Git-Remote "template" existiert und noch
#       kein base_commit gesetzt ist - `template-update.py --init` per Subprocess aufrufen.
#       Bricht vor jeder Aenderung ab (Exit 2), wenn KI-Werkzeuge einen unbekannten Namen enthaelt - sonst
#       wuerde ein Tippfehler ("Claude" statt "Claude Code") die Dateien des gemeinten Werkzeugs loeschen.
#       CONFIG.md bleibt bestehen.
#   python .claude/scripts/new-project.py --finish
#       Prueft, dass docs/project/project_description.md ausgefuellt wurde (keine Vorlagenzeile mehr) und
#       docs/ai/ledger.md einen echten Eintrag hat, loescht danach CONFIG.md. Idempotent: fehlt CONFIG.md
#       bereits, Exit 0 mit Hinweis (nichts zu tun).
#
# Exit-Codes: 0 = ok, 2 = Vorbedingungs-/Parsefehler. Ein Fehler dieses Scripts darf nie mit Traceback nach
# aussen dringen: main() laeuft komplett in try/except, Fehlermeldungen auf stderr.

import importlib.util
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

CONFIG_REL = "CONFIG.md"
EXCLUDED_FROM_REPLACE = {
    "CONFIG.md",
    # Diese beiden Scripte erklaeren die Platzhalter-Mechanik in ihren Kopfkommentaren ("ersetzt
    # `{{PROJEKTNAME}}` usw.") - wird dort ersetzt, steht danach Unsinn im Kommentar. Gleiche Liste wie
    # `no_replace` in `.claude/template.json`.
    ".claude/scripts/new-project.py",
    ".claude/scripts/template-update.py",
}

KEY_MAP = {
    "Projektname": "projektname",
    "Auftraggeber": "auftraggeber",
    "Orchestrator": "orchestrator",
    "Sprache": "sprache",
    "KI-Werkzeuge": "ki_werkzeuge",
    "Stack": "stack",
    "Logging": "logging",
    "Logging-Tiefe": "logging_tiefe",
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
    "chatgpt/codex": "ChatGPT/Codex",
    "chatgpt": "ChatGPT/Codex",
    "codex": "ChatGPT/Codex",
    "ollama": "Ollama",
}

# Nur Werkzeuge mit eigenen Dateien im Repo koennen entfernt werden; ChatGPT/Codex und Ollama haben keine.
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
    """Laedt template-update.py als Modul (gleicher Ordner) - eine gemeinsame Quelle fuer die Struktur von
    .claude/template.json statt sie hier zu duplizieren."""
    tu_path = Path(__file__).resolve().parent / "template-update.py"
    spec = importlib.util.spec_from_file_location("_template_update", tu_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# CONFIG.md parsen
# ---------------------------------------------------------------------------


def _strip_trailing_comment(value: str) -> str:
    """Schneidet an der ersten oeffnenden Klammer ab (Erklaerungskommentar, ggf. ueber Zeilenende hinaus
    unbalanciert). Bleibt danach nichts uebrig, ist der Wert nicht gesetzt (Nutzer hat die Vorlagenzeile
    unveraendert gelassen)."""
    return value.split("(", 1)[0].strip()


def parse_config(text: str) -> dict:
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
        m = re.match(r"^([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9\- ]*):\s?(.*)$", line)
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
        "AUFTRAGGEBER": cfg.get("auftraggeber"),
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


def tools_to_remove(cfg: dict):
    keep = set(cfg.get("ki_werkzeuge_liste") or [])
    if not keep:
        return []  # leer = alle behalten, nichts entfernen
    return [t for t in REMOVABLE_TOOLS if t not in keep]


# ---------------------------------------------------------------------------
# Dateiwalk fuer die Platzhalter-Ersetzung
# ---------------------------------------------------------------------------


def _iter_text_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for fname in filenames:
            fp = Path(dirpath) / fname
            rel = fp.relative_to(root).as_posix()
            if rel in EXCLUDED_FROM_REPLACE:
                continue
            yield fp, rel


def replace_placeholders(root: Path, values: dict):
    """Ersetzt {{KEY}} in allen Textdateien (ausser den 3 Ausnahmen). Gibt (geaenderte_dateien,
    verbleibende_platzhalter) zurueck - Letzteres als Liste 'Datei:Zeile' (max 20)."""
    changed = []
    remaining = []
    for fp, rel in _iter_text_files(root):
        try:
            content = fp.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        new_content = content
        for key, val in values.items():
            if val is None:
                continue
            new_content = new_content.replace("{{" + key + "}}", str(val))
        if new_content != content:
            try:
                fp.write_text(new_content, encoding="utf-8", newline="\n")
                changed.append(rel)
            except OSError:
                continue
        # .py-Quelldateien (Scripte) enthalten "{{" nur als Code-Literal (z.B. String-Konkatenation), nie als
        # echten, auszufuellenden Platzhalter - aus der "offen"-Meldung raushalten, um sie lesbar zu halten.
        if fp.suffix == ".py":
            continue
        if "{{" in new_content and len(remaining) < 20:
            for i, line in enumerate(new_content.splitlines(), start=1):
                if "{{" in line:
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
                text = doc_path.read_text(encoding="utf-8")
            except OSError:
                continue
            new_text = text
            for tool in remove_list:
                row_key = TOOL_ROW_KEY.get(tool)
                if row_key:
                    new_text = _remove_table_row(new_text, row_key)
            if new_text != text:
                doc_path.write_text(new_text, encoding="utf-8", newline="\n")

    return removed


# ---------------------------------------------------------------------------
# AGENTS.md Logging-Schalter
# ---------------------------------------------------------------------------


def set_logging_switch(root: Path, logging_val: str, logging_tiefe: str) -> bool:
    agents_path = root / "AGENTS.md"
    if not agents_path.exists():
        return False
    try:
        text = agents_path.read_text(encoding="utf-8")
    except OSError:
        return False
    new_text = re.sub(r"(?m)^(AI_LOG)=\S+", r"\1=" + logging_val, text)
    new_text = re.sub(r"(?m)^(AI_LOG_LEVEL)=\S+", r"\1=" + logging_tiefe, new_text)
    if new_text != text:
        agents_path.write_text(new_text, encoding="utf-8", newline="\n")
        return True
    return False


# ---------------------------------------------------------------------------
# template.json
# ---------------------------------------------------------------------------


def write_template_json_values(root: Path, values: dict):
    tu = _load_template_update_module()
    cfg, path = tu.load_template_json(root)
    tu_values = cfg.setdefault("values", {})
    for key in PLACEHOLDER_KEYS:
        val = values.get(key)
        if val is not None:
            tu_values[key] = val
    tu.save_template_json(root, cfg, path)
    return cfg


def maybe_init_template_update(root: Path) -> str:
    """Ruft template-update.py --init per Subprocess auf, wenn ein Git-Remote 'template' existiert.
    Gibt eine kurze Statuszeile fuer die Zusammenfassung zurueck."""
    tu = _load_template_update_module()
    cfg_tu, _ = tu.load_template_json(root)
    if cfg_tu.get("base_commit"):
        return "base_commit bereits gesetzt (consume-template.py/--init) - --init uebersprungen."
    res = run_git(root, ["remote"])
    remotes = res.stdout.split() if res.returncode == 0 else []
    if "template" not in remotes:
        return "kein Remote 'template' - base_commit nicht gesetzt."
    script = Path(__file__).resolve().parent / "template-update.py"
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
        return f"template-update.py --init fehlgeschlagen: {e}"
    if res_init.returncode != 0:
        return f"template-update.py --init: {res_init.stderr.strip() or res_init.stdout.strip()}"
    return "template-update.py --init ok (base_commit gesetzt)."


# ---------------------------------------------------------------------------
# --dry-run
# ---------------------------------------------------------------------------


def cmd_dry_run(root: Path) -> int:
    cfg = load_config(root)
    values = compute_values(cfg)
    logging_val, logging_tiefe = logging_settings(cfg)
    remove_list = tools_to_remove(cfg)

    lines = ["new-project.py --dry-run", ""]
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

    warnungen = config_warnungen(cfg)
    unbekannt = unbekannte_werkzeuge(cfg)
    if warnungen or unbekannt:
        lines.append("")
        lines.append("Hinweise zu CONFIG.md:")
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

    # Vor jeder Aenderung: ein Tippfehler in KI-Werkzeuge darf nicht dazu fuehren, dass das betroffene
    # Werkzeug als "nicht genutzt" gilt und seine Dateien geloescht werden.
    unbekannt = unbekannte_werkzeuge(cfg)
    if unbekannt:
        print("Fehler: --apply abgebrochen, CONFIG.md § KI-Werkzeuge nicht eindeutig:", file=sys.stderr)
        for name in unbekannt:
            print(f"  - unbekannter Name: \"{name}\"", file=sys.stderr)
        print(f"  Erlaubt sind: {', '.join(sorted(set(TOOL_CANON.values())))} "
              "(leer = alle behalten, nichts wird entfernt).", file=sys.stderr)
        return 2

    remove_list = tools_to_remove(cfg)

    changed, remaining = replace_placeholders(root, values)
    removed_files = remove_tool_files(root, remove_list)
    logging_changed = set_logging_switch(root, logging_val, logging_tiefe)
    write_template_json_values(root, values)
    init_status = maybe_init_template_update(root)

    lines = ["new-project.py --apply", ""]
    for w in config_warnungen(cfg):
        lines.append(f"Hinweis: {w}")
    if config_warnungen(cfg):
        lines.append("")
    lines.append(f"Gesetzte Werte: {', '.join(k + '=' + str(v) for k, v in values.items() if v is not None)}")
    lines.append(f"Dateien mit ersetzten Platzhaltern: {len(changed)}")
    lines.append(f"Entfernte Werkzeug-Dateien: {', '.join(removed_files) if removed_files else '(keine)'}")
    lines.append(f"Logging: AI_LOG={logging_val}, AI_LOG_LEVEL={logging_tiefe}" + (" (geschrieben)" if logging_changed else " (unveraendert)"))
    lines.append(f"template.json: {init_status}")

    lines.append("")
    if remaining:
        lines.append(f"Offene Platzhalter (max. 20 gezeigt):")
        for entry in remaining:
            lines.append(f"  {entry}")
    else:
        lines.append("Offene Platzhalter: keine (ausser den bekannten Fundstellen in checklists.md/new-project SKILL.md).")

    lines.append("")
    lines.append("CONFIG-Abschnitte (Hinweis fuer die Doku-Befuellung durch den Skill):")
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


def cmd_finish(root: Path) -> int:
    config_path = root / CONFIG_REL
    if not config_path.exists():
        print(f"{CONFIG_REL} bereits entfernt - nichts zu tun.")
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

    try:
        config_path.unlink()
    except OSError as e:
        print(f"Fehler: {CONFIG_REL} konnte nicht geloescht werden: {e}", file=sys.stderr)
        return 2

    print(f"{CONFIG_REL} entfernt - Projekt-Setup abgeschlossen.")
    return 0


# ---------------------------------------------------------------------------
# main / Argument-Parsing
# ---------------------------------------------------------------------------


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="new-project.py",
        description="CONFIG.md einlesen und ein neues Projekt aus dem Template zuschneiden (Weg 1).",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--dry-run", action="store_true", help="Plan anzeigen, nichts aendern (Default)")
    group.add_argument("--apply", action="store_true", help="Platzhalter ersetzen, Werkzeug-Dateien entfernen, Werte speichern")
    group.add_argument("--finish", action="store_true", help="Vorbedingungen pruefen, CONFIG.md entfernen")
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

    if args.apply:
        return cmd_apply(root)
    if args.finish:
        return cmd_finish(root)
    return cmd_dry_run(root)


def main() -> int:
    try:
        return _run(sys.argv[1:])
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 - darf nie mit Traceback nach aussen dringen
        print(f"new-project: Fehler: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
