> Datenstand: 2026-09-17 – Status: aktuell

# Fragen — Template-Entwicklung

Antwort einfach in die `* Antwort:`-Zeile unter der Frage schreiben — ein Buchstabe oder ein Stichwort genügt,
freier Text geht immer. Alles Weitere erledigt der Orchestrator: Er verbucht die Antwort, bestätigt kurz
darunter und verschiebt die Frage später nach `questions_archive.md`.

🔴 heißt: blockiert gerade die Arbeit. Sonst gilt die Reihenfolge nach Nummer, nicht nach Dringlichkeit.

*Format, Teilfragen und Archivierungsregeln: `../../../docs/ai/README.md` § „Fragen" (eigene Fassung folgt
mit T5 Schritt 3).*

Beantwortete und archivierte Fragen `Q1`–`Q18`: `questions_archive.md`.

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

