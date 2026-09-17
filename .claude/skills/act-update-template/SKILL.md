---
name: act-update-template
description: Checkliste Template-Update - Änderungen des Templates per Merge einspielen, Platzhalterwerte bleiben erhalten.
---

# Template-Update (nur Hauptkontext)

Setzt die werkzeugneutrale Checkliste „Template-Update" aus `docs/ai/checklists.md` um, mit der Mechanik von
`.claude/scripts/update-template.py`. Läuft im Hauptkontext, da mögliche Merge-Konflikte Entscheidungen mit
{{AUFTRAGGEBER}} brauchen und nur der Orchestrator committet.

## Ablauf

1. `python .claude/scripts/update-template.py --check` ausführen; Zusammenfassung an {{AUFTRAGGEBER}}
   (Anzahl Commits, geänderte Dateien, welche davon `(keep_local)` markiert sind).
2. Sauberer Arbeitsbaum prüfen (`git status`) — sonst zuerst die laufende Aufgabe abschließen (Skill `/commit`).
3. `python .claude/scripts/update-template.py --apply` ausführen.
4. **Bei Exit 4 (Konflikte offen): inhaltlich zusammenführen, nicht eine Seite wegwerfen.**
   `python .claude/scripts/update-template.py --conflicts` liefert je Konflikt die Art, die geltende
   Prioritätsregel, den Umfang beider Änderungen, mögliche Umbenennungen und die Befehle, mit denen sich beide
   Fassungen ansehen lassen (`git show <ref>:<pfad>`, `git show HEAD:<pfad>`).

   Vorgehen je Konflikt — **immer beide Fassungen lesen, bevor entschieden wird**:
   - **Beide Seiten haben geändert.** Die Absicht hinter jeder Änderung erkennen und beide umsetzen. Eine neue
     Template-Regel und eine projektspezifische Ergänzung schließen sich fast nie aus: Die Template-Fassung
     bildet das Gerüst, die Projektzeilen (echte Werte, eigener Stack, `AI_LOG`-Schalter, zusätzliche Agenten
     oder Skills) werden hineingezogen. Nur wenn sich zwei Regeln inhaltlich widersprechen, gilt die Priorität
     aus der Regel-Spalte — und der verworfene Teil wird im Ledger genannt.
   - **Vom Projekt gelöscht, im Template geändert.** Zuerst prüfen, ob die Datei im Projekt unter einem anderen
     Namen weiterlebt — `--conflicts` zeigt Umbenennungs-Kandidaten mit Ähnlichkeitswert, und eine
     umstrukturierte `docs/ai/` ist der Normalfall. Wenn ja: die Template-Änderung **in die neue Datei**
     einarbeiten, die alte bleibt gelöscht (`git rm`). Wenn die Datei wirklich bewusst entfernt wurde (etwa
     abgewählte Wartung): gelöscht lassen. Diesen Fall legt das Script dir immer vor, sobald es einen
     Umbenennungs-Kandidaten findet — nur ohne Kandidat **und** bei einem `keep_local`-Pfad entscheidet es
     selbst auf „gelöscht lassen".
   - **Umbenannt auf beiden Seiten** (`AU`/`UA`, beide haben dieselbe Datei woanders hin verschoben): beide
     Zielpfade ansehen, Inhalte in den Projektpfad zusammenführen, den Template-Pfad entfernen. Für diesen Fall
     liefert `--conflicts` noch keinen Umbenennungs-Hinweis — die Zuordnung ergibt sich aus den Pfadnamen.
   - **Von beiden neu angelegt.** Beide Fassungen zusammenführen, die Template-Struktur als Grundlage nehmen.
   - **Weiterleitungs-Skills** (`.claude/skills/commit`, `idea`, `prepare`, `update-template` — alte
     Vollfassungen von vor der `act-`-Umbenennung, heute reine Verweise auf `act-<name>/SKILL.md`): hier
     gewinnt immer die Template-Seite, unabhängig von der Konfliktart — das Script löst das automatisch auf.
     War die Projektfassung gegenüber der gemeinsamen Basis lokal verändert, meldet die Ausgabe das
     zusätzlich als **WARNUNG** samt Rückweg zur alten Fassung (`git show HEAD:<Pfad>`, nach dem Commit
     stattdessen `git show ORIG_HEAD:<Pfad>`) — dann prüfen, ob diese Änderung noch woanders gebraucht wird.

   Umstrukturierte Projekte brauchen mehr als eine Datei-zu-Datei-Zuordnung: Hat das Projekt Inhalte auf andere
   Dateien verteilt oder zusammengezogen, gehört die Template-Änderung dorthin, wo das Thema im Projekt
   tatsächlich steht — und nicht in eine wiederbelebte Datei nach Template-Schema. Im Zweifel {{AUFTRAGGEBER}}
   fragen, statt eine Struktur zurückzudrehen, für die es einen Grund gab.

   `docs/ai/resources.md` ist der umgekehrte Fall: Die Quellensammlung pflegt das Template, nur der Abschnitt
   „Eigene Quellen dieses Projekts“ am Dateiende gehört dem Projekt. Bei einem Konflikt dort also die
   Template-Fassung nehmen und den eigenen Abschnitt anhängen.

   `.claude/template.json` und die `keep_local`-Pfade mit gewöhnlichem Konflikt hat das Script bereits
   zugunsten der Projektfassung gelöst; offen bleiben genau die Fälle, die eine Entscheidung brauchen. Nach dem
   Auflösen jeweils `git add <pfad>` (bzw. `git rm` für bewusst Gelöschtes), dann
   `python .claude/scripts/update-template.py --continue` ausführen.

   **Bei einer bereits abgeschlossenen Einrichtung** (`setup_complete` in `.claude/template.json`) hat das
   Script zusätzlich die Template-Seite der Abschnitte verworfen, die `/act-finalize` aus diesem Projekt
   entfernt hat — Einrichtungs-Scripte/-Skill-Ordner, die Checklisten-Abschnitte „Neues Projekt"/„Projekt
   nachrüsten"/„Einrichtung abschließen" und die `template-only`-Blöcke in `AGENTS.md`/`CLAUDE.md` — und
   meldet das als eigene Zeile(n). Ein danach noch gemeldeter Restkonflikt in `AGENTS.md`, `CLAUDE.md` oder
   `docs/ai/checklists.md` betrifft echten Inhalt außerhalb dieser Abschnitte und braucht wie jeder andere
   Konflikt eine inhaltliche Entscheidung.
5. Prüfen: `grep -rn "{{" .` (nur die Scripte in `.claude/scripts/` sind unbedenklich — `no_replace` —,
   alles andere klären),
   `python -m json.tool .claude/settings.json`, `python .claude/scripts/ai-log.py --status`.
   `--apply`/`--continue` ergänzen dabei automatisch fehlende Zeilen in `AI-CONFIG.md` (steht in `keep_local`,
   wird sonst nie mitgemergt) und melden das; ganze fehlende Tabellen werden nur gemeldet, nicht angelegt.
   Meldet die Ausgabe stattdessen Konfliktmarker in `AI-CONFIG.md`, den Konflikt zuerst wirklich auflösen,
   dann `python .claude/scripts/sync-config.py --apply` nachholen.
6. **Nie als halber Merge liegen lassen.** Sobald keine Konflikte mehr offen sind, sofort committen
   (Pathspec, nach Freigabe von {{AUFTRAGGEBER}} — oder `--commit` bei Schritt 3/4, wenn die Freigabe vorab
   erteilt wurde) **oder** {{AUFTRAGGEBER}} ausdrücklich fragen, ob der Merge bewusst offen bleiben soll
   (z. B. um ihn selbst zu prüfen). Ohne eine der beiden Antworten endet dieser Skill nicht — ein gestagter,
   nie committeter Merge fällt sonst erst beim nächsten Sitzungsstart auf (`--check`/`--status` warnen dann,
   aber das ist der Notnagel, nicht der Normalfall).
7. `docs/ai/ledger.md`-Zeile mit Basis-Commit-Wechsel und Anzahl Commits.
8. Fiel bei diesem Update ein Fehler der Vorlage selbst auf (falsch eingespielte oder fehlende Datei,
   doppelter Abschnitt, unwirksame Regel/Mechanik): sofort als Eintrag anlegen — Sofort-Auslöser in
   `.claude/skills/act-feedback/SKILL.md`, Regel in `AGENTS.md` § „Freiwillige Rückmeldung an den
   Template-Autor".

## Wann NICHT

Bei laufender Feature-Welle mit uncommitteten Änderungen — erst abschließen (Checkliste
„Aufgabe abschließen"), dann Template-Update.

## Ein bereits offener Merge

Meldet `--check` oder `--status` eine Warnung zu `MERGE_HEAD` (Merge vom Template-Remote, noch nicht
committet — auch von einer vorigen, abgebrochenen Sitzung), zuerst `--status` ansehen: keine Konflikte mehr
offen heißt nur der Commit fehlt (Schritt 6 hier oben nachholen), offene Konflikte heißen bei Schritt 4
weitermachen (`--conflicts`, dann `--continue`).

## Abbrechen

`python .claude/scripts/update-template.py --abort` bricht einen laufenden Merge ab, ohne
`.claude/template.json` zu verändern.
