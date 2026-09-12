# {{PROJEKTNAME}} — Vorlage für „Agentic Coding"

> Diese README richtet sich an Menschen (keine Vorkenntnisse über KI-Assistenten nötig). Platzhalter wie
> `{{PROJEKTNAME}}`, `{{AUFTRAGGEBER}}`, `{{ORCHESTRATOR}}` werden beim Anlegen des Projekts aus `CONFIG.md`
> ersetzt (Checkliste „Neues Projekt" in `docs/ai/checklists.md`, Claude Code: `/new-project`).

## Was ist das?

Ein Vorlagen-Repository für Projekte, an denen ein Mensch (**{{AUFTRAGGEBER}}**) zusammen mit einem oder
mehreren KI-Assistenten arbeitet — egal ob Claude Code, ChatGPT/Codex, GitHub Copilot, Cursor, Aider, Gemini
CLI oder ein lokales Modell. Es liefert:

- eine anbieterneutrale Regeldatei (`AGENTS.md`) plus Verweisdateien für die gängigen Werkzeuge,
- einen Arbeitsordner für die Zusammenarbeit (`docs/ai/`: Board, Aufgaben, Fragen, Ledger, Checklisten),
- ein Skelett für die eigentliche Projekt-Dokumentation (`docs/project/`),
- für Claude-Code-Nutzer zusätzlich fertige Sub-Agenten und Skills (`.claude/`), die dieselben Checklisten
  automatisiert anstoßen.

Der Kerngedanke: **ein Assistent orchestriert** (plant, prüft, committet), **weitere Assistenten/Sessions
arbeiten** die umrissenen Teilaufgaben ab. Details dazu in `AGENTS.md`.

## Schnellstart — einfach sagen, was entstehen soll

Claude Code im Ordner dieses Templates starten und einen Satz schreiben. Der Assistent erkennt daraus, welcher
Weg gemeint ist, legt das Zielverzeichnis an, richtet Git ein und führt die passende Checkliste aus:

```text
Erstelle eine neue Anwendung in C:\development\mein-neues-projekt
Erstelle ein leeres Projekt in C:\empty-project
Nutze das Template in der bestehenden Anwendung C:\development\mein-langjaehriges-projekt
   und mache ein Code Review
```

Bei einer neuen Anwendung fragt der Assistent kurz nach Ziel, Stack und ersten Features und füllt `CONFIG.md`
selbst aus. „Leeres Projekt" überspringt die Fragen und legt ein Gerüst unter dem Namen „MyApp" an. Bei einem
bestehenden Repository analysiert er den Bestand, dokumentiert den Ist-Zustand, schlägt die Umstellung auf die
Template-Struktur vor und prüft auf Wunsch den Code.

Danach in den neuen Ordner wechseln und dort weiterarbeiten — die Regeln, Agenten und Skills liegen ab jetzt
im Projekt selbst.

## Die Befehle

| Befehl | Wofür |
| :--- | :--- |
| `/new-project` | Neues Projekt aus `CONFIG.md` aufsetzen: Platzhalter ersetzen, nicht genutzte Werkzeuge entfernen, Doku befüllen |
| `/consume-template` | Bestehendes Repository nachrüsten: Ist-Zustand dokumentieren, Struktur angleichen, optional Code-Review |
| `/template-update` | Neuerungen aus dem Template nachziehen, eigene Anpassungen bleiben |
| `/delegate` | Aufgabe auf parallele Sub-Agenten verteilen |
| `/project-docs` | Projekt-Doku nach einer Feature-Welle nachziehen |
| `/docs-audit` | Doku gegen den echten Code-Stand prüfen |
| `/session-wrapup` | Sitzung abschließen: Journal, Aufgaben, Fragen, Commit |
| `/maintenance` | Wiederkehrende Wartung (optional, per `CONFIG.md` abwählbar) |

Ohne Claude Code funktioniert alles genauso — dann statt des Befehls den Satz sagen: „Führe die Checkliste
Neues Projekt aus (`docs/ai/checklists.md`)."

## Von Hand, falls gewünscht

**Neues Projekt.** `git clone <Template-URL> <projekt>`, dann
`cd <projekt> && git remote rename origin template && git remote add origin <eigene-Repo-URL>`. Danach
`CONFIG.md` ausfüllen (oder leer lassen) und `/new-project` starten. In `CONFIG.md` stehen auch die Schalter
für das Modell der Hauptsession, das Agenten-Logging und die Wartung.

*Ohne Klon:* Wer im Template-Checkout bleiben will, legt einen Branch an (`git switch -c projekt/<name>`) —
das Projekt entsteht dann als Branch, Updates kommen später per Merge aus `main`. Auf `main` selbst bricht
`/new-project` ab, damit das Template seine Platzhalter behält.

**Bestehendes Projekt.** `python .claude/scripts/consume-template.py --target <ziel-repo>` kopiert die
Grundausstattung, ohne etwas zu überschreiben. Dann im Ziel-Repo `/consume-template`: Der Assistent
dokumentiert den Ist-Zustand, schlägt die Struktur-Migration vor (vorhandene KI-Ordner wandern nach
`docs/ai/`, der bisherige Rufname des Assistenten wird projektweit ersetzt, Regeldateien werden
zusammengeführt) und fragt, ob er zusätzlich den Code prüfen soll. Zum Schluss verknüpft
`python .claude/scripts/template-update.py --graft` die Historien, damit spätere Updates funktionieren.

## Template später aktualisieren

Ein `SessionStart`-Hook meldet in Claude Code automatisch, wenn das Template neuer ist als der zuletzt
eingespielte Stand. Einspielen: Assistenten anweisen „Führe die Checkliste Template-Update aus"
(`docs/ai/checklists.md`), Claude Code: `/template-update`. Die in `.claude/template.json` unter
`keep_local` gelisteten Dateien (u. a. `docs/project/**`, `docs/ai/`-Arbeitsdateien, `README.md`,
`CONFIG.md`) gewinnen **bei Konflikten** immer mit der Projektfassung; `no_replace` listet zusätzlich
Dateien, die zwar normal mitgemergt, aber nie platzhalter-ersetzt werden (sie zeigen Platzhalter absichtlich
als Beispiel, u. a. `docs/ai/checklists.md`).

## Mit welchem Assistenten?

| Werkzeug | Liest automatisch | Start |
| :--- | :--- | :--- |
| Claude Code | `CLAUDE.md` + `AGENTS.md` (Verweis) | Repo öffnen, startet automatisch mit beiden Dateien |
| Codex/ChatGPT (Repo-Modus) | `AGENTS.md` | Repo öffnen, als Projektkontext erkannt |
| GitHub Copilot | `.github/copilot-instructions.md` | Repo öffnen, Copilot Chat nutzen |
| Cursor | `.cursor/rules/agents.mdc` (`alwaysApply: true`) | Repo öffnen, Regel lädt automatisch |
| Aider | `.aider.conf.yml` (lädt `AGENTS.md` + `board.md`) | `aider` im Repo-Root starten |
| Gemini CLI | `GEMINI.md` (Verweis) | `gemini` im Repo-Root starten |
| ChatGPT (Web), Ollama, sonstige | nichts automatisch | `AGENTS.md` + `docs/ai/board.md` als System-Prompt |

## Ordnerübersicht

```text
AGENTS.md            # anbieterneutrale Grundregeln (zuerst lesen)
CLAUDE.md             # Claude-Code-Ergänzung (Sub-Agenten, Skills, Modell-IDs)
CONFIG.md             # Formular für Weg 1 (Projektname, Modell, Logging, Wartung, Ziel/Features) — wird von
                      # /new-project gelesen und danach entfernt
GEMINI.md  .aider.conf.yml  .cursor/rules/agents.mdc  .github/copilot-instructions.md   # Werkzeug-Verweise
.claude/              # Claude Code: Sub-Agenten, Skills, Scripte, Settings (Modell + Hooks), Wartung (optional)
.claude/scripts/      # u. a. new-project.py, consume-template.py, template-update.py, ai-log.py
.claude/template.json # Herkunft/Update-Stand ggü. dem Template (Remote, Basis-Commit, eingesetzte Werte)
ai.log                # optionaler Live-Mitschnitt aller Agentenaktionen (gitignored, AGENTS.md § Logging)
docs/
  README.md           # Index aller Doku-Dateien
  project/            # Projekt-Doku (IST-Zustand): Architektur, Coding-Regeln, Tests, Features, ADRs, ...
  ai/                 # Zusammenarbeit: Board, Aufgaben, Fragen, Ledger, Umbauliste, Checklisten
.github/README.md     # Beschreibung des Templates (GitHub zeigt sie statt dieser Datei); beim
                      # Anlegen eines Projekts entfernt
.github/workflows/ci.yml   # Lint/Typecheck/Test (Platzhalter-Befehle)
.templatedev.md       # nur im Template: Umbauliste/Fragen/Journal der Template-Entwicklung —
                      # wird beim Anlegen eines Projekts entfernt
LICENSE               # MIT (Wolfgang Rufeger) — gilt für das Template, nicht für deinen Projektcode
.env.example  .mcp.json.example  renovate.json  .editorconfig  .gitignore  .gitattributes
```

## Modell-/Kostenlogik in Kürze

Ein starkes/teures Modell plant, integriert und prüft — die eigentliche Kleinarbeit übernehmen günstigere/
schnellere Modelle in klar umrissenen Teilaufgaben. Unabhängige Teilaufgaben laufen parallel, nicht
nacheinander. Ergebnisse werden vor der Übernahme stichprobenartig gegen den echten Stand geprüft, nie
blind übernommen. „Fertig" gilt nur mit einem Beleg (Testlauf, Commit-Hash, Aufruf von außen). Gespart wird
bei den Helfern, nicht am Kopf: der Orchestrator läuft auf dem starken Modell (bei Claude Code: Opus, festgelegt
in `.claude/settings.json`). Scheitert ein Helfer zweimal an derselben Aufgabe, übernimmt einmal eine
Eskalationsrolle mit hoher Denkstufe statt eines dritten Anlaufs. Details und eine Beispiel-Tabelle je Anbieter
stehen in `AGENTS.md` § „Modell-/Kostenlogik".

## Lizenz

Das Template steht unter der [MIT-Lizenz](LICENSE): nutzen, ändern, weitergeben und kommerziell einsetzen ist
erlaubt, solange der Copyright-Hinweis auf Wolfgang Rufeger (`wolfgang@rufeger.de`) und der Lizenztext
erhalten bleiben.

Für ein daraus entstandenes Projekt heißt das: Die `LICENSE` bleibt liegen, solange Template-Teile
(`.claude/`, `AGENTS.md`, die Checklisten, die Scripte) im Repo sind. Der eigene Projektcode kann unter einer
beliebigen anderen Lizenz stehen — dann eine zweite Lizenzdatei ergänzen und in der Projekt-README benennen,
welche Lizenz für welchen Teil gilt.

## FAQ

**Muss ich Claude Code benutzen?** Nein. `AGENTS.md` ist die eigentliche Regeldatei und funktioniert mit jedem
Assistenten (siehe Tabelle oben); `.claude/` ist eine optionale, zusätzliche Automatisierungsschicht.

**Was gehört in `docs/ai/`, was in `docs/project/`?** `docs/ai/` ist Zusammenarbeit (Stand, Aufgaben, Fragen,
Verlauf) — `docs/project/` ist die eigentliche Projekt-Dokumentation (IST-Zustand von Architektur, Code, Tests).
Nie vermischen.

**Wer darf `docs/ai/` beschreiben?** Nur der Orchestrator (Hauptassistent). Sub-Agenten/Worker liefern
Ergebnisse zurück, schreiben dort aber nie hinein und committen nie (`AGENTS.md`).

**Was, wenn eine Aktion von einem Sicherheits-Classifier blockiert wird?** Siehe `AGENTS.md` §
„Umgang mit Sicherheits-/Safeguard-Warnungen" — nicht grundlos abbrechen, prüfen, ggf. eskalieren oder als
Aufgabe für {{AUFTRAGGEBER}} ablegen.

**Kann ich einzelne Dateien weglassen, die ich nicht brauche?** Ja — z. B. `.aider.conf.yml`, wenn Aider nicht
genutzt wird. `AGENTS.md`, `docs/ai/` und `docs/project/` sind der Kern und sollten bleiben.
