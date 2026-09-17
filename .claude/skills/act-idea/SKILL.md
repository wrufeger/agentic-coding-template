---
name: act-idea
description: Eine Idee, ein Feature oder einen Änderungswunsch aufnehmen - analysieren, Optionen mit Empfehlung vorlegen, nach der Entscheidung Aufwand und Werkzeuge abschätzen, in Backlog und Aufgaben verbuchen. Auslöser - "/idea", "ich hätte da eine Idee", "können wir X einbauen", "wäre gut, wenn", "Änderungswunsch".
---

# Idee oder Änderungswunsch aufnehmen

Setzt die Checkliste „Idee oder Änderungswunsch aufnehmen" aus `docs/ai/checklists.md` um. Läuft im
Hauptkontext ({{ORCHESTRATOR}}), weil Entscheidung und Priorität bei {{AUFTRAGGEBER}} liegen.

**Der Skill baut nichts.** Er endet mit einem Backlog-Punkt und — wenn es jetzt drankommt — einer Aufgabe.
Gebaut wird danach, über `/prepare` und den normalen Ablauf.

## Ablauf

1. **Wortlaut festhalten**, unverändert. Er ist die Messlatte; jede spätere Umsetzung wird daran gemessen,
   nicht an der Zusammenfassung des Assistenten.
2. **Bestand prüfen, bevor analysiert wird.** Parallel per `explorer`: Gibt es das teilweise schon? Welche
   Dateien wären betroffen? Und vor allem — **widerspricht der Wunsch einer getroffenen Entscheidung**
   (`docs/project/decisions.md`)? Wenn ja, steht das an erster Stelle, nicht als Fußnote: Dann geht es nicht
   um ein Feature, sondern um die Revision eines ADR, und das ist eine andere Frage.
3. **Konzept schreiben** nach `docs/project/konzepte/<thema>.md`: Ausgangslage mit Fundstellen, **Optionen**
   (je Beschreibung, Vorteile, Nachteile, Aufwand), **Empfehlung**. Die Option „nichts tun" gehört dazu, mit
   ihren Folgen — manchmal ist sie die richtige.
4. **Zur Entscheidung vorlegen** als Frage in `docs/ai/questions.md`, Optionen `a)`/`b)`/`c)`, Empfehlung
   gekennzeichnet. Bis zur Antwort wird nichts gebaut und nichts in `tasks.md` eingetragen.
5. **Nach der Entscheidung abschätzen** — und zwar nur für den gewählten Weg:
   - **Umfang** in der Einheit des Projekts.
   - **Was fehlt an Werkzeug:** eine Bibliothek, ein MCP-Server (`.claude/mcp-katalog.md`), ein Regelsatz
     (`docs/project/coding_rules.d/`, nachladbar per `guidelines.py`), ein Skill, den es noch nicht gibt.
     Das ist ein eigener Arbeitsschritt mit eigenem Aufwand, kein Nebenbei.
   - **Grobe Aufteilung** in Stories und Aufgaben, je mit Ziel und Abnahmebedingung.
   - ADR in `docs/project/decisions.md`: was entschieden, was verworfen, welche Folge.
6. **Priorität und Zeitpunkt.** {{AUFTRAGGEBER}} nennt beides. {{ORCHESTRATOR}} setzt **seine eigene**
   Einschätzung daneben — nicht dieselbe Zahl aus Höflichkeit; sie kommt aus einem anderen Blickwinkel
   (technischer Druck, Abhängigkeiten, Risiko im Bestand). In den Backlog geht der Mittelwert, beide
   Einzelwerte bleiben sichtbar. **Bei mehr als einer Stufe Abstand: eine Zeile, woher der Unterschied
   kommt.** Skala und Schreibweise: `docs/ai/README.md` § Backlog.
7. **Verbuchen:** Backlog-Punkt mit Thema, Prio, Zeitpunkt, Aufwand, Bezug auf Konzept und ADR; Aufgaben in
   `tasks.md` nur für das, was **jetzt** gemacht wird. Ledger-Eintrag mit der Entscheidung.

## Abkürzung für Kleinigkeiten

Ein Tippfehler, ein Feldname, eine Zeile Konfiguration braucht kein Konzept und kein ADR — daraus wird direkt
eine Aufgabe oder ein Backlog-Punkt. **Die Abkürzung wird ausgesprochen** („mache ich direkt als Aufgabe,
kein Konzept"), damit {{AUFTRAGGEBER}} widersprechen kann.

Im Zweifel für die Analyse: Ein überflüssiges Konzept kostet eine halbe Stunde, ein übersehener Widerspruch
zu einer bestehenden Entscheidung kostet den Umbau.

## Grenzen

- **Keine Umsetzung in diesem Skill**, auch nicht „schnell mal angefangen". Wer währenddessen Code schreibt,
  hat die Entscheidung vorweggenommen.
- **Keine Empfehlung ohne echte Alternative.** Eine Option und drei Strohmänner sind keine Auswahl.
- **Die Prioritäten werden nicht angeglichen.** Der Assistent übernimmt nicht {{AUFTRAGGEBER}}s Zahl, damit
  es ordentlich aussieht — der Abstand ist die eigentliche Information.
- **Kein Aufwand ohne Grundlage.** Beruht die Schätzung auf einer Annahme (Datenmenge, Fremdsystem,
  Schnittstelle), wird sie genannt; eine Zahl ohne Annahme ist geraten.
