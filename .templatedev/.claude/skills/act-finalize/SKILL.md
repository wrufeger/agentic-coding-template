---
name: act-finalize
description: Im Pflege-Projekt gesperrt – „Einrichtung abschließen" hat hier keine Wirkung.
metadata:
  phase: setup
disable-model-invocation: true
---

Im Pflege-Projekt gesperrt — hier nicht verfügbar.
Grund: `.templatedev/` hat keine Einrichtungsphase, die abgeschlossen werden könnte
(`.claude/template.json` trägt bereits `setup_complete: true`).
Stattdessen: nichts — dieser Schritt entfällt hier ganz.
