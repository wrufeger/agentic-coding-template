#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Teile der Agentic-Coding-Grundausstattung nach `~/.claude/` legen, damit sie in ALLEN Projekten
#        dieses Rechners gelten - auch in Projekten ohne dieses Template (Claude Code haengt `~/.claude/
#        CLAUDE.md` an die projekteigene CLAUDE.md an, `~/.claude/agents/` und `~/.claude/skills/` gelten
#        automatisch mit, Projektfassung gewinnt bei gleichem Namen). Siehe README.md § "Global vs.
#        projektgebunden", CLAUDE.md § 5 "Memory". Reine Python-Stdlib, kein Paket noetig.
#
# Warum nur ein Teil global geht (Auswahl, siehe auch AI-CONFIG.md § "Globale Ablage"):
#   - Agenten (`.claude/agents/*.md`, ALLE acht) - Rollen wie "Builder" oder "Reviewer" sind an sich
#     projektunabhaengig; welche Datei ein einzelner Agent referenziert (docs/ai/, docs/project/, eigene
#     Scripte) ist Sache des jeweiligen Projekts und wird unten je Datei gemeldet, nicht ausgefiltert.
#   - Skills: NUR `/commit` und `/audit-docs`. Die uebrigen (`create-project`, `apply-template`,
#     `update-template`, `run-maintenance`) rufen Scripte auf, die es ausserhalb eines Template-Checkouts/
#     -Projekts gar nicht gibt (`create-project.py`, `apply-template.py`, `update-template.py`,
#     `maintenance-check.py`) - global angeboten waeren sie nur totes Menue.
#   - Ein Board, eine Aufgabenliste oder Checklisten fuer alle Projekte gleichzeitig ergeben keinen Sinn
#     (`docs/ai/`, `docs/project/` bleiben deshalb projektgebunden) - Projektverbindlichkeiten (CI, Team,
#     Cloud-Sessions) muessen ohnehin im Repo liegen, weil die genannten Umgebungen `~/.claude/` nicht sehen.
#   - "rules": statt der vollen `CLAUDE.md` (die auf projekteigene Agenten/Skill-Pfade zeigt) ein kurzer,
#     selbst verfasster Regelauszug (Rollen, "fertig nur mit Beleg", Modell-/Kostenlogik) - Inhalt in
#     GLOBAL_CLAUDE_MD_CONTENT unten, keine Kopie einer Repo-Datei.
#
# Platzhalter: Agenten-/Skill-Dateien im Template enthalten `{{ORCHESTRATOR}}`/`{{AUFTRAGGEBER}}`/
#   `{{PROJEKTNAME}}`. Quelle fuer die Werte ist IMMER das lokale `.claude/template.json` dieses Checkouts/
#   Projekts (Feld `values`): laeuft dieses Script in einem bereits angelegten Projekt, stehen dort die
#   echten Werte (oder - wenn ein Wert bewusst leer gelassen wurde - weiterhin `null`); im Template-Checkout
#   selbst sind alle Werte `null`. Ein `null`-Wert wird global durch einen neutralen Begriff ersetzt
#   (NEUTRAL_FALLBACK), NIE durch den unaufgeloesten Platzhalter - nach jedem --apply steht in keiner
#   geschriebenen Datei mehr "{{".
#
# Aufruf:
#   python .claude/scripts/install-global.py --plan (Default)
#       Zeigt je Datei Quelle -> Ziel, ob das Ziel schon existiert (wuerde ohne --force uebersprungen) und
#       welche projektgebundenen Verweise (docs/ai/, docs/project/, .claude/scripts/*, AI-CONFIG.md, ...) die
#       Datei enthaelt. Schreibt nichts. Exit 0.
#   python .claude/scripts/install-global.py --apply [--force]
#       Kopiert/schreibt. Ohne --force wird eine vorhandene Zieldatei NIE ueberschrieben (nur gemeldet und
#       uebersprungen). Mit --force wird vorher eine Sicherung <name>.bak angelegt (eine bereits vorhandene
#       Sicherung wird dabei nicht ihrerseits ueberschrieben - dann nur Hinweis, das Ueberschreiben des
#       Ziels erfolgt trotzdem). Schreibt danach `.template-global.json` im Zielverzeichnis (Herkunft: Datei-
#       Hashes, Template-Commit, Datum) fuer --status/--remove. Exit 0, Exit 2 bei Vorbedingungsfehlern (z.B.
#       AI-CONFIG.md steht auf "fragen" und --parts wurde nicht explizit angegeben - das entscheidet der
#       Skill nach Rueckfrage im Chat, nicht dieses Script).
#   python .claude/scripts/install-global.py --status
#       Was liegt global, aus welchem Template-Commit/Datum, je Datei unveraendert oder von Hand geaendert
#       (Hash-Vergleich mit dem beim Installieren gemerkten Wert). Exit 0.
#   python .claude/scripts/install-global.py --remove
#       Entfernt NUR Dateien, die laut `.template-global.json` von diesem Script stammen und seitdem
#       unveraendert sind (Hash-Vergleich). Von Hand geaenderte Dateien werden gemeldet, nicht geloescht.
#       Exit 0.
#   --parts agents,skills,rules
#       Auswahl der Teile. Ohne Angabe: aus AI-CONFIG.md -> "Globale Ablage" (nein |
#       agenten | agenten+skills | alles | fragen). "nein"/fehlend -> nichts zu tun (Exit 0, kein Fehler).
#       "fragen" ohne explizites --parts: bei --plan werden alle drei Teile als Vorschau gezeigt (mit
#       Hinweis, dass die Auswahl im Chat noch offen ist); bei --apply Exit 2 (siehe oben).
#   --home-dir PFAD  |  Env CLAUDE_GLOBAL_DIR
#       Zielverzeichnis statt `~/.claude` (fuer Tests - NIE ungewollt gegen das echte Nutzerverzeichnis
#       laufen lassen). --home-dir hat Vorrang vor der Umgebungsvariable.
#
# Exit-Codes: 0 = ok, 2 = Vorbedingungsfehler (unbekannter --parts-Wert, "fragen" ohne --parts bei --apply,
# Zielverzeichnis nicht anlegbar). Ein Fehler dieses Scripts darf nie mit Traceback nach aussen dringen:
# main() laeuft komplett in try/except, Fehlermeldungen auf stderr.

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

STATE_FILE_NAME = ".template-global.json"

PLACEHOLDER_KEYS = ["PROJEKTNAME", "AUFTRAGGEBER", "ORCHESTRATOR"]
NEUTRAL_FALLBACK = {
    "PROJEKTNAME": "das Projekt",
    "AUFTRAGGEBER": "der Auftraggeber",
    "ORCHESTRATOR": "der Orchestrator",
}

# Nur diese beiden Skills sind ohne die Scripte des Templates sinnvoll (siehe Kopfkommentar).
SKILL_ITEMS = ["commit", "audit-docs"]

REFERENCE_MARKERS = [
    "docs/ai/",
    "docs/project/",
    ".claude/scripts/",
    ".claude/maintenance",
    "AI-CONFIG.md",
]

GLOBAL_CLAUDE_MD_CONTENT = """# Persönlicher Regelauszug (global, alle Projekte)

Gilt zusätzlich zu jeder projekteigenen `CLAUDE.md` (Claude Code hängt beide aneinander, Nutzer-Ebene
zuerst, Projekt danach — bei Widerspruch gewinnt die Projektfassung). Enthält nur, was projektunabhängig
gilt; Board, Aufgaben, Fragen und Checklisten bleiben bewusst im jeweiligen Repo — ein gemeinsamer Stand für
alle Projekte ergibt keinen Sinn, und Projektverbindlichkeiten müssen ohnehin im Repo liegen, weil Team, CI
und Cloud-Sessions dieses Nutzerverzeichnis nicht sehen.

## Rollen

- Ein Assistent orchestriert (plant, prüft, entscheidet, committet), Sub-Agenten/Worker arbeiten umrissene
  Aufträge ab, schreiben nie in projektgebundene Arbeitsdateien und committen nie selbst.
- Rückgaben eines Workers vor der Übernahme stichprobenartig gegen den echten Stand prüfen, nie blind
  übernehmen.
- „Fertig" gilt nur mit einem Beleg (Testlauf, Commit-Hash, Aufruf von außen) — keine Erfolgsmeldung ohne
  Beleg.
- Scheitert ein Worker zweimal an derselben Aufgabe, keinen dritten Versuch mit demselben Auftrag starten —
  Auftrag schärfen oder mit vollem Kontext eskalieren.

## Modell-/Kostenlogik

Ein starkes/teures Modell orchestriert (plant, prüft, entscheidet), günstigere/schnellere Modelle übernehmen
klar umrissene Teilaufgaben. Unabhängige Teilaufgaben parallel starten, nicht nacheinander.

## Herkunft

Installiert von `install-global.py` aus dem Template „Agentic Coding" — Stand/Herkunft in
`~/.claude/.template-global.json`. Aus demselben Grund liegen dort auch Rollen (`~/.claude/agents/`) und die
Skills `/commit`+`/audit-docs` (`~/.claude/skills/`); was diese jeweils projektintern voraussetzen (z. B.
`docs/ai/`), gilt nur in Projekten, die selbst mit dem Template arbeiten.
"""


# ---------------------------------------------------------------------------
# Grundlagen
# ---------------------------------------------------------------------------


def _own_root() -> Path:
    # Wie apply-template.py: bewusst nicht ueber CLAUDE_PROJECT_DIR, sondern relativ zu diesem Scriptpfad -
    # das ist immer der Checkout/Projekt, aus dem heraus gerade installiert wird.
    return Path(__file__).resolve().parents[2]


def _load_template_update_module(own_root: Path):
    tu_path = own_root / ".claude" / "scripts" / "update-template.py"
    spec = importlib.util.spec_from_file_location("_install_global_tu", tu_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def resolve_home_dir(args) -> Path:
    if args.home_dir:
        return Path(args.home_dir).expanduser().resolve()
    import os

    env = os.environ.get("CLAUDE_GLOBAL_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".claude"


def _strip_trailing_comment(value: str) -> str:
    return value.split("(", 1)[0].strip()


def read_globale_ablage(own_root: Path) -> str:
    """Liest AI-CONFIG.md -> "Globale Ablage" (siehe create-project.py:parse_config fuer das
    allgemeine Format). Fehlt die Datei/der Schluessel: "nein" (Default)."""
    path = own_root / "AI-CONFIG.md"
    if not path.exists():
        return "nein"
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return "nein"
    # Zwei Formate muessen gehen: die Tabellenzeile "| Globale Ablage | <wert> | ... |" (aktuell) und die
    # aeltere Zeile "Globale Ablage: <wert> (kommentar)" - ein Projekt, das vor der Umstellung angelegt
    # wurde, hat die alte Fassung, und niemand wird zum Wechsel gezwungen.
    m = re.search(r"^[ \t]*\|\s*`?Globale Ablage`?\s*\|([^|]*)\|", text, re.MULTILINE | re.IGNORECASE)
    if m:
        return m.group(1).strip().strip("`").lower() or "nein"
    m = re.search(r"^[ \t]*Globale Ablage:\s?(.*)$", text, re.MULTILINE | re.IGNORECASE)
    if not m:
        return "nein"
    val = _strip_trailing_comment(m.group(1)).lower()
    return val or "nein"


PARTS_FROM_ABLAGE = {
    "nein": [],
    "agenten": ["agents"],
    "agenten+skills": ["agents", "skills"],
    "alles": ["agents", "skills", "rules"],
}


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    return raw.decode("utf-8").replace("\r\n", "\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def substitute_placeholders(text: str, values: dict) -> str:
    for key in PLACEHOLDER_KEYS:
        val = values.get(key) or NEUTRAL_FALLBACK[key]
        text = text.replace("{{" + key + "}}", val)
    return text


def find_reference_markers(text: str):
    return [m for m in REFERENCE_MARKERS if m in text]


# ---------------------------------------------------------------------------
# Kandidaten (Quelle -> Ziel-relativpfad unter dem Home-Verzeichnis)
# ---------------------------------------------------------------------------


# Agenten, die global NICHT angeboten werden: Sie arbeiten nach Dateien, die nur ein Projekt aus diesem
# Template hat. Dieselbe Begruendung wie bei den uebersprungenen Skills (siehe SKILL_ITEMS) - der
# maintenance-orchestrator laeuft nach `.claude/maintenance/status.json`, ohne die Datei hat er keinen
# Auftrag, und sein Skill `/run-maintenance` wird global ohnehin nicht mitinstalliert.
AGENTS_SKIP = {"maintenance-orchestrator"}


def _current_head(own_root: Path):
    """Kurzer Commit-Hash des Repos, aus dem installiert wird - None, wenn kein Git verfuegbar ist."""
    try:
        res = subprocess.run(
            ["git", "-C", str(own_root), "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return res.stdout.strip() or None if res.returncode == 0 else None


def _candidates(own_root: Path, parts):
    """Liefert Liste von dicts {part, src(Path|None), rel_dest(str), generated_text(str|None)}. src=None
    bedeutet: Inhalt wird generiert (GLOBAL_CLAUDE_MD_CONTENT), nicht aus einer Repo-Datei kopiert."""
    items = []
    if "agents" in parts:
        for src in sorted((own_root / ".claude" / "agents").glob("*.md")):
            if src.stem in AGENTS_SKIP:
                continue
            items.append({"part": "agents", "src": src, "rel_dest": f"agents/{src.name}", "generated_text": None})
    if "skills" in parts:
        for name in SKILL_ITEMS:
            src = own_root / ".claude" / "skills" / name / "SKILL.md"
            if src.exists():
                items.append(
                    {"part": "skills", "src": src, "rel_dest": f"skills/{name}/SKILL.md", "generated_text": None}
                )
    if "rules" in parts:
        items.append({"part": "rules", "src": None, "rel_dest": "CLAUDE.md", "generated_text": GLOBAL_CLAUDE_MD_CONTENT})
    return items


def _rendered_content(item: dict, values: dict) -> str:
    if item["generated_text"] is not None:
        return item["generated_text"]
    return substitute_placeholders(_read_text(item["src"]), values)


# ---------------------------------------------------------------------------
# Zustand (.template-global.json im Home-Verzeichnis)
# ---------------------------------------------------------------------------


def load_state(home_dir: Path) -> dict:
    path = home_dir / STATE_FILE_NAME
    if not path.exists():
        return {"files": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"files": {}}
        if not isinstance(data.get("files"), dict):
            data["files"] = {}
        return data
    except (OSError, ValueError):
        return {"files": {}}


def save_state(home_dir: Path, state: dict) -> None:
    path = home_dir / STATE_FILE_NAME
    home_dir.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(state, f, indent=2, ensure_ascii=False, sort_keys=True)
        f.write("\n")


# ---------------------------------------------------------------------------
# --plan
# ---------------------------------------------------------------------------


def cmd_plan(own_root: Path, home_dir: Path, parts, ablage_hint: str) -> int:
    tu = _load_template_update_module(own_root)
    cfg, _ = tu.load_template_json(own_root)
    values = cfg.get("values") or {}

    lines = [f"install-global.py --plan -> {home_dir}", f"AI-CONFIG.md -> Globale Ablage: {ablage_hint}", ""]
    if not parts:
        lines.append("Keine Teile ausgewaehlt (Default 'nein' bzw. --parts leer) - nichts zu tun.")
        lines.append("Explizit anfordern mit --parts agents,skills,rules.")
        print("\n".join(lines))
        return 0

    items = _candidates(own_root, parts)
    for item in items:
        dest = home_dir / item["rel_dest"]
        content = _rendered_content(item, values)
        status = "existiert bereits - wuerde ohne --force uebersprungen" if dest.exists() else "wuerde angelegt"
        lines.append(f"[{item['part']}] {item['rel_dest']}  ({status})")
        markers = find_reference_markers(content)
        if markers:
            lines.append(f"    moegliche projektgebundene Verweise: {', '.join(markers)}")
        if "{{" in content:
            lines.append("    WARN: enthaelt noch unaufgeloeste Platzhalter nach der Ersetzung")

    lines.append("")
    lines.append(f"Insgesamt {len(items)} Datei(en). Anwenden: --apply (zusaetzlich --force zum Ueberschreiben).")
    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------------------
# --apply
# ---------------------------------------------------------------------------


def cmd_apply(own_root: Path, home_dir: Path, parts, force: bool) -> int:
    tu = _load_template_update_module(own_root)
    cfg, _ = tu.load_template_json(own_root)
    values = cfg.get("values") or {}

    items = _candidates(own_root, parts)
    state = load_state(home_dir)

    written, skipped, backed_up, warns = [], [], [], []
    for item in items:
        dest = home_dir / item["rel_dest"]
        content = _rendered_content(item, values)
        if "{{" in content:
            warns.append(item["rel_dest"])
        if dest.exists() and not force:
            skipped.append(item["rel_dest"])
            continue
        if dest.exists() and force:
            bak = dest.with_name(dest.name + ".bak")
            if bak.exists():
                backed_up.append(f"{item['rel_dest']} (Sicherung existiert schon, keine neue angelegt)")
            else:
                bak.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(dest, bak)
                backed_up.append(item["rel_dest"])
        _write_text(dest, content)
        written.append(item["rel_dest"])
        state["files"][item["rel_dest"]] = {"sha256": _sha256_text(content)}

    if written:
        state["template_url"] = cfg.get("template_url")
        # base_commit fehlt im Template-Checkout selbst (den setzt erst create-project.py). Dann den
        # aktuellen HEAD nehmen, damit --status sagen kann, welcher Stand global liegt.
        state["base_commit"] = cfg.get("base_commit") or _current_head(own_root)
        state["parts"] = sorted(set(state.get("parts", []) + parts))
        state["installed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        save_state(home_dir, state)

    lines = [f"install-global.py --apply -> {home_dir}", ""]
    lines.append(f"Geschrieben ({len(written)}): " + (", ".join(written) if written else "(keine)"))
    lines.append(
        f"Uebersprungen, existiert schon ({len(skipped)}): " + (", ".join(skipped) if skipped else "(keine)")
    )
    if force:
        lines.append(f"Sicherungen ({len(backed_up)}): " + (", ".join(backed_up) if backed_up else "(keine)"))
    if warns:
        lines.append(f"WARN - noch unaufgeloeste Platzhalter in: {', '.join(warns)}")
    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------------------
# --status
# ---------------------------------------------------------------------------


def cmd_status(home_dir: Path) -> int:
    state = load_state(home_dir)
    if not state.get("files"):
        print(f"install-global.py --status -> {home_dir}\nNichts installiert (keine {STATE_FILE_NAME} gefunden).")
        return 0

    lines = [f"install-global.py --status -> {home_dir}", ""]
    lines.append(f"Installiert am: {state.get('installed_at', '?')}")
    lines.append(f"Template-Commit: {state.get('base_commit', '?')}")
    lines.append(f"Teile: {', '.join(state.get('parts', [])) or '?'}")
    lines.append("")
    for rel, meta in sorted(state.get("files", {}).items()):
        dest = home_dir / rel
        if not dest.exists():
            lines.append(f"  {rel}: fehlt (von Hand geloescht?)")
            continue
        current = _sha256(dest)
        changed = current != meta.get("sha256")
        lines.append(f"  {rel}: {'von Hand geaendert seit Installation' if changed else 'unveraendert'}")
    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------------------
# --remove
# ---------------------------------------------------------------------------


def cmd_remove(home_dir: Path) -> int:
    state = load_state(home_dir)
    if not state.get("files"):
        print(f"install-global.py --remove -> {home_dir}\nNichts installiert, nichts zu entfernen.")
        return 0

    removed, kept_changed, missing = [], [], []
    remaining_files = {}
    for rel, meta in state.get("files", {}).items():
        dest = home_dir / rel
        if not dest.exists():
            missing.append(rel)
            continue
        if _sha256(dest) != meta.get("sha256"):
            kept_changed.append(rel)
            remaining_files[rel] = meta
            continue
        dest.unlink()
        removed.append(rel)
        try:
            dest.parent.rmdir()
        except OSError:
            pass  # nicht leer (z.B. Geschwisterdatei) - bleibt liegen

    if remaining_files:
        state["files"] = remaining_files
        save_state(home_dir, state)
    else:
        state_path = home_dir / STATE_FILE_NAME
        if state_path.exists():
            state_path.unlink()

    lines = [f"install-global.py --remove -> {home_dir}", ""]
    lines.append(f"Entfernt ({len(removed)}): " + (", ".join(sorted(removed)) if removed else "(keine)"))
    lines.append(
        f"Von Hand geaendert, NICHT entfernt ({len(kept_changed)}): "
        + (", ".join(sorted(kept_changed)) if kept_changed else "(keine)")
    )
    if missing:
        lines.append(f"Bereits fehlend ({len(missing)}): " + ", ".join(sorted(missing)))
    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def _resolve_parts(args, own_root: Path):
    """Liefert (parts, ablage_hint, error|None)."""
    ablage = read_globale_ablage(own_root)
    if args.parts is not None:
        raw = [p.strip() for p in args.parts.split(",") if p.strip()]
        unknown = [p for p in raw if p not in ("agents", "skills", "rules")]
        if unknown:
            return None, ablage, f"Unbekannte(r) Teil(e) in --parts: {', '.join(unknown)} (erlaubt: agents, skills, rules)"
        return raw, ablage, None
    if ablage == "fragen":
        return "fragen", ablage, None  # vom Aufrufer je Kommando behandelt
    parts = PARTS_FROM_ABLAGE.get(ablage)
    if parts is None:
        return [], ablage, None  # unbekannter Wert -> wie "nein" behandeln, nichts zu tun
    return parts, ablage, None


def build_parser():
    parser = argparse.ArgumentParser(
        prog="install-global.py",
        description="Agenten/Skills/Regelauszug des Templates nach ~/.claude/ legen (global, alle Projekte).",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--plan", action="store_true", help="Nur anzeigen (Default)")
    group.add_argument("--apply", action="store_true", help="Tatsaechlich schreiben")
    group.add_argument("--status", action="store_true", help="Installierten Stand zeigen")
    group.add_argument("--remove", action="store_true", help="Nur von hier installierte, unveraenderte Dateien entfernen")
    parser.add_argument("--force", action="store_true", help="Vorhandene Zieldatei ueberschreiben (vorher Sicherung .bak)")
    parser.add_argument("--parts", default=None, help="Kommaliste aus agents,skills,rules (Default: aus AI-CONFIG.md)")
    parser.add_argument("--home-dir", default=None, help="Zielverzeichnis statt ~/.claude (Tests)")
    return parser


def _run(argv) -> int:
    args = build_parser().parse_args(argv)
    own_root = _own_root()
    home_dir = resolve_home_dir(args)

    if args.status:
        return cmd_status(home_dir)
    if args.remove:
        return cmd_remove(home_dir)

    parts, ablage, err = _resolve_parts(args, own_root)
    if err:
        print(f"install-global.py: Fehler: {err}", file=sys.stderr)
        return 2

    if args.apply:
        if parts == "fragen":
            print(
                "install-global.py: Fehler: AI-CONFIG.md § 'Globale Ablage' steht auf 'fragen' - --parts "
                "explizit angeben (Auswahl klaert der Skill vorher im Chat, keine Standardantwort).",
                file=sys.stderr,
            )
            return 2
        if not parts:
            print(f"install-global.py --apply -> {home_dir}\nGlobale Ablage: {ablage} - nichts zu tun.")
            return 0
        return cmd_apply(own_root, home_dir, parts, args.force)

    # --plan ist Default, auch ohne explizites Flag.
    ablage_hint = ablage if parts != "fragen" else f"{ablage} (Auswahl im Chat noch offen - Vorschau fuer alle Teile)"
    plan_parts = ["agents", "skills", "rules"] if parts == "fragen" else parts
    return cmd_plan(own_root, home_dir, plan_parts, ablage_hint)


def main() -> int:
    try:
        return _run(sys.argv[1:])
    except SystemExit:
        raise
    except BaseException as e:  # noqa: BLE001 - darf nie mit Traceback nach aussen dringen
        print(f"install-global.py: Fehler: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
