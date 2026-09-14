> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# Fragen an {{AUFTRAGGEBER}}

Hier stellt der Orchestrator Fragen an {{AUFTRAGGEBER}}; die Antworten werden einfach in die `* Antwort:`-Zeile
unter der Frage geschrieben, Stichworte reichen völlig. Der Orchestrator verbucht alles und bestätigt direkt
darunter. Offene Fragen stehen oben (Abschnitt „Offen"), innerhalb davon **nach Nummer sortiert**; Dringendes
wird mit 🔴 markiert, nicht vorgezogen. {{AUFTRAGGEBER}}s Zeilen bleiben unverändert stehen.

Beantwortete Fragen wandern nach dem Verbuchen ins Archiv `docs/ai/questions_archive.md`.

Formregeln: keine Markdown-Tabellen, Zeilen bei ca. 72 Zeichen umbrechen, je Frage eine eigene `* Antwort:`-Zeile,
Dringendes mit 🔴 markieren. Jede Frage bekommt eine fortlaufende Nummer mit Präfix `Q<n>` (Aufgaben laufen unter
`T<n>`, siehe `tasks.md`) — die Nummer wird in Ledger und Aufgaben zitiert und nach dem Archivieren nie neu
vergeben.

**Antworten so leicht wie möglich machen.** {{AUFTRAGGEBER}} soll mit einem Wort antworten können:

- Antwortmöglichkeiten **vorgeben**: ja/nein oder `a)`/`b)`/`c)` — jede Option eine Zeile, mit der Folge in
  drei bis fünf Wörtern. Eine freie Textantwort ist immer zusätzlich möglich.
- **Keine Standardantwort annehmen.** Eine unbeantwortete Frage bleibt offen und wird nicht stillschweigend
  nach der Einschätzung des Assistenten entschieden. Ist eine Option die naheliegende, darf sie als Empfehlung
  gekennzeichnet werden (`a) … (Empfehlung)`) — beantwortet ist sie damit nicht.
- Blockiert eine offene Frage die Arbeit, wird das in der Frage vermerkt (🔴) und im Board als offene Freigabe
  geführt; der Assistent arbeitet in der Zwischenzeit an etwas anderem weiter.
- Höchstens drei bis vier Zeilen Kontext vor der Frage, kein Fließtext, keine Herleitung.
- Eine Frage = eine Entscheidung. Alles, was mehrere Entscheidungen enthält, wird in mehrere nummerierte
  Fragen geteilt statt in einen langen Absatz gepackt.
- Offene Fragen („Wie stellst du dir X vor?") nur, wenn sich wirklich keine Optionen bilden lassen.

Beispiel:

```
Q3. Soll der Import fehlende Pflichtfelder überspringen oder abbrechen? 🔴
   a) überspringen, Fehler ins Log — Import läuft durch (Empfehlung)
   b) abbrechen — nichts wird importiert, Ursache zuerst klären
   Blockiert T12, solange offen.
   * Antwort:
```

**Teilfragen (`Q5a`, `Q5b`, …).** Hängen mehrere Einzelentscheidungen so zusammen, dass die Umsetzung erst
beginnen kann, wenn **alle** beantwortet sind, bekommen sie dieselbe Nummer mit Buchstaben-Suffix und stehen
als Block untereinander. Der Assistent verarbeitet einen solchen Block **erst, wenn jede Teilfrage beantwortet
ist** — einzelne Antworten werden bis dahin nur stehen gelassen, nicht umgesetzt. Teilweise beantwortete
Blöcke bleiben offen und werden im Board als offene Freigabe geführt.

```
Q5 · Benachrichtigungen (alle drei nötig, bevor umgesetzt wird)
Q5a. Über welchen Kanal? a) E-Mail  b) Messenger  c) beides
   * Antwort:
Q5b. Wie oft? a) sofort  b) stündliche Sammelmeldung  c) täglich
   * Antwort:
Q5c. Auch bei Warnungen oder nur bei Fehlern? a) beides  b) nur Fehler
   * Antwort:
```

<!-- check-refs:ignore -->
**Reihenfolge und Gruppierung.** Fragen stehen immer nach Nummer sortiert (`Q1`, `Q2`, `Q3a`, `Q3b`, `Q4`, …),
auch nach dem Archivieren einzelner Fragen — Lücken bleiben, es wird nie umnummeriert. Werden es viele offene
Fragen (mehr als etwa zehn), kommen Themen-Überschriften (`### Datenbank`, `### Oberfläche`) dazu; innerhalb
jedes Themas bleibt die Sortierung nach Nummer. Dringendes wird mit 🔴 markiert, nicht nach vorne sortiert.

---

## Offen (Stand {{DATUM}})

*(noch keine Fragen — Vorlage)*

---

## Erledigt (zusammengefasst)

*(noch keine)*
