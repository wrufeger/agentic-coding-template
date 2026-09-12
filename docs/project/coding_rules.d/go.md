# Coding-Regeln — Go

Regeln für idiomatisches Go: Fehlerbehandlung, kleine Interfaces, Kontextpropagierung.

## Sprache und Stil
- `gofmt`/`goimports` vor jedem Commit, keine manuell abweichende Formatierung.
- Kurze, aussagekräftige Paketnamen, keine `util`/`common`-Sammelpakete ohne fachlichen Bezug.

## Struktur
- Interfaces beim Konsumenten definieren (klein, oft ein bis zwei Methoden), nicht vorab beim Anbieter.
- `context.Context` als erster Parameter jeder Funktion, die Abbruch/Deadline/Werte weiterreichen können muss.

## Typisierung / Fehlerbehandlung
- Fehler als letzter Rückgabewert, sofort nach dem Aufruf prüfen (`if err != nil`) statt zu sammeln.
- Fehler mit `%w` wrappen (`fmt.Errorf("...: %w", err)`), damit `errors.Is`/`errors.As` funktionieren.
- Keine Panics in Bibliothekscode für erwartbare Fehlerfälle — Panic nur bei echten Programmierfehlern.
- Rückgabewerte nicht mit `_` verwerfen, wenn ein Fehler mitgeliefert wird, ohne ihn geprüft zu haben.

## Werkzeuge
- Linter/Formatter: `go vet`, `staticcheck`, `gofmt` in der CI erzwingen.

## Fallstricke
- Goroutinen ohne erkennbares Lebenszyklus-Ende (kein `WaitGroup`/Kontext-Abbruch) vermeiden — Leaks.
- Shared State zwischen Goroutinen über Kanäle oder explizite Locks synchronisieren, nicht stillschweigend.
