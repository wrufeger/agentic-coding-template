> Datenstand: 2026-09-14 – Status: aktuell

# Ledger — Template-Entwicklung

Sitzungs-Journal und Kurzchronik. Neueste Sitzung oben. Nur der Orchestrator schreibt hier.

**Verdichtungsregeln:**
- Heutiger Tag und der Vortag: detailliert, alle Läufe eines Tages unter einer Tagesüberschrift.
- Älter als 2 Tage bis 1 Woche: ein Eintrag je Tag, max. 8 Stichpunkte.
- Älter als 1 Woche: ein Eintrag je Monat (Abschnitt „Archiv" ganz unten).
- Commit-Hashes, Nummern, Versionen, Dateipfade und Kennzahlen werden nie weggekürzt.

---

## 2026-09-14 — Ablage der Template-Entwicklung: zurück nach `.templatedev/`, versioniert

**Das ist der Endstand nach drei Anläufen an einem Tag.** Wer die Ablage erneut ändern will, liest zuerst
diesen Eintrag und den darunter.

- **Anlauf 1 — `.templatedev/` gitignored.** Idee: Arbeitsstand ist nur lokal relevant. Fehler: Ohne
  Versionierung gibt es keine Historie und keine Sicherung, und das eigentliche Ziel („nicht in abgeleitete
  Projekte") war durch `template_only` längst gelöst. Ich hatte widersprochen, Wolfgang hat es bestätigt,
  also umgesetzt — der Nachteil zeigte sich sofort beim nächsten Schritt.
- **Anlauf 2 — eigenes Projekt `template-agentic-coding-project-development`.** Idee: Entwicklungsdaten
  wieder versioniert, ohne das Template zu belasten; nebenbei das fehlende Weg-1-Testprojekt. Technisch
  sauber und in einer knappen Stunde gebaut. Fehler: **Struktur und Notizen lagen in verschiedenen Fenstern.**
  Beim Arbeiten am Template will man den Verzeichnisbaum sehen, Zeilen von Hand anpassen — und zugleich
  Umbauliste und Journal lesen, die die KI ins andere Repo schreibt. Wolfgangs Einwand, und er wiegt schwerer
  als der Vorteil der Trennung.
- **Endstand:** `.templatedev/` im Template, **versioniert**. Erfüllt alle drei Ziele zugleich, die vorher
  gegeneinander standen: nicht in abgeleitete Projekte (`template_only`, am echten Fall belegt), Historie und
  Sicherung (Git), alles in einem Baum sichtbar.
- **Die Lehre, allgemeiner:** Die ersten beiden Anläufe optimierten je ein Ziel und übersahen ein drittes,
  das nur beim Benutzen auffällt. „Wo liegt es?" ist keine reine Ablagefrage, sondern eine Frage danach, was
  man beim Arbeiten gleichzeitig sehen muss. Das lässt sich am Reißbrett schlecht entscheiden — es zeigt sich
  nach zehn Minuten Arbeit.
- Zurückgeholt: Umbauliste, Journal, Regeln, Testprojekt-Tabelle und `testprojekte.py` (Pfadauflösung wieder
  auf `.templatedev/README.md`, Repo-Wurzel eine Ebene höher). Neu: `INDEX.md` als Einstieg. `AGENTS.md`,
  `CLAUDE.md`, beide READMEs, Projektbäume und der SessionStart-Hook sind entsprechend zurückgedreht;
  `init.py` und die Vorlagen entfallen — bei versionierten Dateien gibt es nichts wiederherzustellen.
- **Vor dem Auflösen von Anlauf 2 gerettet:** der Kreislauf eines Befunds (jetzt in `regeln.md`, angepasst
  auf zwei Repos statt drei) und die dort angelegte offene Aufgabe „Erkenntnisse aus `bandliste` prüfen"
  (jetzt Umbaupunkt 22). Der Rest des Repos war Doppelung des hier Vorhandenen.
- Weg 1 hat damit weiterhin kein dauerhaftes Testprojekt. Das ist vertretbar: Der Weg wurde beim Anlegen von
  Anlauf 2 real durchgespielt und hat dabei bestätigt, dass `create-project.py` den Ordner `.templatedev/`
  korrekt entfernt. Ein leeres Projekt nur als Beleg vorzuhalten, kostet mehr Pflege als es einbringt —
  für den nächsten Test genügt ein Wegwerf-Klon.

## 2026-09-14 — Template-Entwicklung wird ein eigenes Projekt (Anlauf 2, überholt)

- **Anlass:** Die Arbeitsdateien der Template-Entwicklung (Umbauliste, Fragen, Journal) lagen im Template
  unter `.templatedev/` und waren dort seit dem Vortag **gitignored** — also ohne Historie und ohne
  Sicherung. Wolfgangs Lösung: ein eigenes Projekt, erzeugt mit dem Template selbst.
- **Angelegt** als Weg 1: von `git@github.com:wrufeger/agentic-coding-template.git` (Stand `d4a304b`)
  geklont, Remote in `template` umbenannt, `AI-CONFIG.md` befüllt, `create-project.py --apply`. Kein eigenes
  `origin` — vorerst nur lokal.
- **Nebenbefund, der zählt:** `create-project.py` hat `.templatedev` beim Anlegen korrekt entfernt. Damit ist
  der `template_only`-Mechanismus vom Vortag nicht nur im Wegwerf-Repo, sondern am echten Fall belegt.
  Vorher gesichert wurden die drei gitignorierten Arbeitsdateien — ein `git clone` bringt sie nicht mit.
- **Übernommen:** Umbauliste → `docs/ai/backlog.md` (Punkte 1–21 mit ihren Nummern), Journal →
  `docs/ai/ledger.md`, Regeln → `docs/project/template-pflege.md`, Testprojekte →
  `docs/project/testprojekte.md`, `testprojekte.py` → `.claude/scripts/`.
- **Damit hat das Template sein Weg-1-Testprojekt**, das bisher fehlte: Dieses Repo ist selbst aus dem
  Template entstanden und zieht Änderungen per `/update-template` nach.
- **Wartung eingeschaltet** (`testprojekte=7, docs=30, kurz=14`) — der Abgleich der Test-Installationen ist
  der wiederkehrende Zweck dieses Projekts, keine Nebensache.
- Offen: **A2** — im Template den Verweis setzen und die gitignore-Sonderregel zurücknehmen. Bis dahin gibt
  es die Template-Entwicklung an zwei Orten.

## 2026-09-13 — erster echter Einsatz am Fremdprojekt, danach sieben Punkte
- **Das Template wurde zum ersten Mal auf ein bestehendes Projekt angewendet** (`bandliste`, Nuxt 4 +
  Prisma, 107 Dateien, dazu 49.000 Dateien Alt-PHP in `old-project/`). Der Durchlauf hat mehr über das
  Template verraten als jede Prüfung am eigenen Repo: Zwei Fehler fielen erst dort auf (Punkte 17 und 18),
  und zwei Anforderungen entstanden aus dem, was danach im Projekt liegen blieb (19 und 20).
- **Punkt 18 war der teuerste Fund.** `.junie/guidelines.md` enthielt 110 Zeilen projekteigener Stil- und
  Sicherheitsregeln — genau das Material, für das `docs/project/coding_rules.md` da ist. `migrate-project.py
  --plan` meldete „keine Kandidaten". Aufgefallen ist es nur, weil ein `explorer` die Datei nebenbei erwähnte.
  Ohne diesen Zufall hätten zwei Regelwerke nebeneinander gegolten. Lehre: Die Kandidatenliste muss die
  Ablagen **anderer** Werkzeuge kennen, nicht nur die eigenen — nachgezogen für Junie, Cline, Windsurf, Roo,
  Copilot-Instructions und `AGENT.md`.
- **Punkt 19, die eigentliche Neuerung:** Nach der Einrichtung blieb das gesamte Einrichtungswerkzeug im
  Projekt liegen. Beim Aufräumen zeigte sich, dass `create-project.py` und `migrate-project.py` längst
  zweierlei sind — Einrichtungs-CLI **und** Bibliothek: `sync-config.py` lädt 32 bzw. 2 Funktionen daraus,
  und `AI-CONFIG.md` wirkt laufend. Schlichtes Löschen hätte die Konfigurationssteuerung stillgelegt.
  Deshalb getrennt: `setup-lib.py`/`rename-lib.py` bleiben als Bibliothek, die CLIs darüber verschwinden.
- **Der Abschluss ist bewusst kein Automatismus.** Erste Fassung sollte am Ende von `/create-project`
  aufräumen. Wolfgang hat das korrigiert: Die Einrichtung ist dort meist noch gar nicht fertig — `docs/project/`
  will nachgeschärft, vielleicht wird ein zweites Mal nachgerüstet. Jetzt fragt der Skill am Ende nur, ob es
  so weit ist; wenn nicht, erinnert ein SessionStart-Hook bei jedem Start, bis `/finalize` läuft. Danach sind
  `create-project` und `apply-template` im Projekt nicht mehr aufrufbar — auch nicht über die Bibliothek
  (`setup_complete`-Guard in `setup-lib.py`).
- **Beleg:** End-to-End-Smoketest über beide Wege in Wegwerf-Repos — Weg 2 vom Nachrüsten bis zum
  aufgeräumten Projekt, Weg 1 als Klon, dazu der Verweigerungstest im Template selbst. Alle drei bestanden.
  Der Test fand einen Fehler, den kein Einzeltest gefunden hätte: `no_replace` in `.claude/template.json`
  führte noch die alten Dateinamen, ein späterer Merge hätte Platzhalter in `setup-lib.py` ersetzt.
- **Nachtrag am selben Abend (`e59a697`):** Eine parallel laufende Sitzung richtete in `bandliste` einen
  MCP-Server ein und fand dabei, dass `CLAUDE.md` § MCP und `.mcp.json.example` beide falsch lagen: Claude Code
  löst `${VAR}` in `.mcp.json` nur aus der **Prozessumgebung** auf und liest **keine `.env`** — belegt durch
  `claude mcp list`, das die Variablen trotz gefüllter `.env` als fehlend meldete. Korrigiert, mit drei Wegen
  in fester Reihenfolge; bevorzugt liest der Server die `.env` selbst, damit sie die einzige Quelle für
  Zugangsdaten bleibt und `settings.local.json.example` sich nicht selbst widerspricht.
- **Zur Arbeitsweise:** sechs Sub-Agenten, davon vier parallel auf disjunkten Dateien. Das ging nur, weil die
  Aufträge nach Dateien geschnitten waren, nicht nach Themen — jeder Auftrag nannte ausdrücklich, welche
  Dateien fremd sind. Ein Agent bekam seine Ergänzung erst **nach** dem Lauf statt mitten hinein; genau daran
  war die Sitzung davor entgleist.

## 2026-09-13 — AI-CONFIG.md wirkt laufend, Tabellenformat, Delegationsregeln
- `AI-CONFIG.md` ist jetzt Steuerung statt Protokoll: **beide** Teile wirken laufend, gelesen vor jeder
  Aufgabe. Neues Script `sync-config.py` gleicht die Datei gegen `applied_config` in `.claude/template.json`
  ab. Ergänzungen laufen automatisch (Werkzeugdateien werden per `git show` aus dem Template nachgeladen,
  Platzhalter dabei ersetzt), Löschendes und projektweites Ersetzen braucht `--yes`.
- Format: fünf Tabellen nach Thema statt der Abschnitte „Betrieb"/„Einrichtung", Spalten Schlüssel, Wert,
  Optionen, Platzhalter, Bedeutung. Der Parser liest weiterhin auch `Schlüssel: Wert`, sonst brächen
  Projekte, die vorher angelegt wurden. Die Platzhalter-Spalte nennt die Marke **ohne** Klammern — mit
  Klammern hätte das Anlegen sie in der Konfiguration selbst ersetzt.
- Geänderte Standards: Wartungsberichte `docs` (Verlauf sonst beim nächsten Checkout weg), Commit-Verhalten
  `automatisch` (war gelebte Praxis), Auftraggeber „Entwickler", `streng` heißt `intensiv`.
- **Lehre aus einem entgleisten Lauf:** Ein Builder lief 36 Minuten und verbrauchte 335.000 Token, weil ich
  den Auftrag zu groß geschnitten und dreimal während des Laufs nachgebessert hatte — darunter ein
  Formatwechsel. Abgebrochen; der Teilstand trug, es fehlten nur Tests. Die als eigener, enger Auftrag
  nachgeholt: sechs Fälle, sieben Minuten, ein echter Fehler gefunden (ein Teilstand wurde als vollständig
  umgesetzt verbucht, wodurch eine ausstehende Löschung spurlos verschwunden wäre).
  Daraus entstanden: Richtwerte und Eingriffswege in der Checkliste „Delegation", Mechanik in `CLAUDE.md`,
  Kostenargument in `AGENTS.md`, Meldepflicht in der Builder-Rolle.

## 2026-09-13 — Quellensammlung, Werkzeug-Alternativen, globale Ablage
- `docs/ai/resources.md` neu: 40 geprüfte Links (Einstieg, Werkzeuge, Anbieter, Standards, Nachrichten,
  Grenzen). Das Template pflegt die Datei, nur der Abschnitt „Eigene Quellen dieses Projekts“ gehört dem
  Projekt — eigene Regel in `priority_label()` beider Scripte, damit der Merge das weiß.
- `AGENTS.md` § „Worker starten“: je Werkzeug, wie parallele Worker gestartet werden (Copilot Fleet,
  Subagents in Gemini CLI und Codex, Cursor Multitask, Cline, Amp, Devin). Aider hat keine Sub-Agenten.
  Roo Code wurde am 15.05.2026 eingestellt und steht deshalb nur noch als Warnhinweis in der Sammlung.
- `install-global.py`: Rollen und die allgemein verwendbaren Skills lassen sich nach `~/.claude/` legen.
  Nicht global: `AGENTS.md`, `docs/ai/`, `docs/project/` — Team, CI und Cloud-Sitzungen sehen das
  Nutzerverzeichnis nicht.
- **Wichtigster Fund der Sitzung:** Claude Code liest von sich aus nur `CLAUDE.md`, niemals `AGENTS.md`.
  Die Grundregeln kamen bisher nur über eine Bitte im Fließtext in den Kontext. Jetzt steht `@AGENTS.md`
  als echter Import in der ersten Zeile — ohne Backticks und außerhalb von Code-Blöcken, sonst greift er
  nicht. Beleg: Doku-Seite zu Memory und Importen.
- Commits: `a8c50d5`, `2d0e72d`.

## 2026-09-13 — dreizehn Punkte der Umbauliste abgearbeitet
- Vier parallele Läufe, je ein Script: `update-template.py` (1, 3, 12, 13, 14), `create-project.py` und
  `maintenance-check.py` (4, 8, 9), `migrate-project.py` (10, 11, 15), Doku (5, 6).
- Punkt 1 größer als geplant: Der feldweise Merge von `.claude/template.json` läuft jetzt auch dann, wenn
  git gar keinen Konflikt meldet — reine Listenergänzungen mergt git klaglos, und der unbedingte
  `save_template_json`-Rewrite hätte die Template-Ergänzung danach still verworfen. Dazu muss
  `save_template_json` unbekannte Felder wie `is_template` erhalten statt sie zu verwerfen.
- Punkt 11 lässt Code-Blöcke und URLs beim Ersetzen des Rufnamens aus (Zeilen-/Regex-Scanner ohne Fremdpaket).
- Punkt 10 nimmt gitignorierte Dateien per `git check-ignore` von der Verschiebung aus und meldet sie nur.
- Punkte 2 und 7 bleiben bewusst offen (keine Freigabe).
- Beleg: `py_compile` über alle sieben Scripte, JSON-Prüfung von `template.json`/`settings.json`,
  End-to-End-Smoketest über alle vier Scripte in Temp-Repos.

## 2026-09-12 — Template-Entwicklung aus `docs/ai/` herausgelöst
- Die 15 Punkte der Umbauliste standen bis dahin in `docs/ai/backlog.md` und wären damit in jedes abgeleitete
  Projekt gewandert. `docs/ai/backlog.md` ist wieder eine leere Vorlage; die Inhalte stehen hier.
- Vorher in dieser Sitzung entstanden: Logging, Template-Updates per Merge, zwei Wege hinein (heute `/create-project`
  und `/apply-template`), Opus als Orchestrator-Default, `expert-solver`, optionale Wartung, Struktur-Migration
  für nachgerüstete Projekte, optionale Code-Analyse, `optimizer`, Guideline-Bausteine.
