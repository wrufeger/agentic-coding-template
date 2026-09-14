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
   * Antwort:

**Q2 · Welcher Standardwert für den Schalter `Feedback`?**

   Vorgeschlagen wurde `ja` als Default. Ich rate ab: Ein voreingestelltes „ja" ist eine
   Einwilligung, die niemand erteilt hat — und es trifft nicht dich, sondern fremde
   Entwickler, die das Template klonen.
   a) `fragen` — beim Abschluss der Einrichtung einmal fragen, ohne Antwort passiert
      nichts (Empfehlung)
   b) `ja` — standardmäßig melden, wer nicht will, schaltet ab
   c) `nein` — standardmäßig aus, wer will, schaltet ein
   * Antwort:

**Q3 · Gehört der Schalter überhaupt nach `AI-CONFIG.md`?**

   Alle Schlüssel dort wirken **laufend**; dieser wirkt genau einmal, beim Abschluss der
   Einrichtung. Das ist ein Fremdkörper in der Datei.
   a) trotzdem in `AI-CONFIG.md` — ein Ort für alle Einstellungen (Empfehlung)
   b) nur als einmalige Frage in `/finalize`, gar kein Schlüssel
   * Antwort:

---
