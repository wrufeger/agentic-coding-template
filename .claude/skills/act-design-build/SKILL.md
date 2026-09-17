---
name: act-design-build
description: Eine Komponente oder Seite nach Vorlage umsetzen und das Ergebnis selbst im Browser prüfen - in mehreren Runden, bis es passt. Auslöser - "/design-build", "bau <Komponente> nach diesem Screenshot", "setz Variante 2 um", "Seite X umsetzen".
---

# Oberfläche umsetzen und selbst prüfen

Setzt eine Komponente oder eine ganze Seite im **echten Projektcode** um und vergleicht das Ergebnis
anschließend selbst mit der Vorlage — so oft, wie es nötig ist, aber höchstens dreimal. Vorlage ist ein
Screenshot, eine Variante aus `/design-ideas`, ein Weblink oder eine Beschreibung.

**Der Unterschied zu „bau mir das mal":** Der Skill prüft sein eigenes Ergebnis, bevor er es abgibt. Ohne
diese Schleife liefert ein Assistent Code, der plausibel aussieht und im Browser daneben liegt.

## Voraussetzungen

Prüfe zu Beginn, **ob die Selbstprüfung möglich ist**, und sag das Ergebnis vor dem ersten Schritt:

1. **Playwright** (`playwright.config.*` oder `@playwright/test`) und ein Dev-Server-Befehl (`AI-CONFIG.md`
   § `Dev-Start-Befehl`): der Normalfall. Braucht einmalig `npx playwright install`.
2. **Claude in Chrome**: geht auch — langsamer, dafür ohne Testaufbau.
3. **Nichts davon**: Der Skill läuft trotzdem, aber **ohne** die Prüfschleife. Das ist dann kein
   „umgesetzt und geprüft", sondern „umgesetzt" — sag es genau so, statt die Prüfung stillschweigend
   wegzulassen.

## Ablauf

1. **Auftrag und Vorlage klären.** Was wird gebaut (Komponente, Seite, Ausschnitt), wo landet es (Pfad),
   was ist die Vorlage? Bei einem Weblink als Vorbild: Screenshot per Claude in Chrome erzeugen, **nicht**
   `WebFetch`. Bei einer Variante aus `/design-ideas`: die zugehörige HTML-Datei und ihren Screenshot lesen.
2. **Regeln und Bestand lesen — vor der ersten Zeile Code:**
   - `docs/project/coding_rules.md` und die Bausteine unter `coding_rules.d/` (Komponentenaufbau,
     Typisierung, Reihenfolge der Blöcke).
   - Welche Komponenten es schon gibt. **Nichts neu bauen, was die Bibliothek bereits hat** — das ist der
     häufigste Fehler bei Oberflächen aus KI-Hand.
   - Farb-, Abstands- und Typo-Tokens des Projekts. Keine harten Farbwerte, wenn es Tokens gibt.
3. **Umsetzen** (Sub-Agent `builder`, Sonnet, oder im Hauptkontext bei einer einzelnen kleinen Komponente).
   Dabei gilt, was auch sonst gilt: Texte über die Übersetzungsschicht, keine hartcodierten Zeichenketten,
   Zustände (Laden, Leer, Fehler) mitdenken, Barrierefreiheit nicht vergessen (`alt`, Fokusreihenfolge,
   Kontrast).
4. **Prüfen** — das Kernstück:
   - Dev-Server starten, Zielseite öffnen, Screenshot aufnehmen. Mindestens Desktop (1280 px) und
     Mobil (390 px).
   - Screenshot **neben** die Vorlage legen und benennen, was abweicht: Abstände, Größenverhältnisse,
     Ausrichtung, Farbe, Zeilenumbrüche, überlaufender Text.
   - Browser-Konsole lesen. Fehler dort zählen als Abweichung, auch wenn das Bild stimmt.
5. **Nachbessern, höchstens zwei weitere Runden.** Nach jeder Runde erneut prüfen. Steht es nach der dritten
   Runde immer noch nicht, **abbrechen und berichten**: was passt, was nicht, woran es liegt. Eine vierte
   Runde bringt erfahrungsgemäß nichts, was eine kurze Rückfrage nicht schneller löst.
6. **Belegen und abschließen:** Lint und Typecheck laufen lassen (Befehle aus `AI-CONFIG.md` § Technik),
   Ergebnis-Screenshot ablegen, Abweichungen benennen, die bewusst geblieben sind. Dann die Checkliste
   „Aufgabe abschließen" (`/commit`).

## Grenzen

- **Die Prüfschleife ersetzt kein Urteil.** Der Skill vergleicht Bilder; ob das Ergebnis *gut* ist, sagt
  {{AUFTRAGGEBER}}. Bei einer Abweichung, die eine Gestaltungsfrage ist und kein Fehler, wird gefragt statt
  entschieden.
- **Höchstens drei Runden.** Danach Bericht, keine stille Endlosschleife. Wer mehr braucht, hat einen zu
  großen Auftrag geschnitten — Seite in Komponenten teilen.
- **Kein Umbau nebenbei.** Fällt beim Bauen etwas anderes auf (unbenutzte Komponente, doppelte Typen), gehört
  das nach `docs/ai/backlog.md`, nicht in diesen Auftrag.
- Screenshots aus der Prüfung sind Wegwerfware und gehören nach `.design-varianten/` (gitignored). Nur ein
  Bild, das eine Entscheidung belegt, wandert bewusst ins Repo.
