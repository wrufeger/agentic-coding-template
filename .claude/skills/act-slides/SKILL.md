---
name: act-slides
description: Eine Präsentation über das Projekt erstellen oder aktualisieren - Folien als Markdown im Repo, Inhalt aus der vorhandenen Doku, Export nach HTML/PDF. Auslöser - "/slides", "Präsentation erstellen", "Folien für das Projekt", "Vortrag vorbereiten", "Schulung".
---

# Präsentation über das Projekt

Erzeugt einen Foliensatz über dieses Projekt — für eine Schulung, eine Übergabe, einen Vortrag oder ein
Statusgespräch. **Die Folien sind Quelltext**: eine Markdown-Datei im Repo, versioniert wie alles andere,
diffbar, ohne Binärformat im Git.

**Der Inhalt kommt aus dem Repo, nicht aus der Fantasie.** Was auf einer Folie behauptet wird, muss in
`README.md`, `docs/project/` oder `docs/ai/board.md` belegt sein. Eine Präsentation, die vom Projekt
abweicht, ist schlimmer als keine — im Raum sitzen Leute, die den Code kennen.

## Werkzeug

Standard ist **Marp** (`marp-cli`, offiziell gepflegt): eine Markdown-Datei, Folientrennung mit `---`,
Export über `npx`. Es braucht nur Node und einen installierten Browser — keine Office-Installation, kein
Konto, kein Dienst.

```bash
npx @marp-team/marp-cli@latest docs/praesentation/<name>.md -o build/<name>.html
npx @marp-team/marp-cli@latest docs/praesentation/<name>.md --pdf -o build/<name>.pdf
```

**Wird ausdrücklich eine in PowerPoint nachbearbeitbare `.pptx` verlangt**, ist Marp der falsche Weg: Sein
PPTX-Export besteht aus Bildern, nicht aus Text. Dann **Quarto** nehmen (`quarto render <datei>.qmd --to
pptx`) — es erzeugt über Pandoc echte Textfolien, verlangt aber eine eigene CLI-Installation.
{{AUFTRAGGEBER}} entscheidet das, nicht der Assistent; frag danach, sobald „PowerPoint" fällt.

Bringt das Projekt bereits ein Präsentationswerkzeug mit (Slidev, reveal.js, Quarto), wird **dieses**
genutzt — kein zweites danebenstellen.

## Ablauf

1. **Zweck, Publikum, Dauer klären** — in dieser Reihenfolge, sie bestimmen alles Weitere. „Schulung für
   Entwickler ohne Vorkenntnisse, 45 Minuten" ergibt einen anderen Satz als „Statusbericht für die
   Projektleitung, 10 Minuten". Ohne diese drei Angaben nicht anfangen, sondern fragen.
2. **Material sichten statt erfinden.** `README.md` (was ist das, wie fängt man an), `docs/project/`
   (Architektur, Entscheidungen, Stand), `docs/ai/board.md` (wo es gerade steht). Was nirgends steht, ist
   entweder keine Folie wert oder muss erst in die Doku.
3. **Gliederung vorlegen, bevor eine Folie entsteht** — Titel je Folie, eine Zeile Kernaussage, geschätzte
   Redezeit. {{AUFTRAGGEBER}} streicht hier, nicht am fertigen Satz. Faustregel: eine Folie pro Minute
   Redezeit ist zu schnell, drei Minuten pro Folie ist der Normalfall.
4. **Folien schreiben.** Je Folie **eine** Aussage. Die Erläuterung gehört in die Sprechernotizen
   (`<!-- … -->` bei Marp), nicht auf die Folie — sonst liest der Raum, statt zuzuhören.
5. **Diagramme als Text.** Mermaid, wo das Werkzeug es kann, sonst ein exportiertes SVG. Keine Screenshots
   von Code oder Terminals: Sie veralten still und sind in der letzten Reihe unlesbar. Echter Code gehört in
   einen Codeblock mit höchstens zehn Zeilen.
6. **Rendern und ansehen.** Der Export muss einmal gelaufen sein, bevor etwas als fertig gilt — ein
   Markdown, das Marp nicht übersetzt, ist keine Präsentation. Bei einer Live-Demo zusätzlich Schritt 7.
7. **Live-Demo als Ablaufplan, nicht als Folie.** Eine eigene Datei neben dem Foliensatz: Vorbereitung
   (welche Fenster, welche Umgebungsvariablen, welcher Ausgangszustand), die Schritte in der Reihenfolge des
   Vortrags, und je Schritt **was schiefgehen kann und was dann gezeigt wird**. Die Demo wird **einmal
   vollständig geprobt**, bevor sie als fertig gilt.
8. Beleg sichern (Exportlauf ohne Fehler, Pfad der erzeugten Datei), dann Checkliste „Aufgabe abschließen"
   (`/commit`).

## Ablage

- Quelle: `docs/praesentation/<name>.md`, versioniert. Bilder daneben in `docs/praesentation/bilder/`.
- Ergebnis: nach `build/` oder in einen anderen ignorierten Ordner — **erzeugte HTML-, PDF- und
  PPTX-Dateien gehören nicht ins Git**. Sie entstehen in Sekunden neu und blähen sonst die Historie.
- Neue Dateien in `docs/README.md` eintragen (Index), Kopfzeile mit Datenstand und Status wie überall.

## Grenzen

- **Kein Foliensatz ohne Zweck, Publikum und Dauer.** Fehlt eines davon, wird gefragt, nicht geraten.
- **Keine Behauptung ohne Beleg im Repo.** Zahlen, Stände und Architekturaussagen werden aus der Doku
  übernommen; stimmt die Doku nicht mehr, wird zuerst sie berichtigt.
- **Kein Nachbau einer Firmen-Vorlage** aus einer vorhandenen `.pptx` — Schrift, Farben und Logo sind
  Vorgaben, die {{AUFTRAGGEBER}} liefert; als Marp-Theme (CSS) oder gar nicht.
- **Keine Textwüsten.** Wird eine Folie länger als sechs Zeilen, wird sie geteilt oder der Text wandert in
  die Notizen.
- Der Assistent hält den Vortrag nicht und schätzt auch nicht, wie er ankommt — er liefert Folien,
  Notizen und den Ablaufplan.
