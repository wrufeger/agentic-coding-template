> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# Fehleranalysen — {{PROJEKTNAME}}

## Wann dokumentieren

Nur schwerwiegende Fälle: Build-/Startfehler, Produktionsausfälle, sicherheitsrelevante Fehler, Datenverlust.
Gewöhnliche Bugs brauchen keine eigene Analyse-Datei.

## Standard: eine Datei je Vorfall

Bei wenigen Fällen reicht eine einzelne Markdown-Datei direkt in `docs/project/incidents/`:

`docs/project/incidents/YYYY-MM-DD_kurzer-titel.md`

mit den vier Pflicht-Abschnitten:

1. **Fehlerbild** — was war zu sehen, seit wann, wer hat es bemerkt?
2. **Ursache** — die tatsächliche Ursache (nicht die erste Vermutung), mit Fundstelle `Datei:Zeile` oder
   Log-Auszug.
3. **Behebung** — was konkret geändert wurde, Commit-Hash.
4. **Verifikation** — womit belegt ist, dass es behoben ist: Testlauf, Aufruf von außen, Beobachtungszeitraum.

Kein Eintrag ohne Verifikation — „vermutlich behoben" reicht nicht.

### Vorlage zum Kopieren

```markdown
# YYYY-MM-DD — Kurztitel

## Fehlerbild
(was war zu sehen, seit wann, wer hat es bemerkt)

## Ursache
(die tatsächliche Ursache, mit Datei:Zeile oder Log-Auszug)

## Behebung
(was geändert wurde, Commit-Hash)

## Verifikation
(Testlauf, Aufruf von außen, Beobachtungszeitraum)
```

## Ab etwa fünf Analysen pro Jahr

Dann lohnt sich eine Gliederung in Unterordner je Jahr oder Bereich (z. B. `incidents/2026/` oder
`incidents/backend/`) — das ist ein Hinweis, keine Vorschrift. Bis dahin bleiben alle Dateien flach direkt in
`docs/project/incidents/`.
