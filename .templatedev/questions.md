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

---
