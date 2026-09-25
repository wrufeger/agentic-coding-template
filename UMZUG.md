# Umzug: neue Fassung des Templates

Diese `main`-Historie ist die eingefrorene Vorgänger-Fassung dieses Templates. Es gibt eine neue Fassung —
Mechanik unter `.act/` (statt `.claude/`), Regeln und Scripte auf Englisch, Doku weiter wahlweise auf
Deutsch. Sie ersetzt diese `main` nicht durch einen normalen Commit-Verlauf, sondern lebt als eigener
Checkout.

## Was NICHT geht

**Kein `/act-update-template` bzw. `--apply` von hier aus.** Die neue Fassung stammt zwar von diesem `main`
ab, ist aber eine andere Struktur (`.act/` statt `.claude/`, kein `template.json`) — ein normaler
Git-Merge würde beides vermengen, nicht ablösen. `update-template.py --apply` erkennt die neue Fassung
selbst (Marker `.act/VERSION` im geholten Stand) und bricht deshalb von sich aus ab, bevor irgendetwas
gemergt oder geschrieben wird.

## Wie der Umzug stattdessen geht

1. Die neue Fassung an anderer Stelle auschecken oder klonen (README dort nennt die URL/den Pfad).
2. In diesem (alten) Projekt eine Sitzung mit dem Assistenten starten und den Skill `act-adopt` aus dem
   neuen Checkout ausführen lassen — er übernimmt Board, Aufgaben, Fragen, Journal, Backlog und die eigene
   Projekt-Dokumentation in die neue Struktur.
3. Der Assistent legt dafür einen eigenen Branch an und richtet den neuen Checkout im Projekt ein; nichts
   an der bisherigen Arbeit geht dabei verloren — Verlauf, Entscheidungen und offene Fragen wandern mit.
4. Was aus der alten Struktur nicht mehr gebraucht wird (z. B. `.claude/`-eigene Dateien ohne Entsprechung),
   landet in einem Legacy-Archiv im Projekt, nicht im Nichts — nachlesbar, aber nicht mehr aktiv im Weg.

## Rückweg

Der Umzug legt den bisherigen Stand nicht still: der alte Branch bleibt erhalten, und bis zum Abschluss
lässt sich jederzeit dorthin zurückwechseln, ohne dass etwas aus dem Umzug-Versuch verloren geht.
