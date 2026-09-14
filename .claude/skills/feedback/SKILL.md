---
name: feedback
description: Rückmeldung an den Template-Autor zusammenstellen und senden - was sich an der Arbeitsweise bewährt oder gefehlt hat, ohne Projektbezug. Auslöser - "/feedback", "Feedback senden", "ans Template melden", "Rückmeldung geben".
---

# Rückmeldung an den Template-Autor

Stellt zusammen, was in diesem Projekt an der **Arbeitsweise** gelernt wurde, und sendet es — freiwillig,
gefiltert, protokolliert. Mechanik: `.claude/scripts/feedback.py`.

**Gesteuert wird über `AI-CONFIG.md`:** `Feedback` (`aus` · `bestaetigen` · `automatisch` · `manuell`) und
`Feedback-Takt` (`manuell` · `sofort` · `stuendlich` · `taeglich` · `woechentlich` · `automatisch`). Steht
`Feedback` auf `aus`, tut dieser Skill nichts und sagt das auch — er umgeht die Einstellung nicht.

Dieser Skill ist der **manuelle** Weg: Er sendet mit `--force` und übergeht damit Takt und Modus `manuell`.
Der Modus `bestaetigen` bleibt wirksam — dort wird die Nutzlast gezeigt und erst mit Zusage gesendet.

## Ablauf

1. **Zustand prüfen:** `python .claude/scripts/feedback.py --status`. Bei `aus` hier abbrechen und
   {{AUFTRAGGEBER}} sagen, wie er es einschaltet — nicht selbst umstellen.
2. **Lesen und herausdestillieren.** `.claude/`, `CLAUDE.md`, `AGENTS.md`, `docs/ai/` durchgehen und die
   Frage stellen: **Was davon hilft jemandem, der dieses Projekt nie sehen wird?** Typische Funde:
   - eine Regel, die hier ergänzt wurde, weil die Vorlage sie nicht hatte
   - ein Ablauf, der sich bewährt hat — oder einer, der regelmäßig scheiterte
   - ein Script oder ein Skill, der hier entstand und allgemein taugt
   - ein MCP-Server, der sich als nützlich erwies
   - eine Stelle, an der die Zusammenarbeit hakte: missverständliche Formulierung, fehlende Vorgabe,
     doppelte Regel
   - **ein nützlicher Link** aus `docs/ai/resources.md` § „Eigene Quellen dieses Projekts" — jemand hat eine
     gute Quelle gefunden, und die hilft anderen genauso. **Der Abschnitt „Private Links" ganz unten bleibt
     außen vor**, ausnahmslos; er existiert genau dafür.
3. **Je Fund einen Eintrag anlegen:**
   `python .claude/scripts/feedback.py --add --art <regel|script|skill|ablauf|doku|fehler|mcp|link>
   --titel "<eine Zeile>" --text "<zwei bis sechs Sätze>"`
   Für einen Link: `--art link --url <https://…>` — die Adresse gehört ins eigene Feld, nicht in den Text.
   Geprüft wird sie eigens: nur `http(s)`, keine Zugangsdaten in der URL, kein localhost, keine privaten
   IP-Bereiche, kein `*.intern`/`*.local`.
   Das Script lehnt sonst Pfade, Mailadressen, IPs und Zugangsdaten-Wörter ab — es ist die letzte Schranke,
   nicht die erste.
4. **Ansehen:** `--plan` zeigt die vollständige Nutzlast.
5. **Senden:** `--send --force` (bei Modus `bestaetigen` zusätzlich `--yes` nach der Ansicht).
6. Das geschriebene Protokoll unter `docs/ai/template-feedback/` **mitcommitten** — es gehört zum Nachweis,
   nicht in den Papierkorb.

## Wie ein guter Eintrag aussieht

| Nicht so | Sondern so |
| :--- | :--- |
| „In `app/stores/countries.ts` fehlte der Rückgabetyp" | „Eine Regel zu expliziten Rückgabetypen fehlte im TypeScript-Regelsatz und musste nachgetragen werden" |
| „Wir haben die Bandliste auf Kysely umgestellt" | „Beim Wechsel des Datenzugriffs half ein Konzept mit Optionen mehr als eine Aufgabe — die Entscheidung stand vorher fest" |
| „Unser Kunde braucht zwei Datenbanken" | „Zwei gleichartige MCP-Server mit verschiedenen Zugängen brauchen getrennte Einträge; das war aus der Doku nicht ersichtlich" |

Der Maßstab ist jedes Mal derselbe: **das Muster, nicht der Fall.**

## Grenzen

- **Nichts senden, was nur hier stimmt.** Eine Eigenheit dieses Projekts ist kein Befund fürs Template.
- **Keine Zahlen aus dem Projekt**, keine Dateinamen aus dem Projekt, keine Personen, keine Kunden.
- **Die Einstellung wird nicht umgangen.** Steht `Feedback` auf `aus`, wird gefragt statt geschaltet.
- **Kein Lob.** „Läuft gut" hilft niemandem — beschrieben wird, was konkret half oder fehlte.
