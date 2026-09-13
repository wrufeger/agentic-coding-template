#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: Die Arbeitsdateien der Template-Entwicklung (`backlog.md`, `questions.md`, `ledger.md`) sind
#        gitignored - sie tragen den laufenden Arbeitsstand und bleiben lokal (siehe `.gitignore` und
#        `.templatedev/regeln.md`). In einem frischen Checkout fehlen sie deshalb. Dieses Script legt sie aus
#        den versionierten Vorlagen unter `.templatedev/vorlagen/` an. Vorhandene Dateien werden NIE
#        angefasst - der Arbeitsstand ist unwiederbringlich, ein Ueberschreiben waere ein Datenverlust.
#
# Aufruf:
#   python .templatedev/init.py            (wie --check: nur melden, was fehlt)
#   python .templatedev/init.py --check
#   python .templatedev/init.py --apply    (fehlende Dateien aus den Vorlagen anlegen)
#
# Exit-Codes: 0 = nichts zu tun bzw. erfolgreich angelegt, 1 = es fehlen Dateien (nur bei --check),
#   2 = Vorbedingungsfehler (Vorlagen-Ordner fehlt). Kein Traceback nach aussen.
#
# Laeuft nur im Template-Checkout selbst. In einem abgeleiteten Projekt gibt es `.templatedev/` nicht - der
# Ordner wird beim Anlegen entfernt und nie ins Projekt gemergt (`template_only`).

import argparse
import shutil
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

ARBEITSDATEIEN = ("backlog.md", "questions.md", "ledger.md")


def _root() -> Path:
    return Path(__file__).resolve().parent


def _pruefen(root: Path):
    """Liefert (fehlend, vorhanden) als Listen von Dateinamen."""
    fehlend, vorhanden = [], []
    for name in ARBEITSDATEIEN:
        (vorhanden if (root / name).exists() else fehlend).append(name)
    return fehlend, vorhanden


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="init.py",
        description="Fehlende Arbeitsdateien der Template-Entwicklung aus den Vorlagen anlegen.",
    )
    gruppe = parser.add_mutually_exclusive_group()
    gruppe.add_argument("--check", action="store_true", help="nur melden, was fehlt (Default)")
    gruppe.add_argument("--apply", action="store_true", help="fehlende Dateien anlegen")
    args = parser.parse_args()

    root = _root()
    vorlagen = root / "vorlagen"
    if not vorlagen.is_dir():
        print(f"Fehler: {vorlagen} fehlt - ohne Vorlagen laesst sich nichts anlegen.", file=sys.stderr)
        return 2

    fehlend, vorhanden = _pruefen(root)
    if not fehlend:
        if args.apply or args.check:
            print("Arbeitsdateien vollstaendig: " + ", ".join(vorhanden))
        return 0

    if not args.apply:
        print("Es fehlen Arbeitsdateien der Template-Entwicklung:")
        for name in fehlend:
            print(f"  - .templatedev/{name}")
        print("Anlegen mit: python .templatedev/init.py --apply")
        return 1

    angelegt, uebersprungen = [], []
    for name in fehlend:
        quelle = vorlagen / name
        if not quelle.exists():
            uebersprungen.append(f"{name} (keine Vorlage unter vorlagen/)")
            continue
        shutil.copy2(quelle, root / name)
        angelegt.append(name)

    if angelegt:
        print("Angelegt aus den Vorlagen:")
        for name in angelegt:
            print(f"  - .templatedev/{name}")
    if uebersprungen:
        print("Uebersprungen:")
        for eintrag in uebersprungen:
            print(f"  - {eintrag}")
    if vorhanden:
        print("Unveraendert (Arbeitsstand bleibt): " + ", ".join(vorhanden))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Abgebrochen.", file=sys.stderr)
        sys.exit(2)
    except Exception as fehler:  # noqa: BLE001 - kein Traceback nach aussen
        print(f"Fehler: {fehler}", file=sys.stderr)
        sys.exit(2)
