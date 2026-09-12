# Agentic Coding Template

Ein Vorlagen-Repository für Projekte, an denen ein Mensch gemeinsam mit KI-Assistenten arbeitet — für neue
Anwendungen ebenso wie für gewachsene Codebasen.

Es liefert ausgearbeitete Regeln und Rollen für den Orchestrator, seine Sub-Agenten, Skills und Scripte, dazu
einen Arbeitsordner für die tägliche Zusammenarbeit (Board, Aufgaben, Fragen, Journal) und ein Skelett für die
Projekt-Dokumentation. Die Grundidee: **ein starker Assistent plant**, prüft und committet, **günstigere Modelle
arbeiten** die klar umrissenen Teilaufgaben parallel ab — und „fertig" gilt nur mit Beleg.

Schon bei der Einrichtung passt sich das Template an: Ein Formular wird ausgefüllt, dann ersetzt der Assistent
die Platzhalter, entfernt die Dateien nicht genutzter Werkzeuge und befüllt die Dokumentation — bei einem
bestehenden Projekt aus dem echten Code, nicht aus Vermutungen. Spätere Verbesserungen am Template lassen sich
jederzeit nachziehen, ohne die eigenen Anpassungen zu verlieren.

## Zwei Wege hinein

**Neues Projekt.** Repository klonen, `CONFIG.md` ausfüllen (Projektname, Stack, Ziel, erste Features — alles
optional) und den Assistenten die Checkliste „Neues Projekt" ausführen lassen. Wer das Formular leer lässt,
bekommt ein sauberes, leeres Projekt.

**Bestehendes Projekt nachrüsten.** Ein Script kopiert die Grundausstattung in das vorhandene Repository, ohne
etwas zu überschreiben. Danach analysiert der Assistent den Bestand, dokumentiert den Ist-Zustand und schlägt
auf Wunsch vor, wie die Struktur an das Template angeglichen wird: bereits vorhandene KI-Arbeitsordner werden
übernommen, der bisherige Rufname des Assistenten projektweit ersetzt, eigene Regeln mit denen des Templates
zusammengeführt. Dabei gewinnt das Template bei allem, was Agenten und Zusammenarbeit betrifft, das Projekt
behält seine eigene Dokumentation, und bei den Coding-Regeln setzt sich die strengere Vorgabe durch. Optional
prüft der Assistent anschließend den Code und sammelt Verbesserungsvorschläge — ohne eine Zeile zu ändern.

## Bleibt aktuell

Jedes abgeleitete Projekt behält die Verbindung zum Template. Ein Update wird gemeldet, sobald es eines gibt,
und über die Checkliste „Template-Update" eingespielt: neue Agenten, Skills und Regeln kommen an, die eigenen
Werte und die Projekt-Dokumentation bleiben unangetastet.

## Was drin ist

- **Anbieterneutrale Regeln** in `AGENTS.md`: Rollen, Zusammenarbeit, Umgang mit Sicherheitswarnungen, Zugriff
  auf laufende Systeme, Modell- und Kostenlogik.
- **Sub-Agenten** für Umsetzung, Recherche, adversarialen Review, Dokumentation, Kurzchecks und eine
  Eskalationsrolle, die erst einspringt, wenn ein Agent zweimal an derselben Aufgabe gescheitert ist.
- **Skills** als ausführbare Checklisten: Projekt anlegen, nachrüsten, delegieren, Dokumentation nachziehen,
  Doku-Audit, Sitzungsabschluss, Template-Update.
- **Arbeitsordner** `docs/ai/`: Board, Aufgaben mit Nummern und Ständen, Fragen mit vorgegebenen
  Antwortmöglichkeiten, Journal mit Belegen, Umbauliste.
- **Optionale Bausteine**: wiederkehrende Wartung mit Fälligkeitsprüfung und ein Mitschnitt aller
  Agentenaktionen, der sich im Terminal live mitlesen lässt.

## Werkzeuge

Optimiert für Claude Code mit seinen Sub-Agenten, Skills und Hooks — die Regeln selbst sind aber
werkzeugunabhängig. Für GitHub Copilot, Cursor, Aider, Gemini CLI und Codex liegen Verweisdateien bei; mit
jedem anderen Assistenten genügt es, die Regeldatei und das Board als Kontext zu laden. Nicht genutzte
Werkzeuge werden beim Anlegen des Projekts entfernt.

## Sprache

Dokumentation, Oberflächentexte und Kommentare auf Deutsch, Code-Bezeichner auf Englisch. Beides ist im
Template als Regel hinterlegt und lässt sich projektweit ändern.

## Lizenz

[MIT](../LICENSE) — nutzen, ändern, weitergeben und kommerziell einsetzen ist ausdrücklich erlaubt. Einzige
Bedingung: Der Copyright-Hinweis auf **Wolfgang Rufeger &lt;wolfgang@rufeger.de&gt;** und der Lizenztext bleiben
erhalten, wenn Teile dieses Templates weitergegeben werden. Für den eigenen Projektcode gilt die Lizenz des
jeweiligen Projekts.

---

Die ausführliche Anleitung mit Schnellstart, Ordnerübersicht und FAQ steht in der
[README im Repository-Root](../README.md).
