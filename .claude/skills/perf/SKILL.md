---
name: perf
description: Leistung verbessern - Symptom und Ziel benennen, messen, Ursache suchen, eine Änderung, erneut messen, Ergebnis gegenüberstellen. Auslöser - "/perf", "Performance verbessern", "das ist zu langsam", "Ladezeit optimieren", "Anfrage/Abfrage beschleunigen".
---

# Leistung verbessern

Verbessert die Leistung eines konkreten, benannten Ausschnitts — einer Seite, einer Abfrage, eines
Endpunkts — auf Grundlage von Messwerten, nicht von Vermutungen. Kernregel: **erst messen, dann ändern.**
Ohne Messung vorher gibt es keine Verbesserung, sondern eine Behauptung. Der Skill ist nicht dafür da,
Code „generell schneller" zu machen, ohne dass jemand sagen kann, wofür.

## Ablauf

1. **Symptom und Ziel benennen.** Was genau ist langsam, für wen (welcher Pfad, welche Nutzergruppe, welche
   Datenmenge), ab wann ist es gut genug — als Zahl, nicht als Gefühl (z. B. „unter 300 ms", „unter 2 s bis
   interaktiv").
2. **Messen und die Messung festhalten**, bevor irgendetwas geändert wird: Werkzeug (Profiler,
   Browser-DevTools, Abfrageplan, Lasttest), Bedingungen (Umgebung, Datenmenge, Wiederholungen), gemessener
   Wert. Ohne diesen Ausgangswert gibt es später nichts zum Vergleichen.
3. **Ursache suchen statt raten.** Profil auswerten, Abfragen zählen und ihre Pläne lesen, Netzwerk-Wasserfall
   prüfen, Rendering-Zeiten aufschlüsseln — je nachdem, wo das Symptom liegt. Erst wenn die Ursache benannt
   ist, wird eine Änderung entworfen.
4. **Eine Änderung umsetzen** (Sub-Agent `builder`, Sonnet), die genau diese Ursache adressiert — nicht
   mehrere Änderungen auf einmal, sonst lässt sich die Wirkung nicht zuordnen.
5. **Erneut messen**, mit denselben Bedingungen und demselben Werkzeug wie in Schritt 2.
6. **Ergebnis gegenüberstellen.** Vorher-/Nachher-Wert nennen, gegen das Ziel aus Schritt 1 prüfen. Reicht
   die Verbesserung nicht, weiter bei Schritt 3 mit der nächsten Ursache — wieder nur eine Änderung je Runde.
7. **Belegen und abschließen.** Lint/Typecheck/Tests laufen lassen, Vorher-/Nachher-Zahlen ins Journal
   (`docs/ai/ledger.md`) eintragen, dann Checkliste „Aufgabe abschließen" (`/commit`).

## Grenzen

- Keine Optimierung ohne Messwert davor **und** danach — ein plausibler Grund reicht nicht.
- Keine Lesbarkeit gegen Mikrooptimierung eintauschen; ein Codeschnipsel, der 2 % bringt und die nächste
  Person verwirrt, ist keine Verbesserung.
- Zeigt die Messung nach der Änderung keine Verbesserung, wird die Änderung **zurückgenommen**, nicht aus
  Prinzip behalten.
- Ergebnis immer mit Zahlen ins Journal, nie mit „sollte jetzt schneller sein".
