> Datenstand: 2026-09-17 – Status: entschieden — `Q12`–`Q15` beantwortet, Umsetzung offen (T5)

# Template-Pflege als eigenes Projekt in `.templatedev/`

**Leitfrage:** Wie wird `.templatedev/` ein Projekt mit derselben Struktur und denselben KI-Regeln wie ein per
`/create-project` angelegtes — ohne dass der Root seine Rolle als Template verliert? (T5, Variante a aus `Q7`)

**Aufwand:** ~1,5 PT in fünf Schritten, siehe unten.

## Ausgangslage

- **Inhalt ohne Struktur.** `.templatedev/` hat `backlog.md`, `questions.md`, `tasks.md`, `tasks_archive.md`,
  `ledger.md` (1:1 zu `docs/ai/`), dazu Dateien ohne Gegenstück: `INDEX.md`, `README.md` (Testprojekte),
  `regeln.md`, `konzept-*.md`, `testprojekte.py`, `scripts/`, `daten/`. Es fehlen `board.md`,
  `questions_archive.md`, `checklists.md`, `README.md` im Sinne von `docs/ai/README.md` — und damit die
  Formregeln, weshalb Fragen hier bisher knapper aussehen als in jedem Projekt.
- **Ladeverhalten** (Versuch 2026-09-16, Ledger): Sitzung in `.templatedev/` lädt CLAUDE.md, Agenten und
  Skills des Roots mit; gleichnamige in `.templatedev/` gewinnen; Eltern-CLAUDE.md per `claudeMdExcludes`
  abschaltbar; `settings.json`/Hooks nur aus `.templatedev/`.
- **Scripte sind wiederverwendbar.** Probe 2026-09-16: In der Sitzung zeigt `CLAUDE_PROJECT_DIR` auf
  `.templatedev/`; ein Hook mit `"shell": "bash"` ruft `$CLAUDE_PROJECT_DIR/../.claude/scripts/<name>.py`
  auf. Alle Root-Scripte nehmen `CLAUDE_PROJECT_DIR` als Projektordner — sie arbeiten dann auf
  `.templatedev/`, ohne kopiert zu werden.
- **Sonderfälle im Root:**

| Gruppe | Umfang | Nach dem Umbau |
| :--- | :--- | :--- |
| `is_template`-Abfragen | 39 Stellen, 8 Dateien | **bleiben** — schützen den Template-Checkout vor `create-project --apply`, Feedback-Versand |
| `template_only` (`setup-lib.py`, `update-template.py`, `template.json`) | 3 Listen | **bleiben** — `.templatedev/` darf nie in ein Projekt |
| Blöcke `template-only` in `AGENTS.md`/`CLAUDE.md` | 2 Blöcke, ~30 Zeilen | **schrumpfen** auf einen Hinweis (`Q14`) |
| `.templatedev`-Pfade in `check-refs.py` | Sammeln + 3 Definitionslisten | **entfallen** — `.templatedev/` wird ein eigener Lauf mit `docs/ai/` |
| `testprojekte.py`, `scripts/feedback-abholen.py` | Root über `CLAUDE_PROJECT_DIR` bzw. `parents[N]` | **anpassen** — in der neuen Sitzung ist `CLAUDE_PROJECT_DIR` nicht mehr der Root |

Weniger Sonderfälle als erhofft: Der Gewinn liegt in Struktur und Formregeln, nicht im Streichen von
`is_template`.

## Zielbild

```text
.templatedev/
├── AGENTS.md  CLAUDE.md          # geerbt aus dem Root, Platzhalter ersetzt (Q12)
├── AI-CONFIG.md                  # Projekt „Template-Pflege", Auftraggeber Wolfgang, Orchestrator Opus
├── .claude/
│   ├── settings.json             # claudeMdExcludes für ../CLAUDE.md, Hooks → ../.claude/scripts/
│   ├── template.json             # Werte der Platzhalter, kein is_template
│   └── skills/                   # Sperr-Fassungen: create-project, apply-template, finalize,
│                                 # update-template, run-maintenance („hier nicht — Sitzung im Root")
├── docs/
│   ├── ai/                       # board, tasks(+archive), questions(+archive), ledger, backlog,
│   │                             # README und checklists geerbt
│   └── project/                  # coding_rules.md ← regeln.md; test-projects.md ← README.md;
│                                 # konzepte/ ← konzept-*.md; data/ ← daten/ (Q13)
└── scripts/                      # test-projects.py, feedback-fetch.py, feedback-endpoint.php …
```

## Umsetzung

1. **Gerüst** (0,25 PT): `AI-CONFIG.md`, `.claude/settings.json`, `.claude/template.json`, leere
   `docs/ai/`-Dateien. Beleg: `claude -p` in `.templatedev/` — nur eigene CLAUDE.md, Hooks laufen.
2. **Umzug** (0,5 PT): per `git mv` (Historie bleibt), englische Namen, Verweise nachziehen;
   `questions.md`/`tasks.md` auf die Formregeln aus `docs/ai/README.md` bringen. Beleg: `check-refs.py
   --root .templatedev` ohne tote Verweise.
3. **Vererbung** (0,5 PT): Script `scripts/sync-rules.py` erzeugt `AGENTS.md`, `CLAUDE.md`,
   `docs/ai/README.md`, `docs/ai/checklists.md` aus dem Root mit den Werten aus `.claude/template.json`
   (nutzt `replace_placeholders` aus `files-lib.py`, entfernt die `template-only`-Blöcke); `--check` als
   SessionStart-Hook meldet Abweichungen. Sperr-Skills anlegen.
4. **Root aufräumen** (0,25 PT): Blöcke in `AGENTS.md`/`CLAUDE.md` kürzen (`Q14`), `.templatedev`-Sonderpfade
   aus `check-refs.py`, `testprojekte`-Scripte auf festen Root umstellen.
5. **Beleg:** Pflege-Sitzung in `.templatedev/` mit Fragen und `/commit`; `/create-project` in einem
   Wegwerf-Klon entfernt `.templatedev/` weiterhin vollständig.

**Stolperstein `/commit`:** Die Sitzung liegt nicht im Git-Root — Pathspecs sind relativ zu `.templatedev/`.
Änderungen am Template (`../.claude/…`) müssen mit `../` angegeben werden; Schritt 5 prüft genau das.

## Pflege-Modus im Root (Wunsch 2026-09-17, zurückgestellt — Backlog-Punkt 35)

Schalter in `.env`, z. B. `TEMPLATEDEV_MODE=ein`: Eine Sitzung im Root verhält sich, als liefe sie in
`.templatedev/` — praktisch, wenn IDE und Terminal ohnehin im Root geöffnet sind.

**Was geht:**

- **Regeln umlenken:** Der SessionStart-Hook von `finish-setup.py --check` meldet im Template-Checkout heute
  „hier nichts zu tun". Er liest zusätzlich den Schalter aus `.env` und gibt dann den Pflege-Kontext aus:
  `.templatedev/AGENTS.md` und `CLAUDE.md` gelten, Arbeitsordner ist `.templatedev/docs/ai/`, Pathspecs mit
  `.templatedev/` davor. Kein neuer Hook, also nichts, was in abgeleitete Projekte wandert.
- **Scripte umlenken:** Scripte, die Projektdateien lesen (`check-refs.py`, `sync-config.py`, `ai-log.py` …),
  nehmen bei gesetztem Schalter `.templatedev/` als Projektordner — nur im Template-Checkout (`is_template`).
- **Sperren:** `create-project`, `apply-template`, `finalize` lehnen im Pflege-Modus ab (Script-Ebene).

**Was nicht geht — das ist der Unterschied zu einer Sitzung in `.templatedev/`:**

- Claude Code liest `.env` nicht; der Schalter wirkt nur über Hook-Ausgabe und Scripte.
- Die Root-`CLAUDE.md` mit Platzhaltern bleibt geladen, `.templatedev/.claude/settings.json` (Ausschlüsse,
  Hooks) und die Sperr-Skills gelten nicht. Zwei Regelsätze stehen im Kontext; der Hook sagt, welcher gilt —
  das ist eine Anweisung, keine technische Trennung.
- Ein Umschalten wirkt erst mit der nächsten Sitzung.

**Aufwand:** ~0,5 PT zusätzlich (Schalter lesen in einer gemeinsamen Hilfsfunktion, Hook-Text, drei Sperren).

## Empfehlung

- `Q12` a — gerenderte Kopie: Regeln gelten wörtlich wie in jedem Projekt, ohne Platzhalter und ohne den
  Template-Block; das Script hält sie aktuell.
- `Q13` a — alles in die Standardorte, englische Namen; `docs/project/konzepte/` bleibt so, solange das
  Template selbst den Ordner so nennt.
- `Q14` a — drei Zeilen im Root statt ~30.
- `Q15` a — Schalter in `.env` wie gewünscht; die Grenzen oben stehen dann im Hook-Text selbst.

## Entschieden am 2026-09-17

- **Vererbung (`Q12` a):** gerenderte Kopie per `scripts/sync-rules.py`, `--check` beim Sitzungsstart.
- **Ablage (`Q13` b):** Standardorte mit englischen Namen; zusätzlich heißt `docs/project/konzepte/` im
  Template künftig `docs/project/concepts/` — alle Links, Erwähnungen und Referenzen werden geprüft.
  Abgeleitete Projekte (`bandliste`) behalten eigene Konzepte zunächst im alten Ordner; der Umzug dort ist
  ein Hinweis beim nächsten `/update-template`.
- **Root (`Q14` a):** drei Zeilen Hinweis statt der Blöcke.
- **Pflege-Modus (`Q15` c):** kein Schalter; Idee als Backlog-Punkt 35.
- **Wechsel der Sitzung:** bis einschließlich Schritt 4 wird im Root gearbeitet; erst für den Beleg in
  Schritt 5 startet Wolfgang eine neue Sitzung in `.templatedev/` — das wird rechtzeitig angesagt.
