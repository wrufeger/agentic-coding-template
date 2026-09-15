---
name: finalize
description: Einrichtung abschließen - Projekterstellung oder Nachrüsten für beendet erklären und die Einrichtungswerkzeuge aus dem Projekt entfernen. Auslöser - "/finalize", "Projekterstellung abschließen", "Nachrüsten abschließen", "Einrichtung fertig".
---

# Einrichtung abschließen (nur Hauptkontext)

Erklärt die Einrichtung dieses Projekts für beendet und entfernt danach alles, was nur zum Anlegen bzw.
Nachrüsten gebraucht wurde. Mechanik: `.claude/scripts/finish-setup.py`. Läuft **nie** in einem Sub-Agenten —
es wird gelöscht, und nur der Orchestrator committet.

**Wann.** Nicht am Ende von `/create-project` oder `/apply-template` — die Einrichtung ist dort meist noch
nicht wirklich fertig: `docs/project/` will nachgeschärft, `AI-CONFIG.md` nachjustiert, vielleicht muss ein
zweites Mal nachgerüstet werden. Der Abschluss ist deshalb ein eigener Schritt, den {{AUFTRAGGEBER}} auslöst,
wenn er mit allem durch ist. Bis dahin erinnert der SessionStart-Hook bei jedem Sitzungsstart kurz daran.

**Was danach nicht mehr geht.** `create-project`, `apply-template` und die Struktur-Migration sind im Projekt
anschließend nicht mehr aufrufbar. Das ist beabsichtigt: Ein eingerichtetes Projekt soll sich nicht versehentlich
noch einmal einrichten lassen. Weiter funktionieren `/update-template`, `sync-config.py` (`AI-CONFIG.md` wirkt
unverändert laufend), `guidelines.py`, `ai-log.py` und die Alltags-Skills `/commit` und `/audit-docs`.

**Feedback anbieten — einmal, mit vollständiger Offenlegung.** Nach dem Aufräumen wird gefragt, ob dieses
Projekt dem Template-Autor zurückmelden soll, was sich an der **Arbeitsweise** bewährt oder gefehlt hat. Die
Frage kommt **einmal**; ohne Antwort passiert nichts.

Der Wortlaut muss diese sechs Punkte nennen, sonst ist es keine Einwilligung:

> Möchtest du zurückmelden, was hier an der Zusammenarbeit gut lief oder gefehlt hat? Das hilft, die
> Standardregeln, Skripte und Skills des Templates zu verbessern.
>
> **Wie das läuft:** Ich lese dafür `.claude/`, `CLAUDE.md`, `AGENTS.md` und `docs/ai/` und schreibe daraus
> eine kurze Zusammenfassung — welche Regel ergänzt wurde, welcher Ablauf sich bewährt hat, welcher
> MCP-Server dazukam. **Verschickt werden keine Dateien**, sondern nur diese Zusammenfassung, ohne
> Projektbezug, ohne Namen, ohne Daten. Dazu ein paar Angaben aus festen Listen: Datum, Template-Stand,
> wie das Projekt entstand, welche Werkzeuge und Regelsätze du gewählt hast.
> **Wohin:** `https://rufeger.de/agentic-coding-feedback`
> **Wie oft und wie:** Das bestimmst du — ohne Rückfrage, mit Bestätigung vor jedem Versand, oder
> nur auf Zuruf. Ebenso den Takt (Vorschlag: höchstens einmal pro Woche). Beides steht danach in
> `AI-CONFIG.md` und lässt sich jederzeit ändern.
> **Was du siehst:** Jede Sendung liegt vollständig unter `docs/ai/template-feedback/` — standardmäßig
> **versioniert**, du kannst also jederzeit nachlesen, was hinausging, und es fällt im Diff auf. Ist dein
> Repo öffentlich, wäre damit auch die Rückmeldung öffentlich lesbar; das Protokoll lässt sich deshalb auf
> Wunsch per `.gitignore` lokal halten (gleich die nächste Frage).
> **Was es kostet:** Das Zusammenfassen und Filtern verbraucht ein paar Token zusätzlich.
> **Wie damit umgegangen wird:** Die Daten werden vertraulich behandelt und vor jeder Verwendung im
> öffentlichen Template persönlich durchgesehen — falls doch einmal etwas durchrutscht.
> a) ja  b) nein  c) später entscheiden

Bei **a)** zusätzlich fragen, **wie** gesendet werden soll — die Antwort landet in `AI-CONFIG.md` und gilt
ab dann laufend: „ohne Rückfrage (`automatisch`), mit Anzeige und Bestätigung vor jedem Versand
(`bestaetigen`), oder nur wenn du `/feedback` aufrufst (`manuell`)?" Dazu den Takt, falls nicht
`manuell`: `sofort` · `stuendlich` · `taeglich` · `woechentlich` (Vorschlag) · `automatisch`.

Ebenfalls bei **a)** fragen, **wo das Sendeprotokoll liegen soll** — die Frage wird gestellt, nicht
angenommen:

> Jede Sendung wird unter `docs/ai/template-feedback/` abgelegt. Soll dieses Protokoll
> a) **mitversioniert** werden (Vorschlag — der Nachweis steht im Verlauf, und im Diff fällt jede Sendung auf)
> oder b) **nur lokal** liegen (Eintrag in `.gitignore`; sinnvoll, wenn das Repo öffentlich ist oder andere
> es nicht lesen sollen — dann ist es nach einem frischen Klon allerdings weg)?

Dann: `python .claude/scripts/feedback.py --enable --modus <automatisch|bestaetigen|manuell>
--protokoll <versionieren|lokal>
--weg <neu|nachgeruestet> --ausfuellart <leer|interview|config>`, optional `--repo-url <https://…>` bei
einem **öffentlichen** Repo; den Takt in `AI-CONFIG.md` § `Feedback-Takt` setzen. Danach die Erstmeldung
zusammenstellen (`--add`, siehe unten) und `--send --force` aufrufen.

Bei **b)** oder **c)**: nichts tun, `Feedback` bleibt auf `aus`. Einschalten ist jederzeit nachholbar
(`--enable` oder die Zeile in `AI-CONFIG.md`), `--disable` widerruft.

**Was in eine Meldung gehört.** Der Assistent liest die Regel- und Arbeitsdateien und macht daraus Einträge
(`feedback.py --add --art <regel|script|skill|ablauf|doku|fehler|mcp|link> --titel … --text …`). Maßstab ist
allein: **Hilft das einem Fremden, der dieses Projekt nie sehen wird?** Also „eine Regel gegen X fehlte" statt
„wir haben X gebaut"; das Muster, nicht der Fall. Kein Projektname, keine Pfade, kein Code, keine Zahlen aus
dem Projekt. Der Filter im Script lehnt Pfade, Mailadressen, IPs und Zugangsdaten-Wörter ohnehin ab — er ist
die letzte Schranke, nicht die erste.

## Ablauf

1. **Vorbedingungen prüfen.** `git status` — der Arbeitsbaum muss sauber sein. Ist er es nicht, zuerst die
   laufende Aufgabe abschließen (`/commit`); das Aufräumen löscht Dateien und soll für sich im Verlauf stehen.
2. `python .claude/scripts/finish-setup.py --plan` ausführen und die Ausgabe **vollständig** zeigen: was
   entfernt wird, was bewusst liegen bleibt, was inhaltlich noch offen ist.
3. **Einmal nachfragen**, auch wenn {{AUFTRAGGEBER}} den Skill selbst aufgerufen hat — der Schritt ist nicht
   ohne Weiteres rückgängig zu machen (nur über `git revert` bzw. `git checkout` des Commits):

   „Einrichtung abschließen? Danach sind `create-project` und `apply-template` in diesem Projekt nicht mehr
   verfügbar. a) ja b) noch nicht"

   Ohne Antwort **nicht** ausführen (`AGENTS.md` — keine Standardantwort annehmen).
4. Meldet der Plan unter „Noch einzuarbeiten" fremde KI-Regeldateien (`.junie/guidelines.md`, `.clinerules`,
   `.windsurfrules`, `.cursorrules`, `.github/instructions/`, `AGENT.md`), diese **vor** dem Abschluss
   erledigen — sonst gelten zwei Regelwerke nebeneinander und laufen auseinander:
   - Inhalt nach `docs/project/coding_rules.md` übernehmen, soweit er dort noch nicht steht (Sub-Agent
     `doc-writer`, Sonnet). Bei Widersprüchen gilt die strengere Regel.
   - Die Altdatei danach auf einen Verweis eindampfen, Beispiel für `.junie/guidelines.md`:

     ```markdown
     # Projektregeln

     Die verbindlichen Regeln dieses Projekts stehen in `AGENTS.md` im Repo-Root (werkzeugunabhängig) und
     in `docs/project/coding_rules.md` (Stil- und Sprachregeln). Diese Datei wird nicht mehr gepflegt.
     ```
   - Nur löschen statt eindampfen, wenn das Werkzeug die Datei gar nicht mehr braucht und {{AUFTRAGGEBER}}
     zustimmt.
5. `python .claude/scripts/finish-setup.py --apply` ausführen, Ausgabe zeigen.
6. Ergebnis verbuchen: Ledger-Eintrag „Einrichtung abgeschlossen" mit der Liste der entfernten Dateien,
   Board-Kurzbilanz nachziehen.
7. Commit per Pathspec (die Löschungen sind bereits vorgemerkt, wenn das Script `git rm` genutzt hat —
   `git status` prüfen und nur die betroffenen Pfade committen).

## Grenzen

- Kein Projektinhalt wird angefasst: nichts unter `docs/project/` (außer der Regelübernahme in Schritt 4),
  kein Anwendungscode, keine Abhängigkeit.
- `docs/ai/checklists.md` verliert die drei Abschnitte „Neues Projekt", „Projekt nachrüsten" und „Einrichtung
  abschließen", weil sie im eingerichteten Projekt nur noch in die Irre führen. Alle übrigen Checklisten
  bleiben.
- Das Script entfernt am Ende diesen Skill und sich selbst. Ein zweiter Lauf ist damit weder möglich
  noch nötig.
- Im Template-Checkout selbst (Marker `is_template` in `.claude/template.json`) verweigert das Script den
  Dienst — dort werden die Einrichtungswerkzeuge gepflegt, nicht gelöscht.
