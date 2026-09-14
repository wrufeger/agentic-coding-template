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

29. -> offen: **Rückmeldung abgeleiteter Projekte** (Priorität offen, angelegt 2026-09-14): Projekte, die aus
   dem Template entstehen, sollen sich freiwillig als Testkandidat melden (Datum, öffentliche Repo-URL, Weg
   neu/nachgerüstet, Ausfüllart leer/Interview/Config), damit `.templatedev` ihre Weiterentwicklung auswerten
   kann. Konzept mit vier Optionen und Aufwand: `konzept-feedback.md`. **Erst entscheiden** (`Q1`–`Q3`),
   dann bauen — es geht um fremde Daten, und eine Gegenstelle gibt es heute nicht.
   Der Schalter `Feedback` in `AI-CONFIG.md` ist deshalb **noch nicht angelegt**.

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
