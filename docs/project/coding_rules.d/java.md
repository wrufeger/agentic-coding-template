# Coding-Regeln — Java

Regeln für moderne Java-Versionen (LTS) mit Fokus auf Unveränderlichkeit, ausdrückliche Nullbarkeit und
Nebenläufigkeit über `java.util.concurrent`.

## Sprache und Stil
- Records für unveränderliche Datenträger (DTOs, Wertobjekte), Sealed Interfaces/Classes mit Pattern Matching
  (`switch` auf Typen) statt `instanceof`-Ketten.
- `var` nur, wenn der Typ aus der rechten Seite offensichtlich bleibt, sonst expliziter Typ.
- Text Blocks für mehrzeilige Zeichenketten (SQL, JSON-Vorlagen) statt Verkettung.
- `Optional<T>` nur als Rückgabetyp für „möglicherweise kein Ergebnis" — nie als Feld, Parameter oder in
  Collections.

## Struktur
- Pakete nach Fachlichkeit schneiden, nicht nach technischer Schicht.
- Sichtbarkeit so eng wie möglich, Felder `final`, keine Setter ohne Grund — Unveränderlichkeit als Standard.
  Sie ist zugleich der beste Schutz gegen Nebenläufigkeitsfehler.
- Konstruktor-Injektion statt Feld-Injektion, auch außerhalb eines DI-Containers.

## Typisierung / Fehlerbehandlung
- Kein rohes `Object`, keine Raw Types bei Generics.
- Nullbarkeit an Feldern, Parametern und Rückgabetypen ausdrücklich machen (JSpecify `@Nullable`/`@NonNull`
  oder die im Projekt festgelegte Alternative).
- Keine leeren `catch`-Blöcke, kein `catch (Exception e)` ohne konkreten Grund. Unchecked für
  Programmierfehler, Checked für erwartbare, behandelbare Fälle.
- Ressourcen ausschließlich über try-with-resources verwalten.
- Nebenläufigkeit über `java.util.concurrent` (Executors, `CompletableFuture`, konkurrenzsichere Collections)
  statt manuellem `synchronized`/`wait`/`notify`. Virtuelle Threads (ab Java 21) nur, wenn Laufzeitumgebung
  und Bibliotheken sie unterstützen.
- SLF4J als Logging-Fassade, parametrisiert loggen statt Zeichenketten zu verketten, keine `System.out`-
  Ausgaben, keine Zugangsdaten oder personenbezogenen Daten im Log.

## Werkzeuge
- Build: Maven oder Gradle — die Wahl trifft das Projekt.
- Formatierung und statische Analyse: Spotless/google-java-format, Checkstyle, SpotBugs, Error Prone oder PMD,
  in der CI verbindlich.
- Tests: JUnit 5 mit AssertJ, Testnamen beschreiben das erwartete Verhalten; keine Zufälligkeit ohne festen
  Seed, keine Wartezeiten über `Thread.sleep`.

## Fallstricke
- `equals`/`hashCode` nur gemeinsam überschreiben.
- `java.time` statt `Date`/`Calendar`.
- Geldbeträge mit `BigDecimal`, nie mit `float`/`double`.
- Zeichensatz nie implizit — `UTF_8` explizit angeben.
- Nur parametrisierte SQL-Abfragen, kein SQL aus Zeichenkettenverkettung.
- Streams nicht um jeden Preis — eine klassische Schleife darf lesbarer sein.
