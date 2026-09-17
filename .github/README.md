# Agentic Coding Template

Ein Vorlagen-Repository für Projekte, an denen ein Mensch gemeinsam mit KI-Assistenten arbeitet — für neue
Anwendungen ebenso wie für gewachsene Codebasen.

Es liefert ausgearbeitete Regeln und Rollen für den Orchestrator, seine Sub-Agenten, Skills und Scripte, dazu
einen Arbeitsordner für die tägliche Zusammenarbeit (Board, Aufgaben, Fragen, Journal) und ein Skelett für die
Projekt-Dokumentation. Die Grundidee: **ein starker Assistent plant**, prüft und committet, **günstigere Modelle
arbeiten** die klar umrissenen Teilaufgaben parallel ab — und „fertig" gilt nur mit Beleg.

Und es bleibt nicht stehen: Projekte, die es einsetzen, können **freiwillig zurückmelden**, was an der
Arbeitsweise geholfen oder gefehlt hat. Was zwei Projekte unabhängig voneinander melden, wird zur Regel für
alle — siehe „Lernt mit" weiter unten.

Schon bei der Einrichtung passt sich das Template an: Ein Formular wird ausgefüllt, dann ersetzt der Assistent
die Platzhalter, entfernt die Dateien nicht genutzter Werkzeuge und befüllt die Dokumentation — bei einem
bestehenden Projekt aus dem echten Code, nicht aus Vermutungen. Spätere Verbesserungen am Template lassen sich
jederzeit nachziehen, ohne die eigenen Anpassungen zu verlieren.

## Voraussetzungen

**Python 3.9+** im `PATH` (`python3 --version`/`python --version`) — Grundlage für Projekt anlegen/nachrüsten,
Template-Update, den laufenden `AI-CONFIG.md`-Abgleich, Feedback und Logging. Ohne Python bleiben die
Regeldateien, die Sub-Agenten und reine Anleitungs-Skills nutzbar; ein Hook meldet die fehlende Voraussetzung
bei Sitzungsstart, bricht aber nichts ab. Installation: Windows `winget install Python.Python.3.12`
(Microsoft-Store-Platzhalter „python3" per App-Ausführungsaliase deaktivieren), macOS `brew install python`,
Linux über den Paketmanager. Details: [README im Repository-Root](../README.md#voraussetzungen).

## Loslegen

Repository klonen, Claude Code darin starten und einen Satz schreiben:

```text
Erstelle eine neue Anwendung in ~/projekte/mein-neues-projekt
Erstelle ein leeres Projekt in ~/projekte/empty-project
Nutze das Template in der bestehenden Anwendung ~/projekte/mein-langjaehriges-projekt
   und mache ein Code Review
```

(Windows-Pfade wie `C:\projekte\mein-neues-projekt` funktionieren genauso — der Assistent nimmt den Pfad,
wie er genannt wird.)

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
| `/act-create-project` | Neues Projekt aufsetzen: Platzhalter, Werkzeuge, Dokumentation |
| `/act-apply-template` | Bestehendes Repository nachrüsten und angleichen |
| `/act-update-template` | Neuerungen aus dem Template nachziehen |
| `/act-audit-docs` | Dokumentation gegen den echten Stand prüfen und nachziehen |
| `/act-commit` | Aufgabe abnehmen: archivieren, Index, Bilanz, Commit |
| `/act-run-maintenance` | Wiederkehrende Wartung (optional) |

Ohne Claude Code funktioniert alles genauso — dann statt des Befehls den entsprechenden Satz sagen, etwa
„Führe die Checkliste Neues Projekt aus".

## Bleibt aktuell

Jedes abgeleitete Projekt behält die Verbindung zum Template. Ein Update wird gemeldet, sobald es eines gibt,
und über die Checkliste „Template-Update" eingespielt: neue Agenten, Skills und Regeln kommen an, die eigenen
Werte und die Projekt-Dokumentation bleiben unangetastet.

## Lernt mit — aus echten Projekten, nicht aus Vermutungen

Die meisten Vorlagen altern ab dem Tag, an dem sie veröffentlicht werden: Was sich in der Praxis als
umständlich erweist, erfährt der Autor nie. Dieses Template hat dafür einen Rückkanal — **freiwillig,
standardmäßig aus** und mit einer Zusage, die im Code durchgesetzt wird.

Wer ihn einschaltet, meldet zurück, was an der **Arbeitsweise** geholfen oder gefehlt hat: eine Regel, die
nachgetragen werden musste, ein Ablauf, der regelmäßig scheiterte, ein Script, das allgemein taugt. Der
Assistent liest dafür die Regel- und Arbeitsdateien und schreibt daraus eine Zusammenfassung — **nie werden
Dateien gesendet**, kein Projektname, keine Pfade, kein Code, keine Zahlen aus dem Projekt. Maßstab für jeden
Eintrag ist eine einzige Frage: *Hilft das jemandem, der dieses Projekt nie sehen wird?*

**Mitarbeiten, ohne eine Zeile zu schreiben.** Das Template ist kostenlos und für jeden da — und wer etwas
zurückgeben will, muss dafür keinen Pull Request öffnen, kein Issue formulieren und nicht einmal einen Satz
tippen. Die Ideen und Kniffe, die ohnehin beim Entwickeln entstehen, sammelt der Assistent nebenbei ein und
schickt sie auf Wunsch weg. Aus zehn Projekten, die still ihre Erkenntnisse teilen, wird eine Vorlage, die
besser ist als alles, was ein Einzelner sich ausdenken könnte — und jedes dieser Projekte bekommt das Ergebnis
per `/act-update-template` zurück.

Was daraus entsteht, ist der eigentliche Punkt: **Meldet dasselbe Anliegen aus zwei unabhängigen Projekten,
wandert es in der Priorität nach oben** — auch wenn beide es völlig anders formuliert haben. Aus einem Fehler,
über den jemand gestolpert ist, wird eine Regel, die alle anderen nicht mehr stolpern lässt. Die Vorlage wird
dadurch besser, während sie benutzt wird.

Und weil ein Rückkanal nur so viel wert ist wie sein Vertrauen:

- **Aus bleibt aus.** Ohne ausdrückliche Zustimmung verlässt nichts das Projekt. Gefragt wird genau einmal,
  beim Abschluss der Einrichtung; ohne Antwort passiert nichts.
- **Alles ist nachlesbar.** Jede Sendung liegt vollständig im Repo (`docs/ai/template-feedback/`) und fällt
  im nächsten Diff auf. Wer sie lieber nicht versioniert, hält sie mit einer Frage mehr lokal.
- **Ein Satz geht immer.** `/act-feedback <Text>` schickt genau diesen Text — auch bei ausgeschalteter
  Rückmeldung, und dann **anonym**: ohne Projekt-Kennung, ohne Kontext, ohne Zuordnung beim Empfänger.
- **Eine letzte Schranke.** Vor jedem Versand prüft ein Filter jede Zeichenkette auf Zugangsdaten, Pfade,
  Mailadressen und interne Adressen — im Zweifel wird nicht gesendet, sondern nachgefragt.
- **Widerruf jederzeit**, mit einem Wort in `AI-CONFIG.md`.

## Was drin ist

- **Anbieterneutrale Regeln** in `AGENTS.md`: Rollen, Zusammenarbeit, Umgang mit Sicherheitswarnungen, Zugriff
  auf laufende Systeme, Modell- und Kostenlogik.
- **Sub-Agenten** für Umsetzung, Recherche, adversarialen Review, Dokumentation, Kurzchecks und eine
  Eskalationsrolle, die erst einspringt, wenn ein Agent zweimal an derselben Aufgabe gescheitert ist.
- **Skills** als ausführbare Checklisten: Projekt anlegen, nachrüsten, Dokumentation prüfen und nachziehen,
  Aufgabe abschließen, Template-Update.
- **Arbeitsordner** `docs/ai/`: Board, Aufgaben mit Nummern und Ständen, Fragen mit vorgegebenen
  Antwortmöglichkeiten, Journal mit Belegen, Backlog.
- **Optionale Bausteine**: wiederkehrende Wartung mit Fälligkeitsprüfung und ein Mitschnitt aller
  Agentenaktionen, der sich im Terminal live mitlesen lässt.

## Werkzeuge

Optimiert für Claude Code mit seinen Sub-Agenten, Skills und Hooks — die Regeln selbst sind aber
werkzeugunabhängig. Für GitHub Copilot, Cursor, Aider, Gemini CLI und Codex liegen Verweisdateien bei; mit
jedem anderen Assistenten genügt es, die Regeldatei und das Board als Kontext zu laden. Nicht genutzte
Werkzeuge werden beim Anlegen des Projekts entfernt.

Parallele Worker beherrschen inzwischen auch andere Werkzeuge — `/fleet` in der Copilot CLI, Subagents in
Gemini CLI und Codex, `/multitask` in Cursor, Subagents in Cline. Die Regeldatei nennt je Werkzeug
Aufruf und Ablageort der Rollen, damit sich dasselbe Rollenmodell dort nachbauen lässt. Aider bleibt die
Ausnahme: dort gibt es keine Sub-Agenten, nur die Architect/Editor-Trennung.

Wer neu im Thema ist, findet in `docs/ai/resources.md` eine geprüfte Linksammlung: Einstieg, Werkzeug-Doku,
Anbieter, Nachrichtenquellen und die bekannten Grenzen. Sie wandert in jedes abgeleitete Projekt mit und wird
per `/act-update-template` aktuell gehalten.

## Sprache

Dokumentation, Oberflächentexte und Kommentare auf Deutsch, Code-Bezeichner auf Englisch. Das ist im Template
fest hinterlegt, kein Schalter in `AI-CONFIG.md`.

## Mitarbeiten

Das Repository enthält bewusst fast keinen echten Inhalt: `docs/ai/` und `docs/project/` sind Gerüste, die
jedes abgeleitete Projekt selbst füllt. Was die Weiterentwicklung des Templates betrifft — Aufgaben, offene Punkte,
Fragen, Journal, Regeln und die Testprojekte — steht deshalb im Ordner `.templatedev/` im Repo-Root und
wird beim Anlegen eines Projekts entfernt. Wer hier tatsächlich entwickelt statt nur zu klonen, legt
zusätzlich die lokale, gitignorierte Marker-Datei `.templatedev/.maintainer` an — sonst bekommt jede
Eingabe, die nicht erkennbar ein Projekt anlegen oder nachrüsten will, zuerst einen kurzen Hinweis auf die
beiden Wege.

## Lizenz

[MIT](../LICENSE) — nutzen, ändern, weitergeben und kommerziell einsetzen ist ausdrücklich erlaubt. Einzige
Bedingung: Der Copyright-Hinweis auf **Wolfgang Rufeger &lt;wolfgang@rufeger.de&gt;** und der Lizenztext bleiben
erhalten, wenn Teile dieses Templates weitergegeben werden. Für den eigenen Projektcode gilt die Lizenz des
jeweiligen Projekts.

---

Die ausführliche Anleitung mit Schnellstart, Ordnerübersicht und FAQ steht in der
[README im Repository-Root](../README.md).
