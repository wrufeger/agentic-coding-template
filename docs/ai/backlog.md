> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# Umbauliste — Vorschläge des Orchestrators

Priorisierte Verbesserungsvorschläge (Sicherheit zuerst). {{AUFTRAGGEBER}} entscheidet — Marker direkt am
Punkt (z. B. „-> machen", „-> später", „-> nein, weil …").

Grundsatz: der bestehende Codestil/die bestehenden Muster bleiben erhalten, solange sie kein echtes Problem
verursachen. Vorschläge hier sind Angebote, keine Aufträge — Umsetzung erst nach Freigabe in `tasks.md`.

---

1. **`.claude/template.json` strukturell mergen** (Priorität mittel): Bei Konflikten gewinnt heute immer die
   Projektfassung der ganzen Datei. Folge: Änderungen des Templates an den Default-Listen `keep_local`/`no_replace`
   erreichen bestehende Projekte nicht (aufgefallen beim zweiten Update der Demo „Datenkiste": neue
   `no_replace`-Liste kam nicht an, Platzhalter mussten von Hand nachersetzt werden). Vorschlag:
   `template-update.py` merged die Datei feldweise — `base_commit`, `values`, `updates` immer aus dem Projekt,
   `keep_local`/`no_replace` als Vereinigung aus Template-Defaults und Projekt-Ergänzungen.
2. **`--apply` ohne Freigabe** (Priorität niedrig): `Bash(python .claude/scripts/new-project.py*)` erlaubt
   `--apply` (löscht Werkzeugdateien) ohne Rückfrage; nach dem Abbruch bei unbekannten Werkzeugnamen vertretbar,
   aber bewusst entscheiden. `Bash(git fetch template*)` matcht per Wildcard auch andere Remote-Namen.
3. **Zeilenenden in nachgerüsteten Repos** (Priorität niedrig): Platzhalter-Ersetzung schreibt geänderte Dateien
   immer mit LF — in Repos ohne `.gitattributes` ein sichtbarer Wechsel; ggf. Zeilenende der Datei erhalten.
