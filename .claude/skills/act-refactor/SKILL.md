---
name: act-refactor
description: Code umbauen, ohne das Verhalten zu ändern - Ziel und Umfang klären, Testnetz prüfen, in kleinen Schritten umbauen, jeden Schritt mit Tests absichern. Auslöser - "/refactor", "das hier aufräumen", "X umbauen", "Struktur verbessern".
---

# Umbauen ohne Verhaltensänderung

Baut bestehenden Code um, ohne dass sich sein Verhalten ändert — lesbarer, einheitlicher oder leichter zu
erweitern, aber am Ende dasselbe Ergebnis wie vorher. Der Skill ist **nicht** dafür da, dabei auch
Funktionalität zu ändern oder Code zu „modernisieren", nur weil er alt aussieht.

**Die wichtigste Regel zuerst:** Ohne Tests für den betroffenen Bereich wird **nicht** umgebaut. Fehlt das
Testnetz, wird zuerst `/test-gap` für genau diesen Bereich durchlaufen — oder der Umbau wird abgelehnt und
zurückgemeldet, statt ihn ungesichert durchzuführen.

## Ablauf

1. **Ziel benennen.** Was soll nach dem Umbau messbar besser sein (kürzer, weniger Duplikation, klarere
   Verantwortlichkeiten, austauschbare Abhängigkeit)? Ein Ziel in einem Satz, keine Sammlung.
2. **Umfang abgrenzen.** Welche Dateien/Module sind betroffen, welche ausdrücklich nicht. Wächst der Umfang
   während der Arbeit über diese Abgrenzung hinaus: abbrechen und den Auftrag neu schneiden, statt
   „nebenbei" weiterzumachen.
3. **Testnetz prüfen.** Deckt die vorhandene Testsuite das betroffene Verhalten ab (`docs/project/testing.md`)?
   Wenn nein: `/test-gap` für den Bereich durchlaufen, danach hier fortsetzen. Ohne Netz kein Schritt 4.
4. **In kleinen Schritten umbauen.** Jeder Schritt für sich nachvollziehbar (eine Umbenennung, eine
   Extraktion, eine Verschiebung) — kein Umbau in einem einzigen großen Patch.
5. **Nach jedem Schritt testen.** Die Testsuite aus Schritt 3 läuft nach jedem Einzelschritt grün, bevor der
   nächste beginnt. Ein roter Zwischenstand wird sofort behoben, nicht mitgeschleppt.
6. **Verhalten am Ende vergleichen.** Ein- und Ausgaben vor und nach dem Umbau stichprobenartig gegenüberstellen,
   dazu die vollständigen Pflichtläufe (`AI-CONFIG.md` § Technik).
7. Beleg sichern (grüne Tests nach jedem Schritt, finaler Vergleich), dann Checkliste
   „Aufgabe abschließen" (`/commit`).

## Grenzen

- **Keine Funktionsänderung im selben Auftrag.** Fällt beim Umbau eine gewünschte Verhaltensänderung auf,
  ist das ein eigener, späterer Commit — nicht dieser.
- **Kein Modernisieren ohne Anlass.** Bestehenden Stil respektieren (`AGENTS.md`, `docs/project/coding_rules.md`).
  Eine neue Bibliothek, ein neues Pattern oder eine andere Formatierung nur, wenn das Ziel aus Schritt 1 das
  verlangt.
- **Abbruch statt Ausweitung.** Wird der Umbau beim Arbeiten größer als in Schritt 2 abgegrenzt, wird
  abgebrochen und neu geschnitten — nicht stillschweigend weitergemacht.
