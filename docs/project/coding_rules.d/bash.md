# Coding-Regeln — Shell-Skripte

Regeln für Bash-Skripte: Robustheit, Quoting, Prüfbarkeit durch Linter.

## Sprache und Stil
- `set -euo pipefail` als erste ausführbare Zeile in jedem Skript.
- Kopfkommentar mit Zweck, Aufruf (Beispiel) und erwarteter Ausgabe/Exit-Verhalten.
- Variablen konsequent quoten (`"$var"`), insbesondere bei Pfaden mit möglichen Leerzeichen.

## Struktur
- Funktionen für wiederverwendbare Abschnitte, kein Kopieren gleicher Befehlsfolgen.
- Ein Skript, ein klar benannter Zweck — keine Mehrzweck-Skripte mit Modus-Flags für unabhängige Aufgaben.

## Typisierung / Fehlerbehandlung
- Exit-Codes bewusst setzen (`exit 0`/`exit 1`/spezifische Codes), nicht implizit den letzten Befehl
  durchreichen.
- Eingaben/Argumente vor Verwendung prüfen (Anzahl, Existenz von Pfaden), Fehlermeldung auf stderr.

## Werkzeuge
- Linter: `shellcheck` vor jedem Commit, Warnungen nicht pauschal unterdrücken.

## Fallstricke
- Keine Parsing-Schleifen über `ls`-Ausgabe — stattdessen Globbing oder `find ... -print0` mit `read -d ''`.
- `cd` in Skripten mit Fehlerprüfung (`cd dir || exit 1`), sonst laufen Folgebefehle im falschen Verzeichnis.
