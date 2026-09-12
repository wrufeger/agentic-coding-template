> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# docs/ai/ — Zusammenarbeit Mensch/Assistent

Dieser Ordner ist die Arbeitsfläche der Zusammenarbeit zwischen {{AUFTRAGGEBER}} (Auftraggeber) und dem
jeweils genutzten Assistenten (Orchestrator, siehe Rollenmodell in `AGENTS.md`). Er ist **keine** Projekt-Doku
(die liegt in `docs/project/`) — hier geht es um Stand, Aufgaben, offene Fragen und Verlauf, nicht um den
IST-Zustand des Projekts selbst.

## Wer schreibt was

- Nur der **Orchestrator** schreibt in diesem Ordner (Board, Aufgaben-Marker, Ledger, Umbauliste-Einträge,
  Verbuchen von Antworten). Ein **Worker** (Sub-Agent/zweite Session) liefert Ergebnisse an den Orchestrator
  zurück, schreibt aber selbst nie hier hinein.
- {{AUFTRAGGEBER}} schreibt frei in `tasks.md` (neue Aufgaben), `questions.md` (Antworten unter den Fragen) und
  kommentiert in `backlog.md` direkt an den Vorschlägen.
- Menschlicher Originaltext ist unantastbar: nie editieren oder löschen, nur darunter kommentieren.

## Dateien

| Datei | Zweck | Wann lesen |
| :--- | :--- | :--- |
| `board.md` | Einstiegs-/Wiedereinstiegsboard: Kurzbilanz, nächster Schritt, offene Freigaben | immer zuerst |
| `tasks.md` | Aufgabenliste inkl. Tabu-Abschnitt „nur für {{AUFTRAGGEBER}}" | vor jeder neuen Aufgabe |
| `tasks_archive.md` | Erledigte Aufgaben im Volltext | bei Bedarf nachschlagen |
| `questions.md` | Offene Fragen/Entscheidungen, die auf {{AUFTRAGGEBER}} warten | nach jeder Antwort verbuchen |
| `questions_archive.md` | Beantwortete/archivierte Fragen | bei Bedarf nachschlagen |
| `ledger.md` | Sitzungsjournal mit Belegen, neueste Sitzung oben | zur Historie/Übergabe |
| `backlog.md` | Verbesserungsvorschläge, {{AUFTRAGGEBER}} entscheidet inline | vor größeren Umbauten |
| `checklists.md` | Neutrale Arbeitsanweisungen (Abschluss, Delegation, Doku prüfen und nachziehen, …) | vor der jeweiligen Aktion |

## Formregeln (verbindlich für `questions.md`/`questions_archive.md`)

- **Keine Markdown-Tabellen** — die Datei muss auch in einem einfachen Texteditor lesbar bleiben.
- Zeilen bei ca. 72 Zeichen umbrechen.
- Jede Frage einzeln, mit einer eigenen `* Antwort:`-Zeile direkt darunter.
- **Antwortmöglichkeiten vorgeben** (ja/nein oder `a)`/`b)`/`c)`, je Option eine Zeile); freier Text ist immer
  zusätzlich möglich. Eine Frage = eine Entscheidung; Längeres wird in mehrere Fragen geteilt statt in einen
  Absatz gepackt. Höchstens drei bis vier Zeilen Kontext, kein Fließtext.
- **Keine Standardantwort annehmen:** Eine unbeantwortete Frage bleibt offen und wird nie stillschweigend nach
  Einschätzung des Assistenten entschieden. Eine naheliegende Option darf als „(Empfehlung)" markiert werden.
- **Teilfragen** (`F5a`, `F5b`, …) für Entscheidungen, die nur gemeinsam umsetzbar sind: als Block
  untereinander, Verarbeitung erst, wenn **alle** beantwortet sind.
- Offene Fragen stehen oben, **nach Nummer sortiert** (nie umnummerieren, Lücken bleiben); Dringendes wird mit
  🔴 markiert statt vorgezogen. Ab etwa zehn offenen Fragen nach Themen gruppieren, innerhalb des Themas
  weiterhin nach Nummer.
- Beantwortete Fragen werden vom Orchestrator verbucht (kurze Bestätigungszeile darunter) und beim nächsten
  Aufräum-Lauf nach `questions_archive.md` verschoben.

## Nummern- und Aufgabenschema (`tasks.md`/`tasks_archive.md`)

Aufgaben laufen unter `A<n>`, Fragen unter `F<n>` — fortlaufende, projektweite Referenz-IDs, die in Ledger und
Commits zitiert werden und nie neu vergeben werden. Jede Aufgabe folgt dem festen Format (Nummer/Titel/Marker,
Ziel, Schritte, `Stand <Datum>:`) aus `tasks.md`; erledigte Aufgaben wandern mit Volltext nach
`tasks_archive.md`. Details dort, nicht hier wiederholt.

Auch Aufgaben sind **Stichpunkte, kein Fließtext**: Ziel ein Satz, Schritte je eine Zeile, eine Aufgabe = ein
Ergebnis (sonst teilen). Aufgaben im Tabu-Abschnitt „nur für {{AUFTRAGGEBER}}" tragen zusätzlich eine
`* Antwort:`-Zeile — dort meldet {{AUFTRAGGEBER}} Erledigung, delegiert die Aufgabe an den Assistenten oder
stellt eine Rückfrage.

## Tabu-Bereich

`tasks.md` enthält einen Abschnitt „Aufgaben nur für {{AUFTRAGGEBER}}". Dieser Abschnitt wird von **keinem**
Assistenten je ausgeführt (siehe `AGENTS.md`). Einträge dort dürfen ergänzt, präzisiert oder als erledigt
markiert werden, sobald {{AUFTRAGGEBER}} es meldet.
