> Datenstand: 2026-09-14 – Status: aktuell

# Regeln für die Arbeit am Template

Gilt zusätzlich zu `AGENTS.md` und `CLAUDE.md` — und zwar nur im Template-Repo selbst
(`D:\dev\rufeger\template-agentic-coding-project`). Diese Regeln beschreiben, was beim Ändern der **Vorlage**
zu beachten ist; für die Arbeit in einem abgeleiteten Projekt sind sie ohne Bedeutung.

## Wo Umbauliste, Fragen und Journal liegen

Alles in diesem Ordner `.templatedev/`, versioniert wie jede andere Datei des Repos. `docs/ai/` und
`docs/project/` bleiben leere Vorlagen — was dort steht, wandert in jedes abgeleitete Projekt.

Dass der Arbeitsstand hier liegt und nicht anderswo, ist eine bewusste Entscheidung nach zwei Fehlversuchen
(beide am 2026-09-14, Begründung im `ledger.md`): gitignored verliert Historie und Sicherung, ein getrenntes
Entwicklungs-Repo trennt Struktur von Notizen, obwohl man beim Arbeiten beides zugleich braucht. Wer die
Ablage erneut ändern will, liest zuerst diese beiden Einträge.

## Was hier anders ist als in einem Projekt

- **`docs/` im Template ist Gerüst, kein Inhalt.** Was dort steht, landet in jedem abgeleiteten Projekt — auch
  ein gut gemeinter Backlog-Eintrag. Arbeitsstände zur Template-Entwicklung gehören in dieses Projekt, nicht
  nach `docs/ai/` oder `docs/project/` des Templates.
- **Platzhalter bleiben stehen.** `{{PROJEKTNAME}}`, `{{AUFTRAGGEBER}}`, `{{ORCHESTRATOR}}`, `{{STACK}}` und
  die Befehls-Marken werden im Template **nie** durch echte Werte ersetzt. Wer sie versehentlich ersetzt,
  macht die Vorlage unbrauchbar.
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
  — und umgekehrt. Der Smoketest über beide Wege gehört ins Journal dieses Projekts (`docs/ai/ledger.md`).

## Belege und Testprojekte

- Ein Wegwerf-Repo prüft, **dass** ein Script läuft. Ein Testprojekt prüft, **ob die Regel taugt**. Beides ist
  nötig, und nur das Zweite entscheidet.
- Wer eine Regel ändert, prüft sie an dem Testprojekt, das den betroffenen Weg abdeckt (siehe
  `docs/project/testprojekte.md`). Geht das nicht, wird der Vorbehalt im Journal vermerkt — nicht verschwiegen.

## Delegation im Template

- `docs/ai/` **dieses Projekts** ist Orchestrator-Gebiet: **Worker schreiben hier nie.** Sie liefern Text
  zurück, eingepflegt wird er vom Orchestrator. Im Template-Checkout selbst gilt dieselbe Regel für dessen
  `docs/ai/`-Gerüst.
- Aufträge an Worker werden **nach Dateien** geschnitten, nicht nach Themen — mehrere Agenten gleichzeitig in
  derselben Datei überschreiben einander. Jeder Auftrag nennt ausdrücklich, welche Dateien fremd sind.
- Ergänzungen zu einem laufenden Auftrag werden **nach** dessen Abschluss nachgereicht, nicht mitten hinein.
