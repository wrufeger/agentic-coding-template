# Fragen

Offene Entscheidungen zur Weiterentwicklung — Nummern `Q<n>`, vorgegebene Antwortmöglichkeiten, keine
Standardantwort annehmen (dieselben Formregeln wie `docs/ai/questions.md`).

**Q1 · Wie sollen sich abgeleitete Projekte als Testkandidat zurückmelden?**

   Konzept mit Ausgangslage, vier Optionen und Aufwand: `konzept-feedback.md`.
   Es geht um fremde Daten (eine Repo-URL identifiziert oft eine Person oder Firma),
   und eine Gegenstelle gibt es heute nicht — das Template ist ein Repo, kein Dienst.
   a) GitHub-Issue im Template-Repo, per `gh` nach Zustimmung (Empfehlung, ~0,5 PT) —
      der Entwickler sieht vorher, was gepostet wird, alles öffentlich und prüfbar
   b) Pull Request auf eine Liste im Repo (~1 PT) — versioniert, aber viel Reibung
   c) eigener HTTPS-Endpunkt (~3 PT plus Betrieb) — stille Meldung, dafür nicht
      einsehbar und mit Datenschutzerklärung
   d) gar keine Mechanik, beim Abschluss nur einmal im Chat fragen
   * Antwort: c) eigenere Endpunkt. Domain rufeger.de ist vorhanden. Dort z.B. einen endpunkt in php, über den die KI der neu erstellten Anwendung aktiv Informationen zurückmelden kann. Wenn Q2 aktiv mit ja beantwortet oder in CONFIG.md aktiv geändert wurde zu ja, dann schickt die KI einmalig einen Zusammenfassung über die Installation per "/finalize" an die URL, im verlauf der Entwicklung immer dann wenn Änderungen an der KI gemacht wurden.
   * generell sollte jede Verbesserung, Optimierung der Kommunikation, zusätzliches allgemeingültiges Tool, Script, skill analysiert und an den endpunkt geschickt werden. Gilt auch nur für neu erstellte Anwendungen, nicht für die Entwicklung des Templates selbst. URL zum Endpunkt könnte in .templatedev/regeln.md definiert werden oder was schlägst Du vor?

**Q2 · Welcher Standardwert für den Schalter `Feedback`?**

   Vorgeschlagen wurde `ja` als Default. Ich rate ab: Ein voreingestelltes „ja" ist eine
   Einwilligung, die niemand erteilt hat — und es trifft nicht dich, sondern fremde
   Entwickler, die das Template klonen.
   a) `fragen` — beim Abschluss der Einrichtung einmal fragen, ohne Antwort passiert
      nichts (Empfehlung)
   b) `ja` — standardmäßig melden, wer nicht will, schaltet ab
   c) `nein` — standardmäßig aus, wer will, schaltet ein
   * Antwort: a) bei erstellung eines Projekts, feedback dann besser aktiv durch die jeweilige Anwendung. So könnten auch rein lokal entwickelte Anwendungen Feedback geben. Es sollte klar erwähnt werden, daß die Daten an z.B. https://rufeger.de/agentic-coding-feedback gesendet werden und daß es sich rein um anonymisierte Daten aus den jeweiligen config Dateien der KI-Umbebungen (z.B. .claude), CLAUDE.md, AGENTS.md, /docs/ai, ... handelt, niemals sensible Daten enthält und auch keine reinen Projektdaten. Es geht um Verbesserung der Standardregeln, Tools, optimierte Kommunikation zwischen KI und Mensch, übersichtlichere Dokumentation, Optimierung in Abläufen, hilfreiche Helpers  (Script, skill) die die KI im Projekt entwickelt hat, ...

**Q3 · Gehört der Schalter überhaupt nach `AI-CONFIG.md`?**

   Alle Schlüssel dort wirken **laufend**; dieser wirkt genau einmal, beim Abschluss der
   Einrichtung. Das ist ein Fremdkörper in der Datei.
   a) trotzdem in `AI-CONFIG.md` — ein Ort für alle Einstellungen (Empfehlung)
   b) nur als einmalige Frage in `/finalize`, gar kein Schlüssel
   * Antwort: b)


**Q4 · `setup-lib.py` (2461 Zeilen) — aufteilen, kürzen oder so lassen?**

   Auslöser ist die neue Regel in `docs/project/coding_rules.md` § Dateigröße: Die Datei hat
   heute zum zweiten Mal parallele Arbeit blockiert — zwei `builder`-Aufträge mussten
   nacheinander laufen, weil beide sie anfassen. Sie enthält Platzhalter-Ersetzung,
   Werkzeug-/Wartungs-/Optimizer-Entfernung, CLAUDE.md-Textchirurgie, Hook-Pflege und die
   Wortlisten für `AI-CONFIG.md`. `sync-config.py` (1025) und `update-template.py` (1500)
   hängen als Importeure daran.
   a) aufteilen nach Zuständigkeit (Config-Parser · Datei-/Pfadoperationen · CLAUDE.md-Textchirurgie),
      `setup-lib.py` bleibt als dünne Fassade, damit die Importeure unverändert laufen (Empfehlung)
   b) nur die CLAUDE.md-Textchirurgie herauslösen — der kleinste Schnitt, der den heutigen
      Engpass entschärft
   c) so lassen — die Datei ist geordnet, das Problem ist die Delegation, nicht die Datei
   * Antwort: ja aufteilen (2026-09-16) — also a): nach Zuständigkeit schneiden, `setup-lib.py` bleibt als
     dünne Fassade stehen, damit `sync-config.py`, `update-template.py` und `install-global.py` unverändert
     weiterlaufen.
   * Erledigt am 2026-09-16: `config-lib.py` (761) · `files-lib.py` (642) · `claudemd-lib.py` (208) ·
     `setup-lib.py` (1047, Ablauf + Fassade). Beleg im Ledger. a)

**Q5 · Wie sollen die offenen Änderungen im Arbeitsbaum committet werden?**

   Offen sind deine Feedback-Änderungen (Endpunkt, Abholung, `feedback/SKILL.md`, `docs/ai/template-feedback/`,
   Checkliste) und meine Aufgaben-Verweise (`tasks.md`, `tasks_archive.md`, INDEX, AGENTS/CLAUDE, `check-refs.py`).
   `ledger.md` enthält Einträge von beiden. Ein Push ist nötig, damit `bandliste` per `/update-template` nachzieht.
   a) zwei Commits (erst Feedback, dann Aufgaben-Verweise) und pushen (Empfehlung)
   b) zwei Commits, ohne Push
   c) vorerst nichts committen — die Feedback-Änderungen sind noch nicht fertig
   * Antwort: a)
   * Verarbeitet 2026-09-16: `dcf4cf5` (Feedback), Aufgaben-Verweise im Folgecommit, beides gepusht.

**Q6 · Soll ich das gemeinsame Konzept für T1–T3 jetzt schreiben?**

   T1–T3 sind neue Funktionen im Template, keine Tests — es gibt heute weder PR/MR- noch Issue-Skill.
   Das Konzept (`.templatedev/konzept-repo-issues.md`) legt Optionen und Empfehlung vor: Erkennung der Zugänge,
   Zielbranch, Zustimmung vor dem Anlegen, welche Tracker zuerst, wie MCP-/PR-Fehler als Rückmeldung erfasst werden.
   a) ja, alle drei in einem Konzept (Empfehlung)
   b) ja, aber erst nur T1
   c) nein, später
   * Antwort: a)
   * Verarbeitet 2026-09-16: Konzept `.templatedev/konzept-repo-issues.md` wird geschrieben, T1–T3 danach.

**Q7 · Wie wird die Template-Entwicklung vom Template getrennt?**

   Heute liegt das Template im Root, die Entwicklungsnotizen in `.templatedev/`. Das kostet Sonderfälle
   (Blöcke „noch nicht initialisiert" in `AGENTS.md`/`CLAUDE.md`, `is_template`, `template_only`, 103 Stellen
   in `.claude/scripts/`). `/update-template` merged per Git und braucht das Template im Root eines Branches.
   Ladeversuch 2026-09-16 (Claude Code 2.1.273, Sitzung im Unterordner, Details im Ledger): CLAUDE.md,
   Agenten und Skills des Elternordners werden mitgeladen, bei gleichem Namen gewinnt der Unterordner;
   Eltern-CLAUDE.md per `claudeMdExcludes` abschaltbar; `settings.json`/Hooks kommen nur aus dem Startordner.
   a) Aufbau bleibt, Sitzung für die Pflege startet **in `.templatedev/`**: eigene CLAUDE.md, Eltern-CLAUDE.md
      ausgeschlossen, Agenten/Skills des Templates werden geerbt und nur bei Bedarf gleichnamig überschrieben;
      Standardstruktur in `.templatedev/`, Abgleich per Script statt `/update-template`. Kein Split, kein
      Umzug von `bandliste` (Empfehlung, ~1–1,5 PT)
   b) Umdrehen: Root = Pflegeprojekt, Template in `template-src/`, Veröffentlichung per `git subtree split`
      auf einen Branch `template`; Skills aus `template-src/` laden beim Dateizugriff nach, ohne Schalter (~2–3 PT)
   c) Zwei Nachbarordner `template-src/` und `template-management/` im selben Repo: saubere Trennung, aber
      Split plus Unterordner-Modus für `update-template.py` (~3 PT)
   * Antwort: a)
   * Verarbeitet 2026-09-16: T5 auf Variante a) ausgerichtet, Konzept `.templatedev/concept-project-structure.md` (englischer Dateiname, siehe Q9).

---

**Q8 · Über welchen Weg sprechen die Skills mit Git-Hoster und Tracker?**

   Konzept: `konzept-repo-issues.md` § „Wege zum Dienst". `bandliste` liegt auf selbst betriebenem GitLab,
   ohne `gh`/`glab`.

   a) Git-Hoster per REST-Script (Token aus Umgebung/`.env`), CLI wenn vorhanden, MCP als Zusatz;
      Jira/YouTrack/Linear per MCP — **Empfehlung**

   b) alles per MCP — einheitlich, aber auf selbst betriebenem GitLab unsicher

   c) alles per CLI (`gh`, `glab`, Jira-CLI) — Installation auf jedem Rechner nötig

   * Antwort: a)
   * Verarbeitet 2026-09-16: Konzept § Entschieden; gilt für T1–T3.

---

**Q9 · Wo wird das Ergebnis der Zugangsprüfung (T1) abgelegt?**

   a) neue Datei `docs/project/integrationen.md` (Fähigkeit × Weg × Stand × Datum) — **Empfehlung**

   b) neue Tabelle in `AI-CONFIG.md` — dort steht aber Steuerung, kein Messergebnis

   c) Abschnitt in `docs/project/architecture.md`

   * Antwort: a) aber als integrations.md, da Dateinamen immer in englisch
   * Verarbeitet 2026-09-16: `docs/project/integrations.md`; Skill und Script heißen entsprechend `/integrations`, `integrations.py`.

---

**Q10 · Welche Freigabe braucht das Anlegen von PR/MR, Issue oder Kommentar?**

   Heute verlangt `AGENTS.md` für Schreibzugriffe eine datierte Freigabe je Zweck.

   a) Vorschau plus „ja" im Chat je Aktion, Journal-Eintrag mit Link automatisch;
      `AGENTS.md` wird um diesen Fall ergänzt — **Empfehlung**

   b) wie a), PR/MR aber immer zuerst als Entwurf (Draft)

   c) datierte Freigabe im Journal vor jeder Aktion, wie heute

   * Antwort: a)
   * Verarbeitet 2026-09-16: Ergänzung von `AGENTS.md` § „Zugriff auf laufende Systeme" ist Schritt in T2.

---

**Q11 · Mit welchen Diensten fangen wir an?**

   a) GitLab (Beleg in `bandliste`) und GitHub, danach Jira, YouTrack zuletzt — **Empfehlung**

   b) nur GitLab, weitere erst bei Bedarf

   c) GitLab, GitHub und Jira gleichzeitig

   * Antwort: GitLab und GitHub, Rest später
   * Verarbeitet 2026-09-16: GitLab und GitHub in T1–T3; Jira, YouTrack, Linear als Backlog-Punkt 34.

---

**Q12 · Wie erbt `.templatedev/` die Regeln aus `AGENTS.md` und `CLAUDE.md`?**

   Konzept: `concept-project-structure.md` § Umsetzung, Schritt 3.

   a) gerenderte Kopie per Script (Platzhalter ersetzt, Template-Block entfernt), `--check` beim
      Sitzungsstart meldet Abweichungen — **Empfehlung**

   b) eigene kurze Dateien mit Verweis auf `../AGENTS.md` — Platzhalter und Template-Block bleiben sichtbar

   c) Import per `@../AGENTS.md` — lädt dieselben Platzhalter mit, kein Script nötig

   * Antwort: a)
   * Verarbeitet 2026-09-17: T5 Schritt 3 (`sync-rules.py`, `--check` beim Sitzungsstart).

---

**Q13 · Wohin mit den Dateien ohne Gegenstück in der Standardstruktur?**

   a) `regeln.md` → `docs/project/coding_rules.md` · `README.md` (Testprojekte) → `docs/project/test-projects.md` ·
      `konzept-*.md` → `docs/project/konzepte/` · `daten/` → `docs/project/data/` ·
      `testprojekte.py` und `scripts/` → `scripts/` mit englischen Namen — **Empfehlung**

   b) wie a), zusätzlich `docs/project/konzepte/` im Template selbst in `concepts/` umbenennen

   c) Dateien ohne Gegenstück bleiben, wo sie sind; nur die `docs/ai/`-Dateien ziehen um

   * Antwort: b) und alle Links, Erwähnungen und Referenzen prüfen
   * Verarbeitet 2026-09-17: T5 Schritt 2 um die Umbenennung `docs/project/konzepte/` → `concepts/` im Template erweitert (heute 12 Erwähnungen in 9 Dateien), samt Prüfung aller Verweise und Hinweis für `bandliste` beim nächsten `/update-template`.

---

**Q14 · Was bleibt im Root von den Template-Blöcken in `AGENTS.md` und `CLAUDE.md`?**

   a) drei Zeilen: „Template-Checkout — Pflege in einer Sitzung in `.templatedev/`, hier nur Projekte
      anlegen oder nachrüsten" — **Empfehlung**

   b) nichts; der Hinweis steht nur in `.github/README.md`

   c) die heutigen Blöcke bleiben unverändert

   * Antwort: a)
   * Verarbeitet 2026-09-17: T5 Schritt 4.

---

**Q15 · Wie wird der Pflege-Modus im Root eingeschaltet?**

   Wunsch: Sitzung im Root arbeitet wie in `.templatedev/`. Konzept: `concept-project-structure.md`
   § „Pflege-Modus im Root" — technisch nur über Hook-Ausgabe und Scripte, die Root-`CLAUDE.md` und die
   Root-Skills bleiben geladen.

   a) `TEMPLATEDEV_MODE=ein` in `.env`; Hook nennt die geltenden Regeln, Scripte nehmen `.templatedev/` als
      Projektordner, `create-project`/`apply-template`/`finalize` lehnen ab (~0,5 PT) — **Empfehlung**

   b) `CLAUDE.local.md` im Root (gitignored) mit dem Hinweis auf `.templatedev/` — kein Code, aber auch
      keine Umlenkung der Scripte und keine Sperren

   c) kein Schalter; Pflege nur in einer Sitzung in `.templatedev/`

   * Antwort: c) TEMPLATEDEV_MODE=ein als Idee festhalten, prio gering. Sag rechtzeitig Bescheid, wenn ich das Verzeichnis wechseln und eine neue Session beginnen muß
   * Verarbeitet 2026-09-17: kein Schalter in T5; Idee als Backlog-Punkt 35 (Priorität gering). Zeitpunkt für den Wechsel nach `.templatedev/` steht in T5 und wird angesagt.

---

**Q16 · Sollen die Commits seit `70b0af0` gepusht werden?**

   Lokal liegen u. a. `993b82e` (Präfix `act-`), `568b1a8` und `0be54df` (`/act`) sowie die Commits vom
   2026-09-17 (Journal). Ein Push macht sie für `bandliste` per `/act-update-template` verfügbar.

   a) ja, alles pushen — **Empfehlung**, sobald Q18 geprüft ist

   b) nur bis `993b82e` (Umbenennung), `/act` erst nach dem Test

   c) noch nicht

   * Antwort: a)
   * Verarbeitet 2026-09-17: gepusht `6843618..8807ad1`.

---

**Q17 · Sollen Kurz-Befehle wie `/idea` weiter funktionieren?**

   Interaktiv weist Claude Code unbekannte Befehle ab, bevor das Modell sie sieht („Unknown command: /idea").
   Möglich sind nur echte Weiterleitungs-Skills ohne Präfix (je zwei Zeilen, nur von Hand aufrufbar).
   Eingebaute Namen (`/feedback`, vermutlich `/bug`) sind ausgeschlossen.

   a) Weiterleitungen für alle Skills außer eingebauten Namen (~0,25 PT)

   b) nur für die häufigsten: `commit`, `idea`, `prepare`, `update-template` — **Empfehlung**

   c) keine; `/act-…` und die Sätze genügen

   * Antwort: b)
   * Verarbeitet 2026-09-17: Weiterleitungs-Skills `commit`, `idea`, `prepare`, `update-template` angelegt; beim Update gewinnt dort die Template-Fassung.

---

**Q18 · Zeigt `/act` die Liste jetzt sofort?**

   Hook `act-help.py --hook` (Commit `0be54df`) fängt `/act` und `/act <name>` ab, bevor das Modell läuft
   (Probe mit `claude -p`: 0 Runden, 0 $). Interaktiv ungeprüft; ggf. nach Neustart der Sitzung.

   a) ja, sofort und lesbar

   b) ja, aber die Zusatzzeilen von Claude Code („blocked by hook", „Original prompt") stören

   c) nein — es denkt weiter nach oder wählt `/act-bug`

   * Antwort: a)
   * Verarbeitet 2026-09-17: nichts zu tun; `/act`-Hook bestätigt.

---

**Q19 · Bleibt der Marker `.templatedev/.maintainer` nach T5?**

Nach dem Umbau wird in `.templatedev/` gepflegt; der Root dient nur noch zum Anlegen/Nachrüsten.

- a) behalten — eine Root-Sitzung in deinem Checkout bleibt ohne Begrüßungs-Hinweis — **Empfehlung**
- b) entfernen — der Root verhält sich immer wie ein frischer Klon, auch bei dir

Unbeantwortet: Marker bleibt, wie heute.

* Antwort: b), damit ist selbst auch direkt merke, daß ich im falschen Kontext arbeite. Die Ideen, das über Einstellungen zu ändern bitte auch löschen. Strikte Trenneung und klare Regeln, je nach Start der Session
* Verarbeitet 2026-09-17: Marker entfällt; Root verhält sich immer wie ein frischer Klon, Pflege nur in einer Sitzung in `.templatedev/`. Backlog-Punkt 35 (Pflege-Modus per Einstellung) und der Konzeptabschnitt dazu werden gelöscht. T5 Schritt 1/5.

---

**Q20 · Journal beim Umzug nach den Verdichtungsregeln kürzen?**

`ledger.md` hat 986 Zeilen; die Regeln verlangen Verdichtung nach Alter (Commit-Hashes, Nummern, Pfade bleiben).

- a) ja, beim Umzug verdichten — **Empfehlung**
- b) unverändert umziehen, später verdichten

Unbeantwortet: unverändert umziehen.

* Antwort: a)
* Verarbeitet 2026-09-17: Journal wird beim Umzug verdichtet (T5).

---

**Q21 · Was passiert mit den beantworteten Fragen Q1–Q18?**

- a) nach `docs/ai/questions_archive.md`; die `* Verarbeitet …`-Zeilen bleiben im Wortlaut — **Empfehlung**
- b) wie a), zusätzlich die Quittungen ins `✅ **Datum** — …`-Format umschreiben
- c) bleiben in `questions.md`

Unbeantwortet: a).

* Antwort: a)
* Verarbeitet 2026-09-17: Q1–Q18 ziehen nach `docs/ai/questions_archive.md`, Quittungen im Wortlaut (T5).

---

**Q22 · Feld `phase` der Skills in das dokumentierte `metadata` verschieben?**

`phase` steht nicht in der Frontmatter-Referenz von Claude Code, `metadata` schon.

- a) `metadata:` mit `phase: setup` — robust gegen künftige Prüfungen — **Empfehlung**
- b) bleibt als eigenes Feld

Unbeantwortet: bleibt, wie es ist (b).

* Antwort: a)
* Verarbeitet 2026-09-17: `phase` wandert unter `metadata:` (T5 Schritt 1).

---

**Q23 · Wird nach dem Beleg in der neuen Sitzung gepusht?**

- a) ja, direkt nach bestandenem Beleg — **Empfehlung**
- b) erst nach deiner Durchsicht

Unbeantwortet: b).

* Antwort: a)
* Verarbeitet 2026-09-17: Push direkt nach bestandenem Beleg (T5 Schritt 7).

---

