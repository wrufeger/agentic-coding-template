> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# Hilfe zu AI-CONFIG.md

Ausführliche Erläuterungen zu einzelnen Schlüsseln aus `AI-CONFIG.md` — dort stehen nur noch die Tabellen
(Spalten Schlüssel/Wert/Optionen/Platzhalter/Bedeutung) und ein Verweis hierher. Diese Datei wird von keinem
Script geparst; Struktur und Schlüsselnamen der Tabellen sind allein in `AI-CONFIG.md` verbindlich, hier
steht nur die Begründung dahinter. Gegliedert nach denselben Abschnitten wie dort.

## Technik

### Testtiefe

Sie sagt, was zu einer fertigen Aufgabe dazugehört — nicht, ob getestet werden *darf*. `alles` ist der
Standard; `ohne` ist eine bewusste Entscheidung, die den Beleg nicht abschafft: „Fertig" braucht dann einen
anderen Nachweis (ein Aufruf von außen, ein Screenshot, ein Datenstand). Details je Stufe:
`docs/project/testing.md`.

## Assistenten

### Orchestrator-Modell

Der Orchestrator plant, prüft und entscheidet — gespart wird bei den Workern, nicht hier.

### Commit-Verhalten

`automatisch` committet abgenommene Arbeit selbst, `fragen` schlägt sie vor und wartet, `manuell` wartet auf
eine ausdrückliche Anweisung.

### Ideen-Ablauf

`automatisch` schreibt ein Konzept für alles, was eine Entscheidung braucht, und macht aus Kleinigkeiten
direkt eine Aufgabe — die Abkürzung wird dabei ausgesprochen. `konzept` erzwingt den vollen Weg (Konzept,
Optionen, Entscheidung) auch bei Kleinigkeiten, `direkt` überspringt ihn immer. Ablauf:
`docs/ai/checklists.md` § „Idee oder Änderungswunsch aufnehmen".

### Schreibstil

Gilt für Fragen, Aufgaben, Journal und die Antworten im Chat, nicht für Code-Kommentare (die regelt
`docs/project/coding_rules.md`). `kurz` heißt stichpunktartig und auf den Punkt, `normal` ergänzt einen Satz
Begründung dort, wo er trägt, `ausführlich` begründet vollständig und nachvollziehbar — sinnvoll, wenn jemand
mitliest, der das Projekt nicht kennt.

### Feedback

`aus` ist der Standard — ohne ausdrückliche Entscheidung verlässt nichts das Projekt. `bestätigen` zeigt vor
jedem Versand die vollständige Nutzlast und fragt; `automatisch` sendet ohne Rückfrage; `manuell` sendet nur
auf Aufruf von `/act-feedback`. Die frühere Schreibweise ohne Umlaut (`bestaetigen`, ebenso `stuendlich`,
`taeglich`, `woechentlich` bei `Feedback-Takt`) wird als Alias weiterhin angenommen. Protokolliert wird in
jedem Fall unter `docs/ai/template-feedback/` —
standardmäßig versioniert, auf Wunsch per `.gitignore` lokal (`feedback.py --enable --protokoll lokal`). Was
gesendet wird und was nicht, steht in `AGENTS.md` § „Freiwillige Rückmeldung an den Template-Autor" — nie
Dateien, nie Projektbezug, nie Namen oder Zahlen aus dem Projekt. Das Zusammenfassen und Filtern kostet ein
paar Token zusätzlich.

### Feedback-Umfang

Steuert nur, was der Assistent **selbst zusammenträgt**. Was du mit `/act-feedback <Text>` von Hand schickst,
geht unabhängig davon — dieser Kanal ist immer offen, auch bei `Feedback: aus`; dann enthält die Nachricht
ausschließlich deinen Text, ohne Projekt-Kennung und ohne Kontext. Echte Dateien aus `docs/` sind bewusst
nicht wählbar: Das widerspräche der Zusage „nie Dateien, nie Projektbezug".

### Feedback-Takt

Der Wert ist eine **Obergrenze**, keine Verpflichtung — gibt es nichts zu melden, wird auch nichts gesendet.
`sofort` meldet nach jedem brauchbaren Vorschlag, `automatisch` überlässt dem Assistenten die Wahl des
Zeitpunkts (frühestens eine Stunde nach der letzten Sendung).

### Code-Optimierung

`ein` ist eine Runde, `intensiv` bis zu zwei und nimmt Geschwindigkeit und Speicher dazu, `aus` entfernt den
Agenten `optimizer`. Der ältere Wert `streng` gilt weiter und bedeutet `intensiv`.

### MCP-Server

Die Kennungen stehen mit Anbieter, Zweck, Reifegrad und benötigten Umgebungsvariablen in
`.claude/mcp-katalog.md`. Eingetragen werden nur Server, die das Projekt wirklich braucht — jeder weitere ist
eine zusätzliche Vertrauensbeziehung und bei den schreibfähigen zusätzlich ein Risiko. Secrets kommen nie in
`.mcp.json`, sondern als `${VAR}` aus der Prozessumgebung (`CLAUDE.md` § MCP-Server); für Schreibzugriffe
gilt `AGENTS.md` § „Zugriff auf laufende Systeme".

### Globale Ablage

Was dort liegt, sehen Team, CI und Sitzungen in der Cloud **nicht** — Verbindliches gehört ins Repo. Mechanik:
`python .claude/scripts/install-global.py --plan`.

## Protokoll und Wartung / Nur beim Nachrüsten

### Wartung

`aus` ist kein Einbahnweg. Wer später wieder `ein` einträgt, bekommt mit
`python .claude/scripts/sync-config.py --apply` Ordner, Skill, Agent, Hook und `status.json` zurück — die
Dateien holt das Script per `git show` aus dem Remote `template`. Das setzt voraus, dass dieser Remote
existiert; fehlt er (etwa weil das Projekt kopiert statt geklont wurde), richtet
`python .claude/scripts/update-template.py --init` ihn ein, und `--graft` stellt die gemeinsame Historie her.
Dasselbe gilt für ein abgewähltes KI-Werkzeug, einen nachgetragenen Regelsatz und den `optimizer`
(`Code-Optimierung`).
