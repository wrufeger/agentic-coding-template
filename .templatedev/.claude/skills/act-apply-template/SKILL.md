---
name: act-apply-template
description: Im Pflege-Projekt gesperrt – Checkliste „Projekt nachrüsten" hat hier keine Wirkung.
metadata:
  phase: setup
disable-model-invocation: true
---

Im Pflege-Projekt gesperrt — hier nicht verfügbar.
Grund: `.templatedev/` ist die Pflege-Sitzung des Templates selbst, kein fremdes Repo zum Nachrüsten.
Stattdessen: Änderungen direkt unter `../` vornehmen; `/act-apply-template` läuft nur in einem fremden
Ziel-Repo.
