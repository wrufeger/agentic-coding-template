> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# Stories — {{PROJEKTNAME}}

Eine Story ist **ein abgegrenzter Schritt eines Features oder Backlog-Punkts, der umgesetzt und getestet
werden kann**. Hierher wandern Begründung und Umsetzungsdetails, die in `../../ai/backlog.md` oder in einer
Aufgabe mehr als etwa drei Zeilen gebraucht hätten — dort bleibt die Zeile mit dem Verweis, die Story trägt
die Erklärung.

Abgrenzung: Ein **Konzept** (`../konzepte/`) wägt Optionen ab und empfiehlt eine; eine **Story** setzt eine
bereits getroffene Entscheidung in prüfbare Schritte um. Eine **Aufgabe** (`../../ai/tasks.md`) ist der
Auftrag, eine Story tatsächlich zu bauen.

## Format

Dateiname `S<n>-<kurzname>.md`, fortlaufend nummeriert, nie neu vergeben (wie `T<n>`/`Q<n>` in `docs/ai/`).
Zitiert wird die Story als `S<n>`.

```text
> Datenstand: JJJJ-MM-TT – Status: Entwurf

# S<n> · <Titel>

**Ziel:** ein Satz, was danach anders ist.
**Bezug:** `B<n>` · Feature <x> · `T<n>` · `Q<n>` · ADR-<n>
**Vorbedingungen:** was vorher fertig sein muss, mit Verweis.
**Aufwand:** S/M/L oder Personentage.

## Umsetzung
Schritte, je eine Zeile.

## Fertig wenn
Prüfbare Bedingungen — woran erkennt man, dass die Story abgeschlossen ist.

## Offene Punkte
Was noch entschieden werden muss — als Frage in `../../ai/questions.md`, hier nur verwiesen.
```

Der Status im Kopf läuft `Entwurf` → `abgestimmt` ({{AUFTRAGGEBER}} hat zugestimmt) → `umgesetzt` (Beleg
vorhanden, siehe `ledger.md`).

## Vorhandene Stories

*(noch keine — Tabelle Nummer · Titel · Status · Aufwand pflegen, sobald die erste Story entsteht)*
