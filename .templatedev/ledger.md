> Datenstand: 2026-09-14 – Status: aktuell

# Ledger — Template-Entwicklung

Sitzungs-Journal und Kurzchronik. Neueste Sitzung oben. Nur der Orchestrator schreibt hier.

**Verdichtungsregeln:**
- Heutiger Tag und der Vortag: detailliert, alle Läufe eines Tages unter einer Tagesüberschrift.
- Älter als 2 Tage bis 1 Woche: ein Eintrag je Tag, max. 8 Stichpunkte.
- Älter als 1 Woche: ein Eintrag je Monat (Abschnitt „Archiv" ganz unten).
- Commit-Hashes, Nummern, Versionen, Dateipfade und Kennzahlen werden nie weggekürzt.

---

## 2026-09-14 — Präsentationen: kein MCP-Server, sondern Skill `/slides`

Wolfgang wollte einen PowerPoint-MCP-Server (`ykuwai/ppt-mcp`, `Ayushmaniar/powerpoint-mcp`) oder „eine
andere Möglichkeit, eine Präsentation für sein Projekt zu erstellen".

- **Beide genannten Server steuern ein laufendes, installiertes PowerPoint über COM.** Das verlangt Windows
  *und* eine Office-Lizenz — Ausschluss für ein plattformneutrales Template. Der einzige Server ohne
  Office-Zwang (`GongRzhe/Office-PowerPoint-MCP-Server`, 1.900 Sterne) ist seit dem 2026-03-03 **archiviert**
  und war ohnehin nur ein dünner Wrapper um `python-pptx`. Einen offiziellen Server von Microsoft oder Google
  gibt es nicht.
- **Hier lohnt überhaupt kein MCP-Server.** Alle brauchbaren Folienwerkzeuge sind Kommandozeilenprogramme —
  ein Server brächte nur dann etwas, was ein Script nicht kann, wenn eine bereits geöffnete fremde
  Präsentation live weiterbearbeitet werden soll. Das ist der Fall nicht.
- **Neuer Skill `/slides`** mit **Marp** (offiziell gepflegt, 3.800 Sterne): Folien sind eine Markdown-Datei
  im Repo, versioniert und diffbar; Export per `npx`, nur Node und ein Browser nötig. Am Beleg geprüft:
  `npx @marp-team/marp-cli` erzeugt hier eine HTML-Datei aus einer zweiseitigen Probe.
- **Die eine Einschränkung ehrlich benannt:** Marps PPTX-Export sind **Bildfolien**, nicht nachbearbeitbarer
  Text. Wer wirklich eine editierbare `.pptx` braucht, nimmt **Quarto** (über Pandoc, echte Textfolien,
  dafür eigene CLI-Installation). Der Skill sagt das und lässt {{AUFTRAGGEBER}} entscheiden, statt Marp als
  PowerPoint-Ersatz zu verkaufen.
- **Abgegrenzt:** Ins Template gehört die **Fähigkeit**, nicht der Inhalt. Ein konkreter Foliensatz über
  dieses Template wäre projekteigener Inhalt und würde über `create-project` in jedes abgeleitete Projekt
  wandern — derselbe Fehler wie seinerzeit die Notizen in `docs/ai/`. Wolfgang hat das klargestellt, als ich
  ihm eine Schulungsgliederung als Zwischenstand vorlegte; sie lag nur im Scratchpad, aber das Vorlegen
  allein hat schon den falschen Eindruck erzeugt.

## 2026-09-14 — Fünf Quellen zu MCP-Servern und Skills ausgewertet

Wolfgang hat fünf Listen genannt (totalum.app, skyvia, awesome-claude-skills, welcomedeveloper,
Stack-Overflow-Ankündigung). Ausbeute bewusst klein gehalten — die Listen sind zu einem guten Teil Werbung.

- **Aufgenommen (2 von rund 60 genannten):** `kubernetes` (containers-Org, Go, aktiv — Cluster ohne
  `kubectl`-Umweg) und `firecrawl` (Mendable, offiziell — Doku-Websites als Markdown, kann Crawling und
  JS-Rendering, also mehr als ein Fetch). Katalog jetzt 41 Server.
- **Stack Overflow** gibt es wirklich (offiziell, Beta seit 12/2025), aber mit einstelliger Commit-Zahl und
  100 Aufrufen am Tag. Der Vorteil gegenüber der Websuche wäre die Struktur (akzeptierte Antwort, Stimmen) —
  das wiegt die Unreife heute nicht auf. Als „beim nächsten Durchgang erneut ansehen" dokumentiert, nicht
  stillschweigend übergangen.
- **Neuer Skill `/a11y`.** Die einzige echte Lücke unter den 17 vorhandenen: Barrierefreiheit kam bisher als
  halber Satz in `/design-build` vor. `/design-build` prüft gegen die **Vorlage** („sieht es aus wie
  gedacht?"), `/a11y` gegen die **Benutzbarkeit** („kommt jeder damit klar?") — eine Oberfläche kann der
  Vorlage exakt entsprechen und trotzdem mit der Tastatur unbedienbar sein.
- **Verworfen:** Superpowers und Spartan Toolkit (ihr Ablauf Spec→Plan→Test→Review ist genau das, was
  `AGENTS.md` schon vorschreibt), Code Simplifier (= `optimizer`), alles Stack-Spezifische (Vercel-React,
  shadcn, Expo, iOS-Simulator — widerspricht der Stack-Neutralität), sowie CRM-, Marketing- und
  Vertriebsanbindungen. Reine API-Wrapper (Exa, Brave Search, Browserbase) ebenfalls nicht.
- **Die Lehre zu solchen Listen:** Von rund sechzig genannten Einträgen blieben zwei. Die Trefferquote sinkt
  mit jeder weiteren Liste, weil sie voneinander abschreiben — der Aufwand steckt im Aussortieren, nicht im
  Finden. Ein Eintrag, der nur in einer Liste steht und dort auffällig beworben wird, stammt meist vom
  Betreiber der Liste selbst.

## 2026-09-14 — Sechs Formbefunde aus `bandliste`, alle im Template behoben

Wolfgang hat `docs/ai/` in `bandliste` durchgesehen. **Alle sechs Befunde sind Template-Befunde** — die
Struktur dieser Dateien kommt aus der Vorlage, `bandliste` hat sie nur sichtbar gemacht. Genau der Kreislauf,
für den `.templatedev` da ist (`regeln.md`).

| Befund | Ursache im Template | Behoben durch |
| :--- | :--- | :--- |
| Einleitungen zu lang, KI-Anweisungen mitten im Arbeitsblatt | Formregeln standen doppelt: in `docs/ai/README.md` **und** im Kopf jeder Arbeitsdatei | Regeln nur noch in `README.md`; `tasks.md` 101 → 41, `questions.md` 73 → 25, `backlog.md`/`board.md`/`ledger.md` auf einen kurzen Kopf gestutzt |
| Anmerkungen sammeln sich am Backlog-Ende und werden übersehen | keine Regel, was mit Rückfragen am Punkt passiert | Regel: daraus wird sofort eine Frage oder Aufgabe, am Punkt bleibt der Verweis |
| „Umbauliste" statt „Backlog" | Erfindung des Templates, im Deutschen ist „Backlog" der gebräuchliche Name | in allen `.md` ersetzt (`.py`-Kommentare mit historischen Punktnummern blieben) |
| Board sammelt Erledigtes und Belangloses | keine Abgrenzung je Abschnitt | drei Abschnitte mit klarer Regel; „Offene Freigaben" → **„Ausstehende Freigaben"**; Checkliste „Aufgabe abschließen" Schritt 5 sagt jetzt ausdrücklich, was **entfernt** wird |
| Ledger: `### n. Lauf`, älteste Einträge oben | Vorlage gab die Laufnummer vor und sagte „neueste oben" nur im Fließtext | Überschriften tragen die **Uhrzeit**; Sortierregel gilt ausdrücklich auf beiden Ebenen |
| `migration-scope.md` frei in `docs/ai/` abgelegt | für Analysen und Konzepte gab es **keinen** vorgesehenen Ort — obwohl die Querverweis-Tabelle längst auf `stories/` verwies, das es im Template gar nicht gab | neu: `docs/project/konzepte/` und `docs/project/stories/`, beide mit Format-README; `docs/ai/README.md` § „Was hier *nicht* hingehört" |

- **Dazu ein siebter, ungefragter Befund:** Die Statuszeile `> Datenstand: … – Status: Vorlage, noch nicht
  projektspezifisch` blieb in **jedem** abgeleiteten Projekt stehen — in `bandliste` in 8 Dateien. Der Zusatz
  ist kein `{{PLATZHALTER}}`, also hat ihn nie jemand ersetzt. `setup-lib.py` ersetzt ihn jetzt unter `docs/`
  mit; das Vokabular der Statuswörter (`aktuell` · `Entwurf` · `veraltet`) steht in `docs/README.md`
  § Konventionen. In `bandliste` standen bis dahin elf verschiedene Statustexte nebeneinander.
- **Die Lehre:** Die Vorlage hat jedes dieser Formate einmal beschrieben — aber an zwei Stellen zugleich, und
  dann nur die eine gepflegt. Eine Regel gehört an genau einen Ort; die Arbeitsdatei bekommt einen Zeiger,
  keine Kopie. Vier der sieben Befunde sind Varianten dieses einen Fehlers.
- **Zweiter Punkt, allgemeiner:** Drei Befunde entstanden nicht aus einer falschen Regel, sondern aus einer
  **fehlenden**. Wo das Template keinen Platz vorsieht (Konzepte, Stories), erfindet das Projekt einen — und
  weil die Erfindung nirgends steht, prüft sie auch keine Checkliste. Deshalb kamen `konzepte/` und
  `stories/` als leere, dokumentierte Ordner ins Template, nicht nur als Regel im Fließtext.
- **Rückweg aus `bandliste`, zweiter Teil (Abgleich am 2026-09-14):** Der Bestand beider Repos verglichen.
  Übernommen war bereits `legacy-inventory.py` → `code-inventory.py` (verallgemeinert), die Formate von
  `konzepte/` und `stories/`, die Nuxt-Regeln, die MCP-`${VAR}`-Erkenntnis und die README-Regel. **Zwei
  Lücken blieben:** die Backlog-**Tabelle** (dort seit 55 Punkten im Einsatz, im Template gab es kein Format
  über die nummerierte Liste hinaus — jetzt mit Schwelle „ab etwa fünfzehn Punkten" und dem bewährten
  Spaltensatz beschrieben) und die Form des Fragen-Archivs (die Vorlage sagte „chronologisch, älteste
  zuerst", die neue Regel gruppiert nach Verschiebelauf mit neuester Gruppe oben — die Vorlage widersprach
  also der Regel, die im selben Ordner steht).
- **Rückweg aus `bandliste`:** Dort war eine Regel entstanden, die das Template nicht hatte — jede Antwort
  von Wolfgang wird **an Ort und Stelle** quittiert (`✅ **<Datum Uhrzeit>** — <Folge>`), nie gesammelt am
  Dateiende. Sie ist jetzt in `docs/ai/README.md` § „Antworten quittieren". Das ist die Richtung, für die
  `.templatedev` eigentlich da ist: Das Testprojekt liefert nicht nur Fehler, sondern auch Lösungen.
- Offen geblieben: `AGENTS.md` nennt `docs/ai/checklists.md` und `.claude/skills/create-project/SKILL.md` als
  `no_replace`, `template.json` führt dort aber nur die drei `.py`-Dateien. Einer von beiden hat unrecht —
  als `B28` notiert.

## 2026-09-14 — Kürzel vereinheitlicht; Verlinken versucht und wieder verworfen

- **Umbenannt:** `A<n>` → `T<n>` (Task), `F<n>` → `Q<n>` (Question), Backlog-Verweise bekommen `B<n>`;
  `S<n>` und `ADR-<n>` bleiben. Ohne führende Null. 56 Ersetzungen in 12 Dateien, Commit `4da3c11`.
  Grund: Die Mischung aus deutschen und englischen Anfangsbuchstaben war nicht mehr zuzuordnen — `A` stand
  für Aufgabe, `F` für Frage, `S` aber schon für Story. Ich hatte vom Umbenennen abgeraten (Verweise in
  alten Commits zeigen ins Leere); Wolfgang hat es entschieden, und die Zuordnung ist jetzt eindeutig.
- **Verworfen: Kürzel als Markdown-Links.** `check-refs.py --links` konnte fehlende Links ergänzen und hat
  im Template 10 gesetzt. Beim Ansehen fiel der Konstruktionsfehler auf: Aufgaben, Fragen und Umbaupunkte
  sind Listen- oder Tabellenzeilen **ohne eigene Überschrift**, also ohne Anker. Jeder `B<n>`-Link landet
  am Kopf von `backlog.md`, die Suche nach dem Eintrag beginnt dort von vorn. Ein Link, der nur den
  Dateinamen wiederholt, kostet Lesbarkeit und bringt nichts.
- Zurückgenommen: die 10 Links, der `--links`-Modus samt `--yes` in `check-refs.py`, die Verlink-Regel in
  `docs/ai/README.md` § „Querverweise". Geblieben ist die **Prüfung** auf tote und verwaiste Verweise —
  die hat Wert, sie findet Nummern ohne Ziel. Beleg: `check-refs.py` meldet 41 Dateien, 16 Zitate,
  28 Definitionen, 0 tot.
- Die Kürzel-Tabelle in `docs/ai/README.md` sagt jetzt ausdrücklich, dass **nicht** verlinkt wird, und
  warum — sonst schlägt es der nächste Lauf wieder vor.
- **Die Lehre:** Eine Verlinkung ist nur so gut wie ihr Anker. Wo das Ziel keine Überschrift hat, ist die
  Volltextsuche nach dem Kürzel der schnellere Weg.

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
  (jetzt Umbaupunkt `B22`). Der Rest des Repos war Doppelung des hier Vorhandenen.
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
- **Übernommen:** Umbauliste → `docs/ai/backlog.md` (Punkte `B1`–`B21` mit ihren Nummern), Journal →
  `docs/ai/ledger.md`, Regeln → `docs/project/template-pflege.md`, Testprojekte →
  `docs/project/testprojekte.md`, `testprojekte.py` → `.claude/scripts/`.
- **Damit hat das Template sein Weg-1-Testprojekt**, das bisher fehlte: Dieses Repo ist selbst aus dem
  Template entstanden und zieht Änderungen per `/update-template` nach.
- **Wartung eingeschaltet** (`testprojekte=7, docs=30, kurz=14`) — der Abgleich der Test-Installationen ist
  der wiederkehrende Zweck dieses Projekts, keine Nebensache.
- Offen war damals: im Template den Verweis setzen und die gitignore-Sonderregel zurücknehmen (im
  aufgelösten Repo als eigene Aufgabe geführt; erledigt mit dem Rückbau am selben Tag).

## 2026-09-13 — erster echter Einsatz am Fremdprojekt, danach sieben Punkte
- **Das Template wurde zum ersten Mal auf ein bestehendes Projekt angewendet** (`bandliste`, Nuxt 4 +
  Prisma, 107 Dateien, dazu 49.000 Dateien Alt-PHP in `old-project/`). Der Durchlauf hat mehr über das
  Template verraten als jede Prüfung am eigenen Repo: Zwei Fehler fielen erst dort auf (Punkte `B17` und `B18`),
  und zwei Anforderungen entstanden aus dem, was danach im Projekt liegen blieb (19 und 20).
- **Punkt `B18` war der teuerste Fund.** `.junie/guidelines.md` enthielt 110 Zeilen projekteigener Stil- und
  Sicherheitsregeln — genau das Material, für das `docs/project/coding_rules.md` da ist. `migrate-project.py
  --plan` meldete „keine Kandidaten". Aufgefallen ist es nur, weil ein `explorer` die Datei nebenbei erwähnte.
  Ohne diesen Zufall hätten zwei Regelwerke nebeneinander gegolten. Lehre: Die Kandidatenliste muss die
  Ablagen **anderer** Werkzeuge kennen, nicht nur die eigenen — nachgezogen für Junie, Cline, Windsurf, Roo,
  Copilot-Instructions und `AGENT.md`.
- **Punkt `B19`, die eigentliche Neuerung:** Nach der Einrichtung blieb das gesamte Einrichtungswerkzeug im
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
- Punkt `B1` größer als geplant: Der feldweise Merge von `.claude/template.json` läuft jetzt auch dann, wenn
  git gar keinen Konflikt meldet — reine Listenergänzungen mergt git klaglos, und der unbedingte
  `save_template_json`-Rewrite hätte die Template-Ergänzung danach still verworfen. Dazu muss
  `save_template_json` unbekannte Felder wie `is_template` erhalten statt sie zu verwerfen.
- Punkt `B11` lässt Code-Blöcke und URLs beim Ersetzen des Rufnamens aus (Zeilen-/Regex-Scanner ohne Fremdpaket).
- Punkt `B10` nimmt gitignorierte Dateien per `git check-ignore` von der Verschiebung aus und meldet sie nur.
- Punkte `B2` und `B7` bleiben bewusst offen (keine Freigabe).
- Beleg: `py_compile` über alle sieben Scripte, JSON-Prüfung von `template.json`/`settings.json`,
  End-to-End-Smoketest über alle vier Scripte in Temp-Repos.

## 2026-09-12 — Template-Entwicklung aus `docs/ai/` herausgelöst
- Die 15 Punkte der Umbauliste standen bis dahin in `docs/ai/backlog.md` und wären damit in jedes abgeleitete
  Projekt gewandert. `docs/ai/backlog.md` ist wieder eine leere Vorlage; die Inhalte stehen hier.
- Vorher in dieser Sitzung entstanden: Logging, Template-Updates per Merge, zwei Wege hinein (heute `/create-project`
  und `/apply-template`), Opus als Orchestrator-Default, `expert-solver`, optionale Wartung, Struktur-Migration
  für nachgerüstete Projekte, optionale Code-Analyse, `optimizer`, Guideline-Bausteine.
