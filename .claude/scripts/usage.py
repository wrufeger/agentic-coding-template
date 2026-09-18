#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Anonyme Nutzungsstatistik lokal fuehren - wie oft welcher Skill/welches Script tatsaechlich
#        benutzt wurde bzw. welches Feedback-Ereignis eintrat (Grundlage fuer AI-CONFIG.md § Feedback-
#        Umfang "c" Werkzeug-Nutzung; Entscheidung Wolfgang 2026-09-18). ERGAENZT die Bestandszahlen aus
#        feedback.py:_werkzeug_nutzung() (wie VIELE Skills/Scripte es im Projekt gibt), ersetzt sie aber
#        NICHT - Bestand und Nutzung beantworten verschiedene Fragen und gehen beide in die Nutzlast
#        (siehe feedback.py:_nutzlast()). Gezaehlt wird nur,
#        was es im Template tatsaechlich gibt: die Skill-Ordner unter `.claude/skills/` und die Scripte
#        unter `.claude/scripts/`, dazu eine feste kleine Ereignisliste (siehe EREIGNISSE unten). Eine
#        unbekannte Kennung landet NICHT unter ihrem eigenen Namen, sondern auf dem Sammelzaehler "eigen" -
#        Namen selbstgebauter Skills/Scripte verraten oft, worum es im Projekt geht, ihre blosse Anzahl
#        nicht. Gespeichert werden ausschliesslich Kennung + Zaehlerstand, nie Argumente, Pfade,
#        Zeitstempel je Aufruf oder Text - "seit" ist ein einziger Zeitstempel fuer die ganze Datei, kein
#        Verlauf. Reine Python-Stdlib, kein Paket noetig.
#
# Aufruf:
#   python .claude/scripts/usage.py --count <kennung>
#       Erhoeht den Zaehler fuer <kennung> um 1 (bekannte Kennung: unter ihrem eigenen Namen, sonst unter
#       "eigen"). Wird aus einzelnen Scripten heraus aufgerufen (z. B. update-template.py --apply,
#       sync-config.py --apply, act-help.py) sowie ueber --hook aus settings.json.
#   python .claude/scripts/usage.py --hook
#       Hook-Modus fuer den `Skill`-Tool-Aufruf in settings.json: liest die Hook-Nutzlast von stdin und
#       zaehlt bei tool_name == "Skill" die uebergebene Kennung (tool_input.skill). Alles andere ist ein
#       stilles No-op.
#   python .claude/scripts/usage.py --status
#       Zaehlerstand lesbar (inkl. "seit").
#   python .claude/scripts/usage.py --json
#       Dieselben Zahlen maschinenlesbar, Grundlage fuer die spaetere Ruecklieferung an /act-feedback (holt
#       die Zahlen ueber diesen Aufruf, liest die Datei nicht selbst).
#   python .claude/scripts/usage.py --reset
#       Setzt alle Zaehler zurueck und "seit" auf jetzt - wird nach einer Sendung durch /act-feedback
#       aufgerufen.
#
# Ablage: `.claude/usage.json` (gitignored, rein lokal je Rechner). Schema:
#   {"seit": "YYYY-MM-DDTHH:MM:SS", "zaehler": {"<kennung>": <int>, ..., "eigen": <int>}}
# Geschrieben wird atomar wie bei `.claude/template.json`/`.claude/maintenance/status.json` (Temp-Datei im
# selben Ordner, dann os.replace - kein Leser sieht eine halb geschriebene Datei), zusaetzlich per
# Datei-Lock serialisiert (gleicher Aufbau wie die Zustandsdatei in ai-log.py: os.open mit O_CREAT|O_EXCL,
# verwaistes Lock nach LOCK_STALE_AFTER uebernehmen, nach LOCK_TIMEOUT notfalls ohne Lock weiterarbeiten).
# Reines os.replace allein schuetzt nicht vor einem Lesen-Aendern-Schreiben-Wettlauf zweier gleichzeitiger
# --count-Aufrufe (z. B. Skill-Hook und ein Script-Zaehlaufruf in derselben Sekunde) - das Lock schon, ein
# eigener Prozess pro Lock-Aufruf macht echte Nebenlaeufigkeit ohnehin selten.
#
# Exit-Code: IMMER 0 - auch bei falschem Aufruf, kaputter Datei oder unbekannter Kennung. Ein Zaehler, der
# eine Sitzung oder einen Hook stoert, ist schlimmer als eine fehlende Zahl. main() laeuft komplett in
# try/except.

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

USAGE_REL = Path(".claude") / "usage.json"
LOCK_TIMEOUT = 1.0  # max. Wartezeit auf das Lock (Sekunden).
LOCK_STALE_AFTER = 5.0  # Lock aelter als das gilt als verwaist und wird uebernommen.
LOCK_SPIN_SLEEP = 0.02

# Ereignisse, die kein Skill/Script sind, aber ebenfalls gezaehlt werden (Feedback-Ablauf, s. act-feedback).
# "feedback-ignoriert" hat noch KEINEN Aufrufer: der einzig sinnvolle Zaehlpunkt waere in
# feedback-check.py:_merker_fortschreiben() (dort, wo "erinnerungen_ohne_reaktion" hochgezaehlt wird), aber
# dieses Script gehoert nicht zu diesem Lauf und wird hier bewusst nicht angefasst. Die Kennung steht schon
# hier, damit --count feedback-ignoriert kuenftig als bekannt gilt, sobald jemand den Aufruf ergaenzt.
EREIGNISSE = {"feedback-gesendet", "feedback-verschoben", "feedback-abgelehnt", "feedback-ignoriert"}
EIGEN = "eigen"


# ---------------------------------------------------------------------------
# Grundlagen
# ---------------------------------------------------------------------------


def _find_root() -> Path:
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[2]


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _known_identifiers(root: Path) -> set:
    """Geschlossene Liste: Skill-Ordner unter .claude/skills/ (mit SKILL.md), Script-Namen (ohne .py)
    unter .claude/scripts/, dazu EREIGNISSE. Wird bei jedem Aufruf frisch ermittelt statt hart codiert -
    so bleibt die Liste automatisch aktuell, wenn Skills/Scripte dazukommen oder verschwinden."""
    kennungen = set(EREIGNISSE)
    skills_dir = root / ".claude" / "skills"
    if skills_dir.is_dir():
        try:
            for eintrag in skills_dir.iterdir():
                if eintrag.is_dir() and (eintrag / "SKILL.md").exists():
                    kennungen.add(eintrag.name)
        except OSError:
            pass
    scripts_dir = root / ".claude" / "scripts"
    if scripts_dir.is_dir():
        try:
            for eintrag in scripts_dir.glob("*.py"):
                kennungen.add(eintrag.stem)
        except OSError:
            pass
    return kennungen


# ---------------------------------------------------------------------------
# Datei-Lock (gleicher Aufbau wie _StateLock in ai-log.py)
# ---------------------------------------------------------------------------


class _FileLock:
    """Bestmoegliches Datei-Lock ueber os.open(O_CREAT|O_EXCL). Blockiert nie dauerhaft: nach
    LOCK_TIMEOUT wird ohne Lock weitergearbeitet, ein verwaistes Lock (> LOCK_STALE_AFTER) wird
    uebernommen. `held` sagt, ob das Lock tatsaechlich gehalten wird (nur informativ)."""

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self.held = False

    def __enter__(self):
        deadline = time.time() + LOCK_TIMEOUT
        while True:
            try:
                fd = os.open(str(self.lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                self.held = True
                return self
            except FileExistsError:
                try:
                    age = time.time() - self.lock_path.stat().st_mtime
                except OSError:
                    age = 0.0
                if age > LOCK_STALE_AFTER:
                    try:
                        self.lock_path.unlink()
                    except OSError:
                        pass
                    continue
                if time.time() >= deadline:
                    self.held = False
                    return self
                time.sleep(LOCK_SPIN_SLEEP)
            except OSError:
                self.held = False
                return self

    def __exit__(self, *exc_info):
        if self.held:
            try:
                self.lock_path.unlink()
            except OSError:
                pass
        return False


def _paths(root: Path):
    path = root / USAGE_REL
    return path, path.with_suffix(path.suffix + ".lock")


def _load(path: Path) -> dict:
    """Liest usage.json; fehlt sie oder ist sie kaputt, wird still neu begonnen."""
    data = None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict) or not isinstance(data.get("zaehler"), dict):
        data = {"seit": _now_iso(), "zaehler": {}}
    return data


def _save(path: Path, data: dict) -> None:
    """Atomar schreiben: Temp-Datei im selben Verzeichnis, dann os.replace - derselbe Stil wie
    maintenance-check.py:save_status()/.claude/template.json."""
    path.parent.mkdir(parents=True, exist_ok=True)
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
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    except OSError:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _increment(root: Path, kennung: str) -> None:
    path, lock_path = _paths(root)
    with _FileLock(lock_path):
        data = _load(path)
        zaehler = data.setdefault("zaehler", {})
        try:
            bisher = int(zaehler.get(kennung, 0))
        except (TypeError, ValueError):
            bisher = 0
        zaehler[kennung] = bisher + 1
        _save(path, data)


# ---------------------------------------------------------------------------
# Befehle
# ---------------------------------------------------------------------------


def cmd_count(root: Path, kennung: str) -> int:
    kennung = (kennung or "").strip()
    if not kennung:
        return 0
    known = _known_identifiers(root)
    key = kennung if kennung in known else EIGEN
    _increment(root, key)
    return 0


def cmd_hook(root: Path) -> int:
    """PreToolUse-Hook fuer das Skill-Tool: liest tool_input.skill aus der Nutzlast und zaehlt sie.
    Jede andere Nutzlast (falscher Tool-Name, kaputtes JSON) ist ein stilles No-op."""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (ValueError, AttributeError):
        return 0
    if not isinstance(payload, dict) or payload.get("tool_name") != "Skill":
        return 0
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0
    return cmd_count(root, str(tool_input.get("skill") or ""))


def cmd_reset(root: Path) -> int:
    path, lock_path = _paths(root)
    with _FileLock(lock_path):
        _save(path, {"seit": _now_iso(), "zaehler": {}})
    print("Zaehler zurueckgesetzt.")
    return 0


def cmd_status(root: Path) -> int:
    path, _lock_path = _paths(root)
    data = _load(path)
    zaehler = data.get("zaehler", {})
    print(f"Zaehlt seit: {data.get('seit', '-')}")
    if not isinstance(zaehler, dict) or not zaehler:
        print("Noch keine Zaehlungen.")
        return 0
    for name in sorted(zaehler):
        print(f"  {name}: {zaehler[name]}")
    return 0


def cmd_json(root: Path) -> int:
    path, _lock_path = _paths(root)
    print(json.dumps(_load(path), ensure_ascii=False))
    return 0


# ---------------------------------------------------------------------------
# main / Argument-Parsing
# ---------------------------------------------------------------------------


def build_parser():
    parser = argparse.ArgumentParser(
        prog="usage.py",
        description="Anonyme Nutzungsstatistik (.claude/usage.json) fuehren.",
    )
    parser.add_argument("--count", metavar="KENNUNG", help="Zaehler fuer KENNUNG um 1 erhoehen")
    parser.add_argument("--hook", action="store_true", help="Skill-Tool-Hook - Kennung aus stdin-Payload zaehlen")
    parser.add_argument("--status", action="store_true", help="Zaehlerstand lesbar anzeigen")
    parser.add_argument("--json", action="store_true", help="Zaehlerstand maschinenlesbar ausgeben")
    parser.add_argument("--reset", action="store_true", help="Alle Zaehler zuruecksetzen")
    return parser


def _run(argv) -> int:
    parser = build_parser()
    args, _unbekannt = parser.parse_known_args(argv)
    root = _find_root()

    if args.hook:
        return cmd_hook(root)
    if args.count is not None:
        return cmd_count(root, args.count)
    if args.reset:
        return cmd_reset(root)
    if args.json:
        return cmd_json(root)
    if args.status:
        return cmd_status(root)
    parser.print_usage(sys.stderr)
    return 0


def main() -> int:
    try:
        return _run(sys.argv[1:])
    except SystemExit:
        # argparse selbst (z.B. --help oder ein fehlender Wert bei --count) darf raus, aber auch das
        # laesst den Aufrufer nie mit einem Fehler-Exit stehen - siehe Kopfkommentar "Exit-Code: IMMER 0".
        return 0
    except BaseException:  # noqa: BLE001 - darf nie mit Traceback nach aussen dringen
        return 0


if __name__ == "__main__":
    sys.exit(main())
