# Coding-Regeln — Python

Regeln für Python 3 mit Typannotationen, Stdlib-first und automatisiertem Linting.

## Sprache und Stil
- Typannotationen an jeder Funktionssignatur (Parameter und Rückgabewert), auch für interne Funktionen.
- f-Strings statt `%`-Formatierung oder `.format()`.
- Stdlib bevorzugen, bevor eine externe Abhängigkeit ergänzt wird.
- Kontextmanager (`with`) für alles, was geöffnet/geschlossen werden muss (Dateien, Locks, Verbindungen).

## Struktur
- Virtualenv/`venv` je Projekt, keine globale Installation von Projekt-Abhängigkeiten.
- Abhängigkeiten mit gepinnten Versionen in einer Lockdatei (z. B. `requirements.txt`/`poetry.lock`).
- Ein Modul pro fachlichem Verantwortungsbereich, keine Sammel-Module ohne Abgrenzung.

## Typisierung / Fehlerbehandlung
- Keine mutbaren Default-Argumente (`def f(x: list = [])`) — stattdessen `None` und im Rumpf initialisieren.
- Spezifische Exception-Klassen fangen, kein pauschales `except Exception` ohne erneutes Werfen oder Loggen.
- `dataclasses`/`TypedDict`/`pydantic`-Modelle für strukturierte Daten statt loser Dicts.

## Werkzeuge
- Linter/Formatter: ruff (Linting) und black (Formatierung), beide mit Projektkonfiguration.
- Tests: pytest, Fixtures statt Setup-Code in jedem Testmodul.

## Fallstricke
- `is`/`is not` nur für Identitätsvergleiche (`None`, Singletons), nicht für Werte.
- Zirkuläre Importe durch klare Modulgrenzen vermeiden statt durch verzögerte Imports zu umschiffen.
