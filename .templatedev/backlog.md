> Datenstand: 2026-09-14 – Status: aus dem Ordner .templatedev/ des Templates übernommen

# Umbauliste — Template-Entwicklung

Priorisierte Verbesserungsvorschläge für das **Template**; Checkout unter
`D:/dev/rufeger/template-agentic-coding-project`. Marker direkt am Punkt („-> machen", „-> später",
„-> nein, weil …"). Nummern werden nie neu vergeben; umgesetzte Punkte wandern als Einzeiler nach
„Erledigt".

Die Punkte 1–21 stammen aus dem früheren Ordner `.templatedev/` im Template und behalten ihre Nummern —
sie werden in Journal und Commits zitiert.

---

22. -> machen: **Erkenntnisse aus `bandliste` auf Template-Relevanz prüfen** (Priorität hoch, angelegt
   2026-09-14): Der Kernzweck dieser Ablage — bisher nie systematisch gelaufen. Im Weg-2-Testprojekt sind an
   einem Tag 26 beantwortete Fragen und ADR-7 bis ADR-32 entstanden, dazu ein Backlog mit über 50 Punkten.
   Vorgehen: `docs/ai/questions_archive.md`, `questions.md` und `ledger.md` in `D:\dev\rufeger\bandliste`
   durchgehen und je Punkt entscheiden — Template-Regel, Baustein unter `docs/project/coding_rules.d/`, neuer
   Agent oder Skill, oder nichts. Was ins Template gehört, bekommt hier eine eigene Nummer; umgesetzt wird im
   Template, nicht in der Notiz. **Umfang unbekannt:** Erst nach dem Durchgang lässt sich sagen, ob das eine
   Sitzung wird oder mehrere; bei mehr als etwa zehn Kandidaten in Teilaufgaben je Themenbereich schneiden.

23. -> erledigt (2026-09-14), teils überholt durch Punkt 24: **Design-Wege über `/design` hinaus.** Recherchiert und in `CLAUDE.md` § 5
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
