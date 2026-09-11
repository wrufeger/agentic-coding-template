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
| `questions.md` | Offene Fragen/Entscheidungen, die auf {{AUFTRAGGEBER}} warten | nach jeder Antwort verbuchen |
| `questions_archive.md` | Beantwortete/archivierte Fragen | bei Bedarf nachschlagen |
| `ledger.md` | Sitzungsjournal mit Belegen, neueste Sitzung oben | zur Historie/Übergabe |
| `backlog.md` | Verbesserungsvorschläge, {{AUFTRAGGEBER}} entscheidet inline | vor größeren Umbauten |
| `checklists.md` | Neutrale Arbeitsanweisungen (Abschluss, Delegation, Doku-Nachzug, …) | vor der jeweiligen Aktion |

## Formregeln (verbindlich für `questions.md`/`questions_archive.md`)

- **Keine Markdown-Tabellen** — die Datei muss auch in einem einfachen Texteditor lesbar bleiben.
- Zeilen bei ca. 72 Zeichen umbrechen.
- Jede Frage einzeln, mit einer eigenen `* Antwort:`-Zeile direkt darunter.
- Offenes steht oben, Dringendes zuerst (Markierung z. B. 🔴).
- Beantwortete Fragen werden vom Orchestrator verbucht (kurze Bestätigungszeile darunter) und beim nächsten
  Aufräum-Lauf nach `questions_archive.md` verschoben.

## Tabu-Bereich

`tasks.md` enthält einen Abschnitt „Aufgaben nur für {{AUFTRAGGEBER}}". Dieser Abschnitt wird von **keinem**
Assistenten je ausgeführt (siehe `AGENTS.md`). Einträge dort dürfen ergänzt, präzisiert oder als erledigt
markiert werden, sobald {{AUFTRAGGEBER}} es meldet.
