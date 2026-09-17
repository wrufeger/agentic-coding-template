---
name: act-onboard
description: Ein fremdes Projekt verstehen - Einstiegspunkte, Datenfluss, Abhängigkeiten und Testlage erfassen, Ergebnis nach docs/project/ und docs/ai/ statt in eine flüchtige Chat-Antwort. Auslöser - "/onboard", "dieses Projekt verstehen", "in ein fremdes Repo einarbeiten", "wie funktioniert dieses Repo".
---

# Fremdes Projekt verstehen

Für den Fall, dass jemand — Mensch oder Assistent — ein Repo übernimmt, das er nicht kennt. Anders als eine
freie Recherche im Chat landet das Ergebnis dauerhaft in `docs/project/` und `docs/ai/`, damit die nächste
Sitzung nicht wieder bei null anfängt.

## Ablauf

1. **Umfang festlegen.** Ohne genannten Teilbereich gilt das ganze Repo. Kurz benennen, welche Bereiche
   geprüft werden.
2. **Einstiegspunkte finden** (Sub-Agent `explorer`, Sonnet): Startbefehl, Hauptmodule, Konfigurationsdateien,
   Einstiegspunkt(e) der Anwendung.
3. **Datenfluss nachvollziehen** (Sub-Agent `explorer`, Sonnet): wie Daten durch die Schichten laufen,
   zentrale Typen/Modelle, wo Zustand gehalten wird.
4. **Abhängigkeiten und externe Systeme identifizieren** (Sub-Agent `explorer`, Sonnet): Paketmanager-Datei,
   Datenbanken, APIs, Warteschlangen, Auth-Provider, sonstige Dienste.

   Schritte 2–4 sind unabhängig voneinander — als parallele `explorer`-Läufe starten, ein Nachrichtenblock mit
   mehreren Agent-Aufrufen (`AGENTS.md` § Modell-/Kostenlogik).
5. **Tests und Pflichtläufe ausprobieren.** Lint-, Typecheck- und Testbefehl tatsächlich ausführen, nicht nur
   aus der Konfiguration ablesen — laufen sie überhaupt, wie lange, was schlägt fehl. Ergebnis mit Beleg
   (Befehl + Ausgabe-Kurzfassung), nicht als Vermutung.
6. **Auffälligkeiten sammeln.** Aus den Rückgaben der Schritte 2–5: tote Bereiche, Widersprüche zwischen
   vorhandener Doku und tatsächlichem Code, ungetestete Bereiche. Reine Feststellung, keine Bewertung.
7. **Ergebnis nach `docs/project/` schreiben** (Sub-Agent `doc-writer`, Sonnet): `architecture.md` (Aufbau,
   Datenfluss), `setup.md` (Voraussetzungen, Einrichtung, Umgebungsvariablen), `testing.md` (welche
   Pflichtläufe es gibt, ob sie grün sind, was ungetestet bleibt). Datenstand-Kopfzeile je Datei aktualisieren.
8. **Zusammenarbeit und offene Fragen nach `docs/ai/`.** Was unklar bleibt oder sich nicht am Code belegen
   lässt, als Frage in `docs/ai/questions.md` mit Antwortoptionen ablegen (`AGENTS.md` — keine
   Standardantwort annehmen), Board-Kurzstand nachziehen.
9. Ergebnis im Chat kurz zusammenfassen (was jetzt in `docs/project/` steht, welche Fragen offen sind), dann
   Abschluss über die Checkliste „Aufgabe abschließen" (`/commit`).

## Grenzen

- Kein Code wird geändert — reine Bestandsaufnahme.
- Keine Qualitätsbewertung des Codes; dafür gibt es die Code-Analyse (`AI-CONFIG.md` § `Code-Analyse`,
  eingebunden in `/apply-template` bzw. `/audit-docs`).
- Nichts wird geraten: was sich nicht am Code oder durch einen Testlauf belegen lässt, wird als Frage notiert,
  nicht als Annahme in `docs/project/` festgeschrieben.
