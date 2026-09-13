---
name: bug
description: Einen gemeldeten Fehler beheben - reproduzieren, eingrenzen, Ursache statt Symptom, mit einem Test belegen, der vorher rot und nachher grün ist. Auslöser - "/bug", "Fehler beheben", "das hier funktioniert nicht", "Bugfix für X".
---

# Fehler beheben

Behebt einen gemeldeten Fehler so, dass der Beleg zweifelsfrei ist: ein Test, der den Fehler vorher zeigt und
nachher nicht mehr. Der Skill ist **nicht** dafür da, nebenbei aufzuräumen oder einen Fehler „auf Verdacht" zu
reparieren, den niemand auslösen konnte — genau diese beiden Abkürzungen sind der Grund, warum der Ablauf hier
festgeschrieben ist, statt ihn jedes Mal neu zu improvisieren.

## Ablauf

1. **Reproduzieren.** Erst wenn der Fehler sich auslösen lässt — lokal, per Testfall oder per Log-Auszug von
   {{AUFTRAGGEBER}} —, wird gesucht. Ohne Reproduktion direkt zu Schritt 6 springen.
2. **Eingrenzen.** Welche Schicht ist betroffen (UI, Logik, Datenzugriff, Konfiguration)? Seit wann tritt der
   Fehler auf — `git log` auf die betroffenen Dateien, bei Unklarheit `git bisect` zwischen einem
   funktionierenden und dem aktuellen Stand.
3. **Ursache benennen.** Nicht die Stelle beschreiben, an der der Fehler sichtbar wird, sondern warum er
   entsteht. Bei mehreren möglichen Ursachen: die naheliegendste zuerst prüfen, nicht raten.
4. **Test schreiben, der rot ist.** Vor jeder Änderung am eigentlichen Code einen Test, der den Fehler zeigt.
   Läuft dieser Test bereits grün, war entweder die Reproduktion unvollständig oder die Ursache falsch
   benannt — zurück zu Schritt 1 bzw. 3.
5. **Beheben.** Kleinstmögliche Änderung an der benannten Ursache, kein Umbau der Umgebung.
6. **Test grün, Pflichtläufe.** Der Test aus Schritt 4 läuft grün, dazu Lint, Typecheck und die übrigen
   Pflichtläufe (`AI-CONFIG.md` § Technik, `docs/project/testing.md`).
7. Beleg sichern (roter Test vorher, grüner Test nachher, Pflichtläufe grün), dann Checkliste
   „Aufgabe abschließen" (`/commit`).

## Grenzen

- **Kein Aufräumen nebenbei.** Fällt beim Beheben etwas anderes auf (Altlast, unklarer Name, fehlender Test
  an anderer Stelle), gehört das nach `docs/ai/backlog.md`, nicht in diesen Auftrag.
- **Kein Fix auf Verdacht.** Lässt sich ein gemeldeter Fehler nicht reproduzieren, wird er nicht „irgendwie"
  behoben. Stattdessen dokumentieren: was gemeldet wurde, was versucht wurde, woran die Reproduktion
  scheiterte — und bei {{AUFTRAGGEBER}} nachfragen, wenn eine Voraussetzung fehlt (Zugangsdaten, Testdaten,
  eine bestimmte Umgebung).
- **Zwei Anläufe, dann Eskalation.** Scheitert die Eingrenzung oder die Behebung zweimal an derselben Sache,
  übernimmt `expert-solver` mit vollständigem Kontext (ursprünglicher Auftrag, beide Fehlversuche samt
  Ausgaben, betroffene Dateien, bereits ausgeschlossene Ursachen) — kein dritter Anlauf mit derselben
  Aufgabenstellung.
