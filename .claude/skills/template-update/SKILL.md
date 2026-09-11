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
2. Sauberer Arbeitsbaum prüfen (`git status`) — sonst zuerst Checkliste „Sitzungsabschluss" ausführen.
3. `python .claude/scripts/template-update.py --apply` ausführen.
4. Bei Exit 4 (Konflikte offen): Konflikte von Hand auflösen. Regel: in `.claude/**`, `AGENTS.md`,
   `CLAUDE.md`, `docs/ai/checklists.md`, `docs/ai/README.md` gewinnt die Template-Logik; projektspezifische
   Zeilen (echte Werte, projektspezifische Regeln wie der `AI_LOG`-Schalter, Stack-Ergänzungen) bleiben —
   beide Seiten zusammenführen, nie blind eine Seite nehmen. `.claude/template.json` selbst und
   `keep_local`-Pfade hat das Script bereits automatisch zugunsten der Projektfassung gelöst. Danach
   `python .claude/scripts/template-update.py --continue` ausführen.
5. Prüfen: `grep -rn "{{" .` (nur bekannte Fundstellen in `.claude/skills/new-project/SKILL.md`,
   `docs/ai/checklists.md`, `.claude/scripts/` und diese Datei sind unbedenklich, alles andere klären),
   `python -m json.tool .claude/settings.json`, `python .claude/scripts/ai-log.py --status`.
6. Commit per Pathspec nach Freigabe von {{AUFTRAGGEBER}} (oder `--commit` bei Schritt 3/4, wenn die
   Freigabe vorab erteilt wurde).
7. `docs/ai/ledger.md`-Zeile mit Basis-Commit-Wechsel und Anzahl Commits.

## Wann NICHT

Bei laufender Feature-Welle mit uncommitteten Änderungen — erst abschließen (Checkliste
„Sitzungsabschluss"), dann Template-Update.

## Abbrechen

`python .claude/scripts/template-update.py --abort` bricht einen laufenden Merge ab, ohne
`.claude/template.json` zu verändern.
