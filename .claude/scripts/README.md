# Scripte für wiederkehrende, token-intensive Vorgänge

Regel (`CLAUDE.md` § 3): Was komplex, langwierig und wiederkehrend ist, wird einmal als Script gebaut und
danach nur noch ausgeführt — der Sub-Agent wertet nur die Ausgabe aus. Stdlib bevorzugt, Secrets nur aus
`.env`/der lokalen Umgebung (nie hart codiert, nie in der Ausgabe), Kopfkommentar mit Zweck/Aufruf/
Ausgabeformat.

| Script | Zweck | Aufruf | Stand |
| :--- | :--- | :--- | :--- |
| *(noch keins)* | *(noch keins — Vorlage)* | *(offen)* | {{DATUM}} |

**Kandidaten (beim nächsten Wartungslauf prüfen):** Dateiübersicht `docs/project/` (Pfad · Zeilen · Datenstand)
für `docs/README.md`, Zählung offener Aufgaben/Fragen, Abhängigkeits-Report-Zusammenfassung.
