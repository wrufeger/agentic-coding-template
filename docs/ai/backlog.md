> Datenstand: {{DATUM}} – Status: Vorlage, noch nicht projektspezifisch

# Umbauliste — Vorschläge des Orchestrators

Priorisierte Verbesserungsvorschläge (Sicherheit zuerst). {{AUFTRAGGEBER}} entscheidet — Marker direkt am
Punkt (z. B. „-> machen", „-> später", „-> nein, weil …").

Grundsatz: der bestehende Codestil/die bestehenden Muster bleiben erhalten, solange sie kein echtes Problem
verursachen. Vorschläge hier sind Angebote, keine Aufträge — Umsetzung erst nach Freigabe in `tasks.md`.

Hierher schreibt der Orchestrator auch die Befunde der optionalen Code-Analyse beim Nachrüsten eines
bestehenden Projekts (Checkliste „Projekt nachrüsten", Schritt 7) — je Punkt: Befund, Fundstelle
`Datei:Zeile`, Vorschlag, geschätzter Aufwand.

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
4. **Wartungsberichte sichtbar ablegen** (Priorität niedrig): Berichte liegen unter
   `.claude/maintenance/reports/` und sind gitignored. In einem realen Projekt haben sie sich unter `docs/`
   (versioniert, im Doku-Index verlinkt) als nützlicher erwiesen, weil der Verlauf der Prüfungen nachlesbar
   bleibt. Vorschlag: Ablageort über `CONFIG.md` wählbar machen, Default unverändert lassen.
5. **Datenstand-Fußnoten im Doku-Index** (Priorität niedrig): `docs/README.md` listet je Datei einen
   Datenstand; für Dateien ohne eigene Kopfzeile fehlt eine Konvention. In einem realen Projekt hat sich ein
   Fußnoten-System bewährt („¹ Datenstand aus dem letzten Audit, Datei trägt keine Kopfzeile"), damit fehlende
   Stände sichtbar statt stillschweigend leer bleiben.
6. **Incident als Einzeldatei** (Priorität niedrig): `docs/project/incidents/` ist als Ordner mit Schema-README
   angelegt. Bei wenigen Fällen reicht eine Datei je Vorfall mit den Abschnitten Fehlerbild/Ursache/Behebung/
   Verifikation; die schwerere Ordnerstruktur lohnt erst ab mehreren Analysen pro Jahr.
7. **`status.json` atomar schreiben** (Priorität niedrig): `maintenance-check.py` schreibt die Statusdatei
   direkt. Zwei gleichzeitige `--done`-Aufrufe verlieren einen Schreibvorgang, ein Leser im Schreibfenster
   sieht halbes JSON (bei `--check` folgenlos, weil dieser Pfad still ist). Vorschlag: in eine Temp-Datei
   schreiben und per `os.replace` umbenennen — dasselbe Muster wäre auch für `template.json` sinnvoll.
8. **Hook-Entfernung genauer treffen** (Priorität niedrig): `new-project.py` entfernt bei `Wartung: aus` jeden
   `SessionStart`-Hook, dessen Kommando `maintenance-check.py` enthält. Ein selbst ergänzter Hook, der dieses
   Script nur nebenbei aufruft, würde mitentfernt. Vorschlag: zusätzlich auf `$CLAUDE_PROJECT_DIR` im
   Kommando prüfen oder die vom Template gesetzten Hooks markieren.
9. **Leere Argumente melden** (Priorität niedrig): `maintenance-check.py --set ""` und `--done ""` fallen still
   auf `--check` zurück, statt mit Exit 2 abzubrechen. Außerdem meldet `Wartung: ein` bei fehlendem
   `.claude/maintenance/` nur die neue `status.json`, ohne darauf hinzuweisen, dass Runner und README des
   Wartungsordners fehlen (Fall „Projekt per `consume-template.py` nachgerüstet").
10. **Gitignorierte Dateien bei der Migration** (Priorität mittel): `migrate-project.py --apply` verschiebt
   eine Arbeitsdatei auch dann nach `docs/ai/` und legt sie in den Index, wenn sie im alten Ordner bewusst
   gitignoriert war (z. B. private Notizen). Vorschlag: vor dem Verschieben `git check-ignore` prüfen und
   solche Dateien nur melden statt zu verschieben.
11. **Namensersetzung trifft Pfade, URLs und Code** (Priorität mittel): `--rename-orchestrator` ersetzt den
   Rufnamen überall, wo er als eigenes Wort steht — auch in `https://fable.io/`, in Pfadangaben innerhalb von
   Texten und in Code-Beispielen. Wortgrenzen schützen nur vor Teilwort-Treffern (`Fabelwesen` bleibt).
   Vorschlag: Code-Blöcke und URLs in Markdown auslassen, oder vor dem Schreiben eine Trefferliste zur
   Bestätigung anzeigen. Bis dahin gilt: vorher committen, Ergebnis mit `git diff` prüfen.
12. **Merge-Kandidaten unvollständig** (Priorität niedrig): `migrate-project.py` meldet `AGENTS.md`,
   `CLAUDE.md`, `.claude/**`, `docs/ai/**` und `docs/project/**` als zusammenzuführen, aber nicht
   `.claude/settings.json`, `GEMINI.md`, `.aider.conf.yml`, `.cursor/`, `.github/copilot-instructions.md` und
   `docs/README.md`. Existieren die im Zielrepo schon, bleiben Unterschiede unbemerkt.
