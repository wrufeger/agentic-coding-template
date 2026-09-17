---
name: act-create-project
description: Im Pflege-Projekt gesperrt – Checkliste „Neues Projekt" hat hier keine Wirkung.
metadata:
  phase: setup
disable-model-invocation: true
---

Im Pflege-Projekt gesperrt — hier nicht verfügbar.
Grund: `.templatedev/` ist bereits ein Projekt, keine Vorlage zum Anlegen eines neuen.
Stattdessen: Template-Dateien direkt unter `../` bearbeiten; ein neues Projekt entsteht per
`/act-create-project` in einer eigenen Sitzung außerhalb des Templates.
