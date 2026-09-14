> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# docs/ai/ — Zusammenarbeit Mensch/Assistent

Dieser Ordner ist die Arbeitsfläche der Zusammenarbeit zwischen {{AUFTRAGGEBER}} (Auftraggeber) und dem
jeweils genutzten Assistenten (Orchestrator, siehe Rollenmodell in `AGENTS.md`). Er ist **keine** Projekt-Doku
(die liegt in `docs/project/`) — hier geht es um Stand, Aufgaben, offene Fragen und Verlauf, nicht um den
IST-Zustand des Projekts selbst.

**Diese Datei ist die Formvorschrift für alle Dateien des Ordners.** Die Arbeitsdateien selbst tragen nur
einen kurzen Kopf für den Menschen, der sie öffnet — Regeln, Formate und Beispiele stehen hier. Das ist
Absicht: `tasks.md`, `questions.md` und `backlog.md` werden im Alltag von Hand gelesen und beschrieben, und
wer dort etwas eintragen will, soll nicht erst durch sechzig Zeilen Anleitung scrollen.

## Wer schreibt was

- Nur der **Orchestrator** schreibt in diesem Ordner (Board, Aufgaben-Marker, Ledger, Backlog-Einträge,
  Verbuchen von Antworten). Ein **Worker** (Sub-Agent/zweite Session) liefert Ergebnisse an den Orchestrator
  zurück, schreibt aber selbst nie hier hinein.
- {{AUFTRAGGEBER}} schreibt frei in `tasks.md` (neue Aufgaben), `questions.md` (Antworten unter den Fragen) und
  kommentiert in `backlog.md` direkt an den Vorschlägen.
- Menschlicher Originaltext ist unantastbar: nie editieren oder löschen, nur darunter kommentieren.

## Antworten quittieren

Jede Antwort von {{AUFTRAGGEBER}} — in `questions.md`, in den `* Antwort:`-Zeilen von `tasks.md` oder in
jeder anderen Datei — wird **direkt darunter** quittiert:

```text
✅ **<Datum Uhrzeit>** — <was daraus folgte, mit Verweis auf ADR, Aufgabe oder Backlog-Punkt>
```

Keine Sammelverbuchung am Dateiende: {{AUFTRAGGEBER}} muss an der einzelnen Stelle sehen, ob seine Antwort
angekommen und umgesetzt ist. Sein eigener Wortlaut bleibt dabei unverändert stehen — quittiert wird
ausschließlich darunter.

## Dateien

| Datei | Zweck | Wann lesen |
| :--- | :--- | :--- |
| `board.md` | Einstiegs-/Wiedereinstiegsboard: Kurzbilanz, nächster Schritt, ausstehende Freigaben | immer zuerst |
| `tasks.md` | Aufgabenliste inkl. Tabu-Abschnitt „nur für {{AUFTRAGGEBER}}" | vor jeder neuen Aufgabe |
| `tasks_archive.md` | Erledigte Aufgaben im Volltext | bei Bedarf nachschlagen |
| `questions.md` | Offene Fragen/Entscheidungen, die auf {{AUFTRAGGEBER}} warten | nach jeder Antwort verbuchen |
| `questions_archive.md` | Beantwortete/archivierte Fragen | bei Bedarf nachschlagen |
| `ledger.md` | Sitzungsjournal mit Belegen, neuester Eintrag oben | zur Historie/Übergabe |
| `backlog.md` | Verbesserungsvorschläge, {{AUFTRAGGEBER}} entscheidet inline | vor größeren Umbauten |
| `checklists.md` | Neutrale Arbeitsanweisungen (Abschluss, Delegation, Doku prüfen und nachziehen, …) | vor der jeweiligen Aktion |
| `resources.md` | Quellen zu Agentic Coding — vom Template gepflegt | beim Einarbeiten |

## Statuszeile über jeder Datei

Jede Doku-Datei beginnt mit `> Datenstand: JJJJ-MM-TT – Status: <wort>`. Welche Wörter erlaubt sind und was
das Datum bedeutet, steht einmal für alle Doku-Ordner in `../README.md` § „Konventionen für diese Doku".

## Board (`board.md`)

Der erste Blick jeder Sitzung, und deshalb **die kürzeste Datei im Ordner** — eine Bildschirmseite, nicht mehr.
Drei Abschnitte, jeder mit einer klaren Abgrenzung:

- **Kurzbilanz** — wo das Projekt gerade steht, in wenigen Zeilen. Maßstab ist nicht „interessant", sondern
  „ändert etwas an der nächsten Entscheidung". Was nur erzählt, wie es dazu kam, gehört ins `ledger.md`;
  Kennzahlen und Befunde gehören nach `docs/project/`.
- **Als Nächstes** — ausschließlich das, was noch aussteht, in der Reihenfolge, in der es angefasst wird.
  **Kein erledigter Punkt, keine durchgestrichene Zeile, kein „erledigt am …".** Fertiges verschwindet hier
  vollständig; sein Beleg steht im `ledger.md`, sein Ergebnis in `tasks_archive.md`.
- **Ausstehende Freigaben** — nur Fragen, die *jetzt* auf eine Antwort von {{AUFTRAGGEBER}} warten, je eine
  Zeile mit Nummer und dem, was sie blockiert. Beantwortete Fragen werden hier gelöscht, nicht abgehakt.

Das Board wird bei jeder Berührung **überschrieben**, nicht ergänzt. Es ist eine Momentaufnahme; die Historie
führt das `ledger.md`.

## Aufgaben (`tasks.md`, `tasks_archive.md`)

<!-- check-refs:ignore -->
Jede Aufgabe bekommt eine fortlaufende Nummer mit Präfix `T<n>` (z. B. `T7`) — projektweite Referenz-ID, die
in Ledger und Commits zitiert und **nie neu vergeben** wird, auch nach dem Archivieren nicht.

**Offene Aufgabe:**

```text
- [ ] **T7 · Kurztitel der Aufgabe** 🔄
  Ziel: ein Satz, woran man erkennt, dass die Aufgabe erledigt ist.
  Schritte:
  1. …
  2. …
  Offen: was noch fehlt, um anfangen oder fertig werden zu können — fehlende Vorgaben, Zugänge,
    unbeantwortete Fragen (`Q<n>`), abhängige Aufgaben (`T<n>`). Entfällt, wenn nichts offen ist.
  Entschieden: was bereits feststeht und nicht neu verhandelt wird, je Punkt eine Zeile mit Verweis
    (`ADR-<n>`, `Q<n>`). Entfällt, wenn nichts entschieden wurde.
  Stand 2026-01-31: eine Zeile — wo die Aufgabe gerade steht.
```

**Erledigte Aufgabe** — Haken gesetzt, Marker ✅, und statt Schritten das Ergebnis:

```text
- [x] **T7 · Kurztitel der Aufgabe** ✅
  Ziel: unverändert stehen lassen.
  Ergebnis: was tatsächlich getan wurde, in ein bis drei Zeilen, mit Beleg (Commit-Hash, Datei, Testlauf).
  Stand 2026-02-03: erledigt.
```

- **Der Entscheidungsverlauf gehört nicht in die Aufgabe.** Wie eine Entscheidung zustande kam, steht in
  `../project/decisions.md` und in `questions_archive.md`; was währenddessen passierte, im `ledger.md`. In der
  Aufgabe steht nur das **Ergebnis** — sonst wächst jede Aufgabe zu einem Protokoll, das niemand überfliegt.
- Die `Stand <Datum>:`-Zeile wird bei jeder Berührung **aktualisiert** und bleibt **eine** Zeile; ältere
  Stände werden ersetzt, nicht gestapelt.
- Erledigte Aufgaben (✅) wandern **mit Volltext** nach `tasks_archive.md` (nicht löschen) — spätestens beim
  nächsten Lauf der Checkliste „Aufgabe abschließen", damit `tasks.md` nur zeigt, was noch aussteht.
- Titel eine Zeile, `Ziel:` ein Satz, Schritte als nummerierte Stichpunkte im Imperativ. Keine Absätze, keine
  Prosa, keine Tabellen. `Offen:` und `Entschieden:` sind Stichpunktlisten, keine Begründungen.
- Eine Aufgabe = ein Ergebnis. Braucht sie mehr als etwa fünf Schritte oder mehrere Entscheidungen, wird sie
  geteilt. Unklarheiten werden nicht in der Aufgabe ausdiskutiert, sondern zu einer Frage in `questions.md`.

## Fragen (`questions.md`, `questions_archive.md`)

- **Keine Markdown-Tabellen** — die Datei muss auch in einem einfachen Texteditor lesbar bleiben. Zeilen bei
  ca. 72 Zeichen umbrechen.
- Jede Frage einzeln, mit einer eigenen `* Antwort:`-Zeile direkt darunter. Nummer mit Präfix `Q<n>`.
- **Antwortmöglichkeiten vorgeben** (ja/nein oder `a)`/`b)`/`c)`, je Option eine Zeile mit der Folge in drei
  bis fünf Wörtern); freier Text ist immer zusätzlich möglich. Höchstens drei bis vier Zeilen Kontext vor der
  Frage, kein Fließtext, keine Herleitung. Eine Frage = eine Entscheidung.
- **Keine Standardantwort annehmen:** Eine unbeantwortete Frage bleibt offen und wird nie stillschweigend nach
  Einschätzung des Assistenten entschieden. Eine naheliegende Option darf als „(Empfehlung)" markiert werden —
  beantwortet ist sie damit nicht.
- Blockiert eine Frage die Arbeit, wird sie mit 🔴 markiert und im Board unter „Ausstehende Freigaben"
  geführt; der Assistent arbeitet in der Zwischenzeit an etwas anderem weiter.
- Offene Fragen stehen oben, **nach Nummer sortiert** (nie umnummerieren, Lücken bleiben). Ab etwa zehn
  offenen Fragen nach Themen gruppieren, innerhalb des Themas weiterhin nach Nummer.

```text
Q3. Soll der Import fehlende Pflichtfelder überspringen oder abbrechen? 🔴
   a) überspringen, Fehler ins Log — Import läuft durch (Empfehlung)
   b) abbrechen — nichts wird importiert, Ursache zuerst klären
   Blockiert T12, solange offen.
   * Antwort:
```

**Teilfragen (`Q5a`, `Q5b`, …).** Hängen mehrere Einzelentscheidungen so zusammen, dass die Umsetzung erst
beginnen kann, wenn **alle** beantwortet sind, bekommen sie dieselbe Nummer mit Buchstaben-Suffix und stehen
als Block untereinander. Der Assistent verarbeitet einen solchen Block **erst, wenn jede Teilfrage beantwortet
ist**; teilweise beantwortete Blöcke bleiben offen.

```text
Q5 · Benachrichtigungen (alle drei nötig, bevor umgesetzt wird)
Q5a. Über welchen Kanal? a) E-Mail  b) Messenger  c) beides
   * Antwort:
Q5b. Wie oft? a) sofort  b) stündliche Sammelmeldung  c) täglich
   * Antwort:
Q5c. Auch bei Warnungen oder nur bei Fehlern? a) beides  b) nur Fehler
   * Antwort:
```

**Archivieren.** Eine beantwortete Frage wird verbucht (kurze Bestätigungszeile darunter, wohin die Antwort
gewirkt hat) und beim **nächsten** Lauf der Checkliste „Aufgabe abschließen" nach `questions_archive.md`
verschoben. Daraus folgt: Alle Fragen eines Archivierungslaufs tragen **dasselbe Verschiebedatum** — das
Datum der Antwort steht in der Frage, das Datum des Verschiebens an der Gruppe. Stehen im Archiv Fragen mit
uneinheitlichen Verschiebedaten, wurde nicht laufweise archiviert, sondern nachträglich aus der Erinnerung.

## Backlog (`backlog.md`)

Priorisierte Verbesserungsvorschläge, Sicherheit zuerst. Vorschläge sind **Angebote, keine Aufträge**: Umsetzung
erst, wenn daraus eine Aufgabe in `tasks.md` geworden ist. Der bestehende Codestil bleibt erhalten, solange er
kein echtes Problem verursacht.

- Jeder Punkt trägt eine Nummer, zitiert wird sie als `B<n>`. Nummern bleiben stabil, auch nach dem Erledigen.
- {{AUFTRAGGEBER}} entscheidet **direkt am Punkt** — „-> machen", „-> später", „-> nein, weil …".
- **Kommentare, Rückfragen und Umbau-Überlegungen sammeln sich nicht am Dateiende.** Ein Anhang „Anmerkungen"
  unter dreißig Backlog-Punkten wird zuverlässig übersehen. Wird beim Durchgehen etwas offen, entsteht daraus
  sofort das passende Artefakt: eine **Frage** in `questions.md`, wenn eine Entscheidung fehlt, eine
  **Aufgabe** in `tasks.md`, wenn die Entscheidung steht — und am Backlog-Punkt bleibt nur der Verweis
  (`-> siehe Q<n>`). Der Backlog ist eine Liste von Vorschlägen, kein Diskussionsfaden.
- Hierher schreibt der Orchestrator auch die Befunde der optionalen Code-Analyse beim Nachrüsten (Checkliste
  „Projekt nachrüsten"): je Punkt Befund, Fundstelle `Datei:Zeile`, Vorschlag, geschätzter Aufwand.

**Liste oder Tabelle?** Bis etwa fünfzehn Punkte genügt eine nummerierte Liste. Darüber wird sie
unübersichtlich — dann in eine Tabelle überführen, ohne die Nummern anzufassen:

| Spalte | Inhalt |
| :--- | :--- |
| `ID` | die Nummer, für immer stabil |
| Titel | eine Zeile, worum es geht |
| Anweisung | `machen` · `nicht machen` · `offen` — hier entscheidet {{AUFTRAGGEBER}} |
| Prio | `⌀ x,y (u/o)` — Mittelwert, dahinter die beiden Einzelwerte (siehe unten) |
| Zeitpunkt | wann es dran ist: `sofort` · `nächste Welle` · `vor Release` · `später` · `offen`, oder ein Datum |
| Aufwand | `S`/`M`/`L` oder die Einheit des Projekts |
| Bezug | `T<n>`, `Q<n>`, ADR, Feature, Story, Konzept |
| Status | `offen` · `erledigt` |
| Fundstelle | `Datei:Zeile` plus Stichwort — der Beleg, ohne den ein Punkt in sechs Monaten nicht mehr nachvollziehbar ist |

Die letzte Spalte ist die wichtigste und wird am ehesten weggelassen: Ohne sie steht in der Zeile eine
Behauptung ohne Nachweis. Erledigte Punkte bleiben mit Status `erledigt` stehen, damit Nummerierung und
Historie erhalten bleiben — gelöscht wird nichts.

**Priorität wird von beiden Seiten vergeben.** {{AUFTRAGGEBER}} kennt den Geschäftswert, {{ORCHESTRATOR}} den
technischen Druck — beide Zahlen stehen nebeneinander, und sortiert wird nach ihrem Mittelwert:

| Stufe | Zahl | Wann |
| :--- | ---: | :--- |
| kritisch | 4 | Sicherheit, Datenverlust, Rechtsverstoß — duldet keinen Aufschub |
| wichtig | 3 | blockiert anderes oder wächst mit der Zeit |
| normal | 2 | soll gemacht werden, wenn Platz ist |
| niedrig | 1 | schön, aber verzichtbar |

Schreibweise in der Spalte: `⌀ 3,5 (4/3)` — Mittelwert, dahinter {{AUFTRAGGEBER}}s und {{ORCHESTRATOR}}s
Wert in dieser Reihenfolge. Fehlt eine der beiden Einschätzungen, steht dort `-` und der Mittelwert ist der
vorhandene Wert; er wird **nicht** geraten.

**Weichen die beiden um mehr als eine Stufe ab, steht der Grund in einer Zeile am Punkt.** Das ist keine
Förmlichkeit: Eine Lücke von zwei Stufen heißt fast immer, dass eine Seite etwas weiß, das die andere nicht
hat — eine Frist, ein Risiko im Code, eine geplante Änderung. Diese Information geht verloren, wenn nur der
Mittelwert überlebt.

**Sortierung:** zuerst nach **Thema** (Abschnittsüberschriften wie `## Sicherheit`, `## Datenmodell`), innerhalb
des Themas absteigend nach Mittelwert. Die Themen ordnen den Blick, die Priorität ordnet die Arbeit. Bei
gleichem Mittelwert entscheidet der Zeitpunkt, dann die kleinere Nummer.

## Ledger (`ledger.md`)

Sitzungsjournal mit Belegen. **Neuester Eintrag oben** — wer die Datei öffnet, sieht zuerst, was zuletzt
geschah, und muss nicht ans Ende scrollen. Das gilt auf beiden Ebenen: die Tagesüberschriften absteigend, und
innerhalb eines Tages ebenfalls der jüngste Lauf zuerst.

Überschriften tragen die **Uhrzeit**, nicht eine Laufnummer:

```text
## 2026-02-03

### 16:20 — Kysely-Umstellung, Schritt 2
### 09:05 — Schema-Drift behoben
```

Eine Laufnummer („3. Lauf") sagt niemandem etwas, sobald der Tag vorbei ist; die Uhrzeit ordnet die Einträge
auch dann noch ein und passt zu den Zeitstempeln in `ai.log` und der Git-Historie.

**Verdichtungsregeln:**

- Heutiger Tag und der Vortag: detailliert, alle Läufe eines Tages unter einer Tagesüberschrift, aber auf das
  Wesentliche gekürzt.
- Älter als 2 Tage bis 1 Woche: ein Eintrag je Tag, max. 8 Stichpunkte.
- Älter als 1 Woche: ein Eintrag je Monat (Abschnitt „Archiv" ganz unten).
- Commit-Hashes, Nummern (`T<n>`/`Q<n>`/`B<n>`), Versionsnummern, Dateipfade und Kennzahlen werden nie
  weggekürzt.

## Querverweise

Die Kürzel werden überall im Repo zitiert. Damit sie nutzbar bleiben, gilt:

| Kürzel | Bedeutung | Ziel |
| :--- | :--- | :--- |
| `T<n>` | Aufgabe | `tasks.md`, nach dem Erledigen `tasks_archive.md` |
| `Q<n>` | Frage | `questions.md`, nach der Antwort `questions_archive.md` |
| `ADR-<n>` | Architekturentscheidung | `../project/decisions.md` |
| `S<n>` | Story | `../project/stories/S<n>-….md` |
| `B<n>` | Backlog-Punkt | `backlog.md` |

- **Kürzel bleiben nackt, es wird nicht verlinkt.** Ein Markdown-Link kann in dieser Struktur nur auf die
  Datei zeigen, nicht auf den Eintrag — Aufgaben, Fragen und Backlog-Punkte sind Listen- oder Tabellenzeilen
  ohne eigene Überschrift, also ohne Anker. Wer `B22` anklickt, landet am Kopf von `backlog.md` und sucht von
  dort doch wieder selbst. Die Tabelle oben sagt, in welcher Datei zu suchen ist; die Suche nach dem Kürzel
  findet den Eintrag schneller als ein Link, der nur den Dateinamen wiederholt.
- **Nummern werden nie neu vergeben**, auch nicht nach dem Archivieren — ein Verweis von vor einem halben Jahr
  muss weiterhin auf dasselbe zeigen.
- `python .claude/scripts/check-refs.py` prüft alle Verweise: Was zitiert wird, aber nicht existiert (toter
  Verweis), und was existiert, aber nirgends zitiert wird. Gehört in den Lauf „Doku prüfen und nachziehen".

## Tabu-Bereich

`tasks.md` enthält einen Abschnitt „Aufgaben nur für {{AUFTRAGGEBER}}". Dieser Abschnitt wird von **keinem**
Assistenten je ausgeführt (siehe `AGENTS.md`). Einträge dort dürfen ergänzt, präzisiert oder als erledigt
markiert werden, sobald {{AUFTRAGGEBER}} es meldet.

## Was hier *nicht* hingehört

Dieser Ordner hat **keine freien Dateien**. Wer eine Analyse, ein Konzept oder eine längere Abwägung
unterbringen will, legt sie nicht als neue Datei daneben, sondern an einen der vorgesehenen Orte:

| Was | Wohin |
| :--- | :--- |
| Konzept, Analyse, Abwägung, Umbauplan | `../project/konzepte/` — eine Datei je Thema, siehe README dort |
| Abgegrenztes Vorhaben mit Umfang und Abnahme | `../project/stories/S<n>-….md` |
| Ergebnis einer Entscheidung | `../project/decisions.md` (ADR) |
| IST-Zustand des Projekts | die feste Dateiliste in `../project/` |

Der Grund ist nicht Ordnungsliebe: Alles in `docs/ai/` ist **flüchtig** — Aufgaben werden archiviert, Fragen
beantwortet, das Board überschrieben. Ein Konzept, das hier liegt, wird beim nächsten Aufräumen entweder
mitentsorgt oder bleibt als Fremdkörper zurück, den keine Checkliste je wieder prüft.
