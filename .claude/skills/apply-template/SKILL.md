---
name: apply-template
description: Checkliste Projekt nachrüsten - bestehendes Repo mit der Agentic-Coding-Grundausstattung ausstatten, IST-Zustand dokumentieren.
---

# Projekt nachrüsten

Setzt die werkzeugneutrale Checkliste „Projekt nachrüsten" aus `docs/ai/checklists.md` um (Weg 2). Läuft im
Hauptkontext, **im Ziel-Repo** — nachdem `apply-template.py` (aus dem Template-Checkout heraus) bereits
dorthin kopiert hat. Mechanik: `.claude/scripts/apply-template.py` (Kopiervorgang, läuft vorher aus dem
Template), `.claude/scripts/migrate-project.py` (Struktur-Migration im Ziel: KI-Ordner umstellen,
Orchestrator-Name ersetzen), `.claude/scripts/create-project.py` (Platzhalter/Werte),
`.claude/scripts/update-template.py --graft` (Historie verknüpfen).

## Ablauf

1. `git status` sichten, die von `apply-template.py` kopierten Dateien stichprobenartig prüfen. Dateien, die
   im Ziel schon existierten, wurden **nicht** überschrieben — sie stehen in der Ausgabe unter
   „zusammenführen". Die Template-Fassung jeder Datei zeigt `git show template/<branch>:<pfad>` — der Branch steht in
   `.claude/template.json` (`template_branch`, meist `main`); `migrate-project.py --plan` nennt den fertigen
   Befehl je Datei.

   **Vor allem Weiteren: Arbeitsbaum committen.** Die Migration in Schritt 2 verschiebt Dateien und ersetzt
   Namen im ganzen Repo — ohne sauberen Stand ist sie nicht rückgängig zu machen.
2. **Struktur-Migration** (`AI-CONFIG.md` § `Struktur-Migration`: `ja` | `nein` | `fragen`, Default `fragen`).
   `python .claude/scripts/migrate-project.py --plan` ausführen und den Plan zeigen: welche KI-Arbeitsordner
   gefunden wurden (`fable/`, `ai/`, `ki/`, `docs/fable/`, …), wohin ihre Dateien wandern, welche Dateien
   inhaltlich zusammengeführt werden müssen, welcher Orchestrator-Name ersetzt würde.
   - Bei `fragen`: Plan zeigen und **einmal** nachfragen: „Soll ich das Repo auf die Template-Struktur
     umstellen (Dateien werden per `git mv` verschoben, Orchestrator-Name projektweit ersetzt)? a) ja
     b) nein, nur fehlende Dateien ergänzen". Ohne Antwort **nicht** migrieren.
   - Bei `ja` bzw. nach Zustimmung: `--apply` ausführen. Ist der alte Orchestrator-Name nicht in `AI-CONFIG.md`
     hinterlegt, die erkannten Kandidaten kurz bestätigen lassen, dann
     `--rename-orchestrator <Alt>=<Neu>`; `<Neu>` ist der Wert aus `AI-CONFIG.md` § `Orchestrator`.
   - Bei `nein`: überspringen, weiter mit Schritt 3.

   **Prioritäten beim Zusammenführen** (gilt für alles, was das Script als „zusammenführen" meldet):

   | Bereich | Wer gewinnt |
   | :--- | :--- |
   | `.claude/**`, `AGENTS.md`, `CLAUDE.md`, `docs/ai/checklists.md`, `docs/ai/README.md` | **Template** — Regeln zu Agenten, Skills und Zusammenarbeit werden übernommen; projektspezifische Ergänzungen (eigene Agenten, eigene Skills, Stack-Eigenheiten) werden eingearbeitet, nicht weggeworfen |
   | `docs/ai/`-Arbeitsdateien (board, tasks, questions, ledger, backlog) | **Template-Struktur, Projekt-Inhalt** — Dateinamen und Form richten sich nach dem Template, die Einträge des Projekts bleiben vollständig erhalten |
   | `docs/project/**` | **Projekt** — eine vorhandene Projektdefinition hat Vorrang, das Template liefert nur die fehlenden Skelette |
   | `docs/project/coding_rules.md` | **die strengere Regel** — Template-Regeln, die strikter sind als die vorhandenen, werden immer übernommen (z. B. „kein `any`", „keine `console.log` im Commit") |
   | `README.md`, `.gitignore` | **Projekt** — das Template ergänzt nur (eigener Abschnitt bzw. fehlende Zeilen) |

   Verschobene Altdateien, die das Script als `*.alt.md` (bzw. `*.alt2.md`, …) abgelegt hat, inhaltlich in
   die Template-Fassung einarbeiten und danach löschen. War eine Altdatei inhaltsgleich mit der bereits
   vorhandenen, hat das Script sie direkt entfernt (`git rm`) — der Inhalt steckt dann in der Template-Fassung.
   Markdown in **Unterordnern** eines alten KI-Ordners (typisch `archiv/`) verschiebt das Script bewusst nicht;
   es listet die Dateien auf, die Zuordnung machst du von Hand. Leer gewordene Altordner erst nach Sichtung
   entfernen.
3. Sub-Agent `explorer` (Sonnet) analysiert das bestehende Repo: Projektname (`package.json` o. Ä.), Stack,
   Verzeichnisstruktur, Tests, Befehle (Install/Dev-Start/Lint/Typecheck/Test/E2E), CI — Rückgabe ≤ 40
   Zeilen mit Belegen (`Datei:Zeile`).
4. `AI-CONFIG.md` daraus befüllen (Projektname, Stack, Befehle; `KI-Werkzeuge` nach kurzer Rückfrage an
   {{AUFTRAGGEBER}}, welche Werkzeuge im Projekt genutzt werden). Danach `python .claude/scripts/
   create-project.py --apply` ausführen — ersetzt Platzhalter, entfernt nicht genutzte Werkzeug-Dateien, setzt
   die Werte in `.claude/template.json`.
5. `docs/project/*` mit dem **echten IST-Zustand** befüllen — nicht raten, am Code prüfen (Sub-Agent
   `doc-writer`, Sonnet). `.gitignore`-Vorschläge aus Schritt 1 übernehmen (von Hand zusammenführen, nie
   automatisch überschreiben). Im Projekt-`README.md` einen Abschnitt „Zusammenarbeit mit KI-Assistenten"
   ergänzen (Verweis auf `AGENTS.md` und `docs/ai/board.md`).
6. **Code-Analyse — nur wenn gewünscht.** Maßgeblich ist `AI-CONFIG.md` § `Code-Analyse` (der Wert steht auch in
   der Ausgabe von `create-project.py`):
   - `nein` → überspringen, direkt zu Schritt 7.
   - `fragen` (Default) → jetzt, **nach** dem Befüllen von `docs/project/`, einmal im Chat nachfragen:
     „`docs/project/` ist befüllt. Soll ich zusätzlich den Bestand prüfen und Verbesserungen vorschlagen
     (nur Vorschläge in `docs/ai/backlog.md`, kein Code wird geändert)? a) ja b) nein". Ohne Antwort **nicht**
     analysieren — die Frage wird nicht stillschweigend entschieden (`AGENTS.md`).
   - `vorschlagen` → ohne Rückfrage ausführen.

   Ablauf der Analyse (read-only, parallel): `explorer` (Sonnet) je Bereich für Struktur, Duplikate, tote
   Pfade, fehlende Tests, veraltete Abhängigkeiten; `reviewer` (Opus) für Sicherheits- und Risikobefunde.
   Ergebnis geht **ausschließlich** als priorisierte Liste nach `docs/ai/backlog.md` (Sicherheit zuerst, je
   Punkt: Befund, Fundstelle `Datei:Zeile`, Vorschlag, geschätzter Aufwand) — kein Code wird geändert, keine
   Aufgabe wird angelegt. {{AUFTRAGGEBER}} entscheidet dort mit einem Marker, was in `docs/ai/tasks.md` wandert.
7. Ersten `docs/ai/board.md`-Stand und `docs/ai/ledger.md`-Eintrag „Template nachgerüstet" schreiben (mit
   Beleg: was `apply-template.py` kopiert/übersprungen hat, was befüllt wurde, ob eine Code-Analyse lief).
8. `python .claude/scripts/create-project.py --finish` ausführen (prüft vorher Schritt 5/7, schreibt danach
   `AI-CONFIG.md` fort statt sie zu löschen: Freitext-Abschnitte raus, Vermerk in Zeile 1, „Betrieb"/
   „Einrichtung" bleiben).
9. **Globale Ablage anbieten** (`AI-CONFIG.md` § Einrichtung → `Globale Ablage`): `nein` → überspringen.
   `agenten` / `agenten+skills` / `alles` → ohne Rückfrage `python .claude/scripts/install-global.py --plan
   --parts <entsprechend>` zeigen und nach Zustimmung `--apply` (mit `--force` nur, wenn
   {{AUFTRAGGEBER}} eine vorhandene Zieldatei ausdrücklich überschreiben will). `fragen` (Default) → **einmal**
   im Chat nachfragen: „Sollen Agenten-Rollen (und/oder `/commit`+`/audit-docs`, ein kurzer Regelauszug)
   zusätzlich nach `~/.claude/` gelegt werden, damit sie in allen Projekten dieses Rechners gelten — auch
   ohne dieses Template? a) nein b) nur Agenten c) Agenten + Skills d) alles". Ohne Antwort **nicht**
   installieren — keine Standardantwort annehmen.
10. Commit per Pathspec nach Freigabe von {{AUFTRAGGEBER}}.
11. `python .claude/scripts/update-template.py --graft` ausführen (nach Freigabe — erzeugt einen
   Merge-Commit ohne Änderung des Arbeitsbaums, Voraussetzung für spätere `/update-template`-Läufe).

## Grenzen

Kein Code wird am bestehenden Projekt geändert — nur die Agentic-Coding-Grundausstattung kommt hinzu. Das gilt
auch für die Code-Analyse aus Schritt 6: sie liefert Vorschläge in `docs/ai/backlog.md`, nie Änderungen.
Findings zum Code selbst (fehlende Tests, TODOs) werden Vorschläge bzw. — wenn {{AUFTRAGGEBER}} sie freigibt —
Aufgaben in `docs/ai/tasks.md`, nicht direkt umgesetzt.
