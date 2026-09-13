#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# Zweck: CLI-Einstieg der Struktur-Migration (Weg 2, "Projekt nachruesten") - die eigentliche Logik liegt
#        in rename-lib.py (Bibliothek, bleibt nach der Einrichtung dauerhaft bestehen, weil sync-config.py
#        sie fuer den laufenden AI-CONFIG.md-Abgleich braucht). Dieser duenne Wrapper wird von
#        finish-setup.py beim Abschluss der Einrichtung entfernt - danach laeuft die Konfiguration nur
#        noch ueber sync-config.py. Reine Python-Stdlib, kein Paket noetig.
#
# Aufruf: siehe Kopfkommentar in rename-lib.py (identische Optionen: --plan/--apply/--rename-orchestrator/
#         --status).

import importlib.util
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass

_lib_path = Path(__file__).resolve().parent / "rename-lib.py"
if not _lib_path.exists():
    print(f"Fehler: {_lib_path} fehlt - dieser Wrapper braucht rename-lib.py.", file=sys.stderr)
    sys.exit(2)
_spec = importlib.util.spec_from_file_location("_rename_lib_cli", _lib_path)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

if __name__ == "__main__":
    sys.exit(_mod.main())
