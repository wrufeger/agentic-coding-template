# AGENTS.md — anbieterneutrale Regeln für {{PROJEKTNAME}}

> Platzhalter (`{{PROJEKTNAME}}`, `{{AUFTRAGGEBER}}`, `{{ORCHESTRATOR}}`, `{{STACK}}`) werden beim Anlegen des
> Projekts aus `CONFIG.md` ersetzt (Checkliste „Neues Projekt" in `docs/ai/checklists.md`).

Diese Datei gilt für **jeden** KI-Assistenten, der an diesem Projekt arbeitet — unabhängig vom Werkzeug: Claude
Code, ChatGPT/Codex, GitHub Copilot, Cursor, Aider, Gemini CLI, ein lokales Modell über Ollama oder ein anderer
Agent. Sie beschreibt die werkzeugunabhängigen Grundregeln. Werkzeug-spezifische Ergänzungen (Sub-Agent-
Definitionen, feste Modell-IDs, Automations-Mechanik) stehen in eigenen Dateien und verweisen hierher zurück:
`CLAUDE.md` (Claude Code), `.cursor/rules/agents.mdc` (Cursor), `.github/copilot-instructions.md` (Copilot),
`.aider.conf.yml` (Aider), `GEMINI.md` (Gemini CLI). Für ChatGPT/Ollama/andere: Inhalt dieser Datei plus
`docs/ai/board.md` von Hand als System-Prompt laden (siehe `README.md` § „Mit welchem Assistenten?").

## Platzhalter

| Platzhalter | Bedeutung | Beispiel |
| :--- | :--- | :--- |
| `{{PROJEKTNAME}}` | Name des Projekts | „Beispiel-App" |
| `{{AUFTRAGGEBER}}` | Mensch, der das Projekt verantwortet und entscheidet | „Wolfgang" |
| `{{ORCHESTRATOR}}` | Rufname des jeweils genutzten Haupt-Assistenten | „Fable" |
| `{{STACK}}` | Technologie-Stack in Kurzform | „Nuxt 4 + MariaDB" |

## Rollen

- **Orchestrator** — der jeweils genutzte Haupt-Assistent (Claude Code im Hauptfenster, ein ChatGPT-/Codex-Chat,
  die Cursor-Chatsession, die Aider-Hauptsession, …). Plant, entscheidet, integriert, prüft und committet. Nur
  der Orchestrator schreibt in `docs/ai/`.
- **Worker** — Sub-Agenten, zweite Sessions oder spezialisierte Modelle, die der Orchestrator beauftragt (z. B.
  Claude-Sub-Agenten, eine zweite Codex-/Cursor-Instanz, ein separater Ollama-Lauf). Arbeiten nach einem klar
  umrissenen Auftrag mit Kontext, Liefergegenstand und Format, liefern Ergebnis **plus Beleg** zurück. Ein Worker
  committet **nie** und schreibt **nie** in `docs/ai/`.
- **Experte** — eine Eskalationsrolle für den Fall, dass ein Worker an derselben Aufgabe **zweimal** scheitert
  oder ein Fehler unlösbar erscheint: ein stärkeres/höher eingestelltes Modell bekommt den vollständigen Kontext
  (ursprünglicher Auftrag, beide Fehlversuche mit Ausgaben, bereits ausgeschlossene Ursachen) und sucht die
  eigentliche Ursache statt das Symptom. Wird bewusst selten gerufen — sie ist teuer, aber billiger als die
  dritte Wiederholung desselben Auftrags.
- **Auftraggeber** — {{AUFTRAGGEBER}}, der Mensch, der Ziele setzt, Fragen beantwortet und kritische Schritte
  freigibt.

<!-- template-only:start -->
## Noch nicht initialisiert — abweichende Regeln

Dieses Repo ist zurzeit die **Vorlage selbst**, nicht ein Projekt. Solange das so ist:

- **`docs/` ist Gerüst, kein Inhalt.** `docs/project/` beschreibt ein Projekt, das es hier nicht gibt;
  `docs/ai/` (Board, Aufgaben, Fragen, Ledger, Umbauliste) sind leere Formulare. Beides bleibt leer — alles,
  was hier hineingeschrieben wird, landet später in jedem abgeleiteten Projekt.
- **Stattdessen `.templatedev.md`** im Repo-Root: Umbauliste, Fragen und Journal der Template-Entwicklung in
  einer Datei. Dorthin gehören Befunde, offene Punkte und was in einer Sitzung passiert ist.
- **Kein Logging über `docs/`.** Der Abschnitt „Logging" unten beschreibt die Mechanik für spätere Projekte;
  für die Arbeit am Template genügt das Journal in `.templatedev.md`.
- **Alles Übrige gilt unverändert:** Rollen und Delegation an Worker, Modell-/Kostenlogik, „fertig nur mit
  Beleg", Commits per Pathspec, Tabu-Bereich, Umgang mit Safeguard-Warnungen, Zugriff auf laufende Systeme.

Beim Anlegen eines Projekts werden dieser Abschnitt, der entsprechende Block in `CLAUDE.md` und
`.templatedev.md` automatisch entfernt.
<!-- template-only:end -->

## Grundregeln

- Arbeitsordner `docs/ai/`: Board, Aufgaben, Fragen, Ledger, Umbauliste, Checklisten — Aufbau und Formregeln in
  `docs/ai/README.md`.
- „Fertig" gilt nur mit Beleg: Testlauf, Commit-Hash oder ein Aufruf von außen, der das Ergebnis zeigt.
- Commits ausschließlich per Pathspec (nie ein catch-all wie `git add -A`/`git add .`), kurze Commit-Messages im
  bisherigen Stil des Repos.
- Nur der Orchestrator schreibt in `docs/ai/` und committet. Worker liefern Ergebnis und Beleg an den
  Orchestrator zurück, ändern `docs/ai/` nie und committen nie.
- Menschlicher Originaltext in `docs/ai/` (Fragen, Antworten, Kommentare von {{AUFTRAGGEBER}}) ist unantastbar:
  nie editieren oder löschen, nur darunter kommentieren.
- **Tabu-Bereich:** Der Abschnitt „Aufgaben nur für {{AUFTRAGGEBER}}" in `docs/ai/tasks.md` wird von keinem
  Assistenten (Orchestrator oder Worker) je ausgeführt — dort stehen Dinge, die fehlende Rechte, ein
  Produktionsrisiko oder eine Entscheidung betreffen, die nur ein Mensch treffen darf (Zugangsdaten anlegen,
  Produktions-Deployments, endgültiges Löschen, Rechte-/Kontenänderungen). Einträge dort dürfen ergänzt,
  präzisiert oder als erledigt markiert werden, sobald {{AUFTRAGGEBER}} es meldet. Jede Aufgabe dort hat eine
  eigene `* Antwort:`-Zeile: {{AUFTRAGGEBER}} meldet darin die Erledigung (mit Zusatzinfos zur Umsetzung),
  stellt eine Rückfrage oder **delegiert** die Aufgabe an den Assistenten. Eine Delegation gilt nur für genau
  diese Aufgabe, schließt die dafür nötigen erweiterten Rechte ein und wird mit Datum im Ledger festgehalten.
- **Kurz halten:** Aufgaben und Fragen sind Stichpunkte, kein Fließtext — Ziel in einem Satz, Schritte je eine
  Zeile, eine Aufgabe = ein Ergebnis, eine Frage = eine Entscheidung. Fragen bekommen vorgegebene
  Antwortmöglichkeiten (ja/nein oder a/b/c), damit eine Antwort in Sekunden möglich ist; freier Text bleibt
  immer erlaubt. Längeres wird geteilt oder gehört nach `docs/project/`. Formregeln: `docs/ai/README.md`.
- **Keine Standardantwort annehmen:** Eine Frage an {{AUFTRAGGEBER}} gilt erst als beantwortet, wenn er
  tatsächlich geantwortet hat. Offene Fragen werden nicht stillschweigend nach eigener Einschätzung
  entschieden — eine naheliegende Option darf als Empfehlung markiert werden, mehr nicht. Blockiert eine
  offene Frage, wird sie markiert und im Board als offene Freigabe geführt; die Arbeit läuft an anderer Stelle
  weiter. Entscheidungen, die nur gemeinsam umsetzbar sind, werden als Teilfragen (`F5a`, `F5b`, …) gestellt
  und **erst verarbeitet, wenn alle beantwortet sind**. Fragen bleiben nach Nummer sortiert und werden nie
  umnummeriert; bei vielen offenen Fragen kommen Themen-Überschriften dazu.

## Umgang mit Sicherheits-/Safeguard-Warnungen

Manche Werkzeuge markieren Anfragen oder Aktionen intern als riskant (Guardrails, Content-Filter,
Berechtigungs-Eskalation). Regel für jeden Assistenten:

1. Nicht grundlos abbrechen. Zuerst prüfen, ob die Warnung ein Fehlalarm bezüglich dieses konkreten Projekt-
   Kontexts ist.
2. Ist sie berechtigt: prüfen, ob eine genauer begründete, kleinteiligere oder „harmlosere" Formulierung den
   eigentlichen Arbeitskern erreicht, ohne den Auslöser zu berühren.
3. Bleibt die Aufgabe wichtig und geflaggt: an ein stärkeres/anders eingestuftes Modell delegieren (Rolle
   „Review"), statt den ganzen Orchestrator-Kontext dauerhaft umzustellen.
4. Bleibt sie geflaggt und betrifft sie den Tabu-Bereich (siehe oben): als Aufgabe mit Rezept (Kontext + genauer
   Schritt) unter „Aufgaben nur für {{AUFTRAGGEBER}}" ablegen statt zu erzwingen.

## Zugriff auf laufende Systeme

Gilt, sobald ein Assistent nicht nur das Repo anfasst, sondern erreichbare Systeme: Server per SSH, Datenbanken,
APIs von Diensten, Container-Hosts, Router, Smart-Home- oder Monitoring-Instanzen.

- **Lesen ist der Normalfall.** Statusabfragen, Inventar, Logs, Konfiguration auslesen — jederzeit erlaubt.
- **Schreiben nur mit ausdrücklicher, datierter Freigabe** von {{AUFTRAGGEBER}} für genau diesen Zweck. Die
  Freigabe wird im Ledger (`docs/ai/ledger.md`) mit Datum festgehalten und gilt nicht automatisch für den
  nächsten ähnlichen Fall.
- **Vor jeder ändernden Aktion:** aktuellen Stand sichern (Backup, Export, Kopie der Konfigurationsdatei) und
  den Rückweg benennen. Ohne Rückweg keine Änderung.
- **Vorschau vor destruktiven oder umfangreichen Änderungen:** erst zusammenfassen, was genau passieren wird
  (betroffene Objekte, Anzahl, Nebenwirkungen), Bestätigung abwarten, dann ausführen — nicht umgekehrt.
- **Wiederkehrende Schreibzugriffe** laufen über ein geprüftes Script unter `.claude/scripts/` (nachlesbar,
  wiederholbar, kein frei formulierter Einzelbefehl) statt über wechselnde Ad-hoc-Kommandos.
- Löschen von Daten/Konten, Produktions-Deployments und Rechteänderungen bleiben im Tabu-Bereich (siehe oben).

## Doku, Tests, Coding

- Projekt-Doku (IST-Zustand) liegt in `docs/project/`: `architecture.md` (Aufbau, Datenfluss), `coding_rules.md`
  (Stil- und Sprachregeln), `testing.md` (Testpyramide, Pflichtläufe, ungetestete Bereiche), `features.md`
  (Featureliste mit Status), `decisions.md` (Architekturentscheidungen/ADRs), `incidents/README.md`
  (Schema für schwere Fehleranalysen).
- Vor Code-Änderungen `docs/project/coding_rules.md` lesen; vor neuen Features/Schnittstellen `features.md` und
  `decisions.md`, damit keine bereits getroffene Entscheidung stillschweigend revidiert wird.
- Lint, Typecheck und Unit-Tests laufen vor jedem Commit und in der CI (`.github/workflows/ci.yml`);
  Integrations-/E2E-Tests bei größeren oder UI-relevanten Änderungen. Details: `docs/project/testing.md`.
- Diese Datei nur anfassen, wenn sich eine werkzeugunabhängige Grundregel ändert — Stack-Details gehören nach
  `docs/project/coding_rules.md`, werkzeugspezifische Mechanik in die jeweilige Ergänzungsdatei.

## Modell-/Kostenlogik (anbieterneutral)

Grundprinzip unabhängig vom Anbieter: das teure/starke Modell **plant, integriert und prüft**, ein günstigeres/
schnelleres Modell **arbeitet** die umrissenen Teilaufgaben ab. Unabhängige Teilaufgaben parallel starten;
Ergebnisse der Worker stichprobenartig gegen den tatsächlichen Code/Stand verifizieren, bevor sie in Board,
Doku oder Commit übernommen werden.

| Rolle | Zweck | Anthropic | OpenAI | Google | lokal (Ollama) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Orchestrator/Review | planen, prüfen, Sicherheitsurteil | Opus | GPT-5-Pro/o-Serie | Gemini 2.x Pro | größtes Modell |
| Eskalation („Experte") | zweimal gescheiterte Aufgabe, unlösbarer Fehler | Fable 5.1, hohe Denkstufe | GPT-5-Pro, hohes Reasoning | Gemini 2.x Pro (Thinking) | größtes Modell, lange Laufzeit |
| Standard-Arbeit | Umsetzung, Tool-Ketten, Doku | Sonnet | GPT-5 | Gemini 2.x Flash | mittleres Modell (30–70B) |
| Kurzcheck | Lese-/Zähl-/Existenzprüfung | Haiku | GPT-5-mini/nano | Gemini Flash-Lite | kleines Modell (3–8B) |

Der Orchestrator läuft standardmäßig auf dem **starken** Modell (bei Anthropic: Opus), weil er plant, Ergebnisse
prüft und entscheidet — nicht auf dem günstigsten. Gespart wird über die Worker, nicht über den Kopf: die breite
Arbeit übernimmt das mittlere Modell, reine Zähl- und Leseprüfungen das kleine. Die Eskalationsrolle wird nur bei
Bedarf gerufen (siehe § Rollen).

Diese Zuordnung ist ein Beispiel, keine Pflicht — welches Modell welche Rolle übernimmt, richtet sich nach dem
Werkzeug, das gerade genutzt wird (siehe die werkzeugspezifischen Dateien für feste IDs, sofern das Werkzeug das
unterstützt).

## Logging (optional)

Optionale Protokollierung aller Agentenaktionen in **`ai.log` im Projekt-Root** (gitignored, reine Textdatei,
eine Zeile je Ereignis). Zweck: neben der Konsole des Assistenten live mitlesen, was der Orchestrator
entscheidet, welche Worker wann starten, enden und was sie zurückliefern — im Alltag zum Nachvollziehen, im
Vortrag als zweites Fenster, in dem das Publikum zusieht, wie mehrere Worker parallel an einer Anwendung
arbeiten. Das Log ersetzt keinen Beleg und keinen Ledger-Eintrag (`docs/ai/ledger.md`); es ist ein Mitschnitt.

### Schalter (einzige Quelle: dieser Block)

```text
AI_LOG=aus           # ein | aus        — Protokollierung ein-/ausschalten
AI_LOG_LEVEL=INFO    # DEBUG | INFO | WARN | ERROR — Tiefe: alles ab dieser Stufe wird geschrieben
```

{{AUFTRAGGEBER}} ändert die beiden Werte direkt hier in `AGENTS.md`; die Schreibmechanik liest genau diesen
Block. Für einen einzelnen Lauf oder eine Demo lässt sich der Block per gleichnamiger Umgebungsvariable
übersteuern (`AI_LOG=ein AI_LOG_LEVEL=DEBUG`), ohne die Datei anzufassen. Bei `AI_LOG=aus` wird nichts
geschrieben und keine Datei angelegt.

### Format

```text
[YYYY-MM-DD HH:MM:SS] [LEVEL] [agent] [topic] Text in einer Zeile
```

- `LEVEL`: `DEBUG` · `INFO` · `WARN` · `ERROR`.
- `agent`: wer handelt — `orchestrator`, `user` ({{AUFTRAGGEBER}}), sonst der Worker-Name (`builder`,
  `explorer`, `reviewer`, `doc-writer`, `quick-check`, `maintenance`, …), `system` für die Mechanik selbst.
  Worker tragen eine **laufende Nummer je Sitzung und Typ** (`builder#1`, `builder#2`, …), damit mehrere
  gleichnamige Worker — parallel oder nacheinander — auseinanderzuhalten sind; die Nummer wird beim Start
  vergeben und bleibt bis zum Ende dieselbe. Ein Worker, der selbst loggt, nutzt den Namen, den ihm der
  Orchestrator im Auftrag genannt hat (z. B. `builder#2`), sonst den nackten Typnamen.
- `topic` (feste Wortliste, klein geschrieben): `session` · `prompt` · `decision` · `delegate` · `start` ·
  `end` · `result` · `tool` · `test` · `review` · `docs` · `commit` · `safeguard` · `error`.
- `Text`: eine Zeile, ≤ 200 Zeichen, gekürzt mit `…`; keine Zeilenumbrüche, keine Secrets (Tokens, Passwörter,
  Schlüssel, Zugangsdaten — auch nicht in gekürzten Tool-Argumenten).

Beispiel eines Delegationslaufs:

```text
[2026-09-11 14:02:11] [INFO] [user] [prompt] Aufgabe #12 umsetzen: Login-Formular mit Validierung
[2026-09-11 14:02:15] [INFO] [orchestrator] [decision] #12 in 3 Teile: Explorer (Bestand), Builder (Form), Builder (Tests)
[2026-09-11 14:02:16] [INFO] [orchestrator] [delegate] explorer ← Bestand Auth-Modul + Formkomponenten sichten
[2026-09-11 14:02:16] [INFO] [explorer#1] [start] Bestand Auth-Modul + Formkomponenten sichten
[2026-09-11 14:03:40] [INFO] [explorer#1] [end] ok · 3 Fundstellen (src/auth/*.ts)
[2026-09-11 14:03:41] [INFO] [orchestrator] [delegate] builder ← Login-Formular nach coding_rules.md
[2026-09-11 14:03:41] [INFO] [orchestrator] [delegate] builder ← Unit-Tests für Login-Validierung
[2026-09-11 14:03:42] [INFO] [builder#1] [start] Login-Formular nach coding_rules.md
[2026-09-11 14:03:42] [INFO] [builder#2] [start] Unit-Tests für Login-Validierung
[2026-09-11 14:05:02] [INFO] [builder#1] [test] lint ok · typecheck ok · 14 tests ok
[2026-09-11 14:05:03] [INFO] [builder#1] [end] ok · 2 Dateien geändert
[2026-09-11 14:05:40] [INFO] [builder#2] [end] ok · 6 neue Tests, alle grün
[2026-09-11 14:05:50] [WARN] [reviewer#1] [review] BLOCK · fehlende Server-Validierung in src/auth/login.ts:42
[2026-09-11 14:07:30] [INFO] [orchestrator] [commit] 3f9c2ab feat: Login-Formular mit Validierung
```

### Was protokolliert wird (je Tiefe)

| Tiefe | Inhalt (jede Stufe enthält die darüber liegenden) |
| :--- | :--- |
| `ERROR` | abgebrochene Worker, fehlgeschlagene Tool-Aufrufe/Testläufe, Fehler der Mechanik selbst |
| `WARN` | Safeguard-Warnungen (siehe oben), Review-Urteil `BLOCK`, rote Tests, Einträge für den Tabu-Bereich |
| `INFO` | Sitzungsstart/-ende · jede Eingabe von {{AUFTRAGGEBER}} (gekürzt) · **jede Entscheidung des Orchestrators** (was, warum, an wen) · **Start und Ende jedes Workers** mit Auftrag bzw. Ergebnis-Kurzfassung · Review-Urteile · Doku-Nachzug · Commits |
| `DEBUG` | zusätzlich jeder Tool-Aufruf (Name + Kurzargument, z. B. Datei oder Befehl) und die Rückgaben der Worker (gekürzt) |

### Pflichten bei eingeschaltetem Logging

- **Orchestrator:** vor jeder Ausführung die Entscheidung als `[orchestrator] [decision]` schreiben (Plan,
  Aufteilung, Modellwahl, warum), jede Delegation als `[delegate] <worker> ← <Auftrag>`, jeden Commit als
  `[commit] <hash> <message>`, Sitzungsende als `[session] ende · <Kurzbilanz>`.
- **Worker:** melden Meilensteine unter ihrem eigenen Namen (`[test]`, `[result]`, `[review]`, `[docs]`); Start
  und Ende schreibt der Orchestrator bzw. — wo das Werkzeug es kann — die Werkzeugmechanik automatisch.
  Startet der Orchestrator mehrere Worker desselben Typs, nennt er jedem im Auftrag seinen Log-Namen
  (`builder#1`, `builder#2`, … in Startreihenfolge), damit dessen eigene Zeilen zur Mechanik passen.
- **Schreibweg (werkzeugunabhängig):** `python .claude/scripts/ai-log.py <LEVEL> <agent> <topic> "<Text>"`
  (Stdlib-Python 3, kein Paket nötig, auf macOS/Linux `python3`; prüft den Schalter oben selbst und ist bei
  `aus` ein No-op). Assistenten
  ohne Shell-Zugriff (ChatGPT-Web o. Ä.) können nicht loggen — dann bleibt das Log leer, alles andere gilt
  unverändert. Claude Code schreibt Sitzungs-, Prompt- und Worker-Start/Ende-Zeilen zusätzlich automatisch
  per Hooks (`CLAUDE.md` § Logging).

### Mitlesen

```text
tail -f ai.log                              # Git Bash, Linux, macOS
Get-Content ai.log -Wait -Tail 20           # PowerShell
python .claude/scripts/ai-log.py --tail     # plattformunabhängig, farbig je Level (für Beamer/Vortrag)
python .claude/scripts/ai-log.py --tail --grep builder   # nur ein Worker
```

Für den Vortrag: zweites Terminal neben der Assistenten-Konsole mit `--tail` öffnen, `AI_LOG=ein` und
`AI_LOG_LEVEL=INFO` setzen (bei `DEBUG` verdeckt der Tool-Lärm die Entscheidungen). Die Datei wächst nur an —
zum Leeren vor einer Demo `python .claude/scripts/ai-log.py --reset` (legt die alte Datei als
`ai.log.<zeitstempel>.bak` ab, ebenfalls gitignored).

## Template-Herkunft und Updates

Ist dieses Projekt aus dem Template entstanden — per `git clone` (Checkliste „Neues Projekt",
`docs/ai/checklists.md`) oder nachträglich per `consume-template.py` + `--graft` (Checkliste „Projekt
nachrüsten") —, teilen Projekt und Template über den Git-Remote `template` eine gemeinsame Historie —
spätere Template-Änderungen lassen sich so per Merge nachziehen, ohne bereits eingesetzte echte Werte wieder
durch Platzhalter zu ersetzen. `.claude/template.json` hält dafür Remote/Branch des Templates, den zuletzt
eingespielten Basis-Commit, die eingesetzten Platzhalterwerte und die Update-Historie fest; `keep_local`
darin listet Dateien/Ordner, deren Projektfassung **bei Konflikten** gewinnt (u. a. `docs/project/**`,
`docs/ai/`-Arbeitsdateien, `README.md`, `CONFIG.md`) — konfliktfreie Template-Änderungen an diesen Dateien
werden normal mitgemergt. `no_replace` listet zusätzlich Dateien, die zwar normal mitgemergt, aber nie
platzhalter-ersetzt werden, weil sie Platzhalter absichtlich als Beispiel zeigen (`docs/ai/checklists.md`,
`.claude/skills/new-project/SKILL.md`).

Regel bei einem Update: Template-Logik in `.claude/`, `AGENTS.md`, `CLAUDE.md` und den Checklisten wird
nachgezogen; Projektinhalte in `docs/project/`, die `docs/ai/`-Arbeitsdateien und die README werden nie
überschrieben — bei Konflikten außerhalb von `keep_local` beide Seiten zusammenführen, nie blind eine Seite
nehmen. Ablauf: Checkliste „Template-Update" (`docs/ai/checklists.md`); Claude-Code-Mechanik dazu in
`CLAUDE.md` § 2 (Skill `/template-update`). Ein per `consume-template.py` nachgerüstetes Projekt hat zunächst
keinen gemeinsamen Vorfahren mit dem Template — `template-update.py --graft` stellt ihn per leerem
Merge-Commit her (Arbeitsbaum bleibt unverändert), erst danach funktionieren `--check`/`--apply` normal.

## Werkzeugspezifische Ergänzungsdateien

| Werkzeug | Datei | Inhalt |
| :--- | :--- | :--- |
| Claude Code | `CLAUDE.md` | Sub-Agenten, Skills, feste Modell-IDs, Token-Sparregeln, MCP, Logging-Hooks |
| GitHub Copilot | `.github/copilot-instructions.md` | Verweis auf diese Datei |
| Cursor | `.cursor/rules/agents.mdc` | Verweis auf diese Datei, `alwaysApply: true` |
| Aider | `.aider.conf.yml` | lädt diese Datei plus `docs/ai/board.md` automatisch |
| Gemini CLI | `GEMINI.md` | Verweis auf diese Datei |
| ChatGPT/Codex, Ollama, sonstige | — | Inhalt dieser Datei + `docs/ai/board.md` manuell laden |
