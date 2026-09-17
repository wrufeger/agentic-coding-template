---
name: act-deps
description: Abhängigkeiten aktualisieren - Bestand und Abstand ermitteln, Patch/Minor gebündelt, Major einzeln mit Prüfung des Änderungsprotokolls, nach jedem Schritt Lint/Typecheck/Tests. Auslöser - "/deps", "Abhängigkeiten aktualisieren", "Dependencies updaten", "Pakete auf den neuesten Stand bringen".
---

# Abhängigkeiten aktualisieren

Bringt die Abhängigkeiten des Projekts kontrolliert auf einen neueren Stand — nicht in einem Sammel-Update,
sondern in nachvollziehbaren Schritten, die sich einzeln zurückrollen lassen. Kernregel: **erst das Netz,
dann der Sprung.** Ohne laufende Tests und Typecheck lässt sich nach einem Update nicht unterscheiden, was
das Update kaputt gemacht hat und was vorher schon defekt war. Fehlt diese Ausstattung, wird sie zuerst
hergestellt (Checkliste dazu ggf. in `docs/project/testing.md` nachtragen), bevor überhaupt ein Paket
angefasst wird.

## Ablauf

1. **Bestand und Abstand ermitteln.** Mit dem Paketmanager des Projekts (Befehle aus `AI-CONFIG.md` §
   Technik) prüfen, welche Abhängigkeiten wie weit hinter ihrer aktuellen Version liegen, und ob
   `renovate.json` einen Teil davon bereits automatisiert vorschlägt — dort laufende Vorschläge nicht doppelt
   von Hand bearbeiten.
2. **Trennen in Patch/Minor und Major.** Patch- und Minor-Anhebungen dürfen gebündelt in einem Schritt
   laufen. Jede Major-Anhebung läuft **einzeln, in einem eigenen Commit** — nie mehrere Majors zusammen.
3. **Vor jedem Major das Änderungsprotokoll lesen.** Release Notes bzw. Changelog des Pakets auf Breaking
   Changes prüfen, statt zu raten, was sich geändert hat. Betroffene Stellen im Code vorab suchen
   (`explorer`, Sonnet, bei mehreren Fundstellen).
4. **Update ausführen.** Sub-Agent `builder` (Sonnet) je Schritt: Version anheben, Lockfile aktualisieren.
   Ändert das Update selbst Code (z. B. eine neue API), gehört das in einen **eigenen** Commit nach der
   Versionsanhebung, nie in denselben.
5. **Nach jedem Schritt prüfen.** Lint, Typecheck und Tests laufen lassen (Befehle aus `AI-CONFIG.md` §
   Technik). Erst bei grünem Ergebnis gilt der Schritt als abgeschlossen; rot bedeutet zurückrollen oder die
   nötige Codeänderung sofort nachziehen, nicht liegen lassen.
6. **Doku nachziehen, falls nötig.** Ändert ein Update Install-, Start-, Lint-, Typecheck- oder Testbefehl,
   `AI-CONFIG.md` § Technik entsprechend anpassen.
7. **Abschließen** je erledigtem Schritt über die Checkliste „Aufgabe abschließen" (`/commit`) — nicht erst
   am Ende der ganzen Aktualisierung.

## Grenzen

- Kein Sammel-Update über mehrere Major-Versionen hinweg — jede einzeln, mit eigenem Changelog-Check und
  eigenem Commit.
- Keine Abhängigkeit hinzufügen, die für die eigentliche Aufgabe nicht gebraucht wird, auch wenn sie
  „gerade praktisch wäre".
- Eine Versionsanhebung und eine dadurch nötige Codeänderung gehören nie in denselben Commit.
- Ohne grüne Pflichtläufe (Lint, Typecheck, Tests) gilt kein Schritt als abgeschlossen — auch nicht bei
  Zeitdruck.
