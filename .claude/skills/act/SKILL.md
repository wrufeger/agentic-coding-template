---
name: act
description: Übersicht aller Projekt-Befehle (/act-…) mit Parametern und Kurzbeschreibung, wie eine man page; mit Namen ein einzelner Befehl ausführlich.
argument-hint: "[befehl]"
disable-model-invocation: true
allowed-tools: Bash(python .claude/scripts/act-help.py*), Bash(python3 .claude/scripts/act-help.py*)
---

# Projekt-Befehle anzeigen

Normalerweise kommt die Eingabe `/act` hier gar nicht an: Der `UserPromptSubmit`-Hook
(`act-help.py --hook`) zeigt die Liste sofort und ohne Modell. Dieser Skill ist der Rückweg, falls Hooks
abgeschaltet sind.

Führe `python .claude/scripts/act-help.py $ARGUMENTS` aus (auf macOS/Linux `python3`) und gib die Ausgabe
**unverändert in einem Codeblock** wieder — ohne Einleitung, ohne Zusammenfassung, ohne eigene Ergänzungen.
Nichts weiter tun, keinen der gelisteten Befehle starten.
