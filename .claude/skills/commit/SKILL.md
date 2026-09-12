---
name: commit
description: Abgeschlossene Aufgabe abnehmen - archivieren, Doku-Index, Bilanz, Commit per Pathspec, danach Kontext komprimieren.
---

# Aufgabe abschließen und committen (nur Hauptkontext)

Läuft **nach jeder abgeschlossenen Aufgabe**, nicht erst am Sitzungsende — und wird vom Orchestrator selbst
angestoßen, sobald eine Aufgabe abgenommen ist. Setzt die werkzeugneutrale Checkliste „Aufgabe abschließen"
aus `docs/ai/checklists.md` um; hier steht nur die Claude-Code-Mechanik.

Journal, Aufgabenstand und offene Fragen sind zu diesem Zeitpunkt **schon nachgezogen** — das passiert
laufend während der Arbeit (`AGENTS.md` § Grundregeln), nicht hier. Dieser Skill räumt auf, was sich
angesammelt hat, und sichert das Ergebnis.

## Ablauf

1. **Beleg prüfen.** Testlauf, Aufruf von außen oder Commit-Hash — ohne Beleg wird nicht abgenommen. Die
   Pflichtläufe aus `docs/project/testing.md` müssen grün sein.
2. **Archivieren.** Als ✅ markierte Aufgaben mit Volltext nach `docs/ai/tasks_archive.md`, beantwortete und
   verbuchte Fragen nach `docs/ai/questions_archive.md`. Nummern (`A<n>`/`F<n>`) bleiben gültig.
3. **Journal ergänzen oder verdichten.** Fehlt noch ein Eintrag zur gerade abgeschlossenen Aufgabe, jetzt
   nachtragen. Ältere Einträge nach den Regeln im Kopf von `docs/ai/ledger.md` zusammenfassen —
   Commit-Hashes, Nummern, Versionen und Pfade bleiben dabei immer erhalten.
4. **Doku-Index.** Neue Dateien in `docs/README.md` eintragen, Datenstände der geänderten Dateien prüfen.
5. **Board.** `docs/ai/board.md` auf den neuen Stand bringen: Kurzbilanz, nächster Schritt, offene Freigaben.
6. **Commit-Verhalten prüfen.** `AI-CONFIG.md` § „Betrieb" → `Commit-Verhalten` entscheidet, wie es weitergeht:
   `automatisch` committet direkt (Schritt 7), `fragen` (Default) schlägt den Commit vor und wartet auf
   Zustimmung, `manuell` committet nur auf ausdrückliche Anweisung von {{AUFTRAGGEBER}} — sonst bleibt die
   Arbeit abgenommen, aber uncommittet.
7. **Commit per Pathspec.** `git add <pfad …>` — nie ein catch-all. Committet wird **abgenommene Arbeit**,
   nicht ein Zeitabschnitt; mehrere Commits pro Sitzung sind der Normalfall. Kurze Message im Repo-Stil,
   Attribution wie in der laufenden Sitzung vorgegeben. Fremde uncommittete Änderungen anderer Sitzungen nicht
   stillschweigend mitnehmen — sichten, dann entscheiden.
8. **Bilanz an {{AUFTRAGGEBER}}.** Ergebnis zuerst, Belege (Hash, Testzahlen), offene Punkte und Fragen mit
   Nummern.
9. **Logging** (falls eingeschaltet, `AGENTS.md` § Logging): `python .claude/scripts/ai-log.py INFO
   orchestrator commit "<hash> <message>"`.
10. **Kontext freigeben.** Der Detailkontext der erledigten Aufgabe wird nicht mehr gebraucht — der Stand
   liegt vollständig in Git und in `docs/ai/`. Jetzt ist der günstigste Zeitpunkt zum Komprimieren.
   `/compact` kann ein Assistent **nicht selbst auslösen** (Slash-Befehle sind dem Menschen vorbehalten) —
   also {{AUFTRAGGEBER}} in der Bilanz darauf hinweisen, am besten mit einem Satz zur nächsten Aufgabe, damit
   die Zusammenfassung sie mitnimmt. Wer das nicht von Hand tun will, überlässt es der automatischen
   Komprimierung (`autoCompactEnabled` in `.claude/settings.json`, Schwelle `autoCompactWindow`).
   Wirksamer als jedes Komprimieren ist aber, den Hauptkontext gar nicht erst vollzuschreiben: lange
   Arbeitsschritte laufen in Sub-Agenten oder in Skills mit `context: fork` (`CLAUDE.md` § 3).

## Regeln

- Läuft **immer** im Hauptkontext, nie in einem Sub-Agenten — nur der Orchestrator schreibt in `docs/ai/` und
  committet (`AGENTS.md`).
- Entwürfe dürfen ausgelagert werden: Einen Worker mit dem Auftrag „nur Entwurf, nichts committen" eine
  Journal-Zusammenfassung ins Scratchpad schreiben lassen; der Hauptkontext prüft sie gegen die echten Belege
  und übernimmt sie gekürzt. Das lohnt sich erst bei langen Sitzungen mit vielen Einzelbelegen.
- Ist eine Aufgabe **nicht** abgenommen (Tests rot, Beleg fehlt, offene Rückfrage), wird nicht committet —
  stattdessen `Stand <Datum>:` in `docs/ai/tasks.md` aktualisieren und offen lassen.
