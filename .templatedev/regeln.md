# Regeln für die Arbeit am Template

Gilt zusätzlich zu `AGENTS.md` und `CLAUDE.md` — und zwar nur hier, im Template-Repo selbst. Diese Regeln
beschreiben, was beim Ändern der **Vorlage** zu beachten ist; für die Arbeit in einem abgeleiteten Projekt
sind sie ohne Bedeutung.

## Was versioniert ist und was nicht

`backlog.md`, `questions.md` und `ledger.md` sind **gitignored** — sie tragen den laufenden Arbeitsstand und
bleiben lokal. Versioniert bleiben die Struktur (`README.md`, diese Datei), die Testprojekt-Tabelle, die
Vorlagen unter `vorlagen/` und die Scripte.

Was daraus folgt, und zwar in beide Richtungen:

- **Ein frischer Checkout hat keinen Arbeitsstand.** Fehlen die drei Dateien, legt
  `python .templatedev/init.py --apply` sie aus den Vorlagen an. Der SessionStart-Hook meldet beim
  Sitzungsstart, wenn etwas fehlt; angelegt wird erst auf Zuruf. Vorhandene Dateien werden dabei **nie**
  überschrieben — der Arbeitsstand ist unwiederbringlich.
- **Es gibt keine Sicherung.** Kein `git log`, kein Push, kein zweiter Rechner. Wer den Ordner löscht,
  löscht die gesamte Entwicklungsgeschichte des Templates. Der Stand bis zum Commit `db4ba6e` liegt noch in
  der Historie der früheren Datei `.templatedev.md` (`git show db4ba6e:.templatedev.md`) — alles danach
  existiert nur lokal.
- **Was dauerhaft gelten soll, gehört woanders hin.** Eine Erkenntnis, die das Template betrifft, wird als
  Regel in `AGENTS.md`, `CLAUDE.md` oder einen Baustein unter `docs/project/coding_rules.d/` überführt und
  dort committet. Das Journal ist Gedächtnisstütze, nicht Ablage: Was nur dort steht, ist beim nächsten
  Rechnerwechsel weg.

## Was hier anders ist als in einem Projekt

- **`docs/` ist Gerüst, kein Inhalt.** Was dort steht, landet in jedem abgeleiteten Projekt — auch ein gut
  gemeinter Backlog-Eintrag. Arbeitsstände gehören in diesen Ordner, nicht nach `docs/ai/`.
- **Platzhalter bleiben stehen.** `{{PROJEKTNAME}}`, `{{AUFTRAGGEBER}}`, `{{ORCHESTRATOR}}`, `{{STACK}}` und
  die Befehls-Marken werden hier **nie** durch echte Werte ersetzt. Wer sie versehentlich ersetzt, macht die
  Vorlage unbrauchbar.
- **Kein `create-project.py --apply` im Template.** Der Marker `is_template` in `.claude/template.json`
  schützt davor; er wird nie entfernt.

## Änderungen an der Mechanik

- **Jede Änderung an einem Script braucht einen Beleg**, der über `py_compile` hinausgeht: ein echter Lauf in
  einem Wegwerf-Repo unter dem Scratchpad, mit gezeigter Ausgabe. Ein Script, das „kompiliert", ist nicht
  geprüft.
- **Pfadlisten hängen zusammen.** Wird eine Datei umbenannt, verschoben oder neu angelegt, sind mindestens
  diese Stellen zu prüfen:

  | Liste | Datei | Wofür |
  | :--- | :--- | :--- |
  | `COPY_ITEMS`, `EXCLUDE_*` | `apply-template.py` | was beim Nachrüsten kopiert wird |
  | `TEMPLATE_ONLY_PATHS` | `setup-lib.py` | was beim Anlegen entfernt wird |
  | `DEFAULT_TEMPLATE_ONLY` | `update-template.py` | was nie ins Projekt gemergt wird |
  | `template_only`, `keep_local`, `no_replace` | `.claude/template.json` | dasselbe zur Laufzeit |
  | `REMOVE_ITEMS` | `finish-setup.py` | was beim Abschluss der Einrichtung verschwindet |

  Eine vergessene Liste fällt oft erst Wochen später auf, im falschen Projekt.
- **Beide Wege prüfen.** Eine Änderung, die Weg 2 (Nachrüsten) betrifft, betrifft meist auch Weg 1 (Anlegen)
  — und umgekehrt. Der Smoketest über beide Wege ist in `ledger.md` beschrieben.

## Belege und Testprojekte

- Ein Wegwerf-Repo prüft, **dass** ein Script läuft. Ein Testprojekt prüft, **ob die Regel taugt**. Beides ist
  nötig, und nur das Zweite entscheidet.
- Wer eine Regel ändert, prüft sie an dem Testprojekt, das den betroffenen Weg abdeckt (siehe `README.md`
  § Testprojekte). Geht das nicht, wird der Vorbehalt im Journal vermerkt — nicht verschwiegen.

## Delegation im Template

- `.templatedev/` ist Orchestrator-Gebiet wie `docs/ai/` in einem Projekt: **Worker schreiben hier nie.** Sie
  liefern Text zurück, eingepflegt wird er vom Orchestrator.
- Aufträge an Worker werden **nach Dateien** geschnitten, nicht nach Themen — mehrere Agenten gleichzeitig in
  derselben Datei überschreiben einander. Jeder Auftrag nennt ausdrücklich, welche Dateien fremd sind.
- Ergänzungen zu einem laufenden Auftrag werden **nach** dessen Abschluss nachgereicht, nicht mitten hinein.
