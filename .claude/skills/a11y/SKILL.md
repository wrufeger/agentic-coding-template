---
name: a11y
description: Eine Oberfläche auf Barrierefreiheit prüfen und die Befunde nach Schwere abarbeiten - Tastaturbedienung, Fokus, Kontrast, Beschriftungen, Struktur. Auslöser - "/a11y", "Barrierefreiheit prüfen", "ist das zugänglich?", "Screenreader", "WCAG".
---

# Barrierefreiheit prüfen

Prüft eine bestehende Oberfläche darauf, ob sie ohne Maus, ohne Farbsehen und mit einem Screenreader
benutzbar ist. Abgrenzung zu `/design-build`: Dort wird gegen eine **Vorlage** geprüft („sieht es aus wie
gedacht?"), hier gegen die **Benutzbarkeit** („kommt jeder damit klar?"). Eine Oberfläche kann der Vorlage
exakt entsprechen und trotzdem unbedienbar sein.

Die Prüfung ist stack-unabhängig: Sie sieht sich das gerenderte Ergebnis an, nicht das Framework.

## Ablauf

1. **Umfang festlegen.** Eine Seite oder eine Komponente, nicht „die ganze Anwendung". Ohne klare Grenze
   entsteht eine Mängelliste, die niemand abarbeitet.
2. **Automatisch messen, wo es geht.** Ist Playwright eingerichtet (`AI-CONFIG.md` § Technik), einen Lauf mit
   einer Prüf-Bibliothek (z. B. `axe-core`) gegen die laufende Seite fahren. Das findet die mechanischen
   Fehler: fehlende Beschriftungen, zu geringe Kontraste, doppelte IDs, fehlende Sprachauszeichnung.
   **Ein grüner automatischer Lauf heißt nicht barrierefrei** — er deckt erfahrungsgemäß nur einen Teil ab.
3. **Von Hand prüfen, was kein Werkzeug sieht** — in dieser Reihenfolge, weil die Fehler oben am häufigsten
   und am schwersten wiegen:
   - **Tastatur:** Ist jedes Bedienelement mit `Tab` erreichbar und mit `Enter`/`Space` auslösbar? Ist die
     Reihenfolge die des Inhalts? Gibt es eine Falle, aus der man nicht mehr heraustabbt (Dialog, Menü)?
   - **Fokus:** Ist sichtbar, wo man gerade ist? Springt der Fokus beim Öffnen eines Dialogs hinein und beim
     Schließen dorthin zurück, wo er herkam?
   - **Struktur:** Überschriften in sinnvoller Rangfolge ohne Sprünge, Bedienelemente als das ausgezeichnet,
     was sie sind (ein `div` mit Klick-Handler ist kein Button), Formularfelder mit verbundener Beschriftung.
   - **Ohne Farbe:** Wird eine Information allein über Farbe transportiert (Fehler rot, Erfolg grün)? Dann
     fehlt das zweite Merkmal — Text, Symbol, Position.
   - **Bewegte Inhalte:** abschaltbar, und respektieren sie `prefers-reduced-motion`?
4. **Befunde nach Schwere vorlegen**, je Befund eine Zeile: was, wo (`Datei:Zeile` oder Auswahl im DOM),
   welche Auswirkung für wen, Vorschlag. Reihenfolge: **blockiert die Nutzung** → **erschwert sie erheblich**
   → **Schönheitsfehler**. Erst danach wird etwas geändert.
5. **Beheben, was freigegeben ist**, von oben nach unten. Nach jeder Gruppe erneut messen — Korrekturen an
   der Fokusreihenfolge verschieben gern etwas anderes.
6. Beleg sichern (Prüflauf vorher/nachher, Liste der behobenen Punkte), dann Checkliste
   „Aufgabe abschließen" (`/commit`).

## Grenzen

- **Kein Ersatz für einen Test mit echten Nutzern.** Der Skill findet handwerkliche Fehler, nicht schlechte
  Bedienlogik. Wer eine Anwendung wirklich zugänglich machen will, lässt sie von jemandem bedienen, der auf
  Hilfsmittel angewiesen ist.
- **Keine Konformitätsaussage.** „WCAG AA erfüllt" ist eine Prüfaussage mit rechtlicher Bedeutung und wird
  hier nicht getroffen — gemeldet wird, was gefunden und was behoben wurde.
- **Kein Umbau der Oberfläche.** Stellt sich heraus, dass die Struktur grundsätzlich nicht trägt, ist das ein
  Befund für den Backlog und eine eigene Aufgabe, kein Nebenbei-Umbau in diesem Lauf.
- `aria-*` nur, wo natives HTML nicht reicht. Ein falsch gesetztes ARIA-Attribut ist schlechter als keines.
