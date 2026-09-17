> Datenstand: 2026-09-14 – Status: aus dem Ordner .templatedev/ des Templates übernommen

# Backlog — Template-Entwicklung

Priorisierte Verbesserungsvorschläge für das **Template**; Checkout unter
`D:/dev/rufeger/template-agentic-coding-project`. Marker direkt am Punkt („-> machen", „-> später",
„-> nein, weil …"). Nummern werden nie neu vergeben; umgesetzte Punkte wandern als Einzeiler nach
„Erledigt".

Die Punkte `B1`–`B21` stammen aus dem früheren Ordner `.templatedev/` im Template und behalten ihre Nummern —
sie werden in Journal und Commits zitiert.

---

22. -> machen: **Erkenntnisse aus `bandliste` auf Template-Relevanz prüfen** (Priorität hoch, angelegt
   2026-09-14): Der Kernzweck dieser Ablage — bisher nie systematisch gelaufen. Im Weg-2-Testprojekt sind an
<!-- check-refs:ignore -->
   einem Tag 26 beantwortete Fragen und ADR-7 bis ADR-32 entstanden, dazu ein Backlog mit über 50 Punkten.
   (Die genannten Nummern gehören zum Testprojekt, nicht zu diesem Repo — daher oben der Ignorier-Marker.)
   Vorgehen: `docs/ai/questions_archive.md`, `questions.md` und `ledger.md` in `D:\dev\rufeger\bandliste`
   durchgehen und je Punkt entscheiden — Template-Regel, Baustein unter `docs/project/coding_rules.d/`, neuer
   Agent oder Skill, oder nichts. Was ins Template gehört, bekommt hier eine eigene Nummer; umgesetzt wird im
   Template, nicht in der Notiz. **Umfang unbekannt:** Erst nach dem Durchgang lässt sich sagen, ob das eine
   Sitzung wird oder mehrere; bei mehr als etwa zehn Kandidaten in Teilaufgaben je Themenbereich schneiden.

23. -> erledigt (2026-09-14), teils überholt durch Punkt `B24`: **Design-Wege über `/design` hinaus.** Recherchiert und in `CLAUDE.md` § 5
   als Tabelle aufgenommen: Screenshot direkt einfügen (Grenzen: 8000 × 8000 px, 10 MB, unter 200 px
   unzuverlässig), Webseite über einen Chrome-Screenshot statt `WebFetch` (das liefert nur HTML als Text),
   Figma über den offiziellen MCP-Server (remote per Plugin oder Desktop über `127.0.0.1:3845/mcp`, als
   Beispiel in `.mcp.json.example`), `.psd` nur über PNG-Export. Kernaussage des Abschnitts ist jetzt der
   **Rückkanal**: die laufende Anwendung in Claude in Chrome öffnen und das Gebaute gegen die Vorlage prüfen —
   Anthropic nennt genau diesen Ablauf als Beispiel. Faustregel für ein bestehendes Projekt mit
   Komponentenbibliothek: Screenshot → echter Code → Prüfung im Browser, ohne Zwischenformat.

24. -> erledigt (2026-09-14): **Design-Schalter raus, MCP-Katalog und drei Design-Skills rein.** Der Schalter
   `Design` für Claude Design ist zurückgebaut — ein Schalter für ein einzelnes Cloud-Werkzeug war der
   falsche Zuschnitt. Stattdessen: `.claude/mcp-katalog.md` mit 21 geprüften MCP-Servern (Kennung, Anbieter,
   Transport, Secrets, Reifegrad, Einbindungsbefehl), auswählbar über `AI-CONFIG.md` § `MCP-Server`; dazu die
   Skills `/design-ideas` (drei bis vier Varianten als Playwright-Screenshots zur Auswahl), `/design-build`
   (umsetzen im echten Code, Selbstprüfung im Browser, höchstens drei Runden) und `/design-assets` (Logo,
   Icons, Favicons als SVG; Rasterbilder nur über ein Bildmodell per MCP).
   **Zwei Befunde aus der Recherche, die den Zuschnitt bestimmt haben:** Claude erzeugt keine Rasterbilder —
   SVG ist Code und geht, alles Fotorealistische braucht einen externen Dienst mit Kosten je Bild. Und rein
   KI-generierte Werke sind nicht automatisch urheberrechtlich geschützt (menschlicher Schöpfungsanteil
   nötig) — bei einem Logo ist das wichtiger als die Bildqualität, steht deshalb im Skill.

25. -> machen: **MCP-Auswahl aus `AI-CONFIG.md` automatisch einrichten** (Priorität mittel, angelegt
   2026-09-14): Der Schlüssel `MCP-Server` hält heute nur fest, welche Server zum Projekt gehören —
   eingerichtet werden sie von Hand. Zu bauen: `sync-config.py` liest die Kennungen, gleicht sie gegen
   `.claude/mcp-katalog.md` ab und schreibt die Einträge nach `.mcp.json` (Secrets nur als `${VAR}`, nie
   Werte). Aufnehmen läuft automatisch durch, **Entfernen braucht eine Zusage** — in `.mcp.json` kann
   inzwischen projekteigene Konfiguration stehen. Dazu: unbekannte Kennungen melden statt still übergehen,
   und die benötigten Umgebungsvariablen in `.env.example` ergänzen, damit sichtbar ist, was fehlt.
   Voraussetzung ist ein maschinenlesbarer Katalog — die Markdown-Tabelle taugt dafür nur bedingt, ein
   `.claude/mcp-katalog.json` neben der Doku wäre der sauberere Weg.

26. -> erledigt (2026-09-14): **README des Zielprojekts blieb der Vorlagentext.** In `bandliste` stand nach
   dem Nachrüsten immer noch der englische „Nuxt Minimal Starter" — die Regel verlangte nur, einen Abschnitt
   „Zusammenarbeit mit KI-Assistenten" zu **ergänzen**, und genau das war geschehen: Einleitung oben,
   Starter-Text darunter, doppelte Installationsanweisungen für vier Paketmanager. Skill und Checkliste
   verlangen jetzt, die README zu **prüfen und zu überarbeiten**, wenn sie erkennbar nie angefasst wurde,
   mit Vorgabe für den Aufbau (Schnellstart, Befehlstabelle, Struktur, Doku-Wegweiser) und der Auflage,
   ehrlich zu bleiben — was rot ist oder fehlt, gehört sichtbar in die Tabelle.
   **Nachtrag am selben Tag:** Der erste Versuch war trotzdem falsch — die README begann mit dem technischen
   Schnellstart, die Arbeitsweise stand als Abschnitt weit unten. Bei einem Projekt, das mit KI-Assistenten
   entwickelt wird, gehört genau das nach oben, direkt nach der Einleitung, und zwar für Menschen lesbar mit
   `AI-CONFIG.md` an erster Stelle. Die Regel sagt das jetzt ausdrücklich, samt Aufbau.
   Die Lehre dahinter, zweimal dieselbe: **„ergänzen" und „erwähnen" sind schwache Anweisungen.** Wo die
   Position und die Lesart zählen, muss die Regel beides vorgeben — sonst landet der wichtigste Teil unten
   und liest sich wie eine Dateiliste.

27. -> machen: **Sprache aus `AI-CONFIG.md` wirkt nicht** (Priorität hoch, angelegt 2026-09-14): Der
   Schlüssel `Sprache` steht in der Konfiguration, hat aber keine Wirkung — das Template ist durchgehend
   deutsch, und ein angelegtes Projekt bleibt es auch. Zwei Teile:
   **(a) Template auf Englisch umstellen.** Für die Veröffentlichung auf GitHub ist Deutsch die falsche
   Ausgangssprache. Betrifft `AGENTS.md`, `CLAUDE.md`, `README.md`, alle Checklisten, Skills, Agenten-Rollen,
   Regelbausteine, Doku-Skelette und die Ausgaben der Scripte — der größte Einzelposten dieser Liste.
   **(b) Sprache beim Anlegen und Nachrüsten anwenden.** Steht in `AI-CONFIG.md` § `Sprache` etwas anderes
   als die Ausgangssprache, wird das Zielprojekt darin geführt: Doku, Kommentare, Commit-Messages **und die
   Kommunikation des Assistenten** im Projekt. Das ist keine reine Textersetzung — die Vorlagen müssten
   entweder zweisprachig vorliegen oder beim Anlegen übersetzt werden.
   **Zu klären, bevor jemand anfängt:** Werden die Vorlagen zweisprachig gepflegt (doppelter Pflegeaufwand,
   dafür verlässlich) oder beim Anlegen einmalig übersetzt (billiger, aber jede Template-Aktualisierung
   trifft danach auf übersetzten Text und `/update-template` bekommt Konflikte in jeder Zeile)? Diese
   Entscheidung bestimmt den ganzen Rest — vorher keine Zeile übersetzen.

28. -> machen: **`no_replace` steht in `AGENTS.md` anders als in `template.json`** (Priorität niedrig,
   angelegt 2026-09-14): `AGENTS.md` § „Template-Herkunft und Updates" nennt `docs/ai/checklists.md` und
   `.claude/skills/create-project/SKILL.md` als nie platzhalter-ersetzt; `.claude/template.json` führt unter
   `no_replace` aber nur die drei `.py`-Dateien, und `EXCLUDED_FROM_REPLACE` in `setup-lib.py` deckt sich mit
   der JSON-Fassung. **Dritte Fundstelle:** `docs/ai/checklists.md` § „Neues Projekt", Schritt 3 behauptet
   dasselbe wie `AGENTS.md` („ersetzt Platzhalter im ganzen Repo außer `AI-CONFIG.md`,
   `docs/ai/checklists.md`, `.claude/skills/create-project/SKILL.md`"). Zwei Dokumente sagen das eine, der
   Code das andere. Erst prüfen, welche Fassung gewollt ist (zeigen die
   beiden Dateien Platzhalter absichtlich als Beispiel?), dann die andere angleichen — nicht blind eine Liste
   erweitern. Gefunden beim Einbau der Statuszeilen-Ersetzung.

29. -> in Arbeit: **Rückmeldung abgeleiteter Projekte** (Priorität offen, angelegt 2026-09-14): Projekte, die aus
   dem Template entstehen, sollen sich freiwillig als Testkandidat melden (Datum, öffentliche Repo-URL, Weg
   neu/nachgerüstet, Ausfüllart leer/Interview/Config), damit `.templatedev` ihre Weiterentwicklung auswerten
   kann. Konzept mit vier Optionen und Aufwand: `konzept-feedback.md`. **Erst entscheiden** (`Q1`–`Q3`),
   dann bauen — es geht um fremde Daten, und eine Gegenstelle gibt es heute nicht.
   **Stand 2026-09-14:** `Q1`–`Q3` beantwortet (eigener Endpunkt, Frage einmalig bei `/finalize`; die
   Steuerung ist inzwischen doch in `AI-CONFIG.md` gelandet, siehe Nachtrag im Konzept). **Client-Seite
   gebaut** (`.claude/scripts/feedback.py`), Schnittstellenvertrag im Konzept.
   **Stand 2026-09-15:** **beide Gegenstellen gebaut** — `.templatedev/scripts/feedback-endpunkt.php`
   (öffentliches `POST`, JWT-geschütztes `GET /inbox` + `POST /ack`) und
   `.templatedev/scripts/feedback-abholen.py`; belegt gegen einen laufenden `php -S`. Dazu: das
   Sendeprotokoll im Projekt ist auf Wunsch gitignorierbar (`feedback.py --enable --protokoll lokal`), und
   Abgeholtes ist hier grundsätzlich gitignored.
   **Offen:** Ausrollen auf `rufeger.de` (Datei, Geheimnis, Ablage außerhalb des Web-Roots), Datenschutz-
   hinweis unter der URL, danach die eigentliche Auswertung.

30. -> **erledigt 2026-09-15** (Beleg im Ledger): **Löschen trifft nie ungesicherte Dateien** (angelegt und
   entschieden 2026-09-15): `remove_maintenance_files`, `remove_optimizer_files` und `remove_tool_files` (setup-lib.py)
   löschen Pfade, ohne zu prüfen, ob sie überhaupt anderswo liegen. `.claude/maintenance/reports/` ist
   gitignored — beim Abschalten der Wartung sind die Berichte unwiederbringlich weg. Umsetzung: gemeinsamer
   Helfer, der vor dem Löschen `git status --porcelain --ignored -z -- <pfad>` fragt; gitignorierte,
   ungetrackte und lokal geänderte Pfade bleiben liegen und werden zurückgemeldet (Muster: `rename-lib.py`
   B10, `git check-ignore`). Kein Git-Repo = nicht prüfbar = liegen lassen und melden. Verworfene Alternative
   (`.bak`/`.disabled` statt Löschen): veraltet gegenüber dem Template, verschmutzt Diffs, spart die
   CLAUDE.md-Arbeit nicht.

31. -> **erledigt 2026-09-15** (Beleg im Ledger): **Abgewählte Pfade bleiben beim Template-Update draußen**
   (angelegt 2026-09-15): Wer
   `Wartung: aus`, `Code-Optimierung: aus` oder ein KI-Werkzeug abwählt, bekommt die Dateien beim nächsten
   `update-template.py --apply` teilweise zurück. Belegt an `update-template.py:1025-1070`: (a) ändert das
   Template eine gelöschte Datei, entsteht ein `DU`-Konflikt, der nur für `keep_local`-Pfade automatisch
   „gelöscht belassen" wird — `optimizer.md` und `.claude/maintenance/**` stehen dort nicht, also kommt bei
   jedem Update eine Rückfrage; (b) legt das Template eine **neue** Datei in dem Bereich an, wird sie
   konfliktfrei hinzugefügt, ohne dass jemand gefragt wird.
   Umsetzung: `update-template.py` leitet die abgewählten Pfade zur Merge-Zeit aus
   `.claude/template.json` § `applied_config` ab (`Wartung`, `Code-Optimierung`, `KI-Werkzeuge` gegen
   `MAINTENANCE_REMOVE_PATHS`/`OPTIMIZER_REMOVE_PATHS`/Werkzeugpfade in `setup-lib.py`) und behandelt sie für
   diesen Lauf wie `template_only`: `DU` ohne Rückfrage gelöscht belassen, neu hinzugekommene Dateien
   darunter nach dem Merge entfernen (`_remove_template_only()` als Muster). Keine neue Liste in
   `template.json` — sie würde gegenüber `AI-CONFIG.md` veralten; schaltet jemand auf `ein`, fällt der
   Ausschluss von selbst weg. 
32. -> **umgesetzt 2026-09-15** bis auf die Endpunkt-Inbetriebnahme (Beleg im Ledger; offen bleiben das
   Ausrollen auf `rufeger.de` samt Datenschutzhinweis und die Frage, ob `Feedback` beim Abschluss der
   Einrichtung aktiv angeboten statt nur erwähnt wird): **Feedback muß nochmal neu bearbeitet werden**:
     Frage nach Erstellung oder Anbindung einer App nach Feedback: ja (empfohlen) oder nein
     bei ja:
       - Umfang: nur einmalige Registrierung(Art,Datum,KI-Tools,Stack) und manuelles Feedback direkt als Antwort, alles (ohne (d) also ohne echte Projektdaten, empfohlen), wirklich alles oder
        (mehrere auswählbar)
        a) statistische Daten (Art der Erstellung, Datum, Häufigkeit der Nutzung, Anteil KI-generierter Code, Häufigkeit von Änderungen an docs/ai, Anzahl
        Dateien im Repo, Größe des Repo, öffentliche Repo URL des Projekts ?, ...)
        b) Änderungen an Dateien und Daten die KI betreffend (AGENTS.md, CLAUDE.md, .claude/agents, .claude/skills, ...) oder wenn Änderungen an der Struktur von Dateien in docs besprochen werden (xy als Tabelle, Abschnitt xy mit mehreren Zeilen und Einrückung darstellen, backlog um Spalte xy erweitern, ... was auch immer eine Optimierung und kein "Inhalt" ist, also OHNE echte Dateien aus docs/ai)
        c) Tool-Nutzung (MCP server zugefügt, skill aktualisiert oder erstellt, agent definiert oder geändert, neues script oder aktualisiert, ...)
        d) Änderung auch an docs/ai und docs/project (hier zwar nur wirklich relevante Änderungen, aber auch echte Dateien mit Inhalt)
     - Häufigkeit: autom. (empfohlen, wöchentlich macht keinen Sinn bei Entwicklern, die nur 1x die Woche coden, also autom. an das Nutzerverhalten angepasst, User wird je nach Feedback-Anzahl, Dringlichkeit (z.B. krit. Fixes), Datum des letzten Sendes, Häufigkeit der Arbeit am Projekt, ... autom. an Feedback erinnert oder der Prozess autom. angestossen), max. tägl., max. wöchentlich, manuell mit "/send-feedback" oder "schicke Feedback"
     - Bestätigung: Diskrete Nachfrage im Chat, ob das gesammelte Feedback in docs/ai/template-feedback gesendet werden darf (empfohlen), autom. im Hintergrund
     - Ordner template-feedback in .gitignore zufügen? nein (empfohlen), ja

     docs/ai/template-feedback/
        - hier wird von der lokalen AI des Projektes gesammeltes Feedback in Dateien hinterlegt. Gesammelt werden soll nur der freigegebene Umfang und auch nur dann,
          wenn die Daten sinnvolle Ergänzungen im Template Project darstellen könnten (Optimierungen, v.a. am Arbeitsablauf, Kommunikation KI/Mensch, Texten im Template Project, Scripten, ...)
          Gespeichert wird eine [name|title|subject].md mit einer textuellen Zusammenfassung, sowie eine [name|title|subject].json mit den Daten, die besser im Template Projekt verarbeitet werden können.
          Beim Senden Dateien in den Unterordner sent/ verschieben.
        - feedback.md (hier kann der Entwickler selbst Feedback senden. Ein paar vorgefertigte Fragen beantworten, Feedback in Textform, Vorschläge und Ideen, Programmiererfahrung, Erfahrung mit KI, ...).
          Beim Senden beantwortete Fragen und Textantworten zusammenfassen und ans Ende der Datei anfügen, dann Fragen und Abschnitts-Überschriften wiederherstellen für ein weiteres oder späteres Feedback

    Werden alle Fragen mit ok bestätigt, also die Empfehlungen angenommen, so wird Feedback wahrscheinlich wöchentlich nach kurzer Rückfrage gesendet und dabei auf den Ordner docs/ai/template-feedback/ verwiesen, um ggf. feedback.md manuell zu ergänzen.
    Das solle datenschutkonform sein und nicht zu aufdringlich. Frequenz und Umfang soll der User ja jederzeit über die AI-CONFIG umstellen können.

    **Entschieden am 2026-09-15 (Wolfgang), drei Punkte, die den Bau bestimmen:**
    - **Umfang `d` entfällt.** Echte Dateien aus `docs/ai`/`docs/project` widersprechen der Zusage in
      `AGENTS.md` („nie Dateien, nie Projektbezug") und dem Filter in `feedback.py`, der Pfade, Mailadressen
      und IPs pauschal ablehnt. `b` meldet Strukturänderungen weiterhin — aber als **Beschreibung**
      („Backlog um Spalte X erweitert"), nicht als Datei.
    - **Statistiken (`a`) kommen aus `git log` und dem Dateisystem**, `ai.log` nur, wenn es vorhanden ist.
      Was sich daraus nicht ermitteln lässt, wird **weggelassen statt geschätzt**.
    - **Der adaptive Takt bekommt einen eigenen `SessionStart`-Hook**, unabhängig von der Wartung — die ist
      abwählbar, der Hook dort wäre bei `Wartung: aus` verschwunden.

    **Schnitt in Aufgaben** (in dieser Reihenfolge, jede mit eigenem Beleg):
    1. `AI-CONFIG.md`: neuer Schlüssel `Feedback-Umfang` (Mehrfachauswahl `a,b,c`, Default `a,b,c`),
       `Feedback-Takt` um `adaptiv` erweitern; `sync-config.py` erkennt und setzt beides um.
    2. Erhebung je Umfang in `feedback.py` (git log, Dateisystem, `ai.log` falls vorhanden).
    3. Ablage umbauen: `<subject>.md` + `<subject>.json` unter `docs/ai/template-feedback/`, beim Senden
       nach `sent/` verschieben; der bisherige Ausgang `.claude/feedback-outbox.json` entfällt.
    4. `feedback.md` als Fragebogen anlegen (Fragen, Freitext; beim Senden Antworten zusammenfassen, ans
       Dateiende anfügen, Fragen und Überschriften wiederherstellen).
    5. Eigener `SessionStart`-Hook für die Erinnerung beim Takt `adaptiv`.
    6. Endpunkt auf Schema 2 (`.templatedev/scripts/feedback-endpunkt.php`): neue Felder, Wortlisten,
       32-KB-Deckel prüfen.
    7. Zusagetexte nachziehen: `AGENTS.md`, `/finalize`, `/feedback`, `docs/ai/template-feedback/README.md`.

33. -> machen: **Aufgaben für den Auftraggeber erst eintragen, wenn sie ausführbar sind** (angelegt
   2026-09-16): Wolfgang liest „Aufgaben nur für {{AUFTRAGGEBER}}" als Arbeitsliste und führt die Schritte
   nacheinander aus — eine `Offen:`-Zeile hält ihn davon nicht ab (Anlass: die Test-Aufgabe für
   `bandliste` in `.templatedev/tasks.md` stand dort, bevor T1–T3 gebaut und gepusht waren). Regel für `AGENTS.md` § Tabu-Bereich und
   `docs/ai/README.md`: Eine Aufgabe für den Auftraggeber erscheint erst, wenn alle Voraussetzungen erfüllt
   sind (Code gepusht, Fragen beantwortet); bis dahin steht sie als Folgeschritt in der Aufgabe des
   Assistenten, die sie auslöst.

34. -> später: **Issue-Tracker ohne Git anbinden — Jira, YouTrack, Linear** (angelegt 2026-09-16): `/issue`
   und `/integrations` (T1, T3) bauen zunächst nur GitLab und GitHub (Q11). Danach dieselben Abläufe über MCP
   (`atlassian`, `linear`); YouTrack fehlt noch im Katalog `.claude/mcp-katalog.md`.

35. -> Idee, Priorität gering: **Pflege-Modus im Root per `.env`** (angelegt 2026-09-17): `TEMPLATEDEV_MODE=ein`
   lässt eine Sitzung im Root so arbeiten, als liefe sie in `.templatedev/` — Hook-Hinweis, Scripte mit
   `.templatedev/` als Projektordner, Sperren für `create-project`/`apply-template`/`finalize`. Grenzen und
   Aufwand (~0,5 PT): `concept-project-structure.md` § „Pflege-Modus im Root". Entscheidung: Q15.

## Erledigt

2026-09-13 (3. Runde):

- 21 · `.templatedev.md` und `.github/README.md` wandern nicht mehr per Merge ins Projekt: dritte Liste
  `template_only` neben `keep_local`/`no_replace` (`update-template.py`, `template.json`). Gefunden beim
  ersten echten `/update-template` an einem Fremdprojekt — der Weg war bis dahin nie unter realen
  Bedingungen gelaufen.

2026-09-13 (2. Runde) — die restlichen sieben Punkte, Details im Journal:

- 2 · Permissions eng gefasst: `--apply`/`--finish` fragen nach, `git fetch template` exakt (`settings.json`).
- 7 · `status.json` und `template.json` werden atomar geschrieben (`maintenance-check.py`,
  `update-template.py`, `setup-lib.py`).
- 16 · Umbenennung des Rufnamens zeigt vorher eine Zeilen-Trefferliste, Schreiben erst mit `--yes`
  (`rename-lib.py`).
- 17 · Restplatzhalter-Meldung trifft nur noch echte Marken in Doku/Regeldateien, nicht Vue-Mustache
  (`setup-lib.py`).
- 18 · Fremde KI-Regeldateien werden erkannt und als eigene Kategorie gemeldet (`rename-lib.py`).
- 19 · Einrichtung wird abgeschlossen statt liegengelassen: `finish-setup.py`, Skill `/finalize`,
  SessionStart-Erinnerung, Bibliothekstrennung `setup-lib.py`/`rename-lib.py`.
- 20 · Fremde Regeldateien werden eingearbeitet und auf einen Verweis eingedampft (Checkliste,
  `/apply-template`, Meldung in `finish-setup.py`).

2026-09-13 — dreizehn Punkte umgesetzt, Details im Journal:

- 1 · `template.json` wird feldweise gemergt (`update-template.py`).
- 3 · Platzhalter-Ersetzung erhält CRLF (`update-template.py`).
- 4 · Ablageort der Wartungsberichte per `AI-CONFIG.md` wählbar (`create-project.py`).
- 5 · Fußnoten-Konvention für fehlende Datenstände (`docs/README.md`).
- 6 · Incident als Einzeldatei beschrieben (`docs/project/incidents/README.md`).
- 8 · Hook-Entfernung trifft nur die vom Template gesetzten Hooks (`create-project.py`).
- 9 · Leere Argumente brechen mit Exit 2 ab (`maintenance-check.py`).
- 10 · Gitignorierte Dateien werden gemeldet statt verschoben (`migrate-project.py`).
- 11 · Namensersetzung lässt Code-Blöcke und URLs aus (`migrate-project.py`).
- 12 · Umbenennung auf beiden Seiten wird erkannt (`update-template.py --conflicts`).
- 13 · UTF-8-Ausgabe in allen sieben Scripten.
- 14 · Tote Konstante `PRIORITY_RULES` entfernt (`update-template.py`).
- 15 · Merge-Kandidaten um Werkzeug-Verweisdateien ergänzt (`migrate-project.py`).

---
