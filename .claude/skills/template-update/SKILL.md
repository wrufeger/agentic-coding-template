---
name: template-update
description: Checkliste Template-Update - Änderungen des Templates per Merge einspielen, Platzhalterwerte bleiben erhalten.
---

# Template-Update (nur Hauptkontext)

Setzt die werkzeugneutrale Checkliste „Template-Update" aus `docs/ai/checklists.md` um, mit der Mechanik von
`.claude/scripts/template-update.py`. Läuft im Hauptkontext, da mögliche Merge-Konflikte Entscheidungen mit
{{AUFTRAGGEBER}} brauchen und nur der Orchestrator committet.

## Ablauf

1. `python .claude/scripts/template-update.py --check` ausführen; Zusammenfassung an {{AUFTRAGGEBER}}
   (Anzahl Commits, geänderte Dateien, welche davon `(keep_local)` markiert sind).
2. Sauberer Arbeitsbaum prüfen (`git status`) — sonst zuerst die laufende Aufgabe abschließen (Skill `/commit`).
3. `python .claude/scripts/template-update.py --apply` ausführen.
4. **Bei Exit 4 (Konflikte offen): inhaltlich zusammenführen, nicht eine Seite wegwerfen.**
   `python .claude/scripts/template-update.py --conflicts` liefert je Konflikt die Art, die geltende
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

   Umstrukturierte Projekte brauchen mehr als eine Datei-zu-Datei-Zuordnung: Hat das Projekt Inhalte auf andere
   Dateien verteilt oder zusammengezogen, gehört die Template-Änderung dorthin, wo das Thema im Projekt
   tatsächlich steht — und nicht in eine wiederbelebte Datei nach Template-Schema. Im Zweifel {{AUFTRAGGEBER}}
   fragen, statt eine Struktur zurückzudrehen, für die es einen Grund gab.

   `.claude/template.json` und die `keep_local`-Pfade mit gewöhnlichem Konflikt hat das Script bereits
   zugunsten der Projektfassung gelöst; offen bleiben genau die Fälle, die eine Entscheidung brauchen. Nach dem
   Auflösen jeweils `git add <pfad>` (bzw. `git rm` für bewusst Gelöschtes), dann
   `python .claude/scripts/template-update.py --continue` ausführen.
5. Prüfen: `grep -rn "{{" .` (nur die Scripte in `.claude/scripts/` sind unbedenklich — `no_replace` —,
   alles andere klären),
   `python -m json.tool .claude/settings.json`, `python .claude/scripts/ai-log.py --status`.
6. Commit per Pathspec nach Freigabe von {{AUFTRAGGEBER}} (oder `--commit` bei Schritt 3/4, wenn die
   Freigabe vorab erteilt wurde).
7. `docs/ai/ledger.md`-Zeile mit Basis-Commit-Wechsel und Anzahl Commits.

## Wann NICHT

Bei laufender Feature-Welle mit uncommitteten Änderungen — erst abschließen (Checkliste
„Aufgabe abschließen"), dann Template-Update.

## Abbrechen

`python .claude/scripts/template-update.py --abort` bricht einen laufenden Merge ab, ohne
`.claude/template.json` zu verändern.
