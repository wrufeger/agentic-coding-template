> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# Checklisten für die Zusammenarbeit

Werkzeugneutrale Arbeitsanweisungen (gelten für jeden Assistenten, siehe `AGENTS.md`). {{AUFTRAGGEBER}} kann sie
wörtlich als Anweisung geben, z. B. „Führe die Checkliste Aufgabe abschließen aus
(`docs/ai/checklists.md` § Aufgabe abschließen)". Welche zusätzliche Mechanik ein bestimmtes Werkzeug dafür anbietet (automatisierter
Aufruf, Ablauf in einer separaten Session o. Ä.), steht in der jeweiligen werkzeugspezifischen Ergänzungsdatei
(siehe `AGENTS.md` § „Werkzeugspezifische Ergänzungsdateien"), nicht in dieser Checkliste.

## Aufgabe abschließen

Läuft **nach jeder abgeschlossenen Aufgabe** im Hauptkontext (Orchestrator), nie bei einem Worker — nicht
erst am Sitzungsende.

Journal, Aufgabenstand und neue Fragen sind zu diesem Zeitpunkt bereits nachgezogen: Das passiert laufend
während der Arbeit, solange die Belege frisch sind (`AGENTS.md` § Grundregeln). Diese Checkliste räumt auf,
was sich angesammelt hat, und sichert das Ergebnis.

1. **Beleg prüfen:** Testlauf, Commit-Hash oder ein Aufruf von außen. Pflichtläufe aus
   `docs/project/testing.md` grün. Ohne Beleg keine Abnahme — dann nur `Stand <Datum>:` in
   `docs/ai/tasks.md` aktualisieren und die Aufgabe offen lassen.
2. **Archivieren:** als ✅ markierte Aufgaben mit Volltext nach `docs/ai/tasks_archive.md`, verbuchte Fragen
   nach `docs/ai/questions_archive.md`. Nummern (`A<n>`/`F<n>`) bleiben gültig und werden nie neu vergeben.
   Aufgaben unter „nur für {{AUFTRAGGEBER}}" nur auf dessen Meldung hin abhaken; Antworten in deren
   `* Antwort:`-Zeilen genauso verbuchen — delegierte Aufgaben wandern in den oberen Abschnitt, erweiterte
   Rechte mit Datum ins Journal.
3. **Journal ergänzen und verdichten:** fehlt ein Eintrag zur gerade abgeschlossenen Aufgabe, jetzt
   nachtragen. Ältere Einträge nach den Regeln im Kopf von `docs/ai/ledger.md` zusammenfassen — Commit-Hashes,
   Nummern, Versionen und Pfade bleiben immer erhalten.
4. **Doku-Index:** neue Dateien in `docs/README.md` eintragen, Datenstände der geänderten Dateien prüfen.
5. **Board:** `docs/ai/board.md` auf den neuen Stand bringen (Kurzbilanz, nächster Schritt, offene Freigaben).
6. **Commit per Pathspec:** `git add <pathspec …>`, nie ein catch-all; kurze Message im Repo-Stil. Committet
   wird die abgenommene Arbeit, nicht ein Zeitabschnitt. Secrets, Archive und Originalmedien bleiben draußen
   (`.gitignore` prüfen). Fremde uncommittete Änderungen anderer Sitzungen nicht stillschweigend mitnehmen —
   sichten, dann entscheiden.
7. **Bilanz an {{AUFTRAGGEBER}}:** Ergebnis zuerst, Belege (Hash, Zahlen), offene Punkte und Fragen mit
   Nummern.
8. **Logging** (falls eingeschaltet, `AGENTS.md` § Logging): Commit als
   `[orchestrator] [commit] <hash> <message>` schreiben — das Log ist Mitschnitt, kein Ersatz für Journal
   oder Beleg.
9. **Kontext freigeben:** Der Detailkontext der erledigten Aufgabe wird nicht mehr gebraucht, der Stand liegt
   vollständig in Git und `docs/ai/`. Werkzeuge mit Kontext-Komprimierung (Claude Code: `/compact`) hier
   einsetzen; steht die nächste Aufgabe schon fest, sie dabei erwähnen.

## Delegation

Bewährte Arbeitsweise: das teure/starke Modell (Orchestrator) plant, integriert und prüft; die breite Arbeit
machen parallele Worker (günstigeres/schnelleres Modell). So bleibt der Kontext des Orchestrators klein und die
Arbeit bezahlbar (siehe `AGENTS.md` § Modell-/Kostenlogik).

- **Wann delegieren:** Codebase-Analysen über mehrere Verzeichnisse, Web-/Doku-Recherche, unabhängige
  Baustellen (mehrere Endpunkte/Komponenten/Dateien), Routine-Doku-Pflege.
- **Nicht delegieren:** kleine Einzeldatei-Fixes, alles, was `docs/ai/` beschreibt (nur der Orchestrator
  schreibt dort), finale Commits, finale Urteile/Freigaben.
- **Auftrags-Regeln:** jeder Auftrag nennt Kontext (2–3 Sätze), konkreten Liefergegenstand, Format des
  Ergebnisses, was zu ignorieren ist (Build-Ordner, `node_modules`, `.git`, generierte Dateien).
- Unabhängige Worker **immer gleichzeitig** starten, nicht nacheinander.
- Worker-Ergebnisse sind Rohmaterial: der Orchestrator verifiziert Kernaussagen stichprobenartig am Code, bevor
  sie in Board, Doku oder Entscheidungen wandern.
- Ein Worker, der sich festgefressen hat, wird nicht endlos weitergefüttert — Auftrag schärfen und neu starten
  ist günstiger.
- **Eskalation:** Scheitert ein Worker **zweimal** an derselben Aufgabe, wird nicht ein drittes Mal derselbe
  Auftrag gestellt. Entweder (a) lag der Fehler am Auftrag — dann schärfen und einmal neu starten — oder (b)
  an die stärkere Denkstufe/„Experten"-Rolle eskalieren, mit vollständigem Kontext beider Fehlversuche
  (ursprünglicher Auftrag, was jeweils versucht wurde, welche Ausgabe kam zurück, betroffene Dateien, bereits
  ausgeschlossene Ursachen). Den Befund danach verbuchen (Ledger, ggf. Coding-Regeln/Umbauliste). Eskalation
  ist billiger als die dritte Wiederholung.
- Nach jeder Welle: Lint + Typecheck laufen lassen, betroffene Funktionen real ausprobieren; „fertig" nur mit
  Beleg; Journal laufend nachziehen (`AGENTS.md` § Grundregeln).
- Nach jeder Umsetzungswelle kann eine kurze Optimierungsrunde über die neu geschriebenen Stellen laufen —
  Ziel ist Verständlichkeit und Kürze, Geschwindigkeit nur, wo sie ohne Mehrkomplexität zu haben ist;
  höchstens zwei Runden, Verhalten und Tests müssen unverändert bleiben. Ist der Aufwand größer, wird daraus
  ein Vorschlag in der Umbauliste statt einer Änderung.
- Bei eingeschaltetem Logging (`AGENTS.md` § Logging): vor jeder Welle die Entscheidung als
  `[orchestrator] [decision]` schreiben, jede Delegation als `[delegate]`, Start/Ende der Worker als
  `[start]`/`[end]` — sofern das Werkzeug das nicht automatisch tut (Claude Code: Hooks, `CLAUDE.md` § 7).

## Doku-Nachzug

Nach jeder Feature-Welle, jedem produktionsrelevanten Bugfix:

- Neue Schnittstelle/neues Konzept/neue Tabelle → `docs/project/architecture.md` bzw. `features.md` ergänzen
  (knapp, im vorhandenen Stil).
- Neue Konvention gelernt (z. B. eine Framework-Falle) → `docs/project/coding_rules.md`, als Regel formuliert,
  nicht als Anekdote.
- Neue/geänderte Tests → `docs/project/testing.md`.
- `AGENTS.md`/`CLAUDE.md` nur anfassen, wenn sich Grundregeln ändern.
- Schwere Fehler (Build-/Startfehler, Produktionsausfälle, Sicherheitsrelevantes) nach
  `docs/project/incidents/README.md` dokumentieren.
- Grundsatz: Doku beschreibt den IST-Zustand, nicht den Wunsch. Was noch nicht gebaut ist, gehört auf die
  Umbauliste oder ins Fragen-Board. Kein Doku-Eintrag ohne Prüfung am Code.

## Neues Projekt

Wenn ein komplett neues Projekt aus diesem Template entstehen soll — leer oder mit einer schon feststehenden
Idee, das Formular `CONFIG.md` deckt beides ab:

0. Projekt per `git clone <Template-URL> <projekt>` anlegen, damit Projekt und Template eine gemeinsame
   Git-Historie teilen (Voraussetzung für spätere Updates per Merge, siehe § „Template-Update" unten); danach
   `cd <projekt> && git remote rename origin template && git remote add origin <eigene-Repo-URL>`.
   Diesen Schritt kann auch der Assistent übernehmen — es genügt, ihm im Template-Checkout zu sagen, wo das
   Projekt entstehen soll („Erstelle eine neue Anwendung in `<pfad>`"; „leeres Projekt" überspringt das
   Interview zu Ziel und Stack). Ein Zielordner, der bereits Inhalt hat, gehört zur Checkliste „Projekt
   nachrüsten" — dort wird nie hineingeklont.
   **Alternative:** direkt im Template-Checkout einen Branch anlegen (`git switch -c projekt/<name>`). Dann
   entsteht das Projekt als Branch, der Basis-Commit wird aus dem Standard-Branch abgeleitet und Updates
   laufen später per Merge von dort — ohne zusätzlichen Remote. Auf dem Standard-Branch selbst (`main`/
   `master`) verweigert der Anlege-Schritt die Arbeit, sonst würde das Template seine Platzhalter verlieren.
1. `CONFIG.md` im Repo-Root ausfüllen — alles optional, leer lassen ist gültig (Kommentare je Zeile erklären,
   was bei „leer" passiert). Bei Unklarheit mit {{AUFTRAGGEBER}} kurz rückfragen statt zu raten.
2. `python .claude/scripts/new-project.py --dry-run` ausführen, Plan (Werte, zu entfernende Dateien,
   Logging-Schalter, offene Platzhalter) gegen {{AUFTRAGGEBER}} prüfen.
3. `python .claude/scripts/new-project.py --apply` ausführen: ersetzt Platzhalter im ganzen Repo (außer
   `CONFIG.md`, `docs/ai/checklists.md`, `.claude/skills/new-project/SKILL.md`), entfernt nicht genutzte
   Werkzeug-Dateien (nur wenn `KI-Werkzeuge` gesetzt ist), setzt `AI_LOG`/`AI_LOG_LEVEL` in `AGENTS.md` und
   schreibt die Werte (und bei vorhandenem Remote `template` den Basis-Commit) in `.claude/template.json`.
4. Aus den `CONFIG.md`-Abschnitten befüllen: `docs/project/project_description.md` (Ziel, Nutzer, Scope aus
   Features, Non-Scope, Risiken), `docs/project/architecture.md` (Architektur-Text), `docs/project/
   coding_rules.md` § „Stack-spezifisch" (aus Stack), erste Aufgaben aus Features nach `docs/ai/tasks.md`,
   offene Platzhalterwerte/Lücken nach `docs/ai/questions.md`, Stand nach `docs/ai/board.md`. Bei leerem
   `CONFIG.md` bleiben die Skelette bestehen — nur Name/Datum sind gesetzt.
5. Werkzeug-Verweise prüfen: `docs/README.md`-Index und `AGENTS.md`-Tabelle „Werkzeugspezifische
   Ergänzungsdateien" gegen die tatsächlich noch vorhandenen Dateien.
6. Ersten `docs/ai/ledger.md`-Eintrag „Projekt angelegt aus CONFIG.md" schreiben — mit allen Setzungen
   (eingesetzte Werte, entfernte Dateien, Logging-Schalter).
7. `python .claude/scripts/new-project.py --finish` ausführen (prüft die Vorbedingungen aus Schritt 4/6,
   entfernt danach `CONFIG.md`).
8. `grep -rn "{{" .` prüfen — nur die Scripte in `.claude/scripts/` (Code-Literale bzw. Kopfkommentare,
   siehe `no_replace` in `.claude/template.json`) und `CONFIG.md` dürfen noch Platzhalter zeigen, alles
   andere klären.
9. Commit per Pathspec nach Freigabe (Checkliste „Aufgabe abschließen").

## Projekt nachrüsten

Wenn ein bestehendes Repo (eigene Historie, kein Template-Klon) die Agentic-Coding-Grundausstattung
nachträglich bekommen soll:

1. Aus dem Template-Checkout heraus: `python <template>/.claude/scripts/consume-template.py --target
   <ziel-repo>` ausführen — kopiert `AGENTS.md`, die Werkzeug-Verweisdateien, `.claude/`, `docs/ai/`,
   `docs/project/`-Skelette, `CONFIG.md` u. a. ins Ziel, ohne dort etwas zu überschreiben (Ausnahmen/Details
   im Kopfkommentar des Scripts). Schreibt `.claude/template.json` mit Basis-Commit/Remote-URL des Templates
   und legt im Ziel den Remote `template` an.
2. Im Ziel-Repo weiterarbeiten: `git status` sichten, den Arbeitsbaum **committen** (Voraussetzung für
   Schritt 3). Dateien, die im Ziel schon existierten, wurden nicht überschrieben — sie werden in Schritt 3
   zusammengeführt.
3. **Struktur-Migration** (Entscheidung von {{AUFTRAGGEBER}}: `CONFIG.md` § `Struktur-Migration` = `ja` |
   `nein` | `fragen`; beim Default `fragen` den Plan zeigen und einmal im Gespräch nachfragen, ohne Antwort
   nicht migrieren). Bei „ja":
   - Vorhandene KI-Arbeitsordner (heißen je nach Projekt `fable/`, `ai/`, `ki/`, `docs/fable/`, …) auf die
     Template-Struktur umstellen: Board, Aufgaben, Fragen, Ledger, Umbauliste wandern unter ihren
     Template-Namen nach `docs/ai/`. Verschieben statt kopieren, damit die Versionsgeschichte erhalten bleibt.
     Kollidiert eine Altdatei mit einer schon vorhandenen, wird sie danebengelegt statt überschrieben (nur
     inhaltsgleiche Dubletten entfallen). Dateien in Unterordnern (z. B. `archiv/`) werden aufgelistet, aber
     nicht automatisch zugeordnet; leer gewordene Altordner werden nur gemeldet, nie selbst gelöscht.
   - Den bisherigen Rufnamen des Orchestrators (oft der Name des alten Ordners) **projektweit** durch den
     neuen ersetzen — auch in Ledger, Chatlogs und Archiven.
   - Vorhandene Regeldateien mit dem Template zusammenführen. Prioritäten: **Template gewinnt** bei allem, was
     Agenten, Skills und Zusammenarbeitsregeln betrifft (projektspezifische Ergänzungen werden eingearbeitet,
     nicht verworfen); **Template-Struktur mit Projekt-Inhalt** bei den Arbeitsdateien; **das Projekt gewinnt**
     in `docs/project/` (vorhandene Projektdefinition hat Vorrang) und bei `README.md`/`.gitignore`, die nur
     ergänzt werden; **die strengere Regel gewinnt** in den Coding-Regeln — strengere Vorgaben des Templates
     werden immer übernommen.
4. Bestand analysieren — nicht raten, am Code prüfen: Name, Stack, Struktur, Tests, Befehle, CI.
5. `CONFIG.md` mit dem gefundenen IST-Zustand befüllen, dann `python .claude/scripts/new-project.py --apply`
   ausführen (ersetzt Platzhalter, entfernt nicht genutzte Werkzeug-Dateien, setzt Werte).
6. `docs/project/*` mit dem echten IST-Zustand befüllen (nicht raten), `.gitignore`-Vorschläge übernehmen, im
   Projekt-`README.md` einen Abschnitt „Zusammenarbeit mit KI-Assistenten" ergänzen (Verweis `AGENTS.md`,
   `docs/ai/board.md`).
7. **Code-Analyse (optional, Entscheidung von {{AUFTRAGGEBER}}):** Entweder vorab über `CONFIG.md`
   § `Code-Analyse` (`nein` | `vorschlagen` | `fragen`) oder — beim Default `fragen` — als einzelne Rückfrage
   im Gespräch, **nachdem** `docs/project/` befüllt ist. Bei „ja": den Bestand read-only prüfen (Struktur,
   Duplikate, tote Pfade, fehlende Tests, veraltete Abhängigkeiten, Sicherheitsrisiken) und das Ergebnis
   **nur** als priorisierte Vorschläge nach `docs/ai/backlog.md` schreiben (Sicherheit zuerst, je Punkt
   Befund, Fundstelle, Vorschlag, Aufwand). Kein Code wird geändert; Umsetzung erst, wenn {{AUFTRAGGEBER}}
   einen Punkt freigibt und er als Aufgabe in `tasks.md` landet.
8. Ersten `docs/ai/board.md`-Stand und `docs/ai/ledger.md`-Eintrag schreiben, danach
   `python .claude/scripts/new-project.py --finish` ausführen.
9. Commit per Pathspec nach Freigabe.
10. `python .claude/scripts/template-update.py --graft` ausführen (nach Freigabe) — stellt per leerem
   Merge-Commit eine gemeinsame Historie mit dem Template her, ohne den Arbeitsbaum zu verändern;
   Voraussetzung für spätere `/template-update`-Läufe.

## Template-Update

Wenn Änderungen aus dem Template (übergeordnetes Vorlagen-Repo, per Remote „template" verbunden) in ein
bereits laufendes, abgeleitetes Projekt nachgezogen werden sollen — die eingesetzten Platzhalterwerte
(Projektname, Auftraggeber, Befehle, …) und die projektspezifische Doku (`docs/project/`, `docs/ai/`-
Arbeitsdateien, README) bleiben dabei erhalten:

1. Verfügbare Änderungen abrufen (fetch) und sichten: wie viele Commits, welche Dateien betroffen.
2. Prüfen, welche der betroffenen Dateien projektspezifisch sind (bleiben unverändert) und welche die
   Template-Logik übernehmen sollen.
3. Änderungen per Merge einspielen.
4. Bei Konflikten: projektspezifische Dateien/Bereiche (siehe `keep_local` in `.claude/template.json`)
   gewinnen bei gewöhnlichen Konflikten automatisch; alle übrigen werden **inhaltlich zusammengeführt**, nie durch Wegwerfen einer Seite
   gelöst. Dazu jeweils beide Fassungen lesen und die Absicht dahinter erkennen:
   - **Beide Seiten geändert:** Template-Fassung als Gerüst, projektspezifische Zeilen (echte Werte, eigener
     Stack, zusätzliche Agenten/Skills) hineinziehen. Nur bei echtem Widerspruch entscheidet die Priorität —
     Template-Logik in `.claude/`, `AGENTS.md`, `CLAUDE.md` und den Checklisten, Projekt in `docs/project/`,
     strengere Regel bei den Coding-Regeln; der verworfene Teil wird im Journal genannt.
   - **Vom Projekt gelöscht, im Template geändert:** erst prüfen, ob die Datei im Projekt unter anderem Namen
     weiterlebt (umstrukturierter Arbeitsordner ist der Normalfall). Dann gehört die Template-Änderung in die
     neue Datei, und die alte bleibt gelöscht. Wurde die Datei dagegen bewusst entfernt, bleibt sie weg.
     Sobald ein Umbenennungs-Kandidat erkennbar ist, wird der Fall immer vorgelegt statt automatisch
     entschieden; nur ohne Kandidat und bei einer ohnehin projekteigenen Datei bleibt es automatisch bei
     „gelöscht".
   - Hat das Projekt Inhalte anders verteilt oder zusammengezogen, wandert die Änderung dorthin, wo das Thema
     im Projekt tatsächlich steht — eine gewachsene Struktur wird nicht auf das Template-Schema zurückgedreht.
5. In den vom Update berührten Dateien Platzhalter durch die bereits im Projekt eingesetzten echten Werte
   ersetzen (kommt z. B. vor, wenn das Template eine neue Datei mit einem Platzhalter der Form `{{NAME}}` mitbringt).
6. Prüfen: keine verbleibenden Platzhalter außer den bekannten Fundstellen in den Checklisten/Skills selbst,
   Konfigurationsdateien weiterhin gültig, Logging weiterhin funktionsfähig.
7. Commit per Pathspec.
8. Den nachgezogenen Basis-Commit des Templates in `.claude/template.json` fortschreiben, damit das nächste
   Update wieder ab diesem Stand vergleicht.
