#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Erinnert bei Sitzungsstart daran, dass eine freiwillige Rueckmeldung faellig waere - und zwar in
#        einem Takt, der zum Projekt passt. Gegenstueck zu maintenance-check.py, aber BEWUSST EIGENSTAENDIG:
#        Die Wartung ist abwaehlbar (AI-CONFIG.md § Wartung), und mit ihr verschwaende ihr Hook - die
#        Rueckmeldung haette dann keinen Ausloeser mehr.
#
#        Warum "adaptiv" ueberhaupt: Ein fester Wochentakt passt nicht zu jemandem, der einmal im Monat an
#        seinem Projekt arbeitet - der bekaeme Erinnerungen fuer Wochen, in denen nichts passiert ist. Und er
#        passt nicht zu jemandem, der taeglich arbeitet - dort waere eine Woche zu selten. Gemessen wird
#        deshalb nicht die Zeit, sondern die ARBEIT: Wie viele Tage mit Commits liegen seit der letzten
#        Sendung? Ab FAELLIG_TAGE Arbeitstagen wird einmal erinnert.
#
#        Der Hook erinnert nur. Er sendet nie, er fragt nie, er schreibt nichts ausser seinem eigenen
#        Merker - und bei "Feedback: aus" tut er sofort gar nichts.
#
# Aufruf:
#   python .claude/scripts/feedback-check.py            (SessionStart-Hook)
#       Gibt eine einzelne Erinnerungszeile aus, wenn etwas faellig ist - sonst nichts. Exit immer 0:
#       ein Hook, der die Sitzung stoert, waere schlimmer als eine verpasste Erinnerung.
#   python .claude/scripts/feedback-check.py --status
#       Zeigt die Rechnung dahinter (Takt, Arbeitstage seit der letzten Sendung, faellig ja/nein).
#
# Ausgabeformat: eine Zeile Klartext oder nichts. Exit immer 0.

import subprocess
import sys
import time
from pathlib import Path

FAELLIG_TAGE = 5          # Tage MIT Commits seit der letzten Sendung
MINDESTABSTAND_H = 48     # nie oefter erinnern, egal wie viel gearbeitet wurde
TEMPLATE_JSON_REL = ".claude/template.json"
CONFIG_REL = "AI-CONFIG.md"


def _root() -> Path:
    import os
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    hier = Path(__file__).resolve().parent
    for kandidat in (hier.parent.parent, hier.parent, hier):
        if (kandidat / "AGENTS.md").exists():
            return kandidat
    return Path.cwd().resolve()


def _feedback_modul(root: Path):
    """feedback.py per importlib - dort stehen Parser, Schalterlesen und der Zustand. Fehlt es (Projekt ohne
    Rueckmeldung), gibt es hier auch nichts zu tun."""
    import importlib.util
    pfad = root / ".claude" / "scripts" / "feedback.py"
    if not pfad.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location("_fb_check", pfad)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:  # noqa: BLE001 - ein kaputtes feedback.py darf die Sitzung nicht aufhalten
        return None


def _arbeitstage_seit(root: Path, stempel: str) -> int:
    """Tage mit mindestens einem Commit seit `stempel` (JJJJ-MM-TT HH:MM). Ohne Stempel: seit jeher."""
    seit = (stempel or "")[:10]
    args = ["git", "-C", str(root), "log", "--format=%ad", "--date=short"]
    if seit:
        args.append(f"--since={seit}")
    try:
        res = subprocess.run(args, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return 0
    if res.returncode != 0:
        return 0
    return len(set(res.stdout.split()))


def main() -> int:
    root = _root()
    fb = _feedback_modul(root)
    if fb is None:
        return 0
    try:
        tj = fb._template_json(root)
        if tj.get("is_template") is True:
            return 0
        modus = fb._modus(root)
        takt = fb._takt(root)
        block = fb._feedback_block(tj)
        zuletzt = block.get("zuletzt_gesendet") or ""
        wartend = len(fb._outbox(root))
        stunden = fb._tage_seit(zuletzt) * 24.0
        arbeitstage = _arbeitstage_seit(root, zuletzt)
    except Exception:  # noqa: BLE001 - siehe oben: nie die Sitzung aufhalten
        return 0

    faellig = (modus not in ("aus",) and takt == "adaptiv"
               and arbeitstage >= FAELLIG_TAGE and stunden >= MINDESTABSTAND_H)

    if "--status" in sys.argv[1:]:
        print(f"Feedback: {modus}, Takt: {takt}")
        print(f"Zuletzt gesendet: {zuletzt or 'nie'} ({stunden / 24:.1f} Tage her)")
        print(f"Arbeitstage seitdem: {arbeitstage} (faellig ab {FAELLIG_TAGE})")
        print(f"Wartende Eintraege: {wartend}")
        print("Faellig: " + ("ja" if faellig else "nein"))
        return 0

    if faellig:
        was = f"{wartend} Eintrag/Eintraege warten" if wartend else "noch nichts gesammelt"
        print(f"Rueckmeldung ans Template waere faellig ({arbeitstage} Arbeitstage seit der letzten "
              f"Sendung, {was}). Ansehen: /act-feedback - oder ein Satz genuegt: /act-feedback <Text>.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        sys.exit(0)
