# Coding-Regeln — PHP

Regeln für moderne PHP-Versionen (8.x): Typisierung, PSR-12, sichere Datenbankzugriffe.

## Sprache und Stil
- `declare(strict_types=1);` als erste Anweisung in jeder PHP-Datei.
- PSR-12 als Formatierungsstandard, Einrückung mit 4 Leerzeichen.
- Namespaces nach PSR-4, ein Namespace pro Composer-Autoload-Wurzel.
- Arrow Functions/Closures statt globaler Callback-Funktionen.

## Struktur
- Abhängigkeiten ausschließlich über Composer, keine manuell eingebundenen Bibliotheken.
- Keine Geschäftslogik in Templates (Blade/Twig/PHP-Templates) — Templates nur für Darstellung.
- Eine Klasse je Datei, Dateiname entspricht Klassenname.

## Typisierung / Fehlerbehandlung
- Parameter- und Rückgabetypen an jeder öffentlichen Methode deklarieren, `mixed` nur mit Begründung.
- Exceptions statt Rückgabe von Fehlercodes oder `false` bei Fehlerfällen.
- Eigene Exception-Klassen je Fehlerdomäne, nicht durchgängig `\Exception` werfen.
- Nullable Typen (`?Type`) explizit markieren, kein impliziter `null`-Rückfall.

## Werkzeuge
- Linter/Formatter: PHP-CS-Fixer oder PHP_CodeSniffer (PSR-12), PHPStan/Psalm für statische Analyse.

## Fallstricke
- Datenbankzugriffe ausschließlich über PDO mit Prepared Statements, keine Stringverkettung von SQL.
- `===`/`!==` statt loser Vergleiche, wo Typgleichheit gemeint ist.
- `error_reporting`/`display_errors` in Produktion deaktiviert, Fehler nur ins Log.
