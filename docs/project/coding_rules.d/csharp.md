# Coding-Regeln — C#

Regeln für modernes C# mit Nullable-Kontext, konsequent asynchronem Code und Records.

## Sprache und Stil
- Nullable-Kontext (`<Nullable>enable</Nullable>`) projektweit aktiv, Warnungen nicht unterdrücken.
- `var` nur, wenn der Typ aus der rechten Seite offensichtlich ist, sonst expliziter Typ.
- Records für unveränderliche Wertobjekte/DTOs, Klassen für Objekte mit Identität und Verhalten.

## Struktur
- Ein öffentlicher Typ je Datei, Dateiname entspricht Typname.
- Abhängigkeiten über Konstruktor-Injektion, keine versteckten Service-Locator-Zugriffe.

## Typisierung / Fehlerbehandlung
- Asynchrone Methoden durchgängig mit `Async`-Suffix benennen und `Task`/`Task<T>` zurückgeben.
- `ConfigureAwait(false)` in Bibliothekscode ohne Abhängigkeit vom UI-Kontext.
- Exceptions für Ausnahmefälle, nicht für regulären Kontrollfluss — Rückgabetypen (`Result<T>`/`bool`) für
  erwartbare Fehlerfälle erwägen.
- `IDisposable`-Ressourcen ausschließlich über `using`/`await using` verwalten.

## Werkzeuge
- Linter/Formatter: `dotnet format`, Analyzer-Regeln (`.editorconfig`-Abschnitt `dotnet_diagnostic`) in der CI.

## Fallstricke
- `async void` nur für Event-Handler, sonst immer `async Task`, sonst werden Exceptions verschluckt.
- `.Result`/`.Wait()` auf Tasks vermeiden — Deadlock-Gefahr in synchronen Kontexten.
