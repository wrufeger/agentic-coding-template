> Datenstand: 2026-09-17 – Status: entschieden — `Q8`–`Q11` beantwortet, Umsetzung offen (T1–T3)

# Repo- und Issue-Dienste: Zugänge, Pull/Merge Requests, Issues

**Leitfrage:** Wie arbeitet ein Projekt aus dem Template mit seinem Git-Hoster und seinem Issue-Tracker —
Zugänge erkennen (T1), PR/MR vorbereiten und anlegen (T2), Issues anzeigen, anlegen und bearbeiten (T3)?

**Aufwand gesamt:** ~4 PT — T1 ~1 PT, T2 ~1 PT, T3 ~2 PT (lesen 0,5 · anlegen 0,5 · „Arbeit starten" 1).

## Ausgangslage

- **Katalog vorhanden, Einrichtung nicht.** `.claude/mcp-katalog.md` führt `github`, `gitlab`, `linear`,
  `atlassian` (Jira, Confluence, Bitbucket); YouTrack fehlt. `AI-CONFIG.md` § `MCP-Server` hält nur die Auswahl
  fest — eingerichtet wird von Hand (Backlog-Punkt 25 will das automatisieren).
- **Niemand prüft, ob ein Zugang wirklich geht.** Kein Script ruft `claude mcp list`, `gh auth status` o. Ä. auf.
- **Keine Schlüssel** für Zielbranch, Branch-Schema oder Issue-Tracker in `AI-CONFIG.md`.
- **Kein Skill fasst Branches, Push oder Remote an.** `/act-commit` committet nur lokal, `/act-release` taggt nur.
  Andockstellen: `/act-prepare` (Zuschnitt in Aufgaben/Story), Checkliste „Idee oder Änderungswunsch aufnehmen".
- **Schreibzugriffe nach außen** fallen unter `AGENTS.md` § „Zugriff auf laufende Systeme": Lesen frei,
  Schreiben nur mit Freigabe, Vorschau vorher, wiederkehrend über ein geprüftes Script.
- **Rückmeldung passt schon:** `feedback.py --add --art fehler|mcp` gibt es; keine neue Kategorie nötig.
- **Testprojekt `bandliste`:** Hoster ist ein **selbst betriebenes GitLab** (`git.rufeger.de`), Standardbranch
  `development`, weder `gh` noch `glab` installiert. Jeder Entwurf muss dort ohne Zusatzinstallation laufen.

## Wege zum Dienst

| Weg | Stärken | Schwächen |
| :--- | :--- | :--- |
| **MCP-Server** (`github`, `gitlab`, `atlassian` …) | Assistent sieht die Werkzeuge direkt; OAuth ohne Token-Datei | Verfügbarkeit je Instanz unsicher (GitLab-MCP braucht eine neue GitLab-Version, bei selbst betriebenen Instanzen zu prüfen); nicht aus einem Script aufrufbar |
| **CLI** (`gh`, `glab`) | ausgereift, scriptbar, eigene Anmeldung | muss installiert und angemeldet sein — in `bandliste` nicht vorhanden |
| **REST-API per Script** (Stdlib-Python, Token aus Prozessumgebung/`.env`) | läuft überall, auch auf selbst betriebenem GitLab; testbar; erfüllt „wiederkehrend über ein geprüftes Script" | Token nötig; je Dienst ein kleiner Adapter |

## T1 — Zugänge prüfen und festhalten

Skill `/integrations` plus Script `.claude/scripts/integrations.py`:

1. **Erkennen** (Script, nur lesend): Hoster aus `git remote -v`; vorhandene CLIs samt Anmeldestatus; Namen
   (nie Werte) gesetzter Token-Variablen; MCP-Server aus `.mcp.json` und `claude mcp list`.
2. **Probeaufruf** (nur lesend): je Weg ein harmloser Aufruf — eigener Benutzer, Projekt lesen, ein Issue lesen.
3. **MCP-Werkzeuge** kann nur der Assistent in der Sitzung sehen: Der Skill listet die Werkzeugnamen der
   verbundenen Server und ordnet sie den Fähigkeiten zu (PR anlegen, Issue lesen, Kommentar …).
4. **Ablage** (`Q9`): Fähigkeit × Weg × Stand × Datum.
5. **Fehlt etwas:** konkreter Einrichtungshinweis (Katalogbefehl, benötigte Variable, `.env` wird von Claude
   Code nicht gelesen — `CLAUDE.md` § 4). Fehlschläge als `feedback.py --add --art mcp|fehler`, nur das
   Muster (z. B. „GitLab-MCP auf selbst betriebener Instanz nicht erreichbar"), ohne Hostnamen.

T2 und T3 lesen die Ablage und rufen `/integrations` selbst auf, wenn sie fehlt oder älter als 30 Tage ist.

## T2 — Pull/Merge Request

Skill `/pr`:

1. **Zielbranch:** Schlüssel `Zielbranch` in `AI-CONFIG.md` (Gruppe Technik); leer → Standardbranch des
   Remotes (`origin/HEAD`), sonst der erste vorhandene aus `development`, `develop`, `main`. Beim ersten
   Mal nachfragen und den bestätigten Wert eintragen.
2. **Vorbedingungen:** Arbeitsbaum sauber, nicht auf dem Zielbranch, Branch gepusht — Push nur nach Zustimmung.
3. **Entwurf** aus `git log` und `git diff <ziel>...HEAD`: Titel im Commit-Stil des Repos; Beschreibung mit
   Zweck, Änderungen, Beleg (Tests), Bezug (`T<n>`, Issue, Story).
4. **Vorschau und Wahl:** anlegen · als Entwurf anlegen · nur Text ausgeben · abbrechen (`Q10`).
5. **Anlegen** über den Weg aus T1; Link und Datum ins Journal.

## T3 — Issues und Stories

Skill `/issue` mit Sätzen statt Unterbefehlen:

- **Lesen** („zeige Issues", „meine offenen Stories", „zeige Issue 42"): frei, Tabelle ≤ 15 Zeilen.
- **Anlegen** („lege ein Issue an: …"): Entwurf, Vorschau, Zustimmung, Link ins Journal.
- **Arbeit starten** („Starte Arbeit an Issue 42"):
  1. Issue lesen, Art bestimmen (Label/Typ `bug` → `bugfix/`, sonst `feature/`), Branch
     `<art>/<nummer>-<kurztitel>` vom Zielbranch anlegen (lokal, kein Push).
  2. Zusammenfassung und Arbeitsauftrag zeigen.
  3. Ablauf „Block vorbereiten" (`/act-prepare`): Bestand, Zuschnitt in `T<n>` (je mit Zeile `Issue: <Link>`),
     bei Größerem eine Story; offene Punkte in **einem** Fragenblock; Aufgaben für den Entwickler erst,
     wenn sie ausführbar sind (Backlog-Punkt 33).
  4. Backlog und Doku nachziehen; zum Schluss Hinweis auf `/pr`.
- **Rückschreiben** ins Issue (Kommentar, Status) nur nach Zustimmung, jeweils mit Vorschau.

## Empfehlung

- **Weg:** Git-Hoster (GitHub, GitLab) über **REST-Script**, CLI wenn vorhanden, MCP als Zusatz; Tracker ohne
  Git (Jira, YouTrack, Linear) über **MCP** (`Q8`).
- **Freigabe:** Vorschau plus ausdrückliches „ja" im Chat genügt je Aktion; Journal-Eintrag mit Link folgt
  automatisch. Dafür wird § „Zugriff auf laufende Systeme" um diesen Fall ergänzt (`Q10`).
- **Reihenfolge:** T1 → T2 → T3 lesen → T3 anlegen/starten; zuerst GitLab (Beleg `bandliste`) und GitHub,
  danach Jira, YouTrack zuletzt (`Q11`).
- **Neue Skills** in alle zusammenhängenden Pfadlisten (`.templatedev/docs/project/coding_rules.md`) und
  `CLAUDE.md` § 2.

## Entschieden am 2026-09-16

- **Weg (`Q8` a):** GitHub/GitLab per REST-Script (Token aus Prozessumgebung oder `.env`), CLI wenn vorhanden,
  MCP als Zusatz; Tracker ohne Git per MCP.
- **Ablage (`Q9` a):** `docs/project/integrations.md` — Dateinamen immer englisch; daher auch
  `/integrations` und `.claude/scripts/integrations.py`.
- **Freigabe (`Q10` a):** Vorschau plus „ja" im Chat je Aktion, Journal-Eintrag mit Link automatisch;
  `AGENTS.md` § „Zugriff auf laufende Systeme" wird darum ergänzt.
- **Umfang (`Q11`):** GitLab und GitHub; Jira, YouTrack, Linear später (Backlog-Punkt 34).
