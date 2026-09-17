> Datenstand: 2026-09-17 – Status: aktuell

# Ledger — Template-Entwicklung

Sitzungs-Journal und Kurzchronik. Neueste Sitzung oben. Nur der Orchestrator schreibt hier.

**Verdichtungsregeln:**
- Heutiger Tag und der Vortag: detailliert, alle Läufe eines Tages unter einer Tagesüberschrift.
- Älter als 2 Tage bis 1 Woche: ein Eintrag je Tag, max. 8 Stichpunkte.
- Älter als 1 Woche: ein Eintrag je Monat (Abschnitt „Archiv" ganz unten).
- Commit-Hashes, Nummern, Versionen, Dateipfade und Kennzahlen werden nie weggekürzt.

---

## 2026-09-17

### T5 — `.templatedev/` wird eigenes Pflege-Projekt

- Vorbereitet per `/act-prepare`: 3 Recherchen parallel (Scripte bei Unterordner-Sitzung, Umzugsliste, Doku zum
  Ladeverhalten). Versuche mit `claude -p` (2.1.274, Zufallswörter): Eltern-`CLAUDE.md` wird mitgeladen;
  `claudeMdExcludes` greift nur mit absolutem Pfad (relativ `../CLAUDE.md` nicht, `**/CLAUDE.md` schließt auch
  die eigene aus) — daher Liste in gitignorierter `.templatedev/.claude/settings.local.json`; gleichnamiger
  Skill im Unterordner gewinnt (Doku-Recherche hatte das Gegenteil behauptet, Versuch gilt).
- Entscheidungen: Q19 b (Marker `.maintainer` entfällt, strikte Trennung, Pflege nur per Sitzung in
  `.templatedev/`), Q20–Q23 a; `/act-update-template` in `.templatedev/` zieht immer aus dem Parent (Weiterleitung an
  `sync-rules.py`, nie Fetch/Merge); alle Spezialregeln gelten weiter.
- Welle 1: Sperren in 8 Scripten über `is_template_maintenance_dir` (`config-lib.py`), Marker entfernt,
  `metadata.phase`, `check-refs.py` ohne Sonderpfade; Umzug per `git mv` an Standardorte (englische Namen,
  `INDEX.md` → `docs/README.md` + `board.md`, Q1–Q18 → `questions_archive.md`, Backlog-Punkt 35 gelöscht); Template-Ordner
  `docs/project/konzepte/` → `concepts/` samt Update-Hinweis in der Checkliste.
- Welle 2: Journal verdichtet (986 → 368 Zeilen, alle Hashes/Nummern per Script verglichen);
  `.templatedev/scripts/sync-rules.py` (rendert `AGENTS.md`, `CLAUDE.md`, `docs/ai/README.md`,
  `docs/ai/checklists.md` aus dem Root-Arbeitsstand mit den echten Setup-Funktionen); Gerüst (`AI-CONFIG.md`,
  `settings.json` mit `additionalDirectories`, `template.json` mit `setup_complete`, 5 Sperr-Skills,
  `act-process-feedback` nach `.templatedev/`).
- Welle 3: `act-help.py` sucht Skills bis zum Git-Root (näherer gewinnt); Root-Blöcke in `AGENTS.md`/`CLAUDE.md`
  auf wenige Zeilen (Q14), „Einstieg in Alltagssprache" als zweiter `template-only`-Block.
- Beleg: `claude -p` in `.templatedev/` sieht nur die gerenderte `CLAUDE.md` (kein `{{PROJEKTNAME}}`).
- Review BLOCK: Feedback aus dem Pflege-Ordner sendbar (`feedback.py` ohne Sperre) → behoben, `--status`/`--direkt`
  rc 2; Sperre per `..`-Pfad umgehbar → `resolve()`; Allow-Regel `scripts/*.py` zu breit (Token-Ausgabe,
  Quittieren am Endpunkt) → nur lesende Aufrufe; `claudeMdExcludes` überschrieb eigene Einträge → zusammengeführt.
  Wegwerf-Klon Weg 1: `.templatedev/`, Hinweis-Hook und alle template-only-Blöcke entfernt.
- Belege: py_compile aller Scripte, `check-refs.py` Root und `--root .templatedev` 0 tot, `create-project.py
  --check` ok, `sync-rules.py --check` rc 0.

### B22, B27, B48, B51

- B27 (Wolfgang): Schlüssel `Sprache` entfernt, Deutsch fest; Ideensammlung Mehrsprachigkeit im Backlog, Prio mittel (u. a. Englisch als Basis, Projektsprache nur für neue `docs/`-Inhalte).
- B48: `/act` nach Repo-Stand gefiltert (Frontmatter `phase`), `/act all`; Phasenwert `maintenance` statt `pflege`.
- B22: `bandliste` durchgesehen (Fragen/ADRs/Backlog fachlich) → 6 Kandidaten: Ersetzung lief durch `node_modules`
  (jetzt gemeinsame `iter_repo_replace_files`), Kodierungsregel `AGENTS.md`, 4 Bausteine `nuxt.md`/`vue.md`
  (u. a. `method="post"` bei `@submit.prevent`, `useState` statt modulweitem `ref`).
- B51 (Wolfgang): frischer Klon erklärt sich selbst. Entscheidungen: Marker `.templatedev/.maintainer`, gilt bis
  angelegt, zuerst Hook mit festem Text — nach Review verworfen (blockte Interview-Antworten), auf Wunsch
  umgestellt auf `additionalContext`, das Modell bewertet.
- Review R1 BLOCK: Interview geblockt; B22-Fix brach Weg 2 (nur `git ls-files`, 53 Dateien mit Platzhaltern) →
  `--cached --others --exclude-standard`; `/act` blendete `act-apply-template` im Weg-2-Ziel aus; Hook blieb in
  angelegten Projekten → entfernt per `remove_welcome_hook`/`TEMPLATE_ONLY_PATHS`. R2 ALLOW, Restpunkte selbst
  behoben (Hook-Text als „keine Nutzeranweisung", Marker nicht selbst anlegen; toter `.gitignore`-Eintrag).
- Geklärt: `decision: block` bei `UserPromptSubmit` ist laut Doku unterstützt (Zitat im Review).
- Belege: py_compile, `check-refs.py` 0 tot, `create-project.py --check` ok, Smoketests Weg 1/Weg 2/Hook-Zustände.

### Rückmeldungen B36–B43 umgesetzt, dazu B44/B45 und Q16–Q18

- Q16 a): gepusht `6843618..8807ad1`. Q17 b): Kurzform-Skills `commit`, `idea`, `prepare`, `update-template`. Q18 a): nichts zu tun.
- Fünf `builder` parallel, nach Dateien geschnitten: `update-template.py` (B36, B38, später B37-Anschluss, F4),
  `config-lib`/`files-lib`/`sync-config` (B43, B37), `feedback.py` (B39), `AI-CONFIG.md` + neu
  `docs/ai/config-guide.md` + `docs/ai/README.md` (B40, B41), `setup-lib`/`act-help` + Kurzformen (B42, Q17).
- Review in vier Runden (`reviewer`, Opus):
  - R1 BLOCK: lokal gewählter Protokollort ging beim Migrieren verloren (F1), verschobener AI-CONFIG-Schlüssel
    verlor seinen Wert (F2), `--check` fetchte im Hook (F3), Kurzformen kollidieren beim Update mit alten
    Skillpfaden (F4, Entscheidung: Template gewinnt, mit Warnung und Rückweg).
  - R2 BLOCK: B38 griff nicht, weil `/act-finalize` genau `finish-setup.py` löscht; Hook meldete reine Hinweise
    bei jedem Start.
  - R3 BLOCK (Sicherheit): der B38-Fix führte beim Sitzungsstart `finish-setup.py` aus dem frisch geholten
    Template-Ref aus. Jetzt: Ref nur statisch per `ast.literal_eval`, Ausführung nur in `--apply` aus
    `pre_merge_head`/`base_commit`, nie aus `MERGE_HEAD`; unaufgelöste Konfliktfassung wird nie geladen.
    Dazu: Hooks fanden den Windows-Store-Platzhalter `python3` und fielen still aus → Interpreter per Probe.
  - R4 ALLOW; Restpunkt selbst behoben: `_remove_paths` löscht nur sichere relative Pfade im Projekt
    (Beleg: `''`, `.`, `../x`, absoluter Pfad übersprungen, nur `weg.txt` gelöscht), `except Exception` beim
    statischen Lesen.
- B44 (Wunsch): Python 3.9+ als Voraussetzung in beiden READMEs, Prüf-Hook ohne Python.
- B45 (Wunsch): Pfade außerhalb des Projekts plattformgerecht, Regel in `AGENTS.md`/`CLAUDE.md` § 4.
- Neue Regeln in `regeln.md`: nie Code aus geholtem Ref ausführen; Hook-Interpreter per Probe; plattformgerechte Pfade.
- Neu im Backlog: B46 (Latenz der Probe), B47 (Hooks laufen auf ungeprüfter Merge-Fassung).
- Belege: py_compile aller geänderten Scripte, `check-refs.py` 0 tote Verweise, `create-project.py --check` ok,
  `settings.json` gültig, Smoketests je Punkt in Wegwerf-Repos (Scratchpad).

### Feedback abgeholt (dritter Abruf)

- Freigabe per `/act-process-feedback`: 2 Sendungen abgeholt und quittiert (0 wartend), 1 Projekt.
- Neu nur die zwei Direktmeldungen; die übrigen 8 Einträge waren schon als B36–B42 verbucht.
- `B43` (hoch): fehlender `import time` in `files-lib.py`, `sync-config.py --apply` bricht ab — am Code bestätigt.
- Ablage der Sendeprotokolle: Dublette zu `B39`, dort als bestätigt ergänzt. Nichts verworfen.

### Backlog als Themen-Tabellen, `/act` per Hook, Feedback-Einträge als eine Datei

- **Backlog neu formatiert** (Wunsch Wolfgang): 6 Themen-Tabellen `| [ ] | Nr | Prio | Titel | Info |`,
  offene nach Prio oben, erledigte unten je Tabelle; lange Texte unter `## Details` mit Sprungmarke. Entwurf
  per `builder` im Scratchpad, geprüft: B1–B42 je genau einmal, alle Zeilen des Wortlauts in B32 unverändert,
  Schlüsselbegriffe vorhanden; Entscheidungs-Nummern des Testprojekts aus einer Info-Zelle genommen (tote
  Verweise). `check-refs.py` kennt die neue Zeilenform (`_BACKLOG_STATUS_ROW_RE`). Beleg: 0 tot.
- **`/act`:** Skill plus `act-help.py` (liest das Frontmatter aller Skills, `argument-hint` für `act-feedback`
  ergänzt). Interaktiv dachte das Modell bei `/act` lange nach → `UserPromptSubmit`-Hook `act-help.py --hook`
  blockt genau `/act [name]` und zeigt die Liste als Grund. Beleg `claude -p '/act'` in Wegwerf-Kopie:
  0 Runden, 0 $. Interaktiv ungeprüft → Q18. Commits `568b1a8`, `0be54df`.
- **Kurz-Befehle:** interaktiv „Unknown command: /idea" — unbekannte Befehle erreichen weder Modell noch Hook
  (nur `-p` reicht sie durch). Weiterleitungs-Skills als Lösung → Q17.
- **Feedback-Einträge** (Wunsch Wolfgang, Teil von B39): eine `.md` mit YAML-Front-Matter statt `.md`+`.json`,
  Lesen akzeptiert beide Formate, Status beim Versand (`builder`). Beleg: Probe in Wegwerf-Kopie (neuer Eintrag,
  Altpaar daneben = 2, `_nach_sent` setzt Status, Sonderzeichen-Rundweg) plus eigene Stichprobe mit zwei echten
  Altpaaren aus `bandliste` (kopiert, nur gelesen): 3 wartend, `README.md` kein Eintrag. Dazu aus `bandliste`
  übernommen: `template_basis` als kurzer Hash.
- **Nicht gepusht** (keine Freigabe): offene Commits seit `70b0af0` → Q16. Danach PC per `shutdown /s /t 300`
  heruntergefahren, wie beauftragt.

### Erste Rückmeldungen abgeholt, Skills bekommen das Präfix `act-`

- **Freigabe:** Wolfgang hat am 2026-09-17 beauftragt, das Feedback abzuholen und zu verarbeiten; das
  schließt das Quittieren (Löschen auf dem Server) ein. `feedback-abholen.py --status`: 3 wartend →
  `--hole`: 3 geschrieben nach `.templatedev/daten/feedback/eingang/`, 3 quittiert, 0 wartend.
- **Inhalt:** 3 Meldungen aus 1 Projekt, 6 Punkte (4 Fehler, 2 Doku), keiner schon im Backlog. Neu
  formuliert als Backlog-Punkte 36–41 (halber Merge nach Update, verlorene `AI-CONFIG`-Schlüssel,
  zurückkehrende Setup-Abschnitte, Feedback-Ablage nach Versand, Fragenformat, Erläuterungen aus
  `AI-CONFIG`). Nichts verworfen. Arbeitsliste lokal: `daten/feedback/auswertung-2026-09-17.md`.
- **Anlass Präfix:** `/feedback` kollidiert mit dem eingebauten Claude-Code-Befehl. Alle 22 Skills heißen
  künftig `act-<name>`; `/act` listet dann alle Projekt-Befehle. Umbenennung läuft über einen `builder`.
- **Neu:** Skill `act-process-feedback` (Abholen, Einordnen, neu formuliert ins Backlog) — gehört nur zur
  Template-Pflege, muss in die `template_only`-Listen und zieht mit T5 nach `.templatedev/`.
- **Umbenennung erledigt** (`builder`): 22 Skill-Ordner per `git mv`, Verweise in 37 Dateien, davon 15 Scripte.
  Mitgefunden: `install-global.py` (`SKILL_ITEMS` mit nackten Namen) und der Prompt in
  `run-maintenance.ps1`/`.sh` hätten die Skills sonst nicht mehr gefunden. Übergang: Altnamen zusätzlich in
  `REMOVE_ITEMS`, `MAINTENANCE_REMOVE_PATHS`, `ABGEWAEHLT_SCHALTER_PATHS`. Beleg: `py_compile` ok,
  `check-refs.py` 0 tot, Wegwerf-Kopie: `create-project.py --dry-run`, `finish-setup.py --plan`,
  `install-global.py --plan` fehlerfrei; `apply-template.py --dry-run` kopiert 22 `act-`-Skills, nicht
  `act-process-feedback`. Rest: Warnung bei `create-project.py --check` → Backlog-Punkt 42.
- `act-process-feedback` in `TEMPLATE_ONLY_PATHS`, `DEFAULT_TEMPLATE_ONLY`, `template.json`, `EXCLUDE_GLOBS`.
- `feedback-abholen.py` zählt jetzt „Sendungen mit Einträgen" (3 Sendungen, 6 Einträge) — „3 Meldungen" las sich
  wie ein Verlust gegenüber 6 Dateien in `sent/` des Projekts.
- **Zweiter Abruf** (`/act-process-feedback`, erster Lauf des Skills): `--status` 1 wartend → `--hole`: 1 Sendung
  mit 2 Einträgen geschrieben, 1 quittiert, 0 wartend. 1 Projekt, beide Doku; beide gehören zur Feedback-Ablage
  und stehen als Ergänzung bei Backlog-Punkt 39, kein neuer Punkt, nichts verworfen.
- **Fehler dabei gefunden und behoben:** `--auswerten` überschrieb die Arbeitsliste desselben Tages samt
  Einordnung. Jetzt entsteht `auswertung-<datum>-2.md` usw.; Beleg: zweiter Lauf legte `-3` an, die
  eingeordnete Liste blieb unverändert (6 Einordnungen).

## 2026-09-16

### Ladeversuch: was Claude Code in einer Sitzung im Unterordner sieht

Anlass: Q7/T5 — Pflege-Sitzung in `.templatedev/` statt im Root. Wegwerf-Repo im Scratchpad, Root und
`.templatedev/` je mit CLAUDE.md (Erkennungstext), Agent, Skill und gleichnamigem Agent/Skill; `claude -p`
(2.1.273, Haiku) im Unterordner, Auswertung des `init`-Events und der Antworten. Kosten ~0,10 $.

| Was | Ergebnis |
| :--- | :--- |
| CLAUDE.md des Elternordners | beim Start geladen (`MARKER-root` und `MARKER-dev` zitiert) |
| `claudeMdExcludes` in `.templatedev/.claude/settings.json` | wirkt: nur noch `MARKER-dev` |
| Agenten des Elternordners | geladen (`agent-root` in der Liste); gleicher Name → Unterordner gewinnt (`gleich` → „dev") |
| Skills des Elternordners | geladen (`skill-root`); gleicher Name → einer in der Liste, Aufruf lieferte `SKILL-dev` |
| `settings.json`/SessionStart-Hook des Elternordners | nicht ausgeführt; Hook im Unterordner lief |

- Folge: Die Pflege-Sitzung erbt Agenten und Skills des Templates von selbst, überschreibt gleichnamig, und
  schließt nur die Platzhalter-CLAUDE.md aus. Q7 neu gefasst, Empfehlung a).
- Stolperstein Git Bash: `claude -p '/skill'` wird zu `C:/Program Files/Git/skill` umgeschrieben —
  `MSYS_NO_PATHCONV=1` davor.

### `.templatedev/` bekommt Aufgaben und Aufgaben-Archiv

- Wolfgang hat `.templatedev/tasks.md` angelegt (formlose Einträge, Tabu-Abschnitt wie `docs/ai/tasks.md`);
  dazu neu `.templatedev/tasks_archive.md` (Volltext, neueste oben, Nummern bleiben gültig).
- Verweise nachgezogen: `.templatedev/INDEX.md` (Tabelle, Sitzungsbeginn, Nummernregel), `AGENTS.md` und
  `CLAUDE.md` (template-only-Blöcke), `.github/README.md` § Mitarbeiten.
- `check-refs.py`: `T<n>`-Definitionen auch aus `.templatedev/tasks.md`/`tasks_archive.md`, wie bei `Q<n>`.
  Beleg: `python .claude/scripts/check-refs.py` → 49 Dateien, 47 Zitate, 0 tot.
- Wolfgangs drei Einträge als `T1`–`T3` nummeriert (Wortlaut bleibt stehen): Zugänge prüfen (T1) als
  Voraussetzung für PR/MR-Skill (T2) und Issue-/Story-Abläufe (T3). Alle drei sind Ideen im Sinne der
  Checkliste „Idee oder Änderungswunsch aufnehmen" — erst Konzept und Entscheidung, noch kein Code.

### Freigabe für Schreibzugriff auf `rufeger.de` (über die Sitzung `homeassistant`)

**Datierte Freigabe nach `AGENTS.md` § „Zugriff auf laufende Systeme":** Wolfgang hat am 2026-09-16
zugestimmt, dass die Claude-Code-Sitzung in `D:\dev\rufeger\homeassistant` — sie hat die Zugangsdaten und
SSH-Leserechte — den Feedback-Endpunkt auf `rufeger.de` **liest** und nach seiner ausdrücklichen Freigabe
in ihrer eigenen Shell auch **schreibt** (die Datei vor Ort aktualisieren, php-fpm neu laden). Die Freigabe
gilt für genau diesen Zweck und nicht für den nächsten ähnlichen Fall.

- Der Auftrag ist in drei Schritte geteilt: erst **nur lesen** und zurückmelden (wo liegt das ausgelieferte
  Verzeichnis wirklich, wie alt ist die `index.php`, wie steht OPcache), dann erst — nach Freigabe und nur
  wenn die Ursache feststeht — schreiben, mit Kopie der alten Datei als Rückweg.
- Beleg für „Upload angekommen" ist die Prüfsumme aus `?op=fassung`, nicht ein `202`.
- Ausdrücklich mitgegeben: **keine Geheimnisse in der Antwort** — der Inhalt der `feedback-endpunkt.config.php`
  wird weder ausgegeben noch zitiert, es genügt, ob und wo sie liegt.
- Zusätzlich angeregt (Wolfgang): einmal `fail2ban` ansehen. Anlass ist konkret — ich habe in der letzten
  Stunde rund 20 Anfragen an den Endpunkt geschickt, mehrere davon mit 403/401/400.

**Was daraufhin am Server geschah** (die Sitzung `homeassistant` hat gelesen und nach Wolfgangs Freigabe in
ihrer eigenen Shell geschrieben; alle Befunde von dort, keine Geheimnisse ausgetauscht):

- **Die Diagnose hat meinen Verdacht widerlegt.** Server, Pfad und OPcache waren in Ordnung
  (`validate_timestamps=On`, `revalidate_freq=2`, kein Symlink, kein Alias) — hochgeladen wurde schlicht
  dreimal eine ältere Kopie. Der Server-Stand (641 Zeilen) passte zu keiner Fassung im Repo, weder zum
  Commit (643) noch zum Arbeitsbaum (707). Lehre: Bevor man Serverkonfiguration verdächtigt, prüft man, ob
  das Hochgeladene überhaupt das ist, was man meint — genau dafür gibt es jetzt `?op=fassung`.
- **`.htaccess` im Endpunkt-Ordner angelegt:** `Require all denied` per Präfix-Muster auf
  `feedback-endpunkt.config.php` (deckt `.example`, `.bak`, `~`, `.save` mit ab) — die Datei liefert seitdem
  403 statt 200. Die andere Sitzung hat dabei die **bessere** Lösung gewählt als meine: 403 aus der
  Server-Regel gilt unabhängig davon, welche Fassung läuft, und hält auch dann, wenn PHP die Datei einmal
  nicht ausführt. Meine 404-Notbremse in der Vorlage bleibt als zweite Schicht, ersetzt sie aber nicht.
- **`Cache-Control` nachgezogen:** Die `.htaccess` der Domain setzte pauschal `public, max-age=86400` — das
  galt auch für `?op=inbox`, und darüber gehen die abgeholten Rückmeldungen im Klartext. Jetzt
  `Header always unset` + `set "no-store"` im Endpunkt-Ordner. Ein realer Fund der anderen Sitzung, den ich
  von außen nie gesehen hätte.
- **fail2ban wertet diese Domain nicht aus:** 19 Jails, aber keine für den Access-Log — rund 20 Sonden mit
  401/403/400/404, darunter `.env`, `*.bak` und ein Pfad-Traversal-Versuch, lösten nichts aus. Die 403 auf
  `.env`/`.bak` kamen von ModSecurity, nicht von einer eigenen Regel (Korrektur meiner früheren Aussage).
- **Kein Fehler, sondern Absicht:** Das Datenverzeichnis liegt eine Ebene über dem App-Ordner im
  Abo-Wurzelverzeichnis. Das sieht bei einer Inventur nach falschem relativem Pfad aus, ist aber der Zweck —
  außerhalb jedes Web-Roots. Von außen mit einer echten Meldungs-ID gegengeprüft: nicht erreichbar. Steht
  jetzt als Warnung in der Betriebsdoku, damit es niemand „aufräumt".
- **Endstand des Servers am 2026-09-16:** Fassung `2026-09-16.2` läuft (per `?op=fassung` bestätigt, nachdem
  vier Anläufe im Dunkeln getappt hatten), Konfigurationsdatei `403`, Endpunkt-Antworten `no-store`. Die
  Domain hat als globalen Standard `private, no-cache, must-revalidate` statt des früheren
  `public, max-age=86400` — für eine ganze Website die richtige Wahl, für diesen Ordner gilt zusätzlich die
  strengere Regel.
- **Versionsnummer nachgerüstet** (Kritik von Wolfgang, berechtigt): Die Datei war ausführlich kommentiert,
  aber man konnte ihr nicht ansehen, welcher Stand sie ist. `const FASSUNG` plus Kopfzeile, ausgegeben von
  `?op=fassung` neben Prüfsumme und Änderungszeit. Prüfsumme und Fassung ersetzen einander nicht: Die eine
  beweist, die andere sagt einem Menschen etwas.

### Der echte Endpunkt zeigt zwei Fehler, die kein Wegwerf-Test gefunden hätte

Wolfgang hat den Endpunkt ausgerollt. Der erste Lauf des echten Clients gegen `rufeger.de` förderte sofort
zwei Dinge zutage, die lokal gegen `php -S` nie auffallen konnten — **genau der Grund, warum `regeln.md`
verlangt, am echten Ziel zu prüfen.**

- **Der fehlende Schrägstrich hätte jeden Versand verschluckt.** Ohne ihn antwortet der Server mit `301` auf
  die Variante mit Schrägstrich, und `urllib` macht bei einer Weiterleitung aus dem `POST` ein `GET` — die
  Nutzlast ist weg, zurück kommt ein irreführendes `405`. Die eingebaute Adresse hatte genau diese Form.
  Behoben doppelt: `_endpoint()` hängt den Schrägstrich an, und der Sender **folgt keiner Weiterleitung**
  mehr, sondern meldet sie samt Zieladresse.
- **Unterpfade erreichen das Script nicht.** `…/agentic-coding-feedback/inbox` lieferte die Startseite der
  Domain aus (HTTP 200, HTML) — der Webserver reicht den Unterpfad nicht weiter. `feedback-abholen.py`
  spricht den Endpunkt jetzt über `?op=inbox` an; das funktioniert mit und ohne `PATH_INFO`.
- **Live belegt:** `--direkt` gegen den echten Endpunkt -> HTTP 202, anonym, ohne Projekt-Kennung.
- **Offen beim Betrieb:** Auf dem Server liegt noch die Fassung von vor der Herkunftsprüfung — eine Meldung
  ohne `herkunft` wurde mit 202 angenommen statt mit 403 abgewiesen. Datei neu hochladen. In der Ablage
  liegen zwei Datensätze aus diesen Proben, beide beim ersten Abholen verwerfen.
- **Regel daraus, schon in `.templatedev/scripts/README.md`:** Ein `202` sagt nur, dass *irgendeine* Fassung
  läuft. Welche, zeigt eine Meldung ohne `herkunft`.

**Nach dem Austausch der Datei: neue Fassung bestätigt, dritter Befund.** Proben gegen den echten Endpunkt:
ohne `herkunft` **403**, mit falscher **403**, Handnachricht ohne Text **400**, vollständige Meldung **202**.
In die Testmeldung habe ich absichtlich Müll gemischt (erfundenes Kennzahlenfeld, unbekannter Schalter,
Eintrag mit erfundener `art`) — beim Abholen darf davon nichts auftauchen, das ist der Beweis, dass der
Endpunkt die Nutzlast neu aufbaut statt sie durchzureichen.

- **Dritter Befund: der `Authorization`-Header kam bei PHP nicht an** („kein Token", obwohl das Geheimnis
  stimmte). Apache reicht ihn ohne `CGIPassAuth On` nicht an FastCGI weiter. Statt die Serverkonfiguration
  zur Voraussetzung zu machen, sucht `bearer_kopf()` das Token auf vier Wegen — `HTTP_AUTHORIZATION`, die
  `REDIRECT_`-Variante, `apache_request_headers()` und zuletzt einen eigenen Header `X-Feedback-Auth`, den
  kein Server anfasst. Das Abholskript schickt beide Header.
- **Das Geheimnis liegt in der `.env`** — und genau das sah das Script nicht, weil es nur die Prozessumgebung
  las (dieselbe Falle wie bei den MCP-Servern, `CLAUDE.md` § 4). `feedback-abholen.py` liest die `.env` jetzt
  selbst; die Prozessumgebung behält Vorrang.
- Vorab lokal belegt, bevor die Datei zum dritten Mal hochging: ohne Header 401, nur `Authorization` 200,
  **nur `X-Feedback-Auth` 200**, gefälschte Signatur 401 — der Transportweg ist egal, die Prüfung bleibt scharf.

**Die Kette ist vollständig belegt (2026-09-16).** Nach dem dritten Upload: `--status` meldet 3 wartende
Meldungen, `--hole --kein-ack` holt sie, `--hole` quittiert, der Server ist danach leer.

- **Der Filter des Endpunkts ist am echten Ziel bewiesen.** In die Testmeldung war Müll gemischt: ein
  erfundenes Kennzahlenfeld, ein unbekannter Schalter, ein Eintrag mit erfundener `art`. **Nichts davon ist
  in der Ablage angekommen**, alles Legitime vollständig. Der Endpunkt baut die Nutzlast neu auf, statt sie
  durchzureichen — genau das war der Entwurfsgedanke, jetzt ist er kein Vorsatz mehr, sondern belegt.
- **Vierter Befund, kosmetisch aber lästig:** PHP macht aus einer leeren Gruppe in JSON `[]` statt `{}` —
  die Auswertung bekäme mal eine Liste, mal ein Objekt. Leere Gruppen werden jetzt weggelassen (`schalter`
  und `mcp_server` mit eingereiht). Geht beim nächsten Upload mit, eilt nicht.
- **Die Ähnlichkeitserkennung hat sich an echten Daten bewährt:** Sie hat die beiden Testmeldungen als
  verwandt erkannt (38 %, projektübergreifend) — inhaltlich richtig, beide sagen dasselbe in anderen Worten.
- Testdaten danach aus dem lokalen Eingang entfernt; der Server ist leer, die Ablage wieder sauber.

**`Q4` beantwortet und umgesetzt: `setup-lib.py` ist aufgeteilt.** Aus 2525 Zeilen wurden vier Dateien —
`config-lib.py` (761, alles rund um `AI-CONFIG.md`), `files-lib.py` (642, Datei-/Pfadoperationen),
`claudemd-lib.py` (208, Textchirurgie an `CLAUDE.md`) und `setup-lib.py` (1047, Ablauf **plus Fassade**).
Die Fassade hebt alle Namen der drei Module in den eigenen Namensraum, damit die zehn importierenden
Scripte unverändert `cp.<name>` benutzen können.

- Belegt, und zwar unabhängig vom Sub-Agenten nachgeprüft: **AST-Vergleich gegen `HEAD`** zeigt 132 alte
  Definitionen, alle 132 sind noch da (jetzt 147, der Rest ist die heutige Arbeit plus Split-Helfer);
  Fassade 43/43 Namen; **alle acht Einstiegspunkte** der Importeure laufen mit Exit 0; ein echter
  `create-project.py --dry-run` liefert den vollständigen Plan inklusive der neuen `Feedback-Umfang`-Zeilen;
  `--check` meldet „alle gelisteten Pfade vorhanden". Der Sub-Agent selbst hatte zusätzlich die Ausgabe von
  `--dry-run` vor und nach dem Split verglichen: identisch.
- **Abweichung, die der Sub-Agent gemeldet statt kaschiert hat:** `_remove_table_row` sollte laut Auftrag
  nach `claudemd-lib.py`, wird aber nur von `remove_tool_files` gebraucht — der Weg dorthin hätte einen
  echten Import-Ring erzeugt. Es blieb bei seinem einzigen Aufrufer, vermerkt im Kopfkommentar. Richtige
  Entscheidung; die Auftragsbeschreibung war an der Stelle zu grob.
- Die Pfadlisten-Tabelle in `regeln.md` ist nachgezogen: Die Konstanten liegen jetzt in `config-lib.py` bzw.
  `files-lib.py`, `setup-lib.py` bleibt nur der Weg dorthin.

## 2026-09-15 — Feedback-Endpunkt live, Lesbarkeit, Worktree-Frage, Backlog 30–32, Safeguard-Blockade

- Feedback-Öffentlichkeit geklärt: Issue-Weg bleibt verworfen (Konzept korrigiert, Grund ergänzt); Sendeprotokoll
  `docs/ai/template-feedback/` wird bei `feedback.py --enable --protokoll lokal` per `.gitignore` lokal gehalten,
  `/finalize` fragt die Einwilligung ab.
- Gegenstelle gebaut: `.templatedev/scripts/feedback-endpunkt.php` (Deckel 32 KB, 20 Einträge, Ratenbegrenzung
  30/h je IP, 24/Tag je Projekt, Ablage außerhalb Web-Root, JWT-Ausgabe) und `.templatedev/scripts/feedback-abholen.py`
  (Token, Abholen, Quittieren); fremde Meldungen gitignored, am laufenden `php -S`-Server belegt (202/400/401,
  Pfad-Traversal abgewiesen, unbekannte Felder verworfen).
- Zwei Lesbarkeitskorrekturen Wolfgangs: Stufenschreibweise `<` statt Komma (`Testtiefe`, `Logging-Tiefe`);
  Rückweg für „`aus` entfernt Ordner" ergänzt (CLAUDE.md-Verweise kamen sonst nicht zurück), Auflage „nie löschen,
  was nicht anderswo liegt" für `MAINTENANCE_REMOVE_PATHS` — Technik wie `rename-lib.py` (`B10`).
- Worktree-Frage verneint (trennt Platte, nicht Absicht) → neue Regeln in `checklists.md` § Delegation,
  `CLAUDE.md` § 1, `coding_rules.md` § Dateigröße; `setup-lib.py` (2461 Zeilen) als eigener Fall in `Q4`
  (Empfehlung, unbeantwortet).
- `Backlog 30` (Löschschutz) umgesetzt: `ungesicherte_pfade()` prüft `git status --porcelain --ignored`, drei
  Löschfunktionen respektieren `schutz=True`; Fund: komplett ignorierte Ordner erscheinen als ein Eintrag mit
  Schrägstrich, Präfix-Abgleich nötig.
- `Backlog 31` umgesetzt: `update-template.py` leitet abgewählte Pfade aus `applied_config` ab statt aus einer
  eigenen Liste — Wartung/Code-Optimierung `aus`, gestrichene KI-Werkzeuge kommen bei einem Update nicht zurück.
- `Backlog 32` begonnen (7-Aufgaben-Schnitt), Scheiben 1–7 umgesetzt: Schalter `Feedback-Umfang`/`Feedback-Takt:
  adaptiv`; Handkanal `/feedback <Text>` immer möglich (auch bei `aus`, dann ohne Projekt-Kennung); Ablage je
  Projekt/anonym mit Dublettenerkennung (Stammform-Überlappung, Schwelle 40 %); Herkunftskennung
  `agentic-coding-template/1`; Erhebung nach Umfang a/b/c aus `git log`; neue Ablage
  `docs/ai/template-feedback/<datum>-<thema>.md`+`.json` statt `.claude/feedback-outbox.json`; Fragebogen
  `feedback.md` + adaptiver Hook (fällig ab 5 Commit-Tagen, Mindestabstand 48 h).
- Ab Sitzungsmitte blockierte eine Sicherheitsprüfung jede schreibende Aktion (kein Sub-Agent abgebrochen,
  Wortlaut „reagiert auf früheren Gesprächsverlauf"); Ursache nicht sicher geklärt (Verdacht: PowerShell-Deny-Regel),
  behoben nach deren Entfernung über `Edit` statt `Bash`; neue Regeln in `AGENTS.md` § „Umgang mit
  Sicherheits-/Safeguard-Warnungen" (zwei Fälle unterscheiden, kein Geheimnis auf der Kommandozeile, kein
  `rm -rf` aus der Shell, mechanische Formulierung, Häufung vermeiden, jede Blockade protokollieren).

## 2026-09-14 — Rufname, Feedback-Konfiguration, neue Schalter/Skills, Formbefunde aus bandliste, Ablage endgültig in `.templatedev/`

- Rufname-Regeln geschärft: `AGENTS.md` § Rollen — Anrede „Orchestrator"/„du" bleibt gültig, Nennen einer
  Worker-Rolle ist Auftrag an den Orchestrator, kein Direktkanal zum Worker. Rufname wird künftig vom erkannten
  Werkzeug/Modell abgeleitet (leere Zelle in `AI-CONFIG.md` = Kurzname dessen, was arbeitet), Fallback „Fable"
  nur wenn nichts erkannt wird.
- Feedback-Konzept dreimal nachgeschärft: `AI-CONFIG.md`-Schlüssel `Feedback`/`Feedback-Takt` doch eingeführt
  (dreht `Q3` um), Nachweis läuft über versioniertes Protokoll statt Vorab-Bestätigung, Wochensperre,
  MCP-Whitelist, Links aus `resources.md` teilbar außer Abschnitt „Private Links", Client am echten
  Testempfänger belegt (HTTP 202).
- Vier gewünschte AI-CONFIG-Schalter: `Ideen-Ablauf`, `Testtiefe`, `Schreibstil` gebaut; `Feedback` selbst
  zunächst nicht direkt gebaut, sondern als Konzept mit Optionen (`konzept-feedback.md`, `Q1`–`Q3`,
  Backlog-Punkt `B29`) — erster Einsatz der neuen Ideen-Checkliste am Template selbst.
- Idee-zu-Backlog-Ablauf ausformuliert: Skill `/idea`, Prio als Mittelwert aus beiden Einschätzungen
  (`⌀ 3,5 (4/3)`), Begründungspflicht bei Abweichung über eine Stufe, Backlog-Tabelle um `Zeitpunkt` erweitert.
- „Rasen mähen": Checkliste „Block vorbereiten" + Skill `/prepare` — Startklar-Kriterien, ein gebündelter
  Fragenblock, unbeaufsichtigter Lauf hält bei blockiertem Rest an, Abwesenheit ist keine Freigabe.
- Werkzeugerkennung (`detect_ai_tool`, `--detect`) und Warnung, wenn das laufende Werkzeug nicht in
  `KI-Werkzeuge` steht; Anlegen fragt jetzt „leeres Projekt?" statt zu raten — dabei `B28` gefunden (dritte
  widersprüchliche Stelle zu `no_replace`).
- Skill `/slides` (Marp) statt PowerPoint-MCP (Office-Zwang bzw. archiviert); MCP-/Skill-Quellen ausgewertet →
  `kubernetes`, `firecrawl` neu, Skill `/a11y` neu, Superpowers/Spartan/Code Simplifier/Stack-Spezifisches
  verworfen.
- Sechs Formbefunde aus `bandliste` behoben (README-Formregeln vereinheitlicht, „Backlog" statt „Umbauliste",
  Board-Abschnitte geschärft, Ledger-Überschriften mit Uhrzeit, `docs/project/konzepte/`+`stories/` neu) plus
  Statuszeilen-Nachzug; Kürzel vereinheitlicht `A→T`/`F→Q` (Commit `4da3c11`), Verlinken der Kürzel versucht und
  wieder verworfen (fehlende Anker); Ablage der Template-Entwicklung endgültig zurück nach `.templatedev/`,
  versioniert (nach Zwischenstation als eigenes Projekt, Stand `d4a304b`, `Umbaupunkt B22` als Übernahme aus
  `bandliste`), Übernahme der Punkte `B1`–`B21` aus der alten Umbauliste.

## 2026-09-13 — Erster Fremdeinsatz, AI-CONFIG laufend, Quellensammlung, 13 Umbaupunkte

- Erster Einsatz an einem Fremdprojekt (`bandliste`, Nuxt 4 + Prisma, 107 Dateien + 49.000 Alt-PHP-Dateien)
  deckte zwei Fehler auf, die am eigenen Repo nie auffielen: `B17`, und der teuerste Fund `B18`
  (`.junie/guidelines.md` mit 110 Zeilen projekteigener Regeln, von `migrate-project.py --plan` übersehen —
  Kandidatenliste um weitere Fremd-Werkzeug-Ablagen ergänzt).
- `B19`: Trennung von Einrichtungs-CLI und Bibliothek (`setup-lib.py`/`rename-lib.py` bleiben,
  `create-project.py`/`migrate-project.py` verschwinden erst nach `/finalize`, `setup_complete`-Guard) — der
  Abschluss bewusst kein Automatismus, sondern Skill-Nachfrage plus SessionStart-Hook-Erinnerung.
- End-to-End-Smoketest über beide Wege fand einen weiteren Fehler (`no_replace` in `template.json` mit alten
  Dateinamen). Nachtrag am selben Abend (Commit `e59a697`): `.mcp.json`-`${VAR}` löst nur aus der
  Prozessumgebung auf, keine `.env` — `CLAUDE.md` § MCP korrigiert, drei Wege in fester Reihenfolge.
- Sechs Sub-Agenten, vier davon parallel auf disjunkten Dateien (Zuschnitt nach Datei, nicht Thema) — als
  Vorbild für spätere Delegationsregeln festgehalten.
- `AI-CONFIG.md` wirkt jetzt laufend (`sync-config.py` gleicht gegen `applied_config` ab), neues
  Fünf-Tabellen-Format nach Thema. Lehre aus einem entgleisten Lauf (36 Min., 335.000 Token wegen zu großem,
  dreimal nachgebessertem Auftrag) → Richtwerte/Eingriffswege in Checkliste „Delegation", Kostenargument in
  `AGENTS.md`, Meldepflicht in der Builder-Rolle.
- `docs/ai/resources.md` neu (40 geprüfte Links), `AGENTS.md` § „Worker starten" je Werkzeug,
  `install-global.py` für Rollen/Skills nach `~/.claude/`. Wichtigster Fund: Claude Code liest nur `CLAUDE.md`,
  nie `AGENTS.md` — `@AGENTS.md`-Import als erste Zeile ergänzt (Commits `a8c50d5`, `2d0e72d`).
- Dreizehn Punkte der Umbauliste abgearbeitet (vier parallele Läufe je Script): `B1` größer als geplant
  (feldweiser Merge von `template.json` auch ohne Git-Konflikt, `save_template_json` erhält unbekannte Felder),
  `B11` (Rufname-Ersetzung lässt Code-Blöcke/URLs aus), `B10` (gitignorierte Dateien per `git check-ignore` von
  Verschiebung ausgenommen).
- `B2` und `B7` bewusst offen gelassen (keine Freigabe). Beleg: `py_compile` über sieben Scripte,
  JSON-Prüfung, End-to-End-Smoketest über alle vier Scripte in Temp-Repos.

## 2026-09-12 — Template-Entwicklung aus `docs/ai/` herausgelöst
- Die 15 Punkte der Umbauliste standen bis dahin in `docs/ai/backlog.md` und wären damit in jedes abgeleitete
  Projekt gewandert. `docs/ai/backlog.md` ist wieder eine leere Vorlage; die Inhalte stehen hier.
- Vorher in dieser Sitzung entstanden: Logging, Template-Updates per Merge, zwei Wege hinein (heute `/create-project`
  und `/apply-template`), Opus als Orchestrator-Default, `expert-solver`, optionale Wartung, Struktur-Migration
  für nachgerüstete Projekte, optionale Code-Analyse, `optimizer`, Guideline-Bausteine.
