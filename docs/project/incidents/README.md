> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# Fehleranalysen — {{PROJEKTNAME}}

## Wann dokumentieren

Nur schwerwiegende Fälle: Build-/Startfehler, Produktionsausfälle, sicherheitsrelevante Fehler, kritische
Laufzeitfehler. Kleinere Bugs brauchen keine eigene Analyse-Datei.

## Dateiname

`docs/project/incidents/YYYY-MM-DD-kurzname.md` (kleingeschrieben, Bindestriche statt Leerzeichen).

## Pflicht-Abschnitte

1. **Fehlerbild** — was war zu beobachten (Symptom, Fehlermeldung, betroffener Bereich)?
2. **Ursache** — was war die eigentliche Ursache (nicht nur das Symptom)?
3. **Umsetzung** — was wurde konkret geändert (Datei/Commit-Bezug)?
4. **Verifikation** — konkreter Beleg, dass es behoben ist (Testlauf, Aufruf von außen, Commit-Hash).

Kein Eintrag ohne Verifikation — „vermutlich behoben" reicht nicht.
