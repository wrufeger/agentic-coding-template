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

## Loslegen

Repository klonen, Claude Code darin starten und einen Satz schreiben:

```text
Erstelle eine neue Anwendung in C:\development\mein-neues-projekt
Erstelle ein leeres Projekt in C:\empty-project
Nutze das Template in der bestehenden Anwendung C:\development\mein-langjaehriges-projekt
   und mache ein Code Review
```

Der Assistent erkennt daraus, welcher Weg gemeint ist, legt das Zielverzeichnis an, richtet Git ein und führt
die passende Checkliste aus.

**Neues Projekt.** Kurzes Interview zu Ziel, Stack und ersten Features, dann werden Platzhalter ersetzt, die
Dateien nicht genutzter Werkzeuge entfernt und die Dokumentation befüllt. „Leeres Projekt" überspringt die
Fragen und legt nur das Gerüst an.

**Bestehendes Projekt nachrüsten.** Die Grundausstattung wird kopiert, ohne etwas zu überschreiben. Danach
analysiert der Assistent den Bestand, dokumentiert den Ist-Zustand und schlägt vor, wie die Struktur an das
Template angeglichen wird: bereits vorhandene KI-Arbeitsordner werden übernommen, der bisherige Rufname des
Assistenten projektweit ersetzt, eigene Regeln mit denen des Templates zusammengeführt. Dabei gewinnt das
Template bei allem, was Agenten und Zusammenarbeit betrifft, das Projekt behält seine eigene Dokumentation,
und bei den Coding-Regeln setzt sich die strengere Vorgabe durch. Auf Wunsch prüft der Assistent anschließend
den Code und sammelt Verbesserungsvorschläge — ohne eine Zeile zu ändern.

## Befehle

| Befehl | Wofür |
| :--- | :--- |
| `/new-project` | Neues Projekt aufsetzen: Platzhalter, Werkzeuge, Dokumentation |
| `/consume-template` | Bestehendes Repository nachrüsten und angleichen |
| `/template-update` | Neuerungen aus dem Template nachziehen |
| `/project-docs` · `/docs-audit` | Dokumentation nachziehen bzw. gegen den Code prüfen |
| `/commit` | Aufgabe abnehmen: archivieren, Index, Bilanz, Commit |
| `/maintenance` | Wiederkehrende Wartung (optional) |

Ohne Claude Code funktioniert alles genauso — dann statt des Befehls den entsprechenden Satz sagen, etwa
„Führe die Checkliste Neues Projekt aus".

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
  Doku-Audit, Aufgabe abschließen, Template-Update.
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

## Mitarbeiten

Das Repository enthält bewusst fast keinen echten Inhalt: `docs/ai/` und `docs/project/` sind Gerüste, die
jedes abgeleitete Projekt selbst füllt. Was die Weiterentwicklung des Templates betrifft — offene Punkte,
Fragen, Journal — steht deshalb in `.templatedev.md` im Repo-Root und wird beim Anlegen eines Projekts
entfernt.

## Lizenz

[MIT](../LICENSE) — nutzen, ändern, weitergeben und kommerziell einsetzen ist ausdrücklich erlaubt. Einzige
Bedingung: Der Copyright-Hinweis auf **Wolfgang Rufeger &lt;wolfgang@rufeger.de&gt;** und der Lizenztext bleiben
erhalten, wenn Teile dieses Templates weitergegeben werden. Für den eigenen Projektcode gilt die Lizenz des
jeweiligen Projekts.

---

Die ausführliche Anleitung mit Schnellstart, Ordnerübersicht und FAQ steht in der
[README im Repository-Root](../README.md).
